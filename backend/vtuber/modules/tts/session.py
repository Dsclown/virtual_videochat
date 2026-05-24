"""TTS 回合会话：切句后并行合成、按序下发；``async with`` 退出时自动释放。"""

import asyncio
import logging
from typing import Awaitable, Callable

from vtuber.modules.tts.base import TTSModule
from vtuber.modules.avatar.render_session import AvatarRenderSession

logger = logging.getLogger(__name__)

SendFn = Callable[[dict], Awaitable[None]]


class TtsSession:
    """单轮 TTS 管线；编排层只需 ``async with TtsSession(...) as tts: await tts.speak(...)``。"""

    def __init__(
        self,
        send: SendFn,
        tts: TTSModule,
        *,
        avatar: AvatarRenderSession,
    ):
        self._send = send
        self._tts = tts
        self._avatar = avatar
        self._tasks: set[asyncio.Task] = set()
        self._payload_queue: asyncio.Queue[tuple[dict, int, bytes | None] | None] = asyncio.Queue()
        self._sender_task: asyncio.Task | None = None
        self._sequence = 0
        self._next_to_send = 0
        self._shutdown = False
        self._abort = False

    @property
    def closed(self) -> bool:
        return self._shutdown

    async def __aenter__(self) -> "TtsSession":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._shutdown:
            return
        if self._abort or exc_type is not None:
            self.cancel()
        else:
            await self.finish()

    def abort(self) -> None:
        """标记本轮非正常结束（编排层打断/提前退出）。"""
        self._abort = True

    async def speak(
        self,
        text: str,
        *,
        live2d_actions: list[int | str] | None = None,
    ) -> int:
        if self._shutdown:
            return -1
        text = text.strip()
        if not text:
            return -1

        seq = self._sequence
        self._sequence += 1

        if not self._sender_task or self._sender_task.done():
            self._sender_task = asyncio.create_task(self._sender_loop())

        task = asyncio.create_task(
            self._synthesize_and_queue(text, seq, live2d_actions=live2d_actions)
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return seq

    def _build_payload(
        self,
        text: str,
        seq: int,
        *,
        live2d_actions: list[int | str] | None = None,
    ) -> dict:
        payload = {
            "type": "assistant_utterance",
            "text": text,
            "index": seq,
        }
        if live2d_actions:
            payload["live2d_actions"] = live2d_actions
        return payload

    async def _synthesize_and_queue(
        self,
        text: str,
        seq: int,
        *,
        live2d_actions: list[int | str] | None = None,
    ) -> None:
        if self._shutdown:
            return
        audio: bytes | None = None
        try:
            audio = await asyncio.wait_for(self._tts.synthesize(text), timeout=45.0)
        except asyncio.TimeoutError:
            logger.warning("TTS 合成超时: %r", text[:40])
        except asyncio.CancelledError:
            if not self._shutdown:
                await self._payload_queue.put(
                    (self._build_payload(text, seq, live2d_actions=live2d_actions), seq, None)
                )
            raise
        except Exception:
            logger.exception("TTS 合成失败: %r", text[:40])

        if self._shutdown:
            return

        # 失败/超时也占位入队，避免 sender 卡在某个 seq 导致后续句永不播放（对齐 OLV silent payload）
        await self._payload_queue.put(
            (
                self._build_payload(text, seq, live2d_actions=live2d_actions),
                seq,
                audio,
            )
        )

    async def _feed_avatar_in_order(
        self, mp3: bytes | None, payload: dict
    ) -> None:
        if not mp3:
            return
        try:
            actions = payload.get("live2d_actions")
            if actions:
                await self._avatar.apply_llm_actions(actions)
            await self._avatar.start_talk_motion()
            await self._avatar.feed_utterance(mp3)
        except Exception:
            logger.exception("Avatar feed_utterance 失败")

    async def _sender_loop(self) -> None:
        buffered: dict[int, tuple[dict, bytes | None]] = {}
        try:
            while not self._shutdown:
                item = await self._payload_queue.get()
                try:
                    if item is None:
                        while self._next_to_send in buffered and not self._shutdown:
                            out_payload, out_mp3 = buffered.pop(self._next_to_send)
                            await self._feed_avatar_in_order(out_mp3, out_payload)
                            await self._send(out_payload)
                            self._next_to_send += 1
                        return
                    payload, seq, mp3 = item
                    if self._shutdown:
                        continue
                    buffered[seq] = (payload, mp3)
                    while self._next_to_send in buffered and not self._shutdown:
                        out_payload, out_mp3 = buffered.pop(self._next_to_send)
                        await self._feed_avatar_in_order(out_mp3, out_payload)
                        await self._send(out_payload)
                        self._next_to_send += 1
                finally:
                    self._payload_queue.task_done()
        except asyncio.CancelledError:
            pass
        finally:
            buffered.clear()

    async def finish(self) -> None:
        if self._shutdown:
            return
        total = self._sequence
        try:
            pending = [t for t in self._tasks if not t.done()]
            if pending:
                _, still = await asyncio.wait(pending, timeout=60.0)
                for t in still:
                    t.cancel()
                if still:
                    await asyncio.gather(*still, return_exceptions=True)
            if self._sender_task and not self._sender_task.done():
                await self._payload_queue.put(None)
                await asyncio.wait_for(self._sender_task, timeout=60.0)
        except asyncio.TimeoutError:
            logger.warning("TTS finish 超时，强制 cancel")
            self.cancel()
            return
        except asyncio.CancelledError:
            self.cancel()
            raise
        finally:
            if not self._shutdown:
                self._release(total)

    def cancel(self) -> None:
        if self._shutdown:
            return
        total = self._sequence
        self._shutdown = True
        for t in list(self._tasks):
            if not t.done():
                t.cancel()
        self._tasks.clear()
        if self._sender_task and not self._sender_task.done():
            self._sender_task.cancel()
        self._sender_task = None
        self._drain_queue()
        self._sequence = 0
        self._next_to_send = 0
        logger.debug("TTS 已取消释放 (%d 句)", total)

    def _release(self, total: int) -> None:
        self._shutdown = True
        self._tasks.clear()
        self._sender_task = None
        self._drain_queue()
        self._sequence = 0
        self._next_to_send = 0
        logger.debug("TTS 回合资源已释放 (%d 句)", total)

    def _drain_queue(self) -> None:
        while True:
            try:
                self._payload_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            else:
                try:
                    self._payload_queue.task_done()
                except ValueError:
                    pass
