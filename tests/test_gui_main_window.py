from pathlib import Path
from unittest.mock import MagicMock, patch

from PyQt5.QtGui import QCloseEvent
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
    "\u5b89\u88c5\u65b9\u5f0f": ["\u624b\u6301", "\u7a7f\u6234", "\u8f66\u8f7d"],
    "\u8fd0\u52a8\u6a21\u5f0f": ["\u884c\u8d70", "\u8dd1\u6b65"],
    "\u8fd0\u955c\u65b9\u5f0f": ["\u5e73\u79fb"],
    "\u5149\u6e90": ["\u6b63\u5e38"],
    "\u753b\u9762\u7279\u5f81": ["\u7eb9\u7406\u4e30\u5bcc"],
    "\u5f71\u50cf\u8868\u8fbe": ["\u8fd0\u52a8\u8ddf\u62cd"],
}

_DEVICE_ID_KEY = "\u8bbe\u5907\u7f16\u53f7"
_DEVICE_MODEL_KEY = "\u6a21\u7ec4\u578b\u53f7"
_DEVICE_MODE_KEY = "\u91c7\u96c6\u6a21\u5f0f"


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


def _make_manifest(case_id: str, row_index: int = 2):
    from video_tagging_assistant.pipeline_models import CaseManifest

    return CaseManifest(
        case_id=case_id,
        row_index=row_index,
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
        install_method="\u624b\u6301",
        motion_mode="\u884c\u8d70",
        camera_move="\u5e73\u79fb",
        light_source="\u6b63\u5e38",
        image_feature="\u7eb9\u7406\u4e30\u5bcc",
        image_expression="\u8fd0\u52a8\u8ddf\u62cd",
        scene_description="case reviewed",
        device_info=device_info or {},
        review_status="\u5ba1\u6838\u901a\u8fc7",
    )


def _make_ai_result():
    return {
        "\u5b89\u88c5\u65b9\u5f0f": "\u624b\u6301",
        "\u8fd0\u52a8\u6a21\u5f0f": "\u884c\u8d70",
        "\u8fd0\u955c\u65b9\u5f0f": "\u5e73\u79fb",
        "\u5149\u6e90": "\u6b63\u5e38",
        "\u753b\u9762\u7279\u5f81": ["\u7eb9\u7406\u4e30\u5bcc"],
        "\u5f71\u50cf\u8868\u8fbe": ["\u8fd0\u52a8\u8ddf\u62cd"],
        "\u753b\u9762\u63cf\u8ff0": "case reviewed",
    }


def _select_first_option_per_group(review_tab) -> None:
    for group in review_tab._groups.values():
        buttons = group.buttons()
        if buttons:
            buttons[0].setChecked(True)


def _load_batch(window, workbook_path: Path, manifests: list) -> None:
    fake_state = MagicMock()
    window._alignment_tab.load_batch = MagicMock()
    with patch("video_tagging_assistant.gui.main_window.load_rk_raw_values", return_value={}), patch(
        "video_tagging_assistant.gui.main_window.scan_rk_candidates",
        return_value=(Path("/tmp/rk"), [], []),
    ), patch(
        "video_tagging_assistant.gui.main_window.build_alignment_batch_state",
        return_value=fake_state,
    ):
        window._on_batch_loaded(
            {
                "manifests": manifests,
                "source_workbook": workbook_path,
                "writeback_workbook": workbook_path,
            }
        )


def _enter_review(
    window,
    workbook_path: Path,
    results: list,
    auto_mode: bool = False,
    selected_device=None,
    dut_devices=None,
) -> None:
    manifests = [result["manifest"] for result in results]
    _load_batch(window, workbook_path, manifests)
    window._tagging_tab._xlsx_writeback_path = workbook_path
    window._tagging_tab.auto_execution_enabled = MagicMock(return_value=auto_mode)
    window._tagging_tab.selected_device_info = MagicMock(return_value=selected_device or {})
    with patch(
        "video_tagging_assistant.gui.main_window.load_dut_info",
        return_value=dut_devices or [],
    ):
        window._on_tagging_complete(results)
        window._on_alignment_state_changed(len(manifests), len(manifests), False)


def test_main_window_title():
    window = _make_window()
    assert window.windowTitle() == "Video Tagging Pipeline"


def test_main_window_has_four_tabs():
    window = _make_window()
    assert window._tabs.count() == 4
    assert window._tabs.widget(0) is window._tagging_tab
    assert window._tabs.widget(1) is window._alignment_tab
    assert window._tabs.widget(2) is window._review_tab
    assert window._tabs.widget(3) is window._execution_tab


def test_main_window_uses_readable_chinese_tab_labels():
    window = _make_window()
    assert [window._tabs.tabText(i) for i in range(window._tabs.count())] == [
        "打标",
        "对齐",
        "审核",
        "执行队列",
    ]


def test_alignment_review_and_execution_tabs_initially_disabled():
    window = _make_window()
    assert not window._tabs.isTabEnabled(1)
    assert not window._tabs.isTabEnabled(2)
    assert not window._tabs.isTabEnabled(3)


def test_batch_load_reads_rk_raw_from_get_list_sheet(tmp_path):
    window = _make_window()
    window._alignment_tab.load_batch = MagicMock()
    manifest = _make_manifest("case_A_0078", row_index=3)
    workbook_path = tmp_path / "records.xlsx"
    workbook_path.write_text("", encoding="utf-8")
    fake_state = MagicMock()

    with patch("video_tagging_assistant.gui.main_window.load_rk_raw_values", return_value={}) as mock_load_rk_raw, patch(
        "video_tagging_assistant.gui.main_window.scan_rk_candidates",
        return_value=(Path("/tmp/rk"), [], []),
    ), patch(
        "video_tagging_assistant.gui.main_window.build_alignment_batch_state",
        return_value=fake_state,
    ):
        window._on_batch_loaded(
            {
                "manifests": [manifest],
                "source_workbook": workbook_path,
                "writeback_workbook": workbook_path,
            }
        )

    mock_load_rk_raw.assert_called_once_with(workbook_path, source_sheet="获取列表")


def test_batch_load_passes_adb_exe_to_rk_candidate_scan(tmp_path):
    window = _make_window()
    window._alignment_tab.load_batch = MagicMock()
    manifest = _make_manifest("case_A_0078", row_index=3)
    workbook_path = tmp_path / "records.xlsx"
    workbook_path.write_text("", encoding="utf-8")
    fake_state = MagicMock()

    with patch("video_tagging_assistant.gui.main_window.load_rk_raw_values", return_value={}), patch(
        "video_tagging_assistant.gui.main_window.scan_rk_candidates",
        return_value=(Path("/tmp/rk"), [], []),
    ) as mock_scan_rk_candidates, patch(
        "video_tagging_assistant.gui.main_window.build_alignment_batch_state",
        return_value=fake_state,
    ):
        window._on_batch_loaded(
            {
                "manifests": [manifest],
                "source_workbook": workbook_path,
                "writeback_workbook": workbook_path,
            }
        )

    mock_scan_rk_candidates.assert_called_once_with(
        temp_root="",
        dut_root="/mnt",
        adb_exe="adb.exe",
    )


def test_close_event_shuts_down_alignment_tab_before_execution_worker():
    window = _make_window()
    close_event = QCloseEvent()
    call_order = []

    window._alignment_tab.shutdown = MagicMock(side_effect=lambda: call_order.append("alignment_shutdown"))
    window._worker.stop.side_effect = lambda: call_order.append("worker_stop")
    window._worker.wait.side_effect = lambda timeout: call_order.append(("worker_wait", timeout))

    window.closeEvent(close_event)

    window._alignment_tab.shutdown.assert_called_once_with()
    window._worker.stop.assert_called_once_with()
    window._worker.wait.assert_called_once_with(3000)
    assert call_order == [
        "alignment_shutdown",
        "worker_stop",
        ("worker_wait", 3000),
    ]


def test_close_event_keeps_window_open_when_alignment_shutdown_fails():
    window = _make_window()
    close_event = QCloseEvent()
    call_order = []

    window._alignment_tab.shutdown = MagicMock(side_effect=RuntimeError("preview stop failed"))
    window._worker.stop.side_effect = lambda: call_order.append("worker_stop")
    window._worker.wait.side_effect = lambda timeout: call_order.append(("worker_wait", timeout))
    window.statusBar().showMessage = MagicMock()

    window.closeEvent(close_event)

    window._alignment_tab.shutdown.assert_called_once_with()
    window._worker.stop.assert_called_once_with()
    window._worker.wait.assert_called_once_with(3000)
    window.statusBar().showMessage.assert_called_once_with(
        "alignment shutdown failed: preview stop failed",
        0,
    )
    assert not close_event.isAccepted()
    assert call_order == [
        "worker_stop",
        ("worker_wait", 3000),
    ]


def test_main_window_keeps_review_locked_until_alignment_and_tagging_finish(tmp_path):
    window = _make_window()
    manifest = _make_manifest("case_A_0078", row_index=3)
    results = [{"manifest": manifest, "ai_result": {"瀹夎鏂瑰紡": "鎵嬫寔"}, "missing": False}]
    workbook_path = tmp_path / "records.xlsx"
    workbook_path.write_text("", encoding="utf-8")
    window._review_tab.load_cases = MagicMock()

    _load_batch(window, workbook_path, [manifest])

    assert window._tabs.isTabEnabled(1)
    assert not window._tabs.isTabEnabled(2)
    assert not window._tabs.isTabEnabled(3)

    window._tagging_tab._xlsx_writeback_path = workbook_path
    window._tagging_tab.auto_execution_enabled = MagicMock(return_value=False)
    window._tagging_tab.selected_device_info = MagicMock(return_value={})
    window._on_tagging_complete(results)

    assert not window._tabs.isTabEnabled(2)
    window._review_tab.load_cases.assert_not_called()

    window._on_alignment_state_changed(1, 1, False)

    assert window._tabs.isTabEnabled(2)
    assert window._tabs.currentIndex() == 2
    window._review_tab.load_cases.assert_called_once()


def test_main_window_relocks_and_reopens_review_when_alignment_changes(tmp_path):
    window = _make_window()
    manifest_one = _make_manifest("case_A_0001", row_index=3)
    manifest_two = _make_manifest("case_A_0002", row_index=4)
    results = [
        {"manifest": manifest_one, "ai_result": {"瀹夎鏂瑰紡": "鎵嬫寔"}, "missing": False},
        {"manifest": manifest_two, "ai_result": {"瀹夎鏂瑰紡": "绌挎埓"}, "missing": False},
    ]
    workbook_path = tmp_path / "records.xlsx"
    workbook_path.write_text("", encoding="utf-8")
    window._execution_tab.add_case = MagicMock()
    _enter_review(window, workbook_path, results)

    window._review_tab.load_cases = MagicMock()
    window._review_tab.advance_after_approval = MagicMock()
    approved_txt = tmp_path / "approved.txt"
    approved_txt.write_text("ok", encoding="utf-8")
    with patch("video_tagging_assistant.gui.main_window.upsert_create_record_row"), patch(
        "video_tagging_assistant.gui.main_window.write_case_txt",
        return_value=approved_txt,
    ):
        window._on_case_approved(manifest_one, _make_tag_result())

    assert window._execution_tab.add_case.call_count == 1
    window._execution_tab.add_case.reset_mock()

    window._on_alignment_state_changed(1, 2, False)

    assert not window._alignment_ready
    assert not window._tabs.isTabEnabled(2)
    assert not window._review_tab.isEnabled()
    assert window._tabs.currentIndex() == 1

    blocked_txt = tmp_path / "blocked.txt"
    blocked_txt.write_text("blocked", encoding="utf-8")
    with patch("video_tagging_assistant.gui.main_window.upsert_create_record_row"), patch(
        "video_tagging_assistant.gui.main_window.write_case_txt",
        return_value=blocked_txt,
    ):
        window._on_case_approved(manifest_two, _make_tag_result())

    assert manifest_two.case_id not in window._approved_case_ids
    window._execution_tab.add_case.assert_not_called()

    window._on_alignment_state_changed(2, 2, False)

    assert window._tabs.isTabEnabled(2)
    assert window._review_tab.isEnabled()
    window._review_tab.load_cases.assert_called_once_with(
        [manifest_two],
        {"case_A_0002": {"瀹夎鏂瑰紡": "绌挎埓"}},
        dut_devices=[],
        auto_mode=False,
        locked_device={},
    )
    window._execution_tab.add_case.assert_not_called()


def test_auto_mode_tagging_completion_locks_selected_device_without_prequeueing_execution(tmp_path):
    window = _make_window()
    workbook_path = tmp_path / "cases.xlsx"
    workbook_path.write_text("", encoding="utf-8")
    manifest_one = _make_manifest("case_A_0001")
    manifest_two = _make_manifest("case_A_0002", row_index=3)
    locked_device = {
        _DEVICE_ID_KEY: "DUT-01",
        _DEVICE_MODEL_KEY: "IMX989",
        _DEVICE_MODE_KEY: "HDR",
    }
    dut_devices = [
        locked_device,
        {
            _DEVICE_ID_KEY: "DUT-02",
            _DEVICE_MODEL_KEY: "OV50H40",
            _DEVICE_MODE_KEY: "NORMAL",
        },
    ]
    results = [
        {"manifest": manifest_one, "ai_result": {"瀹夎鏂瑰紡": "鎵嬫寔"}, "missing": False},
        {"manifest": manifest_two, "ai_result": {"瀹夎鏂瑰紡": "绌挎埓"}, "missing": False},
    ]

    _load_batch(window, workbook_path, [manifest_one, manifest_two])
    window._tagging_tab._xlsx_writeback_path = workbook_path
    window._tagging_tab.auto_execution_enabled = MagicMock(return_value=True)
    window._tagging_tab.selected_device_info = MagicMock(return_value=locked_device)
    window._review_tab.load_cases = MagicMock()
    window._execution_tab.add_case = MagicMock()

    with patch("video_tagging_assistant.gui.main_window.load_dut_info", return_value=dut_devices):
        window._on_tagging_complete(results)
        window._on_alignment_state_changed(2, 2, False)

    expected_mode = "IMX989_HDR"
    expected_local_root = Path("/tmp/local") / expected_mode
    expected_server_root = Path("/tmp/server") / expected_mode

    assert window._auto_execution_enabled is True
    assert window._locked_device_info == locked_device
    assert window._tabs.isTabEnabled(1)
    assert window._tabs.isTabEnabled(2)
    assert not window._tabs.isTabEnabled(3)
    assert window._tabs.currentIndex() == 2
    for manifest in (manifest_one, manifest_two):
        assert manifest.mode == expected_mode
        assert manifest.local_case_root == expected_local_root / manifest.created_date / manifest.case_id
        assert manifest.server_case_dir == expected_server_root / manifest.created_date / manifest.case_id

    window._review_tab.load_cases.assert_called_once_with(
        [manifest_one, manifest_two],
        {
            "case_A_0001": {"瀹夎鏂瑰紡": "鎵嬫寔"},
            "case_A_0002": {"瀹夎鏂瑰紡": "绌挎埓"},
        },
        dut_devices=dut_devices,
        auto_mode=True,
        locked_device=locked_device,
    )
    window._execution_tab.add_case.assert_not_called()


def test_auto_mode_alignment_clear_keeps_execution_locked_until_case_approval(tmp_path):
    window = _make_window()
    workbook_path = tmp_path / "cases.xlsx"
    workbook_path.write_text("", encoding="utf-8")
    manifest = _make_manifest("case_A_0001", row_index=3)
    locked_device = {
        _DEVICE_ID_KEY: "DUT-01",
        _DEVICE_MODEL_KEY: "IMX989",
        _DEVICE_MODE_KEY: "HDR",
    }

    _load_batch(window, workbook_path, [manifest])
    window._tagging_tab._xlsx_writeback_path = workbook_path
    window._tagging_tab.auto_execution_enabled = MagicMock(return_value=True)
    window._tagging_tab.selected_device_info = MagicMock(return_value=locked_device)
    window._execution_tab.add_case = MagicMock()

    with patch("video_tagging_assistant.gui.main_window.load_dut_info", return_value=[locked_device]):
        window._on_tagging_complete([{"manifest": manifest, "ai_result": _make_ai_result(), "missing": False}])
        window._on_alignment_state_changed(1, 1, False)

    assert not window._tabs.isTabEnabled(3)
    assert not window._execution_tab.add_case.called

    window._on_alignment_state_changed(0, 1, False)

    assert not window._tabs.isTabEnabled(2)
    assert not window._tabs.isTabEnabled(3)
    assert not window._execution_tab.add_case.called


def test_auto_mode_approval_writes_outputs_advances_and_enqueues_once(tmp_path):
    window = _make_window()
    manifest = _make_manifest("case_A_0001")
    manifest.mode = "IMX989_HDR"
    manifest.local_case_root = Path("/tmp/local/IMX989_HDR/20260422/case_A_0001")
    manifest.server_case_dir = Path("/tmp/server/IMX989_HDR/20260422/case_A_0001")
    tag_result = _make_tag_result(
        {
            _DEVICE_ID_KEY: "DUT-01",
            _DEVICE_MODEL_KEY: "IMX989",
            _DEVICE_MODE_KEY: "HDR",
        }
    )
    workbook_path = tmp_path / "cases.xlsx"
    workbook_path.write_text("", encoding="utf-8")

    window._auto_execution_enabled = True
    window._alignment_ready = True
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
    assert window._tabs.isTabEnabled(3)
    window._execution_tab.add_case.assert_called_once()


def test_auto_mode_approval_syncs_txt_to_existing_server_case_dir(tmp_path):
    window = _make_window()
    manifest = _make_manifest("case_A_0001")
    manifest.mode = "IMX989_HDR"
    manifest.local_case_root = tmp_path / "local" / "IMX989_HDR" / "20260422" / "case_A_0001"
    manifest.server_case_dir = tmp_path / "server" / "IMX989_HDR" / "20260422" / "case_A_0001"
    manifest.server_case_dir.mkdir(parents=True, exist_ok=True)
    tag_result = _make_tag_result(
        {
            "鐠佹儳顦紓鏍у娇": "DUT-01",
            "濡紕绮嶉崹瀣娇": "IMX989",
            "闁插洭娉﹀Ο鈥崇础": "HDR",
        }
    )
    workbook_path = tmp_path / "cases.xlsx"
    workbook_path.write_text("", encoding="utf-8")

    window._auto_execution_enabled = True
    window._alignment_ready = True
    window._workbook_path = workbook_path
    window._review_tab.advance_after_approval = MagicMock()
    window._execution_tab.add_case = MagicMock()

    with patch("video_tagging_assistant.gui.main_window.upsert_create_record_row"):
        window._on_case_approved(manifest, tag_result)

    server_txt_files = list(manifest.server_case_dir.glob("*.txt"))
    assert len(server_txt_files) == 1
    assert server_txt_files[0].name.startswith("case_A_0001_")
    assert "case reviewed" in server_txt_files[0].read_text(encoding="gbk")
    window._review_tab.advance_after_approval.assert_called_once_with()
    window._execution_tab.add_case.assert_called_once()


def test_auto_mode_existing_server_txt_sync_failure_blocks_advance(tmp_path):
    window = _make_window()
    manifest = _make_manifest("case_A_0001")
    manifest.local_case_root = tmp_path / "local" / "OV50H40_Action5Pro_DCG HDR" / "20260422" / "case_A_0001"
    manifest.server_case_dir = tmp_path / "server" / "OV50H40_Action5Pro_DCG HDR" / "20260422" / "case_A_0001"
    manifest.server_case_dir.mkdir(parents=True, exist_ok=True)
    txt_path = manifest.local_case_root / "case_A_0001_case reviewed.txt"
    txt_path.parent.mkdir(parents=True, exist_ok=True)
    txt_path.write_text("case reviewed", encoding="gbk")
    tag_result = _make_tag_result()
    workbook_path = tmp_path / "cases.xlsx"
    workbook_path.write_text("", encoding="utf-8")

    window._auto_execution_enabled = True
    window._alignment_ready = True
    window._workbook_path = workbook_path
    window._review_tab.advance_after_approval = MagicMock()
    window._execution_tab.add_case = MagicMock()

    with patch("video_tagging_assistant.gui.main_window.upsert_create_record_row"), patch(
        "video_tagging_assistant.gui.main_window.write_case_txt",
        return_value=txt_path,
    ), patch(
        "video_tagging_assistant.gui.main_window.shutil.copy2",
        side_effect=PermissionError("copy failed"),
    ):
        window._on_case_approved(manifest, tag_result)

    window._review_tab.advance_after_approval.assert_not_called()
    window._execution_tab.add_case.assert_not_called()
    assert "txt" in window.statusBar().currentMessage()


def test_writeback_failure_keeps_current_case_in_place_and_does_not_advance(tmp_path):
    window = _make_window()
    manifest = _make_manifest("case_A_0001")
    tag_result = _make_tag_result()
    workbook_path = tmp_path / "cases.xlsx"
    workbook_path.write_text("", encoding="utf-8")

    window._workbook_path = workbook_path
    window._alignment_ready = True
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


def test_writeback_failure_keeps_current_case_visible_and_restores_retryable_review_state(tmp_path):
    window = _make_window()
    manifest = _make_manifest("case_A_0001")
    workbook_path = tmp_path / "cases.xlsx"
    workbook_path.write_text("", encoding="utf-8")
    window._execution_tab.add_case = MagicMock()

    _enter_review(
        window,
        workbook_path,
        [{"manifest": manifest, "ai_result": _make_ai_result(), "missing": False}],
    )
    _select_first_option_per_group(window._review_tab)

    with patch("video_tagging_assistant.gui.main_window.upsert_create_record_row"), patch(
        "video_tagging_assistant.gui.main_window.write_case_txt",
        side_effect=RuntimeError("txt failed"),
    ):
        window._review_tab._pass_btn.click()

    assert window._review_tab._current_index == 0
    assert "case_A_0001" in window._review_tab._case_label.text()
    assert window._review_tab._pass_btn.isEnabled()
    assert window._review_tab._skip_btn.isEnabled()
    assert not window._execution_tab.add_case.called
def test_manual_mode_approval_applies_device_info_and_enqueues_after_successful_writeback(tmp_path):
    window = _make_window()
    manifest = _make_manifest("case_A_0001")
    device_info = {
        _DEVICE_ID_KEY: "DUT-09",
        _DEVICE_MODEL_KEY: "IMX766",
        _DEVICE_MODE_KEY: "NORMAL",
    }
    tag_result = _make_tag_result(device_info)
    workbook_path = tmp_path / "cases.xlsx"
    workbook_path.write_text("", encoding="utf-8")

    window._auto_execution_enabled = False
    window._alignment_ready = True
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
    assert window._tabs.isTabEnabled(3)
    window._execution_tab.add_case.assert_called_once_with(manifest)


def test_manual_batch_after_auto_batch_clears_stale_locked_device_when_no_dut_devices(tmp_path):
    window = _make_window()
    auto_workbook_path = tmp_path / "auto_cases.xlsx"
    auto_workbook_path.write_text("", encoding="utf-8")
    manual_workbook_path = tmp_path / "manual_cases.xlsx"
    manual_workbook_path.write_text("", encoding="utf-8")
    locked_device = {
        _DEVICE_ID_KEY: "DUT-01",
        _DEVICE_MODEL_KEY: "IMX989",
        _DEVICE_MODE_KEY: "HDR",
    }

    auto_manifest = _make_manifest("case_A_0001")
    manual_manifest = _make_manifest("case_A_0002", row_index=3)
    window._execution_tab.add_case = MagicMock()

    _load_batch(window, auto_workbook_path, [auto_manifest])
    window._tagging_tab._xlsx_writeback_path = auto_workbook_path
    window._tagging_tab.auto_execution_enabled = MagicMock(return_value=True)
    window._tagging_tab.selected_device_info = MagicMock(return_value=locked_device)
    with patch("video_tagging_assistant.gui.main_window.load_dut_info", return_value=[locked_device]):
        window._on_tagging_complete([{"manifest": auto_manifest, "ai_result": _make_ai_result(), "missing": False}])
        window._on_alignment_state_changed(1, 1, False)

    assert window._review_tab._device_combo.count() == 1
    assert window._review_tab._device_combo.currentData() == locked_device
    assert not window._review_tab._device_combo.isEnabled()

    _load_batch(window, manual_workbook_path, [manual_manifest])
    window._tagging_tab._xlsx_writeback_path = manual_workbook_path
    window._tagging_tab.auto_execution_enabled = MagicMock(return_value=False)
    window._tagging_tab.selected_device_info = MagicMock(return_value={})
    with patch("video_tagging_assistant.gui.main_window.load_dut_info", return_value=[]):
        window._on_tagging_complete([{"manifest": manual_manifest, "ai_result": _make_ai_result(), "missing": False}])
        window._on_alignment_state_changed(1, 1, False)

    assert window._review_tab._device_combo.count() == 0
    assert window._review_tab._device_combo.currentData() is None
    assert window._review_tab._device_combo.isEnabled()
