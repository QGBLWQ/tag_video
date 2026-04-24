from pathlib import Path
from typing import List

from video_tagging_assistant.models import VideoTask

SUPPORTED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi"}


def scan_videos(root: Path) -> List[VideoTask]:
    root = Path(root)
    tasks: List[VideoTask] = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS:
            tasks.append(
                VideoTask(
                    source_video_path=path,
                    relative_path=path.relative_to(root),
                    file_name=path.name,
                )
            )
    return tasks
