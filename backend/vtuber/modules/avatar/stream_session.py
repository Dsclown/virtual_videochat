"""单连接 Avatar：Playwright 渲染循环 + WebRTC + TTS 口型/音频。"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from aiortc import RTCPeerConnection, RTCSessionDescription

from vtuber.config.loader import AvatarConfig
from vtuber.modules.avatar.lipsync import mp3_to_pcm48k, pcm_rms_envelope
from vtuber.modules.avatar.playwright_manager import PlaywrightManager
from vtuber.modules.avatar.live2d_model import Live2dModel
from vtuber.modules.avatar.playwright_renderer import PlaywrightRenderer
from vtuber.modules.avatar.webrtc_tracks import AvatarAudioTrack, AvatarVideoTrack, _black_rgb
from vtuber.modules.avatar.webrtc_utils import (
    attach_ice_candidate_handler,
    ice_candidate_from_payload,
    rtc_configuration_from_avatar,
    wait_ice_gathering,
)

logger = logging.getLogger(__name__)

IceSendFn = Callable[[dict], Awaitable[None]]


@dataclass
class _Utterance:
    pcm: bytes
    mouth: list[float]
    audio_pos: int = 0


@dataclass
class _Playback:
    queue: list[_Utterance] = field(default_factory=list)
    current: _Utterance | None = None
    generation: int = 0


class AvatarStreamSession:
    def __init__(
        self,
        manager: PlaywrightManager,
        cfg: AvatarConfig,
        *,
        live2d_model: Live2dModel | None = None,
        send_ice: IceSendFn | None = None,
    ):
        self._manager = manager
        self._cfg = cfg
        self._live2d = live2d_model
        self._send_ice = send_ice
        self._renderer = PlaywrightRenderer(manager, cfg)
        self._pc: RTCPeerConnection | None = None
        self._video_track: AvatarVideoTrack | None = None
        self._audio_track: AvatarAudioTrack | None = None
        self._render_task: asyncio.Task | None = None
        self._audio_prefetch_task: asyncio.Task | None = None
        self._running = False
        self._pcm_chunk_bytes = 960 * 2
        self._audio_prefetch_target = self._pcm_chunk_bytes * 25  # ~500ms 预缓冲
        self._frame_interval = 1.0 / max(1, cfg.fps)
        self._latest_rgb: tuple[bytes, int, int] | None = None
        self._last_good_rgb: tuple[bytes, int, int] | None = None
        self._frame_seq: int = 0
        self._last_sent_frame_seq: int = 0
        self._frame_lock = asyncio.Lock()
        self._mouth = 0.0
        self._playback = _Playback()
        self._playback_lock = asyncio.Lock()
        self._audio_buffer = bytearray()
        self._audio_lock = asyncio.Lock()
        self._silent_chunk = b"\x00" * (960 * 2)

    @property
    def webrtc_enabled(self) -> bool:
        return self._cfg.webrtc_enabled

    async def start(self, *, wait_ready: bool = True) -> None:
        """幂等：WebRTC 协商前启动渲染循环。"""
        if self._render_task and not self._render_task.done():
            return

        await self._renderer.start(wait_ready=wait_ready)
        self._running = True
        self._render_task = asyncio.create_task(self._render_loop())
        if not self._audio_prefetch_task or self._audio_prefetch_task.done():
            self._audio_prefetch_task = asyncio.create_task(self._audio_prefetch_loop())
        if wait_ready:
            for _ in range(120):
                if self._latest_rgb is not None:
                    break
                await asyncio.sleep(0.05)
            if self._latest_rgb is None:
                logger.warning("首帧未就绪，将重试抓帧")

    async def create_answer(self, offer_sdp: str) -> str:
        if not self.webrtc_enabled:
            raise RuntimeError("avatar.webrtc_enabled=false")
        await self.start(wait_ready=False)

        self._pc = RTCPeerConnection(rtc_configuration_from_avatar(self._cfg))
        attach_ice_candidate_handler(self._pc, self._send_ice)
        self._video_track = AvatarVideoTrack(self)
        self._audio_track = AvatarAudioTrack(self)
        self._pc.addTrack(self._video_track)
        self._pc.addTrack(self._audio_track)

        offer = RTCSessionDescription(sdp=offer_sdp, type="offer")
        await self._pc.setRemoteDescription(offer)
        answer = await self._pc.createAnswer()
        await self._pc.setLocalDescription(answer)
        await wait_ice_gathering(self._pc)
        assert self._pc.localDescription
        logger.info("WebRTC answer 已生成 (ice=%s)", self._pc.iceConnectionState)
        return self._pc.localDescription.sdp

    async def add_ice_candidate(self, raw: dict | None) -> None:
        if not self._pc:
            return
        candidate = ice_candidate_from_payload(raw or {})
        if candidate is None:
            return
        await self._pc.addIceCandidate(candidate)

    async def feed_utterance(self, mp3_bytes: bytes) -> None:
        if not mp3_bytes:
            return
        pcm, sr = await asyncio.to_thread(mp3_to_pcm48k, mp3_bytes)
        mouth = pcm_rms_envelope(pcm, sr, self._cfg.fps)
        utt = _Utterance(pcm=pcm, mouth=mouth)
        async with self._playback_lock:
            self._playback.queue.append(utt)
            queued = len(self._playback.queue) + (1 if self._playback.current else 0)
        dur_s = len(pcm) / 2 / sr
        logger.info(
            "Avatar 入队 utterance dur=%.2fs pcm=%d queue=%d",
            dur_s, len(pcm), queued,
        )

    def _playback_has_pending_locked(self) -> bool:
        pb = self._playback
        if pb.queue:
            return True
        cur = pb.current
        return cur is not None and cur.audio_pos < len(cur.pcm)

    async def playback_pending(self) -> bool:
        async with self._playback_lock:
            pending = self._playback_has_pending_locked()
        if pending:
            return True
        async with self._audio_lock:
            return len(self._audio_buffer) > 0

    async def wait_playback_drained(self, timeout: float = 180.0) -> None:
        """TTS 已全部 feed 后，等待 WebRTC PCM 队列播完（对齐 OLV frontend-playback-complete）。"""
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            if not await self.playback_pending():
                return
            await asyncio.sleep(0.05)
        logger.warning("Avatar PCM 播放 drain 超时 (%.0fs)", timeout)

    async def apply_llm_actions(self, actions: list[int | str]) -> None:
        if not actions:
            return
        await self._renderer.apply_action(actions[-1])

    async def start_talk_motion(self) -> None:
        group = self._live2d.talk_motion_group if self._live2d else "Tap"
        await self._renderer.start_random_motion(group)

    async def reset_to_idle_motion(self) -> None:
        group = self._live2d.idle_motion_group if self._live2d else "Idle"
        await self._renderer.start_random_motion(group)

    async def interrupt(self) -> None:
        async with self._playback_lock:
            self._playback.generation += 1
            self._playback.queue.clear()
            self._playback.current = None
        async with self._audio_lock:
            self._audio_buffer.clear()
        self._mouth = 0.0
        await self._renderer.set_mouth(0.0)
        await self.reset_to_idle_motion()

    async def next_video_frame(self, *, force_idle: bool = False) -> tuple[bytes, int, int] | None:
        async with self._frame_lock:
            if self._latest_rgb is None:
                return None
            return self._latest_rgb

    async def wait_video_frame(self, timeout: float = 2.0) -> tuple[bytes, int, int]:
        """仅在新抓帧（_frame_seq 前进）时返回，避免 WebRTC 重复编码同一帧导致客户端 framesDecoded 虚高。"""
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            async with self._frame_lock:
                if (
                    self._latest_rgb is not None
                    and self._frame_seq > self._last_sent_frame_seq
                ):
                    self._last_sent_frame_seq = self._frame_seq
                    self._last_good_rgb = self._latest_rgb
                    return self._latest_rgb
            if asyncio.get_running_loop().time() >= deadline:
                if self._last_good_rgb is not None:
                    return self._last_good_rgb
                return _black_rgb(self._cfg.width, self._cfg.height)
            await asyncio.sleep(0.005)

    async def next_audio_chunk(self, byte_len: int) -> bytes:
        """WebRTC recv 只读预缓冲；PCM 推进由 _audio_prefetch_loop 按实时节拍负责。"""
        deadline = asyncio.get_running_loop().time() + 0.5
        while asyncio.get_running_loop().time() < deadline:
            async with self._audio_lock:
                if len(self._audio_buffer) >= byte_len:
                    out = bytes(self._audio_buffer[:byte_len])
                    del self._audio_buffer[:byte_len]
                    return out
            await asyncio.sleep(0.002)
        logger.warning("WebRTC 音频预缓冲 underrun (%d bytes)", byte_len)
        return self._silent_chunk[:byte_len]

    async def _audio_prefetch_loop(self) -> None:
        """独立于 Playwright 渲染，按 20ms 节拍把 PCM 写入预缓冲，避免渲染卡顿吞字。"""
        chunk = self._pcm_chunk_bytes
        target = self._audio_prefetch_target
        try:
            while self._running:
                async with self._audio_lock:
                    backlog = len(self._audio_buffer)
                if backlog < target:
                    pcm = await self._pull_pcm_chunk(chunk)
                    async with self._audio_lock:
                        self._audio_buffer.extend(pcm)
                    continue
                await asyncio.sleep(0.005)
        except asyncio.CancelledError:
            raise

    async def _pull_pcm_chunk(self, size: int) -> bytes:
        parts = bytearray()
        async with self._playback_lock:
            pb = self._playback
            while len(parts) < size:
                if pb.current is None and pb.queue:
                    pb.current = pb.queue.pop(0)
                cur = pb.current
                if cur is None:
                    parts.extend(self._silent_chunk[: size - len(parts)])
                    break
                if cur.audio_pos >= len(cur.pcm):
                    pb.current = pb.queue.pop(0) if pb.queue else None
                    continue
                need = size - len(parts)
                end = min(len(cur.pcm), cur.audio_pos + need)
                parts.extend(cur.pcm[cur.audio_pos:end])
                cur.audio_pos = end
        if len(parts) < size:
            parts.extend(b"\x00" * (size - len(parts)))
        return bytes(parts)

    async def _render_loop(self) -> None:
        try:
            while self._running:
                frame_start = time.monotonic()
                try:
                    await self._advance_mouth()
                    rgb_frame = await self._renderer.capture_rgb()
                    if rgb_frame:
                        rgb_bytes, w, h = rgb_frame
                        async with self._frame_lock:
                            self._latest_rgb = (rgb_bytes, w, h)
                            self._last_good_rgb = self._latest_rgb
                            self._frame_seq += 1
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Avatar 渲染单帧失败")
                elapsed = time.monotonic() - frame_start
                await asyncio.sleep(max(0, self._frame_interval - elapsed))
        except asyncio.CancelledError:
            raise
        finally:
            self._running = False

    async def _advance_mouth(self) -> None:
        mouth = 0.0
        speaking = False
        async with self._playback_lock:
            cur = self._playback.current
            if cur and cur.mouth and cur.audio_pos < len(cur.pcm):
                speaking = True
                bytes_per_step = max(1, (48_000 // max(1, self._cfg.fps)) * 2)
                idx = min(len(cur.mouth) - 1, cur.audio_pos // bytes_per_step)
                mouth = cur.mouth[idx]

        if speaking:
            if abs(mouth - self._mouth) > 0.008:
                self._mouth = mouth
                await self._renderer.set_mouth(mouth)
        elif self._mouth > 0.008:
            self._mouth = 0.0
            await self._renderer.set_mouth(0.0)

    async def close(self) -> None:
        self._running = False
        for task in (self._render_task, self._audio_prefetch_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._render_task = None
        self._audio_prefetch_task = None
        if self._pc:
            await self._pc.close()
            self._pc = None
        await self._renderer.close()
        logger.info("AvatarStreamSession 已关闭")
