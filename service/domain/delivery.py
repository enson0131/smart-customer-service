"""演示履约与物流数据，由访客自己的虚构订单生成。"""

from .outcomes import Outcome


def delivery_record(order, tool):
    facts = {"order_id": order["id"], "product": order["product"], "simulated": True}
    if tool == "check_fulfillment":
        return Outcome("fulfillment", {**facts, "warehouse": "已出库并交运"})
    if tool == "check_delivery_receipt":
        receipt = f"{order['delivered']}，小区代收点代收" if order["delivered"] else "尚无签收回执"
        return Outcome("receipt", {**facts, "record": receipt})
    if order["delivered"]:
        return Outcome("shipment", {**facts, "state": "已签收", "event": f"{order['delivered']} 记录为签收"})
    return Outcome("shipment", {**facts, "state": "运输中", "event": "已离开分拨中心，下一站暂无扫描记录"})
