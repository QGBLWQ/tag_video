from pathlib import Path

from video_tagging_assistant.compressor import get_ffmpeg_log_path


def test_get_ffmpeg_log_path_uses_log_directory(tmp_path: Path):
    log_path = get_ffmpeg_log_path(tmp_path / "logs", Path("videos/clip01.mp4"))
    assert log_path.name == "clip01.log"
    assert log_path.parent == tmp_path / "logs" / "compression"
