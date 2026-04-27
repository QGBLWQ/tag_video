# Case Pull Copy Upload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a single entrypoint that reads pull/move bat files, groups work by case, performs resumable RK raw pull plus validation, copies DJI files, and uploads each completed case to the dated server directory.

**Architecture:** Add a separate case-ingest workflow alongside the existing video-tagging pipeline instead of overloading `run_batch()`. Keep bat parsing, case models, pull/copy workers, upload worker, and orchestration in focused files so the case workflow remains testable and independent. Use TDD for each unit and a single background upload thread to overlap case upload with the next case pull.

**Tech Stack:** Python 3.8+, pathlib, shutil, subprocess, threading, queue, dataclasses, pytest.

---

## File Structure

- Modify: `video_tagging_assistant/config.py` — accept an optional `case_ingest` config section and keep existing config loading behavior unchanged.
- Create: `video_tagging_assistant/case_ingest_models.py` — dataclasses for parsed bat rows, grouped case tasks, per-case status, and final summary rows.
- Create: `video_tagging_assistant/bat_parser.py` — detect bat encoding, parse pull bat pairs, parse move bat copy rows, and group records by `case_id`.
- Create: `video_tagging_assistant/pull_worker.py` — wait for device, count remote files, perform resumable pull into `_tmp`, merge into final RK raw directory, and validate file counts.
- Create: `video_tagging_assistant/copy_worker.py` — copy DJI files declared in move bat and validate destination presence.
- Create: `video_tagging_assistant/upload_worker.py` — compute server target path, skip existing server case directories, upload whole case directories, and expose a queue-driven worker loop.
- Create: `video_tagging_assistant/case_ingest_orchestrator.py` — run the case workflow in order, enqueue uploads, collect upload results, and return a summary dict.
- Modify: `video_tagging_assistant/cli.py` — add a `case-ingest` command with explicit bat/date/server arguments while preserving the existing tagging CLI path.
- Create: `tests/test_case_ingest_models.py` — dataclass coverage for case task defaults and summary state transitions.
- Create: `tests/test_bat_parser.py` — parsing and grouping coverage for pull/move bat content.
- Create: `tests/test_pull_worker.py` — resumable pull, merge, and file-count validation coverage with subprocess stubs.
- Create: `tests/test_copy_worker.py` — DJI copy execution and validation coverage.
- Create: `tests/test_upload_worker.py` — server skip/upload logic and background worker coverage.
- Create: `tests/test_case_ingest_orchestrator.py` — end-to-end orchestration behavior with stubbed workers.
- Modify: `tests/test_config.py` — config acceptance for optional `case_ingest` defaults.
- Modify: `tests/test_pipeline.py` — keep the existing video-tagging path stable while adding CLI coverage for the new command.

## Assumptions Locked In

- `pull.bat` remains the source of RK raw device-to-case mapping.
- `move.bat` remains the source of DJI normal/night file-to-case mapping.
- Upload content is the whole case directory, not only the RK raw subdirectory.
- A case enters upload only after RK raw validation passes and all declared DJI files are copied into the case directory.
- If the server target case directory already exists, upload is skipped and reported as `upload_skipped_exists`.
- First version uses one background upload thread and one main case-processing thread.

### Task 1: Add case ingest config support

**Files:**
- Modify: `video_tagging_assistant/config.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Write the failing config test for optional case-ingest settings**

```python
import json
from pathlib import Path

from video_tagging_assistant.config import load_config


def test_load_config_keeps_optional_case_ingest_defaults(tmp_path: Path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "input_dir": "videos",
                "output_dir": "output",
                "compression": {"width": 960, "video_bitrate": "700k"},
                "provider": {"name": "mock", "model": "fake-model"},
                "prompt_template": {"system": "describe video"},
                "case_ingest": {"server_root": r"\\\\10.10.10.164\\rk3668_capture"},
            }
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config["case_ingest"]["server_root"] == r"\\10.10.10.164\rk3668_capture"
    assert config["case_ingest"]["skip_upload"] is False
    assert config["case_ingest"]["upload_workers"] == 1
```

- [ ] **Step 2: Run the config test to verify it fails**

Run: `pytest tests/test_config.py::test_load_config_keeps_optional_case_ingest_defaults -v`
Expected: FAIL because `case_ingest.skip_upload` and `case_ingest.upload_workers` are missing.

- [ ] **Step 3: Add minimal case-ingest defaults in config loading**

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

CASE_INGEST_DEFAULTS = {
    "skip_upload": False,
    "upload_workers": 1,
}


def load_config(config_path: Path) -> Dict:
    config_path = Path(config_path)
    data = json.loads(config_path.read_text(encoding="utf-8"))
    missing = REQUIRED_TOP_LEVEL_KEYS - set(data)
    if missing:
        missing_list = ", ".join(sorted(missing))
        raise ValueError(f"Missing config keys: {missing_list}")

    if "case_ingest" in data:
        case_ingest = dict(CASE_INGEST_DEFAULTS)
        case_ingest.update(data["case_ingest"])
        data["case_ingest"] = case_ingest

    return data
```

- [ ] **Step 4: Run config tests**

Run: `pytest tests/test_config.py -v`
Expected: PASS for the existing config test and the new case-ingest config test.

- [ ] **Step 5: Commit**

```bash
git add tests/test_config.py video_tagging_assistant/config.py
git commit -m "feat: add case ingest config defaults"
```

### Task 2: Add case ingest dataclasses

**Files:**
- Create: `video_tagging_assistant/case_ingest_models.py`
- Create: `tests/test_case_ingest_models.py`

- [ ] **Step 1: Write failing tests for case task and summary models**

```python
from pathlib import Path

from video_tagging_assistant.case_ingest_models import CaseTask, CopyTask, PullTask, UploadResult


def test_case_task_defaults_to_pending_status():
    task = CaseTask(
        case_id="case_A_0078",
        pull_task=PullTask(
            case_id="case_A_0078",
            device_path="/mnt/nvme/CapturedData/117",
            local_name="case_A_0078_RK_raw_117",
            move_src=r"E:\DV\case_A_0078_RK_raw_117",
            move_dst=r"E:\DV\OV50\20260427\case_A_0078\case_A_0078_RK_raw_117",
        ),
        case_root_dir=Path(r"E:\DV\OV50\20260427\case_A_0078"),
        server_case_dir=Path(r"\\10.10.10.164\rk3668_capture\OV50\20260427\case_A_0078"),
    )

    assert task.status == "pending"
    assert task.copy_tasks == []


def test_upload_result_preserves_skip_exists_state():
    result = UploadResult(case_id="case_A_0078", status="upload_skipped_exists", message="exists")

    assert result.status == "upload_skipped_exists"
    assert result.message == "exists"
```

- [ ] **Step 2: Run the new model tests to verify the module is missing**

Run: `pytest tests/test_case_ingest_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'video_tagging_assistant.case_ingest_models'`.

- [ ] **Step 3: Implement focused case-ingest dataclasses**

```python
from dataclasses import dataclass, field
from pathlib import Path
from typing import List


@dataclass
class PullTask:
    case_id: str
    device_path: str
    local_name: str
    move_src: str
    move_dst: str


@dataclass
class CopyTask:
    case_id: str
    source_path: Path
    target_path: Path
    kind: str


@dataclass
class CaseTask:
    case_id: str
    pull_task: PullTask
    case_root_dir: Path
    server_case_dir: Path
    copy_tasks: List[CopyTask] = field(default_factory=list)
    status: str = "pending"
    message: str = ""


@dataclass
class UploadResult:
    case_id: str
    status: str
    message: str = ""
```

- [ ] **Step 4: Run the model tests**

Run: `pytest tests/test_case_ingest_models.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_case_ingest_models.py video_tagging_assistant/case_ingest_models.py
git commit -m "feat: add case ingest models"
```

### Task 3: Parse pull and move bat files into grouped case tasks

**Files:**
- Create: `video_tagging_assistant/bat_parser.py`
- Modify: `video_tagging_assistant/case_ingest_models.py`
- Create: `tests/test_bat_parser.py`

- [ ] **Step 1: Write failing tests for pull parsing, move parsing, and grouping**

```python
from pathlib import Path

from video_tagging_assistant.bat_parser import group_case_tasks, parse_move_bat, parse_pull_bat


def test_parse_pull_bat_extracts_case_mapping(tmp_path: Path):
    bat_path = tmp_path / "pull.bat"
    bat_path.write_text(
        "\n".join(
            [
                "adb wait-for-device",
                r"adb pull /mnt/nvme/CapturedData/117 .\\case_A_0078_RK_raw_117",
                r'move "E:\\DV\\case_A_0078_RK_raw_117" "E:\\DV\\OV50\\20260427\\case_A_0078\\case_A_0078_RK_raw_117"',
            ]
        ),
        encoding="utf-8",
    )

    rows = parse_pull_bat(bat_path)

    assert len(rows) == 1
    assert rows[0].case_id == "case_A_0078"
    assert rows[0].device_path == "/mnt/nvme/CapturedData/117"


def test_parse_move_bat_extracts_normal_and_night_rows(tmp_path: Path):
    bat_path = tmp_path / "move.bat"
    bat_path.write_text(
        "\n".join(
            [
                r'copy "E:\\DJI\\Nomal\\a.mp4" "E:\\DV\\OV50\\20260427\\case_A_0078\\case_A_0078_DJI_a.mp4"',
                r'copy "E:\\DJI\\Night\\b.mp4" "E:\\DV\\OV50\\20260427\\case_A_0078\\case_A_0078_night_DJI_b.mp4"',
            ]
        ),
        encoding="utf-8",
    )

    rows = parse_move_bat(bat_path)

    assert [row.kind for row in rows] == ["normal", "night"]
    assert rows[1].case_id == "case_A_0078"


def test_group_case_tasks_merges_pull_and_copy_rows(tmp_path: Path):
    pull_path = tmp_path / "pull.bat"
    move_path = tmp_path / "move.bat"
    pull_path.write_text(
        r'adb pull /mnt/nvme/CapturedData/117 .\\case_A_0078_RK_raw_117' + "\n" +
        r'move "E:\\DV\\case_A_0078_RK_raw_117" "E:\\DV\\OV50\\20260427\\case_A_0078\\case_A_0078_RK_raw_117"',
        encoding="utf-8",
    )
    move_path.write_text(
        r'copy "E:\\DJI\\Night\\b.mp4" "E:\\DV\\OV50\\20260427\\case_A_0078\\case_A_0078_night_DJI_b.mp4"',
        encoding="utf-8",
    )

    tasks = group_case_tasks(pull_path, move_path, Path(r"\\10.10.10.164\rk3668_capture\OV50"), "20260427")

    assert len(tasks) == 1
    assert tasks[0].case_id == "case_A_0078"
    assert tasks[0].copy_tasks[0].kind == "night"
    assert tasks[0].server_case_dir == Path(r"\\10.10.10.164\rk3668_capture\OV50\20260427\case_A_0078")
```

- [ ] **Step 2: Run the parser tests to verify they fail**

Run: `pytest tests/test_bat_parser.py -v`
Expected: FAIL because `bat_parser.py` does not exist.

- [ ] **Step 3: Implement encoding detection, parsing, and grouping**

```python
import re
from pathlib import Path
from typing import List

from video_tagging_assistant.case_ingest_models import CaseTask, CopyTask, PullTask

CASE_PATTERN = re.compile(r"(case_[A-Z]_\d{4})", re.IGNORECASE)
PULL_PATTERN = re.compile(r"adb\s+pull\s+(\S+)\s+\.\\\s*(\S+)", re.IGNORECASE)
MOVE_PATTERN = re.compile(r'move\s+"([^"]+)"\s+"([^"]+)"', re.IGNORECASE)
COPY_PATTERN = re.compile(r'copy\s+"([^"]+)"\s+"([^"]+)"', re.IGNORECASE)


def detect_encoding(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gbk", "latin-1"):
        try:
            raw.decode(encoding)
            return encoding
        except UnicodeDecodeError:
            continue
    return "latin-1"


def _extract_case_id(text: str) -> str:
    match = CASE_PATTERN.search(text)
    if not match:
        raise ValueError(f"Unable to extract case id from: {text}")
    return match.group(1)


def parse_pull_bat(path: Path) -> List[PullTask]:
    rows = []
    pending = None
    with path.open(encoding=detect_encoding(path), errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            pull_match = PULL_PATTERN.search(line)
            if pull_match:
                pending = (pull_match.group(1), pull_match.group(2))
                continue
            move_match = MOVE_PATTERN.search(line)
            if move_match and pending:
                move_dst = move_match.group(2)
                rows.append(
                    PullTask(
                        case_id=_extract_case_id(move_dst),
                        device_path=pending[0],
                        local_name=pending[1],
                        move_src=move_match.group(1),
                        move_dst=move_dst,
                    )
                )
                pending = None
    return rows


def parse_move_bat(path: Path) -> List[CopyTask]:
    rows = []
    with path.open(encoding=detect_encoding(path), errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            copy_match = COPY_PATTERN.search(line)
            if not copy_match:
                continue
            target = Path(copy_match.group(2))
            name = target.name.lower()
            kind = "night" if "night" in name else "normal"
            rows.append(
                CopyTask(
                    case_id=_extract_case_id(str(target)),
                    source_path=Path(copy_match.group(1)),
                    target_path=target,
                    kind=kind,
                )
            )
    return rows


def group_case_tasks(pull_bat: Path, move_bat: Path, server_root: Path, date: str) -> List[CaseTask]:
    grouped = {}
    for pull_row in parse_pull_bat(pull_bat):
        case_root_dir = Path(pull_row.move_dst).parent
        grouped[pull_row.case_id] = CaseTask(
            case_id=pull_row.case_id,
            pull_task=pull_row,
            case_root_dir=case_root_dir,
            server_case_dir=server_root / date / pull_row.case_id,
        )

    for copy_row in parse_move_bat(move_bat):
        if copy_row.case_id in grouped:
            grouped[copy_row.case_id].copy_tasks.append(copy_row)

    return [grouped[key] for key in sorted(grouped)]
```

- [ ] **Step 4: Run parser tests**

Run: `pytest tests/test_bat_parser.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_bat_parser.py video_tagging_assistant/bat_parser.py video_tagging_assistant/case_ingest_models.py
git commit -m "feat: parse pull and move bat tasks"
```

### Task 4: Add resumable pull and RK raw validation

**Files:**
- Create: `video_tagging_assistant/pull_worker.py`
- Create: `tests/test_pull_worker.py`

- [ ] **Step 1: Write failing tests for merge, completed-skip detection, and validation**

```python
from pathlib import Path

from video_tagging_assistant.case_ingest_models import PullTask
from video_tagging_assistant.pull_worker import merge_tmp_into_final, validate_pull_counts


def test_merge_tmp_into_final_moves_missing_files_only(tmp_path: Path):
    final_dir = tmp_path / "case_A_0078_RK_raw_117"
    tmp_dir = tmp_path / "case_A_0078_RK_raw_117_tmp"
    (final_dir / "a").mkdir(parents=True)
    (tmp_dir / "a").mkdir(parents=True)
    (final_dir / "a" / "1.txt").write_text("old", encoding="utf-8")
    (tmp_dir / "a" / "1.txt").write_text("new", encoding="utf-8")
    (tmp_dir / "a" / "2.txt").write_text("new", encoding="utf-8")

    merge_tmp_into_final(tmp_dir, final_dir)

    assert (final_dir / "a" / "1.txt").read_text(encoding="utf-8") == "old"
    assert (final_dir / "a" / "2.txt").read_text(encoding="utf-8") == "new"
    assert not tmp_dir.exists()


def test_validate_pull_counts_returns_true_when_equal(tmp_path: Path):
    final_dir = tmp_path / "case_A_0078_RK_raw_117"
    final_dir.mkdir()
    (final_dir / "1.txt").write_text("1", encoding="utf-8")
    (final_dir / "2.txt").write_text("2", encoding="utf-8")

    assert validate_pull_counts(2, final_dir) is True
```

- [ ] **Step 2: Run the pull worker tests to verify they fail**

Run: `pytest tests/test_pull_worker.py -v`
Expected: FAIL because `pull_worker.py` does not exist.

- [ ] **Step 3: Implement merge and validation helpers**

```python
import shutil
import subprocess
from pathlib import Path

from video_tagging_assistant.case_ingest_models import PullTask


def count_local_files(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for file_path in path.rglob("*") if file_path.is_file())


def merge_tmp_into_final(tmp_dir: Path, final_dir: Path) -> None:
    if not tmp_dir.exists():
        return
    if not final_dir.exists():
        tmp_dir.rename(final_dir)
        return

    for source in tmp_dir.rglob("*"):
        if not source.is_file():
            continue
        relative = source.relative_to(tmp_dir)
        target = final_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.move(str(source), str(target))

    shutil.rmtree(tmp_dir, ignore_errors=True)


def validate_pull_counts(remote_count: int, final_dir: Path) -> bool:
    return remote_count >= 0 and count_local_files(final_dir) == remote_count
```

- [ ] **Step 4: Extend the worker with device count and resumable pull flow**

```python
def count_remote_files(device_path: str) -> int:
    result = subprocess.run(
        ["adb", "shell", "find", device_path, "-type", "f"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "adb shell find failed")
    return len([line for line in result.stdout.splitlines() if line.strip()])


def wait_for_device() -> None:
    subprocess.run(["adb", "wait-for-device"], check=True)


def run_resumable_pull(task: PullTask) -> Path:
    final_dir = Path(task.local_name)
    tmp_dir = Path(f"{task.local_name}_tmp")
    remote_count = count_remote_files(task.device_path)

    if validate_pull_counts(remote_count, final_dir):
        return final_dir

    if tmp_dir.exists():
        shutil.rmtree(tmp_dir, ignore_errors=True)

    subprocess.run(["adb", "pull", task.device_path, str(tmp_dir)], check=True)
    merge_tmp_into_final(tmp_dir, final_dir)

    if not validate_pull_counts(remote_count, final_dir):
        raise RuntimeError(f"pull validation failed for {task.case_id}")

    return final_dir
```

- [ ] **Step 5: Run pull worker tests**

Run: `pytest tests/test_pull_worker.py -v`
Expected: PASS for merge and validation helpers.

- [ ] **Step 6: Commit**

```bash
git add tests/test_pull_worker.py video_tagging_assistant/pull_worker.py
git commit -m "feat: add resumable pull worker"
```

### Task 5: Add DJI copy worker

**Files:**
- Create: `video_tagging_assistant/copy_worker.py`
- Create: `tests/test_copy_worker.py`

- [ ] **Step 1: Write failing tests for copying DJI files into case directories**

```python
from pathlib import Path

from video_tagging_assistant.case_ingest_models import CopyTask
from video_tagging_assistant.copy_worker import copy_declared_files


def test_copy_declared_files_copies_all_sources(tmp_path: Path):
    source_file = tmp_path / "DJI_0001.MP4"
    source_file.write_bytes(b"video")
    target_file = tmp_path / "case_A_0078" / "case_A_0078_DJI_0001.MP4"
    tasks = [
        CopyTask(
            case_id="case_A_0078",
            source_path=source_file,
            target_path=target_file,
            kind="normal",
        )
    ]

    copy_declared_files(tasks)

    assert target_file.exists()
    assert target_file.read_bytes() == b"video"
```

- [ ] **Step 2: Run the copy worker test to verify it fails**

Run: `pytest tests/test_copy_worker.py -v`
Expected: FAIL because `copy_worker.py` does not exist.

- [ ] **Step 3: Implement the minimal copy worker**

```python
import shutil
from typing import Iterable

from video_tagging_assistant.case_ingest_models import CopyTask


def copy_declared_files(tasks: Iterable[CopyTask]) -> None:
    for task in tasks:
        if not task.source_path.exists():
            raise FileNotFoundError(str(task.source_path))
        task.target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(task.source_path, task.target_path)
        if not task.target_path.exists():
            raise RuntimeError(f"copy failed: {task.target_path}")
```

- [ ] **Step 4: Run the copy worker test**

Run: `pytest tests/test_copy_worker.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_copy_worker.py video_tagging_assistant/copy_worker.py
git commit -m "feat: add dji copy worker"
```

### Task 6: Add server upload worker with skip-existing behavior

**Files:**
- Create: `video_tagging_assistant/upload_worker.py`
- Create: `tests/test_upload_worker.py`

- [ ] **Step 1: Write failing tests for skip-existing and upload behavior**

```python
from pathlib import Path

from video_tagging_assistant.upload_worker import upload_case_directory


def test_upload_case_directory_skips_when_server_case_exists(tmp_path: Path):
    local_case = tmp_path / "local" / "case_A_0078"
    server_case = tmp_path / "server" / "case_A_0078"
    local_case.mkdir(parents=True)
    server_case.mkdir(parents=True)

    result = upload_case_directory("case_A_0078", local_case, server_case)

    assert result.status == "upload_skipped_exists"


def test_upload_case_directory_copies_whole_case_when_missing(tmp_path: Path):
    local_case = tmp_path / "local" / "case_A_0078"
    server_case = tmp_path / "server" / "case_A_0078"
    (local_case / "sub").mkdir(parents=True)
    (local_case / "sub" / "1.txt").write_text("ok", encoding="utf-8")

    result = upload_case_directory("case_A_0078", local_case, server_case)

    assert result.status == "uploaded"
    assert (server_case / "sub" / "1.txt").read_text(encoding="utf-8") == "ok"
```

- [ ] **Step 2: Run the upload worker tests to verify they fail**

Run: `pytest tests/test_upload_worker.py -v`
Expected: FAIL because `upload_worker.py` does not exist.

- [ ] **Step 3: Implement upload and skip-existing logic**

```python
import shutil
from pathlib import Path

from video_tagging_assistant.case_ingest_models import UploadResult


def upload_case_directory(case_id: str, local_case_dir: Path, server_case_dir: Path) -> UploadResult:
    if server_case_dir.exists():
        return UploadResult(case_id=case_id, status="upload_skipped_exists", message="server case already exists")

    server_case_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(local_case_dir, server_case_dir)
    return UploadResult(case_id=case_id, status="uploaded")
```

- [ ] **Step 4: Add a queue-driven worker loop**

```python
from queue import Empty


def upload_worker_loop(task_queue, result_queue, stop_event) -> None:
    while not stop_event.is_set() or not task_queue.empty():
        try:
            case_task = task_queue.get(timeout=0.1)
        except Empty:
            continue

        try:
            result = upload_case_directory(
                case_task.case_id,
                case_task.case_root_dir,
                case_task.server_case_dir,
            )
        except Exception as exc:
            result = UploadResult(case_id=case_task.case_id, status="failed", message=str(exc))

        result_queue.put(result)
        task_queue.task_done()
```

- [ ] **Step 5: Run the upload worker tests**

Run: `pytest tests/test_upload_worker.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tests/test_upload_worker.py video_tagging_assistant/upload_worker.py
git commit -m "feat: add case upload worker"
```

### Task 7: Add case-ingest orchestration

**Files:**
- Create: `video_tagging_assistant/case_ingest_orchestrator.py`
- Create: `tests/test_case_ingest_orchestrator.py`

- [ ] **Step 1: Write failing orchestration test with stub workers**

```python
from pathlib import Path

from video_tagging_assistant.case_ingest_models import CaseTask, PullTask, UploadResult
from video_tagging_assistant.case_ingest_orchestrator import run_case_ingest


class StubPullWorker:
    def __call__(self, pull_task):
        final_dir = Path(pull_task.move_dst)
        final_dir.mkdir(parents=True, exist_ok=True)
        (final_dir / "1.txt").write_text("ok", encoding="utf-8")
        return final_dir


class StubCopyWorker:
    def __call__(self, copy_tasks):
        for copy_task in copy_tasks:
            copy_task.target_path.parent.mkdir(parents=True, exist_ok=True)
            copy_task.target_path.write_text("copied", encoding="utf-8")


class StubUploader:
    def __call__(self, case_id, local_case_dir, server_case_dir):
        return UploadResult(case_id=case_id, status="uploaded")


def test_run_case_ingest_processes_case_and_reports_uploaded(tmp_path: Path):
    case_root = tmp_path / "local" / "case_A_0078"
    server_case = tmp_path / "server" / "case_A_0078"
    task = CaseTask(
        case_id="case_A_0078",
        pull_task=PullTask(
            case_id="case_A_0078",
            device_path="/mnt/nvme/CapturedData/117",
            local_name=str(case_root / "case_A_0078_RK_raw_117"),
            move_src=str(case_root / "case_A_0078_RK_raw_117"),
            move_dst=str(case_root / "case_A_0078_RK_raw_117"),
        ),
        case_root_dir=case_root,
        server_case_dir=server_case,
    )

    summary = run_case_ingest(
        [task],
        pull_runner=StubPullWorker(),
        copy_runner=StubCopyWorker(),
        upload_runner=StubUploader(),
        skip_upload=False,
    )

    assert summary["processed"] == 1
    assert summary["uploaded"] == 1
    assert summary["failed"] == 0
```

- [ ] **Step 2: Run the orchestrator test to verify it fails**

Run: `pytest tests/test_case_ingest_orchestrator.py -v`
Expected: FAIL because `case_ingest_orchestrator.py` does not exist.

- [ ] **Step 3: Implement the orchestration flow with one upload thread**

```python
import threading
from queue import Queue
from typing import Iterable

from video_tagging_assistant.copy_worker import copy_declared_files
from video_tagging_assistant.pull_worker import run_resumable_pull, wait_for_device
from video_tagging_assistant.upload_worker import upload_worker_loop


def run_case_ingest(tasks: Iterable, pull_runner=run_resumable_pull, copy_runner=copy_declared_files, upload_runner=None, skip_upload=False):
    task_queue = Queue()
    result_queue = Queue()
    stop_event = threading.Event()
    upload_results = {}

    if not skip_upload:
        upload_thread = threading.Thread(
            target=upload_worker_loop,
            args=(task_queue, result_queue, stop_event),
            daemon=True,
        )
        upload_thread.start()
    else:
        upload_thread = None

    processed = 0
    failed = 0
    uploaded = 0
    skipped = 0

    for case_task in tasks:
        try:
            wait_for_device()
            pull_runner(case_task.pull_task)
            copy_runner(case_task.copy_tasks)
            case_task.status = "ready_to_upload"
            processed += 1
            if skip_upload:
                skipped += 1
            else:
                task_queue.put(case_task)
        except Exception as exc:
            case_task.status = "failed"
            case_task.message = str(exc)
            failed += 1

    if not skip_upload:
        task_queue.join()
        stop_event.set()
        upload_thread.join()
        while not result_queue.empty():
            result = result_queue.get()
            upload_results[result.case_id] = result
            if result.status == "uploaded":
                uploaded += 1
            elif result.status == "upload_skipped_exists":
                skipped += 1
            else:
                failed += 1

    return {
        "processed": processed,
        "uploaded": uploaded,
        "skipped": skipped,
        "failed": failed,
        "upload_results": upload_results,
    }
```

- [ ] **Step 4: Run orchestrator tests**

Run: `pytest tests/test_case_ingest_orchestrator.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_case_ingest_orchestrator.py video_tagging_assistant/case_ingest_orchestrator.py
git commit -m "feat: add case ingest orchestrator"
```

### Task 8: Add CLI entrypoint for case ingest workflow

**Files:**
- Modify: `video_tagging_assistant/cli.py`
- Modify: `tests/test_pipeline.py`

- [ ] **Step 1: Write failing CLI test for the new case-ingest command**

```python
from pathlib import Path

from video_tagging_assistant.cli import main


def test_main_supports_case_ingest_command(monkeypatch, tmp_path: Path):
    captured = {}

    def fake_run_case_ingest(tasks, **kwargs):
        captured["tasks"] = tasks
        return {"processed": 1, "uploaded": 1, "skipped": 0, "failed": 0, "upload_results": {}}

    def fake_group_case_tasks(pull_bat, move_bat, server_root, date):
        captured["date"] = date
        captured["server_root"] = server_root
        return ["case-task"]

    monkeypatch.setattr("video_tagging_assistant.cli.group_case_tasks", fake_group_case_tasks)
    monkeypatch.setattr("video_tagging_assistant.cli.run_case_ingest", fake_run_case_ingest)
    monkeypatch.setattr(
        "sys.argv",
        [
            "video-tagging-assistant",
            "case-ingest",
            "--pull-bat",
            str(tmp_path / "pull.bat"),
            "--move-bat",
            str(tmp_path / "move.bat"),
            "--date",
            "20260427",
            "--server-root",
            r"\\10.10.10.164\rk3668_capture\OV50",
        ],
    )

    assert main() == 0
    assert captured["date"] == "20260427"
    assert captured["tasks"] == ["case-task"]
```

- [ ] **Step 2: Run the CLI test to verify it fails**

Run: `pytest tests/test_pipeline.py::test_main_supports_case_ingest_command -v`
Expected: FAIL because the CLI only supports `--config` today.

- [ ] **Step 3: Implement a subcommand-based CLI without breaking the batch path**

```python
import argparse
from pathlib import Path

from video_tagging_assistant.bat_parser import group_case_tasks
from video_tagging_assistant.case_ingest_orchestrator import run_case_ingest
from video_tagging_assistant.config import load_config
from video_tagging_assistant.orchestrator import run_batch
from video_tagging_assistant.providers.mock_provider import MockVideoTagProvider
from video_tagging_assistant.providers.openai_compatible import OpenAICompatibleVideoTagProvider
from video_tagging_assistant.providers.qwen_dashscope_provider import QwenDashScopeVideoTagProvider


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")

    batch_parser = subparsers.add_parser("batch")
    batch_parser.add_argument("--config", required=True)

    case_ingest_parser = subparsers.add_parser("case-ingest")
    case_ingest_parser.add_argument("--pull-bat", required=True)
    case_ingest_parser.add_argument("--move-bat", required=True)
    case_ingest_parser.add_argument("--date", required=True)
    case_ingest_parser.add_argument("--server-root", required=True)
    case_ingest_parser.add_argument("--skip-upload", action="store_true")

    args = parser.parse_args()

    if args.command in (None, "batch"):
        config_path = Path(args.config) if args.command == "batch" else Path(parser.parse_args(["batch", *filter(None, [])]).config)
        config = load_config(config_path)
        provider = build_provider_from_config(config)
        summary = run_batch(config, provider=provider)
        print(f"Processed {summary['processed']} videos")
        print(f"Review list: {summary['review_path']}")
        return 0

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
```

- [ ] **Step 4: Refine the batch branch to stay compatible with the current `--config` usage**

```python
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config")
    subparsers = parser.add_subparsers(dest="command")

    case_ingest_parser = subparsers.add_parser("case-ingest")
    case_ingest_parser.add_argument("--pull-bat", required=True)
    case_ingest_parser.add_argument("--move-bat", required=True)
    case_ingest_parser.add_argument("--date", required=True)
    case_ingest_parser.add_argument("--server-root", required=True)
    case_ingest_parser.add_argument("--skip-upload", action="store_true")

    args = parser.parse_args()

    if args.command == "case-ingest":
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
```

- [ ] **Step 5: Run CLI and pipeline tests**

Run: `pytest tests/test_pipeline.py::test_main_supports_case_ingest_command tests/test_pipeline.py -v`
Expected: PASS for the new CLI test and the existing pipeline tests.

- [ ] **Step 6: Commit**

```bash
git add tests/test_pipeline.py video_tagging_assistant/cli.py
git commit -m "feat: add case ingest cli command"
```

### Task 9: Add end-to-end workflow validation for skip-existing uploads

**Files:**
- Modify: `tests/test_case_ingest_orchestrator.py`
- Modify: `video_tagging_assistant/case_ingest_orchestrator.py`
- Modify: `video_tagging_assistant/upload_worker.py`

- [ ] **Step 1: Write the failing orchestration test for existing server cases**

```python
def test_run_case_ingest_counts_existing_server_case_as_skipped(tmp_path: Path):
    case_root = tmp_path / "local" / "case_A_0078"
    server_case = tmp_path / "server" / "case_A_0078"
    server_case.mkdir(parents=True)
    task = CaseTask(
        case_id="case_A_0078",
        pull_task=PullTask(
            case_id="case_A_0078",
            device_path="/mnt/nvme/CapturedData/117",
            local_name=str(case_root / "case_A_0078_RK_raw_117"),
            move_src=str(case_root / "case_A_0078_RK_raw_117"),
            move_dst=str(case_root / "case_A_0078_RK_raw_117"),
        ),
        case_root_dir=case_root,
        server_case_dir=server_case,
    )

    summary = run_case_ingest(
        [task],
        pull_runner=StubPullWorker(),
        copy_runner=StubCopyWorker(),
        skip_upload=False,
    )

    assert summary["processed"] == 1
    assert summary["uploaded"] == 0
    assert summary["skipped"] == 1
    assert summary["upload_results"]["case_A_0078"].status == "upload_skipped_exists"
```

- [ ] **Step 2: Run the orchestrator tests to verify the new case fails**

Run: `pytest tests/test_case_ingest_orchestrator.py -v`
Expected: FAIL if skipped uploads are not counted correctly.

- [ ] **Step 3: Adjust upload result accounting to preserve skip-existing outcomes**

```python
        while not result_queue.empty():
            result = result_queue.get()
            upload_results[result.case_id] = result
            if result.status == "uploaded":
                uploaded += 1
            elif result.status == "upload_skipped_exists":
                skipped += 1
            else:
                failed += 1
```

- [ ] **Step 4: Run orchestration and upload tests**

Run: `pytest tests/test_case_ingest_orchestrator.py tests/test_upload_worker.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_case_ingest_orchestrator.py video_tagging_assistant/case_ingest_orchestrator.py video_tagging_assistant/upload_worker.py
git commit -m "fix: track skipped server uploads"
```

### Task 10: Run the focused test suite and verify spec coverage

**Files:**
- No code changes expected unless tests fail.

- [ ] **Step 1: Run the full case-ingest test suite**

Run: `pytest tests/test_config.py tests/test_case_ingest_models.py tests/test_bat_parser.py tests/test_pull_worker.py tests/test_copy_worker.py tests/test_upload_worker.py tests/test_case_ingest_orchestrator.py tests/test_pipeline.py -v`
Expected: PASS.

- [ ] **Step 2: Run the broader existing regression tests that touch unchanged paths**

Run: `pytest tests/test_provider.py tests/test_context_builder.py tests/test_excel_models.py tests/test_excel_workbook.py -v`
Expected: PASS.

- [ ] **Step 3: If any test fails, make the smallest fix and re-run only the failing test before re-running the full case-ingest suite**

```bash
pytest <failing-test-node> -v
pytest tests/test_config.py tests/test_case_ingest_models.py tests/test_bat_parser.py tests/test_pull_worker.py tests/test_copy_worker.py tests/test_upload_worker.py tests/test_case_ingest_orchestrator.py tests/test_pipeline.py -v
```

- [ ] **Step 4: Commit the final verified state**

```bash
git status --short
git add video_tagging_assistant/config.py video_tagging_assistant/case_ingest_models.py video_tagging_assistant/bat_parser.py video_tagging_assistant/pull_worker.py video_tagging_assistant/copy_worker.py video_tagging_assistant/upload_worker.py video_tagging_assistant/case_ingest_orchestrator.py video_tagging_assistant/cli.py tests/test_config.py tests/test_case_ingest_models.py tests/test_bat_parser.py tests/test_pull_worker.py tests/test_copy_worker.py tests/test_upload_worker.py tests/test_case_ingest_orchestrator.py tests/test_pipeline.py
git commit -m "test: verify case ingest workflow"
```

## Self-Review

- **Spec coverage:**
  - Single entrypoint: Task 8.
  - Pull/move bat parsing and case grouping: Task 3.
  - Resumable pull: Task 4.
  - RK raw validation: Task 4.
  - DJI copy from move bat: Task 5.
  - Whole-case upload after local completion: Tasks 6 and 7.
  - Skip upload when server case already exists: Tasks 6 and 9.
  - Pull/upload overlap with one upload thread: Task 7.
  - Per-case summary output: Tasks 7 and 8.
- **Placeholder scan:** No `TODO`, `TBD`, or “similar to” placeholders remain; every code-writing step includes concrete code.
- **Type consistency:** `PullTask`, `CopyTask`, `CaseTask`, and `UploadResult` names are introduced in Task 2 and used consistently afterward; `run_case_ingest()`, `upload_case_directory()`, `copy_declared_files()`, and `run_resumable_pull()` are defined before later references.
