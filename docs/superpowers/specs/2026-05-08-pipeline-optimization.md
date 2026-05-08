# Pipeline 优化与 Review 回退功能 — 设计文档

> **状态：** 待实施  
> **创建：** 2026-05-08

---

## 目标

1. **逐 case 流水线**：打标&对齐完成的 case 立即进入审核，不等全部完成
2. **增量 adb pull**：按文件名+大小跳过已存在的文件，实现断点续传
3. **审核回退修改**：支持回到上一个 case 修改，覆盖写回 xlsx + txt
4. **错误中文化**：adb 错误给出可读的中文提示
5. **压缩→AI 流水线化**：压缩完一个视频立即投递给千问，不等全部压缩完成

---

## 一、逐 case 流水线

### 当前状态

```
Tag ALL done ──→ Align ALL done ──→ Review ALL ──→ Execute
```

MainWindow 在 `_on_tagging_complete` 保存全部结果到 `_pending_tagging_results`，`_maybe_enter_review` 检查 `_tagging_finished && _alignment_ready`（全体完成）。

### 目标状态

```
case_A: Tag done ──→ Align done ──→ Review ──→ Execute
case_B: Tag done ──→ Align done ──→ Review ──→ Execute
case_C: Tag running...  Align done ⤳ (等待 Tag)
```

每个 case 独立流转。审核 Tab 逐 case 增量出现。

### 实现要点

**MainWindow 新增 `_case_readiness: dict[str, dict]`**

```python
_case_readiness = {
    "case_A_0142": {"tagged": True,  "ai_result": {...}, "aligned": True},
    "case_A_0143": {"tagged": False, "ai_result": None,  "aligned": True},
}
```

**两个检查点：**

1. 打标侧：每收到一个 case 的 tagging 结果 → 写 `_case_readiness` → 检查 `aligned` 也为 True → 调用 `_review_tab.add_case()`
2. 对齐侧：`_on_alignment_state_changed` 每确认一个 case → 写 `_case_readiness` → 检查 `tagged` 也为 True → 调用 `_review_tab.add_case()`

**ReviewTab 新增 `add_case(manifest, ai_result)`**

- 追加到 `_manifests` 和 `_tagging_results`
- 如果当前正在显示"全部审核完毕"，自动跳到新 case
- 审核 Tab 解锁条件：至少 1 个 case 就绪（不再是全体就绪）

**DJI 预览帧不变** — 仍在 batch_loaded 时开始生成，与打标并行。

**文件改动：**
- `gui/main_window.py` — 新增 `_case_readiness`，改写 `_on_tagging_complete` 为逐 case，修改 `_on_alignment_state_changed`
- `gui/review_tab.py` — 新增 `add_case()`，`load_cases` 保留兼容

---

## 二、增量 adb pull

### 策略

文件名 + 文件大小（byte）对比。不比较 hash/时间戳以保持简单。

### 实现

修改 `pull_case` (`case_ingest_orchestrator.py:136`)：

```python
def pull_case(manifest, config):
    dest = Path(config["local_case_root"]) / f"{case_id}_RK_raw_{rk_suffix}"
    dest.mkdir(parents=True, exist_ok=True)
    
    # 1. 获取远端文件列表
    remote_list = _adb_list_files(config["adb_exe"], remote_dir)
    # {"hdr2_001445_4096x3072.rkraw": 12345678, ...}
    
    # 2. 对比本地
    missing = {}
    for name, size in remote_list.items():
        local_file = dest / name
        if local_file.exists() and local_file.stat().st_size == size:
            continue  # 已存在，跳过
        missing[name] = size
    
    # 3. 只拉缺失/变化的文件
    if missing:
        for name in missing:
            subprocess.run(
                [config["adb_exe"], "pull", f"{remote_dir}/{name}", str(dest / name)],
                check=True, timeout=...
            )
```

`_adb_list_files` 新函数：`adb shell ls -la {dir}` → 解析输出 → `{filename: size}`。

### 对现有逻辑影响

- 首次执行：全部文件缺失 → 全量 pull（与现在行为一致）
- 重跑执行：大部分文件已存在 → 几乎秒级完成
- 部分失败重试：已拉的文件不重复拉

**文件改动：** `case_ingest_orchestrator.py` — 新增 `_adb_list_files()`，修改 `pull_case()`

---

## 三、审核回退修改

### 需求

审核 Tab 新增"上一个"按钮，允许回到之前通过的 case 修改后重新通过。重新通过时覆盖写回 xlsx 和 txt。

### 实现

**ReviewTab UI 改动：**

- `_setup_ui` 加一个 `← 上一个` 按钮
- 维护 `_reviewed_history: list`，记录已通过的 (manifest, tag_result) 列表
- "上一个"回退：`_current_index -= 1`，渲染上一个 case 的已选字段
- 如果上一个 case 之前已通过，预填当时选的字段值

**写回覆盖：**

`upsert_create_record_row` 已按 `case_id` 匹配 → 找到则覆盖行，找不到则追加。无需改。

`write_case_txt` 已覆盖同名文件。无需改。

**文件改动：** `gui/review_tab.py` — 新增按钮 + `_go_previous()` + 历史字段恢复

---

## 四、错误中文化

### 策略

在 adb 调用底层 `_adb_find` / `pull_case` 等位置统一拦截 `subprocess.CalledProcessError`，解析 stderr 关键字。

### 映射表

| stderr 关键字 | 中文提示 |
|---------------|---------|
| `device not found` / `no devices` | 设备未连接，请检查 USB 线缆并确认 adb devices 可见 |
| `permission denied` | 权限不足，请在设备端执行 adb root |
| `No such file or directory` | 远端路径不存在，请检查 dut_root 配置和 RK 目录名 |
| `timeout` / `timed out` | 设备响应超时，请重启 adb server (adb kill-server) |
| `offline` | 设备离线，请重新插拔 USB 并等待设备上线 |

### 实现

`case_ingest_orchestrator.py` 新增函数：

```python
def _translate_adb_error(error: subprocess.CalledProcessError) -> str:
    stderr = (error.stderr or "").lower()
    for keyword, chinese in _ADB_ERROR_MAP.items():
        if keyword in stderr:
            return f"{chinese}（原始错误: {error.stderr.strip()}）"
    return f"adb 命令失败: {error.stderr.strip() or error.stdout.strip()}"
```

pull_case、_adb_find 等处 catch 后调用此函数。

**文件改动：** `rk_alignment_service.py` `_adb_find`、`case_ingest_orchestrator.py` `pull_case`

---

## 五、压缩→AI 流水线化

### 当前状态

```python
# Phase 1: 全部压缩完成
with ThreadPoolExecutor(compression_workers) as pool:
    for f in as_completed(...):  # 阻塞等全部完成
        artifacts[id] = f.result()

# Phase 2: 全部提交 AI
with ThreadPoolExecutor(provider_workers) as pool:
    for f in as_completed(...):  # 阻塞等全部完成
        fresh_results[id] = f.result()
```

两个 `with` 块串行。10 个视频、压缩 20s、AI 15s、各 2 并发 → **~88s**。

### 目标状态

压缩线程和 AI 线程共存于一个线程池。压缩完成一个 → 立即触发对应 case 的 AI 调用。压缩和 AI 调用重叠执行。

```python
with ThreadPoolExecutor(max_workers=compression_workers + provider_workers) as pool:
    compress_futures = {pool.submit(compressor, ...): m for m in to_tag}
    # 压缩完成 → 立即提交 AI，不等待其他压缩
    for f in as_completed(compress_futures):
        artifact = f.result()
        # 立刻提交 AI 任务
        ai_future = pool.submit(_generate_with_retry, ...)
        ai_futures[ai_future] = manifest
    
    for f in as_completed(ai_futures):
        fresh_results[id] = f.result()
```

重叠后 → **~50s**（压缩总时间 = ceil(10/2)*20s，AI 在压缩期间并行消耗）。

### 事件调整

- `compressing` → 提交压缩时 emit（不变）
- `compressed` → 压缩完成时 emit，同时 emit `tagging`（AI 已提交）
- `tagged` → AI 完成时 emit（不变）

### 文件改动

- `tagging_service.py` — `run_batch_tagging` 合并两个 ThreadPoolExecutor 为一个

---

## 改动文件汇总

| 文件 | 改动内容 | 优化项 |
|------|---------|--------|
| `gui/main_window.py` | `_case_readiness` 字典 + 逐 case 检查 | #1, #3 |
| `gui/review_tab.py` | `add_case()` 增量 + `← 上一个` 按钮 | #1, #3, 回退 |
| `case_ingest_orchestrator.py` | `_adb_list_files()` + `pull_case` 增量 + 错误翻译 | #2, #6 |
| `rk_alignment_service.py` | `_adb_find` 错误翻译 | #6 |
| `tagging_service.py` | 合并两个 ThreadPoolExecutor → 压缩完即投 AI | #5 |

---

## 不变的部分

- DJI 预览帧时机（batch_loaded 开始）
- 执行 Tab 架构（串行 pull→move，upload 独立线程）
- Mode 流转（manifest.mode 动态覆写）
- 对齐 Tab 交互（预览/确认/重写）
- 所有 config 格式
