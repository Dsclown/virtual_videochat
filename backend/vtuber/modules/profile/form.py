import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from vtuber.config.loader import PROJECT_ROOT, ProfileConfig
from vtuber.modules.profile.constants import (
    DEFAULT_CURRENT_TOPIC,
    DEFAULT_USER_PROFILE,
    PROFILE_SUMMARY_MAX_CHARS,
    TOPIC_SUMMARY_MAX_CHARS,
    truncate_text,
)
from vtuber.modules.profile.interests import (
    HistoricalInterest,
    MAX_HISTORICAL_INTERESTS,
    apply_interest_updates,
    cap_interests,
    parse_interests_from_storage,
    sort_interests,
)
from vtuber.modules.profile.reply_parse import parse_reply_with_form

logger = logging.getLogger(__name__)

SAFE_USER = re.compile(r"^[\w\-]{1,64}$")

__all__ = [
    "UserProfileForm",
    "ProfileFormStore",
    "sanitize_user_id",
    "parse_reply_with_form",
]


@dataclass
class UserProfileForm:
    user_profile: str = DEFAULT_USER_PROFILE
    current_topic: str = DEFAULT_CURRENT_TOPIC
    historical_interests: list[HistoricalInterest] = field(default_factory=list)
    updated_at: str = ""

    def sorted_interests(self) -> list[HistoricalInterest]:
        return sort_interests(self.historical_interests)

    def interests_for_api(self) -> list[dict[str, Any]]:
        return [x.to_dict() for x in self.sorted_interests()]

    def to_prompt_block(self) -> str:
        sorted_items = self.sorted_interests()
        if not sorted_items:
            interests = "- （暂无）"
        else:
            lines: list[str] = []
            for i, item in enumerate(sorted_items):
                tier = item.tier_label(i)
                ts = item.last_mentioned_at or "—"
                lines.append(
                    f"{i}. [{tier}·提及{item.mention_count}次·最近 {ts}] {item.content}"
                )
            interests = "\n".join(lines)
        return (
            f"【用户画像】\n{self.user_profile}\n\n"
            f"【目前在聊话题】\n{self.current_topic}\n\n"
            f"【历史关注内容】（共 {len(sorted_items)}/{MAX_HISTORICAL_INTERESTS} 条；"
            f"排序后前 6 条为强关注，后 4 条为弱关注）\n{interests}"
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
        raw = p.read_text(encoding="utf-8").strip()
        if not raw:
            logger.warning("profile_form.json 为空，使用默认表单 user=%s", user_id)
            return UserProfileForm()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            logger.warning(
                "profile_form.json 无效 JSON，使用默认表单 user=%s: %s", user_id, e
            )
            return UserProfileForm()
        if not isinstance(data, dict):
            logger.warning("profile_form.json 根节点非对象，使用默认表单 user=%s", user_id)
            return UserProfileForm()
        interests = parse_interests_from_storage(data.get("historical_interests"))
        return UserProfileForm(
            user_profile=data.get("user_profile", DEFAULT_USER_PROFILE),
            current_topic=data.get("current_topic", DEFAULT_CURRENT_TOPIC),
            historical_interests=interests,
            updated_at=data.get("updated_at", ""),
        )

    def save(self, user_id: str, form: UserProfileForm) -> None:
        form.historical_interests = cap_interests(form.historical_interests)
        form.updated_at = datetime.now().isoformat(timespec="seconds")
        p = self._path(user_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(form)
        payload["historical_interests"] = form.interests_for_api()
        p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def apply_update(self, user_id: str, patch: dict | None) -> UserProfileForm:
        if not patch:
            return self.load(user_id)
        form = self.load(user_id)
        if "user_profile" in patch and patch["user_profile"]:
            form.user_profile = truncate_text(
                str(patch["user_profile"]),
                PROFILE_SUMMARY_MAX_CHARS,
            )
        if "current_topic" in patch and patch["current_topic"]:
            form.current_topic = truncate_text(
                str(patch["current_topic"]),
                TOPIC_SUMMARY_MAX_CHARS,
            )
        updates = patch.get("historical_interest_updates")
        if isinstance(updates, list) and updates:
            form.historical_interests = apply_interest_updates(
                form.historical_interests,
                updates,
            )
        self.save(user_id, form)
        return form
