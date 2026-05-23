"""Silero VAD（与 Open-LLM-VTuber 同源状态机逻辑）。"""

import logging
import threading
from collections import deque
from enum import Enum

import numpy as np
import torch
from silero_vad import load_silero_vad

from vtuber.modules.vad.interface import VADInterface

logger = logging.getLogger(__name__)

PAUSE_MARKER = b"<|PAUSE|>"
RESUME_MARKER = b"<|RESUME|>"


class SileroVADConfig:
    def __init__(
        self,
        orig_sr: int = 16000,
        target_sr: int = 16000,
        prob_threshold: float = 0.4,
        db_threshold: int = 60,
        required_hits: int = 3,
        required_misses: int = 24,
        smoothing_window: int = 5,
    ):
        self.orig_sr = orig_sr
        self.target_sr = target_sr
        self.prob_threshold = prob_threshold
        self.db_threshold = db_threshold
        self.required_hits = required_hits
        self.required_misses = required_misses
        self.smoothing_window = smoothing_window


class SileroVADBackend:
    """进程内共享 Silero 权重；多连接各用独立 StateMachine。"""

    def __init__(self, target_sr: int = 16000):
        self.target_sr = target_sr
        self.window_size_samples = 512 if target_sr == 16000 else 256
        logger.info("加载 Silero-VAD 模型（全局共享）…")
        self.model = load_silero_vad()
        self._lock = threading.Lock()

    def speech_prob(self, chunk_np: np.ndarray) -> float:
        chunk = torch.Tensor(chunk_np)
        with self._lock:
            with torch.no_grad():
                return self.model(chunk, self.target_sr).item()


class VADEngine(VADInterface):
    """单连接 VAD：共享 backend + 独立状态机。"""

    def __init__(self, backend: SileroVADBackend, config: SileroVADConfig):
        self._backend = backend
        self.config = config
        self.state = StateMachine(config)
        self.window_size_samples = backend.window_size_samples

    def detect_speech(self, audio_data: list[float]):
        audio_np = np.array(audio_data, dtype=np.float32)
        for i in range(0, len(audio_np), self.window_size_samples):
            chunk_np = audio_np[i : i + self.window_size_samples]
            if len(chunk_np) < self.window_size_samples:
                break
            speech_prob = self._backend.speech_prob(chunk_np)
            if speech_prob:
                for _probs, _dbs, chunk in self.state.get_result(speech_prob, chunk_np):
                    yield bytes(chunk)
        del audio_np


class State(Enum):
    IDLE = 1
    ACTIVE = 2
    INACTIVE = 3


class StateMachine:
    def __init__(self, config: SileroVADConfig):
        self.state = State.IDLE
        self.prob_threshold = config.prob_threshold
        self.db_threshold = config.db_threshold
        self.required_hits = config.required_hits
        self.required_misses = config.required_misses
        self.smoothing_window = config.smoothing_window
        self.probs: list[float] = []
        self.dbs: list[float] = []
        self.bytes = bytearray()
        self.miss_count = 0
        self.hit_count = 0
        self.prob_window = deque(maxlen=self.smoothing_window)
        self.db_window = deque(maxlen=self.smoothing_window)
        self.pre_buffer = deque(maxlen=20)

    @classmethod
    def calculate_db(cls, audio_data: np.ndarray) -> float:
        rms = np.sqrt(np.mean(np.square(audio_data)))
        return 20 * np.log10(rms + 1e-7) if rms > 0 else -np.inf

    def update(self, chunk_bytes, prob, db):
        self.probs.append(prob)
        self.dbs.append(db)
        self.bytes.extend(chunk_bytes)

    def reset_buffers(self):
        self.probs.clear()
        self.dbs.clear()
        self.bytes.clear()

    def get_smoothed_values(self, prob, db):
        self.prob_window.append(prob)
        self.db_window.append(db)
        return np.mean(self.prob_window), np.mean(self.db_window)

    def process(self, prob, float_chunk_np: np.ndarray):
        int_chunk_np = float_chunk_np * 32767
        chunk_bytes = int_chunk_np.astype(np.int16).tobytes()
        db = self.calculate_db(int_chunk_np)
        smoothed_prob, smoothed_db = self.get_smoothed_values(prob, db)

        if self.state == State.IDLE:
            self.pre_buffer.append(chunk_bytes)
            if (
                smoothed_prob >= self.prob_threshold
                and smoothed_db >= self.db_threshold
            ):
                self.hit_count += 1
                if self.hit_count >= self.required_hits:
                    self.state = State.ACTIVE
                    self.update(chunk_bytes, smoothed_prob, smoothed_db)
                    self.hit_count = 0
                    yield [], [], PAUSE_MARKER
            else:
                self.hit_count = 0

        elif self.state == State.ACTIVE:
            self.update(chunk_bytes, smoothed_prob, smoothed_db)
            if (
                smoothed_prob >= self.prob_threshold
                and smoothed_db >= self.db_threshold
            ):
                self.miss_count = 0
            else:
                self.miss_count += 1
                if self.miss_count >= self.required_misses:
                    self.state = State.INACTIVE
                    self.miss_count = 0

        elif self.state == State.INACTIVE:
            self.update(chunk_bytes, smoothed_prob, smoothed_db)
            if (
                smoothed_prob >= self.prob_threshold
                and smoothed_db >= self.db_threshold
            ):
                self.hit_count += 1
                if self.hit_count >= self.required_hits:
                    self.state = State.ACTIVE
                    self.hit_count = 0
                    self.miss_count = 0
            else:
                self.hit_count = 0
                self.miss_count += 1
                if self.miss_count >= self.required_misses:
                    self.state = State.IDLE
                    self.miss_count = 0
                    yield [], [], RESUME_MARKER
                    if len(self.probs) > 30:
                        pre_bytes = b"".join(self.pre_buffer)
                        yield self.probs, self.dbs, pre_bytes + self.bytes
                        self.reset_buffers()
                    self.pre_buffer.clear()

    def get_result(self, input_num, chunk_np):
        yield from self.process(input_num, chunk_np)
