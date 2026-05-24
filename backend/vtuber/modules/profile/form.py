import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from vtuber.config.loader import PROJECT_ROOT, ProfileConfig

SAFE_USER = re.compile(r"^[\w\-]{1,64}$")


@dataclass
class UserProfileForm:
    user_profile: str = "（暂无画像：对话后请补充 2～4 句摘要，含身份、偏好、沟通习惯等）"
    current_topic: str = "（暂无：请用 1～2 句描述当前在聊内容及背景）"
    historical_interests: list[str] = field(default_factory=list)
    updated_at: str = ""

    def to_prompt_block(self) -> str:
        interests = "\n".join(f"- {x}" for x in self.historical_interests) or "- （暂无）"
        return (
            f"【用户画像】\n{self.user_profile}\n\n"
            f"【目前在聊话题】\n{self.current_topic}\n\n"
            f"【历史关注内容】\n{interests}"
        )


def sanitize_user_id(user_id: str) -> str:
    uid = (user_id or "").strip()
    if not uid or not SAFE_USER.match(uid):
        raise ValueError("用户 ID 仅允许字母、数字、下划线、横线，最长 64 字符")
    return uid


class ProfileFormStore:
    def __init__(self, cfg: ProfileConfig):
        self._cfg = cfg
        self._base = (PROJECT_ROOT / cfg.storage_dir).resolve()
        self._base.mkdir(parents=True, exist_ok=True)

    def _path(self, user_id: str) -> Path:
        return self._base / sanitize_user_id(user_id) / "profile_form.json"

    def load(self, user_id: str) -> UserProfileForm:
        p = self._path(user_id)
        if not p.exists():
            return UserProfileForm()
        data = json.loads(p.read_text(encoding="utf-8"))
        return UserProfileForm(
            user_profile=data.get(
                "user_profile",
                "（暂无画像：对话后请补充 2～4 句摘要，含身份、偏好、沟通习惯等）",
            ),
            current_topic=data.get(
                "current_topic",
                "（暂无：请用 1～2 句描述当前在聊内容及背景）",
            ),
            historical_interests=list(data.get("historical_interests") or [])[: self._cfg.max_interests],
            updated_at=data.get("updated_at", ""),
        )

    def save(self, user_id: str, form: UserProfileForm) -> None:
        form.historical_interests = form.historical_interests[: self._cfg.max_interests]
        form.updated_at = datetime.now().isoformat(timespec="seconds")
        p = self._path(user_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(asdict(form), ensure_ascii=False, indent=2), encoding="utf-8")

    def apply_update(self, user_id: str, patch: dict | None) -> UserProfileForm:
        if not patch:
            return self.load(user_id)
        form = self.load(user_id)
        if "user_profile" in patch and patch["user_profile"]:
            form.user_profile = _truncate(
                str(patch["user_profile"]),
                self._cfg.profile_summary_max_chars,
            )
        if "current_topic" in patch and patch["current_topic"]:
            form.current_topic = _truncate(
                str(patch["current_topic"]),
                self._cfg.topic_summary_max_chars,
            )
        if "historical_interests" in patch and isinstance(patch["historical_interests"], list):
            cleaned = [
                _truncate(str(x).strip(), self._cfg.interest_summary_max_chars)
                for x in patch["historical_interests"]
                if str(x).strip()
            ]
            form.historical_interests = cleaned[: self._cfg.max_interests]
        self.save(user_id, form)
        return form


def _truncate(text: str, max_chars: int) -> str:
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def build_form_update_instruction(cfg: ProfileConfig) -> str:
    return f"""
每轮回复末尾单独一行输出 JSON（无 markdown），用于更新用户上下文表单；不需要更新时 form_update 为 null。
格式：
{{"form_update":{{"user_profile":"...","current_topic":"...","historical_interests":["..."]}}}}

【重要】表单字段是给人看的「摘要」，不是标签或小标题：
- user_profile：2～4 句连贯摘要（约 {cfg.profile_summary_min_chars}～{cfg.profile_summary_max_chars} 字），概括对方是谁、长期偏好、沟通风格、已知重要事实；禁止只写「喜欢游戏」「上班族」这类短语。
- current_topic：1～2 句（不超过 {cfg.topic_summary_max_chars} 字），说明此刻在聊什么、聊到哪一步、相关背景；禁止只写「排位」「天气」等词。
- historical_interests：完整替换列表，最多 {cfg.max_interests} 条；每条为一行主题摘要（约 20～{cfg.interest_summary_max_chars} 字），写清「曾聊过什么 + 要点」，例如「曾咨询川泰美食，关注口味与位置」；禁止只写「饮食」「游戏」等单词。
- 若本轮用户话来自语音识别且存在近音误识，form_update 请按你理解后的真实含义书写，勿照抄明显错字（如「川泰」若语境是美食应写「川菜」）。
- 有实质新信息时再更新；无变化则 form_update 为 null。
- form_update 各字段可选，只写需要更新的项；historical_interests 合并去重，保留最近、最有代表性的主题。
- 口语回复写在 JSON 之前，保持简短；表单更新不受口语字数限制。
- 口语中禁止朗读、复述 form_update JSON 或用户表单字段名与内容（表单仅写入 JSON，不念给用户听）。
""".strip()


def parse_reply_with_form(full_text: str) -> tuple[str, dict | None]:
    """分离口语回复与 form_update JSON。"""
    lines = full_text.strip().splitlines()
    reply_lines: list[str] = []
    form_update = None

    for line in lines:
        s = line.strip()
        if s.startswith("{") and s.endswith("}"):
            try:
                data = json.loads(s)
                if "form_update" in data:
                    fu = data.get("form_update")
                    form_update = fu if isinstance(fu, dict) else None
            except json.JSONDecodeError:
                reply_lines.append(line)
        else:
            reply_lines.append(line)

    reply = "\n".join(reply_lines).strip() or full_text.strip()
    return reply, form_update
