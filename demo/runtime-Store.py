"""Runtime Store 示例：按租户和用户保存跨会话的学习偏好。

运行：.venv/bin/python demo/runtime-Store.py
依赖项目根目录 .env 中的 DEEPSEEK_API_KEY 和 DEEPSEEK_BASE_URL。
InMemoryStore 可在当前进程中跨会话共享数据，进程退出后数据会丢失。
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain.messages import HumanMessage
from langchain.tools import ToolRuntime, tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore


MODEL_NAME = "deepseek-flash"
PREFERENCE_KEY = "learning_preferences"


@dataclass(frozen=True)
class UserContext:
    """由服务端认证结果提供身份，不让模型选择要访问的用户。"""

    user_id: str
    tenant_id: str


# 1. namespace 不包含 thread_id，因此同一用户的不同会话共享偏好。
def preference_namespace(ctx: UserContext) -> tuple[str, ...]:
    return ("heima_platform", ctx.tenant_id, ctx.user_id)


# 2. 工具通过 runtime.store 读写，runtime 参数由框架自动注入。
@tool
def save_learning_preference(
    preference_name: str,
    preference_value: str,
    runtime: ToolRuntime[UserContext],
) -> str:
    """保存当前用户的一项长期学习偏好，同名偏好会更新，其他偏好会保留。"""
    if runtime.context is None or runtime.store is None:
        return "缺少用户上下文或 Store，无法保存偏好。"
    preference_name = preference_name.strip()
    preference_value = preference_value.strip()
    if not preference_name or not preference_value:
        return "偏好名称和值不能为空。"

    namespace = preference_namespace(runtime.context)
    print(f"保存偏好：{namespace}，{preference_name}={preference_value}", flush=True)

    item = runtime.store.get(namespace, PREFERENCE_KEY)
    # 复制已有字典，合并后显式 put，不直接修改读出的对象。
    preferences = dict(item.value) if item else {}
    preferences[preference_name] = preference_value
    runtime.store.put(namespace, PREFERENCE_KEY, preferences)
    return f"已保存偏好：{preference_name}={preference_value}"


@tool
def get_learning_preferences(runtime: ToolRuntime[UserContext]) -> str:
    """读取当前用户已保存的所有长期学习偏好，可跨会话查询。"""
    if runtime.context is None or runtime.store is None:
        return "缺少用户上下文或 Store，无法读取偏好。"
    item = runtime.store.get(preference_namespace(runtime.context), PREFERENCE_KEY)
    if item is None or not item.value:
        return "当前用户尚未保存学习偏好。"
    return json.dumps(item.value, ensure_ascii=False)


def main() -> None:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    config = {
        name: os.getenv(name, "").strip()
        for name in ("DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL")
    }
    missing = [name for name, value in config.items() if not value]
    if missing:
        raise ValueError(f"请在项目根目录的 .env 中配置：{', '.join(missing)}")

    model = init_chat_model(
        model=MODEL_NAME,
        model_provider="deepseek",
        api_key=config["DEEPSEEK_API_KEY"],
        base_url=config["DEEPSEEK_BASE_URL"],
        extra_body={"thinking": {"type": "disabled"}},
        timeout=30,
        max_retries=1,
    )

    # 3. Store 保存用户偏好；checkpointer 按 thread_id 保存会话消息。
    # 同一个 Store 实例必须复用，不能在每轮调用时重新创建。
    store = InMemoryStore()
    agent = create_agent(
        model=model,
        tools=[save_learning_preference, get_learning_preferences],
        context_schema=UserContext,
        checkpointer=InMemorySaver(),
        store=store,
        system_prompt=(
            "你是课程平台助手。用户要求记住偏好时调用保存工具，"
            "查询偏好或讲解代码前调用读取工具。以工具结果为准，"
            "不要编造偏好，也不要在用户只要求查询时写入偏好。用中文简洁回答。"
        ),
    )

    # 4. 会话 A 保存，会话 B 读取；其他租户和用户应查不到该偏好。
    # 每个会话绑定一个身份，避免将历史消息带给其他用户。
    examples = [
        ("store-demo-a", UserContext("u001", "school_a"),
         "请记住我的学习偏好：内容顺序偏好是先代码，再原理。"),
        ("store-demo-b", UserContext("u001", "school_a"),
         "请查询我保存过的学习偏好。"),
        ("store-demo-c", UserContext("u001", "school_b"),
         "请查询我保存过的学习偏好。"),
        ("store-demo-d", UserContext("u002", "school_a"),
         "请查询我保存过的学习偏好。"),
    ]
    for thread_id, context, question in examples:
        print(f"\n会话：{thread_id}，用户上下文：{context}", flush=True)
        response = agent.invoke(
            {"messages": [HumanMessage(question)]},
            config={"configurable": {"thread_id": thread_id}},
            context=context,
        )
        print("助手回复：", response["messages"][-1].content)
        item = store.get(preference_namespace(context), PREFERENCE_KEY)
        print("Store 中的偏好：", item.value if item else {})


if __name__ == "__main__":
    main()

#  执行 .venv/bin/python demo/runtime-Store.py


# 会话：store-demo-a，用户上下文：UserContext(user_id='u001', tenant_id='school_a')
# 保存偏好：('heima_platform', 'school_a', 'u001')，内容顺序偏好=先代码，再原理
# 助手回复： 已记住：**内容顺序偏好 = 先代码，再原理**。以后讲解会先给代码示例，再解释原理。
# Store 中的偏好： {'内容顺序偏好': '先代码，再原理'}

# 会话：store-demo-b，用户上下文：UserContext(user_id='u001', tenant_id='school_a')
# 助手回复： 你当前保存的学习偏好：

# - **内容顺序偏好**：先代码，再原理

# 如需修改或新增偏好，告诉我即可。
# Store 中的偏好： {'内容顺序偏好': '先代码，再原理'}

# 会话：store-demo-c，用户上下文：UserContext(user_id='u001', tenant_id='school_b')
# 助手回复： 你目前还没有保存过任何学习偏好。需要我帮你记录一些吗？比如偏好的语言、讲解详略程度、示例风格等。
# Store 中的偏好： {}

# 会话：store-demo-d，用户上下文：UserContext(user_id='u002', tenant_id='school_a')
# 助手回复： 你目前还没有保存过任何学习偏好。需要我记录一些吗？比如讲解代码的风格、常用语言等。
# Store 中的偏好： {}