"""使用 DashScopeEmbeddings 和内存向量库演示文档增删与检索。

运行：uv run python demo/rag-vectorStore.py
请先在项目根目录 .env 中配置 DASHSCOPE_API_KEY。
向量库仅保存在内存中，退出程序后数据消失。
"""

from pathlib import Path

from dotenv import load_dotenv
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_text_splitters import MarkdownHeaderTextSplitter


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    load_dotenv(project_root / ".env")

    # 1. 读取 Markdown，按三级标题切分，保留正文中的标题和标题元数据。
    source_path = project_root / "resources/评估.md"
    text = source_path.read_text(encoding="utf-8")
    markdown_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=[("#", "H1"), ("##", "H2"), ("###", "H3")],
        strip_headers=False, # 保留正文中的标题，标题仍保存在 metadata 中。
    )
    documents = markdown_splitter.split_text(text)
    for i, document in enumerate(documents, start=1):
        document.id = f"doc_{i}"
    print(f"切分为 {len(documents)} 个文档块")

    # 2. 初始化向量模型和向量库，批量向量化文档并入库。
    # DashScopeEmbeddings 自动读取环境变量 DASHSCOPE_API_KEY。
    embeddings = DashScopeEmbeddings(model="text-embedding-v4")
    vector_store = InMemoryVectorStore(embeddings)
    ids = vector_store.add_documents(documents)
    print(f"已添加文档：{ids}")

    query = "论语中教育的目的是什么"

    # 3. 普通检索，返回 list[Document]。
    print(f"\n普通检索：{query}")
    results = vector_store.similarity_search(query=query, k=2)
    for document in results:
        print(f"=============={document.id}==============")
        print(document.model_dump_json(indent=2))

    # 4. 带分数检索，返回 list[tuple[Document, float]]。
    # InMemoryVectorStore 返回余弦相似度，分数越大越相似。
    print("\n带分数检索：")
    scored_results = vector_store.similarity_search_with_score(query=query, k=2)
    for document, score in scored_results:
        print(f"=============={document.id} 相似度：{score:.6f}==============")
        print(document.model_dump_json(indent=2))

    # 5. 按 ID 删除，并通过原生 get_by_ids 验证结果。
    vector_store.delete(ids=["doc_1"])
    print(f"\n删除 doc_1 后，按 ID 查询结果：{vector_store.get_by_ids(['doc_1'])}")


if __name__ == "__main__":
    main()


# uv run python demo/rag-vectorStore.py
# /Users/user/Desktop/workspace/smart-customer-service/demo/rag-vectorStore.py:11: DeprecationWarning: `langchain-community` is being sunset and is no longer actively maintained. See https://github.com/langchain-ai/langchain-community/issues/674 for details and migration guidance toward standalone integration packages.
#   from langchain_community.embeddings import DashScopeEmbeddings
# 切分为 7 个文档块
# 已添加文档：['doc_1', 'doc_2', 'doc_3', 'doc_4', 'doc_5', 'doc_6', 'doc_7']

# 普通检索：论语中教育的目的是什么
# ==============doc_3==============
# {
#   "id": "doc_3",
#   "metadata": {
#     "H1": "第一章 教育概述",
#     "H2": "第一节 中外教育家及其教育思想",
#     "H3": "（三）孔子及《论语》主要思想"
#   },
#   "page_content": "### （三）孔子及《论语》主要思想\n- 教育作用：庶、富、教；性相近，习相远。\n- 教育对象：“有教无类”，教育民主思想。\n- 教育目的：以完善人格为教育的首要目的，培养士和君子。\n- 教学内容：文、行、忠、义。\n- 教学过程：学、思、习、行。\n- 教学原则：因材施教、启发诱导、学思结合、谦虚笃实。\n- 教师观：其身正，不令而行；其身不正，虽令不从。",
#   "type": "Document"
# }
# ==============doc_4==============
# {
#   "id": "doc_4",
#   "metadata": {
#     "H1": "第一章 教育概述",
#     "H2": "第一节 中外教育家及其教育思想",
#     "H3": "（四）孟子主要思想"
#   },
#   "page_content": "### （四）孟子主要思想\n- 人性论：人性本善，人先天具有仁、义、礼、智四个“善端”。\n- 教育作用：发扬善端，培养道德完人，得天下英才而教育之。\n- 教学原则：循序渐进，专心有恒。",
#   "type": "Document"
# }

# 带分数检索：
# ==============doc_3 相似度：0.705091==============
# {
#   "id": "doc_3",
#   "metadata": {
#     "H1": "第一章 教育概述",
#     "H2": "第一节 中外教育家及其教育思想",
#     "H3": "（三）孔子及《论语》主要思想"
#   },
#   "page_content": "### （三）孔子及《论语》主要思想\n- 教育作用：庶、富、教；性相近，习相远。\n- 教育对象：“有教无类”，教育民主思想。\n- 教育目的：以完善人格为教育的首要目的，培养士和君子。\n- 教学内容：文、行、忠、义。\n- 教学过程：学、思、习、行。\n- 教学原则：因材施教、启发诱导、学思结合、谦虚笃实。\n- 教师观：其身正，不令而行；其身不正，虽令不从。",
#   "type": "Document"
# }
# ==============doc_4 相似度：0.551624==============
# {
#   "id": "doc_4",
#   "metadata": {
#     "H1": "第一章 教育概述",
#     "H2": "第一节 中外教育家及其教育思想",
#     "H3": "（四）孟子主要思想"
#   },
#   "page_content": "### （四）孟子主要思想\n- 人性论：人性本善，人先天具有仁、义、礼、智四个“善端”。\n- 教育作用：发扬善端，培养道德完人，得天下英才而教育之。\n- 教学原则：循序渐进，专心有恒。",
#   "type": "Document"
# }

# 删除 doc_1 后，按 ID 查询结果：[]