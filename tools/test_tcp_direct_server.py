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
SERVER_ROOT = os.environ.get("TEST_SERVER_ROOT", r"\\192.168.1.100\share\test_pull")
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
    dirs = [d.strip().split("/")[-1] for d in result.stdout.splitlines() if d.strip().isdigit()]
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
        print("❌ 服务器不可达！请检查:")
        print("   1. SERVER_ROOT 路径是否正确")
        print("   2. 网络是否连通")
        print(f"   当前 SERVER_ROOT = {SERVER_ROOT}")
        print(f"   可通过环境变量设置: set TEST_SERVER_ROOT=\\\\your\\server\\path")
        sys.exit(1)
    print("✅ 服务器可达")

    # 3. 检查设备和工具
    android_tar = _find_android_tar(ADB)
    android_nc = _find_android_nc(ADB)
    if not android_tar or not android_nc:
        print(f"❌ 设备缺少工具: tar={bool(android_tar)}, nc={bool(android_nc)}")
        sys.exit(1)
    print(f"✅ Android tar: {android_tar}")
    print(f"✅ Android nc:  {android_nc}")

    # 4. 获取文件列表
    remote_files = _adb_list_files(ADB, remote_dir)
    file_list = list(remote_files.keys())[:FILE_COUNT]
    total_bytes = sum(remote_files[name] for name in file_list)
    print(f"\n测试文件: {len(file_list)} 个, 总 {_parse_size(total_bytes)}")

    # 5. 清理旧 forward
    _run([ADB, "forward", "--remove", f"tcp:{TCP_PORT}"],
         capture_output=True, timeout=5)

    # 6. 建立 forward
    print(f"\n建立 adb forward tcp:{TCP_PORT}...")
    _run([ADB, "forward", f"tcp:{TCP_PORT}", f"tcp:{TCP_PORT}"],
         capture_output=True, timeout=10, check=True)

    # 7. 设备侧启 shell
    file_args = " ".join(file_list)
    shell_cmd = (
        f"cd {remote_dir} && "
        f"{android_tar} cf - {file_args} | {android_nc} -l -p {TCP_PORT}"
    )
    print(f"设备侧启动: nc -l | tar ...")
    shell_proc = _popen(
        [ADB, "shell", shell_cmd],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )

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
            print("❌ 连接 nc 超时")
            sys.exit(1)

        print("✅ TCP 已连接，接收中...")
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
            print(f"\n✅ 接收完成: {tar_mb:.0f}MB, {recv_time:.1f}s, {tar_mb/recv_time:.1f}MB/s")

            # ★ 直传服务器：解压到 server 目录 ★
            print(f"解压到服务器: {server_dest} ...")
            extract_start = time.time()
            os.makedirs(server_dest, exist_ok=True)
            _extract_tar_file(tmp_path, server_dest, None, len(file_list))
            extract_time = time.time() - extract_start

            # 验证
            actual_files = sum(1 for _ in Path(server_dest).rglob("*") if _.is_file())
            actual_bytes = sum(
                f.stat().st_size for f in Path(server_dest).rglob("*") if f.is_file()
            )
            actual_mb = actual_bytes / (1024 * 1024)
            total_time = recv_time + extract_time

            print(f"✅ 解压完成: {extract_time:.1f}s")
            print(f"\n{'='*50}")
            print("结果")
            print(f"{'='*50}")
            print(f"  文件数:     {actual_files}/{len(file_list)}")
            print(f"  数据量:     {tar_mb:.0f}MB (tar) / {actual_mb:.0f}MB (解压)")
            print(f"  接收耗时:   {recv_time:.1f}s  ({tar_mb/recv_time:.1f}MB/s)")
            print(f"  解压耗时:   {extract_time:.1f}s  ({actual_mb/extract_time:.1f}MB/s)")
            print(f"  总耗时:     {total_time:.1f}s  ({actual_mb/total_time:.1f}MB/s)")
            print(f"  服务器路径: {server_dest}")

            ok = True
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    except Exception as e:
        print(f"\n❌ 失败: {e}")
    finally:
        if sock:
            sock.close()
        if shell_proc.poll() is None:
            shell_proc.kill()
            shell_proc.wait(timeout=3)
        _run([ADB, "forward", "--remove", f"tcp:{TCP_PORT}"],
             capture_output=True, timeout=5)

    if ok:
        print("\n✅ 全部成功！")
        print(f"   服务器上检查: {server_dest}")
    else:
        print("\n❌ 测试失败")


if __name__ == "__main__":
    main()
