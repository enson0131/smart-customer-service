import os

from dotenv import load_dotenv

from . import DEFAULT_MODEL_BASE_URL, PROJECT_ROOT


def deepseek_connection(*, require_base_url: bool = False) -> dict[str, str]:
    """读取连接参数，进程环境优先于项目 .env。"""
    load_dotenv(PROJECT_ROOT / ".env")
    key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    url = os.getenv("DEEPSEEK_BASE_URL", "").strip()
    if not key:
        raise RuntimeError("请在项目 .env 或环境变量中配置 DEEPSEEK_API_KEY。")
    if require_base_url and not url:
        raise ValueError("请在项目 .env 或环境变量中配置 DEEPSEEK_BASE_URL。")
    return {"api_key": key, "base_url": url or DEFAULT_MODEL_BASE_URL}
