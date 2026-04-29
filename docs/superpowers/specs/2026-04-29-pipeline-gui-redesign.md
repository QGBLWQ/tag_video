# GUI 流水线重新设计 — 设计规格

**日期：** 2026-04-29
**范围：** 重写 GUI 层，后端保持不动；修正业务流程与实际需求的偏差

---

## 1. 背景与问题

现有 GUI 实现与实际业务流程存在以下主要偏差：

1. **打标模式**：「旧数据」模式读取的是 JSON 缓存，而非按 case 对应关系加载 `intermediate/` 目录下的文件
2. **审核节奏**：现有实现打标完一个就可审核，业务要求全部打标完成后统一进入审核
3. **审核写回**：现有实现只写「审核结果」sheet，业务要求写回「创建记录」sheet 的标签字段
4. **执行触发**：pull/move/upload 依赖 bat 文件解析，不是由审核通过直接驱动
5. **字段选择**：审核时多选字段需人工从候选项中选一个，现有实现无此逻辑

---

## 2. 整体架构

### 2.1 分层原则

GUI 层完全重写，后端模块保持不动。GUI 通过明确的函数接口调用后端，不直接操作后端内部状态。

```
┌─────────────────────────────────────────────┐
│                   GUI 层                     │
│  main_window / tagging_tab / review_tab /   │
│  execution_tab / execution_worker           │
└────────────────┬────────────────────────────┘
                 │ 调用
┌────────────────▼────────────────────────────┐
│                  后端层                      │
│  excel_workbook / orchestrator /            │
│  tagging_service / case_ingest_orchestrator │
└─────────────────────────────────────────────┘
```

### 2.2 状态流转

```
启动软件
  → 加载 config.json
  → 选择工作簿（默认读 config 中的路径，可手动覆盖）
  → 读取「获取列表」sheet，展示本批 case 列表

Tab1 打标阶段
  → 选择模式：重新标定 / 旧数据
  → 重新标定：扫描 dji_nomal_dir，对所有视频跑 AI 打标，写 intermediate JSON
  → 旧数据：按 Action5Pro_Nomal 文件名 stem 从 intermediate_dir 加载对应 JSON
  → 全部 case 加载完成 → 自动解锁 Tab2

Tab2 审核阶段
  → 逐 case 展示打标结果（单选字段 + 多选字段人工选一）
  → 提供 PotPlayer 预览按钮
  → 操作：通过 / 跳过
  → 通过：写回「创建记录」sheet → 自动加入 Tab3 执行队列

Tab3 执行队列
  → 串行执行每个 case：pull → move → upload
  → 实时 log 面板显示进度
  → 失败单独列出，支持重试
```

---

## 3. 配置文件

所有路径和外部地址集中在 `configs/config.json`，代码中不硬编码任何路径。

```json
{
  "workbook_path": "C:/Users/19872/Desktop/work！/PC_A_采集记录表v2.1.xlsm",
  "dji_nomal_dir": "E:/DV/采集建档V2.1/Dji_mp4/Nomal",
  "dji_night_dir": "E:/DV/采集建档V2.1/Dji_mp4/Night",
  "intermediate_dir": "output/intermediate",
  "potplayer_exe": "C:/Program Files/DAUM/PotPlayer/PotPlayerMini64.exe",
  "adb_exe": "adb.exe",
  "dut_root": "/mnt/nvme/CapturedData",
  "local_case_root": "E:/DV/采集建档V2.1",
  "server_upload_root": "\\\\10.10.10.164\\rk3668_capture",
  "mode": "OV50H40_Action5Pro_DCG HDR",
  "pc_id": "A",
  "ai_provider": "qwen_dashscope",
  "ai_model": "qwen3.6-flash"
}
```

| 字段 | 用途 |
|------|------|
| `workbook_path` | Excel 工作簿路径，启动时默认加载 |
| `dji_nomal_dir` | 重新标定时扫描的视频目录 |
| `dji_night_dir` | move 操作时 DJI Night 视频的来源目录 |
| `intermediate_dir` | 旧数据模式加载 JSON 的目录 |
| `potplayer_exe` | 预览视频时调用的播放器路径 |
| `adb_exe` | adb 可执行文件路径 |
| `dut_root` | ADB pull 的设备端根目录 |
| `local_case_root` | pull/move 后的本地存放根目录 |
| `server_upload_root` | upload 目标服务器路径 |
| `mode` | 模组模式，决定服务器和本地的子目录名 |
| `pc_id` | PC 编号，决定 case_id 前缀（case_A_xxxx） |
| `ai_provider` / `ai_model` | 打标用的 AI 服务配置 |

---

## 4. 后端接口调整

### 4.1 复用不改动的模块

- `video_tagging_assistant/tagging_service.py`
- `video_tagging_assistant/orchestrator.py`
- `video_tagging_assistant/pipeline_models.py`
- `video_tagging_assistant/excel_workbook.py`（读取部分）

### 4.2 需要新增的后端函数

**`excel_workbook.py` 新增：**

```python
def write_tag_result_to_create_record(
    workbook_path: Path,
    row_index: int,
    tag_result: TagResult,
) -> None:
    """
    审核通过后，将人工确认的标签写回「创建记录」sheet 对应行。
    写入字段：安装方式、运动模式、运镜元素、光源划分、画面特征、影像表达、标签审核状态。
    workbook_path 必须是 .xlsx（不支持 .xlsm 写回）。
    """
```

`TagResult` 数据类：

```python
@dataclass
class TagResult:
    install_method: str       # 安装方式（单选）
    motion_mode: str          # 运动模式（单选）
    camera_move: str          # 运镜元素（单选）
    light_source: str         # 光源划分（单选）
    image_feature: str        # 画面特征（单选，从 AI 多选中人工选一）
    image_expression: str     # 影像表达（单选，从 AI 多选中人工选一）
    review_status: str        # 固定值 "审核通过"
```

**`case_ingest_orchestrator.py` 新增：**

```python
def pull_case(manifest: CaseManifest, config: dict) -> None:
    """执行单个 case 的 adb pull 操作。"""

def move_case(manifest: CaseManifest, config: dict) -> None:
    """执行单个 case 的本地文件 move 操作。"""

def upload_case(manifest: CaseManifest, config: dict) -> None:
    """执行单个 case 的服务器 upload 操作。"""
```

### 4.3 txt 文件生成（待确认）

审核通过后需生成一个 case 描述 txt 文件，格式待确认（需参考服务器上的现有样本）。实现时作为 `write_tag_result_to_create_record()` 之后的额外步骤插入，不影响其他流程。

---

## 5. GUI 模块结构

```
video_tagging_assistant/gui/
├── app.py                # 入口：加载 config，启动主窗口
├── main_window.py        # 三 Tab 主窗口，管理 Tab 间状态切换
├── tagging_tab.py        # Tab1：模式选择 + 打标进度
├── review_tab.py         # Tab2：逐 case 审核面板
├── execution_tab.py      # Tab3：串行队列 + log 面板
└── execution_worker.py   # QThread：串行执行 pull→move→upload
```

---

## 6. Tab1：打标

### 6.1 界面元素

- 工作簿路径显示（可点击「浏览」覆盖 config 默认值）
- 本批 case 列表（从「获取列表」sheet 读取，只读展示）
- 模式选择：`○ 重新标定` / `○ 旧数据`
- 「开始」按钮
- 进度条 + 当前处理文件名
- 错误信息区（打标失败的文件列出）

### 6.2 重新标定模式

1. 扫描 `dji_nomal_dir` 下所有视频文件
2. 逐个调用 `tagging_service` 进行 AI 打标
3. 结果写入 `intermediate_dir/{stem}.json`
4. 全部完成后自动切换到 Tab2

### 6.3 旧数据模式

1. 读取「获取列表」每一行的 `Action5Pro_Nomal` 字段
2. 取文件名 stem（去掉扩展名），在 `intermediate_dir` 下查找 `{stem}.json`
3. 找不到对应文件的 case 标记为「缺少打标数据」，在列表中高亮显示
4. 全部加载完成后自动切换到 Tab2

---

## 7. Tab2：审核

### 7.1 界面布局

```
┌─ 审核 (3/12) ─────────────────────────────────┐
│ case_A_0078   DJI_20260422151829_0001_D.MP4   │
│ [▶ PotPlayer 预览]                             │
│                                               │
│ AI 原始返回（参考）：                          │
│   安装方式: 手持 | 运动模式: 步行 | ...        │
│   画面特征: 边缘特征强弱, 反射与透视           │
│   影像表达: 建筑空间, 风景录像                 │
│                                               │
│ 安装方式   ○手持  ○穿戴  ○载具               │
│ 运动模式   ○行走  ○跑步  ○登山  ○骑行 ...    │
│ 运镜方式   ○推U摇 ○拉U摇 ○移U跟 ...          │
│ 光源       ○低    ○正常  ○强   ○大光比 ...   │
│                                               │
│ 画面特征（AI建议多项，选一个）                 │
│ ○纹理高低频  ○边缘特征强弱  ○反射与透视       │
│                                               │
│ 影像表达（AI建议多项，选一个）                 │
│ ○建筑空间   ○风景录像                         │
│                                               │
│ 备注: [________________________________]      │
│                                               │
│ [✓ 通过]   [→ 跳过]                           │
└───────────────────────────────────────────────┘
```

### 7.2 字段枚举值

所有字段使用固定枚举，存储在 `configs/tag_options.json`（不硬编码在代码中）：

```json
{
  "安装方式": ["手持", "穿戴", "载具"],
  "运动模式": ["行走", "跑步", "登山", "骑行", "机动车", "车辆", "滑行", "飞行", "船舶", "潜水", "冲浪"],
  "运镜方式": ["推U摇", "拉U摇", "移U跟", "升U俯拍", "环绕U推or拉", "用镜头", "推/拉U升/降", "希区柯克变"],
  "光源": ["低", "正常", "强", "大光比", "亮度突变", "多种光源", "色温交织", "雨天", "雾天", "极端天气"],
  "画面特征": ["纹理 高低频", "重复纹理", "边缘特征 强弱", "运动对焦", "人物肤色", "景深远近切换", "反射与透视"],
  "影像表达": ["风景录像", "建筑空间", "美食游街", "运动跟拍", "主题拍摄", "赛事舞台", "多目标分散运", "交互叙事"]
}
```

### 7.3 预选逻辑

- AI 返回的原始值显示在顶部「AI 原始返回」区域作为参考
- 所有单选按钮**不预选**，人工从头选
- 对于多选字段（画面特征、影像表达），只显示 AI 建议的候选项（不显示全部枚举），人工从中选一个
- 若 AI 建议项只有一个，仍需人工点击确认，不自动选中

### 7.4 通过操作

点击「通过」时：
1. 校验所有字段均已选择，否则提示未完成
2. 调用 `write_tag_result_to_create_record()` 写回「创建记录」sheet
3. 将该 case 加入 Tab3 执行队列
4. 自动跳到下一个 case

点击「跳过」时：
- 不写回，不加入队列，直接跳到下一个 case

### 7.5 PotPlayer 预览

点击「▶ PotPlayer 预览」按钮：
- 调用 `subprocess.Popen([config["potplayer_exe"], str(video_path)])`
- 视频路径为 `dji_nomal_dir / Action5Pro_Nomal 文件名`
- 若 potplayer_exe 不存在，弹出提示「请在 config.json 中配置 potplayer_exe 路径」

---

## 8. Tab3：执行队列

### 8.1 界面布局

```
┌─ 执行队列 ────────────────────────────────────┐
│ [队列列表]                                     │
│  ● case_A_0078  pull 进行中...   [取消]        │
│  ○ case_A_0079  待执行                         │
│  ✓ case_A_0077  已完成                         │
│  ✗ case_A_0076  失败: move 失败-路径不存在 [重试]│
│                                               │
│ [执行日志]                                     │
│  14:32:01  case_A_0078  pull 开始              │
│  14:32:05  case_A_0078  pull 完成              │
│  14:32:05  case_A_0078  move 开始              │
│  14:32:06  case_A_0078  move 完成              │
│  14:32:06  case_A_0078  upload 开始            │
│  14:32:10  case_A_0078  upload 完成            │
└───────────────────────────────────────────────┘
```

### 8.2 执行规则

- pull 严格串行：同一时刻只有一个 case 在执行 pull
- 单个 case 的三步顺序执行：pull → move → upload
- 一个 case 全部完成后，才开始下一个 case 的 pull
- 失败的 case 停在失败状态，不阻塞后续 case 继续执行
- 支持对失败 case 单独点「重试」，重新从失败的步骤开始

### 8.3 执行命令

**pull：**
```
adb pull /mnt/nvme/CapturedData/{rk_raw} .\{case_id}_RK_raw_{rk_raw}
```

**move：**
```
move "{local_case_root}\{case_id}_RK_raw_{rk_raw}" 
     "{local_case_root}\{mode}\{created_date}\{case_id}\{case_id}_RK_raw_{rk_raw}"
```

**upload：**
将本地 case 目录同步到 `{server_upload_root}\{mode}\{created_date}\{case_id}\`

### 8.4 execution_worker.py

- 运行在独立 QThread 中
- 通过 Qt 信号向 Tab3 发送状态更新，不直接操作 UI
- 信号定义：

```python
status_changed = Signal(str, str, str, str)
# (case_id, step, status, message)
# step: "pull" | "move" | "upload"
# status: "started" | "completed" | "failed"
```

- 新 case 加入队列时通过线程安全的队列对象（`queue.Queue`）传递给 worker

---

## 9. 待确认项

| 项目 | 状态 | 说明 |
|------|------|------|
| txt 文件生成 | 待确认 | 需参考服务器上现有样本，确认字段和格式后补充 |
| .xlsm 写回限制 | 已知 | openpyxl 写 .xlsm 会损坏 VBA，写回操作需要用户提供 .xlsx 副本，或在界面上提示 |

---

## 10. 不在本次范围内

- CLI 入口（`cli.py`）保持不变
- 「审核结果」sheet 的读写逻辑保持不变
- 统计 sheet、采集日志 sheet 不涉及
- 多台 PC 并发采集的协调逻辑不涉及
