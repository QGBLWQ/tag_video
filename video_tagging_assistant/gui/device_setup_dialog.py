"""多设备配置对话框 — 分配标号 + DJI 目录。"""
from pathlib import Path
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFileDialog, QFormLayout,
)
from video_tagging_assistant.device_profile import DeviceProfile


class DeviceSetupDialog(QDialog):
    def __init__(self, serials: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("设备配置")
        self.resize(600, 200)
        self._profiles: list[DeviceProfile] = []
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel(f"检测到 {len(serials)} 台设备，请为每台分配标号和 DJI 目录："))

        form = QFormLayout()
        self._rows = []  # [(serial, label_edit, dji_label)]
        for idx, s in enumerate(serials):
            label_edit = QLineEdit()
            label_edit.setPlaceholderText("如 M1_3")
            dji_label = QLabel("未选择")
            dji_btn = QPushButton("DJI 目录...")

            row = QHBoxLayout()
            row.addWidget(QLabel(s))
            row.addWidget(label_edit)
            row.addWidget(QLabel("DJI:"))
            row.addWidget(dji_label, stretch=1)
            row.addWidget(dji_btn)
            form.addRow(row)
            self._rows.append((s, label_edit, dji_label))

            # closure correctly captures dji_label
            dji_btn.clicked.connect(
                lambda checked, dl=dji_label: self._pick_dji(dl))

        layout.addLayout(form)

        confirm = QPushButton("确认")
        confirm.clicked.connect(self._on_confirm)
        layout.addWidget(confirm)

    def _pick_dji(self, label_widget: QLabel):
        path = QFileDialog.getExistingDirectory(self, "选择 DJI 目录")
        if path:
            label_widget.setText(path)

    def _on_confirm(self):
        for idx, (serial, label_edit, dji_label) in enumerate(self._rows):
            label = label_edit.text().strip()
            dji_path = dji_label.text()
            if not label or dji_path == "未选择":
                continue
            self._profiles.append(DeviceProfile(
                serial=serial,
                label=label,
                dji_dir=Path(dji_path),
                port_base=5555 + idx * 50,
            ))
        self.accept()

    def profiles(self) -> list[DeviceProfile]:
        return self._profiles
