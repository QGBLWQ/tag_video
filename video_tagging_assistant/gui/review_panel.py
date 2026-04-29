from PyQt5.QtWidgets import QLabel, QVBoxLayout, QWidget


class ReviewPanel(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("打标审核"))
