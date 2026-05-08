"""可恢复 RK 拉取与 temp_path 消费逻辑的底层辅助模块。"""

import shutil
import subprocess
from pathlib import Path

from video_tagging_assistant.case_ingest_models import PullTask


def count_local_files(path: Path) -> int:
    """递归统计本地目录下的文件数。"""
    if not path.exists():
        return 0
    return sum(1 for file_path in path.rglob("*") if file_path.is_file())


def relative_file_set(path: Path) -> set:
    """返回目录下所有文件的相对路径集合。"""
    if not path.exists():
        return set()
    return {file_path.relative_to(path) for file_path in path.rglob("*") if file_path.is_file()}


def merge_tmp_into_final(tmp_dir: Path, final_dir: Path) -> None:
    """将新拉取的临时目录合并进最终目录。"""
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
    """通过本地文件数与远端文件数对比校验拉取结果。"""
    return remote_count >= 0 and count_local_files(final_dir) == remote_count


def consume_temp_pull_source(temp_root: Path, rk_suffix: str, final_dir: Path) -> bool:
    """优先消费人工准备好的 temp_path RK 目录，而不是走 adb pull。"""
    candidate = temp_root / rk_suffix
    if not candidate.exists():
        return False

    source_files = relative_file_set(candidate)
    if not source_files:
        return False

    if not final_dir.exists():
        final_dir.parent.mkdir(parents=True, exist_ok=True)
        candidate.rename(final_dir)
        if relative_file_set(final_dir) != source_files:
            final_dir.rename(candidate)
            raise RuntimeError(f"temp_path validation failed for rk_suffix={rk_suffix}")
        return True

    if relative_file_set(final_dir) == source_files:
        return True

    missing_files = source_files - relative_file_set(final_dir)
    for relative_path in missing_files:
        source = candidate / relative_path
        target = final_dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    if relative_file_set(final_dir) != source_files:
        raise RuntimeError(f"temp_path validation failed for rk_suffix={rk_suffix}")

    shutil.rmtree(candidate, ignore_errors=True)
    return True


def count_remote_files(device_path: str) -> int:
    """通过 `adb shell find` 统计设备侧目录下的文件数。"""
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
    """阻塞等待，直到 adb 检测到设备可用。"""
    subprocess.run(["adb", "wait-for-device"], check=True, timeout=120)


def _emit(progress_callback, payload):
    """安全调用进度回调，供 pull 相关辅助函数复用。"""
    if progress_callback is not None:
        progress_callback(payload)


def run_resumable_pull(task: PullTask, progress_callback=None) -> Path:
    """执行可恢复的拉取流程，并带远端文件数校验。

    Args:
        task: 描述设备源路径与本地目标路径的 `PullTask`。
        progress_callback: 可选进度回调，接收结构化进度字典。

    Returns:
        已完成校验的最终本地目录路径。
    """
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

    subprocess.run(["adb", "pull", task.device_path, str(tmp_dir)], check=True, timeout=600)
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
