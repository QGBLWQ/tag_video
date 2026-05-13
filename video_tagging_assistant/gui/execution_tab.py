"""执行页界面。

展示每个 case 的 pull、move、upload 状态，并提供失败重试入口。
"""

from datetime import datetime

from PyQt5.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class ExecutionTab(QWidget):
    """第三个主流程 Tab：执行队列与实时日志。"""

    def __init__(self, worker, parent=None) -> None:
        super().__init__(parent)
        self._worker = worker
        self._manifests: dict = {}
        self._retry_buttons: dict = {}
        self._upload_bars: dict = {}  # case_id -> (QProgressBar, QLabel)
        self._setup_ui()

    def _setup_ui(self) -> None:
        """初始化队列列表、进度条区和日志区。"""
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("执行队列："))
        self._queue_list = QListWidget()
        layout.addWidget(self._queue_list)

        layout.addWidget(QLabel("Pull 进度："))
        self._pull_bar = QProgressBar()
        self._pull_bar.setValue(0)
        self._pull_label = QLabel("")
        layout.addWidget(self._pull_bar)
        layout.addWidget(self._pull_label)

        layout.addWidget(QLabel("Upload 进度："))
        self._upload_container = QVBoxLayout()
        layout.addLayout(self._upload_container)
        self._upload_placeholder = QLabel("  （暂无上传任务）")
        self._upload_container.addWidget(self._upload_placeholder)

        layout.addWidget(QLabel("执行日志："))
        self._log_panel = QTextEdit()
        self._log_panel.setReadOnly(True)
        layout.addWidget(self._log_panel)

    def add_case(self, manifest) -> None:
        """把 case 加入界面队列，并通知后台 worker 开始处理。"""
        self._manifests[manifest.case_id] = manifest
        item = QListWidgetItem(f"[ ] {manifest.case_id}  待执行")
        item.setData(256, manifest.case_id)  # Qt.UserRole = 256
        self._queue_list.addItem(item)
        self._worker.enqueue(manifest)

    def on_pull_progress(
        self, case_id: str, current: int, total: int, message: str
    ) -> None:
        """更新 pull 进度条。"""
        if total > 0:
            self._pull_bar.setMaximum(total)
        self._pull_bar.setValue(current)
        self._pull_label.setText(f"{case_id}: {message}")
        item = self._find_item(case_id)
        if item:
            item.setText(f"● {case_id}  pull {message}")

    def on_upload_progress(
        self, case_id: str, current: int, total: int, filename: str
    ) -> None:
        """动态创建/更新 per-case upload 进度条。"""
        if case_id not in self._upload_bars:
            self._ensure_upload_bar(case_id)
        bar, label = self._upload_bars[case_id]
        if total > 0:
            bar.setMaximum(total)
        bar.setValue(current)
        label.setText(f"{case_id}: {current}/{total}  {filename}")
        item = self._find_item(case_id)
        if item:
            item.setText(f"● {case_id}  upload {current}/{total}  {filename}")

    def on_status_changed(
        self, case_id: str, step: str, status: str, message: str
    ) -> None:
        """响应后台状态变化，更新列表与日志。"""
        self._append_log(case_id, step, status, message)
        item = self._find_item(case_id)
        if item is None:
            return

        if status == "started":
            item.setText(f"[ ] {case_id}  {step} 进行中")
        elif status == "completed":
            if step == "upload":
                item.setText(f"[ok] {case_id}  已完成")
                self._remove_upload_bar(case_id)
            else:
                item.setText(f"[ ] {case_id}  {step} 完成，等待下一步")
        elif status == "failed":
            item.setText(f"[x] {case_id}  失败: {step} - {message}")
            self._add_retry_button(case_id)
            if step == "upload":
                self._remove_upload_bar(case_id)

    def _find_item(self, case_id: str):
        """在队列列表中查找指定 case 对应的项。"""
        for i in range(self._queue_list.count()):
            item = self._queue_list.item(i)
            if item.data(256) == case_id:
                return item
        return None

    def _append_log(self, case_id: str, step: str, status: str, message: str) -> None:
        """向日志面板追加一条执行日志。"""
        ts = datetime.now().strftime("%H:%M:%S")
        msg = f"{ts}  {case_id}  {step}  {status}"
        if message:
            msg += f"  - {message}"
        self._log_panel.append(msg)

    def _ensure_upload_bar(self, case_id: str) -> None:
        """为指定 case 创建 upload 进度条。"""
        if not self._upload_bars:
            self._upload_placeholder.hide()
        bar = QProgressBar()
        bar.setValue(0)
        label = QLabel(case_id)
        self._upload_container.addWidget(bar)
        self._upload_container.addWidget(label)
        self._upload_bars[case_id] = (bar, label)

    def _remove_upload_bar(self, case_id: str) -> None:
        """上传完成后移除对应的进度条。"""
        pair = self._upload_bars.pop(case_id, None)
        if pair is None:
            return
        bar, label = pair
        bar.hide()
        label.hide()
        bar.deleteLater()
        label.deleteLater()
        if not self._upload_bars:
            self._upload_placeholder.show()

    def _add_retry_button(self, case_id: str) -> None:
        """为失败 case 增加一次重试按钮。"""
        if case_id in self._retry_buttons:
            return
        btn = QPushButton(f"重试 {case_id}")
        self._retry_buttons[case_id] = btn
        btn.clicked.connect(lambda: self._retry(case_id))
        self.layout().addWidget(btn)

    def _retry(self, case_id: str) -> None:
        """把失败 case 重新送回执行队列。"""
        manifest = self._manifests.get(case_id)
        if manifest is None:
            return
        item = self._find_item(case_id)
        if item:
            item.setText(f"[ ] {case_id}  重试中")
        self._worker.enqueue(manifest)
        btn = self._retry_buttons.pop(case_id, None)
        if btn:
            btn.hide()
            btn.deleteLater()
