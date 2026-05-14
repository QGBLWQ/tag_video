"""测试 adb pull 速率。

用法：
    python tools/test_pull_speed.py

先 tar 流式拉取测试目录，再 adb pull 对比，输出速率。
"""

import subprocess
import sys
import tempfile
import time
import os
from pathlib import Path

ADB = "adb"
DUT_ROOT = "/mnt/nvme/CapturedData"
# 默认取第一个目录作为测试对象
TEST_DIR = None  # 自动检测


def find_test_dir() -> str:
    result = subprocess.run(
        [ADB, "shell", f"ls {DUT_ROOT}"],
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
    return dirs[0]


def find_android_tar() -> str | None:
    for candidate in [
        "tar", "busybox tar", "toybox tar",
        "/system/bin/tar", "/system/xbin/tar",
        "/data/local/tmp/tar", "/data/local/tmp/busybox tar",
    ]:
        try:
            r = subprocess.run(
                [ADB, "shell", f"which {candidate.split()[0]} 2>/dev/null"],
                capture_output=True, text=True, timeout=10,
            )
            if r.returncode == 0 and r.stdout.strip():
                full = r.stdout.strip()
                if " " in candidate:
                    full += " " + candidate.split(" ", 1)[1]
                return full
        except Exception:
            pass
    return None


def list_remote_files(remote_dir: str) -> dict[str, int]:
    result = subprocess.run(
        [ADB, "shell", "ls", "-la", remote_dir],
        capture_output=True, text=True, timeout=30,
    )
    files = {}
    for line in result.stdout.splitlines():
        parts = line.strip().split()
        if len(parts) >= 5 and parts[0].startswith("-"):
            try:
                size = int(parts[4])
                name = parts[-1]
                if name not in (".", ".."):
                    files[name] = size
            except ValueError:
                pass
    return files


def test_tar_pull(remote_dir: str, dest: str, android_tar: str, timeout: int = 600) -> float:
    """返回 MB/s"""
    import tarfile

    cmd = f"cd {remote_dir} && {android_tar} cf - ."
    print(f"\n===== tar 流式拉取 =====")
    print(f"命令: adb exec-out {cmd}")

    start = time.time()
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".tar")
    total = 0
    try:
        proc = subprocess.Popen(
            [ADB, "exec-out", cmd],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        with os.fdopen(tmp_fd, "wb") as f:
            while True:
                chunk = proc.stdout.read(8 * 1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                total += len(chunk)
                elapsed = max(time.time() - start, 0.001)
                mb = total / (1024 * 1024)
                speed = mb / elapsed
                print(f"\r  接收: {mb:.0f}MB  {speed:.1f}MB/s", end="", flush=True)

        proc.wait(timeout=timeout)
        recv_time = time.time() - start

        if proc.returncode != 0:
            print(f"\n  adb exec-out 失败 (code={proc.returncode})")
            return 0

        # 解压
        print(f"\n  解压中...", end="", flush=True)
        extract_start = time.time()
        with tarfile.open(tmp_path, mode="r") as tar:
            tar.extractall(path=dest)
        extract_time = time.time() - extract_start
        total_time = time.time() - start

        mb_total = total / (1024 * 1024)
        print(f"\n")
        print(f"  接收: {mb_total:.0f}MB  {mb_total/recv_time:.1f}MB/s")
        print(f"  解压: {extract_time:.1f}s")
        print(f"  总耗时: {total_time:.1f}s")
        print(f"  整体速率: {mb_total/total_time:.1f}MB/s")
        return mb_total / total_time
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def test_adb_pull(remote_dir: str, dest: str, timeout: int = 600) -> float:
    """返回 MB/s"""
    print(f"\n===== adb pull =====")
    print(f"命令: adb pull {remote_dir}/. {dest}")

    start = time.time()
    proc = subprocess.Popen(
        [ADB, "pull", f"{remote_dir}/.", dest],
        stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
    )
    for line in proc.stderr:
        line = line.strip()
        if line.startswith("[") and "%" in line:
            print(f"\r  {line}", end="", flush=True)
    proc.wait(timeout=timeout)

    total_time = time.time() - start

    # 计算总大小
    total_bytes = sum(
        f.stat().st_size for f in Path(dest).rglob("*") if f.is_file()
    )
    mb = total_bytes / (1024 * 1024)
    speed = mb / total_time if total_time > 0 else 0
    print(f"\n")
    print(f"  总大小: {mb:.0f}MB")
    print(f"  总耗时: {total_time:.1f}s")
    print(f"  速率: {speed:.1f}MB/s")
    return speed


def main():
    global TEST_DIR
    if TEST_DIR is None:
        TEST_DIR = find_test_dir()

    remote_dir = f"{DUT_ROOT}/{TEST_DIR}"
    print(f"测试目录: {remote_dir}")

    # 检查远端文件
    print("检查远端文件...")
    remote_files = list_remote_files(remote_dir)
    total_size = sum(remote_files.values())
    file_count = len(remote_files)
    print(f"  文件数: {file_count}  总大小: {total_size/(1024*1024):.0f}MB")

    # 临时目标目录
    dest_base = Path(__file__).parent.parent / "tools" / "_test_pull_dest"

    # 测试 tar
    android_tar = find_android_tar()
    tar_speed = 0
    if android_tar:
        print(f"检测到 tar: {android_tar}")
        dest1 = str(dest_base / "tar_test")
        Path(dest1).mkdir(parents=True, exist_ok=True)
        tar_speed = test_tar_pull(remote_dir, dest1, android_tar)
        # 清理
        for f in Path(dest1).rglob("*"):
            if f.is_file():
                f.unlink()
    else:
        print("未检测到 tar，跳过 tar 测试")

    # 测试 adb pull
    dest2 = str(dest_base / "adb_test")
    Path(dest2).mkdir(parents=True, exist_ok=True)
    adb_speed = test_adb_pull(remote_dir, dest2)

    # 清理
    import shutil
    shutil.rmtree(str(dest_base), ignore_errors=True)

    # 对比
    print(f"\n===== 对比 =====")
    if tar_speed > 0:
        print(f"  tar:  {tar_speed:.1f}MB/s")
    print(f"  adb pull: {adb_speed:.1f}MB/s")
    if tar_speed > 0:
        ratio = tar_speed / max(adb_speed, 0.001)
        print(f"  tar 是 adb pull 的 {ratio:.1f}x")


if __name__ == "__main__":
    main()
