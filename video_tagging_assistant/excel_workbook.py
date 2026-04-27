from pathlib import Path
from typing import Dict, List

from openpyxl import load_workbook

from video_tagging_assistant.excel_models import ConfirmedCaseRow, ReviewSheetRow

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


def _header_map(sheet) -> Dict[str, int]:
    return {str(cell.value).strip(): idx + 1 for idx, cell in enumerate(sheet[1]) if cell.value is not None}


def load_confirmed_cases(
    workbook_path: Path,
    source_sheet: str,
    case_key_column: str,
    status_column: str,
) -> List[ConfirmedCaseRow]:
    workbook = load_workbook(workbook_path)
    sheet = workbook[source_sheet]
    headers = _header_map(sheet)

    rows: List[ConfirmedCaseRow] = []
    for row_index in range(2, sheet.max_row + 1):
        case_value = sheet.cell(row_index, headers[case_key_column]).value
        if not case_value:
            continue
        rows.append(
            ConfirmedCaseRow(
                case_key=str(case_value).strip(),
                workbook_row_index=row_index,
                raw_path=str(sheet.cell(row_index, headers["Raw存放路径"]).value or "").strip(),
                vs_normal_path=str(sheet.cell(row_index, headers["VS_Nomal"]).value or "").strip(),
                vs_night_path=str(sheet.cell(row_index, headers["VS_Night"]).value or "").strip(),
                note=str(sheet.cell(row_index, headers["备注"]).value or "").strip(),
                attributes={
                    "安装方式": str(sheet.cell(row_index, headers["安装方式"]).value or "").strip(),
                    "运动模式": str(sheet.cell(row_index, headers["运动模式"]).value or "").strip(),
                },
            )
        )
    return rows


def upsert_review_rows(workbook_path: Path, review_sheet: str, rows: List[ReviewSheetRow]) -> None:
    workbook = load_workbook(workbook_path)
    if review_sheet in workbook.sheetnames:
        sheet = workbook[review_sheet]
    else:
        sheet = workbook.create_sheet(review_sheet)
        sheet.append(REVIEW_HEADERS)

    headers = _header_map(sheet)
    existing = {}
    for row_index in range(2, sheet.max_row + 1):
        case_key = sheet.cell(row_index, headers["文件夹名"]).value
        if case_key:
            existing[str(case_key).strip()] = row_index

    for row in rows:
        row_index = existing.get(row.case_key, sheet.max_row + 1)
        values = {
            "文件夹名": row.case_key,
            "创建记录行号": row.workbook_row_index,
            "Raw存放路径": row.raw_path,
            "视频路径": row.video_path,
            "自动简介": row.auto_summary,
            "自动标签": row.auto_tags,
            "自动画面描述": row.auto_scene_description,
            "审核结论": row.review_decision,
            "人工修订简介": row.manual_summary,
            "人工修订标签": row.manual_tags,
            "审核备注": row.review_note,
            "审核人": row.reviewer,
            "审核时间": row.reviewed_at,
            "同步状态": row.sync_status,
            "归档状态": row.archive_status,
            "归档目标路径": row.archive_target_path,
        }
        for header, value in values.items():
            sheet.cell(row_index, headers[header]).value = value

    workbook.save(workbook_path)


def sync_approved_rows(workbook_path: Path, source_sheet: str, review_sheet: str) -> None:
    workbook = load_workbook(workbook_path)
    source = workbook[source_sheet]
    review = workbook[review_sheet]
    source_headers = _header_map(source)
    review_headers = _header_map(review)

    for row_index in range(2, review.max_row + 1):
        decision = str(review.cell(row_index, review_headers["审核结论"]).value or "").strip()
        if decision not in {"审核通过", "修改后通过"}:
            continue
        source_row = int(review.cell(row_index, review_headers["创建记录行号"]).value)
        auto_summary = str(review.cell(row_index, review_headers["自动简介"]).value or "").strip()
        auto_tags = str(review.cell(row_index, review_headers["自动标签"]).value or "").strip()
        manual_summary = str(review.cell(row_index, review_headers["人工修订简介"]).value or "").strip()
        manual_tags = str(review.cell(row_index, review_headers["人工修订标签"]).value or "").strip()

        source.cell(source_row, source_headers["标签审核状态"]).value = decision
        source.cell(source_row, source_headers["最终简介"]).value = manual_summary or auto_summary
        source.cell(source_row, source_headers["最终标签"]).value = manual_tags or auto_tags

    workbook.save(workbook_path)
