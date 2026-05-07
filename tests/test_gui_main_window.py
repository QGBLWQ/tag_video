from pathlib import Path
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
    "运镜方式": ["推拉"],
    "光源": ["正常"],
    "画面特征": ["边缘特征 强弱"],
    "影像表达": ["风景录像"],
}


def _make_window():
    from video_tagging_assistant.gui.main_window import MainWindow

    with patch("video_tagging_assistant.gui.main_window.ExecutionWorker") as mock_worker_cls:
        mock_worker = MagicMock()
        mock_worker.status_changed = MagicMock()
        mock_worker.status_changed.connect = MagicMock()
        mock_worker.upload_progress = MagicMock()
        mock_worker.upload_progress.connect = MagicMock()
        mock_worker_cls.return_value = mock_worker
        window = MainWindow(config=_CONFIG, tag_options=_TAG_OPTIONS)
        window._worker = mock_worker
    return window


def _make_manifest(case_id: str):
    from video_tagging_assistant.pipeline_models import CaseManifest

    return CaseManifest(
        case_id=case_id,
        row_index=2,
        created_date="20260422",
        mode="OV50H40_Action5Pro_DCG HDR",
        raw_path=Path("/mnt/117"),
        vs_normal_path=Path(f"{case_id}_normal.MP4"),
        vs_night_path=Path(f"{case_id}_night.MP4"),
        local_case_root=Path("/tmp/local/OV50H40_Action5Pro_DCG HDR/20260422") / case_id,
        server_case_dir=Path("/tmp/server/OV50H40_Action5Pro_DCG HDR/20260422") / case_id,
        remark="",
    )


def _make_tag_result(device_info=None):
    from video_tagging_assistant.excel_workbook import TagResult

    return TagResult(
        install_method="手持",
        motion_mode="行走",
        camera_move="推拉",
        light_source="正常",
        image_feature="边缘特征 强弱",
        image_expression="风景录像",
        scene_description="case reviewed",
        device_info=device_info or {},
        review_status="审核通过",
    )


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
    window = _make_window()
    manifest = _make_manifest("case_A_0078")
    results = [{"manifest": manifest, "ai_result": {"安装方式": "手持"}, "missing": False}]

    window._review_tab.load_cases = MagicMock()
    window._on_tagging_complete(results)

    assert window._tabs.isTabEnabled(1)
    window._review_tab.load_cases.assert_called_once()


def test_auto_mode_tagging_completion_locks_selected_device_and_enqueues_all_cases(tmp_path):
    window = _make_window()
    workbook_path = tmp_path / "cases.xlsx"
    workbook_path.write_text("", encoding="utf-8")
    manifest_one = _make_manifest("case_A_0001")
    manifest_two = _make_manifest("case_A_0002")
    locked_device = {
        "设备编号": "DUT-01",
        "模组型号": "IMX989",
        "采集模式": "HDR",
    }
    dut_devices = [
        locked_device,
        {
            "设备编号": "DUT-02",
            "模组型号": "OV50H40",
            "采集模式": "NORMAL",
        },
    ]
    results = [
        {"manifest": manifest_one, "ai_result": {"安装方式": "手持"}, "missing": False},
        {"manifest": manifest_two, "ai_result": {"安装方式": "穿戴"}, "missing": False},
    ]

    window._tagging_tab._xlsx_writeback_path = workbook_path
    window._tagging_tab.auto_execution_enabled = MagicMock(return_value=True)
    window._tagging_tab.selected_device_info = MagicMock(return_value=locked_device)
    window._review_tab.load_cases = MagicMock()
    window._execution_tab.add_case = MagicMock()

    with patch("video_tagging_assistant.gui.main_window.load_dut_info", return_value=dut_devices):
        window._on_tagging_complete(results)

    expected_mode = "IMX989_HDR"
    expected_local_root = Path("/tmp/local") / expected_mode
    expected_server_root = Path("/tmp/server") / expected_mode

    assert window._auto_execution_enabled is True
    assert window._locked_device_info == locked_device
    assert window._tabs.isTabEnabled(1)
    assert window._tabs.isTabEnabled(2)
    assert window._tabs.currentIndex() == 1
    for manifest in (manifest_one, manifest_two):
        assert manifest.mode == expected_mode
        assert manifest.local_case_root == expected_local_root / manifest.created_date / manifest.case_id
        assert manifest.server_case_dir == expected_server_root / manifest.created_date / manifest.case_id

    window._review_tab.load_cases.assert_called_once_with(
        [manifest_one, manifest_two],
        {
            "case_A_0001": {"安装方式": "手持"},
            "case_A_0002": {"安装方式": "穿戴"},
        },
        dut_devices=dut_devices,
        auto_mode=True,
        locked_device=locked_device,
    )
    assert window._execution_tab.add_case.call_count == 2
    window._execution_tab.add_case.assert_any_call(manifest_one)
    window._execution_tab.add_case.assert_any_call(manifest_two)


def test_auto_mode_approval_writes_outputs_and_advances_without_reenqueueing(tmp_path):
    window = _make_window()
    manifest = _make_manifest("case_A_0001")
    manifest.mode = "IMX989_HDR"
    manifest.local_case_root = Path("/tmp/local/IMX989_HDR/20260422/case_A_0001")
    manifest.server_case_dir = Path("/tmp/server/IMX989_HDR/20260422/case_A_0001")
    tag_result = _make_tag_result(
        {
            "设备编号": "DUT-01",
            "模组型号": "IMX989",
            "采集模式": "HDR",
        }
    )
    workbook_path = tmp_path / "cases.xlsx"
    workbook_path.write_text("", encoding="utf-8")

    window._auto_execution_enabled = True
    window._workbook_path = workbook_path
    window._review_tab.advance_after_approval = MagicMock()
    window._execution_tab.add_case = MagicMock()

    with patch("video_tagging_assistant.gui.main_window.upsert_create_record_row") as mock_upsert, patch(
        "video_tagging_assistant.gui.main_window.write_case_txt"
    ) as mock_write_txt:
        window._on_case_approved(manifest, tag_result)

    mock_upsert.assert_called_once_with(workbook_path, manifest, tag_result)
    mock_write_txt.assert_called_once_with(manifest, tag_result)
    window._review_tab.advance_after_approval.assert_called_once_with()
    window._execution_tab.add_case.assert_not_called()


def test_writeback_failure_keeps_current_case_in_place_and_does_not_advance(tmp_path):
    window = _make_window()
    manifest = _make_manifest("case_A_0001")
    tag_result = _make_tag_result()
    workbook_path = tmp_path / "cases.xlsx"
    workbook_path.write_text("", encoding="utf-8")

    window._workbook_path = workbook_path
    window._review_tab.advance_after_approval = MagicMock()
    window._execution_tab.add_case = MagicMock()

    with patch("video_tagging_assistant.gui.main_window.upsert_create_record_row") as mock_upsert, patch(
        "video_tagging_assistant.gui.main_window.write_case_txt",
        side_effect=RuntimeError("txt failed"),
    ) as mock_write_txt:
        window._on_case_approved(manifest, tag_result)

    mock_upsert.assert_called_once_with(workbook_path, manifest, tag_result)
    mock_write_txt.assert_called_once_with(manifest, tag_result)
    window._review_tab.advance_after_approval.assert_not_called()
    window._execution_tab.add_case.assert_not_called()
    assert "txt" in window.statusBar().currentMessage()


def test_manual_mode_approval_applies_device_info_and_enqueues_after_successful_writeback(tmp_path):
    window = _make_window()
    manifest = _make_manifest("case_A_0001")
    device_info = {
        "设备编号": "DUT-09",
        "模组型号": "IMX766",
        "采集模式": "NORMAL",
    }
    tag_result = _make_tag_result(device_info)
    workbook_path = tmp_path / "cases.xlsx"
    workbook_path.write_text("", encoding="utf-8")

    window._auto_execution_enabled = False
    window._workbook_path = workbook_path
    window._review_tab.advance_after_approval = MagicMock()
    window._execution_tab.add_case = MagicMock()

    with patch("video_tagging_assistant.gui.main_window.upsert_create_record_row") as mock_upsert, patch(
        "video_tagging_assistant.gui.main_window.write_case_txt"
    ) as mock_write_txt:
        window._on_case_approved(manifest, tag_result)

    expected_mode = "IMX766_NORMAL"
    assert manifest.mode == expected_mode
    assert manifest.local_case_root == Path("/tmp/local") / expected_mode / manifest.created_date / manifest.case_id
    assert manifest.server_case_dir == Path("/tmp/server") / expected_mode / manifest.created_date / manifest.case_id
    mock_upsert.assert_called_once_with(workbook_path, manifest, tag_result)
    mock_write_txt.assert_called_once_with(manifest, tag_result)
    window._review_tab.advance_after_approval.assert_called_once_with()
    assert window._tabs.isTabEnabled(2)
    window._execution_tab.add_case.assert_called_once_with(manifest)
