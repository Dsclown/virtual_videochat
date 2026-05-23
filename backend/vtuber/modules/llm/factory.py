from vtuber.config.loader import LLMConfig
from vtuber.modules.llm.base import LLMModule
from vtuber.modules.llm.openai_api import OpenAIApiLLM


class LLMFactory:
    @staticmethod
    def create(cfg: LLMConfig) -> LLMModule:
        if cfg.provider != "openai_api":
            raise ValueError(f"初版仅支持 llm.provider=openai_api，当前: {cfg.provider}")
        return OpenAIApiLLM(cfg)
