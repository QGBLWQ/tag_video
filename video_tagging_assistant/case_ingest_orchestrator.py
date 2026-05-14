"""case-ingest 流程编排器。

负责串起单个 case 的 pull、move/copy、upload 三段流程，
供 GUI 执行队列和批处理入口复用。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from queue import Queue
from typing import Callable, Iterable

# Windows: 让子进程脱离 cmd 控制台，避免 cmd QuickEdit 模式挂起 adb
if sys.platform == "win32":
    _CREATE_NO_WINDOW = 0x08000000
else:
    _CREATE_NO_WINDOW = 0


def _popen(args, **kwargs):
    """subprocess.Popen 的 wrapper，自动加 CREATE_NO_WINDOW。"""
    if sys.platform == "win32":
        kwargs.setdefault("creationflags", _CREATE_NO_WINDOW)
    return subprocess.Popen(args, **kwargs)


def _run(args, **kwargs):
    """subprocess.run 的 wrapper，自动加 CREATE_NO_WINDOW。"""
    if sys.platform == "win32":
        kwargs.setdefault("creationflags", _CREATE_NO_WINDOW)
    return subprocess.run(args, **kwargs)

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
    result = _run(
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


def _find_android_tar(adb_exe: str) -> str | None:
    """检测 Android 设备上可用的 tar 二进制。返回可用的命令行或 None。"""
    for candidate in ["tar", "busybox tar", "toybox tar",
                      "/system/bin/tar", "/system/xbin/tar",
                      "/data/local/tmp/tar", "/data/local/tmp/busybox tar"]:
        try:
            # 先用 which 拿完整路径
            which_result = _run(
                [adb_exe, "shell", f"which {candidate.split()[0]} 2>/dev/null"],
                capture_output=True, text=True, timeout=10,
            )
            if which_result.returncode == 0 and which_result.stdout.strip():
                full_path = which_result.stdout.strip()
                # 返回完整路径形式：/usr/bin/tar cf 或 /data/local/tmp/busybox tar cf
                if " " in candidate:
                    full_path += " " + candidate.split(" ", 1)[1]
                return full_path
            # which 失败则尝试直接运行
            ver_result = _run(
                [adb_exe, "shell", f"{candidate} --version 2>/dev/null"],
                capture_output=True, text=True, timeout=10,
            )
            if ver_result.returncode == 0 and ver_result.stdout.strip():
                return candidate
        except Exception:
            pass
    return None


def _find_seven_zip() -> str | None:
    """查找 7-Zip 可执行文件路径。"""
    import shutil as _shutil
    candidates = [
        "7z", "7z.exe",
        r"C:\Program Files\7-Zip\7z.exe",
        r"C:\Program Files (x86)\7-Zip\7z.exe",
    ]
    for c in candidates:
        if _shutil.which(c):
            return c
    return None


def _try_native_extract(tool: str, args: list, timeout: int = 300) -> bool:
    """调用外部解压工具，成功返回 True。"""
    try:
        _run(args, check=True, capture_output=True, timeout=timeout)
        return True
    except Exception:
        return False


def _extract_via_python_tarfile(tar_path: str, dest: str,
                                 progress_cb, total_files: int) -> None:
    """Python tarfile 回退方案，逐文件报告进度。"""
    import tarfile as _tarfile
    with _tarfile.open(tar_path, mode="r") as tar:
        members = tar.getmembers()
        total = len(members)
        for i, member in enumerate(members):
            tar.extract(member, path=dest)
            if progress_cb and total > 0:
                pct = int((i + 1) / total * 100)
                progress_cb(total_files, total_files, f"解压 {pct}%  {member.name}")


def _extract_tar_file(tar_path: str, dest: str,
                       progress_cb, total_files: int) -> None:
    """按优先级尝试解压：系统 tar > 7-Zip > Python tarfile。"""
    # 1. Windows 自带 tar (Win10 1803+)
    if _try_native_extract("tar", ["tar", "-xf", tar_path, "-C", dest], timeout=300):
        return

    # 2. 7-Zip
    seven_zip = _find_seven_zip()
    if seven_zip:
        if _try_native_extract(seven_zip,
                               [seven_zip, "x", tar_path, f"-o{dest}", "-y"],
                               timeout=300):
            return

    # 3. Python tarfile（最慢但始终可用）
    _extract_via_python_tarfile(tar_path, dest, progress_cb, total_files)


def _pull_via_tar(adb_exe: str, remote_dir: str, dest: str, timeout: int,
                  progress_cb, remote_files: dict, missing: int) -> bool:
    """adb exec-out + tar 流式拉取，两线程顺序执行。

    Thread 1 (接收): adb exec-out → 临时 tar 文件，实时显示速率。
    Thread 2 (解压): Python tarfile 解压到目标目录。
    两阶段不并行，解压等待接收完成后开始。
    """
    import os
    import tempfile
    import threading

    android_tar = _find_android_tar(adb_exe)
    if android_tar is None:
        if progress_cb:
            progress_cb(0, len(remote_files), "Android 无 tar，回退 adb pull")
        return False

    total_est = sum(remote_files.values())
    total_files = len(remote_files)

    if progress_cb:
        progress_cb(0, total_files, f"tar 流式传输 ({android_tar})")

    # ── 两阶段共享状态 ──
    tmp_path = [None]
    total_read = [0]
    recv_ok = [False]
    recv_error = [None]
    recv_done = threading.Event()

    # ═══════════════════════════════════════════════
    # Thread 1: 接收 tar 流 → 临时文件
    # ═══════════════════════════════════════════════
    def _receive_tar():
        try:
            tmp_fd, tp = tempfile.mkstemp(suffix=".tar")
            tmp_path[0] = tp
            start_time = time.time()

            tar_cmd = f"cd {remote_dir} && {android_tar} cf - ."
            proc = _popen(
                [adb_exe, "exec-out", tar_cmd],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            with os.fdopen(tmp_fd, "wb") as f:
                while True:
                    chunk = proc.stdout.read(8 * 1024 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    total_read[0] += len(chunk)
                    if progress_cb and total_est > 0:
                        elapsed = max(time.time() - start_time, 0.001)
                        mb = total_read[0] / (1024 * 1024)
                        speed = mb / elapsed
                        pct = min(int(total_read[0] / total_est * 100), 99)
                        progress_cb(pct, 100, f"tar接收 {mb:.0f}MB {speed:.1f}MB/s")
            proc.wait(timeout=timeout)

            if proc.returncode != 0:
                stderr = proc.stderr.read().decode("utf-8", errors="replace").strip()
                raise RuntimeError(f"adb exec-out 失败(code={proc.returncode}): {stderr[:100]}")
            if total_read[0] < 1024:
                raise RuntimeError(f"tar 流仅 {total_read[0]} 字节")

            recv_ok[0] = True
        except Exception as e:
            recv_error[0] = e
        finally:
            recv_done.set()

    t_recv = threading.Thread(target=_receive_tar, daemon=True, name=f"tar-recv")
    t_recv.start()
    recv_done.wait()
    t_recv.join()

    if recv_error[0]:
        try:
            os.unlink(tmp_path[0])
        except OSError:
            pass
        if progress_cb:
            progress_cb(0, total_files, f"tar 接收异常: {recv_error[0]}，回退 adb pull")
        return False
    if not recv_ok[0]:
        return False

    # ═══════════════════════════════════════════════
    # Thread 2: 解压 tar → 目标目录（优先外部工具，回退 Python tarfile）
    # ═══════════════════════════════════════════════
    extract_ok = [False]
    extract_error = [None]
    extract_done = threading.Event()

    def _extract_tar():
        try:
            if progress_cb:
                progress_cb(total_files * 0.9, total_files, "tar 解压中...")
            _extract_tar_file(tmp_path[0], dest, progress_cb, total_files)
            extract_ok[0] = True
        except Exception as e:
            extract_error[0] = e
        finally:
            extract_done.set()
            try:
                os.unlink(tmp_path[0])
            except OSError:
                pass

    t_extract = threading.Thread(target=_extract_tar, daemon=True, name=f"tar-extract")
    t_extract.start()
    extract_done.wait()
    t_extract.join()

    if extract_error[0]:
        if progress_cb:
            progress_cb(0, total_files, f"tar 解压异常: {extract_error[0]}，回退 adb pull")
        return False

    return extract_ok[0]


# ═══════════════════════════════════════════════════════════
# TCP 隧道传输：adb forward + 设备侧 nc | tar
# ═══════════════════════════════════════════════════════════

_PORT_LOCK = threading.Lock()
_NEXT_PORT = [5555]


def _alloc_forward_port(adb_exe: str) -> int:
    """分配一个未被 adb forward 占用的本地端口。"""
    with _PORT_LOCK:
        try:
            result = _run([adb_exe, "forward", "--list"],
                          capture_output=True, text=True, timeout=5)
            used = set()
            for line in result.stdout.splitlines():
                if "tcp:" in line:
                    for part in line.split():
                        if part.startswith("tcp:"):
                            try:
                                used.add(int(part[4:]))
                            except ValueError:
                                pass
        except Exception:
            used = set()

        port = _NEXT_PORT[0]
        while port in used:
            port += 1
        _NEXT_PORT[0] = port + 1
        if _NEXT_PORT[0] > 5655:
            _NEXT_PORT[0] = 5555
        return port


def _find_android_nc(adb_exe: str) -> str | None:
    """检测设备上的 nc / busybox nc（验证 applet 真实存在）。"""
    for candidate in ["nc", "busybox nc", "toybox nc",
                      "/data/local/tmp/busybox nc",
                      "/mnt/nvme/CapturedData/busybox nc"]:
        try:
            first = candidate.split()[0]
            r = _run([adb_exe, "shell", f"which {first} 2>/dev/null"],
                     capture_output=True, text=True, timeout=5)
            if r.returncode == 0 and r.stdout.strip():
                full = r.stdout.strip()
                if " " in candidate:
                    full += " " + candidate.split(" ", 1)[1]
                # 验证 nc applet 真实可用（busybox 可能不带 nc）
                if "busybox" in full:
                    # full 是 "busybox nc"，先取出 busybox 本体路径再做 --list
                    bb_path = full.rsplit(" ", 1)[0]
                    check = _run(
                        [adb_exe, "shell", f"{bb_path} --list 2>/dev/null | grep -w nc"],
                        capture_output=True, text=True, timeout=5,
                    )
                    if check.returncode != 0 or not check.stdout.strip():
                        continue  # 这个 busybox 没有 nc，试下一个
                return full
        except Exception:
            pass
    return None


def _pull_via_tcp(adb_exe: str, remote_dir: str, dest: str, timeout: int,
                  progress_cb, remote_files: dict) -> bool:
    """adb forward + 设备侧 cat | nc 原始流直写目标目录。

    - 设备: cat file1 file2 ... | nc -l -p PORT
    - PC: 按已知文件大小切分流，队列 + 多线程并行写目标路径
    - 零 tar 编解码，零临时文件
    成功返回 True，失败返回 False（让上层回退）。
    """
    import os as _os
    import socket as _socket

    _LOG_PATH = "C:/Users/19872/Desktop/work！/tools/_tcp_debug.log"
    def _dbg(msg):
        try:
            with open(_LOG_PATH, "a", encoding="utf-8") as lf:
                lf.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
        except Exception:
            pass
    _dbg(f"=== START dest={dest} files={len(remote_files)} ===")

    android_nc = _find_android_nc(adb_exe)
    if not android_nc:
        _dbg("no nc, bail")
        if progress_cb:
            progress_cb(0, len(remote_files), "设备无 nc，降级")
        return False

    port = _alloc_forward_port(adb_exe)
    file_list = list(remote_files.items())  # [(name, size), ...]
    total_bytes = sum(s for _, s in file_list)
    total_files = len(file_list)

    if progress_cb:
        progress_cb(0, 100, f"TCP raw (port {port})")

    try:
        _run([adb_exe, "forward", f"tcp:{port}", f"tcp:{port}"],
             capture_output=True, timeout=10, check=True)
    except Exception as e:
        if progress_cb:
            progress_cb(0, 100, f"adb forward 失败: {e}，降级")
        return False

    # 设备侧：cat files | nc
    file_args = " ".join(f'"{name}"' for name, _ in file_list)
    shell_cmd = (
        f"cd '{remote_dir}' && "
        f"cat {file_args} | {android_nc} -l -p {port}"
    )
    shell_proc = _popen(
        [adb_exe, "shell", shell_cmd],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    time.sleep(1)
    if shell_proc.poll() is not None:
        err = shell_proc.stderr.read().decode("utf-8", errors="replace")
        if progress_cb:
            progress_cb(0, 100, f"shell 退出: {err[:100]}，降级")
        _run([adb_exe, "forward", "--remove", f"tcp:{port}"],
             capture_output=True, timeout=5)
        return False

    sock = None
    ok = False
    try:
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                sock = _socket.create_connection(("127.0.0.1", port), timeout=2)
                break
            except (ConnectionRefusedError, _socket.timeout, OSError):
                time.sleep(0.1)
        else:
            if progress_cb:
                progress_cb(0, 100, "连接 nc 超时，降级")
            return False

        sock.settimeout(timeout)

        _dbg(f"connected, dest={dest} len={len(str(dest))}")

        def _to_ext_path(p):
            s = str(p)
            if s.startswith("\\\\"):
                return "\\\\?\\UNC" + s[1:]
            elif s.startswith("//"):
                return "//?/UNC" + s[1:]
            else:
                return "\\\\?\\" + s

        ext_dest = _to_ext_path(dest)
        _dbg(f"ext_dest len={len(ext_dest)}")
        try:
            _os.makedirs(ext_dest, exist_ok=True)
        except Exception as e:
            _dbg(f"makedirs FAIL: {e}")
            raise

        # 写入队列 + 多线程并行写
        import queue as _queue
        chunk_q = _queue.Queue(maxsize=64)
        write_errors = []
        written_bytes = [0]
        write_lock = threading.Lock()

        def _writer():
            while True:
                item = chunk_q.get()
                if item is None:
                    break
                name, data = item
                fpath = _os.path.join(dest, name)
                ext_fpath = _to_ext_path(fpath)
                try:
                    ext_dpath = _to_ext_path(_os.path.dirname(fpath))
                    _os.makedirs(ext_dpath, exist_ok=True)
                    with open(ext_fpath, "wb") as f:
                        f.write(data)
                    with write_lock:
                        written_bytes[0] += len(data)
                except Exception as e:
                    _dbg(f"WRITE_ERR name={name} len(fpath)={len(fpath)} err={e}")
                    write_errors.append(str(e))
                finally:
                    chunk_q.task_done()

        # UNC 路径用并行写（打满带宽），本地路径单线程足够
        workers = 32 if (str(dest).startswith("\\\\") or str(dest).startswith("//")) else 4
        writers = []
        for _ in range(workers):
            t = threading.Thread(target=_writer, daemon=True)
            t.start()
            writers.append(t)

        total_read = 0
        start = time.time()
        for name, size in file_list:
            try:
                data = _recv_exactly(sock, size)
            except Exception as e:
                _dbg(f"RECV_ERR name={name} size={size} err={e}")
                raise
            total_read += len(data)
            chunk_q.put((name, data))
            if progress_cb:
                elapsed = max(time.time() - start, 0.001)
                mb_read = total_read / (1024 * 1024)
                speed = mb_read / elapsed
                pct = int(total_read / total_bytes * 100) if total_bytes > 0 else 0
                progress_cb(pct, 100,
                            f"TCP {pct}% {mb_read:.0f}MB {speed:.1f}MB/s")

        chunk_q.join()
        for _ in writers:
            chunk_q.put(None)
        for t in writers:
            t.join()

        if write_errors:
            if progress_cb:
                progress_cb(0, 100, f"写入失败: {'; '.join(write_errors[:3])}，降级")
            return False

        ok = True
    except Exception as e:
        if progress_cb:
            progress_cb(0, 100, f"TCP 异常: {e}，降级")
    finally:
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass
        if shell_proc.poll() is None:
            try:
                shell_proc.kill()
                shell_proc.wait(timeout=3)
            except Exception:
                pass
        try:
            _run([adb_exe, "forward", "--remove", f"tcp:{port}"],
                 capture_output=True, timeout=5)
        except Exception:
            pass

    return ok


def _recv_exactly(sock, n: int) -> bytes:
    """从 socket 精确读取 n 字节。"""
    buf = bytearray()
    while len(buf) < n:
        need = n - len(buf)
        chunk = sock.recv(min(need, 16 * 1024 * 1024))
        if not chunk:
            raise ConnectionError(f"socket 断开: 已读 {len(buf)}/{n} 字节")
        buf.extend(chunk)
    return bytes(buf)


def _pull_via_adb(adb_exe: str, remote_dir: str, dest: str, timeout: int,
                  progress_cb, total_bytes: int = 0) -> None:
    """adb pull 整目录，实时显示百分比和速率。"""
    remote_path = f"{remote_dir}/."
    proc = _popen(
        [adb_exe, "pull", remote_path, dest],
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    start_time = time.time()
    try:
        for line in proc.stderr:
            line = line.strip()
            if not line:
                continue
            if line.startswith("[") and "%" in line:
                pct_str = line.split("%")[0].split("[")[-1].strip()
                try:
                    pct = int(float(pct_str))
                    if progress_cb and total_bytes > 0:
                        elapsed = max(time.time() - start_time, 0.001)
                        mb_done = total_bytes * pct / 100 / (1024 * 1024)
                        speed = mb_done / elapsed
                        progress_cb(pct, 100, f"pull {pct}%  {mb_done:.0f}MB  {speed:.1f}MB/s")
                    elif progress_cb:
                        progress_cb(pct, 100, f"pull {pct}%")
                except (ValueError, IndexError):
                    pass
        proc.wait(timeout=timeout)
    finally:
        if proc.returncode is None:
            proc.kill()
            proc.wait()
    if proc.returncode != 0:
        stderr_text = proc.stderr.read() if hasattr(proc.stderr, 'read') else ""
        raise RuntimeError(f"adb pull 失败: {stderr_text}")


def pull_case(manifest, config: dict, progress_cb=None, server_dest=None) -> None:
    """增量 pull。若 server_dest 可达，RK 直接解压到服务器，跳过本地。

    Args:
        server_dest: 服务器上 case_RK_raw 目录的完整路径，若为 None 或不可达则走本地。
    """
    rk_suffix = manifest.raw_path.name

    # 确定目标目录：优先直传服务器
    use_server = False
    if server_dest and config.get("direct_server_pull", True):
        server_path = str(server_dest)
        if _server_reachable(server_path):
            use_server = True
            dest = Path(server_path)
            if progress_cb:
                progress_cb(0, 1, f"直传服务器: {server_path}")
        elif progress_cb:
            progress_cb(0, 1, "服务器不可达，降级到本地")

    if not use_server:
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

    total_bytes = sum(remote_files.values())
    pull_mode = config.get("pull_mode", "tcp")

    if progress_cb:
        mode_label = {"tcp": "TCP 隧道", "tar": "tar 流式", "adb": "adb pull"}.get(
            pull_mode, pull_mode)
        progress_cb(0, len(remote_files), f"传输中 - {mode_label} ({missing} 文件)")

    # 按配置模式尝试，失败自动降级到 adb pull（该 case 独立降级）
    success = False
    if pull_mode == "tcp":
        try:
            success = _pull_via_tcp(adb_exe, remote_dir, str(dest), timeout,
                                     progress_cb, remote_files)
        except Exception as exc:
            if progress_cb:
                progress_cb(0, len(remote_files), f"TCP 异常: {exc}，降级 adb pull")
    elif pull_mode == "tar":
        # tar 模式失败单独重试一次
        for attempt in range(2):
            try:
                success = _pull_via_tar(adb_exe, remote_dir, str(dest), timeout,
                                         progress_cb, remote_files, missing)
                if success:
                    break
                if progress_cb and attempt == 0:
                    progress_cb(0, len(remote_files), "tar 失败，重试一次")
            except Exception as exc:
                if progress_cb:
                    progress_cb(0, len(remote_files),
                                f"tar 异常: {exc} (尝试 {attempt+1}/2)")

    if not success:
        # 最终回退：adb pull（该 case 独立走，不影响其他 case）
        _pull_via_adb(adb_exe, remote_dir, str(dest), timeout, progress_cb,
                      total_bytes=total_bytes)

    manifest.rk_on_server = use_server

    if progress_cb:
        progress_cb(len(remote_files), len(remote_files), "传输完成")


def move_case(manifest, config: dict) -> None:
    """整理 case 目录。rk_on_server=True 时只复制 DJI，跳过 RK move。"""
    rk_suffix = manifest.raw_path.name
    case_id = manifest.case_id
    local_root = Path(config["local_case_root"])
    mode = (manifest.mode or "").strip() or config["mode"]
    dest_dir = local_root / mode / manifest.created_date / case_id
    dest_dir.mkdir(parents=True, exist_ok=True)

    if not manifest.rk_on_server:
        local_rk_dir = local_root / f"{case_id}_RK_raw_{rk_suffix}"
        if local_rk_dir.exists():
            shutil.move(
                str(local_rk_dir),
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

    # 清理空的临时目录残留
    for entry in local_root.iterdir():
        if entry.is_dir() and entry.name.startswith(case_id) and not any(entry.iterdir()):
            try:
                entry.rmdir()
            except OSError:
                pass


def _server_reachable(server_path: str) -> bool:
    """检测服务器路径是否可写。返回 True 表示可达。"""
    import os as _os
    parent = str(Path(server_path).parent)
    try:
        _os.makedirs(parent, exist_ok=True)
        # 尝试创建一个测试文件验证可达性
        test_file = _os.path.join(parent, ".pull_write_test")
        with open(test_file, "w") as f:
            f.write("ok")
        _os.remove(test_file)
        return True
    except Exception:
        return False


def _copytree_with_progress(src: Path, dest: Path, progress_cb=None, workers: int = 8) -> None:
    """复制目录树到服务器。

    UNC 路径用 robocopy（多线程、断点续传、速率显示）；
    本地路径回退到 ThreadPoolExecutor + 大缓冲区 copyfile。
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

    # 本地路径或 robocopy 不可用 → 多线程 copyfile（跳过元数据）+ 大缓冲区
    import threading
    from concurrent.futures import ThreadPoolExecutor, as_completed

    counter = [0]
    lock = threading.Lock()
    start_time = time.time()

    def _copy_one(file: Path):
        rel = file.relative_to(src)
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(file, "rb") as fsrc, open(target, "wb") as fdst:
            shutil.copyfileobj(fsrc, fdst, length=16 * 1024 * 1024)
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
        _run(["robocopy", "/?"], capture_output=True, timeout=5)
        return True
    except Exception:
        return False


def _robocopy_with_progress(src: str, dest: str, total_files: int, progress_cb=None) -> None:
    """用 robocopy 复制目录树，独立线程轮询目标目录文件数报告进度。

    robocopy /MT 多线程模式不输出 'New File' 行，只能轮询目标目录大小推算进度。
    """
    proc = _popen(
        ["robocopy", src, dest, "/E", "/MT:32", "/R:3", "/W:5",
         "/NP", "/NDL", "/NJH", "/NJS", "/NFL"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # 后台线程轮询目标目录，统计文件数和大小
    stop_flag = threading.Event()
    start_time = time.time()
    last_bytes = [0]

    def _poll_progress():
        from pathlib import Path as _P
        dest_path = _P(dest)
        while not stop_flag.is_set():
            if dest_path.exists():
                try:
                    files_now = sum(1 for _ in dest_path.rglob("*") if _.is_file())
                    bytes_now = sum(f.stat().st_size for f in dest_path.rglob("*") if f.is_file())
                    elapsed = max(time.time() - start_time, 0.001)
                    delta = bytes_now - last_bytes[0]
                    last_bytes[0] = bytes_now
                    mb = bytes_now / (1024 * 1024)
                    inst_speed = (delta / 0.5) / (1024 * 1024) if elapsed > 0.5 else mb / elapsed
                    if progress_cb:
                        progress_cb("upload", files_now, total_files,
                                    f"{files_now}/{total_files} {mb:.0f}MB {inst_speed:.1f}MB/s")
                except OSError:
                    pass
            stop_flag.wait(0.5)

    poller = threading.Thread(target=_poll_progress, daemon=True, name="robocopy-poll")
    poller.start()

    try:
        proc.wait(timeout=3600)
    finally:
        stop_flag.set()
        poller.join(timeout=1)
        if proc.returncode is None:
            proc.kill()
            proc.wait()
    if proc.returncode >= 8:
        raise RuntimeError(f"robocopy 失败 (code={proc.returncode})")
    # 最终一次进度报告（确保到达 100%）
    if progress_cb:
        progress_cb("upload", total_files, total_files,
                    f"{total_files}/{total_files} 完成")


def upload_case(manifest, config: dict, progress_cb=None) -> None:
    """上传 case 目录到服务器。rk_on_server=True 时只上传 DJI + txt。"""
    local_root = Path(config["local_case_root"])
    server_root = Path(config["server_upload_root"])
    mode = (manifest.mode or "").strip() or config["mode"]
    workers = int(config.get("upload_workers", 8))
    src = local_root / mode / manifest.created_date / manifest.case_id
    dest = server_root / mode / manifest.created_date / manifest.case_id
    print(f"[UPLOAD_CASE] cid={manifest.case_id} rk_on_server={manifest.rk_on_server} "
          f"src={src} dest={dest} raw={manifest.raw_path.name}")

    if manifest.rk_on_server:
        # RK 已在服务器 — 只补传 DJI normal/night/txt
        dest.parent.mkdir(parents=True, exist_ok=True)
        import shutil as _shutil
        for item in src.iterdir():
            if item.is_dir() and "RK_raw" in item.name:
                print(f"[UPLOAD_CASE] skip RK dir: {item.name}")
                continue
            print(f"[UPLOAD_CASE] upload item: {item.name}")
            if item.is_dir():
                _shutil.copytree(str(item), str(dest / item.name), dirs_exist_ok=True)
            else:
                _shutil.copy2(str(item), str(dest / item.name))
        return

    # 原有逻辑：整目录上传
    rk_subdir = dest / f"{manifest.case_id}_RK_raw_{manifest.raw_path.name}"
    if rk_subdir.exists() and any(rk_subdir.iterdir()):
        print(f"[UPLOAD_CASE] already exists, skip")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"[UPLOAD_CASE] full copytree {len(list(src.iterdir()))} items in src")
    _copytree_with_progress(src, dest, progress_cb, workers=workers)
