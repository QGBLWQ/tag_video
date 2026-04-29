# GUI Tagging Input Config Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the GUI case pipeline choose tagging input videos from either Excel paths or a configured local directory, so offline testing no longer depends on UNC/company-network paths.

**Architecture:** Keep Excel scanning unchanged so `CaseManifest` still reflects workbook truth. Add the new `gui_pipeline` config keys in `configs/config.json`, then make `video_tagging_assistant/gui/app.py` resolve a runtime manifest list inside `start_tagging()` before handing it to `run_batch_tagging()`. The remapping stays in the app assembly layer and never mutates Excel data.

**Tech Stack:** Python 3.8, pathlib, dataclasses, JSON config loading, pytest, existing `video_tagging_assistant` GUI/tagging modules

---

## File Structure

### Existing files to modify

- `configs/config.json`
  - Add `gui_pipeline.tagging_input_mode` and `gui_pipeline.tagging_input_root` defaults.
- `video_tagging_assistant/gui/app.py`
  - Read the new config values, validate them, and resolve runtime manifests before calling `run_batch_tagging()`.
- `tests/test_gui_smoke.py`
  - Add focused tests for `excel` passthrough, `local_root` remapping, and missing local input errors.

### Existing files to read while implementing

- `video_tagging_assistant/pipeline_models.py`
  - Confirm `CaseManifest` shape for runtime copy/replacement.
- `video_tagging_assistant/tagging_service.py`
  - Confirm only `manifest.vs_normal_path` / `vs_night_path` need remapping before `run_batch_tagging()`.
- `docs/superpowers/specs/2026-04-29-gui-tagging-input-config-design.md`
  - Source of truth for scope and non-goals.

### New files to create

- None required.

---

### Task 1: Add tagging input config keys and a failing bridge test

**Files:**
- Modify: `configs/config.json`
- Modify: `tests/test_gui_smoke.py`

- [ ] **Step 1: Write the failing config-driven remap test**

```python
def test_launch_case_pipeline_gui_remaps_tagging_inputs_from_local_root(monkeypatch, tmp_path: Path):
    captured = {}
    provider_calls = []
    tagging_calls = []
    local_video_root = tmp_path / "videos"
    local_video_root.mkdir()
    local_normal = local_video_root / "normal.MP4"
    local_night = local_video_root / "night.MP4"
    local_normal.write_text("normal", encoding="utf-8")
    local_night.write_text("night", encoding="utf-8")

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
                "tagging_input_mode": "local_root",
                "tagging_input_root": str(local_video_root),
                "cache_root": "my_cache",
                "tagging_output_root": "my_gui_output",
            },
        },
    )
    monkeypatch.setattr(gui_app, "build_provider_from_config", lambda config: provider_calls.append(config["provider"]) or object())
    monkeypatch.setattr(
        gui_app,
        "run_batch_tagging",
        lambda manifests, cache_root, output_root, provider, prompt_template, mode, event_callback: tagging_calls.append(
            {
                "manifests": manifests,
                "cache_root": cache_root,
                "output_root": output_root,
                "mode": mode,
            }
        ) or [],
    )

    gui_app.launch_case_pipeline_gui(workbook_path=str(tmp_path / "records.xlsx"))

    manifest = CaseManifest(
        case_id="case_A_0105",
        row_index=2,
        created_date="20260428",
        mode="OV50H40_Action5Pro_DCG HDR",
        raw_path=tmp_path / "raw",
        vs_normal_path=Path(r"\\10.10.10.164\rk3668_capture\normal.MP4"),
        vs_night_path=Path(r"\\10.10.10.164\rk3668_capture\night.MP4"),
        local_case_root=tmp_path / "local" / "case_A_0105",
        server_case_dir=tmp_path / "server" / "case_A_0105",
        remark="场景备注",
        labels={"安装方式": "手持"},
    )

    captured["start_tagging"]([manifest], "fresh", lambda event: None)

    assert provider_calls == [{"name": "mock", "model": "mock-model"}]
    assert tagging_calls[0]["cache_root"] == Path("my_cache")
    assert tagging_calls[0]["output_root"] == Path("my_gui_output")
    remapped_manifest = tagging_calls[0]["manifests"][0]
    assert remapped_manifest is not manifest
    assert remapped_manifest.case_id == "case_A_0105"
    assert remapped_manifest.vs_normal_path == local_normal
    assert remapped_manifest.vs_night_path == local_night
    assert manifest.vs_normal_path == Path(r"\\10.10.10.164\rk3668_capture\normal.MP4")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_gui_smoke.py::test_launch_case_pipeline_gui_remaps_tagging_inputs_from_local_root -v`
Expected: FAIL because `start_tagging()` still forwards the original manifests without remapping.

- [ ] **Step 3: Add the new keys to the real config file**

```json
  "gui_pipeline": {
    "source_sheet": "创建记录",
    "review_sheet": "审核结果",
    "mode": "OV50H40_Action5Pro_DCG HDR",
    "allowed_statuses": ["", "queued", "failed"],
    "local_root": "cases",
    "server_root": "server_cases",
    "cache_root": "artifacts/cache",
    "tagging_output_root": "artifacts/gui_pipeline",
    "tagging_input_mode": "excel",
    "tagging_input_root": "videos"
  }
```

- [ ] **Step 4: Run the same test again**

Run: `pytest tests/test_gui_smoke.py::test_launch_case_pipeline_gui_remaps_tagging_inputs_from_local_root -v`
Expected: still FAIL, proving the remaining work is in `video_tagging_assistant/gui/app.py` rather than config shape.

- [ ] **Step 5: Commit**

```bash
git add configs/config.json tests/test_gui_smoke.py
git commit -m "test: cover gui tagging input config"
```

### Task 2: Implement runtime tagging input resolution in `gui/app.py`

**Files:**
- Modify: `video_tagging_assistant/gui/app.py`
- Modify: `tests/test_gui_smoke.py`

- [ ] **Step 1: Add a focused passthrough test for `excel` mode**

```python
def test_launch_case_pipeline_gui_keeps_excel_tagging_inputs_in_excel_mode(monkeypatch, tmp_path: Path):
    captured = {}
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
                "tagging_input_mode": "excel",
                "tagging_input_root": "ignored",
            },
        },
    )
    monkeypatch.setattr(gui_app, "build_provider_from_config", lambda config: object())
    monkeypatch.setattr(
        gui_app,
        "run_batch_tagging",
        lambda manifests, cache_root, output_root, provider, prompt_template, mode, event_callback: tagging_calls.append(manifests) or [],
    )

    gui_app.launch_case_pipeline_gui(workbook_path=str(tmp_path / "records.xlsx"))
    manifest = CaseManifest(
        case_id="case_A_0105",
        row_index=2,
        created_date="20260428",
        mode="OV50H40_Action5Pro_DCG HDR",
        raw_path=tmp_path / "raw",
        vs_normal_path=tmp_path / "excel_normal.MP4",
        vs_night_path=tmp_path / "excel_night.MP4",
        local_case_root=tmp_path / "local" / "case_A_0105",
        server_case_dir=tmp_path / "server" / "case_A_0105",
        remark="场景备注",
        labels={"安装方式": "手持"},
    )

    captured["start_tagging"]([manifest], "fresh", lambda event: None)

    assert tagging_calls == [[manifest]]
```

- [ ] **Step 2: Implement the runtime resolver in `video_tagging_assistant/gui/app.py`**

```python
from dataclasses import replace
from pathlib import Path

...
DEFAULT_TAGGING_INPUT_MODE = "excel"
DEFAULT_TAGGING_INPUT_ROOT = Path("videos")


def _resolve_tagging_manifests(manifests, tagging_input_mode: str, tagging_input_root: Path):
    if tagging_input_mode == "excel":
        return manifests
    if tagging_input_mode != "local_root":
        raise ValueError(f"Unsupported gui_pipeline.tagging_input_mode: {tagging_input_mode}")

    resolved = []
    for manifest in manifests:
        local_normal = tagging_input_root / manifest.vs_normal_path.name
        local_night = tagging_input_root / manifest.vs_night_path.name
        if not local_normal.exists():
            raise FileNotFoundError(
                f"Local tagging input not found for {manifest.case_id}: {local_normal}"
            )
        if not local_night.exists():
            raise FileNotFoundError(
                f"Local tagging input not found for {manifest.case_id}: {local_night}"
            )
        resolved.append(
            replace(
                manifest,
                vs_normal_path=local_normal,
                vs_night_path=local_night,
            )
        )
    return resolved


def launch_case_pipeline_gui(workbook_path=None):
    ...
    tagging_input_mode = gui_pipeline.get("tagging_input_mode", DEFAULT_TAGGING_INPUT_MODE)
    tagging_input_root = Path(gui_pipeline.get("tagging_input_root", str(DEFAULT_TAGGING_INPUT_ROOT)))
    ...

    def start_tagging(manifests, mode, event_callback):
        provider = build_provider_from_config(config)
        runtime_manifests = _resolve_tagging_manifests(
            manifests,
            tagging_input_mode=tagging_input_mode,
            tagging_input_root=tagging_input_root,
        )
        return run_batch_tagging(
            manifests=runtime_manifests,
            cache_root=cache_root,
            output_root=tagging_output_root,
            provider=provider,
            prompt_template=config["prompt_template"],
            mode=mode,
            event_callback=event_callback,
        )
```

- [ ] **Step 3: Run the two focused tests**

Run: `pytest tests/test_gui_smoke.py::test_launch_case_pipeline_gui_keeps_excel_tagging_inputs_in_excel_mode tests/test_gui_smoke.py::test_launch_case_pipeline_gui_remaps_tagging_inputs_from_local_root -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_gui_smoke.py video_tagging_assistant/gui/app.py
git commit -m "feat: configure gui tagging input sources"
```

### Task 3: Add failing-path coverage for missing local files and invalid mode

**Files:**
- Modify: `tests/test_gui_smoke.py`
- Modify: `video_tagging_assistant/gui/app.py`

- [ ] **Step 1: Add the missing-file failing test**

```python
import pytest


def test_launch_case_pipeline_gui_raises_when_local_tagging_input_missing(monkeypatch, tmp_path: Path):
    captured = {}

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
                "tagging_input_mode": "local_root",
                "tagging_input_root": str(tmp_path / "missing_videos"),
            },
        },
    )
    monkeypatch.setattr(gui_app, "build_provider_from_config", lambda config: object())

    gui_app.launch_case_pipeline_gui(workbook_path=str(tmp_path / "records.xlsx"))
    manifest = CaseManifest(
        case_id="case_A_0001",
        row_index=2,
        created_date="20260428",
        mode="OV50H40_Action5Pro_DCG HDR",
        raw_path=tmp_path / "raw",
        vs_normal_path=Path(r"\\10.10.10.164\rk3668_capture\case_A_0001_DJI_20260414144209_0109_D.DNG"),
        vs_night_path=Path(r"\\10.10.10.164\rk3668_capture\case_A_0001_DJI_20260414144209_0109_N.DNG"),
        local_case_root=tmp_path / "local" / "case_A_0001",
        server_case_dir=tmp_path / "server" / "case_A_0001",
        remark="场景备注",
        labels={"安装方式": "手持"},
    )

    with pytest.raises(FileNotFoundError) as exc:
        captured["start_tagging"]([manifest], "fresh", lambda event: None)

    assert "case_A_0001" in str(exc.value)
    assert "case_A_0001_DJI_20260414144209_0109_D.DNG" in str(exc.value)
    assert str(tmp_path / "missing_videos") in str(exc.value)
```

- [ ] **Step 2: Add the invalid-mode failing test**

```python
def test_launch_case_pipeline_gui_rejects_invalid_tagging_input_mode(monkeypatch, tmp_path: Path):
    captured = {}

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
                "tagging_input_mode": "bad_mode",
                "tagging_input_root": "videos",
            },
        },
    )
    monkeypatch.setattr(gui_app, "build_provider_from_config", lambda config: object())

    gui_app.launch_case_pipeline_gui(workbook_path=str(tmp_path / "records.xlsx"))
    manifest = CaseManifest(
        case_id="case_A_0105",
        row_index=2,
        created_date="20260428",
        mode="OV50H40_Action5Pro_DCG HDR",
        raw_path=tmp_path / "raw",
        vs_normal_path=tmp_path / "excel_normal.MP4",
        vs_night_path=tmp_path / "excel_night.MP4",
        local_case_root=tmp_path / "local" / "case_A_0105",
        server_case_dir=tmp_path / "server" / "case_A_0105",
        remark="场景备注",
        labels={"安装方式": "手持"},
    )

    with pytest.raises(ValueError) as exc:
        captured["start_tagging"]([manifest], "fresh", lambda event: None)

    assert "tagging_input_mode" in str(exc.value)
    assert "bad_mode" in str(exc.value)
```

- [ ] **Step 3: Run the four targeted GUI tests**

Run: `pytest tests/test_gui_smoke.py::test_launch_case_pipeline_gui_keeps_excel_tagging_inputs_in_excel_mode tests/test_gui_smoke.py::test_launch_case_pipeline_gui_remaps_tagging_inputs_from_local_root tests/test_gui_smoke.py::test_launch_case_pipeline_gui_raises_when_local_tagging_input_missing tests/test_gui_smoke.py::test_launch_case_pipeline_gui_rejects_invalid_tagging_input_mode -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_gui_smoke.py video_tagging_assistant/gui/app.py
git commit -m "test: cover gui tagging input errors"
```

### Task 4: Run focused regression for the GUI pipeline

**Files:**
- Test: `tests/test_gui_smoke.py`
- Test: `tests/test_case_ingest_cli_config.py`
- Test: `tests/test_excel_workbook_pipeline.py`
- Test: `tests/test_pipeline_controller.py`

- [ ] **Step 1: Run the GUI smoke suite**

Run: `pytest tests/test_gui_smoke.py -v`
Expected: PASS, including the new tagging input mode coverage and prior GUI launcher/event-loop/config tests.

- [ ] **Step 2: Run the broader related regression suite**

Run: `pytest tests/test_case_ingest_cli_config.py tests/test_excel_workbook_pipeline.py tests/test_pipeline_controller.py -v`
Expected: PASS with no regressions in config loading, workbook manifest assembly, or execution control.

- [ ] **Step 3: Commit verification-complete state**

```bash
git add configs/config.json tests/test_gui_smoke.py video_tagging_assistant/gui/app.py
git commit -m "test: verify gui tagging input configuration"
```

## Self-Review

### Spec coverage

- `gui_pipeline` gains `tagging_input_mode` and `tagging_input_root`: covered by Task 1.
- `excel` mode keeps existing manifest paths unchanged: covered by Task 2.
- `local_root` mode remaps by filename inside `start_tagging()`: covered by Task 2.
- Missing local files raise clear errors without UNC fallback: covered by Task 3.
- Invalid config values fail early and clearly: covered by Task 3.
- No Excel mutation, no scan-stage rewrite, no GUI directory picker, no execution remap changes: preserved by the architecture and task boundaries above.

### Placeholder scan

- No `TODO`, `TBD`, or vague “handle appropriately” instructions remain.
- Every code-changing step includes concrete code blocks.
- Every validation step includes exact pytest commands and expected outcomes.

### Type consistency

- `tagging_input_mode` is consistently named across config, tests, and `gui/app.py`.
- `tagging_input_root` is consistently converted to `Path` before file resolution.
- Runtime manifest replacement uses `dataclasses.replace(...)` on `CaseManifest`, preserving all non-path fields unchanged.
