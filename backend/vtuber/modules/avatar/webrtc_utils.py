"""WebRTC 工具：ICE 等待与 candidate 解析。"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiortc import RTCIceCandidate, RTCPeerConnection, RTCConfiguration, RTCIceServer
from aiortc.sdp import candidate_from_sdp

from vtuber.config.loader import AvatarConfig, IceServerConfig

logger = logging.getLogger(__name__)

IceSendFn = Callable[[dict], Awaitable[None]]


def ice_server_to_dict(entry: IceServerConfig) -> dict[str, Any]:
    out: dict[str, Any] = {"urls": entry.urls}
    if entry.username:
        out["username"] = entry.username
    if entry.credential:
        out["credential"] = entry.credential
    return out


def ice_servers_for_browser(cfg: AvatarConfig) -> list[dict[str, Any]]:
    return [ice_server_to_dict(s) for s in cfg.ice_servers]


def rtc_configuration_from_avatar(cfg: AvatarConfig) -> RTCConfiguration:
    servers = [
        RTCIceServer(
            urls=s.urls,
            username=s.username,
            credential=s.credential,
        )
        for s in cfg.ice_servers
    ]
    return RTCConfiguration(iceServers=servers or None)


async def wait_ice_gathering(pc: RTCPeerConnection, timeout: float = 10.0) -> None:
    if pc.iceGatheringState == "complete":
        return
    deadline = asyncio.get_running_loop().time() + timeout
    while pc.iceGatheringState != "complete":
        if asyncio.get_running_loop().time() >= deadline:
            logger.warning("ICE gathering 超时 (%ss)，继续用当前 SDP", timeout)
            return
        await asyncio.sleep(0.05)


def ice_candidate_from_payload(raw: dict[str, Any]) -> RTCIceCandidate | None:
    if not raw:
        return None
    cand = raw.get("candidate")
    if not cand:
        return None
    sdp = cand.split(":", 1)[1] if str(cand).startswith("candidate:") else str(cand)
    ice = candidate_from_sdp(sdp)
    ice.sdpMid = raw.get("sdpMid")
    ice.sdpMLineIndex = raw.get("sdpMLineIndex")
    return ice


def attach_ice_candidate_handler(pc: RTCPeerConnection, send: IceSendFn | None) -> None:
    if send is None:
        return

    @pc.on("icecandidate")
    async def _on_ice(event) -> None:
        if event.candidate:
            try:
                await send({
                    "type": "webrtc_ice",
                    "candidate": event.candidate.to_json(),
                })
            except Exception:
                logger.debug("发送 ICE candidate 失败", exc_info=True)
