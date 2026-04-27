
#!/usr/bin/env python3
"""
adb_pull.py  —  pull + check 一体化脚本
────────────────────────────────────────────────────────────────
核心改进：真正的文件级断点续传
  - 先 adb shell find 拿到设备文件列表（路径 + 大小）
  - 对比本地已有文件，只 pull「不存在」或「大小不一致」的文件
  - 不再全量拉取整个目录，中断后重启只补缺失文件

其他修复：
  1. 设备文件数获取失败返回 -1，禁止误 SKIP
  2. SKIP 检测同时覆盖「已归档」和「pull完待move」两种状态
  3. run_move 目标已存在时先比文件数，一致则跳过，不直接覆盖
  4. check 在 move 成功后才执行，校验最终归档目录
  5. 统一退出码：任意失败/FAIL 以非零退出
"""

import re
import subprocess
import shutil
import sys
import os
import time
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional
from tqdm import tqdm

# ─────────────────────────────────────────────
# 配置
# ─────────────────────────────────────────────
MAX_RETRY     = 3
RETRY_WAIT    = 3    # 秒，重试等待
POLL_INTERVAL = 0.5  # 秒，进度轮询间隔


# ─────────────────────────────────────────────
# 数据结构
# ─────────────────────────────────────────────
@dataclass
class DeviceFile:
    """设备上的单个文件信息"""
    device_path: str   # 设备端绝对路径，如 /mnt/nvme/CapturedData/15/a.bin
    rel_path:    str   # 相对于 task.device_path 的相对路径，如 a.bin
    size:        int   # 文件大小（字节），-1 表示获取失败

@dataclass
class Task:
    device_path: str   # 设备端目录，如 /mnt/nvme/CapturedData/15
    local_name:  str   # pull 落地目录名，如 case_A_0018_RK_raw_15
    move_src:    str   # move 源路径
    move_dst:    str   # move 目标路径（最终归档位置）
    label:       str   # 任务标签

@dataclass
class TaskResult:
    task:         Task
    pull_ok:      Optional[bool] = None  # None=SKIP, True=成功, False=失败
    move_ok:      Optional[bool] = None
    device_count: int = -1
    local_count:  int = -1
    check_match:  Optional[bool] = None  # None=无法校验
    skip_reason:  str = ""
    error:        str = ""


# ─────────────────────────────────────────────
# 编码检测
# ─────────────────────────────────────────────
def detect_encoding(path: str) -> str:
    candidates = ["utf-8-sig", "utf-8", "gbk", "latin-1"]
    raw = Path(path).read_bytes()
    for enc in candidates:
        try:
            raw.decode(enc)
            tqdm.write(f"  → 检测到编码: {enc}")
            return enc
        except (UnicodeDecodeError, LookupError):
            continue
    return "latin-1"


# ─────────────────────────────────────────────
# 解析 bat
# ─────────────────────────────────────────────
def parse_bat(bat_path: str) -> list[Task]:
    pull_pattern = re.compile(r'adb\s+pull\s+(\S+)\s+\.\\\s*(\S+)', re.IGNORECASE)
    move_pattern = re.compile(r'move\s+"([^"]+)"\s+"([^"]+)"',       re.IGNORECASE)

    encoding = detect_encoding(bat_path)
    tasks: list[Task] = []
    pending: Optional[tuple[str, str]] = None

    with open(bat_path, encoding=encoding, errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or line.lower().startswith("rem") or line.startswith("::"):
                continue

            m = pull_pattern.search(line)
            if m:
                pending = (m.group(1), m.group(2))
                continue

            m = move_pattern.search(line)
            if m and pending:
                tasks.append(Task(
                    device_path=pending[0],
                    local_name=pending[1],
                    move_src=m.group(1),
                    move_dst=m.group(2),
                    label=pending[1],
                ))
                pending = None

    return tasks


# ─────────────────────────────────────────────
# 设备文件列表（断点续传核心依赖）
# ─────────────────────────────────────────────
def get_device_file_list(device_dir: str) -> tuple[list[DeviceFile], str]:
    """
    用 adb shell find + stat 获取设备目录下所有文件的路径和大小。
    返回 (文件列表, 错误信息)，失败时列表为空。

    两步走：
      1. find -type f  拿路径列表
      2. stat -c "%s %n" 逐文件拿大小（一次批量执行，用换行分隔）
    """
    # Step 1: 获取文件路径列表
    try:
        r = subprocess.run(
            ["adb", "shell", "find", device_dir, "-type", "f"],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=60
        )
        if r.returncode != 0:
            return [], r.stderr.strip() or "find 命令返回非零退出码"

        file_paths = [l.strip() for l in r.stdout.splitlines() if l.strip()]
        if not file_paths:
            return [], ""

    except subprocess.TimeoutExpired:
        return [], "adb shell find 超时（>60s）"
    except FileNotFoundError:
        return [], "未找到 adb 命令"
    except Exception as e:
        return [], str(e)

    # Step 2: 批量获取文件大小
    # 用 && 拼接多条 stat 命令，单次 adb shell 调用，减少通信开销
    # 格式：stat -c "%s %n" /path/to/file
    stat_cmd = " && ".join(f'stat -c "%s %n" "{p}"' for p in file_paths)
    try:
        r = subprocess.run(
            ["adb", "shell", stat_cmd],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=120
        )
        # stat 部分失败不致命，解析能拿到多少算多少
        size_map: dict[str, int] = {}
        for line in r.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split(" ", 1)
            if len(parts) == 2:
                try:
                    size_map[parts[1]] = int(parts[0])
                except ValueError:
                    pass

    except Exception:
        # stat 整体失败时，大小全部标为 -1（仍可按存在性 pull）
        size_map = {}

    device_files = []
    for p in file_paths:
        # 计算相对路径：去掉 device_dir 前缀
        rel = p[len(device_dir):].lstrip("/")
        device_files.append(DeviceFile(
            device_path=p,
            rel_path=rel,
            size=size_map.get(p, -1),
        ))

    return device_files, ""


def count_local_files(path: Path) -> int:
    """递归统计本地文件数，目录不存在返回 0。"""
    if not path.exists():
        return 0
    return sum(1 for f in path.rglob("*") if f.is_file())


def count_local_files_ex(local_path: str) -> tuple[int, str]:
    """带错误信息版，供 check 阶段使用。"""
    p = Path(local_path)
    if not p.exists():
        return -1, f"路径不存在: {local_path}"
    if not p.is_dir():
        return -1, f"路径不是目录: {local_path}"
    try:
        return sum(1 for f in p.rglob("*") if f.is_file()), ""
    except PermissionError as e:
        return -1, f"权限不足: {e}"
    except Exception as e:
        return -1, str(e)


# ─────────────────────────────────────────────
# 真断点续传：文件级 pull
# ─────────────────────────────────────────────
def pull_missing_files(
    device_files: list[DeviceFile],
    final_dir: Path,
    bar: tqdm,
) -> tuple[bool, int, int]:
    """
    文件级断点续传核心：
      对每个设备文件，判断本地是否已存在且大小一致：
        - 本地不存在             → adb pull（新文件）
        - 本地存在但大小不一致   → adb pull（覆盖残缺文件）
        - 本地存在且大小一致     → 跳过（已完整）

    返回 (全部成功与否, 实际pull数, 跳过数)
    """
    total     = len(device_files)
    pulled    = 0
    skipped   = 0
    failed    = 0

    bar.reset(total=total)
    bar.set_description("分析缺失文件...")

    for i, df in enumerate(device_files, 1):
        local_file = final_dir / df.rel_path
        need_pull  = False

        if not local_file.exists():
            need_pull = True
            reason    = "不存在"
        elif df.size >= 0 and local_file.stat().st_size != df.size:
            need_pull = True
            reason    = f"大小不符(本地{local_file.stat().st_size} vs 设备{df.size})"
        else:
            skipped += 1
            bar.n = i
            bar.set_postfix_str(f"跳过 {df.rel_path}")
            bar.refresh()
            continue

        # 确保父目录存在
        local_file.parent.mkdir(parents=True, exist_ok=True)

        tqdm.write(f"  → pull [{reason}] {df.rel_path}")
        bar.set_description(f"pull {df.rel_path[:40]}")

        # 单文件 pull，重试 MAX_RETRY 次
        ok = False
        for attempt in range(1, MAX_RETRY + 1):
            r = subprocess.run(
                ["adb", "pull", df.device_path, str(local_file)],
                capture_output=True, text=True,
                encoding="utf-8", errors="replace",
            )
            if r.returncode == 0:
                ok = True
                break
            tqdm.write(f"    [WARN] 单文件 pull 失败 (try {attempt}/{MAX_RETRY}): {df.rel_path}")
            if attempt < MAX_RETRY:
                time.sleep(RETRY_WAIT)

        if ok:
            pulled += 1
        else:
            failed += 1
            tqdm.write(f"    [ERROR] 放弃: {df.rel_path}")

        bar.n = i
        bar.set_postfix_str(f"pull={pulled} skip={skipped} fail={failed}")
        bar.refresh()

    success = (failed == 0)
    return success, pulled, skipped


# ─────────────────────────────────────────────
# 任务级 SKIP 检测
# ─────────────────────────────────────────────
def check_already_done(
    total: int,
    final_dir: Path,
    move_dst: Path,
) -> str:
    """
    检测任务是否已完成，返回 skip_reason（空字符串表示不跳过）。

    分两种已完成状态：
      A. 已归档（final_dir 不存在，move_dst 文件数 == total）
      B. pull 完但未 move（final_dir 文件数 == total）

    每种状态均做 1 秒二次确认，防止文件正在写入时的瞬间误判。
    注意：total <= 0 时不允许 SKIP（设备文件数未知，不能判断完成）。
    """
    if total <= 0:
        return ""

    # 情况 A：已完成归档
    if count_local_files(move_dst) == total:
        time.sleep(1)
        if count_local_files(move_dst) == total:
            return f"已归档 ({total} 文件)"

    # 情况 B：pull 完待 move
    if count_local_files(final_dir) == total:
        time.sleep(1)
        if count_local_files(final_dir) == total:
            return f"pull已完成待move ({total} 文件)"

    return ""


# ─────────────────────────────────────────────
# adb pull 主入口
# ─────────────────────────────────────────────
def run_adb_pull(task: Task, bar: tqdm) -> tuple[bool, str]:
    """
    返回 (成功与否, skip_reason)。
    skip_reason 非空表示已跳过（视为成功）。
    """
    final_dir = Path(task.local_name)
    move_dst  = Path(task.move_dst)

    # ── Step 1: 获取设备文件列表 ──────────────────────────────────
    bar.set_description("获取设备文件列表...")
    bar.refresh()

    device_files, err = get_device_file_list(task.device_path)

    if err:
        # 设备文件列表获取失败 → 不允许 SKIP，直接报错
        return False, ""

    total = len(device_files)

    # ── Step 2: SKIP 检测 ─────────────────────────────────────────
    skip_reason = check_already_done(total, final_dir, move_dst)
    if skip_reason:
        bar.reset(total=total)
        bar.n = total
        bar.refresh()
        return True, skip_reason

    # ── Step 3: 文件级断点续传 pull ───────────────────────────────
    tqdm.write(f"  设备文件数: {total}，开始文件级断点续传...")
    final_dir.mkdir(parents=True, exist_ok=True)

    ok, pulled, skipped = pull_missing_files(device_files, final_dir, bar)

    tqdm.write(f"  pull完成: 新拉={pulled}, 跳过={skipped}, 失败={len(device_files)-pulled-skipped}")
    return ok, ""


# ─────────────────────────────────────────────
# move 归档
# ─────────────────────────────────────────────
def run_move(task: Task) -> tuple[bool, str]:
    """
    将 final_dir move 到 move_dst（归档路径）。

    目标已存在时先比文件数：
      - 文件数一致 → 跳过（已完成）
      - 文件数不一致 → 打印警告后覆盖
    """
    src = Path(task.move_src)
    dst = Path(task.move_dst)

    try:
        dst.parent.mkdir(parents=True, exist_ok=True)

        if dst.exists():
            dst_count = count_local_files(dst)
            src_count = count_local_files(src)

            if src_count > 0 and dst_count == src_count:
                tqdm.write(f"  [SKIP move] 目标已存在且文件数一致 ({dst_count})，跳过")
                return True, "move已完成(跳过)"

            tqdm.write(
                f"  [WARN] 目标已存在但文件数不一致 "
                f"(src={src_count}, dst={dst_count})，覆盖"
            )
            shutil.rmtree(str(dst))

        shutil.move(str(src), str(dst))
        return True, ""

    except Exception as e:
        return False, str(e)


# ─────────────────────────────────────────────
# check 校验（move 成功后执行）
# ─────────────────────────────────────────────
def run_check_single(task: Task) -> tuple[int, int, Optional[bool], str]:
    """
    校验归档目录（move_dst）文件数 vs 设备文件数。
    返回 (device_count, local_count, match, error_msg)
    """
    dev_files, dev_err = get_device_file_list(task.device_path)
    dev_count = len(dev_files) if not dev_err else -1

    loc_count, loc_err = count_local_files_ex(task.move_dst)

    if dev_err or loc_err:
        return dev_count, loc_count, None, dev_err or loc_err

    return dev_count, loc_count, (dev_count == loc_count), ""


# ─────────────────────────────────────────────
# 汇总表格
# ─────────────────────────────────────────────
COL_W = {"label": 32, "pull": 10, "move": 10, "dev": 10, "local": 10, "status": 12, "note": 36}

def _sep(char="-"):
    return char * (sum(COL_W.values()) + 4)

def print_header():
    h = (f"{'任务标签':<{COL_W['label']}}"
         f"{'pull':^{COL_W['pull']}}"
         f"{'move':^{COL_W['move']}}"
         f"{'设备文件数':>{COL_W['dev']}}"
         f"{'归档文件数':>{COL_W['local']}}"
         f"{'校验':^{COL_W['status']}}"
         f"备注")
    tqdm.write("\n" + _sep())
    tqdm.write(h)
    tqdm.write(_sep())

def print_row(r: TaskResult):
    if r.pull_ok is None:
        pull_str = "—"
    elif r.skip_reason:
        pull_str = "SKIP"
    elif r.pull_ok:
        pull_str = "✅"
    else:
        pull_str = "❌"

    if r.move_ok is None:
        move_str = "—"
    elif r.move_ok:
        move_str = "✅"
    else:
        move_str = "❌"

    if r.error:
        check_str = "⚠️  ERR"
        note = r.error[:34]
    elif r.check_match is True:
        check_str = "✅ PASS"
        note = r.skip_reason or ""
    elif r.check_match is False:
        check_str = "❌ FAIL"
        note = f"差值: {abs(r.device_count - r.local_count)} 个文件"
    else:
        check_str = "⚠️  N/A"
        note = r.error or r.skip_reason or ""

    dev_str = str(r.device_count) if r.device_count >= 0 else "N/A"
    loc_str = str(r.local_count)  if r.local_count  >= 0 else "N/A"

    tqdm.write(
        f"{r.task.label:<{COL_W['label']}}"
        f"{pull_str:^{COL_W['pull']}}"
        f"{move_str:^{COL_W['move']}}"
        f"{dev_str:>{COL_W['dev']}}"
        f"{loc_str:>{COL_W['local']}}"
        f"  {check_str:<{COL_W['status']}}"
        f"{note}"
    )

def print_summary(results: list[TaskResult]):
    total    = len(results)
    passed   = sum(1 for r in results if r.check_match is True)
    failed   = sum(1 for r in results if r.check_match is False)
    errored  = sum(1 for r in results if r.error)
    skipped  = sum(1 for r in results if r.skip_reason)
    pull_err = sum(1 for r in results if r.pull_ok is False)
    move_err = sum(1 for r in results if r.move_ok is False)

    tqdm.write(_sep("="))
    tqdm.write(
        f"汇总：共 {total} 项  |  ✅ 校验通过 {passed}  |  "
        f"❌ 校验失败 {failed}  |  ⚠️  错误 {errored}  |  ⏭️  跳过 {skipped}"
    )
    if pull_err:
        tqdm.write(f"  ⚠️  pull 失败: {pull_err} 项")
    if move_err:
        tqdm.write(f"  ⚠️  move 失败: {move_err} 项")
    tqdm.write(_sep("=") + "\n")

    if failed == 0 and errored == 0 and pull_err == 0 and move_err == 0:
        tqdm.write("🎉 所有任务完成，文件数一致！")
    else:
        tqdm.write("🔍 存在失败或不一致，建议手动核查上述任务。")


# ─────────────────────────────────────────────
# 主流程
# ─────────────────────────────────────────────
def run(tasks: list[Task]) -> list[TaskResult]:
    """
    一体化流程（for each task）：
      1. adb wait-for-device
      2. 获取设备文件列表
      3. SKIP 检测（已归档 / pull完待move）
      4. 文件级断点续传 pull（只拉缺失或残缺的文件）
      5. move 归档（目标已完成则跳过）
      6. check 校验（仅在 move 成功后，校验归档目录）
    """
    results: list[TaskResult] = []
    print_header()

    with tqdm(total=len(tasks), desc="总进度", unit="task", colour="cyan", position=0) as overall:
        for i, task in enumerate(tasks, 1):
            tqdm.write(f"\n[{i}/{len(tasks)}] {task.label}")
            result = TaskResult(task=task)

            # ── 1. 等待设备 ─────────────────────────────────────
            tqdm.write("  等待设备...")
            subprocess.run(["adb", "wait-for-device"], timeout=30)

            # ── 2~4. adb pull（含 SKIP 检测 + 文件级断点续传）──
            with tqdm(desc="初始化", unit="file", leave=False,
                      position=1, colour="green") as bar:
                pull_ok, skip_reason = run_adb_pull(task, bar)

            result.pull_ok     = pull_ok
            result.skip_reason = skip_reason

            if not pull_ok:
                result.error = "adb pull 最终失败（部分文件重试后仍失败）"
                tqdm.write(f"  ❌ pull 失败: {task.label}")
                print_row(result)
                results.append(result)
                overall.update(1)
                continue

            if skip_reason:
                tqdm.write(f"  ⏭️  SKIP pull: {skip_reason}")

            # ── 5. move 归档 ─────────────────────────────────────
            # 已完整归档时跳过 move
            if "已归档" in skip_reason:
                tqdm.write("  ⏭️  SKIP move: 已在归档目录")
                result.move_ok = True
            else:
                move_ok, move_note = run_move(task)
                result.move_ok = move_ok
                if not move_ok:
                    result.error = f"move 失败: {move_note}"
                    tqdm.write(f"  ❌ move 失败: {move_note}")
                    print_row(result)
                    results.append(result)
                    overall.update(1)
                    continue
                tqdm.write(f"  ✅ move 完成" + (f" ({move_note})" if move_note else ""))

            # ── 6. check 校验 ────────────────────────────────────
            tqdm.write("  校验文件数...")
            dev_c, loc_c, match, chk_err = run_check_single(task)
            result.device_count = dev_c
            result.local_count  = loc_c
            result.check_match  = match
            if chk_err:
                result.error = chk_err

            status = "✅ PASS" if match is True else ("❌ FAIL" if match is False else "⚠️  ERROR")
            tqdm.write(f"  {status}  设备:{dev_c}  归档:{loc_c}")

            print_row(result)
            results.append(result)
            overall.update(1)

    print_summary(results)
    return results


# ─────────────────────────────────────────────
# 入口
# ─────────────────────────────────────────────
if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")

    bat_file = sys.argv[1]

    if not os.path.exists(bat_file):
        print(f"[ERROR] 找不到 bat 文件: {bat_file}")
        sys.exit(1)

    print(f"📄 解析 bat 文件: {bat_file}")
    tasks = parse_bat(bat_file)

    if not tasks:
        print("[ERROR] 未从 bat 文件中解析到任何任务，请检查格式")
        sys.exit(1)

    print("=" * 70)
    print(f"共找到 {len(tasks)} 个任务")
    print("=" * 70)
    for i, t in enumerate(tasks, 1):
        print(f"  [{i}] {t.label}")
        print(f"       设备端:   {t.device_path}")
        print(f"       归档目标: {t.move_dst}")
    print("=" * 70 + "\n")

    results = run(tasks)

    any_fail = any(
        r.pull_ok is False
        or r.move_ok is False
        or r.check_match is False
        or bool(r.error)
        for r in results
    )
    sys.exit(1 if any_fail else 0)
