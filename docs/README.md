# 售后客服系统文档

## LangGraph 执行流程

![售后客服 ReAct 执行流程，包含工具调用循环、任务暂停和回复汇总](chat-flow.svg)

agent 子图内的 model 与 tools 构成 ReAct 循环：模型选择工具，工具把结果交回模型。需要用户补充时，执行工具节点通过 interrupt() 等待，下一次请求校验聊天归属后，使用相同 chat_id 作为 thread_id，通过 Command 恢复该节点。visitor_id 负责身份和订单归属，一个访客可以拥有多个独立聊天。

[查看 Mermaid 源文件](chat-flow.mmd) · [节点说明与重新生成命令](../README.md#langgraph-执行流程)
