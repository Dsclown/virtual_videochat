# Live2D 模型

将 Cubism 模型目录放到本目录下，例如：

```
assets/live2d/models/shizuku/
  shizuku.model3.json
  ...
```

或创建符号链接（开发机示例）：

```bash
ln -s /path/to/live2d-models assets/live2d/models
```

`config.yaml` 中 `avatar.model_name` 需与模型文件夹名一致（默认 `shizuku`）。
