"""历史关注内容：提及次数、时间戳、强 6 / 弱 4 槽位与淘汰。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import logging
from datetime import datetime
from typing import Any

from vtuber.modules.profile.constants import truncate_text

logger = logging.getLogger(__name__)

# 与 prompts/profile_form_rules.md 一致
INTEREST_SUMMARY_MAX_CHARS = 80
MAX_HISTORICAL_INTERESTS = 10
STRONG_INTEREST_COUNT = 6
WEAK_INTEREST_COUNT = 4


@dataclass
class HistoricalInterest:
    content: str
    mention_count: int = 1
    last_mentioned_at: str = ""

    def tier_label(self, rank: int) -> str:
        return "强" if rank < STRONG_INTEREST_COUNT else "弱"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HistoricalInterest:
        if not isinstance(data, dict):
            raise ValueError("historical_interests 条目必须为对象")
        content = str(data.get("content", "")).strip()
        if not content:
            raise ValueError("historical_interests.content 不能为空")
        try:
            count = int(data["mention_count"])
        except (KeyError, TypeError, ValueError) as e:
            raise ValueError("historical_interests.mention_count 必须为整数") from e
        if count < 1:
            raise ValueError("historical_interests.mention_count 必须 >= 1")
        last_at = str(data.get("last_mentioned_at", "")).strip()
        if not last_at:
            raise ValueError("historical_interests.last_mentioned_at 不能为空")
        return cls(
            content=truncate_text(content, INTEREST_SUMMARY_MAX_CHARS),
            mention_count=count,
            last_mentioned_at=last_at,
        )


def interest_now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _parse_ts(ts: str) -> float:
    if not ts:
        return 0.0
    try:
        return datetime.fromisoformat(ts).timestamp()
    except ValueError:
        return 0.0


def sort_interests(items: list[HistoricalInterest]) -> list[HistoricalInterest]:
    """提及次数降序；相同则最近提及时间越新越靠前。"""
    return sorted(
        items,
        key=lambda x: (-x.mention_count, -_parse_ts(x.last_mentioned_at)),
    )


def cap_interests(items: list[HistoricalInterest]) -> list[HistoricalInterest]:
    """保留最多 10 条；超出时从排序第 7 名及以后（弱关注区）中淘汰最近提及最早的一条。"""
    items = sort_interests(items)
    while len(items) > MAX_HISTORICAL_INTERESTS:
        candidates = items[STRONG_INTEREST_COUNT:]
        if not candidates:
            items.pop()
            continue
        victim = min(
            candidates,
            key=lambda x: (_parse_ts(x.last_mentioned_at), x.mention_count),
        )
        items.remove(victim)
    return sort_interests(items)


def parse_interests_from_storage(raw: Any) -> list[HistoricalInterest]:
    """从 profile_form.json 加载；仅支持 {content, mention_count, last_mentioned_at} 对象列表。"""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("historical_interests 必须为数组")
    items: list[HistoricalInterest] = []
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict):
            logger.warning("跳过无效 historical_interests[%d]：非对象", i)
            continue
        try:
            items.append(HistoricalInterest.from_dict(entry))
        except ValueError as e:
            logger.warning("跳过无效 historical_interests[%d]：%s", i, e)
    return cap_interests(items)


def apply_interest_updates(
    existing: list[HistoricalInterest],
    updates: list[dict[str, Any]],
    *,
    now: str | None = None,
) -> list[HistoricalInterest]:
    """合并本轮 LLM 提交的 historical_interest_updates。"""
    if not updates:
        return cap_interests(list(existing))

    now = now or interest_now_iso()
    items = list(existing)
    sorted_view = sort_interests(items)

    for patch in updates:
        if not isinstance(patch, dict):
            continue
        content = str(patch.get("content", "")).strip()
        ref = patch.get("ref_index")
        if ref is not None and ref != "":
            try:
                idx = int(ref)
            except (TypeError, ValueError):
                continue
            if 0 <= idx < len(sorted_view):
                item = sorted_view[idx]
                item.mention_count += 1
                item.last_mentioned_at = now
                if content:
                    item.content = truncate_text(content, INTEREST_SUMMARY_MAX_CHARS)
            continue
        if not content:
            continue
        items.append(
            HistoricalInterest(
                content=truncate_text(content, INTEREST_SUMMARY_MAX_CHARS),
                mention_count=1,
                last_mentioned_at=now,
            )
        )
        items = cap_interests(items)
        sorted_view = sort_interests(items)

    return cap_interests(items)
