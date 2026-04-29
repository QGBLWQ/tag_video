# 获取列表 Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the GUI pipeline read `获取列表` as an index sheet, bridge each row back to a unique `创建记录` row using `RK_raw + normal/night filenames`, and then continue building standard `CaseManifest` objects without re-enabling `.xlsm` writes.

**Architecture:** Keep `.xlsm` safety guardrails in place and add a separate read-only parsing path for `获取列表` inside `video_tagging_assistant/excel_workbook.py`. The new bridge should parse row 1/row 2 layout, build lightweight index entries, match them back to `创建记录` rows, and then reuse the existing `CaseManifest` construction path rather than inventing a second manifest model.

**Tech Stack:** Python 3.8, pathlib, openpyxl read-only workbook access, dataclasses, pytest, existing GUI/workbook helpers

---

## File Structure

### Existing files to modify

- `video_tagging_assistant/excel_workbook.py`
  - Add read-only `获取列表` parsing and bridge helpers, while preserving `.xlsm` write protection.
- `video_tagging_assistant/gui/app.py`
  - Replace the temporary `获取列表` rejection in `scan_cases()` with a bridge-aware manifest loading path.
- `tests/test_excel_workbook_pipeline.py`
  - Add focused tests for parsing `获取列表`, successful bridging, missing matches, duplicate matches, and `.xlsm` safety staying intact.
- `tests/test_gui_smoke.py`
  - Replace the temporary “reject 获取列表” smoke expectation with a successful bridge flow test.

### Existing files to read while implementing

- `video_tagging_assistant/pipeline_models.py`
  - Confirm the `ExcelCaseRecord` and `CaseManifest` fields the bridge must populate.
- `video_tagging_assistant/case_task_factory.py`
  - Reuse the existing raw-path suffix assumption for `RK_raw` matching.
- `docs/superpowers/specs/2026-04-29-get-list-bridge-design.md`
  - Source of truth for bridge semantics, matching rules, and non-goals.

### New files to create

- None required.

---

### Task 1: Add failing `获取列表` parsing and bridge tests

**Files:**
- Modify: `tests/test_excel_workbook_pipeline.py`

- [ ] **Step 1: Add fixtures for `创建记录` + `获取列表` bridge workbooks**

```python
GET_LIST_HEADERS = ["处理状态", "RK_raw", "Action5Pro_Nomal", "Action5Pro_Night"]


def build_bridge_workbook(path: Path):
    wb = Workbook()
    create_record = wb.active
    create_record.title = "创建记录"
    create_record.append(PIPELINE_HEADERS)
    create_record.append([
        1,
        "case_A_0001",
        "场景备注",
        "20260422",
        r"E:\DV\case_A_0001\case_A_0001_RK_raw_117",
        r"E:\DV\case_A_0001\DJI_20260422151829_0001_D.MP4",
        r"E:\DV\case_A_0001\DJI_20260422151916_0021_D.MP4",
        "手持",
        "行走",
    ])
    get_list = wb.create_sheet("获取列表")
    get_list.append(["日期", "20260422", "", ""])
    get_list.append(GET_LIST_HEADERS)
    get_list.append(["R", "117", "DJI_20260422151829_0001_D.MP4", "DJI_20260422151916_0021_D.MP4"])
    review = wb.create_sheet("审核结果")
    review.append(REVIEW_HEADERS)
    wb.save(path)
```

- [ ] **Step 2: Write the failing successful-bridge test**

```python
def test_build_case_manifests_from_get_list_bridges_back_to_create_record(tmp_path: Path):
    workbook_path = tmp_path / "records.xlsx"
    build_bridge_workbook(workbook_path)
    ensure_pipeline_columns(workbook_path, source_sheet="创建记录")
    update_pipeline_status(
        workbook_path,
        source_sheet="创建记录",
        case_id="case_A_0001",
        status_updates={"pipeline_status": "queued"},
    )

    manifests = build_case_manifests(
        workbook_path,
        source_sheet="获取列表",
        allowed_statuses={"queued"},
        local_root=tmp_path / "local",
        server_root=tmp_path / "server",
        mode="OV50H40_Action5Pro_DCG HDR",
    )

    assert len(manifests) == 1
    assert manifests[0].case_id == "case_A_0001"
    assert manifests[0].created_date == "20260422"
    assert manifests[0].vs_normal_path.name == "DJI_20260422151829_0001_D.MP4"
```

- [ ] **Step 3: Write the failing “no match” test**

```python
def test_build_case_manifests_from_get_list_raises_when_create_record_match_missing(tmp_path: Path):
    workbook_path = tmp_path / "records.xlsx"
    build_bridge_workbook(workbook_path)

    wb = load_workbook(workbook_path)
    ws = wb["获取列表"]
    ws.cell(3, 2).value = "999"
    wb.save(workbook_path)

    with pytest.raises(ValueError) as exc:
        build_case_manifests(
            workbook_path,
            source_sheet="获取列表",
            allowed_statuses={"queued", ""},
            local_root=tmp_path / "local",
            server_root=tmp_path / "server",
            mode="OV50H40_Action5Pro_DCG HDR",
        )

    assert "RK_raw=999" in str(exc.value)
    assert "No matching create-record row found" in str(exc.value)
```

- [ ] **Step 4: Write the failing duplicate-match test**

```python
def test_build_case_manifests_from_get_list_raises_when_create_record_match_is_ambiguous(tmp_path: Path):
    workbook_path = tmp_path / "records.xlsx"
    build_bridge_workbook(workbook_path)

    wb = load_workbook(workbook_path)
    ws = wb["创建记录"]
    ws.append([
        2,
        "case_A_0002",
        "重复候选",
        "20260422",
        r"E:\DV\case_A_0002\case_A_0002_RK_raw_117",
        r"E:\DV\case_A_0002\DJI_20260422151829_0001_D.MP4",
        r"E:\DV\case_A_0002\DJI_20260422151916_0021_D.MP4",
        "手持",
        "行走",
    ])
    wb.save(workbook_path)
    ensure_pipeline_columns(workbook_path, source_sheet="创建记录")

    with pytest.raises(ValueError) as exc:
        build_case_manifests(
            workbook_path,
            source_sheet="获取列表",
            allowed_statuses={"queued", ""},
            local_root=tmp_path / "local",
            server_root=tmp_path / "server",
            mode="OV50H40_Action5Pro_DCG HDR",
        )

    assert "Matched 2 create-record rows" in str(exc.value)
    assert "RK_raw=117" in str(exc.value)
```

- [ ] **Step 5: Run tests to verify they fail**

Run: `pytest tests/test_excel_workbook_pipeline.py::test_build_case_manifests_from_get_list_bridges_back_to_create_record tests/test_excel_workbook_pipeline.py::test_build_case_manifests_from_get_list_raises_when_create_record_match_missing tests/test_excel_workbook_pipeline.py::test_build_case_manifests_from_get_list_raises_when_create_record_match_is_ambiguous -v`
Expected: FAIL because `build_case_manifests()` still assumes `获取列表` is a create-record-style sheet.

- [ ] **Step 6: Commit**

```bash
git add tests/test_excel_workbook_pipeline.py
git commit -m "test: cover 获取列表 bridge behavior"
```

### Task 2: Implement read-only `获取列表` parsing and bridge helpers

**Files:**
- Modify: `video_tagging_assistant/excel_workbook.py`
- Modify: `tests/test_excel_workbook_pipeline.py`

- [ ] **Step 1: Add lightweight `获取列表` parsing helpers**

```python
from dataclasses import dataclass

...

GET_LIST_REQUIRED_HEADERS = {"处理状态", "RK_raw", "Action5Pro_Nomal", "Action5Pro_Night"}


@dataclass
class GetListRow:
    created_date: str
    status: str
    rk_raw: str
    vs_normal_name: str
    vs_night_name: str


def _header_map_for_row(sheet, row_index: int) -> Dict[str, int]:
    return {
        str(cell.value).strip(): idx + 1
        for idx, cell in enumerate(sheet[row_index])
        if cell.value is not None
    }


def _load_get_list_rows(workbook_path: Path, source_sheet: str) -> List[GetListRow]:
    workbook = load_workbook(workbook_path, data_only=True)
    sheet = workbook[source_sheet]
    created_date = str(sheet.cell(1, 2).value or "").strip()
    headers = _header_map_for_row(sheet, 2)
    missing = GET_LIST_REQUIRED_HEADERS - set(headers)
    if missing:
        raise ValueError(f"获取列表 缺少必要表头: {sorted(missing)}")

    rows: List[GetListRow] = []
    for row_index in range(3, sheet.max_row + 1):
        rk_raw = str(sheet.cell(row_index, headers["RK_raw"]).value or "").strip()
        normal = str(sheet.cell(row_index, headers["Action5Pro_Nomal"]).value or "").strip()
        night = str(sheet.cell(row_index, headers["Action5Pro_Night"]).value or "").strip()
        if not rk_raw and not normal and not night:
            continue
        rows.append(
            GetListRow(
                created_date=created_date,
                status=str(sheet.cell(row_index, headers["处理状态"]).value or "").strip(),
                rk_raw=rk_raw,
                vs_normal_name=normal,
                vs_night_name=night,
            )
        )
    return rows
```

- [ ] **Step 2: Add create-record matching helpers**

```python
def _extract_raw_suffix(raw_path: str) -> str:
    return Path(raw_path).name.split("_")[-1]


def _match_create_record_rows(create_record_rows: List[ExcelCaseRecord], get_list_row: GetListRow) -> ExcelCaseRecord:
    matches = [
        row
        for row in create_record_rows
        if _extract_raw_suffix(row.raw_path) == get_list_row.rk_raw
        and Path(row.vs_normal_path).name == get_list_row.vs_normal_name
        and Path(row.vs_night_path).name == get_list_row.vs_night_name
    ]
    if not matches:
        raise ValueError(
            "No matching create-record row found for "
            f"RK_raw={get_list_row.rk_raw}, normal={get_list_row.vs_normal_name}, night={get_list_row.vs_night_name}"
        )
    if len(matches) > 1:
        raise ValueError(
            "Matched "
            f"{len(matches)} create-record rows for RK_raw={get_list_row.rk_raw}, "
            f"normal={get_list_row.vs_normal_name}, night={get_list_row.vs_night_name}"
        )
    return matches[0]
```

- [ ] **Step 3: Route `build_case_manifests()` through the bridge when source sheet is `获取列表`**

```python
def build_case_manifests(
    workbook_path: Path,
    source_sheet: str,
    allowed_statuses: Set[str],
    local_root: Path,
    server_root: Path,
    mode: str,
) -> List[CaseManifest]:
    if source_sheet == "获取列表":
        create_record_rows = load_pipeline_cases(
            workbook_path,
            source_sheet="创建记录",
            allowed_statuses=allowed_statuses,
        )
        bridged_rows = [
            _match_create_record_rows(create_record_rows, row)
            for row in _load_get_list_rows(workbook_path, source_sheet)
        ]
        rows = bridged_rows
    else:
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
```

- [ ] **Step 4: Run the focused bridge tests**

Run: `pytest tests/test_excel_workbook_pipeline.py::test_build_case_manifests_from_get_list_bridges_back_to_create_record tests/test_excel_workbook_pipeline.py::test_build_case_manifests_from_get_list_raises_when_create_record_match_missing tests/test_excel_workbook_pipeline.py::test_build_case_manifests_from_get_list_raises_when_create_record_match_is_ambiguous -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add video_tagging_assistant/excel_workbook.py tests/test_excel_workbook_pipeline.py
git commit -m "feat: bridge 获取列表 into create record manifests"
```

### Task 3: Replace the temporary GUI rejection with a successful bridge smoke test

**Files:**
- Modify: `tests/test_gui_smoke.py`
- Modify: `video_tagging_assistant/gui/app.py`

- [ ] **Step 1: Replace the temporary rejection smoke test with a successful bridge test**

```python
def test_launch_case_pipeline_gui_bridges_get_list_into_manifests(monkeypatch, tmp_path: Path):
    workbook_path = tmp_path / "records.xlsx"
    build_bridge_workbook(workbook_path)
    ensure_pipeline_columns(workbook_path, source_sheet="创建记录")
    update_pipeline_status(
        workbook_path,
        source_sheet="创建记录",
        case_id="case_A_0001",
        status_updates={"pipeline_status": "queued"},
    )

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
            "prompt_template": {"system": "describe"},
            "gui_pipeline": {
                "source_sheet": "获取列表",
                "review_sheet": "审核结果",
                "mode": "OV50H40_Action5Pro_DCG HDR",
                "allowed_statuses": ["queued"],
                "local_root": "cases",
                "server_root": "server_cases",
            },
        },
    )

    gui_app.launch_case_pipeline_gui(workbook_path=str(workbook_path))
    manifests = captured["scan_cases"]()

    assert [manifest.case_id for manifest in manifests] == ["case_A_0001"]
```

- [ ] **Step 2: Remove the temporary hard stop in `gui/app.py`**

```python
def scan_cases():
    if workbook is None or not workbook.exists():
        return []
    if source_sheet != "获取列表":
        ensure_pipeline_columns(workbook, source_sheet=source_sheet)
    return build_case_manifests(
        workbook,
        source_sheet=source_sheet,
        allowed_statuses=allowed_statuses,
        local_root=local_root,
        server_root=server_root,
        mode=mode_name,
    )
```

- [ ] **Step 3: Run the focused GUI bridge test**

Run: `pytest tests/test_gui_smoke.py::test_launch_case_pipeline_gui_bridges_get_list_into_manifests -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_gui_smoke.py video_tagging_assistant/gui/app.py
git commit -m "feat: scan GUI queue from 获取列表 bridge"
```

### Task 4: Verify `.xlsm` safety guard remains intact

**Files:**
- Modify: `tests/test_excel_workbook_pipeline.py`

- [ ] **Step 1: Add the explicit `.xlsm` bridge safety test**

```python
def test_build_case_manifests_from_get_list_reads_xlsm_without_writing(tmp_path: Path):
    workbook_path = tmp_path / "records.xlsm"
    build_bridge_workbook(workbook_path)

    manifests = build_case_manifests(
        workbook_path,
        source_sheet="获取列表",
        allowed_statuses={"", "queued", "failed"},
        local_root=tmp_path / "local",
        server_root=tmp_path / "server",
        mode="OV50H40_Action5Pro_DCG HDR",
    )

    assert len(manifests) == 1
    assert manifests[0].case_id == "case_A_0001"
```

- [ ] **Step 2: Run the safety-specific tests**

Run: `pytest tests/test_excel_workbook_pipeline.py::test_ensure_pipeline_columns_rejects_xlsm_workbook tests/test_excel_workbook_pipeline.py::test_build_case_manifests_from_get_list_reads_xlsm_without_writing -v`
Expected: PASS — reads are allowed, writes are blocked.

- [ ] **Step 3: Commit**

```bash
git add tests/test_excel_workbook_pipeline.py
git commit -m "test: verify 获取列表 bridge keeps xlsm read-only"
```

### Task 5: Run broader regression for workbook and GUI behavior

**Files:**
- Test: `tests/test_excel_workbook.py`
- Test: `tests/test_excel_workbook_pipeline.py`
- Test: `tests/test_gui_smoke.py`
- Test: `tests/test_pipeline_controller.py`

- [ ] **Step 1: Run workbook and GUI suites**

Run: `pytest tests/test_excel_workbook.py tests/test_excel_workbook_pipeline.py tests/test_gui_smoke.py -v`
Expected: PASS, including the new `获取列表` bridge behavior and existing `.xlsm` safety guard.

- [ ] **Step 2: Run the related controller regression**

Run: `pytest tests/test_pipeline_controller.py -v`
Expected: PASS with no controller changes required.

- [ ] **Step 3: Run the full suite**

Run: `pytest -v`
Expected: PASS

- [ ] **Step 4: Commit verification-complete state**

```bash
git add video_tagging_assistant/excel_workbook.py video_tagging_assistant/gui/app.py tests/test_excel_workbook_pipeline.py tests/test_gui_smoke.py
git commit -m "test: verify 获取列表 bridge flow"
```

## Self-Review

### Spec coverage

- Read `获取列表` row 1 date and row 2 headers: covered by Task 1 and Task 2.
- Bridge using `RK_raw + normal/night filenames`: covered by Task 2.
- Use `创建记录` as the final truth source for `CaseManifest`: covered by Task 2.
- Error on missing match and duplicate match: covered by Task 1 and Task 2.
- Keep `.xlsm` read-only: covered by Task 4.
- No changes to controller or write-back behavior: preserved by Task 3 and Task 5.

### Placeholder scan

- No `TODO`, `TBD`, or vague instructions remain.
- Every code-changing step includes concrete code.
- Every verification step includes exact pytest commands and expected outcomes.

### Type consistency

- `GetListRow` is the only new intermediate type and stays read-only.
- `build_case_manifests()` remains the single public manifest builder.
- `source_sheet` continues to drive scan mode, but `获取列表` now follows a bridge path instead of the legacy direct-table path.
