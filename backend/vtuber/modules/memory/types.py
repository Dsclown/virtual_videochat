"""对话轮次记录（main.jsonl 每行一条）。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass
class ChatTurn:
    ts: str
    user: str
    assistant: str

    @classmethod
    def now(cls, user: str, assistant: str) -> ChatTurn:
        ts = datetime.now().astimezone().isoformat(timespec="milliseconds")
        return cls(ts=ts, user=user, assistant=assistant)

    def to_dict(self) -> dict[str, str]:
        return {"ts": self.ts, "user": self.user, "assistant": self.assistant}

    @classmethod
    def from_dict(cls, data: dict) -> ChatTurn:
        return cls(
            ts=str(data["ts"]),
            user=str(data["user"]),
            assistant=str(data["assistant"]),
        )

    def local_date(self) -> date:
        return datetime.fromisoformat(self.ts).astimezone().date()
