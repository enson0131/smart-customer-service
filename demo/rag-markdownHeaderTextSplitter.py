"""使用 MarkdownHeaderTextSplitter 按三级标题切分 Markdown。

运行：uv run python demo/rag-markdownHeaderTextSplitter.py
读取 resources/评估.md，输出包含正文和标题元数据的 Document JSON。
本例无需模型或 API 密钥。
"""

from pathlib import Path

from langchain_text_splitters import MarkdownHeaderTextSplitter


def main() -> None:
    source_path = Path(__file__).resolve().parents[1] / "resources/评估.md"
    doc = source_path.read_text(encoding="utf-8")

    markdown_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=[
            ("#", " H1"),
            ("##", "H2"),
            ("###", "H3"),
        ],
        strip_headers=True,  # 从正文中移除标题，标题仍保存在 metadata 中。
    )
    # split_text 接收字符串，返回 list[Document]，而非字符串列表。
    chunks = markdown_splitter.split_text(doc)

    print(f"切分为 {len(chunks)} 个块：\n")
    for chunk in chunks:
        print(chunk.model_dump_json(indent=2)) # model_dump_json() 用来把对象转换成 JSON 字符串。
        print()


if __name__ == "__main__":
    main()
