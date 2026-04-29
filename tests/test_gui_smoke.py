from PyQt5.QtWidgets import QApplication

from video_tagging_assistant.gui.main_window import PipelineMainWindow


def test_pipeline_main_window_builds():
    app = QApplication.instance() or QApplication([])
    window = PipelineMainWindow()
    assert window.windowTitle() == "Case Pipeline"
    assert window.tabs.count() >= 3


def test_gui_exposes_tagging_mode_selector():
    app = QApplication.instance() or QApplication([])
    window = PipelineMainWindow()
    assert window.tagging_mode_combo.count() == 2
    assert window.tagging_mode_combo.itemText(0) == "重新打标"
    assert window.tagging_mode_combo.itemText(1) == "复用旧打标结果"


def test_gui_log_panel_appends_event_text():
    app = QApplication.instance() or QApplication([])
    window = PipelineMainWindow()
    window.append_log_line("case_A_0105 upload started")
    assert "upload started" in window.log_panel.toPlainText()
