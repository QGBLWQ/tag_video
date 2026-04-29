# GUI App 层真实装配设计

- 日期：2026-04-29
- 主题：将 `video_tagging_assistant/gui/app.py` 从最小窗口启动器升级为真实依赖装配层，采用 B1 方案
- 状态：待用户审阅

## 1. 背景

当前 `gui/app.py` 只负责：

- 创建 `QApplication`
- 构造 `PipelineMainWindow`
- 调用 `show()`

它还没有承担 GUI 应有的装配职责，因此当前 GUI 虽然已经具备：

- 扫描 case 的界面入口
- 启动打标的界面入口
- 审核通过触发执行的界面入口
- Excel 刷新审核结果的界面入口

但这些能力主要还停留在“可注入测试回调”阶段，而不是由 app 层真正组装出一个默认可运行的依赖集合。

现在需要做的不是重新设计 GUI 流程，而是把 `app.py` 提升为真正的装配层：

- 真实创建 `PipelineController`
- 真实装配 workbook 读路径
- 真实装配 Excel 审核刷新路径
- 以桥接函数形式装配打标与执行启动

## 2. 目标

### 2.1 目标

1. `gui/app.py` 负责真实依赖装配，而不再只是 `PipelineMainWindow()` 的薄包装。
2. `launch_case_pipeline_gui(workbook_path=...)` 在提供 workbook 路径时，可以默认组装出：
   - `scan_cases`
   - `refresh_excel_reviews`
   - `controller`
   - `run_execution_case`
   - `start_tagging`
3. 扫描与 Excel 审核刷新走真实 workbook helper：
   - `ensure_pipeline_columns`
   - `build_case_manifests`
   - `load_approved_review_rows`
4. 执行启动走真实 `PipelineController`。
5. 打标入口在 app 层提供一个真实桥接函数，但保留清晰的失败边界。
6. `PipelineMainWindow` 继续通过注入回调工作的结构，不把装配逻辑塞回窗口类。

### 2.2 非目标

1. 本轮不引入完整后台线程框架。
2. 本轮不做 workbook 文件选择器。
3. 本轮不在 GUI 中开放 provider/config 的复杂配置面板。
4. 本轮不做多 workbook / 多项目切换。
5. 本轮不做自动 Excel 轮询。

## 3. 方案选择

采用：

**B1：真实装配 scan / refresh / controller，打标与执行通过 app 层桥接函数接入。**

### 3.1 为什么不是“全部硬连死”

如果一次性把 config、provider、线程、路径策略、错误恢复全部在 `app.py` 里硬编码，虽然表面上“更真实”，但会导致：

- 测试变脆
- 默认路径假设过多
- 一旦 provider/config 缺失，GUI 启动体验很差

### 3.2 为什么不是“继续只做注入壳子”

如果 `app.py` 继续只负责把回调留给外部注入，那么：

- GUI 仍然不是默认可运行入口
- `case-pipeline-gui` 命令的价值有限
- 真实运行路径永远停留在测试替身层面

### 3.3 B1 的核心边界

B1 的边界是：

- **真实读路径和真实 controller** 由 `app.py` 装起来
- **写路径和运行路径** 也给真实桥接函数
- 但桥接函数内部允许“清晰失败”，而不是强行吞掉问题或引入大而全框架

## 4. app.py 的职责划分

### 4.1 真实装配职责

`launch_case_pipeline_gui(workbook_path=None)` 需要负责：

1. 创建 `QApplication`
2. 规范化 workbook 路径
3. 创建 `PipelineController`
4. 创建 `scan_cases()`
5. 创建 `refresh_excel_reviews()`
6. 创建 `run_execution_case(case_id)`
7. 创建 `start_tagging(manifests, mode, event_callback)`
8. 将这些对象注入 `PipelineMainWindow`

### 4.2 不承担的职责

`app.py` 不负责：

- 直接更新 UI
- 保存 review panel 当前内容
- 实现 controller 状态机细节
- 实现 workbook helper 内部逻辑

## 5. 真实装配细节

### 5.1 workbook_path 处理

输入 `workbook_path` 时：

- 转为 `Path` 对象
- 若为空，则允许 GUI 启动
- 若提供值，则在桥接函数真正使用时再检查其可用性

这样做的原因是：

- GUI 启动不应因为路径为空而立即失败
- 但真正扫描或刷新时，应明确暴露路径问题

### 5.2 scan_cases()

`scan_cases()` 的默认逻辑：

1. 若 workbook 不存在，返回空列表或抛出清晰错误
2. 调用 `ensure_pipeline_columns(workbook, source_sheet="创建记录")`
3. 调用 `build_case_manifests(...)`
4. 返回 `CaseManifest[]`

默认参数建议：

- `source_sheet="创建记录"`
- `allowed_statuses={"", "queued", "failed"}`
- `mode` 先使用固定字符串
- `local_root` 和 `server_root` 先使用 app 层约定的默认目录

### 5.3 refresh_excel_reviews()

`refresh_excel_reviews()` 的默认逻辑：

1. 若 workbook 不存在，返回空列表或抛出清晰错误
2. 调用 `load_approved_review_rows(workbook, review_sheet="审核结果")`
3. 返回审核通过列表

### 5.4 run_execution_case(case_id)

执行桥接函数的默认逻辑：

1. 不直接用 `case_id` 查 worker
2. 只在 controller 队列中已有 case 时，调用 `controller.run_next_execution_case()`
3. 若队列为空，不做额外动作

这个桥接函数的本质是：

- GUI 批准动作负责 `approve_case(case_id)`
- `run_execution_case(case_id)` 负责把 controller 里已入队的下一项真正跑起来

### 5.5 start_tagging(...)

`start_tagging(manifests, mode, event_callback)` 的默认逻辑：

1. 读取一个约定的 config 文件
2. 从 config 中取 prompt template
3. 构造 provider
4. 调用 `run_batch_tagging(...)`
5. 返回 `TaggingReviewRow[]`

这一层是真实桥接，但需要允许以下失败以“清晰异常”的形式暴露：

- config 不存在
- config 内容不完整
- provider 无法构造
- 运行目录不存在

本轮不在 `app.py` 吞掉这些失败。

## 6. 默认约定

为了让 B1 可落地，先接受以下固定约定：

- workbook source sheet：`创建记录`
- workbook review sheet：`审核结果`
- pipeline mode：先固定一个现有 mode 字符串
- local root：`cases/`
- cache root：`artifacts/cache/`
- tagging output root：`artifacts/gui_pipeline/`

这些约定后续可以配置化，但本轮不展开。

## 7. 错误处理策略

### 7.1 启动阶段

- `QApplication` 和窗口构造失败：直接抛错
- workbook_path 缺失：允许启动 GUI

### 7.2 运行阶段

- scan / refresh / tagging / execution 失败：由桥接函数抛出清晰异常
- GUI 主窗口可以在后续迭代中把这些异常转成日志或提示框

### 7.3 当前阶段不做

- 自动重试
- 静默降级
- fallback provider
- 自动创建复杂目录树以掩盖配置问题

## 8. 测试策略

### 8.1 单测

至少覆盖：

1. `launch_case_pipeline_gui()` 会把 workbook_path 传给窗口
2. app 层创建的 `scan_cases()` 使用真实 workbook helpers
3. app 层创建的 `refresh_excel_reviews()` 使用真实 workbook helpers
4. app 层创建的 `run_execution_case()` 调用 controller 的执行入口
5. app 层创建的 `start_tagging()` 能正确桥接到 tagging service（或在缺配置时清晰失败）

### 8.2 回归验证

至少重跑：

- `tests/test_gui_smoke.py`
- `tests/test_pipeline_controller.py`
- `tests/test_excel_workbook_pipeline.py`
- `tests/test_case_ingest_cli_config.py`

## 9. 结论

这次 B1 设计的目标不是把 GUI 系统一次性做成完整产品，而是把 `gui/app.py` 提升为真正的依赖装配层。

这样做之后：

- `case-pipeline-gui` 不再只是空窗口启动器
- GUI 的真实运行入口开始具备默认行为
- `PipelineMainWindow` 仍保持可测试和可替换的结构
- 后续若要加线程、provider 配置化、路径选择器，都可以继续在 `app.py` 上演进，而不需要回头重构窗口类
