"""jump_to 中间件：限制当前会话的模型调用次数，达到上限后直接结束。

运行：.venv/bin/python demo/middleware-jump.py
依赖项目根目录 .env 中的 DEEPSEEK_API_KEY 和 DEEPSEEK_BASE_URL。
示例上限为 2 次，同一会话的第三次请求直接返回提示，不再调用模型。
"""

import os
from pathlib import Path
from typing import Any, NotRequired

from dotenv import load_dotenv
from langchain.agents import AgentState, create_agent
from langchain.agents.middleware import AgentMiddleware, hook_config
from langchain.chat_models import init_chat_model
from langchain.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.runtime import Runtime


MODEL_NAME = "deepseek-flash"


# 1. 将计数保存在会话 State 中，首次没有这个字段时按 0 处理。
class CustomAgentState(AgentState):
    """记录当前会话中模型成功返回的次数。"""

    model_call_count: NotRequired[int]


# 2. 类形式的中间件，同时实现调用前检查和调用后计数。
class ModelCallLimitMiddleware(AgentMiddleware[CustomAgentState]):
    """每个 thread_id 独立累计计数，达到上限后跳转至 end。"""

    def __init__(self, max_limit: int = 10) -> None:
        super().__init__()
        self.max_limit = max_limit

    def after_model(
        self, state: CustomAgentState, runtime: Runtime
    ) -> dict[str, Any]:
        """模型成功返回后加一；被拦截的请求不会进入这个钩子。"""
        current_count = state.get("model_call_count", 0)
        return {"model_call_count": current_count + 1}

    # 声明允许跳转的目标，框架才会为此钩子建立通往 end 的路由。
    @hook_config(can_jump_to=["end"])
    def before_model(
        self, state: CustomAgentState, runtime: Runtime
    ) -> dict[str, Any] | None:
        current_count = state.get("model_call_count", 0)
        print(f"已完成模型调用次数：{current_count}/{self.max_limit}", flush=True)
        if current_count >= self.max_limit:
            return {
                "jump_to": "end",
                "messages": [
                    AIMessage(
                        content=f"模型调用次数已达到最大限制：{self.max_limit} 次，本次请求已结束。"
                    )
                ],
            }
        return None


def main() -> None:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    model_config = {
        name: os.getenv(name, "").strip()
        for name in ("DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL")
    }
    missing = [name for name, value in model_config.items() if not value]
    if missing:
        raise ValueError(f"请在项目根目录的 .env 中配置：{', '.join(missing)}")

    model = init_chat_model(
        model=MODEL_NAME,
        model_provider="deepseek",
        api_key=model_config["DEEPSEEK_API_KEY"],
        base_url=model_config["DEEPSEEK_BASE_URL"],
        extra_body={"thinking": {"type": "disabled"}},
    )

    # 检查点按 thread_id 保存历史消息和计数，仅在当前进程内保留。
    agent = create_agent(
        model=model,
        tools=[],
        middleware=[ModelCallLimitMiddleware(max_limit=2)],
        checkpointer=InMemorySaver(),
        state_schema=CustomAgentState, # 自定义 State 类型，才能在中间件中使用 model_call_count。
        system_prompt="你是一个 AI 助手，请用中文简洁回答用户的问题。",
    )
    config = {"configurable": {"thread_id": "1"}}

    # 4. 前两轮调用模型，第三轮由中间件添加提示消息并跳转至 end。
    # 每轮只传新消息，不要重复传 model_call_count=0，以免重置计数。
    # 本例没有工具；有工具时，一轮用户请求可能包含多次模型调用。
    for prompt in ("Hello", "讲个笑话吧", "再讲一个笑话吧"):
        print(f"\n用户：{prompt}", flush=True)
        response = agent.invoke(
            {"messages": [HumanMessage(content=prompt)]},
            config=config,
        )
        response["messages"][-1].pretty_print()
        print("当前会话累计模型调用次数：", response.get("model_call_count", 0))


if __name__ == "__main__":
    main()

# .venv/bin/python demo/middleware-jump.py

# 用户：Hello
# 已完成模型调用次数：0/2
# ================================== Ai Message ==================================

# 你好！有什么可以帮你的吗？
# 当前会话累计模型调用次数： 1

# 用户：讲个笑话吧
# 已完成模型调用次数：1/2
# ================================== Ai Message ==================================

# 一个程序员去面试，面试官问：“你最大的缺点是什么？”

# 程序员想了想说：“我太追求完美了。”

# 面试官点点头：“这不算什么大缺点吧？”

# 程序员说：“你说得对，我重新说一个。” 😄
# 当前会话累计模型调用次数： 2

# 用户：再讲一个笑话吧
# 已完成模型调用次数：2/2
# ================================== Ai Message ==================================

# 模型调用次数已达到最大限制：2 次，本次请求已结束。
# 当前会话累计模型调用次数： 2