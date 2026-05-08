from pathlib import Path
from typing import List

from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QApplication

from video_tagging_assistant.pipeline_models import CaseManifest
from video_tagging_assistant.rk_alignment_service import (
    RkCandidate,
    build_alignment_batch_state,
    scan_rk_candidates,
)

_APP = QApplication.instance() or QApplication([])

_CONFIG = {
    "ffprobe_exe": "ffprobe",
    "ffmpeg_exe": "ffmpeg",
}


def _make_manifest(
    tmp_path: Path,
    row_index: int = 3,
    case_id: str = "case_A_0001",
    video_stem: str = "",
) -> CaseManifest:
    video_name_prefix = video_stem or case_id
    return CaseManifest(
        case_id=case_id,
        row_index=row_index,
        created_date="20260508",
        mode="OV50H40_Action5Pro_DCG HDR",
        raw_path=Path(""),
        vs_normal_path=tmp_path / f"{video_name_prefix}_normal.mp4",
        vs_night_path=tmp_path / f"{video_name_prefix}_night.mp4",
        local_case_root=tmp_path / "local" / case_id,
        server_case_dir=tmp_path / "server" / case_id,
        remark="",
        labels={},
    )


def _make_candidates(tmp_path: Path, *names: str) -> List[RkCandidate]:
    candidates = []
    for name in names:
        folder_path = tmp_path / name
        folder_path.mkdir(parents=True, exist_ok=True)
        preview_path = folder_path / "preview.jpg"
        preview_path.write_bytes(b"preview")
        candidates.append(
            RkCandidate(
                folder_name=name,
                folder_path=folder_path,
                preview_path=preview_path,
                numeric_value=int(name.rstrip("x")),
                has_x_suffix=name.endswith("x"),
            )
        )
    return candidates


class _PreviewWorkerStub(QObject):
    preview_result = pyqtSignal(object)
    log_message = pyqtSignal(str)
    finished = pyqtSignal()

    created = []

    def __init__(self, config: dict, manifests: list, parent=None) -> None:
        super().__init__(parent)
        self.config = config
        self.manifests = list(manifests)
        self.started = False
        self.stopped = False
        self.wait_calls = []
        type(self).created.append(self)

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def wait(self, msecs=None) -> bool:
        self.wait_calls.append(msecs)
        return True


def _install_preview_worker_stub(monkeypatch, alignment_tab_module):
    _PreviewWorkerStub.created = []
    monkeypatch.setattr(alignment_tab_module, "AlignmentPreviewWorker", _PreviewWorkerStub)
    return _PreviewWorkerStub


def _write_preview_frames(output_dir: Path, count: int = 2) -> List[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    for index in range(count):
        frame_path = output_dir / f"frame_{index:03d}.jpg"
        pixmap = QPixmap(24, 24)
        pixmap.fill()
        pixmap.save(str(frame_path), "JPG")
        frames.append(frame_path)
    return frames


def _prepared_payload(tmp_path: Path, manifest: CaseManifest) -> dict:
    return {
        "row_index": manifest.row_index,
        "case_id": manifest.case_id,
        "status": "prepared",
        "normal_source": manifest.vs_normal_path,
        "night_source": manifest.vs_night_path,
        "normal_frames": _write_preview_frames(tmp_path / "prepared" / manifest.case_id / "normal"),
        "night_frames": _write_preview_frames(tmp_path / "prepared" / manifest.case_id / "night"),
    }


def _failed_payload(manifest: CaseManifest, error: str = "ffmpeg failed") -> dict:
    return {
        "row_index": manifest.row_index,
        "case_id": manifest.case_id,
        "status": "failed",
        "normal_source": manifest.vs_normal_path,
        "night_source": manifest.vs_night_path,
        "normal_exists": Path(manifest.vs_normal_path).exists(),
        "night_exists": Path(manifest.vs_night_path).exists(),
        "error": error,
    }


def test_alignment_tab_load_batch_starts_background_preparation(tmp_path: Path, monkeypatch):
    import video_tagging_assistant.gui.alignment_tab as alignment_tab_module

    monkeypatch.chdir(tmp_path)
    manifest = _make_manifest(tmp_path)
    candidates = _make_candidates(tmp_path / "rk-source", "31")
    state = build_alignment_batch_state(
        manifests=[manifest],
        rk_raw_by_row={manifest.row_index: ""},
        candidates=candidates,
        bad_directory_logs=[],
    )
    worker_cls = _install_preview_worker_stub(monkeypatch, alignment_tab_module)

    tab = alignment_tab_module.AlignmentTab(_CONFIG)
    tab.load_batch([manifest], tmp_path / "source.xlsx", tmp_path / "writeback.xlsx", state)

    assert len(worker_cls.created) == 1
    worker = worker_cls.created[0]
    assert worker.started
    assert worker.manifests == [manifest]

    tab.shutdown()
    assert worker.stopped


def test_alignment_tab_waits_for_old_worker_to_finish_before_starting_next_one(tmp_path: Path, monkeypatch):
    import video_tagging_assistant.gui.alignment_tab as alignment_tab_module

    class _DelayedStopWorker(QObject):
        preview_result = pyqtSignal(object)
        log_message = pyqtSignal(str)
        finished = pyqtSignal()

        created = []
        full_wait_completed = False

        def __init__(self, config: dict, manifests: list, parent=None) -> None:
            super().__init__(parent)
            self.manifests = list(manifests)
            self.started = False
            self.stopped = False
            self.wait_calls = []
            self.index = len(type(self).created)
            type(self).created.append(self)

        def start(self) -> None:
            if self.index == 1:
                assert type(self).full_wait_completed
            self.started = True

        def stop(self) -> None:
            self.stopped = True

        def wait(self, msecs=None) -> bool:
            self.wait_calls.append(msecs)
            if self.index == 0 and self.wait_calls == [2000]:
                return False
            if self.index == 0:
                type(self).full_wait_completed = True
            return True

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(alignment_tab_module, "AlignmentPreviewWorker", _DelayedStopWorker)
    manifest_one = _make_manifest(tmp_path, row_index=3, case_id="case_A_0001")
    manifest_two = _make_manifest(tmp_path, row_index=4, case_id="case_A_0002")
    candidates = _make_candidates(tmp_path / "rk-source", "31", "32")
    state_one = build_alignment_batch_state(
        manifests=[manifest_one],
        rk_raw_by_row={manifest_one.row_index: ""},
        candidates=candidates,
        bad_directory_logs=[],
    )
    state_two = build_alignment_batch_state(
        manifests=[manifest_two],
        rk_raw_by_row={manifest_two.row_index: ""},
        candidates=candidates,
        bad_directory_logs=[],
    )

    tab = alignment_tab_module.AlignmentTab(_CONFIG)
    tab.load_batch([manifest_one], tmp_path / "source.xlsx", tmp_path / "writeback.xlsx", state_one)
    tab.load_batch([manifest_two], tmp_path / "source.xlsx", tmp_path / "writeback.xlsx", state_two)

    assert len(_DelayedStopWorker.created) == 2
    assert _DelayedStopWorker.created[0].stopped
    assert _DelayedStopWorker.created[0].wait_calls == [2000, None]
    assert _DelayedStopWorker.created[1].started


def test_alignment_tab_loads_pending_cases_and_bad_logs(tmp_path: Path, monkeypatch):
    import video_tagging_assistant.gui.alignment_tab as alignment_tab_module

    monkeypatch.chdir(tmp_path)
    temp_root = tmp_path / "rk-source"
    (temp_root / "31").mkdir(parents=True)
    (temp_root / "31" / "preview.jpg").write_bytes(b"preview")
    (temp_root / "32x").mkdir(parents=True)
    manifest = _make_manifest(tmp_path)
    _, candidates, bad_logs = scan_rk_candidates(str(temp_root), "")
    state = build_alignment_batch_state(
        manifests=[manifest],
        rk_raw_by_row={manifest.row_index: ""},
        candidates=candidates,
        bad_directory_logs=bad_logs,
    )
    worker_cls = _install_preview_worker_stub(monkeypatch, alignment_tab_module)

    tab = alignment_tab_module.AlignmentTab(_CONFIG)
    tab.load_batch([manifest], tmp_path / "source.xlsx", tmp_path / "writeback.xlsx", state)

    assert tab._queue_list.count() == 1
    assert "missing preview" in tab._log_panel.toPlainText()
    assert "\u9884\u89c8\u51c6\u5907\u4e2d" in tab._rk_preview_label.text()
    assert tab._normal_preview_list.count() == 0
    assert tab._night_preview_list.count() == 0
    assert not tab._confirm_btn.isEnabled()

    worker_cls.created[0].preview_result.emit(_prepared_payload(tmp_path, manifest))

    assert tab._normal_preview_list.count() == 2
    assert tab._night_preview_list.count() == 2
    assert not tab._normal_preview_list.item(0).icon().isNull()
    assert not tab._night_preview_list.item(0).icon().isNull()


def test_alignment_tab_switches_candidates_with_next_and_previous(tmp_path: Path, monkeypatch):
    import video_tagging_assistant.gui.alignment_tab as alignment_tab_module

    monkeypatch.chdir(tmp_path)
    manifest = _make_manifest(tmp_path)
    candidates = _make_candidates(tmp_path / "rk-source", "31", "32")
    state = build_alignment_batch_state(
        manifests=[manifest],
        rk_raw_by_row={manifest.row_index: ""},
        candidates=candidates,
        bad_directory_logs=[],
    )
    _install_preview_worker_stub(monkeypatch, alignment_tab_module)

    tab = alignment_tab_module.AlignmentTab(_CONFIG)
    tab.load_batch([manifest], tmp_path / "source.xlsx", tmp_path / "writeback.xlsx", state)

    assert tab._candidate_label.text().startswith("31")

    tab._next_btn.click()
    assert tab._candidate_label.text().startswith("32")

    tab._prev_btn.click()
    assert tab._candidate_label.text().startswith("31")


def test_alignment_tab_confirm_stays_disabled_until_preview_ready(tmp_path: Path, monkeypatch):
    import video_tagging_assistant.gui.alignment_tab as alignment_tab_module

    monkeypatch.chdir(tmp_path)
    manifest = _make_manifest(tmp_path)
    candidates = _make_candidates(tmp_path / "rk-source", "31")
    state = build_alignment_batch_state(
        manifests=[manifest],
        rk_raw_by_row={manifest.row_index: ""},
        candidates=candidates,
        bad_directory_logs=[],
    )
    worker_cls = _install_preview_worker_stub(monkeypatch, alignment_tab_module)

    tab = alignment_tab_module.AlignmentTab(_CONFIG)
    tab.load_batch([manifest], tmp_path / "source.xlsx", tmp_path / "writeback.xlsx", state)

    assert not tab._confirm_btn.isEnabled()

    worker_cls.created[0].preview_result.emit(_failed_payload(manifest))
    assert not tab._confirm_btn.isEnabled()

    worker_cls.created[0].preview_result.emit(_prepared_payload(tmp_path, manifest))
    assert tab._confirm_btn.isEnabled()


def test_alignment_tab_confirm_writes_rk_raw_and_emits_state_change(tmp_path: Path, monkeypatch):
    import video_tagging_assistant.gui.alignment_tab as alignment_tab_module

    monkeypatch.chdir(tmp_path)
    manifest = _make_manifest(tmp_path)
    candidates = _make_candidates(tmp_path / "rk-source", "31", "32")
    state = build_alignment_batch_state(
        manifests=[manifest],
        rk_raw_by_row={manifest.row_index: ""},
        candidates=candidates,
        bad_directory_logs=[],
    )
    worker_cls = _install_preview_worker_stub(monkeypatch, alignment_tab_module)
    write_calls = []
    emitted = []

    def _write_rk_raw_value(workbook_path: Path, source_sheet: str, row_index: int, rk_raw_value: str) -> None:
        write_calls.append((row_index, rk_raw_value))

    monkeypatch.setattr(alignment_tab_module, "write_rk_raw_value", _write_rk_raw_value)

    tab = alignment_tab_module.AlignmentTab(_CONFIG)
    tab.alignment_state_changed.connect(lambda confirmed, total, blocked: emitted.append((confirmed, total, blocked)))
    tab.load_batch([manifest], tmp_path / "source.xlsx", tmp_path / "writeback.xlsx", state)
    worker_cls.created[0].preview_result.emit(_prepared_payload(tmp_path, manifest))

    tab._confirm_btn.click()

    assert write_calls == [(manifest.row_index, "31")]
    assert manifest.raw_path == Path("31")
    assert emitted[-1] == (1, 1, False)


def test_alignment_tab_load_rewrite_rows_displays_selected_aligned_case(tmp_path: Path, monkeypatch):
    import video_tagging_assistant.gui.alignment_tab as alignment_tab_module

    monkeypatch.chdir(tmp_path)
    manifest = _make_manifest(tmp_path)
    candidates = _make_candidates(tmp_path / "rk-source", "31", "32")
    state = build_alignment_batch_state(
        manifests=[manifest],
        rk_raw_by_row={manifest.row_index: "31"},
        candidates=candidates,
        bad_directory_logs=[],
    )
    _install_preview_worker_stub(monkeypatch, alignment_tab_module)

    tab = alignment_tab_module.AlignmentTab(_CONFIG)
    tab.load_batch([manifest], tmp_path / "source.xlsx", tmp_path / "writeback.xlsx", state)
    tab.load_rewrite_rows([manifest.row_index])

    assert manifest.row_index in tab._state.rewrite_row_indices
    assert tab._queue_list.count() == 1
    queue_text = tab._queue_list.item(0).text()
    assert manifest.case_id in queue_text
    assert f"row {manifest.row_index}" in queue_text
    assert "rewrite_aligned" in queue_text


def test_alignment_tab_rewrite_button_updates_service_state(tmp_path: Path, monkeypatch):
    import video_tagging_assistant.gui.alignment_tab as alignment_tab_module

    monkeypatch.chdir(tmp_path)
    manifest = _make_manifest(tmp_path)
    candidates = _make_candidates(tmp_path / "rk-source", "31", "32")
    state = build_alignment_batch_state(
        manifests=[manifest],
        rk_raw_by_row={manifest.row_index: "31"},
        candidates=candidates,
        bad_directory_logs=[],
    )
    _install_preview_worker_stub(monkeypatch, alignment_tab_module)

    tab = alignment_tab_module.AlignmentTab(_CONFIG)
    tab.load_batch([manifest], tmp_path / "source.xlsx", tmp_path / "writeback.xlsx", state)

    tab._rewrite_btn.click()

    assert manifest.row_index in tab._state.rewrite_row_indices
    assert tab._queue_list.count() == 1
    assert "rewrite_aligned" in tab._queue_list.item(0).text()


def test_alignment_tab_clear_reopens_case(tmp_path: Path, monkeypatch):
    import video_tagging_assistant.gui.alignment_tab as alignment_tab_module

    monkeypatch.chdir(tmp_path)
    manifest = _make_manifest(tmp_path)
    candidates = _make_candidates(tmp_path / "rk-source", "31", "32")
    state = build_alignment_batch_state(
        manifests=[manifest],
        rk_raw_by_row={manifest.row_index: "31"},
        candidates=candidates,
        bad_directory_logs=[],
    )
    _install_preview_worker_stub(monkeypatch, alignment_tab_module)
    clear_calls = []

    def _clear_rk_raw_value(workbook_path: Path, source_sheet: str, row_index: int) -> None:
        clear_calls.append(row_index)

    monkeypatch.setattr(alignment_tab_module, "clear_rk_raw_value", _clear_rk_raw_value)

    tab = alignment_tab_module.AlignmentTab(_CONFIG)
    tab.load_batch([manifest], tmp_path / "source.xlsx", tmp_path / "writeback.xlsx", state)
    tab._rewrite_btn.click()

    tab._clear_btn.click()

    assert clear_calls == [manifest.row_index]
    assert manifest.row_index in tab._state.rewrite_row_indices
    assert tab._queue_list.count() == 1
    assert "rewrite_pending" in tab._queue_list.item(0).text()


def test_alignment_tab_invalid_confirm_does_not_write_workbook(tmp_path: Path, monkeypatch):
    import video_tagging_assistant.gui.alignment_tab as alignment_tab_module

    monkeypatch.chdir(tmp_path)
    manifest_one = _make_manifest(tmp_path, row_index=3, case_id="case_A_0001")
    manifest_two = _make_manifest(tmp_path, row_index=4, case_id="case_A_0002")
    candidates = _make_candidates(tmp_path / "rk-source", "31", "32")
    state = build_alignment_batch_state(
        manifests=[manifest_one, manifest_two],
        rk_raw_by_row={
            manifest_one.row_index: "31",
            manifest_two.row_index: "32",
        },
        candidates=candidates,
        bad_directory_logs=[],
    )
    worker_cls = _install_preview_worker_stub(monkeypatch, alignment_tab_module)
    write_calls = []

    def _write_rk_raw_value(workbook_path: Path, source_sheet: str, row_index: int, rk_raw_value: str) -> None:
        write_calls.append((row_index, rk_raw_value))

    monkeypatch.setattr(alignment_tab_module, "write_rk_raw_value", _write_rk_raw_value)

    tab = alignment_tab_module.AlignmentTab(_CONFIG)
    tab.load_batch(
        [manifest_one, manifest_two],
        tmp_path / "source.xlsx",
        tmp_path / "writeback.xlsx",
        state,
    )
    worker_cls.created[0].preview_result.emit(_prepared_payload(tmp_path, manifest_one))
    tab.load_rewrite_rows([manifest_one.row_index])
    tab._next_btn.click()
    tab._confirm_btn.click()

    assert write_calls == []
    assert "confirm failed" in tab._log_panel.toPlainText()


def test_alignment_tab_row_selection_no_longer_invokes_preview_builder_directly(tmp_path: Path, monkeypatch):
    import video_tagging_assistant.alignment_preview as alignment_preview_module
    import video_tagging_assistant.gui.alignment_tab as alignment_tab_module

    monkeypatch.chdir(tmp_path)
    manifest_one = _make_manifest(tmp_path, row_index=3, case_id="case_A_0001")
    manifest_two = _make_manifest(tmp_path, row_index=4, case_id="case_A_0002")
    candidates = _make_candidates(tmp_path / "rk-source", "31", "32")
    state = build_alignment_batch_state(
        manifests=[manifest_one, manifest_two],
        rk_raw_by_row={manifest_one.row_index: "", manifest_two.row_index: ""},
        candidates=candidates,
        bad_directory_logs=[],
    )
    _install_preview_worker_stub(monkeypatch, alignment_tab_module)
    preview_calls = []

    def _record_preview_calls(*args, **kwargs):
        preview_calls.append((args, kwargs))
        return []

    monkeypatch.setattr(alignment_preview_module, "build_dji_preview_frames", _record_preview_calls)

    tab = alignment_tab_module.AlignmentTab(_CONFIG)
    tab.load_batch(
        [manifest_one, manifest_two],
        tmp_path / "source.xlsx",
        tmp_path / "writeback.xlsx",
        state,
    )
    tab._queue_list.setCurrentRow(1)
    tab._queue_list.setCurrentRow(0)

    assert preview_calls == []


def test_alignment_tab_preview_failure_logs_and_keeps_empty_dji_lists(tmp_path: Path, monkeypatch):
    import video_tagging_assistant.gui.alignment_tab as alignment_tab_module

    monkeypatch.chdir(tmp_path)
    manifest = _make_manifest(tmp_path)
    candidates = _make_candidates(tmp_path / "rk-source", "31")
    state = build_alignment_batch_state(
        manifests=[manifest],
        rk_raw_by_row={manifest.row_index: ""},
        candidates=candidates,
        bad_directory_logs=[],
    )
    worker_cls = _install_preview_worker_stub(monkeypatch, alignment_tab_module)
    write_calls = []

    def _write_rk_raw_value(workbook_path: Path, source_sheet: str, row_index: int, rk_raw_value: str) -> None:
        write_calls.append((row_index, rk_raw_value))

    monkeypatch.setattr(alignment_tab_module, "write_rk_raw_value", _write_rk_raw_value)

    tab = alignment_tab_module.AlignmentTab(_CONFIG)
    tab.load_batch([manifest], tmp_path / "source.xlsx", tmp_path / "writeback.xlsx", state)
    worker_cls.created[0].preview_result.emit(_failed_payload(manifest))
    tab._confirm_btn.click()

    assert tab._normal_preview_list.count() == 0
    assert tab._night_preview_list.count() == 0
    assert "\u9884\u89c8\u751f\u6210\u5931\u8d25" in tab._rk_preview_label.text()
    assert "preview generation failed" in tab._log_panel.toPlainText()
    assert not tab._confirm_btn.isEnabled()
    assert write_calls == []


def test_alignment_tab_preview_failure_logs_full_video_paths_and_existence(tmp_path: Path, monkeypatch):
    import video_tagging_assistant.gui.alignment_tab as alignment_tab_module

    monkeypatch.chdir(tmp_path)
    manifest = _make_manifest(tmp_path)
    manifest.vs_normal_path.write_bytes(b"video")
    candidates = _make_candidates(tmp_path / "rk-source", "31")
    state = build_alignment_batch_state(
        manifests=[manifest],
        rk_raw_by_row={manifest.row_index: ""},
        candidates=candidates,
        bad_directory_logs=[],
    )
    worker_cls = _install_preview_worker_stub(monkeypatch, alignment_tab_module)

    tab = alignment_tab_module.AlignmentTab(_CONFIG)
    tab.load_batch([manifest], tmp_path / "source.xlsx", tmp_path / "writeback.xlsx", state)
    worker_cls.created[0].preview_result.emit(_failed_payload(manifest))

    log_text = tab._log_panel.toPlainText()
    assert str(manifest.vs_normal_path) in log_text
    assert str(manifest.vs_night_path) in log_text
    assert "exists=True" in log_text
    assert "exists=False" in log_text
