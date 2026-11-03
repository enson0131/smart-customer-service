"""客服工具的参数定义，供 LangChain Agent 绑定和校验。"""

from pydantic import BaseModel, ConfigDict, Field


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class orders(ToolInput):
    """查询当前访客的订单列表，或查看指定订单。"""

    order_id: str = Field(default="", pattern=r"^(?:O-[0-9a-f]{16})?$")


class track_shipment(orders):
    """查询模拟包裹物流轨迹，返回运输中或已签收的记录。"""


class check_fulfillment(orders):
    """查询模拟仓库履约信息，判断是否已经交运。"""


class check_delivery_receipt(orders):
    """核对模拟签收回执，确认记录中是否有签收日期和交付位置。"""


class preview(orders):
    """核验退货资格并展示退款确认卡。如果订单有歧义，省略订单号并要求选择。"""

    reason: str = Field(default="", max_length=240)
    choose_order: bool = Field(default=False, description="存在多个可能订单且无法确定时为 true")


class policy(ToolInput):
    """检索政策。根据对话把指代还原为可独立检索的问题。"""

    query: str = Field(min_length=1, max_length=1200)


class shipping_cost(ToolInput):
    """查询订单实付运费金额；当前演示订单缺少此字段。"""


class progress(ToolInput):
    """查询当前访客的退款申请进度。"""

    reference: str = Field(default="", pattern=r"^(?:R-[a-f0-9]{16})?$")


class cancel(ToolInput):
    """取消当前待确认操作。"""


class clarify(ToolInput):
    """需求不明确时向用户提出一个简短的澄清问题。"""

    question: str = Field(min_length=1, max_length=240)
    choose_order: bool = Field(default=False, description="需要用户从订单列表中选择时为 true")


TOOLS = {tool.__name__: tool for tool in (orders, preview, policy, shipping_cost, progress, cancel, clarify, track_shipment, check_fulfillment, check_delivery_receipt)}
