# GUI Local Upload Simulation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a config-driven local upload simulation mode to the GUI case pipeline and correct the queue source sheet to `获取列表`.

**Architecture:** Keep `PipelineController` unchanged as a state machine with injected runners. Extend `video_tagging_assistant/gui/app.py` to read the new `gui_pipeline` settings, build an upload runner that either keeps the real `server_case_dir` or rewrites it to a local mirror path, and continue passing that runner into the controller. Also correct the scan source sheet default and config value to `获取列表`.

**Tech Stack:** Python 3.8, pathlib, shutil-based upload worker, JSON config loading, pytest, existing GUI/controller modules

---

## File Structure

### Existing files to modify

- `configs/config.json`
  - Change `gui_pipeline.source_sheet` to `获取列表` and add `local_upload_enabled` / `local_upload_root`.
- `video_tagging_assistant/gui/app.py`
  - Read the new config keys, validate them, and build a wrapped upload runner for offline local upload simulation.
- `tests/test_gui_smoke.py`
  - Add tests for source sheet selection and config-driven local upload target rewriting.

### Existing files to read while implementing

- `video_tagging_assistant/upload_worker.py`
  - Confirm the upload worker interface and existing copy semantics.
- `video_tagging_assistant/pipeline_controller.py`
  - Confirm the upload runner injection point stays unchanged.
- `video_tagging_assistant/case_task_factory.py`
  - Confirm how `server_case_dir` is currently derived for execution.
- `docs/superpowers/specs/2026-04-29-gui-local-upload-simulation-design.md`
  - Source of truth for scope, runtime behavior, and non-goals.

### New files to create

- None required.

---

### Task 1: Add config keys and a failing source-sheet test

**Files:**
- Modify: `configs/config.json`
- Modify: `tests/test_gui_smoke.py`

- [ ] **Step 1: Write the failing source-sheet test**

```python
def test_launch_case_pipeline_gui_uses_get_list_source_sheet(monkeypatch, tmp_path: Path):
    workbook_path = tmp_path / "records.xlsx"
    workbook_path.write_text("placeholder", encoding="utf-8")
    captured = {}
    calls = {}

    class FakeWindow:
        def __init__(self, scan_cases=None, **kwargs):
            captured["scan_cases"] = scan_cases

        def show(self):
            pass

    class FakeQApplication:
        @staticmethod
        def instance():
            return None

        def __init__(self, argv):
            pass

        def exec_(self):
            return 0

    monkeypatch.setattr(gui_app, "PipelineMainWindow", FakeWindow)
    monkeypatch.setattr(gui_app, "QApplication", FakeQApplication)
    monkeypatch.setattr(
        gui_app,
        "load_config",
        lambda path: {
            "input_dir": "videos",
            "output_dir": "output",
            "compression": {},
            "provider": {"name": "mock", "model": "mock-model"},
            "prompt_template": {"system": "describe"},
            "gui_pipeline": {
                "source_sheet": "获取列表",
                "review_sheet": "审核结果",
            },
        },
    )
    monkeypatch.setattr(gui_app, "ensure_pipeline_columns", lambda workbook, source_sheet: calls.update({"source_sheet": source_sheet}))
    monkeypatch.setattr(
        gui_app,
        "build_case_manifests",
        lambda workbook, source_sheet, allowed_statuses, local_root, server_root, mode: calls.update({"manifest_source_sheet": source_sheet}) or [],
    )

    gui_app.launch_case_pipeline_gui(workbook_path=str(workbook_path))
    captured["scan_cases"]()

    assert calls["source_sheet"] == "获取列表"
    assert calls["manifest_source_sheet"] == "获取列表"
```

- [ ] **Step 2: Run test to verify it fails if the config/default still points at `创建记录`**

Run: `pytest tests/test_gui_smoke.py::test_launch_case_pipeline_gui_uses_get_list_source_sheet -v`
Expected: FAIL until the config/default is corrected to `获取列表`.

- [ ] **Step 3: Update the real config file**

```json
  "gui_pipeline": {
    "source_sheet": "获取列表",
    "review_sheet": "审核结果",
    "mode": "OV50H40_Action5Pro_DCG HDR",
    "allowed_statuses": ["", "queued", "failed"],
    "local_root": "cases",
    "server_root": "server_cases",
    "cache_root": "artifacts/cache",
    "tagging_output_root": "artifacts/gui_pipeline",
    "tagging_input_mode": "excel",
    "tagging_input_root": "videos",
    "local_upload_enabled": false,
    "local_upload_root": "mock_server_cases"
  }
```

- [ ] **Step 4: Run the same test again**

Run: `pytest tests/test_gui_smoke.py::test_launch_case_pipeline_gui_uses_get_list_source_sheet -v`
Expected: PASS once the source-sheet wiring reads the corrected config value.

- [ ] **Step 5: Commit**

```bash
git add configs/config.json tests/test_gui_smoke.py
git commit -m "test: cover gui source sheet selection"
```

### Task 2: Add a failing local-upload runner test

**Files:**
- Modify: `tests/test_gui_smoke.py`
- Modify: `video_tagging_assistant/gui/app.py`

- [ ] **Step 1: Write the failing local-upload target rewrite test**

```python
def test_launch_case_pipeline_gui_rewrites_upload_target_when_local_upload_enabled(monkeypatch, tmp_path: Path):
    captured = {}
    upload_calls = []

    class FakeController:
        def __init__(self, pull_runner=None, copy_runner=None, upload_runner=None, event_callback=None):
            captured["upload_runner"] = upload_runner

        def has_execution_case(self):
            return False

        def run_next_execution_case(self):
            return None

    class FakeWindow:
        def __init__(self, **kwargs):
            pass

        def show(self):
            pass

    class FakeQApplication:
        @staticmethod
        def instance():
            return None

        def __init__(self, argv):
            pass

        def exec_(self):
            return 0

    monkeypatch.setattr(gui_app, "PipelineController", FakeController)
    monkeypatch.setattr(gui_app, "PipelineMainWindow", FakeWindow)
    monkeypatch.setattr(gui_app, "QApplication", FakeQApplication)
    monkeypatch.setattr(
        gui_app,
        "load_config",
        lambda path: {
            "input_dir": "videos",
            "output_dir": "output",
            "compression": {},
            "provider": {"name": "mock", "model": "mock-model"},
            "prompt_template": {"system": "describe"},
            "gui_pipeline": {
                "source_sheet": "获取列表",
                "review_sheet": "审核结果",
                "local_upload_enabled": True,
                "local_upload_root": str(tmp_path / "mock_server_cases"),
            },
        },
    )
    monkeypatch.setattr(
        gui_app,
        "upload_case_directory",
        lambda case_id, local_case_dir, server_case_dir, progress_callback=None: upload_calls.append(
            (case_id, local_case_dir, server_case_dir)
        ),
    )

    gui_app.launch_case_pipeline_gui(workbook_path=str(tmp_path / "records.xlsx"))
    captured["upload_runner"](
        "case_A_0001",
        tmp_path / "cases" / "OV50H40_Action5Pro_DCG HDR" / "20260414" / "case_A_0001",
        tmp_path / "server_cases" / "OV50H40_Action5Pro_DCG HDR" / "20260414" / "case_A_0001",
    )

    assert upload_calls == [
        (
            "case_A_0001",
            tmp_path / "cases" / "OV50H40_Action5Pro_DCG HDR" / "20260414" / "case_A_0001",
            tmp_path / "mock_server_cases" / "OV50H40_Action5Pro_DCG HDR" / "20260414" / "case_A_0001",
        )
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_gui_smoke.py::test_launch_case_pipeline_gui_rewrites_upload_target_when_local_upload_enabled -v`
Expected: FAIL because `launch_case_pipeline_gui()` still constructs `PipelineController()` without a wrapped upload runner.

- [ ] **Step 3: Implement the wrapped upload runner in `video_tagging_assistant/gui/app.py`**

```python
from video_tagging_assistant.upload_worker import upload_case_directory

...
DEFAULT_SOURCE_SHEET = "获取列表"
DEFAULT_LOCAL_UPLOAD_ENABLED = False
DEFAULT_LOCAL_UPLOAD_ROOT = Path("mock_server_cases")


def _build_upload_runner(local_upload_enabled: bool, local_upload_root: Path):
    if not local_upload_enabled:
        return upload_case_directory
    if not str(local_upload_root).strip():
        raise ValueError("gui_pipeline.local_upload_root is required when local_upload_enabled is true")

    def upload_runner(case_id, local_case_dir, server_case_dir, progress_callback=None):
        target_dir = local_upload_root / server_case_dir.parent.name / server_case_dir.name
        if len(server_case_dir.parts) >= 3:
            target_dir = local_upload_root / server_case_dir.parts[-3] / server_case_dir.parts[-2] / server_case_dir.parts[-1]
        return upload_case_directory(case_id, local_case_dir, target_dir, progress_callback=progress_callback)

    return upload_runner


def launch_case_pipeline_gui(workbook_path=None):
    ...
    local_upload_enabled = bool(gui_pipeline.get("local_upload_enabled", DEFAULT_LOCAL_UPLOAD_ENABLED))
    local_upload_root = Path(gui_pipeline.get("local_upload_root", str(DEFAULT_LOCAL_UPLOAD_ROOT)))
    upload_runner = _build_upload_runner(local_upload_enabled, local_upload_root)
    controller = PipelineController(upload_runner=upload_runner)
    ...
```

- [ ] **Step 4: Run the two focused tests**

Run: `pytest tests/test_gui_smoke.py::test_launch_case_pipeline_gui_uses_get_list_source_sheet tests/test_gui_smoke.py::test_launch_case_pipeline_gui_rewrites_upload_target_when_local_upload_enabled -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_gui_smoke.py video_tagging_assistant/gui/app.py configs/config.json
git commit -m "feat: add local upload simulation for gui"
```

### Task 3: Add default-mode and invalid-config coverage

**Files:**
- Modify: `tests/test_gui_smoke.py`
- Modify: `video_tagging_assistant/gui/app.py`

- [ ] **Step 1: Add the default upload target passthrough test**

```python
def test_launch_case_pipeline_gui_keeps_server_upload_target_when_local_upload_disabled(monkeypatch, tmp_path: Path):
    captured = {}
    upload_calls = []

    class FakeController:
        def __init__(self, pull_runner=None, copy_runner=None, upload_runner=None, event_callback=None):
            captured["upload_runner"] = upload_runner

        def has_execution_case(self):
            return False

        def run_next_execution_case(self):
            return None

    class FakeWindow:
        def __init__(self, **kwargs):
            pass

        def show(self):
            pass

    class FakeQApplication:
        @staticmethod
        def instance():
            return None

        def __init__(self, argv):
            pass

        def exec_(self):
            return 0

    monkeypatch.setattr(gui_app, "PipelineController", FakeController)
    monkeypatch.setattr(gui_app, "PipelineMainWindow", FakeWindow)
    monkeypatch.setattr(gui_app, "QApplication", FakeQApplication)
    monkeypatch.setattr(
        gui_app,
        "load_config",
        lambda path: {
            "input_dir": "videos",
            "output_dir": "output",
            "compression": {},
            "provider": {"name": "mock", "model": "mock-model"},
            "prompt_template": {"system": "describe"},
            "gui_pipeline": {
                "source_sheet": "获取列表",
                "review_sheet": "审核结果",
                "local_upload_enabled": False,
                "local_upload_root": str(tmp_path / "mock_server_cases"),
            },
        },
    )
    monkeypatch.setattr(
        gui_app,
        "upload_case_directory",
        lambda case_id, local_case_dir, server_case_dir, progress_callback=None: upload_calls.append(
            (case_id, local_case_dir, server_case_dir)
        ),
    )

    gui_app.launch_case_pipeline_gui(workbook_path=str(tmp_path / "records.xlsx"))
    original_target = tmp_path / "server_cases" / "OV50H40_Action5Pro_DCG HDR" / "20260414" / "case_A_0001"
    captured["upload_runner"](
        "case_A_0001",
        tmp_path / "cases" / "OV50H40_Action5Pro_DCG HDR" / "20260414" / "case_A_0001",
        original_target,
    )

    assert upload_calls == [
        (
            "case_A_0001",
            tmp_path / "cases" / "OV50H40_Action5Pro_DCG HDR" / "20260414" / "case_A_0001",
            original_target,
        )
    ]
```

- [ ] **Step 2: Add the invalid-config test**

```python
import pytest


def test_launch_case_pipeline_gui_requires_local_upload_root_when_local_upload_enabled(monkeypatch, tmp_path: Path):
    class FakeWindow:
        def __init__(self, **kwargs):
            pass

        def show(self):
            pass

    class FakeQApplication:
        @staticmethod
        def instance():
            return None

        def __init__(self, argv):
            pass

        def exec_(self):
            return 0

    monkeypatch.setattr(gui_app, "PipelineMainWindow", FakeWindow)
    monkeypatch.setattr(gui_app, "QApplication", FakeQApplication)
    monkeypatch.setattr(
        gui_app,
        "load_config",
        lambda path: {
            "input_dir": "videos",
            "output_dir": "output",
            "compression": {},
            "provider": {"name": "mock", "model": "mock-model"},
            "prompt_template": {"system": "describe"},
            "gui_pipeline": {
                "source_sheet": "获取列表",
                "review_sheet": "审核结果",
                "local_upload_enabled": True,
                "local_upload_root": "",
            },
        },
    )

    with pytest.raises(ValueError) as exc:
        gui_app.launch_case_pipeline_gui(workbook_path=str(tmp_path / "records.xlsx"))

    assert "local_upload_root" in str(exc.value)
```

- [ ] **Step 3: Run the three focused tests**

Run: `pytest tests/test_gui_smoke.py::test_launch_case_pipeline_gui_keeps_server_upload_target_when_local_upload_disabled tests/test_gui_smoke.py::test_launch_case_pipeline_gui_rewrites_upload_target_when_local_upload_enabled tests/test_gui_smoke.py::test_launch_case_pipeline_gui_requires_local_upload_root_when_local_upload_enabled -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_gui_smoke.py video_tagging_assistant/gui/app.py
 git commit -m "test: cover gui local upload config"
```

### Task 4: Run focused regression for GUI upload simulation

**Files:**
- Test: `tests/test_gui_smoke.py`
- Test: `tests/test_pipeline_controller.py`
- Test: `tests/test_case_ingest_cli_config.py`
- Test: `tests/test_excel_workbook_pipeline.py`

- [ ] **Step 1: Run the GUI smoke suite**

Run: `pytest tests/test_gui_smoke.py -v`
Expected: PASS, including source-sheet selection, local upload target rewriting, and existing tagging-input tests.

- [ ] **Step 2: Run related regression suites**

Run: `pytest tests/test_pipeline_controller.py tests/test_case_ingest_cli_config.py tests/test_excel_workbook_pipeline.py -v`
Expected: PASS with no regressions in controller staging, GUI command parsing, or workbook manifest loading.

- [ ] **Step 3: Commit verification-complete state**

```bash
git add configs/config.json tests/test_gui_smoke.py video_tagging_assistant/gui/app.py
git commit -m "test: verify gui local upload simulation"
```

## Self-Review

### Spec coverage

- `gui_pipeline` gains `local_upload_enabled` and `local_upload_root`: covered by Task 1.
- `source_sheet` corrected to `获取列表`: covered by Task 1.
- `local_upload_enabled = true` rewrites upload target to a local mirror path: covered by Task 2.
- `local_upload_enabled = false` preserves original upload target: covered by Task 3.
- Missing `local_upload_root` fails clearly: covered by Task 3.
- Controller state machine remains ignorant of simulation mode and upload worker semantics stay intact: preserved by the app-layer runner injection in Task 2 and regression coverage in Task 4.

### Placeholder scan

- No `TODO`, `TBD`, or vague “handle appropriately” steps remain.
- Every code-changing step includes concrete code blocks.
- Every verification step includes exact pytest commands and expected outcomes.

### Type consistency

- `local_upload_enabled` and `local_upload_root` are named consistently across config, tests, and `gui/app.py`.
- The wrapped upload runner keeps the existing `upload_case_directory(case_id, local_case_dir, server_case_dir, progress_callback=None)` signature.
- `source_sheet` remains the queue-source field; only its value changes from `创建记录` to `获取列表`.
