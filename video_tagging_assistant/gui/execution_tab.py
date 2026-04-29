"""执行队列 Tab 占位实现（Task 4 将完整实现）。"""
from PyQt5.QtWidgets import QWidget


class ExecutionTab(QWidget):
    def __init__(self, worker, parent=None):
        super().__init__(parent)
        self._worker = worker

    def add_case(self, manifest) -> None:
        """将 manifest 加入执行队列显示。"""

    def on_status_changed(self, case_id: str, step: str, status: str, message: str) -> None:
        """处理 ExecutionWorker.status_changed 信号。"""
