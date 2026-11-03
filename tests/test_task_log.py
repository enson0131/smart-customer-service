import json
import tempfile
import unittest
from pathlib import Path

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from service.task_log import TaskTrace, task_logger


class TaskLogTest(unittest.TestCase):
    def test_pretty_snapshot_updates_on_response_and_error_after_rotation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            source = path / "tasks.jsonl"
            source.write_text('{"event":"existing"}\n')
            target = path / "tasks.pretty.json"
            with task_logger(path) as logger:
                trace = TaskTrace(logger, "test")
                trace.write("chat.response", reply={"text": "请选择订单"})
                self.assertIn('  {', target.read_text())
                self.assertEqual(json.loads(target.read_text()), list(map(json.loads, source.read_text().splitlines())))
                logger.handlers[0].maxBytes = 1
                trace.write("request.error", error_type="TimeoutError")
                self.assertEqual(json.loads(target.read_text()), [json.loads(source.read_text())])
                self.assertTrue((path / "tasks.jsonl.1").exists())

    def test_native_chat_callback_logs_prompt_and_tool_response(self):
        secret = "P-0123456789abcdef"
        result = AIMessage(content="查询订单", tool_calls=[
            {"name": "orders", "args": {"ticket": secret}, "id": "call_1"}])
        model = FakeMessagesListChatModel(responses=[result])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            with task_logger(path) as logger:
                trace = TaskTrace(logger, "test")
                model.invoke([("system", "仅使用已核实事实"), ("human", "查物流")],
                             config={"callbacks": [trace]})
            raw = (path / "tasks.jsonl").read_text()
        request, response = map(json.loads, raw.splitlines())
        self.assertEqual(request["messages"][0][0], {"role": "system", "content": "仅使用已核实事实"})
        self.assertEqual(request["messages"][0][1]["content"], "查物流")
        self.assertEqual(request["call_id"], response["call_id"])
        self.assertEqual(response["answers"][0]["tool_calls"][0]["name"], "orders")
        self.assertNotIn(secret, raw)
