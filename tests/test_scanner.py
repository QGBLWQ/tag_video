from pathlib import Path

from video_tagging_assistant.scanner import scan_videos


def test_scan_videos_discovers_supported_files(tmp_path: Path):
    (tmp_path / "case_a").mkdir()
    (tmp_path / "case_a" / "clip01.mp4").write_bytes(b"data")
    (tmp_path / "case_a" / "ignore.txt").write_text("x", encoding="utf-8")

    tasks = scan_videos(tmp_path)

    assert len(tasks) == 1
    assert tasks[0].file_name == "clip01.mp4"
    assert tasks[0].relative_path.as_posix() == "case_a/clip01.mp4"
    assert tasks[0].status == "pending"
