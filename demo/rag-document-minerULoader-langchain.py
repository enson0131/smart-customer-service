"""使用 LangChain MinerULoader 加载 PDF，并保存 Markdown 正文。

运行：uv run python demo/rag-document-minerULoader-langchain.py
默认上传 resources/贵州茅台研报.pdf 教学模拟材料到 MinerU 在线服务。
Flash 模式无需 Token；也可在项目根目录 .env 中配置 MINERU_TOKEN。
输出文件：resources/output/r1.md。
文档：https://github.com/opendatalab/MinerU-Ecosystem/tree/main/langchain_mineru
"""

from pathlib import Path

from dotenv import load_dotenv
from langchain_mineru import MinerULoader


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    load_dotenv(project_root / ".env")

    loader = MinerULoader(
        source=str(project_root / "resources/贵州茅台研报.pdf"),
        mode="flash",  # flash：轻量级模式；precision：精准模式，需 MINERU_TOKEN。
    )
    # 返回 LangChain 的 list[Document]，正文为 Markdown。
    docs = loader.load()
    print(docs[0].metadata)

    output_path = project_root / "resources/output/r1.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(docs[0].page_content, encoding="utf-8")
    print(f"Markdown 已保存：{output_path}")


if __name__ == "__main__":
    main()
