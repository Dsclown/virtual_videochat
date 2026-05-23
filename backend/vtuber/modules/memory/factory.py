from vtuber.config.loader import MemoryConfig
from vtuber.modules.memory.base import MemoryModule
from vtuber.modules.memory.json_store import JsonFileMemory


class MemoryFactory:
    @staticmethod
    def create(cfg: MemoryConfig, user_id: str) -> MemoryModule:
        if cfg.provider != "json_file":
            raise ValueError(f"初版仅支持 memory.provider=json_file，当前: {cfg.provider}")
        return JsonFileMemory(cfg, user_id)
