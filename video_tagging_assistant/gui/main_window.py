from PyQt5.QtWidgets import QComboBox, QHBoxLayout, QLabel, QMainWindow, QPushButton, QTabWidget, QTextEdit, QVBoxLayout, QWidget


class PipelineMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Case Pipeline")
        self.tabs = QTabWidget()
        self.tabs.addTab(self._placeholder_tab("今日队列"), "今日队列")
        self.tabs.addTab(self._placeholder_tab("打标审核"), "打标审核")
        self.tabs.addTab(self._placeholder_tab("执行监控"), "执行监控")
        self.tabs.addTab(self._placeholder_tab("失败重试"), "失败重试")

        self.tagging_mode_combo = QComboBox()
        self.tagging_mode_combo.addItems(["重新打标", "复用旧打标结果"])
        self.scan_button = QPushButton("扫描新增记录")
        self.start_button = QPushButton("启动流水线")
        self.log_panel = QTextEdit()
        self.log_panel.setReadOnly(True)

        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.addWidget(self.tagging_mode_combo)
        header_layout.addWidget(self.scan_button)
        header_layout.addWidget(self.start_button)

        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.addWidget(header)
        layout.addWidget(self.tabs)
        layout.addWidget(self.log_panel)
        self.setCentralWidget(wrapper)

    def _placeholder_tab(self, text: str):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addWidget(QLabel(text))
        return widget

    def append_log_line(self, line: str):
        self.log_panel.append(line)
