"""case-ingest 流程编排器。

负责串起单个 case 的 pull、move/copy、upload 三段流程，
供 GUI 执行队列和批处理入口复用。
"""

import shutil
import subprocess
import threading
from pathlib import Path
from queue import Queue
from typing import Callable, Iterable

from video_tagging_assistant.copy_worker import copy_declared_files
from video_tagging_assistant.pull_worker import (
    consume_temp_pull_source,
    run_resumable_pull,
    wait_for_device,
)
from video_tagging_assistant.upload_worker import upload_case_directory, upload_worker_loop


def _drain_upload_results(result_queue, upload_results):
    """消费上传结果队列，并累计本轮统计信息。"""
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
    """根据上传执行函数构造后台上传线程。"""
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
    """顺序执行 case-ingest 任务，并按需并发上传。

    参数:
        tasks: 要执行的 case 任务序列。
        pull_runner: pull 阶段执行函数。
        copy_runner: move/copy 阶段执行函数。
        upload_runner: 单 case 上传函数。
        upload_worker: 后台上传 worker 入口。
        wait_for_device_runner: 每个 case 开始前的设备就绪检查。
        skip_upload: 为 True 时跳过上传，只执行 pull 和 copy。
    """
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
    """把单个 case 的 RK 数据拉到本地临时目录。

    若 `temp_path` 中存在同名 RK 目录，则优先消费式 move 到目标位置，
    否则回退到 adb pull。
    """
    rk_suffix = manifest.raw_path.name
    dest = Path(config["local_case_root"]) / f"{manifest.case_id}_RK_raw_{rk_suffix}"
    temp_path = str(config.get("temp_path") or "").strip()
    if temp_path:
        temp_root = Path(temp_path)
        if temp_root.exists() and consume_temp_pull_source(temp_root, rk_suffix, dest):
            return

    dest.mkdir(parents=True, exist_ok=True)
    remote_path = f"{config['dut_root']}/{rk_suffix}/."
    subprocess.run(
        [config["adb_exe"], "pull", remote_path, str(dest)],
        check=True,
        timeout=int(config.get("adb_pull_timeout", 600)),
    )


def move_case(manifest, config: dict) -> None:
    """把 pull 下来的 RK 数据与 DJI 视频整理到最终 case 目录。"""
    rk_suffix = manifest.raw_path.name
    case_id = manifest.case_id
    local_root = Path(config["local_case_root"])
    mode = (manifest.mode or "").strip() or config["mode"]
    dest_dir = local_root / mode / manifest.created_date / case_id
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

    # 清理空的临时目录残留：local_root 下任何以 case_id 开头的空目录都删掉
    for entry in local_root.iterdir():
        if entry.is_dir() and entry.name.startswith(case_id) and not any(entry.iterdir()):
            try:
                entry.rmdir()
            except OSError:
                pass


def _copytree_with_progress(src: Path, dest: Path, progress_cb=None, workers: int = 8) -> None:
    """并发复制目录树，并通过回调上报文件级进度。"""
    import threading
    from concurrent.futures import ThreadPoolExecutor, as_completed

    files = [f for f in src.rglob("*") if f.is_file()]
    if not files:
        raise RuntimeError(f"upload 源目录为空或不存在: {src}")
    total = len(files)
    counter = [0]
    lock = threading.Lock()

    def _copy_one(file: Path):
        rel = file.relative_to(src)
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(file), str(target))
        with lock:
            counter[0] += 1
            n = counter[0]
        if progress_cb:
            progress_cb(n, total, file.name)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_copy_one, f) for f in files]
        for fut in as_completed(futures):
            fut.result()  # re-raise any exception


def upload_case(manifest, config: dict, progress_cb=None) -> None:
    """把本地 case 目录复制到服务器上传目录。"""
    local_root = Path(config["local_case_root"])
    server_root = Path(config["server_upload_root"])
    mode = (manifest.mode or "").strip() or config["mode"]
    workers = int(config.get("upload_workers", 8))
    src = local_root / mode / manifest.created_date / manifest.case_id
    dest = server_root / mode / manifest.created_date / manifest.case_id
    if dest.exists() and any(f.is_file() for f in dest.rglob("*")):
        return  # already uploaded
    dest.parent.mkdir(parents=True, exist_ok=True)
    _copytree_with_progress(src, dest, progress_cb, workers=workers)
