"""同一组售后能力供规则入口和 LangChain 工具节点调用。"""

import json
from dataclasses import asdict

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import StructuredTool
from langgraph.types import interrupt

from ..domain.aftercare import preview_refund, refund_progress, shipping_cost
from ..domain.delivery import delivery_record
from ..domain.outcomes import Outcome
from ..domain.tools import TOOLS
from ..task_log import event
from .presentation import template


class SupportTools:
    def __init__(self, store, knowledge):
        self.store = store
        self.knowledge = knowledge

    def execute(self, name, args, visitor_id, chat_id):
        chat = self.store.chat(visitor_id, chat_id)
        event("tool.request", tool=name, params=args, selected_order=chat["selected"])
        result = self.run(name, args, chat)
        event("tool.result", tool=name, status=result.status, facts=result.facts, artifacts=result.artifacts)
        return result

    def ask(self, question, choices=(), status="clarify", reason=""):
        reply = {"text": question, "sources": []}
        if choices:
            reply["orders"] = choices
        return interrupt({"reply": reply, "status": status, "reason": reason,
                          "choices": [o["id"] for o in choices]})

    def run(self, name, args, chat):
        visitor = chat["visitor_id"]
        chat_id = chat["id"]
        if name == "cancel":
            closed = self.store.cancel_pending(chat_id)
            return Outcome("cancelled" if closed else "nothing_pending")
        if name == "shipping_cost":
            return shipping_cost()
        if name == "progress":
            return refund_progress(self.store, visitor, args.get("reference"))
        if name == "policy":
            query = args["query"]
            sources = self.knowledge.search(query)
            return Outcome("policy_found" if sources else "policy_missing", {"query": query, "sources": sources})
        if name == "clarify":
            choices = self.store.orders(visitor) if args.get("choose_order") else []
            response = self.ask(args["question"], choices)
            action = response.get("action") or {}
            if action.get("kind") == "select_order":
                self.store.context(chat_id, "orders", action["order_id"])
            return Outcome("user_input", {"message": response["message"]})

        rows = self.store.orders(visitor)
        selected = None if args.get("choose_order") else args.get("order_id")
        if name == "orders" and not selected:
            self.store.context(chat_id, "orders")
            return Outcome("order_list", {"orders": [{"id": o["id"], "product": o["product"]} for o in rows]},
                           {"orders": rows})
        if not args.get("choose_order"):
            selected = selected or chat["selected"]
        reason = args.get("reason") or chat["reason"] or "客户申请整单退款"
        if not selected and len(rows) == 1:
            selected = rows[0]["id"]
        if not selected and rows:
            status = "choose_refund" if name == "preview" else "choose_delivery"
            response = self.ask(template(Outcome(status)), rows, status, reason)
            action = response.get("action") or {}
            if action.get("kind") == "cancel_pending":
                self.store.cancel_pending(chat_id)
                return Outcome("cancelled")
            if action.get("kind") != "select_order":
                return Outcome("user_input", {"message": response["message"]})
            selected = action["order_id"]
        order = next((row for row in rows if row["id"] == selected), None)
        if not order:
            return Outcome("order_missing")
        if name == "preview":
            result = preview_refund(self.store, visitor, selected, reason)
            if result.status == "needs_confirmation":
                self.store.context(chat_id, "preview", selected, result.artifacts["card"]["ticket"], reason)
            elif result.status in {"outside_window", "not_delivered"}:
                self.store.context(chat_id, "orders", selected)
            return result
        if name == "orders" or chat["selected"] != selected:
            self.store.context(chat_id, "orders", selected)
        if name == "orders":
            return Outcome("order_found", {"order_id": selected, "product": order["product"]}, {"orders": [order]})
        return delivery_record(order, name)

    def as_tool(self, name, schema):
        def call(config: RunnableConfig, **args):
            settings = config["configurable"]
            outcome = self.execute(name, args, settings["visitor_id"], settings["thread_id"])
            # content 可见于模型；卡片、票据只经 artifact 返回页面。
            content = {"status": outcome.status, "facts": outcome.facts}
            return json.dumps(content, ensure_ascii=False), asdict(outcome)

        return StructuredTool.from_function(call, name=name, description=schema.__doc__, args_schema=schema,
                                           response_format="content_and_artifact", return_direct=name == "cancel")

    def registered(self):
        return [self.as_tool(name, schema) for name, schema in TOOLS.items()]
