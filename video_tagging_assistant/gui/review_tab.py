"""审核页界面。

负责按 case 逐条展示 AI 打标结果，并由人工补全单选/多选字段、
修订画面描述、选择设备信息后确认通过。
"""

import subprocess
from pathlib import Path

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from video_tagging_assistant.excel_workbook import TagResult

_FIELD_ATTR = {
    "\u5b89\u88c5\u65b9\u5f0f": "install_method",
    "\u8fd0\u52a8\u6a21\u5f0f": "motion_mode",
    "\u8fd0\u955c\u65b9\u5f0f": "camera_move",
    "\u5149\u6e90": "light_source",
    "\u753b\u9762\u7279\u5f81": "image_feature",
    "\u5f71\u50cf\u8868\u8fbe": "image_expression",
}

_SINGLE_FIELDS = [
    "\u5b89\u88c5\u65b9\u5f0f",
    "\u8fd0\u52a8\u6a21\u5f0f",
    "\u8fd0\u955c\u65b9\u5f0f",
    "\u5149\u6e90",
]
_MULTI_FIELDS = ["\u753b\u9762\u7279\u5f81", "\u5f71\u50cf\u8868\u8fbe"]


def _device_label(device: dict) -> str:
    """把设备字典格式化成下拉框中可读的一行文本。"""
    label_parts = [
        device.get("\u8bbe\u5907\u7f16\u53f7", ""),
        device.get("\u6a21\u7ec4\u578b\u53f7", ""),
        device.get("\u91c7\u96c6\u6a21\u5f0f", ""),
    ]
    return " / ".join(part for part in label_parts if part) or "\u8bbe\u5907\u4fe1\u606f"


class ReviewTab(QWidget):
    """第二个主流程 Tab：逐条人工审核打标结果。"""

    case_approved = pyqtSignal(object, object)  # (CaseManifest, TagResult)

    def __init__(self, config: dict, tag_options: dict, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._tag_options = tag_options
        self._manifests: list = []
        self._tagging_results: dict = {}
        self._current_index = 0
        self._groups: dict = {}
        self._auto_mode = False
        self._approved_ids: set = set()
        self._back_history: list = []  # [{"index": int, "selections": dict, "scene": str}, ...]
        self._locked_device = None
        self._awaiting_parent_confirmation = False
        self._device_combo = QComboBox()
        self._setup_ui()

    def _setup_ui(self) -> None:
        """初始化审核页控件与按钮事件。"""
        outer = QVBoxLayout(self)

        info_row = QHBoxLayout()
        self._progress_label = QLabel("0/0")
        self._case_label = QLabel("-")
        self._preview_btn = QPushButton("\u25b6 PotPlayer \u9884\u89c8")
        info_row.addWidget(self._progress_label)
        info_row.addWidget(self._case_label, stretch=1)
        info_row.addWidget(self._preview_btn)
        outer.addLayout(info_row)

        device_row = QHBoxLayout()
        device_row.addWidget(QLabel("\u8bbe\u5907\u7f16\u53f7:"))
        device_row.addWidget(self._device_combo, stretch=1)
        outer.addLayout(device_row)

        self._ai_summary_label = QLabel("AI \u6807\u7b7e\uff1a\uff08\u672a\u52a0\u8f7d\uff09")
        self._ai_summary_label.setWordWrap(True)
        outer.addWidget(self._ai_summary_label)

        outer.addWidget(QLabel("\u753b\u9762\u63cf\u8ff0\uff08\u53ef\u4fee\u6539\uff09\uff1a"))
        self._scene_desc_edit = QTextEdit()
        self._scene_desc_edit.setMaximumHeight(80)
        outer.addWidget(self._scene_desc_edit)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        fields_widget = QWidget()
        self._fields_layout = QFormLayout(fields_widget)
        scroll.setWidget(fields_widget)
        outer.addWidget(scroll, stretch=1)

        note_row = QHBoxLayout()
        note_row.addWidget(QLabel("\u5907\u6ce8:"))
        self._note_edit = QLineEdit()
        note_row.addWidget(self._note_edit, stretch=1)
        outer.addLayout(note_row)

        btn_row = QHBoxLayout()
        self._prev_btn = QPushButton("\u2190 \u4e0a\u4e00\u4e2a")
        self._pass_btn = QPushButton("\u2714 \u5199\u5165")
        self._skip_btn = QPushButton("\u2192 \u8df3\u8fc7")
        btn_row.addWidget(self._prev_btn)
        btn_row.addWidget(self._pass_btn)
        btn_row.addWidget(self._skip_btn)
        btn_row.addStretch()
        outer.addLayout(btn_row)

        self._preview_btn.clicked.connect(self._open_potplayer)
        self._prev_btn.clicked.connect(self._go_previous)
        self._pass_btn.clicked.connect(self._handle_pass)
        self._skip_btn.clicked.connect(self._handle_skip)

    def _rebuild_field_buttons(self, ai_result: dict) -> None:
        """根据当前 AI 结果重建所有字段的单选按钮组。"""
        while self._fields_layout.rowCount() > 0:
            self._fields_layout.removeRow(0)
        self._groups.clear()

        for field in _SINGLE_FIELDS:
            options = self._tag_options.get(field, [])
            ai_value = ai_result.get(field, "")
            group = QButtonGroup(self)
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            for option in options:
                button = QRadioButton(option)
                if option == ai_value:
                    button.setChecked(True)
                group.addButton(button)
                row_layout.addWidget(button)
            row_layout.addStretch()
            self._groups[field] = group
            self._fields_layout.addRow(f"{field}:", row_widget)

        for field in _MULTI_FIELDS:
            ai_suggestions = ai_result.get(field, [])
            if isinstance(ai_suggestions, str):
                ai_suggestions = [ai_suggestions]
            options = ai_suggestions if ai_suggestions else self._tag_options.get(field, [])
            group = QButtonGroup(self)
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            for option in options:
                button = QRadioButton(option)
                group.addButton(button)
                row_layout.addWidget(button)
            row_layout.addStretch()
            self._groups[field] = group
            self._fields_layout.addRow(f"{field}\uff08AI \u5efa\u8bae\uff0c\u9009\u4e00\uff09:", row_widget)

    def _populate_device_combo(self, dut_devices) -> None:
        """刷新设备下拉框，并尽量保留之前的选择。"""
        previous_label = self._device_combo.currentText()
        self._device_combo.clear()
        for device in dut_devices:
            self._device_combo.addItem(device.get("\u8bbe\u5907\u7f16\u53f7", ""), device)
        index = self._device_combo.findText(previous_label)
        if index >= 0:
            self._device_combo.setCurrentIndex(index)

    def _sync_action_buttons(self) -> None:
        """根据当前 case 状态刷新通过/跳过按钮是否可点击。"""
        has_current_case = bool(self._manifests) and self._current_index < len(self._manifests)
        allow_actions = has_current_case and not self._awaiting_parent_confirmation
        self._pass_btn.setEnabled(allow_actions)
        self._skip_btn.setEnabled(allow_actions and not self._auto_mode)
        if self._prev_btn:
            self._prev_btn.setEnabled(
                self._current_index > 0
                and not self._awaiting_parent_confirmation
                and bool(self._back_history)
            )

    def load_cases(
        self,
        cases: list,
        tagging_results: dict,
        dut_devices=None,
        auto_mode: bool = False,
        locked_device=None,
    ) -> None:
        """装载一批待审核 case，并根据模式初始化设备选择状态。"""
        self._manifests = cases
        self._tagging_results = tagging_results
        self._current_index = 0
        self._auto_mode = auto_mode
        self._locked_device = locked_device if isinstance(locked_device, dict) else None
        self._awaiting_parent_confirmation = False
        self._approved_ids = set()
        self._back_history = []

        if self._auto_mode and self._locked_device:
            self._device_combo.clear()
            self._device_combo.addItem(_device_label(self._locked_device), self._locked_device)
            self._device_combo.setEnabled(False)
        else:
            if dut_devices:
                self._populate_device_combo(dut_devices)
            self._device_combo.setEnabled(True)

        self._show_case(0)

    def add_case(self, manifest, ai_result: dict) -> None:
        """增量追加单个 case 到审核队列。"""
        self._manifests.append(manifest)
        self._tagging_results[manifest.case_id] = ai_result
        self._show_case(self._current_index)
        self._sync_action_buttons()

    def update_case_results(self, results: list) -> None:
        """审核页已开放时，用新的打标结果更新已有 case 的 AI 数据。"""
        for r in results:
            cid = r["manifest"].case_id
            self._tagging_results[cid] = r.get("ai_result", {})
            # 重新加载后被覆盖，清除已通过状态
            self._approved_ids.discard(cid)
        self._show_case(self._current_index)
        self._sync_action_buttons()

    def _show_case(self, index: int) -> None:
        """把指定索引的 case 渲染到审核界面。"""
        if not self._manifests or index >= len(self._manifests):
            self._progress_label.setText(f"{index}/{len(self._manifests)}")
            self._case_label.setText("\u5168\u90e8\u5ba1\u6838\u5b8c\u6bd5")
            self._sync_action_buttons()
            return

        manifest = self._manifests[index]
        ai_result = self._tagging_results.get(manifest.case_id, {})

        status_tag = " [已通过]" if manifest.case_id in self._approved_ids else ""
        self._progress_label.setText(f"{index + 1}/{len(self._manifests)}")
        self._case_label.setText(f"{manifest.case_id}{status_tag}   {manifest.vs_normal_path.name}")
        self._note_edit.clear()

        lines = []
        for key, value in ai_result.items():
            if key == "\u753b\u9762\u63cf\u8ff0":
                continue
            if isinstance(value, list):
                lines.append(f"{key}: {', '.join(value)}")
            else:
                lines.append(f"{key}: {value}")
        self._ai_summary_label.setText("AI \u6807\u7b7e\uff1a" + " | ".join(lines))
        self._scene_desc_edit.setPlainText(ai_result.get("\u753b\u9762\u63cf\u8ff0", ""))

        self._rebuild_field_buttons(ai_result)
        self._sync_action_buttons()

    def _advance(self) -> None:
        """切换到下一个待审核 case。"""
        self._current_index += 1
        self._show_case(self._current_index)

    def advance_after_approval(self) -> None:
        """父窗口写回成功后，正式推进到下一条 case。"""
        if not self._awaiting_parent_confirmation:
            return
        self._awaiting_parent_confirmation = False
        self._advance()

    def _collect_selections(self):
        """收集当前各字段的人工选择，若未选满则返回 None。"""
        selections = {}
        for field in list(_SINGLE_FIELDS) + list(_MULTI_FIELDS):
            group = self._groups.get(field)
            if group is None:
                continue
            checked = group.checkedButton()
            if checked is None:
                return None
            selections[field] = checked.text()
        return selections

    def _handle_pass(self) -> None:
        """组装人工审核结果，并通知父窗口执行后续写回逻辑。"""
        if self._awaiting_parent_confirmation:
            return

        selections = self._collect_selections()
        if selections is None:
            QMessageBox.warning(
                self,
                "\u5b57\u6bb5\u672a\u5b8c\u6574",
                "\u8bf7\u9009\u62e9\u6240\u6709\u5b57\u6bb5\u540e\u518d\u70b9\u51fb\u901a\u8fc7\u3002",
            )
            return

        manifest = self._manifests[self._current_index]
        if manifest.case_id in self._approved_ids:
            reply = QMessageBox.question(
                self, "确认覆盖",
                f"{manifest.case_id} 已写入过，确定覆盖？",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

        device_info = self._device_combo.currentData() or {}
        tag_result = TagResult(
            install_method=selections.get("\u5b89\u88c5\u65b9\u5f0f", ""),
            motion_mode=selections.get("\u8fd0\u52a8\u6a21\u5f0f", ""),
            camera_move=selections.get("\u8fd0\u955c\u65b9\u5f0f", ""),
            light_source=selections.get("\u5149\u6e90", ""),
            image_feature=selections.get("\u753b\u9762\u7279\u5f81", ""),
            image_expression=selections.get("\u5f71\u50cf\u8868\u8fbe", ""),
            scene_description=self._scene_desc_edit.toPlainText().strip(),
            device_info=device_info,
            review_status="\u5ba1\u6838\u901a\u8fc7",
        )
        self._push_back_state(selections)
        self._approved_ids.add(manifest.case_id)
        self._awaiting_parent_confirmation = True
        self._sync_action_buttons()
        self.case_approved.emit(manifest, tag_result)

    def _push_back_state(self, selections: dict) -> None:
        self._back_history.append({
            "index": self._current_index,
            "selections": selections,
            "scene": self._scene_desc_edit.toPlainText().strip(),
        })

    def _handle_skip(self) -> None:
        """跳过当前 case，仅在非全自动模式下可用。"""
        if self._awaiting_parent_confirmation:
            return
        self._push_back_state({})
        self._advance()

    def _go_previous(self) -> None:
        """回到上一个 case，恢复之前状态（通过或跳过）。"""
        if not self._back_history or self._current_index == 0:
            return

        last = self._back_history.pop()
        self._current_index = last["index"]
        self._show_case(self._current_index)

        # 恢复场景描述
        if last["scene"]:
            self._scene_desc_edit.setPlainText(last["scene"])
        # 恢复字段选择
        for field, group in self._groups.items():
            target_value = last["selections"].get(field, "")
            if target_value:
                for button in group.buttons():
                    if button.text() == target_value:
                        button.setChecked(True)
                        break

    def _open_potplayer(self) -> None:
        """调用 PotPlayer 打开当前 normal 视频，便于人工复核。"""
        if not self._manifests or self._current_index >= len(self._manifests):
            return

        manifest = self._manifests[self._current_index]
        potplayer = self._config.get("potplayer_exe", "")
        dji_dir = Path(self._config.get("dji_nomal_dir", ""))
        video_path = dji_dir / manifest.vs_normal_path.name

        if not potplayer or not Path(potplayer).exists():
            QMessageBox.warning(
                self,
                "\u64ad\u653e\u5668\u672a\u914d\u7f6e",
                "\u8bf7\u5728 configs/config.json \u4e2d\u914d\u7f6e potplayer_exe \u8def\u5f84\u3002",
            )
            return

        subprocess.Popen([potplayer, str(video_path)])
