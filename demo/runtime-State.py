"""Runtime State 示例：工具读取和更新状态，并在同一会话中保留计数。

运行：.venv/bin/python demo/runtime-State.py
依赖项目根目录 .env 中的 DEEPSEEK_API_KEY 和 DEEPSEEK_BASE_URL。
"""

import os
from pathlib import Path
from pprint import pprint

from dotenv import load_dotenv
from langchain.agents import AgentState, create_agent
from langchain.chat_models import init_chat_model
from langchain.messages import HumanMessage, ToolMessage
from langchain.tools import ToolRuntime, tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command


MODEL_NAME = "deepseek-flash"


# 1. 继承 AgentState，保留内置的 messages，再增加自定义字段。
class CustomState(AgentState):
    """Agent 的任务状态。"""

    # 沿用截图中的工具名称，但 count 实际记录计数工具执行次数。
    # 一次工具执行通常还会触发模型再次生成回复，因此它不是模型请求总数。
    count: int


# 2. runtime 自动注入；State 按字典读取，通过 Command 提交更新。
@tool
def update_model_call_count(runtime: ToolRuntime[None, CustomState]) -> Command:
    """将当前会话的计数增加一次，并返回最新值。每轮用户请求只调用一次。"""
    count = runtime.state.get("count", 0)
    updated_count = count + 1
    return Command(
        update={
            "count": updated_count,
            # 回复必须关联本次工具调用，让模型知道工具已经执行完毕。
            "messages": [
                ToolMessage(
                    content=f"状态更新成功，当前会话累计计数：{updated_count}",
                    tool_call_id=runtime.tool_call_id,
                )
            ],
        }
    )


def main() -> None:
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
    )

    # 3. 指定自定义 State 和检查点，按 thread_id 保存各会话状态。
    # InMemorySaver 只保存在当前进程内，脚本退出后数据会丢失。
    agent = create_agent(
        model=model,
        tools=[update_model_call_count],
        state_schema=CustomState,
        checkpointer=InMemorySaver(),
        system_prompt=(
            "你是 AI 助手，你需要在每次回答用户前调用工具记录模型的调用次数"
        ),
    )

    config = {"configurable": {"thread_id": "1"}}

    response = agent.invoke(
        # 仅发送本轮新消息；历史消息和 count 由检查点恢复。
        # 不要每轮传 count=0，否则会覆盖之前保存的计数。
        {"messages": [HumanMessage("你好，我是 enson！")]},
        config,
    )
    # print("助手回复：", response["messages"][-1].content)
    # print("State 中的 count：", response.get("count", 0))

    for message in response["messages"]:
       message.pretty_print()

    # get_state 返回 StateSnapshot；实际状态字典保存在 values 属性中。
    snapshot = agent.get_state(config=config)
    pprint(snapshot.values, sort_dicts=False)

if __name__ == "__main__":
    main()


# .venv/bin/python demo/runtime-State.py
