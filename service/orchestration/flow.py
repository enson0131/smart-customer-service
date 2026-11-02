import json
import re
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from ..intent import recognition
from ..domain.aftercare import preview_refund, refund_progress
from ..domain.tools import TOOLS
from ..model.deepseek import SupportModel


class State(TypedDict, total=False):
    session: dict
    message: str
    route: str
    order_id: str
    reason: str
    query: str
    question: str
    choose_order: bool
    result: dict


def reply(text, **extra):
    return {"result": {"text": text, "sources": [], **extra}}


def build_flow(store, knowledge, model):
    assistant = SupportModel(model, TOOLS.values()) if model is not None else None

    def route(s):
        session, message = s["session"], s["message"]
        if assistant is None or recognition.explicit_action(message):
            return recognition.fallback(s)
        history = store.recent_turns(session["id"])
        try:
            return recognition.recognize(assistant, session, message, history)
        except Exception:
            return recognition.fallback(s)

    def orders(s):
        session = s["session"]
        rows = store.orders(session["id"])
        if s["order_id"]:
            rows = [o for o in rows if o["id"] == s["order_id"]]
            if not rows:
                return reply("未找到这笔订单。")
            store.context(session["id"], "orders", rows[0]["id"])
            return reply("已选中这笔订单，可继续问「这单能退吗」。", orders=rows)
        store.context(session["id"], "orders")
        return reply("请选择要查看的订单。", orders=rows)

    def preview(s):
        session = s["session"]
        visitor = session["id"]
        selected = None if s.get("choose_order") else s["order_id"] or session["selected"]
        if not selected:
            store.context(visitor, "choose_refund", reason=s["reason"])
            return reply("请先选一笔要办理退款的订单。", orders=store.orders(visitor))
        result = preview_refund(store, visitor, selected, s["reason"])
        if "card" in result:
            card = result["card"]
            store.context(visitor, "preview", selected, card["ticket"], card["reason"])
            return reply(result["text"], card=card)
        if result.get("ineligible"):
            store.context(visitor, "orders", selected)
        return reply(result["text"])

    def progress(s):
        visitor = s["session"]["id"]
        ref = re.search(r"R-[a-f0-9]{16}", s["message"], re.I)
        reference = "R-" + ref[0][2:].lower() if ref else None
        text = refund_progress(store, visitor, reference)
        store.context(visitor, "progress", s["session"]["selected"])
        return reply(text)

    def cancel(s):
        session = s["session"]
        store.context(session["id"], "orders", session["selected"])
        return reply("已关闭待确认操作。")

    def policy(s):
        session, msg = s["session"], s["message"]
        msg = s.get("query") or msg
        sources = knowledge.search(msg)
        store.context(session["id"], "policy", session["selected"])
        if not sources:
            return reply(f"演示知识库缺少关于「{msg}」的依据，请向人工客服核实。", mode="检索模式")
        if assistant:
            try:
                answer = assistant.answer_policy(msg, sources)
                if isinstance(answer, str) and answer.strip():
                    return reply(answer, sources=sources, mode="DeepSeek")
            except Exception:
                pass
        return reply("找到以下相关政策原文，供你核对。", sources=sources, mode="检索模式")

    def remember(s):
        result = s["result"]
        # Keep order choices for references such as “第二个”. Never send a confirmation ticket to the model.
        summary = {k: result[k] for k in ("text", "orders") if k in result}
        if "card" in result:
            summary["预览订单"] = result["card"]["order_id"]
        store.record_turn(s["session"]["id"], s["message"], json.dumps(summary, ensure_ascii=False))
        return {}

    graph = StateGraph(State)
    graph.add_node("remember", remember)
    graph.add_edge("remember", END)
    graph.add_node("route", route)
    handlers = {"orders": orders, "preview": preview, "progress": progress, "policy": policy, "cancel": cancel,
                "clarify": lambda s: reply(s["question"])}
    graph.add_edge(START, "route")
    for name, handler in handlers.items():
        graph.add_node(name, handler)
        graph.add_edge(name, "remember")
    graph.add_conditional_edges("route", lambda state: state["route"], list(handlers))
    return graph.compile()
