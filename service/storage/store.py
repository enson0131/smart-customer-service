import json
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

    def visitor(self, cookie):
        if cookie:
            rows = self.sql("SELECT id FROM visitors WHERE id=?", cookie)
            if rows:
                return rows[0]
        visitor = secrets.token_urlsafe(32)
        today = datetime.now(UTC).date()
        self.sql("INSERT INTO visitors(id) VALUES (?)", visitor)
        self.sql("INSERT INTO orders VALUES (?,?,?,?,?), (?,?,?,?,?), (?,?,?,?,?)",
                 ident("O-"), visitor, "云杉阅读灯", 12900, str(today - timedelta(days=2)),
                 ident("O-"), visitor, "雾蓝随行杯", 6900, str(today - timedelta(days=10)),
                 ident("O-"), visitor, "山野收纳包", 3900, None)
        return {"id": visitor}

    def orders(self, visitor):
        return self.sql("SELECT id,product,cents,delivered FROM orders WHERE visitor=? ORDER BY rowid", visitor)

    def create_chat(self, visitor_id):
        chat_id = ident("C-")
        self.sql("INSERT INTO chats(id,visitor_id) VALUES (?,?)", chat_id, visitor_id)
        return self.chat(visitor_id, chat_id)

    def chat(self, visitor_id, chat_id):
        rows = self.sql("SELECT * FROM chats WHERE id=? AND visitor_id=?", chat_id, visitor_id)
        if not rows:
            raise HTTPException(404, "未找到这段聊天。")
        return rows[0]

    def chats(self, visitor_id):
        return self.sql("""SELECT id,created_at,COALESCE(
            (SELECT substr(message,1,24) FROM chat_messages WHERE chat_id=chats.id ORDER BY id LIMIT 1),
            '新聊天') AS title FROM chats WHERE visitor_id=? ORDER BY rowid DESC""", visitor_id)

    def messages(self, chat_id):
        return self.sql("SELECT message,answer FROM chat_messages WHERE chat_id=? ORDER BY id", chat_id)

    def recent_turns(self, chat_id):
        rows = self.sql("SELECT message,answer FROM chat_messages WHERE chat_id=? ORDER BY id DESC LIMIT 6", chat_id)
        return rows[::-1]

    def record_turn(self, chat_id, message, reply):
        self.sql("INSERT INTO chat_messages(chat_id,message,answer) VALUES (?,?,?)",
                 chat_id, message, json.dumps(reply, ensure_ascii=False))

    def context(self, chat_id, topic, selected=None, ticket=None, reason=None):
        self.sql("UPDATE chats SET topic=?,selected=?,ticket=?,reason=? WHERE id=?",
                 topic, selected, ticket, reason, chat_id)

    def cancel_pending(self, chat_id):
        rows = self.sql("""UPDATE chats SET topic='orders',ticket=NULL,reason=NULL
            WHERE id=? AND (topic='choose_refund' OR (topic='preview' AND ticket IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM refunds WHERE refunds.ticket=chats.ticket)))
            RETURNING id""", chat_id)
        return bool(rows)

    def confirm(self, visitor_id, chat_id, ticket):
        self.chat(visitor_id, chat_id)
        # 确认仅使用本聊天的有效票据，写入时再次核验访客归属和退款期限。
        self.sql("""INSERT INTO refunds (id,visitor,order_id,ticket,cents,reason,chat_id)
            SELECT ?,c.visitor_id,o.id,c.ticket,o.cents,c.reason,c.id FROM chats c
            JOIN orders o ON o.id=c.selected AND o.visitor=c.visitor_id
            WHERE c.id=? AND c.visitor_id=? AND c.ticket=?
            AND o.delivered BETWEEN date('now',?) AND date('now')
            ON CONFLICT DO NOTHING""", ident("R-"), chat_id, visitor_id, ticket, f"-{RETURN_WINDOW_DAYS} days")
        rows = self.sql("SELECT id FROM refunds WHERE visitor=? AND chat_id=? AND ticket=?", visitor_id, chat_id, ticket)
        if not rows:
            raise HTTPException(409, "确认卡已失效，请重新查看该订单。")
        return self.refund(visitor_id, rows[0]["id"])

    def refund(self, visitor, ref):
        rows = self.sql("SELECT id,order_id,cents,reason FROM refunds WHERE visitor=? AND id=?", visitor, ref)
        if not rows:
            raise HTTPException(404, "未找到这笔申请。")
        return {**rows[0], "status": REFUND_STATUS}
