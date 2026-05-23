from vtuber.config.loader import LLMConfig
from vtuber.modules.llm.base import LLMModule
from vtuber.modules.llm.client import ChatStream, LLMClient
from vtuber.modules.llm.openai_client import OpenAIChatClient


class OpenAIApiLLM(LLMModule):
    """OpenAI 兼容 API 模块。"""

    def __init__(self, cfg: LLMConfig):
        self._client = OpenAIChatClient(cfg)

    @property
    def client(self) -> LLMClient:
        return self._client

    def open_stream(self, messages: list[dict]) -> ChatStream:
        return self._client.open_stream(messages)
