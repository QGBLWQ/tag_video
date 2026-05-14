"""测试 TCP 隧道直传服务器：adb forward + nc|tar → 直接解压到服务器目录。

用法：
    python tools/test_tcp_direct_server.py

需要先设置环境变量或修改脚本中的 SERVER_ROOT 为实际服务器路径。
"""

import os
import random
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from video_tagging_assistant.case_ingest_orchestrator import (
    _adb_list_files,
    _extract_tar_file,
    _find_android_nc,
    _find_android_tar,
    _popen,
    _run,
)

ADB = "adb"
DUT_ROOT = "/mnt/nvme/CapturedData"
# 修改为你的服务器路径（UNC 或本地路径均可）
SERVER_ROOT = os.environ.get("TEST_SERVER_ROOT", str(Path(__file__).parent / "_test_server"))
FILE_COUNT = 100
TCP_PORT = 15555


def _parse_size(s: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if s < 1024:
            return f"{s:.1f}{unit}"
        s /= 1024
    return f"{s:.1f}TB"


def _server_reachable(server_path: str) -> bool:
    parent = str(Path(server_path).parent)
    try:
        os.makedirs(parent, exist_ok=True)
        test_file = os.path.join(parent, ".pull_write_test")
        with open(test_file, "w") as f:
            f.write("ok")
        os.remove(test_file)
        return True
    except Exception:
        return False


def find_random_test_dir() -> str:
    result = _run(
        [ADB, "shell", f"ls -d {DUT_ROOT}/*/"],
        capture_output=True, text=True, timeout=10,
    )
    dirs = []
    for d in result.stdout.splitlines():
        name = d.strip().rstrip("/").split("/")[-1]
        if name.isdigit():
            dirs.append(name)
    if not dirs:
        print(f"无法在 {DUT_ROOT} 找到纯数字目录")
        sys.exit(1)
    chosen = random.choice(dirs)
    print(f"随机选中目录: {chosen}")
    return chosen


def main():
    # 1. 选目录
    test_dir = find_random_test_dir()
    remote_dir = f"{DUT_ROOT}/{test_dir}"
    server_dest = f"{SERVER_ROOT}/test_tcp_{test_dir}"

    # 2. 检查服务器可达性
    print(f"\n服务器路径: {server_dest}")
    if not _server_reachable(server_dest):
        print("[FAIL] 服务器不可达！请检查:")
        print("   1. SERVER_ROOT 路径是否正确")
        print("   2. 网络是否连通")
        print(f"   当前 SERVER_ROOT = {SERVER_ROOT}")
        print(f"   可通过环境变量设置: set TEST_SERVER_ROOT=\\\\your\\server\\path")
        sys.exit(1)
    print("[OK] 服务器可达")

    # 3. 检查设备和工具
    android_tar = _find_android_tar(ADB)
    android_nc = _find_android_nc(ADB)
    if not android_tar or not android_nc:
        print(f"[FAIL] 设备缺少工具: tar={bool(android_tar)}, nc={bool(android_nc)}")
        sys.exit(1)
    print(f"[OK] Android tar: {android_tar}")
    print(f"[OK] Android nc:  {android_nc}")

    # 4. 取前 FILE_COUNT 个文件
    remote_all = _adb_list_files(ADB, remote_dir)
    remote_files = dict(list(remote_all.items())[:FILE_COUNT])
    total_bytes = sum(remote_files.values())
    print(f"\n远端文件: {len(remote_all)} 个, 取前 {FILE_COUNT} 个, 总 {_parse_size(total_bytes)}")

    # 5. 清理旧 forward
    _run([ADB, "forward", "--remove", f"tcp:{TCP_PORT}"],
         capture_output=True, timeout=5)

    # 6. 建立 forward
    print(f"\n建立 adb forward tcp:{TCP_PORT}...")
    _run([ADB, "forward", f"tcp:{TCP_PORT}", f"tcp:{TCP_PORT}"],
         capture_output=True, timeout=10, check=True)

    # 7. 设备侧启 shell（只 tar 选中的文件）
    file_args = " ".join(f'"{name}"' for name in list(remote_files.keys()))
    shell_cmd = (
        f"cd '{remote_dir}' && "
        f"{android_tar} cf - {file_args} | {android_nc} -l -p {TCP_PORT}"
    )
    print(f"设备侧启动: nc -l | tar ...")
    shell_proc = _popen(
        [ADB, "shell", shell_cmd],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    # 等一下看有没有错误
    time.sleep(1)
    if shell_proc.poll() is not None:
        err = shell_proc.stderr.read().decode("utf-8", errors="replace")
        print(f"[FAIL] shell 已退出, code={shell_proc.returncode}, stderr={err[:300]}")
        _run([ADB, "forward", "--remove", f"tcp:{TCP_PORT}"], capture_output=True, timeout=5)
        sys.exit(1)

    # 8. PC 侧连接 + 接收 + 直写服务器
    import socket as _socket
    import tempfile as _tmp

    sock = None
    ok = False
    try:
        # 等 nc listen
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                sock = _socket.create_connection(("127.0.0.1", TCP_PORT), timeout=2)
                break
            except (ConnectionRefusedError, _socket.timeout, OSError):
                time.sleep(0.1)
        else:
            print("[FAIL] 连接 nc 超时")
            sys.exit(1)

        print("[OK] TCP 已连接，接收中...")
        sock.settimeout(600)

        tmp_fd, tmp_path = _tmp.mkstemp(suffix=".tar")
        total_read = 0
        total_est = total_bytes
        start = time.time()
        try:
            with os.fdopen(tmp_fd, "wb") as f:
                while True:
                    chunk = sock.recv(16 * 1024 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    total_read += len(chunk)
                    elapsed = max(time.time() - start, 0.001)
                    mb = total_read / (1024 * 1024)
                    speed = mb / elapsed
                    pct = min(int(total_read / total_est * 100), 99) if total_est else 0
                    print(f"\r  TCP {pct}%  {mb:.0f}MB  {speed:.1f}MB/s", end="", flush=True)

            recv_time = time.time() - start
            tar_mb = total_read / (1024 * 1024)
            print(f"\n[OK] 接收完成: {tar_mb:.0f}MB, {recv_time:.1f}s, {tar_mb/recv_time:.1f}MB/s")

            # ★ 多线程并行写服务器：逐文件解压，线程池并发写 SMB ★
            import tarfile as _tarfile
            from concurrent.futures import ThreadPoolExecutor as _TPE
            from concurrent.futures import as_completed as _ac

            extract_start = time.time()
            os.makedirs(server_dest, exist_ok=True)
            server_written = [0]
            server_bytes = [0]
            extract_lock = threading.Lock()
            errors = []

            def _write_one_to_server(member, data):
                """单个文件写服务器（线程池调用）。"""
                fname = member.name.lstrip("./")
                fpath = os.path.join(server_dest, fname.replace("/", os.sep))
                os.makedirs(os.path.dirname(fpath), exist_ok=True)
                with open(fpath, "wb") as f:
                    f.write(data)
                with extract_lock:
                    server_written[0] += 1
                    server_bytes[0] += len(data)

            # 打开 tar，逐个 member 读取数据 → 提交线程池写服务器
            with _tarfile.open(tmp_path, mode="r") as tar:
                members = [m for m in tar.getmembers() if m.isfile()]
                with _TPE(max_workers=32) as pool:
                    futures = []
                    for member in members:
                        data = tar.extractfile(member).read()
                        futures.append(pool.submit(_write_one_to_server, member, data))
                    for fut in _ac(futures):
                        try:
                            fut.result()
                        except Exception as e:
                            errors.append(str(e))

            if errors:
                print(f"[FAIL] 写入错误: {errors[:3]}")
                return

            extract_time = time.time() - extract_start
            # 验证
            actual_files = server_written[0]
            actual_bytes = server_bytes[0]
            actual_mb = actual_bytes / (1024 * 1024)
            total_time = recv_time + extract_time

            print(f"\n{'='*50}")
            print("结果")
            print(f"{'='*50}")
            print(f"  文件数:     {actual_files}")
            print(f"  数据量:     {tar_mb:.0f}MB (tar) / {actual_mb:.0f}MB (解压)")
            print(f"  TCP 接收:   {recv_time:.1f}s  ({tar_mb/recv_time:.1f}MB/s)")
            print(f"  并行写SMB:  {extract_time:.1f}s  ({actual_mb/extract_time:.1f}MB/s, 32线程)")
            print(f"  总耗时:     {total_time:.1f}s  ({actual_mb/total_time:.1f}MB/s)")
            print(f"  服务器路径: {server_dest}")

            ok = True
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    except Exception as e:
        print(f"\n[FAIL] 失败: {e}")
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
        print(f"   服务器上检查: {server_dest}")
    else:
        print("\n[FAIL] 测试失败")


if __name__ == "__main__":
    main()
