import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from fake_chat import TestChatModel, goal_and_tools

from chat_client import ChatTestClient as TestClient

from service.app import create_app
from service.storage.store import Store


class ScriptedModel:
    """以已返回的工具观察决定本次模拟模型调用。"""
    def __init__(self):
        self.plans = {
            "退货运费谁承担": [("policy", {"query": "退货运费谁承担"})],
            "海外关税如何计算": [("policy", {"query": "海外关税如何计算"})],
            "因为质量问题想退款": [("preview", {"reason": "质量问题"})],
            "查询退款进度": [("progress", {})],
            "这单能退吗": [("preview", {})],
            "我取消刚刚的操作": [("cancel", {})],
            "取消刚刚的操作": [("cancel", {})],
            "取消这个订单": [("clarify", {"question": "订单不支持撤销。"})],
        }

    def invoke(self, messages):
        goal, tools = goal_and_tools(messages)
        if goal.startswith("{"):
            return ""
        steps = self.plans[goal]
        return [steps[len(tools)]] if len(tools) < len(steps) else ""


class SupportTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.db = Store(Path(directory.name) / "support.db")
        self.model = ScriptedModel()
        self.client = self.open_client()

    def open_client(self, model=None):
        client = TestClient(create_app(self.db, lambda: TestChatModel(responder=lambda messages: (model or self.model).invoke(messages))))
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        return client

    def chat(self, message, client=None, action=None):
        response = (client or self.client).post("/api/chat", json={"message": message, "action": action})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_policy_and_unknown(self):
        result = self.chat("退货运费谁承担")
        self.assertEqual(result["mode"], "检索模式")
        self.assertIn("商家承担", result["sources"][0]["excerpt"])
        self.assertFalse(self.chat("海外关税如何计算")["sources"])

    def test_confirmation_is_idempotent_and_private(self):
        choices = self.chat("因为质量问题想退款")["orders"]
        card = self.chat(choices[0]["id"], action={"kind":"select_order", "order_id":choices[0]["id"]})["card"]
        self.assertIn("质量问题", card["reason"])
        body = {"ticket": card["ticket"]}
        self.assertIn("没有提交", self.chat("查询退款进度")["text"])
        self.assertEqual(self.client.post("/api/refunds/confirm", json=body).status_code, 409)
        card = self.chat("这单能退吗")["card"]
        body = {"ticket": card["ticket"]}
        other = self.open_client()
        self.assertNotIn(choices[0]["id"], str(other.get("/api/orders").json()))
        self.assertIn("未找到", self.chat(choices[0]["id"], other, {"kind":"select_order", "order_id":choices[0]["id"]})["text"])
        self.assertEqual(other.post("/api/refunds/confirm", json=body).status_code, 409)
        with ThreadPoolExecutor(4) as pool:
            results = list(pool.map(lambda _: self.client.post("/api/refunds/confirm", json=body).json(), range(8)))
        ids = {r["id"] for r in results}
        self.assertEqual(len(ids), 1)
        ref = results[0]["id"]
        self.assertEqual(self.db.sql("SELECT COUNT(*) AS n FROM refunds")[0]["n"], 1)
        self.assertEqual(other.get("/api/refunds/" + ref).status_code, 404)
        self.assertEqual(self.client.get("/api/refunds/" + ref).json()["cents"], choices[0]["cents"])
        restarted = self.open_client()
        restarted.cookies.update(self.client.cookies)
        self.assertIn(ref, self.chat("查询退款进度", restarted)["text"])

    def test_cancel_and_eligibility(self):
        rows = self.client.get("/api/orders").json()
        for row in rows:
            self.model.plans["申请退款 " + row["id"]] = [("preview", {"order_id": row["id"]})]
        card = self.chat("申请退款 " + rows[0]["id"])["card"]
        self.chat("取消", action={"kind":"cancel_pending"})
        self.assertEqual(self.client.post("/api/refunds/confirm", json={"ticket": card["ticket"]}).status_code, 409)
        self.assertIn("超过", self.chat("申请退款 " + rows[1]["id"])["text"])
        self.assertIn("尚未签收", self.chat("申请退款 " + rows[2]["id"])["text"])
        self.assertFalse(self.db.sql("SELECT id FROM refunds"))

    def test_orders_and_shipping(self):
        row = self.client.get("/api/orders").json()[0]
        self.model.plans["我想查询这个订单，然后再查看这单的运费是多少？"] = [("orders", {"order_id": row["id"]}), ("shipping_cost", {})]
        self.chat(row["id"], action={"kind":"select_order", "order_id":row["id"]})
        answer = self.chat("我想查询这个订单，然后再查看这单的运费是多少？")
        self.assertEqual([r["id"] for r in answer["orders"]], [row["id"]])
        self.assertIn("没有记录具体运费", answer["text"])

        model = ScriptedModel()
        message = "帮我找找买的东西，也想知道邮寄要花几块钱"
        model.plans[message] = [("orders", {}), ("shipping_cost", {})]
        answer = self.chat(message, self.open_client(model))
        self.assertTrue(answer["orders"])
        self.assertIn("没有记录具体运费", answer["text"])

    def test_composed_reply_preserves_order_card(self):
        order = self.client.get("/api/orders").json()[0]
        message = "查这笔订单，再看看运费"
        expected = "查到了你的云杉阅读灯订单，但订单里没有单列运费。"
        class Model(ScriptedModel):
            def invoke(self, messages):
                goal, tools = goal_and_tools(messages)
                if len(tools) == 2:
                    assert goal == message
                    assert json.loads(tools[0].content)["facts"]["product"] == order["product"]
                    assert json.loads(tools[1].content)["status"] == "unavailable"
                    return "" if self.timeout else expected
                return super().invoke(messages)

        model = Model()
        model.timeout = False
        model.plans[message] = [("orders", {"order_id": order["id"]}), ("shipping_cost", {})]
        client = self.open_client(model)
        client.cookies.update(self.client.cookies)
        result = self.chat(message, client)
        self.assertEqual(result["text"], expected)
        self.assertEqual(result["orders"], [order])
        model.timeout = True
        fallback = self.chat(message, client)
        self.assertIn(order["product"], fallback["text"])
        self.assertIn("没有记录具体运费", fallback["text"])
        self.assertEqual(fallback["orders"], [order])

    def test_cancel_operation_scope(self):
        row = self.client.get("/api/orders").json()[0]
        self.model.plans["申请退款 " + row["id"]] = [("preview", {"order_id": row["id"]})]
        card = self.chat("申请退款 " + row["id"])["card"]
        self.assertIn("不支持撤销", self.chat("取消这个订单")["text"])
        self.assertIn("已关闭", self.chat("我取消刚刚的操作")["text"])
        self.assertEqual(self.client.post("/api/refunds/confirm", json={"ticket": card["ticket"]}).status_code, 409)
        self.assertEqual(self.client.get("/api/orders").json()[0], row)
        self.assertIn("没有待确认", self.chat("取消刚刚的操作")["text"])
        card = self.chat("申请退款 " + row["id"])["card"]
        ref = self.client.post("/api/refunds/confirm", json={"ticket": card["ticket"]}).json()["id"]
        self.assertIn("没有待确认", self.chat("取消刚刚的操作")["text"])
        self.assertEqual(self.client.get("/api/refunds/" + ref).status_code, 200)

    def test_observation_order_and_invalid_call(self):
        row = self.client.get("/api/orders").json()[0]
        self.model.plans["办三件事"] = [
            ("orders", {"order_id": row["id"]}), ("preview", {}), ("shipping_cost", {}),
        ]
        result = self.chat("办三件事")
        self.assertEqual(result["card"]["order_id"], row["id"])
        self.assertLess(result["text"].index("查到了"), result["text"].index("符合退款"))
        self.assertLess(result["text"].index("符合退款"), result["text"].index("具体运费"))
        self.assertEqual(len(self.db.sql("SELECT id FROM chat_messages")), 1)
        self.model.plans["错误计划"] = [("unknown", {})]
        self.assertIn("稍后重试", self.chat("错误计划")["text"])
        # 单独输入“取消”没有指定取消对象，交给模型澄清。
        self.assertIn("稍后重试", self.chat("取消")["text"])
        self.assertEqual(self.client.post("/api/refunds/confirm", json={
            "ticket": result["card"]["ticket"]}).status_code, 200)

    def test_exact_rule_or_whole_message_to_model(self):
        from unittest.mock import patch
        with patch.object(self.model, "invoke", wraps=self.model.invoke) as invoke:
            self.assertTrue(self.chat("查看我的订单")["orders"])
            invoke.assert_not_called()
            for message in ("不要查看我的订单", "查看我的订单，然后查询退款进度"):
                self.model.plans[message] = [("clarify", {"question": "已收到完整请求"})]
                self.assertEqual(self.chat(message)["text"], "已收到完整请求")
                self.assertEqual(goal_and_tools(invoke.call_args.args[0])[0], message)
            self.assertEqual(invoke.call_count, 2)

    def test_model_routing_and_failure(self):
        class Model:
            def invoke(self, messages):
                goal, tools = goal_and_tools(messages)
                if goal.startswith("{"):
                    return "质量问题的退货运费由商家承担。"
                if tools:
                    return ""
                assert any("当前会话选中订单" in m.content for m in messages)
                return [("preview", {})]

        client = self.open_client(Model())
        order = self.chat("查看我的订单", client)["orders"][0]
        self.chat(order["id"], client, {"kind":"select_order", "order_id":order["id"]})
        self.assertEqual(self.chat("打算寄回这件", client)["card"]["order_id"], order["id"])
        answer = self.chat("退货运费谁承担", client)
        self.assertEqual(answer["mode"], "DeepSeek")
        self.assertTrue(answer["sources"])

        class Timeout:
            def bind_tools(self, tools):
                return self

            def invoke(self, messages):
                raise TimeoutError

        client = self.open_client(Timeout())
        self.assertEqual(self.chat("退货运费谁承担", client)["mode"], "检索模式")
        self.assertIn("稍后重试", self.chat("帮我看看退货运费该谁付", client)["text"])
        self.assertFalse(self.chat("海外关税如何计算", client)["sources"])
