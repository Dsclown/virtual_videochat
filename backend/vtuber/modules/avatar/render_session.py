"""单连接 Avatar 渲染：Playwright + TTS 口型（无 WebRTC，媒体由 Gateway 拉取或推送）。"""

import asyncio
import logging
import time
from dataclasses import dataclass, field

from vtuber.config.loader import AvatarConfig
from vtuber.modules.avatar.lipsync import mp3_to_pcm48k, pcm_rms_envelope
from vtuber.modules.avatar.playwright_manager import PlaywrightManager
from vtuber.modules.avatar.live2d_model import Live2dModel
from vtuber.modules.avatar.playwright_renderer import PlaywrightRenderer
from vtuber.modules.avatar.frame_util import black_rgb

logger = logging.getLogger(__name__)


@dataclass
class _Utterance:
    pcm: bytes
    mouth: list[float]
    prefetch_pos: int = 0
    play_pos: int = 0


@dataclass
class _Playback:
    queue: list[_Utterance] = field(default_factory=list)
    play_index: int = 0
    prefetch_index: int = 0
    generation: int = 0


class AvatarRenderSession:
    """核心侧 Live2D 渲染与 TTS PCM 队列；Gateway 通过 wait_video_frame / next_audio_chunk 消费。"""

    def __init__(
        self,
        manager: PlaywrightManager,
        cfg: AvatarConfig,
        *,
        live2d_model: Live2dModel | None = None,
    ):
        self._manager = manager
        self._cfg = cfg
        self._live2d = live2d_model
        self._renderer = PlaywrightRenderer(manager, cfg)
        self._render_task: asyncio.Task | None = None
        self._running = False
        self._pcm_chunk_bytes = 960 * 2
        self._frame_interval = 1.0 / max(1, cfg.fps)
        self._latest_rgb: tuple[bytes, int, int] | None = None
        self._last_good_rgb: tuple[bytes, int, int] | None = None
        self._frame_seq: int = 0
        self._last_sent_frame_seq: int = 0
        self._frame_lock = asyncio.Lock()
        self._mouth = 0.0
        self._mouth_target = 0.0
        self._talk_motion_active = False
        self._playback = _Playback()
        self._playback_lock = asyncio.Lock()
        self._audio_buffer = bytearray()
        self._audio_lock = asyncio.Lock()
        self._silent_chunk = b"\x00" * (960 * 2)

    async def start(self, *, wait_ready: bool = True) -> None:
        if self._render_task and not self._render_task.done():
            return
        await self._renderer.start(wait_ready=wait_ready)
        self._running = True
        self._render_task = asyncio.create_task(self._render_loop())
        if wait_ready:
            for _ in range(120):
                if self._latest_rgb is not None:
                    break
                await asyncio.sleep(0.05)

    async def feed_utterance(self, mp3_bytes: bytes) -> None:
        if not mp3_bytes:
            return
        pcm, sr = await asyncio.to_thread(mp3_to_pcm48k, mp3_bytes)
        mouth = pcm_rms_envelope(pcm, sr, self._cfg.fps)
        utt = _Utterance(pcm=pcm, mouth=mouth)
        async with self._playback_lock:
            self._playback.queue.append(utt)

    def _play_utterance_locked(self) -> _Utterance | None:
        pb = self._playback
        if pb.play_index >= len(pb.queue):
            return None
        return pb.queue[pb.play_index]

    def _utterance_playback_pending_locked(self) -> bool:
        cur = self._play_utterance_locked()
        return cur is not None and cur.play_pos < len(cur.pcm)

    async def playback_pending(self) -> bool:
        async with self._playback_lock:
            if self._utterance_playback_pending_locked():
                return True
        async with self._audio_lock:
            return len(self._audio_buffer) > 0

    async def wait_playback_drained(self, timeout: float = 180.0) -> None:
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            if not await self.playback_pending():
                return
            await asyncio.sleep(0.05)

    async def apply_llm_actions(self, actions: list[int | str]) -> None:
        if not actions:
            return
        await self._renderer.apply_action(actions[-1])

    async def start_talk_motion(self) -> None:
        if self._talk_motion_active:
            return
        group = self._live2d.talk_motion_group if self._live2d else "Tap"
        await self._renderer.start_random_motion(group)
        self._talk_motion_active = True

    async def reset_to_idle_motion(self) -> None:
        group = self._live2d.idle_motion_group if self._live2d else "Idle"
        await self._renderer.start_random_motion(group)

    async def stop_playback(self) -> None:
        """停播：清队列/缓冲/口型（对齐旧版 stop_audio），不 bump 回合。"""
        async with self._playback_lock:
            self._playback.generation += 1
            self._playback.queue.clear()
            self._playback.play_index = 0
            self._playback.prefetch_index = 0
        async with self._audio_lock:
            self._audio_buffer.clear()
        self._mouth = 0.0
        self._mouth_target = 0.0
        self._talk_motion_active = False
        await self._renderer.set_mouth(0.0)
        await self.reset_to_idle_motion()

    async def interrupt(self) -> None:
        await self.stop_playback()

    async def latest_video_frame(self) -> tuple[bytes, int, int]:
        async with self._frame_lock:
            if self._last_good_rgb is not None:
                return self._last_good_rgb
            if self._latest_rgb is not None:
                return self._latest_rgb
        return black_rgb(self._cfg.width, self._cfg.height)

    async def try_take_video_frame(self) -> tuple[bytes, int, int] | None:
        """仅在新抓帧时返回，避免媒体泵按 20ms 重复发送同一画面。"""
        async with self._frame_lock:
            if (
                self._latest_rgb is not None
                and self._frame_seq > self._last_sent_frame_seq
            ):
                self._last_sent_frame_seq = self._frame_seq
                self._last_good_rgb = self._latest_rgb
                return self._latest_rgb
        return None

    async def wait_video_frame(self, timeout: float = 2.0) -> tuple[bytes, int, int]:
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
                return black_rgb(self._cfg.width, self._cfg.height)
            await asyncio.sleep(0.005)

    async def next_audio_chunk(self, byte_len: int) -> bytes:
        """按 WebRTC 节拍拉取；仅在此时从 TTS 队列取 PCM（对齐旧版 AvatarAudioTrack.recv）。"""
        deadline = asyncio.get_running_loop().time() + 0.5
        while asyncio.get_running_loop().time() < deadline:
            need = 0
            async with self._audio_lock:
                backlog = len(self._audio_buffer)
                if backlog < byte_len:
                    need = byte_len - backlog
            if need > 0:
                extra = await self._pull_pcm_chunk(need)
                async with self._audio_lock:
                    self._audio_buffer.extend(extra)
            out: bytes | None = None
            async with self._audio_lock:
                if len(self._audio_buffer) >= byte_len:
                    out = bytes(self._audio_buffer[:byte_len])
                    del self._audio_buffer[:byte_len]
            if out is not None:
                await self._advance_play_pos(len(out))
                await self._update_mouth_target()
                return out
            await asyncio.sleep(0.002)
        return self._silent_chunk[:byte_len]

    async def _pull_pcm_chunk(self, size: int) -> bytes:
        parts = bytearray()
        async with self._playback_lock:
            pb = self._playback
            while len(parts) < size:
                if pb.prefetch_index >= len(pb.queue):
                    parts.extend(self._silent_chunk[: size - len(parts)])
                    break
                cur = pb.queue[pb.prefetch_index]
                if cur.prefetch_pos >= len(cur.pcm):
                    pb.prefetch_index += 1
                    continue
                need = size - len(parts)
                end = min(len(cur.pcm), cur.prefetch_pos + need)
                parts.extend(cur.pcm[cur.prefetch_pos:end])
                cur.prefetch_pos = end
        if len(parts) < size:
            parts.extend(b"\x00" * (size - len(parts)))
        return bytes(parts)

    async def _render_loop(self) -> None:
        try:
            while self._running:
                frame_start = time.monotonic()
                try:
                    await self._update_mouth_target()
                    await self._apply_mouth_to_renderer()
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

    async def _advance_play_pos(self, nbytes: int) -> None:
        if nbytes <= 0:
            return
        remaining = nbytes
        async with self._playback_lock:
            pb = self._playback
            while remaining > 0 and pb.play_index < len(pb.queue):
                cur = pb.queue[pb.play_index]
                left = len(cur.pcm) - cur.play_pos
                if left <= 0:
                    pb.play_index += 1
                    continue
                step = min(remaining, left)
                cur.play_pos += step
                remaining -= step
                if cur.play_pos >= len(cur.pcm):
                    pb.play_index += 1

    async def _update_mouth_target(self) -> None:
        """按 play_pos 更新目标口型（不碰 Playwright，避免拖慢 20ms 音频泵）。"""
        mouth = 0.0
        async with self._playback_lock:
            cur = self._play_utterance_locked()
            if cur and cur.mouth and cur.play_pos < len(cur.pcm):
                bytes_per_step = max(1, (48_000 // max(1, self._cfg.fps)) * 2)
                idx = min(len(cur.mouth) - 1, cur.play_pos // bytes_per_step)
                mouth = cur.mouth[idx]
        self._mouth_target = mouth

    async def _apply_mouth_to_renderer(self) -> None:
        """仅在抓帧前写入 Live2D（约 fps 次/秒），避免每 20ms 一次 CDP。"""
        if abs(self._mouth_target - self._mouth) > 0.008:
            self._mouth = self._mouth_target
            await self._renderer.set_mouth(self._mouth)
        elif self._mouth > 0.008 and self._mouth_target <= 0.008:
            self._mouth = 0.0
            await self._renderer.set_mouth(0.0)

    async def close(self) -> None:
        self._running = False
        if self._render_task and not self._render_task.done():
            self._render_task.cancel()
            try:
                await self._render_task
            except asyncio.CancelledError:
                pass
        self._render_task = None
        await self._renderer.close()
