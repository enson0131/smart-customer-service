"""使用 Agent 流式输出模型回复。"""

import os
from pathlib import Path

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain.messages import HumanMessage


MODEL_NAME = "deepseek-flash"

# 从项目根目录读取凭证和接口地址，模型名称直接在代码中配置。
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

config = {
    name: os.getenv(name, "").strip()
    for name in ("DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL")
}
missing = [name for name, value in config.items() if not value]
if missing:
    raise ValueError(f"请在项目根目录的 .env 中配置：{', '.join(missing)}")

# 1. 初始化模型，关闭思考模式。
model = init_chat_model(
    model=MODEL_NAME,
    model_provider="deepseek",
    api_key=config["DEEPSEEK_API_KEY"],
    base_url=config["DEEPSEEK_BASE_URL"],
    extra_body={"thinking": {"type": "disabled"}},
)

# 2. 初始化 Agent。
agent = create_agent(
    model=model,
    tools=[],
    system_prompt="你扮演小团团，用小团团的口吻来回答问题。",
)


if __name__ == "__main__":
    # 3. 流式调用：逐块接收文本，立即打印。
    stream = agent.stream_events(
        {"messages": [HumanMessage("你好啊~")]},
        version="v3",
    )

    for message in stream.messages:
        for token in message.text:
            print(token, end="", flush=True)
    print()


# 运行：.venv/bin/python demo/流式响应.py
