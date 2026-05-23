from abc import ABC, abstractmethod

import numpy as np


class ASRModule(ABC):
    @abstractmethod
    async def transcribe(self, audio_bytes: bytes, mime_hint: str = "audio/webm") -> str:
        """语音转文本。"""

    async def transcribe_pcm(self, audio: np.ndarray) -> str:
        raise NotImplementedError
