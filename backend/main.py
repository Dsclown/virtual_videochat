import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from vtuber.app.context import ServiceContext
from vtuber.config.loader import PROJECT_ROOT, load_config
from vtuber.core.stages import Stage
from vtuber.core.ws_session import VoiceChatSession
from vtuber.modules.profile.form import sanitize_user_id

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

FRONTEND_DIR = PROJECT_ROOT / "frontend"
RENDER_ENGINE_DIR = PROJECT_ROOT / "render-engine"
LIVE2D_LIBS_DIR = PROJECT_ROOT / "assets" / "live2d" / "libs"
LIVE2D_PIXI_DIR = PROJECT_ROOT / "assets" / "live2d" / "pixi"

app_config = load_config()
service_ctx: ServiceContext | None = None


class LoginBody(BaseModel):
    user_id: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    global service_ctx
    logger.info("初始化 ServiceContext …")
    service_ctx = ServiceContext(app_config)
    try:
        yield
    finally:
        if service_ctx:
            await service_ctx.shutdown_async()
            service_ctx.shutdown()


app = FastAPI(title="Virtual Voice Chat", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_models_dir = (PROJECT_ROOT / app_config.avatar.models_root).resolve()
if _models_dir.is_dir():
    app.mount(
        "/live2d-models",
        StaticFiles(directory=str(_models_dir)),
        name="live2d-models",
    )
if LIVE2D_PIXI_DIR.is_dir():
    app.mount(
        "/live2d/pixi",
        StaticFiles(directory=str(LIVE2D_PIXI_DIR)),
        name="live2d-pixi",
    )
if LIVE2D_LIBS_DIR.is_dir():
    app.mount(
        "/live2d/libs",
        StaticFiles(directory=str(LIVE2D_LIBS_DIR)),
        name="live2d-libs",
    )
if RENDER_ENGINE_DIR.is_dir():
    app.mount(
        "/render-engine",
        StaticFiles(directory=str(RENDER_ENGINE_DIR)),
        name="render-engine",
    )


@app.post("/api/login")
async def login(body: LoginBody):
    try:
        uid = sanitize_user_id(body.user_id)
    except ValueError as e:
        return {"ok": False, "message": str(e)}
    form = service_ctx.profile.load(uid)
    return {
        "ok": True,
        "user_id": uid,
        "profile_form": {
            "user_profile": form.user_profile,
            "current_topic": form.current_topic,
            "historical_interests": form.historical_interests,
        },
    }


@app.get("/api/health")
async def health():
    avatar = app_config.avatar
    return {
        "ok": True,
        "stages": [s.value for s in Stage],
        "avatar": {
            "enabled": avatar.enabled,
            "provider": avatar.provider,
            "webrtc": avatar.webrtc_enabled,
        },
    }


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    session = VoiceChatSession(ws, service_ctx, app_config)
    try:
        await session.run()
    except WebSocketDisconnect:
        logger.info("client disconnected")
    except Exception:
        logger.exception("websocket error")
        try:
            await session.send({"type": "error", "message": "服务器内部错误"})
        except Exception:
            pass


@app.get("/")
async def index():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/login.html")
async def login_page():
    return FileResponse(FRONTEND_DIR / "login.html")


@app.get("/app.js")
async def app_js():
    return FileResponse(FRONTEND_DIR / "app.js")


@app.get("/style.css")
async def style_css():
    return FileResponse(FRONTEND_DIR / "style.css")
