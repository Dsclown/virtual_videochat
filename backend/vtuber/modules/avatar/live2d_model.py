"""Live2D 模型元数据（对齐 Open-LLM-VTuber model_dict + LLM [emotion] 标签）。"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from vtuber.config.loader import PROJECT_ROOT

logger = logging.getLogger(__name__)

DEFAULT_MODEL_DICT = PROJECT_ROOT / "assets" / "live2d" / "model_dict.json"
EXPRESSION_PROMPT_FILE = (
    PROJECT_ROOT / "prompts" / "utils" / "live2d_expression_prompt.txt"
)


def resolve_model_dict_path(path: str | Path | None = None) -> Path:
    """config 中为相对路径时，相对项目根（非 backend 工作目录）。"""
    p = Path(path) if path else DEFAULT_MODEL_DICT
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    return p.resolve()


class Live2dModel:
    """解析 model_dict：LLM 的 [keyword] → 表情索引或动作组名。"""

    def __init__(
        self,
        model_name: str,
        model_dict_path: str | Path | None = None,
    ):
        self.model_dict_path = resolve_model_dict_path(model_dict_path)
        self.model_name = model_name
        self.model_info: dict[str, Any] = self._lookup_model_info(model_name)
        raw_map = self.model_info.get("emotionMap") or {}
        self.emo_map: dict[str, int | str] = {
            str(k).lower(): v for k, v in raw_map.items()
        }
        self.emo_str = " ".join(f"[{k}]," for k in self.emo_map)
        idle = self.model_info.get("idleMotionGroupName")
        self.idle_motion_group: str = "Idle" if idle is None else str(idle)
        talk = self.model_info.get("talkMotionGroupName")
        # mao_pro 等模型用空字符串组名 "" 表示默认动作组（含多条 motion）
        self.talk_motion_group: str = "Tap" if talk is None else str(talk)

    def _lookup_model_info(self, model_name: str) -> dict[str, Any]:
        if not self.model_dict_path.is_file():
            raise FileNotFoundError(f"model_dict 不存在: {self.model_dict_path}")
        data = json.loads(self.model_dict_path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError("model_dict.json 应为数组")
        for item in data:
            if isinstance(item, dict) and item.get("name") == model_name:
                logger.info("Live2D model_dict 已加载: %s", model_name)
                return item
        raise KeyError(f"{model_name} 不在 {self.model_dict_path}")

    def extract_actions(self, text: str) -> list[int | str]:
        """按出现顺序提取 [keyword] 对应的动作/表情。"""
        actions: list[int | str] = []
        lower = text.lower()
        i = 0
        while i < len(lower):
            if lower[i] != "[":
                i += 1
                continue
            for key in self.emo_map:
                tag = f"[{key}]"
                if lower[i : i + len(tag)] == tag:
                    actions.append(self.emo_map[key])
                    i += len(tag)
                    break
            else:
                i += 1
        return actions

    def remove_emotion_keywords(self, text: str) -> str:
        out = text
        lower = out.lower()
        for key in self.emo_map:
            tag = f"[{key}]"
            while True:
                idx = lower.find(tag)
                if idx < 0:
                    break
                out = out[:idx] + out[idx + len(tag) :]
                lower = out.lower()
        return out.strip()

    @staticmethod
    def load_expression_prompt(emo_str: str) -> str:
        if not EXPRESSION_PROMPT_FILE.is_file():
            return ""
        body = EXPRESSION_PROMPT_FILE.read_text(encoding="utf-8").strip()
        return body.replace("[<insert_emomap_keys>]", emo_str)
