"""单 WebSocket 连接：消息路由、回合生命周期、VAD 与打断。"""

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket

from vtuber.app.context import ServiceContext
from vtuber.config.loader import AppConfig
from vtuber.core.messaging import TURN_TAG_TYPES, SendFn
from vtuber.core.orchestrator import ConversationOrchestrator
from vtuber.core.stages import Stage
from vtuber.core.vad_session import VadSession
from vtuber.modules.avatar.stream_session import AvatarStreamSession
from vtuber.modules.avatar.webrtc_utils import ice_servers_for_browser
from vtuber.modules.memory.factory import MemoryFactory
from vtuber.modules.profile.form import sanitize_user_id

logger = logging.getLogger(__name__)

# 音频入队上限；超出则丢帧，避免多轮后 task/线程池堆积
_AUDIO_QUEUE_MAX = 16


class VoiceChatSession:
    """一条 WebSocket 连接：出站队列 + 串行音频管线 + 回合 task 管理。"""

    def __init__(self, ws: WebSocket, ctx: ServiceContext, config: AppConfig):
        self._ws = ws
        self._ctx = ctx
        self._config = config

        self._user_id: str | None = None
        self._vad: VadSession | None = None
        self._orchestrator: ConversationOrchestrator | None = None
        self._avatar: AvatarStreamSession | None = None

        self._turn_id = 0
        self._gen = 0
        self._turn_running = False
        self._outbox: asyncio.Queue[dict | None] = asyncio.Queue()
        self._audio_in: asyncio.Queue[dict | None] = asyncio.Queue(maxsize=_AUDIO_QUEUE_MAX)
        self._writer_task: asyncio.Task[Any] | None = None
        self._audio_task: asyncio.Task[Any] | None = None
        self._tasks: set[asyncio.Task[Any]] = set()

    # ------------------------------------------------------------------ I/O

    async def run(self) -> None:
        self._writer_task = asyncio.create_task(self._write_loop())
        self._audio_task = asyncio.create_task(self._audio_loop())
        await self.send({"type": "await_auth"})
        try:
            while True:
                raw = await self._ws.receive()
                if raw["type"] == "websocket.disconnect":
                    break
                asyncio.create_task(self._safe_dispatch(raw))
        finally:
            if self._avatar:
                await self._avatar.close()
                self._avatar = None
            self.close()
            await self._audio_in.put(None)
            await self._outbox.put(None)
            if self._audio_task:
                await self._audio_task
            if self._writer_task:
                await self._writer_task

    async def _safe_dispatch(self, raw: dict) -> None:
        try:
            await self._dispatch(raw)
        except Exception:
            logger.exception("处理 WS 消息失败")

    async def _write_loop(self) -> None:
        while True:
            msg = await self._outbox.get()
            try:
                if msg is None:
                    return
                if msg.get("type") == "assistant_utterance" and msg.get("data"):
                    payload = await asyncio.to_thread(
                        json.dumps, msg, ensure_ascii=False
                    )
                    await self._ws.send_text(payload)
                else:
                    await self._ws.send_text(json.dumps(msg, ensure_ascii=False))
            except Exception:
                logger.exception("WS 文本发送失败 type=%s", msg.get("type"))
            finally:
                self._outbox.task_done()

    async def send(self, msg: dict) -> None:
        if msg.get("type") in TURN_TAG_TYPES:
            msg = {**msg, "turn_id": self._turn_id}
        if msg.get("type") == "stage" and self._vad:
            stage = msg.get("stage")
            self._vad.set_turn_active(stage in (Stage.THINKING.value, Stage.SPEAKING.value))
        await self._outbox.put(msg)

    def _gated_send(self, gen: int) -> SendFn:
        async def _send(msg: dict) -> None:
            if gen != self._gen:
                return
            await self.send(msg)

        return _send

    # ---------------------------------------------------------------- 音频管线

    async def _audio_loop(self) -> None:
        """串行处理 VAD，避免每帧 create_task 耗尽线程池。"""
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

    def _enqueue_audio(self, data: dict) -> None:
        try:
            self._audio_in.put_nowait(data)
        except asyncio.QueueFull:
            pass  # 丢弃过载帧

    # ---------------------------------------------------------------- 回合管理

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
        task.add_done_callback(self._on_turn_done)

    def _on_turn_done(self, task: asyncio.Task[Any]) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error("回合任务异常退出", exc_info=exc)

    async def _run_turn(self, coro, gen: int) -> None:
        try:
            self._orchestrator = ConversationOrchestrator(
                self._ctx, self._user_id, self._gated_send(gen), avatar=self._avatar
            )
            await coro(self._orchestrator)
            logger.info("回合完成 (gen=%d)", gen)
        except asyncio.CancelledError:
            logger.info("回合已取消 (gen=%d)", gen)
            if self._orchestrator:
                self._orchestrator.cancel()
            raise
        finally:
            self._turn_running = False

    async def interrupt(self) -> None:
        self._bump_turn()
        if self._avatar:
            await self._avatar.interrupt()
        await self.send({"type": "stop_audio"})
        self._cancel_all_tasks()
        await self.send({"type": "control", "text": "interrupt"})
        await self.send({"type": "interrupted", "stage": Stage.LISTENING.value})
        await self.send({"type": "stage", "stage": Stage.LISTENING.value})

    def close(self) -> None:
        self._gen += 1
        self._cancel_all_tasks()

    # ---------------------------------------------------------------- 消息分发

    async def _dispatch(self, raw: dict) -> None:
        if "text" in raw and raw["text"]:
            data = json.loads(raw["text"])
            if data.get("type") == "raw_audio":
                self._enqueue_audio(data)
                return
            await self._handle_text(data)

    async def _handle_text(self, data: dict) -> None:
        t = data.get("type")

        if t == "auth":
            await self._auth(data)
            return
        if not self._user_id:
            await self.send({"type": "error", "message": "请先登录（发送 auth）"})
            return

        handlers = {
            "ping": self._ping,
            "reset": self._reset,
            "interrupt": self.interrupt,
            "user_text": self._user_text,
            "webrtc_offer": self._webrtc_offer,
            "webrtc_ice": self._webrtc_ice,
        }
        if t == "control" and data.get("text") == "interrupt":
            await self.interrupt()
        elif t in handlers:
            await handlers[t](data)
        else:
            await self.send({"type": "error", "message": f"未知消息: {t}"})

    async def _auth(self, data: dict) -> None:
        try:
            self._user_id = sanitize_user_id(data.get("user_id", ""))
        except ValueError as e:
            await self.send({"type": "error", "message": str(e)})
            return

        form = self._ctx.profile.load(self._user_id)
        engine = self._ctx.new_vad_engine()
        if engine:
            sv = self._config.vad.silero_vad
            min_samples = int(sv.min_speech_duration_sec * sv.target_sr)
            self._vad = VadSession(
                engine,
                self.send,
                min_speech_samples=min_samples,
                speech_filter=self._config.vad.speech_filter,
                run_vad=self._ctx.run_vad,
            )

        await self.send({
            "type": "auth_ok",
            "user_id": self._user_id,
            "stage": Stage.LISTENING.value,
            "vad_enabled": self._vad is not None,
            "avatar_enabled": self._ctx.playwright.enabled,
            "avatar_webrtc": self._ctx.config.avatar.webrtc_enabled,
            "ice_servers": ice_servers_for_browser(self._ctx.config.avatar),
            "ice_transport_policy": self._ctx.config.avatar.ice_transport_policy,
            "profile_form": {
                "user_profile": form.user_profile,
                "current_topic": form.current_topic,
                "historical_interests": form.historical_interests,
            },
        })

    async def _webrtc_offer(self, data: dict) -> None:
        if not self._ctx.playwright.enabled:
            await self.send({"type": "error", "message": "Avatar 未启用"})
            return
        sdp = (data.get("sdp") or "").strip()
        if not sdp:
            await self.send({"type": "error", "message": "webrtc_offer 缺少 sdp"})
            return
        try:
            if self._avatar is None:
                self._avatar = AvatarStreamSession(
                    self._ctx.playwright,
                    self._ctx.config.avatar,
                    live2d_model=self._ctx.live2d_model,
                    send_ice=self.send,
                )
            answer_sdp = await self._avatar.create_answer(sdp)
            await self.send({
                "type": "webrtc_answer",
                "sdp": answer_sdp,
            })
        except Exception as e:
            logger.exception("WebRTC 协商失败")
            await self.send({"type": "error", "message": f"Avatar 视频流失败: {e}"})

    async def _webrtc_ice(self, data: dict) -> None:
        if not self._avatar:
            return
        try:
            await self._avatar.add_ice_candidate(data.get("candidate"))
        except Exception:
            logger.debug("添加 ICE candidate 失败", exc_info=True)

    async def _ping(self, _data: dict) -> None:
        await self.send({"type": "pong"})

    async def _reset(self, _data: dict) -> None:
        await self.interrupt()
        MemoryFactory.create(self._config.memory, self._user_id).clear()
        await self.send({"type": "reset_ok", "stage": Stage.LISTENING.value})

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

        pcm_data = pcm

        async def _pcm(orch: ConversationOrchestrator) -> None:
            await orch.run_turn_pcm(pcm_data)

        self._start_turn(_pcm, bump=not should_interrupt)

    async def _user_text(self, data: dict) -> None:
        text = (data.get("text") or "").strip()

        async def _text(orch: ConversationOrchestrator) -> None:
            await orch.run_turn_text(text)

        self._start_turn(_text)
