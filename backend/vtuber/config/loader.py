import logging
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

import yaml

from vtuber.prompts.loader import DEFAULT_SYSTEM_PROMPT_FILE, load_prompt_file

logger = logging.getLogger(__name__)

# backend/vtuber/config/loader.py -> 项目根 virtual_videochat
PROJECT_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class SystemConfig:
    host: str = "0.0.0.0"
    port: int = 8765
    # 初版目标 3～5 人同时在线；VAD 推理线程数（每连接 PCM 并行处理）
    vad_executor_workers: int = 4
    io_executor_workers: int = 4


@dataclass
class CharacterConfig:
    name: str = "助手"
    system_prompt_file: str = DEFAULT_SYSTEM_PROMPT_FILE
    system_prompt: str = "你是友好的虚拟助手。"


@dataclass
class LLMConfig:
    provider: str = "openai_api"
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    temperature: float = 0.8


@dataclass
class ASRConfig:
    provider: str = "sherpa_onnx"
    model_type: str = "sense_voice"
    model_dir: str = "models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17"
    num_threads: int = 2
    provider_device: str = "cpu"
    # 并行 recognizer 数量（int8 约 228MB/槽）；初版 3～5 人建议 4
    pool_size: int = 4


@dataclass
class TTSConfig:
    provider: str = "edge"
    voice: str = "zh-CN-XiaoxiaoNeural"


@dataclass
class MemoryConfig:
    provider: str = "json_file"
    storage_dir: str = "data/users"


@dataclass
class ProfileConfig:
    storage_dir: str = "data/users"
    max_interests: int = 5
    # 表单字段期望长度（写入 prompt，并对超长内容截断）
    profile_summary_min_chars: int = 40
    profile_summary_max_chars: int = 280
    topic_summary_max_chars: int = 120
    interest_summary_max_chars: int = 80


@dataclass
class IceServerConfig:
    urls: str | list[str] = "stun:stun.l.google.com:19302"
    username: str | None = None
    credential: str | None = None


def _default_ice_servers() -> list[IceServerConfig]:
    return [IceServerConfig(urls="stun:stun.l.google.com:19302")]


@dataclass
class AvatarConfig:
    provider: str = "playwright"
    enabled: bool = True
    # render-engine 子目录名，如 playwright-live2d
    render_engine: str = "playwright-live2d"
    model_name: str = "shizuku"
    models_root: str = "assets/live2d/models"
    server_base_url: str = "http://127.0.0.1:8765"
    width: int = 480
    height: int = 480
    fps: int = 20
    # webrtc：低延迟同网；websocket：走 WS 传 JPEG（SSH 隧道/跨网）；auto：先 WebRTC 失败再 WS
    video_transport: str = "auto"
    webrtc_enabled: bool = True
    # True 时 WS 不再下发 MP3，仅 WebRTC 出声（需 avatar 已连接）
    suppress_ws_audio: bool = False
    # STUN/TURN；SSH+跨网需在 coturn 部署后填写 TURN 项
    ice_servers: list[IceServerConfig] = field(default_factory=_default_ice_servers)
    # all：允许直连；relay：仅 TURN 中继（SSH 隧道访问建议 relay）
    ice_transport_policy: str = "all"


@dataclass
class SileroVADConfig:
    orig_sr: int = 16000
    target_sr: int = 16000
    prob_threshold: float = 0.4
    db_threshold: int = 60
    required_hits: int = 3
    required_misses: int = 24
    smoothing_window: int = 5
    # 短于该时长的切段不送 ASR（可过滤部分音乐瞬态误触发）
    min_speech_duration_sec: float = 0.6


@dataclass
class SpeechFilterConfig:
    enabled: bool = True
    min_rms: float = 0.015
    min_rms_above_noise_ratio: float = 2.5
    max_spectral_flatness: float = 0.62
    skip_flatness_if_rms_above: float = 0.04
    noise_floor_ema_alpha: float = 0.05


@dataclass
class VADConfig:
    vad_model: str | None = "silero_vad"
    silero_vad: SileroVADConfig = field(default_factory=SileroVADConfig)
    speech_filter: SpeechFilterConfig = field(default_factory=SpeechFilterConfig)


@dataclass
class AppConfig:
    system: SystemConfig = field(default_factory=SystemConfig)
    character: CharacterConfig = field(default_factory=CharacterConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    asr: ASRConfig = field(default_factory=ASRConfig)
    tts: TTSConfig = field(default_factory=TTSConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    profile: ProfileConfig = field(default_factory=ProfileConfig)
    avatar: AvatarConfig = field(default_factory=AvatarConfig)
    vad: VADConfig = field(default_factory=VADConfig)


def _load_avatar_config(avatar_raw: dict[str, Any]) -> AvatarConfig:
    avatar_raw = dict(avatar_raw or {})
    ice_raw = avatar_raw.pop("ice_servers", None)
    known = {f.name for f in fields(AvatarConfig)}
    cfg = AvatarConfig(**{k: v for k, v in avatar_raw.items() if k in known})
    if ice_raw:
        cfg.ice_servers = [
            IceServerConfig(**item)
            if isinstance(item, dict)
            else IceServerConfig(urls=str(item))
            for item in ice_raw
        ]
    return cfg


def _load_character_config(char_raw: dict[str, Any]) -> CharacterConfig:
    char_raw = dict(char_raw or {})
    name = char_raw.get("name", "助手")
    prompt_file = char_raw.get("system_prompt_file", DEFAULT_SYSTEM_PROMPT_FILE)
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


def load_config(path: Path | None = None) -> AppConfig:
    path = path or (PROJECT_ROOT / "config.yaml")
    if not path.exists():
        logger.warning("未找到 %s，使用默认配置", path)
        return AppConfig()

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    vad_raw = raw.get("vad", {}) or {}
    silero_raw = vad_raw.get("silero_vad", {}) or {}
    cfg = AppConfig(
        system=SystemConfig(**raw.get("system", {})),
        character=_load_character_config(raw.get("character", {})),
        llm=LLMConfig(**raw.get("llm", {})),
        asr=ASRConfig(**raw.get("asr", {})),
        tts=TTSConfig(**raw.get("tts", {})),
        memory=MemoryConfig(**raw.get("memory", {})),
        profile=ProfileConfig(**raw.get("profile", {})),
        avatar=_load_avatar_config(raw.get("avatar", {})),
        vad=VADConfig(
            vad_model=vad_raw.get("vad_model", "silero_vad"),
            silero_vad=SileroVADConfig(**silero_raw) if silero_raw else SileroVADConfig(),
            speech_filter=SpeechFilterConfig(
                **(vad_raw.get("speech_filter") or {})
            ),
        ),
    )
    if not cfg.llm.api_key:
        logger.warning("config.yaml 中 llm.api_key 为空，对话将无法调用大模型")
    return cfg
