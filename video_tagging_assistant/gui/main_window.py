from PyQt5.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QTabWidget,
    QTableView,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from video_tagging_assistant.gui.review_panel import ReviewPanel
from video_tagging_assistant.gui.table_models import CaseTableModel


class PipelineMainWindow(QMainWindow):
    def __init__(
        self,
        workbook_path=None,
        scan_cases=None,
        start_tagging=None,
        refresh_excel_reviews=None,
        run_execution_case=None,
        controller=None,
    ):
        super().__init__()
        self.workbook_path = workbook_path
        self._scan_cases = scan_cases
        self._start_tagging = start_tagging
        self._refresh_excel_reviews = refresh_excel_reviews
        self._run_execution_case = run_execution_case
        self._controller = controller
        self._manifests_by_case_id = {}
        self._review_rows_by_case_id = {}

        self.setWindowTitle("Case Pipeline")
        self.queue_model = CaseTableModel([])
        self.queue_table = QTableView()
        self.queue_table.setModel(self.queue_model)
        self.review_panel = ReviewPanel(
            on_approve=self._handle_approve,
            on_approve_after_edit=self._handle_approve_after_edit,
            on_reject=self._handle_reject,
            on_refresh_excel_reviews=self._handle_refresh_excel_reviews,
        )

        self.tabs = QTabWidget()
        self.tabs.addTab(self.queue_table, "今日队列")
        self.tabs.addTab(self.review_panel, "打标审核")
        self.tabs.addTab(self._placeholder_tab("执行监控"), "执行监控")
        self.tabs.addTab(self._placeholder_tab("失败重试"), "失败重试")

        self.tagging_mode_combo = QComboBox()
        self.tagging_mode_combo.addItems(["重新打标", "复用旧打标结果"])
        self.scan_button = QPushButton("扫描新增记录")
        self.start_button = QPushButton("启动流水线")
        self.log_panel = QTextEdit()
        self.log_panel.setReadOnly(True)

        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.addWidget(self.tagging_mode_combo)
        header_layout.addWidget(self.scan_button)
        header_layout.addWidget(self.start_button)

        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.addWidget(header)
        layout.addWidget(self.tabs)
        layout.addWidget(self.log_panel)
        self.setCentralWidget(wrapper)

        self.scan_button.clicked.connect(self._handle_scan)
        self.start_button.clicked.connect(self._handle_start)

    def _selected_tagging_mode(self) -> str:
        return "cached" if self.tagging_mode_combo.currentText() == "复用旧打标结果" else "fresh"

    def _handle_pipeline_event(self, event) -> None:
        stage_value = getattr(event.stage, "value", str(event.stage))
        self.append_log_line(f"{event.case_id} [{stage_value}] {event.message}")

    def _handle_scan(self):
        manifests = self._scan_cases() if self._scan_cases is not None else []
        self._manifests_by_case_id = {manifest.case_id: manifest for manifest in manifests}
        self.queue_model.set_rows(
            [
                {
                    "case_id": manifest.case_id,
                    "stage": "queued",
                    "tag_source": "",
                    "message": manifest.remark,
                }
                for manifest in manifests
            ]
        )
        self.append_log_line(f"Scanned {len(manifests)} cases")

    def _handle_start(self):
        manifests = list(self._manifests_by_case_id.values())
        if not manifests or self._start_tagging is None:
            return
        results = self._start_tagging(manifests, self._selected_tagging_mode(), self._handle_pipeline_event)
        self._review_rows_by_case_id = {row.case_id: row for row in results}
        if results:
            self.review_panel.set_review_row(results[0])
            self.tabs.setCurrentIndex(1)

    def _approve_case(self, case_id: str, label: str) -> None:
        if self._controller is None:
            return
        approved = self._controller.approve_case(case_id)
        self.append_log_line(f"{case_id} {label}")
        if approved and self._run_execution_case is not None:
            self._run_execution_case(case_id)

    def _handle_approve(self):
        payload = self.review_panel.current_review_payload()
        self._approve_case(payload["case_id"], "approved in gui")

    def _handle_approve_after_edit(self):
        payload = self.review_panel.current_review_payload()
        self._approve_case(payload["case_id"], "approved after edit in gui")

    def _handle_reject(self):
        payload = self.review_panel.current_review_payload()
        self.append_log_line(f"{payload['case_id']} rejected in gui")

    def _handle_refresh_excel_reviews(self):
        rows = self._refresh_excel_reviews() if self._refresh_excel_reviews is not None else []
        for row in rows:
            self._approve_case(row["case_id"], f"approved from excel: {row['review_decision']}")

    def _placeholder_tab(self, text: str):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addWidget(QLabel(text))
        return widget

    def append_log_line(self, line: str):
        self.log_panel.append(line)
