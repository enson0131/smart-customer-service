"""读取本地知识库并检索原文片段；回答生成由编排层负责。"""

import math
import re
from collections import Counter
from pathlib import Path


# BM25 参数：控制词频增长的收益，以及段落长度对得分的影响。
BM25_K1 = 1.2
BM25_B = 0.75

# 本项目的筛选规则，不是 BM25 算法本身的要求。
MIN_QUERY_COVERAGE = 0.22
MAX_RESULTS = 2
MIN_RELATIVE_SCORE = 0.65


def tokens(text):
    """英文和数字保留整词，连续中文按相邻两个字切分。

    例如："退货运费 ABC123" → ["退货", "货运", "运费", "abc123"]。
    这不是按中文词义分词，而是不依赖词典的简单切分方式。
    """
    result = []
    normalized_text = text.lower()
    words = re.findall(r"[\u3400-\u9fff]+|[a-z0-9]+", normalized_text)
    for word in words:
        if word.isascii() or len(word) == 1:
            result.append(word)
            continue

        for index in range(len(word) - 1):
            two_characters = word[index:index + 2]
            result.append(two_characters)

    return result


class Knowledge:
    def __init__(self, directory):
        # 每项包含：供页面引用的原文、供检索打分的词频。
        self.chunks = self._load_chunks(directory)

        # 每个词出现于多少个片段。同一片段出现多次，也只计一次。
        self.document_frequencies = Counter()
        total_token_count = 0
        for _, token_counts in self.chunks:
            self.document_frequencies.update(token_counts.keys())
            total_token_count += token_counts.total()

        if self.chunks:
            self.average_chunk_length = total_token_count / len(self.chunks)
        else:
            self.average_chunk_length = 0

    def _load_chunks(self, directory):
        """按空行和 Markdown 标题切段，让正文沿用最近的标题。"""
        chunks = []
        for path in sorted(Path(directory).rglob("*")):
            if path.suffix.lower() not in {".txt", ".md"}:
                continue

            title = path.stem
            content = path.read_text().strip()
            # 第一部分匹配空行；第二部分在行首标题之前切分，但保留标题。
            parts = re.split(r"\n\s*\n|(?=^#{1,6} )", content, flags=re.M)
            for part in parts:
                if part.startswith("#"):
                    heading, _, part = part.partition("\n")
                    title = heading.strip("# ")

                if not part.strip():
                    continue

                source = {
                    "title": f"{path.stem} · {title}",
                    "excerpt": part.strip(),
                }
                # 标题也参与匹配，例如正文没写“运费”，标题仍可能包含它。
                searchable_text = title + " " + part
                token_counts = Counter(tokens(searchable_text))
                chunks.append((source, token_counts))

        return chunks

    def _score_chunk(self, matched_terms, token_counts):
        """将每个命中词的 BM25 得分相加，得到片段的相关性分数。"""
        chunk_count = len(self.chunks)
        chunk_length = token_counts.total()
        length_ratio = chunk_length / self.average_chunk_length
        length_normalization = 1 - BM25_B + BM25_B * length_ratio

        score = 0
        for term in matched_terms:
            # 一个词出现在越少的片段中，区分能力越强，权重越高。
            matching_chunk_count = self.document_frequencies[term]
            rarity_ratio = (chunk_count - matching_chunk_count + 0.5) / (matching_chunk_count + 0.5)
            inverse_document_frequency = math.log1p(rarity_ratio)

            # 出现次数越多，得分越高，但增长逐渐放缓；同时校正片段长度。
            term_frequency = token_counts[term]
            weighted_frequency = inverse_document_frequency * term_frequency * (BM25_K1 + 1)
            denominator = term_frequency + BM25_K1 * length_normalization
            term_score = weighted_frequency / denominator
            score += term_score

        return score

    def search(self, query):
        """返回相关片段的标题和原文，最多两项；没有匹配时返回空列表。"""
        # 问题中的重复词只参与一次检索。
        query_terms = set(tokens(query))
        if not query_terms:
            return []

        ranked_chunks = []
        for source, token_counts in self.chunks:
            matched_terms = query_terms.intersection(token_counts.keys())
            if not matched_terms:
                continue

            # 问题拆成 10 个不同的词时，至少命中 3 个才能达到 22%。
            query_coverage = len(matched_terms) / len(query_terms)
            if query_coverage < MIN_QUERY_COVERAGE:
                continue

            score = self._score_chunk(matched_terms, token_counts)
            ranked_chunks.append((score, source))

        if not ranked_chunks:
            return []

        ranked_chunks.sort(key=lambda item: item[0], reverse=True)
        best_score = ranked_chunks[0][0]
        minimum_score = best_score * MIN_RELATIVE_SCORE

        results = []
        for score, source in ranked_chunks[:MAX_RESULTS]:
            if score >= minimum_score:
                results.append(source)

        return results
