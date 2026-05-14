# 多设备支持 — 实现计划

> **For agentic workers:** Use superpowers:subagent-driven-development

**Goal:** 支持多台 Android 设备同时连接 PC，case 自动路由到对应设备，单队列串行执行

**Architecture:** DeviceProfile 存储设备配置，pull/move/upload 根据 manifest.device_label 查设备，Case 分配时扫描各设备 DJI 目录，从 xlsm 起始 ID 连续分配

**Tech Stack:** Python 3.8+, PyQt5, openpyxl

---

## 文件改动

| # | 文件 | 类型 |
|---|------|------|
| 1 | `video_tagging_assistant/device_profile.py` | 新建 |
| 2 | `video_tagging_assistant/gui/device_setup_dialog.py` | 新建 |
| 3 | `video_tagging_assistant/excel_workbook.py` | 修改 |
| 4 | `video_tagging_assistant/case_ingest_orchestrator.py` | 修改 |
| 5 | `video_tagging_assistant/gui/execution_worker.py` | 修改 |
| 6 | `video_tagging_assistant/gui/execution_tab.py` | 修改 |
| 7 | `video_tagging_assistant/gui/main_window.py` | 修改 |
| 8 | `video_tagging_assistant/pipeline_models.py` | 修改 |

---

### Task 1: DeviceProfile dataclass

**Files:** Create `video_tagging_assistant/device_profile.py`

```python
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

@dataclass
class DeviceProfile:
    serial: str                                    # "e4e06e1f59b112c4"
    label: str                                     # "M1_3"
    dut_root: str = ""                             # "/mnt/nvme/CapturedData"
    dji_dir: Path = field(default_factory=Path)   # "tools/_dji_M1_3"
    port_base: int = 5555
    adb_prefix: str = ""                           # "-s e4e06e1f59b112c4"

    def __post_init__(self):
        if not self.adb_prefix:
            self.adb_prefix = f"-s {self.serial}"
        if isinstance(self.dji_dir, str):
            self.dji_dir = Path(self.dji_dir)
```

**Commit:**
```bash
git add video_tagging_assistant/device_profile.py
git commit -m "feat: add DeviceProfile dataclass"
```

---

### Task 2: 设备设置对话框

**Files:** Create `video_tagging_assistant/gui/device_setup_dialog.py`

QDialog，展示 `adb devices` 列表，每行：
- serial（只读）
- label 输入框
- "选择 DJI 目录" 按钮
- "确认"按钮

点确认后返回 `List[DeviceProfile]`。

关键代码：
```python
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, 
                           QPushButton, QFileDialog, QFormLayout
from PyQt5.QtCore import Qt
from video_tagging_assistant.device_profile import DeviceProfile

class DeviceSetupDialog(QDialog):
    def __init__(self, serials: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("设备配置")
        self._profiles: list[DeviceProfile] = []
        self._serial_rows: list[tuple[str, QLineEdit, Path]] = []
        
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"检测到 {len(serials)} 台设备，请为每台分配标号和 DJI 目录："))
        
        form = QFormLayout()
        for s in serials:
            label_edit = QLineEdit()
            label_edit.setPlaceholderText("如 M1_3")
            dji_label = QLabel("未选择")
            dji_btn = QPushButton("DJI 目录...")
            
            row = QHBoxLayout()
            row.addWidget(QLabel(s))
            row.addWidget(label_edit)
            row.addWidget(QLabel("DJI:"))
            row.addWidget(dji_label, stretch=1)
            row.addWidget(dji_btn)
            form.addRow(row)
            self._serial_rows.append((s, label_edit, dji_label, dji_btn))
            
            def make_handler(sl=dji_label):
                return lambda: self._pick_dji(sl)
            dji_btn.clicked.connect(make_handler(dji_label))
        
        layout.addLayout(form)
        
        confirm = QPushButton("确认")
        confirm.clicked.connect(self._on_confirm)
        layout.addWidget(confirm)
    
    def _pick_dji(self, label_widget: QLabel):
        path = QFileDialog.getExistingDirectory(self, "选择 DJI 目录")
        if path:
            label_widget.setText(path)
    
    def _on_confirm(self):
        for serial, label_edit, dji_label, _ in self._serial_rows:
            label = label_edit.text().strip()
            dji_path = dji_label.text()
            if not label or dji_path == "未选择":
                continue
            idx = len(self._profiles)
            self._profiles.append(DeviceProfile(
                serial=serial, label=label, dji_dir=dji_path,
                port_base=5555 + idx * 50,
            ))
        self.accept()
    
    def profiles(self) -> list[DeviceProfile]:
        return self._profiles
```

**Commit:**
```bash
git add video_tagging_assistant/gui/device_setup_dialog.py
git commit -m "feat: device setup dialog for multi-device label assignment"
```

---

### Task 3: CaseManifest 加 device_label

**Files:** Modify `video_tagging_assistant/pipeline_models.py`

在 CaseManifest 中加：
```python
device_label: str = ""  # "M1_3" 或空（单设备兼容）
```

**Commit:**
```bash
git add video_tagging_assistant/pipeline_models.py
git commit -m "feat: add device_label to CaseManifest"
```

---

### Task 4: Case 分配逻辑

**Files:** Modify `video_tagging_assistant/excel_workbook.py`

新增函数 `allocate_multi_device_cases`：
```python
def allocate_multi_device_cases(
    workbook_path: Path,
    source_sheet: str,
    devices: dict[str, DeviceProfile],  # label -> profile
) -> dict[str, list[CaseManifest]]:    # label -> manifests
```

流程：
1. 扫描每个 DeviceProfile.dji_dir 的 DJI 文件
2. 读 xlsm 获取下一个 case_id（从 get_next_case_sequence）
3. 按设备 label 顺序分配连续 case_id 块
4. 写入 xlsm「获取列表」新行
5. 返回 `{label: [CaseManifest, ...]}`

（具体实现依赖现有的 `get_next_case_sequence` 和 `load_get_list_manifests`）

**Commit:**
```bash
git add video_tagging_assistant/excel_workbook.py
git commit -m "feat: allocate_multi_device_cases for DJI-to-case_id assignment"
```

---

### Task 5: pull_case/move_case/upload_case + device

**Files:** Modify `video_tagging_assistant/case_ingest_orchestrator.py`

每个函数签名加 `device: DeviceProfile = None`：
- `pull_case`: 用 `device.adb_prefix` 构造 adb 命令，用 `device.port_base` 分配端口，server_dest 包含 `device.label`
- `move_case`: DJI 源路径改为 `device.dji_dir / manifest.vs_normal_path.name`
- `upload_case`: dest 包含 `device.label`

```python
def pull_case(manifest, config: dict, progress_cb=None, server_dest=None,
              device=None) -> None:
    ...
    adb_exe = f"adb {device.adb_prefix}" if device else config["adb_exe"]
```

**Commit:**
```bash
git add video_tagging_assistant/case_ingest_orchestrator.py
git commit -m "feat: route pull/move/upload by device label"
```

---

### Task 6: ExecutionWorker 设备路由

**Files:** Modify `video_tagging_assistant/gui/execution_worker.py`

- 新增 `self._devices: dict[str, DeviceProfile]`（外部注入）
- `_build_server_dest` 中加入 `device.label` 层级
- `_make_pull_cb` / `_do_upload` 中传递 device

**Commit:**
```bash
git add video_tagging_assistant/gui/execution_worker.py
git commit -m "feat: execution_worker device routing"
```

---

### Task 7: ExecutionTab 显示设备标签

**Files:** Modify `video_tagging_assistant/gui/execution_tab.py`

队列项格式：`[M1_3] case_0XXX  pull 45% 650MB 217MB/s`

**Commit:**
```bash
git add video_tagging_assistant/gui/execution_tab.py
git commit -m "feat: show device label in execution tab"
```

---

### Task 8: MainWindow 集成

**Files:** Modify `video_tagging_assistant/gui/main_window.py`

- 启动时如果有设备连接：弹 DeviceSetupDialog
- 将 devices 传给 ExecutionWorker 和 TaggingTab
- 单设备时行为不变

**Commit:**
```bash
git add video_tagging_assistant/gui/main_window.py
git commit -m "feat: main_window multi-device integration"
```

---

### Task 9: 端到端验证

1. 全文件语法检查
2. 模拟单设备场景（不弹对话框）→ 和现在行为一致
3. 模拟多设备场景 → case 正确分配

**Commit:**
```bash
git add ... && git commit -m "test: multi-device end-to-end verification"
```
