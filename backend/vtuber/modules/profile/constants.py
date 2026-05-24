"""用户表单：字数上限与默认占位（与 prompts/profile_form_rules.md 一致）。"""

PROFILE_SUMMARY_MAX_CHARS = 280
TOPIC_SUMMARY_MAX_CHARS = 120

DEFAULT_USER_PROFILE = (
    "（暂无画像：对话后请写 2～4 句人物侧写，含性格、喜好与厌恶、长期兴趣、重要事实等）"
)
DEFAULT_CURRENT_TOPIC = "（暂无：请用 1～2 句描述当前在聊内容及背景）"


def truncate_text(text: str, max_chars: int) -> str:
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"
