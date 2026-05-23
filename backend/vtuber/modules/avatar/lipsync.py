"""TTS 音频解码与口型包络。"""

import io
import math
import struct

from pydub import AudioSegment


def mp3_to_pcm48k(mp3_bytes: bytes) -> tuple[bytes, int]:
    """MP3 → mono s16le 48kHz PCM。"""
    seg = AudioSegment.from_file(io.BytesIO(mp3_bytes), format="mp3")
    seg = seg.set_channels(1).set_frame_rate(48_000).set_sample_width(2)
    return seg.raw_data, 48_000


def pcm_rms_envelope(pcm: bytes, sample_rate: int, fps: int) -> list[float]:
    """按视频帧率计算 RMS 嘴型开度 0..1。"""
    if not pcm or fps <= 0:
        return []
    samples_per_frame = max(1, sample_rate // fps)
    frame_count = len(pcm) // 2 // samples_per_frame
    out: list[float] = []
    for i in range(frame_count):
        start = i * samples_per_frame * 2
        end = start + samples_per_frame * 2
        chunk = pcm[start:end]
        if len(chunk) < 2:
            break
        count = len(chunk) // 2
        acc = 0.0
        for j in range(0, len(chunk), 2):
            sample = struct.unpack_from("<h", chunk, j)[0] / 32768.0
            acc += sample * sample
        rms = math.sqrt(acc / max(1, count))
        out.append(min(1.0, rms * 10.0))
    return out


def iter_pcm_frames(pcm: bytes, sample_rate: int, frame_samples: int = 960):
    """48kHz 下默认 20ms 一帧（960 samples）。"""
    step = frame_samples * 2
    for i in range(0, len(pcm), step):
        chunk = pcm[i : i + step]
        if not chunk:
            break
        if len(chunk) < step:
            chunk = chunk + b"\x00" * (step - len(chunk))
        yield chunk
