from abc import ABC, abstractmethod

from vtuber.modules.memory.types import ChatTurn


class MemoryModule(ABC):
    @abstractmethod
    def load_today_turns(self) -> list[ChatTurn]:
        """加载当日全部对话轮次（登录/会话建立时调用一次）。"""

    @abstractmethod
    def append_turn(self, user: str, assistant: str) -> ChatTurn:
        """追加一轮对话并持久化。"""

    @abstractmethod
    def clear(self) -> None:
        """清空对话记录。"""
