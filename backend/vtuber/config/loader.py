import logging
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

import yaml

from vtuber.prompts.loader import DEFAULT_SYSTEM_PROMPT_FILE, load_prompt_file

logger = logging.getLogger(__name__)

# backend/vtuber/config/loader.py -> 项目根 virtual_videochat
PROJECT_ROOT = Path(__file__).resolve().parents[3]

_CONFIG_EXAMPLE = PROJECT_ROOT / "config.example.yaml"

_TOP_LEVEL_SECTIONS = (
    "system",
    "character",
    "llm",
    "asr",
    "tts",
    "memory",
    "profile",
    "avatar",
    "vad",
)


class ConfigError(Exception):
    """config.yaml 缺失、为空或与 schema 不一致。"""


# 以下 dataclass 仅描述结构；有效配置一律来自 config.yaml（见 load_config / _strict_dataclass）


@dataclass
class SystemConfig:
    host: str
    port: int
    vad_executor_workers: int
    io_executor_workers: int


@dataclass
class CharacterConfig:
    name: str
    system_prompt_file: str
    system_prompt: str


@dataclass
class LLMConfig:
    provider: str
    api_key: str
    base_url: str
    model: str
    temperature: float


@dataclass
class ASRConfig:
    provider: str
    model_type: str
    model_dir: str
    num_threads: int
    provider_device: str
    pool_size: int


@dataclass
class TTSConfig:
    provider: str
    voice: str


@dataclass
class MemoryConfig:
    provider: str
    storage_dir: str


@dataclass
class ProfileConfig:
    storage_dir: str
    max_interests: int
    profile_summary_min_chars: int
    profile_summary_max_chars: int
    topic_summary_max_chars: int
    interest_summary_max_chars: int


@dataclass
class IceServerConfig:
    urls: str | list[str]
    username: str | None = None
    credential: str | None = None


@dataclass
class AvatarConfig:
    provider: str
    enabled: bool
    render_engine: str
    model_name: str
    models_root: str
    server_base_url: str
    width: int
    height: int
    fps: int
    webrtc_enabled: bool
    ice_servers: list[IceServerConfig]
    ice_transport_policy: str
    model_dict_path: str
    live2d_expressions_enabled: bool
    view_scale: float


@dataclass
class SileroVADConfig:
    orig_sr: int
    target_sr: int
    prob_threshold: float
    db_threshold: int
    required_hits: int
    required_misses: int
    smoothing_window: int
    min_speech_duration_sec: float


@dataclass
class SpeechFilterConfig:
    enabled: bool
    min_rms: float
    min_rms_above_noise_ratio: float
    max_spectral_flatness: float
    skip_flatness_if_rms_above: float
    noise_floor_ema_alpha: float


@dataclass
class VADConfig:
    vad_model: str
    silero_vad: SileroVADConfig
    speech_filter: SpeechFilterConfig


@dataclass
class AppConfig:
    system: SystemConfig
    character: CharacterConfig
    llm: LLMConfig
    asr: ASRConfig
    tts: TTSConfig
    memory: MemoryConfig
    profile: ProfileConfig
    avatar: AvatarConfig
    vad: VADConfig


def _require_section(raw: dict[str, Any], name: str) -> dict[str, Any]:
    if name not in raw:
        raise ConfigError(f"config.yaml 缺少顶层配置段: {name}")
    section = raw[name]
    if not isinstance(section, dict):
        raise ConfigError(f"config.yaml 的 {name} 必须为对象")
    return section


def _strict_dataclass(
    cls: type,
    data: dict[str, Any],
    path: str,
    *,
    skip: frozenset[str] = frozenset(),
    as_dict: bool = False,
):
    """要求 data 与 dataclass 字段一一对应；配置值仅来自 yaml。"""
    if not isinstance(data, dict) or not data:
        raise ConfigError(f"{path} 必须为非空对象")
    allowed = {f.name for f in fields(cls)} - set(skip)
    extra = set(data) - allowed
    if extra:
        raise ConfigError(f"{path} 含未知配置项: {sorted(extra)}")
    missing = allowed - set(data)
    if missing:
        raise ConfigError(
            f"{path} 缺少必填项: {sorted(missing)}（请参考 {_CONFIG_EXAMPLE.name}）"
        )
    kwargs = {k: data[k] for k in allowed}
    return kwargs if as_dict else cls(**kwargs)


def _load_avatar_config(avatar_raw: dict[str, Any]) -> AvatarConfig:
    avatar_raw = dict(avatar_raw)
    if "ice_servers" not in avatar_raw:
        raise ConfigError("avatar 缺少 ice_servers")
    ice_raw = avatar_raw.pop("ice_servers")
    if not isinstance(ice_raw, list) or not ice_raw:
        raise ConfigError("avatar.ice_servers 必须为非空列表")
    ice_servers = [
        IceServerConfig(**item)
        if isinstance(item, dict)
        else IceServerConfig(urls=str(item))
        for item in ice_raw
    ]
    kwargs = _strict_dataclass(
        AvatarConfig, avatar_raw, "avatar", skip=frozenset({"ice_servers"}), as_dict=True
    )
    kwargs["ice_servers"] = ice_servers
    return AvatarConfig(**kwargs)


def _load_character_config(char_raw: dict[str, Any]) -> CharacterConfig:
    if "name" not in char_raw:
        raise ConfigError("character 缺少 name")
    if "system_prompt_file" not in char_raw and "system_prompt" not in char_raw:
        raise ConfigError(
            "character 需配置 system_prompt_file 或内联 system_prompt"
        )
    allowed = {f.name for f in fields(CharacterConfig)}
    extra = set(char_raw) - allowed
    if extra:
        raise ConfigError(f"character 含未知配置项: {sorted(extra)}")
    name = str(char_raw["name"])
    if "system_prompt_file" in char_raw:
        prompt_file = str(char_raw["system_prompt_file"])
    else:
        prompt_file = DEFAULT_SYSTEM_PROMPT_FILE
    inline = char_raw.get("system_prompt")
    if inline is not None and str(inline).strip():
        system_prompt = str(inline).strip()
    else:
        system_prompt = load_prompt_file(prompt_file)
    return CharacterConfig(
        name=name,
        system_prompt_file=prompt_file,
        system_prompt=system_prompt,
    )


def _load_vad_config(vad_raw: dict[str, Any]) -> VADConfig:
    if "vad_model" not in vad_raw:
        raise ConfigError("vad 缺少 vad_model")
    if "silero_vad" not in vad_raw:
        raise ConfigError("vad 缺少 silero_vad")
    if "speech_filter" not in vad_raw:
        raise ConfigError("vad 缺少 speech_filter")
    return VADConfig(
        vad_model=str(vad_raw["vad_model"]),
        silero_vad=_strict_dataclass(
            SileroVADConfig, vad_raw["silero_vad"], "vad.silero_vad"
        ),
        speech_filter=_strict_dataclass(
            SpeechFilterConfig, vad_raw["speech_filter"], "vad.speech_filter"
        ),
    )


def load_config(path: Path | None = None) -> AppConfig:
    path = path or (PROJECT_ROOT / "config.yaml")
    if not path.is_file():
        raise ConfigError(
            f"未找到配置文件: {path}\n"
            f"请执行: cp {_CONFIG_EXAMPLE} config.yaml"
        )

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not raw:
        raise ConfigError(f"配置文件为空或格式无效: {path}")

    missing_top = [k for k in _TOP_LEVEL_SECTIONS if k not in raw]
    if missing_top:
        raise ConfigError(
            f"config.yaml 缺少顶层配置段: {missing_top}（请参考 {_CONFIG_EXAMPLE.name}）"
        )

    cfg = AppConfig(
        system=_strict_dataclass(SystemConfig, _require_section(raw, "system"), "system"),
        character=_load_character_config(_require_section(raw, "character")),
        llm=_strict_dataclass(LLMConfig, _require_section(raw, "llm"), "llm"),
        asr=_strict_dataclass(ASRConfig, _require_section(raw, "asr"), "asr"),
        tts=_strict_dataclass(TTSConfig, _require_section(raw, "tts"), "tts"),
        memory=_strict_dataclass(MemoryConfig, _require_section(raw, "memory"), "memory"),
        profile=_strict_dataclass(ProfileConfig, _require_section(raw, "profile"), "profile"),
        avatar=_load_avatar_config(_require_section(raw, "avatar")),
        vad=_load_vad_config(_require_section(raw, "vad")),
    )
    if not cfg.llm.api_key:
        logger.warning("config.yaml 中 llm.api_key 为空，对话将无法调用大模型")
    return cfg
