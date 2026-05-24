"""Gateway WebRTC：ICE / SDP 工具。"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiortc import RTCIceCandidate, RTCPeerConnection, RTCConfiguration, RTCIceServer
from aiortc.sdp import candidate_from_sdp

from gateway.config import GatewayAvatarConfig

logger = logging.getLogger(__name__)

IceSendFn = Callable[[dict], Awaitable[None]]


def rtc_configuration(cfg: GatewayAvatarConfig) -> RTCConfiguration:
    servers = [
        RTCIceServer(urls=s.urls, username=s.username, credential=s.credential)
        for s in cfg.ice_servers
    ]
    return RTCConfiguration(iceServers=servers or None)


async def wait_ice_gathering(pc: RTCPeerConnection, timeout: float = 10.0) -> None:
    if pc.iceGatheringState == "complete":
        return
    deadline = asyncio.get_running_loop().time() + timeout
    while pc.iceGatheringState != "complete":
        if asyncio.get_running_loop().time() >= deadline:
            logger.warning("ICE gathering 超时 (%ss)", timeout)
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
