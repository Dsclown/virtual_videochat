import json

from vtuber.config.loader import MemoryConfig, PROJECT_ROOT
from vtuber.modules.memory.base import MemoryModule
from vtuber.modules.profile.form import sanitize_user_id

CHAT_FILENAME = "main.jsonl"


class JsonFileMemory(MemoryModule):
    """每用户一份 main.jsonl 对话记录（JSONL，append 只写不读）。"""

    def __init__(self, cfg: MemoryConfig, user_id: str):
        self._user_id = sanitize_user_id(user_id)
        self._user_dir = (PROJECT_ROOT / cfg.storage_dir / self._user_id).resolve()
        self._user_dir.mkdir(parents=True, exist_ok=True)
        self._path = self._user_dir / CHAT_FILENAME

    def load_messages(self) -> list[dict]:
        if not self._path.exists():
            return []
        msgs: list[dict] = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                msgs.append(json.loads(line))
        return msgs

    def save_messages(self, messages: list[dict]) -> None:
        lines = [json.dumps(m, ensure_ascii=False) for m in messages]
        self._path.write_text(
            "\n".join(lines) + ("\n" if lines else ""),
            encoding="utf-8",
        )

    def append(self, role: str, content: str) -> None:
        line = json.dumps({"role": role, "content": content}, ensure_ascii=False)
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def clear(self) -> None:
        self._path.write_text("", encoding="utf-8")
