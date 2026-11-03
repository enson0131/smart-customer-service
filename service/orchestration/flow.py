import json
import logging
from typing import TypedDict

from langgraph.types import interrupt
from langgraph.graph import END, START, StateGraph

from constants import MAX_REACT_STEPS
from ..domain.delivery import delivery_record
from ..intent import recognition
from ..intent.rules import match_single_intent
from ..domain.aftercare import preview_refund, refund_progress, shipping_cost
from ..domain.outcomes import Outcome
from .presentation import present
from ..domain.tools import TOOLS
from ..model.deepseek import SupportModel



class State(TypedDict, total=False):
    """goal 保留原请求；steps 和 results 只记录已经执行的动作及其观察。"""

    session: dict
    message: str
    action: dict | None
    goal: str
    supplement: str
    steps: list[dict]
    results: list[Outcome]
    step: dict
    direct: bool
    destination: str
    result: dict


def build_flow(store, knowledge, model, checkpointer=None):
    assistant = SupportModel(model, TOOLS.values()) if model is not None else None

    def enter(state):
        session = state["session"]
        action = state.get("action")
        message = state["message"]
        matched = match_single_intent(message, session, action)
        # 兼容升级前尚未完成的旧任务；新任务由图的 checkpointer 保存。
        pending = store.pending_task(session["id"])
        update = {"goal": message, "supplement": "", "steps": [], "results": [],
                  "direct": matched is not None, "step": matched or {},
                  "destination": "act" if matched else "reason"}
        if pending and matched and action and action["kind"] == "select_order":
            order_id = action["order_id"]
            if order_id not in pending["choices"] or not any(
                row["id"] == order_id for row in store.orders(session["id"])
            ):
                return {**update, "destination": "summarize", "steps": [{"name": "orders"}],
                        "results": [Outcome("order_missing")]}
            store.context(session["id"], "orders", order_id)
            update["supplement"] = "已选订单 " + order_id
            blocked = pending["blocked"]
            if blocked:
                blocked["args"]["order_id"] = order_id
                if blocked["name"] == "preview":
                    blocked["args"]["choose_order"] = False
                update["step"] = blocked
            else:
                update["destination"] = "reason"
        elif pending and matched and matched["name"] == "orders" and not action and pending["choices"]:
            # 刷新页面后再次打开订单列表，保留原任务，供用户重新点选。
            rows = [row for row in store.orders(session["id"]) if row["id"] in pending["choices"]]
            return {**update, "steps": [{"name": "orders"}],
                    "results": [Outcome("order_list", {"count": len(rows)}, {"orders": rows})],
                    "destination": "summarize"}
        elif pending and not matched:
            update.update(supplement=message, destination="reason")
        else:
            if pending and matched and matched["name"] != "cancel":
                store.clear_task(session["id"])
            return update
        restored = [Outcome(**item) for item in pending["results"]]
        if matched and action and action["kind"] == "select_order":
            # 用户已经选好订单，历史工具输出里的候选列表不应再次提示用户选单。
            for index, item in enumerate(restored):
                if item.status == "order_list":
                    chosen = next((row for row in item.artifacts["orders"] if row["id"] == order_id), None)
                    if chosen:
                        restored[index] = Outcome("order_found", {"order_id": order_id, "product": chosen["product"]},
                                                  {"orders": [chosen]})
        store.clear_task(session["id"])
        update.update(goal=pending["goal"], direct=False, steps=pending["steps"], results=restored)
        return update

    def reason(state):
        observations = [{"tool": step["name"], "args": step["args"], "status": item.status,
                         "facts": item.facts} for step, item in zip(state["steps"], state["results"])]
        visitor = state["session"]["id"]
        try:
            step = recognition.next_action(assistant, store.session(visitor), state["goal"],
                                           store.recent_turns(visitor), observations, state["supplement"])
            if step["name"] == "finish" and observations:
                store.clear_task(visitor)
                return {"destination": "summarize"}
            if step["name"] == "finish" or step in state["steps"] or len(observations) >= MAX_REACT_STEPS:
                raise ValueError("没有新的可执行步骤")
        except Exception as error:
            logging.getLogger(__name__).warning("ReAct decision failed: %s (observations=%d)",
                                                type(error).__name__, len(observations))
            if observations and len(observations) < MAX_REACT_STEPS:
                return {"step": {"name": "clarify", "args": {"question": "暂时无法继续核实其余事项，请稍后重试。"}},
                        "destination": "act"}
            # 区分首步失败与已有部分结果，避免暗示尚未执行的查询已经完成。
            message = "暂时无法识别这次请求，请稍后重试。" if not observations else "暂时无法继续核实其余事项，请稍后重试。"
            return {"destination": "summarize", "steps": state["steps"] + [{"name": "clarify"}],
                    "results": state["results"] + [Outcome("clarify", {"question": message})]}
        return {"step": step, "destination": "act"}

    def orders(s):
        """查询当前访客的订单。传订单号时选中该单，未传时返回供页面展示的订单列表。"""
        session = s["session"]
        rows = store.orders(session["id"])
        if s["order_id"]:
            rows = [o for o in rows if o["id"] == s["order_id"]]
            if not rows:
                return Outcome("order_missing")
            # 记住选中的订单，后续提到“这单”时可以沿用。
            store.context(session["id"], "orders", rows[0]["id"])
            return Outcome("order_found", {"product": rows[0]["product"], "order_id": rows[0]["id"]}, {"orders": rows})
        store.context(session["id"], "orders")
        return Outcome("order_list", {"orders": [{"id": r["id"], "product": r["product"]} for r in rows]}, {"orders": rows})

    def preview(s):
        """准备整单退款预览。订单不明确时先让用户选单，符合条件时生成待确认卡片。"""
        session = s["session"]
        visitor = session["id"]
        # 需要重新选单时忽略旧选择，否则优先用本步骤指定的订单，再用会话中选中的订单。
        selected = None if s.get("choose_order") else s["order_id"] or session["selected"]
        if not selected:
            return Outcome("choose_refund", artifacts={"orders": store.orders(visitor)})
        # 本节点只生成预览；真正提交由确认接口复核票据后完成。
        result = preview_refund(store, visitor, selected, s["reason"])
        if result.status == "needs_confirmation":
            # 保存与页面确认卡对应的票据，供用户点击确认时校验。
            card = result.artifacts["card"]
            store.context(visitor, "preview", selected, card["ticket"], card["reason"])
        elif result.status in {"outside_window", "not_delivered"}:
            store.context(visitor, "orders", selected)
        return result

    def progress(s):
        """查询当前访客的退款进度。有申请编号时查指定申请，否则列出该访客的申请。"""
        visitor = s["session"]["id"]
        result = refund_progress(store, visitor, s.get("reference"))
        # results 为空表示这是本轮第一步；若前面已生成确认卡，就保留那一步的会话状态。
        if not s["results"]:
            store.context(visitor, "progress", s["session"]["selected"])
        return result

    def cancel(s):
        """关闭当前访客尚在选单或待确认的退款操作；订单和已提交的退款申请保持原状。"""
        session = s["session"]
        abandoned = store.clear_task(session["id"])
        if store.cancel_pending(session["id"]) or abandoned:
            return Outcome("cancelled")
        return Outcome("nothing_pending")

    def policy(s):
        """按问题检索售后知识库，把检索词和命中原文交给汇总节点，用于答复和引用。"""
        session = s["session"]
        if not s["results"]:
            store.context(session["id"], "policy", session["selected"])
        # 多意图请求优先用拆出的政策问题，避免将查单等无关内容带入检索。
        query = s.get("query") or s["message"]
        sources = knowledge.search(query)
        return Outcome("policy_found" if sources else "policy_missing", {"query": query, "sources": sources})

    def clarify(s):
        """返回需要用户补充的问题。执行节点遇到 clarify 会停止本轮剩余步骤并进入汇总。"""
        return Outcome("clarify", {"question": s["question"]})

    # {
    # "result": {
    #     "text": "请选择要查看的订单。",
    #     "sources": [],
    #     "orders": [
    #         {"id": "O-001", "product": "阅读灯"},
    #         {"id": "O-002", "product": "随行杯"},
    #         {"id": "O-003", "product": "收纳包"},
    #     ],
    #     }
    # }
    def remember(state):
        """保存本轮用户消息和客服回复摘要，供后续对话识别指代。"""
        assistant_reply = state["result"]
        reply_summary = {}

        if "text" in assistant_reply:
            reply_summary["text"] = assistant_reply["text"]
        if "orders" in assistant_reply:
            # 保留展示顺序，下一轮才能理解“第二个订单”。
            reply_summary["orders"] = assistant_reply["orders"]
        if "card" in assistant_reply:
            # 只记录预览的订单号，避免将退款确认票据写入模型上下文。
            reply_summary["预览订单"] = assistant_reply["card"]["order_id"]

        visitor_id = state["session"]["id"]
        user_message = state["message"]
        reply_summary_json = json.dumps(reply_summary, ensure_ascii=False) # 将 json 转化成字符串
        # | 参数 | 数据库字段 | 举例 |
        # |---|---|---|
        # | `visitor_id` | `visitor` | 这条记录属于哪个访客 |
        # | `user_message` | `message` | `这单能退吗？` |
        # | `reply_summary_json` | `answer` | `{"text":"订单符合退款条件。请核对后点击确认提交。","预览订单":"O-002"}` |
        store.record_turn(visitor_id, user_message, reply_summary_json)

        # 对话已写入数据库，返回空字典表示无需更新 LangGraph 状态。
        return {}

    def shipment_tool(s):
        session = s["session"]
        rows = store.orders(session["id"])
        selected = s["order_id"] or session["selected"]
        if not selected and len(rows) == 1:
            selected = rows[0]["id"]
        if not selected and rows:
            return Outcome("choose_delivery", artifacts={"orders": rows})
        order = next((row for row in rows if row["id"] == selected), None)
        if not order:
            return Outcome("order_missing")
        if session["selected"] != selected:
            store.context(session["id"], "orders", selected)
        return delivery_record(order, s["tool"])

    handlers = {
        "orders": orders, "preview": preview, "progress": progress, "policy": policy,
        "shipping_cost": lambda _: shipping_cost(), "cancel": cancel, "clarify": clarify,
        "track_shipment": shipment_tool, "check_fulfillment": shipment_tool,
        "check_delivery_receipt": shipment_tool,
    }

    def act(state):
        step = state["step"]
        session = store.session(state["session"]["id"])
        args = dict(step["args"])
        args.setdefault("order_id", "")
        args["reason"] = args.get("reason") or session["reason"] or "客户申请整单退款"
        outcome = handlers[step["name"]]({**args, "tool": step["name"], "session": session,
                                          "message": state["goal"], "results": state["results"]})
        destination = "summarize" if state["direct"] or step["name"] == "cancel" else "reason"
        steps = state["steps"] + [step]
        results = state["results"] + [outcome]
        if outcome.status in {"clarify", "choose_refund", "choose_delivery"}:
            # interrupt 恢复时会从 act 开头重跑。等待输入的三个分支在此之前只读。
            question = present(state["goal"], steps, results, None)
            eligible = outcome.artifacts.get("orders", question.get("orders", []))
            response = interrupt({"reply": question, "status": outcome.status, "reason": args["reason"], "choices": [row["id"] for row in eligible]})
            action = response.get("action") or {}
            message = response["message"]
            matched = match_single_intent(message, session, action or None)
            if matched and action.get("kind") == "select_order":
                selected = action["order_id"]
                store.context(session["id"], "orders", selected)
                # 选单完成后把候选列表替换为选中的单据。
                restored = []
                for item in state["results"]:
                    chosen = next((row for row in item.artifacts.get("orders", []) if row["id"] == selected), None)
                    if item.status == "order_list" and chosen:
                        item = Outcome("order_found", {"order_id": selected, "product": chosen["product"]},
                                       {"orders": [chosen]})
                    restored.append(item)
                update = {"results": restored, "message": message, "supplement": "已选订单 " + selected,
                          "direct": False, "destination": "reason"}
                if outcome.status != "clarify":
                    args = {**step["args"], "order_id": selected}
                    if step["name"] == "preview":
                        args["choose_order"] = False
                    update.update(step={"name": step["name"], "args": args}, destination="act")
                return update
            if matched and matched["name"] == "cancel":
                store.cancel_pending(session["id"])
                return {"steps": [matched], "results": [Outcome("cancelled")],
                        "message": message, "destination": "summarize"}
            if matched:
                return {"step": matched, "steps": [], "results": [], "goal": message, "message": message,
                        "direct": True, "destination": "act"}
            return {"supplement": message, "message": message, "direct": False, "destination": "reason"}
        if outcome.status == "order_missing":
            destination = "summarize"
        return {"steps": steps, "results": results, "destination": destination}

    def summarize(state):
        outcomes = list(state["results"])
        if any("card" in item.artifacts for item in outcomes):
            active_ticket = store.session(state["session"]["id"])["ticket"]
            for index, item in enumerate(outcomes):
                card = item.artifacts.get("card")
                if card and card["ticket"] != active_ticket:
                    outcomes[index] = Outcome("preview_closed")
        return {"result": present(state["goal"], state["steps"], outcomes, assistant)}

    def next_node(state: State) -> str:
        """读取当前节点写入的 destination，供条件边选择下一节点。"""
        return state["destination"]

    graph = StateGraph(State)
    for node in (enter, reason, act, summarize, remember):
        graph.add_node(node)
    graph.add_edge(START, "enter")
    for node, targets in (("enter", ["reason", "act", "summarize"]),
                          ("reason", ["act", "summarize"]),
                          ("act", ["reason", "act", "summarize"])):
        graph.add_conditional_edges(node, next_node, targets)
    graph.add_edge("summarize", "remember")
    graph.add_edge("remember", END)
    return graph.compile(checkpointer=checkpointer)
