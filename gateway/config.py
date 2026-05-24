"""Gateway 独立配置（仅读取与本服务相关的字段）。"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
_CONFIG_PATH = PROJECT_ROOT / "config.yaml"
_CONFIG_EXAMPLE = PROJECT_ROOT / "config.example.yaml"


class GatewayConfigError(Exception):
    pass


@dataclass
class IceServerConfig:
    urls: str | list[str]
    username: str | None = None
    credential: str | None = None


@dataclass
class GatewayAvatarConfig:
    enabled: bool
    webrtc_enabled: bool
    ice_transport_policy: str
    ice_servers: list[IceServerConfig]
    models_root: str


@dataclass
class GatewayConfig:
    avatar: GatewayAvatarConfig


def _require_avatar(raw: dict[str, Any]) -> dict[str, Any]:
    if "avatar" not in raw or not isinstance(raw["avatar"], dict):
        raise GatewayConfigError("config.yaml 缺少 avatar 段")
    return raw["avatar"]


def load_gateway_config(path: Path | None = None) -> GatewayConfig:
    path = path or _CONFIG_PATH
    if not path.is_file():
        raise GatewayConfigError(
            f"未找到 {path}，请执行: cp {_CONFIG_EXAMPLE.name} config.yaml"
        )
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise GatewayConfigError("config.yaml 格式无效")

    av = _require_avatar(raw)
    for key in ("enabled", "webrtc_enabled", "ice_transport_policy", "ice_servers", "models_root"):
        if key not in av:
            raise GatewayConfigError(f"avatar 缺少 Gateway 必填项: {key}")

    ice_raw = av["ice_servers"]
    if not isinstance(ice_raw, list) or not ice_raw:
        raise GatewayConfigError("avatar.ice_servers 必须为非空列表")

    ice_servers = [
        IceServerConfig(**item) if isinstance(item, dict) else IceServerConfig(urls=str(item))
        for item in ice_raw
    ]

    return GatewayConfig(
        avatar=GatewayAvatarConfig(
            enabled=bool(av["enabled"]),
            webrtc_enabled=bool(av["webrtc_enabled"]),
            ice_transport_policy=str(av["ice_transport_policy"]),
            ice_servers=ice_servers,
            models_root=str(av["models_root"]),
        )
    )


def ice_servers_for_browser(cfg: GatewayAvatarConfig) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for s in cfg.ice_servers:
        item: dict[str, Any] = {"urls": s.urls}
        if s.username:
            item["username"] = s.username
        if s.credential:
            item["credential"] = s.credential
        out.append(item)
    return out
