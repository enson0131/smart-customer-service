"""通过 stdio 连接 Time MCP 服务，让 Agent 查询当前时间。

运行：uv run python demo/mcp-stdio.py 或者 .venv/bin/python demo/mcp-stdio.py
依赖：项目依赖及 uvx（随 uv 安装），首次运行需联网下载 mcp-server-time。
模型配置：项目根目录 .env 中的 DEEPSEEK_API_KEY 和 DEEPSEEK_BASE_URL。
"""

import asyncio
import shutil
import sys
from pathlib import Path

# 支持直接运行脚本，也支持从其他工作目录启动。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from constants import DEEPSEEK_MODEL
from constants.deepseek import deepseek_connection
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain.messages import HumanMessage
from langchain_mcp_adapters.client import MultiServerMCPClient


async def main() -> None:
    connection = deepseek_connection(require_base_url=True)

    # 1. 客户端通过子进程的标准输入/输出与 MCP 服务通信，无需启动 HTTP 服务。
    client = MultiServerMCPClient(
        {
            "time": {
                "transport": "stdio",
                "command": "uvx",
                "args": [
                    "mcp-server-time",
                    "--local-timezone=Asia/Shanghai",
                ],
            }
        }
    )

    # 2. 异步发现 MCP 工具，并转换成 LangChain 可用的工具。
    # get_tools() 自动管理会话；后续工具调用也会自动建立和关闭会话。
    print("正在连接 Time MCP 服务并获取工具……", flush=True)
    tools = await client.get_tools()
    for tool in tools:
        print(tool.name)
        print(tool.description)
        print("-" * 40, flush=True)

    # 3. 沿用项目统一的模型名称与连接配置，关闭思考模式。
    model = init_chat_model(
        model=DEEPSEEK_MODEL,
        model_provider="deepseek",
        **connection,
        extra_body={"thinking": {"type": "disabled"}},
        timeout=30,
        max_retries=1,
    )
    agent = create_agent(
        model=model,
        tools=tools,
        system_prompt=(
            "你是时间助手。查询当前时间时必须调用 MCP 工具，以工具结果为准。"
            "用户未指定时区时使用 Asia/Shanghai，用中文简洁回答，并注明时区。"
        ),
    )

    # 4. 必须使用异步调用，以便 Agent 执行 MCP 的异步工具。
    response = await agent.ainvoke({"messages": [HumanMessage("现在几点了？")]})
    for message in response["messages"]:
        message.pretty_print()


if __name__ == "__main__":
    asyncio.run(main())
