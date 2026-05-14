# RK Raw 直传服务器 — 实现计划

> **For agentic workers:** Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 消除 RK raw 数据的本地磁盘中转，设备端数据直接解压到服务器目录

**Architecture:** pull_case 新增 server_dest 可选参数，传递到 pull_via_xxx 作为 dest；move_case/upload_case 根据 manifest.rk_on_server 标记跳过 RK 操作

**Tech Stack:** Python 3.8+, openpyxl, subprocess, pathlib

---

## 文件改动清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `video_tagging_assistant/pipeline_models.py` | 修改 | CaseManifest 加 rk_on_server 字段 |
| `video_tagging_assistant/case_ingest_orchestrator.py` | 修改 | pull_case/move_case/upload_case + 新增 _server_reachable |
| `video_tagging_assistant/gui/execution_worker.py` | 修改 | 构造 server_dest 传入 pull_case |

---

### Task 1: CaseManifest 新增 rk_on_server 字段

**Files:**
- Modify: `video_tagging_assistant/pipeline_models.py`

- [ ] **Step 1: 加字段**

```python
# 在 CaseManifest 的 labels 字段之后加一行
rk_on_server: bool = False
```

- [ ] **Step 2: 验证**

```bash
python -c "from video_tagging_assistant.pipeline_models import CaseManifest; m = CaseManifest(case_id='test', row_index=1, created_date='', mode='', raw_path='.', vs_normal_path='.', vs_night_path='.', local_case_root='.', server_case_dir='.', remark=''); assert m.rk_on_server == False; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add video_tagging_assistant/pipeline_models.py
git commit -m "feat: add rk_on_server flag to CaseManifest"
```

---

### Task 2: 新增 _server_reachable 检测函数

**Files:**
- Modify: `video_tagging_assistant/case_ingest_orchestrator.py`

- [ ] **Step 1: 在 _copytree_with_progress 之前插入函数**

```python
def _server_reachable(server_path: str) -> bool:
    """检测服务器路径是否可写。返回 True 表示可达。"""
    import os as _os
    parent = str(Path(server_path).parent)
    try:
        _os.makedirs(parent, exist_ok=True)
        # 尝试创建一个测试文件验证可达性
        test_file = _os.path.join(parent, ".pull_write_test")
        with open(test_file, "w") as f:
            f.write("ok")
        _os.remove(test_file)
        return True
    except Exception:
        return False
```

- [ ] **Step 2: 验证语法**

```bash
python -c "import py_compile; py_compile.compile('video_tagging_assistant/case_ingest_orchestrator.py', doraise=True); print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add video_tagging_assistant/case_ingest_orchestrator.py
git commit -m "feat: add _server_reachable detection function"
```

---

### Task 3: pull_case 支持 server_dest 直传模式

**Files:**
- Modify: `video_tagging_assistant/case_ingest_orchestrator.py:pull_case`

- [ ] **Step 1: 修改 pull_case 签名和逻辑**

当前签名：
```python
def pull_case(manifest, config: dict, progress_cb=None) -> None:
```

改为：
```python
def pull_case(manifest, config: dict, progress_cb=None, server_dest=None) -> None:
    """增量 pull。若 server_dest 可达，RK 直接解压到服务器，跳过本地。

    Args:
        server_dest: 服务器上 case_RK_raw 目录的完整路径，若为 None 或不可达则走本地。
    """
```

- [ ] **Step 2: 修改 dest 计算逻辑**

当前代码第 663-664 行：
```python
    rk_suffix = manifest.raw_path.name
    dest = Path(config["local_case_root"]) / f"{manifest.case_id}_RK_raw_{rk_suffix}"
    dest.mkdir(parents=True, exist_ok=True)
```

改为：
```python
    rk_suffix = manifest.raw_path.name

    # 确定目标目录：优先直传服务器
    use_server = False
    if server_dest and config.get("direct_server_pull", True):
        server_path = str(server_dest)
        if _server_reachable(server_path):
            use_server = True
            dest = Path(server_path)
            if progress_cb:
                progress_cb(0, 1, f"直传服务器: {server_path}")
        elif progress_cb:
            progress_cb(0, 1, "服务器不可达，降级到本地")

    if not use_server:
        dest = Path(config["local_case_root"]) / f"{manifest.case_id}_RK_raw_{rk_suffix}"

    dest.mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 3: 在 pull 成功后设置 rk_on_server 标记**

在 `pull_case` 末尾的 `progress_cb("传输完成")` 之前加：
```python
    manifest.rk_on_server = use_server
```

- [ ] **Step 4: 验证语法**

```bash
python -c "import py_compile; py_compile.compile('video_tagging_assistant/case_ingest_orchestrator.py', doraise=True); print('OK')"
```

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add video_tagging_assistant/case_ingest_orchestrator.py
git commit -m "feat: pull_case supports server_dest for direct RK upload"
```

---

### Task 4: move_case 根据 rk_on_server 跳过 RK move

**Files:**
- Modify: `video_tagging_assistant/case_ingest_orchestrator.py:move_case`

- [ ] **Step 1: 修改 move_case**

当前第 725-760 行，将 RK move 部分包在条件中：

```python
def move_case(manifest, config: dict) -> None:
    """把 pull 下来的 RK 数据与 DJI 视频整理到最终 case 目录。

    rk_on_server=True 时跳过 RK move（RK 已在服务器）。
    """
    rk_suffix = manifest.raw_path.name
    case_id = manifest.case_id
    local_root = Path(config["local_case_root"])
    mode = (manifest.mode or "").strip() or config["mode"]
    dest_dir = local_root / mode / manifest.created_date / case_id
    dest_dir.mkdir(parents=True, exist_ok=True)

    if not manifest.rk_on_server:
        local_rk_dir = local_root / f"{case_id}_RK_raw_{rk_suffix}"
        if local_rk_dir.exists():
            shutil.move(
                str(local_rk_dir),
                str(dest_dir / f"{case_id}_RK_raw_{rk_suffix}"),
            )

    if manifest.vs_normal_path and str(manifest.vs_normal_path) != ".":
        if not manifest.vs_normal_path.exists():
            raise FileNotFoundError(
                f"DJI 普通视频不存在，请检查 dji_nomal_dir 配置: {manifest.vs_normal_path}"
            )
        shutil.copy2(
            str(manifest.vs_normal_path),
            str(dest_dir / f"{case_id}_{manifest.vs_normal_path.name}"),
        )
    if manifest.vs_night_path and str(manifest.vs_night_path) != ".":
        if manifest.vs_night_path.exists():
            shutil.copy2(
                str(manifest.vs_night_path),
                str(dest_dir / f"{case_id}_night_{manifest.vs_night_path.name}"),
            )

    # 清理空的临时目录残留
    for entry in local_root.iterdir():
        if entry.is_dir() and entry.name.startswith(case_id) and not any(entry.iterdir()):
            try:
                entry.rmdir()
            except OSError:
                pass
```

- [ ] **Step 2: 验证语法**

```bash
python -c "import py_compile; py_compile.compile('video_tagging_assistant/case_ingest_orchestrator.py', doraise=True); print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add video_tagging_assistant/case_ingest_orchestrator.py
git commit -m "feat: move_case skips RK move when rk_on_server=True"
```

---

### Task 5: upload_case 根据 rk_on_server 跳过 RK 上传

**Files:**
- Modify: `video_tagging_assistant/case_ingest_orchestrator.py:upload_case`

- [ ] **Step 1: 修改 upload_case**

当前第 873-890 行，在开头加 rk_on_server 判断：

```python
def upload_case(manifest, config: dict, progress_cb=None) -> None:
    """上传 case 目录到服务器。rk_on_server=True 时只上传 DJI + txt。"""
    local_root = Path(config["local_case_root"])
    server_root = Path(config["server_upload_root"])
    mode = (manifest.mode or "").strip() or config["mode"]
    workers = int(config.get("upload_workers", 8))
    src = local_root / mode / manifest.created_date / manifest.case_id
    dest = server_root / mode / manifest.created_date / manifest.case_id

    if manifest.rk_on_server:
        # RK 已在服务器 — 只补传 DJI normal/night/txt
        dest.parent.mkdir(parents=True, exist_ok=True)
        import shutil as _shutil
        for item in src.iterdir():
            if item.is_dir() and "RK_raw" in item.name:
                continue  # 跳过 RK 目录
            if item.is_dir():
                _shutil.copytree(str(item), str(dest / item.name), dirs_exist_ok=True)
            else:
                _shutil.copy2(str(item), str(dest / item.name))
        return

    # 原有逻辑：整目录上传
    rk_subdir = dest / f"{manifest.case_id}_RK_raw_{manifest.raw_path.name}"
    if rk_subdir.exists() and any(rk_subdir.iterdir()):
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    _copytree_with_progress(src, dest, progress_cb, workers=workers)
```

- [ ] **Step 2: 验证语法**

```bash
python -c "import py_compile; py_compile.compile('video_tagging_assistant/case_ingest_orchestrator.py', doraise=True); print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add video_tagging_assistant/case_ingest_orchestrator.py
git commit -m "feat: upload_case skips RK upload when rk_on_server=True"
```

---

### Task 6: execution_worker 构造 server_dest 传入 pull_case

**Files:**
- Modify: `video_tagging_assistant/gui/execution_worker.py:run`

- [ ] **Step 1: 新增 _build_server_dest 方法**

在 `ExecutionWorker` 类中添加：

```python
def _build_server_dest(self, manifest):
    """构造服务器 RK 目录路径。server_root 不可达时返回 None。"""
    server_root = self._config.get("server_upload_root", "")
    if not server_root:
        return None
    rk_suffix = manifest.raw_path.name
    mode = (manifest.mode or "").strip() or self._config.get("mode", "")
    if not mode:
        return None
    server_dest = (
        Path(server_root) / mode / manifest.created_date / manifest.case_id
        / f"{manifest.case_id}_RK_raw_{rk_suffix}"
    )
    from video_tagging_assistant.case_ingest_orchestrator import _server_reachable
    if _server_reachable(str(server_dest)):
        return server_dest
    return None
```

- [ ] **Step 2: 修改 pull_pool.submit 调用时传 server_dest**

当前 `run()` 第 82-83 行：
```python
f = pull_pool.submit(pull_case, manifest, self._config,
                     progress_cb=_make_pull_cb(manifest.case_id))
```

改为：
```python
server_dest = self._build_server_dest(manifest)
f = pull_pool.submit(pull_case, manifest, self._config,
                     progress_cb=_make_pull_cb(manifest.case_id),
                     server_dest=server_dest)
```

- [ ] **Step 3: 验证语法**

```bash
python -c "import py_compile; py_compile.compile('video_tagging_assistant/gui/execution_worker.py', doraise=True); print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add video_tagging_assistant/gui/execution_worker.py
git commit -m "feat: execution_worker constructs server_dest for direct RK pull"
```

---

### Task 7: 端到端验证

- [ ] **Step 1: 全文件语法检查**

```bash
python -c "
import py_compile
for f in [
    'video_tagging_assistant/pipeline_models.py',
    'video_tagging_assistant/case_ingest_orchestrator.py',
    'video_tagging_assistant/gui/execution_worker.py',
]:
    py_compile.compile(f, doraise=True)
    print(f'OK {f}')
"
```

Expected: all OK

- [ ] **Step 2: 逻辑验证 — 直传模式**

```python
# 模拟直传模式：server 可达 → manifest.rk_on_server 应为 True
from pathlib import Path
from video_tagging_assistant.case_ingest_orchestrator import _server_reachable
import tempfile, os

tmp = tempfile.mkdtemp()
assert _server_reachable(tmp) == True, "临时目录应可达"
os.rmdir(tmp)
print("PASS: _server_reachable works")
```

- [ ] **Step 3: 逻辑验证 — 降级模式**

```python
# 模拟降级：server 不可达 → 应走本地
from pathlib import Path
from video_tagging_assistant.case_ingest_orchestrator import _server_reachable

assert _server_reachable("Z:/nonexistent/path/that/does/not/exist") == False
print("PASS: unreachable path returns False")
```

- [ ] **Step 4: Commit (如果有改动)**

```bash
# 通常不需要额外 commit，除非 Step 2/3 发现 bug 修了
```

---

## 自检清单

| 检查项 | 状态 |
|--------|------|
| Spec 全部覆盖 | pull/move/upload/execution_worker + rk_on_server + _server_reachable |
| 无占位符 | 每步都有完整代码 |
| 类型一致 | rk_on_server 全部为 bool，server_dest 全部为 Optional[Path] |
| 三场景覆盖 | 正常直传 / 降级本地 / 中途失败（现有异常处理 + 重试降级） |
