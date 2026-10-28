"""Runtime Context 示例：通过运行时上下文查询当前租户下的用户课程。

运行：.venv/bin/python demo/runtime-Context.py
依赖项目根目录 .env 中的 DEEPSEEK_API_KEY 和 DEEPSEEK_BASE_URL。
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain.messages import HumanMessage
from langchain.tools import ToolRuntime, tool


MODEL_NAME = "deepseek-flash"

# 1. 模拟多租户数据库：不同学校可以存在相同的 user_id。
USER_DATABASE = {
    "school_a": {
        "u001": {"name": "虎哥", "course": "LangChain 开发指南"},
        "u002": {"name": "小明", "course": "Java开发入门"},
    },
    "school_b": {
        "u001": {"name": "涛哥", "course": "Python 入门"},
        "u002": {"name": "阿伟", "course": "VibeCoding 实战"},
    },
}


# 2. 定义 Context Schema，frozen=True 防止运行时修改身份信息。
@dataclass(frozen=True)
class UserContext:
    """由应用传入的当前登录用户身份，一次调用内保持不变。"""

    user_id: str
    tenant_id: str


# 3. runtime 由 LangChain 自动注入，不会暴露为模型的工具入参。
@tool
def get_current_user_profile(runtime: ToolRuntime[UserContext]) -> str:
    """查询当前登录用户的姓名和正在学习的课程。"""
    ctx = runtime.context
    if ctx is None:
        return "缺少用户上下文，无法查询当前登录用户的资料。"

    # 必须同时使用 tenant_id 和 user_id，避免查询到其他租户的数据。
    profile = USER_DATABASE.get(ctx.tenant_id, {}).get(ctx.user_id)
    if profile is None:
        return "当前租户下未找到该用户的资料。"

    return f"姓名：{profile['name']}，课程：{profile['course']}"


def main() -> None:
    # 使用绝对路径，从其他目录启动脚本也能加载项目配置。
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    config = {
        name: os.getenv(name, "").strip()
        for name in ("DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL")
    }
    missing = [name for name, value in config.items() if not value]
    if missing:
        raise ValueError(f"请在项目根目录的 .env 中配置：{', '.join(missing)}")

    model = init_chat_model(
        model=MODEL_NAME,
        model_provider="deepseek",
        api_key=config["DEEPSEEK_API_KEY"],
        base_url=config["DEEPSEEK_BASE_URL"],
        extra_body={"thinking": {"type": "disabled"}},
        timeout=30,
        max_retries=1,
    )

    # 4. 创建 Agent 时指定 Context 类型。
    agent = create_agent(
        model=model,
        tools=[get_current_user_profile],
        context_schema=UserContext,
        system_prompt=(
            "你是课程平台助手。查询用户资料或课程时必须调用工具，"
            "根据工具结果用中文回答，不要编造信息。"
        ),
    )

    # 5. 同一个 Agent、同一个问题，通过不同 Context 获取各自的数据。
    # 实际应用中，身份应来自服务端认证结果。
    for tenant_id in ("school_a", "school_b"):
        context = UserContext(user_id="u001", tenant_id=tenant_id)
        print(f"\n当前上下文：{context}", flush=True)
        response = agent.invoke(
            {"messages": [HumanMessage("帮我查询我正在学习的课程")]},
            context=context,
        )
        print("助手回复：", response["messages"][-1].content)


if __name__ == "__main__":
    main()



# 当前上下文：UserContext(user_id='u001', tenant_id='school_a')
# 助手回复： 你好，虎哥！你当前正在学习的课程是**《LangChain 开发指南》**。需要我帮你查询其他信息吗？

# 当前上下文：UserContext(user_id='u001', tenant_id='school_b')
# 助手回复： 你当前登录的用户是**涛哥**，正在学习的课程是：**Python 入门**。