"""代理视频生成阶段使用的 FFmpeg 命令拼装与压缩辅助模块。"""

import re
import subprocess
from pathlib import Path
from typing import Callable, Dict, List, Optional

from video_tagging_assistant.models import CompressedArtifact, VideoTask


def build_ffmpeg_command(source: Path, target: Path, compression_config: Dict) -> List[str]:
    """构造单个代理视频的 ffmpeg 命令行参数。"""
    width = compression_config["width"]
    video_bitrate = compression_config["video_bitrate"]
    audio_bitrate = compression_config["audio_bitrate"]
    fps = compression_config["fps"]
    return [
        "ffmpeg",
        "-y",
        "-i",
        str(source),
        "-t",
        "30",
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


def _parse_ffmpeg_time(time_str: str) -> float:
    """将 ffmpeg 时间字符串 HH:MM:SS.ms 转为秒数。"""
    m = re.match(r"(\d+):(\d+):(\d+)\.(\d+)", time_str)
    if not m:
        return 0.0
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + int(m.group(4)) / 100


def compress_video(
    task: VideoTask,
    output_dir: Path,
    compression_config: Dict,
    progress_cb: Optional[Callable[[int, str], None]] = None,
) -> CompressedArtifact:
    """将单个源视频压缩为适合模型消费的代理视频。已有缓存则跳过。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"{task.source_video_path.stem}_proxy.mp4"

    if target.exists() and target.stat().st_size > 0:
        if progress_cb:
            progress_cb(100, task.case_id)
        return CompressedArtifact(
            source_video_path=task.source_video_path,
            compressed_video_path=target,
            size_bytes=target.stat().st_size,
            compression_profile=f"{compression_config['width']}px/{compression_config['video_bitrate']}",
        )

    command = build_ffmpeg_command(task.source_video_path, target, compression_config)

    proc = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        encoding="utf-8",
        errors="replace",
    )

    duration_sec = 0.0
    try:
        for line in proc.stderr:
            if duration_sec == 0.0:
                dur_match = re.search(r"Duration:\s*(\d+:\d+:\d+\.\d+)", line)
                if dur_match:
                    duration_sec = _parse_ffmpeg_time(dur_match.group(1))
            time_match = re.search(r"time=(\d+:\d+:\d+\.\d+)", line)
            if time_match and duration_sec > 0 and progress_cb is not None:
                current_sec = _parse_ffmpeg_time(time_match.group(1))
                effective_dur = min(duration_sec, 30)
                pct = min(int(current_sec / effective_dur * 100), 99)
                progress_cb(pct, task.case_id)
    finally:
        proc.wait()

    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, command)

    if progress_cb is not None:
        progress_cb(100, task.case_id)

    return CompressedArtifact(
        source_video_path=task.source_video_path,
        compressed_video_path=target,
        size_bytes=target.stat().st_size if target.exists() else None,
        compression_profile=f"{compression_config['width']}px/{compression_config['video_bitrate']}",
    )
