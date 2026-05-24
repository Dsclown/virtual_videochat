# virtual_videochat

虚拟人视频对话：**Gateway**（WebRTC / WebSocket 接入）与 **Core**（VAD / ASR / LLM / TTS / Live2D 渲染）为两个独立进程，经 `proto/` gRPC 通信，**互不 import 对方业务代码**。

---

## 进程架构

```
浏览器 → Web (:8780)  静态页 / 登录
              │  WS
              ▼
         Gateway (:8765)  ──gRPC──►  Core (:50051)
              │                         │
    WebRTC / Live2D 静态资源          对话编排 / 记忆 / 表单
```

| 服务 | 目录 | 入口 | 默认端口 |
|------|------|------|----------|
| **Core** | `backend/` | `backend/core_main.py` | gRPC `50051` |
| **Gateway** | `gateway/` | `gateway/main.py` | `8765` |
| **Web 测试端** | `web/` | `web/main.py` | `8780` |
| **契约** | `proto/vtuber/v1/core.proto` | `scripts/gen_grpc.py` | — |

- Web 通过 `VVC_GATEWAY_ORIGIN`（默认 `http://127.0.0.1:8765`）访问 Gateway API。
- Playwright 拉 Live2D 资源使用 `config.yaml` 中 `avatar.server_base_url`（指向 Gateway）。
- ICE / TURN 由 Gateway 读取；Core 不加载 `ice_servers`。

---

## 快速启动

```bash
cp config.example.yaml config.yaml
# 编辑 config.yaml：llm.api_key、avatar、TURN 等
./start.sh
```

浏览器打开 **http://127.0.0.1:8780**（不是 8765）。

环境变量（可选）：

| 变量 | 默认 | 说明 |
|------|------|------|
| `VVC_CORE_GRPC_PORT` | `50051` | Core gRPC |
| `VVC_HTTP_PORT` | `8765` | Gateway |
| `VVC_WEB_PORT` | `8780` | Web 测试页 |
| `VVC_GATEWAY_ORIGIN` | `http://127.0.0.1:8765` | Web → Gateway |

生成 gRPC 桩（改 proto 后执行）：

```bash
backend/.venv/bin/python scripts/gen_grpc.py
```

---

## 配置要点

根目录 `config.yaml`（参考 `config.example.yaml`）。

| 段 | 说明 |
|----|------|
| `character.system_prompt_file` | 角色人设，默认 `prompts/assistant.md` |
| `profile.form_rules_file` | 用户表单维护规则，默认 `prompts/profile_form_rules.md` |
| `memory.llm_context_rounds` | 送入 LLM 的最近对话轮数（每轮 user+assistant） |
| `memory.storage_dir` / `profile.storage_dir` | 用户数据目录，默认 `data/users` |
| `llm` / `asr` / `tts` / `vad` / `avatar` | 各模块提供商与参数 |

---

## 用户数据（按 `user_id`）

目录：`data/users/{user_id}/`

| 文件 | 格式 | 说明 |
|------|------|------|
| `profile_form.json` | JSON | 用户画像、当前话题、历史关注（见下） |
| `main.jsonl` | 每行一轮 | `{"ts","user","assistant"}`，仅当日加载进内存 |

**历史关注**每条：`content`、`mention_count`、`last_mentioned_at`；最多 10 条（强 6 / 弱 4），由 Core 排序与淘汰。LLM 通过 `historical_interest_updates` 增量更新，规则见 `prompts/profile_form_rules.md`。

---

## 单轮对话流程（Core）

1. **构建上下文**：人设 + 表单规则 + 当前表单 + 最近 N 轮对话 + 本轮用户输入。
2. **流式 LLM**：口语逐句送 TTS / Live2D；句末标点含 `。！？~～` 等（见 `sentence_buffer.py`）。
3. **回合结束**：解析末尾 `form_update` JSON → 更新表单与 `main.jsonl`（表单写盘在线程池，不阻塞 TTS 播放）。

口语与表单分离：JSON / ` ``` ` 围栏不会进 TTS；表单字段以用户表述为主，规则见 `profile_form_rules.md`。

---

## 目录结构

```
virtual_videochat/
├── config.yaml / config.example.yaml
├── prompts/
│   ├── assistant.md              # 角色人设
│   └── profile_form_rules.md     # 用户表单维护规则（LLM system 注入）
├── proto/vtuber/v1/core.proto
├── scripts/gen_grpc.py
├── data/users/                   # 运行时用户数据
├── gateway/                      # Gateway（WebRTC、WS、gRPC 客户端）
│   ├── main.py
│   ├── web_session.py
│   ├── core_client.py
│   └── grpc/v1/                  # 生成
├── web/                          # 测试页（静态资源 + 登录）
│   ├── main.py
│   └── app.js
└── backend/                      # Core
    ├── core_main.py
    └── vtuber/
        ├── grpc/servicer.py
        ├── core/
        │   ├── conversation_session.py
        │   └── orchestrator.py
        ├── modules/
        │   ├── profile/            # 表单存储、历史关注、回复解析
        │   ├── memory/             # 对话轮次 jsonl
        │   ├── llm|asr|tts|vad|avatar/
        │   └── ...
        └── utils/sentence_buffer.py  # 流式切句 / 剥离 JSON
```

---

## 扩展第三方平台

在 `gateway/` 下新增平台适配，复用 `core_client.py` 与 `webrtc_egress.py`；**勿改** `backend/vtuber/core/` 编排主流程。业务规则与 prompt 优先改 `prompts/` 与 `config.yaml`，而非硬编码进 Gateway。
