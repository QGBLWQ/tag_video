from pathlib import Path

from openpyxl import Workbook, load_workbook

from video_tagging_assistant.excel_workbook import (
    build_case_manifests,
    ensure_pipeline_columns,
    load_approved_review_rows,
    load_pipeline_cases,
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
