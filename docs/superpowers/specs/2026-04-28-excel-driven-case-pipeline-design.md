# Excel 驱动的 Case 自动化流水线设计

- 日期：2026-04-28
- 主题：保留 Excel 作为人工对齐与正式台账，新增 PyQt 可视化主控台，将批量打标、审核驱动的 pull/copy/upload、状态回写与日志统一到一条自动化流水线
- 状态：已确认设计，待用户审阅书面 spec

## 1. 背景

当前项目已经具备两段互相关联但尚未真正串联的能力：

1. **Excel 建档流程**
   - `PC_A_采集记录表v2.1.xlsm` 负责导入 RK raw 与 DJI 视频列表、人工对齐、填写备注与标签信息、按递增顺序维护 `创建记录` sheet。
   - 宏会生成 `YYYYMMDD_pull.bat` 与 `YYYYMMDD_move.bat`，并创建 case 目录及说明 txt。

2. **Python 执行流程**
   - 当前仓库已有 `case-ingest` 能力，可执行 pull / copy / upload，并支持断点续传与流水线式的 pull / upload 编排。
   - 当前仓库也已有视频打标能力，可批量压缩视频、调用模型生成标签和画面描述。

现状的问题不是单点功能缺失，而是整条链路仍分散在 Excel、bat、目录与 Python 命令之间：

- Excel 是人工对齐和正式记录入口，但不是自动化主控台。
- bat 是旧流程的中间产物，但不适合承载完整状态机。
- 打标、审核、pull、upload 之间没有统一的可视化调度与状态回写。
- 审核通过一个 case 后，不能立即自动推进该 case 的 pull / upload。
- 重跑后半段时，缺少“复用旧打标结果”的正式入口。

用户的明确目标是：

- **RK 与 DJI 对齐必须人工完成**。
- 除此之外，其他步骤都应尽量自动化。
- 保留 Excel 作为正式记录台账，并继续按历史规则递增写入 `创建记录`。
- Python 侧需要可视化界面，支持人工审核打标结果、实时查看 pull / upload 进度与日志。
- 运行方式应是：**先对一批 case 批量压缩并批量打标，再在审核通过单个 case 后立刻对该 case 启动 pull / copy / upload，而不是等全部审核完再统一执行。**

## 2. 目标与非目标

### 2.1 目标

1. 保留 Excel `创建记录` 作为唯一正式记录台账。
2. 保留人工完成 RK / DJI 对齐，不试图自动推断对齐关系。
3. 新增一个 PyQt 桌面主控台，作为整条自动化流程的统一操作入口。
4. 支持从 Excel 读取新增 case，并将运行状态持续回写 Excel。
5. 支持两种打标模式：
   - 重新打标
   - 跳过打标并导入旧打标结果
6. 支持对一批 case 先批量压缩与批量打标。
7. 支持对单个 case 审核通过后立即启动该 case 的 pull / copy / upload。
8. 支持实时显示：
   - 打标进度
   - pull 进度
   - upload 进度
   - 当前日志与错误信息
9. 最大化复用当前仓库中已有的：
   - 视频打标逻辑
   - case-ingest 的 pull / copy / upload 逻辑
10. 为失败重试、断点续跑和重复运行提供正式状态机制与日志机制。

### 2.2 非目标

1. 不替换 Excel 为新的对齐工具。
2. 不自动完成 RK / DJI 对齐。
3. 不在第一期中重写 Excel 宏的全部功能。
4. 不要求完全移除 bat 文件的存在；但 bat 不再作为新系统的主驱动。
5. 不在第一期中支持复杂的多人协作锁、权限体系或远程共享调度。
6. 不在第一期中重构无关的视频打标或 case-ingest 核心算法。

## 3. 推荐方案

最终采用：

**方案 A：Excel 继续做人机对齐与正式记录，Python 通过 PyQt 主控台接管其余自动化流程。**

推荐原因：

- 与当前工作习惯最贴近，迁移风险最低。
- 避免为“人工必须参与”的对齐环节强行重写前台系统。
- 能在保留 Excel 的前提下，用 Python 串起批量打标、审核、pull、copy、upload、日志与状态回写。
- 能复用当前仓库已有执行链路，而不是从零重做整个流程。

## 4. 业务边界与总体流程

### 4.1 人工段

人工只保留两类动作：

1. **RK / DJI 对齐**
   - 导入 DJI 视频列表
   - 导入 RK raw 列表
   - 在 Excel 中人工确认配对关系
   - 按既有递增规则写入 `创建记录`

2. **打标结果审核**
   - Python 批量生成标签候选结果后，由操作员在 PyQt 中逐 case 审核
   - 审核通过一个 case，即可立刻推进后续执行链

### 4.2 自动段

一旦 `创建记录` 中存在新增且可运行的 case，Python 自动接管：

1. 从 Excel 读取新增 case
2. 构建内部 manifest
3. 批量压缩视频
4. 批量执行打标或导入旧打标结果
5. 将结果放入待审核队列
6. 某个 case 审核通过后立即执行：
   - pull RK raw
   - copy / move DJI 文件
   - upload 到服务器
7. 持续回写 Excel 状态
8. 持续输出 GUI 实时日志、全局日志、case 日志

## 5. Excel 作为正式台账的设计

### 5.1 `创建记录` 的定位

`创建记录` 继续承担两种职责：

1. 正式 case 记录表
2. case 编号递增顺序的唯一来源

Python 不重新发明 case 编号规则，而是以 Excel 为准：

- 读取当前最大合法 `case_A_xxxx`
- 新增记录时继续递增
- 后续所有自动化围绕该 `case_id` 运行

### 5.2 运行态列设计

为了支持自动化状态推进，应在 `创建记录` 右侧追加运行态列，而不是复用旧含义列。

建议新增：

- `pipeline_status`
- `tag_status`
- `review_status`
- `pull_status`
- `copy_status`
- `upload_status`
- `last_error`
- `run_id`
- `updated_at`

这些列的作用是：

- 记录每个 case 当前所处阶段
- 支持失败后重试
- 支持中断后恢复
- 让 Excel 始终反映真实执行进度

### 5.3 新增记录识别规则

Python 每次扫描时，不依赖目录猜测，也不以 bat 作为主输入，而是直接从 `创建记录` 判断哪些 case 进入自动化。

一条记录满足以下条件时可进入流程：

1. `文件夹名` 存在，且符合 `case_[A-Z]_\d{4}`
2. RK / DJI 对齐字段已完整
3. 备注与必要标签字段达到最小要求
4. `pipeline_status` 为空，或处于允许重试的状态

### 5.4 递增写回规则

#### 创建新记录

人工对齐完成后，新记录追加到 `创建记录` 的末尾：

- 读取最后一个合法 `case_A_xxxx`
- 数字部分加 1
- 生成新 `case_id`
- 写入新行

#### 自动回写状态

自动化执行过程中，只更新该行的运行态列，不改变 case 顺序，不回填其他行。

## 6. PyQt 可视化主控台设计

### 6.1 采用 PyQt 的原因

推荐前端形态为 **PyQt 桌面端**，原因如下：

- 当前工作流运行在 Windows 本地环境
- 需要和 Excel、本地文件系统、共享目录、adb、播放器等本地能力深度耦合
- 需要持续显示 pull / upload 进度与实时日志
- 需要人工审核打标结果，桌面端交互与本地集成成本最低

### 6.2 主页面结构

建议使用 `QMainWindow + QTabWidget`，划分为四个主页面：

1. **今日队列**
   - 读取 Excel 新增 case
   - 启动 / 暂停 / 恢复流程
   - 查看每个 case 当前阶段与总体状态

2. **打标审核**
   - 视频预览
   - 展示模型生成标签、描述与结构化结果
   - 人工修改并审核通过 / 驳回 / 稍后处理

3. **执行监控**
   - 实时显示 pull / copy / upload 进度
   - 显示当前文件、完成数、跳过数、速度与日志

4. **失败重试 / 历史记录**
   - 查看失败项
   - 从当前步骤或指定步骤重试
   - 查看完成记录与历史运行日志

### 6.3 启动区控件

首页建议包含以下控件：

- Excel 文件路径
- 扫描新增记录
- 打标模式：
  - `重新打标`
  - `复用旧打标结果`
- 打标并发数配置
- 执行并发数配置
- 启动 / 暂停 / 恢复 / 仅重试失败项

## 7. 流水线与并发策略

本系统不是“所有 case 完成打标审核后再统一执行”，而是分为两个阶段。

### 7.1 阶段 A：批量打标准备与执行

对一批待处理 case 先统一执行：

1. 从 Excel 读取新增 case
2. 构建内部 manifest
3. 批量压缩视频
4. 批量执行送模 / 打标
5. 为每个 case 产出标签候选结果
6. 状态推进到 `awaiting_review`

这一步面向一批 case 并发处理，目标是尽快产出待审核结果。

### 7.2 阶段 B：审核驱动的逐 case 执行流水线

当某个 case 审核通过后，系统立刻对该 case 启动执行链：

1. pull RK raw
2. copy / move DJI 文件
3. upload 到服务器

同时操作员可继续审核下一个 case。这样形成：

- **case 内部串行**：pull -> copy -> upload
- **case 之间并发重叠**：一个 case 上传时，下一个 case 可以 pull，再下一个 case 可以等待审核

这正是目标工作方式：

- 先批量完成一批打标
- 再在人工审核与后端执行之间形成流水线
- 审核通过一个就立即执行一个，不等待整批审核结束

## 8. 状态机设计

### 8.1 打标阶段状态

- `queued`
- `tagging_preparing`
- `tagging_running`
- `tagging_finished`
- `tagging_skipped_using_cached`
- `awaiting_review`

### 8.2 审核阶段状态

- `reviewing`
- `review_passed`
- `review_rejected`

### 8.3 执行阶段状态

- `pull_queued`
- `pulling`
- `pull_done`
- `copying`
- `copy_done`
- `upload_queued`
- `uploading`
- `completed`
- `failed`

Excel 回写时可根据需要映射成更简化的文本，但内部状态机应保持足够细，以便 GUI、日志和重试逻辑准确工作。

## 9. 打标与旧结果复用设计

### 9.1 打标模式

启动流程前，操作员可以选择：

1. **重新打标**
   - 重新压缩
   - 重新送模
   - 重新产出标签结果

2. **复用旧打标结果**
   - 不再压缩
   - 不再送模
   - 从历史缓存中导入旧标签结果
   - 直接进入 `awaiting_review`

### 9.2 旧结果可用性校验

当选择“复用旧打标结果”时，系统不能无条件信任旧数据。至少应校验：

- `case_id` 是否存在历史标签结果
- 关键源文件名是否匹配
- 关键输入摘要是否匹配
- 缓存文件是否完整

若任一校验失败，应明确提示该 case 需要重新打标。

### 9.3 标签缓存目录

建议按 case 保存缓存，例如：

- `output/tagging_cache/<case_id>/manifest.json`
- `output/tagging_cache/<case_id>/tagging_result.json`
- `output/tagging_cache/<case_id>/review_result.json`

这样可支持：

- 重复运行时复用旧结果
- 失败后从打标与审核间状态恢复
- 崩溃后恢复上下文

## 10. 组件设计

### 10.1 Excel 接入层

职责：

- 打开 Excel 工作簿
- 读取 `创建记录`
- 读取配置页中的路径和默认值
- 追加新记录
- 找下一条 case_id
- 回写状态列

推荐提供接口：

- `load_pending_cases()`
- `append_case_record(...)`
- `update_case_status(case_id, ...)`
- `get_next_case_id()`
- `load_workbook_config()`

### 10.2 Manifest 转换层

职责：

- 将 Excel 的一行记录转换成统一的内部 `CaseManifest`
- 隔离后续逻辑对 Excel 列名和 COM 的直接依赖

### 10.3 Pipeline 编排层

职责：

- 管理批量打标阶段
- 管理待审核队列
- 管理审核通过后进入执行队列的 case
- 推进状态机
- 将事件分发给 GUI、日志和 Excel 回写

### 10.4 现有能力复用层

#### case-ingest 复用

保留并复用已有：

- `video_tagging_assistant/pull_worker.py`
- `video_tagging_assistant/copy_worker.py`
- `video_tagging_assistant/upload_worker.py`
- `video_tagging_assistant/case_ingest_orchestrator.py` 的执行思想

但新的主驱动不再依赖“先生成 bat 再解析 bat”，而是直接由 `CaseManifest` 生成：

- `PullTask`
- `CopyTask`
- `CaseTask`

#### 视频打标复用

复用：

- provider 调用能力
- 压缩逻辑
- 上下文构建逻辑
- review 输出逻辑

新增一个按单 case 运转的 tagging service，以便纳入 GUI 审核与缓存机制。

### 10.5 GUI 层

职责：

- 展示队列
- 展示审核页面
- 展示 pull / upload 进度
- 提供开始、暂停、重试、审核通过/驳回等操作

### 10.6 事件与日志层

职责：

- 统一记录状态变化与运行事件
- 为 GUI 提供实时事件
- 为本地日志提供结构化输出
- 为 Excel 回写提供触发依据

## 11. 数据模型建议

### 11.1 `ExcelCaseRecord`

表示从 Excel 读取的原始记录。

字段包括：

- `row_index`
- `case_id`
- `created_date`
- `remark`
- `label_fields`
- `rk_raw_id`
- `dji_normal_name`
- `dji_night_name`
- `raw_target_path`
- `vs_normal_target_path`
- `vs_night_target_path`
- `pipeline_status_columns`

### 11.2 `CaseManifest`

程序内部统一对象，字段建议包括：

- `case_id`
- `excel_row`
- `date`
- `mode`
- `rk_raw_id`
- `rk_device_path`
- `local_case_root`
- `local_rk_dir`
- `dji_normal_source`
- `dji_night_source`
- `dji_normal_target`
- `dji_night_target`
- `server_case_dir`
- `remark`
- `tag_fields`
- `device_info`

### 11.3 `TaggingResult`

用于缓存与审核输入，字段包括：

- `case_id`
- `source_video_paths`
- `generated_labels`
- `generated_description`
- `generated_structured_output`
- `review_status`
- `reviewed_labels`
- `reviewed_description`
- `generated_at`
- `model_info`

### 11.4 `PipelineEvent`

统一事件对象，字段包括：

- `event_type`
- `case_id`
- `stage`
- `message`
- `progress_current`
- `progress_total`
- `extra`
- `timestamp`

## 12. 线程与队列模型

### 12.1 GUI 主线程

职责仅限：

- 渲染界面
- 响应按钮点击
- 接收后台事件
- 更新表格、进度条与日志窗口

GUI 主线程不直接执行 Excel 重 IO、adb、上传、压缩或模型调用。

### 12.2 Excel 服务线程

Excel COM 访问集中在单独线程中串行执行，避免多个线程直接共享 COM 对象。

设计原则：

- 启动时打开 workbook，并在会话内复用
- 所有读写请求通过该线程的请求队列进入
- 写入失败时可重试并明确报告“Excel 被占用/不可写”

### 12.3 批量打标 worker 池

职责：

- 压缩视频
- 准备送模输入
- 执行打标
- 读取或写入标签缓存

特点：

- 并发数可配置
- 面向整批待处理 case
- 打标完成后将结果推入待审核队列

### 12.4 执行流水线 worker 池

职责：

- 接收审核通过的 case
- 串行执行该 case 的 pull -> copy -> upload
- 持续上报进度事件

多个 case 可并发运行，形成 case 间流水线。

## 13. 进度展示策略

### 13.1 打标进度

应显示：

- 压缩开始/完成
- 上传/送模开始/完成
- 模型处理中
- 标签结果已缓存

### 13.2 pull 进度

优先解析结构化进度；若 `adb` 输出不稳定，则退化为：

- 本地已完成文件数
- 设备端总文件数

### 13.3 upload 进度

应显示：

- 已上传文件数
- 总文件数
- 当前文件名
- 已跳过数
- 失败数

这些事件统一通过 `PipelineEvent` 上报到 GUI 和日志层。

## 14. 日志与运行态持久化

### 14.1 全局运行日志

每次运行生成：

- `logs/pipeline/YYYYMMDD_HHMMSS_run.log`

记录：

- 启动时间
- 打标模式
- 扫描到的 case 数
- 并发数配置
- 全局异常

### 14.2 case 独立日志

每个 case 生成独立日志，例如：

- `logs/cases/case_A_0001.log`

记录：

- 打标开始/结束
- 审核结果
- pull 输出摘要
- copy 结果
- upload 结果
- 错误堆栈

### 14.3 GUI 实时日志

GUI 中应实时展示最近事件，而不是要求操作员手动打开日志文件。

### 14.4 本地运行态快照

建议额外保存：

- `output/pipeline_state/current_run.json`

用于记录：

- `run_id`
- 本次模式
- 已入队 case
- 每个 case 当前状态
- 队列快照
- 最近错误

这样即便 GUI 崩溃，也有利于现场恢复与问题排查。

## 15. Excel 回写时机

建议在以下时机回写：

- 入队时：`pipeline_status=queued`
- 打标完成时：`tag_status=generated`
- 使用旧打标结果时：`tag_status=cached`
- 审核通过时：`review_status=passed`
- 审核驳回时：`review_status=rejected`
- pull 完成时：`pull_status=done`
- copy 完成时：`copy_status=done`
- upload 完成时：`upload_status=done`
- 整体完成时：`pipeline_status=completed`
- 任一步失败时：`pipeline_status=failed`，并写 `last_error`

## 16. MVP 实施范围

第一期应优先落地最关键主链路，而非一次性做满。

### 16.1 第一阶段 MVP 包含

1. 读取 Excel `创建记录`
2. 识别新增 case
3. 批量打标 / 或导入旧打标结果
4. 打标审核 GUI
5. 审核通过即触发 pull / copy / upload
6. GUI 实时日志
7. Excel 状态回写
8. 失败后手动重试

### 16.2 暂不包含

1. 任意中间步骤的复杂自动恢复
2. 多人协作锁
3. 审核权限系统
4. 复杂的批次对账与跨运行合并工具

## 17. 验证策略

### 17.1 Excel 接入验证

验证：

- 能稳定读取 `创建记录`
- 能找到最大合法 `case_id`
- 能稳定回写状态列
- Excel 被占用时能给出清晰错误

### 17.2 打标模式验证

验证：

- 重新打标模式可正常执行完整打标流程
- 复用旧打标结果模式可正确命中缓存
- 缓存不完整时能正确拒绝复用

### 17.3 审核驱动执行验证

验证：

- 批量打标完成后，case 进入待审核队列
- 某 case 审核通过后立刻进入 pull / copy / upload
- 不需要等待其他 case 全部审核完成

### 17.4 GUI 监控验证

验证：

- pull / upload 进度能实时刷新
- 日志面板能显示当前关键事件
- 失败项可从 GUI 发起重试

### 17.5 回归验证

验证：

- 现有 case-ingest 核心 pull / copy / upload 逻辑未被破坏
- 现有视频打标核心能力在新封装下结果一致

## 18. 结论

本次设计应严格聚焦在：

**保留 Excel 作为人工对齐与正式台账，引入 PyQt 主控台，将批量打标、逐 case 审核、审核驱动的 pull/copy/upload、状态回写与日志统一为一条可视化自动化流水线。**

第一期不重写人工对齐流程，不替换 Excel，不在 GUI 中重新发明旧建档系统；而是通过“Excel 主账本 + manifest + 批量打标 + 审核驱动执行队列 + 实时日志与状态回写”的方式，以最低风险将现有分散流程串联成一套可日常使用的正式自动化方案。
