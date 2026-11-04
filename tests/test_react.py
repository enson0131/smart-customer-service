import json
import tempfile
import unittest
from pathlib import Path
from fake_chat import TestChatModel, goal_and_tools

from chat_client import ChatTestClient as TestClient

from service.app import create_app
from service.storage.store import Store
from constants import VISITOR_COOKIE


class DeliveryModel:
    """模拟策略只读取本轮真实工具观察，不能预先决定走回执还是仓库。"""

    def __init__(self):
        self.decisions = []

    def invoke(self, messages):
        goal, tools = goal_and_tools(messages)
        observations = [json.loads(m.content) for m in tools]
        seen = [m.name for m in tools]
        if not seen:
            name = "track_shipment"
        elif "能退" in goal and "preview" not in seen:
            name = "preview"
        elif "为什么" in goal and len(seen) == 1:
            status = observations[0]["facts"]["state"]
            name = "check_delivery_receipt" if status == "已签收" else "check_fulfillment"
        else:
            name = "finish"
        self.decisions.append((goal, name))
        return "" if name == "finish" else [(name, {})]


class ReactTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "support.db"
        self.model = DeliveryModel()
        self.client = self.open()

    def open(self):
        client = TestClient(create_app(Store(self.path), lambda: TestChatModel(responder=lambda messages: self.model.invoke(messages))))
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        return client

    def send(self, message, select=False):
        body = {"message": message}
        if select:
            body["action"] = {"kind": "select_order", "order_id": message}
        response = self.client.post("/api/chat", json=body)
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_selection_uses_action_order_id(self):
        pending = self.send("查物流，再看看能不能退")
        selected = pending["orders"][0]["id"]
        response = self.client.post("/api/chat", json={
            "message": "选择云杉阅读灯订单",
            "action": {"kind": "select_order", "order_id": selected},
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["card"]["order_id"], selected)

        # 无中断时的按钮入口也以 action.order_id 为准，不请求模型识别。
        self.model.decisions.clear()
        response = self.client.post("/api/chat", json={
            "message": "查看选中的订单",
            "action": {"kind": "select_order", "order_id": selected},
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["orders"][0]["id"], selected)
        self.assertEqual(self.model.decisions, [])

    def test_resume_after_restart_and_finish_both_goals(self):
        goal = "帮我查物流，再看看能退吗"
        pending = self.send(goal)
        self.assertNotIn("card", pending)
        self.assertEqual(len(pending["orders"]), 3)
        stranger = self.open().get("/api/orders").json()[0]["id"]
        self.assertIn("未找到", self.send(stranger, True)["text"])

        old = self.client
        self.client = self.open()
        self.client.cookies.update(old.cookies)
        orders = self.send("查看我的订单")["orders"]
        selected = orders[0]["id"]
        result = self.send(selected, True)
        self.assertIn("模拟物流", result["text"])
        self.assertEqual(result["card"]["order_id"], selected)
        self.assertEqual(self.model.decisions, [(goal, "track_shipment"), (goal, "preview"), (goal, "finish")])
        db = Store(self.path)
        config = {"configurable": {"thread_id": self.client.chat_id}}
        self.assertFalse(self.client.app.state.conversation.graph.get_state(config).interrupts)
        self.assertFalse(db.sql("SELECT id FROM refunds"))

    def test_multiple_proposals_resume_batch_after_restart(self):
        observed = []
        def propose(messages):
            _, tools = goal_and_tools(messages)
            seen = [m.name for m in tools]
            observed.append(seen)
            if "preview" in seen:
                calls = [call for message in messages if hasattr(message, "tool_calls") for call in message.tool_calls]
                self.assertEqual([call["id"] for call in calls], [tool.tool_call_id for tool in tools])
                return "物流已签收，符合退款条件，请核对确认卡。"
            return [("track_shipment", {}), ("preview", {})]
        self.model.invoke = propose
        first = self.send("查物流，再看看能不能退")
        self.assertEqual(observed, [[]])
        self.assertFalse(Store(self.path).chat(self.client.cookies[VISITOR_COOKIE], self.client.chat_id)["ticket"])
        old = self.client
        self.client = self.open()
        self.client.cookies.update(old.cookies)
        result = self.send(first["orders"][0]["id"], True)
        self.assertEqual(observed, [[], ["track_shipment", "preview"]])
        self.assertEqual(result["text"], "物流已签收，符合退款条件，请核对确认卡。")
        self.assertEqual(result["card"]["order_id"], first["orders"][0]["id"])
        rows = [json.loads(line) for line in (self.path.parent / "logs/tasks.jsonl").read_text().splitlines()]
        self.assertEqual([row["tool"] for row in rows if row["event"] == "tool.result"],
                         ["track_shipment", "preview"])


    def test_cancel_selection_discards_remaining_batch(self):
        observed = []
        def propose(messages):
            _, tools = goal_and_tools(messages)
            observed.append([tool.name for tool in tools])
            return "已取消本次操作。" if tools else [("track_shipment", {}), ("preview", {})]
        self.model.invoke = propose
        self.send("查物流，再看看能不能退")
        response = self.client.post("/api/chat", json={
            "message": "取消", "action": {"kind": "cancel_pending"}})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("card", response.json())
        self.assertEqual(observed, [[], ["track_shipment"]])
        self.assertFalse(Store(self.path).chat(self.client.cookies[VISITOR_COOKIE], self.client.chat_id)["ticket"])

    def test_batch_preserves_same_tool_with_different_arguments(self):
        orders = self.client.get("/api/orders").json()
        observed = []
        def propose(messages):
            _, tools = goal_and_tools(messages)
            observed.append([tool.name for tool in tools])
            if tools:
                self.assertEqual([json.loads(tool.content)["facts"]["order_id"] for tool in tools],
                                 [order["id"] for order in orders[:2]])
                return "两笔订单已查询。"
            return [("orders", {"order_id": order["id"]}) for order in orders[:2]]
        self.model.invoke = propose
        self.assertEqual(self.send("帮我对比两笔订单")["text"], "两笔订单已查询。")
        self.assertEqual(observed, [[], ["orders", "orders"]])

    def test_task_log_follows_interrupt_across_requests(self):
        goal = "帮我查物流，再看看能退吗"
        response = self.client.post("/api/chat", json={"message": goal})
        self.assertNotIn("X-Task-ID", response.headers)
        order = response.json()["orders"][0]["id"]
        client = self.open()
        client.cookies.update(self.client.cookies)
        resumed = client.post("/api/chat", json={
            "message": order, "action": {"kind": "select_order", "order_id": order}})
        self.assertNotIn("X-Task-ID", resumed.headers)
        log = (self.path.parent / "logs/tasks.jsonl").read_text()
        rows = [json.loads(line) for line in log.splitlines()]
        task_id = rows[0]["task_id"]
        self.assertEqual({row["task_id"] for row in rows}, {task_id})
        self.assertNotIn(task_id, response.text)
        self.assertNotIn(task_id, resumed.text)
        events = [row["event"] for row in rows]
        for name in ("task.start", "node.start", "model.proposals", "tool.result", "node.interrupt",
                     "task.wait", "task.resume", "node.end", "task.end"):
            self.assertIn(name, events)
        self.assertLess(events.index("task.wait"), events.index("task.resume"))
        self.assertEqual(next(row["message"] for row in rows if row["event"] == "chat.request"), goal)
        self.assertEqual(next(row for row in reversed(rows) if row["event"] == "chat.response")["reply"]["card"]["ticket"],
                         "[REDACTED]")
        self.assertNotIn(client.cookies[VISITOR_COOKIE], log)
        self.assertNotIn(resumed.json()["card"]["ticket"], log)
        new = client.post("/api/chat", json={"message": "查看我的订单"})
        self.assertEqual(new.status_code, 200)
        last = (self.path.parent / "logs/tasks.jsonl").read_text().splitlines()[-1]
        self.assertNotEqual(task_id, json.loads(last)["task_id"])

    def test_native_interrupt_remains_at_act_until_valid_resume(self):
        pending = self.send("查物流")
        visitor = self.client.cookies[VISITOR_COOKIE]
        config = {"configurable": {"thread_id": self.client.chat_id}}
        graph = self.client.app.state.conversation.graph
        snapshot = graph.get_state(config)
        self.assertEqual(snapshot.next, ("agent",))
        self.assertNotIn("pause", graph.get_graph().nodes)
        interrupt_id = snapshot.interrupts[0].id
        self.assertEqual(snapshot.interrupts[0].value["reply"], pending)

        self.assertEqual(self.send("查看我的订单"), pending)
        self.assertIn("未找到", self.send("O-0000000000000000", True)["text"])
        self.assertEqual(graph.get_state(config).interrupts[0].id, interrupt_id)
        self.assertIn("模拟物流", self.send(pending["orders"][0]["id"], True)["text"])
        self.assertFalse(graph.get_state(config).interrupts)

    def test_retry_uses_saved_observation(self):
        order = self.client.get("/api/orders").json()[0]
        self.send(order["id"], True)
        invoke = self.model.invoke
        def fail_once(messages):
            _, tools = goal_and_tools(messages)
            if tools:
                self.model.invoke = invoke
                raise TimeoutError
            return invoke(messages)
        self.model.invoke = fail_once
        goal = "查物流，再看看能退吗"
        partial = self.send(goal)
        self.assertIn("模拟物流", partial["text"])
        self.assertIn("重试", partial["text"])
        self.assertIn("card", self.send("继续"))
        self.assertEqual([name for _, name in self.model.decisions], ["track_shipment", "preview", "finish"])

    def test_model_retry_after_batch_does_not_repeat_tools(self):
        observed = []
        def propose(messages):
            _, tools = goal_and_tools(messages)
            observed.append([tool.name for tool in tools])
            if not tools:
                return [("track_shipment", {}), ("preview", {})]
            if len(observed) == 2:
                raise TimeoutError
            return "物流与退款资格已核实，请核对确认卡。"
        self.model.invoke = propose
        pending = self.send("查物流，再看看能不能退")
        partial = self.send(pending["orders"][0]["id"], True)
        self.assertIn("重试", partial["text"])
        result = self.send("继续")
        self.assertIn("card", result)
        self.assertEqual(observed, [[], ["track_shipment", "preview"], ["track_shipment", "preview"]])
        rows = [json.loads(line) for line in (self.path.parent / "logs/tasks.jsonl").read_text().splitlines()]
        self.assertEqual([row["tool"] for row in rows if row["event"] == "tool.result"],
                         ["track_shipment", "preview"])

    def test_diagnosis_branches_on_actual_observation(self):
        orders = self.client.get("/api/orders").json()
        for order, expected in [(orders[0], "check_delivery_receipt"), (orders[-1], "check_fulfillment")]:
            self.send(order["id"], True)
            self.model.decisions.clear()
            answer = self.send("为什么我的包裹还没到？")
            self.assertIn("模拟", answer["text"])
            self.assertEqual([name for _, name in self.model.decisions], ["track_shipment", expected, "finish"])
