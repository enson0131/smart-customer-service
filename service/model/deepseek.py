from langchain.chat_models import init_chat_model

from constants import DEEPSEEK_MODEL, MODEL_MAX_RETRIES, MODEL_PROVIDER, MODEL_TIMEOUT_SECONDS
from constants.deepseek import deepseek_connection


def configured_model():
    return init_chat_model(
        model=DEEPSEEK_MODEL,
        model_provider=MODEL_PROVIDER,
        **deepseek_connection(),
        extra_body={"thinking": {"type": "disabled"}},
        timeout=MODEL_TIMEOUT_SECONDS,
        max_retries=MODEL_MAX_RETRIES,
    )
