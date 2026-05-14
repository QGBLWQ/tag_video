"""测试 RNDIS USB 网络 + HTTP 拉取速率（不经过 adb 传输数据）。

用法:
    1. 在 Android 设备上开启「USB 网络共享」(USB tethering)
    2. 运行: python tools/test_rndis_http_pull.py

流程:
    - 扫描 RNDIS 网卡获取设备 IP
    - adb shell 在设备端启动 Python http.server (仅做控制)
    - PC 端用 httpx/requests + 多线程分片拉取
    - 对比 adb pull 速率
"""

import math
import os
import random
import re
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from video_tagging_assistant.case_ingest_orchestrator import _adb_list_files, _popen, _run

ADB = "adb"
DUT_ROOT = "/mnt/nvme/CapturedData"
FILE_COUNT = 100
HTTP_PORT = 18080
FETCH_WORKERS = 8  # HTTP 并发拉取线程


def find_rndis_ip() -> str | None:
    """扫描 RNDIS 子网获取设备 IP（通常 192.168.42.129）。

    先 ping 广播地址探测，再逐个尝试常见 IP。
    """
    # 方法1: adb shell ifconfig 找 rndis0
    try:
        r = _run([ADB, "shell", "ip addr show rndis0 2>/dev/null || ifconfig rndis0 2>/dev/null"],
                 capture_output=True, text=True, timeout=5)
        m = re.search(r"inet\s+(\d+\.\d+\.\d+\.\d+)", r.stdout)
        if m:
            return m.group(1)
    except Exception:
        pass

    # 方法2: 常见 IP 序列
    candidates = ["192.168.42.129", "192.168.42.1", "192.168.42.2",
                  "192.168.225.1", "192.168.137.1"]
    for ip in candidates:
        try:
            r = subprocess.run(["ping", "-n", "1", "-w", "500", ip],
                               capture_output=True, text=True, timeout=1)
            if "TTL=" in r.stdout or "ttl=" in r.stdout:
                return ip
        except Exception:
            pass
    return None


def get_test_file_list(remote_dir: str) -> list[str]:
    """获取测试用的文件列表（前 FILE_COUNT 个，优先大文件）。"""
    files = _adb_list_files(ADB, remote_dir)
    # 按大小降序，取前 FILE_COUNT 个
    sorted_files = sorted(files.items(), key=lambda x: x[1], reverse=True)
    return [name for name, _ in sorted_files[:FILE_COUNT]]


def _parse_size(s: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if s < 1024:
            return f"{s:.1f}{unit}"
        s /= 1024
    return f"{s:.1f}TB"


# ──────────────────────────────────────────────
# Phase 1: HTTP 多线程并发拉取
# ──────────────────────────────────────────────
def test_http_pull(device_ip: str, remote_dir: str, file_list: list,
                   dest_dir: str, total_bytes: int) -> dict:
    """PC 端用多线程 HTTP GET 并发拉取设备上的文件。"""
    import urllib.error
    import urllib.request

    os.makedirs(dest_dir, exist_ok=True)
    total_mb = total_bytes / (1024 * 1024)
    print(f"  HTTP base: http://{device_ip}:{HTTP_PORT}/")
    print(f"  文件: {len(file_list)} 个, 总大小 {_parse_size(total_bytes)}")
    print(f"  并发: {FETCH_WORKERS} 线程")

    lock = threading.Lock()
    counter = [0]
    total_read = [0]
    start = time.time()
    errors = []

    def fetch_one(filename: str):
        url = f"http://{device_ip}:{HTTP_PORT}/{filename}"
        dest_path = os.path.join(dest_dir, filename)
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=60) as resp:
                with open(dest_path, "wb") as f:
                    while True:
                        chunk = resp.read(16 * 1024 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)
                        total_read[0] += len(chunk)
            with lock:
                counter[0] += 1
                n = counter[0]
            elapsed = max(time.time() - start, 0.001)
            mb = total_read[0] / (1024 * 1024)
            speed = mb / elapsed
            pct = int(total_read[0] / total_bytes * 100) if total_bytes > 0 else 0
            with lock:
                print(f"\r  HTTP [{counter[0]:3d}/{len(file_list)}] {pct}% "
                      f"{total_read[0]/(1024*1024):.0f}/{total_mb:.0f}MB {speed:.1f}MB/s",
                      end="", flush=True)
        except Exception as e:
            errors.append((filename, str(e)))

    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
        futures = {pool.submit(fetch_one, f): f for f in file_list}
        for fut in as_completed(futures):
            fut.result()

    total_time = time.time() - start
    actual_bytes = sum(
        os.path.getsize(os.path.join(dest_dir, f))
        for f in os.listdir(dest_dir)
        if os.path.isfile(os.path.join(dest_dir, f))
    )
    actual_mb = actual_bytes / (1024 * 1024)
    speed = actual_mb / total_time if total_time > 0 else 0
    actual_files = len(os.listdir(dest_dir))

    print(f"\n  HTTP 完成: {total_time:.1f}s, {actual_mb:.0f}MB, "
          f"{speed:.1f}MB/s, {actual_files} 文件")
    if errors:
        print(f"  错误: {len(errors)} 个文件")
        for fn, err in errors[:5]:
            print(f"    - {fn}: {err}")

    return {
        "mode": "HTTP RNDIS",
        "time": total_time,
        "bytes": actual_bytes,
        "files": actual_files,
        "speed_mbs": speed,
        "errors": len(errors),
    }


# ──────────────────────────────────────────────
# Phase 2: adb pull（对比基准）
# ──────────────────────────────────────────────
def test_adb_pull(remote_dir: str, dest_dir: str) -> dict:
    """adb pull 全目录，作为对比基准。"""
    os.makedirs(dest_dir, exist_ok=True)
    print(f"\n  adb pull 中...")
    start = time.time()
    proc = _popen(
        [ADB, "pull", f"{remote_dir}/.", dest_dir],
        stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
    )
    for line in proc.stderr:
        line = line.strip()
        if line.startswith("[") and "%" in line:
            print(f"\r  {line}", end="", flush=True)
    proc.wait(timeout=600)
    total_time = time.time() - start
    actual_bytes = sum(
        f.stat().st_size for f in Path(dest_dir).rglob("*") if f.is_file()
    )
    actual_mb = actual_bytes / (1024 * 1024)
    speed = actual_mb / total_time if total_time > 0 else 0
    files = sum(1 for _ in Path(dest_dir).rglob("*") if _.is_file())
    print(f"\n  adb pull 完成: {total_time:.1f}s, {actual_mb:.0f}MB, "
          f"{speed:.1f}MB/s, {files} 文件")
    return {
        "mode": "adb pull",
        "time": total_time,
        "bytes": actual_bytes,
        "files": files,
        "speed_mbs": speed,
        "errors": 0,
    }


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────
def main():
    # 1. 找远程测试目录
    result = _run([ADB, "shell", f"ls -d {DUT_ROOT}/*/"],
                  capture_output=True, text=True, timeout=10)
    dirs = []
    for d in result.stdout.splitlines():
        name = d.strip().rstrip("/").split("/")[-1]
        if name.isdigit():
            dirs.append(name)
    if not dirs:
        print(f"无法在 {DUT_ROOT} 找到纯数字目录")
        sys.exit(1)
    chosen = random.choice(dirs)
    remote_dir = f"{DUT_ROOT}/{chosen}"
    print(f"随机选中目录: {chosen}")

    # 2. 获取文件列表
    file_list = get_test_file_list(remote_dir)
    if not file_list:
        print("无文件可测试")
        sys.exit(1)
    total_bytes = sum(
        _adb_list_files(ADB, remote_dir)[name] for name in file_list
    )
    print(f"测试文件: {len(file_list)} 个, 总 {_parse_size(total_bytes)}")

    tmp_dir = Path(__file__).parent / "_test_rndis"
    tmp_dir.mkdir(exist_ok=True)

    # ═══════════════════════════════════════
    # Phase 1: HTTP RNDIS
    # ═══════════════════════════════════════
    print(f"\n{'='*50}")
    print("Phase 1: RNDIS HTTP 拉取")
    print(f"{'='*50}")
    device_ip = find_rndis_ip()
    if device_ip is None:
        print("  ❌ 未检测到 RNDIS 设备 IP（请先开启 Android USB 网络共享）")
        sys.exit(1)
    print(f"  设备 IP: {device_ip}")

    # 设备端启动 HTTP server（仅用 adb 做控制，不传数据）
    print("  设备端启 HTTP server...")
    _run([ADB, "shell", f"pkill -f 'http.server {HTTP_PORT}' 2>/dev/null; pkill -f 'httpd.*{HTTP_PORT}' 2>/dev/null"],
         capture_output=True, timeout=3)

    http_proc = None
    server_cmd = None

    # 尝试 1: python3
    r = _run([ADB, "shell", "which python3 2>/dev/null"],
             capture_output=True, text=True, timeout=5)
    if r.returncode == 0 and r.stdout.strip():
        server_cmd = f"cd {remote_dir} && python3 -m http.server {HTTP_PORT} --bind 0.0.0.0 2>&1"
        print("  使用: python3 http.server")
    else:
        # 尝试 2: busybox httpd
        r = _run([ADB, "shell", "which busybox 2>/dev/null || which /data/local/tmp/busybox 2>/dev/null"],
                 capture_output=True, text=True, timeout=5)
        bb = r.stdout.strip() if r.returncode == 0 else ""
        if bb and "httpd" in _run(
            [ADB, "shell", f"{bb} --list 2>/dev/null"],
            capture_output=True, text=True, timeout=5,
        ).stdout:
            server_cmd = f"cd {remote_dir} && {bb} httpd -p {HTTP_PORT} -h . 2>&1"
            print(f"  使用: {bb} httpd")
        else:
            print("  ❌ 设备上无 Python3 且无 busybox httpd。需要安装一个:")
            print("     adb push busybox-arm64 /data/local/tmp/busybox")
            print("     adb shell chmod 755 /data/local/tmp/busybox")
            sys.exit(1)

    http_proc = _popen(
        [ADB, "shell", server_cmd],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    # 等 server 就绪
    import urllib.request
    for _ in range(20):
        try:
            urllib.request.urlopen(
                f"http://{device_ip}:{HTTP_PORT}/", timeout=1)
            print("  HTTP server 已就绪")
            break
        except Exception:
            time.sleep(0.3)
    else:
        print("  HTTP server 启动超时")
        http_proc.kill()
        sys.exit(1)

    try:
        dest_http = str(tmp_dir / "http_pull")
        r1 = test_http_pull(device_ip, remote_dir, file_list,
                            dest_http, total_bytes)
    finally:
        http_proc.kill()
        _run([ADB, "shell", f"pkill -f 'http.server {HTTP_PORT}' 2>/dev/null"],
             capture_output=True, timeout=3)

    # ═══════════════════════════════════════
    # Phase 2: adb pull（对比）
    # ═══════════════════════════════════════
    print(f"\n{'='*50}")
    print("Phase 2: adb pull（对比基准）")
    print(f"{'='*50}")
    dest_adb = str(tmp_dir / "adb_pull")
    r2 = test_adb_pull(remote_dir, dest_adb)

    # ═══════════════════════════════════════
    # 对比
    # ═══════════════════════════════════════
    print(f"\n{'='*60}")
    print("对比结果")
    print(f"{'='*60}")
    print(f"  {'方式':20s} {'耗时':>8s} {'速率':>10s} {'文件数':>8s} {'数据量':>10s}")
    print(f"  {'─'*20} {'─'*8} {'─'*10} {'─'*8} {'─'*10}")
    for r in (r1, r2):
        speed_str = f"{r['speed_mbs']:.1f} MB/s"
        size_str = f"{r['bytes']/(1024*1024):.0f}MB"
        print(f"  {r['mode']:20s} {r['time']:7.1f}s {speed_str:>10s} "
              f"{r['files']:8d} {size_str:>10s}")
    print(f"  {'─'*20} {'─'*8} {'─'*10} {'─'*8} {'─'*10}")
    ratio = r1["speed_mbs"] / max(r2["speed_mbs"], 0.1)
    print(f"  HTTP RNDIS 是 adb pull 的 {ratio:.1f}x")

    # 清理
    shutil.rmtree(str(tmp_dir), ignore_errors=True)
    print(f"\n已清理临时文件")


if __name__ == "__main__":
    main()
