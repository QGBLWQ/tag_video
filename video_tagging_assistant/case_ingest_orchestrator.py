import shutil
import subprocess
import threading
from pathlib import Path
from queue import Queue
from typing import Callable, Iterable

from video_tagging_assistant.copy_worker import copy_declared_files
from video_tagging_assistant.pull_worker import run_resumable_pull, wait_for_device
from video_tagging_assistant.upload_worker import upload_case_directory, upload_worker_loop


def _drain_upload_results(result_queue, upload_results):
    uploaded = 0
    skipped = 0
    failed = 0

    while not result_queue.empty():
        result = result_queue.get()
        upload_results[result.case_id] = result
        if result.status == "uploaded":
            uploaded += 1
        elif result.status == "upload_skipped_exists":
            skipped += 1
        else:
            failed += 1

    return uploaded, skipped, failed


def _build_upload_thread(task_queue, result_queue, stop_event, upload_worker):
    if upload_worker is upload_worker_loop:
        return threading.Thread(
            target=upload_worker,
            args=(task_queue, result_queue, stop_event),
            daemon=True,
        )

    return threading.Thread(
        target=upload_worker,
        args=(task_queue, result_queue, stop_event),
        daemon=True,
    )


def run_case_ingest(
    tasks: Iterable,
    pull_runner=run_resumable_pull,
    copy_runner=copy_declared_files,
    upload_runner=upload_case_directory,
    upload_worker=upload_worker_loop,
    wait_for_device_runner: Callable[[], None] = wait_for_device,
    skip_upload=False,
):
    upload_results = {}
    processed = 0
    failed = 0
    uploaded = 0
    skipped = 0
    task_queue = Queue()
    result_queue = Queue()
    stop_event = threading.Event()
    worker_thread = None

    if not skip_upload:
        worker_thread = _build_upload_thread(task_queue, result_queue, stop_event, upload_worker)
        worker_thread.start()

    for case_task in tasks:
        try:
            wait_for_device_runner()
            pull_runner(case_task.pull_task)
            copy_runner(case_task.copy_tasks)
            case_task.status = "ready_to_upload"
            processed += 1

            if skip_upload:
                skipped += 1
                continue

            if upload_worker is upload_worker_loop:
                task_queue.put(case_task)
            else:
                task_queue.put((case_task, upload_runner))

            newly_uploaded, newly_skipped, newly_failed = _drain_upload_results(result_queue, upload_results)
            uploaded += newly_uploaded
            skipped += newly_skipped
            failed += newly_failed
        except Exception as exc:
            case_task.status = "failed"
            case_task.message = str(exc)
            failed += 1

    if not skip_upload:
        stop_event.set()
        task_queue.join()
        worker_thread.join()
        newly_uploaded, newly_skipped, newly_failed = _drain_upload_results(result_queue, upload_results)
        uploaded += newly_uploaded
        skipped += newly_skipped
        failed += newly_failed

    return {
        "processed": processed,
        "uploaded": uploaded,
        "skipped": skipped,
        "failed": failed,
        "upload_results": upload_results,
    }


def pull_case(manifest, config: dict) -> None:
    """执行单个 case 的 adb pull 操作。

    adb pull {dut_root}/{rk_suffix}/. {local_case_root}/{case_id}_RK_raw_{rk_suffix}
    用 /. 拉取目录内容而非目录本身，避免 adb 将远端目录嵌套进已存在的目标目录。
    """
    rk_suffix = manifest.raw_path.name
    dest = Path(config["local_case_root"]) / f"{manifest.case_id}_RK_raw_{rk_suffix}"
    dest.mkdir(parents=True, exist_ok=True)
    remote_path = f"{config['dut_root']}/{rk_suffix}/."
    subprocess.run(
        [config["adb_exe"], "pull", remote_path, str(dest)],
        check=True,
    )


def move_case(manifest, config: dict) -> None:
    """执行单个 case 的本地文件 move 操作。

    将以下文件/目录移入 {local_case_root}/{mode}/{created_date}/{case_id}/:
      - {case_id}_RK_raw_{rk_suffix}    (adb pull 临时目录)
      - {case_id}_{vs_normal.name}      (DJI 普通视频)
      - {case_id}_night_{vs_night.name} (DJI 夜间视频，可选)
    """
    rk_suffix = manifest.raw_path.name
    case_id = manifest.case_id
    local_root = Path(config["local_case_root"])
    dest_dir = local_root / config["mode"] / manifest.created_date / case_id
    dest_dir.mkdir(parents=True, exist_ok=True)

    shutil.move(
        str(local_root / f"{case_id}_RK_raw_{rk_suffix}"),
        str(dest_dir / f"{case_id}_RK_raw_{rk_suffix}"),
    )
    if manifest.vs_normal_path and str(manifest.vs_normal_path) != ".":
        if not manifest.vs_normal_path.exists():
            raise FileNotFoundError(
                f"DJI 普通视频不存在，请检查 dji_nomal_dir 配置: {manifest.vs_normal_path}"
            )
        shutil.copy2(
            str(manifest.vs_normal_path),
            str(dest_dir / f"{case_id}_{manifest.vs_normal_path.name}"),
        )
    if manifest.vs_night_path and str(manifest.vs_night_path) != ".":
        if manifest.vs_night_path.exists():
            shutil.copy2(
                str(manifest.vs_night_path),
                str(dest_dir / f"{case_id}_night_{manifest.vs_night_path.name}"),
            )


def _copytree_with_progress(src: Path, dest: Path, progress_cb=None) -> None:
    files = [f for f in src.rglob("*") if f.is_file()]
    if not files:
        raise RuntimeError(f"upload 源目录为空或不存在: {src}")
    total = len(files)
    for i, file in enumerate(files):
        rel = file.relative_to(src)
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(file), str(target))
        if progress_cb:
            progress_cb(i + 1, total, file.name)


def upload_case(manifest, config: dict, progress_cb=None) -> None:
    """执行单个 case 的服务器 upload 操作。

    将 {local_case_root}/{mode}/{created_date}/{case_id}
    整目录复制到 {server_upload_root}/{mode}/{created_date}/{case_id}
    目标已存在时抛出 RuntimeError。
    """
    local_root = Path(config["local_case_root"])
    server_root = Path(config["server_upload_root"])
    src = local_root / config["mode"] / manifest.created_date / manifest.case_id
    dest = server_root / config["mode"] / manifest.created_date / manifest.case_id
    if dest.exists() and any(f.is_file() for f in dest.rglob("*")):
        return  # already uploaded
    dest.parent.mkdir(parents=True, exist_ok=True)
    _copytree_with_progress(src, dest, progress_cb)
