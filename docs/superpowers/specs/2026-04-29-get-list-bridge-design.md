# 获取列表到创建记录桥接设计

- 日期：2026-04-29
- 主题：为 GUI pipeline 增加从 `获取列表` 索引表桥接到 `创建记录` 正式台账的读取逻辑
- 状态：待用户审阅

## 1. 背景

前一轮排查已经确认两件事：

1. 原始 `PC_A_采集记录表v2.1.xlsm` 不能被当前 `openpyxl` 流程安全原地写回，必须保持只读保护。
2. `获取列表` 并不是当前 `load_pipeline_cases()` 所假设的“创建记录式 manifest 表”。

真实的 `获取列表` 结构更像一个索引表：

- 第 1 行：日期，例如 `日期 / 20260422`
- 第 2 行：业务表头，例如：
  - `处理状态`
  - `RK_raw`
  - `Action5Pro_Nomal`
  - `Action5Pro_Night`
- 第 3 行开始：数据行，例如：
  - `R / 117 / DJI_20260422151829_0001_D.MP4 / DJI_20260422151916_0021_D.MP4`

而当前 GUI pipeline 真正需要的是完整 `CaseManifest`，它包含：

- `case_id`
- `created_date`
- `raw_path`
- `vs_normal_path`
- `vs_night_path`
- `local_case_root`
- `server_case_dir`
- `remark`
- `labels`

这些完整字段仍然只有 `创建记录` 具备。

因此新的正确方向不是“让 `获取列表` 直接替代 `创建记录`”，而是：

> **把 `获取列表` 视作索引输入，再桥接回 `创建记录` 里的正式记录。**

## 2. 目标

### 2.1 目标

1. 支持 GUI 从 `获取列表` 读取索引行。
2. 用 `RK_raw + normal/night 文件名` 组合键桥接到 `创建记录` 中的正式记录。
3. 仍然由 `创建记录` 生成最终 `CaseManifest`。
4. 不修改原始 `.xlsm`，保持只读。
5. 找不到或匹配不唯一时，抛出清晰错误。
6. 最大程度复用现有 `CaseManifest` 构造逻辑。

### 2.2 非目标

1. 本轮不恢复对 `.xlsm` 的写回。
2. 本轮不引入模糊匹配。
3. 本轮不支持只靠 `获取列表` 独立生成完整 case。
4. 本轮不做多设备/多模式通用桥接框架。
5. 本轮不修改 upload / tagging / review 的主流程结构。

## 3. 方案选择

采用：

**先读 `获取列表` 索引，再匹配 `创建记录` 正式行，最后沿用现有 manifest 构造逻辑。**

### 3.1 为什么不直接改 `load_pipeline_cases()` 去读 `获取列表`

`load_pipeline_cases()` 当前假设：

- 第 1 行就是标准表头
- 表头中存在：
  - `文件夹名`
  - `创建日期`
  - `Raw存放路径`
  - `VS_Nomal`
  - `VS_Night`

而真实 `获取列表`：

- 第 1 行不是业务表头
- 第 2 行字段也不同
- 没有 `文件夹名`
- 没有完整 `raw_path`

所以不能简单把 `source_sheet = 获取列表` 塞给现有 `load_pipeline_cases()`。

### 3.2 为什么仍以 `创建记录` 为真值来源

`创建记录` 仍然是唯一能提供完整 case 语义的地方，包括：

- case_id
- 完整 raw 路径
- normal/night 原路径
- 备注
- 标签

而 `获取列表` 只是更轻量的索引表。

所以桥接完成后，最终 `CaseManifest` 仍应来自 `创建记录`，不是来自 `获取列表` 拼凑出的半结构对象。

## 4. 运行时流程

### 4.1 读取 `获取列表`

新增一个只读解析过程：

1. 读取 workbook
2. 打开 `获取列表`
3. 第 1 行读取日期值，例如：`20260422`
4. 第 2 行读取表头
5. 第 3 行开始读取数据行

每一行至少提取：

- `处理状态`
- `RK_raw`
- `Action5Pro_Nomal`
- `Action5Pro_Night`
- 以及来自第 1 行的日期

### 4.2 桥接到 `创建记录`

对 `获取列表` 每一行，在 `创建记录` 中查找候选记录。

桥接条件采用组合键：

1. `raw_path` 尾号对应 `RK_raw`
2. `vs_normal_path.name == Action5Pro_Nomal`
3. `vs_night_path.name == Action5Pro_Night`

当且仅当唯一匹配时，认定该 `获取列表` 行对应这条 `创建记录` 行。

### 4.3 生成 `CaseManifest`

一旦桥接成功：

- 直接复用现有 `创建记录 -> CaseManifest` 的构造逻辑
- 不重新定义另一套 manifest 结构

## 5. 匹配规则细节

### 5.1 `RK_raw` 匹配

当前 `case_task_factory.py` 已经暗示 raw 路径尾号有稳定语义：

- 例如路径尾段可能是：`case_A_0001_RK_raw_117`
- 当前代码也在用类似方式拆尾号

因此桥接时可以用：

- `raw_path.name` 或其尾号部分
- 去匹配 `获取列表.RK_raw`

### 5.2 normal/night 文件名匹配

桥接时统一按文件名比较：

- `Path(vs_normal_path).name == Action5Pro_Nomal`
- `Path(vs_night_path).name == Action5Pro_Night`

不比较父目录结构。

### 5.3 为什么要组合匹配

单独使用某一个字段都不够稳：

- 只靠 `RK_raw` 可能撞历史记录或异常数据
- 只靠视频文件名也可能不够唯一

因此本轮采用：

- `RK_raw + normal 文件名 + night 文件名`

作为桥接键。

## 6. 错误处理策略

### 6.1 `获取列表` 表头不符合预期

如果第 2 行缺少任一关键列：

- `处理状态`
- `RK_raw`
- `Action5Pro_Nomal`
- `Action5Pro_Night`

则立即报清晰错误。

### 6.2 找不到匹配的创建记录

如果某一行在 `创建记录` 中找不到候选：

- 直接报错
- 错误信息至少包含：
  - `RK_raw`
  - `Action5Pro_Nomal`
  - `Action5Pro_Night`

例如：

```text
No matching create-record row found for RK_raw=117, normal=DJI_xxx, night=DJI_xxx
```

### 6.3 匹配到多条创建记录

如果候选不唯一：

- 也直接报错
- 因为继续运行会把 case 绑定错

错误信息至少包含：

- 上述 3 个桥接字段
- 匹配数量

### 6.4 `.xlsm` 仍保持只读保护

即使后续支持 `获取列表` 扫描：

- 也只是读取原始 `.xlsm`
- 不恢复写回
- 所有 workbook 修改路径继续被安全护栏拦住

## 7. app 层职责

桥接逻辑仍建议放在 app / workbook 读取边界，而不是 controller 中。

职责建议如下：

- `excel_workbook.py`
  - 负责：
    - 解析 `获取列表`
    - 桥接到 `创建记录`
    - 输出正式 `CaseManifest`
- `gui/app.py`
  - 负责选择扫描模式与来源 sheet
- `pipeline_controller.py`
  - 不感知桥接来源
  - 只消费 `CaseManifest`

## 8. 测试策略

### 8.1 单测

至少新增以下测试：

1. 能读取 `获取列表` 第 1 行日期和第 2 行表头。
2. 能用 `RK_raw + normal/night 文件名` 唯一匹配到 `创建记录`。
3. 找不到匹配时会报清晰错误。
4. 匹配到多条时会报清晰错误。
5. 最终仍产出标准 `CaseManifest`。
6. `.xlsm` 只读保护不被桥接逻辑绕过。

### 8.2 回归测试

至少重跑：

- `tests/test_excel_workbook.py`
- `tests/test_excel_workbook_pipeline.py`
- `tests/test_gui_smoke.py`
- `tests/test_pipeline_controller.py`

## 9. 结论

这次设计的核心不是让 `获取列表` 取代 `创建记录`，而是明确两者分工：

- `获取列表`：索引输入
- `创建记录`：正式台账真值来源

通过引入组合键桥接：

- `RK_raw`
- `Action5Pro_Nomal`
- `Action5Pro_Night`

系统可以在不破坏既有 pipeline 主体结构的情况下，把 `获取列表` 纳入 GUI 扫描入口，同时继续让最终 manifest 语义保持稳定。
