# Pipeline 优化实施计划

> **For agentic workers:** Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 打标流程提速（压缩→AI 流水线化）、逐 case 审核流、增量 adb pull、审核回退修改、adb 错误中文化。

**Architecture:** 5 个独立改动分散在 5 个文件中，互不依赖。MainWindow 新增 `_case_readiness` 字典驱动流式审核；tagging_service 合并两个 ThreadPoolExecutor；pull_case 新增 adb 文件列表对比实现增量传输。

**Tech Stack:** Python 3.10+, PyQt5, openpyxl, subprocess (adb/ffmpeg)

---

### Task 1: 压缩→AI 流水线化

**Files:**
- Modify: `video_tagging_assistant/tagging_service.py:148-232`

合并 Phase 1（压缩）和 Phase 2（AI）两个 ThreadPoolExecutor 块为一个流水线：压缩完成一个立即提交对应 AI 任务。

- [ ] **Step 1: 替换两段式 executor 为流水线**

删除现有的两个 `with ThreadPoolExecutor` 块（第 152-208 行附近），替换为：

```python
    # Combined pipeline: compress → immediately submit to AI
    artifacts_by_id: Dict[str, object] = {}
    fresh_results: Dict[str, TaggingReviewRow] = {}
    tasks_by_id: Dict[str, VideoTask] = {}
    total_to_tag = len(to_tag)
    compressed_count = 0
    tagged_count = 0

    with ThreadPoolExecutor(max_workers=max(1, compression_workers)) as compress_pool:
        compress_futures = {}
        for manifest in to_tag:
            task = _manifest_to_video_task(manifest)
            tasks_by_id[manifest.case_id] = task
            f = compress_pool.submit(compressor, task, compressed_dir, compression_config)
            compress_futures[f] = manifest
            event_callback(
                PipelineEvent(
                    case_id=manifest.case_id,
                    stage=RuntimeStage.TAGGING_RUNNING,
                    event_type="info",
                    message="compressing",
                    progress_current=compressed_count,
                    progress_total=total_to_tag,
                )
            )

        with ThreadPoolExecutor(max_workers=max(1, provider_workers)) as ai_pool:
            ai_futures = {}
            for f in as_completed(compress_futures):
                manifest = compress_futures[f]
                try:
                    artifacts_by_id[manifest.case_id] = f.result()
                    compressed_count += 1
                    event_callback(
                        PipelineEvent(
                            case_id=manifest.case_id,
                            stage=RuntimeStage.TAGGING_RUNNING,
                            event_type="info",
                            message="compressed",
                            progress_current=compressed_count,
                            progress_total=total_to_tag,
                        )
                    )
                except Exception as exc:
                    event_callback(
                        PipelineEvent(
                            case_id=manifest.case_id,
                            stage=RuntimeStage.TAGGING_RUNNING,
                            event_type="error",
                            message=f"压缩失败: {exc}",
                        )
                    )
                    continue  # skip AI for this case

                # Immediately submit AI task for this manifest
                task = tasks_by_id[manifest.case_id]
                artifact = artifacts_by_id[manifest.case_id]
                context = build_prompt_context(
                    task, artifact, prompt_template, case_row=_manifest_to_case_row(manifest)
                )
                event_callback(
                    PipelineEvent(
                        case_id=manifest.case_id,
                        stage=RuntimeStage.TAGGING_RUNNING,
                        event_type="info",
                        message="tagging",
                        progress_current=tagged_count,
                        progress_total=total_to_tag,
                    )
                )
                ai_f = ai_pool.submit(_generate_with_retry, provider, context, concurrency)
                ai_futures[ai_f] = manifest

            for ai_f in as_completed(ai_futures):
                manifest = ai_futures[ai_f]
                try:
                    generated = ai_f.result()
                    tagged_count += 1
                    event_callback(
                        PipelineEvent(
                            case_id=manifest.case_id,
                            stage=RuntimeStage.TAGGING_RUNNING,
                            event_type="info",
                            message="tagged",
                            progress_current=tagged_count,
                            progress_total=total_to_tag,
                        )
                    )
                except Exception as exc:
                    event_callback(
                        PipelineEvent(
                            case_id=manifest.case_id,
                            stage=RuntimeStage.TAGGING_RUNNING,
                            event_type="error",
                            message=f"AI 打标失败: {exc}",
                        )
                    )
                    continue

                payload = {
                    "summary_text": generated.summary_text,
                    "tags": [f"{key}={value}" for key, value in generated.structured_tags.items()],
                    "scene_description": generated.scene_description,
                    "structured_tags": generated.structured_tags,
                    "multi_select_tags": generated.multi_select_tags,
                }
                save_cached_result(cache_root, manifest, payload)
                fresh_results[manifest.case_id] = TaggingReviewRow(
                    case_id=manifest.case_id,
                    auto_summary=generated.summary_text,
                    auto_tags=";".join(payload["tags"]),
                    auto_scene_description=generated.scene_description,
                    tag_source="fresh",
                )
```

- [ ] **Step 2: 验证一致性**

确保打标结果与之前行为一致——刷新前后的 TaggingReviewRow 结构、cached_results 合并逻辑不变。

- [ ] **Step 3: Commit**

```bash
git add video_tagging_assistant/tagging_service.py
git commit -m "perf: pipeline compression → AI submission without waiting for all compressions"
```

---

### Task 2: 增量 adb pull + 错误中文化

**Files:**
- Modify: `video_tagging_assistant/case_ingest_orchestrator.py:136-155`

新增 `_adb_list_files` 函数，改写 `pull_case` 为增量拉取，同时为 adb 错误加中文翻译。

- [ ] **Step 1: 新增 `_ADB_ERROR_MAP` 和 `_translate_adb_error` 函数**

在文件顶部（import 之后，第一个函数之前）插入：

```python
_ADB_ERROR_MAP = {
    "device not found": "设备未连接，请检查 USB 线缆并确认 adb devices 可见",
    "no devices": "设备未连接，请检查 USB 线缆并确认 adb devices 可见",
    "permission denied": "权限不足，请在设备端执行 adb root",
    "no such file or directory": "远端路径不存在，请检查 dut_root 配置和 RK 目录名",
    "timeout": "设备响应超时，请重启 adb server（adb kill-server）",
    "timed out": "设备响应超时，请重启 adb server（adb kill-server）",
    "offline": "设备离线，请重新插拔 USB 并等待设备上线",
}


def _translate_adb_error(error: subprocess.CalledProcessError) -> str:
    stderr = (error.stderr or "").lower()
    if isinstance(stderr, bytes):
        stderr = stderr.decode("utf-8", errors="replace")
    for keyword, chinese in _ADB_ERROR_MAP.items():
        if keyword in stderr:
            return f"{chinese}（原始错误: {stderr.strip()}）"
    return f"adb 命令失败: {stderr.strip() or str(error)}"
```

- [ ] **Step 2: 新增 `_adb_list_files` 函数**

```python
def _adb_list_files(adb_exe: str, remote_dir: str, timeout: int = 30) -> dict:
    """通过 adb shell ls -la 获取远端目录文件列表，返回 {filename: size_bytes}。"""
    result = subprocess.run(
        [adb_exe, "shell", "ls", "-la", remote_dir],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode, [adb_exe, "shell", "ls", "-la", remote_dir],
            output=result.stdout, stderr=result.stderr,
        )
    files = {}
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("total ") or line.startswith("d"):
            continue
        # ls -la 输出格式: -rw-rw-rw- 1 root root  12345678 2025-04-29 10:00 filename.rkraw
        parts = line.split()
        if len(parts) >= 5:
            try:
                size = int(parts[4])
            except ValueError:
                continue
            name = parts[-1]
            if name not in (".", ".."):
                files[name] = size
    return files
```

- [ ] **Step 3: 改写 `pull_case` 为增量拉取**

将 `pull_case`（第 136-155 行）替换为：

```python
def pull_case(manifest, config: dict) -> None:
    """增量 pull：对比远端文件列表与本地已有文件，只拉缺失或大小不同的。"""
    rk_suffix = manifest.raw_path.name
    dest = Path(config["local_case_root"]) / f"{manifest.case_id}_RK_raw_{rk_suffix}"
    dest.mkdir(parents=True, exist_ok=True)
    remote_dir = f"{config['dut_root']}/{rk_suffix}"
    adb_exe = config["adb_exe"]
    timeout = int(config.get("adb_pull_timeout", 600))

    try:
        remote_files = _adb_list_files(adb_exe, remote_dir)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(_translate_adb_error(exc)) from exc

    to_pull = {}
    for name, size in remote_files.items():
        local_file = dest / name
        if local_file.exists() and local_file.stat().st_size == size:
            continue
        to_pull[name] = size

    if not to_pull:
        return  # all files already present

    for name in to_pull:
        remote_path = f"{remote_dir}/{name}"
        try:
            subprocess.run(
                [adb_exe, "pull", remote_path, str(dest / name)],
                check=True,
                timeout=timeout,
            )
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(_translate_adb_error(exc)) from exc
```

- [ ] **Step 4: Commit**

```bash
git add video_tagging_assistant/case_ingest_orchestrator.py
git commit -m "feat: incremental adb pull by filename+size; Chinese adb error messages"
```

---

### Task 3: 错误中文化 — rk_alignment_service

**Files:**
- Modify: `video_tagging_assistant/rk_alignment_service.py:233-251`

`_adb_find` 函数 catch `CalledProcessError` 并翻译。

- [ ] **Step 1: 在 `_adb_find` 加入错误翻译**

导入 subprocess 已经存在。将 `_adb_find` 函数体末尾的 bare `raise` 改为带翻译：

```python
def _adb_find(adb_exe: str, target_path: str, extra_args: list[str]) -> list[str]:
    """调用 `adb shell find` 并返回非空输出行。"""
    try:
        result = subprocess.run(
            [adb_exe, "shell", "find", target_path, *extra_args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"adb shell find {target_path} 超时，请检查设备连接状态") from None
    if result.returncode != 0:
        stderr_text = (result.stderr or "").strip()
        stdout_text = (result.stdout or "").strip()
        raw = stderr_text or stdout_text or f"adb shell find failed for {target_path}"
        raise RuntimeError(_translate_adb_stderr(raw))
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]
```

在文件顶部加 `_translate_adb_stderr` 函数（复用同一套关键词映射）：

```python
def _translate_adb_stderr(stderr: str) -> str:
    text = stderr.lower()
    for keyword, chinese in [
        ("device not found", "设备未连接，请检查 USB 线缆并确认 adb devices 可见"),
        ("no devices", "设备未连接，请检查 USB 线缆并确认 adb devices 可见"),
        ("permission denied", "权限不足，请在设备端执行 adb root"),
        ("no such file or directory", "远端路径不存在，请检查 dut_root 配置"),
        ("timeout", "设备响应超时，请重启 adb server（adb kill-server）"),
        ("timed out", "设备响应超时，请重启 adb server（adb kill-server）"),
        ("offline", "设备离线，请重新插拔 USB 并等待设备上线"),
    ]:
        if keyword in text:
            return f"{chinese}（原始错误: {stderr.strip()}）"
    return f"adb 命令失败: {stderr.strip()}"
```

- [ ] **Step 2: Commit**

```bash
git add video_tagging_assistant/rk_alignment_service.py
git commit -m "feat: Chinese error messages for adb shell find failures"
```

---

### Task 4: 审核回退修改（"上一个"按钮）

**Files:**
- Modify: `video_tagging_assistant/gui/review_tab.py`

新增 `← 上一个` 按钮支持回退修改。通过后覆盖写回 xlsx 和 txt（现有 `upsert_create_record_row` 和 `write_case_txt` 已支持覆盖，不需改）。

`_reviewed_history` 记录已通过的 case，回退时恢复字段选择。

- [ ] **Step 1: 在 `__init__` 中新增状态变量**

在第 70 行附近加入：

```python
self._reviewed_history: list = []  # (manifest, tag_result, selections) 元组
self._previous_btn: QPushButton = None
```

- [ ] **Step 2: 在 `_setup_ui` 的按钮行加入"上一个"按钮**

在 `_pass_btn` 和 `_skip_btn` 的 btn_row（第 116-122 行）中加入：

```python
self._previous_btn = QPushButton("← 上一个")
btn_row.addWidget(self._previous_btn)
btn_row.addWidget(self._pass_btn)
btn_row.addWidget(self._skip_btn)
```

在信号连接区（第 124-126 行）加入：

```python
self._previous_btn.clicked.connect(self._go_previous)
```

- [ ] **Step 3: 改写 `_handle_pass` 保存历史**

```python
def _handle_pass(self) -> None:
    ...
    selections = self._collect_selections()
    ...
    tag_result = TagResult(...)
    
    # 保存历史：记录本次通过的 case 和字段选择
    manifest = self._manifests[self._current_index]
    self._reviewed_history.append((manifest, tag_result, selections))
    
    self._awaiting_parent_confirmation = True
    self._sync_action_buttons()
    self.case_approved.emit(manifest, tag_result)
```

- [ ] **Step 4: 新增 `_go_previous` 方法**

```python
def _go_previous(self) -> None:
    """回到上一个 case，恢复其字段选择以供修改。"""
    if not self._reviewed_history:
        return
    if self._current_index == 0:
        return

    self._current_index -= 1
    prev_manifest, prev_tag_result, prev_selections = self._reviewed_history.pop()
    self._show_case(self._current_index)

    # 恢复之前的字段选择
    self._scene_desc_edit.setPlainText(prev_tag_result.scene_description)
    for field, group in self._groups.items():
        target_value = prev_selections.get(field, "")
        for button in group.buttons():
            if button.text() == target_value:
                button.setChecked(True)
                break
```

- [ ] **Step 5: 更新 `_sync_action_buttons` 控制"上一个"启用状态**

```python
def _sync_action_buttons(self) -> None:
    has_current_case = bool(self._manifests) and self._current_index < len(self._manifests)
    allow_actions = has_current_case and not self._awaiting_parent_confirmation
    self._pass_btn.setEnabled(allow_actions)
    self._skip_btn.setEnabled(allow_actions and not self._auto_mode)
    if self._previous_btn:
        self._previous_btn.setEnabled(
            self._current_index > 0 and not self._awaiting_parent_confirmation
        )
```

- [ ] **Step 6: 在 `load_cases` 时清空历史**

```python
def load_cases(self, ...):
    ...
    self._reviewed_history = []
    ...
```

- [ ] **Step 7: Commit**

```bash
git add video_tagging_assistant/gui/review_tab.py
git commit -m "feat: review back button to modify previously approved cases"
```

---

### Task 5: 逐 case 流式审核

**Files:**
- Modify: `video_tagging_assistant/gui/main_window.py`
- Modify: `video_tagging_assistant/gui/review_tab.py`

MainWindow 新增 `_case_readiness` 字典，打标和对齐各自产生结果时交叉检查 readiness。ReviewTab 新增 `add_case()` 增量方法。

- [ ] **Step 1: MainWindow `__init__` 加入 `_case_readiness` 和 `_tagging_results` 缓存**

在第 58 行附近加入：

```python
self._case_readiness: dict = {}     # case_id → {tagged:bool, aligned:bool, ai_result:dict}
self._case_ai_results: dict = {}    # case_id → ai_result（打标产出，等待对齐）
```

- [ ] **Step 2: 改写 `_on_tagging_complete` 为逐 case 模式**

将 `_on_tagging_complete`（第 203-216 行）改为逐 case 注册并检查 readiness：

```python
def _on_tagging_complete(self, results: list) -> None:
    """打标完成：逐个注册 case 结果，与对齐状态交叉检查。"""
    if self._tagging_tab._xlsx_writeback_path:
        self._workbook_path = self._tagging_tab._xlsx_writeback_path
    else:
        self._workbook_path = Path(self._tagging_tab._workbook_edit.text().strip())

    self._auto_execution_enabled = self._tagging_tab.auto_execution_enabled()
    selected_device_info = self._tagging_tab.selected_device_info()
    self._locked_device_info = selected_device_info if isinstance(selected_device_info, dict) else None

    for result in results:
        manifest = result["manifest"]
        ai_result = result["ai_result"]
        cid = manifest.case_id
        entry = self._case_readiness.setdefault(cid, {"tagged": False, "aligned": False, "ai_result": None})
        entry["tagged"] = True
        entry["ai_result"] = ai_result
        if self._auto_execution_enabled and self._locked_device_info:
            self._apply_device_info_to_manifest(manifest, self._locked_device_info)
        if entry["aligned"]:
            self._maybe_add_to_review(manifest, ai_result)

    self._tagging_finished = True
```

- [ ] **Step 3: 改写 `_on_alignment_state_changed` 检查 readiness**

在 `_on_alignment_state_changed` 末尾（确认了 case 之后）加入 readiness 检查逻辑。需要从 alignment_tab 获取刚确认的 case 信息。

实际上 alignment_tab 的 `_confirm_current_case` 在 `confirm_alignment` 后调用 `_render()` 和 `_emit_state_change()`。我们需要在 `_on_alignment_state_changed` 里拿到刚对齐的 case 列表。

新增从对齐状态获取已对齐 case 的能力：

```python
def _on_alignment_state_changed(self, confirmed: int, total: int, blocked: bool) -> None:
    self._alignment_confirmed = confirmed
    self._alignment_total = total
    self._alignment_blocked = blocked
    self._alignment_ready = bool(self._loaded_manifests) and not blocked and confirmed == total

    # 检查每个已对齐 case 的 readiness
    alignment_tab = getattr(self, "_alignment_tab", None)
    if alignment_tab is not None and alignment_tab._state is not None:
        for view_case in alignment_tab._state.aligned_cases:
            cid = view_case.manifest.case_id
            entry = self._case_readiness.setdefault(cid, {"tagged": False, "aligned": False, "ai_result": None})
            was_aligned = entry["aligned"]
            entry["aligned"] = True
            if not was_aligned and entry["tagged"]:
                self._maybe_add_to_review(view_case.manifest, entry["ai_result"])

    if not self._alignment_ready:
        self._tabs.setTabEnabled(2, False)
        self._review_loaded = False
        self._review_tab.setEnabled(False)
        if self._tabs.currentIndex() in (2, 3) and self._tabs.isTabEnabled(1):
            self._tabs.setCurrentIndex(1)
    else:
        self._review_tab.setEnabled(True)

    self._maybe_enter_review()
```

- [ ] **Step 4: 新增 `_maybe_add_to_review` 方法**

```python
def _maybe_add_to_review(self, manifest, ai_result) -> None:
    """单个 case 准备好后加入审核队列。"""
    if manifest.case_id in self._approved_case_ids:
        return

    # 首次加入时初始化审核 Tab
    if not self._review_loaded:
        dut_devices = []
        try:
            dut_devices = load_dut_info(self._workbook_path)
        except Exception:
            pass
        self._tabs.setTabEnabled(2, True)
        self._tabs.setCurrentIndex(2)
        self._review_tab.load_cases(
            [manifest],
            {manifest.case_id: ai_result},
            dut_devices=dut_devices,
            auto_mode=self._auto_execution_enabled,
            locked_device=self._locked_device_info,
        )
        self._review_loaded = True
    else:
        self._review_tab.add_case(manifest, ai_result)
```

- [ ] **Step 5: ReviewTab 新增 `add_case` 方法**

在 `review_tab.py` 加入：

```python
def add_case(self, manifest, ai_result: dict) -> None:
    """增量追加单个 case 到审核队列。"""
    self._manifests.append(manifest)
    self._tagging_results[manifest.case_id] = ai_result
    # 如果当前正在显示"全部审核完毕"，切换到新 case
    if self._current_index >= len(self._manifests) - 1:
        self._sync_action_buttons()
```

- [ ] **Step 6: 在 `_on_batch_loaded` 初始化 `_case_readiness`**

```python
def _on_batch_loaded(self, payload: dict) -> None:
    ...
    self._case_readiness = {}
    self._case_ai_results = {}
    ...
```

- [ ] **Step 7: 保留 `_maybe_enter_review` 作为兜底**

`_maybe_enter_review` 保持不变——当打标和对齐都全体完成时（兜底路径），仍然可以批量装载剩余 case。

- [ ] **Step 8: Commit**

```bash
git add video_tagging_assistant/gui/main_window.py video_tagging_assistant/gui/review_tab.py
git commit -m "feat: streaming per-case review — each case enters review when tagged+aligned"
```

---

## 验证步骤

1. 启动 GUI → 加载工作簿 → 对齐 Tab 打开（DJI 预览帧开始生成）
2. 回到打标 Tab → 选"重新标定" → 点"开始"
3. 去对齐 Tab → 确认几个 case
4. 观察审核 Tab：打标完+对齐完的 case 逐个出现
5. 审核通过一个 case → 点"← 上一个" → 修改字段 → 重新通过
6. 执行 Tab：pull 走增量路径（首次全量，二次秒过）
7. 故意拔掉 USB → 检查 adb 错误是否显示中文提示
