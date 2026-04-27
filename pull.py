import re
import subprocess
import shutil
import sys
import os
import time
from pathlib import Path
from dataclasses import dataclass
from typing import Optional
from tqdm import tqdm

# ─────────────────────────────────────────────
# 配置
# ─────────────────────────────────────────────
MAX_RETRY = 3
RETRY_WAIT = 3  # 秒

# ─────────────────────────────────────────────
# 数据结构
# ─────────────────────────────────────────────
@dataclass
class PullTask:
    device_path: str
    local_name: str
    move_src: str
    move_dst: str

# ─────────────────────────────────────────────
# 编码检测
# ─────────────────────────────────────────────
def detect_encoding(path: str) -> str:
    candidates = ["utf-8-sig", "utf-8", "gbk", "latin-1"]
    raw = Path(path).read_bytes()
    for enc in candidates:
        try:
            raw.decode(enc)
            tqdm.write(f" → 编码: {enc}")
            return enc
        except:
            continue
    return "latin-1"

# ─────────────────────────────────────────────
# 解析 bat
# ─────────────────────────────────────────────
def parse_bat(bat_path: str) -> list[PullTask]:
    pull_pattern = re.compile(r'adb\s+pull\s+(\S+)\s+\.\\\s*(\S+)', re.I)
    move_pattern = re.compile(r'move\s+"([^"]+)"\s+"([^"]+)"', re.I)

    encoding = detect_encoding(bat_path)
    tasks = []
    pending = None

    with open(bat_path, encoding=encoding, errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            m = pull_pattern.search(line)
            if m:
                pending = (m.group(1), m.group(2))
                continue

            m = move_pattern.search(line)
            if m and pending:
                tasks.append(PullTask(
                    device_path=pending[0],
                    local_name=pending[1],
                    move_src=m.group(1),
                    move_dst=m.group(2)
                ))
                pending = None

    return tasks

# ─────────────────────────────────────────────
# 获取设备文件数
# ─────────────────────────────────────────────
def get_device_file_count(path: str) -> int:
    cmd = ["adb", "shell", "find", path, "-type", "f"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return len([l for l in r.stdout.splitlines() if l.strip()])
    except:
        return 0

# ─────────────────────────────────────────────
# 本地文件计数
# ─────────────────────────────────────────────
def count_local_files(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for f in path.rglob("*") if f.is_file())

# ─────────────────────────────────────────────
# 合并目录（真正断点续传核心）
# ─────────────────────────────────────────────
def merge_dirs(tmp_dir: Path, final_dir: Path):
    if not tmp_dir.exists():
        return

    if not final_dir.exists():
        tmp_dir.rename(final_dir)
        return

    for src_file in tmp_dir.rglob("*"):
        if src_file.is_file():
            rel = src_file.relative_to(tmp_dir)
            dst_file = final_dir / rel

            dst_file.parent.mkdir(parents=True, exist_ok=True)

            # ✅ 已存在文件 → 跳过（断点续传关键）
            if not dst_file.exists():
                shutil.move(str(src_file), str(dst_file))

    shutil.rmtree(tmp_dir, ignore_errors=True)

# ─────────────────────────────────────────────
# adb pull（最终版：断点续传 + 防嵌套 + 重试）
# ─────────────────────────────────────────────
def run_adb_pull(task: PullTask, bar: tqdm) -> bool:

    total = get_device_file_count(task.device_path)
    if total <= 0:
        total = 1

    final_dir = Path(task.local_name)
    tmp_dir = Path(task.local_name + "_tmp")

    # ✅ 已完成检测（稳定版）
    existing = count_local_files(final_dir)
    if total > 0 and existing == total:
        time.sleep(1)
        if count_local_files(final_dir) == existing:
            tqdm.write(f"[SKIP] 已完成: {task.local_name}")
            bar.reset(total=total)
            bar.n = total
            bar.refresh()
            return True

    # ✅ 清理旧 tmp（防脏数据）
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir, ignore_errors=True)

    for attempt in range(1, MAX_RETRY + 1):

        bar.reset(total=total)
        bar.set_description(f"pull {task.local_name} (try {attempt})")

        proc = subprocess.Popen(
            ["adb", "pull", task.device_path, str(tmp_dir)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        last = -1

        while proc.poll() is None:
            current = count_local_files(final_dir) + count_local_files(tmp_dir)

            bar.n = current
            bar.refresh()

            if current == last:
                bar.set_postfix_str("等待中...")
            else:
                bar.set_postfix_str(f"{current}/{total}")
                last = current

            time.sleep(0.5)

        if proc.returncode == 0:
            # ✅ merge 才是真断点续传
            merge_dirs(tmp_dir, final_dir)
            return True

        tqdm.write(f"[WARN] pull失败，重试 {attempt}/{MAX_RETRY}")
        time.sleep(RETRY_WAIT)

    return False

# ─────────────────────────────────────────────
# move
# ─────────────────────────────────────────────
def run_move(src: str, dst: str) -> bool:
    try:
        Path(dst).parent.mkdir(parents=True, exist_ok=True)

        if Path(dst).exists():
            shutil.rmtree(dst)

        shutil.move(src, dst)
        return True

    except Exception as e:
        tqdm.write(f"[ERROR] move失败: {e}")
        return False

# ─────────────────────────────────────────────
# 主流程
# ─────────────────────────────────────────────
def run(tasks):
    with tqdm(total=len(tasks), desc="总进度", unit="task") as overall:

        for i, task in enumerate(tasks, 1):
            tqdm.write(f"\n[{i}] {task.local_name}")

            with tqdm(desc="初始化", unit="file", leave=False) as bar:

                subprocess.run(["adb", "wait-for-device"])

                ok = run_adb_pull(task, bar)

                if not ok:
                    tqdm.write("❌ pull最终失败")
                    overall.update(1)
                    continue

                ok = run_move(task.move_src, task.move_dst)

                if ok:
                    tqdm.write("✅ 完成")
                else:
                    tqdm.write("❌ move失败")

            overall.update(1)

    tqdm.write("\n🎉 全部任务完成\n")

# ─────────────────────────────────────────────
# 入口
# ─────────────────────────────────────────────
if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")

    bat = sys.argv[1] if len(sys.argv) > 1 else "20260416_pull.bat"

    if not os.path.exists(bat):
        print(f"[ERROR] 找不到文件: {bat}")
        sys.exit(1)

    tasks = parse_bat(bat)

    print("=" * 60)
    print(f"共 {len(tasks)} 个任务")
    print("=" * 60)

    run(tasks)