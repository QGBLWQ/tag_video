# GUI App Assembly Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade `video_tagging_assistant/gui/app.py` from a thin window launcher into a real dependency-assembly layer that wires workbook scanning, Excel approval refresh, controller execution, and tagging bridges into the GUI by default.

**Architecture:** Keep `PipelineMainWindow` callback-driven and testable while moving default runtime assembly into `gui/app.py`. The app layer will build real `scan_cases`, `refresh_excel_reviews`, `run_execution_case`, and `start_tagging` callables around existing workbook helpers, controller logic, config loading, provider creation, and tagging service entrypoints.

**Tech Stack:** Python 3.8, PyQt5, pathlib, existing `video_tagging_assistant` modules, pytest

---

## File Structure

### Existing files to modify

- `video_tagging_assistant/gui/app.py`
  - Replace the thin launcher with real dependency assembly for workbook-driven scan, Excel review refresh, controller execution, and tagging bridges.
- `tests/test_gui_smoke.py`
  - Extend launcher coverage to verify that `launch_case_pipeline_gui()` injects real callable dependencies and routes workbook path correctly.
- `tests/test_case_ingest_cli_config.py`
  - Keep CLI regression coverage for the `case-pipeline-gui` subcommand after app-wiring changes.

### New files to create

- None. This work should fit inside the existing app module and tests.

### Existing files to read while implementing

- `video_tagging_assistant/config.py`
  - For `load_config` and case-ingest defaults.
- `video_tagging_assistant/cli.py`
  - For `build_provider_from_config` and current GUI launcher integration.
- `video_tagging_assistant/excel_workbook.py`
  - For `ensure_pipeline_columns`, `build_case_manifests`, and `load_approved_review_rows`.
- `video_tagging_assistant/pipeline_controller.py`
  - For execution queue and stage handling.
- `video_tagging_assistant/tagging_service.py`
  - For `run_batch_tagging` and `TaggingReviewRow` generation.

---

### Task 1: Wire real scan and refresh callables into the GUI launcher

**Files:**
- Modify: `video_tagging_assistant/gui/app.py`
- Test: `tests/test_gui_smoke.py`

- [ ] **Step 1: Write the failing launcher test for injected callables**

```python
from pathlib import Path

from openpyxl import Workbook

from video_tagging_assistant.gui import app as gui_app


def test_launch_case_pipeline_gui_injects_real_scan_and_refresh(monkeypatch, tmp_path: Path):
    workbook_path = tmp_path / "records.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "创建记录"
    ws.append(["序号", "文件夹名", "备注", "创建日期", "Raw存放路径", "VS_Nomal", "VS_Night", "安装方式", "运动模式"])
    ws.append([1, "case_A_0105", "场景备注", "20260428", r"E:\DV\raw", r"E:\DV\normal.MP4", r"E:\DV\night.MP4", "手持", "行走"])
    review = wb.create_sheet("审核结果")
    review.append(["文件夹名", "创建记录行号", "Raw存放路径", "视频路径", "自动简介", "自动标签", "自动画面描述", "审核结论", "人工修订简介", "人工修订标签", "审核备注", "审核人", "审核时间", "同步状态", "归档状态", "归档目标路径"])
    wb.save(workbook_path)

    captured = {}

    class FakeWindow:
        def __init__(self, workbook_path=None, scan_cases=None, refresh_excel_reviews=None, **kwargs):
            captured["workbook_path"] = workbook_path
            captured["scan_cases"] = scan_cases
            captured["refresh_excel_reviews"] = refresh_excel_reviews

        def show(self):
            captured["shown"] = True

    class FakeQApplication:
        @staticmethod
        def instance():
            return None

        def __init__(self, argv):
            pass

    monkeypatch.setattr(gui_app, "PipelineMainWindow", FakeWindow)
    monkeypatch.setattr(gui_app, "QApplication", FakeQApplication)

    gui_app.launch_case_pipeline_gui(workbook_path=str(workbook_path))

    manifests = captured["scan_cases"]()
    approved = captured["refresh_excel_reviews"]()

    assert captured["workbook_path"].endswith("records.xlsx")
    assert len(manifests) == 1
    assert manifests[0].case_id == "case_A_0105"
    assert approved == []
    assert captured["shown"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_gui_smoke.py::test_launch_case_pipeline_gui_injects_real_scan_and_refresh -v`
Expected: FAIL because `launch_case_pipeline_gui` only passes `workbook_path` and does not inject real `scan_cases` / `refresh_excel_reviews`

- [ ] **Step 3: Implement real workbook-based scan and refresh assembly**

```python
from pathlib import Path

from PyQt5.QtWidgets import QApplication

from video_tagging_assistant.excel_workbook import (
    build_case_manifests,
    ensure_pipeline_columns,
    load_approved_review_rows,
)
from video_tagging_assistant.gui.main_window import PipelineMainWindow
from video_tagging_assistant.pipeline_controller import PipelineController

DEFAULT_MODE = "OV50H40_Action5Pro_DCG HDR"
DEFAULT_SOURCE_SHEET = "创建记录"
DEFAULT_REVIEW_SHEET = "审核结果"
DEFAULT_ALLOWED_STATUSES = {"", "queued", "failed"}
DEFAULT_LOCAL_ROOT = Path("cases")
DEFAULT_SERVER_ROOT = Path("server_cases")


def launch_case_pipeline_gui(workbook_path=None):
    app = QApplication.instance() or QApplication([])
    workbook = Path(workbook_path) if workbook_path else None
    controller = PipelineController()

    def scan_cases():
        if workbook is None or not workbook.exists():
            return []
        ensure_pipeline_columns(workbook, source_sheet=DEFAULT_SOURCE_SHEET)
        return build_case_manifests(
            workbook,
            source_sheet=DEFAULT_SOURCE_SHEET,
            allowed_statuses=DEFAULT_ALLOWED_STATUSES,
            local_root=DEFAULT_LOCAL_ROOT,
            server_root=DEFAULT_SERVER_ROOT,
            mode=DEFAULT_MODE,
        )

    def refresh_excel_reviews():
        if workbook is None or not workbook.exists():
            return []
        return load_approved_review_rows(workbook, review_sheet=DEFAULT_REVIEW_SHEET)

    window = PipelineMainWindow(
        workbook_path=str(workbook) if workbook else None,
        scan_cases=scan_cases,
        refresh_excel_reviews=refresh_excel_reviews,
        controller=controller,
    )
    window.show()
    return 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_gui_smoke.py::test_launch_case_pipeline_gui_injects_real_scan_and_refresh -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_gui_smoke.py video_tagging_assistant/gui/app.py
git commit -m "feat: assemble workbook scan and refresh in gui app"
```

### Task 2: Add a real execution bridge around the controller queue

**Files:**
- Modify: `video_tagging_assistant/gui/app.py`
- Test: `tests/test_gui_smoke.py`

- [ ] **Step 1: Write the failing execution-bridge test**

```python
from pathlib import Path

from video_tagging_assistant.gui import app as gui_app


def test_launch_case_pipeline_gui_injects_execution_bridge(monkeypatch, tmp_path: Path):
    captured = {}
    execution_calls = []

    class FakeController:
        def has_execution_case(self):
            execution_calls.append("has")
            return True

        def run_next_execution_case(self):
            execution_calls.append("run")

    class FakeWindow:
        def __init__(self, run_execution_case=None, **kwargs):
            captured["run_execution_case"] = run_execution_case

        def show(self):
            pass

    class FakeQApplication:
        @staticmethod
        def instance():
            return None

        def __init__(self, argv):
            pass

    monkeypatch.setattr(gui_app, "PipelineController", lambda: FakeController())
    monkeypatch.setattr(gui_app, "PipelineMainWindow", FakeWindow)
    monkeypatch.setattr(gui_app, "QApplication", FakeQApplication)

    gui_app.launch_case_pipeline_gui(workbook_path=str(tmp_path / "records.xlsx"))
    captured["run_execution_case"]("case_A_0105")

    assert execution_calls == ["has", "run"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_gui_smoke.py::test_launch_case_pipeline_gui_injects_execution_bridge -v`
Expected: FAIL because no `run_execution_case` callable is injected yet

- [ ] **Step 3: Implement the controller execution bridge**

```python
def launch_case_pipeline_gui(workbook_path=None):
    app = QApplication.instance() or QApplication([])
    workbook = Path(workbook_path) if workbook_path else None
    controller = PipelineController()

    def run_execution_case(case_id):
        if controller.has_execution_case():
            controller.run_next_execution_case()

    window = PipelineMainWindow(
        workbook_path=str(workbook) if workbook else None,
        scan_cases=scan_cases,
        refresh_excel_reviews=refresh_excel_reviews,
        run_execution_case=run_execution_case,
        controller=controller,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_gui_smoke.py::test_launch_case_pipeline_gui_injects_execution_bridge -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_gui_smoke.py video_tagging_assistant/gui/app.py
git commit -m "feat: add gui app execution bridge"
```

### Task 3: Add a real tagging bridge using config and provider construction

**Files:**
- Modify: `video_tagging_assistant/gui/app.py`
- Test: `tests/test_gui_smoke.py`
- Test: `tests/test_case_ingest_cli_config.py`

- [ ] **Step 1: Write the failing tagging-bridge tests**

```python
from pathlib import Path

from video_tagging_assistant.gui import app as gui_app
from video_tagging_assistant.pipeline_models import CaseManifest


def test_launch_case_pipeline_gui_injects_tagging_bridge(monkeypatch, tmp_path: Path):
    captured = {}
    provider_calls = []
    tagging_calls = []

    class FakeWindow:
        def __init__(self, start_tagging=None, **kwargs):
            captured["start_tagging"] = start_tagging

        def show(self):
            pass

    class FakeQApplication:
        @staticmethod
        def instance():
            return None

        def __init__(self, argv):
            pass

    monkeypatch.setattr(gui_app, "PipelineMainWindow", FakeWindow)
    monkeypatch.setattr(gui_app, "QApplication", FakeQApplication)
    monkeypatch.setattr(gui_app, "load_config", lambda path: {"prompt_template": {"system": "describe"}, "provider": {"name": "mock", "model": "mock-model"}, "input_dir": "in", "output_dir": "out", "compression": {}})
    monkeypatch.setattr(gui_app, "build_provider_from_config", lambda config: provider_calls.append(config["provider"]) or object())
    monkeypatch.setattr(
        gui_app,
        "run_batch_tagging",
        lambda manifests, cache_root, output_root, provider, prompt_template, mode, event_callback: tagging_calls.append(
            {
                "count": len(manifests),
                "mode": mode,
                "prompt_template": prompt_template,
                "cache_root": cache_root,
                "output_root": output_root,
                "provider": provider,
            }
        )
        or [],
    )

    gui_app.launch_case_pipeline_gui(workbook_path=str(tmp_path / "records.xlsx"))

    manifest = CaseManifest(
        case_id="case_A_0105",
        row_index=2,
        created_date="20260428",
        mode="OV50H40_Action5Pro_DCG HDR",
        raw_path=tmp_path / "raw",
        vs_normal_path=tmp_path / "normal.MP4",
        vs_night_path=tmp_path / "night.MP4",
        local_case_root=tmp_path / "local" / "case_A_0105",
        server_case_dir=tmp_path / "server" / "case_A_0105",
        remark="场景备注",
        labels={"安装方式": "手持"},
    )

    captured["start_tagging"]([manifest], "fresh", lambda event: None)

    assert provider_calls[0]["name"] == "mock"
    assert tagging_calls[0]["count"] == 1
    assert tagging_calls[0]["mode"] == "fresh"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_gui_smoke.py::test_launch_case_pipeline_gui_injects_tagging_bridge -v`
Expected: FAIL because no real `start_tagging` callable is injected yet

- [ ] **Step 3: Implement the tagging bridge with config/provider assembly**

```python
from video_tagging_assistant.cli import build_provider_from_config
from video_tagging_assistant.config import load_config
from video_tagging_assistant.tagging_service import run_batch_tagging

DEFAULT_CONFIG_PATH = Path("configs/config.json")
DEFAULT_CACHE_ROOT = Path("artifacts/cache")
DEFAULT_TAGGING_OUTPUT_ROOT = Path("artifacts/gui_pipeline")


def launch_case_pipeline_gui(workbook_path=None):
    app = QApplication.instance() or QApplication([])
    workbook = Path(workbook_path) if workbook_path else None
    controller = PipelineController()

    def start_tagging(manifests, mode, event_callback):
        config = load_config(DEFAULT_CONFIG_PATH)
        provider = build_provider_from_config(config)
        return run_batch_tagging(
            manifests=manifests,
            cache_root=DEFAULT_CACHE_ROOT,
            output_root=DEFAULT_TAGGING_OUTPUT_ROOT,
            provider=provider,
            prompt_template=config["prompt_template"],
            mode=mode,
            event_callback=event_callback,
        )

    window = PipelineMainWindow(
        workbook_path=str(workbook) if workbook else None,
        scan_cases=scan_cases,
        start_tagging=start_tagging,
        refresh_excel_reviews=refresh_excel_reviews,
        run_execution_case=run_execution_case,
        controller=controller,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_gui_smoke.py::test_launch_case_pipeline_gui_injects_tagging_bridge -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_gui_smoke.py video_tagging_assistant/gui/app.py
git commit -m "feat: add gui app tagging bridge"
```

### Task 4: Run focused app-assembly verification

**Files:**
- Test: `tests/test_gui_smoke.py`
- Test: `tests/test_case_ingest_cli_config.py`

- [ ] **Step 1: Run the focused GUI app tests**

Run: `pytest tests/test_gui_smoke.py::test_launch_case_pipeline_gui_passes_workbook_path tests/test_gui_smoke.py::test_launch_case_pipeline_gui_injects_real_scan_and_refresh tests/test_gui_smoke.py::test_launch_case_pipeline_gui_injects_execution_bridge tests/test_gui_smoke.py::test_launch_case_pipeline_gui_injects_tagging_bridge -v`
Expected: PASS

- [ ] **Step 2: Run CLI regression for the GUI entrypoint**

Run: `pytest tests/test_case_ingest_cli_config.py::test_case_pipeline_gui_command_parses -v`
Expected: PASS

- [ ] **Step 3: Commit verification-complete state**

```bash
git add tests/test_gui_smoke.py tests/test_case_ingest_cli_config.py video_tagging_assistant/gui/app.py
git commit -m "test: verify gui app assembly"
```

## Self-Review

### Spec coverage

- `gui/app.py` becomes a real assembly layer: covered by Tasks 1-3.
- Real workbook-based scan and refresh: covered by Task 1.
- Real controller-backed execution bridge: covered by Task 2.
- Real config/provider-backed tagging bridge: covered by Task 3.
- `PipelineMainWindow` remains callback-driven and testable: preserved across all tasks because assembly stays in `app.py`.
- No new threading, dialog pickers, or provider UI: intentionally excluded.

### Placeholder scan

- No `TODO`, `TBD`, or vague “wire this up” steps remain.
- Every task names exact files and concrete pytest commands.
- Every implementation step contains concrete code blocks.

### Type consistency

- `scan_cases`, `refresh_excel_reviews`, `run_execution_case`, and `start_tagging` are named consistently across tasks.
- `PipelineMainWindow` consistently receives `workbook_path`, `controller`, and the four injected callables.
- Config/provider bridge uses the existing `load_config` + `build_provider_from_config` pairing consistently.
