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

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from video_tagging_assistant.excel_workbook import build_case_manifests


class _TaggingWorker(QThread):
    """在后台线程中加载 / 打标，避免阻塞 UI。"""

    progress = pyqtSignal(int, int, str)   # (current, total, current_file)
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

        def _on_event(event):
            self.progress.emit(0, total, getattr(event, "current_file", "") or event.case_id)

        try:
            run_batch_tagging(
                manifests=self._manifests,
                cache_root=cache_root,
                output_root=output_root,
                provider=build_provider_from_config(self._config),
                prompt_template=self._config["prompt_template"],
                mode="fresh",
                event_callback=_on_event,
            )
        except Exception as exc:
            self.error.emit(f"打标批次错误: {exc}")

        results = []
        for i, manifest in enumerate(self._manifests):
            cached = load_cached_result(cache_root, manifest) or {}
            ai_result = cached.get("structured_tags", {})
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

    def __init__(self, config: dict, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._manifests: list = []
        self._worker: Optional[_TaggingWorker] = None
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

        # Case 列表（只读展示）
        self._case_list = QListWidget()
        self._case_list.setMaximumHeight(160)
        layout.addWidget(QLabel("本批 Case 列表："))
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

        # 开始按钮 + 进度
        self._start_btn = QPushButton("开始")
        layout.addWidget(self._start_btn)
        self._progress_bar = QProgressBar()
        self._progress_bar.setValue(0)
        self._current_file_label = QLabel("")
        layout.addWidget(self._progress_bar)
        layout.addWidget(self._current_file_label)

        # 错误列表
        layout.addWidget(QLabel("错误（缺少打标数据的 case）："))
        self._error_list = QListWidget()
        self._error_list.setMaximumHeight(100)
        layout.addWidget(self._error_list)

        # 信号连接
        self._browse_btn.clicked.connect(self._browse_workbook)
        self._load_btn.clicked.connect(self._load_cases_from_workbook)
        self._start_btn.clicked.connect(self._start_tagging)

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
            self._manifests = build_case_manifests(
                workbook_path=wb_path,
                source_sheet="获取列表",
                allowed_statuses=set(),
                local_root=Path(self._config.get("local_case_root", "cases")),
                server_root=Path(self._config.get("server_upload_root", "server_cases")),
                mode=self._config.get("mode", ""),
            )
        except Exception as exc:
            self._error_list.addItem(f"加载失败: {exc}")
            return

        self._case_list.clear()
        for manifest in self._manifests:
            self._case_list.addItem(
                f"{manifest.case_id}  {manifest.vs_normal_path.name}"
            )

    def _start_tagging(self) -> None:
        if not self._manifests:
            self._load_cases_from_workbook()
        if not self._manifests:
            return

        mode = "rerun" if self._radio_rerun.isChecked() else "cached"
        self._error_list.clear()
        self._progress_bar.setMaximum(len(self._manifests))
        self._progress_bar.setValue(0)
        self._start_btn.setEnabled(False)

        self._worker = _TaggingWorker(self._config, self._manifests, mode)
        self._worker.progress.connect(self._on_progress)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _on_progress(self, current: int, total: int, filename: str) -> None:
        if total > 0:
            self._progress_bar.setMaximum(total)
        self._progress_bar.setValue(current)
        self._current_file_label.setText(filename)

    def _on_error(self, message: str) -> None:
        item = QListWidgetItem(message)
        item.setForeground(QColor("red"))
        self._error_list.addItem(item)

    def _on_finished(self, results: list) -> None:
        self._start_btn.setEnabled(True)
        self._current_file_label.setText("完成")
        self.tagging_complete.emit(results)
