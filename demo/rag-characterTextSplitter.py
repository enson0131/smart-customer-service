"""使用 CharacterTextSplitter 按字符切分长文本。

运行：uv run python demo/rag-characterTextSplitter.py
本例只演示 RAG 的文本切分步骤，无需模型或 API 密钥。
"""

from langchain_text_splitters import CharacterTextSplitter


doc = """
大型语言模型是近年来人工智能领域最令人瞩目的突破性技术之一。GPT-3、GPT-4、BERT、T5等模型的出现，彻底改变了自然语言处理领域的研究范式。

这些模型基于深度学习架构，通过在海量文本数据上进行预训练，学习到了丰富的语言知识和世界知识。

检索增强生成是近年来兴起的一种重要技术范式，它通过将大型语言模型与外部知识检索系统相结合，有效解决了模型知识更新困难、事实性错误、缺乏专业领域知识等问题。在这种范式中，当用户提出一个问题时，系统首先从外部知识库中检索相关的文档片段，然后将这些片段与用户问题一起作为输入传递给大型语言模型进行答案生成。这种方法不仅提高了模型回答的准确性，还增强了模型的可解释性和可控性。文本分割是构建检索增强生成系统的关键预处理步骤，因为检索的对象通常是文本片段，而分割的质量直接影响后续检索的精确度和召回率。如果分割策略不合理，会带来一系列严重的问题，比如当分割过于粗粒度时检索到的内容可能包含大量无关信息，当分割过于细粒度时则可能丢失关键的上下文信息。

LangChain提供了多种文本分割器实现。CharacterTextSplitter使用指定的单个分隔符对文本进行分割，实现简单高效。RecursiveCharacterTextSplitter则持有一个分隔符优先级列表，能够递归地尝试不同粒度的分隔符。这个分割器因此在处理结构复杂、格式多样的文本时表现更佳，也是LangChain官方推荐的默认分割器。在实际的工程实践中，选择合适的文本分割策略需要综合考虑文本本身的特征和下游任务的具体需求。

通过合理的实验设计和评估，开发者可以找到最适合特定场景的分割策略。
"""


def main() -> None:
    text_splitter = CharacterTextSplitter(
        separator="",  # 空字符串表示可以在任意字符之间切分。
        chunk_size=200,  # 每块最多 200 个字符。
        chunk_overlap=0,  # 块之间不重叠。
    )
    chunks = text_splitter.split_text(doc)

    print(f"原始文本长度：{len(doc)} 字符")
    print(f"切分为 {len(chunks)} 个块：\n")
    for i, chunk in enumerate(chunks):
        print(f"--- Chunk {i + 1} ({len(chunk)} 字符) ---")
        print(chunk)
        print()


if __name__ == "__main__":
    main()
