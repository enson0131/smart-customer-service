from dataclasses import dataclass, field


@dataclass
class Outcome:
    """facts 用于生成答复；artifacts 仅用于服务端状态与页面组件。"""

    status: str
    facts: dict = field(default_factory=dict)
    artifacts: dict = field(default_factory=dict)
