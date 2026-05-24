"""核心对话会话：VAD / 编排 / Avatar 渲染；经 EventEmitter 向 Gateway 输出。"""

import asyncio
import logging
import struct
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

import numpy as np

from vtuber.app.context import ServiceContext
from vtuber.config.loader import AppConfig
from vtuber.core.messaging import TURN_TAG_TYPES
from vtuber.core.orchestrator import ConversationOrchestrator
from vtuber.core.stages import Stage
from vtuber.core.vad_session import VadSession
from vtuber.modules.avatar.render_session import AvatarRenderSession
from vtuber.modules.memory.factory import MemoryFactory
from vtuber.modules.memory.types import ChatTurn
from vtuber.modules.profile.form import sanitize_user_id

logger = logging.getLogger(__name__)

_AUDIO_QUEUE_MAX = 16
TARGET_SR = 16_000
# 与 Gateway WebRTC 轨一致：48kHz、20ms 一帧
_AUDIO_CHUNK_BYTES = 960 * 2
_AUDIO_PTIME_SEC = 0.020

EmitFn = Callable[[dict], Awaitable[None]]
MediaFn = Callable[[dict], Awaitable[None]]


class CoreConversationSession:
    def __init__(
        self,
        session_id: str,
        ctx: ServiceContext,
        config: AppConfig,
        emit: EmitFn,
        emit_media: MediaFn,
    ):
        self.session_id = session_id
        self._ctx = ctx
        self._config = config
        self._emit = emit
        self._emit_media = emit_media

        self._user_id: str | None = None
        self._memory = None
        self._chat_turns: list[ChatTurn] = []
        self._vad: VadSession | None = None
        self._orchestrator: ConversationOrchestrator | None = None
        self._avatar: AvatarRenderSession | None = None  # open() 成功后必有

        self._turn_id = 0
        self._gen = 0
        self._turn_running = False
        self._closed = False
        self._audio_in: asyncio.Queue[dict | None] = asyncio.Queue(maxsize=_AUDIO_QUEUE_MAX)
        self._audio_task: asyncio.Task[Any] | None = None
        self._media_tasks: list[asyncio.Task[Any]] = []
        self._tasks: set[asyncio.Task[Any]] = set()

    @property
    def avatar(self) -> AvatarRenderSession | None:
        return self._avatar

    async def open(self, user_id: str) -> dict:
        try:
            self._user_id = sanitize_user_id(user_id)
        except ValueError as e:
            await self._emit({"type": "error", "message": str(e)})
            raise

        self._memory = MemoryFactory.create(self._config.memory, self._user_id)
        self._chat_turns = await self._ctx.run_io(self._memory.load_today_turns)

        engine = self._ctx.new_vad_engine()
        if engine:
            sv = self._config.vad.silero_vad
            min_samples = int(sv.min_speech_duration_sec * sv.target_sr)
            self._vad = VadSession(
                engine,
                self._vad_send,
                min_speech_samples=min_samples,
                speech_filter=self._config.vad.speech_filter,
                run_vad=self._ctx.run_vad,
            )

        if not self._ctx.playwright.enabled:
            msg = "未启用 Playwright，无法启动虚拟人 Avatar"
            await self._emit({"type": "error", "message": msg})
            raise RuntimeError(msg)

        self._avatar = AvatarRenderSession(
            self._ctx.playwright,
            self._config.avatar,
            live2d_model=self._ctx.live2d_model,
        )
        await self._avatar.start(wait_ready=False)
        self._start_media_pumps()

        self._audio_task = asyncio.create_task(self._audio_loop())
        return {
            "vad_enabled": self._vad is not None,
            "avatar_enabled": True,
        }

    async def _vad_send(self, msg: dict) -> None:
        t = msg.get("type")
        if t == "vad":
            ev = msg.get("event")
            if ev == "speech_start":
                await self._emit({"type": "vad", "event": "speech_start"})
            elif ev == "speech_end":
                await self._emit({"type": "vad", "event": "speech_end"})
            elif ev == "filtered":
                await self._emit({
                    "type": "vad",
                    "event": "filtered",
                    "reason": msg.get("reason", ""),
                })
            return
        # 旧版 stop_audio：停播并清 Avatar 状态，但不 turn_cancelled（误显示打断）
        if t == "stop_audio":
            if self._avatar:
                await self._avatar.stop_playback()
            return
        if t == "control" and msg.get("text") == "interrupt":
            await self.interrupt()
            return
        await self._emit(msg)

    async def send(self, msg: dict) -> None:
        if self._closed:
            return
        t = msg.get("type")
        if t == "stage":
            if self._vad:
                stage = msg.get("stage")
                self._vad.set_turn_active(
                    stage in (Stage.THINKING.value, Stage.SPEAKING.value)
                )
            return
        if t in TURN_TAG_TYPES:
            msg = {**msg, "turn_id": self._turn_id}
        await self._emit(msg)

    def _gated_send(self, gen: int) -> EmitFn:
        async def _send(msg: dict) -> None:
            if gen != self._gen or self._closed:
                return
            await self.send(msg)

        return _send

    async def feed_pcm_f32(self, pcm_f32le: bytes, sample_rate: int = TARGET_SR) -> None:
        if sample_rate != TARGET_SR:
            logger.warning("忽略非 16kHz PCM: %d", sample_rate)
            return
        n = len(pcm_f32le) // 4
        if n <= 0:
            return
        floats = list(struct.unpack(f"<{n}f", pcm_f32le))
        self._enqueue_audio({"audio": floats})

    def _enqueue_audio(self, data: dict) -> None:
        try:
            self._audio_in.put_nowait(data)
        except asyncio.QueueFull:
            pass

    async def _audio_loop(self) -> None:
        while True:
            data = await self._audio_in.get()
            try:
                if data is None:
                    return
                await self._process_raw_audio(data)
            except Exception:
                logger.exception("音频帧处理失败")
            finally:
                self._audio_in.task_done()

    async def _process_raw_audio(self, data: dict) -> None:
        chunk = data.get("audio") or []
        if not chunk or not self._vad:
            return
        should_interrupt, pcm = await self._vad.feed(chunk)
        if should_interrupt:
            await self.interrupt()
        if pcm is None:
            return
        ai_busy = self._vad.turn_active or self._turn_running
        if ai_busy and not should_interrupt:
            return

        async def _pcm(orch: ConversationOrchestrator) -> None:
            await orch.run_turn_pcm(pcm)

        self._start_turn(_pcm, bump=not should_interrupt)

    async def run_user_text(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return

        async def _text(orch: ConversationOrchestrator) -> None:
            await orch.run_turn_text(text)

        self._start_turn(_text)

    async def reset_memory(self) -> None:
        await self.interrupt()
        if self._memory:
            await self._ctx.run_io(self._memory.clear)
            self._chat_turns.clear()
        await self._emit({"type": "reset_ok"})

    async def interrupt(self) -> None:
        self._bump_turn()
        if self._avatar:
            await self._avatar.interrupt()
        if self._vad:
            self._vad.set_turn_active(False)
        self._cancel_all_tasks()
        await self._emit({"type": "turn_cancelled"})

    def _bump_turn(self) -> int:
        self._turn_id += 1
        self._gen += 1
        return self._gen

    def _cancel_all_tasks(self) -> None:
        if self._orchestrator:
            self._orchestrator.cancel()
        for task in list(self._tasks):
            if not task.done():
                task.cancel()

    def _start_turn(self, coro, *, bump: bool = True) -> None:
        if bump:
            self._bump_turn()
        gen = self._gen
        self._turn_running = True
        self._cancel_all_tasks()
        task = asyncio.create_task(self._run_turn(coro, gen))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run_turn(self, coro, gen: int) -> None:
        try:
            self._orchestrator = ConversationOrchestrator(
                self._ctx,
                self._user_id,
                self._gated_send(gen),
                avatar=self._avatar,
                memory=self._memory,
                chat_turns=self._chat_turns,
                llm_context_rounds=self._config.memory.llm_context_rounds,
            )
            await coro(self._orchestrator)
        except asyncio.CancelledError:
            if self._orchestrator:
                self._orchestrator.cancel()
            raise
        finally:
            self._turn_running = False

    def _start_media_pumps(self) -> None:
        self._media_tasks = [
            asyncio.create_task(self._av_media_loop()),
        ]

    async def _av_media_loop(self) -> None:
        """每 tick 一条 MediaOut 同时携带 audio + video。"""
        assert self._avatar
        try:
            while not self._closed:
                loop = asyncio.get_running_loop()
                t0 = loop.time()
                pcm = await self._avatar.next_audio_chunk(_AUDIO_CHUNK_BYTES)
                await asyncio.sleep(0)
                await self._emit_media({"pcm_s16le": pcm})
                frame = await self._avatar.try_take_video_frame()
                if frame is not None:
                    rgb, w, h = frame
                    await self._emit_media({
                        "width": w,
                        "height": h,
                        "rgb24": rgb,
                    })
                elapsed = loop.time() - t0
                await asyncio.sleep(max(0.0, _AUDIO_PTIME_SEC - elapsed))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("音视频媒体泵异常退出")

    async def close(self) -> None:
        self._closed = True
        self._gen += 1
        self._cancel_all_tasks()
        await self._audio_in.put(None)
        if self._audio_task:
            await self._audio_task
        for t in self._media_tasks:
            if not t.done():
                t.cancel()
        if self._media_tasks:
            await asyncio.gather(*self._media_tasks, return_exceptions=True)
        if self._avatar:
            await self._avatar.close()
            self._avatar = None


def new_session_id() -> str:
    return uuid4().hex
