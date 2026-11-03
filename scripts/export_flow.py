"""从项目根目录运行 uv run python -m scripts.export_flow，导出带中文标注的流程图。"""

from langchain_core.runnables.graph import CurveStyle, NodeStyles

from constants import PROJECT_ROOT
from service.orchestration.flow import build_flow


def main():
    graph = build_flow(None, None, None).get_graph()
    labels = {
        "__start__": "收到消息", "enter": "识别入口 · enter",
        "reason": "模型决策 · reason", "act": "执行工具 · act",
        "summarize": "汇总回复 · summarize",
        "remember": "记录对话 · remember", "__end__": "本轮结束",
    }
    for key, node in graph.nodes.items():
        graph.nodes[key] = node._replace(name=labels.get(key, node.name))
    conditions = {
        ("enter", "act"): "精确规则", ("enter", "reason"): "自由输入",
        ("act", "reason"): "返回工具观察", ("reason", "act"): "选择下一步",
        ("act", "act"): "选单后执行工具", ("reason", "summarize"): "完成或停止",
    }
    graph.edges = [edge._replace(data=conditions.get((edge.source, edge.target), edge.data))
                   for edge in graph.edges]
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
    diagram += ("\tclassDef react fill:#E9F0FF,stroke:#517BC6,stroke-width:2px,color:#193E78\n"
                "\tclass reason,act react\n")
    (PROJECT_ROOT / "docs/chat-flow.mmd").write_text(diagram)


if __name__ == "__main__":
    main()
