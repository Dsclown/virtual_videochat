"""全局 Playwright Chromium：每 WebSocket 连接独占 Page。"""

import asyncio
import logging
from urllib.parse import quote

from vtuber.config.loader import AvatarConfig, PROJECT_ROOT

logger = logging.getLogger(__name__)


class PlaywrightManager:
    def __init__(self, cfg: AvatarConfig):
        self._cfg = cfg
        self._playwright = None
        self._browser = None
        self._lock = asyncio.Lock()

    @property
    def enabled(self) -> bool:
        return self._cfg.enabled and self._cfg.provider == "playwright"

    async def ensure_browser(self) -> None:
        if self._browser is not None:
            return
        async with self._lock:
            if self._browser is not None:
                return
            from playwright.async_api import async_playwright

            logger.debug("启动 Playwright Chromium …")
            self._playwright = await async_playwright().start()
            try:
                self._browser = await self._playwright.chromium.launch(
                    headless=True,
                    args=[
                        "--use-gl=angle",
                        "--enable-webgl",
                        "--hide-scrollbars",
                        "--mute-audio",
                    ],
                )
            except Exception as e:
                hint = (
                    "Playwright 浏览器未安装。请在 backend 目录执行："
                    " .venv/bin/playwright install chromium"
                )
                if "Executable doesn't exist" in str(e):
                    raise RuntimeError(hint) from e
                raise
            logger.debug("Playwright Chromium 已就绪")

    async def new_page(self):
        await self.ensure_browser()
        assert self._browser is not None
        return await self._browser.new_page(
            viewport={"width": self._cfg.width, "height": self._cfg.height},
        )

    def render_page_url(self) -> str:
        model_path = (
            PROJECT_ROOT
            / self._cfg.models_root
            / self._cfg.model_name
            / "runtime"
            / f"{self._cfg.model_name}.model3.json"
        )
        if not model_path.exists():
            raise FileNotFoundError(f"Live2D 模型不存在: {model_path}")
        model_url = (
            f"{self._cfg.server_base_url.rstrip('/')}"
            f"/live2d-models/{self._cfg.model_name}/runtime/"
            f"{self._cfg.model_name}.model3.json"
        )
        q = (
            f"model={quote(model_url, safe='/:')}"
            f"&w={self._cfg.width}&h={self._cfg.height}"
        )
        if self._cfg.view_scale and self._cfg.view_scale > 0:
            q += f"&scale={self._cfg.view_scale}"
        engine = self._cfg.render_engine.strip("/")
        return (
            f"{self._cfg.server_base_url.rstrip('/')}"
            f"/render-engine/{engine}/render.html?{q}"
        )

    async def shutdown(self) -> None:
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        logger.debug("Playwright 已关闭")
