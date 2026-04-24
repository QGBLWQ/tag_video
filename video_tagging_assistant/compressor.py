import subprocess
from pathlib import Path
from typing import Dict, List

from video_tagging_assistant.models import CompressedArtifact, VideoTask


def build_ffmpeg_command(source: Path, target: Path, compression_config: Dict) -> List[str]:
    width = compression_config["width"]
    video_bitrate = compression_config["video_bitrate"]
    audio_bitrate = compression_config["audio_bitrate"]
    fps = compression_config["fps"]
    return [
        "ffmpeg",
        "-y",
        "-i",
        str(source),
        "-vf",
        f"scale={width}:-2",
        "-r",
        str(fps),
        "-b:v",
        video_bitrate,
        "-b:a",
        audio_bitrate,
        str(target),
    ]


def get_ffmpeg_log_path(log_dir: Path, source_video_path: Path) -> Path:
    compression_dir = Path(log_dir) / "compression"
    compression_dir.mkdir(parents=True, exist_ok=True)
    return compression_dir / f"{source_video_path.stem}.log"


def compress_video(task: VideoTask, output_dir: Path, compression_config: Dict) -> CompressedArtifact:
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"{task.source_video_path.stem}_proxy.mp4"
    command = build_ffmpeg_command(task.source_video_path, target, compression_config)

    logging_config = compression_config.get("logging", {})
    log_dir = logging_config.get("log_dir")
    capture_ffmpeg_output = logging_config.get("capture_ffmpeg_output", False)
    quiet_terminal = logging_config.get("quiet_terminal", False)

    stdout_target = None
    stderr_target = None
    log_handle = None
    try:
        if capture_ffmpeg_output and log_dir:
            log_path = get_ffmpeg_log_path(Path(log_dir), task.source_video_path)
            log_handle = open(log_path, "w", encoding="utf-8", errors="replace")
            stdout_target = log_handle
            stderr_target = subprocess.STDOUT
        elif quiet_terminal:
            stdout_target = subprocess.DEVNULL
            stderr_target = subprocess.DEVNULL

        subprocess.run(command, check=True, stdout=stdout_target, stderr=stderr_target)
    finally:
        if log_handle is not None:
            log_handle.close()

    return CompressedArtifact(
        source_video_path=task.source_video_path,
        compressed_video_path=target,
        size_bytes=target.stat().st_size if target.exists() else None,
        compression_profile=f"{compression_config['width']}px/{compression_config['video_bitrate']}",
    )
