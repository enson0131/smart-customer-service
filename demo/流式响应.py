"""使用 Agent 流式输出模型回复。"""


from constants import DEEPSEEK_MODEL
from constants.deepseek import deepseek_connection
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain.messages import HumanMessage



# 从项目根目录读取凭证和接口地址，模型名称直接在代码中配置。

# 1. 初始化模型，关闭思考模式。
model = init_chat_model(
    model=DEEPSEEK_MODEL,
    model_provider="deepseek",
    **deepseek_connection(require_base_url=True),
    extra_body={"thinking": {"type": "disabled"}},
)

# 2. 初始化 Agent。
agent = create_agent(
    model=model,
    tools=[],
    system_prompt="你扮演小团团，用小团团的口吻来回答问题。",
)


if __name__ == "__main__":
    # 3. 流式调用：逐块接收文本，立即打印。
    stream = agent.stream_events(
        {"messages": [HumanMessage("你好啊~")]},
        version="v3",
    )

    for message in stream.messages:
        for token in message.text:
            print(token, end="", flush=True)
    print()


# 运行：.venv/bin/python demo/流式响应.py
