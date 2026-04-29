"""Tab2 审核：逐 case 展示 AI 打标结果，人工选择字段后写回工作簿。

字段分两类：
  单选字段（安装方式/运动模式/运镜方式/光源）：显示 tag_options 中全部候选项，不预选。
  多选字段（画面特征/影像表达）：只显示 AI 建议的候选项，人工从中选一个。

操作：
  通过：校验所有字段已选 → 构造 TagResult → emit case_approved → 显示下一 case
  跳过：不写回，不加入队列，直接跳到下一 case
"""
import subprocess
from pathlib import Path

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QButtonGroup,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from video_tagging_assistant.excel_workbook import TagResult

# 字段名 → TagResult 属性名映射
_FIELD_ATTR = {
    "安装方式": "install_method",
    "运动模式": "motion_mode",
    "运镜方式": "camera_move",
    "光源": "light_source",
    "画面特征": "image_feature",
    "影像表达": "image_expression",
}

_SINGLE_FIELDS = ["安装方式", "运动模式", "运镜方式", "光源"]
_MULTI_FIELDS = ["画面特征", "影像表达"]


class ReviewTab(QWidget):
    """Tab2：逐 case 审核面板。"""

    case_approved = pyqtSignal(object, object)  # (CaseManifest, TagResult)

    def __init__(self, config: dict, tag_options: dict, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._tag_options = tag_options
        self._manifests: list = []
        self._tagging_results: dict = {}
        self._current_index: int = 0
        self._groups: dict = {}
        self._setup_ui()

    def _setup_ui(self) -> None:
        outer = QVBoxLayout(self)

        # 进度 + case 信息行
        info_row = QHBoxLayout()
        self._progress_label = QLabel("0/0")
        self._case_label = QLabel("—")
        self._preview_btn = QPushButton("▶ PotPlayer 预览")
        info_row.addWidget(self._progress_label)
        info_row.addWidget(self._case_label, stretch=1)
        info_row.addWidget(self._preview_btn)
        outer.addLayout(info_row)

        # AI 原始返回（参考）
        self._ai_label = QLabel("AI 原始返回：（未加载）")
        self._ai_label.setWordWrap(True)
        outer.addWidget(self._ai_label)

        # 字段选择区域（可滚动）
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        fields_widget = QWidget()
        self._fields_layout = QFormLayout(fields_widget)
        scroll.setWidget(fields_widget)
        outer.addWidget(scroll, stretch=1)

        # 备注
        note_row = QHBoxLayout()
        note_row.addWidget(QLabel("备注:"))
        self._note_edit = QLineEdit()
        note_row.addWidget(self._note_edit, stretch=1)
        outer.addLayout(note_row)

        # 通过 / 跳过
        btn_row = QHBoxLayout()
        self._pass_btn = QPushButton("✓ 通过")
        self._skip_btn = QPushButton("→ 跳过")
        btn_row.addWidget(self._pass_btn)
        btn_row.addWidget(self._skip_btn)
        btn_row.addStretch()
        outer.addLayout(btn_row)

        self._preview_btn.clicked.connect(self._open_potplayer)
        self._pass_btn.clicked.connect(self._handle_pass)
        self._skip_btn.clicked.connect(self._handle_skip)

    def _rebuild_field_buttons(self, ai_result: dict) -> None:
        """根据当前 case 的 AI 结果重建字段选择区域。"""
        # 清空旧内容
        while self._fields_layout.rowCount() > 0:
            self._fields_layout.removeRow(0)
        self._groups.clear()

        # 单选字段：显示全部候选项
        for field in _SINGLE_FIELDS:
            options = self._tag_options.get(field, [])
            group = QButtonGroup(self)
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            for opt in options:
                rb = QRadioButton(opt)
                group.addButton(rb)
                row_layout.addWidget(rb)
            row_layout.addStretch()
            self._groups[field] = group
            self._fields_layout.addRow(f"{field}：", row_widget)

        # 多选字段：只显示 AI 建议的候选项
        for field in _MULTI_FIELDS:
            ai_suggestions = ai_result.get(field, [])
            if isinstance(ai_suggestions, str):
                ai_suggestions = [ai_suggestions]
            options = ai_suggestions if ai_suggestions else self._tag_options.get(field, [])
            group = QButtonGroup(self)
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            for opt in options:
                rb = QRadioButton(opt)
                group.addButton(rb)
                row_layout.addWidget(rb)
            row_layout.addStretch()
            self._groups[field] = group
            label = f"{field}（AI 建议，选一）："
            self._fields_layout.addRow(label, row_widget)

    def load_cases(self, cases: list, tagging_results: dict) -> None:
        """由 MainWindow 在打标完成后调用，初始化审核队列。"""
        self._manifests = cases
        self._tagging_results = tagging_results
        self._current_index = 0
        self._show_case(0)

    def _show_case(self, index: int) -> None:
        if not self._manifests or index >= len(self._manifests):
            self._progress_label.setText(f"{index}/{len(self._manifests)}")
            self._case_label.setText("全部审核完毕")
            return

        manifest = self._manifests[index]
        ai_result = self._tagging_results.get(manifest.case_id, {})

        self._progress_label.setText(f"{index + 1}/{len(self._manifests)}")
        self._case_label.setText(f"{manifest.case_id}   {manifest.vs_normal_path.name}")
        self._note_edit.clear()

        # 构建 AI 原始返回摘要
        lines = []
        for k, v in ai_result.items():
            if isinstance(v, list):
                lines.append(f"{k}: {', '.join(v)}")
            else:
                lines.append(f"{k}: {v}")
        self._ai_label.setText("AI 原始返回：" + " | ".join(lines))

        self._rebuild_field_buttons(ai_result)

    def _advance(self) -> None:
        self._current_index += 1
        self._show_case(self._current_index)

    def _collect_selections(self):
        """收集当前所有字段的选中值，任一字段未选则返回 None。"""
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
        selections = self._collect_selections()
        if selections is None:
            QMessageBox.warning(self, "字段未完整", "请选择所有字段后再点击通过。")
            return

        manifest = self._manifests[self._current_index]
        tag_result = TagResult(
            install_method=selections.get("安装方式", ""),
            motion_mode=selections.get("运动模式", ""),
            camera_move=selections.get("运镜方式", ""),
            light_source=selections.get("光源", ""),
            image_feature=selections.get("画面特征", ""),
            image_expression=selections.get("影像表达", ""),
            review_status="审核通过",
        )
        self.case_approved.emit(manifest, tag_result)
        self._advance()

    def _handle_skip(self) -> None:
        self._advance()

    def _open_potplayer(self) -> None:
        if not self._manifests or self._current_index >= len(self._manifests):
            return
        manifest = self._manifests[self._current_index]
        potplayer = self._config.get("potplayer_exe", "")
        dji_dir = Path(self._config.get("dji_nomal_dir", ""))
        video_path = dji_dir / manifest.vs_normal_path.name

        if not potplayer or not Path(potplayer).exists():
            QMessageBox.warning(
                self, "播放器未配置",
                "请在 configs/config.json 中配置 potplayer_exe 路径。"
            )
            return
        subprocess.Popen([potplayer, str(video_path)])
