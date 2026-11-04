import { writeFile } from "node:fs/promises";
import { FakeToolCallingModel } from "langchain";
import { createSupportAgent } from "../workers/orchestration/chat";
import { Store } from "../workers/storage/store";

// 导出真实 createAgent 图结构，无需模型密钥或数据库连接。
const agent = createSupportAgent(
  new Store({} as D1Database),
  { id: "diagram", selected: null, ticket: null, reason: null },
  [],
  new FakeToolCallingModel({ toolCalls: [[]] }),
);
const graph = await agent.graph.getGraphAsync();
await writeFile("docs/chat-flow.mmd", graph.drawMermaid());
console.log(
  JSON.stringify(
    { nodes: Object.keys(graph.nodes), edges: graph.edges },
    null,
    2,
  ),
);
// SVG 的节点和连线同样来自原生图，仅在这里设置排版和中文说明。
const names = Object.keys(graph.nodes);
const labels: Record<string, string> = {
  __start__: "开始",
  model_request: "模型与中间件",
  tools: "执行工具 · interrupt / resume",
  __end__: "结束",
};
const y = (name: string) => 100 + names.indexOf(name) * 105;
const escape = (value: string) =>
  value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll('"', "&quot;");
const lines = graph.edges
  .map((edge) => {
    const from = y(edge.source),
      to = y(edge.target);
    const skip =
      Math.abs(names.indexOf(edge.source) - names.indexOf(edge.target)) > 1;
    const path =
      to < from
        ? `M190 ${from + 22} C100 ${from + 22} 100 ${to + 22} 190 ${to + 22}`
        : skip
          ? `M490 ${from + 22} C580 ${from + 22} 580 ${to + 22} 490 ${to + 22}`
          : `M340 ${from + 48} L340 ${to}`;
    return `<path d="${path}" fill="none" stroke="#6880a7" stroke-width="2" ${edge.conditional ? 'stroke-dasharray="6 4"' : ""} marker-end="url(#arrow)"/>`;
  })
  .join("\n");
const boxes = names
  .map(
    (name) =>
      `<g><rect x="190" y="${y(name)}" width="300" height="48" rx="12" fill="#fff" stroke="#c4d4ea"/><text x="340" y="${y(name) + 21}" text-anchor="middle" font-size="15">${escape(labels[name] || name)}</text><text x="340" y="${y(name) + 38}" text-anchor="middle" font-size="11" fill="#657b96">${escape(name)}</text></g>`,
  )
  .join("\n");
await writeFile(
  "docs/chat-flow.svg",
  `<svg xmlns="http://www.w3.org/2000/svg" width="680" height="550" viewBox="0 0 680 550" role="img" aria-label="从 LangGraph 导出的客服 Agent 流程"><defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10" fill="#6880a7"/></marker></defs><rect width="680" height="550" rx="18" fill="#f3f6fb"/><g font-family="PingFang SC,Microsoft YaHei,sans-serif" fill="#203958"><text x="40" y="45" font-size="25" font-weight="600">原生 createAgent · LangGraph</text><text x="40" y="73" font-size="14">实线为普通边，虚线为条件边</text>${lines}${boxes}<text x="40" y="505" font-size="14">工具缺少订单时中断，下一请求通过同一线程恢复。</text><text x="40" y="530" font-size="14">本地 SQLite 与线上 D1 保存同一结构的检查点。</text></g></svg>\n`,
);
