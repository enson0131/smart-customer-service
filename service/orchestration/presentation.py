"""将业务事实转为客户答复，页面组件始终从后端结果组装。"""

from ..domain.outcomes import Outcome


def template(outcome: Outcome):
    facts = outcome.facts
    match outcome.status:
        case "order_found":
            return f"查到了你的「{facts['product']}」订单。"
        case "order_list":
            return "请选择要查看的订单。"
        case "order_missing":
            return "未找到这笔订单。"
        case "choose_delivery":
            return "请先选一笔订单，我会接着查询这笔订单的物流。"
        case "receipt":
            return f"模拟回执 · {facts['product']}：{facts['record']}。"
        case "shipment":
            return f"模拟物流 · {facts['product']}：{facts['state']}。{facts['event']}。"
        case "fulfillment":
            return f"模拟履约记录 · {facts['product']}：{facts['warehouse']}。"
        case "choose_refund":
            return "请先选一笔要办理退款的订单。"
        case "needs_confirmation":
            return "订单符合退款条件。请核对后点击确认提交。"
        case "preview_closed":
            return "这张退款确认卡已失效。"
        case "not_delivered":
            return "这笔订单尚未签收。"
        case "outside_window":
            return f"这笔订单已超过 {facts['days']} 天退货期限。"
        case "already_submitted":
            return f"该订单已提交申请 {facts['reference']}，状态为{facts['status']}。"
        case "refund_progress":
            return "\n".join(f"{r['order_id']} · {r['id']} · {r['status']}" for r in facts["refunds"]) or "你还没有提交退款申请。"
        case "cancelled":
            return "已关闭本次待确认的退款操作。订单保持原状。"
        case "nothing_pending":
            return "当前没有待确认的退款操作。"
        case "policy_found":
            return "找到以下相关政策原文，供你核对。"
        case "policy_missing":
            return f"演示知识库缺少关于「{facts['query']}」的依据，请向人工客服核实。"
        case "unavailable":
            return "订单里没有记录具体运费，目前查不到金额。"
        case "user_input":
            return facts["message"]
        case "clarify":
            return facts["question"]
    raise ValueError(f"未知的业务结果：{outcome.status}")


def present(plan, outcomes):
    response = {"text": "\n".join(template(item) for item in outcomes), "sources": []}
    orders = {}
    for step, item in zip(plan, outcomes):
        for order in item.artifacts.get("orders", []):
            orders[order["id"]] = order
        if "card" in item.artifacts:
            response["card"] = item.artifacts["card"]
        if step["name"] == "policy":
            response["mode"] = "检索模式"
            for source in item.facts.get("sources", []):
                if source not in response["sources"]:
                    response["sources"].append(source)
    # 该组合即使不调用模型，也能用商品名称和运费缺失原因组成完整答复。
    if [item.status for item in outcomes] == ["order_found", "unavailable"]:
        product = outcomes[0].facts["product"]
        response["text"] = f"这笔「{product}」订单没有记录具体运费，目前查不到金额。"
    if orders:
        response["orders"] = list(orders.values())

    return response
