from video_tagging_assistant.excel_models import ConfirmedCaseRow, ReviewSheetRow


def test_review_sheet_row_prefers_manual_values():
    row = ReviewSheetRow(
        case_key="case_A_0001",
        workbook_row_index=2,
        raw_path="raw/path",
        video_path="videos/case_A_0001/clip01.mp4",
        auto_summary="自动简介",
        auto_tags="安装方式=手持;运动模式=行走",
        manual_summary="人工简介",
        manual_tags="安装方式=穿戴;运动模式=跑步",
        review_decision="修改后通过",
    )

    assert row.final_summary == "人工简介"
    assert row.final_tags == "安装方式=穿戴;运动模式=跑步"


def test_confirmed_case_row_exposes_case_key_and_attributes():
    row = ConfirmedCaseRow(
        case_key="case_A_0001",
        workbook_row_index=2,
        raw_path="raw/path",
        vs_normal_path="videos/case_A_0001/clip01.mp4",
        vs_night_path="videos/case_A_0001/night.mp4",
        note="场景备注",
        attributes={"安装方式": "手持", "运动模式": "行走"},
    )

    assert row.case_key == "case_A_0001"
    assert row.attributes["安装方式"] == "手持"
