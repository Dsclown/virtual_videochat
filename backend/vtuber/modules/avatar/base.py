from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class AvatarState:
    """预留：非 Playwright 渲染路径的状态载体。"""


class AvatarModule(ABC):
    @abstractmethod
    def parse_from_reply(self, full_text: str) -> tuple[str, AvatarState | None]:
        """从 LLM 完整回复中分离口语文本（扩展点）。"""
