"""Gateway HTTP/WebSocket 入口。"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from gateway.auth import sanitize_user_id
from gateway.config import load_gateway_config
from gateway.settings import CORE_GRPC_TARGET
from gateway.web_session import WebGatewaySession

try:
    from vtuber.logging_config import configure_logging
except ImportError:
    import logging

    def configure_logging(level: int = logging.INFO) -> None:
        logging.basicConfig(level=level)

configure_logging()
logger = logging.getLogger(__name__)

app_config = load_gateway_config()


class LoginBody(BaseModel):
    user_id: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Gateway 已启动，Core gRPC 目标: %s", CORE_GRPC_TARGET)
    yield


app = FastAPI(title="Virtual Voice Chat Gateway", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/api/login")
async def login(body: LoginBody):
    try:
        uid = sanitize_user_id(body.user_id)
    except ValueError as e:
        return {"ok": False, "message": str(e)}
    return {"ok": True, "user_id": uid}


@app.get("/api/health")
async def health():
    av = app_config.avatar
    return {
        "ok": True,
        "role": "gateway",
        "avatar": {"enabled": av.enabled, "webrtc": av.webrtc_enabled},
    }


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    session = WebGatewaySession(ws, app_config)
    try:
        await session.run()
    except WebSocketDisconnect:
        logger.debug("Web 客户端断开")
    except Exception:
        logger.exception("WebSocket 错误")
        try:
            await session.send({"type": "error", "message": "Gateway 内部错误"})
        except Exception:
            pass

