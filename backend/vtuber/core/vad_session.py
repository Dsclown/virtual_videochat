"""每连接独立的 VAD 会话（共享 Silero 权重 + 独立状态机）。"""

import logging
from enum import Enum
from typing import Awaitable, Callable

import numpy as np

from vtuber.config.loader import SpeechFilterConfig
from vtuber.modules.vad.interface import VADInterface
from vtuber.modules.vad.silero import PAUSE_MARKER
from vtuber.utils.speech_filter import (
    is_probably_speech,
    update_noise_floor,
)

logger = logging.getLogger(__name__)

SendFn = Callable[[dict], Awaitable[None]]


class VadEventType(str, Enum):
    SPEECH_START = "speech_start"
    SPEECH_END = "speech_end"
    FILTERED = "filtered"


class VadSession:
    def __init__(
        self,
        engine: VADInterface,
        send: SendFn,
        *,
        min_speech_samples: int = 9600,
        speech_filter: SpeechFilterConfig | None = None,
        run_vad=None,
    ):
        self._engine = engine
        self._send = send
        self._run_vad_fn = run_vad
        self._turn_active = False
        self._in_speech = False
        self._min_speech_samples = min_speech_samples
        self._filter = speech_filter or SpeechFilterConfig()
        self._noise_floor = 0.0

    def set_turn_active(self, active: bool) -> None:
        """AI 思考/回应期间不更新环境底噪（避免 TTS 外放抬高 floor）。"""
        if self._turn_active and not active:
            logger.debug("回合结束，当前环境底噪 floor=%.4f", self._noise_floor)
        self._turn_active = active

    @property
    def turn_active(self) -> bool:
        return self._turn_active

    def _maybe_update_noise_floor(self, samples: list[float]) -> None:
        if self._in_speech or self._turn_active:
            return
        prev = self._noise_floor
        self._noise_floor = update_noise_floor(
            samples,
            self._noise_floor,
            self._filter.noise_floor_ema_alpha,
        )
        if abs(self._noise_floor - prev) > 1e-5:
            logger.debug("环境底噪更新 floor=%.4f", self._noise_floor)

    @staticmethod
    def _run_vad(engine: VADInterface, samples: list[float]) -> list[bytes]:
        """Silero VAD 含 torch 同步推理，必须在子线程跑以免阻塞事件循环。"""
        return list(engine.detect_speech(samples))

    async def feed(self, samples: list[float]) -> tuple[bool, np.ndarray | None]:
        """
        喂入 16kHz float 样本。
        返回 (应打断当前轮, 通过人声筛选的 PCM 或 None)。
        """
        should_interrupt = False
        pcm_segment: np.ndarray | None = None
        ended_utterance = False

        vad_events = await self._run_vad_fn(self._run_vad, self._engine, samples)
        for audio_bytes in vad_events:
            if audio_bytes == PAUSE_MARKER:
                self._in_speech = True
                await self._send({"type": "vad", "event": VadEventType.SPEECH_START.value})
                await self._send({"type": "stop_audio"})
                if self._turn_active:
                    await self._send({"type": "control", "text": "interrupt"})
                    should_interrupt = True
                continue
            if len(audio_bytes) <= 1024:
                continue

            ended_utterance = True
            pcm = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            if pcm.size < self._min_speech_samples:
                logger.debug(
                    "VAD 切段过短 %.2fs，忽略",
                    pcm.size / 16000,
                )
                continue

            ok, reason = is_probably_speech(pcm, self._filter, self._noise_floor)
            if not ok:
                logger.debug(
                    "非人声切段已丢弃 %.2fs: %s (floor=%.4f)",
                    pcm.size / 16000,
                    reason,
                    self._noise_floor,
                )
                await self._send({
                    "type": "vad",
                    "event": VadEventType.FILTERED.value,
                    "reason": reason,
                })
                continue

            await self._send({"type": "vad", "event": VadEventType.SPEECH_END.value})
            pcm_segment = pcm
            logger.debug("VAD 人声切段 %.2fs (%s)", pcm.size / 16000, reason)

        if ended_utterance:
            self._in_speech = False

        self._maybe_update_noise_floor(samples)
        return should_interrupt, pcm_segment
