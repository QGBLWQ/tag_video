"""审核 Tab 占位实现（Task 6 将完整实现）。"""
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QWidget


class ReviewTab(QWidget):
    case_approved = pyqtSignal(object, object)

    def __init__(self, config: dict, tag_options: dict, parent=None):
        super().__init__(parent)

    def load_cases(self, manifests: list, tagging_results: dict) -> None:
        """加载 case 列表供审核。"""
