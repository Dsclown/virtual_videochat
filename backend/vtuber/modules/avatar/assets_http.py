"""Core 侧 Live2D 渲染用静态资源 HTTP（Playwright 拉 render.html / 模型 / SDK）。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from vtuber.config.loader import PROJECT_ROOT

if TYPE_CHECKING:
    from vtuber.config.loader import AvatarConfig

logger = logging.getLogger(__name__)

LIVE2D_LIBS_DIR = PROJECT_ROOT / "assets" / "live2d" / "libs"
RENDER_ENGINE_DIR = PROJECT_ROOT / "render-engine"


def build_avatar_assets_app(cfg: AvatarConfig) -> FastAPI:
    app = FastAPI(title="Vtuber Avatar Assets", docs_url=None, redoc_url=None)
    models_dir = (PROJECT_ROOT / cfg.models_root).resolve()
    if models_dir.is_dir():
        app.mount(
            "/live2d-models",
            StaticFiles(directory=str(models_dir)),
            name="live2d-models",
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

    @app.get("/api/health")
    async def health() -> dict:
        return {"ok": True, "role": "core_avatar_assets"}

    return app


async def run_avatar_assets_http(app: FastAPI, host: str, port: int) -> None:
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    logger.info("Live2D 静态资源 HTTP 已监听 %s:%s", host, port)
    await server.serve()
