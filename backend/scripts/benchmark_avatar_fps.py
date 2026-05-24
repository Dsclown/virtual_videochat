"""测量 Avatar 实际抓帧帧率（canvas.captureStream → RGB）。

用法（需本机 uvicorn 已启动，与线上一致）:
  cd backend && .venv/bin/python scripts/benchmark_avatar_fps.py
  .venv/bin/python scripts/benchmark_avatar_fps.py --frames 40 --warmup 5
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vtuber.config.loader import load_config
from vtuber.modules.avatar.playwright_manager import PlaywrightManager
from vtuber.modules.avatar.playwright_renderer import PlaywrightRenderer


async def main() -> None:
    parser = argparse.ArgumentParser(description="Avatar 抓帧 FPS 基准")
    parser.add_argument("--frames", type=int, default=30, help="统计帧数")
    parser.add_argument("--warmup", type=int, default=5, help="预热帧数（不计入统计）")
    args = parser.parse_args()

    cfg = load_config()
    print(
        f"配置: {cfg.avatar.width}x{cfg.avatar.height} fps目标={cfg.avatar.fps} "
        f"captureStream"
    )

    mgr = PlaywrightManager(cfg.avatar)
    renderer = PlaywrightRenderer(mgr, cfg.avatar)
    try:
        await renderer.start()
        await renderer.set_mouth(0.4)

        for _ in range(args.warmup):
            await renderer.capture_rgb()
            await asyncio.sleep(0)

        times: list[float] = []
        for i in range(args.frames):
            t0 = time.perf_counter()
            frame = await renderer.capture_rgb()
            elapsed = time.perf_counter() - t0
            if not frame:
                print(f"帧 #{i}: 失败（无数据）")
                continue
            rgb, w, h = frame
            times.append(elapsed)
            print(
                f"帧 #{i}: {elapsed * 1000:.1f}ms "
                f"({w}x{h} rgb={len(rgb)} bytes)"
            )

        if not times:
            print("FAIL: 无有效帧")
            sys.exit(1)

        avg = statistics.mean(times)
        p50 = statistics.median(times)
        p90 = sorted(times)[int(len(times) * 0.9) - 1]
        mx = max(times)
        print()
        print("--- 统计 ---")
        print(f"有效帧: {len(times)}")
        print(f"平均: {avg * 1000:.1f}ms  → 实际 FPS ≈ {1 / avg:.2f}")
        print(f"P50:  {p50 * 1000:.1f}ms  → {1 / p50:.2f} fps")
        print(f"P90:  {p90 * 1000:.1f}ms")
        print(f"最大: {mx * 1000:.1f}ms  → {1 / mx:.2f} fps")
        print(f"配置 fps 上限: {cfg.avatar.fps}（实际由抓帧耗时决定）")
    finally:
        await renderer.close()
        await mgr.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
