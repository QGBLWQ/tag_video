# 多设备并行工作设计文档

> **基线 commit**: `e4102ef`

## 目标

支持多台 Android 设备同时连接到一台 PC，各自独立执行 pull/move/upload 流水线。

## 关键决策

| 决策 | 选择 |
|------|------|
| Case 分配 | 加载工作簿时通过 DJI 文件名匹配确定归属设备 |
| 执行模式 | 每台设备独立 ExecutionWorker，并行执行 |
| 隔离范围 | 端口范围隔离 + DJI 目录隔离 + 服务器路径按设备标号分 |
| 设备发现 | 启动时 `adb devices` 自动检测，用户手动分配标号 |
| xlsm 写入 | 复用现有乱序写入机制 |

---

## 新增数据结构

### DeviceProfile

```python
@dataclass
class DeviceProfile:
    serial: str          # adb 设备序列号 "e4e06e1f59b112c4"
    label: str           # 用户分配的标号 "M1_3"
    dut_root: str        # 设备端数据根目录 "/mnt/nvme/CapturedData"
    dji_dir: Path        # PC 端临时 DJI 目录 "tools/_dji_M1_3"
    port_base: int        # 端口范围起始 5555/5600/5655
    worker: object       # 对应的 ExecutionWorker
    status: str          # "idle" / "busy" / "offline"
```

---

## 文件改动清单

### 1. `video_tagging_assistant/device_profile.py`（新建）

`DeviceProfile` dataclass 定义。

### 2. `video_tagging_assistant/device_manager.py`（新建）

- 启动时 `adb devices` 扫描
- 弹出设备标号对话框（用户分配 label）
- 创建 DeviceProfile 列表
- 提供 `get_device_by_label(label)` 查询

### 3. `video_tagging_assistant/gui/device_setup_dialog.py`（新建）

设备标号分配对话框。列表显示 `serial → [label输入框] → [dji目录选择按钮]`

### 4. `video_tagging_assistant/gui/main_window.py`

- 启动时调用 DeviceManager 扫描分配设备
- 创建多个 ExecutionWorker（每台设备一个）
- 更新 ExecutionTab 显示多设备状态

### 5. `video_tagging_assistant/gui/execution_worker.py`

- `_alloc_forward_port` 改为接收 `port_base` 参数
- `_build_server_dest` 中加入设备 label：`server_root/label/mode/date/case_id`

### 6. `video_tagging_assistant/gui/execution_tab.py`

- 队列列表改为显示 case 归属设备
- 进度条区分设备

### 7. `video_tagging_assistant/case_ingest_orchestrator.py`

- `pull_case`, `move_case`, `upload_case` 签名加 `device: DeviceProfile` 参数
- 内部 `adb_exe` 替换为 `adb -s SERIAL`
- `_alloc_forward_port` 改为接收 `port_base`

### 8. `video_tagging_assistant/excel_workbook.py`

- `load_get_list_manifests` 新增 DJI 文件名→设备标号匹配逻辑

---

## 数据流

### 初始化

```
adb devices → 发现 2 台设备
    ↓
用户分配:  serial1 → M1_3, serial2 → M2_2
    ↓
创建: DeviceProfile(M1_3), DeviceProfile(M2_2)
    ↓
创建: ExecutionWorker(M1_3), ExecutionWorker(M2_2)
```

### 加载工作簿

```
load_get_list_manifests()
    ↓
扫描 DJI 目录:  _dji_M1_3/ 和 _dji_M2_2/
    ↓
匹配 case 的 vs_normal_name → 确定归属设备
    ↓
manifest.device_label = "M1_3"
```

### 执行

```
Case 入执行队列（带 device_label）
    ↓
ExecutionWorker(M1_3) 空闲 → 取 label=M1_3 的 case → pull(device=M1_3)
ExecutionWorker(M2_2) 空闲 → 取 label=M2_2 的 case → pull(device=M2_2)
    ↓
并行 pull → move(DJI 从对应 dji_dir 取) → upload(写到 server/M1_3/...)
```

---

## 端口隔离

每台设备分配 50 个端口：

| 设备 | 端口范围 |
|------|---------|
| 设备 1 | 5555 - 5604 |
| 设备 2 | 5605 - 5654 |
| ... | ... |

---

## 服务器路径

```
server_upload_root/
  ├── M1_3/
  │   └── OV50H40_Action5Pro_DCG HDR/20260513/case_0204/
  │       ├── case_0204_RK_raw_117/
  │       ├── case_0204_dji.mp4
  │       └── case_0204.txt
  └── M2_2/
      └── .../
```

DeviceProfile 的 `label` 直接作为服务器路径中的设备目录名。

---

## 兼容性

- `config` 中保留 `adb_exe` 作为全局默认（单设备模式回退）
- 未检测到多设备时，行为与当前完全一致
- `pull_mode` 配置保持不变
