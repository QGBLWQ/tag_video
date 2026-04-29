"""三 Tab 主窗口：打标 → 审核 → 执行队列。

管理 Tab 间状态切换，不直接执行业务逻辑：
  - 打标完成 → 解锁审核 Tab，调用 review_tab.load_cases()
  - 审核通过 → 写回工作簿，将 manifest 加入执行队列，解锁执行 Tab

PipelineMainWindow 保留供旧代码向后兼容。
"""
from pathlib import Path

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

from video_tagging_assistant.excel_workbook import upsert_create_record_row, load_dut_info
from video_tagging_assistant.gui.execution_tab import ExecutionTab
from video_tagging_assistant.gui.execution_worker import ExecutionWorker
from video_tagging_assistant.gui.review_panel import ReviewPanel
from video_tagging_assistant.gui.review_tab import ReviewTab
from video_tagging_assistant.gui.table_models import CaseTableModel
from video_tagging_assistant.gui.tagging_tab import TaggingTab


class MainWindow(QMainWindow):
    def __init__(self, config: dict, tag_options: dict, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._tag_options = tag_options
        self._workbook_path = Path(config.get("workbook_path", ""))

        self.setWindowTitle("Video Tagging Pipeline")

        # 执行 Worker（后台线程，贯穿整个 window 生命周期）
        self._worker = ExecutionWorker(config)
        self._worker.start()

        # 三个 Tab
        self._tagging_tab = TaggingTab(config)
        self._review_tab = ReviewTab(config, tag_options)
        self._execution_tab = ExecutionTab(self._worker)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._tagging_tab, "打标")
        self._tabs.addTab(self._review_tab, "审核")
        self._tabs.addTab(self._execution_tab, "执行队列")

        # 初始状态：审核和执行 Tab 禁用
        self._tabs.setTabEnabled(1, False)
        self._tabs.setTabEnabled(2, False)

        self.setCentralWidget(self._tabs)

        # 信号连接
        self._tagging_tab.tagging_complete.connect(self._on_tagging_complete)
        self._review_tab.case_approved.connect(self._on_case_approved)
        self._worker.status_changed.connect(self._execution_tab.on_status_changed)

    def _on_tagging_complete(self, results: list) -> None:
        """打标完成：同步当前工作簿路径，解锁审核 Tab，切换过去，并加载 case 列表。"""
        self._workbook_path = Path(self._tagging_tab._workbook_edit.text().strip())
        manifests = [r["manifest"] for r in results]
        tagging_results = {r["manifest"].case_id: r["ai_result"] for r in results}
        dut_devices = []
        try:
            dut_devices = load_dut_info(self._workbook_path)
        except Exception:
            pass
        self._tabs.setTabEnabled(1, True)
        self._tabs.setCurrentIndex(1)
        self._review_tab.load_cases(manifests, tagging_results, dut_devices=dut_devices)

    def _on_case_approved(self, manifest, tag_result) -> None:
        """审核通过：写回工作簿（仅 .xlsx），将 case 加入执行队列，解锁执行 Tab。"""
        if self._workbook_path.exists() and self._workbook_path.suffix.lower() == ".xlsx":
            try:
                upsert_create_record_row(self._workbook_path, manifest, tag_result)
                self.statusBar().showMessage(f"已写入 {manifest.case_id}", 3000)
            except Exception as exc:
                self.statusBar().showMessage(f"写回失败: {exc}", 0)
        self._tabs.setTabEnabled(2, True)
        self._execution_tab.add_case(manifest)

    def closeEvent(self, event) -> None:
        self._worker.stop()
        self._worker.wait(3000)
        super().closeEvent(event)


# ---------------------------------------------------------------------------
# Legacy window — kept for backward compatibility with app.py and older tests
# ---------------------------------------------------------------------------

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
