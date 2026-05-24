"""单连接 Live2D 离屏页：浏览器 rAF 渲染 + JPEG 截图抓 RGB。"""

import asyncio
import logging
from io import BytesIO

from PIL import Image
from playwright.async_api import Locator, Page

from vtuber.config.loader import AvatarConfig
from vtuber.modules.avatar.playwright_manager import PlaywrightManager

logger = logging.getLogger(__name__)

_CANVAS_SELECTOR = "#live2d-canvas"
_JPEG_QUALITY = 82

_START_RENDER_LOOP_JS = """(fps) => {
  if (window.__vvcRenderLoop) return;
  window.__vvcRenderLoop = true;
  const ms = 1000 / Math.max(1, fps);
  let last = performance.now();
  const step = (now) => {
    if (!window.__vvcRenderLoop) return;
    if (now - last >= ms) {
      window.__avatar?.renderTick?.();
      last = now;
    }
    window.__vvcRenderLoopHandle = requestAnimationFrame(step);
  };
  window.__vvcRenderLoopHandle = requestAnimationFrame(step);
}"""

_STOP_RENDER_LOOP_JS = """() => {
  window.__vvcRenderLoop = false;
  if (window.__vvcRenderLoopHandle) {
    cancelAnimationFrame(window.__vvcRenderLoopHandle);
    window.__vvcRenderLoopHandle = 0;
  }
}"""


class PlaywrightRenderer:
    def __init__(self, manager: PlaywrightManager, cfg: AvatarConfig):
        self._manager = manager
        self._cfg = cfg
        self._page: Page | None = None
        self._canvas: Locator | None = None
        self._mouth = 0.0
        self._closed = False
        self._start_lock = asyncio.Lock()
        self._ready_task: asyncio.Task | None = None

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
        async with self._start_lock:
            if await self._page_ready():
                return
            if self._ready_task and not self._ready_task.done():
                if wait_ready:
                    await self._ready_task
                return

            if self._page:
                try:
                    await self._page.close()
                except Exception:
                    pass
                self._page = None
                self._canvas = None

            self._closed = False
            self._page = await self._manager.new_page()
            url = self._manager.render_page_url()
            logger.debug("Avatar 渲染页: %s", url)
            await self._page.goto(url, wait_until="domcontentloaded", timeout=120_000)
            if wait_ready:
                await self._wait_until_ready()
            else:
                self._ready_task = asyncio.create_task(self._wait_until_ready())

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
        self._canvas = self._page.locator(_CANVAS_SELECTOR)
        await self._page.evaluate(_START_RENDER_LOOP_JS, max(1, self._cfg.fps))
        logger.info(
            "Live2D 模型已就绪 (%dx%d, 目标 %dfps)",
            self._cfg.width,
            self._cfg.height,
            self._cfg.fps,
        )

    async def apply_action(self, action: int | str) -> None:
        if not await self._page_ready():
            return
        try:
            if isinstance(action, str):
                spec = {"motionGroup": action}
            else:
                spec = {"expressionIndex": int(action)}
            await self._page.evaluate(
                """(spec) => {
                  requestAnimationFrame(() => window.__avatar?.applyAction?.(spec));
                }""",
                spec,
            )
        except Exception:
            logger.debug("apply_action 失败", exc_info=True)

    async def start_random_motion(self, group: str) -> None:
        if not await self._page_ready():
            return
        try:
            await self._page.evaluate(
                """(g) => {
                  requestAnimationFrame(() => window.__avatar?.startRandomMotion?.(g));
                }""",
                group,
            )
        except Exception:
            logger.debug("start_random_motion 失败", exc_info=True)

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

    async def capture_rgb(self) -> tuple[bytes, int, int] | None:
        """JPEG 截 canvas（rAF 已在页内按 fps 刷新，此处不再 tick）。"""
        if not await self._page_ready() or not self._canvas:
            return None
        try:
            if await self._canvas.count() == 0:
                return None
            jpeg = await self._canvas.screenshot(
                type="jpeg",
                quality=_JPEG_QUALITY,
                animations="disabled",
            )
            img = Image.open(BytesIO(jpeg)).convert("RGB")
            w, h = img.size
            if w <= 0 or h <= 0:
                return None
            return img.tobytes(), w, h
        except Exception:
            logger.debug("capture_rgb 失败", exc_info=True)
            return None

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._page:
            try:
                await self._page.evaluate(_STOP_RENDER_LOOP_JS)
            except Exception:
                pass
            try:
                await self._page.close()
            except Exception:
                logger.debug("关闭 avatar page 失败", exc_info=True)
            self._page = None
            self._canvas = None
