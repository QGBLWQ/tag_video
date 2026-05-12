"""Tab1 打标：模式选择 + 加载工作簿 + 驱动批量打标。

重新标定模式：扫描 dji_nomal_dir，对所有 case 的 vs_normal 视频跑 AI 打标，
              结果写入 intermediate_dir/{stem}.json。
旧数据模式：按获取列表每行 vs_normal_name 的 stem 从 intermediate_dir 加载 JSON，
            找不到的 case 标红并加入错误列表。

全部 case 加载/打标完成后 emit tagging_complete(list)，
list 每项为 {"manifest": CaseManifest, "ai_result": dict, "missing": bool}。
"""
import json
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from video_tagging_assistant.excel_workbook import (
    get_next_case_sequence,
    load_dut_info,
    load_get_list_manifests,
)


class _TaggingWorker(QThread):
    """在后台线程中加载 / 打标，避免阻塞 UI。"""

    progress = pyqtSignal(int, int, str)   # (current, total, current_file)
    log_msg = pyqtSignal(str)              # 日志消息
    error = pyqtSignal(str)                # 错误描述
    finished = pyqtSignal(list)            # list of result dicts

    def __init__(self, config: dict, manifests: list, mode: str, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._manifests = manifests
        self._mode = mode  # "rerun" or "cached"

    def run(self) -> None:
        if self._mode == "rerun":
            self._run_rerun()
        else:
            self._load_cached()

    def _run_rerun(self) -> None:
        """调用 run_batch_tagging，将结构化结果写到 intermediate_dir/{stem}.json。"""
        from video_tagging_assistant.tagging_cache import load_cached_result
        from video_tagging_assistant.tagging_service import run_batch_tagging
        from video_tagging_assistant.gui.app import build_provider_from_config

        intermediate_dir = Path(self._config.get("intermediate_dir", "output/intermediate"))
        intermediate_dir.mkdir(parents=True, exist_ok=True)
        cache_root = Path(self._config.get("cache_root", "artifacts/cache"))
        output_root = Path(self._config.get("tagging_output_root", "artifacts/gui_pipeline"))
        total = len(self._manifests)

        _EVENT_CN = {
            "compressing": "压缩中",
            "compressed": "压缩完成",
            "tagging": "等待AI返回",
            "tagged": "AI打标完成",
            "loaded cache": "命中缓存",
        }

        def _on_event(event):
            msg = event.message
            total_val = event.progress_total or total
            cn_msg = _EVENT_CN.get(msg, msg)
            from datetime import datetime
            ts = datetime.now().strftime("%H:%M:%S")
            log = f"{ts}  {event.case_id}  {cn_msg}"
            # 只有 AI 打标完成才更新进度条
            if msg == "tagged":
                self.progress.emit(event.progress_current or 0, total_val, log)
            else:
                self.log_msg.emit(log)
            if event.event_type in ("error",):
                self.error.emit(f"{ts}  {event.case_id}  错误: {msg}")

        try:
            run_batch_tagging(
                manifests=self._manifests,
                cache_root=cache_root,
                output_root=output_root,
                provider=build_provider_from_config(self._config),
                prompt_template=self._config["prompt_template"],
                mode="fresh",
                event_callback=_on_event,
                concurrency=self._config.get("concurrency", {}),
                compression_config=self._config.get("compression"),
            )
        except Exception as exc:
            self.error.emit(f"打标批次错误: {exc}")

        results = []
        for i, manifest in enumerate(self._manifests):
            cached = load_cached_result(cache_root, manifest) or {}
            ai_result = dict(cached.get("structured_tags", {}))
            ai_result.update(cached.get("multi_select_tags", {}))
            if cached.get("scene_description"):
                ai_result["画面描述"] = cached["scene_description"]
            stem = manifest.vs_normal_path.stem
            json_path = intermediate_dir / f"{stem}.json"
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump({"structured_tags": ai_result}, f, ensure_ascii=False, indent=2)
            results.append({"manifest": manifest, "ai_result": ai_result, "missing": False})
            self.progress.emit(i + 1, total, manifest.case_id)

        self.finished.emit(results)

    def _load_cached(self) -> None:
        """从 intermediate_dir/{stem}.json 加载已有打标结果。"""
        intermediate_dir = Path(self._config.get("intermediate_dir", "output/intermediate"))
        total = len(self._manifests)
        results = []

        for i, manifest in enumerate(self._manifests):
            stem = manifest.vs_normal_path.stem
            json_path = intermediate_dir / f"{stem}.json"
            if json_path.exists():
                with open(json_path, encoding="utf-8") as f:
                    data = json.load(f)
                ai_result = data.get("structured_tags", data)
                missing = False
            else:
                ai_result = {}
                missing = True
                self.error.emit(f"缺少打标数据: {manifest.case_id}（找不到 {stem}.json）")

            results.append({"manifest": manifest, "ai_result": ai_result, "missing": missing})
            self.progress.emit(i + 1, total, manifest.case_id)

        self.finished.emit(results)


class TaggingTab(QWidget):
    """Tab1：工作簿选择 + 模式切换 + 打标进度。"""

    tagging_complete = pyqtSignal(list)
    batch_loaded = pyqtSignal(object)
    auto_exec_requested = pyqtSignal()

    def __init__(self, config: dict, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._manifests: list = []
        self._dut_devices: list = []
        self._auto_start_validator = None
        self._worker: Optional[_TaggingWorker] = None
        self._writeback_path: Optional[Path] = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        # 工作簿路径行
        wb_row = QHBoxLayout()
        self._workbook_edit = QLineEdit(self._config.get("workbook_path", ""))
        self._browse_btn = QPushButton("浏览…")
        self._load_btn = QPushButton("加载工作簿")
        wb_row.addWidget(QLabel("工作簿:"))
        wb_row.addWidget(self._workbook_edit, stretch=1)
        wb_row.addWidget(self._browse_btn)
        wb_row.addWidget(self._load_btn)
        layout.addLayout(wb_row)

        # Case 列表（可勾选，默认全选）
        case_header = QHBoxLayout()
        case_header.addWidget(QLabel("本批 Case 列表："))
        case_header.addStretch()
        self._select_all_btn = QPushButton("全选")
        self._deselect_all_btn = QPushButton("取消全选")
        case_header.addWidget(self._select_all_btn)
        case_header.addWidget(self._deselect_all_btn)
        layout.addLayout(case_header)
        self._case_list = QListWidget()
        self._case_list.setMaximumHeight(160)
        layout.addWidget(self._case_list)

        # 模式选择
        mode_row = QHBoxLayout()
        self._radio_rerun = QRadioButton("重新标定")
        self._radio_cached = QRadioButton("旧数据")
        self._radio_cached.setChecked(True)
        mode_row.addWidget(self._radio_rerun)
        mode_row.addWidget(self._radio_cached)
        mode_row.addStretch()
        layout.addLayout(mode_row)

        auto_row = QHBoxLayout()
        self._auto_mode_check = QCheckBox("自动执行")
        self._device_combo = QComboBox()
        self._device_combo.setEnabled(False)
        auto_row.addWidget(self._auto_mode_check)
        auto_row.addWidget(QLabel("锁定设备"))
        auto_row.addWidget(self._device_combo, stretch=1)
        layout.addLayout(auto_row)

        # 开始按钮 + 进度
        self._start_btn = QPushButton("开始")
        layout.addWidget(self._start_btn)
        self._progress_bar = QProgressBar()
        self._progress_bar.setValue(0)
        self._current_file_label = QLabel("")
        layout.addWidget(self._progress_bar)
        layout.addWidget(self._current_file_label)

        # 执行日志面板
        layout.addWidget(QLabel("执行日志："))
        self._log_panel = QTextEdit()
        self._log_panel.setReadOnly(True)
        self._log_panel.setMaximumHeight(120)
        layout.addWidget(self._log_panel)

        # 错误列表
        layout.addWidget(QLabel("错误（缺少打标数据的 case）："))
        self._error_list = QListWidget()
        self._error_list.setMaximumHeight(100)
        layout.addWidget(self._error_list)

        # 信号连接
        self._browse_btn.clicked.connect(self._browse_workbook)
        self._load_btn.clicked.connect(self._load_cases_from_workbook)
        self._start_btn.clicked.connect(self._start_tagging)
        self._auto_mode_check.toggled.connect(self._sync_auto_mode_widgets)
        self._select_all_btn.clicked.connect(self._select_all_cases)
        self._deselect_all_btn.clicked.connect(self._deselect_all_cases)

    def _browse_workbook(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择工作簿", "", "Excel 文件 (*.xlsx *.xlsm)"
        )
        if path:
            self._workbook_edit.setText(path)
            self._load_cases_from_workbook()

    def _load_cases_from_workbook(self) -> None:
        wb_path = Path(self._workbook_edit.text().strip())
        if not wb_path.exists():
            return
        try:
            pc_id = self._config.get("pc_id", "A")
            starting_seq = get_next_case_sequence(wb_path, pc_id)
            self._manifests, msg = load_get_list_manifests(
                workbook_path=wb_path,
                source_sheet="获取列表",
                pc_id=pc_id,
                dji_nomal_dir=Path(self._config.get("dji_nomal_dir", ".")),
                dji_night_dir=Path(self._config.get("dji_night_dir", ".")),
                local_root=Path(self._config.get("local_case_root", "cases")),
                server_root=Path(self._config.get("server_upload_root", "server_cases")),
                mode=self._config.get("mode", ""),
                starting_sequence=starting_seq,
            )
            if msg:
                self._log_panel.append(msg)
        except Exception as exc:
            self._error_list.addItem(f"加载失败: {exc}")
            return

        self._writeback_path = wb_path

        self._case_list.clear()
        for manifest in self._manifests:
            item = QListWidgetItem(
                f"{manifest.case_id}  {manifest.vs_normal_path.name}"
            )
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            item.setData(Qt.UserRole, manifest)
            self._case_list.addItem(item)

        try:
            self._dut_devices = load_dut_info(wb_path)
        except Exception as exc:
            self._dut_devices = []
            self._error_list.addItem(
                f"加载 DUT 设备信息失败: {exc}。可继续普通打标；如需自动执行，请检查 Dut_info。"
            )

        self._device_combo.clear()
        for device in self._dut_devices:
            label_parts = [
                device.get("\u8bbe\u5907\u7f16\u53f7", ""),
                device.get("\u6a21\u7ec4\u578b\u53f7", ""),
                device.get("\u91c7\u96c6\u6a21\u5f0f", ""),
            ]
            label = " / ".join(part for part in label_parts if part) or "设备信息"
            self._device_combo.addItem(label, device)
        self._device_combo.setCurrentIndex(-1)
        self._sync_auto_mode_widgets()
        self.batch_loaded.emit(
            {
                "manifests": list(self._manifests),
                "source_workbook": wb_path,
                "writeback_workbook": self._writeback_path,
            }
        )

    def _sync_auto_mode_widgets(self) -> None:
        self._device_combo.setEnabled(
            self._auto_mode_check.isChecked() and bool(self._dut_devices)
        )

    def auto_execution_enabled(self) -> bool:
        return self._auto_mode_check.isChecked()

    def selected_device_info(self) -> dict:
        device_info = self._device_combo.currentData()
        if isinstance(device_info, dict):
            return device_info
        return {}

    def set_auto_start_validator(self, validator) -> None:
        self._auto_start_validator = validator

    def _validate_start(self) -> bool:
        if not self.auto_execution_enabled():
            return True

        # 全自动模式：检查对齐是否完成
        if self._auto_start_validator is not None and not self._auto_start_validator():
            return False

        device_info = self.selected_device_info()
        if not device_info:
            self._on_error('已开启自动执行，请先在“锁定设备”中选择一条 Dut_info 设备信息。')
            return False

        required_fields = [
            "\u6a21\u7ec4\u578b\u53f7",
            "\u91c7\u96c6\u6a21\u5f0f",
        ]
        missing_fields = [field for field in required_fields if not device_info.get(field)]
        if missing_fields:
            self._on_error(
                f'所选设备信息缺少必填字段：{", ".join(missing_fields)}。'
                "请在 Dut_info 表中补全后重新加载。"
            )
            return False

        return True

    def _select_all_cases(self) -> None:
        for i in range(self._case_list.count()):
            self._case_list.item(i).setCheckState(Qt.Checked)

    def _deselect_all_cases(self) -> None:
        for i in range(self._case_list.count()):
            self._case_list.item(i).setCheckState(Qt.Unchecked)

    def _get_checked_manifests(self) -> list:
        checked = []
        for i in range(self._case_list.count()):
            item = self._case_list.item(i)
            if item.checkState() == Qt.Checked:
                manifest = item.data(Qt.UserRole)
                if manifest is not None:
                    checked.append(manifest)
        return checked

    def _start_tagging(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return

        if not self._manifests:
            self._load_cases_from_workbook()
        if not self._manifests:
            return

        checked = self._get_checked_manifests()
        if not checked:
            self._on_error("未勾选任何 case，请至少勾选一个。")
            return

        mode = "rerun" if self._radio_rerun.isChecked() else "cached"
        self._error_list.clear()
        if not self._validate_start():
            return
        if self.auto_execution_enabled():
            self.auto_exec_requested.emit()
        self._progress_bar.setMaximum(len(checked))
        self._progress_bar.setValue(0)
        self._log_panel.clear()
        self._start_btn.setEnabled(False)

        if self._worker is not None:
            try:
                self._worker.progress.disconnect()
                self._worker.error.disconnect()
                self._worker.finished.disconnect()
            except TypeError:
                pass  # already disconnected

        self._worker = _TaggingWorker(self._config, checked, mode)
        self._worker.progress.connect(self._on_progress)
        self._worker.log_msg.connect(self._log_panel.append)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _on_progress(self, current: int, total: int, filename: str) -> None:
        if total > 0:
            self._progress_bar.setMaximum(total)
        self._progress_bar.setValue(current)
        self._current_file_label.setText(filename)
        self._log_panel.append(filename)

    def _on_error(self, message: str) -> None:
        item = QListWidgetItem(message)
        item.setForeground(QColor("red"))
        self._error_list.addItem(item)

    def _on_finished(self, results: list) -> None:
        self._start_btn.setEnabled(True)
        self._current_file_label.setText("完成")
        self.tagging_complete.emit(results)
