"""测试 TCP 直推 tar 到服务器 + 远程触发服务器解压。

用法：
    python tools/test_tcp_server_extract.py

前提：
    1. Android 设备已连接
    2. 服务器 UNC 可写
    3. 服务器端 Windows 10+ 自带 tar.exe
    4. PC 能通过 wmic 远程执行服务器命令（通常需同域/同账号管理员）

流程：
    1. adb forward + nc|tar → PC 直接写服务器 .tar 文件
    2. PC 用 wmic 远程触发服务器 tar -xf 解压
    3. 服务器删掉 .tar 临时文件
"""

import os
import random
import subprocess
import sys
import threading
import time
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
SERVER_UNC = os.environ.get("TEST_SERVER_ROOT", r"\\10.10.10.164\rk3668_capture\test")
SERVER_HOST = os.environ.get("TEST_SERVER_HOST", "10.10.10.164")
FILE_COUNT = 100
TCP_PORT = 15555


def _parse_size(s: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if s < 1024:
            return f"{s:.1f}{unit}"
        s /= 1024
    return f"{s:.1f}TB"


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
        print(f"[FAIL] 无法在 {DUT_ROOT} 找到纯数字目录")
        sys.exit(1)
    chosen = random.choice(dirs)
    print(f"随机选中目录: {chosen}")
    return chosen


def _server_reachable(path: str) -> bool:
    parent = str(Path(path).parent)
    try:
        os.makedirs(parent, exist_ok=True)
        test_file = os.path.join(parent, ".pull_write_test")
        with open(test_file, "w") as f:
            f.write("ok")
        os.remove(test_file)
        return True
    except Exception:
        return False


def remote_extract(tar_path: str, dest_dir: str) -> tuple:
    """通过 wmic 远程触发服务器解压 tar 文件。

    tar_path 和 dest_dir 是服务器本地路径（不是 UNC），
    由 UNC 路径转换得到。
    返回 (success: bool, time_sec: float)。
    """
    tar_path_srv = tar_path
    dest_dir_srv = dest_dir

    cmd = (
        f'cmd /c "'
        f'mkdir {dest_dir_srv} 2>nul & '
        f'tar -xf {tar_path_srv} -C {dest_dir_srv} '
        f'&& del {tar_path_srv}'
        f'"'
    )
    print(f"  远程命令: wmic /node:{SERVER_HOST} process call create ...")
    print(f"  tar={tar_path_srv}  ->  {dest_dir_srv}")

    start = time.time()
    try:
        result = subprocess.run(
            [
                "wmic",
                f"/node:{SERVER_HOST}",
                "process", "call", "create",
                cmd,
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )
        elapsed = time.time() - start
        if result.returncode == 0 and "ReturnValue = 0" in result.stdout:
            print(f"  [OK] 远程解压完成: {elapsed:.1f}s")
            return True, elapsed
        else:
            print(f"  [FAIL] wmic rc={result.returncode}")
            print(f"  stdout: {result.stdout[:300]}")
            print(f"  stderr: {result.stderr[:300]}")
            return False, elapsed
    except Exception as e:
        print(f"  [FAIL] wmic 异常: {e}")
        return False, time.time() - start


def main():
    # 1. 选目录
    test_dir = find_random_test_dir()
    remote_dir = f"{DUT_ROOT}/{test_dir}"
    server_dir_unc = f"{SERVER_UNC}/tcp_srv_{test_dir}"
    server_extract_unc = f"{SERVER_UNC}/tcp_srv_{test_dir}_extracted"
    server_tar_unc = f"{server_dir_unc}/case.tar"

    # 2. 检测设备和服务器
    if not _server_reachable(server_tar_unc):
        print(f"[FAIL] 服务器不可达: {server_tar_unc}")
        print(f"  请设置环境变量: set TEST_SERVER_ROOT=...")
        sys.exit(1)
    print(f"[OK] 服务器可达: {server_tar_unc}")

    android_tar = _find_android_tar(ADB)
    android_nc = _find_android_nc(ADB)
    if not android_tar or not android_nc:
        print(f"[FAIL] 设备缺少工具: tar={bool(android_tar)}, nc={bool(android_nc)}")
        sys.exit(1)
    print(f"[OK] tar={android_tar}, nc={android_nc}")

    # 3. 文件信息
    remote_all = _adb_list_files(ADB, remote_dir)
    remote_files = dict(list(remote_all.items())[:FILE_COUNT])
    total_bytes = sum(remote_files.values())
    print(f"\n远端文件: {len(remote_all)} 个, 取前 {FILE_COUNT}, {_parse_size(total_bytes)}")

    # 4. 准备服务器目录，写 tar 文件
    os.makedirs(server_dir_unc, exist_ok=True)
    _run([ADB, "forward", "--remove", f"tcp:{TCP_PORT}"],
         capture_output=True, timeout=5)

    # 5. adb forward
    _run([ADB, "forward", f"tcp:{TCP_PORT}", f"tcp:{TCP_PORT}"],
         capture_output=True, timeout=10, check=True)

    # 6. 设备侧 shell
    file_args = " ".join(f'"{name}"' for name in list(remote_files.keys()))
    shell_cmd = (
        f"cd '{remote_dir}' && "
        f"{android_tar} cf - {file_args} | {android_nc} -l -p {TCP_PORT}"
    )
    print(f"\n设备侧: nc -l | tar ...")
    shell_proc = _popen(
        [ADB, "shell", shell_cmd],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    time.sleep(1)
    if shell_proc.poll() is not None:
        err = shell_proc.stderr.read().decode("utf-8", errors="replace")
        print(f"[FAIL] shell 已退出: {err[:300]}")
        _run([ADB, "forward", "--remove", f"tcp:{TCP_PORT}"],
             capture_output=True, timeout=5)
        sys.exit(1)

    # 7. PC 连接 + 直写服务器 tar 文件
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

        print(f"[OK] TCP 已连接，直接写服务器 .tar 文件...")
        sock.settimeout(600)

        total_read = 0
        total_est = total_bytes
        start = time.time()

        with open(server_tar_unc, "wb") as f:
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
                print(f"\r  TCP写 {pct}%  {mb:.0f}MB  {speed:.1f}MB/s",
                      end="", flush=True)

        recv_time = time.time() - start
        tar_mb = total_read / (1024 * 1024)
        print(f"\n[OK] tar 写到服务器: {tar_mb:.0f}MB, {recv_time:.1f}s, "
              f"{tar_mb/recv_time:.1f}MB/s")
        print(f"    文件: {server_tar_unc}")

        # 8. 远程触发服务器解压
        # UNC: \\10.10.10.164\rk3668_capture\test\tcp_srv_3\case.tar
        # 本地: D:\rk3668_capture\test\tcp_srv_3\case.tar
        # 转换 UNC 到本地路径: 去掉服务器名，把 share 挂到盘符
        # 这里是猜测盘符映射，用户可能需要调整
        tar_path_srv = server_tar_unc.replace(
            f"\\\\{SERVER_HOST}\\rk3668_capture", "D:\\rk3668_capture"
        )
        extract_srv = server_extract_unc.replace(
            f"\\\\{SERVER_HOST}\\rk3668_capture", "D:\\rk3668_capture"
        )

        print(f"\n=== 远程触发服务器解压 ===")
        print(f"  UNC tar:   {server_tar_unc}")
        print(f"  SVR tar:   {tar_path_srv}")
        print(f"  SVR dest:  {extract_srv}")
        print(f"  (盘符映射可在脚本头部 SERVER_LOCAL_ROOT 修改)")

        srv_ok, srv_time = remote_extract(tar_path_srv, extract_srv)
        if not srv_ok:
            print("[FAIL] 服务器解压失败，tar 文件保留可手动处理")
            return

        # 9. 验证
        time.sleep(1)  # 等文件系统同步
        files_count = sum(1 for _ in Path(server_extract_unc).rglob("*")
                          if _.is_file()) if os.path.exists(server_extract_unc) else 0
        actual_bytes = sum(
            f.stat().st_size for f in Path(server_extract_unc).rglob("*")
            if f.is_file()
        ) if os.path.exists(server_extract_unc) else 0
        actual_mb = actual_bytes / (1024 * 1024) if actual_bytes > 0 else 0
        total_time = recv_time + srv_time

        print(f"\n{'='*50}")
        print("结果")
        print(f"{'='*50}")
        print(f"  tar 写入服务器: {recv_time:.1f}s  ({tar_mb/recv_time:.1f}MB/s)")
        print(f"  服务器解压:     {srv_time:.1f}s  ({actual_mb/srv_time:.1f}MB/s)")
        print(f"  总耗时:         {total_time:.1f}s  ({actual_mb/total_time:.1f}MB/s)")
        print(f"  文件数:         {files_count}")
        print(f"  服务器路径:     {server_extract_unc}")

        ok = True
    except Exception as e:
        print(f"\n[FAIL] {e}")
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
