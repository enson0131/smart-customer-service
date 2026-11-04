"""通过 HTTP 和 stdio 同时连接 MCP 服务，让 Agent 查询航班。

运行：uv run python demo/mcp-http.py 或 .venv/bin/python demo/mcp-http.py
依赖：项目依赖及 uvx；首次运行需联网下载 mcp-server-time。
模型配置：项目根目录 .env 中的 DEEPSEEK_API_KEY 和 DEEPSEEK_BASE_URL。
Kiwi MCP 地址：https://mcp.kiwi.com，运行时需要能访问该远程服务。
"""

import asyncio
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

    # 1. 同一个客户端连接两个服务：远程 HTTP 航班服务和本地 stdio 时间服务。
    client = MultiServerMCPClient(
        {
            "kiwi-com-flight-search": {
                "transport": "http",
                "url": "https://mcp.kiwi.com",
                "timeout": 30,
                "sse_read_timeout": 60,
            },
            "time": {
                "transport": "stdio",
                "command": "uvx",
                "args": [
                    "mcp-server-time",
                    "--local-timezone=Asia/Shanghai",
                ],
            },
        }
    )

    # 2. 异步获取两个服务的工具；客户端自动管理发现和调用时的会话。
    print("正在连接 Kiwi 和 Time MCP 服务并获取工具……", flush=True)
    tools = await client.get_tools()
    # 本示例只查询信息，不向 Kiwi 开发者发送反馈。
    tools = [tool for tool in tools if tool.name != "feedback-to-devs"]
    for tool in tools:
        print(tool.name)
        print(tool.description)
        print("-" * 40, flush=True)

    # 3. 沿用项目的 DeepSeek 配置，关闭思考模式。
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
            "你是一名旅行 Agent，帮助用户查询并比较航班，不要追问用户。"
            "遇到今天、下周四等相对日期，必须先调用时间工具获取 Asia/Shanghai "
            "的当前日期，再计算出行日期；下周指下一个周一开始的一周。"
            "用户未指定时，按单程、1 名成人、经济舱查询，优先直飞。"
            "用户使用中文时，Kiwi 工具的 locale 必须使用 zh-cn，不能使用 zh。"
            "必须调用航班搜索工具，以实际结果为准，用中文说明出行日期、"
            "起降机场、当地起降时间、价格及币种，并提供工具返回的预订链接。"
            "工具报错或没有结果时如实说明，不要编造航班和价格。"
        ),
    )

    # 4. 异步执行：先获取当前日期，再查询下周四北京飞杭州的航班。
    response = await agent.ainvoke(
        {"messages": [HumanMessage("查一下下周四从北京飞杭州的航班。")]},
        config={"recursion_limit": 16},
    )
    for message in response["messages"]:
        message.pretty_print()


if __name__ == "__main__":
    asyncio.run(main())
