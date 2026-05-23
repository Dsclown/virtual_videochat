"""WebRTC 音视频轨：Playwright 帧 + TTS PCM。"""

import asyncio
import fractions
import logging
import time

import av
from aiortc import MediaStreamTrack

logger = logging.getLogger(__name__)

VIDEO_PTIME = 1 / 30
AUDIO_PTIME = 0.020  # 20ms
VIDEO_CLOCK = 90_000
SAMPLE_RATE = 48_000


def _black_rgb(width: int, height: int) -> tuple[bytes, int, int]:
    return (bytes(width * height * 3), width, height)


def _rgb_to_video_frame(
    data: bytes, width: int, height: int, *, pts: int, time_base: fractions.Fraction
) -> av.VideoFrame:
    rgb = av.VideoFrame(width, height, "rgb24")
    rgb.planes[0].update(data)
    video = rgb.reformat(format="yuv420p")
    video.pts = pts
    video.time_base = time_base
    return video


class AvatarVideoTrack(MediaStreamTrack):
    kind = "video"

    def __init__(self, session: "AvatarStreamSession"):
        super().__init__()
        self._session = session
        self._start: float | None = None

    async def recv(self) -> av.VideoFrame:
        if self.readyState != "live":
            raise Exception("track ended")

        frame_rgb = await self._session.wait_video_frame()
        data, width, height = frame_rgb

        if self._start is None:
            self._start = time.time()
        pts = int((time.time() - self._start) * VIDEO_CLOCK)
        time_base = fractions.Fraction(1, VIDEO_CLOCK)
        return _rgb_to_video_frame(data, width, height, pts=pts, time_base=time_base)


class AvatarAudioTrack(MediaStreamTrack):
    kind = "audio"

    def __init__(self, session: "AvatarStreamSession"):
        super().__init__()
        self._session = session
        self._start: float | None = None
        self._timestamp = 0

    async def recv(self) -> av.AudioFrame:
        if self.readyState != "live":
            raise Exception("track ended")

        samples = int(SAMPLE_RATE * AUDIO_PTIME)
        if self._start is None:
            self._start = time.time()
            self._timestamp = 0
        else:
            self._timestamp += samples
            wait = self._start + (self._timestamp / SAMPLE_RATE) - time.time()
            if wait > 0:
                await asyncio.sleep(wait)

        pcm = await self._session.next_audio_chunk(samples * 2)
        frame = av.AudioFrame(format="s16", layout="mono", samples=samples)
        frame.planes[0].update(pcm)
        frame.sample_rate = SAMPLE_RATE
        frame.pts = self._timestamp
        frame.time_base = fractions.Fraction(1, SAMPLE_RATE)
        return frame


# 避免循环 import 的类型提示
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from vtuber.modules.avatar.stream_session import AvatarStreamSession
