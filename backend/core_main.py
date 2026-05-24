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

configure_logging()
logger = logging.getLogger(__name__)

GRPC_HOST = os.environ.get("VVC_CORE_GRPC_HOST", "0.0.0.0")
GRPC_PORT = int(os.environ.get("VVC_CORE_GRPC_PORT", "50051"))


async def main() -> None:
    config = load_config()
    ctx = ServiceContext(config)
    server = await serve_grpc(ctx, GRPC_HOST, GRPC_PORT)

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
    await server.stop(grace=5)
    await ctx.shutdown_async()
    ctx.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
