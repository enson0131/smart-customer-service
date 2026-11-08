"""使用 PyPDFLoader 加载 PDF，查看 Document 的元数据和正文。

运行：uv run python demo/rag-document-pyPdfLoader.py
读取项目根目录下的 resources/贵州茅台研报.pdf 教学模拟材料。
本例只演示 RAG 的文档加载步骤，无需模型或 API 密钥。
"""

from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader


def main() -> None:
    # 使用 LangChain 原生加载器，返回 list[Document]。
    loader = PyPDFLoader(
        file_path=str(Path(__file__).resolve().parents[1] / "resources/贵州茅台研报.pdf"),
        mode="page",  # single：整份 PDF；page：按 PDF 分页。
    )
    docs = loader.load()
    print(f"文档数量：{len(docs)}")

    # 每个 Document 都包含 page_content 和 metadata 两个属性。
    for i, doc in enumerate(docs):
        print(f"==============Doc_{i}=================")
        print("metadata =", doc.metadata)
        print("page_content =", doc.page_content)


if __name__ == "__main__":
    main()
