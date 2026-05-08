from pathlib import Path
from types import SimpleNamespace

import pytest

from video_tagging_assistant.alignment_preview import build_dji_preview_frames


def test_build_dji_preview_frames_uses_ffprobe_then_ffmpeg(tmp_path: Path, monkeypatch):
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
            return SimpleNamespace(stdout="12.0")
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
    )

    assert calls[0][0] == "ffprobe"
    assert calls[1][0] == "ffmpeg"
    assert "fps=2.0" in calls[1]
    assert calls[1][-1].endswith("frame_%03d.jpg")
    assert not (output_dir / "old.txt").exists()
    assert [frame.name for frame in frames] == ["frame_000.jpg", "frame_001.jpg", "frame_002.jpg"]
    assert sorted(path.name for path in output_dir.iterdir()) == ["frame_000.jpg", "frame_001.jpg", "frame_002.jpg"]

    def fake_run_invalid_duration(command, check, capture_output=False, text=False):
        calls.append(command)
        if command[0] == "ffprobe":
            return SimpleNamespace(stdout="")
        raise AssertionError("ffmpeg should not run when ffprobe duration is invalid")

    monkeypatch.setattr(
        "video_tagging_assistant.alignment_preview.subprocess.run",
        fake_run_invalid_duration,
    )

    with pytest.raises(ValueError, match="duration"):
        build_dji_preview_frames(
            video_path=video_path,
            output_dir=output_dir,
            ffprobe_exe="ffprobe",
            ffmpeg_exe="ffmpeg",
            frame_count=24,
        )
