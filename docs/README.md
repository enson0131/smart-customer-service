# 售后客服系统文档

## LangGraph 执行流程

![售后客服 ReAct 执行流程，包含工具调用循环、任务暂停和回复汇总](chat-flow.svg)

TypeScript `createAgent` 图内的 `model_request` 与 `tools` 构成 ReAct 循环。模型选择工具，工具把结果交回模型。需要选单时，工具通过 `interrupt()` 等待，下一次请求通过同一线程的 `Command(resume)` 恢复。

运行 `npm run graph` 可从原生 LangGraph 节点和连线重新生成 Mermaid 与 SVG。入口精确规则和退款确认接口在 Agent 图外处理。

[查看 Mermaid 源文件](chat-flow.mmd) · [节点说明与重新生成命令](../README.md#langgraph-执行流程)
