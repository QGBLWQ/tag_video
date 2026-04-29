from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PyQt5.QtWidgets import QApplication

_APP = QApplication.instance() or QApplication([])

_CONFIG = {
    "workbook_path": "",
    "mode": "OV50H40_Action5Pro_DCG HDR",
    "intermediate_dir": "output/intermediate",
    "dji_nomal_dir": "/tmp/dji",
    "local_case_root": "/tmp/local",
    "server_upload_root": "/tmp/server",
    "cache_root": "artifacts/cache",
    "tagging_output_root": "artifacts/gui_pipeline",
    "provider": {"name": "mock", "model": "mock-model"},
    "prompt_template": {"system": "describe"},
}


def test_tagging_tab_instantiates():
    from video_tagging_assistant.gui.tagging_tab import TaggingTab
    tab = TaggingTab(_CONFIG)
    assert tab is not None


def test_tagging_tab_has_required_widgets():
    from video_tagging_assistant.gui.tagging_tab import TaggingTab
    tab = TaggingTab(_CONFIG)
    assert tab._workbook_edit is not None    # QLineEdit for workbook path
    assert tab._browse_btn is not None       # QPushButton
    assert tab._case_list is not None        # QListWidget
    assert tab._radio_rerun is not None      # QRadioButton: 重新标定
    assert tab._radio_cached is not None     # QRadioButton: 旧数据
    assert tab._start_btn is not None        # QPushButton: 开始
    assert tab._progress_bar is not None     # QProgressBar
    assert tab._current_file_label is not None  # QLabel
    assert tab._error_list is not None       # QListWidget for errors


def test_tagging_tab_loads_workbook_path_from_config():
    from video_tagging_assistant.gui.tagging_tab import TaggingTab
    config = {**_CONFIG, "workbook_path": "/some/path/records.xlsx"}
    tab = TaggingTab(config)
    assert tab._workbook_edit.text() == "/some/path/records.xlsx"


def test_tagging_tab_has_tagging_complete_signal():
    from video_tagging_assistant.gui.tagging_tab import TaggingTab
    tab = TaggingTab(_CONFIG)
    received = []
    tab.tagging_complete.connect(lambda results: received.append(results))
    # Signal exists and is connectable
    assert hasattr(tab, "tagging_complete")


def test_tagging_tab_load_cases_from_workbook(tmp_path: Path):
    """load_cases_from_workbook reads GetListRow and updates QListWidget."""
    import openpyxl
    from video_tagging_assistant.gui.tagging_tab import TaggingTab

    wb_path = tmp_path / "records.xlsx"
    wb = openpyxl.Workbook()
    # 创建记录 sheet
    cr = wb.active
    cr.title = "创建记录"
    cr.append(["序号", "文件夹名", "备注", "创建日期", "Raw存放路径",
               "VS_Nomal", "VS_Night", "安装方式", "运动模式"])
    cr.append([1, "case_A_0001", "", "20260422",
               "/mnt/117", "DJI_0001.MP4", "DJI_0021.MP4", "", ""])
    # 获取列表 sheet
    gl = wb.create_sheet("获取列表")
    gl.append(["日期", "20260422", "", ""])
    gl.append(["处理状态", "RK_raw", "Action5Pro_Nomal", "Action5Pro_Night"])
    gl.append(["R", "117", "DJI_0001.MP4", "DJI_0021.MP4"])
    wb.save(wb_path)

    config = {**_CONFIG, "workbook_path": str(wb_path)}
    tab = TaggingTab(config)
    tab._workbook_edit.setText(str(wb_path))
    tab._load_cases_from_workbook()

    assert tab._case_list.count() == 1
    assert "case_A_0001" in tab._case_list.item(0).text()
