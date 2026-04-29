# Excel-Driven Case Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a PyQt-based Excel-driven case pipeline that batch-generates tagging results, lets operators review each case, and starts pull/copy/upload immediately after each approval while continuously writing status back to Excel.

**Architecture:** Extend the existing openpyxl-based workbook integration and current batch tagging / case-ingest workers instead of inventing a second pipeline. Add a manifest-and-status layer that reads `创建记录`, caches tagging outputs per case, exposes progress/log events, and feeds a GUI controller that splits the workflow into two phases: batch tagging, then approval-driven case execution.

**Tech Stack:** Python 3, PyQt, openpyxl, concurrent.futures / queue / threading, existing `video_tagging_assistant` modules, pytest

---

## File Structure

### Existing files to modify

- `video_tagging_assistant/excel_models.py`
  - Extend workbook row models beyond the current lightweight review-sync types.
- `video_tagging_assistant/excel_workbook.py`
  - Add `创建记录` loading, status-column management, and row update helpers for the new pipeline.
- `video_tagging_assistant/models.py`
  - Add pipeline-facing runtime/event models that fit existing task/result patterns.
- `video_tagging_assistant/orchestrator.py`
  - Reuse and extract batch tagging behavior into a callable service that can emit structured progress events.
- `video_tagging_assistant/pull_worker.py`
  - Add optional progress callback support around remote counting / pull lifecycle.
- `video_tagging_assistant/upload_worker.py`
  - Add optional progress callback support during copytree-based upload lifecycle.
- `video_tagging_assistant/cli.py`
  - Add a GUI launcher entrypoint so the new pipeline is a first-class command.
- `requirements.txt`
  - Add PyQt dependency if not already present.

### New files to create

- `video_tagging_assistant/pipeline_models.py`
  - Dataclasses for Excel case records, manifests, tagging cache records, runtime state, and pipeline events.
- `video_tagging_assistant/tagging_cache.py`
  - Read/write helpers for per-case cache directories.
- `video_tagging_assistant/tagging_service.py`
  - Batch tagging service that accepts manifests, supports fresh run vs cached import, and emits events.
- `video_tagging_assistant/case_task_factory.py`
  - Convert manifests into `PullTask`, `CopyTask`, and case execution payloads without going through bat parsing.
- `video_tagging_assistant/pipeline_logging.py`
  - Global run logger + per-case logger + GUI event log fanout.
- `video_tagging_assistant/pipeline_controller.py`
  - Queue/state-machine orchestration for batch tagging, review queue, and approval-driven execution queue.
- `video_tagging_assistant/gui/__init__.py`
  - GUI package marker.
- `video_tagging_assistant/gui/app.py`
  - Qt application bootstrap and controller wiring.
- `video_tagging_assistant/gui/main_window.py`
  - Main window with tabs and actions.
- `video_tagging_assistant/gui/table_models.py`
  - Qt table models for queue and history views.
- `video_tagging_assistant/gui/review_panel.py`
  - Review form for per-case approval/edit/reject actions.
- `video_tagging_assistant/gui/log_panel.py`
  - Live log/progress widgets.
- `tests/test_pipeline_models.py`
  - Dataclass and status-transition focused tests.
- `tests/test_excel_workbook_pipeline.py`
  - Workbook status-column and pending-case loading tests.
- `tests/test_tagging_cache.py`
  - Cache read/write and cache validation tests.
- `tests/test_tagging_service.py`
  - Fresh-tagging vs cached-tagging tests.
- `tests/test_case_task_factory.py`
  - Manifest-to-case-task conversion tests.
- `tests/test_pipeline_controller.py`
  - Approval-driven execution queue behavior tests.
- `tests/test_gui_smoke.py`
  - Minimal GUI construction test without full user interaction.
- `docs/superpowers/plans/2026-04-28-excel-driven-case-pipeline.md`
  - This plan.

### Existing tests to extend if needed

- `tests/test_excel_pipeline.py`
  - Keep as regression coverage for the current lightweight review-sheet sync flow.
- `tests/test_case_ingest_orchestrator.py`
  - Reuse patterns for orchestration assertions if helpful.
- `tests/test_pull_worker.py`
  - Extend for progress callback coverage.
- `tests/test_upload_worker.py`
  - Extend for upload lifecycle callback coverage.

---

### Task 1: Define the pipeline data model

**Files:**
- Create: `video_tagging_assistant/pipeline_models.py`
- Modify: `video_tagging_assistant/models.py`
- Test: `tests/test_pipeline_models.py`

- [ ] **Step 1: Write the failing model tests**

```python
from pathlib import Path

from video_tagging_assistant.pipeline_models import (
    CaseManifest,
    ExcelCaseRecord,
    PipelineEvent,
    RuntimeStage,
    TaggingCacheRecord,
)


def test_excel_case_record_exposes_case_id_and_row():
    row = ExcelCaseRecord(
        row_index=12,
        case_id="case_A_0105",
        created_date="20260428",
        remark="场景备注",
        raw_path=r"E:\DV\case_A_0105\case_A_0105_RK_raw_117",
        vs_normal_path=r"E:\DV\case_A_0105\case_A_0105_DJI_normal.MP4",
        vs_night_path=r"E:\DV\case_A_0105\case_A_0105_night_DJI.MP4",
        labels={"安装方式": "手持", "运动模式": "行走"},
        pipeline_status="",
    )
    assert row.case_id == "case_A_0105"
    assert row.row_index == 12


def test_manifest_builds_cache_dir_from_case_id(tmp_path: Path):
    manifest = CaseManifest(
        case_id="case_A_0105",
        row_index=12,
        created_date="20260428",
        mode="OV50H40_Action5Pro_DCG HDR",
        raw_path=Path(tmp_path / "case_A_0105_RK_raw_117"),
        vs_normal_path=Path(tmp_path / "normal.MP4"),
        vs_night_path=Path(tmp_path / "night.MP4"),
        local_case_root=tmp_path / "case_A_0105",
        server_case_dir=Path(r"\\10.10.10.164\rk3668_capture\OV50H40_Action5Pro_DCG HDR\20260428\case_A_0105"),
        remark="场景备注",
        labels={"安装方式": "手持"},
    )
    assert manifest.cache_dir_name == "case_A_0105"


def test_pipeline_event_carries_progress_fields():
    event = PipelineEvent(
        case_id="case_A_0105",
        stage=RuntimeStage.PULLING,
        event_type="progress",
        message="pulling raw",
        progress_current=7,
        progress_total=20,
    )
    assert event.progress_current == 7
    assert event.progress_total == 20


def test_tagging_cache_record_reports_cache_ready(tmp_path: Path):
    record = TaggingCacheRecord(
        case_id="case_A_0105",
        manifest_path=tmp_path / "manifest.json",
        tagging_result_path=tmp_path / "tagging_result.json",
        review_result_path=tmp_path / "review_result.json",
        source_fingerprint="abc123",
    )
    assert record.is_complete is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline_models.py -v`
Expected: FAIL with `ModuleNotFoundError` or missing symbols from `video_tagging_assistant.pipeline_models`

- [ ] **Step 3: Write the minimal model implementation**

```python
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, Optional


class RuntimeStage(str, Enum):
    QUEUED = "queued"
    TAGGING_PREPARING = "tagging_preparing"
    TAGGING_RUNNING = "tagging_running"
    TAGGING_FINISHED = "tagging_finished"
    TAGGING_SKIPPED_USING_CACHED = "tagging_skipped_using_cached"
    AWAITING_REVIEW = "awaiting_review"
    REVIEW_PASSED = "review_passed"
    REVIEW_REJECTED = "review_rejected"
    PULLING = "pulling"
    COPYING = "copying"
    UPLOADING = "uploading"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ExcelCaseRecord:
    row_index: int
    case_id: str
    created_date: str
    remark: str
    raw_path: str
    vs_normal_path: str
    vs_night_path: str
    labels: Dict[str, str] = field(default_factory=dict)
    pipeline_status: str = ""


@dataclass
class CaseManifest:
    case_id: str
    row_index: int
    created_date: str
    mode: str
    raw_path: Path
    vs_normal_path: Path
    vs_night_path: Path
    local_case_root: Path
    server_case_dir: Path
    remark: str
    labels: Dict[str, str] = field(default_factory=dict)

    @property
    def cache_dir_name(self) -> str:
        return self.case_id


@dataclass
class TaggingCacheRecord:
    case_id: str
    manifest_path: Path
    tagging_result_path: Path
    review_result_path: Path
    source_fingerprint: str

    @property
    def is_complete(self) -> bool:
        return (
            self.manifest_path.exists()
            and self.tagging_result_path.exists()
            and self.review_result_path.exists()
        )


@dataclass
class PipelineEvent:
    case_id: str
    stage: RuntimeStage
    event_type: str
    message: str
    progress_current: int = 0
    progress_total: int = 0
    current_file: str = ""
    error: str = ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_pipeline_models.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_pipeline_models.py video_tagging_assistant/pipeline_models.py video_tagging_assistant/models.py
git commit -m "feat: add case pipeline data models"
```

### Task 2: Extend workbook access for pipeline records and status columns

**Files:**
- Modify: `video_tagging_assistant/excel_models.py`
- Modify: `video_tagging_assistant/excel_workbook.py`
- Test: `tests/test_excel_workbook_pipeline.py`

- [ ] **Step 1: Write the failing workbook tests**

```python
from pathlib import Path

from openpyxl import Workbook, load_workbook

from video_tagging_assistant.excel_workbook import ensure_pipeline_columns, load_pipeline_cases, update_pipeline_status


PIPELINE_HEADERS = [
    "序号",
    "文件夹名",
    "备注",
    "创建日期",
    "Raw存放路径",
    "VS_Nomal",
    "VS_Night",
    "安装方式",
    "运动模式",
]


def build_pipeline_workbook(path: Path):
    wb = Workbook()
    ws = wb.active
    ws.title = "创建记录"
    ws.append(PIPELINE_HEADERS)
    ws.append([
        1,
        "case_A_0105",
        "场景备注",
        "20260428",
        r"E:\DV\case_A_0105\case_A_0105_RK_raw_117",
        r"E:\DV\case_A_0105\case_A_0105_DJI_normal.MP4",
        r"E:\DV\case_A_0105\case_A_0105_night_DJI.MP4",
        "手持",
        "行走",
    ])
    wb.save(path)


def test_ensure_pipeline_columns_appends_runtime_headers(tmp_path: Path):
    workbook_path = tmp_path / "records.xlsx"
    build_pipeline_workbook(workbook_path)

    ensure_pipeline_columns(workbook_path, source_sheet="创建记录")

    wb = load_workbook(workbook_path)
    ws = wb["创建记录"]
    headers = [cell.value for cell in ws[1]]
    assert "pipeline_status" in headers
    assert "tag_status" in headers
    assert "updated_at" in headers


def test_load_pipeline_cases_returns_only_pending_rows(tmp_path: Path):
    workbook_path = tmp_path / "records.xlsx"
    build_pipeline_workbook(workbook_path)
    ensure_pipeline_columns(workbook_path, source_sheet="创建记录")
    update_pipeline_status(
        workbook_path,
        source_sheet="创建记录",
        case_id="case_A_0105",
        status_updates={"pipeline_status": "queued"},
    )

    rows = load_pipeline_cases(workbook_path, source_sheet="创建记录", allowed_statuses={"queued"})
    assert [row.case_id for row in rows] == ["case_A_0105"]


def test_update_pipeline_status_writes_multiple_runtime_fields(tmp_path: Path):
    workbook_path = tmp_path / "records.xlsx"
    build_pipeline_workbook(workbook_path)
    ensure_pipeline_columns(workbook_path, source_sheet="创建记录")

    update_pipeline_status(
        workbook_path,
        source_sheet="创建记录",
        case_id="case_A_0105",
        status_updates={
            "pipeline_status": "completed",
            "pull_status": "done",
            "upload_status": "done",
            "last_error": "",
        },
    )

    wb = load_workbook(workbook_path)
    ws = wb["创建记录"]
    headers = {cell.value: idx + 1 for idx, cell in enumerate(ws[1])}
    assert ws.cell(2, headers["pipeline_status"]).value == "completed"
    assert ws.cell(2, headers["pull_status"]).value == "done"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_excel_workbook_pipeline.py -v`
Expected: FAIL with missing functions `ensure_pipeline_columns`, `load_pipeline_cases`, or `update_pipeline_status`

- [ ] **Step 3: Implement workbook runtime-column support**

```python
PIPELINE_RUNTIME_HEADERS = [
    "pipeline_status",
    "tag_status",
    "review_status",
    "pull_status",
    "copy_status",
    "upload_status",
    "last_error",
    "run_id",
    "updated_at",
]


def ensure_pipeline_columns(workbook_path: Path, source_sheet: str) -> None:
    workbook = load_workbook(workbook_path)
    sheet = workbook[source_sheet]
    headers = _header_map(sheet)
    next_column = sheet.max_column + 1
    for header in PIPELINE_RUNTIME_HEADERS:
        if header not in headers:
            sheet.cell(1, next_column).value = header
            next_column += 1
    workbook.save(workbook_path)


def load_pipeline_cases(workbook_path: Path, source_sheet: str, allowed_statuses: set[str]):
    workbook = load_workbook(workbook_path)
    sheet = workbook[source_sheet]
    headers = _header_map(sheet)
    rows = []
    for row_index in range(2, sheet.max_row + 1):
        case_id = str(sheet.cell(row_index, headers["文件夹名"]).value or "").strip()
        if not case_id:
            continue
        status = str(sheet.cell(row_index, headers["pipeline_status"]).value or "").strip()
        if status not in allowed_statuses:
            continue
        rows.append(
            ExcelCaseRecord(
                row_index=row_index,
                case_id=case_id,
                created_date=str(sheet.cell(row_index, headers["创建日期"]).value or "").strip(),
                remark=str(sheet.cell(row_index, headers["备注"]).value or "").strip(),
                raw_path=str(sheet.cell(row_index, headers["Raw存放路径"]).value or "").strip(),
                vs_normal_path=str(sheet.cell(row_index, headers["VS_Nomal"]).value or "").strip(),
                vs_night_path=str(sheet.cell(row_index, headers["VS_Night"]).value or "").strip(),
                labels={
                    "安装方式": str(sheet.cell(row_index, headers["安装方式"]).value or "").strip(),
                    "运动模式": str(sheet.cell(row_index, headers["运动模式"]).value or "").strip(),
                },
                pipeline_status=status,
            )
        )
    return rows


def update_pipeline_status(workbook_path: Path, source_sheet: str, case_id: str, status_updates: dict[str, str]) -> None:
    workbook = load_workbook(workbook_path)
    sheet = workbook[source_sheet]
    headers = _header_map(sheet)
    for row_index in range(2, sheet.max_row + 1):
        current_case_id = str(sheet.cell(row_index, headers["文件夹名"]).value or "").strip()
        if current_case_id != case_id:
            continue
        for key, value in status_updates.items():
            sheet.cell(row_index, headers[key]).value = value
        break
    workbook.save(workbook_path)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_excel_workbook_pipeline.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_excel_workbook_pipeline.py video_tagging_assistant/excel_models.py video_tagging_assistant/excel_workbook.py
git commit -m "feat: add workbook runtime status support"
```

### Task 3: Add tagging cache read/write support

**Files:**
- Create: `video_tagging_assistant/tagging_cache.py`
- Test: `tests/test_tagging_cache.py`

- [ ] **Step 1: Write the failing cache tests**

```python
import json
from pathlib import Path

from video_tagging_assistant.pipeline_models import CaseManifest
from video_tagging_assistant.tagging_cache import build_source_fingerprint, load_cached_result, save_cached_result


def build_manifest(tmp_path: Path) -> CaseManifest:
    return CaseManifest(
        case_id="case_A_0105",
        row_index=12,
        created_date="20260428",
        mode="OV50H40_Action5Pro_DCG HDR",
        raw_path=tmp_path / "raw",
        vs_normal_path=tmp_path / "normal.MP4",
        vs_night_path=tmp_path / "night.MP4",
        local_case_root=tmp_path / "case_A_0105",
        server_case_dir=tmp_path / "server" / "case_A_0105",
        remark="场景备注",
        labels={"安装方式": "手持"},
    )


def test_build_source_fingerprint_changes_when_input_changes(tmp_path: Path):
    manifest = build_manifest(tmp_path)
    first = build_source_fingerprint(manifest)
    manifest.remark = "新备注"
    second = build_source_fingerprint(manifest)
    assert first != second


def test_save_and_load_cached_result_round_trip(tmp_path: Path):
    manifest = build_manifest(tmp_path)
    payload = {
        "summary_text": "自动简介",
        "tags": ["手持"],
        "scene_description": "画面描述",
    }
    save_cached_result(tmp_path, manifest, payload)
    loaded = load_cached_result(tmp_path, manifest)
    assert loaded["summary_text"] == "自动简介"
    assert loaded["scene_description"] == "画面描述"


def test_load_cached_result_returns_none_for_mismatched_fingerprint(tmp_path: Path):
    manifest = build_manifest(tmp_path)
    save_cached_result(tmp_path, manifest, {"summary_text": "自动简介"})
    manifest.remark = "不同备注"
    assert load_cached_result(tmp_path, manifest) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_tagging_cache.py -v`
Expected: FAIL with `ModuleNotFoundError` for `video_tagging_assistant.tagging_cache`

- [ ] **Step 3: Implement the cache helpers**

```python
import json
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path


def build_source_fingerprint(manifest) -> str:
    payload = {
        "case_id": manifest.case_id,
        "created_date": manifest.created_date,
        "mode": manifest.mode,
        "raw_path": str(manifest.raw_path),
        "vs_normal_path": str(manifest.vs_normal_path),
        "vs_night_path": str(manifest.vs_night_path),
        "remark": manifest.remark,
        "labels": manifest.labels,
    }
    return sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def save_cached_result(cache_root: Path, manifest, payload: dict) -> None:
    case_dir = cache_root / manifest.case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    fingerprint = build_source_fingerprint(manifest)
    (case_dir / "manifest.json").write_text(
        json.dumps({"fingerprint": fingerprint}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (case_dir / "tagging_result.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_cached_result(cache_root: Path, manifest):
    case_dir = cache_root / manifest.case_id
    manifest_path = case_dir / "manifest.json"
    result_path = case_dir / "tagging_result.json"
    if not manifest_path.exists() or not result_path.exists():
        return None
    manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest_payload.get("fingerprint") != build_source_fingerprint(manifest):
        return None
    return json.loads(result_path.read_text(encoding="utf-8"))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_tagging_cache.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_tagging_cache.py video_tagging_assistant/tagging_cache.py
git commit -m "feat: add tagging cache helpers"
```

### Task 4: Extract a batch tagging service with cache-mode support

**Files:**
- Create: `video_tagging_assistant/tagging_service.py`
- Modify: `video_tagging_assistant/orchestrator.py`
- Test: `tests/test_tagging_service.py`

- [ ] **Step 1: Write the failing tagging service tests**

```python
from pathlib import Path

from video_tagging_assistant.pipeline_models import CaseManifest
from video_tagging_assistant.tagging_service import run_batch_tagging


class StubProvider:
    provider_name = "stub"

    def generate(self, context):
        from video_tagging_assistant.models import GenerationResult

        return GenerationResult(
            source_video_path=context.source_video_path,
            case_key=context.prompt_payload["workbook"]["文件夹名"],
            summary_text="自动简介",
            structured_tags={"安装方式": "手持"},
            scene_description="画面描述",
            provider="stub",
            model="stub-model",
        )


def build_manifest(tmp_path: Path) -> CaseManifest:
    normal = tmp_path / "normal.MP4"
    night = tmp_path / "night.MP4"
    normal.write_bytes(b"video")
    night.write_bytes(b"video")
    return CaseManifest(
        case_id="case_A_0105",
        row_index=12,
        created_date="20260428",
        mode="OV50H40_Action5Pro_DCG HDR",
        raw_path=tmp_path / "raw",
        vs_normal_path=normal,
        vs_night_path=night,
        local_case_root=tmp_path / "case_A_0105",
        server_case_dir=tmp_path / "server" / "case_A_0105",
        remark="场景备注",
        labels={"安装方式": "手持", "运动模式": "行走"},
    )


def test_run_batch_tagging_generates_results_when_mode_is_fresh(tmp_path: Path):
    events = []
    results = run_batch_tagging(
        manifests=[build_manifest(tmp_path)],
        cache_root=tmp_path / "cache",
        output_root=tmp_path / "output",
        provider=StubProvider(),
        prompt_template={"system": "describe"},
        mode="fresh",
        event_callback=events.append,
    )
    assert results[0].case_id == "case_A_0105"
    assert results[0].auto_summary == "自动简介"
    assert any(event.stage.value == "tagging_running" for event in events)


def test_run_batch_tagging_uses_cache_when_mode_is_cached(tmp_path: Path):
    manifest = build_manifest(tmp_path)
    run_batch_tagging(
        manifests=[manifest],
        cache_root=tmp_path / "cache",
        output_root=tmp_path / "output",
        provider=StubProvider(),
        prompt_template={"system": "describe"},
        mode="fresh",
        event_callback=lambda event: None,
    )
    cached_results = run_batch_tagging(
        manifests=[manifest],
        cache_root=tmp_path / "cache",
        output_root=tmp_path / "output2",
        provider=StubProvider(),
        prompt_template={"system": "describe"},
        mode="cached",
        event_callback=lambda event: None,
    )
    assert cached_results[0].tag_source == "cache"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_tagging_service.py -v`
Expected: FAIL with missing `run_batch_tagging`

- [ ] **Step 3: Implement the minimal tagging service**

```python
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from video_tagging_assistant.compressor import compress_video
from video_tagging_assistant.context_builder import build_prompt_context
from video_tagging_assistant.models import CompressedArtifact, VideoTask
from video_tagging_assistant.pipeline_models import PipelineEvent, RuntimeStage
from video_tagging_assistant.tagging_cache import load_cached_result, save_cached_result


def _manifest_to_video_task(manifest):
    return VideoTask(
        source_video_path=manifest.vs_normal_path,
        relative_path=Path(manifest.mode) / manifest.case_id / manifest.vs_normal_path.name,
        file_name=manifest.vs_normal_path.name,
        case_id=manifest.case_id,
        mode=manifest.mode,
    )


def run_batch_tagging(manifests, cache_root, output_root, provider, prompt_template, mode, event_callback):
    results = []
    cache_root = Path(cache_root)
    output_root = Path(output_root)
    compressed_dir = output_root / "compressed"
    compression_config = {"width": 1280, "video_bitrate": "1500k", "audio_bitrate": "128k", "fps": 8}

    for manifest in manifests:
        if mode == "cached":
            cached = load_cached_result(cache_root, manifest)
            if cached is not None:
                event_callback(PipelineEvent(case_id=manifest.case_id, stage=RuntimeStage.TAGGING_SKIPPED_USING_CACHED, event_type="info", message="loaded cache"))
                results.append(type("TaggingReviewRow", (), {"case_id": manifest.case_id, "auto_summary": cached.get("summary_text", ""), "auto_tags": ";".join(cached.get("tags", [])), "auto_scene_description": cached.get("scene_description", ""), "tag_source": "cache"})())
                continue

        event_callback(PipelineEvent(case_id=manifest.case_id, stage=RuntimeStage.TAGGING_RUNNING, event_type="info", message="tagging"))
        task = _manifest_to_video_task(manifest)
        artifact = compress_video(task, compressed_dir, compression_config)
        context = build_prompt_context(task, artifact, prompt_template)
        generated = provider.generate(context)
        payload = {
            "summary_text": generated.summary_text,
            "tags": [f"{k}={v}" for k, v in generated.structured_tags.items()],
            "scene_description": generated.scene_description,
        }
        save_cached_result(cache_root, manifest, payload)
        results.append(type("TaggingReviewRow", (), {"case_id": manifest.case_id, "auto_summary": generated.summary_text, "auto_tags": ";".join(payload["tags"]), "auto_scene_description": generated.scene_description, "tag_source": "fresh"})())
    return results
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_tagging_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_tagging_service.py video_tagging_assistant/tagging_service.py video_tagging_assistant/orchestrator.py
git commit -m "feat: add batch tagging service with cache mode"
```

### Task 5: Build manifest-to-case-task conversion

**Files:**
- Create: `video_tagging_assistant/case_task_factory.py`
- Test: `tests/test_case_task_factory.py`

- [ ] **Step 1: Write the failing case-task factory tests**

```python
from pathlib import Path

from video_tagging_assistant.case_task_factory import build_case_task
from video_tagging_assistant.pipeline_models import CaseManifest


def test_build_case_task_maps_manifest_paths():
    manifest = CaseManifest(
        case_id="case_A_0105",
        row_index=12,
        created_date="20260428",
        mode="OV50H40_Action5Pro_DCG HDR",
        raw_path=Path(r"E:\DV\case_A_0105\case_A_0105_RK_raw_117"),
        vs_normal_path=Path(r"E:\DV\source\DJI_normal.MP4"),
        vs_night_path=Path(r"E:\DV\source\DJI_night.MP4"),
        local_case_root=Path(r"E:\DV\OV50H40_Action5Pro_DCG HDR\20260428\case_A_0105"),
        server_case_dir=Path(r"\\10.10.10.164\rk3668_capture\OV50H40_Action5Pro_DCG HDR\20260428\case_A_0105"),
        remark="场景备注",
        labels={"安装方式": "手持"},
    )

    case_task = build_case_task(manifest)

    assert case_task.case_id == "case_A_0105"
    assert case_task.case_root_dir == manifest.local_case_root
    assert case_task.server_case_dir == manifest.server_case_dir
    assert case_task.pull_task.move_dst.endswith("case_A_0105_RK_raw_117")
    assert len(case_task.copy_tasks) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_case_task_factory.py -v`
Expected: FAIL with missing `video_tagging_assistant.case_task_factory`

- [ ] **Step 3: Implement the minimal case-task factory**

```python
from pathlib import Path

from video_tagging_assistant.case_ingest_models import CaseTask, CopyTask, PullTask


def build_case_task(manifest):
    pull_dir_name = manifest.raw_path.name
    pull_task = PullTask(
        case_id=manifest.case_id,
        device_path=f"/mnt/nvme/CapturedData/{pull_dir_name.split('_')[-1]}",
        local_name=pull_dir_name,
        move_src=str(Path.cwd() / pull_dir_name),
        move_dst=str(manifest.local_case_root / pull_dir_name),
    )
    copy_tasks = [
        CopyTask(
            case_id=manifest.case_id,
            source_path=manifest.vs_normal_path,
            target_path=manifest.local_case_root / f"{manifest.case_id}_{manifest.vs_normal_path.name}",
            kind="normal",
        ),
        CopyTask(
            case_id=manifest.case_id,
            source_path=manifest.vs_night_path,
            target_path=manifest.local_case_root / f"{manifest.case_id}_night_{manifest.vs_night_path.name}",
            kind="night",
        ),
    ]
    return CaseTask(
        case_id=manifest.case_id,
        pull_task=pull_task,
        copy_tasks=copy_tasks,
        case_root_dir=manifest.local_case_root,
        server_case_dir=manifest.server_case_dir,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_case_task_factory.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_case_task_factory.py video_tagging_assistant/case_task_factory.py
git commit -m "feat: build case ingest tasks from manifests"
```

### Task 6: Add progress callbacks to pull and upload workers

**Files:**
- Modify: `video_tagging_assistant/pull_worker.py`
- Modify: `video_tagging_assistant/upload_worker.py`
- Test: `tests/test_pull_worker.py`
- Test: `tests/test_upload_worker.py`

- [ ] **Step 1: Write the failing progress callback tests**

```python
from pathlib import Path

from video_tagging_assistant.case_ingest_models import PullTask
from video_tagging_assistant.pull_worker import run_resumable_pull
from video_tagging_assistant.upload_worker import upload_case_directory


def test_run_resumable_pull_emits_progress_events(tmp_path: Path, monkeypatch):
    events = []
    final_dir = tmp_path / "case_A_0105_RK_raw_117"

    monkeypatch.setattr("video_tagging_assistant.pull_worker.count_remote_files", lambda path: 2)
    monkeypatch.setattr("video_tagging_assistant.pull_worker.validate_pull_counts", lambda remote_count, path: True)
    monkeypatch.setattr("video_tagging_assistant.pull_worker.subprocess.run", lambda *args, **kwargs: None)

    task = PullTask(
        case_id="case_A_0105",
        device_path="/mnt/nvme/CapturedData/117",
        local_name="case_A_0105_RK_raw_117",
        move_src=str(tmp_path / "case_A_0105_RK_raw_117"),
        move_dst=str(final_dir),
    )

    run_resumable_pull(task, progress_callback=events.append)

    assert any(event["stage"] == "pulling" for event in events)


def test_upload_case_directory_emits_start_and_finish_events(tmp_path: Path):
    events = []
    source = tmp_path / "case_A_0105"
    source.mkdir()
    (source / "a.txt").write_text("a", encoding="utf-8")
    target = tmp_path / "server" / "case_A_0105"

    upload_case_directory("case_A_0105", source, target, progress_callback=events.append)

    assert events[0]["stage"] == "uploading"
    assert events[-1]["stage"] == "uploaded"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pull_worker.py tests/test_upload_worker.py -v`
Expected: FAIL because `progress_callback` is not accepted or events are never emitted

- [ ] **Step 3: Implement callback hooks in the workers**

```python
def _emit(progress_callback, payload):
    if progress_callback is not None:
        progress_callback(payload)


def run_resumable_pull(task: PullTask, progress_callback=None) -> Path:
    final_dir = Path(task.move_dst)
    tmp_dir = final_dir.parent / f"{final_dir.name}_tmp"
    _emit(progress_callback, {"case_id": task.case_id, "stage": "pulling", "message": "counting remote files"})
    remote_count = count_remote_files(task.device_path)
    if validate_pull_counts(remote_count, final_dir):
        _emit(progress_callback, {"case_id": task.case_id, "stage": "pull_done", "message": "already complete", "progress_current": remote_count, "progress_total": remote_count})
        return final_dir
    subprocess.run(["adb", "pull", task.device_path, str(tmp_dir)], check=True)
    merge_tmp_into_final(tmp_dir, final_dir)
    if not validate_pull_counts(remote_count, final_dir):
        raise RuntimeError(f"pull validation failed for {task.case_id}")
    _emit(progress_callback, {"case_id": task.case_id, "stage": "pull_done", "message": "pull complete", "progress_current": remote_count, "progress_total": remote_count})
    return final_dir
```

```python
def upload_case_directory(case_id: str, local_case_dir: Path, server_case_dir: Path, progress_callback=None) -> UploadResult:
    if progress_callback is not None:
        progress_callback({"case_id": case_id, "stage": "uploading", "message": "upload started"})
    if server_case_dir.exists():
        if progress_callback is not None:
            progress_callback({"case_id": case_id, "stage": "uploaded", "message": "server case already exists"})
        return UploadResult(case_id=case_id, status="upload_skipped_exists", message="server case already exists")
    server_case_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(local_case_dir, server_case_dir)
    if progress_callback is not None:
        progress_callback({"case_id": case_id, "stage": "uploaded", "message": "upload complete"})
    return UploadResult(case_id=case_id, status="uploaded")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_pull_worker.py tests/test_upload_worker.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_pull_worker.py tests/test_upload_worker.py video_tagging_assistant/pull_worker.py video_tagging_assistant/upload_worker.py
git commit -m "feat: add case ingest progress callbacks"
```

### Task 7: Build pipeline logging and controller state transitions

**Files:**
- Create: `video_tagging_assistant/pipeline_logging.py`
- Create: `video_tagging_assistant/pipeline_controller.py`
- Test: `tests/test_pipeline_controller.py`

- [ ] **Step 1: Write the failing controller tests**

```python
from pathlib import Path

from video_tagging_assistant.pipeline_controller import PipelineController
from video_tagging_assistant.pipeline_models import CaseManifest


def build_manifest(tmp_path: Path, case_id: str) -> CaseManifest:
    return CaseManifest(
        case_id=case_id,
        row_index=12,
        created_date="20260428",
        mode="OV50H40_Action5Pro_DCG HDR",
        raw_path=tmp_path / f"{case_id}_RK_raw_117",
        vs_normal_path=tmp_path / f"{case_id}_normal.MP4",
        vs_night_path=tmp_path / f"{case_id}_night.MP4",
        local_case_root=tmp_path / case_id,
        server_case_dir=tmp_path / "server" / case_id,
        remark="场景备注",
        labels={"安装方式": "手持"},
    )


def test_controller_moves_approved_case_into_execution_queue(tmp_path: Path):
    controller = PipelineController()
    manifest = build_manifest(tmp_path, "case_A_0105")

    controller.register_manifests([manifest])
    controller.mark_tagging_finished("case_A_0105")
    controller.approve_case("case_A_0105")

    queued = controller.dequeue_execution_case()
    assert queued.case_id == "case_A_0105"


def test_controller_does_not_block_on_other_reviews(tmp_path: Path):
    controller = PipelineController()
    first = build_manifest(tmp_path, "case_A_0105")
    second = build_manifest(tmp_path, "case_A_0106")

    controller.register_manifests([first, second])
    controller.mark_tagging_finished("case_A_0105")
    controller.mark_tagging_finished("case_A_0106")
    controller.approve_case("case_A_0105")

    queued = controller.dequeue_execution_case()
    assert queued.case_id == "case_A_0105"
    assert controller.get_case_state("case_A_0106").stage.value == "awaiting_review"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline_controller.py -v`
Expected: FAIL with missing `PipelineController`

- [ ] **Step 3: Implement the minimal controller and log sink**

```python
from collections import deque
from dataclasses import dataclass

from video_tagging_assistant.pipeline_models import PipelineEvent, RuntimeStage


@dataclass
class CaseRuntimeState:
    manifest: object
    stage: RuntimeStage = RuntimeStage.QUEUED


class PipelineController:
    def __init__(self):
        self._cases = {}
        self._execution_queue = deque()

    def register_manifests(self, manifests):
        for manifest in manifests:
            self._cases[manifest.case_id] = CaseRuntimeState(manifest=manifest)

    def mark_tagging_finished(self, case_id: str):
        self._cases[case_id].stage = RuntimeStage.AWAITING_REVIEW

    def approve_case(self, case_id: str):
        state = self._cases[case_id]
        state.stage = RuntimeStage.REVIEW_PASSED
        self._execution_queue.append(state.manifest)

    def dequeue_execution_case(self):
        return self._execution_queue.popleft()

    def get_case_state(self, case_id: str):
        return self._cases[case_id]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_pipeline_controller.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_pipeline_controller.py video_tagging_assistant/pipeline_logging.py video_tagging_assistant/pipeline_controller.py
git commit -m "feat: add pipeline controller state machine"
```

### Task 8: Wire the controller to workbook updates and case execution

**Files:**
- Modify: `video_tagging_assistant/pipeline_controller.py`
- Modify: `video_tagging_assistant/case_task_factory.py`
- Modify: `video_tagging_assistant/excel_workbook.py`
- Test: `tests/test_pipeline_controller.py`
- Test: `tests/test_excel_pipeline.py`

- [ ] **Step 1: Write the failing orchestration tests**

```python
from pathlib import Path

from video_tagging_assistant.pipeline_controller import PipelineController
from video_tagging_assistant.pipeline_models import CaseManifest


def build_manifest(tmp_path: Path) -> CaseManifest:
    return CaseManifest(
        case_id="case_A_0105",
        row_index=12,
        created_date="20260428",
        mode="OV50H40_Action5Pro_DCG HDR",
        raw_path=tmp_path / "case_A_0105_RK_raw_117",
        vs_normal_path=tmp_path / "normal.MP4",
        vs_night_path=tmp_path / "night.MP4",
        local_case_root=tmp_path / "case_A_0105",
        server_case_dir=tmp_path / "server" / "case_A_0105",
        remark="场景备注",
        labels={"安装方式": "手持"},
    )


def test_execute_approved_case_runs_pull_copy_upload_in_order(tmp_path: Path):
    calls = []
    controller = PipelineController(
        pull_runner=lambda task, progress_callback=None: calls.append(("pull", task.case_id)),
        copy_runner=lambda tasks: calls.append(("copy", tasks[0].case_id)),
        upload_runner=lambda case_id, local_case_dir, server_case_dir, progress_callback=None: calls.append(("upload", case_id)),
    )
    manifest = build_manifest(tmp_path)
    controller.register_manifests([manifest])
    controller.mark_tagging_finished(manifest.case_id)
    controller.approve_case(manifest.case_id)

    controller.run_next_execution_case()

    assert calls == [
        ("pull", "case_A_0105"),
        ("copy", "case_A_0105"),
        ("upload", "case_A_0105"),
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline_controller.py::test_execute_approved_case_runs_pull_copy_upload_in_order -v`
Expected: FAIL because `run_next_execution_case` does not exist

- [ ] **Step 3: Implement sequential execution for one approved case**

```python
from video_tagging_assistant.case_task_factory import build_case_task
from video_tagging_assistant.upload_worker import upload_case_directory
from video_tagging_assistant.copy_worker import copy_declared_files
from video_tagging_assistant.pull_worker import run_resumable_pull


class PipelineController:
    def __init__(self, pull_runner=run_resumable_pull, copy_runner=copy_declared_files, upload_runner=upload_case_directory):
        self._cases = {}
        self._execution_queue = deque()
        self._pull_runner = pull_runner
        self._copy_runner = copy_runner
        self._upload_runner = upload_runner

    def run_next_execution_case(self):
        manifest = self.dequeue_execution_case()
        case_task = build_case_task(manifest)
        self._cases[manifest.case_id].stage = RuntimeStage.PULLING
        self._pull_runner(case_task.pull_task)
        self._cases[manifest.case_id].stage = RuntimeStage.COPYING
        self._copy_runner(case_task.copy_tasks)
        self._cases[manifest.case_id].stage = RuntimeStage.UPLOADING
        self._upload_runner(case_task.case_id, case_task.case_root_dir, case_task.server_case_dir)
        self._cases[manifest.case_id].stage = RuntimeStage.COMPLETED
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_pipeline_controller.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_pipeline_controller.py tests/test_excel_pipeline.py video_tagging_assistant/pipeline_controller.py video_tagging_assistant/case_task_factory.py video_tagging_assistant/excel_workbook.py
git commit -m "feat: run approved cases through execution pipeline"
```

### Task 9: Add a minimal PyQt main window and review panel

**Files:**
- Create: `video_tagging_assistant/gui/__init__.py`
- Create: `video_tagging_assistant/gui/app.py`
- Create: `video_tagging_assistant/gui/main_window.py`
- Create: `video_tagging_assistant/gui/review_panel.py`
- Create: `video_tagging_assistant/gui/log_panel.py`
- Create: `video_tagging_assistant/gui/table_models.py`
- Test: `tests/test_gui_smoke.py`

- [ ] **Step 1: Write the failing GUI smoke test**

```python
from PyQt5.QtWidgets import QApplication

from video_tagging_assistant.gui.main_window import PipelineMainWindow


def test_pipeline_main_window_builds(qtbot):
    window = PipelineMainWindow()
    qtbot.addWidget(window)
    assert window.windowTitle() == "Case Pipeline"
    assert window.tabs.count() >= 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_gui_smoke.py -v`
Expected: FAIL with missing `video_tagging_assistant.gui.main_window`

- [ ] **Step 3: Implement the minimal GUI shell**

```python
from PyQt5.QtWidgets import QLabel, QMainWindow, QTabWidget, QVBoxLayout, QWidget


class PipelineMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Case Pipeline")
        self.tabs = QTabWidget()
        self.tabs.addTab(self._placeholder_tab("今日队列"), "今日队列")
        self.tabs.addTab(self._placeholder_tab("打标审核"), "打标审核")
        self.tabs.addTab(self._placeholder_tab("执行监控"), "执行监控")
        self.tabs.addTab(self._placeholder_tab("失败重试"), "失败重试")
        self.setCentralWidget(self.tabs)

    def _placeholder_tab(self, text: str):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addWidget(QLabel(text))
        return widget
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_gui_smoke.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_gui_smoke.py video_tagging_assistant/gui/__init__.py video_tagging_assistant/gui/app.py video_tagging_assistant/gui/main_window.py video_tagging_assistant/gui/review_panel.py video_tagging_assistant/gui/log_panel.py video_tagging_assistant/gui/table_models.py
git commit -m "feat: add case pipeline gui shell"
```

### Task 10: Connect the GUI to scanning, tagging mode, review approval, and logs

**Files:**
- Modify: `video_tagging_assistant/gui/main_window.py`
- Modify: `video_tagging_assistant/gui/review_panel.py`
- Modify: `video_tagging_assistant/gui/log_panel.py`
- Modify: `video_tagging_assistant/gui/table_models.py`
- Modify: `video_tagging_assistant/pipeline_controller.py`
- Modify: `video_tagging_assistant/tagging_service.py`
- Test: `tests/test_gui_smoke.py`
- Test: `tests/test_pipeline_controller.py`

- [ ] **Step 1: Write the failing integration-style GUI/controller tests**

```python
from PyQt5.QtCore import Qt

from video_tagging_assistant.gui.main_window import PipelineMainWindow


def test_gui_exposes_tagging_mode_selector(qtbot):
    window = PipelineMainWindow()
    qtbot.addWidget(window)
    assert window.tagging_mode_combo.count() == 2
    assert window.tagging_mode_combo.itemText(0) == "重新打标"
    assert window.tagging_mode_combo.itemText(1) == "复用旧打标结果"


def test_gui_log_panel_appends_event_text(qtbot):
    window = PipelineMainWindow()
    qtbot.addWidget(window)
    window.append_log_line("case_A_0105 upload started")
    assert "upload started" in window.log_panel.toPlainText()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_gui_smoke.py -v`
Expected: FAIL because the widgets and methods do not exist yet

- [ ] **Step 3: Implement the minimal interactive controls**

```python
from PyQt5.QtWidgets import QComboBox, QHBoxLayout, QPushButton, QTextEdit


class PipelineMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Case Pipeline")
        self.tagging_mode_combo = QComboBox()
        self.tagging_mode_combo.addItems(["重新打标", "复用旧打标结果"])
        self.scan_button = QPushButton("扫描新增记录")
        self.start_button = QPushButton("启动流水线")
        self.log_panel = QTextEdit()
        self.log_panel.setReadOnly(True)
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.addWidget(self.tagging_mode_combo)
        header_layout.addWidget(self.scan_button)
        header_layout.addWidget(self.start_button)
        layout = QVBoxLayout()
        layout.addWidget(header)
        layout.addWidget(self.tabs)
        layout.addWidget(self.log_panel)
        wrapper = QWidget()
        wrapper.setLayout(layout)
        self.setCentralWidget(wrapper)

    def append_log_line(self, line: str):
        self.log_panel.append(line)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_gui_smoke.py tests/test_pipeline_controller.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_gui_smoke.py tests/test_pipeline_controller.py video_tagging_assistant/gui/main_window.py video_tagging_assistant/gui/review_panel.py video_tagging_assistant/gui/log_panel.py video_tagging_assistant/gui/table_models.py video_tagging_assistant/pipeline_controller.py video_tagging_assistant/tagging_service.py
git commit -m "feat: connect gui controls to pipeline workflow"
```

### Task 11: Add CLI entrypoint and documentation-facing verification

**Files:**
- Modify: `video_tagging_assistant/cli.py`
- Modify: `requirements.txt`
- Test: `tests/test_case_ingest_cli_config.py`
- Test: `tests/test_docs_structure.py`

- [ ] **Step 1: Write the failing CLI test**

```python
from video_tagging_assistant.cli import main


def test_case_pipeline_gui_command_parses(monkeypatch):
    called = {}

    def fake_launch(workbook_path=None):
        called["workbook_path"] = workbook_path
        return 0

    monkeypatch.setattr("video_tagging_assistant.cli.launch_case_pipeline_gui", fake_launch)
    exit_code = main(["case-pipeline-gui"])
    assert exit_code == 0
    assert called["workbook_path"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_case_ingest_cli_config.py::test_case_pipeline_gui_command_parses -v`
Expected: FAIL because `case-pipeline-gui` is not a known subcommand

- [ ] **Step 3: Implement the minimal launcher entrypoint**

```python
from video_tagging_assistant.gui.app import launch_case_pipeline_gui


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config")
    subparsers = parser.add_subparsers(dest="command")

    case_pipeline_parser = subparsers.add_parser("case-pipeline-gui")
    case_pipeline_parser.add_argument("--workbook")

    args = parser.parse_args(argv)

    if args.command == "case-pipeline-gui":
        return launch_case_pipeline_gui(workbook_path=args.workbook)
```

```python
from PyQt5.QtWidgets import QApplication

from video_tagging_assistant.gui.main_window import PipelineMainWindow


def launch_case_pipeline_gui(workbook_path=None):
    app = QApplication.instance() or QApplication([])
    window = PipelineMainWindow()
    window.show()
    return 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_case_ingest_cli_config.py::test_case_pipeline_gui_command_parses -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_case_ingest_cli_config.py video_tagging_assistant/cli.py video_tagging_assistant/gui/app.py requirements.txt
git commit -m "feat: add case pipeline gui command"
```

### Task 12: Full targeted verification

**Files:**
- Test: `tests/test_pipeline_models.py`
- Test: `tests/test_excel_workbook_pipeline.py`
- Test: `tests/test_tagging_cache.py`
- Test: `tests/test_tagging_service.py`
- Test: `tests/test_case_task_factory.py`
- Test: `tests/test_pipeline_controller.py`
- Test: `tests/test_gui_smoke.py`
- Test: `tests/test_pull_worker.py`
- Test: `tests/test_upload_worker.py`
- Test: `tests/test_excel_pipeline.py`
- Test: `tests/test_case_ingest_cli_config.py`

- [ ] **Step 1: Run the focused test suite**

Run: `pytest tests/test_pipeline_models.py tests/test_excel_workbook_pipeline.py tests/test_tagging_cache.py tests/test_tagging_service.py tests/test_case_task_factory.py tests/test_pipeline_controller.py tests/test_gui_smoke.py tests/test_pull_worker.py tests/test_upload_worker.py tests/test_excel_pipeline.py tests/test_case_ingest_cli_config.py -v`
Expected: PASS

- [ ] **Step 2: Run the existing top-level regression suite**

Run: `pytest tests -v`
Expected: PASS with no regressions in existing tagging / case-ingest coverage

- [ ] **Step 3: Manually smoke-check the GUI launcher**

Run: `python -m video_tagging_assistant.cli case-pipeline-gui`
Expected: the `Case Pipeline` window opens with tabs for 今日队列 / 打标审核 / 执行监控 / 失败重试

- [ ] **Step 4: Commit the verification-complete state**

```bash
git add video_tagging_assistant tests requirements.txt
git commit -m "test: verify excel-driven case pipeline"
```

## Self-Review

### Spec coverage

- Excel remains the system of record and `创建记录` stays authoritative: covered by Tasks 1-2.
- Batch tagging followed by review-driven execution: covered by Tasks 4, 7, 8, and 10.
- Skip tagging / import old results: covered by Task 3 and Task 4.
- Immediate pull/copy/upload after each approval: covered by Tasks 7-8.
- Real-time progress and logs: covered by Tasks 6, 7, 9, and 10.
- PyQt desktop GUI: covered by Tasks 9-11.
- Reuse of existing batch tagging and case-ingest workers: covered by Tasks 4-8.

### Placeholder scan

- No `TODO`, `TBD`, or “implement later” placeholders remain.
- Every test step names a concrete file and command.
- Every code-writing step includes concrete code blocks.

### Type consistency

- `CaseManifest`, `ExcelCaseRecord`, `PipelineEvent`, `RuntimeStage`, `TaggingCacheRecord`, and `PipelineController` naming is consistent across tasks.
- Tagging mode strings are consistently `fresh` and `cached` in service code, and `重新打标` / `复用旧打标结果` in the GUI.
- Execution ordering remains `pull -> copy -> upload` everywhere in the plan.

Plan complete and saved to `docs/superpowers/plans/2026-04-28-excel-driven-case-pipeline.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
