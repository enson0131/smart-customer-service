"""使用 LangGraph 原生 SQLite 检查点保存中断和消息状态。"""

import sqlite3
from contextlib import closing, contextmanager

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from ..domain.outcomes import Outcome


@contextmanager
def open_checkpointer(store):
    serializer = JsonPlusSerializer(allowed_msgpack_modules=[Outcome])
    with closing(sqlite3.connect(store.path, check_same_thread=False)) as conn:
        yield SqliteSaver(conn, serde=serializer)
