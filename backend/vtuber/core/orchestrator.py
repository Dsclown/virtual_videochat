import asyncio
import logging
from typing import Awaitable, Callable

import numpy as np

from vtuber.app.context import ServiceContext
from vtuber.core.stages import Stage
from vtuber.modules.avatar.stream_session import AvatarStreamSession
from vtuber.modules.memory.factory import MemoryFactory
from vtuber.modules.profile.form import (
    build_form_update_instruction,
    parse_reply_with_form_and_avatar,
)
from vtuber.modules.tts.session import TtsSession
from vtuber.utils.sentence_buffer import (
    drain_complete_sentences,
    flush_remaining,
    truncate_before_json,
)

logger = logging.getLogger(__name__)

SendFn = Callable[[dict], Awaitable[None]]

ASR_USER_PREFIX = (
    "【以下为语音识别转写，可能有错字/近音误识，请结合上下文判别真实意图后再回答；"
    "口语回复与表单更新均按你理解后的含义书写】\n"
)


class ConversationOrchestrator:
    """聆听 → 思考 → 回应：只编排流程，资源由各模块 session 自管。"""

    def __init__(
        self,
        ctx: ServiceContext,
        user_id: str,
        send: SendFn,
        *,
        avatar: AvatarStreamSession | None = None,
    ):
        self._ctx = ctx
        self._user_id = user_id
        self._send = send
        self._avatar = avatar
        self._memory = MemoryFactory.create(ctx.config.memory, user_id)
        self._cancel = asyncio.Event()
        self._tts: TtsSession | None = None

    @property
    def _stopped(self) -> bool:
        return self._cancel.is_set()

    def cancel(self) -> None:
        self._cancel.set()
        if self._tts and not self._tts.closed:
            self._tts.abort()
            self._tts.cancel()

    async def _set_stage(self, stage: Stage) -> None:
        await self._send({"type": "stage", "stage": stage.value})

    async def run_turn_pcm(self, pcm: np.ndarray) -> None:
        await self._with_voice_turn(
            lambda: self._ctx.asr.transcribe_pcm(pcm),
            from_asr=True,
        )

    async def run_turn_audio(self, audio_bytes: bytes) -> None:
        await self._with_voice_turn(
            lambda: self._ctx.asr.transcribe(audio_bytes),
            from_asr=True,
        )

    async def run_turn_text(self, user_text: str) -> None:
        self._cancel.clear()
        try:
            await self._run_dialogue(user_text.strip(), from_asr=False)
        except asyncio.CancelledError:
            self.cancel()
            raise

    async def _with_voice_turn(self, transcribe, *, from_asr: bool) -> None:
        self._cancel.clear()
        try:
            await self._set_stage(Stage.LISTENING)
            if self._stopped:
                return
            try:
                user_text = await transcribe()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("ASR failed")
                if not self._stopped:
                    await self._send({"type": "error", "message": "语音识别失败"})
                    await self._set_stage(Stage.LISTENING)
                return
            if self._stopped:
                return
            await self._run_dialogue(user_text, from_asr=from_asr)
        except asyncio.CancelledError:
            self.cancel()
            raise

    async def _run_dialogue(self, user_text: str, *, from_asr: bool) -> None:
        if self._stopped or not user_text:
            if not user_text:
                await self._send({"type": "error", "message": "未识别到语音内容"})
                await self._set_stage(Stage.LISTENING)
            return

        await self._send({"type": "user_text", "text": user_text})
        await self._ctx.run_io(self._memory.append, "user", user_text)
        await self._set_stage(Stage.THINKING)

        async with TtsSession(
            self._send,
            self._ctx.tts,
            avatar=self._avatar,
            suppress_ws_audio=self._ctx.config.avatar.suppress_ws_audio,
        ) as tts:
            self._tts = tts
            full_reply = await self._stream_llm(user_text, from_asr=from_asr, tts=tts)
            if self._stopped or full_reply is None:
                tts.abort()
                return

            reply_text, form_update, avatar_raw = parse_reply_with_form_and_avatar(full_reply)
            await self._ctx.run_io(self._memory.append, "assistant", reply_text)

            updated = await self._ctx.run_io(
                self._ctx.profile.apply_update, self._user_id, form_update
            )
            await self._send({
                "type": "assistant_final",
                "profile_form": {
                    "user_profile": updated.user_profile,
                    "current_topic": updated.current_topic,
                    "historical_interests": updated.historical_interests,
                },
                "avatar": avatar_raw,
            })

            if self._stopped or not reply_text:
                if not reply_text:
                    await self._set_stage(Stage.LISTENING)
                tts.abort()
                return

        self._tts = None

        if self._stopped:
            return

        if self._avatar:
            await self._avatar.wait_playback_drained()

        await self._send({"type": "turn_done"})
        await self._set_stage(Stage.LISTENING)

    async def _stream_llm(
        self,
        user_text: str,
        *,
        from_asr: bool,
        tts: TtsSession,
    ) -> str | None:
        speech_buffer = ""
        full_reply = ""
        tts_offset = 0
        speaking = False
        messages = self._build_messages(user_text, from_asr=from_asr)

        try:
            async with self._ctx.llm.open_stream(messages) as stream:
                token_count = 0
                async for token in stream:
                    if self._stopped:
                        break
                    token_count += 1
                    if token_count == 1:
                        logger.info("LLM 首 token 到达")
                    full_reply += token
                    speech_buffer, tts_offset, speaking = await self._feed_tokens(
                        full_reply, speech_buffer, tts_offset, speaking, tts
                    )
        except asyncio.CancelledError:
            logger.info("对话任务已取消")
            raise
        except Exception:
            logger.exception("LLM failed")
            await self._send({"type": "error", "message": "对话生成失败"})
            await self._set_stage(Stage.LISTENING)
            return None

        if self._stopped:
            return None

        reply_text, _, _ = parse_reply_with_form_and_avatar(full_reply)
        speech_buffer, tts_offset, speaking = await self._sync_buffer(
            reply_text, speech_buffer, tts_offset, speaking, tts
        )
        tail = f"{speech_buffer}{reply_text[tts_offset:]}".strip()
        for sentence in flush_remaining(tail):
            speaking = await self._speak(sentence, speaking, tts)
        logger.info("LLM 流结束，共 %d 字", len(full_reply))
        return full_reply

    async def _feed_tokens(
        self,
        full_reply: str,
        speech_buffer: str,
        tts_offset: int,
        speaking: bool,
        tts: TtsSession,
    ) -> tuple[str, int, bool]:
        reply_text = truncate_before_json(full_reply)
        if len(reply_text) < tts_offset:
            for sentence in flush_remaining(speech_buffer):
                speaking = await self._speak(sentence, speaking, tts)
            tts_offset = len(reply_text)
            speech_buffer = ""
        elif len(reply_text) > tts_offset:
            speech_buffer += reply_text[tts_offset:]
            tts_offset = len(reply_text)
            completed, speech_buffer = drain_complete_sentences(speech_buffer)
            for sentence in completed:
                speaking = await self._speak(sentence, speaking, tts)
        return speech_buffer, tts_offset, speaking

    async def _sync_buffer(
        self,
        reply_text: str,
        speech_buffer: str,
        tts_offset: int,
        speaking: bool,
        tts: TtsSession,
    ) -> tuple[str, int, bool]:
        if len(reply_text) < tts_offset:
            for sentence in flush_remaining(speech_buffer):
                speaking = await self._speak(sentence, speaking, tts)
            tts_offset = len(reply_text)
            speech_buffer = ""
        return speech_buffer, tts_offset, speaking

    async def _speak(self, sentence: str, speaking: bool, tts: TtsSession) -> bool:
        if self._stopped:
            return speaking
        if not speaking:
            speaking = True
            await self._set_stage(Stage.SPEAKING)
        await tts.speak(sentence)
        return speaking

    def _build_messages(self, user_text: str, *, from_asr: bool) -> list[dict]:
        form = self._ctx.profile.load(self._user_id)
        pcfg = self._ctx.config.profile
        system = (
            f"{self._ctx.config.character.system_prompt.strip()}\n\n"
            f"{build_form_update_instruction(pcfg)}\n\n"
            f"--- 当前用户上下文表单 ---\n{form.to_prompt_block()}"
        )
        user_content = f"{ASR_USER_PREFIX}用户说：{user_text}" if from_asr else user_text
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ]
