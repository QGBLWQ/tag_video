from pathlib import Path
from types import SimpleNamespace
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
    assert "DJI_0001.MP4" in tab._case_list.item(0).text()


def test_tagging_tab_exposes_auto_mode_controls():
    from video_tagging_assistant.gui.tagging_tab import TaggingTab

    tab = TaggingTab(_CONFIG)

    assert tab._auto_mode_check is not None
    assert tab._device_combo is not None
    assert not tab._auto_mode_check.isChecked()
    assert not tab._device_combo.isEnabled()
    assert tab.auto_execution_enabled() is False
    assert tab.selected_device_info() == {}


def test_load_cases_from_workbook_also_loads_dut_devices(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import video_tagging_assistant.gui.tagging_tab as tagging_tab_module

    manifests = [
        SimpleNamespace(case_id="case_A_0001", vs_normal_path=Path("DJI_0001.MP4")),
    ]
    devices = [
        {"设备编号": "DUT-001", "模组型号": "Module-A", "采集模式": "Mode-A"},
        {"设备编号": "DUT-002", "模组型号": "Module-B", "采集模式": "Mode-B"},
    ]
    workbook_path = tmp_path / "records.xlsx"
    workbook_path.write_text("", encoding="utf-8")

    monkeypatch.setattr(tagging_tab_module, "get_next_case_sequence", lambda *args, **kwargs: 1)
    monkeypatch.setattr(tagging_tab_module, "load_get_list_manifests", lambda **kwargs: manifests)
    monkeypatch.setattr(tagging_tab_module, "load_dut_info", lambda path: devices, raising=False)

    tab = tagging_tab_module.TaggingTab(_CONFIG)
    tab._workbook_edit.setText(str(workbook_path))
    tab._load_cases_from_workbook()

    assert tab._dut_devices == devices
    assert tab._device_combo.count() == len(devices)
    assert tab._device_combo.itemData(0) == devices[0]
    assert tab._device_combo.itemData(1) == devices[1]
    assert not tab._device_combo.isEnabled()


def test_start_tagging_requires_selected_device_when_auto_mode_enabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import video_tagging_assistant.gui.tagging_tab as tagging_tab_module

    manifests = [
        SimpleNamespace(case_id="case_A_0001", vs_normal_path=Path("DJI_0001.MP4")),
    ]
    devices = [
        {"设备编号": "DUT-001", "模组型号": "Module-A", "采集模式": "Mode-A"},
    ]
    workbook_path = tmp_path / "records.xlsx"
    workbook_path.write_text("", encoding="utf-8")

    monkeypatch.setattr(tagging_tab_module, "get_next_case_sequence", lambda *args, **kwargs: 1)
    monkeypatch.setattr(tagging_tab_module, "load_get_list_manifests", lambda **kwargs: manifests)
    monkeypatch.setattr(tagging_tab_module, "load_dut_info", lambda path: devices, raising=False)

    tab = tagging_tab_module.TaggingTab(_CONFIG)
    tab._workbook_edit.setText(str(workbook_path))
    tab._load_cases_from_workbook()
    tab._auto_mode_check.setChecked(True)

    assert tab._device_combo.currentIndex() == -1

    tab._start_tagging()

    assert tab._worker is None
    assert tab._error_list.count() == 1
    assert tab._start_btn.isEnabled()


@pytest.mark.parametrize(
    "device_info",
    [
        {"设备编号": "DUT-001", "模组型号": "", "采集模式": "Mode-A"},
        {"设备编号": "DUT-001", "模组型号": "Module-A", "采集模式": ""},
    ],
)
def test_start_tagging_rejects_selected_device_missing_required_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    device_info: dict,
):
    import video_tagging_assistant.gui.tagging_tab as tagging_tab_module

    manifests = [
        SimpleNamespace(case_id="case_A_0001", vs_normal_path=Path("DJI_0001.MP4")),
    ]
    workbook_path = tmp_path / "records.xlsx"
    workbook_path.write_text("", encoding="utf-8")

    monkeypatch.setattr(tagging_tab_module, "get_next_case_sequence", lambda *args, **kwargs: 1)
    monkeypatch.setattr(tagging_tab_module, "load_get_list_manifests", lambda **kwargs: manifests)
    monkeypatch.setattr(tagging_tab_module, "load_dut_info", lambda path: [device_info], raising=False)

    tab = tagging_tab_module.TaggingTab(_CONFIG)
    tab._workbook_edit.setText(str(workbook_path))
    tab._load_cases_from_workbook()
    tab._auto_mode_check.setChecked(True)
    tab._device_combo.setCurrentIndex(0)

    tab._start_tagging()

    assert tab._worker is None
    assert tab._error_list.count() == 1
    assert tab._start_btn.isEnabled()
