"""验证 Playwright Live2D 渲染（需本机已启动 uvicorn 或脚本内自建静态服务）。"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vtuber.config.loader import load_config
from vtuber.modules.avatar.playwright_manager import PlaywrightManager
from vtuber.modules.avatar.playwright_renderer import PlaywrightRenderer


async def main() -> None:
    cfg = load_config()
    mgr = PlaywrightManager(cfg.avatar)
    renderer = PlaywrightRenderer(mgr, cfg.avatar)
    try:
        await renderer.start()
        await renderer.set_mouth(0.6)
        await asyncio.sleep(1.0)
        rgb = await renderer.capture_rgb()
        if not rgb:
            print("FAIL: 未抓到帧")
            sys.exit(1)
        data, w, h = rgb
        print(f"OK: frame {w}x{h} bytes={len(data)}")
    finally:
        await renderer.close()
        await mgr.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
