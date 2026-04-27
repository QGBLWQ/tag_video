# Excel Tag Review Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an Excel-centered post-generation review workflow that reads confirmed case rows from `创建记录`, writes AI tag candidates into a new `标签审核` sheet, syncs approved results back to `创建记录`, and marks cases ready for archive.

**Architecture:** Keep the existing video-tagging pipeline intact for generation, then add a separate Excel integration layer around it. The new layer should treat `创建记录` as the source of truth for manually confirmed case pairing, use `文件夹名` as the case key, and keep AI draft data isolated in `标签审核` until a human approves it.

**Tech Stack:** Python 3.8+, openpyxl, existing `video_tagging_assistant` pipeline modules, pytest.

---

## File Structure

- Modify: `video_tagging_assistant/config.py` — validate new Excel workflow config sections.
- Create: `video_tagging_assistant/excel_models.py` — dataclasses for Excel case rows, review rows, and sync summaries.
- Create: `video_tagging_assistant/excel_workbook.py` — load workbook, locate sheets/columns, read `创建记录`, create/update `标签审核`, and write sync fields back.
- Create: `video_tagging_assistant/excel_pipeline.py` — orchestrate “load confirmed cases → generate AI review rows → sync approved rows”.
- Modify: `video_tagging_assistant/models.py` — extend result models only where needed to carry Excel case key metadata without overloading existing generation fields.
- Modify: `video_tagging_assistant/context_builder.py` — include `文件夹名` and selected Excel fields in prompt context for downstream provider use.
- Modify: `video_tagging_assistant/orchestrator.py` — support a workbook-driven execution path in addition to directory scan mode.
- Modify: `video_tagging_assistant/cli.py` — expose explicit Excel workflow commands.
- Modify: `video_tagging_assistant/review_exporter.py` — optionally emit text review entries keyed by `文件夹名` for debugging, while Excel remains the canonical review surface.
- Test: `tests/test_config.py` — config validation for Excel workflow settings.
- Create: `tests/test_excel_models.py` — dataclass defaults and final-result resolution.
- Create: `tests/test_excel_workbook.py` — workbook read/write behavior.
- Create: `tests/test_excel_pipeline.py` — end-to-end workbook-driven flow with stubs.
- Modify: `tests/test_context_builder.py` — workbook metadata in prompt context.
- Modify: `tests/test_pipeline.py` — orchestrator workbook entry path.
- Modify: `tests/test_provider.py` — provider-facing context expectations stay compatible.

## Assumptions Locked In

- Source workbook is `PC_A_采集记录表v2.1.xlsm`, but implementation should use configurable sheet names instead of hard-coding only this file.
- `创建记录` remains the manually confirmed source sheet.
- `标签审核` is a new sheet created and maintained by the Python tool.
- Case identity is the `文件夹名` column value.
- Automatic fill-back only happens after a human sets an approval status in `标签审核`.
- This first version updates workbook cells and status fields only; actual file moves can be represented as “ready to archive” status and target path preparation, with physical archive move logic deferred unless already trivial in code.

### Task 1: Add workbook workflow config

**Files:**
- Modify: `video_tagging_assistant/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing config test for required Excel sections**

```python
from pathlib import Path

import pytest

from video_tagging_assistant.config import load_config


def test_load_config_accepts_excel_workflow_sections(tmp_path: Path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        """
        {
          "input_dir": "videos",
          "output_dir": "output",
          "compression": {"width": 960, "video_bitrate": "700k", "audio_bitrate": "96k", "fps": 12},
          "provider": {"name": "mock", "model": "mock-video-tagger"},
          "prompt_template": {"system": "describe"},
          "excel_workflow": {
            "enabled": true,
            "workbook_path": "PC_A_采集记录表v2.1.xlsm",
            "source_sheet": "创建记录",
            "review_sheet": "标签审核",
            "case_key_column": "文件夹名"
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config["excel_workflow"]["enabled"] is True
    assert config["excel_workflow"]["review_sheet"] == "标签审核"
```

- [ ] **Step 2: Run test to verify it fails if config normalization is missing**

Run: `pytest tests/test_config.py::test_load_config_accepts_excel_workflow_sections -v`
Expected: FAIL if `excel_workflow` keys are dropped or not validated.

- [ ] **Step 3: Add minimal config normalization for workbook workflow**

```python
EXCEL_WORKFLOW_DEFAULTS = {
    "enabled": False,
    "source_sheet": "创建记录",
    "review_sheet": "标签审核",
    "case_key_column": "文件夹名",
    "status_column": "标签审核状态",
}


def load_config(config_path: Path) -> Dict:
    config_path = Path(config_path)
    data = json.loads(config_path.read_text(encoding="utf-8"))
    missing = REQUIRED_TOP_LEVEL_KEYS - set(data)
    if missing:
        missing_list = ", ".join(sorted(missing))
        raise ValueError(f"Missing config keys: {missing_list}")

    workflow = dict(EXCEL_WORKFLOW_DEFAULTS)
    workflow.update(data.get("excel_workflow", {}))
    if workflow["enabled"] and not workflow.get("workbook_path"):
        raise ValueError("excel_workflow.workbook_path is required when enabled")
    data["excel_workflow"] = workflow
    return data
```

- [ ] **Step 4: Run targeted config tests**

Run: `pytest tests/test_config.py -v`
Expected: PASS for existing config tests and new Excel workflow test.

- [ ] **Step 5: Commit**

```bash
git add tests/test_config.py video_tagging_assistant/config.py
git commit -m "feat: add excel workflow config"
```

### Task 2: Model confirmed workbook rows and review decisions

**Files:**
- Create: `video_tagging_assistant/excel_models.py`
- Test: `tests/test_excel_models.py`
- Modify: `video_tagging_assistant/models.py`

- [ ] **Step 1: Write failing tests for Excel row models and final-value resolution**

```python
from pathlib import Path

from video_tagging_assistant.excel_models import ConfirmedCaseRow, ReviewSheetRow


def test_review_sheet_row_prefers_manual_values():
    row = ReviewSheetRow(
        case_key="case_A_0001",
        workbook_row_index=2,
        raw_path="//server/case_A_0001/raw",
        video_path="//server/case_A_0001/video.mp4",
        auto_summary="自动简介",
        auto_tags="安装方式=手持;运动模式=行走",
        manual_summary="人工简介",
        manual_tags="安装方式=穿戴;运动模式=跑步",
        review_decision="修改后通过",
    )

    assert row.final_summary == "人工简介"
    assert row.final_tags == "安装方式=穿戴;运动模式=跑步"


def test_confirmed_case_row_exposes_case_directory_name():
    row = ConfirmedCaseRow(
        case_key="case_A_0001",
        workbook_row_index=2,
        raw_path="//server/case_A_0001/raw",
        vs_normal_path="//server/case_A_0001/normal.mp4",
        vs_night_path="//server/case_A_0001/night.mp4",
        note="场景备注",
        attributes={"安装方式": "手持"},
    )

    assert row.case_key == "case_A_0001"
    assert row.attributes["安装方式"] == "手持"
```

- [ ] **Step 2: Run tests to verify the module does not exist yet**

Run: `pytest tests/test_excel_models.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement focused Excel workflow dataclasses**

```python
from dataclasses import dataclass, field
from typing import Dict


@dataclass
class ConfirmedCaseRow:
    case_key: str
    workbook_row_index: int
    raw_path: str
    vs_normal_path: str
    vs_night_path: str
    note: str
    attributes: Dict[str, str] = field(default_factory=dict)


@dataclass
class ReviewSheetRow:
    case_key: str
    workbook_row_index: int
    raw_path: str
    video_path: str
    auto_summary: str = ""
    auto_tags: str = ""
    auto_scene_description: str = ""
    manual_summary: str = ""
    manual_tags: str = ""
    review_decision: str = "待审核"

    @property
    def final_summary(self) -> str:
        return self.manual_summary.strip() or self.auto_summary.strip()

    @property
    def final_tags(self) -> str:
        return self.manual_tags.strip() or self.auto_tags.strip()
```

- [ ] **Step 4: Add optional case-key metadata to generation results**

```python
@dataclass
class GenerationResult:
    source_video_path: Path
    summary_text: str = ""
    tags: List[str] = field(default_factory=list)
    notes: str = ""
    structured_tags: Dict[str, str] = field(default_factory=dict)
    multi_select_tags: Dict[str, List[str]] = field(default_factory=dict)
    scene_description: str = ""
    provider: str = ""
    model: str = ""
    raw_response_excerpt: str = ""
    review_status: str = "unreviewed"
    case_key: str = ""
```

- [ ] **Step 5: Run model tests**

Run: `pytest tests/test_excel_models.py tests/test_structured_result_model.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tests/test_excel_models.py video_tagging_assistant/excel_models.py video_tagging_assistant/models.py
git commit -m "feat: add workbook case models"
```

### Task 3: Read confirmed cases from `创建记录` and manage `标签审核`

**Files:**
- Create: `video_tagging_assistant/excel_workbook.py`
- Test: `tests/test_excel_workbook.py`

- [ ] **Step 1: Write failing workbook tests for source and review sheets**

```python
from pathlib import Path

from openpyxl import Workbook

from video_tagging_assistant.excel_workbook import load_confirmed_cases, upsert_review_rows
from video_tagging_assistant.excel_models import ReviewSheetRow


def build_workbook(path: Path) -> None:
    wb = Workbook()
    source = wb.active
    source.title = "创建记录"
    source.append(["序号", "文件夹名", "备注", "Raw存放路径", "VS_Nomal", "VS_Night", "安装方式", "运动模式", "标签审核状态"])
    source.append([1, "case_A_0001", "场景备注", "raw/path", "normal.mp4", "night.mp4", "手持", "行走", "待生成"])
    wb.save(path)


def test_load_confirmed_cases_reads_source_sheet(tmp_path: Path):
    workbook_path = tmp_path / "records.xlsx"
    build_workbook(workbook_path)

    rows = load_confirmed_cases(
        workbook_path,
        source_sheet="创建记录",
        case_key_column="文件夹名",
        status_column="标签审核状态",
    )

    assert len(rows) == 1
    assert rows[0].case_key == "case_A_0001"
    assert rows[0].raw_path == "raw/path"


def test_upsert_review_rows_creates_review_sheet(tmp_path: Path):
    workbook_path = tmp_path / "records.xlsx"
    build_workbook(workbook_path)

    upsert_review_rows(
        workbook_path,
        review_sheet="标签审核",
        rows=[
            ReviewSheetRow(
                case_key="case_A_0001",
                workbook_row_index=2,
                raw_path="raw/path",
                video_path="normal.mp4",
                auto_summary="自动简介",
                auto_tags="安装方式=手持",
            )
        ],
    )

    rows = load_workbook(workbook_path)["标签审核"]
    assert rows["A2"].value == "case_A_0001"
    assert rows["E2"].value == "自动简介"
```

- [ ] **Step 2: Run the new workbook tests to confirm missing implementation**

Run: `pytest tests/test_excel_workbook.py -v`
Expected: FAIL with `ModuleNotFoundError` or missing functions.

- [ ] **Step 3: Implement workbook helpers with explicit headers**

```python
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


def load_confirmed_cases(workbook_path: Path, source_sheet: str, case_key_column: str, status_column: str):
    workbook = load_workbook(workbook_path)
    sheet = workbook[source_sheet]
    header_map = {cell.value: idx + 1 for idx, cell in enumerate(sheet[1])}
    rows = []
    for row_index in range(2, sheet.max_row + 1):
        case_key = sheet.cell(row_index, header_map[case_key_column]).value
        if not case_key:
            continue
        rows.append(
            ConfirmedCaseRow(
                case_key=str(case_key).strip(),
                workbook_row_index=row_index,
                raw_path=str(sheet.cell(row_index, header_map["Raw存放路径"]).value or "").strip(),
                vs_normal_path=str(sheet.cell(row_index, header_map["VS_Nomal"]).value or "").strip(),
                vs_night_path=str(sheet.cell(row_index, header_map["VS_Night"]).value or "").strip(),
                note=str(sheet.cell(row_index, header_map["备注"]).value or "").strip(),
                attributes={
                    "安装方式": str(sheet.cell(row_index, header_map["安装方式"]).value or "").strip(),
                    "运动模式": str(sheet.cell(row_index, header_map["运动模式"]).value or "").strip(),
                },
            )
        )
    return rows
```

- [ ] **Step 4: Run workbook tests**

Run: `pytest tests/test_excel_workbook.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_excel_workbook.py video_tagging_assistant/excel_workbook.py
git commit -m "feat: add excel workbook helpers"
```

### Task 4: Carry workbook metadata into prompt context

**Files:**
- Modify: `video_tagging_assistant/context_builder.py`
- Modify: `tests/test_context_builder.py`

- [ ] **Step 1: Write a failing context-builder test for workbook metadata**

```python
from pathlib import Path

from video_tagging_assistant.context_builder import build_prompt_context
from video_tagging_assistant.excel_models import ConfirmedCaseRow
from video_tagging_assistant.models import CompressedArtifact, VideoTask


def test_build_prompt_context_includes_excel_case_metadata():
    task = VideoTask(
        source_video_path=Path("videos/case_A_0001/clip01.mp4"),
        relative_path=Path("DCG_HDR/case_A_0001/clip01.mp4"),
        file_name="clip01.mp4",
        case_id="case_A_0001",
    )
    artifact = CompressedArtifact(
        source_video_path=task.source_video_path,
        compressed_video_path=Path("output/compressed/clip01_proxy.mp4"),
    )
    case_row = ConfirmedCaseRow(
        case_key="case_A_0001",
        workbook_row_index=2,
        raw_path="raw/path",
        vs_normal_path="normal.mp4",
        vs_night_path="night.mp4",
        note="场景备注",
        attributes={"安装方式": "手持", "运动模式": "行走"},
    )

    context = build_prompt_context(task, artifact, {"system": "describe"}, case_row=case_row)

    assert context.prompt_payload["workbook"]["文件夹名"] == "case_A_0001"
    assert context.prompt_payload["workbook"]["备注"] == "场景备注"
```

- [ ] **Step 2: Run the new test to verify the signature does not support workbook rows yet**

Run: `pytest tests/test_context_builder.py::test_build_prompt_context_includes_excel_case_metadata -v`
Expected: FAIL with unexpected keyword argument `case_row`.

- [ ] **Step 3: Add optional workbook context to `build_prompt_context`**

```python
from typing import Optional

from video_tagging_assistant.excel_models import ConfirmedCaseRow


def build_prompt_context(task, artifact, template_fields, case_row: Optional[ConfirmedCaseRow] = None):
    ...
    workbook_payload = {}
    if case_row is not None:
        workbook_payload = {
            "文件夹名": case_row.case_key,
            "备注": case_row.note,
            "Raw存放路径": case_row.raw_path,
            "VS_Nomal": case_row.vs_normal_path,
            "VS_Night": case_row.vs_night_path,
            "已确认属性": case_row.attributes,
        }

    prompt_payload = {
        "template": template_fields,
        "video": {
            "source_path": str(task.source_video_path),
            "compressed_path": str(artifact.compressed_video_path),
        },
        "metadata": parsed_metadata,
        "workbook": workbook_payload,
    }
```

- [ ] **Step 4: Run context and provider compatibility tests**

Run: `pytest tests/test_context_builder.py tests/test_provider.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_context_builder.py video_tagging_assistant/context_builder.py
git commit -m "feat: add workbook metadata to prompt context"
```

### Task 5: Build workbook-driven generation and review-row upsert flow

**Files:**
- Create: `video_tagging_assistant/excel_pipeline.py`
- Create: `tests/test_excel_pipeline.py`
- Modify: `video_tagging_assistant/review_exporter.py`

- [ ] **Step 1: Write failing pipeline tests for generation from confirmed cases**

```python
from pathlib import Path

from openpyxl import Workbook, load_workbook

from video_tagging_assistant.excel_pipeline import generate_review_sheet
from video_tagging_assistant.models import CompressedArtifact, GenerationResult


class StubCompressor:
    def __call__(self, task, output_dir, compression_config):
        output_dir.mkdir(parents=True, exist_ok=True)
        proxy = output_dir / f"{Path(task.file_name).stem}_proxy.mp4"
        proxy.write_bytes(b"proxy")
        return CompressedArtifact(task.source_video_path, proxy)


class StubProvider:
    provider_name = "stub"

    def generate(self, context):
        return GenerationResult(
            source_video_path=context.source_video_path,
            case_key=context.prompt_payload["workbook"]["文件夹名"],
            summary_text="自动简介",
            structured_tags={"安装方式": "手持", "运动模式": "行走"},
            scene_description="画面描述",
            provider="stub",
            model="stub-model",
        )


def test_generate_review_sheet_writes_ai_rows(tmp_path: Path):
    workbook_path = tmp_path / "records.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "创建记录"
    ws.append(["序号", "文件夹名", "备注", "Raw存放路径", "VS_Nomal", "VS_Night", "安装方式", "运动模式", "标签审核状态"])
    source_video = tmp_path / "cases" / "case_A_0001" / "clip01.mp4"
    source_video.parent.mkdir(parents=True)
    source_video.write_bytes(b"video")
    ws.append([1, "case_A_0001", "场景备注", "raw/path", str(source_video), "night.mp4", "手持", "行走", "待生成"])
    wb.save(workbook_path)

    summary = generate_review_sheet(
        config={
            "output_dir": str(tmp_path / "output"),
            "compression": {"width": 960, "video_bitrate": "700k", "audio_bitrate": "96k", "fps": 12},
            "prompt_template": {"system": "describe"},
            "excel_workflow": {
                "workbook_path": str(workbook_path),
                "source_sheet": "创建记录",
                "review_sheet": "标签审核",
                "case_key_column": "文件夹名",
                "status_column": "标签审核状态",
            },
        },
        compressor=StubCompressor(),
        provider=StubProvider(),
    )

    review_sheet = load_workbook(workbook_path)["标签审核"]
    assert summary["generated"] == 1
    assert review_sheet["A2"].value == "case_A_0001"
    assert review_sheet["E2"].value == "自动简介"
```

- [ ] **Step 2: Run the pipeline test to verify implementation is missing**

Run: `pytest tests/test_excel_pipeline.py::test_generate_review_sheet_writes_ai_rows -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `generate_review_sheet` with confirmed-case orchestration**

```python
def generate_review_sheet(config, compressor, provider):
    workflow = config["excel_workflow"]
    workbook_path = Path(workflow["workbook_path"])
    output_dir = Path(config["output_dir"])
    compressed_dir = output_dir / "compressed"

    confirmed_rows = load_confirmed_cases(
        workbook_path,
        source_sheet=workflow["source_sheet"],
        case_key_column=workflow["case_key_column"],
        status_column=workflow["status_column"],
    )

    review_rows = []
    for case_row in confirmed_rows:
        source_video_path = Path(case_row.vs_normal_path)
        task = VideoTask(
            source_video_path=source_video_path,
            relative_path=Path(case_row.case_key) / source_video_path.name,
            file_name=source_video_path.name,
            case_id=case_row.case_key,
        )
        artifact = compressor(task, compressed_dir, config["compression"])
        context = build_prompt_context(task, artifact, config["prompt_template"], case_row=case_row)
        result = provider.generate(context)
        review_rows.append(
            ReviewSheetRow(
                case_key=case_row.case_key,
                workbook_row_index=case_row.workbook_row_index,
                raw_path=case_row.raw_path,
                video_path=case_row.vs_normal_path,
                auto_summary=result.summary_text,
                auto_tags=";".join(f"{k}={v}" for k, v in result.structured_tags.items()),
                auto_scene_description=result.scene_description,
            )
        )

    upsert_review_rows(workbook_path, workflow["review_sheet"], review_rows)
    return {"generated": len(review_rows), "workbook_path": str(workbook_path)}
```

- [ ] **Step 4: Add an exporter helper for workbook-tag debugging output**

```python
def format_structured_tags(structured_tags: dict) -> str:
    return ";".join(f"{key}={value}" for key, value in structured_tags.items())
```

- [ ] **Step 5: Run pipeline and exporter tests**

Run: `pytest tests/test_excel_pipeline.py tests/test_review_exporter.py tests/test_review_exporter_structured.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tests/test_excel_pipeline.py video_tagging_assistant/excel_pipeline.py video_tagging_assistant/review_exporter.py
git commit -m "feat: generate excel review sheet rows"
```

### Task 6: Sync approved review results back to `创建记录`

**Files:**
- Modify: `video_tagging_assistant/excel_workbook.py`
- Modify: `tests/test_excel_workbook.py`
- Create: `tests/test_excel_sync.py`

- [ ] **Step 1: Write failing sync tests for approved review rows**

```python
from pathlib import Path

from openpyxl import Workbook, load_workbook

from video_tagging_assistant.excel_workbook import sync_approved_rows


def test_sync_approved_rows_updates_source_sheet(tmp_path: Path):
    workbook_path = tmp_path / "records.xlsx"
    wb = Workbook()
    source = wb.active
    source.title = "创建记录"
    source.append(["文件夹名", "标签审核状态", "最终简介", "最终标签"])
    source.append(["case_A_0001", "待审核", "", ""])
    review = wb.create_sheet("标签审核")
    review.append(["文件夹名", "创建记录行号", "自动简介", "自动标签", "审核结论", "人工修订简介", "人工修订标签"])
    review.append(["case_A_0001", 2, "自动简介", "安装方式=手持", "审核通过", "", ""])
    wb.save(workbook_path)

    sync_approved_rows(workbook_path, source_sheet="创建记录", review_sheet="标签审核")

    source_sheet = load_workbook(workbook_path)["创建记录"]
    assert source_sheet["B2"].value == "审核通过"
    assert source_sheet["C2"].value == "自动简介"
    assert source_sheet["D2"].value == "安装方式=手持"
```

- [ ] **Step 2: Run sync tests to confirm missing function**

Run: `pytest tests/test_excel_sync.py::test_sync_approved_rows_updates_source_sheet -v`
Expected: FAIL with missing function.

- [ ] **Step 3: Implement minimal sync-back behavior**

```python
def sync_approved_rows(workbook_path: Path, source_sheet: str, review_sheet: str):
    workbook = load_workbook(workbook_path)
    source = workbook[source_sheet]
    review = workbook[review_sheet]
    source_headers = {cell.value: idx + 1 for idx, cell in enumerate(source[1])}
    review_headers = {cell.value: idx + 1 for idx, cell in enumerate(review[1])}

    for row_index in range(2, review.max_row + 1):
        decision = str(review.cell(row_index, review_headers["审核结论"]).value or "").strip()
        if decision not in {"审核通过", "修改后通过"}:
            continue
        source_row = int(review.cell(row_index, review_headers["创建记录行号"]).value)
        manual_summary = str(review.cell(row_index, review_headers["人工修订简介"]).value or "").strip()
        manual_tags = str(review.cell(row_index, review_headers["人工修订标签"]).value or "").strip()
        auto_summary = str(review.cell(row_index, review_headers["自动简介"]).value or "").strip()
        auto_tags = str(review.cell(row_index, review_headers["自动标签"]).value or "").strip()

        source.cell(source_row, source_headers["最终简介"]).value = manual_summary or auto_summary
        source.cell(source_row, source_headers["最终标签"]).value = manual_tags or auto_tags
        source.cell(source_row, source_headers["标签审核状态"]).value = decision

    workbook.save(workbook_path)
```

- [ ] **Step 4: Run sync tests**

Run: `pytest tests/test_excel_sync.py tests/test_excel_workbook.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_excel_sync.py tests/test_excel_workbook.py video_tagging_assistant/excel_workbook.py
git commit -m "feat: sync approved excel tags back to source sheet"
```

### Task 7: Add workbook workflow entry points to orchestrator and CLI

**Files:**
- Modify: `video_tagging_assistant/orchestrator.py`
- Modify: `video_tagging_assistant/cli.py`
- Modify: `tests/test_pipeline.py`

- [ ] **Step 1: Write failing orchestrator tests for workbook mode**

```python
from pathlib import Path

from openpyxl import Workbook

from video_tagging_assistant.orchestrator import run_excel_workflow


def test_run_excel_workflow_returns_generation_summary(tmp_path: Path):
    workbook_path = tmp_path / "records.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "创建记录"
    ws.append(["序号", "文件夹名", "备注", "Raw存放路径", "VS_Nomal", "VS_Night", "安装方式", "运动模式", "标签审核状态", "最终简介", "最终标签"])
    video_path = tmp_path / "case_A_0001.mp4"
    video_path.write_bytes(b"video")
    ws.append([1, "case_A_0001", "场景备注", "raw/path", str(video_path), "night.mp4", "手持", "行走", "待生成", "", ""])
    wb.save(workbook_path)

    class StubCompressor:
        def __call__(self, task, output_dir, compression_config):
            from video_tagging_assistant.models import CompressedArtifact
            output_dir.mkdir(parents=True, exist_ok=True)
            proxy = output_dir / "proxy.mp4"
            proxy.write_bytes(b"proxy")
            return CompressedArtifact(task.source_video_path, proxy)

    class StubProvider:
        provider_name = "stub"

        def generate(self, context):
            from video_tagging_assistant.models import GenerationResult
            return GenerationResult(
                source_video_path=context.source_video_path,
                case_key="case_A_0001",
                summary_text="自动简介",
                structured_tags={"安装方式": "手持"},
                scene_description="画面描述",
                provider="stub",
                model="stub-model",
            )

    summary = run_excel_workflow(
        {
            "output_dir": str(tmp_path / "output"),
            "compression": {"width": 960, "video_bitrate": "700k", "audio_bitrate": "96k", "fps": 12},
            "prompt_template": {"system": "describe"},
            "excel_workflow": {
                "enabled": True,
                "workbook_path": str(workbook_path),
                "source_sheet": "创建记录",
                "review_sheet": "标签审核",
                "case_key_column": "文件夹名",
                "status_column": "标签审核状态"
            }
        },
        compressor=StubCompressor(),
        provider=StubProvider(),
    )

    assert summary["generated"] == 1
```

- [ ] **Step 2: Run orchestrator workbook test to confirm missing entry point**

Run: `pytest tests/test_pipeline.py::test_run_excel_workflow_returns_generation_summary -v`
Expected: FAIL with missing function.

- [ ] **Step 3: Add explicit workbook entry points**

```python
from video_tagging_assistant.excel_pipeline import generate_review_sheet
from video_tagging_assistant.excel_workbook import sync_approved_rows


def run_excel_workflow(config, compressor=compress_video, provider=None):
    if provider is None:
        raise ValueError("provider is required")
    return generate_review_sheet(config, compressor=compressor, provider=provider)


def run_excel_sync(config):
    workflow = config["excel_workflow"]
    sync_approved_rows(
        Path(workflow["workbook_path"]),
        source_sheet=workflow["source_sheet"],
        review_sheet=workflow["review_sheet"],
    )
    return {"synced": True, "workbook_path": workflow["workbook_path"]}
```

- [ ] **Step 4: Add CLI subcommands for generation and sync**

```python
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument(
        "--mode",
        choices=["batch", "excel-generate", "excel-sync"],
        default="batch",
    )
    args = parser.parse_args()

    config = load_config(Path(args.config))
    provider = build_provider_from_config(config)
    if args.mode == "excel-generate":
        summary = run_excel_workflow(config, provider=provider)
        print(f"Generated {summary['generated']} review rows")
        return 0
    if args.mode == "excel-sync":
        summary = run_excel_sync(config)
        print(f"Synced approved rows for workbook: {summary['workbook_path']}")
        return 0

    summary = run_batch(config, provider=provider)
    print(f"Processed {summary['processed']} videos")
    print(f"Review list: {summary['review_path']}")
    return 0
```

- [ ] **Step 5: Run pipeline and CLI tests**

Run: `pytest tests/test_pipeline.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tests/test_pipeline.py video_tagging_assistant/orchestrator.py video_tagging_assistant/cli.py
git commit -m "feat: add excel workflow cli commands"
```

### Task 8: Add final integration coverage for workbook review loop

**Files:**
- Create: `tests/test_excel_integration.py`
- Modify: `tests/test_reporting_integration.py`

- [ ] **Step 1: Write a failing integration test covering generate then sync**

```python
from pathlib import Path

from openpyxl import Workbook, load_workbook

from video_tagging_assistant.orchestrator import run_excel_sync, run_excel_workflow
from video_tagging_assistant.models import CompressedArtifact, GenerationResult


class StubCompressor:
    def __call__(self, task, output_dir, compression_config):
        output_dir.mkdir(parents=True, exist_ok=True)
        proxy = output_dir / "proxy.mp4"
        proxy.write_bytes(b"proxy")
        return CompressedArtifact(task.source_video_path, proxy)


class StubProvider:
    provider_name = "stub"

    def generate(self, context):
        return GenerationResult(
            source_video_path=context.source_video_path,
            case_key="case_A_0001",
            summary_text="自动简介",
            structured_tags={"安装方式": "手持", "运动模式": "行走"},
            scene_description="画面描述",
            provider="stub",
            model="stub-model",
        )


def test_excel_review_flow_generates_then_syncs(tmp_path: Path):
    workbook_path = tmp_path / "records.xlsx"
    wb = Workbook()
    source = wb.active
    source.title = "创建记录"
    source.append(["序号", "文件夹名", "备注", "Raw存放路径", "VS_Nomal", "VS_Night", "安装方式", "运动模式", "标签审核状态", "最终简介", "最终标签"])
    video_path = tmp_path / "case_A_0001.mp4"
    video_path.write_bytes(b"video")
    source.append([1, "case_A_0001", "场景备注", "raw/path", str(video_path), "night.mp4", "手持", "行走", "待生成", "", ""])
    wb.save(workbook_path)

    config = {
        "output_dir": str(tmp_path / "output"),
        "compression": {"width": 960, "video_bitrate": "700k", "audio_bitrate": "96k", "fps": 12},
        "prompt_template": {"system": "describe"},
        "excel_workflow": {
            "enabled": True,
            "workbook_path": str(workbook_path),
            "source_sheet": "创建记录",
            "review_sheet": "标签审核",
            "case_key_column": "文件夹名",
            "status_column": "标签审核状态",
        },
    }

    run_excel_workflow(config, compressor=StubCompressor(), provider=StubProvider())

    wb = load_workbook(workbook_path)
    review = wb["标签审核"]
    review["H2"] = "审核通过"
    wb.save(workbook_path)

    run_excel_sync(config)

    source_sheet = load_workbook(workbook_path)["创建记录"]
    assert source_sheet["I2"].value == "审核通过"
    assert source_sheet["J2"].value == "自动简介"
    assert "安装方式=手持" in source_sheet["K2"].value
```

- [ ] **Step 2: Run the integration test to verify the whole loop is not complete yet**

Run: `pytest tests/test_excel_integration.py::test_excel_review_flow_generates_then_syncs -v`
Expected: FAIL until all workbook pieces are wired together.

- [ ] **Step 3: Adjust any minimal integration gaps without expanding scope**

```python
# Keep this step constrained to wiring fixes only:
# - header-name mismatches
# - workbook save timing
# - case-key propagation into GenerationResult
# - stable structured-tag serialization
```

- [ ] **Step 4: Run the focused workbook integration suite**

Run: `pytest tests/test_excel_models.py tests/test_excel_workbook.py tests/test_excel_pipeline.py tests/test_excel_sync.py tests/test_excel_integration.py -v`
Expected: PASS.

- [ ] **Step 5: Run the broader regression suite for touched areas**

Run: `pytest tests/test_config.py tests/test_context_builder.py tests/test_provider.py tests/test_pipeline.py tests/test_review_exporter.py tests/test_review_exporter_structured.py tests/test_reporting_integration.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tests/test_excel_integration.py tests/test_reporting_integration.py video_tagging_assistant/*.py
git commit -m "feat: complete excel review sync workflow"
```

## Self-Review

- Spec coverage: this plan covers reading confirmed cases from `创建记录`, isolating AI draft output in `标签审核`, manual approval before sync-back, and workbook-driven status flow. Physical archive move logic is intentionally deferred; current plan prepares status/path fields only.
- Placeholder scan: no TODO/TBD placeholders remain in implementation steps. The single “wiring fixes only” note is intentionally scoped to small integration mismatches, not unspecified feature work.
- Type consistency: `case_key` is the only workbook identity field; `ReviewSheetRow.final_summary` and `final_tags` are the only final-value selectors; CLI modes are `batch`, `excel-generate`, and `excel-sync` across all tasks.
