# RK-DJI Alignment Preview Prebuild and Remote RK Scan Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix RK alignment candidate discovery for remote DUT roots and move DJI alignment preview generation into a configurable, non-blocking background preparation phase.

**Architecture:** Keep the existing `MainWindow -> AlignmentTab` flow and make `AlignmentTab.load_batch()` the point where preview preparation starts. RK candidate discovery remains in `rk_alignment_service.py`, but remote DUT scan is hardened to use `adb` explicitly. DJI preview extraction remains in `alignment_preview.py`, but its sampling rule changes from duration-based FPS sampling to fixed frame-step sampling, and a new GUI worker isolates the batch prebuild from the UI thread.

**Tech Stack:** Python 3, PyQt5 `QThread`, `concurrent.futures.ThreadPoolExecutor`, `subprocess`, `pathlib`, `pytest`

---

## File Map

- `video_tagging_assistant/rk_alignment_service.py`
  - Harden `scan_rk_candidates()` so `dut_root=/mnt/nvme/CapturedData` is scanned remotely through `adb` when it is not a real local directory.
  - Reuse the existing `.jpg` / `.jpeg` validity rule and local preview cache layout.
- `tests/test_rk_alignment_service.py`
  - Lock in remote DUT scan behavior, remote preview pull behavior, and remote scan summary logging.
- `video_tagging_assistant/alignment_preview.py`
  - Replace duration-based preview sampling with fixed-step frame selection.
  - Add pure config parsing helpers for `alignment_preview_frame_count`, `alignment_preview_skip_frames`, and `alignment_preview_workers`.
  - Host the shared alignment preview cache-key helpers used by both the worker and the tab.
- `tests/test_alignment_preview.py`
  - Replace old FPS-sampling assertions with fixed-step filter assertions and config fallback tests.
- `video_tagging_assistant/gui/alignment_preview_worker.py`
  - New dedicated background worker that prepares DJI previews off the UI thread and emits per-case results plus logs.
- `tests/test_alignment_preview_worker.py`
  - New worker-focused tests for success, failure, and config/log behavior.
- `video_tagging_assistant/gui/alignment_tab.py`
  - Remove on-demand `ffprobe/ffmpeg` work from row selection.
  - Track preparation state, consume worker signals, and only enable alignment actions after the batch preparation phase finishes.
- `tests/test_gui_alignment_tab.py`
  - Update the tab tests from “click triggers preview generation” to “load starts background preparation, row selection only renders prepared results”.
- `video_tagging_assistant/gui/main_window.py`
  - Add a small shutdown hook so the alignment preview worker is stopped before the window exits.
- `tests/test_gui_main_window.py`
  - Cover the alignment tab shutdown hook and keep the existing batch-load wiring assertions green.
- `configs/config.example.json`
  - Add the new preview-related top-level config keys.
- `docs/config-reference.md`
  - Document the new config keys and the remote RK scan requirement for `adb`.
- `README.md`
  - Update the operator-facing runtime requirements and alignment behavior notes.

---

### Task 1: Harden Remote RK Candidate Scan Through `adb`

**Files:**
- Modify: `video_tagging_assistant/rk_alignment_service.py`
- Test: `tests/test_rk_alignment_service.py`

- [ ] **Step 1: Write the failing tests**

Add these tests to `tests/test_rk_alignment_service.py`:

```python
def test_scan_rk_candidates_remote_root_uses_adb_find_and_pulls_preview(tmp_path: Path, monkeypatch):
    calls = []

    def fake_run(command, capture_output=False, text=False, encoding=None, errors=None, timeout=None, check=False):
        calls.append(command)
        if command == ["adb.exe", "shell", "find", "/mnt/nvme/CapturedData", "-mindepth", "1", "-maxdepth", "1", "-type", "d"]:
            return SimpleNamespace(
                returncode=0,
                stdout="/mnt/nvme/CapturedData/31\n/mnt/nvme/CapturedData/32x\n/mnt/nvme/CapturedData/CurrentIndex\n",
                stderr="",
            )
        if command == ["adb.exe", "shell", "find", "/mnt/nvme/CapturedData/31", "-maxdepth", "1", "-type", "f"]:
            return SimpleNamespace(
                returncode=0,
                stdout="/mnt/nvme/CapturedData/31/preview.jpg\n/mnt/nvme/CapturedData/31/rkraw.raw\n",
                stderr="",
            )
        if command == ["adb.exe", "shell", "find", "/mnt/nvme/CapturedData/32x", "-maxdepth", "1", "-type", "f"]:
            return SimpleNamespace(
                returncode=0,
                stdout="/mnt/nvme/CapturedData/32x/rkraw.raw\n",
                stderr="",
            )
        if command[:2] == ["adb.exe", "pull"]:
            local_preview = Path(command[3])
            local_preview.parent.mkdir(parents=True, exist_ok=True)
            local_preview.write_bytes(b"jpeg")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr("video_tagging_assistant.rk_alignment_service.subprocess.run", fake_run)

    source_root, candidates, bad_logs = scan_rk_candidates("", "/mnt/nvme/CapturedData", adb_exe="adb.exe")

    assert str(source_root).replace("\\\\", "/").endswith("/mnt/nvme/CapturedData")
    assert [candidate.folder_name for candidate in candidates] == ["31"]
    assert candidates[0].preview_path.exists()
    assert any("32x" in log for log in bad_logs)
    assert any("found 2 numeric directories, 1 valid RK candidates" in log for log in bad_logs)
    assert ["adb.exe", "shell", "find", "/mnt/nvme/CapturedData", "-mindepth", "1", "-maxdepth", "1", "-type", "d"] in calls


def test_scan_rk_candidates_remote_root_keeps_remote_summary_when_no_valid_candidates(tmp_path: Path, monkeypatch):
    def fake_run(command, capture_output=False, text=False, encoding=None, errors=None, timeout=None, check=False):
        if command == ["adb.exe", "shell", "find", "/mnt/nvme/CapturedData", "-mindepth", "1", "-maxdepth", "1", "-type", "d"]:
            return SimpleNamespace(
                returncode=0,
                stdout="/mnt/nvme/CapturedData/31\n/mnt/nvme/CapturedData/32x\n",
                stderr="",
            )
        if command in [
            ["adb.exe", "shell", "find", "/mnt/nvme/CapturedData/31", "-maxdepth", "1", "-type", "f"],
            ["adb.exe", "shell", "find", "/mnt/nvme/CapturedData/32x", "-maxdepth", "1", "-type", "f"],
        ]:
            return SimpleNamespace(returncode=0, stdout="/mnt/nvme/CapturedData/31/rkraw.raw\n", stderr="")
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr("video_tagging_assistant.rk_alignment_service.subprocess.run", fake_run)

    source_root, candidates, bad_logs = scan_rk_candidates("", "/mnt/nvme/CapturedData", adb_exe="adb.exe")

    assert str(source_root).replace("\\\\", "/").endswith("/mnt/nvme/CapturedData")
    assert candidates == []
    assert any("found 2 numeric directories, 0 valid RK candidates" in log for log in bad_logs)
```

- [ ] **Step 2: Run the targeted tests to verify they fail**

Run:

```powershell
pytest tests\test_rk_alignment_service.py -q -k "remote_root_uses_adb_find or remote_root_keeps_remote_summary"
```

Expected: FAIL because the current implementation still shells out through `ls -1` and does not guarantee the remote summary survives the local `Path` fallback logic.

- [ ] **Step 3: Implement the minimal remote-scan fix**

Update `video_tagging_assistant/rk_alignment_service.py` along these lines:

```python
def scan_rk_candidates(temp_root: str, dut_root: str, adb_exe: str = "adb") -> Tuple[Path | None, list[RkCandidate], list[str]]:
    temp_path = _optional_root_path(temp_root)
    normalized_dut_root = str(dut_root or "").strip()
    dut_path = _optional_root_path(normalized_dut_root)

    temp_candidates, temp_logs = _scan_candidate_root(temp_path)
    if temp_candidates:
        return temp_path, temp_candidates, temp_logs

    if dut_path is not None and dut_path.exists() and dut_path.is_dir():
        dut_candidates, dut_logs = _scan_candidate_root(dut_path)
        logs = temp_logs + dut_logs
        if not dut_candidates:
            logs.append(_empty_candidate_summary(dut_path))
        return dut_path, dut_candidates, logs

    if normalized_dut_root:
        remote_source_root = Path(normalized_dut_root)
        dut_candidates, dut_logs = _scan_remote_candidate_root(normalized_dut_root, adb_exe)
        return remote_source_root, dut_candidates, temp_logs + dut_logs

    if temp_path is not None:
        return temp_path, temp_candidates, temp_logs + [_empty_candidate_summary(temp_path)]
    return None, [], temp_logs


def _adb_find(adb_exe: str, *find_args: str) -> list[str]:
    result = subprocess.run(
        [adb_exe, "shell", "find", *find_args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"adb shell find failed for {' '.join(find_args)}")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _scan_remote_candidate_root(root_value: str, adb_exe: str) -> Tuple[list[RkCandidate], list[str]]:
    entries = _adb_find(adb_exe, root_value, "-mindepth", "1", "-maxdepth", "1", "-type", "d")
    matched_directory_names = [
        Path(entry).name
        for entry in entries
        if _RK_DIR_PATTERN.fullmatch(Path(entry).name)
    ]
    matched_directory_names.sort(key=lambda name: (int(_strip_x_suffix(name)), 1 if name.endswith("x") else 0, name))

    candidates = []
    bad_logs = []
    for folder_name in matched_directory_names:
        preview_name = _find_remote_preview_name(adb_exe, root_value, folder_name)
        if preview_name is None:
            bad_logs.append(f"RK candidate {folder_name} under {root_value} is missing a preview jpg/jpeg file")
            continue
        preview_path = _pull_remote_preview(adb_exe, root_value, folder_name, preview_name)
        candidates.append(
            RkCandidate(
                folder_name=folder_name,
                folder_path=Path(root_value) / folder_name,
                preview_path=preview_path,
                numeric_value=int(_strip_x_suffix(folder_name)),
                has_x_suffix=folder_name.endswith("x"),
            )
        )
    bad_logs.append(
        f"RK scan root {root_value}: found {len(matched_directory_names)} numeric directories, {len(candidates)} valid RK candidates"
    )
    candidates.sort(key=_candidate_sort_key)
    return candidates, bad_logs


def _find_remote_preview_name(adb_exe: str, root_value: str, folder_name: str) -> str | None:
    file_entries = _adb_find(adb_exe, f"{root_value}/{folder_name}", "-maxdepth", "1", "-type", "f")
    for child_name in sorted((Path(entry).name for entry in file_entries), key=str.lower):
        if Path(child_name).suffix.lower() in {".jpg", ".jpeg"}:
            return child_name
    return None
```

Keep `_pull_remote_preview()` and the existing `.jpg` / `.jpeg` suffix rule. Do not touch the monotonic alignment-state logic in this task.

- [ ] **Step 4: Run the remote-scan tests again**

Run:

```powershell
pytest tests\test_rk_alignment_service.py -q -k "remote_root_uses_adb_find or remote_root_keeps_remote_summary"
```

Expected: PASS with both new tests green.

- [ ] **Step 5: Commit the remote scan fix**

```powershell
git add tests/test_rk_alignment_service.py video_tagging_assistant/rk_alignment_service.py
git commit -m "fix: scan remote rk candidates through adb"
```

---

### Task 2: Replace Duration-Based Preview Sampling With Fixed-Step Sampling

**Files:**
- Modify: `video_tagging_assistant/alignment_preview.py`
- Test: `tests/test_alignment_preview.py`

- [ ] **Step 1: Write the failing tests**

Replace the old FPS-oriented assertions in `tests/test_alignment_preview.py` with these tests:

```python
def test_build_dji_preview_frames_uses_fixed_step_selection(tmp_path: Path, monkeypatch):
    video_path = tmp_path / "clip.mp4"
    output_dir = tmp_path / "preview_frames"
    video_path.write_bytes(b"video")
    output_dir.mkdir()
    (output_dir / "old.txt").write_text("stale", encoding="utf-8")

    calls = []

    def fake_run(command, check, capture_output=False, text=False):
        calls.append(command)
        if command[0] == "ffprobe":
            return SimpleNamespace(stdout="codec_name=h264\nwidth=1920\nheight=1080\n")
        if command[0] == "ffmpeg":
            for frame_name in ("frame_002.jpg", "frame_000.jpg", "frame_001.jpg"):
                (output_dir / frame_name).write_bytes(b"jpeg")
            return SimpleNamespace(stdout="")
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr("video_tagging_assistant.alignment_preview.subprocess.run", fake_run)

    frames = build_dji_preview_frames(
        video_path=video_path,
        output_dir=output_dir,
        ffprobe_exe="ffprobe",
        ffmpeg_exe="ffmpeg",
        frame_count=4,
        skip_frames=2,
    )

    assert calls[0][0] == "ffprobe"
    assert calls[1][0] == "ffmpeg"
    assert calls[1][calls[1].index("-vf") + 1] == "select=not(mod(n\\,3))"
    assert "-vsync" in calls[1]
    assert calls[1][calls[1].index("-frames:v") + 1] == "4"
    assert not (output_dir / "old.txt").exists()
    assert [frame.name for frame in frames] == ["frame_000.jpg", "frame_001.jpg", "frame_002.jpg"]


def test_resolve_alignment_preview_settings_falls_back_for_invalid_values():
    frame_count, skip_frames, workers, logs = resolve_alignment_preview_settings(
        {
            "alignment_preview_frame_count": "bad",
            "alignment_preview_skip_frames": -1,
            "alignment_preview_workers": 0,
        }
    )

    assert (frame_count, skip_frames, workers) == (30, 2, 2)
    assert any("alignment_preview_frame_count" in log for log in logs)
    assert any("alignment_preview_skip_frames" in log for log in logs)
    assert any("alignment_preview_workers" in log for log in logs)
```

Keep the existing cache-reuse and missing-source tests, but update their call sites to pass `skip_frames=2`.

- [ ] **Step 2: Run the preview tests to verify they fail**

Run:

```powershell
pytest tests\test_alignment_preview.py -q
```

Expected: FAIL because `build_dji_preview_frames()` still computes `fps=<duration-derived-value>` and there is no `resolve_alignment_preview_settings()` helper yet.

- [ ] **Step 3: Implement fixed-step preview generation and pure config parsing**

Update `video_tagging_assistant/alignment_preview.py` along these lines:

```python
DEFAULT_ALIGNMENT_PREVIEW_FRAME_COUNT = 30
DEFAULT_ALIGNMENT_PREVIEW_SKIP_FRAMES = 2
DEFAULT_ALIGNMENT_PREVIEW_WORKERS = 2


def resolve_alignment_preview_settings(config: Mapping[str, object]) -> tuple[int, int, int, list[str]]:
    logs: list[str] = []
    frame_count = _positive_int(config.get("alignment_preview_frame_count"), DEFAULT_ALIGNMENT_PREVIEW_FRAME_COUNT, "alignment_preview_frame_count", logs)
    skip_frames = _non_negative_int(config.get("alignment_preview_skip_frames"), DEFAULT_ALIGNMENT_PREVIEW_SKIP_FRAMES, "alignment_preview_skip_frames", logs)
    workers = _positive_int(config.get("alignment_preview_workers"), DEFAULT_ALIGNMENT_PREVIEW_WORKERS, "alignment_preview_workers", logs)
    return frame_count, skip_frames, workers, logs


def _positive_int(raw_value: object, default: int, key: str, logs: list[str]) -> int:
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        logs.append(f"{key}={raw_value!r} is invalid; using {default}")
        return default
    if value < 1:
        logs.append(f"{key}={raw_value!r} is invalid; using {default}")
        return default
    return value


def _non_negative_int(raw_value: object, default: int, key: str, logs: list[str]) -> int:
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        logs.append(f"{key}={raw_value!r} is invalid; using {default}")
        return default
    if value < 0:
        logs.append(f"{key}={raw_value!r} is invalid; using {default}")
        return default
    return value


def _probe_video_stream(video_path: Path, ffprobe_exe: str) -> str:
    result = subprocess.run(
        [
            ffprobe_exe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,width,height",
            "-of",
            "default=noprint_wrappers=1",
            str(video_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    stream_text = result.stdout.strip()
    if not stream_text:
        raise ValueError(f"invalid ffprobe stream output for {video_path}: {stream_text!r}")
    return stream_text


def build_alignment_preview_cache_key(manifest) -> str:
    identity = "|".join([str(manifest.case_id), str(manifest.vs_normal_path), str(manifest.vs_night_path)])
    digest = hashlib.sha1(identity.encode("utf-8")).hexdigest()[:12]
    return f"{manifest.case_id}_{digest}"


def build_alignment_preview_cache_root(manifest) -> Path:
    return Path("artifacts") / "alignment_previews" / build_alignment_preview_cache_key(manifest)


def build_dji_preview_frames(
    video_path: Path,
    output_dir: Path,
    ffprobe_exe: str,
    ffmpeg_exe: str,
    frame_count: int = DEFAULT_ALIGNMENT_PREVIEW_FRAME_COUNT,
    skip_frames: int = DEFAULT_ALIGNMENT_PREVIEW_SKIP_FRAMES,
) -> List[Path]:
    if not Path(video_path).exists():
        raise FileNotFoundError(f"DJI preview source does not exist: {video_path}")

    cached_frames = sorted(output_dir.glob("frame_*.jpg"))
    if len(cached_frames) >= frame_count:
        return cached_frames[:frame_count]

    if output_dir.exists():
        for child in output_dir.iterdir():
            if child.is_file():
                child.unlink()
    output_dir.mkdir(parents=True, exist_ok=True)

    _probe_video_stream(video_path, ffprobe_exe)
    step = skip_frames + 1
    output_pattern = output_dir / "frame_%03d.jpg"
    subprocess.run(
        [
            ffmpeg_exe,
            "-y",
            "-i",
            str(video_path),
            "-vf",
            f"select=not(mod(n\\,{step}))",
            "-vsync",
            "vfr",
            "-frames:v",
            str(frame_count),
            str(output_pattern),
        ],
        check=True,
    )
    return sorted(output_dir.glob("frame_*.jpg"))
```

- [ ] **Step 4: Run the preview tests again**

Run:

```powershell
pytest tests\test_alignment_preview.py -q
```

Expected: PASS with the fixed-step sampling and config fallback behavior covered.

- [ ] **Step 5: Commit the preview-sampling change**

```powershell
git add tests/test_alignment_preview.py video_tagging_assistant/alignment_preview.py
git commit -m "feat: use fixed-step alignment preview sampling"
```

---

### Task 3: Add Background Preview Preparation And Remove On-Demand Preview Generation From The UI Thread

**Files:**
- Create: `video_tagging_assistant/gui/alignment_preview_worker.py`
- Modify: `video_tagging_assistant/gui/alignment_tab.py`
- Test: `tests/test_alignment_preview_worker.py`
- Test: `tests/test_gui_alignment_tab.py`

- [ ] **Step 1: Write the failing worker and tab tests**

Create `tests/test_alignment_preview_worker.py`:

```python
from pathlib import Path

from PyQt5.QtWidgets import QApplication

from video_tagging_assistant.pipeline_models import CaseManifest

_APP = QApplication.instance() or QApplication([])


def _make_manifest(tmp_path: Path, row_index: int = 3, case_id: str = "case_A_0001") -> CaseManifest:
    return CaseManifest(
        case_id=case_id,
        row_index=row_index,
        created_date="20260508",
        mode="OV50H40_Action5Pro_DCG HDR",
        raw_path=Path(""),
        vs_normal_path=tmp_path / f"{case_id}_normal.mp4",
        vs_night_path=tmp_path / f"{case_id}_night.mp4",
        local_case_root=tmp_path / "local" / case_id,
        server_case_dir=tmp_path / "server" / case_id,
        remark="",
        labels={},
    )


def test_alignment_preview_worker_emits_ready_payload(monkeypatch, tmp_path: Path):
    from video_tagging_assistant.gui.alignment_preview_worker import AlignmentPreviewWorker

    manifest = _make_manifest(tmp_path)
    manifest.vs_normal_path.write_bytes(b"video")
    manifest.vs_night_path.write_bytes(b"video")

    def fake_build(video_path: Path, output_dir: Path, ffprobe_exe: str, ffmpeg_exe: str, frame_count: int = 30, skip_frames: int = 2):
        output_dir.mkdir(parents=True, exist_ok=True)
        frame_path = output_dir / "frame_000.jpg"
        frame_path.write_bytes(b"jpeg")
        return [frame_path]

    monkeypatch.setattr("video_tagging_assistant.gui.alignment_preview_worker.build_dji_preview_frames", fake_build)

    worker = AlignmentPreviewWorker(
        {"ffprobe_exe": "ffprobe", "ffmpeg_exe": "ffmpeg", "alignment_preview_workers": 1},
        [manifest],
    )
    case_updates = []
    summaries = []

    worker.case_prepared.connect(case_updates.append)
    worker.preparation_finished.connect(lambda ready_count, failed_count: summaries.append((ready_count, failed_count)))
    worker.run()

    assert case_updates[0]["row_index"] == manifest.row_index
    assert case_updates[0]["status"] == "ready"
    assert len(case_updates[0]["normal_frames"]) == 1
    assert len(case_updates[0]["night_frames"]) == 1
    assert summaries[-1] == (1, 0)


def test_alignment_preview_worker_emits_failure_payload(monkeypatch, tmp_path: Path):
    from video_tagging_assistant.gui.alignment_preview_worker import AlignmentPreviewWorker

    manifest = _make_manifest(tmp_path)

    def fake_build(*args, **kwargs):
        raise FileNotFoundError("missing preview input")

    monkeypatch.setattr("video_tagging_assistant.gui.alignment_preview_worker.build_dji_preview_frames", fake_build)

    worker = AlignmentPreviewWorker(
        {"ffprobe_exe": "ffprobe", "ffmpeg_exe": "ffmpeg", "alignment_preview_workers": 1},
        [manifest],
    )
    case_updates = []
    summaries = []

    worker.case_prepared.connect(case_updates.append)
    worker.preparation_finished.connect(lambda ready_count, failed_count: summaries.append((ready_count, failed_count)))
    worker.run()

    assert case_updates[0]["row_index"] == manifest.row_index
    assert case_updates[0]["status"] == "failed"
    assert "missing preview input" in case_updates[0]["error"]
    assert summaries[-1] == (0, 1)
```

Add these tests to `tests/test_gui_alignment_tab.py`:

```python
def test_alignment_tab_load_batch_starts_background_prepare_and_disables_confirm_until_finished(tmp_path: Path, monkeypatch):
    import video_tagging_assistant.gui.alignment_tab as alignment_tab_module

    monkeypatch.chdir(tmp_path)
    manifest = _make_manifest(tmp_path)
    candidates = _make_candidates(tmp_path / "rk-source", "31")
    state = build_alignment_batch_state(
        manifests=[manifest],
        rk_raw_by_row={manifest.row_index: ""},
        candidates=candidates,
        bad_directory_logs=[],
    )

    class FakeWorker:
        def __init__(self, config, manifests, parent=None):
            self.case_prepared = _Signal()
            self.log_emitted = _Signal()
            self.preparation_finished = _Signal()
        def start(self):
            self.log_emitted.emit("alignment preview prepare start: 1 cases")
            self.case_prepared.emit(
                {
                    "row_index": manifest.row_index,
                    "status": "ready",
                    "normal_frames": [],
                    "night_frames": [],
                    "error": "",
                }
            )
        def stop(self):
            return None
        def wait(self, msecs=None):
            return True

    monkeypatch.setattr(alignment_tab_module, "AlignmentPreviewWorker", FakeWorker)

    tab = alignment_tab_module.AlignmentTab(_CONFIG)
    tab.load_batch([manifest], tmp_path / "source.xlsx", tmp_path / "writeback.xlsx", state)

    assert not tab._confirm_btn.isEnabled()
    tab._preview_worker.preparation_finished.emit(1, 0)
    assert tab._preview_preparing is False


def test_alignment_tab_row_selection_uses_prepared_frames_without_invoking_builder(tmp_path: Path, monkeypatch):
    import video_tagging_assistant.gui.alignment_tab as alignment_tab_module

    monkeypatch.chdir(tmp_path)
    manifest = _make_manifest(tmp_path)
    candidates = _make_candidates(tmp_path / "rk-source", "31")
    state = build_alignment_batch_state(
        manifests=[manifest],
        rk_raw_by_row={manifest.row_index: ""},
        candidates=candidates,
        bad_directory_logs=[],
    )

    class FakeWorker:
        def __init__(self, config, manifests, parent=None):
            self.case_prepared = _Signal()
            self.log_emitted = _Signal()
            self.preparation_finished = _Signal()
        def start(self):
            normal_frame = tmp_path / "normal_frame_000.jpg"
            night_frame = tmp_path / "night_frame_000.jpg"
            pixmap = QPixmap(24, 24)
            pixmap.fill()
            pixmap.save(str(normal_frame), "JPG")
            pixmap.save(str(night_frame), "JPG")
            self.case_prepared.emit(
                {
                    "row_index": manifest.row_index,
                    "status": "ready",
                    "normal_frames": [normal_frame],
                    "night_frames": [night_frame],
                    "error": "",
                }
            )
            self.preparation_finished.emit(1, 0)
        def stop(self):
            return None
        def wait(self, msecs=None):
            return True

    monkeypatch.setattr(alignment_tab_module, "AlignmentPreviewWorker", FakeWorker)

    tab = alignment_tab_module.AlignmentTab(_CONFIG)
    tab.load_batch([manifest], tmp_path / "source.xlsx", tmp_path / "writeback.xlsx", state)

    assert tab._normal_preview_list.count() == 1
    assert tab._night_preview_list.count() == 1
    assert tab._confirm_btn.isEnabled()
```

Add this tiny helper once near the top of `tests/test_gui_alignment_tab.py` so the fake worker can mimic Qt signals:

```python
class _Signal:
    def __init__(self):
        self._callbacks = []

    def connect(self, callback):
        self._callbacks.append(callback)

    def emit(self, *args, **kwargs):
        for callback in list(self._callbacks):
            callback(*args, **kwargs)
```

- [ ] **Step 2: Run the worker and tab tests to verify they fail**

Run:

```powershell
pytest tests\test_alignment_preview_worker.py tests\test_gui_alignment_tab.py -q
```

Expected: FAIL because there is no `AlignmentPreviewWorker` module yet and `AlignmentTab` still calls `build_dji_preview_frames()` directly from `_show_case_by_index()`.

- [ ] **Step 3: Implement the worker and convert the tab to prepared-preview rendering**

Create `video_tagging_assistant/gui/alignment_preview_worker.py`:

```python
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from PyQt5.QtCore import QThread, pyqtSignal

from video_tagging_assistant.alignment_preview import (
    build_alignment_preview_cache_root,
    build_dji_preview_frames,
    resolve_alignment_preview_settings,
)


class AlignmentPreviewWorker(QThread):
    case_prepared = pyqtSignal(object)
    log_emitted = pyqtSignal(str)
    preparation_finished = pyqtSignal(int, int)

    def __init__(self, config: dict, manifests: list, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._manifests = list(manifests)
        self._cancelled = False

    def stop(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        frame_count, skip_frames, workers, fallback_logs = resolve_alignment_preview_settings(self._config)
        for line in fallback_logs:
            self.log_emitted.emit(line)
        self.log_emitted.emit(f"alignment preview prepare start: {len(self._manifests)} cases")

        ready_count = 0
        failed_count = 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            future_map = {
                pool.submit(self._prepare_case, manifest, frame_count, skip_frames): manifest
                for manifest in self._manifests
            }
            for future in as_completed(future_map):
                if self._cancelled:
                    break
                manifest = future_map[future]
                try:
                    payload = future.result()
                except Exception as exc:
                    failed_count += 1
                    self.log_emitted.emit(
                        f"{manifest.case_id} preview generation failed with ffprobe={self._config.get('ffprobe_exe', 'ffprobe')} "
                        f"ffmpeg={self._config.get('ffmpeg_exe', 'ffmpeg')}: {exc}"
                    )
                    self.case_prepared.emit(
                        {
                            "row_index": manifest.row_index,
                            "status": "failed",
                            "normal_frames": [],
                            "night_frames": [],
                            "error": str(exc),
                        }
                    )
                    continue
                ready_count += 1
                self.case_prepared.emit(payload)
                self.log_emitted.emit(f"{manifest.case_id} preview ready")

        self.log_emitted.emit(
            f"alignment preview prepare complete: {ready_count} cases ready, {failed_count} cases failed"
        )
        self.preparation_finished.emit(ready_count, failed_count)

    def _prepare_case(self, manifest, frame_count: int, skip_frames: int) -> dict:
        cache_root = build_alignment_preview_cache_root(manifest)
        ffprobe_exe = self._config.get("ffprobe_exe", "ffprobe")
        ffmpeg_exe = self._config.get("ffmpeg_exe", "ffmpeg")
        normal_frames = build_dji_preview_frames(
            Path(manifest.vs_normal_path),
            cache_root / "normal",
            ffprobe_exe,
            ffmpeg_exe,
            frame_count=frame_count,
            skip_frames=skip_frames,
        )
        night_frames = build_dji_preview_frames(
            Path(manifest.vs_night_path),
            cache_root / "night",
            ffprobe_exe,
            ffmpeg_exe,
            frame_count=frame_count,
            skip_frames=skip_frames,
        )
        return {
            "row_index": manifest.row_index,
            "status": "ready",
            "normal_frames": normal_frames,
            "night_frames": night_frames,
            "error": "",
        }
```

Then refactor `video_tagging_assistant/gui/alignment_tab.py` so it owns the preparation lifecycle instead of running `ffprobe/ffmpeg` on selection:

```python
from video_tagging_assistant.alignment_preview import build_alignment_preview_cache_root
from video_tagging_assistant.gui.alignment_preview_worker import AlignmentPreviewWorker


class AlignmentTab(QWidget):
    def __init__(self, config: dict, parent=None) -> None:
        ...
        self._preview_status_by_row = {}
        self._preview_frames_by_row = {}
        self._preview_errors_by_row = {}
        self._preview_preparing = False
        self._preview_worker = None
        ...

    def load_batch(self, manifests, workbook_path: Path, writeback_workbook_path: Path, initial_state) -> None:
        ...
        self._preview_status_by_row = {}
        self._preview_frames_by_row = {}
        self._preview_errors_by_row = {}
        self._stop_preview_worker()
        self._preview_preparing = bool(self._display_cases() or getattr(initial_state, "pending_cases", []))
        self._render()
        self._start_preview_prepare()

    def shutdown(self) -> None:
        self._stop_preview_worker()

    def _start_preview_prepare(self) -> None:
        preview_manifests = [case.manifest for case in self._display_cases()]
        if not preview_manifests:
            self._preview_preparing = False
            return
        self._preview_worker = AlignmentPreviewWorker(self._config, preview_manifests, parent=self)
        self._preview_worker.case_prepared.connect(self._on_case_prepared)
        self._preview_worker.log_emitted.connect(self._append_log)
        self._preview_worker.preparation_finished.connect(self._on_preparation_finished)
        self._preview_worker.start()

    def _stop_preview_worker(self) -> None:
        if self._preview_worker is None:
            return
        self._preview_worker.stop()
        self._preview_worker.wait(3000)
        self._preview_worker = None

    def _on_case_prepared(self, payload: dict) -> None:
        row_index = payload["row_index"]
        self._preview_status_by_row[row_index] = payload["status"]
        self._preview_frames_by_row[row_index] = {
            "normal": list(payload.get("normal_frames", [])),
            "night": list(payload.get("night_frames", [])),
        }
        self._preview_errors_by_row[row_index] = str(payload.get("error", ""))
        current_case = self._current_case()
        if current_case is not None and current_case.manifest.row_index == row_index:
            self._show_case_by_index(self._queue_list.currentRow())

    def _on_preparation_finished(self, ready_count: int, failed_count: int) -> None:
        self._preview_preparing = False
        self._render_logs()
        current_case = self._current_case()
        if current_case is not None:
            self._show_case_by_index(self._queue_list.currentRow())

    def _show_case_by_index(self, index: int) -> None:
        ...
        case = self._displayed_cases[index]
        status = self._preview_status_by_row.get(case.manifest.row_index, "pending")
        if status == "ready":
            prepared = self._preview_frames_by_row.get(case.manifest.row_index, {"normal": [], "night": []})
            self._populate_preview_list(self._normal_preview_list, prepared["normal"])
            self._populate_preview_list(self._night_preview_list, prepared["night"])
            self._refresh_candidate_widgets(case, update_rk_preview=True)
            return
        if status == "failed":
            self._normal_preview_list.clear()
            self._night_preview_list.clear()
            self._rk_preview_label.clear()
            self._rk_preview_label.setText("预览生成失败，请检查 DJI 视频")
            self._refresh_candidate_widgets(case, update_rk_preview=False)
            self._sync_buttons(case, self._candidate_by_index(self._current_candidate_index(case)))
            return

        self._normal_preview_list.clear()
        self._night_preview_list.clear()
        self._rk_preview_label.clear()
        self._rk_preview_label.setText("预览准备中")
        self._refresh_candidate_widgets(case, update_rk_preview=False)

    def _sync_buttons(self, case, candidate) -> None:
        ...
        preview_ready = has_case and self._preview_status_by_row.get(case.manifest.row_index) == "ready"
        self._confirm_btn.setEnabled(has_case and has_candidate and preview_ready and not self._preview_preparing)
```

Keep the existing workbook writeback calls, monotonic `confirm_alignment()` guards, and candidate-navigation behavior. This task only changes *when* DJI previews are generated and *how* the tab consumes them.

- [ ] **Step 4: Run the worker and tab tests again**

Run:

```powershell
pytest tests\test_alignment_preview_worker.py tests\test_gui_alignment_tab.py -q
```

Expected: PASS with no `ffprobe/ffmpeg` work triggered from row-selection handlers anymore.

- [ ] **Step 5: Commit the background preview preparation change**

```powershell
git add tests/test_alignment_preview_worker.py tests/test_gui_alignment_tab.py video_tagging_assistant/gui/alignment_preview_worker.py video_tagging_assistant/gui/alignment_tab.py
git commit -m "feat: prebuild alignment previews in background"
```

---

### Task 4: Wire Shutdown, Document Config, And Run The Touched Regression Suite

**Files:**
- Modify: `video_tagging_assistant/gui/main_window.py`
- Test: `tests/test_gui_main_window.py`
- Modify: `configs/config.example.json`
- Modify: `docs/config-reference.md`
- Modify: `README.md`

- [ ] **Step 1: Write the failing integration and documentation-facing tests**

Add this test to `tests/test_gui_main_window.py`:

```python
def test_main_window_close_event_stops_alignment_preview_background_work():
    window = _make_window()
    window._alignment_tab.shutdown = MagicMock()

    event = MagicMock()
    with patch("PyQt5.QtWidgets.QMainWindow.closeEvent") as mock_super_close_event:
        window.closeEvent(event)

    window._alignment_tab.shutdown.assert_called_once_with()
    mock_super_close_event.assert_called_once_with(event)
```

Then extend `configs/config.example.json` in the plan with these new keys:

```json
{
  "ffprobe_exe": "ffprobe",
  "ffmpeg_exe": "ffmpeg",
  "alignment_preview_frame_count": 30,
  "alignment_preview_skip_frames": 2,
  "alignment_preview_workers": 2
}
```

Update `docs/config-reference.md` so the top-level field table explicitly includes:

```markdown
| `ffprobe_exe` | string | `"ffprobe"` | DJI 对齐预览探测命令。可填 PATH 中的可执行名，或完整路径。 |
| `ffmpeg_exe` | string | `"ffmpeg"` | DJI 对齐预览抽帧命令。可填 PATH 中的可执行名，或完整路径。 |
| `alignment_preview_frame_count` | int | `30` | 每个 DJI 视频最多生成多少张对齐预览图。 |
| `alignment_preview_skip_frames` | int | `2` | 每抽取 1 帧后固定跳过多少原始帧；`2` 表示选取 `0,3,6,9...`。 |
| `alignment_preview_workers` | int | `2` | 对齐预览后台预生成的最大并发任务数。 |
```

Update `README.md` so the runtime requirements and workflow note include:

```markdown
- `adb.exe`（当 `dut_root` 是设备侧路径时必须可调用）
- `ffprobe.exe` / `ffmpeg.exe`（对齐预览后台预生成依赖）

加载批次后，GUI 会在后台预生成 DJI 对齐预览图；只有预生成阶段结束后，对齐页才允许确认 RK。
```

- [ ] **Step 2: Run the new main-window test to verify it fails**

Run:

```powershell
pytest tests\test_gui_main_window.py -q -k "close_event_stops_alignment_preview_background_work"
```

Expected: FAIL because `MainWindow.closeEvent()` currently stops only `ExecutionWorker` and does not shut down any alignment-preview background work.

- [ ] **Step 3: Implement the shutdown hook and documentation/config updates**

Update `video_tagging_assistant/gui/main_window.py`:

```python
def closeEvent(self, event) -> None:
    self._alignment_tab.shutdown()
    self._worker.stop()
    self._worker.wait(3000)
    super().closeEvent(event)
```

Then apply the config/docs updates exactly as shown in Step 1.

- [ ] **Step 4: Run the full touched-area regression suite**

Run:

```powershell
pytest tests\test_rk_alignment_service.py tests\test_alignment_preview.py tests\test_alignment_preview_worker.py tests\test_gui_alignment_tab.py tests\test_gui_main_window.py -q
```

Expected: PASS across the remote RK scan, fixed-step preview generation, background prebuild, tab behavior, and window shutdown coverage.

- [ ] **Step 5: Commit the integration/docs update**

```powershell
git add README.md configs/config.example.json docs/config-reference.md tests/test_gui_main_window.py video_tagging_assistant/gui/main_window.py
git commit -m "docs: add alignment preview preparation config"
```

---

## Coverage Check

- Remote `dut_root` scan through `adb` plus local preview cache pull: covered by Task 1.
- Configurable `alignment_preview_frame_count`, `alignment_preview_skip_frames`, and `alignment_preview_workers`: covered by Task 2 pure helpers and Task 4 docs/config updates.
- Fixed-step frame selection replacing duration-based sampling: covered by Task 2.
- Background preview preparation with non-blocking UI: covered by Task 3.
- Alignment actions disabled until preparation completes: covered by Task 3 tab tests.
- Operator-visible logs for preparation success/failure and fallback config: covered by Task 2 helper logs and Task 3 worker/tab signal flow.
- README and config-reference updates for `adb`, `ffprobe`, and `ffmpeg` requirements: covered by Task 4.
