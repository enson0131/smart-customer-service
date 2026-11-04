"""入口图只决定去向；自由输入的模型 → 工具 → 模型循环由 create_agent 管理。"""

import json
from typing import TypedDict

from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware, after_model, before_model, wrap_model_call
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.graph import START, END, StateGraph
from langgraph.types import interrupt

from constants import MAX_REACT_STEPS
from ..domain.outcomes import Outcome
from ..intent.rules import match_single_intent
from ..task_log import event
from .agent_tools import SupportTools
from .presentation import present


class State(TypedDict, total=False):
    task_id: str
    chat: dict
    message: str
    action: dict | None
    step: dict
    messages: list
    result: dict


SYSTEM_PROMPT = """你是智能售后客服。按用户要求处理所有事项，使用工具核实业务事实。
只办理用户明确提出的事项。查到物流且已取得退款预览后，直接回复，勿追加运费或政策查询。
参数已知或只需复用选单的多项工具调用，优先在同一批提出，系统按返回顺序执行。
依赖前一步查询结果才能确定参数的调用应等待结果后再提出。
缺少订单号可直接调用物流或退款预览工具，
系统会请用户选单。同一订单的批次调用应省略 order_id，preview 的 choose_order 保持 false，自动复用选单结果。
仅使用当前访客明确指定或选中的订单；禁止猜测编号。
查物流且询问能否退必须分别获得物流和退款资格。实际运费查 shipping_cost，运费承担查 policy。
配送异常按需要查履约或签收回执。取消仅限当前待确认操作。缺少其他信息用 clarify。
核实后根据全部工具事实统一用中文回复，无需调用结束工具。金额、资格和状态必须忠实于工具结果。
退款只能预览，提交必须由用户点击确认。needs_confirmation 表示确认卡已随本次回复展示，请提示点击下方确认卡，无需再口头确认。
用户取消或改变诉求后，不要继续原来的操作。
"""


def dispatch_tool_batch(reply, calls):
    """一次只交给原生 ToolNode 一个调用，其余随 AIMessage 持久化。"""
    event("tools.dispatch", tool=calls[0]["name"], remaining=[call["name"] for call in calls[1:]])
    return reply.model_copy(update={
        "tool_calls": calls[:1], # 执行第一个
        "additional_kwargs": {"pending_tool_calls": calls[1:]}, # 后续的工具先 padding
    })


@before_model(can_jump_to=["tools"])
def continue_tool_batch(state, runtime):
    """调用模型前，优先执行尚未完成的批次；原生跳转避免多余的模型请求。"""
    messages = state["messages"]
    last_reply = next((message for message in reversed(messages)
                       if isinstance(message, AIMessage)), None)
    pending = last_reply.additional_kwargs.get("pending_tool_calls", []) if last_reply else []
    if not pending:
        return None

    last_result = messages[-1]
    status = (last_result.artifact or {}).get("status")
    # 取消、改问或工具失败后，放弃旧批次，让模型重新理解当前需求。
    if last_result.status == "error" or status in {"cancelled", "user_input", "order_missing"}:
        return None

    next_reply = dispatch_tool_batch(AIMessage(content=""), pending)
    return {"messages": [next_reply], "jump_to": "tools"}


@after_model
def prepare_tool_batch(state, runtime):
    """模型返回后保存新批次，只放行首项；同 ID 更新原消息，不追加重复回复。"""
    reply = state["messages"][-1]
    calls = reply.tool_calls
    event("model.proposals", tools=[call["name"] for call in calls])
    if calls:
        return {"messages": [dispatch_tool_batch(reply, calls)]}
    return None


@wrap_model_call
def handle_model_error(request, handler):
    """只处理模型调用异常：已有结果时保留进度，等待用户重试。"""
    try:
        return handler(request)
    except Exception as error:
        event("decision.error", error_type=type(error).__name__)
        observations = [message for message in request.messages if isinstance(message, ToolMessage)]
        if observations:
            completed = [m for m in observations if m.artifact]
            partial = present([{"name": m.name} for m in completed], [Outcome(**m.artifact) for m in completed])
            partial["text"] += "\n暂时无法继续核实其余事项，请稍后重试。"
            interrupt({"reply": partial, "choices": [], "status": "retry"})
            return AIMessage(content=partial["text"])
        return AIMessage(content="暂时无法识别这次请求，请稍后重试。")


def history_summary(answer_json):
    """网页保存完整回复；给模型的历史仅保留事实，不包含确认票据。"""
    answer = json.loads(answer_json)
    summary = {"text": answer["text"]}
    if "orders" in answer:
        summary["orders"] = answer["orders"]
    if "card" in answer:
        summary["预览订单"] = answer["card"]["order_id"]
    return json.dumps(summary, ensure_ascii=False)


def build_flow(store, knowledge, model, checkpointer=None):
    tools = SupportTools(store, knowledge)
    agent = create_agent(model, tools.registered(), system_prompt=SYSTEM_PROMPT,
                         middleware=[continue_tool_batch,
                                     ModelCallLimitMiddleware(run_limit=MAX_REACT_STEPS + 1),
                                     prepare_tool_batch, handle_model_error])

    # 意图
    def intent(state):
        chat = state["chat"]
        matched = match_single_intent(state["message"], chat, state.get("action"))
        event("intent.route", source="rule" if matched else "model")
        if matched:
            return {"step": matched}
        history = store.recent_turns(chat["id"])
        messages = []
        for turn in history:
            messages.extend([HumanMessage(content=turn["message"]), AIMessage(content=history_summary(turn["answer"]))])
        if chat["selected"]:
            messages.append(AIMessage(content="当前会话选中订单：" + chat["selected"]))
        messages.append(HumanMessage(content=state["message"]))
        return {"messages": messages, "step": {}}

    def route(state):
        return "direct" if state["step"] else "agent"

    def direct(state):
        step = state["step"]
        if step["name"] in {"policy", "progress"}:
            chat = state["chat"]
            store.context(chat["id"], step["name"], chat["selected"])
        outcome = tools.execute(step["name"], step["args"], state["chat"]["visitor_id"], state["chat"]["id"])
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
            active = store.chat(state["chat"]["visitor_id"], state["chat"]["id"])["ticket"]
            outcomes = [Outcome("preview_closed") if o.artifacts.get("card", {}).get("ticket", active) != active
                        else o for o in outcomes]
        result = present(steps, outcomes)
        final = messages[-1]
        if (isinstance(final, AIMessage) and isinstance(final.content, str) and final.content.strip()):
            result["text"] = final.content
        return {"result": result}

    def remember(state):
        store.record_turn(state["chat"]["id"], state["message"], state["result"])
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
