import secrets
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import HTTPException

from constants import REFUND_STATUS, RETURN_WINDOW_DAYS, SCHEMA_PATH


def ident(prefix):
    return prefix + secrets.token_hex(8)


class Store:
    def __init__(self, path=None):
        self.path = Path(path or "data/support.sqlite")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db:
            db.executescript(SCHEMA_PATH.read_text())

    def sql(self, query, *params):
        with closing(sqlite3.connect(self.path, timeout=10)) as db, db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute(query, params)]

    def session(self, cookie):
        if cookie:
            rows = self.sql("SELECT * FROM visitors WHERE id=?", cookie)
            if rows:
                return rows[0]
        visitor = secrets.token_urlsafe(32)
        today = datetime.now(UTC).date()
        self.sql("INSERT INTO visitors(id) VALUES (?)", visitor)
        self.sql("INSERT INTO orders VALUES (?,?,?,?,?), (?,?,?,?,?), (?,?,?,?,?)",
                 ident("O-"), visitor, "云杉阅读灯", 12900, str(today - timedelta(days=2)),
                 ident("O-"), visitor, "雾蓝随行杯", 6900, str(today - timedelta(days=10)),
                 ident("O-"), visitor, "山野收纳包", 3900, None)
        return {"id": visitor, "selected": None, "topic": "", "ticket": None, "reason": None}

    def orders(self, visitor):
        return self.sql("SELECT id,product,cents,delivered FROM orders WHERE visitor=? ORDER BY rowid", visitor)

    def recent_turns(self, visitor):
        rows = self.sql("SELECT message,answer FROM chat_turns WHERE visitor=? ORDER BY id DESC LIMIT 6", visitor)
        return rows[::-1]

    def record_turn(self, visitor, message, answer):
        self.sql("INSERT INTO chat_turns(visitor,message,answer) VALUES (?,?,?)", visitor, message, answer)

    def context(self, visitor, topic, selected=None, ticket=None, reason=None):
        self.sql("UPDATE visitors SET topic=?,selected=?,ticket=?,reason=? WHERE id=?",
                 topic, selected, ticket, reason, visitor)

    def cancel_pending(self, visitor):
        rows = self.sql("""UPDATE visitors SET topic='orders',ticket=NULL,reason=NULL
            WHERE id=? AND (topic='choose_refund' OR (topic='preview' AND ticket IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM refunds WHERE refunds.ticket=visitors.ticket)))
            RETURNING id""", visitor)
        return bool(rows)

    def confirm(self, visitor, ticket):
        # Validate the live preview, ownership and return window in the write itself.
        self.sql("""INSERT INTO refunds (id,visitor,order_id,ticket,cents,reason)
            SELECT ?,v.id,o.id,v.ticket,o.cents,v.reason FROM visitors v
            JOIN orders o ON o.id=v.selected AND o.visitor=v.id
            WHERE v.id=? AND v.ticket=? AND o.delivered BETWEEN date('now',?) AND date('now')
            ON CONFLICT DO NOTHING""", ident("R-"), visitor, ticket, f"-{RETURN_WINDOW_DAYS} days")
        rows = self.sql("SELECT id FROM refunds WHERE visitor=? AND ticket=?", visitor, ticket)
        if not rows:
            raise HTTPException(409, "确认卡已失效，请重新查看该订单。")
        return self.refund(visitor, rows[0]["id"])

    def refund(self, visitor, ref):
        rows = self.sql("SELECT id,order_id,cents,reason FROM refunds WHERE visitor=? AND id=?", visitor, ref)
        if not rows:
            raise HTTPException(404, "未找到这笔申请。")
        return {**rows[0], "status": REFUND_STATUS}
