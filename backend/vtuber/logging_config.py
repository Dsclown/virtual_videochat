"""统一压低第三方库日志噪声。"""

import logging

_QUIET_LOGGERS = (
    "uvicorn",
    "uvicorn.access",
    "uvicorn.error",
    "watchfiles",
    "grpc",
    "grpc.aio",
    "httpx",
    "httpcore",
    "aiortc",
    "aioice",
    "av",
    "playwright",
)


def configure_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(
        level=level,
        format="%(levelname)s:%(name)s:%(message)s",
    )
    for name in _QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
