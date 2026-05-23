import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class AvatarState:
    emotion: str = "neutral"
    gesture: str = "none"
    scene: str = "default"


class AvatarModule(ABC):
    @abstractmethod
    def parse_from_reply(self, full_text: str) -> tuple[str, AvatarState | None]:
        """从 LLM 完整回复中分离口语文本与 Live2D 状态。"""
