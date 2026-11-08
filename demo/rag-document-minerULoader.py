"""使用 MinerU Open API 的 Flash 模式，将 PDF 解析为 Markdown。

运行：uv run python demo/rag-document-minerULoader.py
默认上传 resources/贵州茅台研报.pdf 教学模拟材料到 MinerU 在线服务。
Flash 模式无需 Token；也可在项目根目录 .env 中配置 MINERU_TOKEN。
SDK 文档：https://github.com/opendatalab/MinerU-Ecosystem/tree/main/sdk/python
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from mineru import MinerU


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    load_dotenv(project_root / ".env")

    # 创建客户端；Flash 轻量级模式无需 Token。
    client = MinerU(token=os.getenv("MINERU_TOKEN"))
    try:
        # flash_extract 快速解析模式 extract 精准解析模式
        result = client.flash_extract(str(project_root / "resources/贵州茅台研报.pdf"))
        print(result.markdown)
    finally:
        client.close()  # 无论解析成功还是报错，都关闭客户端连接。


if __name__ == "__main__":
    main()
