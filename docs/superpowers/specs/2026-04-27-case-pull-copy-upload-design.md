# Case 级 pull / check / copy / upload 一体化脚本设计

- 日期：2026-04-27
- 主题：将 `pull.py`、`check.py`、`20260422_pull.bat`、`20260422_move.bat` 的现有流程整合为一个统一脚本，按 case 顺序执行 pull、校验、补齐本地文件，并在每个 case 完成后立即上传服务器
- 状态：待用户审阅

## 1. 背景

当前工作流分散在多份脚本和 bat 文件中：

- `20260422_pull.bat` 维护 RK raw 目录的设备路径与本地 case 目录映射
- `pull.py` 负责增强版 `adb pull`，支持重试、临时目录和合并逻辑
- `check.py` 负责读取 bat 映射后，对比设备端与本地归档目录的文件数
- `20260422_move.bat` 负责把 DJI normal/night 视频复制到对应的 case 目录

当前流程虽然已经可用，但存在以下问题：

1. 需要分阶段执行多个入口，人工串联成本高。
2. `pull`、`check`、`copy`、`upload` 没有被统一编排，失败恢复依赖人工判断。
3. 最耗时的两个步骤是：
   - 从设备 `adb pull`
   - 上传服务器共享目录
4. 如果仍然串行完成“全部 pull 完再统一上传”，会拉长总耗时。

用户希望把这些步骤整合成一个统一脚本，并满足以下约束：

- `pull` 需要具备断点续传能力
- `move` 的 case 对应关系继续从现有 move bat 中读取，不改为自动匹配
- 每个 case 在本地检查通过后，立即上传到服务器
- 服务器目标根目录中的日期目录每天变化，应作为参数传入
- 如果服务器上该 case 已存在，则直接跳过这个 case，不做覆盖、不做补传

## 2. 目标

1. 提供一个单入口脚本，统一完成 pull、check、copy、upload。
2. 保留 `pull.bat` 与 `move.bat` 作为任务来源，不重建映射体系。
3. 以 case 为最小执行单元。
4. `pull` 支持可重跑、可恢复的断点续传。
5. 每个 case 本地完成后立即上传，和下一 case 的 pull 并行重叠。
6. 服务器端若已存在目标 case，则直接跳过。
7. 输出清晰的逐 case 结果汇总，便于人工复核失败项。

## 3. 非目标

本次设计不包含以下内容：

1. 不改为 Excel 或 JSON 作为主任务来源。
2. 不自动生成新的 bat 文件。
3. 不实现多设备并行 pull。
4. 不做哈希级内容校验。
5. 不做服务器端已有 case 的增量补传。
6. 不自动删除本地源文件或设备端源文件。
7. 不接入视频打标、模型分析或 Excel 审核流程。

## 4. 推荐方案

采用“**保留 bat 作为输入 + Python 统一编排 + case 级流水线上传**”方案。

### 4.1 为什么保留 bat 作为输入

- `pull.bat` 已经承载了设备目录与 case 的真实映射
- `move.bat` 已经承载了 DJI 文件与 case 的真实对应关系
- 这些映射已经经过实际使用验证，继续复用风险最低
- 相比重做配置体系，这种方式改动更小、落地更快

### 4.2 为什么按 case 流水线处理

用户已经明确指出耗时最大的是：

1. `adb pull`
2. 上传服务器

因此最佳流程不是“全部本地完成后再上传”，而是：

- 主线程持续处理下一个 case 的 pull
- 后台上传线程负责上传已经完成的 case

这样可以让 pull 和 upload 尽量并行，缩短总体耗时。

## 5. 核心流程

### 5.1 输入参数

统一脚本建议支持以下参数：

- `--pull-bat`
  - 当天 RK raw 拉取映射文件
- `--move-bat`
  - 当天 DJI copy 映射文件
- `--date`
  - 服务器目标日期目录，例如 `20260427`
- `--server-root`
  - 服务器根目录，例如 `\\10.10.10.164\rk3668_capture\OV50H40_Action5Pro_DCG HDR`
- `--work-root`（可选）
  - 本地 case 根目录，用于解析和规范路径
- `--skip-upload`（可选）
  - 仅做本地 pull/check/copy，不上传
- `--case-filter`（可选）
  - 仅处理指定 case，便于重跑或调试

### 5.2 启动阶段

脚本启动后：

1. 解析 `pull.bat`
2. 解析 `move.bat`
3. 从目标路径中提取 case 编号
4. 按 case 聚合出统一任务对象
5. 计算每个 case 的服务器目标路径：

```text
<server_root>/<date>/<case_id>
```

例如：

```text
\\10.10.10.164\rk3668_capture\OV50H40_Action5Pro_DCG HDR\20260427\case_A_0078
```

### 5.3 单 case 处理顺序

主线程按 case 顺序处理，每个 case 的本地流程如下：

1. `adb wait-for-device`
2. 执行 RK raw pull
3. 校验设备端文件数与本地 RK raw 文件数
4. 执行该 case 对应的 DJI copy
5. 检查 case 完整性
6. 若通过，则把整个 case 上传任务放入后台上传队列
7. 主线程立即继续下一个 case

后台上传线程独立消费上传队列：

1. 检查服务器目标 case 是否已存在
2. 已存在则直接跳过该 case
3. 不存在则上传整个 case 目录
4. 记录上传成功或失败结果

## 6. 数据来源与聚合规则

### 6.1 pull bat 解析

从 `pull.bat` 中提取每组配对信息：

- `adb pull <device_path> .\<local_name>`
- `move "<move_src>" "<move_dst>"`

抽取字段：

- `device_path`
- `local_name`
- `move_src`
- `move_dst`
- `case_id`（从路径或目录名提取）
- `rk_raw_dir_name`

### 6.2 move bat 解析

从 `move.bat` 中提取每条 `copy`：

- `copy "<src>" "<dst>"`

抽取字段：

- `src`
- `dst`
- `case_id`
- 文件类型：`normal` 或 `night`

### 6.3 case 聚合

以 `case_A_xxxx` 为 key 聚合成统一任务对象，建议至少包含：

- `case_id`
- `device_path`
- `rk_local_tmp_dir`
- `rk_local_final_dir`
- `case_root_dir`
- `dji_normal_copy`（可选）
- `dji_night_copy`（可选）
- `server_case_dir`

## 7. pull 断点续传设计

### 7.1 本地目录策略

对于每个 RK raw 任务：

- 正式目录：`case_A_xxxx_RK_raw_yyy`
- 临时目录：`case_A_xxxx_RK_raw_yyy_tmp`

### 7.2 断点续传规则

1. 启动该 case 时先统计设备端文件总数。
2. 如果正式目录已存在，统计正式目录文件数。
3. 若正式目录文件数与设备端文件数一致，则判定 pull 已完成，直接跳过 pull。
4. 若未完成，则删除残留 `_tmp` 目录。
5. 重新执行 `adb pull` 到 `_tmp`。
6. pull 成功后，把 `_tmp` 中正式目录没有的文件 merge 到正式目录。
7. merge 完成后删除 `_tmp`。

### 7.3 设计原因

该方案不依赖 adb 协议本身支持真正的断点续传，而是通过“正式目录保留 + 临时目录重拉 + 文件级合并”实现可恢复能力。

优点：

- 中途中断后可重跑
- 已完成文件不重复移动到正式目录
- 与当前 `pull.py` 的成熟思路一致，迁移成本低

## 8. 校验设计

### 8.1 RK raw 文件数校验

pull 结束后立即校验：

- 设备端目录文件总数
- 本地 RK raw 正式目录文件总数

只有两者一致，才认为该 case 的 RK raw 有效。

### 8.2 case 完整性校验

在上传前，脚本还需要检查 case 目录是否具备当前应有内容：

- RK raw 正式目录存在
- `move.bat` 中声明的 DJI normal 文件已复制到目标位置
- `move.bat` 中声明的 DJI night 文件已复制到目标位置

如果 `move.bat` 中某一类文件不存在映射，则不强行要求该类文件存在；如果映射存在但复制失败，则该 case 不允许进入上传队列。

## 9. DJI copy 设计

### 9.1 数据来源

DJI 对应关系继续从 `move.bat` 读取，不改为自动匹配目录。

### 9.2 执行方式

不直接执行 bat，而是由 Python 自己完成 copy：

1. 检查源文件是否存在
2. 创建目标目录
3. 执行复制
4. 校验目标文件是否存在

### 9.3 设计原因

这样可以把错误处理、日志、进度展示和状态记录统一到一套 Python 编排逻辑中。

## 10. 上传设计

### 10.1 上传触发点

一个 case 只有在以下步骤全部完成后才进入上传队列：

1. RK raw pull 完成
2. RK raw 文件数校验通过
3. DJI copy 完成
4. case 完整性检查通过

### 10.2 上传内容

上传内容是**整个 case 目录**，例如：

- 本地：`E:\DV\采集建档V2.1\...\20260427\case_A_0078`
- 服务器：`\\10.10.10.164\rk3668_capture\OV50H40_Action5Pro_DCG HDR\20260427\case_A_0078`

### 10.3 服务器端已存在策略

这是本次设计中已经锁定的规则：

- 如果服务器目标 `case_A_xxxx` 已存在
- 则该 case **直接跳过上传**
- 不覆盖
- 不删后重传
- 不增量补传

### 10.4 设计影响

这个策略意味着：

- 脚本要把“服务器已存在”视为一种明确结果，而不是错误
- 适合避免误覆盖服务器已有数据
- 但如果服务器已有的是半成品，也不会自动修复，需要人工决定是否先删掉再重跑

## 11. 并发模型

### 11.1 推荐并发方式

第一版采用：

- 1 个主线程：负责 case 本地处理
- 1 个后台上传线程：负责服务器上传

主线程执行：

- pull
- 文件数校验
- DJI copy
- case 完整性检查
- 投递上传任务

上传线程执行：

- 检查服务器目标是否存在
- 上传整个 case
- 更新上传结果

### 11.2 不做更激进并发的原因

- ADB 操作单线程更稳，避免设备连接混乱
- 上传与 pull 并行已经能覆盖主要性能收益
- 单上传线程足以形成流水线，复杂度低，便于排查问题

## 12. 状态模型

建议为每个 case 记录如下状态：

- `pending`
- `pulling`
- `pull_verified`
- `copying_dji`
- `ready_to_upload`
- `upload_queued`
- `uploading`
- `uploaded`
- `upload_skipped_exists`
- `failed`

其中：

- `pull_verified` 表示 RK raw 文件数校验通过
- `ready_to_upload` 表示本地 case 已完整
- `upload_skipped_exists` 表示服务器已有同名 case，按规则跳过

## 13. 错误处理与恢复策略

### 13.1 case 是最小失败单元

- 某个 case 失败，不影响后续 case 继续执行
- 每个 case 单独记录失败原因

### 13.2 可重跑原则

重复执行统一脚本时：

- 本地已完成且文件数一致的 RK raw 可跳过 pull
- 本地已复制完成的 DJI 文件可按策略跳过或覆盖式重拷
- 服务器端已存在的 case 直接跳过上传

### 13.3 常见失败场景

需要明确处理的失败包括：

1. `adb wait-for-device` 超时或设备未连接
2. `adb pull` 失败
3. 设备端文件数获取失败
4. 本地文件数不一致
5. DJI 源文件不存在
6. DJI copy 失败
7. 服务器路径不可访问
8. 上传中断或权限不足

## 14. 建议模块拆分

虽然对外是一个统一脚本入口，但内部建议保持模块边界清晰：

- `bat_parser`
  - 解析 pull bat
  - 解析 move bat
  - 提取 case_id 并聚合
- `pull_worker`
  - 设备等待
  - pull
  - 断点续传
  - merge
  - RK 文件数校验
- `copy_worker`
  - DJI copy
  - 目标校验
- `upload_worker`
  - 服务器目标路径计算
  - 已存在判断
  - case 目录上传
- `orchestrator`
  - 串联主流程
  - 投递上传任务
  - 汇总结果
- `cli`
  - 参数解析
  - 启动编排

## 15. 验收标准

满足以下条件即可认为第一版可用：

1. 能读取当天 `pull.bat` 与 `move.bat`。
2. 能正确按 case 聚合 RK raw 与 DJI copy 任务。
3. RK raw pull 支持断点续传，可在中断后重跑恢复。
4. 能对 RK raw 做设备端与本地文件数校验。
5. 能把 `move.bat` 中声明的 DJI 文件复制到对应 case 目录。
6. 每个 case 本地完成后可立即进入上传队列。
7. 上传与下一 case 的 pull 可以并行重叠。
8. 如果服务器上 case 已存在，则上传阶段直接跳过。
9. 最终输出逐 case 的 pull/check/copy/upload 结果汇总。

## 16. 第一版范围总结

第一版包含：

- bat 解析
- case 聚合
- RK raw 断点续传 pull
- RK raw 文件数校验
- DJI copy
- case 级上传
- pull 与 upload 流水线并行
- 结果汇总

第一版不包含：

- Excel 集成
- 自动生成 bat
- 多上传线程
- 哈希校验
- 服务器端增量补传
- 自动清理服务器已有 case
