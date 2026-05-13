"""测试 tar 解压速率：Windows tar vs 7-Zip。

用法：
    python tools/test_tar_extract_speed.py

流程：
1. 随机选一个 Android 设备上的 case 目录
2. adb exec-out tar → 临时文件（测接收速率）
3. 复制 tar 文件两份
4. 分别用 Windows tar / 7-Zip 解压，对比速率
"""

import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# 添加项目根到 sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from video_tagging_assistant.case_ingest_orchestrator import (
    _adb_list_files,
    _find_android_tar,
    _find_seven_zip,
)

ADB = "adb"
DUT_ROOT = "/mnt/nvme/CapturedData"
PULL_COUNT = 100


def _parse_size(s: str) -> str:
    """字节数转换为人类可读。"""
    s = float(s)
    for unit in ("B", "KB", "MB", "GB"):
        if s < 1024:
            return f"{s:.1f}{unit}"
        s /= 1024
    return f"{s:.1f}TB"


def find_random_test_dir() -> str:
    """在设备上随机选取一个目录。"""
    result = subprocess.run(
        [ADB, "shell", f"ls {DUT_ROOT}"],
        capture_output=True, text=True, timeout=10,
    )
    dirs = [d.strip() for d in result.stdout.splitlines() if d.strip().isdigit()]
    if not dirs:
        print(f"无法在 {DUT_ROOT} 找到纯数字目录")
        sys.exit(1)
    chosen = random.choice(dirs)
    print(f"随机选中目录: {chosen}")
    return chosen


def pull_tar_to_file(remote_dir: str, output_path: str) -> tuple:
    """adb exec-out tar → 本地文件，返回 (file_count, total_size_mb, speed_mbs)。"""
    android_tar = _find_android_tar(ADB)
    if android_tar is None:
        print("Android 设备无可用的 tar")
        sys.exit(1)
    print(f"检测到 Android tar: {android_tar}")

    # 先列远端文件
    remote_files = _adb_list_files(ADB, remote_dir)
    total_bytes = sum(remote_files.values())
    file_count = len(remote_files)
    print(f"远端文件: {file_count} 个, 总大小 {_parse_size(total_bytes)}")

    # 拉取 tar 流
    tar_cmd = f"cd {remote_dir} && {android_tar} cf - ."
    print(f"执行: adb exec-out {tar_cmd}")
    print("接收中...", end="", flush=True)

    start = time.time()
    total_read = 0
    proc = subprocess.Popen(
        [ADB, "exec-out", tar_cmd],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    with open(output_path, "wb") as f:
        while True:
            chunk = proc.stdout.read(8 * 1024 * 1024)
            if not chunk:
                break
            f.write(chunk)
            total_read += len(chunk)
            elapsed = max(time.time() - start, 0.001)
            mb = total_read / (1024 * 1024)
            speed = mb / elapsed
            print(f"\r接收: {int(total_read / (1024*1024))}MB  {speed:.1f}MB/s", end="", flush=True)

    proc.wait(timeout=600)
    recv_time = time.time() - start
    mb_total = total_read / (1024 * 1024)
    speed = mb_total / recv_time if recv_time > 0 else 0
    tar_size_mb = os.path.getsize(output_path) / (1024 * 1024)

    print(f"\n接收完成: {tar_size_mb:.0f}MB (tar), {recv_time:.1f}s, {speed:.1f}MB/s")
    if proc.returncode != 0:
        stderr = proc.stderr.read().decode("utf-8", errors="replace")
        print(f"adb exec-out 失败 (code={proc.returncode}): {stderr[:200]}")
        sys.exit(1)

    return file_count, tar_size_mb, speed


def time_extract(tool_name: str, tar_path: str, dest_dir: str) -> float:
    """计时解压并返回秒数。"""
    os.makedirs(dest_dir, exist_ok=True)
    start = time.time()

    if tool_name == "tar":
        subprocess.run(
            ["tar", "-xf", tar_path, "-C", dest_dir],
            check=True, capture_output=True, timeout=300,
        )
    elif tool_name == "7z":
        seven_zip = _find_seven_zip()
        if seven_zip is None:
            print("  7-Zip 未安装")
            return -1
        subprocess.run(
            [seven_zip, "x", tar_path, f"-o{dest_dir}", "-y"],
            check=True, capture_output=True, timeout=300,
        )

    elapsed = time.time() - start
    return elapsed


def main():
    test_dir = find_random_test_dir()
    remote_dir = f"{DUT_ROOT}/{test_dir}"

    tmp_dir = Path(__file__).parent / "_test_extract"
    tmp_dir.mkdir(exist_ok=True)
    tar_path = str(tmp_dir / "test.tar")

    # ── Pull ──
    print(f"\n{'='*50}")
    print("Phase 1: adb tar pull")
    print(f"{'='*50}")
    file_count, tar_size_mb, recv_speed = pull_tar_to_file(remote_dir, tar_path)

    # ── 复制一份 tar 文件供 7-Zip 用 ──
    tar_copy = str(tmp_dir / "test_copy.tar")
    shutil.copy2(tar_path, tar_copy)

    # ── 测试 Windows tar ──
    print(f"\n{'='*50}")
    print("Phase 2: Windows tar -xf 解压")
    print(f"{'='*50}")
    dest1 = str(tmp_dir / "extract_tar")
    t1 = time_extract("tar", tar_path, dest1)
    if t1 > 0:
        speed1 = tar_size_mb / t1
        file_count1 = sum(1 for _ in Path(dest1).rglob("*") if _.is_file())
        print(f"  Windows tar: {t1:.1f}s, {speed1:.1f}MB/s, {file_count1} 文件")

    # ── 测试 7-Zip ──
    print(f"\n{'='*50}")
    print("Phase 3: 7-Zip 解压")
    print(f"{'='*50}")
    dest2 = str(tmp_dir / "extract_7z")
    t2 = time_extract("7z", tar_copy, dest2)
    if t2 > 0:
        speed2 = tar_size_mb / t2
        file_count2 = sum(1 for _ in Path(dest2).rglob("*") if _.is_file())
        print(f"  7-Zip:      {t2:.1f}s, {speed2:.1f}MB/s, {file_count2} 文件")

    # ── 对比 ──
    print(f"\n{'='*50}")
    print("对比结果")
    print(f"{'='*50}")
    print(f"  接收速率: {recv_speed:.1f}MB/s")
    if t1 > 0 and t2 > 0:
        print(f"  Windows tar 解压: {t1:.1f}s ({speed1:.1f}MB/s)")
        print(f"  7-Zip 解压:      {t2:.1f}s ({speed2:.1f}MB/s)")
        ratio = t1 / t2 if t2 > 0 else 0
        if ratio > 1:
            print(f"  7-Zip 比 tar 快 {ratio:.1f}x")
        else:
            print(f"  tar 比 7-Zip 快 {1/ratio:.1f}x")
    elif t1 > 0:
        print(f"  Windows tar 解压: {t1:.1f}s ({speed1:.1f}MB/s)")
        print("  7-Zip 未安装")
    elif t2 > 0:
        print(f"  7-Zip 解压: {t2:.1f}s ({speed2:.1f}MB/s)")
        print("  Windows tar 不可用")

    # ── 清理 ──
    shutil.rmtree(str(tmp_dir), ignore_errors=True)
    print(f"\n已清理临时文件")


if __name__ == "__main__":
    main()
