# GUI 打标输入源配置化设计

- 日期：2026-04-29
- 主题：将 GUI pipeline 的打标输入源选择策略从代码默认行为提升为 `configs/config.json` 中 `gui_pipeline` 的可配置项
- 状态：待用户审阅

## 1. 背景

当前 GUI case pipeline 已经完成了：

- workbook 扫描
- Excel 审核刷新
- controller 执行桥接
- tagging bridge
- `gui_pipeline` 路径和根目录配置化

但真实测试表明，仍然存在一个关键的环境耦合点：

- 扫描得到的 `CaseManifest.vs_normal_path / vs_night_path`
- 默认直接来自 Excel `VS_Nomal / VS_Night`
- 这些值在正式环境中可能是公司内网共享路径
- 在离线/外网环境中不可访问

因此即使：

- `server_root`
- `local_root`
- `tagging_output_root`
- `cache_root`

都已经配置化，GUI 在点击“启动流水线”时仍可能因为 ffmpeg 直接读 Excel 中的远程 UNC 路径而失败。

所以现在真正需要配置化的，不再是“输出去哪儿”，而是：

> **打标阶段的视频输入从哪里取。**

## 2. 目标

### 2.1 目标

1. 在 `gui_pipeline` 配置段中新增“打标输入源策略”字段。
2. 支持两种模式：
   - 正式模式：继续直接使用 Excel 中的 `VS_Nomal / VS_Night`
   - 离线测试模式：从本地目录按文件名映射视频输入
3. 不修改 Excel 原始台账内容。
4. 不改变 `CaseManifest` 的正式语义来源。
5. 将路径替换限制在 app 层的 `start_tagging()` bridge 中完成。
6. 找不到本地输入文件时，抛出清晰错误，而不是继续去访问远程 UNC 路径。

### 2.2 非目标

1. 本轮不增加 GUI 内的输入目录选择器。
2. 本轮不做模糊匹配或递归搜索。
3. 本轮不修改 Excel 中的 `VS_Nomal / VS_Night` 字段值。
4. 本轮不为 execution 阶段单独做另一套输入映射策略。
5. 本轮不引入多 profile 或环境继承系统。

## 3. 配置结构设计

建议在 `gui_pipeline` 中新增：

```json
"gui_pipeline": {
  "tagging_input_mode": "excel",
  "tagging_input_root": "videos"
}
```

### 字段说明

- `tagging_input_mode`
  - `excel`：使用 `CaseManifest` 中已有的 `vs_normal_path / vs_night_path`
  - `local_root`：在打标开始前，将 `vs_normal_path / vs_night_path` 按文件名映射到本地目录

- `tagging_input_root`
  - 仅在 `tagging_input_mode = local_root` 时使用
  - 指向本地测试视频目录，例如 `videos/`

## 4. 方案选择

采用：

**在 app 层 `start_tagging()` bridge 中做输入源解析与覆盖。**

### 4.1 为什么不改扫描阶段

如果在扫描阶段就把 Excel 路径替换掉，会带来两个问题：

1. 今日队列和 review 阶段看到的 manifest 路径不再等同于 Excel 真值
2. 扫描逻辑会混入“环境适配”语义，边界不清晰

因此扫描阶段仍保持：

- 从 Excel 读什么，manifest 就先是什么

而在真正进入打标之前，再决定“实际拿哪个路径给 ffmpeg”。

### 4.2 为什么不改 Excel

Excel 是正式台账。

如果为了离线测试去改 `VS_Nomal / VS_Night` 的内容，会污染正式记录，也会让正式环境和测试环境的语义混在一起。

所以离线适配必须发生在代码 bridge 层，而不是回写 Excel。

## 5. 运行时行为

### 5.1 `tagging_input_mode = excel`

这是默认/正式模式。

行为：

- `run_batch_tagging()` 使用 manifest 当前已有的 `vs_normal_path / vs_night_path`
- 不做任何路径重写

适用场景：

- 公司内网
- Excel 中路径真实可访问
- 正式数据链路验证

### 5.2 `tagging_input_mode = local_root`

这是离线测试模式。

行为：

1. `start_tagging()` 收到 `manifests`
2. 对每个 manifest 复制一份运行时对象
3. 取原始 `vs_normal_path.name` / `vs_night_path.name`
4. 在 `Path(tagging_input_root)` 下拼出：
   - `tagging_input_root / 原始文件名`
5. 用这个本地路径替换掉运行时 manifest 的 `vs_normal_path / vs_night_path`
6. 再将新的 manifests 传给 `run_batch_tagging()`

### 5.3 匹配规则

仅支持：

- **按文件名精确匹配**

例如：

- Excel 中：
  - `\\10.10.10.164\rk3668_capture\...\case_A_0001_DJI_20260414144209_0109_D.DNG`
- 本地目录：
  - `videos/case_A_0001_DJI_20260414144209_0109_D.DNG`

系统只取 `name` 做映射，不解析父目录结构。

## 6. 错误处理策略

### 6.1 本地文件不存在

如果 `tagging_input_mode = local_root`，但本地目录中找不到对应文件：

- 立即抛出清晰错误
- 错误消息至少包含：
  - `case_id`
  - 原始文件名
  - 期望的本地路径

例如：

```text
Local tagging input not found for case_A_0001: videos/case_A_0001_DJI_20260414144209_0109_D.DNG
```

### 6.2 不允许 fallback 回远程路径

在 `local_root` 模式下，如果本地文件没找到：

- 不继续尝试 Excel 原路径

原因是：

- 用户选择本地测试模式，本来就是为了避免访问远程 UNC 路径
- fallback 回远程路径只会让错误变得更隐蔽

### 6.3 配置非法值

如果：

- `tagging_input_mode` 不是 `excel` 或 `local_root`

则应尽早抛出清晰错误，而不是默默走默认逻辑。

## 7. app 层职责

这次逻辑仍然放在 `video_tagging_assistant/gui/app.py`，由 `start_tagging()` bridge 负责：

1. 读取 `gui_pipeline.tagging_input_mode`
2. 读取 `gui_pipeline.tagging_input_root`
3. 根据策略生成运行时 manifest 列表
4. 把处理后的 manifests 交给 `run_batch_tagging()`

`main_window.py` 不需要知道这些细节。

## 8. 测试策略

### 8.1 单测

至少补以下测试：

1. `tagging_input_mode = excel` 时，不改 manifest 输入路径。
2. `tagging_input_mode = local_root` 时，会把输入路径替换为本地 `tagging_input_root / 文件名`。
3. `local_root` 模式下，本地文件不存在时会报清晰错误。
4. `tagging_input_root` 能从 `gui_pipeline` 正确传入。

### 8.2 回归测试

至少重跑：

- `tests/test_gui_smoke.py`
- `tests/test_case_ingest_cli_config.py`
- `tests/test_excel_workbook_pipeline.py`
- `tests/test_pipeline_controller.py`

## 9. 结论

这次设计解决的是 GUI pipeline 最后一个尚未配置化的关键环境依赖：

- **打标输入视频到底从 Excel 原路径读，还是从本地目录映射读取。**

通过把这个选择正式纳入 `gui_pipeline` 配置：

- 正式环境仍可直接走 Excel 路径
- 离线测试可切到本地目录
- Excel 台账不被污染
- app 层继续保持装配职责
- main window 不会承担环境适配逻辑

这样，GUI pipeline 才真正具备“同一套代码，在正式环境和离线测试环境之间切换”的能力。
