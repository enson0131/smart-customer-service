"""将 HTTP 对话请求转换为新图调用或对应访客的原生 resume 命令。"""

import json
from threading import Lock

from langgraph.types import Command


class Conversation:
    def __init__(self, graph, store, saver):
        self.graph = graph
        self.store = store
        self.saver = saver
        self.locks = [Lock() for _ in range(64)]

    def respond(self, session, message, action):
        visitor = session["id"]
        config = {"configurable": {"thread_id": visitor}}
        # 同一进程中，同一访客的两个 HTTP 请求不能同时消费同一个 interrupt。
        with self.locks[hash(visitor) % len(self.locks)]:
            pending = self.graph.get_state(config).interrupts
            if pending:
                waiting = pending[0]
                choices = waiting.value["choices"]
                if choices and message == "查看我的订单" and action is None:
                    return waiting.value["reply"]
                if action and action["kind"] == "select_order":
                    selected = action["order_id"]
                    if selected != message or selected not in choices or not any(
                        row["id"] == selected for row in self.store.orders(visitor)
                    ):
                        return {"text": "未找到这笔订单。", "sources": []}
                graph_input = Command(resume={waiting.id: {"message": message, "action": action}})
            else:
                graph_input = {"session": session, "message": message, "action": action}

            result = self.graph.invoke(graph_input, config, durability="sync")
            if waiting := result.get("__interrupt__"):
                prompt = waiting[0].value
                if prompt["status"] == "choose_refund":
                    # 只在首次向页面发出中断时作废旧票据，不在重放的节点内写入。
                    self.store.context(visitor, "choose_refund", reason=prompt["reason"])
                reply = prompt["reply"]
                summary = {key: reply[key] for key in ("text", "orders") if key in reply}
                self.store.record_turn(visitor, message, json.dumps(summary, ensure_ascii=False))
                return reply
            self.saver.delete_thread(visitor)
            return result["result"]
