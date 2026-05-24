"""Gateway → Core gRPC 客户端。"""

import asyncio
import logging
import struct
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any
from uuid import uuid4

import grpc

from gateway.grpc.v1 import core_pb2, core_pb2_grpc
from gateway.settings import CORE_GRPC_TARGET, PLATFORM_WEB_TEST

logger = logging.getLogger(__name__)

EventHandler = Callable[[core_pb2.CoreToGateway], Awaitable[None]]


class CoreGrpcClient:
    def __init__(self, session_id: str | None = None):
        self.session_id = session_id or uuid4().hex
        self._channel: grpc.aio.Channel | None = None
        self._stream = None
        self._out_queue: asyncio.Queue[core_pb2.GatewayToCore | None] = asyncio.Queue()
        self._reader_task: asyncio.Task[Any] | None = None
        self._on_message: EventHandler | None = None

    async def connect(self, on_message: EventHandler) -> None:
        self._on_message = on_message
        self._channel = grpc.aio.insecure_channel(CORE_GRPC_TARGET)
        stub = core_pb2_grpc.VtuberCoreStub(self._channel)
        self._stream = stub.ConnectSession(self._out_iter())
        self._reader_task = asyncio.create_task(self._read_loop())

    async def _out_iter(self) -> AsyncIterator[core_pb2.GatewayToCore]:
        while True:
            msg = await self._out_queue.get()
            if msg is None:
                return
            yield msg

    async def _read_loop(self) -> None:
        assert self._stream is not None and self._on_message
        try:
            async for item in self._stream:
                await self._on_message(item)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Core gRPC 读流结束")

    def _gw(self, **payload) -> core_pb2.GatewayToCore:
        msg = core_pb2.GatewayToCore(session_id=self.session_id)
        if "open" in payload:
            msg.open.CopyFrom(payload["open"])
        elif "audio" in payload:
            msg.audio.CopyFrom(payload["audio"])
        elif "close" in payload:
            msg.close.CopyFrom(core_pb2.CloseSession())
        elif "ping" in payload:
            msg.ping.CopyFrom(core_pb2.Ping())
        elif "reset" in payload:
            msg.reset.CopyFrom(core_pb2.ResetMemory())
        elif "user_text" in payload:
            msg.user_text.CopyFrom(payload["user_text"])
        return msg

    async def open_session(self, user_id: str) -> None:
        await self._out_queue.put(
            self._gw(
                open=core_pb2.OpenSession(user_id=user_id, platform=PLATFORM_WEB_TEST),
            )
        )

    async def send_pcm_f32(self, samples: list[float], sample_rate: int = 16000) -> None:
        if not samples:
            return
        pcm = struct.pack(f"<{len(samples)}f", *samples)
        await self._out_queue.put(
            self._gw(
                audio=core_pb2.AudioPcm(sample_rate=sample_rate, pcm_f32le=pcm),
            )
        )

    async def send_user_text(self, text: str) -> None:
        await self._out_queue.put(
            self._gw(user_text=core_pb2.UserText(text=text)),
        )

    async def reset_memory(self) -> None:
        await self._out_queue.put(self._gw(reset=core_pb2.ResetMemory()))

    async def close(self) -> None:
        await self._out_queue.put(self._gw(close=core_pb2.CloseSession()))
        await self._out_queue.put(None)
        if self._reader_task:
            await self._reader_task
        if self._channel:
            await self._channel.close()
