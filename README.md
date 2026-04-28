# 视频打标与 Case Ingest 工具

## 项目简介

这个项目用于支持两条日常流程：

- **视频打标**：扫描本地视频，压缩代理文件，调用模型生成标签与画面描述，并输出审核结果。
- **Case Ingest**：读取既有 bat 任务，执行 pull / copy / upload，把 case 采集归档流程统一到一个入口。

## 项目能力概览

### 视频打标流程

当前支持：

- 扫描待处理视频目录
- 压缩送模视频
- 组装结构化上下文
- 调用模型生成标签和画面描述
- 输出 review 文本和中间结果

### Case Ingest 流程

当前支持：

- 读取 `pull.bat` 和 `move.bat`
- 按 `case_A_xxxx` 聚合任务
- 执行 RK raw pull
- 复制 DJI normal / night 文件
- 上传整个 case 目录到服务器日期目录
- 支持可重跑的断点续传

## 环境要求

- Windows
- Python 3.8+
- `ffmpeg.exe`
- `adb.exe`（Case Ingest 需要）
- 可访问模型接口的网络环境（视频打标需要）
- 可访问目标共享目录的网络环境（Case Ingest 上传需要）

## 快速开始

### 视频打标

```bash
python -m video_tagging_assistant.cli --config video_tagging_assistant/default_config.json
```

也可以直接运行：

- `run_cli.bat`

### Case Ingest

推荐直接运行：

- `run_case_ingest.bat`

它会读取：

- `configs/case_ingest.json`

如果需要命令行运行：

```bash
python -m video_tagging_assistant.cli case-ingest --config configs/case_ingest.json
```

## 关键配置文件

### 视频打标

- `video_tagging_assistant/default_config.json`

重点配置：

- 输入目录：`input_dir`
- 输出目录：`output_dir`
- review 文件：`paths.review_file`
- 模型配置：`provider`

### Case Ingest

- `configs/case_ingest.json`

重点配置：

- `pull_bat`
- `move_bat`
- `server_root`
- `date`
- `skip_upload`

## 输出位置

### 视频打标

- 压缩视频：`output/compressed/`
- 中间结果：`output/intermediate/`
- 审核清单：`output/review/review.txt`

### Case Ingest

- 本地 RK raw 归档目录：由 `pull.bat` 中 `move_dst` 决定
- 本地 DJI 目标路径：由 `move.bat` 中目标路径决定
- 服务器目录：`<server_root>/<date>/case_A_xxxx`

## 延伸阅读

- 当前运行框架与模块职责：`docs/architecture.md`
- Case Ingest 详细使用说明：`docs/case-ingest-usage.md`
