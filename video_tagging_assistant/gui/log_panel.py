from PyQt5.QtWidgets import QTextEdit


class LogPanel(QTextEdit):
    def __init__(self):
        super().__init__()
        self.setReadOnly(True)
