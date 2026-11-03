"""记录可观察的任务事件；仅输出显式选取的字段。"""

import json
import logging
import re
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import monotonic

from langchain_core.callbacks import BaseCallbackHandler
from langgraph.errors import GraphInterrupt

_current = ContextVar("task_trace", default=None)


def event(name, **fields):
    trace = _current.get()
    if trace:
        trace.write(name, **fields)


class TaskTrace(BaseCallbackHandler):
    """每个 HTTP 请求使用独立回调；跨请求用检查点中的 task_id 关联。"""

    def __init__(self, logger, task_id, visitor=None):
        self.visitor = visitor
        self.logger = logger
        self.task_id = task_id
        self.nodes = {}

    def write(self, name, **fields):
        row = {"time": datetime.now(UTC).isoformat(timespec="milliseconds"),
               "task_id": self.task_id, "event": name, **fields}
        self.logger.info(json.dumps(self.redact(row), ensure_ascii=False), extra={"task_event": name})

    def redact(self, value):
        if isinstance(value, dict):
            protected = {"api_key", "authorization", "cookie", "set-cookie", "ticket", "password",
                         "access_token", "visitor", "visitor_id", "thread_id"}
            return {key: "[REDACTED]" if key.lower() in protected or key.lower().endswith("_api_key")
                    else self.redact(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.redact(item) for item in value]
        if isinstance(value, str):
            # 模型消息和历史回复可能是嵌套的 JSON 文本。
            if value.lstrip().startswith(("{", "[")):
                try:
                    original = json.loads(value)
                except ValueError:
                    pass
                else:
                    cleaned = self.redact(original)
                    if cleaned != original:
                        value = json.dumps(cleaned, ensure_ascii=False)
            if self.visitor:
                value = value.replace(self.visitor, "[REDACTED]")
            return re.sub(r"(?i)\b(?:P-[a-f0-9]{16}|sk-[\w-]{12,}|Bearer\s+[\w.+/=-]+)", "[REDACTED]", value)
        return value

    def on_chat_model_start(self, serialized, messages, *, run_id, invocation_params=None, **kwargs):
        # 从 LangChain 的实际调用读取提示和绑定参数，不转储客户端配置或 HTTP 头。
        params = invocation_params or {}
        safe_keys = ("model", "model_name", "temperature", "max_tokens", "max_completion_tokens",
                     "top_p", "stop", "stream", "tools", "tool_choice", "parallel_tool_calls")
        batches = []
        for batch in messages:
            items = []
            for msg in batch:
                item = {"role": msg.type, "content": msg.content}
                if getattr(msg, "tool_calls", None):
                    item["tool_calls"] = msg.tool_calls
                if getattr(msg, "tool_call_id", None):
                    item["tool_call_id"] = msg.tool_call_id
                items.append(item)
            batches.append(items)
        self.write("model.request", call_id=str(run_id), messages=batches,
                   params={key: params[key] for key in safe_keys if key in params})

    def on_llm_end(self, response, *, run_id, **kwargs):
        answers = []
        for batch in response.generations:
            for generation in batch:
                message = generation.message
                answers.append({"content": message.content, "tool_calls": message.tool_calls,
                                "invalid_tool_calls": message.invalid_tool_calls,
                                "usage": message.usage_metadata,
                                "finish_reason": message.response_metadata.get("finish_reason")})
        self.write("model.response", call_id=str(run_id), answers=answers)

    def on_llm_error(self, error, *, run_id, **kwargs):
        self.write("model.error", call_id=str(run_id), error_type=type(error).__name__)

    @contextmanager
    def active(self):
        token = _current.set(self)
        try:
            yield
        finally:
            _current.reset(token)

    def on_chain_start(self, serialized, inputs, *, run_id, metadata=None, name=None, tags=None, **kwargs):
        # LangGraph 的节点回调附带 graph:step 标签；忽略内部条件边和模型提示链。
        if name == (metadata or {}).get("langgraph_node") and any(t.startswith("graph:step:") for t in tags or []):
            self.nodes[run_id] = (name, monotonic())
            self.write("node.start", node=name)

    def on_chain_end(self, outputs, *, run_id, **kwargs):
        if run_id in self.nodes:
            name, start = self.nodes.pop(run_id)
            fields = {}
            if isinstance(outputs, dict):
                if outputs.get("destination"):
                    fields["next"] = outputs["destination"]
                if outputs.get("step"):
                    fields["tool"] = outputs["step"]["name"]
            self.write("node.end", node=name, elapsed_ms=round((monotonic()-start)*1000), **fields)

    def on_chain_error(self, error, *, run_id, **kwargs):
        if run_id in self.nodes:
            name, _ = self.nodes.pop(run_id)
            if isinstance(error, GraphInterrupt):
                self.write("node.interrupt", node=name)
            else:
                self.write("node.error", node=name, error_type=type(error).__name__)


class LocalTaskHandler(RotatingFileHandler):
    def emit(self, record):
        super().emit(record)
        if getattr(record, "task_event", None) not in {"chat.response", "request.error"}:
            return
        # 此时 JSONL 已刷新，且 logging 仍持有 handler 锁；轮转或并发写入不会打断快照。
        source = Path(self.baseFilename)
        temporary = None
        try:
            with source.open(encoding="utf-8") as log:
                events = [json.loads(line) for line in log if line.strip()]
            with NamedTemporaryFile(mode="w", encoding="utf-8", dir=source.parent, delete=False) as out:
                temporary = Path(out.name)
                json.dump(events, out, ensure_ascii=False, indent=2)
                out.write("\n")
            temporary.replace(source.with_suffix(".pretty.json"))
        except (OSError, ValueError):
            self.handleError(record)
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)


@contextmanager
def task_logger(directory):
    logger = logging.Logger("aftercare.task", level=logging.INFO)
    if directory is None:
        handler = logging.StreamHandler(sys.stdout)
    else:
        directory.mkdir(parents=True, exist_ok=True)
        handler = LocalTaskHandler(directory / "tasks.jsonl", maxBytes=5*1024*1024,
                                   backupCount=3, encoding="utf-8")
    logger.addHandler(handler)
    try:
        yield logger
    finally:
        logger.removeHandler(handler)
        handler.close()
