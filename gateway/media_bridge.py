"""Gateway 侧媒体缓冲：消费 Core gRPC 媒体流，供 WebRTC 拉取。"""

import asyncio

from gateway.webrtc.tracks import black_rgb


_CHUNK_BYTES = 960 * 2
# 起播前略攒缓冲，吸收 gRPC/大包视频造成的音频到达抖动
_AUDIO_PREBUFFER_BYTES = _CHUNK_BYTES * 3


class GatewayMediaBridge:
    def __init__(self) -> None:
        self._av_lock = asyncio.Lock()
        self._latest_video: tuple[bytes, int, int] | None = None
        self._video_seq = 0
        self._last_sent_seq = 0
        self._audio_buffer = bytearray()
        self._audio_playout_ready = False
        self._silent = b"\x00" * _CHUNK_BYTES

    async def push_av_frame(
        self,
        *,
        pcm_s16le: bytes | None = None,
        rgb: bytes | None = None,
        width: int = 0,
        height: int = 0,
    ) -> None:
        """写入同 tick 的音视频（与 Core MediaOut 一一对应）。"""
        if not pcm_s16le and not rgb:
            return
        async with self._av_lock:
            if pcm_s16le:
                self._audio_buffer.extend(pcm_s16le)
            if rgb:
                self._latest_video = (rgb, width, height)
                self._video_seq += 1

    async def wait_video_frame(self, timeout: float = 5.0) -> tuple[bytes, int, int]:
        """阻塞直到 Core 推送新画面；不因超时重复发送旧帧（避免 WebRTC 虚高 fps）。"""
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            async with self._av_lock:
                if self._latest_video and self._video_seq > self._last_sent_seq:
                    self._last_sent_seq = self._video_seq
                    return self._latest_video
            if asyncio.get_running_loop().time() >= deadline:
                async with self._av_lock:
                    if self._latest_video:
                        return self._latest_video
                return black_rgb(360, 360)
            await asyncio.sleep(0.005)

    async def next_audio_chunk(self, byte_len: int) -> bytes:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 0.5
        while loop.time() < deadline:
            async with self._av_lock:
                backlog = len(self._audio_buffer)
                if not self._audio_playout_ready:
                    if backlog >= _AUDIO_PREBUFFER_BYTES:
                        self._audio_playout_ready = True
                    elif loop.time() >= deadline - 0.15 and backlog >= byte_len:
                        self._audio_playout_ready = True
                if self._audio_playout_ready and backlog >= byte_len:
                    out = bytes(self._audio_buffer[:byte_len])
                    del self._audio_buffer[:byte_len]
                    return out
            await asyncio.sleep(0.002)
        return self._silent[:byte_len]

    def clear_audio(self) -> None:
        self._audio_buffer.clear()
        self._audio_playout_ready = False

    async def clear_av(self) -> None:
        async with self._av_lock:
            self._audio_buffer.clear()
            self._audio_playout_ready = False
            self._latest_video = None
            self._video_seq = 0
            self._last_sent_seq = 0
