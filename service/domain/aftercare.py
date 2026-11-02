"""订单、退款和进度查询能力，所有查询均限定在当前访客范围内。"""

from datetime import UTC, date, datetime

from constants import REFUND_STATUS, RETURN_WINDOW_DAYS
from ..storage.store import ident


def preview_refund(store, visitor, order_id, reason):
    rows = store.orders(visitor)
    order = next((row for row in rows if row["id"] == order_id), None)
    if not order:
        return {"text": "未找到这笔订单。"}
    existing = store.sql("SELECT id FROM refunds WHERE visitor=? AND order_id=?", visitor, order_id)
    if existing:
        return {"text": f"该订单已提交申请 {existing[0]['id']}，状态为{REFUND_STATUS}。"}
    if not order["delivered"]:
        return {"text": "这笔订单尚未签收。", "ineligible": True}
    days = (datetime.now(UTC).date() - date.fromisoformat(order["delivered"])).days
    if not 0 <= days <= RETURN_WINDOW_DAYS:
        return {"text": f"这笔订单已超过 {RETURN_WINDOW_DAYS} 天退货期限。", "ineligible": True}
    return {"text": "订单符合退款条件。请核对后点击确认提交。", "card": {
        "ticket": ident("P-"), "order_id": order_id, "cents": order["cents"], "reason": reason}}


def refund_progress(store, visitor, reference):
    if reference:
        rows = [store.refund(visitor, reference)]
    else:
        rows = store.sql("SELECT id,order_id FROM refunds WHERE visitor=? ORDER BY rowid DESC", visitor)
    return "\n".join(f"{row['order_id']} · {row['id']} · {REFUND_STATUS}" for row in rows) or "你还没有提交退款申请。"
