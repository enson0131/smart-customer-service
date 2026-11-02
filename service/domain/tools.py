"""DeepSeek 可选择的客服工具。参数经校验后由 LangGraph 节点执行。"""

from pydantic import BaseModel, ConfigDict, Field


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class orders(ToolInput):
    """查询当前访客的订单列表，或查看指定订单。"""

    order_id: str = Field(default="", pattern=r"^(?:O-[0-9a-f]{16})?$")


class preview(orders):
    """核验退货资格并展示退款确认卡。如果订单有歧义，省略订单号并要求选择。"""

    reason: str = Field(default="", max_length=240)
    choose_order: bool = Field(default=False, description="存在多个可能订单且无法确定时为 true")


class policy(ToolInput):
    """检索政策。根据对话把指代还原为可独立检索的问题。"""

    query: str = Field(min_length=1, max_length=1200)


class progress(ToolInput):
    """查询当前访客的退款申请进度。"""


class cancel(ToolInput):
    """取消当前待确认操作。"""


class clarify(ToolInput):
    """需求不明确时向用户提出一个简短的澄清问题。"""

    question: str = Field(min_length=1, max_length=240)


TOOLS = {tool.__name__: tool for tool in (orders, preview, policy, progress, cancel, clarify)}
