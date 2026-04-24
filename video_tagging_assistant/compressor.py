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


def compress_video(task: VideoTask, output_dir: Path, compression_config: Dict) -> CompressedArtifact:
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"{task.source_video_path.stem}_proxy.mp4"
    command = build_ffmpeg_command(task.source_video_path, target, compression_config)
    subprocess.run(command, check=True)
    return CompressedArtifact(
        source_video_path=task.source_video_path,
        compressed_video_path=target,
        size_bytes=target.stat().st_size if target.exists() else None,
        compression_profile=f"{compression_config['width']}px/{compression_config['video_bitrate']}",
    )
