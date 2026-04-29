from pathlib import Path
from unittest.mock import MagicMock

from PyQt5.QtWidgets import QApplication

_APP = QApplication.instance() or QApplication([])


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


def _make_tab():
    from video_tagging_assistant.gui.execution_tab import ExecutionTab
    mock_worker = MagicMock()
    mock_worker.status_changed = MagicMock()
    mock_worker.status_changed.connect = MagicMock()
    return ExecutionTab(mock_worker), mock_worker


def test_execution_tab_instantiates():
    from video_tagging_assistant.gui.execution_tab import ExecutionTab
    tab, _ = _make_tab()
    assert tab is not None


def test_add_case_appends_row_to_queue_list():
    tab, mock_worker = _make_tab()
    manifest = _make_manifest("case_A_0001")
    tab.add_case(manifest)
    assert tab._queue_list.count() == 1
    assert "case_A_0001" in tab._queue_list.item(0).text()


def test_add_case_calls_worker_enqueue():
    tab, mock_worker = _make_tab()
    manifest = _make_manifest("case_A_0001")
    tab.add_case(manifest)
    mock_worker.enqueue.assert_called_once_with(manifest)


def test_on_status_changed_updates_item_text():
    tab, _ = _make_tab()
    manifest = _make_manifest("case_A_0078")
    tab.add_case(manifest)

    tab.on_status_changed("case_A_0078", "pull", "started", "")
    text = tab._queue_list.item(0).text()
    assert "pull" in text.lower() or "进行中" in text or "●" in text

    tab.on_status_changed("case_A_0078", "pull", "completed", "")
    tab.on_status_changed("case_A_0078", "move", "completed", "")
    tab.on_status_changed("case_A_0078", "upload", "completed", "")
    final_text = tab._queue_list.item(0).text()
    assert "✓" in final_text or "完成" in final_text


def test_on_status_changed_appends_to_log():
    tab, _ = _make_tab()
    manifest = _make_manifest("case_A_0078")
    tab.add_case(manifest)

    tab.on_status_changed("case_A_0078", "pull", "started", "")
    log_text = tab._log_panel.toPlainText()
    assert "case_A_0078" in log_text
    assert "pull" in log_text


def test_failed_status_shows_retry_button():
    tab, _ = _make_tab()
    manifest = _make_manifest("case_A_0078")
    tab.add_case(manifest)

    tab.on_status_changed("case_A_0078", "pull", "failed", "adb error")

    item_text = tab._queue_list.item(0).text()
    assert "✗" in item_text or "失败" in item_text
    # 确认重试按钮被附加
    assert "case_A_0078" in tab._retry_buttons
