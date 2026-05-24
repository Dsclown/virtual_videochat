"""Web 测试端：WebSocket + WebRTC。"""

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket

from gateway.auth import sanitize_user_id
from gateway.config import GatewayConfig, ice_servers_for_browser
from gateway.core_client import CoreGrpcClient
from gateway.grpc.v1 import core_pb2
from gateway.media_bridge import GatewayMediaBridge
from gateway.webrtc_egress import GatewayWebRtcEgress

logger = logging.getLogger(__name__)

_AUDIO_QUEUE_MAX = 16
TARGET_SR = 16000

_WS_EVENT_TYPES = frozenset({
    "user_text",
    "assistant_utterance",
    "assistant_final",
    "turn_done",
    "turn_cancelled",
    "error",
    "vad",
    "reset_ok",
})


class WebGatewaySession:
    def __init__(self, ws: WebSocket, config: GatewayConfig):
        self._ws = ws
        self._config = config
        self._core = CoreGrpcClient()
        self._media = GatewayMediaBridge()
        self._webrtc: GatewayWebRtcEgress | None = None
        self._user_id: str | None = None
        self._authed = False
        self._mic_enabled = True
        self._avatar_enabled = False
        self._outbox: asyncio.Queue[dict | None] = asyncio.Queue()
        self._audio_in: asyncio.Queue[dict | None] = asyncio.Queue(maxsize=_AUDIO_QUEUE_MAX)
        self._writer_task: asyncio.Task[Any] | None = None
        self._audio_task: asyncio.Task[Any] | None = None

    async def run(self) -> None:
        self._writer_task = asyncio.create_task(self._write_loop())
        self._audio_task = asyncio.create_task(self._audio_forward_loop())
        await self.send({"type": "await_auth"})
        await self._core.connect(self._on_core_message)
        try:
            while True:
                raw = await self._ws.receive()
                if raw["type"] == "websocket.disconnect":
                    break
                if "text" in raw and raw["text"]:
                    data = json.loads(raw["text"])
                    if data.get("type") == "raw_audio":
                        if self._mic_enabled and self._authed:
                            self._enqueue_audio(data)
                        continue
                    await self._handle_text(data)
        finally:
            await self._shutdown()

    async def _shutdown(self) -> None:
        if self._webrtc:
            await self._webrtc.close()
        await self._core.close()
        await self._audio_in.put(None)
        await self._outbox.put(None)
        if self._audio_task:
            await self._audio_task
        if self._writer_task:
            await self._writer_task

    async def _write_loop(self) -> None:
        while True:
            msg = await self._outbox.get()
            try:
                if msg is None:
                    return
                await self._ws.send_text(json.dumps(msg, ensure_ascii=False))
            except Exception:
                logger.exception("Gateway WS 发送失败")
            finally:
                self._outbox.task_done()

    async def send(self, msg: dict) -> None:
        await self._outbox.put(msg)

    async def _on_core_message(self, msg: core_pb2.CoreToGateway) -> None:
        if msg.HasField("ready"):
            await self._on_session_ready(msg.ready)
            return
        if msg.HasField("error"):
            await self.send({"type": "error", "message": msg.error.message})
            return
        if msg.HasField("media"):
            m = msg.media
            pcm = m.audio.pcm_s16le if m.HasField("audio") else None
            video = m.video if m.HasField("video") and m.video.rgb24 else None
            await self._media.push_av_frame(
                pcm_s16le=pcm,
                rgb=video.rgb24 if video else None,
                width=video.width if video else 0,
                height=video.height if video else 0,
            )
            return
        if msg.HasField("event"):
            await self._forward_core_event(msg.event)

    async def _forward_core_event(self, ev: core_pb2.CoreEvent) -> None:
        if ev.type not in _WS_EVENT_TYPES:
            return
        payload: dict = {"type": ev.type}
        if ev.turn_id:
            payload["turn_id"] = ev.turn_id
        if ev.type == "vad" and ev.text:
            payload["event"] = ev.text
        elif ev.text:
            payload["text"] = ev.text
        if ev.type == "vad" and ev.text == "speech_start" and self._webrtc:
            self._webrtc.on_turn_cancelled()
        if ev.type == "turn_cancelled" and self._webrtc:
            self._webrtc.on_turn_cancelled()
        await self.send(payload)

    async def _handle_text(self, data: dict) -> None:
        t = data.get("type")
        if t == "auth":
            try:
                self._user_id = sanitize_user_id(data.get("user_id", ""))
            except ValueError as e:
                await self.send({"type": "error", "message": str(e)})
                return
            await self._core.open_session(self._user_id)
            return
        if not self._authed:
            await self.send({"type": "error", "message": "请先登录"})
            return
        if t == "ping":
            await self.send({"type": "pong"})
        elif t == "reset":
            await self._core.reset_memory()
        elif t == "mic_state":
            self._mic_enabled = bool(data.get("enabled", True))
        elif t == "user_text":
            await self._core.send_user_text(data.get("text") or "")
        elif t == "webrtc_offer":
            await self._webrtc_offer(data)
        elif t == "webrtc_ice" and self._webrtc:
            await self._webrtc.add_ice_candidate(data.get("candidate"))

    async def _on_session_ready(self, ready: core_pb2.SessionReady) -> None:
        self._authed = True
        self._avatar_enabled = ready.avatar_enabled
        av = self._config.avatar
        await self.send({
            "type": "auth_ok",
            "user_id": self._user_id,
            "vad_enabled": ready.vad_enabled,
            "avatar_enabled": ready.avatar_enabled,
            "avatar_webrtc": ready.avatar_enabled and av.webrtc_enabled,
            "ice_servers": ice_servers_for_browser(av),
            "ice_transport_policy": av.ice_transport_policy,
        })

    async def _webrtc_offer(self, data: dict) -> None:
        if not self._avatar_enabled:
            await self.send({"type": "error", "message": "Avatar 未启用"})
            return
        sdp = (data.get("sdp") or "").strip()
        if not sdp:
            await self.send({"type": "error", "message": "webrtc_offer 缺少 sdp"})
            return
        try:
            if self._webrtc is None:
                self._webrtc = GatewayWebRtcEgress(
                    self._config.avatar,
                    self._media,
                    send_ice=self.send,
                )
            answer = await self._webrtc.create_answer(sdp)
            await self.send({"type": "webrtc_answer", "sdp": answer})
        except Exception as e:
            logger.exception("WebRTC 协商失败")
            await self.send({"type": "error", "message": f"Avatar 视频流失败: {e}"})

    def _enqueue_audio(self, data: dict) -> None:
        try:
            self._audio_in.put_nowait(data)
        except asyncio.QueueFull:
            pass

    async def _audio_forward_loop(self) -> None:
        while True:
            data = await self._audio_in.get()
            try:
                if data is None:
                    return
                chunk = data.get("audio") or []
                if chunk:
                    await self._core.send_pcm_f32(chunk, TARGET_SR)
            except Exception:
                logger.exception("转发 PCM 到 Core 失败")
            finally:
                self._audio_in.task_done()
