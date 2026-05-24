"""Avatar 渲染诊断：canvas.captureStream → RGB 帧。

用法:
  cd backend && .venv/bin/python scripts/diagnose_avatar.py

输出 PPM 到 /tmp/avatar_diag_render.ppm（可用 ImageMagick 转 PNG 查看）。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vtuber.config.loader import load_config
from vtuber.modules.avatar.playwright_manager import PlaywrightManager
from vtuber.modules.avatar.playwright_renderer import PlaywrightRenderer

OUT = Path("/tmp/avatar_diag_render.ppm")


def write_ppm(path: Path, rgb: bytes, w: int, h: int) -> None:
    header = f"P6\n{w} {h}\n255\n".encode("ascii")
    path.write_bytes(header + rgb)


def analyze_rgb(rgb: bytes, w: int, h: int) -> dict:
    if len(rgb) != w * h * 3:
        return {"verdict": f"长度异常 {len(rgb)} != {w*h*3}"}
    rs = [rgb[i] for i in range(0, len(rgb), 3)]
    avg = sum(rs) / max(1, len(rs))
    mx = max(rs)
    if avg < 5 and mx < 10:
        verdict = "纯黑/无效"
    elif avg < 15:
        verdict = "极暗"
    else:
        verdict = "有可见内容"
    return {"width": w, "height": h, "avg": round(avg, 1), "max": mx, "verdict": verdict}


async def main() -> None:
    cfg = load_config()
    mgr = PlaywrightManager(cfg.avatar)
    renderer = PlaywrightRenderer(mgr, cfg.avatar)
    try:
        await renderer.start()
        await renderer.set_mouth(0.5)
        await asyncio.sleep(0.8)
        frame = await renderer.capture_rgb()
        if not frame:
            print("FAIL: capture_rgb 返回 None")
            sys.exit(1)
        rgb, w, h = frame
        write_ppm(OUT, rgb, w, h)
        info = analyze_rgb(rgb, w, h)
        print(f"OK: {w}x{h} bytes={len(rgb)}")
        print(f"判定: {info['verdict']} avg={info['avg']} max={info['max']}")
        print(f"文件: {OUT}")
        if info["verdict"] != "有可见内容":
            sys.exit(1)
    finally:
        await renderer.close()
        await mgr.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
