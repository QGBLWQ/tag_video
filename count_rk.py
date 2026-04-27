
#!/usr/bin/env python3
"""
ADB 设备目录统计脚本
功能：
- 统计指定设备路径下，每个子文件夹的文件数量
- 使用 tqdm 显示进度
- 输出清晰表格

示例：
  python adb_count_folders.py /mnt/nvme/CapturedData
"""

import subprocess
import sys
from dataclasses import dataclass
from typing import List
from tqdm import tqdm


# ─────────────────────────────────────────────
# 数据结构
# ─────────────────────────────────────────────
@dataclass
class FolderStat:
    path: str
    name: str
    file_count: int
    error: str = ""


# ─────────────────────────────────────────────
# 获取子目录列表
# ─────────────────────────────────────────────
def list_subdirs(device_root: str) -> List[str]:
    """
    获取设备路径下的一级子目录
    """
    cmd = ["adb", "shell", "ls", "-d", f"{device_root}/*"]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace"
    )

    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())

    lines = [l.strip() for l in result.stdout.splitlines() if l.strip()]
    return lines


# ─────────────────────────────────────────────
# 统计单个目录文件数
# ─────────────────────────────────────────────
def count_files(device_path: str) -> tuple[int, str]:
    """
    adb shell find <path> -type f
    """
    cmd = ["adb", "shell", "find", device_path, "-type", "f"]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60
        )

        if result.returncode != 0:
            return -1, result.stderr.strip()

        lines = [l for l in result.stdout.splitlines() if l.strip()]
        return len(lines), ""

    except subprocess.TimeoutExpired:
        return -1, "timeout"
    except Exception as e:
        return -1, str(e)


# ─────────────────────────────────────────────
# 主流程
# ─────────────────────────────────────────────
def run(device_root: str):
    print(f"\n📂 扫描设备目录: {device_root}\n")

    try:
        subdirs = list_subdirs(device_root)
    except Exception as e:
        print(f"[ERROR] 无法列出目录: {e}")
        sys.exit(1)

    if not subdirs:
        print("[WARN] 没有子目录")
        return

    results: List[FolderStat] = []

    with tqdm(total=len(subdirs), desc="统计中", unit="dir",
              colour="green") as bar:

        for path in subdirs:
            name = path.rstrip("/").split("/")[-1]

            count, err = count_files(path)

            results.append(FolderStat(
                path=path,
                name=name,
                file_count=count,
                error=err
            ))

            bar.update(1)

    # ─────────────────────────────────────────
    # 输出结果
    # ─────────────────────────────────────────
    print("\n" + "=" * 60)
    print(f"{'文件夹':<20}{'文件数':>10}  状态")
    print("=" * 60)

    total_files = 0

    for r in results:
        if r.error:
            status = f"⚠️ {r.error}"
            count_str = "N/A"
        else:
            status = "✅"
            count_str = str(r.file_count)
            total_files += r.file_count

        print(f"{r.name:<20}{count_str:>10}  {status}")

    print("=" * 60)
    print(f"总文件数: {total_files}")
    print(f"目录数:   {len(results)}")
    print("=" * 60 + "\n")


# ─────────────────────────────────────────────
# 入口
# ─────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(1)

    device_root = sys.argv[1]
    run(device_root)
