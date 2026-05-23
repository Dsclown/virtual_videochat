"""单连接 Live2D 离屏页：抓帧 + 嘴型。"""

import asyncio
import base64
import logging
from io import BytesIO

from PIL import Image

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
        try:
            await self._page.evaluate(
                "() => window.__avatar && window.__avatar.renderTick()"
            )
            await asyncio.sleep(0.3)
        except Exception:
            logger.debug("首帧 renderTick 失败", exc_info=True)

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

    async def capture_jpeg_bytes(self) -> bytes | None:
        if not await self._page_ready():
            return None
        try:
            await self._page.evaluate(
                "() => window.__avatar && window.__avatar.renderTick()"
            )
            jpeg = await self._page.locator("#stage").screenshot(
                type="jpeg",
                quality=75,
            )
            if not jpeg or len(jpeg) < 100:
                return None
            return jpeg
        except Exception:
            logger.debug("capture_jpeg_bytes 失败", exc_info=True)
            return None

    async def capture_jpeg_b64(self) -> str | None:
        raw = await self.capture_jpeg_bytes()
        if not raw:
            return None
        return base64.b64encode(raw).decode("ascii")

    async def capture_rgb(self) -> tuple[bytes, int, int] | None:
        raw = await self.capture_jpeg_bytes()
        if not raw:
            return None
        img = Image.open(BytesIO(raw)).convert("RGB")
        w, h = img.size
        return img.tobytes(), w, h

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._page:
            try:
                await self._page.close()
            except Exception:
                logger.debug("关闭 avatar page 失败", exc_info=True)
            self._page = None
