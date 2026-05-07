from pathlib import Path

from PyQt5.QtWidgets import QApplication

_APP = QApplication.instance() or QApplication([])

_CONFIG = {
    "dji_nomal_dir": "/tmp/dji",
    "potplayer_exe": "/not/exist/potplayer.exe",
}


def _review_fields():
    from video_tagging_assistant.gui.review_tab import _MULTI_FIELDS, _SINGLE_FIELDS

    return list(_SINGLE_FIELDS), list(_MULTI_FIELDS)


def _make_tag_options():
    single_fields, multi_fields = _review_fields()
    tag_options = {}

    single_option_sets = [
        ["handheld", "wearable", "rig"],
        ["walk", "run"],
        ["pan", "tilt"],
        ["low", "normal"],
    ]
    multi_option_sets = [
        ["edge contrast", "reflection"],
        ["scenery", "architecture"],
    ]

    for field, options in zip(single_fields, single_option_sets):
        tag_options[field] = options
    for field, options in zip(multi_fields, multi_option_sets):
        tag_options[field] = options
    return tag_options


_TAG_OPTIONS = _make_tag_options()


def _make_ai_result(single_indexes=None, multi_indexes=None, scene_description=""):
    single_fields, multi_fields = _review_fields()
    single_indexes = single_indexes or [0, 0, 0, 1]
    multi_indexes = multi_indexes or [0, 0]
    ai_result = {"\u753b\u9762\u63cf\u8ff0": scene_description}

    for field, option_index in zip(single_fields, single_indexes):
        ai_result[field] = _TAG_OPTIONS[field][option_index]
    for field, option_index in zip(multi_fields, multi_indexes):
        ai_result[field] = [_TAG_OPTIONS[field][option_index]]
    return ai_result


def _make_manifest(case_id: str = "case_A_0078"):
    from video_tagging_assistant.pipeline_models import CaseManifest

    return CaseManifest(
        case_id=case_id,
        row_index=2,
        created_date="20260422",
        mode="OV50H40_Action5Pro_DCG HDR",
        raw_path=Path("/mnt/117"),
        vs_normal_path=Path("DJI_0001.MP4"),
        vs_night_path=Path("DJI_0021.MP4"),
        local_case_root=Path("/tmp/cases"),
        server_case_dir=Path("/tmp/server/case"),
        remark="",
    )


def _select_first_option_per_group(tab) -> None:
    for group in tab._groups.values():
        buttons = group.buttons()
        if buttons:
            buttons[0].setChecked(True)


def test_review_tab_instantiates():
    from video_tagging_assistant.gui.review_tab import ReviewTab

    tab = ReviewTab(_CONFIG, _TAG_OPTIONS)
    assert tab is not None


def test_review_tab_has_case_approved_signal():
    from video_tagging_assistant.gui.review_tab import ReviewTab

    tab = ReviewTab(_CONFIG, _TAG_OPTIONS)
    assert hasattr(tab, "case_approved")


def test_review_tab_load_cases_shows_first_case():
    from video_tagging_assistant.gui.review_tab import ReviewTab

    tab = ReviewTab(_CONFIG, _TAG_OPTIONS)
    manifests = [_make_manifest("case_A_0001"), _make_manifest("case_A_0002")]
    tagging_results = {
        "case_A_0001": _make_ai_result(single_indexes=[0, 0, 0, 1], multi_indexes=[0, 0]),
        "case_A_0002": _make_ai_result(single_indexes=[1, 1, 1, 0], multi_indexes=[1, 1]),
    }

    tab.load_cases(manifests, tagging_results)

    assert "1" in tab._progress_label.text()
    assert "2" in tab._progress_label.text()
    assert "case_A_0001" in tab._case_label.text()


def test_review_tab_approve_without_all_fields_shows_error():
    from unittest.mock import patch

    from video_tagging_assistant.gui.review_tab import ReviewTab

    tab = ReviewTab(_CONFIG, _TAG_OPTIONS)
    manifests = [_make_manifest("case_A_0001")]
    tab.load_cases(manifests, {"case_A_0001": _make_ai_result()})

    approved_signals = []
    tab.case_approved.connect(lambda m, t: approved_signals.append((m, t)))

    with patch("PyQt5.QtWidgets.QMessageBox.warning") as mock_warn:
        tab._pass_btn.click()

    mock_warn.assert_called_once()
    assert approved_signals == []


def test_review_tab_approve_with_all_fields_emits_case_approved():
    from video_tagging_assistant.excel_workbook import TagResult
    from video_tagging_assistant.gui.review_tab import ReviewTab

    tab = ReviewTab(_CONFIG, _TAG_OPTIONS)
    manifests = [_make_manifest("case_A_0001")]
    tab.load_cases(manifests, {"case_A_0001": _make_ai_result()})

    approved_signals = []
    tab.case_approved.connect(lambda m, t: approved_signals.append((m, t)))
    _select_first_option_per_group(tab)

    tab._pass_btn.click()

    assert len(approved_signals) == 1
    manifest, tag_result = approved_signals[0]
    assert manifest.case_id == "case_A_0001"
    assert isinstance(tag_result, TagResult)
    assert tag_result.review_status == "\u5ba1\u6838\u901a\u8fc7"


def test_review_tab_load_cases_auto_mode_locks_device_and_disables_skip():
    from video_tagging_assistant.gui.review_tab import ReviewTab

    tab = ReviewTab(_CONFIG, _TAG_OPTIONS)
    manifest = _make_manifest("case_A_0001")
    tagging_results = {"case_A_0001": _make_ai_result()}
    dut_devices = [
        {
            "\u8bbe\u5907\u7f16\u53f7": "DUT-02",
            "\u6a21\u7ec4\u578b\u53f7": "OTHER",
            "\u91c7\u96c6\u6a21\u5f0f": "NORMAL",
        }
    ]
    locked_device = {
        "\u8bbe\u5907\u7f16\u53f7": "DUT-01",
        "\u6a21\u7ec4\u578b\u53f7": "OV50",
        "\u91c7\u96c6\u6a21\u5f0f": "HDR",
    }

    tab.load_cases(
        [manifest],
        tagging_results,
        dut_devices=dut_devices,
        auto_mode=True,
        locked_device=locked_device,
    )

    assert tab._device_combo.count() == 1
    assert tab._device_combo.currentData() == locked_device
    assert not tab._device_combo.isEnabled()
    assert not tab._skip_btn.isEnabled()


def test_review_tab_normal_mode_preserves_legacy_device_labels_and_keeps_combo_on_empty_list():
    from video_tagging_assistant.gui.review_tab import ReviewTab

    tab = ReviewTab(_CONFIG, _TAG_OPTIONS)
    manifests = [_make_manifest("case_A_0001")]
    tagging_results = {"case_A_0001": _make_ai_result()}
    dut_devices = [
        {
            "\u8bbe\u5907\u7f16\u53f7": "DUT-01",
            "\u6a21\u7ec4\u578b\u53f7": "OV50",
            "\u91c7\u96c6\u6a21\u5f0f": "HDR",
        },
        {
            "\u8bbe\u5907\u7f16\u53f7": "DUT-02",
            "\u6a21\u7ec4\u578b\u53f7": "OTHER",
            "\u91c7\u96c6\u6a21\u5f0f": "NORMAL",
        },
    ]

    tab.load_cases(manifests, tagging_results, dut_devices=dut_devices)

    assert tab._device_combo.count() == 2
    assert tab._device_combo.itemText(0) == "DUT-01"
    assert tab._device_combo.itemText(1) == "DUT-02"

    tab._device_combo.setCurrentIndex(1)
    tab.load_cases(manifests, tagging_results, dut_devices=[])

    assert tab._device_combo.count() == 2
    assert tab._device_combo.currentText() == "DUT-02"
    assert tab._device_combo.itemData(1) == dut_devices[1]


def test_review_tab_pass_emits_approval_without_advancing_until_parent_confirms():
    from video_tagging_assistant.gui.review_tab import ReviewTab

    tab = ReviewTab(_CONFIG, _TAG_OPTIONS)
    manifests = [_make_manifest("case_A_0001"), _make_manifest("case_A_0002")]
    tagging_results = {
        "case_A_0001": _make_ai_result(single_indexes=[0, 0, 0, 1], multi_indexes=[0, 0]),
        "case_A_0002": _make_ai_result(single_indexes=[1, 1, 1, 0], multi_indexes=[1, 1]),
    }

    approved_signals = []
    tab.load_cases(manifests, tagging_results)
    tab.case_approved.connect(lambda m, t: approved_signals.append((m, t)))
    _select_first_option_per_group(tab)

    tab._pass_btn.click()

    assert len(approved_signals) == 1
    assert tab._current_index == 0
    assert "case_A_0001" in tab._case_label.text()

    tab.advance_after_approval()

    assert tab._current_index == 1
    assert "case_A_0002" in tab._case_label.text()


def test_review_tab_pass_ignores_duplicate_clicks_while_awaiting_parent_confirmation():
    from video_tagging_assistant.gui.review_tab import ReviewTab

    tab = ReviewTab(_CONFIG, _TAG_OPTIONS)
    manifests = [_make_manifest("case_A_0001")]
    tagging_results = {"case_A_0001": _make_ai_result()}

    approved_signals = []
    tab.load_cases(manifests, tagging_results)
    tab.case_approved.connect(lambda m, t: approved_signals.append((m, t)))
    _select_first_option_per_group(tab)

    tab._pass_btn.click()
    tab._pass_btn.click()

    assert len(approved_signals) == 1
    assert tab._current_index == 0
    assert not tab._pass_btn.isEnabled()
    assert not tab._skip_btn.isEnabled()


def test_review_tab_advance_after_approval_requires_single_pending_approval():
    from video_tagging_assistant.gui.review_tab import ReviewTab

    tab = ReviewTab(_CONFIG, _TAG_OPTIONS)
    manifests = [_make_manifest("case_A_0001"), _make_manifest("case_A_0002")]
    tagging_results = {
        "case_A_0001": _make_ai_result(single_indexes=[0, 0, 0, 1], multi_indexes=[0, 0]),
        "case_A_0002": _make_ai_result(single_indexes=[1, 1, 1, 0], multi_indexes=[1, 1]),
    }

    tab.load_cases(manifests, tagging_results)
    tab.advance_after_approval()

    assert tab._current_index == 0
    assert "case_A_0001" in tab._case_label.text()

    _select_first_option_per_group(tab)
    tab._pass_btn.click()
    tab.advance_after_approval()

    assert tab._current_index == 1
    assert "case_A_0002" in tab._case_label.text()
    assert tab._pass_btn.isEnabled()
    assert tab._skip_btn.isEnabled()

    tab.advance_after_approval()

    assert tab._current_index == 1
    assert "case_A_0002" in tab._case_label.text()
