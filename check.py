
#!/usr/bin/env python3
"""
ADB Pull 文件数校验脚本
- 自动检测 .bat 文件编码（兼容 GBK / UTF-8 / UTF-8-BOM）
- 自动解析 .bat 文件，获取 (设备路径, 本地归档路径) 对
- 通过 adb shell 统计设备端文件数
- 统计本地归档目录文件数
- 用 tqdm 显示校验进度，最终汇总对比结果
"""

import re
import subprocess
import sys
import os
from pathlib import Path
from dataclasses import dataclass
from typing import Optional
from tqdm import tqdm


# ─────────────────────────────────────────────
# 数据结构
# ─────────────────────────────────────────────
@dataclass
class CheckTask:
    device_path: str    # 设备端路径，如 /mnt/nvme/CapturedData/15
    local_path: str     # 本地归档路径（move 目标），如 E:\DV\采集建档V2.1\...
    label: str          # 任务标签，如 case_A_0018_RK_raw_15

@dataclass
class CheckResult:
    task: CheckTask
    device_count: int = -1      # -1 表示获取失败
    local_count: int = -1
    match: Optional[bool] = None
    error: str = ""


# ─────────────────────────────────────────────
# 编码自动检测
# ─────────────────────────────────────────────
def detect_encoding(bat_path: str) -> str:
    """
    按优先级尝试解码，返回第一个成功的编码名称。
    优先级：UTF-8-BOM → UTF-8 → GBK → Latin-1（兜底）

    Windows 记事本 / bat 脚本默认存为 GBK（936代码页），
    但部分编辑器会存为 UTF-8 或 UTF-8-BOM，因此逐一尝试。
    """
    candidates = ["utf-8-sig", "utf-8", "gbk", "latin-1"]
    with open(bat_path, "rb") as f:
        raw = f.read()

    for enc in candidates:
        try:
            raw.decode(enc)
            print(f"  → 检测到编码: {enc}")
            return enc
        except (UnicodeDecodeError, LookupError):
            continue

    # 理论上 latin-1 能解所有字节，不会走到这里
    return "latin-1"


# ─────────────────────────────────────────────
# 解析 bat 文件
# ─────────────────────────────────────────────
def parse_bat(bat_path: str) -> list[CheckTask]:
    """
    从 .bat 文件中提取所有 (adb pull, move) 任务对。

    支持的格式（与实际 bat 文件一致）：
      adb pull /mnt/nvme/CapturedData/15 .\\case_A_0018_RK_raw_15
      move "E:\\DV\\采集建档V2.1\\case_A_0018_RK_raw_15" "E:\\DV\\采集建档V2.1\\...\\case_A_0018_RK_raw_15"
    """
    pull_pattern = re.compile(
        r'adb\s+pull\s+(\S+)\s+\.\\\s*(\S+)', re.IGNORECASE
    )
    # move 的路径含中文，必须用引号内匹配，不能用 \S+
    move_pattern = re.compile(
        r'move\s+"([^"]+)"\s+"([^"]+)"', re.IGNORECASE
    )

    encoding = detect_encoding(bat_path)
    tasks: list[CheckTask] = []
    pending_pull: Optional[tuple[str, str]] = None  # (device_path, local_name)

    with open(bat_path, encoding=encoding, errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("rem") or line.startswith("::"):
                continue  # 跳过空行和注释

            m = pull_pattern.search(line)
            if m:
                pending_pull = (m.group(1), m.group(2))
                continue

            m = move_pattern.search(line)
            if m and pending_pull:
                tasks.append(CheckTask(
                    device_path=pending_pull[0],
                    local_path=m.group(2),      # move 的【目标】路径，即归档位置
                    label=pending_pull[1],       # e.g. case_A_0018_RK_raw_15
                ))
                pending_pull = None

    return tasks


# ─────────────────────────────────────────────
# 统计文件数
# ─────────────────────────────────────────────
def count_device_files(device_path: str) -> tuple[int, str]:
    """
    通过 adb shell find 统计设备端指定目录下的文件总数
    （递归，只计文件不计目录）。
    返回 (文件数, 错误信息)，成功时错误信息为空字符串。
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
            err = result.stderr.strip() or "adb shell 返回非零退出码"
            return -1, err

        lines = [l for l in result.stdout.strip().splitlines() if l.strip()]
        return len(lines), ""

    except subprocess.TimeoutExpired:
        return -1, "adb shell 超时（>60s）"
    except FileNotFoundError:
        return -1, "未找到 adb 命令，请确保 adb 已加入 PATH"
    except Exception as e:
        return -1, str(e)


def count_local_files(local_path: str) -> tuple[int, str]:
    """
    递归统计本地目录中的文件总数（只计文件，不计子目录本身）。
    路径含中文时，Path() 在 Windows 上可正常处理。
    返回 (文件数, 错误信息)。
    """
    p = Path(local_path)
    if not p.exists():
        return -1, f"路径不存在: {local_path}"
    if not p.is_dir():
        return -1, f"路径不是目录: {local_path}"

    try:
        count = sum(1 for f in p.rglob("*") if f.is_file())
        return count, ""
    except PermissionError as e:
        return -1, f"权限不足: {e}"
    except Exception as e:
        return -1, str(e)


# ─────────────────────────────────────────────
# 打印汇总结果
# ─────────────────────────────────────────────
PASS_STR  = "✅ PASS"
FAIL_STR  = "❌ FAIL"
ERROR_STR = "⚠️  ERROR"

# 中文字符占2个显示宽度，列宽需适当放宽
COL_W = {
    "label":  32,
    "dev":    10,
    "local":  10,
    "status": 12,
    "note":   40,
}

def print_header():
    h = (f"{'任务标签':<{COL_W['label']}}"
         f"{'设备文件数':>{COL_W['dev']}}"
         f"{'本地文件数':>{COL_W['local']}}"
         f"{'结果':<{COL_W['status']}}"
         f"备注")
    sep = "-" * (sum(COL_W.values()) + 2)
    tqdm.write("\n" + sep)
    tqdm.write(h)
    tqdm.write(sep)


def print_row(r: CheckResult):
    if r.error:
        status = ERROR_STR
        note   = r.error[:38]
    elif r.match:
        status = PASS_STR
        note   = ""
    else:
        status = FAIL_STR
        note   = f"差值: {abs(r.device_count - r.local_count)} 个文件"

    dev_str   = str(r.device_count) if r.device_count >= 0 else "N/A"
    local_str = str(r.local_count)  if r.local_count  >= 0 else "N/A"

    row = (f"{r.task.label:<{COL_W['label']}}"
           f"{dev_str:>{COL_W['dev']}}"
           f"{local_str:>{COL_W['local']}}"
           f"  {status:<{COL_W['status']}}"
           f"{note}")
    tqdm.write(row)


def print_summary(results: list[CheckResult]):
    total   = len(results)
    passed  = sum(1 for r in results if r.match is True)
    failed  = sum(1 for r in results if r.match is False)
    errored = sum(1 for r in results if r.error)

    sep = "=" * (sum(COL_W.values()) + 2)
    tqdm.write(sep)
    tqdm.write(f"汇总：共 {total} 项  |  "
               f"✅ 通过 {passed}  |  "
               f"❌ 失败 {failed}  |  "
               f"⚠️  错误 {errored}")
    tqdm.write(sep + "\n")

    if failed == 0 and errored == 0:
        tqdm.write("🎉 所有任务文件数一致，pull 结果完整！")
    else:
        tqdm.write("🔍 存在不一致或错误，建议手动核查上述任务。")


# ─────────────────────────────────────────────
# 主流程
# ─────────────────────────────────────────────
def run_check(tasks: list[CheckTask]):
    results: list[CheckResult] = []
    print_header()

    with tqdm(total=len(tasks), desc="校验进度", unit="task",
              colour="yellow", position=0) as bar:

        for task in tasks:
            bar.set_description(f"校验 {task.label}")
            result = CheckResult(task=task)

            # 1. 统计设备端文件数
            dev_count, dev_err = count_device_files(task.device_path)
            result.device_count = dev_count

            # 2. 统计本地文件数
            local_count, local_err = count_local_files(task.local_path)
            result.local_count = local_count

            # 3. 判断
            if dev_err or local_err:
                result.error = dev_err or local_err
                result.match = None
            else:
                result.match = (dev_count == local_count)

            results.append(result)
            print_row(result)
            bar.update(1)

    print_summary(results)
    return results


# ─────────────────────────────────────────────
# 入口
# ─────────────────────────────────────────────
if __name__ == "__main__":
    # Windows 终端输出中文：强制 stdout 使用 utf-8
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")

    bat_file = sys.argv[1] if len(sys.argv) > 1 else "20260416_pull.bat"

    if not os.path.exists(bat_file):
        print(f"[ERROR] 找不到 bat 文件: {bat_file}")
        sys.exit(1)

    print(f"📄 解析 bat 文件: {bat_file}")
    tasks = parse_bat(bat_file)

    if not tasks:
        print("[ERROR] 未从 bat 文件中解析到任何任务，请检查格式")
        sys.exit(1)

    # 预览解析结果
    print("=" * 70)
    print(f"共找到 {len(tasks)} 个校验任务")
    print("=" * 70)
    for i, t in enumerate(tasks, 1):
        print(f"  [{i}] 设备端: {t.device_path}")
        print(f"       本地:   {t.local_path}")
    print("=" * 70 + "\n")

    results = run_check(tasks)

    # 有失败则以非零退出码退出，方便 CI/自动化流程捕获
    any_fail = any(r.match is False or r.error for r in results)
    sys.exit(1 if any_fail else 0)
