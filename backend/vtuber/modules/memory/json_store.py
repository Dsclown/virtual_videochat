import json
import logging
from datetime import datetime

from vtuber.config.loader import MemoryConfig, PROJECT_ROOT
from vtuber.modules.memory.base import MemoryModule
from vtuber.modules.memory.types import ChatTurn
from vtuber.modules.profile.form import sanitize_user_id

logger = logging.getLogger(__name__)

CHAT_FILENAME = "main.jsonl"


class JsonFileMemory(MemoryModule):
    """每用户一份 main.jsonl：每行一轮 {ts, user, assistant}。"""

    def __init__(self, cfg: MemoryConfig, user_id: str):
        self._user_id = sanitize_user_id(user_id)
        self._user_dir = (PROJECT_ROOT / cfg.storage_dir / self._user_id).resolve()
        self._user_dir.mkdir(parents=True, exist_ok=True)
        self._path = self._user_dir / CHAT_FILENAME

    def load_today_turns(self) -> list[ChatTurn]:
        if not self._path.exists():
            return []
        today = datetime.now().astimezone().date()
        turns: list[ChatTurn] = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                turn = ChatTurn.from_dict(data)
            except (json.JSONDecodeError, KeyError, TypeError):
                logger.warning("跳过无效对话行 user=%s: %r", self._user_id, line[:120])
                continue
            if turn.local_date() == today:
                turns.append(turn)
        return turns

    def append_turn(self, user: str, assistant: str) -> ChatTurn:
        turn = ChatTurn.now(user=user, assistant=assistant)
        line = json.dumps(turn.to_dict(), ensure_ascii=False)
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        return turn

    def clear(self) -> None:
        self._path.write_text("", encoding="utf-8")
