"""case-ingest 流程编排器。

负责串起单个 case 的 pull、move/copy、upload 三段流程，
供 GUI 执行队列和批处理入口复用。
"""

import shutil
import subprocess
import threading
import time
from pathlib import Path
from queue import Queue
from typing import Callable, Iterable

_ADB_ERROR_MAP = {
    "device not found": "设备未连接，请检查 USB 线缆并确认 adb devices 可见",
    "no devices": "设备未连接，请检查 USB 线缆并确认 adb devices 可见",
    "permission denied": "权限不足，请在设备端执行 adb root",
    "no such file or directory": "远端路径不存在，请检查 dut_root 配置和 RK 目录名",
    "timeout": "设备响应超时，请重启 adb server（adb kill-server）",
    "timed out": "设备响应超时，请重启 adb server（adb kill-server）",
    "offline": "设备离线，请重新插拔 USB 并等待设备上线",
}


def _translate_adb_error_text(raw: str) -> str:
    """中文翻译 adb 错误文本。"""
    text = raw.lower()
    for keyword, chinese in _ADB_ERROR_MAP.items():
        if keyword in text:
            return f"{chinese}（原始错误: {raw.strip()}）"
    return f"adb 命令失败: {raw.strip()}"


def _translate_adb_error(error: subprocess.CalledProcessError) -> str:
    stderr = (error.stderr or "").lower()
    if isinstance(stderr, bytes):
        stderr = stderr.decode("utf-8", errors="replace")
    for keyword, chinese in _ADB_ERROR_MAP.items():
        if keyword in stderr:
            return f"{chinese}（原始错误: {stderr.strip()}）"
    return f"adb 命令失败: {stderr.strip() or str(error)}"


def _adb_list_files(adb_exe: str, remote_dir: str, timeout: int = 30) -> dict:
    """通过 adb shell ls -la 获取远端目录文件列表，返回 {filename: size_bytes}。"""
    result = subprocess.run(
        [adb_exe, "shell", "ls", "-la", remote_dir],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode, [adb_exe, "shell", "ls", "-la", remote_dir],
            output=result.stdout, stderr=result.stderr,
        )
    files = {}
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("total ") or line.startswith("d"):
            continue
        # ls -la 输出: -rw-rw-rw- 1 root root  12345678 2025-04-29 10:00 filename
        parts = line.split()
        if len(parts) >= 5:
            try:
                size = int(parts[4])
            except ValueError:
                continue
            name = parts[-1]
            if name not in (".", ".."):
                files[name] = size
    return files

from video_tagging_assistant.copy_worker import copy_declared_files
from video_tagging_assistant.pull_worker import (
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


def pull_case(manifest, config: dict, progress_cb=None) -> None:
    """增量 pull：对比远端/本地文件，有缺失时用 adb exec-out + tar 流式拉取。"""
    rk_suffix = manifest.raw_path.name
    dest = Path(config["local_case_root"]) / f"{manifest.case_id}_RK_raw_{rk_suffix}"
    dest.mkdir(parents=True, exist_ok=True)
    remote_dir = f"{config['dut_root']}/{rk_suffix}"
    adb_exe = config["adb_exe"]
    timeout = int(config.get("adb_pull_timeout", 600))

    try:
        remote_files = _adb_list_files(adb_exe, remote_dir)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(_translate_adb_error(exc)) from exc

    missing = sum(
        1 for name, size in remote_files.items()
        if not (dest / name).exists() or (dest / name).stat().st_size != size
    )

    if missing == 0:
        if progress_cb:
            progress_cb(1, 1, "已全部存在")
        return

    if progress_cb:
        progress_cb(0, len(remote_files), f"传输中 ({missing} 文件)")
    try:
        adb_proc = subprocess.Popen(
            [adb_exe, "exec-out", "cd", remote_dir, "&&", "tar", "cf", "-", "."],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        tar_proc = subprocess.Popen(
            ["tar", "xf", "-", "-C", str(dest)],
            stdin=adb_proc.stdout,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        adb_proc.stdout.close()  # 允许 adb 收到 SIGPIPE
        try:
            adb_proc.wait(timeout=timeout)
            tar_proc.wait(timeout=60)
        finally:
            if adb_proc.returncode is None:
                adb_proc.kill()
                adb_proc.wait()
            if tar_proc.returncode is None:
                tar_proc.kill()
                tar_proc.wait()
        if adb_proc.returncode != 0:
            stderr = adb_proc.stderr.read().decode("utf-8", errors="replace").strip()
            raw = stderr or f"adb exec-out 失败 (code={adb_proc.returncode})"
            raise RuntimeError(_translate_adb_error_text(raw))
        if tar_proc.returncode != 0:
            raise RuntimeError(f"tar 解压失败 (code={tar_proc.returncode})")
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(_translate_adb_error(exc)) from exc
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"adb exec-out {remote_dir} 超时")
    if progress_cb:
        progress_cb(len(remote_files), len(remote_files), "传输完成")


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
    """复制目录树到服务器。

    UNC 路径用 robocopy（多线程、断点续传、速率显示）；
    本地路径回退到 ThreadPoolExecutor + shutil.copy2。
    """
    files = [f for f in src.rglob("*") if f.is_file()]
    if not files:
        raise RuntimeError(f"upload 源目录为空或不存在: {src}")
    total = len(files)
    dest_str = str(dest)
    src_str = str(src)

    # UNC 路径 → 尝试 robocopy，不可用则回退
    if dest_str.startswith("\\\\"):
        if _robocopy_available():
            return _robocopy_with_progress(src_str, dest_str, total, progress_cb)

    # 本地路径或 robocopy 不可用 → 多线程 copy2
    import threading
    from concurrent.futures import ThreadPoolExecutor, as_completed

    counter = [0]
    lock = threading.Lock()
    start_time = time.time()

    def _copy_one(file: Path):
        rel = file.relative_to(src)
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(file), str(target))
        with lock:
            counter[0] += 1
            n = counter[0]
        if progress_cb:
            elapsed = max(time.time() - start_time, 0.001)
            progress_cb("upload", n, total, f"{int(n / elapsed)} f/s  {file.name}")

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_copy_one, f) for f in files]
        for fut in as_completed(futures):
            fut.result()


def _robocopy_available() -> bool:
    """检查 robocopy 是否可用。"""
    try:
        subprocess.run(["robocopy", "/?"], capture_output=True, timeout=5)
        return True
    except Exception:
        return False


def _robocopy_with_progress(src: str, dest: str, total_files: int, progress_cb=None) -> None:
    """用 robocopy 复制目录树，解析输出获取进度与速率。"""
    proc = subprocess.Popen(
        ["robocopy", src, dest, "/E", "/MT:8", "/R:3", "/W:5",
         "/NP", "/NDL", "/NJH", "/NJS"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    copied = 0
    last_speed = ""
    try:
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            if line.startswith("New File"):
                copied += 1
                if progress_cb:
                    progress_cb("upload", copied, total_files, f"{copied}/{total_files} {last_speed}")
            elif "Bytes" in line and ("sec" in line.lower() or "min" in line.lower()):
                last_speed = line.strip()
                if progress_cb:
                    progress_cb("upload", copied, total_files, f"{copied}/{total_files} {last_speed}")
        proc.wait(timeout=3600)
    finally:
        if proc.returncode is None:
            proc.kill()
            proc.wait()
    if proc.returncode >= 8:
        raise RuntimeError(f"robocopy 失败 (code={proc.returncode})")


def upload_case(manifest, config: dict, progress_cb=None) -> None:
    """把本地 case 目录复制到服务器上传目录。"""
    local_root = Path(config["local_case_root"])
    server_root = Path(config["server_upload_root"])
    mode = (manifest.mode or "").strip() or config["mode"]
    workers = int(config.get("upload_workers", 8))
    src = local_root / mode / manifest.created_date / manifest.case_id
    dest = server_root / mode / manifest.created_date / manifest.case_id
    # 只检查 RK 数据是否已存在（txt 可能先到但不算已完成）
    rk_subdir = dest / f"{manifest.case_id}_RK_raw_{manifest.raw_path.name}"
    if rk_subdir.exists() and any(rk_subdir.iterdir()):
        return  # RK data already uploaded
    dest.parent.mkdir(parents=True, exist_ok=True)
    _copytree_with_progress(src, dest, progress_cb, workers=workers)
