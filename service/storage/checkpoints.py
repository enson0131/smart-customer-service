"""同步 LangGraph checkpointer；SQLite 和 Cloudflare D1 共用 Store 的 SQL 接口。"""

import base64
import json
import sqlite3
from contextlib import closing, contextmanager

from langgraph.checkpoint.sqlite import SqliteSaver

from langgraph.checkpoint.base import BaseCheckpointSaver, CheckpointTuple, WRITES_IDX_MAP
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from ..domain.outcomes import Outcome


@contextmanager
def open_checkpointer(store):
    serializer = JsonPlusSerializer(allowed_msgpack_modules=[Outcome])
    if store.remote:
        yield D1Checkpointer(store, serializer)
    else:
        with closing(sqlite3.connect(store.path, check_same_thread=False)) as conn:
            yield SqliteSaver(conn, serde=serializer)


class D1Checkpointer(BaseCheckpointSaver):
    def __init__(self, store, serializer):
        super().__init__(serde=serializer)
        self.store = store

    def encode(self, value):
        kind, data = self.serde.dumps_typed(value)
        return json.dumps([kind, base64.b64encode(data).decode("ascii")])

    def decode(self, encoded):
        kind, data = json.loads(encoded)
        return self.serde.loads_typed((kind, base64.b64decode(data)))

    @staticmethod
    def config(thread, ns, checkpoint_id):
        return {"configurable": {"thread_id": thread, "checkpoint_ns": ns, "checkpoint_id": checkpoint_id}}

    def put(self, config, checkpoint, metadata, new_versions):
        conf = config["configurable"]
        thread, ns = conf["thread_id"], conf.get("checkpoint_ns", "")
        self.store.sql("INSERT OR REPLACE INTO graph_checkpoints VALUES (?,?,?,?,?,?)",
                       thread, ns, checkpoint["id"], conf.get("checkpoint_id"),
                       self.encode(checkpoint), json.dumps(metadata))
        return self.config(thread, ns, checkpoint["id"])

    def put_writes(self, config, writes, task_id, task_path=""):
        conf = config["configurable"]
        rows = [[WRITES_IDX_MAP.get(channel, i), channel, self.encode(value)]
                for i, (channel, value) in enumerate(writes)]
        # Regular task writes are idempotent; LangGraph reserves negative indices for
        # resumable/interrupt writes that may be replaced when the step is replayed.
        self.store.sql("""INSERT INTO graph_writes
            SELECT ?,?,?,?, value->>0, value->>1, value->>2 FROM json_each(?) WHERE true
            ON CONFLICT(thread,ns,id,task,idx) DO UPDATE SET payload=excluded.payload WHERE excluded.idx<0""",
                       conf["thread_id"], conf.get("checkpoint_ns", ""), conf["checkpoint_id"],
                       task_id, json.dumps(rows))

    def get_tuple(self, config):
        conf = config["configurable"]
        thread, ns = conf["thread_id"], conf.get("checkpoint_ns", "")
        checkpoint_id = conf.get("checkpoint_id")
        rows = self.store.sql("""SELECT * FROM graph_checkpoints WHERE thread=? AND ns=?
            AND (? IS NULL OR id=?) ORDER BY id DESC LIMIT 1""", thread, ns, checkpoint_id, checkpoint_id)
        if not rows:
            return None
        row = rows[0]
        writes = self.store.sql("""SELECT task,channel,payload FROM graph_writes
            WHERE thread=? AND ns=? AND id=? ORDER BY task,idx""", thread, ns, row["id"])
        return CheckpointTuple(
            self.config(thread, ns, row["id"]), self.decode(row["payload"]), json.loads(row["metadata"]),
            self.config(thread, ns, row["parent"]) if row["parent"] else None,
            [(w["task"], w["channel"], self.decode(w["payload"])) for w in writes],
        )

    def delete_thread(self, thread_id):
        self.store.sql("DELETE FROM graph_writes WHERE thread=?", thread_id)
        self.store.sql("DELETE FROM graph_checkpoints WHERE thread=?", thread_id)
