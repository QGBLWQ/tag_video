# Case Ingest Launch Simplification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Simplify `case-ingest` so day-to-day runs use a launcher `.bat` plus a dedicated config file, while preserving the existing direct CLI argument mode.

**Architecture:** Keep all pull/copy/upload orchestration unchanged and concentrate the change at the entry boundary. Add a case-ingest-specific config loader that resolves config-relative paths and `date` precedence, extend `video_tagging_assistant/cli.py` to accept `--config`, and add launcher/example `.bat` and config files for stable execution from any current working directory.

**Tech Stack:** Python 3, `argparse`, `json`, `pathlib`, `datetime`, `pytest`, Windows batch scripts

---

## File Structure

**Create:**
- `configs/case_ingest.example.json` — sample case-ingest config for copying/customization
- `configs/case_ingest.json` — default local case-ingest config used by the launcher
- `run_case_ingest.bat` — stable launcher that finds the repo root from its own location and runs `case-ingest --config`
- `run_case_ingest.example.bat` — editable launcher example for custom Python/config paths
- `tests/test_case_ingest_cli_config.py` — config-mode CLI and path/date resolution tests

**Modify:**
- `video_tagging_assistant/config.py` — add dedicated case-ingest config loading and normalization helpers
- `video_tagging_assistant/cli.py` — add `case-ingest --config` support and parameter precedence logic

**Do Not Modify Initially:**
- `video_tagging_assistant/case_ingest_orchestrator.py`
- `video_tagging_assistant/bat_parser.py`
- `video_tagging_assistant/pull_worker.py`
- `video_tagging_assistant/copy_worker.py`
- `video_tagging_assistant/upload_worker.py`

---

### Task 1: Add Case-Ingest Config Loading With Path And Date Resolution

**Files:**
- Modify: `video_tagging_assistant/config.py`
- Create: `tests/test_case_ingest_cli_config.py`

- [ ] **Step 1: Write the failing config resolution tests**

```python
import json
from pathlib import Path

import pytest

from video_tagging_assistant.config import load_case_ingest_config


def test_load_case_ingest_config_resolves_paths_relative_to_config_file(tmp_path: Path):
    config_dir = tmp_path / "configs"
    scripts_dir = tmp_path / "scripts"
    server_dir = tmp_path / "server"
    config_dir.mkdir()
    scripts_dir.mkdir()
    server_dir.mkdir()

    (scripts_dir / "pull.bat").write_text("pull", encoding="utf-8")
    (scripts_dir / "move.bat").write_text("move", encoding="utf-8")

    config_path = config_dir / "case_ingest.json"
    config_path.write_text(
        json.dumps(
            {
                "pull_bat": "../scripts/pull.bat",
                "move_bat": "../scripts/move.bat",
                "server_root": "../server",
                "skip_upload": True,
            }
        ),
        encoding="utf-8",
    )

    resolved = load_case_ingest_config(config_path)

    assert resolved["pull_bat"] == (scripts_dir / "pull.bat").resolve()
    assert resolved["move_bat"] == (scripts_dir / "move.bat").resolve()
    assert resolved["server_root"] == server_dir.resolve()
    assert resolved["skip_upload"] is True


def test_load_case_ingest_config_uses_explicit_date_before_today(tmp_path: Path):
    config_path = tmp_path / "case_ingest.json"
    config_path.write_text(
        json.dumps(
            {
                "pull_bat": "pull.bat",
                "move_bat": "move.bat",
                "server_root": "server",
                "date": "20260420",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "pull.bat").write_text("pull", encoding="utf-8")
    (tmp_path / "move.bat").write_text("move", encoding="utf-8")
    (tmp_path / "server").mkdir()

    resolved = load_case_ingest_config(config_path, cli_date="20260428", today="20260429")

    assert resolved["date"] == "20260428"


def test_load_case_ingest_config_falls_back_to_today_when_date_missing(tmp_path: Path):
    config_path = tmp_path / "case_ingest.json"
    config_path.write_text(
        json.dumps(
            {
                "pull_bat": "pull.bat",
                "move_bat": "move.bat",
                "server_root": "server",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "pull.bat").write_text("pull", encoding="utf-8")
    (tmp_path / "move.bat").write_text("move", encoding="utf-8")
    (tmp_path / "server").mkdir()

    resolved = load_case_ingest_config(config_path, today="20260429")

    assert resolved["date"] == "20260429"


def test_load_case_ingest_config_raises_for_missing_required_key(tmp_path: Path):
    config_path = tmp_path / "case_ingest.json"
    config_path.write_text(json.dumps({"pull_bat": "pull.bat"}), encoding="utf-8")

    with pytest.raises(ValueError, match="Missing case-ingest config keys: move_bat, server_root"):
        load_case_ingest_config(config_path)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_case_ingest_cli_config.py -k load_case_ingest_config -v`
Expected: FAIL with `ImportError` because `load_case_ingest_config` does not exist yet.

- [ ] **Step 3: Add dedicated case-ingest config loading to `video_tagging_assistant/config.py`**

```python
import json
from pathlib import Path
from typing import Dict, Set

REQUIRED_TOP_LEVEL_KEYS: Set[str] = {
    "input_dir",
    "output_dir",
    "compression",
    "provider",
    "prompt_template",
}

CASE_INGEST_REQUIRED_KEYS: Set[str] = {
    "pull_bat",
    "move_bat",
    "server_root",
}

CASE_INGEST_DEFAULTS = {
    "skip_upload": False,
    "upload_workers": 1,
}


def _resolve_config_path(base_dir: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()


def load_case_ingest_config(
    config_path: Path,
    cli_date: str | None = None,
    today: str | None = None,
) -> Dict:
    config_path = Path(config_path).resolve()
    data = json.loads(config_path.read_text(encoding="utf-8"))
    missing = CASE_INGEST_REQUIRED_KEYS - set(data)
    if missing:
        missing_list = ", ".join(sorted(missing))
        raise ValueError(f"Missing case-ingest config keys: {missing_list}")

    base_dir = config_path.parent
    resolved = dict(CASE_INGEST_DEFAULTS)
    resolved.update(data)
    resolved["pull_bat"] = _resolve_config_path(base_dir, resolved["pull_bat"])
    resolved["move_bat"] = _resolve_config_path(base_dir, resolved["move_bat"])
    resolved["server_root"] = _resolve_config_path(base_dir, resolved["server_root"])
    resolved["date"] = cli_date or resolved.get("date") or today
    return resolved
```

Append this helper below the existing `load_config` function in `video_tagging_assistant/config.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_case_ingest_cli_config.py -k load_case_ingest_config -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add video_tagging_assistant/config.py tests/test_case_ingest_cli_config.py
git commit -m "feat: add case-ingest config loader"
```

### Task 2: Add CLI Config Mode While Preserving Legacy Arguments

**Files:**
- Modify: `video_tagging_assistant/cli.py`
- Modify: `tests/test_case_ingest_cli_config.py`

- [ ] **Step 1: Write the failing CLI config-mode tests**

Append these tests to `tests/test_case_ingest_cli_config.py`:

```python
from pathlib import Path

import pytest

from video_tagging_assistant import cli


def test_case_ingest_cli_uses_config_mode(monkeypatch, tmp_path: Path, capsys):
    config_path = tmp_path / "case_ingest.json"
    config_path.write_text("{}", encoding="utf-8")

    captured = {}

    monkeypatch.setattr(
        cli,
        "load_case_ingest_config",
        lambda path, cli_date=None, today=None: {
            "pull_bat": Path("C:/data/pull.bat"),
            "move_bat": Path("C:/data/move.bat"),
            "server_root": Path("C:/server/root"),
            "date": "20260428",
            "skip_upload": True,
        },
    )
    monkeypatch.setattr(
        cli,
        "group_case_tasks",
        lambda pull_bat, move_bat, server_root, date: captured.update(
            {
                "pull_bat": pull_bat,
                "move_bat": move_bat,
                "server_root": server_root,
                "date": date,
            }
        )
        or ["task-a", "task-b"],
    )
    monkeypatch.setattr(
        cli,
        "run_case_ingest",
        lambda tasks, skip_upload=False: {
            "processed": len(tasks),
            "uploaded": 0,
            "skipped": 2,
            "failed": 0,
        },
    )

    result = cli.main([
        "case-ingest",
        "--config",
        str(config_path),
    ])

    assert result == 0
    assert captured == {
        "pull_bat": Path("C:/data/pull.bat"),
        "move_bat": Path("C:/data/move.bat"),
        "server_root": Path("C:/server/root"),
        "date": "20260428",
    }
    out = capsys.readouterr().out
    assert "Processed 2 cases" in out
    assert "Skipped 2 cases" in out


def test_case_ingest_cli_keeps_legacy_argument_mode(monkeypatch, capsys):
    captured = {}

    monkeypatch.setattr(
        cli,
        "group_case_tasks",
        lambda pull_bat, move_bat, server_root, date: captured.update(
            {
                "pull_bat": pull_bat,
                "move_bat": move_bat,
                "server_root": server_root,
                "date": date,
            }
        )
        or ["task-a"],
    )
    monkeypatch.setattr(
        cli,
        "run_case_ingest",
        lambda tasks, skip_upload=False: {
            "processed": len(tasks),
            "uploaded": 1,
            "skipped": 0,
            "failed": 0,
        },
    )

    result = cli.main([
        "case-ingest",
        "--pull-bat",
        "pull.bat",
        "--move-bat",
        "move.bat",
        "--date",
        "20260428",
        "--server-root",
        "server",
    ])

    assert result == 0
    assert captured == {
        "pull_bat": Path("pull.bat"),
        "move_bat": Path("move.bat"),
        "server_root": Path("server"),
        "date": "20260428",
    }
    out = capsys.readouterr().out
    assert "Processed 1 cases" in out
    assert "Uploaded 1 cases" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_case_ingest_cli_config.py -k "config_mode or legacy_argument_mode" -v`
Expected: FAIL because `cli.main()` does not accept argv injection and has no `--config` support.

- [ ] **Step 3: Extend `video_tagging_assistant/cli.py` for config mode**

Replace the current `main` function with this version and add the extra import near the top:

```python
import argparse
from datetime import date as date_cls
from pathlib import Path

from video_tagging_assistant.bat_parser import group_case_tasks
from video_tagging_assistant.case_ingest_orchestrator import run_case_ingest
from video_tagging_assistant.config import load_case_ingest_config, load_config
from video_tagging_assistant.orchestrator import run_batch
from video_tagging_assistant.providers.mock_provider import MockVideoTagProvider
from video_tagging_assistant.providers.openai_compatible import OpenAICompatibleVideoTagProvider
from video_tagging_assistant.providers.qwen_dashscope_provider import QwenDashScopeVideoTagProvider


def build_provider_from_config(config: dict):
    provider_config = config["provider"]
    if provider_config["name"] == "mock":
        return MockVideoTagProvider(model=provider_config["model"])
    if provider_config["name"] == "openai_compatible":
        return OpenAICompatibleVideoTagProvider(
            base_url=provider_config["base_url"],
            api_key_env=provider_config["api_key_env"],
            model=provider_config["model"],
        )
    if provider_config["name"] == "qwen_dashscope":
        return QwenDashScopeVideoTagProvider(
            base_url=provider_config["base_url"],
            api_key_env=provider_config["api_key_env"],
            model=provider_config["model"],
            fps=provider_config.get("fps", 2),
            api_key=provider_config.get("api_key", ""),
        )
    raise ValueError(f"Unsupported provider: {provider_config['name']}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config")
    subparsers = parser.add_subparsers(dest="command")

    case_ingest_parser = subparsers.add_parser("case-ingest")
    case_ingest_parser.add_argument("--config")
    case_ingest_parser.add_argument("--pull-bat")
    case_ingest_parser.add_argument("--move-bat")
    case_ingest_parser.add_argument("--date")
    case_ingest_parser.add_argument("--server-root")
    case_ingest_parser.add_argument("--skip-upload", action="store_true")

    args = parser.parse_args(argv)

    if args.command == "case-ingest":
        if args.config:
            today = date_cls.today().strftime("%Y%m%d")
            resolved = load_case_ingest_config(Path(args.config), cli_date=args.date, today=today)
            tasks = group_case_tasks(
                resolved["pull_bat"],
                resolved["move_bat"],
                resolved["server_root"],
                resolved["date"],
            )
            summary = run_case_ingest(
                tasks,
                skip_upload=bool(args.skip_upload or resolved.get("skip_upload", False)),
            )
        else:
            if not args.pull_bat or not args.move_bat or not args.server_root or not args.date:
                case_ingest_parser.error(
                    "either --config or all of --pull-bat --move-bat --server-root --date are required"
                )
            tasks = group_case_tasks(
                Path(args.pull_bat),
                Path(args.move_bat),
                Path(args.server_root),
                args.date,
            )
            summary = run_case_ingest(tasks, skip_upload=args.skip_upload)

        print(f"Processed {summary['processed']} cases")
        print(f"Uploaded {summary['uploaded']} cases")
        print(f"Skipped {summary['skipped']} cases")
        print(f"Failed {summary['failed']} cases")
        return 0

    if not args.config:
        parser.error("--config is required unless using case-ingest")

    config = load_config(Path(args.config))
    provider = build_provider_from_config(config)
    summary = run_batch(config, provider=provider)
    print(f"Processed {summary['processed']} videos")
    print(f"Review list: {summary['review_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_case_ingest_cli_config.py -k "config_mode or legacy_argument_mode" -v`
Expected: PASS

- [ ] **Step 5: Run the full case-ingest-related test slice**

Run: `pytest tests/test_case_ingest_cli_config.py tests/test_bat_parser.py tests/test_case_ingest_orchestrator.py tests/test_pull_worker.py tests/test_copy_worker.py tests/test_upload_worker.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add video_tagging_assistant/cli.py tests/test_case_ingest_cli_config.py
git commit -m "feat: support config-driven case-ingest cli"
```

### Task 3: Add Default Config And Launcher Files For Daily Use

**Files:**
- Create: `configs/case_ingest.example.json`
- Create: `configs/case_ingest.json`
- Create: `run_case_ingest.bat`
- Create: `run_case_ingest.example.bat`
- Modify: `tests/test_case_ingest_cli_config.py`

- [ ] **Step 1: Write the failing launcher/content tests**

Append these tests to `tests/test_case_ingest_cli_config.py`:

```python
from pathlib import Path


def test_case_ingest_example_config_contains_expected_keys():
    text = Path("configs/case_ingest.example.json").read_text(encoding="utf-8")

    assert '"pull_bat"' in text
    assert '"move_bat"' in text
    assert '"server_root"' in text
    assert '"date"' in text
    assert '"skip_upload"' in text


def test_case_ingest_launcher_uses_own_directory_to_find_config():
    text = Path("run_case_ingest.bat").read_text(encoding="utf-8")

    assert "%~dp0" in text
    assert "configs\\case_ingest.json" in text
    assert "python -m video_tagging_assistant.cli case-ingest --config" in text


def test_case_ingest_example_launcher_mentions_customization_points():
    text = Path("run_case_ingest.example.bat").read_text(encoding="utf-8")

    assert "set \"PYTHON_EXE=" in text
    assert "set \"CONFIG_PATH=" in text
    assert "python -m video_tagging_assistant.cli case-ingest --config" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_case_ingest_cli_config.py -k "launcher or example_config" -v`
Expected: FAIL because the config and launcher files do not exist yet.

- [ ] **Step 3: Create the example config file**

Write this to `configs/case_ingest.example.json`:

```json
{
  "pull_bat": "../20260422_pull.bat",
  "move_bat": "../20260422_move.bat",
  "server_root": "../deployment_package/case_uploads",
  "date": "20260428",
  "skip_upload": false
}
```

- [ ] **Step 4: Create the default local config file**

Write this to `configs/case_ingest.json`:

```json
{
  "pull_bat": "../20260422_pull.bat",
  "move_bat": "../20260422_move.bat",
  "server_root": "../deployment_package/case_uploads",
  "skip_upload": false
}
```

- [ ] **Step 5: Create the stable launcher**

Write this to `run_case_ingest.bat`:

```bat
@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
pushd "%SCRIPT_DIR%"

python -m video_tagging_assistant.cli case-ingest --config "%SCRIPT_DIR%configs\case_ingest.json"
set "EXIT_CODE=%ERRORLEVEL%"

popd
exit /b %EXIT_CODE%
```

- [ ] **Step 6: Create the example launcher**

Write this to `run_case_ingest.example.bat`:

```bat
@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "PYTHON_EXE=python"
set "CONFIG_PATH=%SCRIPT_DIR%configs\case_ingest.json"

pushd "%SCRIPT_DIR%"

"%PYTHON_EXE%" -m video_tagging_assistant.cli case-ingest --config "%CONFIG_PATH%"
set "EXIT_CODE=%ERRORLEVEL%"

popd
exit /b %EXIT_CODE%
```

- [ ] **Step 7: Run test to verify it passes**

Run: `pytest tests/test_case_ingest_cli_config.py -k "launcher or example_config" -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add configs/case_ingest.example.json configs/case_ingest.json run_case_ingest.bat run_case_ingest.example.bat tests/test_case_ingest_cli_config.py
git commit -m "feat: add case-ingest launcher files"
```

### Task 4: Tighten Entry Errors And Verify End-To-End Behavior

**Files:**
- Modify: `video_tagging_assistant/config.py`
- Modify: `tests/test_case_ingest_cli_config.py`

- [ ] **Step 1: Write the failing error-message tests**

Append these tests to `tests/test_case_ingest_cli_config.py`:

```python
import json
from pathlib import Path

import pytest

from video_tagging_assistant.config import load_case_ingest_config


def test_load_case_ingest_config_reports_missing_pull_bat_file(tmp_path: Path):
    config_path = tmp_path / "case_ingest.json"
    config_path.write_text(
        json.dumps(
            {
                "pull_bat": "missing_pull.bat",
                "move_bat": "move.bat",
                "server_root": "server",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "move.bat").write_text("move", encoding="utf-8")
    (tmp_path / "server").mkdir()

    with pytest.raises(ValueError, match="Resolved pull_bat does not exist"):
        load_case_ingest_config(config_path, today="20260429")


def test_load_case_ingest_config_reports_missing_move_bat_file(tmp_path: Path):
    config_path = tmp_path / "case_ingest.json"
    config_path.write_text(
        json.dumps(
            {
                "pull_bat": "pull.bat",
                "move_bat": "missing_move.bat",
                "server_root": "server",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "pull.bat").write_text("pull", encoding="utf-8")
    (tmp_path / "server").mkdir()

    with pytest.raises(ValueError, match="Resolved move_bat does not exist"):
        load_case_ingest_config(config_path, today="20260429")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_case_ingest_cli_config.py -k "reports_missing_pull_bat_file or reports_missing_move_bat_file" -v`
Expected: FAIL because the loader does not validate resolved file existence yet.

- [ ] **Step 3: Add resolved-path validation to `video_tagging_assistant/config.py`**

Update `load_case_ingest_config` so the body ends like this:

```python
    resolved["pull_bat"] = _resolve_config_path(base_dir, resolved["pull_bat"])
    resolved["move_bat"] = _resolve_config_path(base_dir, resolved["move_bat"])
    resolved["server_root"] = _resolve_config_path(base_dir, resolved["server_root"])

    if not resolved["pull_bat"].exists():
        raise ValueError(f"Resolved pull_bat does not exist: {resolved['pull_bat']}")
    if not resolved["move_bat"].exists():
        raise ValueError(f"Resolved move_bat does not exist: {resolved['move_bat']}")
    if not resolved["server_root"].exists():
        raise ValueError(f"Resolved server_root does not exist: {resolved['server_root']}")

    resolved["date"] = cli_date or resolved.get("date") or today
    return resolved
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_case_ingest_cli_config.py -k "reports_missing_pull_bat_file or reports_missing_move_bat_file" -v`
Expected: PASS

- [ ] **Step 5: Run the complete config/CLI regression slice**

Run: `pytest tests/test_case_ingest_cli_config.py tests/test_config.py tests/test_bat_parser.py tests/test_case_ingest_orchestrator.py tests/test_pull_worker.py tests/test_copy_worker.py tests/test_upload_worker.py -v`
Expected: PASS

- [ ] **Step 6: Manual launcher verification**

Run these commands in separate shells:

```bash
cmd /c run_case_ingest.bat
cmd /c "cd /d C:\\ && C:\\Users\\19872\\Desktop\\work！\\run_case_ingest.bat"
```

Expected:
- Both invocations reach the Python CLI without path-resolution errors.
- The second invocation proves current working directory no longer matters.

- [ ] **Step 7: Commit**

```bash
git add video_tagging_assistant/config.py tests/test_case_ingest_cli_config.py
git commit -m "fix: validate case-ingest config paths"
```

---

## Self-Review

- **Spec coverage:** The plan covers launcher `.bat`, dedicated config files, config-relative path resolution, `date` precedence, legacy CLI compatibility, and validation for running from arbitrary current directories.
- **Placeholder scan:** No `TODO`/`TBD` placeholders remain; each code change step includes concrete code and commands.
- **Type consistency:** The new loader is consistently named `load_case_ingest_config`, returns resolved `Path` objects for path fields, and is referenced by the CLI and tests with the same signature.
