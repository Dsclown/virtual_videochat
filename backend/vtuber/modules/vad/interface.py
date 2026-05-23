from abc import ABC, abstractmethod
from typing import Iterator


class VADInterface(ABC):
    @abstractmethod
    def detect_speech(self, audio_data: list[float]) -> Iterator[bytes]:
        """
        流式检测语音活动。
        产出 b"<|PAUSE|>" 表示检测到说话开始；
        产出完整语音段 int16 bytes 表示一段说话结束。
        """
