"""DJI 对齐预览生成工具。

负责解析对齐页抽帧配置、校验视频流，并生成可缓存的预览帧序列。
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import List

DEFAULT_ALIGNMENT_PREVIEW_FRAME_COUNT = 30
DEFAULT_ALIGNMENT_PREVIEW_SKIP_FRAMES = 2
DEFAULT_ALIGNMENT_PREVIEW_WORKERS = 2
ALIGNMENT_PREVIEW_CACHE_METADATA_NAME = "alignment_preview_cache.json"


def resolve_alignment_preview_settings(config: Mapping[str, object] | None) -> tuple[int, int, int, list[str]]:
    """从配置中解析对齐预览抽帧参数，并返回规范化后的值与告警日志。"""
    settings = config if isinstance(config, Mapping) else {}
    logs: list[str] = []
    frame_count = _positive_int(
        settings.get("alignment_preview_frame_count"),
        DEFAULT_ALIGNMENT_PREVIEW_FRAME_COUNT,
        "alignment_preview_frame_count",
        logs,
    )
    skip_frames = _non_negative_int(
        settings.get("alignment_preview_skip_frames"),
        DEFAULT_ALIGNMENT_PREVIEW_SKIP_FRAMES,
        "alignment_preview_skip_frames",
        logs,
    )
    workers = _positive_int(
        settings.get("alignment_preview_workers"),
        DEFAULT_ALIGNMENT_PREVIEW_WORKERS,
        "alignment_preview_workers",
        logs,
    )
    return frame_count, skip_frames, workers, logs


def _positive_int(raw_value: object, default: int, key: str, logs: list[str]) -> int:
    """读取正整数配置项，不合法时回退默认值并记录日志。"""
    value = _coerce_int(raw_value)
    if value is None or value < 1:
        logs.append(f"{key}={raw_value!r} is invalid; using default {default}")
        return default
    return value


def _non_negative_int(raw_value: object, default: int, key: str, logs: list[str]) -> int:
    """读取非负整数配置项，不合法时回退默认值并记录日志。"""
    value = _coerce_int(raw_value)
    if value is None or value < 0:
        logs.append(f"{key}={raw_value!r} is invalid; using default {default}")
        return default
    return value


def _coerce_int(raw_value: object) -> int | None:
    """尽量把原始配置值转换成整数，失败时返回 None。"""
    if isinstance(raw_value, bool):
        return None
    if isinstance(raw_value, int):
        return raw_value
    if isinstance(raw_value, float):
        if raw_value.is_integer():
            return int(raw_value)
        return None
    if isinstance(raw_value, str):
        text = raw_value.strip()
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            return None
    return None


def _probe_video_stream(video_path: Path, ffprobe_exe: str) -> None:
    """用 ffprobe 校验视频流是否可读。"""
    result = subprocess.run(
        [
            ffprobe_exe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,width,height",
            "-of",
            "default=noprint_wrappers=1",
            str(video_path),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    stream_text = result.stdout.strip()
    if not stream_text:
        raise ValueError(f"invalid ffprobe stream output for {video_path}: {stream_text!r}")


def _alignment_preview_cache_metadata_path(output_dir: Path) -> Path:
    """返回预览缓存元数据文件路径。"""
    return output_dir / ALIGNMENT_PREVIEW_CACHE_METADATA_NAME


def _load_alignment_preview_cache_metadata(output_dir: Path) -> dict[str, int] | None:
    """读取预览缓存元数据，不可用时返回 None。"""
    metadata_path = _alignment_preview_cache_metadata_path(output_dir)
    if not metadata_path.exists():
        return None
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(metadata, dict):
        return None

    frame_count = _coerce_int(metadata.get("frame_count"))
    skip_frames = _coerce_int(metadata.get("skip_frames"))
    if frame_count is None or skip_frames is None:
        return None
    return {"frame_count": frame_count, "skip_frames": skip_frames}


def _write_alignment_preview_cache_metadata(output_dir: Path, frame_count: int, skip_frames: int) -> None:
    """写入当前抽帧参数，供后续命中缓存时校验。"""
    metadata_path = _alignment_preview_cache_metadata_path(output_dir)
    metadata_path.write_text(
        json.dumps({"frame_count": frame_count, "skip_frames": skip_frames}, ensure_ascii=False),
        encoding="utf-8",
    )


def _cached_alignment_preview_matches(output_dir: Path, frame_count: int, skip_frames: int) -> bool:
    """判断现有缓存是否与当前抽帧配置一致。"""
    metadata = _load_alignment_preview_cache_metadata(output_dir)
    if metadata is None:
        return False
    return metadata["frame_count"] == frame_count and metadata["skip_frames"] == skip_frames


def build_dji_preview_frames(
    video_path: Path,
    output_dir: Path,
    ffprobe_exe: str,
    ffmpeg_exe: str,
    frame_count: int = DEFAULT_ALIGNMENT_PREVIEW_FRAME_COUNT,
    skip_frames: int = DEFAULT_ALIGNMENT_PREVIEW_SKIP_FRAMES,
) -> List[Path]:
    """为单个 DJI 视频生成抽帧预览图，并复用可命中的缓存。"""
    if not Path(video_path).exists():
        raise FileNotFoundError(f"DJI preview source does not exist: {video_path}")

    cached_frames = sorted(output_dir.glob("frame_*.jpg"))
    if len(cached_frames) >= frame_count and _cached_alignment_preview_matches(output_dir, frame_count, skip_frames):
        return cached_frames[:frame_count]

    if output_dir.exists():
        for child in output_dir.iterdir():
            if child.is_file():
                child.unlink()
    output_dir.mkdir(parents=True, exist_ok=True)

    step = skip_frames + 1
    output_pattern = output_dir / "frame_%03d.jpg"
    subprocess.run(
        [
            ffmpeg_exe,
            "-y",
            "-t", "60",  # 只读前 60 秒，对齐无需全片
            "-i",
            str(video_path),
            "-vf",
            f"select=not(mod(n\\,{step}))",
            "-vsync",
            "vfr",
            "-frames:v",
            str(frame_count),
            str(output_pattern),
        ],
        check=True,
        timeout=30,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _write_alignment_preview_cache_metadata(output_dir, frame_count, skip_frames)
    return sorted(output_dir.glob("frame_*.jpg"))
