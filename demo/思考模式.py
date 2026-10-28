"""从项目根目录的 .env 加载凭证和接口地址并初始化 DeepSeek 模型。"""

import os
from pathlib import Path

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model


MODEL_NAME = "deepseek-flash"

# 使用绝对路径，确保从其他目录运行脚本时也能找到 .env。
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

config = {
    name: os.getenv(name, "").strip()
    for name in ("DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL")
}
missing = [name for name, value in config.items() if not value]
if missing:
    raise ValueError(f"请在项目根目录的 .env 中配置：{', '.join(missing)}")

# 初始化模型，并按照截图开启思考模式。
model = init_chat_model(
    model=MODEL_NAME,
    model_provider="deepseek",
    api_key=config["DEEPSEEK_API_KEY"],
    base_url=config["DEEPSEEK_BASE_URL"],
    extra_body={"thinking": {"type": "disabled"}}, # 思考模式 enabled/ 非思考模式 disabled
)


if __name__ == "__main__":
    print(f"模型初始化成功：{MODEL_NAME}")
    response = model.invoke("你好")
    print("模型回复：", response)


# source .venv/bin/activate
# python demo/思考模式.py

# 思考模式的回复，存在 reasoning_content 字段，表示模型在生成最终回复前的思考过程。
# 模型回复： content='你好！很高兴见到你 😊\n\n有什么我可以帮你的吗？无论是回答问题、写作、翻译、编程，还是聊天解闷，我都很乐意。' additional_kwargs={'refusal': None, 'reasoning_content': 'The user just said "你好" (Hello) in Chinese. I should respond warmly in Chinese and offer help.'} response_metadata={'token_usage': {'completion_tokens': 56, 'prompt_tokens': 31, 'total_tokens': 87, 'completion_tokens_details': {'accepted_prediction_tokens': None, 'audio_tokens': None, 'reasoning_tokens': 23, 'rejected_prediction_tokens': None, 'text_tokens': None}, 'prompt_tokens_details': {'audio_tokens': None, 'cache_write_tokens': None, 'cached_tokens': 0, 'image_tokens': None, 'text_tokens': None}, 'prompt_cache_hit_tokens': 0, 'prompt_cache_miss_tokens': 31}, 'model_provider': 'deepseek', 'model_name': 'deepseek-flash', 'system_fingerprint': 'bc19ba97cbe016479903222bb1578db6', 'id': '1c64cbbd-453e-474a-b151-522945a1b1d5', 'finish_reason': 'stop', 'logprobs': None} id='lc_run--01a180f1-8eca-7777-a9db-13b49c91406a-0' tool_calls=[] invalid_tool_calls=[] usage_metadata={'input_tokens': 31, 'output_tokens': 56, 'total_tokens': 87, 'input_token_details': {'cache_read': 0}, 'output_token_details': {'reasoning': 23}}


# 非思考模式的回复，reasoning_content 字段为 None，表示模型没有思考过程。
# 模型回复： content='你好！很高兴见到你，有什么我可以帮忙的吗？' additional_kwargs={'refusal': None} response_metadata={'token_usage': {'completion_tokens': 11, 'prompt_tokens': 5, 'total_tokens': 16, 'completion_tokens_details': None, 'prompt_tokens_details': {'audio_tokens': None, 'cache_write_tokens': None, 'cached_tokens': 0, 'image_tokens': None, 'text_tokens': None}, 'prompt_cache_hit_tokens': 0, 'prompt_cache_miss_tokens': 5}, 'model_provider': 'deepseek', 'model_name': 'deepseek-flash', 'system_fingerprint': 'bc19ba97cbe016479903222bb1578db6', 'id': '83b7804f-3f1d-44bc-b31f-78956d0b357b', 'finish_reason': 'stop', 'logprobs': None} id='lc_run--01a180f3-4cb7-722c-9037-e91400081127-0' tool_calls=[] invalid_tool_calls=[] usage_metadata={'input_tokens': 5, 'output_tokens': 11, 'total_tokens': 16, 'input_token_details': {'cache_read': 0}, 'output_token_details': {}}
