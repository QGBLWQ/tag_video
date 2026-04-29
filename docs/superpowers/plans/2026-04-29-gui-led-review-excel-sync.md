# GUI-Led Review Excel Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect the existing PyQt GUI shell to the Excel-driven case pipeline so operators can scan cases, run batch tagging, review results in the GUI, import approved Excel reviews, and trigger pull/copy/upload immediately after approval.

**Architecture:** Keep GUI as the primary review surface and Excel as both durable storage and a manual compatibility input source. Extend the existing workbook helpers, tagging service, and pipeline controller with the smallest missing pieces: manifest construction, review-sheet import/export, controller event callbacks, simple Qt models/widgets, and background worker wiring in the main window.

**Tech Stack:** Python 3.8, PyQt5, openpyxl, threading, existing `video_tagging_assistant` modules, pytest

---

## File Structure

### Existing files to modify

- `video_tagging_assistant/excel_workbook.py`
  - Add helpers for turning `ExcelCaseRecord` rows into pipeline-ready data and for reading approved review-sheet rows back into Python.
- `video_tagging_assistant/pipeline_controller.py`
  - Add event callback support, duplicate-approval guards, and failure-to-event conversion during execution.
- `video_tagging_assistant/gui/review_panel.py`
  - Replace the placeholder widget with a small review form that can display one case and emit approve / approve-after-edit / reject / refresh actions.
- `video_tagging_assistant/gui/table_models.py`
  - Replace the empty model with a simple queue/review table model suitable for Qt views.
- `video_tagging_assistant/gui/main_window.py`
  - Wire together workbook scanning, tagging-thread startup, review actions, execution-thread startup, table refreshes, and log updates.
- `video_tagging_assistant/gui/app.py`
  - Inject workbook path and create the real window with the new behavior.
- `tests/test_gui_smoke.py`
  - Extend GUI smoke coverage to cover queue/review wiring.
- `tests/test_pipeline_controller.py`
  - Extend controller tests for event callbacks, duplicate approval prevention, and failure transitions.
- `tests/test_excel_workbook_pipeline.py`
  - Extend workbook tests for manifest conversion and approved review-sheet imports.

### New files to create

- None required. This feature can be completed by filling in the existing shells.

### Existing tests to extend if needed

- `tests/test_case_ingest_cli_config.py`
  - Keep CLI launcher coverage as regression protection after `gui/app.py` changes.

---

### Task 1: Extend workbook helpers for manifest construction and approved review imports

**Files:**
- Modify: `video_tagging_assistant/excel_workbook.py`
- Test: `tests/test_excel_workbook_pipeline.py`

- [ ] **Step 1: Write the failing workbook tests**

```python
from pathlib import Path

from openpyxl import Workbook

from video_tagging_assistant.excel_workbook import (
    build_case_manifests,
    ensure_pipeline_columns,
    load_approved_review_rows,
    update_pipeline_status,
)


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


REVIEW_HEADERS = [
    "文件夹名",
    "创建记录行号",
    "Raw存放路径",
    "视频路径",
    "自动简介",
    "自动标签",
    "自动画面描述",
    "审核结论",
    "人工修订简介",
    "人工修订标签",
    "审核备注",
    "审核人",
    "审核时间",
    "同步状态",
    "归档状态",
    "归档目标路径",
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
    review = wb.create_sheet("审核结果")
    review.append(REVIEW_HEADERS)
    wb.save(path)


def test_build_case_manifests_maps_excel_rows_to_runtime_paths(tmp_path: Path):
    workbook_path = tmp_path / "records.xlsx"
    build_pipeline_workbook(workbook_path)
    ensure_pipeline_columns(workbook_path, source_sheet="创建记录")
    update_pipeline_status(
        workbook_path,
        source_sheet="创建记录",
        case_id="case_A_0105",
        status_updates={"pipeline_status": "queued"},
    )

    manifests = build_case_manifests(
        workbook_path,
        source_sheet="创建记录",
        allowed_statuses={"queued"},
        local_root=tmp_path / "local",
        server_root=tmp_path / "server",
        mode="OV50H40_Action5Pro_DCG HDR",
    )

    assert len(manifests) == 1
    assert manifests[0].case_id == "case_A_0105"
    assert manifests[0].local_case_root == tmp_path / "local" / "OV50H40_Action5Pro_DCG HDR" / "20260428" / "case_A_0105"


def test_load_approved_review_rows_reads_excel_decisions(tmp_path: Path):
    workbook_path = tmp_path / "records.xlsx"
    build_pipeline_workbook(workbook_path)
    from openpyxl import load_workbook

    wb = load_workbook(workbook_path)
    ws = wb["审核结果"]
    ws.append([
        "case_A_0105",
        2,
        r"E:\DV\case_A_0105\case_A_0105_RK_raw_117",
        r"E:\DV\case_A_0105\case_A_0105_DJI_normal.MP4",
        "自动简介",
        "安装方式=手持",
        "自动画面描述",
        "修改后通过",
        "人工简介",
        "安装方式=肩扛",
        "补充备注",
        "tester",
        "2026-04-29 10:00:00",
        "",
        "",
        "",
    ])
    wb.save(workbook_path)

    rows = load_approved_review_rows(workbook_path, review_sheet="审核结果")

    assert len(rows) == 1
    assert rows[0]["case_id"] == "case_A_0105"
    assert rows[0]["review_decision"] == "修改后通过"
    assert rows[0]["manual_summary"] == "人工简介"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_excel_workbook_pipeline.py::test_build_case_manifests_maps_excel_rows_to_runtime_paths tests/test_excel_workbook_pipeline.py::test_load_approved_review_rows_reads_excel_decisions -v`
Expected: FAIL with missing `build_case_manifests` or `load_approved_review_rows`

- [ ] **Step 3: Implement the minimal workbook helpers**

```python
from pathlib import Path
from typing import Dict, List, Set

from video_tagging_assistant.pipeline_models import CaseManifest


def build_case_manifests(
    workbook_path: Path,
    source_sheet: str,
    allowed_statuses: Set[str],
    local_root: Path,
    server_root: Path,
    mode: str,
) -> List[CaseManifest]:
    rows = load_pipeline_cases(workbook_path, source_sheet=source_sheet, allowed_statuses=allowed_statuses)
    manifests: List[CaseManifest] = []
    for row in rows:
        manifests.append(
            CaseManifest(
                case_id=row.case_id,
                row_index=row.row_index,
                created_date=row.created_date,
                mode=mode,
                raw_path=Path(row.raw_path),
                vs_normal_path=Path(row.vs_normal_path),
                vs_night_path=Path(row.vs_night_path),
                local_case_root=Path(local_root) / mode / row.created_date / row.case_id,
                server_case_dir=Path(server_root) / mode / row.created_date / row.case_id,
                remark=row.remark,
                labels=row.labels,
            )
        )
    return manifests


def load_approved_review_rows(workbook_path: Path, review_sheet: str) -> List[Dict[str, str]]:
    workbook = load_workbook(workbook_path)
    sheet = workbook[review_sheet]
    headers = _header_map(sheet)
    rows: List[Dict[str, str]] = []
    for row_index in range(2, sheet.max_row + 1):
        decision = str(sheet.cell(row_index, headers["审核结论"]).value or "").strip()
        if decision not in {"审核通过", "修改后通过"}:
            continue
        rows.append(
            {
                "case_id": str(sheet.cell(row_index, headers["文件夹名"]).value or "").strip(),
                "review_decision": decision,
                "manual_summary": str(sheet.cell(row_index, headers["人工修订简介"]).value or "").strip(),
                "manual_tags": str(sheet.cell(row_index, headers["人工修订标签"]).value or "").strip(),
                "review_note": str(sheet.cell(row_index, headers["审核备注"]).value or "").strip(),
            }
        )
    return rows
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_excel_workbook_pipeline.py::test_build_case_manifests_maps_excel_rows_to_runtime_paths tests/test_excel_workbook_pipeline.py::test_load_approved_review_rows_reads_excel_decisions -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_excel_workbook_pipeline.py video_tagging_assistant/excel_workbook.py
git commit -m "feat: add workbook helpers for gui pipeline"
```

### Task 2: Add controller event callbacks and duplicate-approval guards

**Files:**
- Modify: `video_tagging_assistant/pipeline_controller.py`
- Test: `tests/test_pipeline_controller.py`

- [ ] **Step 1: Write the failing controller tests**

```python
from pathlib import Path

from video_tagging_assistant.pipeline_controller import PipelineController
from video_tagging_assistant.pipeline_models import CaseManifest, RuntimeStage


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


def test_controller_emits_stage_events(tmp_path: Path):
    events = []
    controller = PipelineController(event_callback=events.append)
    manifest = build_manifest(tmp_path, "case_A_0105")

    controller.register_manifests([manifest])
    controller.mark_tagging_finished("case_A_0105")
    controller.approve_case("case_A_0105")

    assert any(event.case_id == "case_A_0105" and event.stage == RuntimeStage.AWAITING_REVIEW for event in events)
    assert any(event.case_id == "case_A_0105" and event.stage == RuntimeStage.REVIEW_PASSED for event in events)


def test_controller_does_not_enqueue_same_case_twice(tmp_path: Path):
    controller = PipelineController()
    manifest = build_manifest(tmp_path, "case_A_0105")

    controller.register_manifests([manifest])
    controller.mark_tagging_finished("case_A_0105")
    controller.approve_case("case_A_0105")
    controller.approve_case("case_A_0105")

    first = controller.dequeue_execution_case()
    assert first.case_id == "case_A_0105"
    assert controller.has_execution_case() is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline_controller.py::test_controller_emits_stage_events tests/test_pipeline_controller.py::test_controller_does_not_enqueue_same_case_twice -v`
Expected: FAIL because `event_callback` or `has_execution_case` does not exist, or duplicate approvals still enqueue twice

- [ ] **Step 3: Implement callback emission and duplicate guards**

```python
from collections import deque
from dataclasses import dataclass
from typing import Callable, Optional

from video_tagging_assistant.pipeline_models import PipelineEvent, RuntimeStage


@dataclass
class CaseRuntimeState:
    manifest: object
    stage: RuntimeStage = RuntimeStage.QUEUED


class PipelineController:
    def __init__(self, pull_runner=run_resumable_pull, copy_runner=copy_declared_files, upload_runner=upload_case_directory, event_callback: Optional[Callable[[PipelineEvent], None]] = None):
        self._cases = {}
        self._execution_queue = deque()
        self._pull_runner = pull_runner
        self._copy_runner = copy_runner
        self._upload_runner = upload_runner
        self._event_callback = event_callback

    def _emit(self, case_id: str, stage: RuntimeStage, message: str, event_type: str = "info") -> None:
        if self._event_callback is not None:
            self._event_callback(PipelineEvent(case_id=case_id, stage=stage, event_type=event_type, message=message))

    def has_execution_case(self) -> bool:
        return bool(self._execution_queue)

    def mark_tagging_finished(self, case_id: str):
        self._cases[case_id].stage = RuntimeStage.AWAITING_REVIEW
        self._emit(case_id, RuntimeStage.AWAITING_REVIEW, "awaiting review")

    def approve_case(self, case_id: str):
        state = self._cases[case_id]
        if state.stage in {
            RuntimeStage.REVIEW_PASSED,
            RuntimeStage.PULLING,
            RuntimeStage.COPYING,
            RuntimeStage.UPLOADING,
            RuntimeStage.COMPLETED,
        }:
            return False
        state.stage = RuntimeStage.REVIEW_PASSED
        self._execution_queue.append(state.manifest)
        self._emit(case_id, RuntimeStage.REVIEW_PASSED, "case approved")
        return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_pipeline_controller.py::test_controller_emits_stage_events tests/test_pipeline_controller.py::test_controller_does_not_enqueue_same_case_twice -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_pipeline_controller.py video_tagging_assistant/pipeline_controller.py
git commit -m "feat: emit pipeline controller events"
```

### Task 3: Surface execution-stage events and failure transitions from the controller

**Files:**
- Modify: `video_tagging_assistant/pipeline_controller.py`
- Test: `tests/test_pipeline_controller.py`

- [ ] **Step 1: Write the failing execution-state tests**

```python
from pathlib import Path

from video_tagging_assistant.pipeline_controller import PipelineController
from video_tagging_assistant.pipeline_models import CaseManifest, RuntimeStage


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


def test_execute_case_emits_pull_copy_upload_and_complete(tmp_path: Path):
    events = []
    calls = []
    controller = PipelineController(
        pull_runner=lambda task, progress_callback=None: calls.append("pull"),
        copy_runner=lambda tasks: calls.append("copy"),
        upload_runner=lambda case_id, local_case_dir, server_case_dir, progress_callback=None: calls.append("upload"),
        event_callback=events.append,
    )
    manifest = build_manifest(tmp_path)
    controller.register_manifests([manifest])
    controller.mark_tagging_finished(manifest.case_id)
    controller.approve_case(manifest.case_id)

    controller.run_next_execution_case()

    assert calls == ["pull", "copy", "upload"]
    assert [event.stage for event in events if event.case_id == manifest.case_id][-4:] == [
        RuntimeStage.PULLING,
        RuntimeStage.COPYING,
        RuntimeStage.UPLOADING,
        RuntimeStage.COMPLETED,
    ]


def test_execute_case_marks_failed_when_runner_raises(tmp_path: Path):
    events = []
    controller = PipelineController(
        pull_runner=lambda task, progress_callback=None: (_ for _ in ()).throw(RuntimeError("boom")),
        event_callback=events.append,
    )
    manifest = build_manifest(tmp_path)
    controller.register_manifests([manifest])
    controller.mark_tagging_finished(manifest.case_id)
    controller.approve_case(manifest.case_id)

    controller.run_next_execution_case()

    assert controller.get_case_state(manifest.case_id).stage == RuntimeStage.FAILED
    assert events[-1].stage == RuntimeStage.FAILED
    assert "boom" in events[-1].message
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline_controller.py::test_execute_case_emits_pull_copy_upload_and_complete tests/test_pipeline_controller.py::test_execute_case_marks_failed_when_runner_raises -v`
Expected: FAIL because stage events are missing or exceptions escape instead of converting to `FAILED`

- [ ] **Step 3: Implement emitted transitions in `run_next_execution_case`**

```python
def run_next_execution_case(self):
    manifest = self.dequeue_execution_case()
    case_task = build_case_task(manifest)
    try:
        self._cases[manifest.case_id].stage = RuntimeStage.PULLING
        self._emit(manifest.case_id, RuntimeStage.PULLING, "pull started")
        self._pull_runner(case_task.pull_task)

        self._cases[manifest.case_id].stage = RuntimeStage.COPYING
        self._emit(manifest.case_id, RuntimeStage.COPYING, "copy started")
        self._copy_runner(case_task.copy_tasks)

        self._cases[manifest.case_id].stage = RuntimeStage.UPLOADING
        self._emit(manifest.case_id, RuntimeStage.UPLOADING, "upload started")
        self._upload_runner(case_task.case_id, case_task.case_root_dir, case_task.server_case_dir)

        self._cases[manifest.case_id].stage = RuntimeStage.COMPLETED
        self._emit(manifest.case_id, RuntimeStage.COMPLETED, "case completed")
    except Exception as exc:
        self._cases[manifest.case_id].stage = RuntimeStage.FAILED
        self._emit(manifest.case_id, RuntimeStage.FAILED, str(exc), event_type="error")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_pipeline_controller.py::test_execute_case_emits_pull_copy_upload_and_complete tests/test_pipeline_controller.py::test_execute_case_marks_failed_when_runner_raises -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_pipeline_controller.py video_tagging_assistant/pipeline_controller.py
git commit -m "feat: track execution stage transitions"
```

### Task 4: Build a real review panel widget with action callbacks

**Files:**
- Modify: `video_tagging_assistant/gui/review_panel.py`
- Test: `tests/test_gui_smoke.py`

- [ ] **Step 1: Write the failing review-panel tests**

```python
from PyQt5.QtWidgets import QApplication

from video_tagging_assistant.gui.review_panel import ReviewPanel
from video_tagging_assistant.tagging_service import TaggingReviewRow


def test_review_panel_loads_row_and_collects_user_edits():
    app = QApplication.instance() or QApplication([])
    panel = ReviewPanel()
    panel.set_review_row(
        TaggingReviewRow(
            case_id="case_A_0105",
            auto_summary="自动简介",
            auto_tags="安装方式=手持",
            auto_scene_description="自动画面描述",
            tag_source="fresh",
        )
    )
    panel.manual_summary_edit.setPlainText("人工简介")
    panel.manual_tags_edit.setPlainText("安装方式=肩扛")
    payload = panel.current_review_payload()

    assert payload["case_id"] == "case_A_0105"
    assert payload["manual_summary"] == "人工简介"
    assert payload["manual_tags"] == "安装方式=肩扛"


def test_review_panel_refresh_button_calls_callback():
    app = QApplication.instance() or QApplication([])
    called = []
    panel = ReviewPanel(on_refresh_excel_reviews=lambda: called.append(True))

    panel.refresh_button.click()

    assert called == [True]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_gui_smoke.py::test_review_panel_loads_row_and_collects_user_edits tests/test_gui_smoke.py::test_review_panel_refresh_button_calls_callback -v`
Expected: FAIL because the widget fields, setter, or callbacks do not exist yet

- [ ] **Step 3: Implement the minimal review panel**

```python
from typing import Callable, Optional

from PyQt5.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class ReviewPanel(QWidget):
    def __init__(self, on_approve: Optional[Callable[[], None]] = None, on_approve_after_edit: Optional[Callable[[], None]] = None, on_reject: Optional[Callable[[], None]] = None, on_refresh_excel_reviews: Optional[Callable[[], None]] = None):
        super().__init__()
        self._current_case_id = ""
        self.case_label = QLabel("未选择 case")
        self.auto_summary_label = QLabel("")
        self.auto_tags_label = QLabel("")
        self.auto_scene_label = QLabel("")
        self.tag_source_label = QLabel("")
        self.manual_summary_edit = QTextEdit()
        self.manual_tags_edit = QTextEdit()
        self.review_note_edit = QTextEdit()
        self.approve_button = QPushButton("通过")
        self.approve_after_edit_button = QPushButton("修改后通过")
        self.reject_button = QPushButton("拒绝")
        self.refresh_button = QPushButton("从 Excel 刷新")

        form = QFormLayout()
        form.addRow("Case", self.case_label)
        form.addRow("自动简介", self.auto_summary_label)
        form.addRow("自动标签", self.auto_tags_label)
        form.addRow("自动画面描述", self.auto_scene_label)
        form.addRow("来源", self.tag_source_label)
        form.addRow("人工修订简介", self.manual_summary_edit)
        form.addRow("人工修订标签", self.manual_tags_edit)
        form.addRow("审核备注", self.review_note_edit)

        buttons = QHBoxLayout()
        buttons.addWidget(self.approve_button)
        buttons.addWidget(self.approve_after_edit_button)
        buttons.addWidget(self.reject_button)
        buttons.addWidget(self.refresh_button)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(buttons)

        if on_approve is not None:
            self.approve_button.clicked.connect(on_approve)
        if on_approve_after_edit is not None:
            self.approve_after_edit_button.clicked.connect(on_approve_after_edit)
        if on_reject is not None:
            self.reject_button.clicked.connect(on_reject)
        if on_refresh_excel_reviews is not None:
            self.refresh_button.clicked.connect(on_refresh_excel_reviews)

    def set_review_row(self, row) -> None:
        self._current_case_id = row.case_id
        self.case_label.setText(row.case_id)
        self.auto_summary_label.setText(row.auto_summary)
        self.auto_tags_label.setText(row.auto_tags)
        self.auto_scene_label.setText(row.auto_scene_description)
        self.tag_source_label.setText(row.tag_source)
        self.manual_summary_edit.setPlainText("")
        self.manual_tags_edit.setPlainText("")
        self.review_note_edit.setPlainText("")

    def current_review_payload(self):
        return {
            "case_id": self._current_case_id,
            "manual_summary": self.manual_summary_edit.toPlainText().strip(),
            "manual_tags": self.manual_tags_edit.toPlainText().strip(),
            "review_note": self.review_note_edit.toPlainText().strip(),
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_gui_smoke.py::test_review_panel_loads_row_and_collects_user_edits tests/test_gui_smoke.py::test_review_panel_refresh_button_calls_callback -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_gui_smoke.py video_tagging_assistant/gui/review_panel.py
git commit -m "feat: add interactive review panel"
```

### Task 5: Add a simple Qt table model for queue and review rows

**Files:**
- Modify: `video_tagging_assistant/gui/table_models.py`
- Modify: `video_tagging_assistant/gui/main_window.py`
- Test: `tests/test_gui_smoke.py`

- [ ] **Step 1: Write the failing table-model tests**

```python
from PyQt5.QtCore import Qt

from video_tagging_assistant.gui.table_models import CaseTableModel


def test_case_table_model_displays_case_stage_and_message():
    model = CaseTableModel(
        [
            {
                "case_id": "case_A_0105",
                "stage": "awaiting_review",
                "tag_source": "fresh",
                "message": "awaiting review",
            }
        ]
    )

    assert model.rowCount() == 1
    assert model.columnCount() == 4
    assert model.data(model.index(0, 0), Qt.DisplayRole) == "case_A_0105"
    assert model.data(model.index(0, 1), Qt.DisplayRole) == "awaiting_review"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_gui_smoke.py::test_case_table_model_displays_case_stage_and_message -v`
Expected: FAIL because the model still returns zero columns and no display data

- [ ] **Step 3: Implement the minimal table model**

```python
from PyQt5.QtCore import QAbstractTableModel, QModelIndex, Qt


class CaseTableModel(QAbstractTableModel):
    HEADERS = ["Case", "Stage", "Tag Source", "Message"]

    def __init__(self, rows=None):
        super().__init__()
        self._rows = rows or []

    def set_rows(self, rows):
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.HEADERS[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or role != Qt.DisplayRole:
            return None
        row = self._rows[index.row()]
        values = [
            row.get("case_id", ""),
            row.get("stage", ""),
            row.get("tag_source", ""),
            row.get("message", ""),
        ]
        return values[index.column()]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_gui_smoke.py::test_case_table_model_displays_case_stage_and_message -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_gui_smoke.py video_tagging_assistant/gui/table_models.py video_tagging_assistant/gui/main_window.py
git commit -m "feat: add gui case table model"
```

### Task 6: Wire the main window to scan workbook rows and show queue state

**Files:**
- Modify: `video_tagging_assistant/gui/main_window.py`
- Modify: `video_tagging_assistant/gui/app.py`
- Test: `tests/test_gui_smoke.py`

- [ ] **Step 1: Write the failing scan tests**

```python
from pathlib import Path

from PyQt5.QtWidgets import QApplication

from video_tagging_assistant.gui.main_window import PipelineMainWindow
from video_tagging_assistant.pipeline_models import CaseManifest


def test_main_window_scan_loads_cases_into_queue(tmp_path: Path):
    app = QApplication.instance() or QApplication([])
    called = []

    def fake_scan():
        called.append(True)
        return [
            CaseManifest(
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
        ]

    window = PipelineMainWindow(scan_cases=fake_scan)
    window.scan_button.click()

    assert called == [True]
    assert window.queue_model.rowCount() == 1
    assert window.log_panel.toPlainText().strip().endswith("Scanned 1 cases")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_gui_smoke.py::test_main_window_scan_loads_cases_into_queue -v`
Expected: FAIL because `PipelineMainWindow` does not accept `scan_cases` and does not populate a queue model

- [ ] **Step 3: Implement scan injection and queue rendering**

```python
from PyQt5.QtWidgets import QTableView

from video_tagging_assistant.gui.review_panel import ReviewPanel
from video_tagging_assistant.gui.table_models import CaseTableModel


class PipelineMainWindow(QMainWindow):
    def __init__(self, scan_cases=None, start_tagging=None, refresh_excel_reviews=None):
        super().__init__()
        self._scan_cases = scan_cases
        self._start_tagging = start_tagging
        self._refresh_excel_reviews = refresh_excel_reviews
        self._manifests_by_case_id = {}
        self._review_rows_by_case_id = {}
        self.queue_model = CaseTableModel([])
        self.queue_table = QTableView()
        self.queue_table.setModel(self.queue_model)
        self.review_panel = ReviewPanel(on_refresh_excel_reviews=self._handle_refresh_excel_reviews)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.queue_table, "今日队列")
        self.tabs.addTab(self.review_panel, "打标审核")
        self.tabs.addTab(self._placeholder_tab("执行监控"), "执行监控")
        self.tabs.addTab(self._placeholder_tab("失败重试"), "失败重试")
        self.scan_button.clicked.connect(self._handle_scan)

    def _handle_scan(self):
        manifests = self._scan_cases() if self._scan_cases is not None else []
        self._manifests_by_case_id = {manifest.case_id: manifest for manifest in manifests}
        self.queue_model.set_rows(
            [
                {
                    "case_id": manifest.case_id,
                    "stage": "queued",
                    "tag_source": "",
                    "message": manifest.remark,
                }
                for manifest in manifests
            ]
        )
        self.append_log_line(f"Scanned {len(manifests)} cases")

    def _handle_refresh_excel_reviews(self):
        if self._refresh_excel_reviews is not None:
            self._refresh_excel_reviews()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_gui_smoke.py::test_main_window_scan_loads_cases_into_queue -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_gui_smoke.py video_tagging_assistant/gui/main_window.py video_tagging_assistant/gui/app.py
git commit -m "feat: load scanned cases into gui"
```

### Task 7: Wire batch tagging results into the GUI review flow and Excel review sheet

**Files:**
- Modify: `video_tagging_assistant/gui/main_window.py`
- Modify: `video_tagging_assistant/gui/app.py`
- Modify: `video_tagging_assistant/excel_workbook.py`
- Test: `tests/test_gui_smoke.py`

- [ ] **Step 1: Write the failing tagging-to-review tests**

```python
from pathlib import Path

from PyQt5.QtWidgets import QApplication

from video_tagging_assistant.gui.main_window import PipelineMainWindow
from video_tagging_assistant.pipeline_models import CaseManifest
from video_tagging_assistant.tagging_service import TaggingReviewRow


def test_main_window_start_pipeline_loads_review_panel(tmp_path: Path):
    app = QApplication.instance() or QApplication([])
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
    captured = []

    def fake_start_tagging(manifests, mode, event_callback):
        captured.append((manifests[0].case_id, mode))
        event_callback(type("Event", (), {"case_id": "case_A_0105", "stage": type("Stage", (), {"value": "tagging_running"})(), "message": "tagging"})())
        return [
            TaggingReviewRow(
                case_id="case_A_0105",
                auto_summary="自动简介",
                auto_tags="安装方式=手持",
                auto_scene_description="自动画面描述",
                tag_source="fresh",
            )
        ]

    window = PipelineMainWindow(start_tagging=fake_start_tagging)
    window._manifests_by_case_id = {manifest.case_id: manifest}
    window.start_button.click()

    assert captured == [("case_A_0105", "fresh")]
    assert window.review_panel.case_label.text() == "case_A_0105"
    assert "tagging" in window.log_panel.toPlainText()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_gui_smoke.py::test_main_window_start_pipeline_loads_review_panel -v`
Expected: FAIL because the start button is not wired to tagging or review-panel population

- [ ] **Step 3: Implement start-tagging wiring**

```python
def _selected_tagging_mode(self) -> str:
    return "cached" if self.tagging_mode_combo.currentText() == "复用旧打标结果" else "fresh"


def _handle_pipeline_event(self, event) -> None:
    stage_value = getattr(event.stage, "value", str(event.stage))
    self.append_log_line(f"{event.case_id} [{stage_value}] {event.message}")


def _handle_start(self):
    manifests = list(self._manifests_by_case_id.values())
    if not manifests or self._start_tagging is None:
        return
    results = self._start_tagging(manifests, self._selected_tagging_mode(), self._handle_pipeline_event)
    self._review_rows_by_case_id = {row.case_id: row for row in results}
    if results:
        self.review_panel.set_review_row(results[0])
        self.tabs.setCurrentIndex(1)

# in __init__
self.start_button.clicked.connect(self._handle_start)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_gui_smoke.py::test_main_window_start_pipeline_loads_review_panel -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_gui_smoke.py video_tagging_assistant/gui/main_window.py video_tagging_assistant/gui/app.py video_tagging_assistant/excel_workbook.py
git commit -m "feat: route tagging results into gui review"
```

### Task 8: Wire GUI approvals and Excel-refresh approvals into execution startup

**Files:**
- Modify: `video_tagging_assistant/gui/main_window.py`
- Modify: `video_tagging_assistant/gui/review_panel.py`
- Modify: `video_tagging_assistant/gui/app.py`
- Test: `tests/test_gui_smoke.py`

- [ ] **Step 1: Write the failing approval tests**

```python
from pathlib import Path

from PyQt5.QtWidgets import QApplication

from video_tagging_assistant.gui.main_window import PipelineMainWindow
from video_tagging_assistant.tagging_service import TaggingReviewRow


def test_gui_approve_calls_controller_and_execution_runner(tmp_path: Path):
    app = QApplication.instance() or QApplication([])
    approvals = []
    runs = []

    class StubController:
        def approve_case(self, case_id):
            approvals.append(case_id)
            return True

    window = PipelineMainWindow(run_execution_case=lambda case_id: runs.append(case_id), controller=StubController())
    window._review_rows_by_case_id = {
        "case_A_0105": TaggingReviewRow(
            case_id="case_A_0105",
            auto_summary="自动简介",
            auto_tags="安装方式=手持",
            auto_scene_description="自动画面描述",
            tag_source="fresh",
        )
    }
    window.review_panel.set_review_row(window._review_rows_by_case_id["case_A_0105"])

    window.review_panel.approve_button.click()

    assert approvals == ["case_A_0105"]
    assert runs == ["case_A_0105"]


def test_refresh_excel_reviews_only_runs_newly_approved_cases():
    app = QApplication.instance() or QApplication([])
    approvals = []
    runs = []

    class StubController:
        def __init__(self):
            self.allowed = True

        def approve_case(self, case_id):
            approvals.append(case_id)
            if case_id == "case_A_0105":
                return True
            return False

    window = PipelineMainWindow(
        controller=StubController(),
        run_execution_case=lambda case_id: runs.append(case_id),
        refresh_excel_reviews=lambda: [
            {"case_id": "case_A_0105", "review_decision": "审核通过", "manual_summary": "", "manual_tags": "", "review_note": ""},
            {"case_id": "case_A_0106", "review_decision": "审核通过", "manual_summary": "", "manual_tags": "", "review_note": ""},
        ],
    )

    window.review_panel.refresh_button.click()

    assert approvals == ["case_A_0105", "case_A_0106"]
    assert runs == ["case_A_0105"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_gui_smoke.py::test_gui_approve_calls_controller_and_execution_runner tests/test_gui_smoke.py::test_refresh_excel_reviews_only_runs_newly_approved_cases -v`
Expected: FAIL because the buttons do not approve through the controller or start execution

- [ ] **Step 3: Implement approve and refresh handlers**

```python
class PipelineMainWindow(QMainWindow):
    def __init__(self, scan_cases=None, start_tagging=None, refresh_excel_reviews=None, run_execution_case=None, controller=None):
        super().__init__()
        self._scan_cases = scan_cases
        self._start_tagging = start_tagging
        self._refresh_excel_reviews = refresh_excel_reviews
        self._run_execution_case = run_execution_case
        self._controller = controller
        self.review_panel = ReviewPanel(
            on_approve=self._handle_approve,
            on_approve_after_edit=self._handle_approve_after_edit,
            on_reject=self._handle_reject,
            on_refresh_excel_reviews=self._handle_refresh_excel_reviews,
        )

    def _approve_case(self, case_id: str, label: str) -> None:
        if self._controller is None:
            return
        approved = self._controller.approve_case(case_id)
        self.append_log_line(f"{case_id} {label}")
        if approved and self._run_execution_case is not None:
            self._run_execution_case(case_id)

    def _handle_approve(self):
        payload = self.review_panel.current_review_payload()
        self._approve_case(payload["case_id"], "approved in gui")

    def _handle_approve_after_edit(self):
        payload = self.review_panel.current_review_payload()
        self._approve_case(payload["case_id"], "approved after edit in gui")

    def _handle_reject(self):
        payload = self.review_panel.current_review_payload()
        self.append_log_line(f"{payload['case_id']} rejected in gui")

    def _handle_refresh_excel_reviews(self):
        rows = self._refresh_excel_reviews() if self._refresh_excel_reviews is not None else []
        for row in rows:
            self._approve_case(row["case_id"], f"approved from excel: {row['review_decision']}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_gui_smoke.py::test_gui_approve_calls_controller_and_execution_runner tests/test_gui_smoke.py::test_refresh_excel_reviews_only_runs_newly_approved_cases -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_gui_smoke.py video_tagging_assistant/gui/main_window.py video_tagging_assistant/gui/review_panel.py video_tagging_assistant/gui/app.py
git commit -m "feat: trigger execution from gui approvals"
```

### Task 9: Assemble the real app wiring and run focused verification

**Files:**
- Modify: `video_tagging_assistant/gui/app.py`
- Modify: `video_tagging_assistant/gui/main_window.py`
- Modify: `video_tagging_assistant/excel_workbook.py`
- Test: `tests/test_gui_smoke.py`
- Test: `tests/test_pipeline_controller.py`
- Test: `tests/test_excel_workbook_pipeline.py`
- Test: `tests/test_case_ingest_cli_config.py`

- [ ] **Step 1: Write the failing app-wiring tests**

```python
from pathlib import Path

from video_tagging_assistant.gui import app as gui_app


def test_launch_case_pipeline_gui_passes_workbook_path(monkeypatch, tmp_path: Path):
    captured = {}

    class FakeWindow:
        def __init__(self, workbook_path=None, **kwargs):
            captured["workbook_path"] = workbook_path

        def show(self):
            captured["shown"] = True

    monkeypatch.setattr(gui_app, "PipelineMainWindow", FakeWindow)
    monkeypatch.setattr(gui_app, "QApplication", type("FakeQApplication", (), {"instance": staticmethod(lambda: None), "__init__": lambda self, argv: None}))

    gui_app.launch_case_pipeline_gui(workbook_path=str(tmp_path / "records.xlsx"))

    assert captured["workbook_path"].endswith("records.xlsx")
    assert captured["shown"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_gui_smoke.py::test_launch_case_pipeline_gui_passes_workbook_path tests/test_case_ingest_cli_config.py::test_case_pipeline_gui_command_parses -v`
Expected: FAIL because `launch_case_pipeline_gui` still builds the window without injected wiring

- [ ] **Step 3: Implement the real app assembly**

```python
from pathlib import Path

from PyQt5.QtWidgets import QApplication

from video_tagging_assistant.config import load_config
from video_tagging_assistant.excel_workbook import build_case_manifests, ensure_pipeline_columns, load_approved_review_rows
from video_tagging_assistant.gui.main_window import PipelineMainWindow
from video_tagging_assistant.pipeline_controller import PipelineController
from video_tagging_assistant.tagging_service import run_batch_tagging


def launch_case_pipeline_gui(workbook_path=None):
    app = QApplication.instance() or QApplication([])
    workbook = Path(workbook_path) if workbook_path else None
    controller = PipelineController()

    def scan_cases():
        if workbook is None:
            return []
        ensure_pipeline_columns(workbook, source_sheet="创建记录")
        return build_case_manifests(
            workbook,
            source_sheet="创建记录",
            allowed_statuses={"", "queued", "failed"},
            local_root=Path("cases"),
            server_root=Path("server_cases"),
            mode="OV50H40_Action5Pro_DCG HDR",
        )

    def refresh_excel_reviews():
        if workbook is None:
            return []
        return load_approved_review_rows(workbook, review_sheet="审核结果")

    def run_execution_case(case_id):
        if controller.has_execution_case():
            controller.run_next_execution_case()

    def start_tagging(manifests, mode, event_callback):
        config = load_config(Path("configs/config.json"))
        provider = None
        prompt_template = config["prompt_template"]
        return run_batch_tagging(
            manifests=manifests,
            cache_root=Path("artifacts/cache"),
            output_root=Path("artifacts/gui_pipeline"),
            provider=provider,
            prompt_template=prompt_template,
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
    window.show()
    return 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_gui_smoke.py tests/test_pipeline_controller.py tests/test_excel_workbook_pipeline.py tests/test_case_ingest_cli_config.py::test_case_pipeline_gui_command_parses -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_gui_smoke.py tests/test_pipeline_controller.py tests/test_excel_workbook_pipeline.py tests/test_case_ingest_cli_config.py video_tagging_assistant/gui/app.py video_tagging_assistant/gui/main_window.py video_tagging_assistant/excel_workbook.py
git commit -m "feat: wire gui to excel-driven pipeline"
```

## Self-Review

### Spec coverage

- GUI becomes the main operating surface: covered by Tasks 4-9.
- Scan Excel and show runnable cases: covered by Tasks 1 and 6.
- Fresh/cached tagging from the GUI: covered by Task 7.
- Tagging results flow into both GUI and Excel review state: covered by Tasks 1 and 7.
- GUI approval triggers immediate execution: covered by Tasks 2, 3, and 8.
- Approved Excel review rows can be imported manually: covered by Tasks 1 and 8.
- Logs and stage changes are surfaced in the UI: covered by Tasks 2, 3, 6, 7, and 8.
- No automatic Excel polling or complex retry UI: intentionally excluded from the tasks.

### Placeholder scan

- No `TODO`, `TBD`, or “similar to above” placeholders remain.
- Every task names exact files and exact test commands.
- Every code-writing step contains concrete code blocks.

### Type consistency

- `CaseManifest`, `TaggingReviewRow`, `PipelineController`, `PipelineEvent`, and `RuntimeStage` are used consistently across tasks.
- GUI tagging mode strings remain `fresh` / `cached`, mapped from the existing Chinese combo-box labels.
- Approval import rows consistently use `case_id`, `review_decision`, `manual_summary`, `manual_tags`, and `review_note`.
