from pathlib import Path
from unittest.mock import MagicMock

from PyQt5.QtWidgets import QApplication, QAbstractButton

_APP = QApplication.instance() or QApplication([])

_TAG_OPTIONS = {
    "安装方式": ["手持", "穿戴", "载具"],
    "运动模式": ["行走", "跑步"],
    "运镜方式": ["推U摇", "拉U摇"],
    "光源": ["低", "正常"],
    "画面特征": ["边缘特征 强弱", "反射与透视"],
    "影像表达": ["风景录像", "建筑空间"],
}

_CONFIG = {
    "dji_nomal_dir": "/tmp/dji",
    "potplayer_exe": "/not/exist/potplayer.exe",
}


def _make_manifest(case_id: str = "case_A_0078"):
    from video_tagging_assistant.pipeline_models import CaseManifest
    return CaseManifest(
        case_id=case_id,
        row_index=2,
        created_date="20260422",
        mode="OV50H40_Action5Pro_DCG HDR",
        raw_path=Path("/mnt/117"),
        vs_normal_path=Path("DJI_0001.MP4"),
        vs_night_path=Path("DJI_0021.MP4"),
        local_case_root=Path("/tmp/cases"),
        server_case_dir=Path("/tmp/server/case"),
        remark="",
    )


def test_review_tab_instantiates():
    from video_tagging_assistant.gui.review_tab import ReviewTab
    tab = ReviewTab(_CONFIG, _TAG_OPTIONS)
    assert tab is not None


def test_review_tab_has_case_approved_signal():
    from video_tagging_assistant.gui.review_tab import ReviewTab
    tab = ReviewTab(_CONFIG, _TAG_OPTIONS)
    assert hasattr(tab, "case_approved")


def test_review_tab_load_cases_shows_first_case():
    from video_tagging_assistant.gui.review_tab import ReviewTab
    tab = ReviewTab(_CONFIG, _TAG_OPTIONS)
    manifests = [_make_manifest("case_A_0001"), _make_manifest("case_A_0002")]
    tagging_results = {
        "case_A_0001": {
            "安装方式": "手持",
            "运动模式": "行走",
            "运镜方式": "推U摇",
            "光源": "正常",
            "画面特征": ["边缘特征 强弱"],
            "影像表达": ["风景录像"],
        },
        "case_A_0002": {
            "安装方式": "穿戴",
            "运动模式": "跑步",
            "运镜方式": "拉U摇",
            "光源": "低",
            "画面特征": ["反射与透视"],
            "影像表达": ["建筑空间"],
        },
    }
    tab.load_cases(manifests, tagging_results)
    # 进度标签应显示 1/2
    assert "1" in tab._progress_label.text()
    assert "2" in tab._progress_label.text()
    # case_id 标签应显示第一个 case
    assert "case_A_0001" in tab._case_label.text()


def test_review_tab_approve_without_all_fields_shows_error():
    """未全选字段时点通过，应弹提示而不 emit case_approved。"""
    from unittest.mock import patch
    from video_tagging_assistant.gui.review_tab import ReviewTab

    tab = ReviewTab(_CONFIG, _TAG_OPTIONS)
    manifests = [_make_manifest("case_A_0001")]
    tab.load_cases(manifests, {"case_A_0001": {
        "安装方式": "手持", "运动模式": "行走",
        "运镜方式": "推U摇", "光源": "正常",
        "画面特征": ["边缘特征 强弱"], "影像表达": ["风景录像"],
    }})

    approved_signals = []
    tab.case_approved.connect(lambda m, t: approved_signals.append((m, t)))

    with patch("PyQt5.QtWidgets.QMessageBox.warning") as mock_warn:
        tab._pass_btn.click()

    # 没有全选，应弹提示，不应 emit
    mock_warn.assert_called_once()
    assert approved_signals == []


def test_review_tab_approve_with_all_fields_emits_case_approved():
    from video_tagging_assistant.gui.review_tab import ReviewTab
    from video_tagging_assistant.excel_workbook import TagResult

    tab = ReviewTab(_CONFIG, _TAG_OPTIONS)
    manifests = [_make_manifest("case_A_0001")]
    tab.load_cases(manifests, {"case_A_0001": {
        "安装方式": "手持", "运动模式": "行走",
        "运镜方式": "推U摇", "光源": "正常",
        "画面特征": ["边缘特征 强弱"], "影像表达": ["风景录像"],
    }})

    approved_signals = []
    tab.case_approved.connect(lambda m, t: approved_signals.append((m, t)))

    # 选中所有必选字段的第一个选项
    for group in tab._groups.values():
        buttons = group.buttons()
        if buttons:
            buttons[0].setChecked(True)

    tab._pass_btn.click()

    assert len(approved_signals) == 1
    manifest, tag_result = approved_signals[0]
    assert manifest.case_id == "case_A_0001"
    assert isinstance(tag_result, TagResult)
    assert tag_result.review_status == "审核通过"
