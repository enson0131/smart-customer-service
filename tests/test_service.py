import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from service.app import create_app
from service.storage.store import Store


class SupportTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.db = Store(Path(directory.name) / "support.db")
        self.client = self.open_client()

    def open_client(self, model=None):
        client = TestClient(create_app(self.db, lambda: model))
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        return client

    def chat(self, message, client=None):
        response = (client or self.client).post("/api/chat", json={"message": message})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_policy_and_unknown(self):
        result = self.chat("退货运费谁承担")
        self.assertEqual(result["mode"], "检索模式")
        self.assertIn("商家承担", result["sources"][0]["excerpt"])
        self.assertFalse(self.chat("海外关税如何计算")["sources"])

    def test_confirmation_is_idempotent_and_private(self):
        choices = self.chat("因为质量问题想退款")["orders"]
        card = self.chat(choices[0]["id"])["card"]
        self.assertIn("质量问题", card["reason"])
        body = {"ticket": card["ticket"]}
        self.assertIn("没有提交", self.chat("查询退款进度")["text"])
        self.assertEqual(self.client.post("/api/refunds/confirm", json=body).status_code, 409)
        card = self.chat("这单能退吗")["card"]
        body = {"ticket": card["ticket"]}
        other = self.open_client()
        self.assertNotIn(choices[0]["id"], str(other.get("/api/orders").json()))
        self.assertIn("未找到", self.chat(choices[0]["id"], other)["text"])
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
        card = self.chat("申请退款 " + rows[0]["id"])["card"]
        self.chat("取消")
        self.assertEqual(self.client.post("/api/refunds/confirm", json={"ticket": card["ticket"]}).status_code, 409)
        self.assertIn("超过", self.chat("申请退款 " + rows[1]["id"])["text"])
        self.assertIn("尚未签收", self.chat("申请退款 " + rows[2]["id"])["text"])
        self.assertFalse(self.db.sql("SELECT id FROM refunds"))

    def test_model_routing_and_failure(self):
        class Model:
            def bind_tools(self, tools):
                class Selector:
                    def invoke(self, messages):
                        import json
                        context = json.loads(messages[-1][1])
                        msg = context["用户消息"]
                        name, args = "orders", {}
                        if "寄回" in msg:
                            assert context["最近对话"] and context["选中订单"]
                            name, args = "preview", {"reason": "打算寄回"}
                        elif "运费" in msg:
                            name, args = "policy", {"query": msg}
                        return SimpleNamespace(tool_calls=[{"name": name, "args": args}])
                return Selector()

            def invoke(self, messages):
                return SimpleNamespace(content="质量问题的退货运费由商家承担。")

        client = self.open_client(Model())
        order = self.chat("查看我的订单", client)["orders"][0]
        self.chat(order["id"], client)
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
        self.assertFalse(self.chat("海外关税如何计算", client)["sources"])
