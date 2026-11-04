"""第一级意图识别。只接受已约定的完整指令，不做关键词或相似度匹配。"""

EXACT_QUERIES = {
    "查看我的订单": "orders",
    "查询退款进度": "progress",
    "退货运费谁承担": "policy",
}


def match_single_intent(message, session, action=None):
    if action is not None:
        # 按钮类型和消息必须一致，避免把附带其他需求的文本截断。
        if action["kind"] == "select_order" and message == action["order_id"]:
            name = "preview" if session["topic"] == "choose_refund" else "orders"
            return {"name": name, "args": {"order_id": action["order_id"]}}
        if action["kind"] == "cancel_pending" and message == "取消":
            return {"name": "cancel", "args": {}}
        return None

    name = EXACT_QUERIES.get(message)
    if name is None:
        return None
    args = {"query": message} if name == "policy" else {}
    return {"name": name, "args": args}
