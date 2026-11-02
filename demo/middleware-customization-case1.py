"""自定义中间件：通过 after_model 钩子累计当前会话的模型调用次数。

运行：.venv/bin/python demo/middleware-customs-case1.py
依赖项目根目录 .env 中的 DEEPSEEK_API_KEY 和 DEEPSEEK_BASE_URL。
"""

from typing import Any, NotRequired

from constants import DEEPSEEK_MODEL
from constants.deepseek import deepseek_connection
from langchain.agents import AgentState, create_agent
from langchain.agents.middleware import after_model
from langchain.chat_models import init_chat_model
from langchain.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.runtime import Runtime




# 1. 扩展 AgentState，保留内置 messages 字段，增加会话计数。
class CustomAgentState(AgentState):
    """计数首次可以省略，由中间件从 0 开始累加。"""

    model_call_count: NotRequired[int]


# 2. 装饰器把函数转换为中间件，并将自定义字段加入 Agent 的状态。
@after_model(state_schema=CustomAgentState)
def increment_counter(
    state: CustomAgentState, runtime: Runtime
) -> dict[str, Any]:
    """每次模型成功返回后加一，通过返回字典提交状态更新。"""
    current_count = state.get("model_call_count", 0)
    return {"model_call_count": current_count + 1}


def main() -> None:

    model = init_chat_model(
        model=DEEPSEEK_MODEL,
        model_provider="deepseek",
        **deepseek_connection(require_base_url=True),
        extra_body={"thinking": {"type": "disabled"}},
    )

    # 3. 注册中间件；检查点按 thread_id 保存历史消息和计数。
    # InMemorySaver 仅在当前进程内保留状态，脚本退出后数据会丢失。
    agent = create_agent(
        model=model,
        tools=[],
        middleware=[increment_counter],
        checkpointer=InMemorySaver(),
        system_prompt="你是一个 AI 助手，请用中文简洁回答用户的问题。",
    )
    config = {"configurable": {"thread_id": "1"}}

    # 4. 同一会话连续调用两轮，计数依次为 1、2。
    # 每轮只传新消息；不要重复传 model_call_count=0，以免覆盖已有计数。
    # 本例没有工具；有工具时，一轮用户请求可能触发多次模型调用。
    for prompt in ("你好", "讲个笑话吧"):
        print(f"\n用户：{prompt}", flush=True)
        response = agent.invoke(
            {"messages": [HumanMessage(content=prompt)]},
            config=config,
        )
        response["messages"][-1].pretty_print()
        print("当前会话累计模型调用次数：", response["model_call_count"])


if __name__ == "__main__":
    main()
