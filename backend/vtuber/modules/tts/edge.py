import logging

import edge_tts

from vtuber.config.loader import TTSConfig
from vtuber.modules.tts.base import TTSModule

logger = logging.getLogger(__name__)


class EdgeTTS(TTSModule):
    def __init__(self, cfg: TTSConfig):
        self._voice = cfg.voice

    async def synthesize(self, text: str) -> bytes:
        text = text.strip()
        if not text:
            return b""
        communicate = edge_tts.Communicate(text, self._voice)
        chunks: list[bytes] = []
        try:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    chunks.append(chunk["data"])
        except Exception:
            logger.exception("Edge TTS 合成异常 len=%d: %r", len(text), text[:80])
            raise
        audio = b"".join(chunks)
        if not audio:
            logger.warning("Edge TTS 无音频数据 len=%d: %r", len(text), text[:80])
        return audio
