from vtuber.config.loader import TTSConfig
from vtuber.modules.tts.base import TTSModule
from vtuber.modules.tts.edge import EdgeTTS


class TTSFactory:
    @staticmethod
    def create(cfg: TTSConfig) -> TTSModule:
        if cfg.provider != "edge":
            raise ValueError(f"初版仅支持 tts.provider=edge，当前: {cfg.provider}")
        return EdgeTTS(cfg)
