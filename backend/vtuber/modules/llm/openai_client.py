import asyncio
import logging
from collections.abc import AsyncIterator

import httpx
from openai import AsyncOpenAI

from vtuber.config.loader import LLMConfig
from vtuber.modules.llm.client import ChatStream, LLMClient

logger = logging.getLogger(__name__)

_TOKEN_TIMEOUT_SEC = 60.0


def _normalize_base(url: str) -> str:
    url = url.rstrip("/")
    return url if url.endswith("/v1") else f"{url}/v1"


class OpenAIChatStream(ChatStream):
    """单路 OpenAI 兼容流；``async with`` 退出时自动 close HTTP 流。"""

    def __init__(self, client: AsyncOpenAI, *, model: str, messages: list[dict], temperature: float):
        self._client = client
        self._model = model
        self._messages = messages
        self._temperature = temperature
        self._stream = None
        self._chunk_iter = None

    async def __aenter__(self) -> "OpenAIChatStream":
        self._stream = await self._client.chat.completions.create(
            model=self._model,
            messages=self._messages,
            stream=True,
            temperature=self._temperature,
            max_tokens=1024,
        )
        self._chunk_iter = self._stream.__aiter__()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self._close()

    def __aiter__(self) -> AsyncIterator[str]:
        return self

    async def __anext__(self) -> str:
        if self._chunk_iter is None:
            raise StopAsyncIteration
        try:
            while True:
                chunk = await asyncio.wait_for(
                    self._chunk_iter.__anext__(),
                    timeout=_TOKEN_TIMEOUT_SEC,
                )
                delta = chunk.choices[0].delta.content if chunk.choices else None
                if delta:
                    return delta
        except StopAsyncIteration:
            raise
        except asyncio.TimeoutError:
            logger.error("LLM token 等待超时 (%ds)", _TOKEN_TIMEOUT_SEC)
            raise StopAsyncIteration

    async def _close(self) -> None:
        if self._stream is None:
            return
        stream = self._stream
        self._stream = None
        self._chunk_iter = None
        close = getattr(stream, "close", None)
        if close is None:
            return
        try:
            await close()
        except Exception:
            logger.debug("关闭 LLM 流异常", exc_info=True)


class OpenAIChatClient(LLMClient):
    """OpenAI 兼容 API 客户端（DeepSeek 等）。"""

    def __init__(self, cfg: LLMConfig):
        if not cfg.api_key:
            raise ValueError("未配置 LLM api_key")
        self._cfg = cfg
        limits = httpx.Limits(max_connections=20, max_keepalive_connections=5)
        self._client = AsyncOpenAI(
            api_key=cfg.api_key,
            base_url=_normalize_base(cfg.base_url),
            timeout=httpx.Timeout(90.0, connect=15.0),
            http_client=httpx.AsyncClient(limits=limits),
        )

    def open_stream(self, messages: list[dict]) -> OpenAIChatStream:
        return OpenAIChatStream(
            self._client,
            model=self._cfg.model,
            messages=messages,
            temperature=self._cfg.temperature,
        )
