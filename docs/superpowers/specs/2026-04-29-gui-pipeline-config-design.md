# GUI Pipeline Config 化设计

- 日期：2026-04-29
- 主题：将 GUI case pipeline 中硬编码的路径、sheet 名称、mode 和本地/服务器根目录收敛到 `configs/config.json` 的 `gui_pipeline` 配置段
- 状态：待用户审阅

## 1. 背景

当前 `video_tagging_assistant/gui/app.py` 已经承担了 GUI 运行入口的真实装配职责，包括：

- workbook 扫描
- Excel 审核结果刷新
- controller 执行桥接
- tagging bridge

但这些真实装配里仍然存在一组硬编码默认值：

- `DEFAULT_MODE`
- `DEFAULT_SOURCE_SHEET`
- `DEFAULT_REVIEW_SHEET`
- `DEFAULT_ALLOWED_STATUSES`
- `DEFAULT_LOCAL_ROOT`
- `DEFAULT_SERVER_ROOT`
- `DEFAULT_CACHE_ROOT`
- `DEFAULT_TAGGING_OUTPUT_ROOT`

这会带来两个问题：

1. **离线 / 外网测试不方便**
   - 用户当前不在公司网络环境
   - Excel 中的路径、默认根目录和实际测试环境不匹配
   - 需要频繁改代码才能切换路径或目标位置

2. **正式运行维护成本高**
   - mode、sheet 名、server 根目录等运行参数本质上属于部署配置
   - 不应该长期硬编码在 `gui/app.py`

因此现在要做的是：

- 不引入临时 override 黑魔法
- 而是把 GUI pipeline 运行相关的地址和路径正式收敛进 `configs/config.json`

## 2. 目标

### 2.1 目标

1. 在 `configs/config.json` 中新增 `gui_pipeline` 配置段。
2. 将 GUI app 层当前使用的硬编码路径和地址迁移到 `gui_pipeline`。
3. 让 `gui/app.py` 在组装：
   - `scan_cases()`
   - `refresh_excel_reviews()`
   - `start_tagging()`
   - `run_execution_case()`
   时优先读取 `gui_pipeline` 配置。
4. 保持 GUI 主窗口和 controller 的结构不变，不把配置读取逻辑塞进 `main_window.py`。
5. 保留一个清晰的 fallback 机制，避免旧配置立刻全部失效。

### 2.2 非目标

1. 本轮不设计新的 GUI 配置界面。
2. 本轮不让用户在窗口里动态编辑这些配置。
3. 本轮不改 Excel 的正式台账语义。
4. 本轮不在配置层引入复杂环境继承或 profile 系统。
5. 本轮不解决 Excel 中视频源字段与本地测试输入之间的语义冲突，只解决“路径和地址从代码移到配置”。

## 3. 方案选择

采用：

**在 `configs/config.json` 顶层新增 `gui_pipeline` 子配置段。**

### 3.1 为什么不用继续扩展顶层字段

当前顶层字段：

- `input_dir`
- `output_dir`
- `compression`
- `provider`
- `prompt_template`

主要服务于原有视频批量打标流程。

如果继续把 GUI pipeline 的：

- sheet 名
- mode
- server root
- local root
- GUI output root

硬塞进现有顶层，会让配置语义越来越混乱，后续维护时很难分清“哪些是原始批量打标配置，哪些是 GUI case pipeline 配置”。

### 3.2 为什么不用完全强制配置

也可以直接要求：

- 没有 `gui_pipeline` 就报错

但当前项目已经在开发迭代中，直接强制会让现有流程和测试一下子全断。

因此更稳妥的方式是：

- `gui_pipeline` 优先
- 旧默认值 fallback

这样可以逐步完成迁移。

## 4. 配置结构设计

建议在 `configs/config.json` 中新增：

```json
{
  "gui_pipeline": {
    "source_sheet": "创建记录",
    "review_sheet": "审核结果",
    "mode": "OV50H40_Action5Pro_DCG HDR",
    "allowed_statuses": ["", "queued", "failed"],
    "local_root": "cases",
    "server_root": "server_cases",
    "cache_root": "artifacts/cache",
    "tagging_output_root": "artifacts/gui_pipeline"
  }
}
```

### 字段说明

- `source_sheet`
  - 从哪个 sheet 扫描 GUI case 队列

- `review_sheet`
  - 从哪个 sheet 读取审核通过结果

- `mode`
  - 当前 GUI pipeline 默认使用的 manifest mode

- `allowed_statuses`
  - 哪些 `pipeline_status` 允许被扫描进入队列

- `local_root`
  - 本地 case 根目录

- `server_root`
  - 目标归档/上传根目录

- `cache_root`
  - tagging cache 根目录

- `tagging_output_root`
  - GUI pipeline 批量打标输出目录

## 5. app 层使用规则

### 5.1 读取方式

`gui/app.py` 在启动时：

1. 读取 `configs/config.json`
2. 查找 `config.get("gui_pipeline", {})`
3. 对各字段按“配置优先，默认值兜底”组装

### 5.2 组装点

这些配置将驱动：

#### `scan_cases()`

使用：

- `source_sheet`
- `allowed_statuses`
- `local_root`
- `server_root`
- `mode`

#### `refresh_excel_reviews()`

使用：

- `review_sheet`

#### `start_tagging()`

使用：

- `cache_root`
- `tagging_output_root`

#### `run_execution_case()`

仍然主要走 controller 队列，不额外直接读这些配置，但其上游生成的 manifest 会已经带着 `local_root / server_root / mode` 的结果。

## 6. fallback 策略

为了平滑迁移，第一版使用 fallback：

- 没有 `gui_pipeline` 时，继续使用当前 `gui/app.py` 里的默认值
- 有 `gui_pipeline` 时，以配置为准

这意味着：

- 旧测试不需要全部推翻
- 新配置可以逐步落地
- 用户现在就可以开始调 `config.json`，无需再改源码

## 7. 错误处理策略

### 7.1 配置缺失

如果 `gui_pipeline` 缺失：

- 不报错
- 使用 fallback

### 7.2 配置字段类型错误

如果：

- `allowed_statuses` 不是列表
- 某个路径字段不是字符串

则应尽早抛出清晰错误，而不是等到下游路径拼接时报隐式异常。

### 7.3 路径不存在

对于：

- workbook 不存在
- cache_root / tagging_output_root / local_root / server_root 目录尚未创建

不要求启动时全部验证；谁真正用到，谁负责按现有逻辑创建或报错。

## 8. 测试策略

### 8.1 单测

至少补以下测试：

1. 有 `gui_pipeline` 时，`launch_case_pipeline_gui()` 注入的 scan/refresh/tagging bridge 使用配置值。
2. 没有 `gui_pipeline` 时，仍使用默认值。
3. `allowed_statuses` 从列表转换成集合后能正确传入扫描逻辑。
4. `tagging_output_root` / `cache_root` 能进入 `run_batch_tagging()`。

### 8.2 回归测试

至少重跑：

- `tests/test_gui_smoke.py`
- `tests/test_case_ingest_cli_config.py`
- `tests/test_excel_workbook_pipeline.py`
- `tests/test_pipeline_controller.py`

## 9. 结论

这次设计的重点不是增加更多 GUI 功能，而是把本来就已经存在、但不该硬编码在 `gui/app.py`` 的运行参数迁移到配置文件中。

这样做之后：

- 用户可以直接改 `configs/config.json` 来调整路径和地址
- 离线测试和正式环境切换不再依赖改源码
- `gui/app.py` 仍然保持“装配层”定位
- `main_window.py` 不会被配置细节污染

这是把 GUI pipeline 从“开发中可运行”推进到“可维护、可部署、可切环境”的必要一步。
