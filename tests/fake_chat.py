"""测试模型也走 create_agent 的标准工具调用和消息协议。"""

import json
from uuid import uuid4

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult


class TestChatModel(BaseChatModel):
    responder: object

    @property
    def _llm_type(self):
        return "test"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, **kwargs):
        result = self.responder(messages)
        if isinstance(result, list):
            result = AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": uuid4().hex}
                                                        for name, args in result])
        else:
            result = AIMessage(content=result)
        return ChatResult(generations=[ChatGeneration(message=result)])


def goal_and_tools(messages):
    goal = next(m.content for m in reversed(messages) if isinstance(m, HumanMessage))
    tools = [m for m in messages if isinstance(m, ToolMessage)]
    if tools and json.loads(tools[-1].content)["status"] == "user_input":
        goal = json.loads(tools[-1].content)["facts"]["message"]
        tools = []
    return goal, tools
