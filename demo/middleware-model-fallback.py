"""模型回退中间件：主模型调用失败后，自动尝试备用模型。

运行：.venv/bin/python demo/middleware-model-fallback.py
依赖项目根目录 .env 中的 DEEPSEEK_API_KEY 和 DEEPSEEK_BASE_URL。
"""


from constants import DEEPSEEK_MODEL
from constants.deepseek import deepseek_connection
from langchain.agents import create_agent
from langchain.agents.middleware import ModelFallbackMiddleware
from langchain.chat_models import init_chat_model
from langchain.messages import HumanMessage


# 沿用截图中的名称。若接口不支持 deepseek-鸡你太美，将触发备用模型调用。
# 实际使用时，请替换为接口支持的主模型名称。
PRIMARY_MODEL_NAME = "deepseek-鸡你太美-假设的模型"
FALLBACK_MODEL_NAME = DEEPSEEK_MODEL


def main() -> None:

    # 1. 分别初始化模型，确保备用模型也使用项目配置的接口和凭证。
    def build_model(model_name: str):
        return init_chat_model(
            model=model_name,
            model_provider="deepseek",
            **deepseek_connection(require_base_url=True),
            extra_body={"thinking": {"type": "disabled"}},
        )

    primary_model = build_model(PRIMARY_MODEL_NAME)
    fallback_model = build_model(FALLBACK_MODEL_NAME)

    # 2. 中间件只放备用模型；主模型在 create_agent 中指定。
    # 多个备用模型可按顺序追加：ModelFallbackMiddleware(backup_a, backup_b)。
    model_fallback_middleware = ModelFallbackMiddleware(fallback_model)
    agent = create_agent(
        model=primary_model,
        tools=[],
        middleware=[model_fallback_middleware],
        system_prompt="你是一个 AI 助手，请用中文简洁回答用户的问题。",
    )

    # 3. 主模型成功则直接返回，失败才按顺序调用备用模型。
    # 所有模型均失败时，中间件会抛出最后一次异常。
    print(f"主模型：{PRIMARY_MODEL_NAME}，备用模型：{FALLBACK_MODEL_NAME}", flush=True)
    response = agent.invoke({"messages": [HumanMessage("你是谁？")]})
    for message in response["messages"]:
        message.pretty_print()

    # 从响应元数据观察实际返回结果的模型，而非让模型自行描述身份。
    actual_model = response["messages"][-1].response_metadata.get("model_name")
    print("实际响应模型：", actual_model or "接口未返回模型名称")


if __name__ == "__main__":
    main()



# .venv/bin/python demo/middleware-model-fallback.py

# 主模型：deepseek-鸡你太美-假设的模型，备用模型：deepseek-flash
# ================================ Human Message =================================

# 你是谁？
# ================================== Ai Message ==================================

# 我是 AI 助手，由深度求索公司创造的 DeepSeek，使用 DeepSeek 最新版本模型。可以帮你解答问题、处理文本、分析资料等。有什么需要帮忙的？
# 实际响应模型： deepseek-flash