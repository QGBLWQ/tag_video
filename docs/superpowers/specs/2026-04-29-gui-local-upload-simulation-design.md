# GUI 离线 Upload 模拟与来源 Sheet 修正设计

- 日期：2026-04-29
- 主题：为 GUI case pipeline 增加可配置的本地 upload 模拟，并将扫描来源 sheet 修正为真实使用的 `获取列表`
- 状态：待用户审阅

## 1. 背景

当前 GUI pipeline 已经具备：

- workbook 扫描
- 打标输入源配置化
- review 审核
- approve 后串行执行 pull / copy / upload

但真实离线测试里，仍然存在一个环境耦合点：

- execution 最后一环的 upload 默认写向 `server_root`
- 用户当前想做的是离线模拟
- 因此 upload 这一环希望仍然执行“上传动作”，但目标改成本地某个目录，而不是正式服务器路径

同时，用户指出当前 `source_sheet` 配置值也不符合真实业务语义：

- 当前默认是 `创建记录`
- 但 GUI 扫描今日队列时，真实来源应该是 `获取列表`

所以这次需要一起解决两个问题：

1. upload 阶段支持本地模拟目标路径
2. GUI 扫描来源 sheet 改为真实业务 sheet

## 2. 目标

### 2.1 目标

1. 在 `gui_pipeline` 中新增 upload 离线模拟配置项。
2. `local_upload_enabled = true` 时，upload 阶段仍执行真实目录复制，但目标改为本地目录。
3. 保持 pull / copy / tagging / review 逻辑不变。
4. 保持 `PipelineController` 的状态机语义不变。
5. 将 `source_sheet` 修正为真实用于扫描 case 队列的 `获取列表`。
6. 所有行为继续通过 app 层装配，而不是把环境判断散到 controller 内部。

### 2.2 非目标

1. 本轮不修改 GUI 界面，不新增 upload 模式切换按钮。
2. 本轮不改 Excel 审核写回逻辑。
3. 本轮不同时改 tagging 输入逻辑。
4. 本轮不引入多 profile / 环境继承系统。
5. 本轮不改变 upload worker 的核心复制语义。

## 3. 配置结构设计

建议在 `gui_pipeline` 中新增或修正：

```json
"gui_pipeline": {
  "source_sheet": "获取列表",
  "review_sheet": "审核结果",
  "local_upload_enabled": false,
  "local_upload_root": "mock_server_cases"
}
```

### 字段说明

- `source_sheet`
  - GUI 扫描 case 队列的来源 sheet
  - 本次修正为 `获取列表`

- `local_upload_enabled`
  - `false`：使用原有 upload 目标，即 `server_case_dir`
  - `true`：将 upload 目标改写为本地模拟目录

- `local_upload_root`
  - 仅在 `local_upload_enabled = true` 时使用
  - 指向本地模拟“服务器”的根目录，例如 `mock_server_cases/`

## 4. 方案选择

采用：

**在 app 层装配 upload runner，并在运行时改写 upload 目标目录。**

### 4.1 为什么不改 controller 状态机

`PipelineController` 当前职责很清晰：

- 管理阶段流转
- 串联 pull / copy / upload 的执行顺序
- 通过依赖注入接收具体 runner

离线模拟 upload 属于“环境适配”，不是状态机语义变化。

因此不应该让 controller 知道：

- 当前是在正式上传
- 还是在本地模拟上传

controller 只需要继续调用注入进来的 upload runner。

### 4.2 为什么不改 upload worker 的核心语义

当前 upload worker 的核心语义是：

- 如果目标已存在，返回 skip
- 否则执行目录复制

这套语义对正式服务器目录和本地模拟目录都成立。

因此本轮不需要重写 upload worker，只需要在 app 层决定“这次上传的目标目录到底是什么”。

## 5. 运行时行为

### 5.1 `local_upload_enabled = false`

默认/正式模式。

行为：

- execution 阶段的 upload 目标仍使用 `CaseTask.server_case_dir`
- 不改 upload 目标路径

适用场景：

- 正式内网环境
- 真实服务器路径可访问

### 5.2 `local_upload_enabled = true`

离线模拟模式。

行为：

1. GUI 读取 `gui_pipeline.local_upload_root`
2. app 层构造一个包装后的 upload runner
3. controller 进入 upload 阶段时，仍然调用 upload runner
4. 但实际目标目录不再使用 manifest 原有的 `server_case_dir`
5. 而是改写为：
   - `local_upload_root / mode / created_date / case_id`
6. 然后继续调用现有 `upload_case_directory(...)`

### 5.3 本地模拟 upload 路径规则

本地 upload 目标路径统一为：

```text
local_upload_root / mode / created_date / case_id
```

例如：

```text
mock_server_cases/OV50H40_Action5Pro_DCG HDR/20260414/case_A_0001
```

这样做的目的：

- 保持与正式 `server_root / mode / date / case_id` 接近的目录结构
- 用户离线测试时更容易检查结果
- 后续切回正式环境时，路径认知不需要重建

## 6. `source_sheet` 修正

### 6.1 当前问题

当前 `source_sheet` 在代码中的职责其实是正确的：

- 它就是 GUI 扫描 case 队列时使用的来源 sheet

问题不在字段名，而在值：

- 当前默认/配置值是 `创建记录`
- 但用户真实流程要求使用 `获取列表`

### 6.2 本轮调整

本轮不新增 `queue_sheet` 等新字段。

直接修正：

- `DEFAULT_SOURCE_SHEET = "获取列表"`
- `configs/config.json` 里的 `gui_pipeline.source_sheet = "获取列表"`

这样是最小、最稳的改法。

## 7. 错误处理策略

### 7.1 `local_upload_enabled = true` 但 `local_upload_root` 缺失

应尽早抛出清晰错误，而不是进入 upload 阶段后再出现路径异常。

错误应至少包含：

- 配置字段名 `local_upload_root`
- 当前模式 `local_upload_enabled = true`

### 7.2 本地 upload 目标已存在

保持现有 upload 语义：

- 如果目标目录已存在，由现有 upload worker 返回 skip / exists 状态
- 不在 app 层重复发明一套策略

### 7.3 `source_sheet` 配错

如果 workbook 中不存在配置的来源 sheet：

- scan 阶段直接失败
- 报出找不到该 sheet
- 不做静默 fallback

### 7.4 不允许影响其他阶段

`local_upload_root` 只用于 upload 阶段。

不能影响：

- tagging 输入来源
- pull 本地落盘逻辑
- copy 目标路径
- review 流程

## 8. app 层职责

这次逻辑继续放在 `video_tagging_assistant/gui/app.py`，由 app 装配层负责：

1. 读取 `gui_pipeline.source_sheet`
2. 读取 `gui_pipeline.local_upload_enabled`
3. 读取 `gui_pipeline.local_upload_root`
4. 构造合适的 upload runner
5. 将 upload runner 注入 `PipelineController`

`PipelineController` 继续只负责：

- case 状态流转
- 队列推进
- 调用注入的 pull/copy/upload runners

## 9. 测试策略

### 9.1 单测

至少补以下测试：

1. `source_sheet = 获取列表` 时，GUI 扫描走该 sheet。
2. `local_upload_enabled = false` 时，upload 仍使用原 `server_case_dir`。
3. `local_upload_enabled = true` 时，upload 目标改写到 `local_upload_root / mode / created_date / case_id`。
4. 本地 upload 模式下，controller 仍然进入 `UPLOADING` 阶段，而不是直接跳过。
5. `local_upload_enabled = true` 且 `local_upload_root` 非法时，会报清晰错误。

### 9.2 回归测试

至少重跑：

- `tests/test_gui_smoke.py`
- `tests/test_pipeline_controller.py`
- `tests/test_case_ingest_cli_config.py`
- `tests/test_excel_workbook_pipeline.py`

## 10. 结论

这次设计解决两个现实问题：

1. 用户离线测试时，upload 需要模拟到本地目录，而不是正式服务器路径
2. GUI 扫描队列的来源 sheet 应该是 `获取列表`，不是当前配置里的 `创建记录`

通过把 upload 模拟纳入 `gui_pipeline` 配置，并把环境适配保持在 app 装配层：

- 正式模式仍走原有 upload
- 离线模式可切换到本地 upload
- controller 状态机无需承担环境判断
- upload worker 保持原有复制语义
- `source_sheet` 语义不变，只修正为真实值

这样，GUI pipeline 在离线测试环境下就能更完整地模拟真实执行链路，同时继续保持代码边界清晰。
