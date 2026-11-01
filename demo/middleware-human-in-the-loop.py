"""Human-in-the-loop 示例：邮件发送前暂停，人工审核后恢复执行。

运行：.venv/bin/python demo/middleware-human-in-the-loop.py
依赖项目根目录 .env 中的 DEEPSEEK_API_KEY 和 DEEPSEEK_BASE_URL。
收件箱和发送工具均为模拟实现，不会发送真实邮件。

审核时输入 approve / reject / edit（也支持 a / r / e）。
InMemorySaver 仅保存当前进程内的状态，退出后不能恢复本次审核。
"""

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langchain.agents.middleware.human_in_the_loop import ActionRequest, Decision
from langchain.chat_models import init_chat_model
from langchain.messages import HumanMessage
from langchain.tools import ToolRuntime, tool
from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command


MODEL_NAME = "deepseek-flash"

# 1. 模拟收件箱，沿用截图中的邮件内容。
emails = [
    {
        "subject": "周末见个面？",
        "content": "嗨 峰哥，\n我下周会去城里，不知道我们有没有机会一起喝杯咖啡？\n\n祝好，简",
        "from": "jane@test.cn",
        "status": "unread",
    },
    {
        "subject": "周五会议",
        "content": "嗨 峰哥，\n非常抱歉，我周五的会议无法准时参加了，能不能重新安排个时间？\n\n祝好，小李",
        "from": "lixiaolong@test.cn",
        "status": "checked",
    },
]


@tool
def check_inbox(runtime: ToolRuntime) -> str:
    """查看收件箱中的邮件。"""
    # runtime 由框架注入，不需要模型提供这个参数。
    return json.dumps(emails, ensure_ascii=False)


@tool
def send_email(to: str, subject: str, body: str, runtime: ToolRuntime) -> str:
    """模拟发送回复邮件，返回模拟发送结果。"""
    return f"[模拟发送成功] 收件人：{to}\n主题：{subject}\n正文：{body}"


def create_hitl_agent(model: BaseChatModel):
    """为发送工具添加人工审核，并通过检查点保存暂停的会话。"""
    # 2. 查看邮件无需审核；发送前必须由人工 approve / reject / edit。
    human_in_loop_middleware = HumanInTheLoopMiddleware(
        interrupt_on={
            "check_inbox": False,
            "send_email": {
                "description": "请确认邮件内容",
                "allowed_decisions": ["approve", "reject", "edit"],
            },
        },
    )

    return create_agent(
        model=model,
        tools=[check_inbox, send_email],
        middleware=[human_in_loop_middleware],
        checkpointer=InMemorySaver(),
        system_prompt=(
            "你是一个邮件助手，请用中文回答"
        ),
    )


def review_action(action: ActionRequest) -> Decision:
    """展示实际待执行的参数，收集一项审核决定。"""
    print(f"\n待审核工具：{action['name']}")
    print(action.get("description", "请审核工具调用"))
    print(json.dumps(action["args"], ensure_ascii=False, indent=2))

    aliases = {"a": "approve", "r": "reject", "e": "edit"}
    while True:
        choice = input("审核决定 [a=批准 / r=拒绝 / e=编辑后发送]：").strip().lower()
        choice = aliases.get(choice, choice)
        if choice == "approve":
            return {"type": "approve"}
        if choice == "reject":
            reason = input("拒绝原因（可要求重新拟稿，留空则取消发送）：").strip()
            return {"type": "reject", "message": reason or "取消发送这封邮件，不要重试。"}
        if choice == "edit":
            # edited_action 必须包含工具名和完整参数，不能只传改动的字段。
            # 本示例固定工具名，允许逐项修改收件人、主题和正文。
            args = dict(action["args"])
            print("逐项编辑，直接回车保留原值；正文中的字面量 \\n 会转换为换行。")
            for field, label in (("to", "收件人"), ("subject", "主题"), ("body", "正文")):
                value = input(f"{label}：").strip()
                if value:
                    args[field] = value.replace("\\n", "\n") if field == "body" else value
            print("将执行以下编辑后的邮件：")
            print(json.dumps(args, ensure_ascii=False, indent=2))
            if input("确认编辑并发送？[y/N]：").strip().lower() == "y":
                return {
                    "type": "edit",
                    "edited_action": {"name": action["name"], "args": args},
                }
            print("未提交编辑，请重新选择审核决定。")
            continue
        print("请输入 approve / reject / edit，或 a / r / e。")


def main() -> None:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    settings = {
        name: os.getenv(name, "").strip()
        for name in ("DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL")
    }
    missing = [name for name, value in settings.items() if not value]
    if missing:
        raise ValueError(f"请在项目根目录的 .env 中配置：{', '.join(missing)}")

    model = init_chat_model(
        model=MODEL_NAME,
        model_provider="deepseek",
        api_key=settings["DEEPSEEK_API_KEY"],
        base_url=settings["DEEPSEEK_BASE_URL"],
        extra_body={"thinking": {"type": "disabled"}},
    )
    agent_with_hitl = create_hitl_agent(model)

    # 3. 初次调用和恢复必须使用相同的 thread_id、Agent 和检查点。
    config = {"configurable": {"thread_id": "1"}}
    print("第一轮：查看邮件（无需人工审核）。", flush=True)
    response = agent_with_hitl.invoke(
        {"messages": [HumanMessage("帮我查看邮件")]}, config=config
    )
    for message in response["messages"]:
        message.pretty_print()
    printed_count = len(response["messages"])

    print("\n第二轮：帮我回复 Jane，很高兴她能来，问问她具体见面时间。", flush=True)
    response = agent_with_hitl.invoke(
        {"messages": [HumanMessage("帮我回复 Jane，很高兴她能来，问问她具体见面时间")]},
        config=config,
    )

    # 4. invoke 返回 __interrupt__ 表示工具尚未执行，需要提交审核结果。
    # 拒绝后可能产生新草稿；用 while 确保新的发送请求仍逐次接受审核。
    while True:
        for message in response["messages"][printed_count:]: # [printed_count:] 是列表切片，表示：跳过之前打印过的消息，只打印新增消息。
            message.pretty_print()
        printed_count = len(response["messages"])
        if not response.get("__interrupt__"):
            break

        # batched 模式下，这个 Agent 每轮产生一个包含所有待审调用的中断。
        request = response["__interrupt__"][0].value
        try:
            # 每个 action 对应一个决定，数量和顺序必须一致。
            decisions = [review_action(action) for action in request["action_requests"]]
        except (EOFError, KeyboardInterrupt):
            print("\n审核已退出，待审核的邮件未发送；内存检查点会随进程退出而丢失。")
            return

        # approve: {"type": "approve"}
        # reject: {"type": "reject", "message": "语气太书面了，Jane 是我的女朋友！请重新拟稿。"}
        # edit: {"type": "edit", "edited_action": {"name": "send_email", "args": {...}}}
        response = agent_with_hitl.invoke(
            Command(resume={"decisions": decisions}),
            config=config,
        )


if __name__ == "__main__":
    main()


# .venv/bin/python demo/middleware-human-in-the-loop.py
# 第一轮：查看邮件（无需人工审核）。
# ================================ Human Message =================================

# 帮我查看邮件
# ================================== Ai Message ==================================
# Tool Calls:
#   check_inbox (call_00_fT8mIHS7WAmGLrEh5PXu5181)
#  Call ID: call_00_fT8mIHS7WAmGLrEh5PXu5181
#   Args:
# ================================= Tool Message =================================
# Name: check_inbox

# [{"subject": "周末见个面？", "content": "嗨 峰哥，\n我下周会去城里，不知道我们有没有机会一起喝杯咖啡？\n\n祝好，简", "from": "jane@test.cn", "status": "unread"}, {"subject": "周五会议", "content": "嗨 峰哥，\n非常抱歉，我周五的会议无法准时参加了，能不能重新安排个时间？\n\n祝好，小李", "from": "lixiaolong@test.cn", "status": "checked"}]
# ================================== Ai Message ==================================

# 已为你查看收件箱，共有 2 封邮件：

# **1. 周末见个面？**（未读）
# - 发件人：jane@test.cn
# - 内容：简说她下周会去城里，想问问有没有机会一起喝杯咖啡。

# **2. 周五会议**（已读）
# - 发件人：lixiaolong@test.cn
# - 内容：小李表示抱歉，周五的会议无法准时参加，希望能重新安排个时间。

# 需要我帮你回复其中哪一封吗？比如跟简约个咖啡时间，或者跟小李重新协调会议时间。

# 第二轮：帮我回复 Jane，很高兴她能来，问问她具体见面时间。
# ================================ Human Message =================================

# 帮我回复 Jane，很高兴她能来，问问她具体见面时间
# ================================== Ai Message ==================================
# Tool Calls:
#   send_email (call_00_fXhNF40MDZlFupsHr6hX5555)
#  Call ID: call_00_fXhNF40MDZlFupsHr6hX5555
#   Args:
#     to: jane@test.cn
#     subject: Re: 周末见个面？
#     body: 嗨 简，

# 很高兴听到你下周会来城里，我也很期待能和你见面喝杯咖啡！

# 你方便的话，能告诉我具体哪天、大概什么时间比较合适吗？我这边好安排一下。

# 祝好，
# 峰哥

# 待审核工具：send_email
# 请确认邮件内容
# {
#   "to": "jane@test.cn",
#   "subject": "Re: 周末见个面？",
#   "body": "嗨 简，\n\n很高兴听到你下周会来城里，我也很期待能和你见面喝杯咖啡！\n\n你方便的话，能告诉我具体哪天、大概什么时间比较合适吗？我这边好安排一下。\n\n祝好，\n峰哥"
# }
# 审核决定 [a=批准 / r=拒绝 / e=编辑后发送]：r
# 拒绝原因（可要求重新拟稿，留空则取消发送）：jane 是我的女朋友， 回复要甜一点
# ================================= Tool Message =================================
# Name: send_email

# User rejected the tool call for `send_email` with reason: jane 是我的女朋友，回复要甜一点
# ================================== Ai Message ==================================

# 明白，那我换个甜一点的版本重新发～
# Tool Calls:
#   send_email (call_00_dCsQSv7bVtFxsx0nZhoP6286)
#  Call ID: call_00_dCsQSv7bVtFxsx0nZhoP6286
#   Args:
#     to: jane@test.cn
#     subject: Re: 周末见个面？
#     body: 亲爱的简，

# 看到你的邮件我特别开心！你能来城里，我简直迫不及待想见到你了，一杯咖啡哪够，我请客，想吃什么都行～

# 快告诉我你具体哪天到、什么时候有空吧，我把时间都留给你，一秒都不想错过。☕️❤️

# 超级想你的，
# 峰哥

# 待审核工具：send_email
# 请确认邮件内容
# {
#   "to": "jane@test.cn",
#   "subject": "Re: 周末见个面？",
#   "body": "亲爱的简，\n\n看到你的邮件我特别开心！你能来城里，我简直迫不及待想见到你了，一杯咖啡哪够，我请客，想吃什么都行～\n\n快告诉我你具体哪天到、什么时候有空吧，我把时间都留给你，一秒都不想错过。☕️❤️\n\n超级想你的，\n峰哥"
# }
# 审核决定 [a=批准 / r=拒绝 / e=编辑后发送]：a
# ================================= Tool Message =================================
# Name: send_email

# [模拟发送成功] 收件人：jane@test.cn
# 主题：Re: 周末见个面？
# 正文：亲爱的简，

# 看到你的邮件我特别开心！你能来城里，我简直迫不及待想见到你了，一杯咖啡哪够，我请客，想吃什么都行～

# 快告诉我你具体哪天到、什么时候有空吧，我把时间都留给你，一秒都不想错过。☕️❤️

# 超级想你的，
# 峰哥
# ================================== Ai Message ==================================

# 已经帮你把甜一点的版本发给简了～

# 邮件大意：
# - 表达看到她要来城里特别开心、迫不及待想见面
# - 主动说咖啡请客，还想请她吃点什么
# - 请她告知具体到城里的日期和有空的时间，并说时间都留给她

# 需要我再帮你跟进小李那封关于会议改期的邮件吗？