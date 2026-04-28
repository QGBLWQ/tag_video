# 架构说明

## 系统概览

当前项目包含两条主流程：

1. **视频打标流程**
   - 面向本地视频理解与审核输出
2. **Case Ingest 流程**
   - 面向 case 采集归档、补拷与上传

统一入口位于 `video_tagging_assistant/cli.py`。

## 运行入口与分流

CLI 有两种主要模式：

- 默认模式：运行视频打标流程
  - `python -m video_tagging_assistant.cli --config video_tagging_assistant/default_config.json`
- 子命令模式：运行 Case Ingest
  - `python -m video_tagging_assistant.cli case-ingest --config configs/case_ingest.json`

其中：

- 视频打标主要依赖 JSON 配置文件
- Case Ingest 既支持直接命令行参数，也支持通过 `configs/case_ingest.json` 读取运行参数
- `run_case_ingest.bat` 是当前推荐的 Case Ingest 启动入口

## 视频打标流程架构

视频打标主流程由 `video_tagging_assistant/orchestrator.py` 串联，核心模块如下：

- `video_tagging_assistant/scanner.py`
  - 扫描输入目录，识别待处理视频
- `video_tagging_assistant/compressor.py`
  - 生成送模压缩视频
- `video_tagging_assistant/context_builder.py`
  - 组装目录、文件名、模板信息，形成提示上下文
- `video_tagging_assistant/providers/*`
  - 屏蔽不同模型提供方的调用差异
- `video_tagging_assistant/review_exporter.py`
  - 输出 review 文本、HTML 报告和中间结果
- `video_tagging_assistant/orchestrator.py`
  - 负责整体批处理编排、并发与结果汇总

数据流顺序是：

`输入视频目录 -> scanner -> compressor -> context_builder -> provider -> review_exporter`

## Case Ingest 流程架构

Case Ingest 主流程由 `video_tagging_assistant/case_ingest_orchestrator.py` 串联，核心模块如下：

- `video_tagging_assistant/bat_parser.py`
  - 解析 `pull.bat` 与 `move.bat`
  - 提取 `case_A_xxxx`、pull 任务和 copy 任务
- `video_tagging_assistant/case_ingest_models.py`
  - 定义 `PullTask`、`CopyTask`、`CaseTask`、`UploadResult`
- `video_tagging_assistant/pull_worker.py`
  - 执行 ADB pull、文件数校验、临时目录合并
- `video_tagging_assistant/copy_worker.py`
  - 执行 DJI 文件补拷
- `video_tagging_assistant/upload_worker.py`
  - 执行整 case 目录上传与跳过逻辑
- `video_tagging_assistant/case_ingest_orchestrator.py`
  - 负责编排 pull / copy / upload

数据流顺序是：

`pull.bat + move.bat -> bat_parser -> CaseTask -> pull_worker -> copy_worker -> upload_worker`

## 关键文件职责

### 入口与配置

- `video_tagging_assistant/cli.py`
  - 项目统一入口，负责在视频打标与 Case Ingest 之间分流
- `video_tagging_assistant/config.py`
  - 加载视频打标配置与 Case Ingest 配置

### 视频打标主链路

- `video_tagging_assistant/scanner.py`
- `video_tagging_assistant/compressor.py`
- `video_tagging_assistant/context_builder.py`
- `video_tagging_assistant/review_exporter.py`
- `video_tagging_assistant/orchestrator.py`

### Case Ingest 主链路

- `video_tagging_assistant/bat_parser.py`
- `video_tagging_assistant/case_ingest_models.py`
- `video_tagging_assistant/pull_worker.py`
- `video_tagging_assistant/copy_worker.py`
- `video_tagging_assistant/upload_worker.py`
- `video_tagging_assistant/case_ingest_orchestrator.py`

## 配置与运行时关系

### 视频打标配置

视频打标主要通过 `video_tagging_assistant/default_config.json` 决定：

- 输入目录
- 输出目录
- review 输出路径
- provider 选择
- 并发参数
- prompt 模板

### Case Ingest 配置

Case Ingest 当前推荐通过 `configs/case_ingest.json` 运行，主要包括：

- `pull_bat`
- `move_bat`
- `server_root`
- `date`
- `skip_upload`

相对路径默认相对配置文件自身解析。

### bat 与最终目录关系

- `pull.bat` 提供 RK raw pull 来源路径与本地最终归档路径
- `move.bat` 提供 DJI 文件复制来源路径与目标路径
- `server_root` 与 `date` 共同决定服务器上传目标目录

## 当前实现边界与限制

### 视频打标流程

- 当前主目标是生成本地审核结果，不是直接写回 Excel
- provider 调用能力已抽象，但仍依赖当前支持的接口实现

### Case Ingest 流程

- 当前上传策略是：服务器同名 case 已存在时直接跳过
- 当前不会自动修复服务器端半成品 case
- 断点续传主要针对 RK raw pull 阶段
- bat 仍然是 Case Ingest 数据来源的一部分，不是完全脱离 bat 的新体系

## 相关文档

- 使用入口：`README.md`
- Case Ingest 详细用法：`docs/case-ingest-usage.md`
