from typing import Callable, Optional

from PyQt5.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class ReviewPanel(QWidget):
    def __init__(
        self,
        on_approve: Optional[Callable[[], None]] = None,
        on_approve_after_edit: Optional[Callable[[], None]] = None,
        on_reject: Optional[Callable[[], None]] = None,
        on_refresh_excel_reviews: Optional[Callable[[], None]] = None,
    ):
        super().__init__()
        self._current_case_id = ""
        self.case_label = QLabel("未选择 case")
        self.auto_summary_label = QLabel("")
        self.auto_tags_label = QLabel("")
        self.auto_scene_label = QLabel("")
        self.tag_source_label = QLabel("")
        self.manual_summary_edit = QTextEdit()
        self.manual_tags_edit = QTextEdit()
        self.review_note_edit = QTextEdit()
        self.approve_button = QPushButton("通过")
        self.approve_after_edit_button = QPushButton("修改后通过")
        self.reject_button = QPushButton("拒绝")
        self.refresh_button = QPushButton("从 Excel 刷新")

        form = QFormLayout()
        form.addRow("Case", self.case_label)
        form.addRow("自动简介", self.auto_summary_label)
        form.addRow("自动标签", self.auto_tags_label)
        form.addRow("自动画面描述", self.auto_scene_label)
        form.addRow("来源", self.tag_source_label)
        form.addRow("人工修订简介", self.manual_summary_edit)
        form.addRow("人工修订标签", self.manual_tags_edit)
        form.addRow("审核备注", self.review_note_edit)

        buttons = QHBoxLayout()
        buttons.addWidget(self.approve_button)
        buttons.addWidget(self.approve_after_edit_button)
        buttons.addWidget(self.reject_button)
        buttons.addWidget(self.refresh_button)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(buttons)

        if on_approve is not None:
            self.approve_button.clicked.connect(on_approve)
        if on_approve_after_edit is not None:
            self.approve_after_edit_button.clicked.connect(on_approve_after_edit)
        if on_reject is not None:
            self.reject_button.clicked.connect(on_reject)
        if on_refresh_excel_reviews is not None:
            self.refresh_button.clicked.connect(on_refresh_excel_reviews)

    def set_review_row(self, row) -> None:
        self._current_case_id = row.case_id
        self.case_label.setText(row.case_id)
        self.auto_summary_label.setText(row.auto_summary)
        self.auto_tags_label.setText(row.auto_tags)
        self.auto_scene_label.setText(row.auto_scene_description)
        self.tag_source_label.setText(row.tag_source)
        self.manual_summary_edit.setPlainText("")
        self.manual_tags_edit.setPlainText("")
        self.review_note_edit.setPlainText("")

    def current_review_payload(self):
        return {
            "case_id": self._current_case_id,
            "manual_summary": self.manual_summary_edit.toPlainText().strip(),
            "manual_tags": self.manual_tags_edit.toPlainText().strip(),
            "review_note": self.review_note_edit.toPlainText().strip(),
        }
