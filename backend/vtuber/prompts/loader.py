import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# backend/vtuber/prompts/loader.py -> 项目根 virtual_videochat
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SYSTEM_PROMPT_FILE = "prompts/assistant.md"
DEFAULT_PROFILE_FORM_RULES_FILE = "prompts/profile_form_rules.md"


def load_prompt_file(rel_path: str) -> str:
    """从项目根目录相对路径加载 prompt 文本（支持 .md / .txt）。"""
    path = (PROJECT_ROOT / rel_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Prompt 文件不存在: {path}")
    for encoding in ("utf-8", "utf-8-sig", "gbk"):
        try:
            text = path.read_text(encoding=encoding).strip()
            logger.debug("已加载 prompt: %s (%d 字符)", path, len(text))
            return text
        except UnicodeDecodeError:
            continue
    raise UnicodeError(f"无法解码 prompt 文件: {path}")
