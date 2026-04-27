import shutil
from typing import Iterable

from video_tagging_assistant.case_ingest_models import CopyTask


def copy_declared_files(tasks: Iterable[CopyTask]) -> None:
    for task in tasks:
        if not task.source_path.exists():
            raise FileNotFoundError(str(task.source_path))
        task.target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(task.source_path, task.target_path)
        if not task.target_path.exists():
            raise RuntimeError(f"copy failed: {task.target_path}")
