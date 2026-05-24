# virtual_videochat

模块化虚拟语音对话系统：流式 ASR → LLM → TTS，服务端 Live2D 渲染，**WebRTC 实时推流**（音视频同源、口型同步）。

参考 [Open-LLM-VTuber](https://github.com/Open-LLM-VTuber) 的模块划分，在对话管线之上增加了**可替换的音视频传输层**，便于后续接入 LiveKit、Agora、TRTC、SRS 等第三方 RTC 平台。

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
| 音视频 | **WebRTC**（aiortc）经 **TURN** 中继；WS 仅信令与控制 |
| 口型 | TTS PCM → RMS 包络 → `PARAM_MOUTH_OPEN_Y`（与音频同源） |
| 记忆 / 画像 | JSON 文件存储，LLM 每轮更新用户表单 |

**默认传输模式**（`config.yaml`）：

- 视频：WebRTC 视频轨（服务端按抓帧节拍推流，**不重复编码同一帧**）
- 音频：WebRTC 音频轨（TTS PCM 实时编码，非 WS 整段 MP3）
- 信令：WebSocket（登录、对话文字、SDP/ICE、`stage`）
- 跨网 / SSH 隧道：配置 TURN + `ice_transport_policy: relay`
- 前端：仅 WebRTC 播放（`<video>` + canvas 绘制），画面右上角显示 **WebRTC 解码帧率**

> 已移除 WebSocket JPEG 视频回退与 `video_transport` 配置；传输面统一为 WebRTC。

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

各模块通过 `Factory` + `config.yaml` 的 `provider` 切换，**编排层不感知具体厂商**。

### Avatar 抓帧链路

```
Playwright 打开 render.html
    → Live2D WebGL 绘制
    → canvas.captureStream(fps)
    → 离屏 canvas 采样 RGB（base64 回传 Python）
    → PyAV rgb24 → H.264（aiortc）
    → TURN → 浏览器解码
    → 前端 canvas 以显示器刷新率重绘（观感可高于解码帧率）
```

### 信令与媒体分离（核心设计）

```
浏览器                          服务端
  │                               │
  │◄──── WebSocket ──────────────►│  auth / 对话 / stage / turn_id
  │      (JSON 控制面)            │
  │                               │
  │◄════ WebRTC (SRTP) ═════════►│  AvatarVideoTrack  ← 新抓帧才 send
  │      经 STUN/TURN             │  AvatarAudioTrack  ← TTS PCM 队列
  │      (媒体面)                 │
```

- **控制面**：回合状态、文字、打断、WebRTC 协商——走 WebSocket
- **媒体面**：音视频帧——走 WebRTC，不经过 WS 文件式下发
- **回合结束 / 打断**：由服务端 `AvatarStreamSession` 管理 PCM 队列与播放生命周期，前端只收流与展示

### 为何方便接第三方音视频平台

当前实现把「**产生媒体**」和「**送出媒体**」拆成两层，后续替换成本低：

| 层级 | 现状 | 可替换为 |
|------|------|----------|
| **媒体源** | TTS → PCM 队列；Playwright → RGB 帧 | 不变，或改为客户端 Live2D |
| **编码与推流** | aiortc `MediaStreamTrack` | LiveKit SDK、Agora、TRTC、GStreamer、FFmpeg RTMP |
| **网络穿透** | `config.avatar.ice_servers`（STUN/TURN） | 任意平台提供的 ICE 配置 |
| **信令** | WS 交换 SDP/ICE | 平台 REST / 房间 Token / WHIP/WHEP |

**接入思路示例**：

1. **保留 PCM + 视频帧队列**，将 `AvatarAudioTrack` / `AvatarVideoTrack` 的实现从 aiortc 改为目标 SDK 的 publish 接口
2. **保留 WS 会话**，仅替换 `webrtc_offer` / `webrtc_ice` handler 为平台房间加入逻辑
3. **ICE/TURN** 已在 `AvatarConfig.ice_servers` 配置化，可填云厂商凭证，无需改代码
4. **TTS 管线**（`TtsSession` 按序合成 → `feed_utterance`）与传输无关，换平台后仍保证音画同源

---

## 性能与资源（参考）

默认 **360×360 @ 10fps**（2 核 VPS 上实测抓帧约 **9–10 fps**，480p 约 3 fps）。

| 项目 | 约值（推流进行中） |
|------|-------------------|
| Avatar 栈 CPU 合计 | ~1.2–1.5 核（Chromium GPU/Renderer + Playwright + Python） |
| Chromium RSS | ~600–800 MB |
| Python worker RSS | 含 LLM/ASR 等，视会话而定 |

瓶颈主要在 **无头 Chrome WebGL + 每帧 RGB 回传**（`page.evaluate`）。前端 canvas 以 ~60Hz 重绘同一解码帧，**观感可较解码帧率更顺**，角标「解码 fps」以 WebRTC `framesDecoded` 为准。

**诊断命令**（需 uvicorn 已启动）：

```bash
cd backend
.venv/bin/python scripts/benchmark_avatar_fps.py    # 服务端抓帧 FPS
.venv/bin/python scripts/diagnose_avatar.py         # 渲染页 / 抓帧健康检查
```

---

## 目录结构

```
virtual_videochat/
├── config.example.yaml       # 配置模板（复制为 config.yaml）
├── prompts/                  # 角色 system prompt
├── frontend/                 # Web 前端（WebRTC + canvas + 解码 fps 角标）
├── assets/live2d/            # Cubism Core + 模型（见 assets/live2d/README.md）
├── render-engine/
│   └── cubism-sdk-live2d/    # Live2D 渲染页（Vite → avatar.js，含 canvas-capture.ts）
├── deploy/coturn/            # TURN 部署模板
├── backend/
│   ├── main.py
│   ├── scripts/
│   │   ├── benchmark_avatar_fps.py
│   │   └── diagnose_avatar.py
│   └── vtuber/
│       ├── core/             # Orchestrator、WsSession、VAD
│       ├── modules/
│       │   ├── avatar/       # Playwright、captureStream、WebRTC tracks、口型
│       │   ├── tts/          # TtsSession 按序下发
│       │   ├── asr/ llm/ memory/ profile/ vad/
│       └── config/
└── start.sh                  # 一键启动（含 Playwright 浏览器检查）
```

---

## 环境要求

- Python 3.10+
- **ffmpeg**（音频转码）
- **Playwright Chromium**（Avatar 渲染，`start.sh` 首次自动安装）
- ASR 模型：首次运行下载 sherpa SenseVoice（见 `config.yaml` 的 `asr.model_dir`）
- Live2D 模型：放入 `assets/live2d/models/<model_name>/`
- 跨网 WebRTC：部署 [coturn](deploy/coturn/turnserver.conf.example) 并填写 TURN 配置

构建渲染引擎（修改 Live2D 页面后）：

```bash
cd render-engine/cubism-sdk-live2d
npm install && npm run build
```

---

## 快速启动

```bash
git clone git@github.com:Dsclown/virtual_videochat.git
cd virtual_videochat
cp config.example.yaml config.yaml
# 编辑 config.yaml：llm.api_key、TURN、模型路径等

./start.sh
# 或：cd backend && .venv/bin/uvicorn main:app --host 0.0.0.0 --port 8765
```

浏览器：`http://localhost:8765/login.html` → 输入 user_id → 对话页。

SSH 隧道访问服务器：

```bash
ssh -L 8765:127.0.0.1:8765 user@your-server
# 本地打开 http://127.0.0.1:8765
```

### 关键配置（`config.yaml`）

```yaml
avatar:
  width: 360                   # 非 4 的倍数宽度需注意 PyAV rgb24 stride 对齐（代码已处理）
  height: 360
  fps: 10                      # captureStream / 渲染循环目标帧率
  webrtc_enabled: true
  suppress_ws_audio: true        # WebRTC 出声时不走 WS MP3
  ice_transport_policy: relay    # 跨网建议 relay
  ice_servers:
    - urls: "stun:stun.l.google.com:19302"
    - urls: "turn:YOUR_HOST:3478"
      username: "..."
      credential: "..."
```

### 登录与数据

- 登录：仅 `user_id`（无密码），数据在 `data/users/<user_id>/`
- 对话记忆：`main.json`；用户画像表单：`profile_form.json`（LLM 每轮 `form_update` 更新）

---

## 扩展新模块

1. 在 `backend/vtuber/modules/<name>/` 实现 `base.py` 接口  
2. 在 `factory.py` 注册 `provider`  
3. 在 `config.yaml` 切换  

对话主流程（`ConversationOrchestrator`）无需修改。

扩展新音视频平台：实现与 `AvatarStreamSession` 同级的推流会话，或替换 `webrtc_tracks.py` 中的 Track 实现，复用现有 PCM / 帧队列与 `TtsSession` 即可。

---

## 相关文档

- Live2D 模型放置：`assets/live2d/README.md`
- TURN 部署：`deploy/coturn/turnserver.conf.example`
