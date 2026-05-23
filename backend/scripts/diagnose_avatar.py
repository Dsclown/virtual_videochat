"""Avatar 三层隔离诊断：渲染 → WS 推流 →（浏览器）显示。

用法（需 uvicorn 已启动，且 config avatar 已启用）:
  .venv/bin/python scripts/diagnose_avatar.py
  .venv/bin/python scripts/diagnose_avatar.py --ws-url ws://127.0.0.1:8765/ws

输出 JPG 到 /tmp/avatar_diag_*.jpg，终端打印每层判定。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image

from vtuber.config.loader import load_config
from vtuber.modules.avatar.playwright_manager import PlaywrightManager
from vtuber.modules.avatar.playwright_renderer import PlaywrightRenderer

OUT_DIR = Path("/tmp")


def analyze_jpeg(raw: bytes, label: str) -> dict:
    info: dict = {"label": label, "bytes": len(raw), "valid_jpeg": raw[:3] == b"\xff\xd8\xff"}
    if not raw:
        info["verdict"] = "空数据"
        return info
    if not info["valid_jpeg"]:
        info["verdict"] = f"非 JPEG（头={raw[:8]!r}）"
        return info
    try:
        img = Image.open(BytesIO(raw)).convert("RGB")
        w, h = img.size
        flat = img.get_flattened_data()
        if flat and isinstance(flat[0], tuple):
            rs = [p[0] for p in flat]
        else:
            rs = [flat[i] for i in range(0, len(flat), 3)]
        n = len(rs)
        avg = sum(rs) / max(1, n)
        mx = max(rs)
        info.update({"width": w, "height": h, "avg": round(avg, 1), "max": mx})
        # avg<5 且 max<10 视为纯黑；avg<15 视为极暗
        if avg < 5 and mx < 10:
            info["verdict"] = "纯黑/无效"
        elif avg < 15:
            info["verdict"] = "极暗（可能只有背景色）"
        else:
            info["verdict"] = "有可见内容"
    except Exception as e:
        info["verdict"] = f"解码失败: {e}"
    return info


def print_layer(title: str, info: dict, path: Path | None = None) -> None:
    print(f"\n=== {title} ===")
    if path:
        print(f"  文件: {path}")
    print(f"  大小: {info.get('bytes', 0)} bytes")
    if "valid_jpeg" in info:
        print(f"  JPEG 魔数: {'OK' if info['valid_jpeg'] else 'FAIL'}")
    if "width" in info:
        print(f"  尺寸: {info['width']}x{info['height']}")
        print(f"  像素 avg={info['avg']} max={info['max']}")
    print(f"  判定: {info.get('verdict', '?')}")


def is_ok(info: dict) -> bool:
    return info.get("verdict") == "有可见内容"


async def layer_render() -> tuple[dict, bytes | None]:
    cfg = load_config()
    mgr = PlaywrightManager(cfg.avatar)
    renderer = PlaywrightRenderer(mgr, cfg.avatar)
    try:
        await renderer.start()
        await renderer.set_mouth(0.5)
        await asyncio.sleep(0.8)
        raw = await renderer.capture_jpeg_bytes()
        if not raw:
            return {"verdict": "capture_jpeg_bytes 返回 None"}, None
        path = OUT_DIR / "avatar_diag_render.jpg"
        path.write_bytes(raw)
        return analyze_jpeg(raw, "render"), raw
    finally:
        await renderer.close()
        await mgr.shutdown()


async def layer_ws(ws_url: str, user_id: str, wait_sec: float, max_frames: int) -> list[bytes]:
    import websockets

    frames: list[bytes] = []
    async with websockets.connect(ws_url, max_size=16 * 1024 * 1024) as ws:
        deadline = time.time() + wait_sec
        authed = False
        ws_started = False

        while time.time() < deadline and len(frames) < max_frames:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=min(3.0, deadline - time.time()))
            except asyncio.TimeoutError:
                break

            if isinstance(msg, bytes):
                frames.append(msg)
                continue

            data = json.loads(msg)
            t = data.get("type")
            if t == "await_auth":
                await ws.send(json.dumps({"type": "auth", "user_id": user_id}, ensure_ascii=False))
            elif t == "auth_ok":
                authed = True
                await ws.send(json.dumps({"type": "avatar_ws_start"}, ensure_ascii=False))
            elif t == "avatar_ws_ok":
                ws_started = True
            elif t == "error":
                raise RuntimeError(data.get("message", "WS error"))

        if not authed:
            raise RuntimeError("未完成 auth")
        if not ws_started and not frames:
            raise RuntimeError("avatar_ws_start 后未收到二进制帧（推流层无数据）")

    return frames


async def main() -> None:
    parser = argparse.ArgumentParser(description="Avatar 三层诊断")
    parser.add_argument("--ws-url", default="ws://127.0.0.1:8765/ws")
    parser.add_argument("--user-id", default="diag")
    parser.add_argument("--skip-ws", action="store_true", help="只测渲染层")
    args = parser.parse_args()

    print("Avatar 问题定位：①渲染  ②WS推流  ③浏览器显示（需手动）")
    print("-" * 56)

    # ① 渲染层
    render_info, render_raw = await layer_render()
    render_path = OUT_DIR / "avatar_diag_render.jpg" if render_raw else None
    print_layer("① 渲染层（Playwright 截图）", render_info, render_path)
    render_ok = is_ok(render_info)

    ws_ok = False
    ws_frames: list[bytes] = []

    if not args.skip_ws:
        print(f"\n连接 WS: {args.ws_url} …")
        try:
            ws_frames = await layer_ws(args.ws_url, args.user_id, wait_sec=4.0, max_frames=8)
        except Exception as e:
            print(f"\n=== ② WS 推流层 ===")
            print(f"  判定: 失败 — {e}")
        else:
            print(f"\n=== ② WS 推流层 ===")
            print(f"  {len(ws_frames)} 帧（4s 内）")
            for i, raw in enumerate(ws_frames[:3]):
                info = analyze_jpeg(raw, f"ws#{i}")
                p = OUT_DIR / f"avatar_diag_ws_{i}.jpg"
                p.write_bytes(raw)
                print_layer(f"  帧 #{i}", info, p)
            if ws_frames:
                ws_ok = is_ok(analyze_jpeg(ws_frames[0], "ws#0"))
                if len(ws_frames) >= 2:
                    last = analyze_jpeg(ws_frames[-1], "ws#last")
                    print(f"  末帧 avg={last.get('avg')} max={last.get('max')} verdict={last.get('verdict')}")

    # ③ 前端提示
    print("\n=== ③ 浏览器显示层（刷新页面前在 Console 粘贴） ===")
    print("""
(function () {
  const NativeWS = WebSocket;
  window.WebSocket = function (...args) {
    const ws = new NativeWS(...args);
    ws.addEventListener("message", (e) => {
      if (typeof e.data !== "string") {
        const b = e.data instanceof Blob ? e.data : new Blob([e.data], { type: "image/jpeg" });
        window.__lastAvatarBlob = b;
        console.log("[avatar blob]", b.size, b.type);
      }
    });
    return ws;
  };
  window.WebSocket.prototype = NativeWS.prototype;
  console.log("hook OK，请刷新页面后看 [avatar blob] 日志");
})();
""".strip())

    # 总结
    print("\n" + "=" * 56)
    print("结论（按层排除）:")
    if not render_ok:
        print("  → 问题在 ① 渲染层：Playwright/Headless WebGL 抓出来就是黑/暗图")
        print("    请直接打开 /tmp/avatar_diag_render.jpg 肉眼确认")
    elif args.skip_ws:
        print("  → ① 渲染正常；请加 -- 无，继续测 WS 层")
    elif not ws_frames:
        print("  → ① 正常，② WS 无帧：推流/会话启动问题（writer 队列、avatar_ws_start）")
    elif not ws_ok:
        print("  → ① 正常，② WS 帧是黑/坏数据：推流编码或抓帧时机问题")
        print("    对比 /tmp/avatar_diag_render.jpg 与 /tmp/avatar_diag_ws_0.jpg")
    else:
        r_avg = render_info.get("avg")
        w_avg = analyze_jpeg(ws_frames[0], "cmp").get("avg")
        if r_avg and w_avg and abs(r_avg - w_avg) < 20:
            print("  → ①② 均正常且一致 → 问题在 ③ 前端显示（CSS/DOM/blob URL/img）")
            print("    Network 里 blob 缩略图有内容但黑屏，基本可确认是显示层")
        else:
            print("  → ①② 都有内容但差异大：推流过程中帧被损坏或切帧逻辑有问题")

    if render_path:
        print(f"\n请查看: {render_path}" + (" 及 /tmp/avatar_diag_ws_0.jpg" if ws_frames else ""))


if __name__ == "__main__":
    asyncio.run(main())
