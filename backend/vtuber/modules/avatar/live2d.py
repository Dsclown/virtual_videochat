import json

from vtuber.modules.avatar.base import AvatarModule, AvatarState


class Live2DAvatar(AvatarModule):
    """初版：解析 LLM 输出的表情 JSON，供前端 Live2D 消费。"""

    def parse_from_reply(self, full_text: str) -> tuple[str, AvatarState | None]:
        lines = full_text.strip().splitlines()
        reply_lines: list[str] = []
        state = None

        for line in lines:
            s = line.strip()
            if s.startswith("{") and s.endswith("}"):
                try:
                    data = json.loads(s)
                    state = AvatarState(
                        emotion=data.get("emotion", "neutral"),
                        gesture=data.get("gesture", "none"),
                        scene=data.get("scene", "default"),
                    )
                except json.JSONDecodeError:
                    reply_lines.append(line)
            else:
                reply_lines.append(line)

        reply = "\n".join(reply_lines).strip() or full_text.strip()
        return reply, state

    def to_ws_payload(self, state: AvatarState | None) -> dict | None:
        if not state:
            return None
        return {
            "emotion": state.emotion,
            "gesture": state.gesture,
            "scene": state.scene,
        }
