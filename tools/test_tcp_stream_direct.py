"""TCP 流式直写服务器：无临时文件，无解压步骤。

用法：
    python tools/test_tcp_stream_direct.py

流程：
    1. adb forward + nc|tar → PC socket 流式读 tar（不落盘）
    2. 逐个 member 读数据 → 线程池并行写服务器 UNC
    3. 零临时文件，零解压步骤
"""

import os
import random
import shutil
import subprocess
import sys
import tarfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from video_tagging_assistant.case_ingest_orchestrator import (
    _adb_list_files,
    _find_android_nc,
    _find_android_tar,
    _popen,
    _run,
)

ADB = "adb"
DUT_ROOT = "/mnt/nvme/CapturedData"
SERVER_UNC = os.environ.get("TEST_SERVER_ROOT", str(Path(__file__).parent / "_test_server"))
FILE_COUNT = 100
TCP_PORT = 15555
WRITE_WORKERS = 32


def _parse_size(s: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if s < 1024:
            return f"{s:.1f}{unit}"
        s /= 1024
    return f"{s:.1f}TB"


def find_test_dir() -> str:
    result = _run([ADB, "shell", f"ls -d {DUT_ROOT}/*/"],
                  capture_output=True, text=True, timeout=10)
    dirs = []
    for d in result.stdout.splitlines():
        name = d.strip().rstrip("/").split("/")[-1]
        if name.isdigit():
            dirs.append(name)
    if not dirs:
        print(f"[FAIL] 无法在 {DUT_ROOT} 找到纯数字目录")
        sys.exit(1)
    chosen = random.choice(dirs)
    print(f"随机选中目录: {chosen}")
    return chosen


def _server_reachable(path: str) -> bool:
    parent = str(Path(path).parent)
    try:
        os.makedirs(parent, exist_ok=True)
        test = os.path.join(parent, ".pull_write_test")
        with open(test, "w") as f:
            f.write("ok")
        os.remove(test)
        return True
    except Exception:
        return False


def main():
    test_dir = find_test_dir()
    remote_dir = f"{DUT_ROOT}/{test_dir}"
    server_dest = f"{SERVER_UNC}/tcp_stream_{test_dir}"

    # Check server
    if not _server_reachable(server_dest):
        print(f"[FAIL] 服务器不可达: {server_dest}")
        sys.exit(1)
    print(f"[OK] 服务器: {server_dest}")

    # Check device
    android_tar = _find_android_tar(ADB)
    android_nc = _find_android_nc(ADB)
    if not android_tar or not android_nc:
        print(f"[FAIL] tar={bool(android_tar)}, nc={bool(android_nc)}")
        sys.exit(1)
    print(f"[OK] tar={android_tar}, nc={android_nc}")

    # File info
    remote_all = _adb_list_files(ADB, remote_dir)
    remote_files = dict(list(remote_all.items())[:FILE_COUNT])
    total_bytes = sum(remote_files.values())
    print(f"\n文件: {len(remote_all)} 个, 取前 {FILE_COUNT}, {_parse_size(total_bytes)}")

    # Setup forward
    _run([ADB, "forward", "--remove", f"tcp:{TCP_PORT}"],
         capture_output=True, timeout=5)
    _run([ADB, "forward", f"tcp:{TCP_PORT}", f"tcp:{TCP_PORT}"],
         capture_output=True, timeout=10, check=True)

    # Device shell
    file_args = " ".join(f'"{name}"' for name in list(remote_files.keys()))
    shell_cmd = (
        f"cd '{remote_dir}' && "
        f"{android_tar} cf - {file_args} | {android_nc} -l -p {TCP_PORT}"
    )
    shell_proc = _popen(
        [ADB, "shell", shell_cmd],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    time.sleep(1)
    if shell_proc.poll() is not None:
        err = shell_proc.stderr.read().decode("utf-8", errors="replace")
        print(f"[FAIL] shell 已退出: {err[:300]}")
        _run([ADB, "forward", "--remove", f"tcp:{TCP_PORT}"],
             capture_output=True, timeout=5)
        sys.exit(1)

    import socket as _socket
    sock = None
    ok = False
    try:
        # Connect
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                sock = _socket.create_connection(("127.0.0.1", TCP_PORT), timeout=2)
                break
            except (ConnectionRefusedError, _socket.timeout, OSError):
                time.sleep(0.1)
        else:
            print("[FAIL] 连接超时")
            sys.exit(1)

        print(f"[OK] 流式读 tar + 并行写 SMB ({WRITE_WORKERS} 线程)...")
        sock.settimeout(600)
        total_start = time.time()
        total_read = [0]
        written = [0]
        written_bytes = [0]
        lock = threading.Lock()
        total_est = total_bytes
        errors = []

        def _write_one(member, data):
            fname = member.name.lstrip("./")
            fpath = os.path.join(server_dest, fname.replace("/", os.sep))
            os.makedirs(os.path.dirname(fpath), exist_ok=True)
            with open(fpath, "wb") as f:
                f.write(data)
            with lock:
                written[0] += 1
                written_bytes[0] += len(data)

        # ★ 核心：socket → tarfile 流式读取，不落临时文件 ★
        sock_file = sock.makefile("rb")
        with tarfile.open(fileobj=sock_file, mode="r|") as tar:
            with ThreadPoolExecutor(max_workers=WRITE_WORKERS) as pool:
                futures = []
                for member in tar:
                    if not member.isfile():
                        continue
                    data = tar.extractfile(member).read()
                    total_read[0] += len(data)
                    futures.append(pool.submit(_write_one, member, data))

                    # 进度
                    elapsed = max(time.time() - total_start, 0.001)
                    mb_total = total_read[0] / (1024 * 1024)
                    speed = mb_total / elapsed
                    pct = min(int(total_read[0] / total_est * 100), 99) if total_est else 0
                    print(f"\r  Stream {pct}% {mb_total:.0f}MB {speed:.1f}MB/s "
                          f"写{written[0]}文件",
                          end="", flush=True)

                # 等所有写完成
                for fut in as_completed(futures):
                    try:
                        fut.result()
                    except Exception as e:
                        errors.append(str(e))

        total_time = time.time() - total_start
        total_mb = total_read[0] / (1024 * 1024)
        actual_mb = written_bytes[0] / (1024 * 1024)

        print(f"\n[OK] 流式直写完成: {total_mb:.0f}MB, {total_time:.1f}s, "
              f"{total_mb/total_time:.1f}MB/s")

        if errors:
            print(f"[FAIL] 写入错误: {errors[:3]}")
            return

        # Verify
        files_count = sum(1 for _ in Path(server_dest).rglob("*") if _.is_file())
        print(f"\n{'='*50}")
        print("结果")
        print(f"{'='*50}")
        print(f"  流式直写 SMB:   {total_time:.1f}s  ({actual_mb/total_time:.1f}MB/s)")
        print(f"  文件数:          {files_count}")
        print(f"  数据量:          {actual_mb:.0f}MB")
        print(f"  零临时文件       (tar 流不落盘)")
        print(f"  服务器路径:      {server_dest}")

        ok = True
    except Exception as e:
        print(f"\n[FAIL] {e}")
        import traceback
        traceback.print_exc()
    finally:
        if sock:
            sock.close()
        if shell_proc.poll() is None:
            shell_proc.kill()
            shell_proc.wait(timeout=3)
        _run([ADB, "forward", "--remove", f"tcp:{TCP_PORT}"],
             capture_output=True, timeout=5)

    if ok:
        print("\n[OK] 全部成功！")
    else:
        print("\n[FAIL] 测试失败")


if __name__ == "__main__":
    main()
