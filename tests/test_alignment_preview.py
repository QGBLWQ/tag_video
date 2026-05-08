import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from video_tagging_assistant.alignment_preview import (
    build_dji_preview_frames,
    resolve_alignment_preview_settings,
)


def test_build_dji_preview_frames_uses_fixed_step_selection(tmp_path: Path, monkeypatch):
    video_path = tmp_path / "clip.mp4"
    output_dir = tmp_path / "preview_frames"
    video_path.write_bytes(b"video")
    output_dir.mkdir()
    (output_dir / "old.txt").write_text("stale", encoding="utf-8")

    calls = []

    def fake_run(command, check, capture_output=False, text=False):
        calls.append(command)
        executable = command[0]
        if executable == "ffprobe":
            return SimpleNamespace(stdout="codec_name=h264\nwidth=1920\nheight=1080\n")
        if executable == "ffmpeg":
            for frame_name in ("frame_002.jpg", "frame_000.jpg", "frame_001.jpg"):
                (output_dir / frame_name).write_bytes(b"jpeg")
            return SimpleNamespace(stdout="")
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr("video_tagging_assistant.alignment_preview.subprocess.run", fake_run)

    frames = build_dji_preview_frames(
        video_path=video_path,
        output_dir=output_dir,
        ffprobe_exe="ffprobe",
        ffmpeg_exe="ffmpeg",
        frame_count=24,
        skip_frames=2,
    )

    assert calls[0][0] == "ffprobe"
    assert calls[1][0] == "ffmpeg"
    assert calls[1][calls[1].index("-vf") + 1] == "select=not(mod(n\\,3))"
    assert "-vsync" in calls[1]
    assert calls[1][calls[1].index("-frames:v") + 1] == "24"
    assert calls[1][-1].endswith("frame_%03d.jpg")
    assert not (output_dir / "old.txt").exists()
    assert [frame.name for frame in frames] == ["frame_000.jpg", "frame_001.jpg", "frame_002.jpg"]
    assert sorted(path.name for path in output_dir.glob("frame_*.jpg")) == [
        "frame_000.jpg",
        "frame_001.jpg",
        "frame_002.jpg",
    ]
    assert (output_dir / "alignment_preview_cache.json").exists()

    def fake_run_invalid_stream(command, check, capture_output=False, text=False):
        calls.append(command)
        if command[0] == "ffprobe":
            return SimpleNamespace(stdout="")
        raise AssertionError("ffmpeg should not run when ffprobe stream output is invalid")

    monkeypatch.setattr(
        "video_tagging_assistant.alignment_preview.subprocess.run",
        fake_run_invalid_stream,
    )

    with pytest.raises(ValueError, match="stream output"):
        build_dji_preview_frames(
            video_path=video_path,
            output_dir=output_dir,
            ffprobe_exe="ffprobe",
            ffmpeg_exe="ffmpeg",
            frame_count=24,
            skip_frames=2,
        )


def test_resolve_alignment_preview_settings_falls_back_for_invalid_values():
    frame_count, skip_frames, workers, logs = resolve_alignment_preview_settings(
        {
            "alignment_preview_frame_count": "bad",
            "alignment_preview_skip_frames": -1,
            "alignment_preview_workers": 0,
        }
    )

    assert (frame_count, skip_frames, workers) == (30, 2, 2)
    assert any("alignment_preview_frame_count" in log for log in logs)
    assert any("alignment_preview_skip_frames" in log for log in logs)
    assert any("alignment_preview_workers" in log for log in logs)


def test_resolve_alignment_preview_settings_rejects_non_integral_numeric_values():
    frame_count, skip_frames, workers, logs = resolve_alignment_preview_settings(
        {
            "alignment_preview_frame_count": 2.9,
            "alignment_preview_skip_frames": 1.5,
            "alignment_preview_workers": "4",
        }
    )

    assert (frame_count, skip_frames, workers) == (30, 2, 4)
    assert any("alignment_preview_frame_count" in log for log in logs)
    assert any("alignment_preview_skip_frames" in log for log in logs)
    assert not any("alignment_preview_workers" in log for log in logs)


def test_resolve_alignment_preview_settings_uses_defaults_for_missing_values():
    frame_count, skip_frames, workers, logs = resolve_alignment_preview_settings({})

    assert (frame_count, skip_frames, workers) == (30, 2, 2)
    assert len(logs) == 3
    assert any("alignment_preview_frame_count" in log for log in logs)
    assert any("alignment_preview_skip_frames" in log for log in logs)
    assert any("alignment_preview_workers" in log for log in logs)


def test_build_dji_preview_frames_reuses_cached_frames_without_regeneration(tmp_path: Path, monkeypatch):
    video_path = tmp_path / "clip.mp4"
    output_dir = tmp_path / "preview_frames"
    video_path.write_bytes(b"video")
    output_dir.mkdir()
    cached_names = []
    for index in range(3):
        frame_name = "frame_{:03d}.jpg".format(index)
        (output_dir / frame_name).write_bytes(b"jpeg")
        cached_names.append(frame_name)
    (output_dir / "alignment_preview_cache.json").write_text(
        '{"frame_count": 3, "skip_frames": 2}',
        encoding="utf-8",
    )

    def fail_if_called(*args, **kwargs):
        raise AssertionError("subprocess.run should not be called when cache is complete")

    monkeypatch.setattr("video_tagging_assistant.alignment_preview.subprocess.run", fail_if_called)

    frames = build_dji_preview_frames(
        video_path=video_path,
        output_dir=output_dir,
        ffprobe_exe="ffprobe",
        ffmpeg_exe="ffmpeg",
        frame_count=3,
        skip_frames=2,
    )

    assert [frame.name for frame in frames] == cached_names
    assert (output_dir / "alignment_preview_cache.json").exists()


def test_build_dji_preview_frames_regenerates_when_cached_parameters_change(tmp_path: Path, monkeypatch):
    video_path = tmp_path / "clip.mp4"
    output_dir = tmp_path / "preview_frames"
    video_path.write_bytes(b"video")
    output_dir.mkdir()
    for index in range(3):
        (output_dir / f"frame_{index:03d}.jpg").write_bytes(b"jpeg")
    (output_dir / "alignment_preview_cache.json").write_text(
        '{"frame_count": 3, "skip_frames": 2}',
        encoding="utf-8",
    )
    (output_dir / "old.txt").write_text("stale", encoding="utf-8")

    calls = []

    def fake_run(command, check, capture_output=False, text=False):
        calls.append(command)
        if command[0] == "ffprobe":
            return SimpleNamespace(stdout="codec_name=h264\nwidth=1920\nheight=1080\n")
        if command[0] == "ffmpeg":
            for frame_name in ("frame_001.jpg", "frame_000.jpg", "frame_002.jpg"):
                (output_dir / frame_name).write_bytes(b"jpeg")
            return SimpleNamespace(stdout="")
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr("video_tagging_assistant.alignment_preview.subprocess.run", fake_run)

    frames = build_dji_preview_frames(
        video_path=video_path,
        output_dir=output_dir,
        ffprobe_exe="ffprobe",
        ffmpeg_exe="ffmpeg",
        frame_count=3,
        skip_frames=0,
    )

    assert calls[0][0] == "ffprobe"
    assert calls[1][0] == "ffmpeg"
    assert calls[1][calls[1].index("-vf") + 1] == "select=not(mod(n\\,1))"
    assert [frame.name for frame in frames] == ["frame_000.jpg", "frame_001.jpg", "frame_002.jpg"]
    assert not (output_dir / "old.txt").exists()
    assert (output_dir / "alignment_preview_cache.json").exists()


def test_build_dji_preview_frames_raises_clear_error_when_video_source_is_missing(tmp_path: Path, monkeypatch):
    video_path = tmp_path / "missing.mp4"
    output_dir = tmp_path / "preview_frames"

    def fail_if_called(*args, **kwargs):
        raise AssertionError("subprocess.run should not be called when the source video is missing")

    monkeypatch.setattr("video_tagging_assistant.alignment_preview.subprocess.run", fail_if_called)

    with pytest.raises(FileNotFoundError, match=re.escape(str(video_path))):
        build_dji_preview_frames(
            video_path=video_path,
            output_dir=output_dir,
            ffprobe_exe="ffprobe",
            ffmpeg_exe="ffmpeg",
            frame_count=3,
            skip_frames=2,
        )
