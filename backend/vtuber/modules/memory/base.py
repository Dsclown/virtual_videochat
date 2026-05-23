from abc import ABC, abstractmethod


class MemoryModule(ABC):
    @abstractmethod
    def load_messages(self) -> list[dict]:
        """加载用户对话记录（OpenAI message 格式）。"""

    @abstractmethod
    def save_messages(self, messages: list[dict]) -> None:
        """持久化对话记录到 main.jsonl。"""

    @abstractmethod
    def append(self, role: str, content: str) -> None:
        pass

    @abstractmethod
    def clear(self) -> None:
        """清空对话记录。"""
