import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from service.app import create_app
from service.storage.store import Store
from constants import VISITOR_COOKIE


class DeliveryModel:
    """模拟策略只读取本轮真实工具观察，不能预先决定走回执还是仓库。"""

    def __init__(self):
        self.decisions = []

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        context = json.loads(messages[-1][1])
        if "工具观察" not in context:
            return SimpleNamespace(content="")
        goal = context["用户消息"]
        observations = context["工具观察"]
        seen = [item["tool"] for item in observations]
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
        return SimpleNamespace(tool_calls=[{"name": name, "args": {}}])


class ReactTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "support.db"
        self.model = DeliveryModel()
        self.client = self.open()

    def open(self):
        client = TestClient(create_app(Store(self.path), lambda: self.model))
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
        self.assertFalse(db.sql("SELECT visitor FROM pending_tasks"))
        self.assertFalse(db.sql("SELECT id FROM refunds"))

    def test_native_interrupt_remains_at_act_until_valid_resume(self):
        pending = self.send("查物流")
        visitor = self.client.cookies[VISITOR_COOKIE]
        config = {"configurable": {"thread_id": visitor}}
        graph = self.client.app.state.conversation.graph
        snapshot = graph.get_state(config)
        self.assertEqual(snapshot.next, ("act",))
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
            data = json.loads(messages[-1][1])
            if data.get("工具观察"):
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

    def test_diagnosis_branches_on_actual_observation(self):
        orders = self.client.get("/api/orders").json()
        for order, expected in [(orders[0], "check_delivery_receipt"), (orders[-1], "check_fulfillment")]:
            self.send(order["id"], True)
            self.model.decisions.clear()
            answer = self.send("为什么我的包裹还没到？")
            self.assertIn("模拟", answer["text"])
            self.assertEqual([name for _, name in self.model.decisions], ["track_shipment", expected, "finish"])
