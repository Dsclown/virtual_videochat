from vtuber.config.loader import VADConfig
from vtuber.modules.vad.interface import VADInterface
from vtuber.modules.vad.silero import SileroVADBackend, SileroVADConfig, VADEngine


class VADFactory:
    @staticmethod
    def create_backend(cfg: VADConfig) -> SileroVADBackend | None:
        if not cfg.vad_model:
            return None
        if cfg.vad_model == "silero_vad":
            s = cfg.silero_vad or SileroVADConfig()
            return SileroVADBackend(target_sr=s.target_sr)
        raise ValueError(f"未知 VAD: {cfg.vad_model}")

    @staticmethod
    def create_session(cfg: VADConfig, backend: SileroVADBackend) -> VADInterface:
        if cfg.vad_model != "silero_vad":
            raise ValueError(f"未知 VAD: {cfg.vad_model}")
        s = cfg.silero_vad or SileroVADConfig()
        vad_cfg = SileroVADConfig(
            orig_sr=s.orig_sr,
            target_sr=s.target_sr,
            prob_threshold=s.prob_threshold,
            db_threshold=s.db_threshold,
            required_hits=s.required_hits,
            required_misses=s.required_misses,
            smoothing_window=s.smoothing_window,
        )
        return VADEngine(backend, vad_cfg)
