# Pipeline GUI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 重写 GUI 层，修正业务流程与实际需求的偏差，实现「打标 → 审核 → 执行队列」三阶段流水线。

**Architecture:** 保留后端模块不动，GUI 层完全重写为三 Tab 主窗口。后端新增 write_tag_result_to_create_record()、pull_case()、move_case()、upload_case() 四个函数供 GUI 调用。执行队列由独立 QThread 串行驱动，通过 Qt 信号更新 UI。

**Tech Stack:** Python 3.x, PyQt5, openpyxl, subprocess (adb), queue.Queue

---

## Task 1: 新增配置文件字段

**Files:**
- Modify: `configs/config.json`
- Create: `configs/tag_options.json`

- [ ] **Step 1: 更新 configs/config.json，在顶层合并新增字段（保留现有字段不动）**

将 `configs/config.json` 替换为以下完整内容（新增字段：workbook_path、dji_nomal_dir、dji_night_dir、intermediate_dir、potplayer_exe、adb_exe、dut_root、local_case_root、server_upload_root、mode、pc_id）：

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
  "input_dir": "videos",
  "output_dir": "output",
  "paths": {
    "compressed_dir": "output/compressed",
    "intermediate_dir": "output/intermediate",
    "review_file": "output/review/review.txt"
  },
  "compression": {
    "width": 960,
    "video_bitrate": "700k",
    "audio_bitrate": "96k",
    "fps": 12
  },
  "provider": {
    "name": "qwen_dashscope",
    "model": "qwen3.6-flash",
    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "api_key_env": "DASHSCOPE_API_KEY",
    "api_key": "sk-9a4ff54f43fe49548ad5e8283bc3b5ca",
    "fps": 2
  },
  "prompt_template": {
    "system": "你是一个中文视频理解助手。请根据视频内容和标签规则输出结构化标签。",
    "ignore_opening_instruction": "画面描述必须忽略视频开头固定出现的手持手机展示时间特写，不得将其写入描述。",
    "scene_description_instruction": "画面描述应从真正进入测试场景之后开始，可以更详细，重点描述光亮变化、场景细节、主体运动和画面变化。",
    "single_choice_fields": {
      "安装方式": ["手持", "穿戴", "载具"],
      "运动模式": ["行走", "跑步", "登山", "骑行", "机动车", "车辆", "滑行", "飞行", "船舶", "潜水", "冲浪"],
      "运镜方式": ["推U摇", "拉U摇", "移U跟", "升U俯拍", "环绕U推or拉", "用镜头", "推/拉U升/降", "希区柯克变"],
      "光源": ["低", "正常", "强", "大光比", "亮度突变", "多种光源", "色温交织", "雨天", "雾天", "极端天气"]
    },
    "multi_choice_fields": {
      "画面特征": ["纹理 高低频", "重复纹理", "边缘特征 强弱", "运动对焦", "人物肤色", "景深远近切换", "反射与透视"],
      "影像表达": ["风景录像", "建筑空间", "美食游街", "运动跟拍", "主题拍摄", "赛事舞台", "多目标分散运", "交互叙事"]
    }
  },
  "concurrency": {
    "compression_workers": 2,
    "provider_workers": 2,
    "max_retries": 3,
    "retry_backoff_seconds": 2,
    "retry_backoff_multiplier": 2
  },
  "gui_pipeline": {
    "source_sheet": "获取列表",
    "review_sheet": "审核结果",
    "mode": "OV50H40_Action5Pro_DCG HDR",
    "allowed_statuses": ["", "queued", "failed"],
    "local_root": "cases",
    "server_root": "server_cases",
    "cache_root": "artifacts/cache",
    "tagging_output_root": "artifacts/gui_pipeline",
    "tagging_input_mode": "local_root",
    "tagging_input_root": "videos",
    "local_upload_enabled": true,
    "local_upload_root": "mock_server_cases"
  }
}
```

- [ ] **Step 2: 创建 configs/tag_options.json**

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

- [ ] **Step 3: Commit**

```bash
git add configs/config.json configs/tag_options.json
git commit -m "$(cat <<'EOF'
config: add GUI pipeline fields and tag_options.json
EOF
)"
```

---

## Task 2: TagResult dataclass 和 write_tag_result_to_create_record

**Files:**
- Modify: `video_tagging_assistant/excel_workbook.py`
- Test: `tests/test_gui_excel_write.py`

- [ ] **Step 1: 写失败测试，创建 tests/test_gui_excel_write.py**

```python
import pytest
from pathlib import Path
import openpyxl
from video_tagging_assistant.excel_workbook import TagResult, write_tag_result_to_create_record


def _build_workbook(path: Path) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "创建记录"
    ws.append([
        "序号", "文件夹名", "备注", "创建日期", "数量",
        "安装方式", "运动模式", "运镜元素", "光源划分",
        "画面特征", "影像表达", "Raw存放路径", "VS_Nomal", "VS_Night",
        "标签审核状态",
    ])
    ws.append([1, "case_A_0001", "", "20260422", 1,
               "", "", "", "", "", "", "", "", "", ""])
    wb.save(path)


def test_write_tag_result_updates_create_record_row(tmp_path: Path):
    wb_path = tmp_path / "test.xlsx"
    _build_workbook(wb_path)

    result = TagResult(
        install_method="手持",
        motion_mode="行走",
        camera_move="推U摇",
        light_source="正常",
        image_feature="边缘特征 强弱",
        image_expression="建筑空间",
        review_status="审核通过",
    )
    write_tag_result_to_create_record(wb_path, row_index=2, tag_result=result)

    wb = openpyxl.load_workbook(wb_path)
    ws = wb["创建记录"]
    # cell.column is 1-based; row tuple is 0-based, so row[col-1]
    headers = {cell.value: cell.column for cell in ws[1]}
    row = ws[2]
    assert row[headers["安装方式"] - 1].value == "手持"
    assert row[headers["运动模式"] - 1].value == "行走"
    assert row[headers["运镜元素"] - 1].value == "推U摇"
    assert row[headers["光源划分"] - 1].value == "正常"
    assert row[headers["画面特征"] - 1].value == "边缘特征 强弱"
    assert row[headers["影像表达"] - 1].value == "建筑空间"
    assert row[headers["标签审核状态"] - 1].value == "审核通过"


def test_write_tag_result_skips_missing_column(tmp_path: Path):
    """Workbook without 运镜元素 column — function should not raise."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "创建记录"
    ws.append(["序号", "文件夹名", "安装方式", "运动模式", "标签审核状态"])
    ws.append([1, "case_A_0001", "", "", ""])
    path = tmp_path / "minimal.xlsx"
    wb.save(path)

    result = TagResult(
        install_method="手持",
        motion_mode="行走",
        camera_move="推U摇",
        light_source="正常",
        image_feature="边缘",
        image_expression="风景录像",
        review_status="审核通过",
    )
    write_tag_result_to_create_record(path, row_index=2, tag_result=result)  # must not raise

    wb2 = openpyxl.load_workbook(path)
    ws2 = wb2["创建记录"]
    headers = {cell.value: cell.column for cell in ws2[1]}
    assert ws2.cell(2, headers["安装方式"]).value == "手持"


def test_write_tag_result_rejects_xlsm(tmp_path: Path):
    xlsm_path = tmp_path / "test.xlsm"
    xlsm_path.write_bytes(b"fake xlsm")
    result = TagResult(
        install_method="手持", motion_mode="行走", camera_move="推U摇",
        light_source="正常", image_feature="边缘", image_expression="风景录像",
        review_status="审核通过",
    )
    with pytest.raises(ValueError, match="xlsm"):
        write_tag_result_to_create_record(xlsm_path, row_index=2, tag_result=result)
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
pytest tests/test_gui_excel_write.py -v
```

期望输出：`FAILED` — `ImportError: cannot import name 'TagResult' from 'video_tagging_assistant.excel_workbook'`

- [ ] **Step 3: 在 video_tagging_assistant/excel_workbook.py 末尾追加 TagResult 和实现**

追加到 `video_tagging_assistant/excel_workbook.py` 文件末尾（`from dataclasses import dataclass` 已在文件顶部导入）：

```python
@dataclass
class TagResult:
    """审核通过后，人工确认的完整标签结果。"""
    install_method: str    # 安装方式（单选）
    motion_mode: str       # 运动模式（单选）
    camera_move: str       # 运镜元素（单选）
    light_source: str      # 光源划分（单选）
    image_feature: str     # 画面特征（从 AI 多选中人工选一）
    image_expression: str  # 影像表达（从 AI 多选中人工选一）
    review_status: str     # 固定值 "审核通过"


def write_tag_result_to_create_record(
    workbook_path: Path,
    row_index: int,
    tag_result: TagResult,
) -> None:
    """审核通过后，将人工确认的标签写回「创建记录」sheet 对应行。

    _header_map() 返回 {header: 1-based-col-index}，直接用于 sheet.cell(column=...)。
    workbook_path 必须是 .xlsx，不支持 .xlsm 写回。
    """
    _reject_xlsm_write(workbook_path)
    workbook = load_workbook(workbook_path)
    sheet = workbook["创建记录"]
    headers = _header_map(sheet)
    field_map = {
        "安装方式": tag_result.install_method,
        "运动模式": tag_result.motion_mode,
        "运镜元素": tag_result.camera_move,
        "光源划分": tag_result.light_source,
        "画面特征": tag_result.image_feature,
        "影像表达": tag_result.image_expression,
        "标签审核状态": tag_result.review_status,
    }
    for col_name, value in field_map.items():
        if col_name in headers:
            sheet.cell(row=row_index, column=headers[col_name]).value = value
    workbook.save(workbook_path)
```

- [ ] **Step 4: 运行测试，确认全部通过**

```bash
pytest tests/test_gui_excel_write.py -v
```

期望输出：`3 passed`

- [ ] **Step 5: Commit**

```bash
git add video_tagging_assistant/excel_workbook.py tests/test_gui_excel_write.py
git commit -m "$(cat <<'EOF'
feat: add TagResult dataclass and write_tag_result_to_create_record
EOF
)"
```

---

## Task 3: pull_case / move_case / upload_case

**Files:**
- Modify: `video_tagging_assistant/case_ingest_orchestrator.py`
- Test: `tests/test_gui_case_ops.py`

- [ ] **Step 1: 写失败测试，创建 tests/test_gui_case_ops.py**

```python
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from video_tagging_assistant.pipeline_models import CaseManifest
from video_tagging_assistant.case_ingest_orchestrator import pull_case, move_case, upload_case


def _make_manifest(tmp_path: Path) -> CaseManifest:
    return CaseManifest(
        case_id="case_A_0078",
        row_index=2,
        created_date="20260422",
        mode="OV50H40_Action5Pro_DCG HDR",
        raw_path=Path("/mnt/nvme/CapturedData/117"),  # name = "117"
        vs_normal_path=Path("DJI_20260422151829_0001_D.MP4"),
        vs_night_path=Path("DJI_20260422151916_0021_D.MP4"),
        local_case_root=tmp_path / "cases" / "OV50H40_Action5Pro_DCG HDR" / "20260422" / "case_A_0078",
        server_case_dir=tmp_path / "server" / "OV50H40_Action5Pro_DCG HDR" / "20260422" / "case_A_0078",
        remark="",
    )


def _make_config(tmp_path: Path) -> dict:
    return {
        "adb_exe": "adb.exe",
        "dut_root": "/mnt/nvme/CapturedData",
        "local_case_root": str(tmp_path),
        "server_upload_root": str(tmp_path / "server"),
        "mode": "OV50H40_Action5Pro_DCG HDR",
    }


def test_pull_case_calls_adb_with_correct_args(tmp_path: Path):
    manifest = _make_manifest(tmp_path)
    config = _make_config(tmp_path)

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        pull_case(manifest, config)

    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert cmd[0] == "adb.exe"
    assert cmd[1] == "pull"
    assert "/mnt/nvme/CapturedData/117" in cmd[2]
    assert "case_A_0078_RK_raw_117" in cmd[3]


def test_move_case_moves_to_structured_directory(tmp_path: Path):
    manifest = _make_manifest(tmp_path)
    config = _make_config(tmp_path)
    # pull_case would create this directory
    src = tmp_path / "case_A_0078_RK_raw_117"
    src.mkdir(parents=True)
    (src / "data.bin").write_bytes(b"rawdata")

    move_case(manifest, config)

    dest = (tmp_path / "OV50H40_Action5Pro_DCG HDR" / "20260422"
            / "case_A_0078" / "case_A_0078_RK_raw_117")
    assert dest.exists()
    assert (dest / "data.bin").read_bytes() == b"rawdata"
    assert not src.exists()


def test_upload_case_copies_directory_to_server(tmp_path: Path):
    manifest = _make_manifest(tmp_path)
    config = _make_config(tmp_path)
    case_dir = (tmp_path / "OV50H40_Action5Pro_DCG HDR" / "20260422" / "case_A_0078")
    case_dir.mkdir(parents=True)
    (case_dir / "payload.bin").write_bytes(b"upload")

    upload_case(manifest, config)

    dest = (tmp_path / "server" / "OV50H40_Action5Pro_DCG HDR"
            / "20260422" / "case_A_0078" / "payload.bin")
    assert dest.exists()
    assert dest.read_bytes() == b"upload"


def test_upload_case_raises_if_destination_exists(tmp_path: Path):
    manifest = _make_manifest(tmp_path)
    config = _make_config(tmp_path)
    case_dir = (tmp_path / "OV50H40_Action5Pro_DCG HDR" / "20260422" / "case_A_0078")
    case_dir.mkdir(parents=True)
    dest = (tmp_path / "server" / "OV50H40_Action5Pro_DCG HDR"
            / "20260422" / "case_A_0078")
    dest.mkdir(parents=True)

    with pytest.raises(RuntimeError, match="already exists"):
        upload_case(manifest, config)
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
pytest tests/test_gui_case_ops.py -v
```

期望输出：`FAILED` — `ImportError: cannot import name 'pull_case' from 'video_tagging_assistant.case_ingest_orchestrator'`

- [ ] **Step 3: 在 video_tagging_assistant/case_ingest_orchestrator.py 末尾追加三个函数**

首先确认文件顶部已有 `import subprocess`（如无则添加）。追加以下代码到文件末尾：

```python
import shutil
import subprocess
from pathlib import Path as _Path


def pull_case(manifest, config: dict) -> None:
    """执行单个 case 的 adb pull 操作。

    adb pull {dut_root}/{rk_suffix} {local_case_root}/{case_id}_RK_raw_{rk_suffix}
    """
    rk_suffix = manifest.raw_path.name
    dest = _Path(config["local_case_root"]) / f"{manifest.case_id}_RK_raw_{rk_suffix}"
    dest.mkdir(parents=True, exist_ok=True)
    remote_path = f"{config['dut_root']}/{rk_suffix}"
    subprocess.run(
        [config["adb_exe"], "pull", remote_path, str(dest)],
        check=True,
    )


def move_case(manifest, config: dict) -> None:
    """执行单个 case 的本地文件 move 操作。

    将 {local_case_root}/{case_id}_RK_raw_{rk_suffix}
    移动到 {local_case_root}/{mode}/{created_date}/{case_id}/{case_id}_RK_raw_{rk_suffix}
    """
    rk_suffix = manifest.raw_path.name
    local_root = _Path(config["local_case_root"])
    src = local_root / f"{manifest.case_id}_RK_raw_{rk_suffix}"
    dest_dir = local_root / config["mode"] / manifest.created_date / manifest.case_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{manifest.case_id}_RK_raw_{rk_suffix}"
    shutil.move(str(src), str(dest))


def upload_case(manifest, config: dict) -> None:
    """执行单个 case 的服务器 upload 操作。

    将 {local_case_root}/{mode}/{created_date}/{case_id}
    整目录复制到 {server_upload_root}/{mode}/{created_date}/{case_id}
    目标已存在时抛出 RuntimeError。
    """
    local_root = _Path(config["local_case_root"])
    server_root = _Path(config["server_upload_root"])
    src = local_root / config["mode"] / manifest.created_date / manifest.case_id
    dest = server_root / config["mode"] / manifest.created_date / manifest.case_id
    if dest.exists():
        raise RuntimeError(f"Upload destination already exists: {dest}")
    shutil.copytree(str(src), str(dest))
```

- [ ] **Step 4: 运行测试，确认全部通过**

```bash
pytest tests/test_gui_case_ops.py -v
```

期望输出：`4 passed`

- [ ] **Step 5: Commit**

```bash
git add video_tagging_assistant/case_ingest_orchestrator.py tests/test_gui_case_ops.py
git commit -m "$(cat <<'EOF'
feat: add pull_case / move_case / upload_case to case_ingest_orchestrator
EOF
)"
```

---

## Task 4: ExecutionWorker

**Files:**
- Create: `video_tagging_assistant/gui/execution_worker.py`
- Test: `tests/test_gui_execution_worker.py`

- [ ] **Step 1: 写失败测试，创建 tests/test_gui_execution_worker.py**

```python
from pathlib import Path
from unittest.mock import patch

from PyQt5.QtWidgets import QApplication

from video_tagging_assistant.pipeline_models import CaseManifest
from video_tagging_assistant.gui.execution_worker import ExecutionWorker


_APP = QApplication.instance() or QApplication([])


def _make_manifest(case_id: str = "case_A_0078") -> CaseManifest:
    return CaseManifest(
        case_id=case_id,
        row_index=2,
        created_date="20260422",
        mode="OV50H40_Action5Pro_DCG HDR",
        raw_path=Path("/mnt/nvme/CapturedData/117"),
        vs_normal_path=Path("DJI_0001.MP4"),
        vs_night_path=Path("DJI_0021.MP4"),
        local_case_root=Path("/tmp/local/case"),
        server_case_dir=Path("/tmp/server/case"),
        remark="",
    )


def _make_config() -> dict:
    return {
        "adb_exe": "adb.exe",
        "dut_root": "/mnt/nvme/CapturedData",
        "local_case_root": "/tmp/local",
        "server_upload_root": "/tmp/server",
        "mode": "OV50H40_Action5Pro_DCG HDR",
    }


def test_worker_emits_started_and_completed_for_each_step():
    signals = []
    with patch("video_tagging_assistant.gui.execution_worker.pull_case"), \
         patch("video_tagging_assistant.gui.execution_worker.move_case"), \
         patch("video_tagging_assistant.gui.execution_worker.upload_case"):

        worker = ExecutionWorker(_make_config())
        worker.status_changed.connect(
            lambda case_id, step, status, msg: signals.append((case_id, step, status))
        )
        worker.enqueue(_make_manifest("case_A_0078"))
        worker.stop()
        worker.start()
        worker.wait(5000)

    assert ("case_A_0078", "pull", "started") in signals
    assert ("case_A_0078", "pull", "completed") in signals
    assert ("case_A_0078", "move", "started") in signals
    assert ("case_A_0078", "move", "completed") in signals
    assert ("case_A_0078", "upload", "started") in signals
    assert ("case_A_0078", "upload", "completed") in signals


def test_worker_emits_failed_on_exception_and_skips_remaining_steps():
    signals = []
    with patch("video_tagging_assistant.gui.execution_worker.pull_case",
               side_effect=RuntimeError("adb connection refused")), \
         patch("video_tagging_assistant.gui.execution_worker.move_case") as mock_move, \
         patch("video_tagging_assistant.gui.execution_worker.upload_case") as mock_upload:

        worker = ExecutionWorker(_make_config())
        worker.status_changed.connect(
            lambda case_id, step, status, msg: signals.append((case_id, step, status))
        )
        worker.enqueue(_make_manifest("case_A_0001"))
        worker.stop()
        worker.start()
        worker.wait(5000)

    assert ("case_A_0001", "pull", "started") in signals
    assert ("case_A_0001", "pull", "failed") in signals
    assert ("case_A_0001", "move", "started") not in signals
    mock_move.assert_not_called()
    mock_upload.assert_not_called()


def test_worker_continues_to_next_case_after_failure():
    signals = []
    pull_calls = []

    def pull_side_effect(manifest, config):
        pull_calls.append(manifest.case_id)
        if manifest.case_id == "case_A_0001":
            raise RuntimeError("first case fails")

    with patch("video_tagging_assistant.gui.execution_worker.pull_case",
               side_effect=pull_side_effect), \
         patch("video_tagging_assistant.gui.execution_worker.move_case"), \
         patch("video_tagging_assistant.gui.execution_worker.upload_case"):

        worker = ExecutionWorker(_make_config())
        worker.status_changed.connect(
            lambda case_id, step, status, msg: signals.append((case_id, step, status))
        )
        worker.enqueue(_make_manifest("case_A_0001"))
        worker.enqueue(_make_manifest("case_A_0002"))
        worker.stop()
        worker.start()
        worker.wait(5000)

    assert ("case_A_0001", "pull", "failed") in signals
    assert ("case_A_0002", "pull", "completed") in signals
    assert pull_calls == ["case_A_0001", "case_A_0002"]
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
pytest tests/test_gui_execution_worker.py -v
```

期望输出：`FAILED` — `ModuleNotFoundError: No module named 'video_tagging_assistant.gui.execution_worker'`

- [ ] **Step 3: 创建 video_tagging_assistant/gui/execution_worker.py**

```python
"""串行执行 pull→move→upload 的 QThread worker。

使用 queue.Queue 接收 CaseManifest，保证线程安全。
通过 status_changed 信号（不直接操作 UI）向 ExecutionTab 报告每步状态。
"""
import queue

from PyQt5.QtCore import QThread, pyqtSignal

from video_tagging_assistant.case_ingest_orchestrator import move_case, pull_case, upload_case
from video_tagging_assistant.pipeline_models import CaseManifest

_SENTINEL = None


class ExecutionWorker(QThread):
    """串行执行 pull→move→upload 的后台线程。

    信号：
        status_changed(case_id, step, status, message)
            step   : "pull" | "move" | "upload"
            status : "started" | "completed" | "failed"
    """

    status_changed = pyqtSignal(str, str, str, str)

    def __init__(self, config: dict, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._queue: queue.Queue = queue.Queue()

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def enqueue(self, manifest: CaseManifest) -> None:
        """将 manifest 加入执行队列（线程安全）。"""
        self._queue.put(manifest)

    def stop(self) -> None:
        """发送哨兵值，run() 循环在处理完当前 case 后退出。"""
        self._queue.put(_SENTINEL)

    # ------------------------------------------------------------------
    # QThread 入口
    # ------------------------------------------------------------------

    def run(self) -> None:
        while True:
            item = self._queue.get()
            if item is _SENTINEL:
                break
            self._process(item)

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _process(self, manifest: CaseManifest) -> None:
        steps = [
            ("pull", pull_case),
            ("move", move_case),
            ("upload", upload_case),
        ]
        for step_name, step_fn in steps:
            self.status_changed.emit(manifest.case_id, step_name, "started", "")
            try:
                step_fn(manifest, self._config)
                self.status_changed.emit(manifest.case_id, step_name, "completed", "")
            except Exception as exc:
                self.status_changed.emit(manifest.case_id, step_name, "failed", str(exc))
                return  # 当前 case 失败，停止后续步骤；继续处理队列中的下一个
```

- [ ] **Step 4: 运行测试，确认全部通过**

```bash
pytest tests/test_gui_execution_worker.py -v
```

期望输出：`3 passed`

- [ ] **Step 5: Commit**

```bash
git add video_tagging_assistant/gui/execution_worker.py tests/test_gui_execution_worker.py
git commit -m "$(cat <<'EOF'
feat: add ExecutionWorker — serial pull/move/upload QThread
EOF
)"
```

---

## Task 5: main_window.py

**Files:**
- Modify: `video_tagging_assistant/gui/main_window.py`
- Test: `tests/test_gui_main_window.py`

- [ ] **Step 1: 写失败测试，创建 tests/test_gui_main_window.py**

```python
from unittest.mock import MagicMock, patch

from PyQt5.QtWidgets import QApplication

_APP = QApplication.instance() or QApplication([])

_CONFIG = {
    "workbook_path": "",
    "mode": "OV50H40_Action5Pro_DCG HDR",
    "adb_exe": "adb.exe",
    "dut_root": "/mnt",
    "local_case_root": "/tmp/local",
    "server_upload_root": "/tmp/server",
    "intermediate_dir": "/tmp/intermediate",
}

_TAG_OPTIONS = {
    "安装方式": ["手持", "穿戴", "载具"],
    "运动模式": ["行走", "跑步"],
    "运镜方式": ["推U摇"],
    "光源": ["正常"],
    "画面特征": ["边缘特征 强弱"],
    "影像表达": ["风景录像"],
}


def _make_window():
    from video_tagging_assistant.gui.main_window import MainWindow
    with patch("video_tagging_assistant.gui.main_window.ExecutionWorker") as MockWorker:
        mock_worker = MagicMock()
        mock_worker.status_changed = MagicMock()
        mock_worker.status_changed.connect = MagicMock()
        MockWorker.return_value = mock_worker
        window = MainWindow(config=_CONFIG, tag_options=_TAG_OPTIONS)
        window._worker = mock_worker
    return window


def test_main_window_title():
    window = _make_window()
    assert window.windowTitle() == "Video Tagging Pipeline"


def test_main_window_has_three_tabs():
    window = _make_window()
    assert window._tabs.count() == 3
    assert window._tabs.tabText(0) == "打标"
    assert window._tabs.tabText(1) == "审核"
    assert window._tabs.tabText(2) == "执行队列"


def test_review_and_execution_tabs_initially_disabled():
    window = _make_window()
    assert not window._tabs.isTabEnabled(1)
    assert not window._tabs.isTabEnabled(2)


def test_on_tagging_complete_enables_review_tab_and_loads_cases():
    from unittest.mock import MagicMock, patch
    from pathlib import Path
    from video_tagging_assistant.pipeline_models import CaseManifest

    window = _make_window()
    manifest = CaseManifest(
        case_id="case_A_0078",
        row_index=2,
        created_date="20260422",
        mode="OV50H40_Action5Pro_DCG HDR",
        raw_path=Path("/mnt/117"),
        vs_normal_path=Path("DJI_0001.MP4"),
        vs_night_path=Path("DJI_0021.MP4"),
        local_case_root=Path("/tmp/cases"),
        server_case_dir=Path("/tmp/server/case"),
        remark="",
    )
    results = [{"manifest": manifest, "ai_result": {"安装方式": "手持"}, "missing": False}]

    window._review_tab.load_cases = MagicMock()
    window._on_tagging_complete(results)

    assert window._tabs.isTabEnabled(1)
    window._review_tab.load_cases.assert_called_once()
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
pytest tests/test_gui_main_window.py -v
```

期望输出：`FAILED` — `ImportError: cannot import name 'MainWindow'`（或 `AttributeError: module ... has no attribute '_tabs'`）

- [ ] **Step 3: 完整重写 video_tagging_assistant/gui/main_window.py**

```python
"""三 Tab 主窗口：打标 → 审核 → 执行队列。

管理 Tab 间状态切换，不直接执行业务逻辑：
  - 打标完成 → 解锁审核 Tab，调用 review_tab.load_cases()
  - 审核通过 → 写回工作簿，将 manifest 加入执行队列，解锁执行 Tab
"""
from pathlib import Path

from PyQt5.QtWidgets import QMainWindow, QTabWidget

from video_tagging_assistant.excel_workbook import write_tag_result_to_create_record
from video_tagging_assistant.gui.execution_tab import ExecutionTab
from video_tagging_assistant.gui.execution_worker import ExecutionWorker
from video_tagging_assistant.gui.review_tab import ReviewTab
from video_tagging_assistant.gui.tagging_tab import TaggingTab


class MainWindow(QMainWindow):
    def __init__(self, config: dict, tag_options: dict, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._tag_options = tag_options
        self._workbook_path = Path(config.get("workbook_path", ""))

        self.setWindowTitle("Video Tagging Pipeline")

        # 执行 Worker（后台线程，贯穿整个 window 生命周期）
        self._worker = ExecutionWorker(config)
        self._worker.start()

        # 三个 Tab
        self._tagging_tab = TaggingTab(config)
        self._review_tab = ReviewTab(config, tag_options)
        self._execution_tab = ExecutionTab(self._worker)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._tagging_tab, "打标")
        self._tabs.addTab(self._review_tab, "审核")
        self._tabs.addTab(self._execution_tab, "执行队列")

        # 初始状态：审核和执行 Tab 禁用
        self._tabs.setTabEnabled(1, False)
        self._tabs.setTabEnabled(2, False)

        self.setCentralWidget(self._tabs)

        # 信号连接
        self._tagging_tab.tagging_complete.connect(self._on_tagging_complete)
        self._review_tab.case_approved.connect(self._on_case_approved)
        self._worker.status_changed.connect(self._execution_tab.on_status_changed)

    # ------------------------------------------------------------------
    # 槽函数
    # ------------------------------------------------------------------

    def _on_tagging_complete(self, results: list) -> None:
        """打标完成：解锁审核 Tab，切换过去，并加载 case 列表。"""
        manifests = [r["manifest"] for r in results]
        tagging_results = {r["manifest"].case_id: r["ai_result"] for r in results}
        self._tabs.setTabEnabled(1, True)
        self._tabs.setCurrentIndex(1)
        self._review_tab.load_cases(manifests, tagging_results)

    def _on_case_approved(self, manifest, tag_result) -> None:
        """审核通过：写回工作簿，将 case 加入执行队列，解锁执行 Tab。"""
        if self._workbook_path.exists():
            write_tag_result_to_create_record(
                self._workbook_path,
                manifest.row_index,
                tag_result,
            )
        self._tabs.setTabEnabled(2, True)
        self._execution_tab.add_case(manifest)

    # ------------------------------------------------------------------
    # 窗口关闭：停止后台线程
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        self._worker.stop()
        self._worker.wait(3000)
        super().closeEvent(event)
```

- [ ] **Step 4: 运行测试，确认全部通过**

```bash
pytest tests/test_gui_main_window.py -v
```

期望输出：`4 passed`

- [ ] **Step 5: Commit**

```bash
git add video_tagging_assistant/gui/main_window.py tests/test_gui_main_window.py
git commit -m "$(cat <<'EOF'
feat: rewrite main_window — three-tab pipeline window
EOF
)"
```

---

## Task 6: tagging_tab.py

**Files:**
- Create: `video_tagging_assistant/gui/tagging_tab.py`
- Test: `tests/test_gui_tagging_tab.py`

- [ ] **Step 1: 写失败测试，创建 tests/test_gui_tagging_tab.py**

```python
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PyQt5.QtWidgets import QApplication

_APP = QApplication.instance() or QApplication([])

_CONFIG = {
    "workbook_path": "",
    "mode": "OV50H40_Action5Pro_DCG HDR",
    "intermediate_dir": "output/intermediate",
    "dji_nomal_dir": "/tmp/dji",
    "local_case_root": "/tmp/local",
    "server_upload_root": "/tmp/server",
    "cache_root": "artifacts/cache",
    "tagging_output_root": "artifacts/gui_pipeline",
    "provider": {"name": "mock", "model": "mock-model"},
    "prompt_template": {"system": "describe"},
}


def test_tagging_tab_instantiates():
    from video_tagging_assistant.gui.tagging_tab import TaggingTab
    tab = TaggingTab(_CONFIG)
    assert tab is not None


def test_tagging_tab_has_required_widgets():
    from video_tagging_assistant.gui.tagging_tab import TaggingTab
    tab = TaggingTab(_CONFIG)
    assert tab._workbook_edit is not None    # QLineEdit for workbook path
    assert tab._browse_btn is not None       # QPushButton
    assert tab._case_list is not None        # QListWidget
    assert tab._radio_rerun is not None      # QRadioButton: 重新标定
    assert tab._radio_cached is not None     # QRadioButton: 旧数据
    assert tab._start_btn is not None        # QPushButton: 开始
    assert tab._progress_bar is not None     # QProgressBar
    assert tab._current_file_label is not None  # QLabel
    assert tab._error_list is not None       # QListWidget for errors


def test_tagging_tab_loads_workbook_path_from_config():
    from video_tagging_assistant.gui.tagging_tab import TaggingTab
    config = {**_CONFIG, "workbook_path": "/some/path/records.xlsx"}
    tab = TaggingTab(config)
    assert tab._workbook_edit.text() == "/some/path/records.xlsx"


def test_tagging_tab_has_tagging_complete_signal():
    from video_tagging_assistant.gui.tagging_tab import TaggingTab
    tab = TaggingTab(_CONFIG)
    received = []
    tab.tagging_complete.connect(lambda results: received.append(results))
    # Signal exists and is connectable
    assert hasattr(tab, "tagging_complete")


def test_tagging_tab_load_cases_from_workbook(tmp_path: Path):
    """load_cases_from_workbook 读 GetListRow 并更新 QListWidget。"""
    import openpyxl
    from video_tagging_assistant.gui.tagging_tab import TaggingTab

    wb_path = tmp_path / "records.xlsx"
    wb = openpyxl.Workbook()
    # 创建记录 sheet
    cr = wb.active
    cr.title = "创建记录"
    cr.append(["序号", "文件夹名", "备注", "创建日期", "Raw存放路径",
               "VS_Nomal", "VS_Night", "安装方式", "运动模式"])
    cr.append([1, "case_A_0001", "", "20260422",
               "/mnt/117", "DJI_0001.MP4", "DJI_0021.MP4", "", ""])
    # 获取列表 sheet
    gl = wb.create_sheet("获取列表")
    gl.append(["日期", "20260422", "", ""])
    gl.append(["处理状态", "RK_raw", "Action5Pro_Nomal", "Action5Pro_Night"])
    gl.append(["R", "117", "DJI_0001.MP4", "DJI_0021.MP4"])
    wb.save(wb_path)

    config = {**_CONFIG, "workbook_path": str(wb_path)}
    tab = TaggingTab(config)
    tab._workbook_edit.setText(str(wb_path))
    tab._load_cases_from_workbook()

    assert tab._case_list.count() == 1
    assert "case_A_0001" in tab._case_list.item(0).text()
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
pytest tests/test_gui_tagging_tab.py -v
```

期望输出：`FAILED` — `ModuleNotFoundError: No module named 'video_tagging_assistant.gui.tagging_tab'`

- [ ] **Step 3: 创建 video_tagging_assistant/gui/tagging_tab.py**

```python
"""Tab1 打标：模式选择 + 加载工作簿 + 驱动批量打标。

重新标定模式：扫描 dji_nomal_dir，对所有 case 的 vs_normal 视频跑 AI 打标，
              结果写入 intermediate_dir/{stem}.json。
旧数据模式：按获取列表每行 vs_normal_name 的 stem 从 intermediate_dir 加载 JSON，
            找不到的 case 标红并加入错误列表。

全部 case 加载/打标完成后 emit tagging_complete(list)，
list 每项为 {"manifest": CaseManifest, "ai_result": dict, "missing": bool}。
"""
import json
from pathlib import Path

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from video_tagging_assistant.excel_workbook import build_case_manifests


class _TaggingWorker(QThread):
    """在后台线程中加载 / 打标，避免阻塞 UI。"""

    progress = pyqtSignal(int, int, str)   # (current, total, current_file)
    error = pyqtSignal(str)                # 错误描述
    finished = pyqtSignal(list)            # list of result dicts

    def __init__(self, config: dict, manifests: list, mode: str, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._manifests = manifests
        self._mode = mode  # "rerun" or "cached"

    def run(self) -> None:
        if self._mode == "rerun":
            self._run_rerun()
        else:
            self._load_cached()

    # ------------------------------------------------------------------

    def _run_rerun(self) -> None:
        """调用 run_batch_tagging，将结构化结果写到 intermediate_dir/{stem}.json。"""
        from video_tagging_assistant.tagging_cache import load_cached_result
        from video_tagging_assistant.tagging_service import run_batch_tagging

        from video_tagging_assistant.gui.app import build_provider_from_config

        intermediate_dir = Path(self._config.get("intermediate_dir", "output/intermediate"))
        intermediate_dir.mkdir(parents=True, exist_ok=True)
        cache_root = Path(self._config.get("cache_root", "artifacts/cache"))
        output_root = Path(self._config.get("tagging_output_root", "artifacts/gui_pipeline"))
        total = len(self._manifests)

        def _on_event(event):
            self.progress.emit(0, total, getattr(event, "current_file", "") or event.case_id)

        try:
            run_batch_tagging(
                manifests=self._manifests,
                cache_root=cache_root,
                output_root=output_root,
                provider=build_provider_from_config(self._config),
                prompt_template=self._config["prompt_template"],
                mode="fresh",
                event_callback=_on_event,
            )
        except Exception as exc:
            self.error.emit(f"打标批次错误: {exc}")

        results = []
        for i, manifest in enumerate(self._manifests):
            cached = load_cached_result(cache_root, manifest) or {}
            ai_result = cached.get("structured_tags", {})
            stem = manifest.vs_normal_path.stem
            json_path = intermediate_dir / f"{stem}.json"
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump({"structured_tags": ai_result}, f, ensure_ascii=False, indent=2)
            results.append({"manifest": manifest, "ai_result": ai_result, "missing": False})
            self.progress.emit(i + 1, total, manifest.case_id)

        self.finished.emit(results)

    def _load_cached(self) -> None:
        """从 intermediate_dir/{stem}.json 加载已有打标结果。"""
        intermediate_dir = Path(self._config.get("intermediate_dir", "output/intermediate"))
        total = len(self._manifests)
        results = []

        for i, manifest in enumerate(self._manifests):
            stem = manifest.vs_normal_path.stem
            json_path = intermediate_dir / f"{stem}.json"
            if json_path.exists():
                with open(json_path, encoding="utf-8") as f:
                    data = json.load(f)
                ai_result = data.get("structured_tags", data)
                missing = False
            else:
                ai_result = {}
                missing = True
                self.error.emit(f"缺少打标数据: {manifest.case_id}（找不到 {stem}.json）")

            results.append({"manifest": manifest, "ai_result": ai_result, "missing": missing})
            self.progress.emit(i + 1, total, manifest.case_id)

        self.finished.emit(results)


class TaggingTab(QWidget):
    """Tab1：工作簿选择 + 模式切换 + 打标进度。"""

    tagging_complete = pyqtSignal(list)

    def __init__(self, config: dict, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._manifests: list = []
        self._worker: _TaggingWorker | None = None
        self._setup_ui()

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        # 工作簿路径行
        wb_row = QHBoxLayout()
        self._workbook_edit = QLineEdit(self._config.get("workbook_path", ""))
        self._browse_btn = QPushButton("浏览…")
        self._load_btn = QPushButton("加载工作簿")
        wb_row.addWidget(QLabel("工作簿:"))
        wb_row.addWidget(self._workbook_edit, stretch=1)
        wb_row.addWidget(self._browse_btn)
        wb_row.addWidget(self._load_btn)
        layout.addLayout(wb_row)

        # Case 列表（只读展示）
        self._case_list = QListWidget()
        self._case_list.setMaximumHeight(160)
        layout.addWidget(QLabel("本批 Case 列表："))
        layout.addWidget(self._case_list)

        # 模式选择
        mode_row = QHBoxLayout()
        self._radio_rerun = QRadioButton("重新标定")
        self._radio_cached = QRadioButton("旧数据")
        self._radio_cached.setChecked(True)
        mode_row.addWidget(self._radio_rerun)
        mode_row.addWidget(self._radio_cached)
        mode_row.addStretch()
        layout.addLayout(mode_row)

        # 开始按钮 + 进度
        self._start_btn = QPushButton("开始")
        layout.addWidget(self._start_btn)
        self._progress_bar = QProgressBar()
        self._progress_bar.setValue(0)
        self._current_file_label = QLabel("")
        layout.addWidget(self._progress_bar)
        layout.addWidget(self._current_file_label)

        # 错误列表
        layout.addWidget(QLabel("错误（缺少打标数据的 case）："))
        self._error_list = QListWidget()
        self._error_list.setMaximumHeight(100)
        layout.addWidget(self._error_list)

        # 信号连接
        self._browse_btn.clicked.connect(self._browse_workbook)
        self._load_btn.clicked.connect(self._load_cases_from_workbook)
        self._start_btn.clicked.connect(self._start_tagging)

    # ------------------------------------------------------------------
    # 槽函数
    # ------------------------------------------------------------------

    def _browse_workbook(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择工作簿", "", "Excel 文件 (*.xlsx *.xlsm)"
        )
        if path:
            self._workbook_edit.setText(path)
            self._load_cases_from_workbook()

    def _load_cases_from_workbook(self) -> None:
        wb_path = Path(self._workbook_edit.text().strip())
        if not wb_path.exists():
            return
        try:
            self._manifests = build_case_manifests(
                workbook_path=wb_path,
                source_sheet="获取列表",
                allowed_statuses=set(),
                local_root=Path(self._config.get("local_case_root", "cases")),
                server_root=Path(self._config.get("server_upload_root", "server_cases")),
                mode=self._config.get("mode", ""),
            )
        except Exception as exc:
            self._error_list.addItem(f"加载失败: {exc}")
            return

        self._case_list.clear()
        for manifest in self._manifests:
            self._case_list.addItem(
                f"{manifest.case_id}  {manifest.vs_normal_path.name}"
            )

    def _start_tagging(self) -> None:
        if not self._manifests:
            self._load_cases_from_workbook()
        if not self._manifests:
            return

        mode = "rerun" if self._radio_rerun.isChecked() else "cached"
        self._error_list.clear()
        self._progress_bar.setMaximum(len(self._manifests))
        self._progress_bar.setValue(0)
        self._start_btn.setEnabled(False)

        self._worker = _TaggingWorker(self._config, self._manifests, mode)
        self._worker.progress.connect(self._on_progress)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _on_progress(self, current: int, total: int, filename: str) -> None:
        if total > 0:
            self._progress_bar.setMaximum(total)
        self._progress_bar.setValue(current)
        self._current_file_label.setText(filename)

    def _on_error(self, message: str) -> None:
        item = QListWidgetItem(message)
        item.setForeground(QColor("red"))
        self._error_list.addItem(item)

    def _on_finished(self, results: list) -> None:
        self._start_btn.setEnabled(True)
        self._current_file_label.setText("完成")
        self.tagging_complete.emit(results)
```

- [ ] **Step 4: 运行测试，确认全部通过**

```bash
pytest tests/test_gui_tagging_tab.py -v
```

期望输出：`5 passed`

- [ ] **Step 5: Commit**

```bash
git add video_tagging_assistant/gui/tagging_tab.py tests/test_gui_tagging_tab.py
git commit -m "$(cat <<'EOF'
feat: add TaggingTab — workbook load + 重新标定/旧数据 mode
EOF
)"
```

---

## Task 7: review_tab.py

**Files:**
- Create: `video_tagging_assistant/gui/review_tab.py`
- Test: `tests/test_gui_review_tab.py`

- [ ] **Step 1: 写失败测试，创建 tests/test_gui_review_tab.py**

```python
from pathlib import Path
from unittest.mock import MagicMock

from PyQt5.QtWidgets import QApplication, QAbstractButton

_APP = QApplication.instance() or QApplication([])

_TAG_OPTIONS = {
    "安装方式": ["手持", "穿戴", "载具"],
    "运动模式": ["行走", "跑步"],
    "运镜方式": ["推U摇", "拉U摇"],
    "光源": ["低", "正常"],
    "画面特征": ["边缘特征 强弱", "反射与透视"],
    "影像表达": ["风景录像", "建筑空间"],
}

_CONFIG = {
    "dji_nomal_dir": "/tmp/dji",
    "potplayer_exe": "/not/exist/potplayer.exe",
}


def _make_manifest(case_id: str = "case_A_0078"):
    from video_tagging_assistant.pipeline_models import CaseManifest
    return CaseManifest(
        case_id=case_id,
        row_index=2,
        created_date="20260422",
        mode="OV50H40_Action5Pro_DCG HDR",
        raw_path=Path("/mnt/117"),
        vs_normal_path=Path("DJI_0001.MP4"),
        vs_night_path=Path("DJI_0021.MP4"),
        local_case_root=Path("/tmp/cases"),
        server_case_dir=Path("/tmp/server/case"),
        remark="",
    )


def test_review_tab_instantiates():
    from video_tagging_assistant.gui.review_tab import ReviewTab
    tab = ReviewTab(_CONFIG, _TAG_OPTIONS)
    assert tab is not None


def test_review_tab_has_case_approved_signal():
    from video_tagging_assistant.gui.review_tab import ReviewTab
    tab = ReviewTab(_CONFIG, _TAG_OPTIONS)
    assert hasattr(tab, "case_approved")


def test_review_tab_load_cases_shows_first_case():
    from video_tagging_assistant.gui.review_tab import ReviewTab
    tab = ReviewTab(_CONFIG, _TAG_OPTIONS)
    manifests = [_make_manifest("case_A_0001"), _make_manifest("case_A_0002")]
    tagging_results = {
        "case_A_0001": {
            "安装方式": "手持",
            "运动模式": "行走",
            "运镜方式": "推U摇",
            "光源": "正常",
            "画面特征": ["边缘特征 强弱"],
            "影像表达": ["风景录像"],
        },
        "case_A_0002": {
            "安装方式": "穿戴",
            "运动模式": "跑步",
            "运镜方式": "拉U摇",
            "光源": "低",
            "画面特征": ["反射与透视"],
            "影像表达": ["建筑空间"],
        },
    }
    tab.load_cases(manifests, tagging_results)
    # 进度标签应显示 1/2
    assert "1" in tab._progress_label.text()
    assert "2" in tab._progress_label.text()
    # case_id 标签应显示第一个 case
    assert "case_A_0001" in tab._case_label.text()


def test_review_tab_approve_without_all_fields_shows_error():
    """未全选字段时点通过，应弹提示而不 emit case_approved。"""
    from unittest.mock import patch
    from video_tagging_assistant.gui.review_tab import ReviewTab

    tab = ReviewTab(_CONFIG, _TAG_OPTIONS)
    manifests = [_make_manifest("case_A_0001")]
    tab.load_cases(manifests, {"case_A_0001": {
        "安装方式": "手持", "运动模式": "行走",
        "运镜方式": "推U摇", "光源": "正常",
        "画面特征": ["边缘特征 强弱"], "影像表达": ["风景录像"],
    }})

    approved_signals = []
    tab.case_approved.connect(lambda m, t: approved_signals.append((m, t)))

    with patch("PyQt5.QtWidgets.QMessageBox.warning") as mock_warn:
        tab._pass_btn.click()

    # 没有全选，应弹提示，不应 emit
    mock_warn.assert_called_once()
    assert approved_signals == []


def test_review_tab_approve_with_all_fields_emits_case_approved():
    from video_tagging_assistant.gui.review_tab import ReviewTab
    from video_tagging_assistant.excel_workbook import TagResult

    tab = ReviewTab(_CONFIG, _TAG_OPTIONS)
    manifests = [_make_manifest("case_A_0001")]
    tab.load_cases(manifests, {"case_A_0001": {
        "安装方式": "手持", "运动模式": "行走",
        "运镜方式": "推U摇", "光源": "正常",
        "画面特征": ["边缘特征 强弱"], "影像表达": ["风景录像"],
    }})

    approved_signals = []
    tab.case_approved.connect(lambda m, t: approved_signals.append((m, t)))

    # 选中所有必选字段的第一个选项
    for group in tab._groups.values():
        buttons = group.buttons()
        if buttons:
            buttons[0].setChecked(True)

    tab._pass_btn.click()

    assert len(approved_signals) == 1
    manifest, tag_result = approved_signals[0]
    assert manifest.case_id == "case_A_0001"
    assert isinstance(tag_result, TagResult)
    assert tag_result.review_status == "审核通过"
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
pytest tests/test_gui_review_tab.py -v
```

期望输出：`FAILED` — `ModuleNotFoundError: No module named 'video_tagging_assistant.gui.review_tab'`

- [ ] **Step 3: 创建 video_tagging_assistant/gui/review_tab.py**

```python
"""Tab2 审核：逐 case 展示 AI 打标结果，人工选择字段后写回工作簿。

字段分两类：
  单选字段（安装方式/运动模式/运镜方式/光源）：显示 tag_options 中全部候选项，不预选。
  多选字段（画面特征/影像表达）：只显示 AI 建议的候选项，人工从中选一个。

操作：
  通过：校验所有字段已选 → 构造 TagResult → emit case_approved → 显示下一 case
  跳过：不写回，不加入队列，直接跳到下一 case
"""
import subprocess
from pathlib import Path

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QButtonGroup,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from video_tagging_assistant.excel_workbook import TagResult

# 字段名 → TagResult 属性名映射
_FIELD_ATTR = {
    "安装方式": "install_method",
    "运动模式": "motion_mode",
    "运镜方式": "camera_move",
    "光源": "light_source",
    "画面特征": "image_feature",
    "影像表达": "image_expression",
}

_SINGLE_FIELDS = ["安装方式", "运动模式", "运镜方式", "光源"]
_MULTI_FIELDS = ["画面特征", "影像表达"]


class ReviewTab(QWidget):
    """Tab2：逐 case 审核面板。"""

    case_approved = pyqtSignal(object, object)  # (CaseManifest, TagResult)

    def __init__(self, config: dict, tag_options: dict, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._tag_options = tag_options
        self._manifests: list = []
        self._tagging_results: dict = {}
        self._current_index: int = 0
        self._groups: dict[str, QButtonGroup] = {}
        self._setup_ui()

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        outer = QVBoxLayout(self)

        # 进度 + case 信息行
        info_row = QHBoxLayout()
        self._progress_label = QLabel("0/0")
        self._case_label = QLabel("—")
        self._preview_btn = QPushButton("▶ PotPlayer 预览")
        info_row.addWidget(self._progress_label)
        info_row.addWidget(self._case_label, stretch=1)
        info_row.addWidget(self._preview_btn)
        outer.addLayout(info_row)

        # AI 原始返回（参考）
        self._ai_label = QLabel("AI 原始返回：（未加载）")
        self._ai_label.setWordWrap(True)
        outer.addWidget(self._ai_label)

        # 字段选择区域（可滚动）
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        fields_widget = QWidget()
        self._fields_layout = QFormLayout(fields_widget)
        scroll.setWidget(fields_widget)
        outer.addWidget(scroll, stretch=1)

        # 备注
        note_row = QHBoxLayout()
        note_row.addWidget(QLabel("备注:"))
        self._note_edit = QLineEdit()
        note_row.addWidget(self._note_edit, stretch=1)
        outer.addLayout(note_row)

        # 通过 / 跳过
        btn_row = QHBoxLayout()
        self._pass_btn = QPushButton("✓ 通过")
        self._skip_btn = QPushButton("→ 跳过")
        btn_row.addWidget(self._pass_btn)
        btn_row.addWidget(self._skip_btn)
        btn_row.addStretch()
        outer.addLayout(btn_row)

        self._preview_btn.clicked.connect(self._open_potplayer)
        self._pass_btn.clicked.connect(self._handle_pass)
        self._skip_btn.clicked.connect(self._handle_skip)

    def _rebuild_field_buttons(self, ai_result: dict) -> None:
        """根据当前 case 的 AI 结果重建字段选择区域。"""
        # 清空旧内容
        while self._fields_layout.rowCount() > 0:
            self._fields_layout.removeRow(0)
        self._groups.clear()

        # 单选字段：显示全部候选项
        for field in _SINGLE_FIELDS:
            options = self._tag_options.get(field, [])
            group = QButtonGroup(self)
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            for opt in options:
                rb = QRadioButton(opt)
                group.addButton(rb)
                row_layout.addWidget(rb)
            row_layout.addStretch()
            self._groups[field] = group
            self._fields_layout.addRow(f"{field}：", row_widget)

        # 多选字段：只显示 AI 建议的候选项
        for field in _MULTI_FIELDS:
            ai_suggestions = ai_result.get(field, [])
            if isinstance(ai_suggestions, str):
                ai_suggestions = [ai_suggestions]
            options = ai_suggestions if ai_suggestions else self._tag_options.get(field, [])
            group = QButtonGroup(self)
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            for opt in options:
                rb = QRadioButton(opt)
                group.addButton(rb)
                row_layout.addWidget(rb)
            row_layout.addStretch()
            self._groups[field] = group
            label = f"{field}（AI 建议，选一）："
            self._fields_layout.addRow(label, row_widget)

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def load_cases(self, cases: list, tagging_results: dict) -> None:
        """由 MainWindow 在打标完成后调用，初始化审核队列。"""
        self._manifests = cases
        self._tagging_results = tagging_results
        self._current_index = 0
        self._show_case(0)

    # ------------------------------------------------------------------
    # 内部导航
    # ------------------------------------------------------------------

    def _show_case(self, index: int) -> None:
        if not self._manifests or index >= len(self._manifests):
            self._progress_label.setText(f"{index}/{len(self._manifests)}")
            self._case_label.setText("全部审核完毕")
            return

        manifest = self._manifests[index]
        ai_result = self._tagging_results.get(manifest.case_id, {})

        self._progress_label.setText(f"{index + 1}/{len(self._manifests)}")
        self._case_label.setText(f"{manifest.case_id}   {manifest.vs_normal_path.name}")
        self._note_edit.clear()

        # 构建 AI 原始返回摘要
        lines = []
        for k, v in ai_result.items():
            if isinstance(v, list):
                lines.append(f"{k}: {', '.join(v)}")
            else:
                lines.append(f"{k}: {v}")
        self._ai_label.setText("AI 原始返回：" + " | ".join(lines))

        self._rebuild_field_buttons(ai_result)

    def _advance(self) -> None:
        self._current_index += 1
        self._show_case(self._current_index)

    # ------------------------------------------------------------------
    # 按钮处理
    # ------------------------------------------------------------------

    def _collect_selections(self) -> dict[str, str] | None:
        """收集当前所有字段的选中值，任一字段未选则返回 None。"""
        selections = {}
        for field in list(_SINGLE_FIELDS) + list(_MULTI_FIELDS):
            group = self._groups.get(field)
            if group is None:
                continue
            checked = group.checkedButton()
            if checked is None:
                return None
            selections[field] = checked.text()
        return selections

    def _handle_pass(self) -> None:
        selections = self._collect_selections()
        if selections is None:
            QMessageBox.warning(self, "字段未完整", "请选择所有字段后再点击通过。")
            return

        manifest = self._manifests[self._current_index]
        tag_result = TagResult(
            install_method=selections.get("安装方式", ""),
            motion_mode=selections.get("运动模式", ""),
            camera_move=selections.get("运镜方式", ""),
            light_source=selections.get("光源", ""),
            image_feature=selections.get("画面特征", ""),
            image_expression=selections.get("影像表达", ""),
            review_status="审核通过",
        )
        self.case_approved.emit(manifest, tag_result)
        self._advance()

    def _handle_skip(self) -> None:
        self._advance()

    def _open_potplayer(self) -> None:
        if not self._manifests or self._current_index >= len(self._manifests):
            return
        manifest = self._manifests[self._current_index]
        potplayer = self._config.get("potplayer_exe", "")
        dji_dir = Path(self._config.get("dji_nomal_dir", ""))
        video_path = dji_dir / manifest.vs_normal_path.name

        if not potplayer or not Path(potplayer).exists():
            QMessageBox.warning(
                self, "播放器未配置",
                "请在 configs/config.json 中配置 potplayer_exe 路径。"
            )
            return
        subprocess.Popen([potplayer, str(video_path)])
```

- [ ] **Step 4: 运行测试，确认全部通过**

```bash
pytest tests/test_gui_review_tab.py -v
```

期望输出：`5 passed`

- [ ] **Step 5: Commit**

```bash
git add video_tagging_assistant/gui/review_tab.py tests/test_gui_review_tab.py
git commit -m "$(cat <<'EOF'
feat: add ReviewTab — field-by-field approval with AI suggestions
EOF
)"
```

---

## Task 8: execution_tab.py

**Files:**
- Create: `video_tagging_assistant/gui/execution_tab.py`
- Test: `tests/test_gui_execution_tab.py`

- [ ] **Step 1: 写失败测试，创建 tests/test_gui_execution_tab.py**

```python
from pathlib import Path
from unittest.mock import MagicMock

from PyQt5.QtWidgets import QApplication

_APP = QApplication.instance() or QApplication([])


def _make_manifest(case_id: str = "case_A_0078"):
    from video_tagging_assistant.pipeline_models import CaseManifest
    return CaseManifest(
        case_id=case_id,
        row_index=2,
        created_date="20260422",
        mode="OV50H40_Action5Pro_DCG HDR",
        raw_path=Path("/mnt/117"),
        vs_normal_path=Path("DJI_0001.MP4"),
        vs_night_path=Path("DJI_0021.MP4"),
        local_case_root=Path("/tmp/cases"),
        server_case_dir=Path("/tmp/server/case"),
        remark="",
    )


def _make_tab():
    from video_tagging_assistant.gui.execution_tab import ExecutionTab
    mock_worker = MagicMock()
    mock_worker.status_changed = MagicMock()
    mock_worker.status_changed.connect = MagicMock()
    return ExecutionTab(mock_worker), mock_worker


def test_execution_tab_instantiates():
    from video_tagging_assistant.gui.execution_tab import ExecutionTab
    tab, _ = _make_tab()
    assert tab is not None


def test_add_case_appends_row_to_queue_list():
    tab, mock_worker = _make_tab()
    manifest = _make_manifest("case_A_0001")
    tab.add_case(manifest)
    assert tab._queue_list.count() == 1
    assert "case_A_0001" in tab._queue_list.item(0).text()


def test_add_case_calls_worker_enqueue():
    tab, mock_worker = _make_tab()
    manifest = _make_manifest("case_A_0001")
    tab.add_case(manifest)
    mock_worker.enqueue.assert_called_once_with(manifest)


def test_on_status_changed_updates_item_text():
    tab, _ = _make_tab()
    manifest = _make_manifest("case_A_0078")
    tab.add_case(manifest)

    tab.on_status_changed("case_A_0078", "pull", "started", "")
    text = tab._queue_list.item(0).text()
    assert "pull" in text.lower() or "进行中" in text or "●" in text

    tab.on_status_changed("case_A_0078", "pull", "completed", "")
    tab.on_status_changed("case_A_0078", "move", "completed", "")
    tab.on_status_changed("case_A_0078", "upload", "completed", "")
    final_text = tab._queue_list.item(0).text()
    assert "✓" in final_text or "完成" in final_text


def test_on_status_changed_appends_to_log():
    tab, _ = _make_tab()
    manifest = _make_manifest("case_A_0078")
    tab.add_case(manifest)

    tab.on_status_changed("case_A_0078", "pull", "started", "")
    log_text = tab._log_panel.toPlainText()
    assert "case_A_0078" in log_text
    assert "pull" in log_text


def test_failed_status_shows_retry_button():
    tab, _ = _make_tab()
    manifest = _make_manifest("case_A_0078")
    tab.add_case(manifest)

    tab.on_status_changed("case_A_0078", "pull", "failed", "adb error")

    item_text = tab._queue_list.item(0).text()
    assert "✗" in item_text or "失败" in item_text
    # 确认重试按钮被附加
    assert "case_A_0078" in tab._retry_buttons
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
pytest tests/test_gui_execution_tab.py -v
```

期望输出：`FAILED` — `ModuleNotFoundError: No module named 'video_tagging_assistant.gui.execution_tab'`

- [ ] **Step 3: 创建 video_tagging_assistant/gui/execution_tab.py**

```python
"""Tab3 执行队列：展示每个 case 的 pull→move→upload 进度，支持失败重试。

add_case(manifest)：
    1. 在 _queue_list 追加「待执行」行
    2. 调用 worker.enqueue(manifest)

on_status_changed(case_id, step, status, message)：
    - 更新对应行的状态图标（● 进行中 / ✓ 完成 / ✗ 失败）
    - 追加日志行（时间戳 + case_id + step + status）
    - 若 status == "failed"：在行末显示「重试」按钮，重试时重新 enqueue
"""
from datetime import datetime

from PyQt5.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class ExecutionTab(QWidget):
    """Tab3：串行执行队列 + 实时日志面板。"""

    def __init__(self, worker, parent=None) -> None:
        super().__init__(parent)
        self._worker = worker
        self._manifests: dict = {}     # case_id → CaseManifest
        self._retry_buttons: dict = {} # case_id → QPushButton
        self._setup_ui()

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("执行队列："))
        self._queue_list = QListWidget()
        layout.addWidget(self._queue_list)

        layout.addWidget(QLabel("执行日志："))
        self._log_panel = QTextEdit()
        self._log_panel.setReadOnly(True)
        layout.addWidget(self._log_panel)

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def add_case(self, manifest) -> None:
        """加入队列列表并通知 worker。"""
        self._manifests[manifest.case_id] = manifest
        item = QListWidgetItem(f"○ {manifest.case_id}  待执行")
        item.setData(256, manifest.case_id)   # Qt.UserRole = 256
        self._queue_list.addItem(item)
        self._worker.enqueue(manifest)

    def on_status_changed(
        self, case_id: str, step: str, status: str, message: str
    ) -> None:
        """更新队列行状态；追加日志；失败时显示重试按钮。"""
        self._append_log(case_id, step, status, message)
        item = self._find_item(case_id)
        if item is None:
            return

        if status == "started":
            item.setText(f"● {case_id}  {step} 进行中…")
        elif status == "completed":
            # 仅当 upload completed 时才标记为全部完成
            if step == "upload":
                item.setText(f"✓ {case_id}  已完成")
            else:
                item.setText(f"● {case_id}  {step} 完成，等待下一步…")
        elif status == "failed":
            item.setText(f"✗ {case_id}  失败: {step} — {message}")
            self._add_retry_button(case_id)

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _find_item(self, case_id: str):
        for i in range(self._queue_list.count()):
            item = self._queue_list.item(i)
            if item.data(256) == case_id:
                return item
        return None

    def _append_log(self, case_id: str, step: str, status: str, message: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        msg = f"{ts}  {case_id}  {step}  {status}"
        if message:
            msg += f"  —  {message}"
        self._log_panel.append(msg)

    def _add_retry_button(self, case_id: str) -> None:
        if case_id in self._retry_buttons:
            return
        btn = QPushButton(f"重试 {case_id}")
        self._retry_buttons[case_id] = btn
        btn.clicked.connect(lambda: self._retry(case_id))
        # 将重试按钮插入日志面板下方（简单追加到布局）
        self.layout().addWidget(btn)

    def _retry(self, case_id: str) -> None:
        manifest = self._manifests.get(case_id)
        if manifest is None:
            return
        item = self._find_item(case_id)
        if item:
            item.setText(f"○ {case_id}  重试中…")
        self._worker.enqueue(manifest)
        # 移除重试按钮
        btn = self._retry_buttons.pop(case_id, None)
        if btn:
            btn.hide()
            btn.deleteLater()
```

- [ ] **Step 4: 运行测试，确认全部通过**

```bash
pytest tests/test_gui_execution_tab.py -v
```

期望输出：`6 passed`

- [ ] **Step 5: Commit**

```bash
git add video_tagging_assistant/gui/execution_tab.py tests/test_gui_execution_tab.py
git commit -m "$(cat <<'EOF'
feat: add ExecutionTab — queue list + live log + retry on failure
EOF
)"
```

---

## Task 9: 替换 app.py 入口

**Files:**
- Modify: `video_tagging_assistant/gui/app.py`
- Test: `tests/test_gui_smoke.py`（在文件末尾新增测试，不删除已有测试）

- [ ] **Step 1: 在 tests/test_gui_smoke.py 末尾追加新 app.py 的失败测试**

```python
# ── 以下测试验证新 launch_case_pipeline_gui (Task 9) ─────────────────────────


def test_new_launch_loads_config_and_tag_options(monkeypatch, tmp_path: Path):
    """新 launch 函数加载 config.json 和 tag_options.json 并传给 MainWindow。"""
    import json
    from video_tagging_assistant.gui import app as gui_app

    config_data = {
        "workbook_path": str(tmp_path / "records.xlsx"),
        "mode": "OV50H40_Action5Pro_DCG HDR",
        "adb_exe": "adb.exe",
        "dut_root": "/mnt",
        "local_case_root": str(tmp_path),
        "server_upload_root": str(tmp_path / "server"),
        "intermediate_dir": str(tmp_path / "intermediate"),
        "provider": {"name": "mock", "model": "mock-model"},
        "prompt_template": {"system": "describe"},
    }
    tag_options_data = {
        "安装方式": ["手持"],
        "运动模式": ["行走"],
        "运镜方式": ["推U摇"],
        "光源": ["正常"],
        "画面特征": ["边缘"],
        "影像表达": ["风景录像"],
    }
    (tmp_path / "config.json").write_text(json.dumps(config_data), encoding="utf-8")
    (tmp_path / "tag_options.json").write_text(
        json.dumps(tag_options_data), encoding="utf-8"
    )

    captured = {}

    class FakeMainWindow:
        def __init__(self, config, tag_options):
            captured["config"] = config
            captured["tag_options"] = tag_options

        def show(self):
            captured["shown"] = True

    class FakeApp:
        @staticmethod
        def instance():
            return None

        def __init__(self, argv):
            pass

        def exec_(self):
            return 0

    monkeypatch.setattr(gui_app, "QApplication", FakeApp)
    monkeypatch.setattr(gui_app, "MainWindow", FakeMainWindow)
    monkeypatch.setattr(
        gui_app,
        "_CONFIG_PATH",
        tmp_path / "config.json",
    )
    monkeypatch.setattr(
        gui_app,
        "_TAG_OPTIONS_PATH",
        tmp_path / "tag_options.json",
    )

    result = gui_app.launch_case_pipeline_gui()

    assert captured["config"]["mode"] == "OV50H40_Action5Pro_DCG HDR"
    assert captured["tag_options"]["安装方式"] == ["手持"]
    assert captured.get("shown") is True
    assert result == 0
```

- [ ] **Step 2: 运行新增测试，确认失败**

```bash
pytest tests/test_gui_smoke.py::test_new_launch_loads_config_and_tag_options -v
```

期望输出：`FAILED` — `AttributeError: module ... has no attribute 'MainWindow'`（或 `_CONFIG_PATH`）

- [ ] **Step 3: 完整重写 video_tagging_assistant/gui/app.py**

保留 `launch_case_pipeline_gui(workbook_path=None)` 函数签名以兼容 cli.py；其余内容完全重写：

```python
"""GUI 入口：加载配置文件，启动三 Tab 主窗口。

cli.py 通过 from video_tagging_assistant.gui.app import launch_case_pipeline_gui
调用本模块，函数签名保持不变。

模块级常量 _CONFIG_PATH / _TAG_OPTIONS_PATH 方便测试时通过 monkeypatch 替换。
"""
import json
from pathlib import Path

from PyQt5.QtWidgets import QApplication

from video_tagging_assistant.gui.main_window import MainWindow

_CONFIG_PATH = Path("configs/config.json")
_TAG_OPTIONS_PATH = Path("configs/tag_options.json")


def _load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def launch_case_pipeline_gui(workbook_path: str | None = None) -> int:
    """启动 GUI 流水线主窗口。

    Args:
        workbook_path: 可选，覆盖 config.json 中的 workbook_path。

    Returns:
        QApplication.exec_() 返回值（0 = 正常退出）。
    """
    config = _load_json(_CONFIG_PATH)
    tag_options = _load_json(_TAG_OPTIONS_PATH)

    if workbook_path is not None:
        config["workbook_path"] = workbook_path

    app = QApplication.instance() or QApplication([])
    window = MainWindow(config=config, tag_options=tag_options)
    window.show()
    return app.exec_()


# ── 保留供 cli.py 内部 build_provider_from_config 调用 ──────────────────────

def build_provider_from_config(config: dict):
    """根据 config["provider"] 构造 AI provider 实例。"""
    from video_tagging_assistant.providers.mock_provider import MockVideoTagProvider
    from video_tagging_assistant.providers.openai_compatible import OpenAICompatibleVideoTagProvider
    from video_tagging_assistant.providers.qwen_dashscope_provider import QwenDashScopeVideoTagProvider

    provider_config = config.get("provider", {})
    name = provider_config.get("name", "mock")
    if name == "mock":
        return MockVideoTagProvider(model=provider_config.get("model", "mock-model"))
    if name == "openai_compatible":
        return OpenAICompatibleVideoTagProvider(
            base_url=provider_config["base_url"],
            api_key_env=provider_config["api_key_env"],
            model=provider_config["model"],
        )
    if name == "qwen_dashscope":
        return QwenDashScopeVideoTagProvider(
            base_url=provider_config["base_url"],
            api_key_env=provider_config["api_key_env"],
            model=provider_config["model"],
            fps=provider_config.get("fps", 2),
            api_key=provider_config.get("api_key", ""),
        )
    raise ValueError(f"Unsupported provider: {name}")
```

- [ ] **Step 4: 运行新增测试确认通过，再运行全量测试检查回归**

```bash
pytest tests/test_gui_smoke.py::test_new_launch_loads_config_and_tag_options -v
```

期望输出：`1 passed`

```bash
pytest tests/test_gui_smoke.py -v --tb=short 2>&1 | tail -20
```

注意：旧 smoke 测试依赖 `PipelineMainWindow`，它仍在原位（Task 5 只添加了 `MainWindow`，并未删除 `PipelineMainWindow`）。若旧测试因 import 变动而报错，在此步骤修复。

- [ ] **Step 5: Commit**

```bash
git add video_tagging_assistant/gui/app.py tests/test_gui_smoke.py
git commit -m "$(cat <<'EOF'
feat: rewrite app.py — load config/tag_options, launch MainWindow
EOF
)"
```

---

*计划完成。共 9 个 Task，覆盖配置新增、后端函数 TDD、ExecutionWorker TDD、五个 GUI 模块实现及测试。*
