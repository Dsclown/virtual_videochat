from abc import ABC, abstractmethod
from typing import AsyncIterator

from vtuber.modules.llm.client import ChatStream, LLMClient


class LLMModule(ABC):
    """对外模块接口：编排层通过 ``open_stream`` 消费 LLM。"""

    @property
    @abstractmethod
    def client(self) -> LLMClient:
        ...

    @abstractmethod
    def open_stream(self, messages: list[dict]) -> ChatStream:
        ...

    async def stream_chat(self, messages: list[dict]) -> AsyncIterator[str]:
        """兼容旧调用；新代码请用 ``async with llm.open_stream(msgs)``。"""
        async with self.open_stream(messages) as stream:
            async for token in stream:
                yield token
