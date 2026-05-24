# virtual_videochat

虚拟人视频对话：**Gateway**（平台接入 / WebRTC / WebSocket）与 **Core**（对话编排 / Live2D 渲染 / 记忆 / 表单）为两个独立进程，经 `proto/vtuber/v1/core.proto` gRPC 双向流通信，**互不 import 对方业务代码**。

流程图基于当前实现，使用 [Mermaid](https://mermaid.js.org/)，可在 GitHub README 中直接渲染。

---

## 架构总览

```mermaid
flowchart TB
  subgraph Browser["浏览器"]
    UI["测试页 UI"]
  end

  subgraph WebProc["web/"]
    STATIC["静态页 · gateway-config.js"]
  end

  subgraph GW["Gateway"]
    WS["WebSocket /ws"]
    WRTC["WebRTC egress"]
    GCLI["CoreGrpcClient"]
    BRIDGE["GatewayMediaBridge"]
  end

  subgraph Core["Core"]
    GRPC["gRPC ConnectSession"]
    SESS["CoreConversationSession"]
    ORCH["ConversationOrchestrator"]
    AV["AvatarRenderSession + Playwright"]
    ASSET["Live2D 静态资源 HTTP"]
  end

  UI -->|HTTP 拉页面| STATIC
  UI -->|WS 信令与麦克风| WS
  UI -->|WebRTC recvonly| WRTC
  WS --> GCLI
  WRTC --> BRIDGE
  GCLI <-->|"GatewayToCore / CoreToGateway"| GRPC
  GRPC --> SESS
  SESS --> ORCH
  SESS --> AV
  ORCH --> AV
  AV -->|HTTP 模型与 render.html| ASSET
  SESS -->|"MediaOut 音视频"| GRPC
  GRPC --> BRIDGE
  BRIDGE --> WRTC
```

| 组件 | 目录 | 职责 |
|------|------|------|
| **Core** | `backend/` | 会话、VAD/ASR/LLM/TTS、Avatar、用户数据 |
| **Core 资源 HTTP** | `backend/`（`assets_http.py`） | Live2D / `render-engine`，供 Playwright 拉取 |
| **Gateway** | `gateway/` | WS、WebRTC、转发 gRPC |
| **Web** | `web/` | 静态测试页；浏览器 **直连** Gateway 做 WS/WebRTC（不经 Web 进程转发） |

---

## 连接与鉴权（Web 测试端）

```mermaid
sequenceDiagram
  autonumber
  participant B as 浏览器
  participant W as Web
  participant G as Gateway
  participant C as Core

  B->>W: GET 静态页（login / chat）
  B->>G: WebSocket /ws
  Note over G: 建立 gRPC ConnectSession 双向流
  G-->>B: await_auth
  B->>G: auth { user_id }
  G->>C: OpenSession platform=web_test
  C->>C: 加载 profile_form · main.jsonl · 启动 VAD/Avatar
  C-->>G: SessionReady
  G-->>B: auth_ok
  B->>G: webrtc_offer
  G-->>B: webrtc_answer
  Note over B,G: WebRTC 接收虚拟人音视频
```

---

## 语音一轮（端到端）

虚拟人**声音与画面**经 **WebRTC** 下发；聊天区**字幕**经 WS `assistant_utterance`（仅文本）。

```mermaid
sequenceDiagram
  autonumber
  participant B as 浏览器
  participant G as Gateway
  participant C as CoreConversationSession
  participant O as ConversationOrchestrator

  par 媒体泵（与会话同生命周期）
    loop 周期性 tick
      C->>G: gRPC MediaOut audio/video
      G->>B: WebRTC 轨
    end
  and 用户说话
    loop 麦克风帧
      B->>G: WS raw_audio
      G->>C: AudioPcm
      C->>C: VadSession.feed
      C-->>G: vad 事件（可选）
      G-->>B: WS vad
    end
    C->>C: speech_end 后 ASR
    C-->>G: user_text
    G-->>B: WS user_text
    C->>O: run_turn_pcm → _run_dialogue
    Note over O: 详见下节
    O-->>G: assistant_utterance（文本）
    G-->>B: WS 字幕
    O-->>G: assistant_final · turn_done
    G-->>B: WS
  end
```

| 要点 | 说明 |
|------|------|
| 麦克风上行 | WS `raw_audio`，非 WebRTC 上行 |
| 虚拟人音视频 | Core 渲染 → gRPC `MediaOut` → Gateway → WebRTC |
| 表单与记忆 | Core 写 `profile_form.json`、`main.jsonl` |
| 文本输入 | WS `user_text` 可走同一套编排（跳过 ASR） |

---

## Core 内：一轮对话编排时序

```mermaid
sequenceDiagram
  participant O as ConversationOrchestrator
  participant L as LLM 流
  participant T as TtsSession
  participant A as AvatarRenderSession
  participant M as memory / profile
  participant G as 经 gRPC 到 Gateway

  O->>G: user_text
  O->>T: async with TtsSession
  loop 流式 token
    L-->>O: token
    O->>O: truncate_before_json · 切句
    O->>T: speak（异步合成，按序下发）
    T->>A: feed_utterance + Live2D 动作
    T->>G: assistant_utterance
  end
  Note over O: 流结束后 flush 剩余口语句
  O->>M: parse · append_turn · apply_update
  O->>G: assistant_final
  Note over T: 更早的 speak 可能仍在合成
  O->>T: finish() 等待队列结束
  O->>A: wait_playback_drained
  O->>A: reset_to_idle_motion
  O->>G: turn_done
```

---

## 用户数据（按 `user_id`）

目录：`data/users/{user_id}/`

| 文件 | 说明 |
|------|------|
| `profile_form.json` | 画像、当前话题、历史关注 |
| `main.jsonl` | 当日对话轮次 |

规则见 `prompts/profile_form_rules.md`。

---

## 快速启动

```bash
cp config.example.yaml config.yaml
# 编辑 config.yaml（API Key 等）
./start.sh
```

生成 gRPC 桩：`backend/.venv/bin/python scripts/gen_grpc.py`  
端口与环境变量见 `config.example.yaml`、`start.sh`。

---

## 目录结构

```
virtual_videochat/
├── proto/vtuber/v1/core.proto
├── gateway/
├── web/
├── assets/live2d/
├── render-engine/
└── backend/
    └── vtuber/core/
        ├── conversation_session.py
        └── orchestrator.py
```

---

## 扩展第三方平台

在 `gateway/` 增加会话适配，复用 `core_client.py`、`webrtc_egress.py`；Core 编排与 Avatar 逻辑保持不变。
