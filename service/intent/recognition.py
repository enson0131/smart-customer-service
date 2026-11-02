import re

from ..domain.tools import TOOLS


def explicit_action(message):
    return message == "取消" or re.fullmatch(r"O-[0-9a-f]{16}", message) is not None


def fallback(s):
    msg, session = s["message"], s["session"]
    order = re.search(r"O-[a-f0-9]{16}(?![a-f0-9])", msg, re.I)
    order_id = "O-" + order[0][2:].lower() if order else ""
    reason = session["reason"] if session["topic"] == "choose_refund" else None
    if any(w in msg for w in ("质量问题", "不喜欢", "不合适", "个人原因")):
        reason = msg[:240]
    if msg in ("取消", "取消申请", "放弃"):
        action = "cancel"
    elif re.search(r"进度|我的申请|申请编号|R-[a-f0-9]{16}", msg, re.I):
        action = "progress"
    elif re.search(r"运费|期限|政策|流程|多少天|几天|怎么退", msg):
        action = "policy"
    elif re.search(r"能退|可以退|想退|要退|申请退款|办理退款|退掉|整单退", msg):
        action = "preview"
    elif order_id:
        action = "preview" if session["topic"] == "choose_refund" else "orders"
    elif re.search(r"订单|查单", msg):
        action = "orders"
    else:
        action = "policy"
    return {"route": action, "order_id": order_id, "reason": reason or "客户申请整单退款"}


def recognize(model, session, message, history):
    context = {"话题": session["topic"], "选中订单": session["selected"],
               "待确认原因": session["reason"], "最近对话": history, "用户消息": message}
    calls = model.select_tool(
        "你是售后助手。根据用户当下的意图和对话记录，调用一个客服工具。"
        "只使用记录中出现或用户提供的订单号，有歧义先澄清。咨询政策选 policy，"
        "询问某单能否退或要求退货选 preview。退款只能由用户点击确认卡提交。", context)
    if len(calls) != 1 or calls[0]["name"] not in TOOLS:
        return {"route": "clarify", "question": "你想了解售后政策、查看订单，还是办理退款？"}
    call = calls[0]
    try:
        args = TOOLS[call["name"]].model_validate(call["args"]).model_dump()
    except ValueError:
        return {"route": "clarify", "question": "请补充要查询的订单或具体问题。"}
    return {"route": call["name"], "order_id": args.get("order_id", ""),
            **args, "reason": args.get("reason") or session["reason"] or "客户申请整单退款"}
