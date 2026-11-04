"""从项目根目录运行 uv run python -m scripts.export_flow，导出带中文标注的流程图。"""

from langchain.chat_models import init_chat_model
from langchain_core.runnables.graph import CurveStyle, NodeStyles

from constants import PROJECT_ROOT
from service.orchestration.flow import build_flow


def main():
    graph = build_flow(None, None, init_chat_model()).get_graph(xray=True)
    labels = {"__start__": "收到消息", "__end__": "本轮结束", "intent": "意图识别",
              "direct": "执行确定指令", "respond": "组装客服答复", "remember": "保存对话",
              "agent:model": "模型决策", "agent:tools": "执行工具 / 等待补充",
              "agent:continue_tool_batch.before_model": "before_model：续派剩余工具",
              "agent:prepare_tool_batch.after_model": "after_model：保存新批次",
              "agent:ModelCallLimitMiddleware.before_model": "检查模型调用次数",
              "agent:ModelCallLimitMiddleware.after_model": "记录模型调用次数"}
    for key, label in labels.items():
        graph.nodes[key] = graph.nodes[key]._replace(name=label)
    endpoint = "fill:#EDF2F5,stroke:#ADBCC5,color:#344957"
    diagram = graph.draw_mermaid(
        curve_style=CurveStyle.BASIS,
        node_colors=NodeStyles(default="fill:#F2F8F6,stroke:#82A99C,color:#204A40",
                               first=endpoint, last=endpoint),
        frontmatter_config={"config": {"theme": "base", "themeVariables": {
            "fontFamily": "system-ui, sans-serif", "fontSize": "16px",
            "lineColor": "#69818E", "edgeLabelBackground": "#FFFFFF",
        }, "flowchart": {"htmlLabels": False, "nodeSpacing": 35, "rankSpacing": 46,
                         "diagramPadding": 24}}},
    )
    # SVG 文本标签无需 HTML 空格实体。
    diagram = diagram.replace("&nbsp;", "")
    (PROJECT_ROOT / "docs/chat-flow.mmd").write_text(diagram)


if __name__ == "__main__":
    main()
