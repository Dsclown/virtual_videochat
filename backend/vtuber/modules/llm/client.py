"""LLM 客户端抽象：每路 stream 自行管理连接生命周期。"""

from abc import ABC, abstractmethod
from typing import AsyncIterator


class ChatStream(ABC):
    """可 ``async with`` + ``async for`` 的单路流式回复。"""

    @abstractmethod
    async def __aenter__(self) -> "ChatStream":
        ...

    @abstractmethod
    async def __aexit__(self, exc_type, exc, tb) -> None:
        ...

    @abstractmethod
    def __aiter__(self) -> AsyncIterator[str]:
        ...


class LLMClient(ABC):
    """进程级 LLM 客户端；``open_stream`` 返回一路独立流。"""

    @abstractmethod
    def open_stream(self, messages: list[dict]) -> ChatStream:
        ...
