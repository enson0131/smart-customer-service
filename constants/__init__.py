"""服务端配置默认值与业务常量。密钥仅在运行时从环境读取。"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = PROJECT_ROOT / "service" / "storage" / "schema.sql"

MODEL_PROVIDER = "deepseek"
DEEPSEEK_MODEL = "deepseek-flash"
DEFAULT_MODEL_BASE_URL = "https://api.deepseek.com"
MODEL_TIMEOUT_SECONDS = 8
MODEL_MAX_RETRIES = 0

RETURN_WINDOW_DAYS = 7
REFUND_STATUS = "已受理（模拟）"
VISITOR_COOKIE = "visitor"
VISITOR_COOKIE_MAX_AGE = 30 * 86400
MAX_MESSAGE_LENGTH = 1200
