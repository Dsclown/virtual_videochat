from abc import ABC, abstractmethod


class TTSModule(ABC):
    @abstractmethod
    async def synthesize(self, text: str) -> bytes:
        """合成整段语音，返回 mp3 字节。"""
