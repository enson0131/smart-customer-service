"""使用 DashScope 向量化文本，并比较余弦相似度。

运行：uv run python demo/rag-dashScopeEmbeddings.py
请先在项目根目录 .env 中配置 DASHSCOPE_API_KEY。
"""

from pathlib import Path

import numpy as np
from dotenv import load_dotenv
from langchain_community.embeddings import DashScopeEmbeddings


def cosine_similarity(vec1: list[float], vec2: list[float]) -> float:
    """计算两个非零向量的余弦相似度。"""
    norm_product = np.linalg.norm(vec1) * np.linalg.norm(vec2)
    if norm_product == 0:
        raise ValueError("零向量无法计算余弦相似度")
    return float(np.dot(vec1, vec2) / norm_product)


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    load_dotenv(project_root / ".env")

    # 自动从环境变量读取 DASHSCOPE_API_KEY。
    embeddings = DashScopeEmbeddings(model="text-embedding-v4")

    # 向量化单条文本。
    text = "我爱上班"
    vector = embeddings.embed_query(text)

    # 批量向量化。
    texts = ["我要躺平", "我爱工作", "拒绝加班"]
    vectors = embeddings.embed_documents(texts)

    print(f"原始文本：{text}")
    print("==============衡量相似度==============")
    for candidate, candidate_vector in zip(texts, vectors, strict=True):
        similarity = cosine_similarity(vector, candidate_vector)
        print(f"{candidate}: {similarity:.6f}")


if __name__ == "__main__":
    main()

# 原始文本：我爱上班
# ==============衡量相似度==============
# 我要躺平: 0.401201
# 我爱工作: 0.822756
# 拒绝加班: 0.416889