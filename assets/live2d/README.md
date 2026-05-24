# Live2D 模型

将 Cubism 模型目录放到本目录下，例如：

```
assets/live2d/models/mao_pro/runtime/mao_pro.model3.json
```

或复用 Open-LLM-VTuber 资源（当前推荐，已符号链接）：

```bash
ln -sf /path/to/Open-LLM-VTuber/live2d-models assets/live2d/models
```

`config.yaml` 中 `avatar.model_name` 需与模型文件夹名一致（`config.example.yaml` 默认 `mao_pro`）。

表情 / 随机动作（对齐 Open-LLM-VTuber）：

- `assets/live2d/model_dict.json`：`emotionMap` 将 LLM 的 `[joy]` 等映射为 **动作组**（shizuku）或 **表情索引**（带 Expressions 的模型如 mao_pro）
- `config.yaml`：`avatar.live2d_expressions_enabled: true` 时，system prompt 会注入 `prompts/utils/live2d_expression_prompt.txt`
- 待机：`Idle` 组在每次 motion 播完后随机重播（渲染循环 `tick` 驱动）
- 说话：每句 TTS 前触发 `talkMotionGroupName`（shizuku 默认 `Tap`）
