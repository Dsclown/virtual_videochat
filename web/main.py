"""Web 测试端：静态页 + 指向 Gateway 的配置（独立进程）。"""

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response

try:
    from vtuber.logging_config import configure_logging

    configure_logging()
except ImportError:
    pass

WEB_DIR = Path(__file__).resolve().parent
GATEWAY_ORIGIN = os.environ.get("VVC_GATEWAY_ORIGIN", "http://127.0.0.1:8765").rstrip("/")

app = FastAPI(title="Virtual Voice Chat Web Test")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/gateway-config.js")
async def gateway_config() -> Response:
    return Response(
        content=f'window.VVC_GATEWAY = "{GATEWAY_ORIGIN}";\n',
        media_type="application/javascript",
    )


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/login.html")
async def login_page() -> FileResponse:
    return FileResponse(WEB_DIR / "login.html")


@app.get("/app.js")
async def app_js() -> FileResponse:
    return FileResponse(WEB_DIR / "app.js")


@app.get("/style.css")
async def style_css() -> FileResponse:
    return FileResponse(WEB_DIR / "style.css")


@app.get("/gateway-client.js")
async def gateway_client_js() -> FileResponse:
    return FileResponse(WEB_DIR / "gateway-client.js")


@app.get("/api/health")
async def health() -> dict:
    return {
        "ok": True,
        "role": "web",
        "gateway_origin": GATEWAY_ORIGIN,
    }
