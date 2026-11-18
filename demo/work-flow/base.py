"""Prompt Chaining：生成笑话 → 检查质量 → 润色 → 加梗。

在项目根目录运行：PYTHONPATH=. .venv/bin/python demo/work-flow/base.py
模型连接沿用项目根目录 .env 中的 DeepSeek 配置。
"""

from typing import Literal, NotRequired, TypedDict

from langchain_core.language_models import BaseChatModel
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from service.model.deepseek import configured_model


class JokeState(TypedDict):
    topic: str
    joke: NotRequired[str]
    improved_joke: NotRequired[str]
    final_joke: NotRequired[str]


def build_chaining_graph(model: BaseChatModel) -> CompiledStateGraph:
    """构建流程；注入模型以便独立运行和测试。"""

    def generate_joke(state: JokeState) -> dict[str, str]:
        """生成初稿，同时作为质量检查通过时的最终结果。"""
        joke = model.invoke(f"Write a short joke about {state['topic']}").text
        return {"joke": joke, "final_joke": joke}

    def check_punchline(state: JokeState) -> Literal["Pass", "Fail"]:
        """检查笑点和双关语，未明确通过时进入改进流程。"""
        verdict = model.invoke(
            "Check if the joke has a punchline and wordplay. "
            "Return only 'Pass' or 'Fail'.\n"
            f"Joke: ```{state['joke']}```"
        ).text
        return "Pass" if verdict.strip().casefold() == "pass" else "Fail"

    def improve_joke(state: JokeState) -> dict[str, str]:
        """增加双关语。"""
        joke = model.invoke(
            f"Make this joke funnier by adding wordplay: {state['joke']}"
        ).text
        return {"improved_joke": joke}

    def polish_joke(state: JokeState) -> dict[str, str]:
        """为改进后的笑话增加反转。"""
        joke = model.invoke(
            f"Add a surprising twist to this joke: {state['improved_joke']}"
        ).text
        return {"final_joke": joke}

    return (
        StateGraph(JokeState)
        .add_node("generate_joke", generate_joke)
        .add_node("improve_joke", improve_joke)
        .add_node("polish_joke", polish_joke)
        .add_edge(START, "generate_joke")
        .add_conditional_edges(
            "generate_joke",
            check_punchline,
            {"Pass": END, "Fail": "improve_joke"},
        )
        .add_edge("improve_joke", "polish_joke")
        .add_edge("polish_joke", END)
        .compile()
    )


def main() -> None:
    graph = build_chaining_graph(configured_model())
    topic = "大树"
    print(f"=== 话题「{topic}」 ===\n")
    result = graph.invoke({"topic": topic})
    print(f"最终笑话:\n{result['final_joke']}")


if __name__ == "__main__":
    main()
