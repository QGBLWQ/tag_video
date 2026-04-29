"""打标 Tab 占位实现（Task 7 将完整实现）。"""
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QWidget


class TaggingTab(QWidget):
    tagging_complete = pyqtSignal(list)

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
