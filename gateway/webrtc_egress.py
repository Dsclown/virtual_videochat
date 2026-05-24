"""Gateway WebRTC 出站。"""

import logging
from collections.abc import Awaitable, Callable

from aiortc import RTCPeerConnection, RTCSessionDescription

from gateway.config import GatewayAvatarConfig
from gateway.media_bridge import GatewayMediaBridge
from gateway.webrtc.tracks import EgressAudioTrack, EgressVideoTrack
from gateway.webrtc.utils import (
    attach_ice_candidate_handler,
    ice_candidate_from_payload,
    rtc_configuration,
    wait_ice_gathering,
)

logger = logging.getLogger(__name__)

IceSendFn = Callable[[dict], Awaitable[None]]


class GatewayWebRtcEgress:
    def __init__(
        self,
        cfg: GatewayAvatarConfig,
        bridge: GatewayMediaBridge,
        *,
        send_ice: IceSendFn | None = None,
    ):
        self._cfg = cfg
        self._bridge = bridge
        self._send_ice = send_ice
        self._pc: RTCPeerConnection | None = None

    async def create_answer(self, offer_sdp: str) -> str:
        self._pc = RTCPeerConnection(rtc_configuration(self._cfg))
        attach_ice_candidate_handler(self._pc, self._send_ice)
        self._pc.addTrack(EgressVideoTrack(self._bridge))
        self._pc.addTrack(EgressAudioTrack(self._bridge))
        offer = RTCSessionDescription(sdp=offer_sdp, type="offer")
        await self._pc.setRemoteDescription(offer)
        answer = await self._pc.createAnswer()
        await self._pc.setLocalDescription(answer)
        await wait_ice_gathering(self._pc)
        assert self._pc.localDescription
        return self._pc.localDescription.sdp

    async def add_ice_candidate(self, raw: dict | None) -> None:
        if not self._pc:
            return
        candidate = ice_candidate_from_payload(raw or {})
        if candidate is None:
            return
        await self._pc.addIceCandidate(candidate)

    async def close(self) -> None:
        if self._pc:
            await self._pc.close()
            self._pc = None

    def on_turn_cancelled(self) -> None:
        self._bridge.clear_audio()
