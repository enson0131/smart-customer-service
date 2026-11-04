"""PII 中间件示例：邮箱输出脱敏，手机号输入拦截。

运行：.venv/bin/python demo/middleware-pii.py
依赖项目根目录 .env 中的 DEEPSEEK_API_KEY 和 DEEPSEEK_BASE_URL。
示例使用虚构数据；邮箱仅在输出中脱敏，输入仍会传给模型。
"""


from constants import DEEPSEEK_MODEL
from constants.deepseek import deepseek_connection
from langchain.agents import create_agent
from langchain.agents.middleware import PIIMiddleware
from langchain.agents.middleware.pii import PIIDetectionError
from langchain.chat_models import init_chat_model
from langchain.messages import HumanMessage


# 本例检测中国大陆手机号，支持 +86/86 前缀和常见的空格、短横线格式。
# 数字边界避免将更长的数字串中的一部分误判为手机号。
PHONE_PATTERN = r"(?<!\d)(?:\+?86[ -]?)?1[3-9]\d[ -]?\d{4}[ -]?\d{4}(?!\d)"


def create_pii_middleware() -> list[PIIMiddleware]:
    """组合不同敏感信息类型的处理策略。"""
    pii_middleware_email = PIIMiddleware(
        "email",
        strategy="redact",  # 输出邮箱替换为 [REDACTED_EMAIL]，也可尝试 mask。
        apply_to_input=False, # 不检查 UserMessage 中的邮箱，避免误拦截。
        apply_to_output=True, # 检查模型回复中的邮箱，避免泄露敏感信息。
    )
    # phone_number 不是内置类型，需要显式提供 detector。
    pii_middleware_phone = PIIMiddleware(
        "phone_number",
        detector=PHONE_PATTERN,
        strategy="mask",  # 输出的手机号会被替换成 ****
        apply_to_input=True, # 检查 UserMessage 中的手机号，避免泄露敏感信息。
        apply_to_output=False, # 不检查模型回复中的手机号，避免误拦截。
    )
    return [pii_middleware_email, pii_middleware_phone]


def main() -> None:

    model = init_chat_model(
        model=DEEPSEEK_MODEL,
        model_provider="deepseek",
        **deepseek_connection(require_base_url=True),
        extra_body={"thinking": {"type": "disabled"}},
    )


    agent = create_agent(
        model=model,
        tools=[],
        middleware=create_pii_middleware(),
    )


    try:
        response = agent.invoke({"messages": [HumanMessage("我的邮箱是 1234@example.com，手机号是 13688888888。你要记住这些信息，后续要用到，如果记住了，请输出一遍。")]})
    except PIIDetectionError:
        # 拦截是预期行为，不打印可能包含敏感数据的异常详情。
        print("请求已拦截：检测到手机号，请移除手机号后重试。")

    for message in response["messages"]:
       message.pretty_print()

if __name__ == "__main__":
    main()


# .venv/bin/python demo/middleware-pii.py

# ================================ Human Message =================================

# 我的邮箱是 1234@example.com，手机号是 ****8888。你要记住这些信息，后续要用到，如果记住了，请输出一遍。
# ================================== Ai Message ==================================

# 好的，我已经记住了：
# - 邮箱：[REDACTED_EMAIL]
# - 手机号：****8888

# 后续需要时会使用这些信息。
