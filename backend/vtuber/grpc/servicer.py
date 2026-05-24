"""VtuberCore gRPC 服务实现（grpc.aio）。"""

import asyncio
import logging
from concurrent import futures

import grpc

from vtuber.app.context import ServiceContext
from vtuber.core.conversation_session import CoreConversationSession, new_session_id
from vtuber.grpc.v1 import core_pb2, core_pb2_grpc

logger = logging.getLogger(__name__)


def _core_msg(session_id: str, **payload) -> core_pb2.CoreToGateway:
    msg = core_pb2.CoreToGateway(session_id=session_id)
    if "ready" in payload:
        msg.ready.CopyFrom(payload["ready"])
    elif "event" in payload:
        msg.event.CopyFrom(payload["event"])
    elif "media" in payload:
        msg.media.CopyFrom(payload["media"])
    elif "pong" in payload:
        msg.pong.CopyFrom(core_pb2.Pong())
    elif "error" in payload:
        msg.error.CopyFrom(payload["error"])
    return msg


class VtuberCoreServicer(core_pb2_grpc.VtuberCoreServicer):
    def __init__(self, ctx: ServiceContext):
        self._ctx = ctx
        self._config = ctx.config

    async def ConnectSession(self, request_iterator, context):
        out_queue: asyncio.Queue[core_pb2.CoreToGateway | None] = asyncio.Queue()
        holder: dict = {"session_id": new_session_id(), "session": None}

        async def emit_dict(msg: dict) -> None:
            sid = holder["session_id"]
            t = msg.get("type", "")
            ev = core_pb2.CoreEvent(type=t, turn_id=int(msg.get("turn_id") or 0))
            if t == "vad" and msg.get("event"):
                ev.text = str(msg["event"])
            elif msg.get("text"):
                ev.text = str(msg["text"])
            await out_queue.put(_core_msg(sid, event=ev))

        async def emit_media(media: dict) -> None:
            sid = holder["session_id"]
            pcm = media.get("pcm_s16le")
            if pcm:
                audio_only = core_pb2.MediaOut()
                audio_only.audio.pcm_s16le = pcm
                await out_queue.put(_core_msg(sid, media=audio_only))
            if "rgb24" in media:
                video_only = core_pb2.MediaOut()
                video_only.video.width = int(media["width"])
                video_only.video.height = int(media["height"])
                video_only.video.rgb24 = media["rgb24"]
                await out_queue.put(_core_msg(sid, media=video_only))

        async def reader():
            try:
                async for req in request_iterator:
                    sid = req.session_id or holder["session_id"]
                    holder["session_id"] = sid

                    if req.HasField("open"):
                        old = holder.get("session")
                        if old is not None:
                            await old.close()
                        sess = CoreConversationSession(
                            sid,
                            self._ctx,
                            self._config,
                            emit_dict,
                            emit_media,
                        )
                        holder["session"] = sess
                        info = await sess.open(req.open.user_id)
                        ready = core_pb2.SessionReady(
                            vad_enabled=info["vad_enabled"],
                            avatar_enabled=info["avatar_enabled"],
                        )
                        await out_queue.put(_core_msg(sid, ready=ready))
                        continue

                    sess: CoreConversationSession | None = holder["session"]
                    if sess is None:
                        await out_queue.put(
                            _core_msg(
                                sid,
                                error=core_pb2.Error(message="请先 open session"),
                            )
                        )
                        continue

                    if req.HasField("close"):
                        break
                    if req.HasField("ping"):
                        await out_queue.put(_core_msg(sid, pong=core_pb2.Pong()))
                        continue
                    if req.HasField("reset"):
                        await sess.reset_memory()
                        continue
                    if req.HasField("user_text"):
                        await sess.run_user_text(req.user_text.text)
                        continue
                    if req.HasField("audio"):
                        await sess.feed_pcm_f32(
                            req.audio.pcm_f32le,
                            sample_rate=req.audio.sample_rate or 16000,
                        )
            except Exception as e:
                logger.exception("ConnectSession")
                await out_queue.put(
                    _core_msg(holder["session_id"], error=core_pb2.Error(message=str(e)))
                )
            finally:
                sess = holder.get("session")
                if sess:
                    await sess.close()
                await out_queue.put(None)

        reader_task = asyncio.create_task(reader())
        try:
            while True:
                item = await out_queue.get()
                if item is None:
                    break
                yield item
        finally:
            if not reader_task.done():
                reader_task.cancel()
                try:
                    await reader_task
                except asyncio.CancelledError:
                    pass


async def serve_grpc(ctx: ServiceContext, host: str, port: int) -> grpc.aio.Server:
    server = grpc.aio.server(futures.ThreadPoolExecutor(max_workers=8))
    core_pb2_grpc.add_VtuberCoreServicer_to_server(VtuberCoreServicer(ctx), server)
    listen = f"{host}:{port}"
    server.add_insecure_port(listen)
    await server.start()
    logger.info("VtuberCore gRPC 监听 %s", listen)
    return server
