from copy import deepcopy
from pathlib import Path

from PyQt5.QtCore import QSize, Qt, pyqtSignal
from PyQt5.QtGui import QIcon, QPixmap
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from video_tagging_assistant.excel_workbook import clear_rk_raw_value, write_rk_raw_value
from video_tagging_assistant.gui.alignment_preview_worker import AlignmentPreviewWorker
from video_tagging_assistant.rk_alignment_service import (
    clear_alignment,
    confirm_alignment,
    enable_rewrite_rows,
)


class AlignmentTab(QWidget):
    alignment_state_changed = pyqtSignal(int, int, bool)

    def __init__(self, config: dict, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._manifests = []
        self._source_workbook_path = None
        self._writeback_workbook_path = None
        self._state = None
        self._displayed_cases = []
        self._rewrite_mode_row_indices = []
        self._candidate_overrides = {}
        self._preview_results_by_row = {}
        self._preview_worker = None
        self._preview_generation = 0
        self._runtime_logs = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        outer = QHBoxLayout(self)

        left = QVBoxLayout()
        left.addWidget(QLabel("\u5bf9\u9f50\u961f\u5217"))
        self._queue_list = QListWidget()
        left.addWidget(self._queue_list, stretch=1)
        self._rewrite_btn = QPushButton("\u91cd\u5199\u5df2\u5bf9\u9f50\u884c")
        left.addWidget(self._rewrite_btn)
        left.addWidget(QLabel("\u65e5\u5fd7"))
        self._log_panel = QTextEdit()
        self._log_panel.setReadOnly(True)
        left.addWidget(self._log_panel, stretch=1)

        right = QVBoxLayout()
        self._candidate_label = QLabel("\u5168\u90e8\u5bf9\u9f50\u5b8c\u6210")
        self._candidate_label.setWordWrap(True)
        right.addWidget(self._candidate_label)
        self._rk_preview_label = QLabel("\u5168\u90e8\u5bf9\u9f50\u5b8c\u6210")
        self._rk_preview_label.setAlignment(Qt.AlignCenter)
        self._rk_preview_label.setMinimumHeight(160)
        self._rk_preview_label.setWordWrap(True)
        right.addWidget(self._rk_preview_label)

        nav_row = QHBoxLayout()
        self._prev_btn = QPushButton("\u4e0a\u4e00\u4e2a RK")
        self._next_btn = QPushButton("\u4e0b\u4e00\u4e2a RK")
        nav_row.addWidget(self._prev_btn)
        nav_row.addWidget(self._next_btn)
        right.addLayout(nav_row)

        right.addWidget(QLabel("DJI Normal"))
        self._normal_preview_list = QListWidget()
        self._normal_preview_list.setIconSize(QSize(120, 90))
        right.addWidget(self._normal_preview_list, stretch=1)
        right.addWidget(QLabel("DJI Night"))
        self._night_preview_list = QListWidget()
        self._night_preview_list.setIconSize(QSize(120, 90))
        right.addWidget(self._night_preview_list, stretch=1)

        action_row = QHBoxLayout()
        self._confirm_btn = QPushButton("\u786e\u8ba4\u5bf9\u9f50")
        self._clear_btn = QPushButton("\u6e05\u9664\u5bf9\u9f50")
        action_row.addWidget(self._confirm_btn)
        action_row.addWidget(self._clear_btn)
        right.addLayout(action_row)

        outer.addLayout(left, stretch=1)
        outer.addLayout(right, stretch=2)

        self._queue_list.currentRowChanged.connect(self._show_case_by_index)
        self._rewrite_btn.clicked.connect(self._load_all_aligned_rows_for_rewrite)
        self._prev_btn.clicked.connect(self._select_previous_candidate)
        self._next_btn.clicked.connect(self._select_next_candidate)
        self._confirm_btn.clicked.connect(self._confirm_current_case)
        self._clear_btn.clicked.connect(self._clear_current_case)

    def load_batch(self, manifests, workbook_path: Path, writeback_workbook_path: Path, initial_state) -> None:
        self._stop_preview_worker()
        self._manifests = list(manifests)
        self._source_workbook_path = Path(workbook_path)
        self._writeback_workbook_path = Path(writeback_workbook_path)
        self._state = initial_state
        self._rewrite_mode_row_indices = []
        self._candidate_overrides = {}
        self._preview_results_by_row = {
            manifest.row_index: {"status": "pending"}
            for manifest in self._manifests
        }
        self._runtime_logs = []
        self._render()
        self._start_preview_worker()

    def load_rewrite_rows(self, row_indices) -> None:
        if self._state is not None:
            self._state = enable_rewrite_rows(self._state, list(row_indices))
        self._rewrite_mode_row_indices = list(row_indices)
        self._render()

    def shutdown(self) -> None:
        self._stop_preview_worker()

    def is_complete(self) -> bool:
        return self._state is not None and not self._state.pending_cases and not self.is_blocked()

    def is_blocked(self) -> bool:
        return self._state is not None and bool(self._state.blocked_messages)

    def _display_cases(self):
        if self._state is None:
            return []
        if not self._rewrite_mode_row_indices:
            return list(self._state.pending_cases)

        aligned_by_row = {
            case.manifest.row_index: case
            for case in self._state.aligned_cases
        }
        pending_by_row = {
            case.manifest.row_index: case
            for case in self._state.pending_cases
        }
        displayed = []
        for row_index in self._rewrite_mode_row_indices:
            case = aligned_by_row.get(row_index)
            if case is None:
                case = pending_by_row.get(row_index)
            if case is not None:
                displayed.append(case)
        return displayed

    def _render(self) -> None:
        self._displayed_cases = self._display_cases()
        self._queue_list.blockSignals(True)
        self._queue_list.clear()
        self._queue_list.setCurrentRow(-1)
        for case in self._displayed_cases:
            self._queue_list.addItem(
                "row {row} | {case_id} | {status} | {normal}".format(
                    row=case.manifest.row_index,
                    case_id=case.manifest.case_id,
                    status=case.status,
                    normal=case.manifest.vs_normal_path.name,
                )
            )
        self._queue_list.blockSignals(False)
        self._render_logs()

        if self._displayed_cases:
            self._queue_list.setCurrentRow(0)
        else:
            self._normal_preview_list.clear()
            self._night_preview_list.clear()
            self._candidate_label.setText("\u5168\u90e8\u5bf9\u9f50\u5b8c\u6210")
            self._rk_preview_label.clear()
            self._rk_preview_label.setText("\u5168\u90e8\u5bf9\u9f50\u5b8c\u6210")
            self._sync_buttons(None, None)

        self._emit_state_change()

    def _render_logs(self) -> None:
        if self._state is None:
            self._log_panel.clear()
            return
        lines = [self._normalize_log_text(line) for line in self._state.bad_directory_logs]
        lines.extend(self._state.blocked_messages)
        lines.extend(self._runtime_logs)
        self._log_panel.setPlainText("\n".join(lines))

    def _show_case_by_index(self, index: int) -> None:
        if index < 0 or index >= len(self._displayed_cases):
            self._normal_preview_list.clear()
            self._night_preview_list.clear()
            self._candidate_label.setText("\u5168\u90e8\u5bf9\u9f50\u5b8c\u6210")
            self._rk_preview_label.clear()
            self._rk_preview_label.setText("\u5168\u90e8\u5bf9\u9f50\u5b8c\u6210")
            self._sync_buttons(None, None)
            return

        case = self._displayed_cases[index]
        preview_ready = self._render_preview_state(case)
        self._refresh_candidate_widgets(case, update_rk_preview=preview_ready)

    def _render_preview_state(self, case) -> bool:
        preview_result = self._preview_results_by_row.get(case.manifest.row_index, {"status": "pending"})
        status = preview_result.get("status", "pending")

        if status == "prepared":
            self._populate_preview_list(self._normal_preview_list, preview_result.get("normal_frames", []))
            self._populate_preview_list(self._night_preview_list, preview_result.get("night_frames", []))
            return True

        self._normal_preview_list.clear()
        self._night_preview_list.clear()
        self._rk_preview_label.clear()
        if status == "failed":
            self._rk_preview_label.setText("\u9884\u89c8\u751f\u6210\u5931\u8d25\uff0c\u8bf7\u68c0\u67e5 DJI \u89c6\u9891")
        else:
            self._rk_preview_label.setText("\u9884\u89c8\u51c6\u5907\u4e2d\uff0c\u8bf7\u7a0d\u5019")
        return False

    def _populate_preview_list(self, widget: QListWidget, frames) -> None:
        widget.clear()
        for frame in frames:
            frame_path = Path(frame)
            item = QListWidgetItem()
            item.setText(frame_path.name)
            icon = QIcon(str(frame_path))
            if not icon.isNull():
                item.setIcon(icon)
            widget.addItem(item)

    def _refresh_candidate_widgets(self, case, update_rk_preview: bool = True) -> None:
        candidate_index = self._current_candidate_index(case)
        candidate = self._candidate_by_index(candidate_index)

        if candidate is None:
            self._candidate_label.setText("\u65e0\u53ef\u7528 RK")
            if update_rk_preview:
                self._rk_preview_label.clear()
                self._rk_preview_label.setText("\u65e0\u53ef\u7528 RK")
        else:
            self._candidate_label.setText(
                f"{candidate.folder_name} ({candidate_index + 1}/{len(self._state.candidates)})"
            )
            if update_rk_preview:
                pixmap = QPixmap(str(candidate.preview_path))
                self._rk_preview_label.clear()
                if pixmap.isNull():
                    self._rk_preview_label.setText(candidate.preview_path.name)
                else:
                    self._rk_preview_label.setPixmap(
                        pixmap.scaled(320, 240, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    )
        self._sync_buttons(case, candidate)

    def _sync_buttons(self, case, candidate) -> None:
        has_case = case is not None
        has_candidate = candidate is not None
        preview_ready = has_case and self._preview_results_by_row.get(case.manifest.row_index, {}).get("status") == "prepared"
        self._prev_btn.setEnabled(has_case and has_candidate and self._current_candidate_index(case) > 0)
        self._next_btn.setEnabled(
            has_case
            and has_candidate
            and self._current_candidate_index(case) < len(self._state.candidates) - 1
        )
        self._confirm_btn.setEnabled(has_case and has_candidate and preview_ready)
        self._clear_btn.setEnabled(has_case)

    def _current_case(self):
        index = self._queue_list.currentRow()
        if index < 0 or index >= len(self._displayed_cases):
            return None
        return self._displayed_cases[index]

    def _current_candidate_index(self, case) -> int:
        return self._candidate_overrides.get(case.manifest.row_index, case.selected_candidate_index)

    def _candidate_by_index(self, candidate_index: int):
        if self._state is None:
            return None
        if candidate_index < 0 or candidate_index >= len(self._state.candidates):
            return None
        return self._state.candidates[candidate_index]

    def _select_previous_candidate(self) -> None:
        case = self._current_case()
        if case is None:
            return
        candidate_index = self._current_candidate_index(case)
        if candidate_index <= 0:
            return
        self._candidate_overrides[case.manifest.row_index] = candidate_index - 1
        self._refresh_candidate_widgets(case)

    def _select_next_candidate(self) -> None:
        case = self._current_case()
        if case is None:
            return
        candidate_index = self._current_candidate_index(case)
        if candidate_index < 0 or candidate_index >= len(self._state.candidates) - 1:
            return
        self._candidate_overrides[case.manifest.row_index] = candidate_index + 1
        self._refresh_candidate_widgets(case)

    def _confirm_current_case(self) -> None:
        case = self._current_case()
        if case is None or self._state is None or self._writeback_workbook_path is None:
            return

        candidate = self._candidate_by_index(self._current_candidate_index(case))
        if candidate is None:
            self._append_log(f"{case.manifest.case_id} has no RK candidate to confirm")
            self._render_logs()
            return
        if self._preview_results_by_row.get(case.manifest.row_index, {}).get("status") != "prepared":
            return

        try:
            confirm_alignment(deepcopy(self._state), case.manifest.row_index, candidate.folder_name)
            write_rk_raw_value(
                self._writeback_workbook_path,
                "\u83b7\u53d6\u5217\u8868",
                case.manifest.row_index,
                candidate.folder_name,
            )
            self._state = confirm_alignment(self._state, case.manifest.row_index, candidate.folder_name)
        except Exception as exc:
            self._append_log(f"{case.manifest.case_id} confirm failed: {exc}")
            self._render_logs()
            return

        self._candidate_overrides.pop(case.manifest.row_index, None)
        self._append_log(f"{case.manifest.case_id} aligned to RK {candidate.folder_name}")
        self._render()

    def _clear_current_case(self) -> None:
        case = self._current_case()
        if case is None or self._state is None or self._writeback_workbook_path is None:
            return

        try:
            clear_rk_raw_value(
                self._writeback_workbook_path,
                "\u83b7\u53d6\u5217\u8868",
                case.manifest.row_index,
            )
            self._state = clear_alignment(self._state, case.manifest.row_index)
        except Exception as exc:
            self._append_log(f"{case.manifest.case_id} clear failed: {exc}")
            self._render_logs()
            return

        self._candidate_overrides.pop(case.manifest.row_index, None)
        self._append_log(f"{case.manifest.case_id} alignment cleared")
        self._render()

    def _load_all_aligned_rows_for_rewrite(self) -> None:
        if self._state is None:
            return
        self.load_rewrite_rows([case.manifest.row_index for case in self._state.aligned_cases])

    def _emit_state_change(self) -> None:
        if self._state is None:
            self.alignment_state_changed.emit(0, 0, False)
            return
        self.alignment_state_changed.emit(
            len(self._state.aligned_cases),
            len(self._state.manifests),
            self.is_blocked(),
        )

    def _append_log(self, message: str) -> None:
        if message not in self._runtime_logs:
            self._runtime_logs.append(message)

    def _normalize_log_text(self, message: str) -> str:
        return message.replace("missing a preview", "missing preview")

    def _start_preview_worker(self) -> None:
        if self._state is None or not self._state.manifests:
            return
        self._preview_generation += 1
        generation = self._preview_generation
        worker = AlignmentPreviewWorker(self._config, list(self._state.manifests), self)
        worker.preview_result.connect(lambda payload, current=generation: self._on_preview_result(current, payload))
        worker.log_message.connect(lambda message, current=generation: self._on_preview_log(current, message))
        worker.finished.connect(lambda current=generation, ref=worker: self._on_preview_worker_finished(current, ref))
        self._preview_worker = worker
        worker.start()

    def _stop_preview_worker(self) -> None:
        worker = self._preview_worker
        if worker is None:
            return
        self._preview_generation += 1
        self._preview_worker = None
        worker.stop()
        if not worker.wait(2000):
            worker.wait()

    def _on_preview_result(self, generation: int, payload: dict) -> None:
        if generation != self._preview_generation:
            return
        row_index = payload.get("row_index")
        if row_index is None:
            return
        self._preview_results_by_row[row_index] = dict(payload)
        if payload.get("status") == "failed":
            self._append_preview_failure_logs(payload)
        current_case = self._current_case()
        if current_case is not None and current_case.manifest.row_index == row_index:
            self._show_case_by_index(self._queue_list.currentRow())

    def _on_preview_log(self, generation: int, message: str) -> None:
        if generation != self._preview_generation:
            return
        self._append_log(message)
        self._render_logs()

    def _on_preview_worker_finished(self, generation: int, worker) -> None:
        if generation != self._preview_generation:
            return
        if self._preview_worker is worker:
            self._preview_worker = None

    def _append_preview_failure_logs(self, payload: dict) -> None:
        case_id = payload.get("case_id", "")
        normal_source = Path(payload.get("normal_source"))
        night_source = Path(payload.get("night_source"))
        normal_exists = payload.get("normal_exists", normal_source.exists())
        night_exists = payload.get("night_exists", night_source.exists())
        self._append_log(f"{case_id} DJI normal preview source: {normal_source} (exists={normal_exists})")
        self._append_log(f"{case_id} DJI night preview source: {night_source} (exists={night_exists})")
        self._append_log(
            f"{case_id} preview generation failed with ffprobe={self._config.get('ffprobe_exe', 'ffprobe')} "
            f"ffmpeg={self._config.get('ffmpeg_exe', 'ffmpeg')}: {payload.get('error', '')}"
        )
        self._render_logs()
