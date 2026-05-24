"""Gateway WebRTC 音视频轨（消费媒体桥接提供的帧）。"""

import fractions
import time

import av
from aiortc import MediaStreamTrack

VIDEO_CLOCK = 90_000
AUDIO_PTIME = 0.020
SAMPLE_RATE = 48_000


def black_rgb(width: int, height: int) -> tuple[bytes, int, int]:
    return (bytes(width * height * 3), width, height)


def _rgb_bytes_for_plane(data: bytes, width: int, height: int, stride: int) -> bytes:
    row_bytes = width * 3
    need = stride * height
    if len(data) == need:
        return data
    if stride == row_bytes:
        return data
    out = bytearray(need)
    for y in range(height):
        src = y * row_bytes
        dst = y * stride
        out[dst : dst + row_bytes] = data[src : src + row_bytes]
    return bytes(out)


def _rgb_to_video_frame(
    data: bytes, width: int, height: int, *, pts: int, time_base: fractions.Fraction
) -> av.VideoFrame:
    rgb = av.VideoFrame(width, height, "rgb24")
    plane = rgb.planes[0]
    plane.update(_rgb_bytes_for_plane(data, width, height, plane.line_size))
    video = rgb.reformat(format="yuv420p")
    video.pts = pts
    video.time_base = time_base
    return video


class EgressVideoTrack(MediaStreamTrack):
    kind = "video"

    def __init__(self, source):
        super().__init__()
        self._source = source
        self._start: float | None = None

    async def recv(self) -> av.VideoFrame:
        if self.readyState != "live":
            raise Exception("track ended")
        data, width, height = await self._source.wait_video_frame()
        if self._start is None:
            self._start = time.time()
        pts = int((time.time() - self._start) * VIDEO_CLOCK)
        return _rgb_to_video_frame(
            data, width, height,
            pts=pts,
            time_base=fractions.Fraction(1, VIDEO_CLOCK),
        )


class EgressAudioTrack(MediaStreamTrack):
    kind = "audio"

    def __init__(self, source):
        super().__init__()
        self._source = source
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
                import asyncio
                await asyncio.sleep(wait)

        pcm = await self._source.next_audio_chunk(samples * 2)
        frame = av.AudioFrame(format="s16", layout="mono", samples=samples)
        frame.planes[0].update(pcm)
        frame.sample_rate = SAMPLE_RATE
        frame.pts = self._timestamp
        frame.time_base = fractions.Fraction(1, SAMPLE_RATE)
        return frame
