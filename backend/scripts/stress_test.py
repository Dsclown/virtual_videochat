#!/usr/bin/env python3
"""并发压测：ASR 池 / WS 文本回合 / WS 语音全通路（VAD→ASR→LLM→TTS）。"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

BACKEND_ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = Path(__file__).resolve().parent / ".cache"
SPEECH_PCM_CACHE = CACHE_DIR / "stress_speech_16k_f32.npy"
CHUNK_SAMPLES = 4096
SAMPLE_RATE = 16000

sys.path.insert(0, str(BACKEND_ROOT))

import edge_tts  # noqa: E402
import websockets  # noqa: E402

from vtuber.config.loader import ASRConfig  # noqa: E402
from vtuber.modules.asr.sherpa_onnx import SherpaOnnxASR  # noqa: E402


async def ensure_speech_pcm() -> np.ndarray:
    """生成/缓存一段真实语音 PCM，供 VAD+ASR 触发。"""
    if SPEECH_PCM_CACHE.is_file():
        return np.load(SPEECH_PCM_CACHE)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    text = "你好，这是全通路压力测试。"
    voice = "zh-CN-XiaoxiaoNeural"
    with tempfile.TemporaryDirectory() as td:
        mp3 = Path(td) / "stress.mp3"
        pcm_out = Path(td) / "stress.pcm"
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(str(mp3))
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", str(mp3),
                "-ac", "1", "-ar", str(SAMPLE_RATE),
                "-f", "f32le", "-acodec", "pcm_f32le", str(pcm_out),
            ],
            check=True,
            capture_output=True,
        )
        speech = np.fromfile(pcm_out, dtype=np.float32)
    # 前后静音，便于 Silero 切段
    prefix = np.zeros(int(0.6 * SAMPLE_RATE), dtype=np.float32)
    suffix = np.zeros(int(1.2 * SAMPLE_RATE), dtype=np.float32)
    pcm = np.concatenate([prefix, speech, suffix])
    np.save(SPEECH_PCM_CACHE, pcm)
    return pcm


async def stress_asr_pool(clients: int) -> list[dict]:
    asr = SherpaOnnxASR(ASRConfig())
    pcm = np.zeros(SAMPLE_RATE, dtype=np.float32)

    async def one(i: int) -> dict:
        t0 = time.perf_counter()
        try:
            await asr.transcribe_pcm(pcm)
            return {"kind": "asr", "id": i, "ok": True, "latency_s": round(time.perf_counter() - t0, 3)}
        except Exception as e:
            return {"kind": "asr", "id": i, "ok": False, "latency_s": round(time.perf_counter() - t0, 3), "error": str(e)}

    t0 = time.perf_counter()
    results = list(await asyncio.gather(*[one(i) for i in range(clients)]))
    wall = round(time.perf_counter() - t0, 3)
    ok = sum(1 for r in results if r["ok"])
    print(f"\n[ASR 池] 并发 {clients} 路 | 成功 {ok}/{clients} | 总耗时 {wall}s")
    for r in sorted(results, key=lambda x: x["id"]):
        tag = "OK" if r["ok"] else f"FAIL {r.get('error')}"
        print(f"  #{r['id']} {r['latency_s']}s {tag}")
    return results


async def _ws_auth(ws, user_id: str) -> str | None:
    first = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
    if first.get("type") != "await_auth":
        return f"unexpected first: {first.get('type')}"
    await ws.send(json.dumps({"type": "auth", "user_id": user_id}))
    auth = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
    if auth.get("type") != "auth_ok":
        return f"auth failed: {auth}"
    return None


async def stress_ws_text_turn(ws_url: str, client_id: int, *, timeout: float) -> dict:
    user_id = f"stress_text_{client_id}"
    t0 = time.perf_counter()
    out: dict = {
        "kind": "ws_text",
        "id": client_id,
        "ok": False,
        "latency_s": None,
        "error": None,
    }
    try:
        async with websockets.connect(ws_url, max_size=20 * 1024 * 1024) as ws:
            err = await _ws_auth(ws, user_id)
            if err:
                out["error"] = err
                return out
            await ws.send(json.dumps({
                "type": "user_text",
                "text": f"第{client_id}路文本压测，请只回复一个字：好",
            }))
            deadline = time.perf_counter() + timeout
            while time.perf_counter() < deadline:
                remain = deadline - time.perf_counter()
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=max(0.1, remain)))
                if msg.get("type") == "error":
                    out["error"] = msg.get("message")
                    return out
                if msg.get("type") == "turn_done":
                    out["ok"] = True
                    out["latency_s"] = round(time.perf_counter() - t0, 2)
                    return out
    except Exception as e:
        out["error"] = str(e)
    if out["latency_s"] is None:
        out["latency_s"] = round(time.perf_counter() - t0, 2)
    return out


async def stress_ws_voice_turn(
    ws_url: str,
    client_id: int,
    pcm: np.ndarray,
    *,
    timeout: float,
    realtime: bool,
) -> dict:
    """auth → 流式 raw_audio → 等 user_text + assistant_utterance + turn_done。"""
    user_id = f"stress_voice_{client_id}"
    t0 = time.perf_counter()
    out: dict = {
        "kind": "ws_voice",
        "id": client_id,
        "ok": False,
        "latency_s": None,
        "error": None,
        "user_text": None,
        "utterances": 0,
        "asr_s": None,
        "turn_s": None,
    }

    async def stream_audio(ws) -> None:
        for i in range(0, len(pcm), CHUNK_SAMPLES):
            chunk = pcm[i : i + CHUNK_SAMPLES]
            await ws.send(json.dumps({"type": "raw_audio", "audio": chunk.tolist()}))
            if realtime:
                await asyncio.sleep(len(chunk) / SAMPLE_RATE)

    try:
        async with websockets.connect(ws_url, max_size=20 * 1024 * 1024) as ws:
            err = await _ws_auth(ws, user_id)
            if err:
                out["error"] = err
                return out

            stream_task = asyncio.create_task(stream_audio(ws))
            deadline = time.perf_counter() + timeout
            asr_at: float | None = None

            while time.perf_counter() < deadline:
                remain = deadline - time.perf_counter()
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=max(0.1, remain)))
                t = msg.get("type")
                if t == "error":
                    out["error"] = msg.get("message")
                    break
                if t == "user_text":
                    out["user_text"] = msg.get("text")
                    asr_at = time.perf_counter()
                    out["asr_s"] = round(asr_at - t0, 2)
                elif t == "assistant_utterance" and msg.get("data"):
                    out["utterances"] += 1
                elif t == "turn_done":
                    out["ok"] = True
                    out["turn_s"] = round(time.perf_counter() - t0, 2)
                    break

            if not stream_task.done():
                stream_task.cancel()
                try:
                    await stream_task
                except asyncio.CancelledError:
                    pass
    except Exception as e:
        out["error"] = str(e)

    if out["latency_s"] is None:
        out["latency_s"] = out.get("turn_s") or round(time.perf_counter() - t0, 2)
    return out


async def run_batch(name: str, coros: list) -> list[dict]:
    t0 = time.perf_counter()
    results = list(await asyncio.gather(*coros))
    wall = round(time.perf_counter() - t0, 2)
    ok = sum(1 for r in results if r["ok"])
    print(f"\n[{name}] 成功 {ok}/{len(results)} | 总耗时 {wall}s")
    return results


def print_voice_results(results: list[dict]) -> None:
    for r in sorted(results, key=lambda x: x["id"]):
        if r["ok"]:
            print(
                f"  stress_voice_{r['id']} ASR@{r.get('asr_s')}s "
                f"turn@{r.get('turn_s')}s utter={r.get('utterances')} "
                f"asr_text={r.get('user_text')!r}"
            )
        else:
            print(
                f"  stress_voice_{r['id']} FAIL {r.get('error')} "
                f"({r.get('latency_s')}s partial={r.get('user_text')!r})"
            )


async def main() -> int:
    p = argparse.ArgumentParser(description="virtual_videochat 压力测试")
    p.add_argument("--clients", type=int, default=5)
    p.add_argument("--ws-url", default="ws://127.0.0.1:8765/ws")
    p.add_argument("--timeout", type=float, default=180.0)
    p.add_argument(
        "--mode",
        choices=("all", "asr", "text", "voice"),
        default="all",
        help="all=ASR池+文本+语音全通路",
    )
    p.add_argument(
        "--realtime",
        action="store_true",
        default=True,
        help="语音流按实时速率发送（默认开，避免 raw_audio 队列丢帧）",
    )
    p.add_argument(
        "--no-realtime",
        action="store_false",
        dest="realtime",
        help="尽快发完 PCM（易触发 VAD 丢帧，仅调试）",
    )
    args = p.parse_args()

    print(f"=== 压测 mode={args.mode} clients={args.clients} ===")
    all_ok = True

    if args.mode in ("all", "asr"):
        asr_results = await stress_asr_pool(args.clients)
        all_ok &= all(r["ok"] for r in asr_results)

    if args.mode in ("all", "text"):
        text_results = await run_batch(
            "WebSocket 文本",
            [
                stress_ws_text_turn(args.ws_url, i, timeout=args.timeout)
                for i in range(args.clients)
            ],
        )
        for r in sorted(text_results, key=lambda x: x["id"]):
            tag = f"turn_done {r['latency_s']}s" if r["ok"] else f"FAIL {r.get('error')}"
            print(f"  stress_text_{r['id']} {tag}")
        all_ok &= all(r["ok"] for r in text_results)

    if args.mode in ("all", "voice"):
        print("\n准备语音样本（edge-tts + ffmpeg，首次较慢）…")
        pcm = await ensure_speech_pcm()
        print(f"  样本 {len(pcm)/SAMPLE_RATE:.1f}s @16kHz")
        voice_results = await run_batch(
            "WebSocket 语音全通路 VAD→ASR→LLM→TTS",
            [
                stress_ws_voice_turn(
                    args.ws_url, i, pcm, timeout=args.timeout, realtime=args.realtime
                )
                for i in range(args.clients)
            ],
        )
        print_voice_results(voice_results)
        all_ok &= all(r["ok"] for r in voice_results)

    print("\n=== 完成 ===")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
