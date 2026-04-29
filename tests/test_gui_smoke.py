from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

from video_tagging_assistant.gui import app as gui_app
from video_tagging_assistant.gui.main_window import PipelineMainWindow
from video_tagging_assistant.gui.review_panel import ReviewPanel
from video_tagging_assistant.gui.table_models import CaseTableModel
from video_tagging_assistant.pipeline_models import CaseManifest
from video_tagging_assistant.tagging_service import TaggingReviewRow


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


def test_review_panel_loads_row_and_collects_user_edits():
    app = QApplication.instance() or QApplication([])
    panel = ReviewPanel()
    panel.set_review_row(
        TaggingReviewRow(
            case_id="case_A_0105",
            auto_summary="自动简介",
            auto_tags="安装方式=手持",
            auto_scene_description="自动画面描述",
            tag_source="fresh",
        )
    )
    panel.manual_summary_edit.setPlainText("人工简介")
    panel.manual_tags_edit.setPlainText("安装方式=肩扛")
    payload = panel.current_review_payload()

    assert payload["case_id"] == "case_A_0105"
    assert payload["manual_summary"] == "人工简介"
    assert payload["manual_tags"] == "安装方式=肩扛"


def test_review_panel_refresh_button_calls_callback():
    app = QApplication.instance() or QApplication([])
    called = []
    panel = ReviewPanel(on_refresh_excel_reviews=lambda: called.append(True))

    panel.refresh_button.click()

    assert called == [True]


def test_case_table_model_displays_case_stage_and_message():
    model = CaseTableModel(
        [
            {
                "case_id": "case_A_0105",
                "stage": "awaiting_review",
                "tag_source": "fresh",
                "message": "awaiting review",
            }
        ]
    )

    assert model.rowCount() == 1
    assert model.columnCount() == 4
    assert model.data(model.index(0, 0), Qt.DisplayRole) == "case_A_0105"
    assert model.data(model.index(0, 1), Qt.DisplayRole) == "awaiting_review"


def test_main_window_scan_loads_cases_into_queue(tmp_path: Path):
    app = QApplication.instance() or QApplication([])
    called = []

    def fake_scan():
        called.append(True)
        return [
            CaseManifest(
                case_id="case_A_0105",
                row_index=2,
                created_date="20260428",
                mode="OV50H40_Action5Pro_DCG HDR",
                raw_path=tmp_path / "raw",
                vs_normal_path=tmp_path / "normal.MP4",
                vs_night_path=tmp_path / "night.MP4",
                local_case_root=tmp_path / "local" / "case_A_0105",
                server_case_dir=tmp_path / "server" / "case_A_0105",
                remark="场景备注",
                labels={"安装方式": "手持"},
            )
        ]

    window = PipelineMainWindow(scan_cases=fake_scan)
    window.scan_button.click()

    assert called == [True]
    assert window.queue_model.rowCount() == 1
    assert window.log_panel.toPlainText().strip().endswith("Scanned 1 cases")


def test_main_window_start_pipeline_loads_review_panel(tmp_path: Path):
    app = QApplication.instance() or QApplication([])
    manifest = CaseManifest(
        case_id="case_A_0105",
        row_index=2,
        created_date="20260428",
        mode="OV50H40_Action5Pro_DCG HDR",
        raw_path=tmp_path / "raw",
        vs_normal_path=tmp_path / "normal.MP4",
        vs_night_path=tmp_path / "night.MP4",
        local_case_root=tmp_path / "local" / "case_A_0105",
        server_case_dir=tmp_path / "server" / "case_A_0105",
        remark="场景备注",
        labels={"安装方式": "手持"},
    )
    captured = []

    def fake_start_tagging(manifests, mode, event_callback):
        captured.append((manifests[0].case_id, mode))
        event_callback(
            type(
                "Event",
                (),
                {
                    "case_id": "case_A_0105",
                    "stage": type("Stage", (), {"value": "tagging_running"})(),
                    "message": "tagging",
                },
            )()
        )
        return [
            TaggingReviewRow(
                case_id="case_A_0105",
                auto_summary="自动简介",
                auto_tags="安装方式=手持",
                auto_scene_description="自动画面描述",
                tag_source="fresh",
            )
        ]

    window = PipelineMainWindow(start_tagging=fake_start_tagging)
    window._manifests_by_case_id = {manifest.case_id: manifest}
    window.start_button.click()

    assert captured == [("case_A_0105", "fresh")]
    assert window.review_panel.case_label.text() == "case_A_0105"
    assert "tagging" in window.log_panel.toPlainText()


def test_gui_approve_calls_controller_and_execution_runner(tmp_path: Path):
    app = QApplication.instance() or QApplication([])
    approvals = []
    runs = []

    class StubController:
        def approve_case(self, case_id):
            approvals.append(case_id)
            return True

    window = PipelineMainWindow(run_execution_case=lambda case_id: runs.append(case_id), controller=StubController())
    window._review_rows_by_case_id = {
        "case_A_0105": TaggingReviewRow(
            case_id="case_A_0105",
            auto_summary="自动简介",
            auto_tags="安装方式=手持",
            auto_scene_description="自动画面描述",
            tag_source="fresh",
        )
    }
    window.review_panel.set_review_row(window._review_rows_by_case_id["case_A_0105"])

    window.review_panel.approve_button.click()

    assert approvals == ["case_A_0105"]
    assert runs == ["case_A_0105"]


def test_refresh_excel_reviews_only_runs_newly_approved_cases():
    app = QApplication.instance() or QApplication([])
    approvals = []
    runs = []

    class StubController:
        def approve_case(self, case_id):
            approvals.append(case_id)
            if case_id == "case_A_0105":
                return True
            return False

    window = PipelineMainWindow(
        controller=StubController(),
        run_execution_case=lambda case_id: runs.append(case_id),
        refresh_excel_reviews=lambda: [
            {"case_id": "case_A_0105", "review_decision": "审核通过", "manual_summary": "", "manual_tags": "", "review_note": ""},
            {"case_id": "case_A_0106", "review_decision": "审核通过", "manual_summary": "", "manual_tags": "", "review_note": ""},
        ],
    )

    window.review_panel.refresh_button.click()

    assert approvals == ["case_A_0105", "case_A_0106"]
    assert runs == ["case_A_0105"]


def test_launch_case_pipeline_gui_passes_workbook_path(monkeypatch, tmp_path: Path):
    captured = {}

    class FakeWindow:
        def __init__(self, workbook_path=None, **kwargs):
            captured["workbook_path"] = workbook_path

        def show(self):
            captured["shown"] = True

    class FakeQApplication:
        @staticmethod
        def instance():
            return None

        def __init__(self, argv):
            pass

    monkeypatch.setattr(gui_app, "PipelineMainWindow", FakeWindow)
    monkeypatch.setattr(gui_app, "QApplication", FakeQApplication)

    gui_app.launch_case_pipeline_gui(workbook_path=str(tmp_path / "records.xlsx"))

    assert captured["workbook_path"].endswith("records.xlsx")
    assert captured["shown"] is True
