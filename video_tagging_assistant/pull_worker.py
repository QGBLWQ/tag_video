import shutil
import subprocess
from pathlib import Path

from video_tagging_assistant.case_ingest_models import PullTask


def count_local_files(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for file_path in path.rglob("*") if file_path.is_file())


def merge_tmp_into_final(tmp_dir: Path, final_dir: Path) -> None:
    if not tmp_dir.exists():
        return
    if not final_dir.exists():
        tmp_dir.rename(final_dir)
        return

    for source in tmp_dir.rglob("*"):
        if not source.is_file():
            continue
        relative = source.relative_to(tmp_dir)
        target = final_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.move(str(source), str(target))

    shutil.rmtree(tmp_dir, ignore_errors=True)


def validate_pull_counts(remote_count: int, final_dir: Path) -> bool:
    return remote_count >= 0 and count_local_files(final_dir) == remote_count


def count_remote_files(device_path: str) -> int:
    result = subprocess.run(
        ["adb", "shell", "find", device_path, "-type", "f"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "adb shell find failed")
    return len([line for line in result.stdout.splitlines() if line.strip()])


def wait_for_device() -> None:
    subprocess.run(["adb", "wait-for-device"], check=True)


def _emit(progress_callback, payload):
    if progress_callback is not None:
        progress_callback(payload)


def run_resumable_pull(task: PullTask, progress_callback=None) -> Path:
    final_dir = Path(task.move_dst)
    tmp_dir = final_dir.parent / f"{final_dir.name}_tmp"
    _emit(progress_callback, {"case_id": task.case_id, "stage": "pulling", "message": "counting remote files"})
    remote_count = count_remote_files(task.device_path)

    if validate_pull_counts(remote_count, final_dir):
        _emit(
            progress_callback,
            {
                "case_id": task.case_id,
                "stage": "pull_done",
                "message": "already complete",
                "progress_current": remote_count,
                "progress_total": remote_count,
            },
        )
        return final_dir

    if tmp_dir.exists():
        shutil.rmtree(tmp_dir, ignore_errors=True)

    subprocess.run(["adb", "pull", task.device_path, str(tmp_dir)], check=True)
    merge_tmp_into_final(tmp_dir, final_dir)

    if not validate_pull_counts(remote_count, final_dir):
        raise RuntimeError(f"pull validation failed for {task.case_id}")

    _emit(
        progress_callback,
        {
            "case_id": task.case_id,
            "stage": "pull_done",
            "message": "pull complete",
            "progress_current": remote_count,
            "progress_total": remote_count,
        },
    )
    return final_dir
