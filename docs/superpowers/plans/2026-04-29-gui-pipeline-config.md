# GUI Pipeline Config Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the GUI case pipeline’s hardcoded mode, sheet names, status filters, cache/output roots, and local/server roots into a `gui_pipeline` section in `configs/config.json`, while keeping a safe fallback to current defaults.

**Architecture:** Keep the config file as the single place for runtime path/address tuning and let `gui/app.py` translate that config into the callback-driven assembly the window already uses. `gui_pipeline` will be optional in the first iteration: if present it overrides defaults, if absent the current behavior remains unchanged.

**Tech Stack:** Python 3.8, pathlib, JSON config loading, existing `video_tagging_assistant` modules, pytest

---

## File Structure

### Existing files to modify

- `configs/config.json`
  - Add the new `gui_pipeline` section with the GUI pipeline runtime paths and sheet settings.
- `video_tagging_assistant/gui/app.py`
  - Read `gui_pipeline` from `config.json`, convert configured strings/lists into `Path`/`set` values, and use them in scan/refresh/tagging assembly.
- `tests/test_gui_smoke.py`
  - Add tests proving configured `gui_pipeline` values override defaults, while defaults still work when `gui_pipeline` is absent.

### Existing files to read while implementing

- `video_tagging_assistant/config.py`
  - To understand what top-level config keys are already validated.
- `video_tagging_assistant/excel_workbook.py`
  - For the arguments expected by `build_case_manifests` and `load_approved_review_rows`.
- `video_tagging_assistant/tagging_service.py`
  - For the arguments expected by `run_batch_tagging`.

### New files to create

- None required.

---

### Task 1: Add the `gui_pipeline` config section

**Files:**
- Modify: `configs/config.json`
- Test: `tests/test_gui_smoke.py`

- [ ] **Step 1: Write the failing config-driven launcher test**

```python
from pathlib import Path

from video_tagging_assistant.gui import app as gui_app


def test_launch_case_pipeline_gui_uses_gui_pipeline_config(monkeypatch, tmp_path: Path):
    captured = {}

    class FakeWindow:
        def __init__(self, scan_cases=None, start_tagging=None, refresh_excel_reviews=None, **kwargs):
            captured["scan_cases"] = scan_cases
            captured["start_tagging"] = start_tagging
            captured["refresh_excel_reviews"] = refresh_excel_reviews

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
                "source_sheet": "我的创建记录",
                "review_sheet": "我的审核表",
                "mode": "MY_MODE",
                "allowed_statuses": ["pending", "failed"],
                "local_root": "my_cases",
                "server_root": "my_server_cases",
                "cache_root": "my_cache",
                "tagging_output_root": "my_gui_output"
            }
        },
    )

    calls = {}
    monkeypatch.setattr(gui_app, "ensure_pipeline_columns", lambda workbook, source_sheet: calls.update({"source_sheet": source_sheet}))
    monkeypatch.setattr(
        gui_app,
        "build_case_manifests",
        lambda workbook, source_sheet, allowed_statuses, local_root, server_root, mode: calls.update(
            {
                "manifest_source_sheet": source_sheet,
                "allowed_statuses": allowed_statuses,
                "local_root": local_root,
                "server_root": server_root,
                "mode": mode,
            }
        )
        or [],
    )
    monkeypatch.setattr(gui_app, "load_approved_review_rows", lambda workbook, review_sheet: calls.update({"review_sheet": review_sheet}) or [])
    monkeypatch.setattr(gui_app, "build_provider_from_config", lambda config: object())
    monkeypatch.setattr(
        gui_app,
        "run_batch_tagging",
        lambda manifests, cache_root, output_root, provider, prompt_template, mode, event_callback: calls.update(
            {"cache_root": cache_root, "output_root": output_root, "tag_mode": mode}
        )
        or [],
    )

    gui_app.launch_case_pipeline_gui(workbook_path=str(tmp_path / "records.xlsx"))
    captured["scan_cases"]()
    captured["refresh_excel_reviews"]()
    captured["start_tagging"]([], "fresh", lambda event: None)

    assert calls["source_sheet"] == "我的创建记录"
    assert calls["manifest_source_sheet"] == "我的创建记录"
    assert calls["review_sheet"] == "我的审核表"
    assert calls["allowed_statuses"] == {"pending", "failed"}
    assert calls["local_root"] == Path("my_cases")
    assert calls["server_root"] == Path("my_server_cases")
    assert calls["mode"] == "MY_MODE"
    assert calls["cache_root"] == Path("my_cache")
    assert calls["output_root"] == Path("my_gui_output")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_gui_smoke.py::test_launch_case_pipeline_gui_uses_gui_pipeline_config -v`
Expected: FAIL because `gui/app.py` still ignores `gui_pipeline` and uses hardcoded defaults

- [ ] **Step 3: Add `gui_pipeline` to the real config file**

```json
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
```

Place it inside `configs/config.json` as a new top-level section.

- [ ] **Step 4: Run test to confirm it still fails for code reasons**

Run: `pytest tests/test_gui_smoke.py::test_launch_case_pipeline_gui_uses_gui_pipeline_config -v`
Expected: FAIL because `gui/app.py` still does not read the new section yet

- [ ] **Step 5: Commit**

```bash
git add configs/config.json tests/test_gui_smoke.py
git commit -m "chore: add gui pipeline config section"
```

### Task 2: Make `gui/app.py` read configured sheet names, mode, and roots

**Files:**
- Modify: `video_tagging_assistant/gui/app.py`
- Test: `tests/test_gui_smoke.py`

- [ ] **Step 1: Implement config-driven scan/refresh/root assembly**

```python
DEFAULT_MODE = "OV50H40_Action5Pro_DCG HDR"
DEFAULT_SOURCE_SHEET = "创建记录"
DEFAULT_REVIEW_SHEET = "审核结果"
DEFAULT_ALLOWED_STATUSES = {"", "queued", "failed"}
DEFAULT_LOCAL_ROOT = Path("cases")
DEFAULT_SERVER_ROOT = Path("server_cases")
DEFAULT_CONFIG_PATH = Path("configs/config.json")
DEFAULT_CACHE_ROOT = Path("artifacts/cache")
DEFAULT_TAGGING_OUTPUT_ROOT = Path("artifacts/gui_pipeline")


def launch_case_pipeline_gui(workbook_path=None):
    app = QApplication.instance() or QApplication([])
    workbook = Path(workbook_path) if workbook_path else None
    controller = PipelineController()
    config = load_config(DEFAULT_CONFIG_PATH)
    gui_pipeline = config.get("gui_pipeline", {})

    source_sheet = gui_pipeline.get("source_sheet", DEFAULT_SOURCE_SHEET)
    review_sheet = gui_pipeline.get("review_sheet", DEFAULT_REVIEW_SHEET)
    mode_name = gui_pipeline.get("mode", DEFAULT_MODE)
    allowed_statuses = set(gui_pipeline.get("allowed_statuses", list(DEFAULT_ALLOWED_STATUSES)))
    local_root = Path(gui_pipeline.get("local_root", str(DEFAULT_LOCAL_ROOT)))
    server_root = Path(gui_pipeline.get("server_root", str(DEFAULT_SERVER_ROOT)))
    cache_root = Path(gui_pipeline.get("cache_root", str(DEFAULT_CACHE_ROOT)))
    tagging_output_root = Path(gui_pipeline.get("tagging_output_root", str(DEFAULT_TAGGING_OUTPUT_ROOT)))

    def scan_cases():
        if workbook is None or not workbook.exists():
            return []
        ensure_pipeline_columns(workbook, source_sheet=source_sheet)
        return build_case_manifests(
            workbook,
            source_sheet=source_sheet,
            allowed_statuses=allowed_statuses,
            local_root=local_root,
            server_root=server_root,
            mode=mode_name,
        )

    def refresh_excel_reviews():
        if workbook is None or not workbook.exists():
            return []
        return load_approved_review_rows(workbook, review_sheet=review_sheet)
```

- [ ] **Step 2: Run test to verify it passes**

Run: `pytest tests/test_gui_smoke.py::test_launch_case_pipeline_gui_uses_gui_pipeline_config -v`
Expected: PASS

- [ ] **Step 3: Add a fallback-behavior test**

```python
def test_launch_case_pipeline_gui_falls_back_when_gui_pipeline_missing(monkeypatch, tmp_path: Path):
    captured = {}

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
            "prompt_template": {"system": "describe"}
        },
    )

    calls = {}
    monkeypatch.setattr(gui_app, "ensure_pipeline_columns", lambda workbook, source_sheet: calls.update({"source_sheet": source_sheet}))
    monkeypatch.setattr(
        gui_app,
        "build_case_manifests",
        lambda workbook, source_sheet, allowed_statuses, local_root, server_root, mode: calls.update(
            {
                "allowed_statuses": allowed_statuses,
                "local_root": local_root,
                "server_root": server_root,
                "mode": mode,
            }
        )
        or [],
    )

    workbook = tmp_path / "records.xlsx"
    workbook.write_text("placeholder", encoding="utf-8")
    gui_app.launch_case_pipeline_gui(workbook_path=str(workbook))
    captured["scan_cases"]()

    assert calls["source_sheet"] == gui_app.DEFAULT_SOURCE_SHEET
    assert calls["allowed_statuses"] == gui_app.DEFAULT_ALLOWED_STATUSES
    assert calls["local_root"] == gui_app.DEFAULT_LOCAL_ROOT
    assert calls["server_root"] == gui_app.DEFAULT_SERVER_ROOT
    assert calls["mode"] == gui_app.DEFAULT_MODE
```

- [ ] **Step 4: Run fallback test to verify it passes**

Run: `pytest tests/test_gui_smoke.py::test_launch_case_pipeline_gui_falls_back_when_gui_pipeline_missing -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_gui_smoke.py video_tagging_assistant/gui/app.py
git commit -m "feat: read gui pipeline paths from config"
```

### Task 3: Make the tagging bridge read `cache_root` and `tagging_output_root` from config

**Files:**
- Modify: `video_tagging_assistant/gui/app.py`
- Test: `tests/test_gui_smoke.py`

- [ ] **Step 1: Verify the existing config-driven test now checks tagging roots too**

Use the test from Task 1, which already asserts:

```python
assert calls["cache_root"] == Path("my_cache")
assert calls["output_root"] == Path("my_gui_output")
```

No new test function is needed if that test still covers the tagging bridge after Task 2.

- [ ] **Step 2: Update `start_tagging()` to use the config-driven roots**

```python
def start_tagging(manifests, mode, event_callback):
    provider = build_provider_from_config(config)
    return run_batch_tagging(
        manifests=manifests,
        cache_root=cache_root,
        output_root=tagging_output_root,
        provider=provider,
        prompt_template=config["prompt_template"],
        mode=mode,
        event_callback=event_callback,
    )
```

- [ ] **Step 3: Run the config-driven launcher test again**

Run: `pytest tests/test_gui_smoke.py::test_launch_case_pipeline_gui_uses_gui_pipeline_config -v`
Expected: PASS with the configured `cache_root` and `tagging_output_root` assertions succeeding

- [ ] **Step 4: Commit**

```bash
git add tests/test_gui_smoke.py video_tagging_assistant/gui/app.py
git commit -m "feat: configure gui tagging roots"
```

### Task 4: Run focused regression for the config-driven GUI pipeline

**Files:**
- Test: `tests/test_gui_smoke.py`
- Test: `tests/test_case_ingest_cli_config.py`
- Test: `tests/test_excel_workbook_pipeline.py`
- Test: `tests/test_pipeline_controller.py`

- [ ] **Step 1: Run focused GUI config tests**

Run: `pytest tests/test_gui_smoke.py::test_launch_case_pipeline_gui_uses_gui_pipeline_config tests/test_gui_smoke.py::test_launch_case_pipeline_gui_falls_back_when_gui_pipeline_missing tests/test_gui_smoke.py::test_launch_case_pipeline_gui_enters_event_loop -v`
Expected: PASS

- [ ] **Step 2: Run the broader related regression suite**

Run: `pytest tests/test_gui_smoke.py tests/test_case_ingest_cli_config.py tests/test_excel_workbook_pipeline.py tests/test_pipeline_controller.py -v`
Expected: PASS with no regressions in GUI assembly, CLI entrypoint, workbook helpers, or controller behavior

- [ ] **Step 3: Commit verification-complete state**

```bash
git add configs/config.json tests/test_gui_smoke.py tests/test_case_ingest_cli_config.py tests/test_excel_workbook_pipeline.py tests/test_pipeline_controller.py video_tagging_assistant/gui/app.py
git commit -m "test: verify config-driven gui pipeline"
```

## Self-Review

### Spec coverage

- `gui_pipeline` section added to `config.json`: covered by Task 1.
- `gui/app.py` reads config-driven sheet names, mode, roots, and allowed statuses: covered by Task 2.
- `start_tagging()` reads cache/output roots from config: covered by Task 3.
- Fallback to existing defaults remains in place: covered by Task 2.
- No GUI settings editor, no environment/profile system, and no Excel semantic rewrite: intentionally excluded.

### Placeholder scan

- No `TODO`, `TBD`, or vague “make configurable” steps remain.
- Every task names exact files and exact pytest commands.
- All implementation steps include concrete code or config blocks.

### Type consistency

- `gui_pipeline` keys are named consistently across the spec, tests, and planned implementation.
- `allowed_statuses` is consistently treated as a list in JSON and a `set` in Python.
- `local_root`, `server_root`, `cache_root`, and `tagging_output_root` are consistently converted to `Path` values in `gui/app.py`.
