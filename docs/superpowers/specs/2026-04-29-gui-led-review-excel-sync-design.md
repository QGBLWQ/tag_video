# GUI 主导审核与 Excel 同步设计

- 日期：2026-04-29
- 主题：将现有 PyQt GUI 真正连接到 Excel 驱动的 case 流水线，采用 GUI 主导审核、Excel 兼容输入的同步方案
- 状态：待用户审阅

## 1. 背景

当前仓库已经具备以下基础能力：

1. `video_tagging_assistant/tagging_service.py`
   - 能对一批 `CaseManifest` 执行 fresh / cached 两种模式的批量打标。
   - 能输出 `TaggingReviewRow`，包含自动简介、自动标签、自动画面描述和来源信息。

2. `video_tagging_assistant/pipeline_controller.py`
   - 已经具备最小状态机和审核通过后的执行队列。
   - 已能执行 `pull -> copy -> upload` 的单 case 顺序链路。

3. `video_tagging_assistant/excel_workbook.py`
   - 已能给 `创建记录` 增加运行时列，并按 `pipeline_status` 读取 case。
   - 已有 review sheet 的 upsert / sync 能力，但尚未和新的 PyQt 流程打通。

4. `video_tagging_assistant/gui/`
   - 已有主窗口骨架、日志面板占位、审核面板占位。
   - 目前 GUI 只是静态壳子，还不能真正扫描 Excel、发起打标、展示审核列表、批准 case、或触发后台执行。

因此，现在缺的不是底层 worker，而是“把 GUI、Excel、批量打标、审核通过触发执行、状态回写”真正串成一条可操作的流程。

## 2. 目标

本轮设计只解决“GUI 连接到流水线”这一个子问题。

### 2.1 目标

1. GUI 成为主操作入口。
2. GUI 可以从 Excel 扫描出可运行 case，并显示到界面中。
3. GUI 可以选择“重新打标 / 复用旧打标结果”并启动批量打标。
4. 批量打标完成后，结果同时进入：
   - GUI 审核页
   - Excel 审核 sheet
5. 操作员在 GUI 中点击“审核通过”后，该 case 立即：
   - 更新 GUI 状态
   - 更新 Excel 状态
   - 进入 `PipelineController` 执行队列
   - 在后台开始 `pull -> copy -> upload`
6. GUI 支持“从 Excel 刷新审核结果”，将 Excel 中已填写的审核结论导回 GUI。
7. 从 Excel 导回的“审核通过”结果，也可以触发相同的执行队列推进。
8. GUI 持续显示执行日志和阶段变化。

### 2.2 非目标

1. 本轮不做 Excel 自动轮询。
2. 本轮不做多用户并发冲突解决。
3. 本轮不做完整视频预览播放器。
4. 本轮不做复杂失败恢复 UI。
5. 本轮不重写打标服务或 case-ingest worker 的核心算法。

## 3. 方案选择

采用：

**GUI 主导，Excel 作为兼容输入与持久化记录。**

### 3.1 GUI 的角色

GUI 是主要审核入口：

- 操作员优先在 GUI 审核自动结果。
- GUI 里的“通过 / 拒绝 / 修改后通过”是第一优先级动作。
- 一旦在 GUI 里通过，立即推进该 case 的执行队列。

### 3.2 Excel 的角色

Excel 继续承担两个职责：

1. **持久化记录**
   - 保存批量打标结果、人工修订结果、审核结论、运行状态。

2. **兼容输入源**
   - 如果操作员已经在 Excel 审核 sheet 中填写了“审核通过”或“修改后通过”，GUI 可以手动读取这些结果，并同步导入。

### 3.3 为什么不做双向实时同步

不采用自动轮询双向同步，原因是：

- 第一版最重要的是先把主流程跑通。
- 自动轮询会引入冲突、状态抖动和重复入队问题。
- 当前需求只要求“也可以从 Excel 读取已有审核结果”，并不要求毫秒级双向实时同步。

因此第一版使用：

- **GUI 主导即时回写**
- **Excel 手动刷新导入**

这是复杂度最低、最稳妥的方案。

## 4. 总体流程

### 4.1 扫描阶段

1. 操作员在 GUI 中选择 workbook 路径。
2. 点击“扫描新增记录”。
3. 程序执行：
   - `ensure_pipeline_columns(workbook_path, "创建记录")`
   - 从 `创建记录` 读取可运行 case
   - 将 Excel 行转换为 `CaseManifest`
   - 注册到 `PipelineController`
4. GUI 的“今日队列”页显示这些 case。

### 4.2 批量打标阶段

1. 操作员在 GUI 中选择：
   - `重新打标`
   - `复用旧打标结果`
2. 点击“启动流水线”。
3. 程序在后台线程中运行 `run_batch_tagging(...)`。
4. 每个 case 的打标事件通过 callback 回传 GUI。
5. 批量打标结束后：
   - `TaggingReviewRow[]` 写入 GUI 审核页
   - 同时 upsert 到 Excel 审核 sheet
   - controller 中对应 case 更新到 `AWAITING_REVIEW`

### 4.3 GUI 审核阶段

GUI 的“打标审核”页显示：

- case_id
- 自动简介
- 自动标签
- 自动画面描述
- 来源（fresh / cache）
- 人工修订简介输入框
- 人工修订标签输入框
- 审核备注输入框
- 按钮：通过、修改后通过、拒绝、从 Excel 刷新

当操作员点击“通过”或“修改后通过”时：

1. GUI 收集当前 case 的人工修订内容。
2. 将审核结果写回 Excel 审核 sheet。
3. 将 `创建记录` 的 `review_status` / `pipeline_status` 更新到通过状态。
4. 调用 `controller.approve_case(case_id)`。
5. 后台线程开始执行该 case 的 `pull -> copy -> upload`。

### 4.4 Excel 刷新导入阶段

当操作员点击“从 Excel 刷新审核结果”时：

1. 程序读取 Excel 审核 sheet。
2. 筛出：
   - `审核通过`
   - `修改后通过`
3. 对于这些 case：
   - 如果 GUI 中已有该 case，则更新显示内容。
   - 如果 controller 当前仍处于 `AWAITING_REVIEW`，则调用批准流程。
   - 如果已经处于 `REVIEW_PASSED / PULLING / COPYING / UPLOADING / COMPLETED`，只同步显示，不重复入队。

## 5. 数据模型与状态设计

### 5.1 GUI 内部状态

主窗口需要维护三类运行时数据：

1. `manifests_by_case_id`
   - 扫描得到的 `CaseManifest`

2. `review_rows_by_case_id`
   - 打标后的 `TaggingReviewRow`
   - 外加人工修订字段和审核状态

3. `controller`
   - 单例 `PipelineController`
   - 负责 case 的执行状态流转和执行队列

### 5.2 controller 状态推进

第一版继续沿用现有 `RuntimeStage`：

- `QUEUED`
- `TAGGING_RUNNING`
- `TAGGING_SKIPPED_USING_CACHED`
- `AWAITING_REVIEW`
- `REVIEW_PASSED`
- `PULLING`
- `COPYING`
- `UPLOADING`
- `COMPLETED`
- `FAILED`

需要补充的不是新状态，而是**事件通知机制**：

- 当状态变化时，controller 要把事件推回 GUI。
- GUI 根据事件刷新队列表格、日志区、审核页状态和 Excel 运行态列。

### 5.3 Excel 状态映射

建议保持以下规则：

- `pipeline_status`
  - `queued`
  - `awaiting_review`
  - `review_passed`
  - `pulling`
  - `copying`
  - `uploading`
  - `completed`
  - `failed`

- `tag_status`
  - `fresh_done`
  - `cache_loaded`
  - `failed`

- `review_status`
  - `pending`
  - `approved`
  - `approved_after_edit`
  - `rejected`

## 6. 组件职责

### 6.1 `video_tagging_assistant/gui/app.py`

职责：

- 解析 workbook 路径
- 构造主窗口
- 注入依赖：config、provider、controller、工作目录
- 启动 QApplication

第一版不把所有逻辑都堆在 `main_window.py`，app 层负责装配依赖。

### 6.2 `video_tagging_assistant/gui/main_window.py`

职责：

- 响应按钮事件
- 扫描 Excel
- 启动打标后台线程
- 启动 case 执行后台线程
- 接收 controller / worker 的事件并更新界面
- 调用 review panel 的显示与当前 case 切换

主窗口不直接实现 pull/upload 细节，但负责协调调用。

### 6.3 `video_tagging_assistant/gui/review_panel.py`

职责：

- 显示当前待审 case
- 展示自动结果
- 允许人工修订
- 触发批准 / 驳回动作
- 触发 Excel 刷新导入

它不直接操作 worker，只通过主窗口或回调向上发出“用户动作”。

### 6.4 `video_tagging_assistant/gui/table_models.py`

职责：

- 提供“今日队列 / 审核列表 / 执行监控”的表格模型
- 至少要能展示：
  - case_id
  - 当前阶段
  - tag 来源
  - 审核状态
  - 最近消息

第一版可以先做简单表格模型，不做复杂筛选和排序。

### 6.5 `video_tagging_assistant/pipeline_controller.py`

需要增强：

1. 增加事件 callback
2. 在以下时机发事件：
   - 注册 case
   - 打标结束
   - 批准 case
   - pull 开始 / 结束
   - copy 开始 / 结束
   - upload 开始 / 结束
   - 全流程完成 / 失败
3. 在 `run_next_execution_case()` 中捕获异常并转成 `FAILED`
4. 避免同一 case 重复入队

### 6.6 `video_tagging_assistant/excel_workbook.py`

需要增强两块能力：

1. **写审核 sheet**
   - 将 `TaggingReviewRow` 批量 upsert 到 review sheet
   - 让 GUI 审核和 Excel 审核都围绕同一份中间结果工作

2. **读审核 sheet**
   - 增加一个 helper：读取 review sheet 中已审核通过的 case
   - 返回 case_id、审核结论、人工修订简介、人工修订标签、审核备注等

## 7. 并发与线程模型

### 7.1 原则

GUI 线程只做界面更新，不做重任务。

### 7.2 后台任务

需要至少两个后台执行单元：

1. **批量打标线程**
   - 负责扫描后的一整批 tagging

2. **case 执行线程**
   - 负责对单个已批准 case 执行 pull/copy/upload
   - 可以每批准一个 case 启动一次，也可以共用一个串行 worker

第一版推荐：

- **批量打标一个后台线程**
- **审批后 case 执行一个串行后台线程**

这样最简单，且符合“审核通过一个就跑一个”的需求。

### 7.3 线程通信

worker 和 controller 不直接碰 UI 控件。

它们通过事件回调产出普通 Python 数据；主窗口收到后再切回 UI 更新。

## 8. 防重复执行规则

这是第一版必须明确的规则。

### 8.1 GUI 审核通过

若 case 当前状态是：

- `AWAITING_REVIEW`

则允许批准并入队。

若状态已经是：

- `REVIEW_PASSED`
- `PULLING`
- `COPYING`
- `UPLOADING`
- `COMPLETED`

则再次点击批准时不应重复入队，只提示“已在执行或已完成”。

### 8.2 Excel 导入批准

从 Excel 刷新到已批准记录时，同样遵循上述规则。

这样能避免 GUI 里点过一次、Excel 再刷新一次时出现双重执行。

## 9. 日志与可观察性

第一版至少提供三层可见性：

1. **GUI 日志面板**
   - 用户实时看到当前在做什么

2. **case 级阶段展示**
   - 在表格中看到每个 case 当前的 stage

3. **Excel 运行态列**
   - 退出 GUI 后仍能看到最终状态

显示粒度以“阶段变化 + 关键消息”为主，不追求第一版展示每个底层文件操作细节。

## 10. 测试策略

### 10.1 单测

至少补这些测试：

1. GUI 扫描后能载入 case 列表。
2. GUI 启动打标后，审核列表能接收到 `TaggingReviewRow`。
3. 在 GUI 中点击批准，会调用 `controller.approve_case(case_id)`。
4. 从 Excel 刷新审核结果时，只会把 `AWAITING_REVIEW` 的 approved case 推进执行。
5. 同一 case 不会重复入队。
6. controller 阶段事件能更新日志文本。

### 10.2 冒烟验证

手动验证路径：

1. 启动 GUI。
2. 选择 workbook。
3. 点击扫描，看到 case 出现在今日队列。
4. 选择 fresh 或 cached，点击启动流水线。
5. 打标结束后，在审核页看到结果。
6. 点击通过，看到日志进入 pulling / copying / uploading / completed。
7. 打开 Excel，确认 review sheet 和 `创建记录` 运行态列都被更新。

## 11. 实现范围建议

本轮实现建议聚焦以下最小可用路径：

1. GUI 扫描 `创建记录`
2. GUI 启动批量打标
3. GUI 展示审核结果
4. GUI 点击通过触发执行
5. GUI 从 Excel 手动导入已审核结果
6. GUI 显示日志和阶段变化
7. Excel 运行态与审核结果同步

不把失败重试、自动轮询、复杂过滤器、完整视频预览塞进这一轮。

## 12. 结论

本设计将当前项目从“有 worker、有 Excel、有 GUI 壳子”推进到“GUI 真正驱动整条流水线”。

它保持：

- Excel 仍是正式记录
- GUI 成为主操作入口
- 批量打标先行
- 单 case 审核通过后立刻执行
- Excel 仍可作为兼容审核输入源

同时通过“GUI 主导 + Excel 手动刷新导入”的边界，避免第一版就陷入双向实时同步的复杂性。
