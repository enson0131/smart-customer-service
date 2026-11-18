"""DeepResearcher：动态规划报告提纲，并行撰写章节，按提纲生成 Markdown。

在项目根目录运行：
.venv/bin/python -m demo.work-flow.orchestrator-worker
"""

import operator
from typing import Annotated, TypedDict

from langchain_core.language_models import BaseChatModel
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Send
from pydantic import BaseModel, Field

from service.model.deepseek import configured_model


# 提纲中的单章写作任务，Worker 根据标题和范围撰写正文。
class Section(BaseModel):
    name: str = Field(min_length=1, description="章节标题")
    description: str = Field(min_length=1, description="本章要回答的问题和写作范围")


# 编排者的结构化输出。模型根据主题决定章节数量，至少规划一章。
class ReportPlan(BaseModel):
    sections: list[Section] = Field(min_length=1, description="按阅读顺序排列的章节")


# 调用工作流时只需提供报告主题。
class ReportInput(TypedDict):
    topic: str


# 整张图共享的状态，继承输入主题，并记录从提纲到成稿的结果。
class ReportState(ReportInput):
    sections: list[Section]  # 编排者规划的提纲，也是最终报告的章节顺序。
    # 每个 Worker 返回 [(章节序号, 正文)]，LangGraph 用 operator.add 拼接这些列表。
    completed_sections: Annotated[list[tuple[int, str]], operator.add]
    final_report: str  # 合成节点按章节序号排列正文后生成的 Markdown 报告。


# Send 为每个 Worker 单独传入报告主题和本次分配的章节任务。
class WorkerState(ReportInput):
    index: int  # 该章在提纲中的位置，从 0 开始，用于合成时恢复顺序。
    section: Section  # 当前 Worker 负责的章节标题和写作范围。


def assign_workers(state: ReportState) -> list[Send]:
    # 条件边读取本次提纲，每章生成一个 Send，交给同一个 worker 节点并行处理。
    # 每次调用都有独立的输入，index 保留该章在提纲中的位置。
    return [
        Send("worker", {"topic": state["topic"], "index": index, "section": section})
        for index, section in enumerate(state["sections"])
    ]


def synthesizer(state: ReportState) -> dict[str, str]:
    parts = [f"# {state['topic']}"]
    # 按派发时的序号排列各章正文，再从原提纲取出对应标题。
    for index, body in sorted(state["completed_sections"]):
        parts.append(f"## {state['sections'][index].name}\n\n{body}")
    return {"final_report": "\n\n".join(parts)}


def build_research_graph(model: BaseChatModel) -> CompiledStateGraph:
    # 让规划模型按 ReportPlan 的结构返回提纲，供条件边逐章派发。
    planner = model.with_structured_output(ReportPlan)

    def orchestrator(state: ReportInput) -> dict[str, list[Section]]:
        # 每份报告先规划一次。模型根据当前主题决定拆成几章，以及每章写什么。
        plan = planner.invoke([
            ("system", "为给定主题规划中文研究报告。根据问题的复杂度决定章节数量，"
             "让每章能独立撰写，范围互补，并按合理的阅读顺序排列。"),
            ("human", state["topic"]),
        ])
        return {"sections": plan.sections}

    def worker(state: WorkerState) -> dict[str, list[tuple[int, str]]]:
        # 每次调用只撰写分配给自己的章节，以整份报告的主题限定上下文。
        section = state["section"]
        response = model.invoke([
            ("system", "撰写指定章节的中文 Markdown 正文，章节标题由系统添加。"
             "区分事实与推测，避免编造数据、来源或引文。"),
            ("human", f"报告主题：{state['topic']}\n章节：{section.name}\n范围：{section.description}"),
        ])
        body = response.text.strip()
        if not body:
            raise ValueError(f"章节「{section.name}」未生成正文")
        # 只返回本章的结果。LangGraph 用 operator.add 将同批结果合入 completed_sections。
        return {"completed_sections": [(state["index"], body)]}

    return (
        StateGraph(ReportState, input_schema=ReportInput)
        .add_node("orchestrator", orchestrator)
        .add_node("worker", worker)
        .add_node("synthesizer", synthesizer)
        .add_edge(START, "orchestrator")
        # 图中只注册一个 worker 节点，运行时的调用次数由 assign_workers 返回的 Send 数量决定。
        .add_conditional_edges("orchestrator", assign_workers, ["worker"])
        # 同一批 worker 全部完成后，LangGraph 在下一步执行一次 synthesizer，生成整份报告。
        .add_edge("worker", "synthesizer")
        .add_edge("synthesizer", END)
        .compile(name="DeepResearcher")
    )


if __name__ == "__main__":
    graph = build_research_graph(configured_model(timeout=120))
    print("[DeepResearcher 工作流 · Mermaid]")
    print(graph.get_graph().draw_mermaid(with_styles=False), flush=True)
    state = graph.invoke({"topic": "创建一份关于 LLM scaling laws 的报告"})
    print(state["final_report"])
