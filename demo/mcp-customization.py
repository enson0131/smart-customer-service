"""连接自定义 Math MCP 服务，让 Agent 通过工具回答数学问题。

运行：uv run python demo/mcp-customization.py 或 .venv/bin/python demo/mcp-customization.py
服务端：同目录的 math_mcp_server.py，由客户端自动启动和关闭。
模型配置：项目根目录 .env 中的 DEEPSEEK_API_KEY 和 DEEPSEEK_BASE_URL。
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

    # 1. 自定义服务是本地 Python 文件，用当前解释器启动，确保依赖环境一致。
    client = MultiServerMCPClient(
        {
            "math": {
                "transport": "stdio",
                "command": sys.executable,
                "args": [str(Path(__file__).with_name("math_mcp_server.py").resolve())],
            }
        }
    )

    # 2. 获取服务注册的工具；会话和子进程生命周期由客户端自动管理。
    print("正在连接自定义 Math MCP 服务并获取工具……", flush=True)
    tools = await client.get_tools()
    for tool in tools:
        print(tool.name)
        print(tool.description)
        print("-" * 40, flush=True)

    # 3. 沿用项目 DeepSeek 配置，创建必须通过工具计算的 Agent。
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
            "你是数学助手，必须使用 MCP 工具进行每一步数学运算。"
            "平方根之和指分别开平方后相加，请先调用 square_root，"
            "再将结果交给 add，不要自行心算。"
            "以工具返回结果为准，用中文简洁回答，近似值请注明。"
            "工具报错时如实说明，不要编造计算结果。"
        ),
    )

    # 4. 异步调用 Agent：计算 sqrt(467) + sqrt(529)，打印完整工具调用过程。
    response = await agent.ainvoke(
        {"messages": [HumanMessage("467和529的平方根之和是多少？")]},
        config={"recursion_limit": 16},
    )
    for message in response["messages"]:
        message.pretty_print()


if __name__ == "__main__":
    asyncio.run(main())
