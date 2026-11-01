"""动态修改模型参数：通过 Context 控制每次请求的思考模式。

运行：.venv/bin/python demo/middleware-modify-model-request.py
依赖项目根目录 .env 中的 DEEPSEEK_API_KEY 和 DEEPSEEK_BASE_URL。
接口需支持 extra_body.thinking.type 的 enabled / disabled 参数。
"""

import os
from collections.abc import Callable
from pathlib import Path

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.agents.middleware import ModelRequest, ModelResponse, wrap_model_call
from langchain.chat_models import init_chat_model
from langchain.messages import HumanMessage
from pydantic.dataclasses import dataclass


MODEL_NAME = "deepseek-flash"


# 1. Context 是应用为本次调用传入的配置，不是用户消息或持久化 State。
@dataclass
class UserContext:
    """用户本次调用是否开启思考模式，默认关闭。"""

    thinking: bool = False


# 2. 每次调用模型前，根据 Context 动态覆盖本次请求的参数。
@wrap_model_call
def dynamic_model_settings(
    request: ModelRequest[UserContext],
    handler: Callable[[ModelRequest[UserContext]], ModelResponse],
) -> ModelResponse:
    """构造新请求并交给 handler，保留原请求和共享模型实例。"""
    context = request.runtime.context or UserContext()
    thinking_type = "enabled" if context.thinking else "disabled"

    # override 会替换整个 model_settings，因此先合并已有配置，
    # 保留其他中间件设置的 temperature、extra_body 等参数。
    model_settings = {
        **request.model_settings,
        "extra_body": {
            **request.model_settings.get("extra_body", {}),
            "thinking": {"type": thinking_type},
        },
    }
    modified_request = request.override(model_settings=model_settings)
    print(f"本次模型请求：thinking.type={thinking_type}", flush=True)
    return handler(modified_request)


def main() -> None:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    model_config = {
        name: os.getenv(name, "").strip()
        for name in ("DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL")
    }
    missing = [name for name, value in model_config.items() if not value]
    if missing:
        raise ValueError(f"请在项目根目录的 .env 中配置：{', '.join(missing)}")

    model = init_chat_model(
        model=MODEL_NAME,
        model_provider="deepseek",
        api_key=model_config["DEEPSEEK_API_KEY"],
        base_url=model_config["DEEPSEEK_BASE_URL"],
        extra_body={"thinking": {"type": "disabled"}},
    )

    # 3. 同一个模型和 Agent，注册中间件并声明 Context 类型。
    agent = create_agent(
        model=model,
        tools=[],
        middleware=[dynamic_model_settings],
        context_schema=UserContext,
        system_prompt="你是一个 AI 助手，请用中文简洁回答用户的问题。",
    )

    # 4. 通过本次调用的 context 切换开关，无需重新创建模型或 Agent。
    # 不设置检查点，两次调用使用独立消息，便于对比同一个问题。
    for thinking in (False, True):
        print(f"\n用户选择：thinking={thinking}", flush=True)
        response = agent.invoke(
            {"messages": [HumanMessage(content="Hello")]},
            context=UserContext(thinking=thinking),
        )
        message = response["messages"][-1]
        message.pretty_print()
        # 此字段是否返回取决于接口实现，观察实际响应，不依赖模型自述。
        print("接口返回思考内容：", bool(message.additional_kwargs.get("reasoning_content")))


if __name__ == "__main__":
    main()


# .venv/bin/python demo/middleware-modify-model-request.py


# 用户选择：thinking=False
# 本次模型请求：thinking.type=disabled
# ================================== Ai Message ==================================

# 你好！有什么可以帮你的吗？
# 接口返回思考内容： False

# 用户选择：thinking=True
# 本次模型请求：thinking.type=enabled
# ================================== Ai Message ==================================

# 你好！有什么可以### 我可以帮你什么吗？
# 接口返回思考内容： False
