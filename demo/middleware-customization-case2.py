"""环绕中间件：模型调用失败时自动重试，最多尝试 3 次。

运行：.venv/bin/python demo/middleware-customization-case2.py
依赖项目根目录 .env 中的 DEEPSEEK_API_KEY 和 DEEPSEEK_BASE_URL。
将 MODEL_NAME 改为接口不支持的 deepseek-xxx，可观察重试及最终异常。
"""

import os
from pathlib import Path
from typing import Callable

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.agents.middleware import ModelRequest, ModelResponse, wrap_model_call
from langchain.chat_models import init_chat_model
from langchain.messages import HumanMessage


MODEL_NAME = "deepseek-xxx"
MAX_ATTEMPTS = 3  # 首次调用 + 最多 2 次重试，总共最多尝试 3 次。


# 1. 环绕钩子接收请求和 handler；调用 handler(request) 才会执行模型请求。
@wrap_model_call
def retry_model(
    request: ModelRequest,
    handler: Callable[[ModelRequest], ModelResponse],
) -> ModelResponse:
    """成功立即返回，失败重新调用 handler，最后一次失败则向外抛出异常。"""
    # 前两次失败后继续重试；本例沿用截图，捕获普通 Exception。
    for attempt in range(1, MAX_ATTEMPTS):
        try:
            return handler(request)
        except Exception as exc:
            print(
                f"第 {attempt}/{MAX_ATTEMPTS} 次模型调用失败：{exc}\n"
                f"准备第 {attempt + 1}/{MAX_ATTEMPTS} 次尝试……",
                flush=True,
            )

    # 最后一次不再捕获，保留模型原始异常及调用栈；不会返回 None。
    return handler(request)


def main() -> None:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    model_config = {
        name: os.getenv(name, "").strip()
        for name in ("DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL")
    }
    missing = [name for name, value in model_config.items() if not value]
    if missing:
        raise ValueError(f"请在项目根目录的 .env 中配置：{', '.join(missing)}")

    # 2. 关闭模型客户端内置重试，使重试次数完全由自定义中间件控制。
    model = init_chat_model(
        model=MODEL_NAME,
        model_provider="deepseek",
        api_key=model_config["DEEPSEEK_API_KEY"],
        base_url=model_config["DEEPSEEK_BASE_URL"],
        max_retries=0,
        extra_body={"thinking": {"type": "disabled"}},
    )

    # 3. 将装饰器生成的中间件注册到 Agent。
    agent = create_agent(
        model=model,
        tools=[],
        middleware=[retry_model],
        system_prompt="你是一个 AI 助手，请用中文简洁回答用户的问题。",
    )

    # 4. 触发模型调用：成功则打印回复，连续失败 3 次则抛出最后一次异常。
    print(f"当前模型：{MODEL_NAME}，最多尝试 {MAX_ATTEMPTS} 次", flush=True)
    response = agent.invoke({"messages": [HumanMessage(content="Hello")]})
    for message in response["messages"]:
        message.pretty_print()


if __name__ == "__main__":
    main()
