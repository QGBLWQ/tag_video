from pathlib import Path

from PyQt5.QtWidgets import QApplication

from video_tagging_assistant.pipeline_models import CaseManifest

_APP = QApplication.instance() or QApplication([])


def _make_manifest(tmp_path: Path, row_index: int = 3, case_id: str = "case_A_0001") -> CaseManifest:
    return CaseManifest(
        case_id=case_id,
        row_index=row_index,
        created_date="20260508",
        mode="OV50H40_Action5Pro_DCG HDR",
        raw_path=Path(""),
        vs_normal_path=tmp_path / f"{case_id}_normal.mp4",
        vs_night_path=tmp_path / f"{case_id}_night.mp4",
        local_case_root=tmp_path / "local" / case_id,
        server_case_dir=tmp_path / "server" / case_id,
        remark="",
        labels={},
    )


def test_alignment_preview_worker_emits_prepared_payload(tmp_path: Path, monkeypatch):
    import video_tagging_assistant.gui.alignment_preview_worker as worker_module

    manifest = _make_manifest(tmp_path)
    build_calls = []

    def _build_preview_frames(
        video_path: Path,
        output_dir: Path,
        ffprobe_exe: str,
        ffmpeg_exe: str,
        frame_count: int = 30,
        skip_frames: int = 2,
    ):
        output_dir.mkdir(parents=True, exist_ok=True)
        build_calls.append((video_path, output_dir, ffprobe_exe, ffmpeg_exe, frame_count, skip_frames))
        frame_path = output_dir / "frame_000.jpg"
        frame_path.write_bytes(b"frame")
        return [frame_path]

    monkeypatch.setattr(worker_module, "build_dji_preview_frames", _build_preview_frames)
    payloads = []
    worker = worker_module.AlignmentPreviewWorker(
        {
            "ffprobe_exe": "probe.exe",
            "ffmpeg_exe": "mpeg.exe",
            "alignment_preview_frame_count": 4,
            "alignment_preview_skip_frames": 1,
            "alignment_preview_workers": 1,
        },
        [manifest],
    )
    worker.preview_result.connect(payloads.append)

    worker.start()
    assert worker.wait(5000)

    assert len(payloads) == 1
    assert payloads[0]["row_index"] == manifest.row_index
    assert payloads[0]["case_id"] == manifest.case_id
    assert payloads[0]["status"] == "prepared"
    assert payloads[0]["normal_frames"][0].name == "frame_000.jpg"
    assert payloads[0]["night_frames"][0].name == "frame_000.jpg"
    assert build_calls == [
        (manifest.vs_normal_path, Path("artifacts") / "alignment_previews" / payloads[0]["cache_key"] / "normal", "probe.exe", "mpeg.exe", 4, 1),
        (manifest.vs_night_path, Path("artifacts") / "alignment_previews" / payloads[0]["cache_key"] / "night", "probe.exe", "mpeg.exe", 4, 1),
    ]


def test_alignment_preview_worker_stops_running_thread_with_start_and_wait(tmp_path: Path, monkeypatch):
    import video_tagging_assistant.gui.alignment_preview_worker as worker_module

    manifest = _make_manifest(tmp_path)
    build_calls = []

    def _build_preview_frames(
        video_path: Path,
        output_dir: Path,
        ffprobe_exe: str,
        ffmpeg_exe: str,
        frame_count: int = 30,
        skip_frames: int = 2,
    ):
        output_dir.mkdir(parents=True, exist_ok=True)
        build_calls.append(output_dir)
        frame_path = output_dir / "frame_000.jpg"
        frame_path.write_bytes(b"frame")
        return [frame_path]

    monkeypatch.setattr(worker_module, "build_dji_preview_frames", _build_preview_frames)
    payloads = []
    worker = worker_module.AlignmentPreviewWorker(_CONFIG, [manifest])
    worker.preview_result.connect(payloads.append)

    worker.start()
    assert worker.wait(5000)

    assert len(payloads) == 1
    assert payloads[0]["status"] == "prepared"
    assert len(build_calls) == 2


def test_alignment_preview_worker_emits_failed_payload(tmp_path: Path, monkeypatch):
    import video_tagging_assistant.gui.alignment_preview_worker as worker_module

    manifest = _make_manifest(tmp_path)
    manifest.vs_normal_path.write_bytes(b"video")

    def _raise_preview_error(
        video_path: Path,
        output_dir: Path,
        ffprobe_exe: str,
        ffmpeg_exe: str,
        frame_count: int = 30,
        skip_frames: int = 2,
    ):
        raise RuntimeError("ffmpeg failed")

    monkeypatch.setattr(worker_module, "build_dji_preview_frames", _raise_preview_error)
    payloads = []
    worker = worker_module.AlignmentPreviewWorker(_CONFIG, [manifest])
    worker.preview_result.connect(payloads.append)

    worker.run()

    assert len(payloads) == 1
    assert payloads[0]["row_index"] == manifest.row_index
    assert payloads[0]["case_id"] == manifest.case_id
    assert payloads[0]["status"] == "failed"
    assert payloads[0]["normal_source"] == manifest.vs_normal_path
    assert payloads[0]["night_source"] == manifest.vs_night_path
    assert payloads[0]["normal_exists"] is True
    assert payloads[0]["night_exists"] is False
    assert "ffmpeg failed" in payloads[0]["error"]


_CONFIG = {
    "ffprobe_exe": "ffprobe",
    "ffmpeg_exe": "ffmpeg",
}
