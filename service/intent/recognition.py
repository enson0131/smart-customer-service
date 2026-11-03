from ..domain.tools import TOOLS


def next_action(model, session, goal, history, observations, supplement):
    """只决定眼前的一步，执行后的事实将在下次决策时传回。"""
    calls = model.select_tool(
        "你是只处理演示售后的 ReAct 客服。每次调用一个工具，根据实际观察再决定下一步。"
        "逐项检查原请求，所有诉求有结果才调用 finish。不要重复已完成步骤。若同时查物流和能否退，必须分别取得轨迹和该订单的退款资格，政策原文不能代替资格检查。"
        "物流用 track_shipment；排查未送达时按观察决定是否查仓库 check_fulfillment 、包裹轨迹或签收回执 check_delivery_receipt。"
        "需查哪单不明确时省略订单号，后端会请用户选择，禁止自行猜测。"
        "仅使用当前用户明确给定、选中或从候选列表明确指代的订单号。"
        "金额查询用 shipping_cost，政策用 policy，能否退用 preview；只预览不能提交。"
        "cancel 只关闭待确认操作，不能取消订单。缺少其他必要信息时用 clarify。"
        "用户补充可能回答先前问题，也可能改变目标，优先遵循最新明确请求。",
        {"用户消息": goal, "用户补充": supplement, "选中订单": session["selected"],
         "话题": session["topic"], "最近对话": history, "工具观察": observations})
    if not calls:
        raise ValueError("模型没有返回工具调用")
    # 有些模型会一次提出多个动作。先校验整组，再执行一个；
    # 其余候选交给下一轮根据真实观察重新决定。
    candidates = []
    for call in calls:
        name = call["name"]
        args = TOOLS[name].model_validate(call["args"]).model_dump()
        candidates.append({"name": name, "args": args})
    if len(candidates) == 1:
        return candidates[0]
    if any(item["name"] in {"cancel", "clarify"} for item in candidates):
        return {"name": "clarify", "args": {"question": "请告诉我想先办理哪一项操作。"}}

    for candidate in candidates:
        if candidate["name"] == "finish":
            continue
        # 用户选单后，此前省略的订单号与当前选中的订单可能指同一笔。
        def same_action(observation):
            if observation["tool"] != candidate["name"]:
                return False
            previous = dict(observation["args"])
            current = dict(candidate["args"])
            if "order_id" in current:
                current["order_id"] = current["order_id"] or session["selected"]
                previous["order_id"] = observation["facts"].get("order_id") or previous.get("order_id")
            return current == previous
        if not any(same_action(item) for item in observations):
            return candidate
    if observations and any(item["name"] == "finish" for item in candidates):
        return {"name": "finish", "args": {}}
    raise ValueError("模型未提出新的工具动作")
