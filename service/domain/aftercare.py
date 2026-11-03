"""订单、退款和进度查询能力，所有查询均限定在当前访客范围内。"""

from datetime import UTC, date, datetime

from constants import REFUND_STATUS, RETURN_WINDOW_DAYS
from ..storage.store import ident
from .outcomes import Outcome


def preview_refund(store, visitor, order_id, reason):
    rows = store.orders(visitor)
    order = next((row for row in rows if row["id"] == order_id), None)
    if not order:
        return Outcome("order_missing")
    existing = store.sql("SELECT id FROM refunds WHERE visitor=? AND order_id=?", visitor, order_id)
    if existing:
        return Outcome("already_submitted", {"reference": existing[0]["id"], "status": REFUND_STATUS})
    if not order["delivered"]:
        return Outcome("not_delivered")
    days = (datetime.now(UTC).date() - date.fromisoformat(order["delivered"])).days
    if not 0 <= days <= RETURN_WINDOW_DAYS:
        return Outcome("outside_window", {"days": RETURN_WINDOW_DAYS})
    facts = {"order_id": order_id, "cents": order["cents"], "reason": reason}
    return Outcome("needs_confirmation", facts, {"card": {**facts, "ticket": ident("P-")}})



def refund_progress(store, visitor, reference):
    if reference:
        rows = [store.refund(visitor, reference)]
    else:
        rows = store.sql("SELECT id,order_id FROM refunds WHERE visitor=? ORDER BY rowid DESC", visitor)
    return Outcome("refund_progress", {"refunds": [{**row, "status": REFUND_STATUS} for row in rows]})


def shipping_cost():
    return Outcome("unavailable", {"reason": "order_has_no_shipping_fee_field"})
