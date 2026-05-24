"""对比抓帧路径耗时（需 Gateway :8765）。"""
from __future__ import annotations

import asyncio
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vtuber.config.loader import load_config
from vtuber.modules.avatar.playwright_manager import PlaywrightManager
from vtuber.modules.avatar.playwright_renderer import PlaywrightRenderer

_RENDER_LOOP_JS = """(fps) => {
  if (window.__vvcRenderLoop) return;
  window.__vvcRenderLoop = true;
  const ms = 1000 / Math.max(1, fps);
  let last = performance.now();
  const step = (now) => {
    if (now - last >= ms) {
      window.__avatar?.renderTick?.();
      last = now;
    }
    requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}"""


async def main() -> None:
    cfg = load_config()
    mgr = PlaywrightManager(cfg.avatar)
    r = PlaywrightRenderer(mgr, cfg.avatar)
    await r.start()
    page = r._page
    loc = page.locator("#live2d-canvas")

    async def bench(name: str, n: int, fn) -> None:
        times: list[float] = []
        for _ in range(n):
            t0 = time.perf_counter()
            await fn()
            times.append(time.perf_counter() - t0)
        avg = statistics.mean(times)
        print(f"{name}: avg {avg * 1000:.1f}ms → {1 / avg:.2f} fps")

    n = 10

    async def tick_png() -> None:
        await page.evaluate("() => window.__avatar?.renderTick?.()")
        await loc.screenshot(type="png", animations="disabled")

    async def tick_jpeg() -> None:
        await page.evaluate("() => window.__avatar?.renderTick?.()")
        await loc.screenshot(type="jpeg", quality=80, animations="disabled")

    async def jpeg_only() -> None:
        await loc.screenshot(type="jpeg", quality=80, animations="disabled")

    await bench("tick+png", n, tick_png)
    await bench("tick+jpeg", n, tick_jpeg)
    await page.evaluate(_RENDER_LOOP_JS, cfg.avatar.fps)
    await asyncio.sleep(0.3)
    await bench("rAF+jpeg only", n, jpeg_only)

    await r.close()
    await mgr.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
