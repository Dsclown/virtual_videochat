from vtuber.modules.avatar.base import AvatarModule, AvatarState


class Live2DAvatar(AvatarModule):
    """占位：非 Playwright 渲染扩展点；表情/动作用 LLM [joy] 标签 + Live2dModel。"""

    def parse_from_reply(self, full_text: str) -> tuple[str, AvatarState | None]:
        return full_text.strip(), None

    def to_ws_payload(self, state: AvatarState | None) -> dict | None:
        return None
