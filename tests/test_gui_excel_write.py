import pytest
from pathlib import Path
import openpyxl
from video_tagging_assistant.excel_workbook import TagResult, write_tag_result_to_create_record


def _build_workbook(path: Path) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "创建记录"
    ws.append([
        "序号", "文件夹名", "备注", "创建日期", "数量",
        "安装方式", "运动模式", "运镜元素", "光源划分",
        "画面特征", "影像表达", "Raw存放路径", "VS_Nomal", "VS_Night",
        "标签审核状态",
    ])
    ws.append([1, "case_A_0001", "", "20260422", 1,
               "", "", "", "", "", "", "", "", "", ""])
    wb.save(path)


def test_write_tag_result_updates_create_record_row(tmp_path: Path):
    wb_path = tmp_path / "test.xlsx"
    _build_workbook(wb_path)

    result = TagResult(
        install_method="手持",
        motion_mode="行走",
        camera_move="推U摇",
        light_source="正常",
        image_feature="边缘特征 强弱",
        image_expression="建筑空间",
        review_status="审核通过",
    )
    write_tag_result_to_create_record(wb_path, row_index=2, tag_result=result)

    wb = openpyxl.load_workbook(wb_path)
    ws = wb["创建记录"]
    # cell.column is 1-based; row tuple is 0-based, so row[col-1]
    headers = {cell.value: cell.column for cell in ws[1]}
    row = ws[2]
    assert row[headers["安装方式"] - 1].value == "手持"
    assert row[headers["运动模式"] - 1].value == "行走"
    assert row[headers["运镜元素"] - 1].value == "推U摇"
    assert row[headers["光源划分"] - 1].value == "正常"
    assert row[headers["画面特征"] - 1].value == "边缘特征 强弱"
    assert row[headers["影像表达"] - 1].value == "建筑空间"
    assert row[headers["标签审核状态"] - 1].value == "审核通过"


def test_write_tag_result_skips_missing_column(tmp_path: Path):
    """Workbook without 运镜元素 column — function should not raise."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "创建记录"
    ws.append(["序号", "文件夹名", "安装方式", "运动模式", "标签审核状态"])
    ws.append([1, "case_A_0001", "", "", ""])
    path = tmp_path / "minimal.xlsx"
    wb.save(path)

    result = TagResult(
        install_method="手持",
        motion_mode="行走",
        camera_move="推U摇",
        light_source="正常",
        image_feature="边缘",
        image_expression="风景录像",
        review_status="审核通过",
    )
    write_tag_result_to_create_record(path, row_index=2, tag_result=result)  # must not raise

    wb2 = openpyxl.load_workbook(path)
    ws2 = wb2["创建记录"]
    headers = {cell.value: cell.column for cell in ws2[1]}
    assert ws2.cell(2, headers["安装方式"]).value == "手持"


def test_write_tag_result_rejects_xlsm(tmp_path: Path):
    xlsm_path = tmp_path / "test.xlsm"
    xlsm_path.write_bytes(b"fake xlsm")
    result = TagResult(
        install_method="手持", motion_mode="行走", camera_move="推U摇",
        light_source="正常", image_feature="边缘", image_expression="风景录像",
        review_status="审核通过",
    )
    with pytest.raises(ValueError, match="xlsm"):
        write_tag_result_to_create_record(xlsm_path, row_index=2, tag_result=result)
