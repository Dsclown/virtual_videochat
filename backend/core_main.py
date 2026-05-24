#!/usr/bin/env python3
"""Vtuber 核心服务：仅 gRPC，不暴露 HTTP/WebSocket。"""

import asyncio
import logging
import os
import signal

from vtuber.app.context import ServiceContext
from vtuber.config.loader import load_config
from vtuber.grpc.servicer import serve_grpc
from vtuber.logging_config import configure_logging
from vtuber.modules.avatar.assets_http import build_avatar_assets_app, run_avatar_assets_http

configure_logging()
logger = logging.getLogger(__name__)

GRPC_HOST = os.environ.get("VVC_CORE_GRPC_HOST", "0.0.0.0")
GRPC_PORT = int(os.environ.get("VVC_CORE_GRPC_PORT", "50051"))


async def main() -> None:
    config = load_config()
    av = config.avatar
    asset_host = os.environ.get("VVC_CORE_ASSET_HTTP_HOST", av.asset_http_host)
    asset_port = int(os.environ.get("VVC_CORE_ASSET_HTTP_PORT", str(av.asset_http_port)))

    assets_app = build_avatar_assets_app(av)
    assets_task = asyncio.create_task(
        run_avatar_assets_http(assets_app, asset_host, asset_port)
    )

    ctx = ServiceContext(config)
    server = await serve_grpc(ctx, GRPC_HOST, GRPC_PORT)
    logger.info(
        "核心服务已就绪 gRPC %s:%s；Playwright 资源基址 %s（本机 HTTP %s:%s）",
        GRPC_HOST,
        GRPC_PORT,
        av.server_base_url,
        asset_host,
        asset_port,
    )

    stop = asyncio.Event()

    def _stop(*_args):
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _stop)
        except NotImplementedError:
            pass

    await stop.wait()
    logger.info("关闭核心服务 …")
    assets_task.cancel()
    await asyncio.gather(assets_task, return_exceptions=True)
    await server.stop(grace=5)
    await ctx.shutdown_async()
    ctx.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
