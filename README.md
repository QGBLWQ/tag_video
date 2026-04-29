# 视频采集打标 GUI 工具

采集记录台账驱动的三阶段流水线：**AI 打标 → 人工审核 → 执行队列（pull / move / upload）**。

---

## 快速开始

```bash
# 1. 复制配置模板并填写
cp configs/config.example.json configs/config.json

# 2. 启动 GUI
python app.py
```

配置字段说明见 [`docs/config-reference.md`](docs/config-reference.md)。

---

## 工作流程

### Tab 1 — 打标

1. 在「工作簿」栏选择台账（`.xlsm` 只读 / `.xlsx` 可写回）
2. 点击「加载工作簿」，从「获取列表」sheet 读入本批 case
   - case_id 自动续接「创建记录」已有最大序号（如已有 case_A_0105，本批从 case_A_0106 开始）
3. 选择模式后点「开始」：
   - **重新标定**：压缩视频 → 调用 AI 接口 → 写入 `output/intermediate/{stem}.json`
   - **旧数据**：直接从 `output/intermediate/` 加载已有 JSON

### Tab 2 — 审核

- 顶部下拉框选择**设备编号**（选一次后自动沿用至本批全部 case，来源：台账 Dut_info sheet）
- AI 标签摘要展示在上方，**画面描述**文本框可直接编辑
- 单选字段（安装方式 / 运动模式 / 运镜方式 / 光源）：AI 预选，可修改
- 多选字段（画面特征 / 影像表达）：仅展示 AI 建议候选项，人工选一个
- **✓ 通过**：写入「创建记录」sheet（仅 `.xlsx`），case 进入执行队列
- **→ 跳过**：不写回，不加队列，直接到下一 case

写入「创建记录」的字段：

| 列 | 内容 |
|----|------|
| 序号 | 递增行号 |
| 文件夹名 | case_id（如 case_A_0106） |
| 备注 | 画面描述文本 |
| 创建日期 | 获取列表 B1 日期 |
| 数量 | 1 |
| 安装方式 / 运动模式 / 运镜元素 / 光源划分 | 审核选择 |
| 画面特征 / 影像表达 | 审核选择 |
| Raw存放路径 | `{server_root}\{mode}\{date}\{case_id}\{case_id}_RK_raw_{suffix}` |
| 设备编号 / 模组型号 / 芯片 / 采集模式 / bit位 / 帧率 / 其他信息 | 来自 Dut_info |
| VS_Nomal | `{server_root}\{mode}\{date}\{case_id}\{case_id}_{normal_filename}` |
| VS_Night | `{server_root}\{mode}\{date}\{case_id}\{case_id}_night_{night_filename}` |

### Tab 3 — 执行队列

审核通过的 case 依次执行：

1. **pull** — `adb pull` 从设备拉取 RK raw 数据
2. **move** — 整理至本地目录结构
3. **upload** — `shutil.copytree` 上传至服务器共享目录

串行执行，实时日志，失败可重试。未连接 ADB 时 pull 步骤会失败，不影响审核写回。

---

## 台账结构（Excel）

| Sheet | 用途 |
|-------|------|
| 获取列表 | 打标输入源，B1 为日期，第 2 行为表头，第 3 行起为数据 |
| 创建记录 | 审核通过后写入，工具自动追加行 |
| Dut_info | 设备选项表，「默认选项=是」的行在审核界面默认选中 |

「获取列表」必须含以下列：`处理状态`、`RK_raw`、`Action5Pro_Nomal`、`Action5Pro_Night`

---

## 环境要求

- Windows 10/11
- Python 3.8+
- `ffmpeg.exe`（放项目根目录或加入 PATH）
- `adb.exe`（pull 步骤需要；不采集时可不配置）
- DashScope API Key（重新标定模式需要）

```bash
pip install -r requirements.txt
```

---

## 配置

配置文件：`configs/config.json`（从 `configs/config.example.json` 复制）

关键字段速查：

| 字段 | 说明 |
|------|------|
| `workbook_path` | 台账 Excel 路径（GUI 默认加载） |
| `dji_nomal_dir` | DJI 普通光视频目录 |
| `dji_night_dir` | DJI 夜间视频目录 |
| `intermediate_dir` | AI 打标中间结果目录（默认 `output/intermediate`） |
| `server_upload_root` | 服务器共享路径（UNC 格式，如 `\\10.10.10.164\rk3668_capture`） |
| `mode` | 模组模式名，决定服务器子目录名（如 `OV50H40_Action5Pro_DCG HDR`） |
| `pc_id` | 本机编号（A/B/C/…），用于生成 case_id 前缀 |
| `provider.api_key` | DashScope API Key（建议用环境变量 `DASHSCOPE_API_KEY`） |

完整说明见 [`docs/config-reference.md`](docs/config-reference.md)。

---

## 输出目录

```
output/
├── intermediate/     # AI 打标 JSON，每个 case 一个文件
├── compressed/       # 送模压缩视频（临时）
└── cache/            # 打标缓存（按 case_id 分目录）
```
