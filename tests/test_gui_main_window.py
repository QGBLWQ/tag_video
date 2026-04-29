from unittest.mock import MagicMock, patch

from PyQt5.QtWidgets import QApplication

_APP = QApplication.instance() or QApplication([])

_CONFIG = {
    "workbook_path": "",
    "mode": "OV50H40_Action5Pro_DCG HDR",
    "adb_exe": "adb.exe",
    "dut_root": "/mnt",
    "local_case_root": "/tmp/local",
    "server_upload_root": "/tmp/server",
    "intermediate_dir": "/tmp/intermediate",
}

_TAG_OPTIONS = {
    "安装方式": ["手持", "穿戴", "载具"],
    "运动模式": ["行走", "跑步"],
    "运镜方式": ["推U摇"],
    "光源": ["正常"],
    "画面特征": ["边缘特征 强弱"],
    "影像表达": ["风景录像"],
}


def _make_window():
    from video_tagging_assistant.gui.main_window import MainWindow
    with patch("video_tagging_assistant.gui.main_window.ExecutionWorker") as MockWorker:
        mock_worker = MagicMock()
        mock_worker.status_changed = MagicMock()
        mock_worker.status_changed.connect = MagicMock()
        MockWorker.return_value = mock_worker
        window = MainWindow(config=_CONFIG, tag_options=_TAG_OPTIONS)
        window._worker = mock_worker
    return window


def test_main_window_title():
    window = _make_window()
    assert window.windowTitle() == "Video Tagging Pipeline"


def test_main_window_has_three_tabs():
    window = _make_window()
    assert window._tabs.count() == 3
    assert window._tabs.tabText(0) == "打标"
    assert window._tabs.tabText(1) == "审核"
    assert window._tabs.tabText(2) == "执行队列"


def test_review_and_execution_tabs_initially_disabled():
    window = _make_window()
    assert not window._tabs.isTabEnabled(1)
    assert not window._tabs.isTabEnabled(2)


def test_on_tagging_complete_enables_review_tab_and_loads_cases():
    from unittest.mock import MagicMock, patch
    from pathlib import Path
    from video_tagging_assistant.pipeline_models import CaseManifest

    window = _make_window()
    manifest = CaseManifest(
        case_id="case_A_0078",
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
    results = [{"manifest": manifest, "ai_result": {"安装方式": "手持"}, "missing": False}]

    window._review_tab.load_cases = MagicMock()
    window._on_tagging_complete(results)

    assert window._tabs.isTabEnabled(1)
    window._review_tab.load_cases.assert_called_once()
