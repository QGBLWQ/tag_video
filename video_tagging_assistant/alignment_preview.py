import shutil
import subprocess
from pathlib import Path
from typing import List


def _video_duration_seconds(video_path: Path, ffprobe_exe: str) -> float:
    result = subprocess.run(
        [
            ffprobe_exe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return max(float(result.stdout.strip() or "0"), 0.1)


def build_dji_preview_frames(
    video_path: Path,
    output_dir: Path,
    ffprobe_exe: str,
    ffmpeg_exe: str,
    frame_count: int = 30,
) -> List[Path]:
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    duration = _video_duration_seconds(video_path, ffprobe_exe)
    fps_value = frame_count / duration
    output_pattern = output_dir / "frame_%03d.jpg"
    subprocess.run(
        [
            ffmpeg_exe,
            "-y",
            "-i",
            str(video_path),
            "-vf",
            f"fps={fps_value}",
            "-frames:v",
            str(frame_count),
            str(output_pattern),
        ],
        check=True,
    )
    return sorted(output_dir.glob("frame_*.jpg"))
