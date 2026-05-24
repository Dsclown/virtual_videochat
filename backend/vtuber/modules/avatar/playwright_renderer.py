"""单连接 Live2D 离屏页：canvas.captureStream 抓 RGB 帧 + 嘴型。"""

import asyncio
import base64
import logging

from vtuber.config.loader import AvatarConfig
from vtuber.modules.avatar.playwright_manager import PlaywrightManager

logger = logging.getLogger(__name__)


class PlaywrightRenderer:
    def __init__(self, manager: PlaywrightManager, cfg: AvatarConfig):
        self._manager = manager
        self._cfg = cfg
        self._page = None
        self._mouth = 0.0
        self._closed = False
        self._stream_started = False

    async def _page_ready(self) -> bool:
        if self._closed or not self._page:
            return False
        try:
            return bool(
                await self._page.evaluate(
                    "() => !!(window.__avatar && window.__avatar.isReady())"
                )
            )
        except Exception:
            return False

    async def start(self, *, wait_ready: bool = True) -> None:
        if await self._page_ready():
            return

        if self._page:
            try:
                await self._page.close()
            except Exception:
                pass
            self._page = None
            self._stream_started = False

        self._closed = False
        self._page = await self._manager.new_page()
        url = self._manager.render_page_url()
        logger.info("Avatar 渲染页: %s", url)
        await self._page.goto(url, wait_until="domcontentloaded", timeout=120_000)
        if wait_ready:
            await self._wait_until_ready()
        else:
            asyncio.create_task(self._wait_until_ready())

    async def _wait_until_ready(self) -> None:
        if not self._page or self._closed:
            return
        try:
            await self._page.wait_for_function(
                "() => window.__avatar && window.__avatar.isReady()",
                timeout=120_000,
            )
        except Exception as e:
            status = "unknown"
            try:
                status = await self._page.locator("#status").inner_text()
            except Exception:
                pass
            logger.error("Live2D 加载失败 (%s): %s", status, e)
            return
        logger.info("Live2D 模型加载完成")
        await self._start_capture_stream()

    async def _start_capture_stream(self) -> None:
        if not self._page or self._closed or self._stream_started:
            return
        ok = await self._page.evaluate(
            "(fps) => window.__avatar && window.__avatar.startCaptureStream(fps)",
            max(1, self._cfg.fps),
        )
        if not ok:
            logger.error("canvas.captureStream 启动失败，Avatar 视频不可用")
            return
        self._stream_started = True
        logger.info("Avatar canvas.captureStream 已启动 (%dfps)", self._cfg.fps)

    async def set_mouth(self, value: float) -> None:
        if not await self._page_ready():
            return
        self._mouth = max(0.0, min(1.0, float(value)))
        try:
            await self._page.evaluate(
                "(v) => window.__avatar.setMouth(v)",
                self._mouth,
            )
        except Exception:
            logger.debug("set_mouth 失败", exc_info=True)

    async def _capture_rgb_js(self) -> dict | None:
        if not await self._page_ready():
            return None
        if not self._stream_started:
            await self._start_capture_stream()
        if not self._stream_started:
            return None
        try:
            return await self._page.evaluate(
                "() => window.__avatar && window.__avatar.captureFrameRgb()"
            )
        except Exception:
            logger.debug("captureFrameRgb 失败", exc_info=True)
            return None

    @staticmethod
    def _parse_rgb(frame: dict | None) -> tuple[bytes, int, int] | None:
        if not frame or not frame.get("b64"):
            return None
        try:
            rgb = base64.b64decode(frame["b64"])
            w = int(frame["width"])
            h = int(frame["height"])
            if w <= 0 or h <= 0 or len(rgb) != w * h * 3:
                return None
            return rgb, w, h
        except (KeyError, TypeError, ValueError):
            return None

    async def capture_rgb(self) -> tuple[bytes, int, int] | None:
        return self._parse_rgb(await self._capture_rgb_js())

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._page:
            try:
                if self._stream_started:
                    await self._page.evaluate(
                        "() => window.__avatar && window.__avatar.stopCaptureStream()"
                    )
            except Exception:
                pass
            try:
                await self._page.close()
            except Exception:
                logger.debug("关闭 avatar page 失败", exc_info=True)
            self._page = None
        self._stream_started = False
