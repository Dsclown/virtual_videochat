from typing import Awaitable, Callable

SendFn = Callable[[dict], Awaitable[None]]

# 需附带 turn_id 的消息类型（前端用于过滤过期回合）
TURN_TAG_TYPES = frozenset({
    "user_text",
    "assistant_utterance",
    "assistant_final",
    "turn_done",
    "stop_audio",
    "interrupted",
})
