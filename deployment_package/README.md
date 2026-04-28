# 视频打标与 Case Ingest 部署包

该目录提供一个可独立拷贝的运行时部署包，用于在目标机器上直接运行视频打标与 case-ingest 工具。

## 环境要求

- Windows
- Python 3.8+
- `ffmpeg.exe` 可在命令行中调用，或与部署目录放在同级
- `adb.exe` 可在命令行中调用（仅 case-ingest 流程需要）

## 部署前需要修改

请先检查并按目标机器修改：

- `default_config.json`
  - `input_dir`
  - `output_dir`
  - `paths.review_file`
  - `provider.api_key` 或 `provider.api_key_env`
- case-ingest 启动参数或配置中的 bat 路径与服务器路径

## 运行方式

视频打标主流程：

```bat
run_cli.bat
```

或：

```bash
python -m video_tagging_assistant.cli --config default_config.json
```

## 输出位置

默认输出会写到：

- `output/compressed/`
- `output/intermediate/`
- `output/review/review.txt`

## 安全说明

如果直接在 `default_config.json` 中填写 `provider.api_key`，请不要把该文件提交到共享仓库或发给无关人员。
