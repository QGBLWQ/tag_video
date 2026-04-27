# 视频打标与 Case Ingest 工具说明

## 1. 项目作用

当前项目包含两条主要流程：

### 1.1 视频打标流程

该工具用于：

- 扫描本地视频
- 压缩视频代理文件
- 调用 Qwen / DashScope 分析视频内容
- 输出结构化标签与详细画面描述
- 生成本地 `review.txt` 供人工审核

### 1.2 Case Ingest 流程

该流程用于把原先分散的 case 采集归档步骤整合为统一入口：

- 读取 `pull.bat`
- 读取 `move.bat`
- 按 `case_A_xxxx` 聚合任务
- 执行 RK raw `adb pull`
- 支持可重跑的断点续传
- 校验设备端与本地 RK raw 文件数
- 按 `move.bat` 复制 DJI normal/night 文件
- 上传整个 case 目录到服务器日期目录
- 如果服务器上同名 case 已存在，则跳过上传
- 采用“主线程继续 pull、后台线程上传”的流水线方式

---

## 2. 环境要求

- Windows
- Python 3.8+
- `ffmpeg.exe`
- `adb.exe`
- 可访问 DashScope / 百炼接口的网络环境（视频打标流程需要）
- 可访问目标共享目录的网络环境（case-ingest 上传需要）

---

## 3. 安装依赖

在部署目录中执行：

```bash
pip install -r requirements.txt
```

---

## 4. 需要准备的内容

### 4.1 视频打标流程

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

### 4.2 Case Ingest 流程

需要准备：

- 当天 RK raw 拉取任务 bat，例如 `20260422_pull.bat`
- 当天 DJI 补拷任务 bat，例如 `20260422_move.bat`
- 可用的 ADB 设备连接
- 本地 case 目录映射已在 bat 中写好
- 服务器目标根目录，例如：

```text
\\10.10.10.164\rk3668_capture\OV50H40_Action5Pro_DCG HDR
```

---

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

---

## 6. 运行方式

### 6.1 视频打标流程

```bash
python -m video_tagging_assistant.cli --config default_config.json
```

或双击：

- `run_cli.bat`

### 6.2 Case Ingest 流程

```bash
python -m video_tagging_assistant.cli case-ingest \
  --pull-bat 20260422_pull.bat \
  --move-bat 20260422_move.bat \
  --date 20260427 \
  --server-root "\\10.10.10.164\rk3668_capture\OV50H40_Action5Pro_DCG HDR"
```

如果只想执行本地 pull / check / copy，不上传服务器：

```bash
python -m video_tagging_assistant.cli case-ingest \
  --pull-bat 20260422_pull.bat \
  --move-bat 20260422_move.bat \
  --date 20260427 \
  --server-root "\\10.10.10.164\rk3668_capture\OV50H40_Action5Pro_DCG HDR" \
  --skip-upload
```

---

## 7. Case Ingest 参数说明

### `--pull-bat`
当天 RK raw 拉取任务文件。

示例内容：

```bat
adb pull /mnt/nvme/CapturedData/117 .\case_A_0078_RK_raw_117
move "E:\DV\case_A_0078_RK_raw_117" "E:\DV\OV50H40_Action5Pro_DCG HDR\20260422\case_A_0078\case_A_0078_RK_raw_117"
```

### `--move-bat`
当天 DJI 文件补拷任务文件。

示例内容：

```bat
copy "E:\DV\Dji_mp4\Nomal\DJI_xxx.MP4" "E:\DV\OV50H40_Action5Pro_DCG HDR\20260422\case_A_0078\case_A_0078_DJI_xxx.MP4"
copy "E:\DV\Dji_mp4\Night\DJI_xxx.MP4" "E:\DV\OV50H40_Action5Pro_DCG HDR\20260422\case_A_0078\case_A_0078_night_DJI_xxx.MP4"
```

### `--date`
服务器目标日期目录，例如：

```text
20260427
```

### `--server-root`
服务器根目录，例如：

```text
\\10.10.10.164\rk3668_capture\OV50H40_Action5Pro_DCG HDR
```

最终每个 case 的上传目标会拼成：

```text
<server-root>\<date>\case_A_xxxx
```

### `--skip-upload`
只执行本地 pull / check / copy，不做上传。

---

## 8. Case Ingest 当前处理流程

对每个 case，当前流程如下：

1. 解析 `pull.bat` 和 `move.bat`
2. 提取 `case_A_xxxx`
3. 生成该 case 的统一任务对象
4. `adb wait-for-device`
5. 执行 RK raw pull
6. 校验设备端文件数和本地 RK raw 目录文件数
7. 复制该 case 对应的 DJI 文件
8. 把该 case 放入上传队列
9. 上传线程把整个 case 目录上传到服务器目标目录
10. 如果服务器目标目录已存在，则直接跳过上传

---

## 9. Case Ingest 断点续传说明

当前 RK raw pull 的断点续传逻辑是：

- 最终目录使用 `pull.bat` 中的 `move_dst`
- 临时目录使用同级的 `_tmp` 目录
- 如果最终目录文件数已经等于设备端文件数，则直接跳过 pull
- 如果未完成，则重新 pull 到 `_tmp`
- pull 完成后把 `_tmp` 中缺失文件 merge 到最终目录
- merge 完成后删除 `_tmp`

这意味着：

- 中途中断后可以重跑
- 已完成的文件不会重复归档
- 最终归档目录就是 case 目录下的 RK raw 目录

---

## 10. Case Ingest 上传策略说明

当前上传策略已经锁定为：

- 上传内容：**整个 case 目录**
- 上传时机：该 case 本地流程完成后
- 如果服务器上同名 case 已存在：**直接跳过**
- 不覆盖
- 不删后重传
- 不做增量补传

这意味着如果服务器上已经存在半成品 case，当前脚本不会自动修复，需要人工先处理服务器目录后再重跑。

---

## 11. 输出位置

### 视频打标流程
- Review 审核清单：`paths.review_file`
- 中间 JSON：`paths.intermediate_dir`
- 压缩后视频：`paths.compressed_dir`

### Case Ingest 流程
- 本地 RK raw 归档目录：由 `pull.bat` 中 `move_dst` 决定
- 本地 DJI 文件目标路径：由 `move.bat` 中目标路径决定
- 服务器上传目录：`<server-root>\<date>\case_A_xxxx`

---

## 12. 当前已验证情况

本次实现已经通过以下测试：

- case-ingest 聚焦测试：23 项通过
- 额外回归测试：10 项通过

已覆盖的测试范围包括：

- 配置默认值
- case 数据模型
- bat 解析与 case 聚合
- pull 合并逻辑
- pull 最终目录是否使用 `move_dst`
- DJI copy
- 上传跳过逻辑
- orchestrator 流水线行为
- CLI 子命令入口

---

## 13. 当前已知限制

### 视频打标流程
- 当前配置支持把 DashScope API Key 直接写在配置文件里，部署方便，但存在泄露风险
- 建议后续切换到环境变量方式

### Case Ingest 流程
1. 还没有单独暴露一个明确的 “case 完整性校验函数”
   - 目前完整性是通过 pull 成功、copy 成功来隐式保证的

2. CLI 还没有实现以下扩展参数：
   - `--case-filter`
   - `--work-root`

3. 上传线程模型目前是单线程
   - 这已经满足当前“pull 与 upload 并行”的需求
   - 但如果后续带宽允许，可以再扩成多上传线程

---

## 14. 迁移到其他电脑

### 视频打标流程
迁移时通常只需要：

- 复制整个部署目录
- 安装 Python 依赖
- 准备 `ffmpeg.exe`
- 修改 `default_config.json` 中的路径和 API 配置

一般不需要改核心代码。

### Case Ingest 流程
迁移时通常还需要：

- 准备 `adb.exe`
- 确保目标电脑能访问 Android 设备
- 确保目标电脑能访问服务器共享目录
- 使用当天有效的 `pull.bat` 和 `move.bat`

---

## 15. 相关代码位置

主要实现文件：

- `video_tagging_assistant/cli.py`
- `video_tagging_assistant/bat_parser.py`
- `video_tagging_assistant/case_ingest_models.py`
- `video_tagging_assistant/pull_worker.py`
- `video_tagging_assistant/copy_worker.py`
- `video_tagging_assistant/upload_worker.py`
- `video_tagging_assistant/case_ingest_orchestrator.py`

主要测试文件：

- `tests/test_config.py`
- `tests/test_case_ingest_models.py`
- `tests/test_bat_parser.py`
- `tests/test_pull_worker.py`
- `tests/test_copy_worker.py`
- `tests/test_upload_worker.py`
- `tests/test_case_ingest_orchestrator.py`
- `tests/test_pipeline.py`
