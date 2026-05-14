"""TCP 隧道直传原始文件：零 tar 开销，零临时文件。

用法：
    python tools/test_tcp_raw_stream.py

流程：
    1. PC 端预先 list 远端文件 + 大小
    2. 设备侧: cat file1 file2 ... | nc -l
    3. PC 端: 按已知大小切分流，多线程并行写 SMB
    4. 零 tar 编解码，零临时文件
"""

import os
import random
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from video_tagging_assistant.case_ingest_orchestrator import (
    _adb_list_files,
    _find_android_nc,
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


def _recv_exactly(sock, n: int) -> bytes:
    """从 socket 精确读取 n 字节。"""
    buf = bytearray()
    sock.settimeout(120)
    while len(buf) < n:
        need = n - len(buf)
        chunk = sock.recv(min(need, 16 * 1024 * 1024))
        if not chunk:
            raise ConnectionError(f"socket 断开: 读了 {len(buf)}/{n} 字节")
        buf.extend(chunk)
    return bytes(buf)


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
    server_dest = f"{SERVER_UNC}/tcp_raw_{test_dir}"

    if not _server_reachable(server_dest):
        print(f"[FAIL] 服务器不可达: {server_dest}")
        sys.exit(1)
    print(f"[OK] 服务器: {server_dest}")

    android_nc = _find_android_nc(ADB)
    if not android_nc:
        print("[FAIL] 设备无 nc")
        sys.exit(1)
    print(f"[OK] nc={android_nc}")

    # 预取文件列表 + 大小
    remote_all = _adb_list_files(ADB, remote_dir)
    file_list = list(remote_all.items())[:FILE_COUNT]  # [(name, size), ...]
    total_bytes = sum(s for _, s in file_list)
    print(f"\n文件: {len(remote_all)} 个, 取前 {FILE_COUNT}, {_parse_size(total_bytes)}")

    # Setup forward
    _run([ADB, "forward", "--remove", f"tcp:{TCP_PORT}"],
         capture_output=True, timeout=5)
    _run([ADB, "forward", f"tcp:{TCP_PORT}", f"tcp:{TCP_PORT}"],
         capture_output=True, timeout=10, check=True)

    # 设备侧: cat files | nc
    file_args = " ".join(f'"{name}"' for name, _ in file_list)
    shell_cmd = (
        f"cd '{remote_dir}' && "
        f"cat {file_args} | {android_nc} -l -p {TCP_PORT}"
    )
    print(f"\n设备侧: cat ... | nc -l")
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

        print(f"[OK] 接收原始流 + {WRITE_WORKERS}线程写SMB...")
        total_start = time.time()
        total_read = [0]
        total_written = [0]
        lock = threading.Lock()
        errors = []

        # 边读边写：socket 收 chunk → 提交线程池写 SMB → 继续收下一个 chunk
        import queue as _queue
        chunk_q = _queue.Queue(maxsize=WRITE_WORKERS * 2)
        write_done = threading.Event()

        def _writer_loop():
            while True:
                item = chunk_q.get()
                if item is None:
                    break
                name, data = item
                try:
                    fpath = os.path.join(server_dest, name)
                    os.makedirs(os.path.dirname(fpath), exist_ok=True)
                    with open(fpath, "wb") as f:
                        f.write(data)
                    with lock:
                        total_written[0] += len(data)
                except Exception as e:
                    errors.append(str(e))
                finally:
                    chunk_q.task_done()

        writers = []
        for _ in range(WRITE_WORKERS):
            t = threading.Thread(target=_writer_loop, daemon=True)
            t.start()
            writers.append(t)

        for idx, (name, size) in enumerate(file_list):
            data = _recv_exactly(sock, size)
            total_read[0] += len(data)
            chunk_q.put((name, data))

            # 进度
            elapsed = max(time.time() - total_start, 0.001)
            mb_read = total_read[0] / (1024 * 1024)
            mb_written = total_written[0] / (1024 * 1024)
            pct = int((idx + 1) / len(file_list) * 100)
            print(f"\r  [{idx+1:3d}/{len(file_list)}] {pct}% "
                  f"读{mb_read:.0f}MB 写{mb_written:.0f}MB "
                  f"{mb_read/elapsed:.1f}MB/s",
                  end="", flush=True)

        # 等写入队列清空
        chunk_q.join()
        for _ in writers:
            chunk_q.put(None)
        for t in writers:
            t.join()

        total_time = time.time() - total_start
        total_mb = total_read[0] / (1024 * 1024)

        if errors:
            print(f"\n[FAIL] 错误: {errors[:3]}")
            return

        # Verify
        files_count = sum(1 for _ in Path(server_dest).rglob("*") if _.is_file())
        print(f"\n\n[OK] 完成: {total_mb:.0f}MB, {total_time:.1f}s, "
              f"{total_mb/total_time:.1f}MB/s")
        print(f"\n{'='*50}")
        print("结果")
        print(f"{'='*50}")
        print(f"  直传原始文件:  {total_time:.1f}s  ({total_mb/total_time:.1f}MB/s)")
        print(f"  文件数:        {files_count}")
        print(f"  数据量:        {total_mb:.0f}MB")
        print(f"  零 tar / 零临时文件")
        print(f"  服务器路径:    {server_dest}")

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
