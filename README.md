# virtual_videochat

模块化虚拟语音对话系统：流式 ASR → LLM → TTS，服务端 Live2D 渲染，**WebRTC 实时推流**（音视频同源、口型同步）。

参考 [Open-LLM-VTuber](https://github.com/Open-LLM-VTuber) 的模块划分；媒体层按 **Ingress（用户上行）/ Egress（虚拟人下行）** 分离，便于后续在 Gateway 层对接飞书、SIP、云 RTC 等第三方通话平台。

---

## 现状概览

| 能力 | 实现 |
|------|------|
| 对话编排 | 聆听 → 思考 → 回应（`ConversationOrchestrator`） |
| ASR | sherpa-onnx SenseVoice（本地 CPU） |
| LLM | OpenAI 兼容 API（DeepSeek 等） |
| TTS | Edge TTS，切句并行合成、按序下发 |
| VAD / 打断 | Silero VAD + 语音过滤，服务端统一处理打断 |
| Avatar | Playwright + Cubism Web SDK；**canvas.captureStream** 浏览器内采样 RGB |
| 用户麦克风 | WebSocket **`raw_audio`**（16kHz float PCM JSON）→ VAD → ASR |
| 虚拟人 A/V | **WebRTC**（aiortc）经 **TURN**；有 Avatar 时 **不经 WS 下发 MP3** |
| Live2D 表情 | LLM **`[joy]` 等标签** → `model_dict.json` → 每句 TTS 前触发 |
| 用户画像 | LLM 末尾 **`form_update` JSON**（与口语分离，不念给用户） |
| 记忆 | `main.jsonl`；画像表单 `profile_form.json` |

**默认传输模式**（`config.yaml`）：

| 方向 | 协议 | 说明 |
|------|------|------|
| **Ingress** | WS `raw_audio` | 浏览器降采样 16kHz → 服务端 VAD/ASR（类微信通话的 WebRTC 上行留作 Gateway 演进） |
| **Egress** | WebRTC 音视频轨 | TTS PCM + 抓帧视频；信令仍走 WS（SDP/ICE、`stage`） |
| **控制面** | WebSocket JSON | 登录、对话文字、打断、`turn_id`、VAD 事件 |

> 已移除：WS JPEG 视频、`video_transport`、WS 二进制音频、JSON `emotion/gesture/scene`、客户端 Pixi 栈、WS MP3 双路出声（`suppress_ws_audio`）。

配置加载：**必须存在 `config.yaml`**（`cp config.example.yaml config.yaml`），缺字段或未知字段会报错，无静默默认值。

---

## 架构

### 对话与模块

```
┌──────────────────────────────────────────────────────────────┐
│                 ConversationOrchestrator                      │
│              聆听 → 思考 → 回应（TtsSession 按序）              │
└──────┬─────────┬─────────┬─────────┬─────────┬───────────────┘
       │         │         │         │         │
   ┌───▼───┐ ┌──▼──┐  ┌───▼───┐ ┌───▼───┐ ┌───▼──────────────┐
   │  ASR  │ │ LLM │  │  TTS  │ │Memory │ │ AvatarStreamSession│
   └───────┘ └─────┘  └───┬───┘ └───────┘ │ 渲染 + PCM 队列    │
                          │               └───┬────────────┬───┘
                          │                   │            │
                          └─────── PCM ────────┘            │
                                                            ▼
                                                    WebRTC Tracks
                                                    (video / audio)
```

各模块通过 `Factory` + `config.yaml` 的 `provider` 切换；`avatar.provider` 支持 `playwright`（当前）与 `live2d`（扩展占位）。

### Ingress / Egress 与第三方平台（规划）

```
第三方 / 浏览器                    Gateway（薄适配，规划中）           核心
─────────────────                  ────────────────────────          ────
飞书 / SIP / 云 RTC  ──decode──►   48k Opus → 16k mono float  ──►  VadSession.feed
浏览器 WS raw_audio  ──────────►   （已是 16k，直通）           ──►  ASR → LLM → TTS
                                                                        │
浏览器 / 第三方      ◄──encode──   WebRTC / 厂商推流          ◄──  AvatarStreamSession
```

- **核心契约**：Ingress 统一为 **16kHz mono PCM + VAD 事件**；Egress 为 **音视频轨或编码帧队列**。
- **Gateway**：只做编解码、重采样、平台信令；**不含**切句、表单、`[joy]` 等业务逻辑。
- 浏览器自建页后续可增加 **WebRTC 上行** Gateway，VAD/ASR 逻辑不变。

### Avatar 抓帧链路

```
Playwright 打开 render.html
    → Live2D WebGL 绘制（[joy] → 表情 / 动作）
    → canvas.captureStream(fps)
    → 离屏 canvas 采样 RGB（回传 Python）
    → PyAV rgb24 → H.264（aiortc，stride 对齐）
    → TURN → 浏览器解码 → canvas 重绘
```

### 信令与媒体分离

```
浏览器                          服务端
  │                               │
  │◄──── WebSocket ──────────────►│  auth / raw_audio / 对话 / SDP·ICE
  │      (控制 + 麦克风 PCM)      │
  │                               │
  │◄════ WebRTC (SRTP) ═════════►│  AvatarVideoTrack / AvatarAudioTrack
  │      经 STUN/TURN             │
```

### 接第三方音视频平台

| 层级 | 现状 | Gateway 可替换为 |
|------|------|------------------|
| **Ingress** | WS 16k PCM | WebRTC 上行、SIP、TRTC Server 拉流 → 同一 `VadSession` |
| **媒体源** | TTS PCM + Playwright RGB | 不变 |
| **Egress 编码** | aiortc `MediaStreamTrack` | LiveKit、Agora、WHIP 等 |
| **信令** | WS SDP/ICE | 平台房间 Token / REST |
| **穿透** | `avatar.ice_servers` | 各厂商 STUN/TURN |

---

## 性能与资源（参考）

默认 **360×360 @ 10fps**（2 核 VPS 上实测抓帧约 **9–10 fps**）。

| 项目 | 约值（推流进行中） |
|------|-------------------|
| Avatar 栈 CPU | ~1.2–1.5 核 / 路（Chromium + Playwright + Python） |
| Chromium RSS | ~600–800 MB |
| ASR 池 | `asr.pool_size` 槽（与 WebRTC 路数独立） |

瓶颈主要在 **无头 Chrome WebGL + RGB 回传**。前端 canvas ~60Hz 重绘同一解码帧，角标 **解码 fps** 以 WebRTC `framesDecoded` 为准。

**诊断命令**（需服务已启动）：

```bash
cd backend
.venv/bin/python scripts/benchmark_avatar_fps.py    # 服务端抓帧 FPS
.venv/bin/python scripts/diagnose_avatar.py         # 渲染页 / 抓帧健康检查
.venv/bin/python scripts/stress_test.py --help      # ASR / WS 全通路压测
```

---

## 目录结构

```
virtual_videochat/
├── config.example.yaml       # 配置模板（复制为 config.yaml，必填）
├── prompts/
│   ├── assistant.md
│   └── utils/live2d_expression_prompt.txt
├── frontend/                 # WebRTC 播放 + WS 麦克风 + 解码 fps 角标
├── assets/live2d/
│   ├── model_dict.json       # [joy] 等 → 表情/动作
│   └── models/               # Cubism 模型目录
├── render-engine/cubism-sdk-live2d/
├── deploy/coturn/
├── backend/
│   ├── main.py
│   ├── scripts/              # benchmark / diagnose / stress_test
│   └── vtuber/
│       ├── core/               # Orchestrator、WsSession、VAD
│       └── modules/
│           ├── avatar/       # Playwright、WebRTC、live2d_model、[joy]
│           ├── tts/ asr/ llm/ memory/ profile/ vad/
│           └── config/       # 严格 YAML 加载
└── start.sh
```

---

## 环境要求

- Python 3.10+
- **ffmpeg**（音频转码）
- **Playwright Chromium**（`start.sh` 首次自动安装）
- ASR：sherpa SenseVoice（`asr.model_dir`）
- Live2D：`assets/live2d/models/<model_name>/`（见 `assets/live2d/README.md`）
- 跨网 WebRTC：[coturn](deploy/coturn/turnserver.conf.example)

修改渲染页后：

```bash
cd render-engine/cubism-sdk-live2d && npm install && npm run build
```

---

## 快速启动

```bash
cp config.example.yaml config.yaml
# 编辑：llm.api_key、TURN、avatar.model_name 等

./start.sh
# 或：cd backend && .venv/bin/uvicorn main:app --host 0.0.0.0 --port 8765
```

浏览器：`http://localhost:8765/login.html` → 输入 user_id。

SSH 隧道：`ssh -L 8765:127.0.0.1:8765 user@server` → `http://127.0.0.1:8765`

### 关键配置（`config.yaml`）

```yaml
avatar:
  provider: playwright          # playwright | live2d（扩展占位）
  model_name: mao_pro
  width: 360
  height: 360
  fps: 10
  webrtc_enabled: true          # 虚拟人音视频走 WebRTC
  live2d_expressions_enabled: true
  model_dict_path: assets/live2d/model_dict.json
  ice_transport_policy: relay
  ice_servers: [ ... ]

asr:
  pool_size: 1                  # 并发 ASR 路数

system:
  vad_executor_workers: 1
  io_executor_workers: 1
```

### 登录与数据

- 登录：仅 `user_id`（无密码）→ `data/users/<user_id>/`
- 对话记忆：`main.jsonl`
- 用户画像：`profile_form.json`（LLM `form_update`）

---

## 扩展

**新对话模块**：`modules/<name>/` + `factory.py` + `config.yaml` 的 `provider`。

**新音视频平台**：实现 Gateway Ingress/Egress，输出 16k PCM / 接收编码轨；复用 `VadSession`、`AvatarStreamSession`、`TtsSession`。

**新 Avatar 渲染**：`avatar.provider: live2d` 预留；当前生产路径为 `playwright`。

---

## 相关文档

- Live2D 模型与 `[joy]`：`assets/live2d/README.md`
- TURN：`deploy/coturn/turnserver.conf.example`
