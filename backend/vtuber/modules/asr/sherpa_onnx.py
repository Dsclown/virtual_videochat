import asyncio
import logging
from pathlib import Path

import numpy as np
import sherpa_onnx

from vtuber.config.loader import ASRConfig, PROJECT_ROOT
from vtuber.modules.asr.base import ASRModule
from vtuber.utils.audio import SAMPLE_RATE, bytes_to_pcm16

logger = logging.getLogger(__name__)

# int8 量化版约 228MB，与 config 中 model.int8.onnx 一致（勿下 999MB 完整包）
SENSE_VOICE_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
    "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17.tar.bz2"
)


def _ensure_model(model_dir: Path) -> tuple[str, str]:
    model_path = model_dir / "model.int8.onnx"
    tokens_path = model_dir / "tokens.txt"
    if model_path.is_file() and tokens_path.is_file():
        return str(model_path), str(tokens_path)

    import urllib.request
    import tarfile

    model_dir.parent.mkdir(parents=True, exist_ok=True)
    archive = model_dir.parent / "sherpa-onnx-sense-voice.tar.bz2"
    logger.info("下载 sherpa SenseVoice 模型…")
    urllib.request.urlretrieve(SENSE_VOICE_URL, archive)
    with tarfile.open(archive, "r:bz2") as tar:
        tar.extractall(path=model_dir.parent)
    archive.unlink(missing_ok=True)
    return str(model_path), str(tokens_path)


def _create_recognizer(cfg: ASRConfig) -> sherpa_onnx.OfflineRecognizer:
    model_dir = (PROJECT_ROOT / cfg.model_dir).resolve()
    sense_voice, tokens = _ensure_model(model_dir)
    return sherpa_onnx.OfflineRecognizer.from_sense_voice(
        model=sense_voice,
        tokens=tokens,
        num_threads=cfg.num_threads,
        use_itn=True,
        provider=cfg.provider_device,
    )


def _transcribe_np(recognizer: sherpa_onnx.OfflineRecognizer, audio: np.ndarray) -> str:
    stream = recognizer.create_stream()
    stream.accept_waveform(SAMPLE_RATE, audio)
    recognizer.decode_stream(stream)
    return (stream.result.text or "").strip()


class SherpaOnnxASR(ASRModule):
    """sherpa-onnx SenseVoice；recognizer 池支持多连接并行 ASR。"""

    def __init__(self, cfg: ASRConfig):
        pool_size = max(1, cfg.pool_size)
        self._pool: asyncio.Queue[sherpa_onnx.OfflineRecognizer] = asyncio.Queue(
            maxsize=pool_size,
        )
        for i in range(pool_size):
            self._pool.put_nowait(_create_recognizer(cfg))
        logger.info(
            "Sherpa ASR 池已就绪 pool_size=%d num_threads=%d（每槽独立 recognizer，可并行 decode）",
            pool_size,
            cfg.num_threads,
        )

    async def transcribe_pcm(self, audio: np.ndarray) -> str:
        recognizer = await self._pool.get()
        try:
            text = await asyncio.to_thread(_transcribe_np, recognizer, audio)
        finally:
            self._pool.put_nowait(recognizer)
        logger.info("ASR 结果: %r", text)
        return text

    async def transcribe(self, audio_bytes: bytes, mime_hint: str = "audio/webm") -> str:
        logger.info("ASR 转码识别，音频 %d bytes", len(audio_bytes))
        pcm = bytes_to_pcm16(audio_bytes, mime_hint)
        return await self.transcribe_pcm(pcm)
