# 配置文件参考

本项目所有配置集中在 `configs/config.json`，代码中不硬编码任何路径或密钥。

**初次使用**：复制 `configs/config.example.json` 为 `configs/config.json`，按本文档填写各字段。

---

## 顶层路径字段（GUI 流水线专用）

这些字段由 GUI 主窗口（`video_tagging_assistant/gui/`）直接读取。

| 字段 | 类型 | 示例值 | 说明 |
|------|------|--------|------|
| `workbook_path` | string | `"C:/Users/.../PC_A_采集记录表v2.1.xlsm"` | Excel 工作簿路径。GUI 启动时默认加载；也可在「打标」Tab 的「浏览…」按钮手动覆盖。支持 `.xlsm`（只读）和 `.xlsx`（可写回）。 |
| `dji_nomal_dir` | string | `"E:/DV/采集建档V2.1/Dji_mp4/Nomal"` | DJI 普通光视频存放目录。「重新标定」模式扫描此目录下的所有视频文件进行 AI 打标。 |
| `dji_night_dir` | string | `"E:/DV/采集建档V2.1/Dji_mp4/Night"` | DJI 夜间视频存放目录。当前主要在 `move` 操作的路径拼接中使用，用于区分夜间素材来源。 |
| `intermediate_dir` | string | `"output/intermediate"` | 打标中间结果目录。「旧数据」模式从此目录按文件名 stem 查找 `{stem}.json`；「重新标定」模式将 AI 结果写入此目录。相对路径以项目根目录为基准。 |
| `potplayer_exe` | string | `"C:/Program Files/DAUM/PotPlayer/PotPlayerMini64.exe"` | PotPlayer 可执行文件的完整路径。「审核」Tab 的「▶ PotPlayer 预览」按钮调用此路径打开视频。若路径不存在，点击预览时会弹出提示。 |
| `adb_exe` | string | `"adb.exe"` | ADB 可执行文件路径。若 adb 已加入系统 PATH 则填 `"adb.exe"`，否则填完整路径（如 `"C:/Android/platform-tools/adb.exe"`）。用于执行 `adb pull` 从设备拉取 RK 原始数据。 |
| `dut_root` | string | `"/mnt/nvme/CapturedData"` | 设备（DUT）上存放 RK 原始数据的根目录（Android/Linux 路径）。`pull` 命令格式：`adb pull {dut_root}/{rk_suffix} ...`。 |
| `local_case_root` | string | `"E:/DV/采集建档V2.1"` | 本地 case 存放根目录。`pull` 操作将文件下载到 `{local_case_root}/{case_id}_RK_raw_{rk_suffix}`，`move` 操作将其整理为 `{local_case_root}/{mode}/{created_date}/{case_id}/` 结构。 |
| `server_upload_root` | string | `"\\\\10.10.10.164\\rk3668_capture"` | 服务器上传目标根路径（UNC 路径或本地映射盘）。`upload` 操作将本地 case 目录复制到 `{server_upload_root}/{mode}/{created_date}/{case_id}/`。目标已存在时会抛出错误，不覆盖。 |
| `mode` | string | `"OV50H40_Action5Pro_DCG HDR"` | 模组模式名称，同时决定本地和服务器的子目录名。每次采集前确认与当前硬件组合一致。 |
| `pc_id` | string | `"A"` | 本机编号（A/B/C/…），用于生成 case_id 前缀（如 `case_A_0078`）。多台 PC 并行采集时需保证唯一。 |

---

## `input_dir` / `output_dir`

| 字段 | 说明 |
|------|------|
| `input_dir` | CLI 批量打标模式的视频输入目录（默认 `"videos"`）。GUI 模式不使用此字段。 |
| `output_dir` | CLI 批量打标模式的输出根目录（默认 `"output"`）。GUI 模式的中间产物路径由 `intermediate_dir` 单独控制。 |

---

## `paths`（CLI 旧版路径，向后兼容）

仅 CLI 批量流水线使用，GUI 不读取此节。

| 字段 | 说明 |
|------|------|
| `paths.compressed_dir` | 视频压缩后的输出目录（默认 `"output/compressed"`）。 |
| `paths.intermediate_dir` | 旧 CLI 流水线的中间结果目录（与顶层 `intermediate_dir` 含义相同，优先级低于顶层字段）。 |
| `paths.review_file` | CLI 流水线生成的审核 txt 文件路径（默认 `"output/review/review.txt"`）。 |

---

## `compression`（视频压缩参数）

CLI 批量流水线在调用 FFmpeg 压缩视频时使用。GUI 模式的「重新标定」路径也通过 `tagging_service` 间接使用。

| 字段 | 类型 | 说明 |
|------|------|------|
| `width` | int | 压缩后视频宽度（像素），保持宽高比。默认 `960`。 |
| `video_bitrate` | string | 视频码率，如 `"700k"`。 |
| `audio_bitrate` | string | 音频码率，如 `"96k"`。 |
| `fps` | int | 压缩后帧率，默认 `12`。用于减小视频体积，加快 AI 处理速度。 |

---

## `provider`（AI 打标服务配置）

控制「重新标定」模式下调用哪个 AI 接口完成视频理解与结构化打标。

| 字段 | 说明 |
|------|------|
| `name` | provider 类型。可选值：`"qwen_dashscope"`（通义千问）、`"openai_compatible"`（兼容 OpenAI 接口的服务）、`"mock"`（测试用）。 |
| `model` | 模型名称，如 `"qwen3.6-flash"`。具体可用值取决于所选 provider。 |
| `base_url` | API 接口基础 URL。DashScope 固定为 `"https://dashscope.aliyuncs.com/compatible-mode/v1"`；其他服务填对应地址。 |
| `api_key_env` | 存放 API Key 的**环境变量名**（推荐方式）。程序优先从此环境变量读取 Key，避免明文写入配置文件。 |
| `api_key` | API Key 明文（备用）。**仅在无法配置环境变量时使用**，推送到 Git 前必须清空或替换为占位符。 |
| `fps` | AI 分析时从视频中抽帧的频率（帧/秒），默认 `2`。值越大分析越细致，费用越高。 |

> **安全提示**：强烈建议通过环境变量（`api_key_env`）传递 API Key，不要将真实 Key 写入 `config.json` 并提交到 Git。

---

## `prompt_template`（AI 提示词模板）

控制发送给 AI 的 system prompt 和字段定义。修改此处会影响 AI 的打标行为和输出格式。

| 字段 | 说明 |
|------|------|
| `system` | System prompt 主体，告知 AI 角色和输出要求。 |
| `ignore_opening_instruction` | 补充指令：忽略视频开头的固定手机展示帧，避免被计入画面描述。 |
| `scene_description_instruction` | 补充指令：要求从正式场景开始描述，重点写光线变化和主体运动。 |
| `single_choice_fields` | 单选标签字段及其候选项。AI 从每个字段的候选项中选且仅选一个值。 |
| `multi_choice_fields` | 多选标签字段及其候选项。AI 可为每个字段返回多个值；审核阶段由人工从中选一个。 |

---

## `concurrency`（并发与重试）

控制 CLI 批量流水线的并发数和错误重试策略。GUI 流水线（pull/move/upload）为串行执行，不受此节影响。

| 字段 | 说明 |
|------|------|
| `compression_workers` | 并行压缩线程数，默认 `2`。 |
| `provider_workers` | 并行 AI 打标线程数，默认 `2`。注意 API 速率限制。 |
| `max_retries` | 单次 API 调用最大重试次数，默认 `3`。 |
| `retry_backoff_seconds` | 首次重试等待秒数，默认 `2`。 |
| `retry_backoff_multiplier` | 重试等待时间倍增系数，默认 `2`（即指数退避：2s → 4s → 8s）。 |

---

## `gui_pipeline`（旧版 GUI 流水线配置，已由顶层字段取代）

此节为早期 GUI 原型保留的配置，当前 GUI 实现（`video_tagging_assistant/gui/`）已**不再读取**此节，直接使用顶层字段。保留仅为向后兼容，可忽略。

| 字段 | 原始说明 |
|------|----------|
| `source_sheet` | 工作簿中的 case 来源 sheet 名 |
| `review_sheet` | 审核结果写入的 sheet 名 |
| `mode` | 同顶层 `mode` |
| `allowed_statuses` | 可进入流水线的 pipeline_status 值 |
| `local_root` / `server_root` | 本地/服务器根目录（已由顶层 `local_case_root` / `server_upload_root` 取代） |
| `cache_root` / `tagging_output_root` | 打标缓存目录（GUI 重新标定模式使用） |
| `tagging_input_mode` / `tagging_input_root` | 打标输入来源（已不使用） |
| `local_upload_enabled` / `local_upload_root` | 本地模拟上传（测试用，已不使用） |

---

## 快速配置检查清单

部署到新机器时，确认以下字段已按实际环境修改：

- [ ] `workbook_path` — 台账 Excel 文件的实际路径
- [ ] `dji_nomal_dir` / `dji_night_dir` — DJI 视频目录
- [ ] `local_case_root` — 本地数据存放根目录
- [ ] `server_upload_root` — 服务器共享路径
- [ ] `adb_exe` — ADB 路径（或确认已加入 PATH）
- [ ] `potplayer_exe` — PotPlayer 安装路径
- [ ] `mode` — 当前硬件模组名称
- [ ] `pc_id` — 本机唯一编号
- [ ] `provider.api_key_env` + 对应环境变量 — AI API 认证
- [ ] `provider.api_key` — **清空或填占位符，不要提交真实 Key**
