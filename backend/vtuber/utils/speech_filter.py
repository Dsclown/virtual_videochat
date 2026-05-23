"""VAD 切段后、ASR 前的人声粗筛（过滤背景音乐等误触发）。"""

import logging
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class SpeechFilterConfig:
    enabled: bool = True
    min_rms: float = 0.015
    min_rms_above_noise_ratio: float = 2.5
    # 人声在背景音乐下平坦度常 0.45～0.6，过严会误杀真人说话
    max_spectral_flatness: float = 0.62
    noise_floor_ema_alpha: float = 0.05
    # 音量高于该值时不再用平坦度否决（你已正常说话往往 >0.04）
    skip_flatness_if_rms_above: float = 0.04


def chunk_rms(pcm: np.ndarray) -> float:
    if pcm.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(pcm))))


def spectral_flatness(pcm: np.ndarray, frame_size: int = 512) -> float:
    """越高越像噪声/音乐，正常对话人声通常较低。"""
    if pcm.size < frame_size:
        return 1.0
    hop = frame_size // 2
    values: list[float] = []
    window = np.hanning(frame_size)
    for start in range(0, pcm.size - frame_size + 1, hop):
        frame = pcm[start : start + frame_size] * window
        mag = np.abs(np.fft.rfft(frame))
        mag = mag[mag > 1e-10]
        if mag.size < 2:
            continue
        geo = np.exp(np.mean(np.log(mag)))
        arith = np.mean(mag)
        if arith > 0:
            values.append(float(geo / arith))
    return float(np.median(values)) if values else 1.0


def is_probably_speech(
    pcm: np.ndarray,
    cfg: SpeechFilterConfig,
    noise_floor: float,
) -> tuple[bool, str]:
    if not cfg.enabled:
        return True, "disabled"

    rms = chunk_rms(pcm)
    if rms < cfg.min_rms:
        return False, f"rms={rms:.4f} 低于绝对阈值"

    adaptive = max(noise_floor, 1e-4) * cfg.min_rms_above_noise_ratio
    if rms < adaptive:
        return False, (
            f"rms={rms:.4f} 未明显高于环境底噪 floor={noise_floor:.4f}"
        )

    # 音量已够大时视为真人说话，不再用平坦度误杀（带 BGM 时 flat 常 >0.5）
    if rms >= cfg.skip_flatness_if_rms_above:
        return True, f"rms={rms:.4f} (能量足够，跳过平坦度检查)"

    flat = spectral_flatness(pcm)
    if flat > cfg.max_spectral_flatness:
        return False, f"spectral_flatness={flat:.3f} 偏高(疑似音乐/稳态噪声)"

    return True, f"rms={rms:.4f} flat={flat:.3f}"


def update_noise_floor(
    samples: list[float] | np.ndarray,
    current: float,
    alpha: float,
) -> float:
    """
    仅用「安静」片段更新底噪；响亮片段（人声/TTS）不抬高 floor。
    """
    arr = np.asarray(samples, dtype=np.float32)
    if arr.size == 0:
        return current
    rms = chunk_rms(arr)
    if current <= 0:
        return rms
    # 当前块明显比已有底噪响 → 多半是人声或喇叭，不参与更新
    if rms > current * 1.5:
        return current
    return (1 - alpha) * current + alpha * rms
