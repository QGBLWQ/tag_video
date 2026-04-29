# Case Ingest 启动与配置简化设计

- 日期：2026-04-28
- 主题：将 case-ingest 从多参数命令行改为“启动 bat + 独立配置文件”的简化运行方式
- 状态：已确认设计，待用户审阅书面 spec

## 1. 背景

当前 `case-ingest` 入口位于 `video_tagging_assistant/cli.py`，运行时需要显式传入 `--pull-bat`、`--move-bat`、`--date`、`--server-root` 等参数。这个方式虽然直接，但日常使用时存在几个问题：

1. 命令较长，不便修改和复用。
2. 路径与运行命令混在一起，不适合非开发式操作。
3. 当用户从不同当前目录启动时，容易因为相对路径基准变化而出错。

当前核心业务流程本身已经相对清晰：`group_case_tasks()` 负责解析 bat 并构造 `CaseTask`，`run_case_ingest()` 负责 pull、copy、upload 编排。当前痛点主要在入口层和运行体验，而不是 case ingest 的核心业务逻辑。

## 2. 目标与非目标

### 2.1 目标

1. 将 `case-ingest` 的日常使用方式简化为一个固定启动 bat。
2. 将 `pull_bat`、`move_bat`、`server_root` 等业务参数移入独立配置文件，便于后续修改。
3. 保证从任意当前工作目录执行启动 bat 时，都能正确运行。
4. 为 `date` 提供“默认当天、允许配置覆盖、允许 CLI 临时覆盖”的机制。
5. 保留现有命令行参数模式，避免破坏已有使用方式。
6. 将路径解析规则收敛到入口层，避免影响现有 case ingest 主流程。

### 2.2 非目标

1. 不修改 `run_case_ingest()` 的核心业务编排逻辑。
2. 不重写 `group_case_tasks()`、`pull_worker.py`、`copy_worker.py`、`upload_worker.py` 的主要职责。
3. 不引入图形界面。
4. 不处理“项目整体搬迁后配置仍然自动发现”的更大范围部署问题。
5. 不在本次改造中新增与当前目标无关的 case 自动发现逻辑。

## 3. 推荐方案

最终采用：

**方案 C：启动 bat 负责运行体验，独立配置文件负责业务参数。**

推荐原因：

- 比“全写进 bat”更易维护，参数集中且结构清晰。
- 比“只保留配置、不提供启动 bat”更适合日常反复执行。
- 可以将“从任意当前目录启动也能跑”的问题完全放在 bat 层解决。
- 能在不动核心业务流程的前提下完成入口简化。

## 4. 调用方式设计

### 4.1 保留双入口

`case-ingest` 支持两种运行方式：

1. **配置驱动模式**（主推荐用法）
   - `python -m video_tagging_assistant.cli case-ingest --config path/to/case_ingest.json`

2. **原始参数模式**（兼容保留）
   - `python -m video_tagging_assistant.cli case-ingest --pull-bat ... --move-bat ... --server-root ... --date ...`

### 4.2 启动 bat 的职责

新增正式启动脚本，例如：

- `run_case_ingest.bat`

该脚本只负责：

1. 定位 bat 自身所在目录。
2. 切换到项目根目录。
3. 定位配置文件路径。
4. 调用 `python -m video_tagging_assistant.cli case-ingest --config ...`。

这样设计后，真正决定执行正确性的不是“用户当前 shell 在哪里”，而是“bat 能否基于自身位置找到项目与配置”。这正对应本次最重要的使用场景：**从任意当前工作目录执行启动 bat，仍能正确运行。**

### 4.3 示例启动脚本

额外提供：

- `run_case_ingest.example.bat`

用途：

- 作为可复制模板，便于将来改 Python 路径、改默认配置路径、改运行参数。
- 与正式启动脚本职责区分，避免临时试验影响正式入口。

## 5. 配置文件设计

### 5.1 文件形态

新增一个 case ingest 专用配置文件，例如：

- `configs/case_ingest.json`

### 5.2 建议字段

第一版建议至少包含：

- `pull_bat`
- `move_bat`
- `server_root`
- `date`（可选）
- `skip_upload`（可选）

后续若需要补充：

- `case_root_dir`
- 默认 Python 可执行路径
- 上传策略开关

也继续放在这个配置文件中，而不是继续扩展大量 CLI 参数。

### 5.3 路径解析规则

这是本次设计中的关键约束：

**配置文件中的相对路径，默认相对配置文件自身位置解析。**

因此：

- `pull_bat: "../20260422_pull.bat"` 的基准是配置文件目录，不是当前 shell 目录。
- `move_bat`、`server_root` 等同样遵循该规则。
- 绝对路径保持原样使用。

这样做的原因是：配置与路径声明应该绑定在一起，而不是受运行时当前目录影响。

## 6. 参数优先级规则

### 6.1 date 处理规则

`date` 采用以下优先级：

1. **CLI 显式覆盖值**
2. **配置文件中的 `date`**
3. **系统当天日期**

这样既满足日常少改字段，也保留了重跑历史日期批次时的可控性。

### 6.2 其他参数处理规则

对于 `pull_bat`、`move_bat`、`server_root`：

- 在配置驱动模式下，默认从配置文件读取。
- 若未来允许 CLI 覆盖，也应遵循“CLI > config”的规则。
- 在兼容模式下，仍允许完全通过原始 CLI 参数提供。

## 7. Python 侧职责拆分

### 7.1 CLI 层新增配置装载能力

主要改动集中在 `video_tagging_assistant/cli.py`：

- 为 `case-ingest` 新增 `--config`。
- 在入口层读取配置文件。
- 在入口层处理路径归一化与参数优先级。
- 生成最终的绝对路径和确定值后，再调用 `group_case_tasks(...)`。

### 7.2 保持核心流程不感知配置来源

以下模块不应承担配置解析职责：

- `video_tagging_assistant/bat_parser.py`
- `video_tagging_assistant/case_ingest_orchestrator.py`
- `video_tagging_assistant/pull_worker.py`
- `video_tagging_assistant/copy_worker.py`
- `video_tagging_assistant/upload_worker.py`

这些模块继续只处理已经准备好的路径与任务对象。

这样可以确保：

- 变化范围集中在入口层。
- 核心业务逻辑不需要知道配置文件在哪里。
- 降低本次改造风险。

## 8. 错误处理与提示

本次建议顺手补强入口层报错信息，使其更适合日常运行：

1. 配置文件不存在时，明确提示配置文件路径。
2. 配置缺少 `pull_bat`、`move_bat`、`server_root` 时，明确指出缺失字段。
3. 配置中的 bat 路径解析后不存在时，明确指出解析后的绝对路径。
4. `date` 无法确定时应有兜底逻辑，不让用户手动补传成为必需。
5. 启动 bat 中若 Python 不可用，应提供直接可理解的失败提示。

## 9. 文件落点建议

建议新增或修改如下内容：

### 新增

- `configs/case_ingest.json` — 正式配置文件
- `configs/case_ingest.example.json` — 示例配置文件
- `run_case_ingest.bat` — 正式启动脚本
- `run_case_ingest.example.bat` — 示例启动脚本
- `docs/superpowers/specs/2026-04-28-case-ingest-launch-simplification.md` — 本设计文档

### 修改

- `video_tagging_assistant/cli.py` — 为 `case-ingest` 增加 `--config` 支持与参数归一化逻辑
- `video_tagging_assistant/config.py` 或新增 case-ingest 专用配置加载函数 — 负责读取配置并解析路径

## 10. 验证策略

建议分三层验证：

### 10.1 配置解析测试

验证：

- 相对路径是否按配置文件目录解析。
- `date` 是否遵循 `CLI > config > today` 优先级。
- 缺失关键字段时是否给出清晰错误。

### 10.2 CLI 兼容测试

验证：

- 老的参数模式仍可运行。
- 新的 `--config` 模式能产出与原模式等价的 `group_case_tasks(...)` 输入。

### 10.3 启动脚本手工验证

验证：

1. 从项目根目录运行 `run_case_ingest.bat`。
2. 从其它当前目录运行同一个 bat。
3. 确认最终读取到正确配置、正确项目路径、正确 bat 路径。

## 11. 结论

本次改造应严格聚焦在：

**简化 case ingest 的入口层与运行方式，并增强路径解析稳定性。**

不修改 case ingest 的核心 pull/copy/upload 编排，不扩展新的业务流程，不引入无关重构。通过“启动 bat + 独立配置文件 + CLI 兼容保留”的方式，可以在最低风险下显著改善日常使用体验。
