import io
import logging
import subprocess
import tempfile
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)
SAMPLE_RATE = 16000


def bytes_to_pcm16(audio_bytes: bytes, mime_hint: str = "audio/webm") -> np.ndarray:
    """将浏览器录音转为 16kHz mono float32 numpy（sherpa 输入）。"""
    suffix = ".webm" if "webm" in mime_hint else ".wav"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(audio_bytes)
        inp = f.name

    out = inp + ".pcm"
    try:
        cmd = [
            "ffmpeg", "-y", "-i", inp,
            "-ac", "1", "-ar", str(SAMPLE_RATE),
            "-f", "s16le", "-acodec", "pcm_s16le", out,
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        pcm = Path(out).read_bytes()
        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        return audio
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        logger.warning("ffmpeg 转码失败: %s", e)
        raise RuntimeError("需要安装 ffmpeg 才能使用 sherpa ASR") from e
    finally:
        for p in (inp, out):
            try:
                Path(p).unlink(missing_ok=True)
            except OSError:
                pass
