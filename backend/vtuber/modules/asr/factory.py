from vtuber.config.loader import ASRConfig
from vtuber.modules.asr.base import ASRModule
from vtuber.modules.asr.sherpa_onnx import SherpaOnnxASR


class ASRFactory:
    @staticmethod
    def create(cfg: ASRConfig) -> ASRModule:
        if cfg.provider != "sherpa_onnx":
            raise ValueError(f"初版仅支持 asr.provider=sherpa_onnx，当前: {cfg.provider}")
        return SherpaOnnxASR(cfg)
