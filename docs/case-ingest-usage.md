# Case Ingest 使用说明

## 1. 当前实现了什么

本次已经把原先分散的以下流程整合为一个统一入口：

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

入口已经接到：

- `video_tagging_assistant/cli.py`

对应子命令为：

- `case-ingest`

---

## 2. 命令行用法

```bash
python -m video_tagging_assistant.cli case-ingest \
  --pull-bat 20260422_pull.bat \
  --move-bat 20260422_move.bat \
  --date 20260427 \
  --server-root "\\10.10.10.164\rk3668_capture\OV50H40_Action5Pro_DCG HDR"
```

如果你只想做本地流程、不上传服务器，可以加：

```bash
--skip-upload
```

完整示例：

```bash
python -m video_tagging_assistant.cli case-ingest \
  --pull-bat 20260422_pull.bat \
  --move-bat 20260422_move.bat \
  --date 20260427 \
  --server-root "\\10.10.10.164\rk3668_capture\OV50H40_Action5Pro_DCG HDR" \
  --skip-upload
```

---

## 3. 参数说明

### `--pull-bat`
当天 RK raw 拉取任务文件。

文件内容需要包含类似：

```bat
adb pull /mnt/nvme/CapturedData/117 .\case_A_0078_RK_raw_117
move "E:\DV\case_A_0078_RK_raw_117" "E:\DV\OV50H40_Action5Pro_DCG HDR\20260422\case_A_0078\case_A_0078_RK_raw_117"
```

### `--move-bat`
当天 DJI 文件补拷任务文件。

文件内容需要包含类似：

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

## 4. 当前处理流程

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

## 5. 断点续传说明

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

## 6. 上传策略说明

当前上传策略已经锁定为：

- 上传内容：**整个 case 目录**
- 上传时机：该 case 本地流程完成后
- 如果服务器上同名 case 已存在：**直接跳过**
- 不覆盖
- 不删后重传
- 不做增量补传

这意味着如果服务器上已经存在半成品 case，当前脚本不会自动修复，需要人工先处理服务器目录后再重跑。

---

## 7. 当前已验证情况

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

## 8. 当前已知限制

当前版本已经可用，但仍有几点属于后续增强项：

1. 还没有单独暴露一个明确的 “case 完整性校验函数”
   - 目前完整性是通过 pull 成功、copy 成功来隐式保证的

2. CLI 还没有实现以下扩展参数：
   - `--case-filter`
   - `--work-root`

3. 上传线程模型目前是单线程
   - 这已经满足当前“pull 与 upload 并行”的需求
   - 但如果后续带宽允许，可以再扩成多上传线程

4. 还没有把这条新流程接入 README 主文档
   - 当前说明先单独保存在本文件中

---

## 9. 相关代码位置

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
