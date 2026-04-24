# 视频打标工具部署说明

## 1. 项目作用

该工具用于：
- 扫描本地视频
- 压缩视频代理文件
- 调用 Qwen / DashScope 分析视频内容
- 输出结构化标签与详细画面描述
- 生成本地 `review.txt` 供人工审核

## 2. 环境要求

- Windows
- Python 3.8+
- `ffmpeg.exe`
- 可访问 DashScope / 百炼接口的网络环境

## 3. 安装依赖

在部署目录中执行：

```bash
pip install -r requirements.txt
```

## 4. 需要准备的内容

- 将待分析视频放到配置文件指定的 `input_dir` 中
- 确保 `ffmpeg.exe` 可以在命令行中调用，或与项目放在同级目录
- 在 `default_config.json` 中配置：
  - 输入目录
  - 输出目录
  - review 文件路径
  - 模型名
  - API Key
  - 标签候选项
  - 并发参数

## 5. 配置文件重点字段

### 路径
- `input_dir`
- `output_dir`
- `paths.compressed_dir`
- `paths.intermediate_dir`
- `paths.review_file`

### Provider
- `provider.model`
- `provider.base_url`
- `provider.api_key_env`
- `provider.api_key`
- `provider.fps`

### 并发
- `concurrency.compression_workers`
- `concurrency.provider_workers`
- `concurrency.max_retries`
- `concurrency.retry_backoff_seconds`
- `concurrency.retry_backoff_multiplier`

### 标签模板
- `prompt_template.single_choice_fields`
- `prompt_template.multi_choice_fields`
- `prompt_template.ignore_opening_instruction`
- `prompt_template.scene_description_instruction`

## 6. 运行方式

```bash
python -m video_tagging_assistant.cli --config default_config.json
```

或双击：

- `run_cli.bat`

## 7. 输出位置

- Review 审核清单：`paths.review_file`
- 中间 JSON：`paths.intermediate_dir`
- 压缩后视频：`paths.compressed_dir`

## 8. 迁移到其他电脑

迁移时通常只需要：
- 复制整个部署目录
- 安装 Python 依赖
- 准备 `ffmpeg.exe`
- 修改 `default_config.json` 中的路径和 API 配置

一般不需要改核心代码。

## 9. 安全提示

当前配置支持把 DashScope API Key 直接写在 `default_config.json` 里，部署方便，但存在泄露风险。
建议后续切换到环境变量方式。
