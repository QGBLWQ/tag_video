"""Tab3 执行队列：展示每个 case 的 pull→move→upload 进度，支持失败重试。

add_case(manifest)：
    1. 在 _queue_list 追加「待执行」行
    2. 调用 worker.enqueue(manifest)

on_status_changed(case_id, step, status, message)：
    - 更新对应行的状态图标（● 进行中 / ✓ 完成 / ✗ 失败）
    - 追加日志行（时间戳 + case_id + step + status）
    - 若 status == "failed"：在行末显示「重试」按钮，重试时重新 enqueue
"""
from datetime import datetime

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


class ExecutionTab(QWidget):
    """Tab3：串行执行队列 + 实时日志面板。"""

    def __init__(self, worker, parent=None) -> None:
        super().__init__(parent)
        self._worker = worker
        self._manifests: dict = {}     # case_id → CaseManifest
        self._retry_buttons: dict = {} # case_id → QPushButton
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("执行队列："))
        self._queue_list = QListWidget()
        layout.addWidget(self._queue_list)

        layout.addWidget(QLabel("执行日志："))
        self._log_panel = QTextEdit()
        self._log_panel.setReadOnly(True)
        layout.addWidget(self._log_panel)

    def add_case(self, manifest) -> None:
        """加入队列列表并通知 worker。"""
        self._manifests[manifest.case_id] = manifest
        item = QListWidgetItem(f"○ {manifest.case_id}  待执行")
        item.setData(256, manifest.case_id)   # Qt.UserRole = 256
        self._queue_list.addItem(item)
        self._worker.enqueue(manifest)

    def on_upload_progress(
        self, case_id: str, current: int, total: int, filename: str
    ) -> None:
        """更新队列行的 upload 进度。"""
        item = self._find_item(case_id)
        if item:
            item.setText(f"● {case_id}  upload {current}/{total}  {filename}")

    def on_status_changed(
        self, case_id: str, step: str, status: str, message: str
    ) -> None:
        """更新队列行状态；追加日志；失败时显示重试按钮。"""
        self._append_log(case_id, step, status, message)
        item = self._find_item(case_id)
        if item is None:
            return

        if status == "started":
            item.setText(f"● {case_id}  {step} 进行中…")
        elif status == "completed":
            # 仅当 upload completed 时才标记为全部完成
            if step == "upload":
                item.setText(f"✓ {case_id}  已完成")
            else:
                item.setText(f"● {case_id}  {step} 完成，等待下一步…")
        elif status == "failed":
            item.setText(f"✗ {case_id}  失败: {step} — {message}")
            self._add_retry_button(case_id)

    def _find_item(self, case_id: str):
        for i in range(self._queue_list.count()):
            item = self._queue_list.item(i)
            if item.data(256) == case_id:
                return item
        return None

    def _append_log(self, case_id: str, step: str, status: str, message: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        msg = f"{ts}  {case_id}  {step}  {status}"
        if message:
            msg += f"  —  {message}"
        self._log_panel.append(msg)

    def _add_retry_button(self, case_id: str) -> None:
        if case_id in self._retry_buttons:
            return
        btn = QPushButton(f"重试 {case_id}")
        self._retry_buttons[case_id] = btn
        btn.clicked.connect(lambda: self._retry(case_id))
        # 将重试按钮插入日志面板下方（简单追加到布局）
        self.layout().addWidget(btn)

    def _retry(self, case_id: str) -> None:
        manifest = self._manifests.get(case_id)
        if manifest is None:
            return
        item = self._find_item(case_id)
        if item:
            item.setText(f"○ {case_id}  重试中…")
        self._worker.enqueue(manifest)
        # 移除重试按钮
        btn = self._retry_buttons.pop(case_id, None)
        if btn:
            btn.hide()
            btn.deleteLater()
