"""入口图只决定去向；自由输入的模型 → 工具 → 模型循环由 create_agent 管理。"""

import json
from typing import TypedDict

from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware, wrap_model_call
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.graph import START, END, StateGraph
from langgraph.types import interrupt

from constants import MAX_REACT_STEPS
from ..domain.outcomes import Outcome
from ..domain.tools import TOOLS
from ..intent.rules import match_single_intent
from ..task_log import event
from .agent_tools import SupportTools
from .presentation import present


class State(TypedDict, total=False):
    task_id: str
    session: dict
    message: str
    action: dict | None
    step: dict
    messages: list
    result: dict


SYSTEM_PROMPT = """你是云杉售后客服。按用户要求处理所有事项，使用工具核实业务事实。
只办理用户明确提出的事项。查到物流且已取得退款预览后，直接回复，勿追加运费或政策查询。
每次选择一个工具，读到工具消息后再决定下一步。缺少订单号可直接调用物流或退款预览工具，
系统会请用户选单。仅使用当前访客明确指定或选中的订单；禁止猜测编号。
查物流且询问能否退必须分别获得物流和退款资格。实际运费查 shipping_cost，运费承担查 policy。
配送异常按需要查履约或签收回执。取消仅限当前待确认操作。缺少其他信息用 clarify。
核实后直接用中文回复，无需调用结束工具。退款只能预览，提交必须由用户点击确认。
"""


@wrap_model_call
def sequential_tools(request, handler):
    """某些模型会同时提出多项调用；涉及选单和确认卡的工具必须逐个执行。"""
    observations = [m for m in request.messages if isinstance(m, ToolMessage)]
    try:
        response = handler(request)
        reply = response.result[-1]
        calls = reply.tool_calls
        event("model.proposals", tools=[call["name"] for call in calls])
        for call in calls:
            TOOLS[call["name"]].model_validate(call["args"])
        if len(calls) > 1:
            # 支持同名工具查询不同订单或政策；只跳过本轮已执行过的相同参数。
            completed_ids = {m.tool_call_id for m in observations}
            completed = [(c["name"], c["args"]) for m in request.messages if isinstance(m, AIMessage)
                         for c in m.tool_calls if c["id"] in completed_ids]
            if any(c["name"] in {"cancel", "clarify"} for c in calls):
                choice = {**calls[0], "name": "clarify", "args": {"question": "请告诉我想先办理哪一项操作。"}}
            else:
                choice = next((c for c in calls if (c["name"], c["args"]) not in completed), None)
            if choice is None:
                return AIMessage(content="")  # 已有工具事实由呈现层统一回复。
            reply = reply.model_copy(update={"tool_calls": [choice]})
            response.result[-1] = reply
        return response
    except Exception as error:
        event("decision.error", error_type=type(error).__name__)
        if observations:
            completed = [m for m in observations if m.artifact]
            partial = present([{"name": m.name} for m in completed], [Outcome(**m.artifact) for m in completed])
            partial["text"] += "\n暂时无法继续核实其余事项，请稍后重试。"
            interrupt({"reply": partial, "choices": [], "status": "retry"})
            return AIMessage(content=partial["text"])
        return AIMessage(content="暂时无法识别这次请求，请稍后重试。")


def build_flow(store, knowledge, model, checkpointer=None):
    tools = SupportTools(store, knowledge)
    agent = create_agent(model, tools.registered(), system_prompt=SYSTEM_PROMPT,
                         middleware=[ModelCallLimitMiddleware(run_limit=MAX_REACT_STEPS + 1), sequential_tools])

    def intent(state):
        session = state["session"]
        matched = match_single_intent(state["message"], session, state.get("action"))
        event("intent.route", source="rule" if matched else "model")
        if matched:
            return {"step": matched}
        history = store.recent_turns(session["id"])
        messages = []
        for turn in history:
            messages.extend([HumanMessage(content=turn["message"]), AIMessage(content=turn["answer"])])
        if session["selected"]:
            messages.append(AIMessage(content="当前会话选中订单：" + session["selected"]))
        messages.append(HumanMessage(content=state["message"]))
        return {"messages": messages, "step": {}}

    def route(state):
        return "direct" if state["step"] else "agent"

    def direct(state):
        step = state["step"]
        if step["name"] in {"policy", "progress"}:
            session = state["session"]
            store.context(session["id"], step["name"], session["selected"])
        outcome = tools.execute(step["name"], step["args"], state["session"]["id"])
        result = present([step], [outcome])
        if outcome.status == "policy_found":
            try:
                answer = model.invoke([("system", "仅根据提供的售后政策回答。"),
                                       ("human", json.dumps(outcome.facts, ensure_ascii=False))]).content
                if isinstance(answer, str) and answer.strip():
                    result.update(text=answer, mode="DeepSeek")
            except Exception:
                pass
        return {"result": result}

    def respond(state):
        # 历史对话只包含文本；本次执行的工具消息携带可渲染的结构化结果。
        messages = state["messages"]
        records = [m for m in messages if isinstance(m, ToolMessage) and m.artifact]
        steps = [{"name": m.name} for m in records]
        outcomes = [Outcome(**m.artifact) for m in records]
        if any("card" in o.artifacts for o in outcomes):
            active = store.session(state["session"]["id"])["ticket"]
            outcomes = [Outcome("preview_closed") if o.artifacts.get("card", {}).get("ticket", active) != active
                        else o for o in outcomes]
        result = present(steps, outcomes)
        final = messages[-1]
        if (isinstance(final, AIMessage) and isinstance(final.content, str) and final.content.strip()
                and all(m.name not in {"preview", "cancel", "progress"} for m in records)):
            result["text"] = final.content
        return {"result": result}

    def remember(state):
        reply = state["result"]
        summary = {"text": reply["text"]}
        if "orders" in reply:
            summary["orders"] = reply["orders"]
        if "card" in reply:
            summary["预览订单"] = reply["card"]["order_id"]
        store.record_turn(state["session"]["id"], state["message"], json.dumps(summary, ensure_ascii=False))
        return {}

    graph = StateGraph(State)
    graph.add_node("intent", intent)
    graph.add_node("direct", direct)
    graph.add_node("agent", agent)
    graph.add_node("respond", respond)
    graph.add_node("remember", remember)
    graph.add_edge(START, "intent")
    graph.add_conditional_edges("intent", route, ["direct", "agent"])
    graph.add_edge("direct", "remember")
    graph.add_edge("agent", "respond")
    graph.add_edge("respond", "remember")
    graph.add_edge("remember", END)
    return graph.compile(checkpointer=checkpointer)
