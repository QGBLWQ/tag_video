# 多设备并行工作设计文档

> **基线 commit**: `e4102ef`

## 目标

支持多台 Android 设备同时连接到一台 PC。Case 按设备路由，串行执行（单 pull 线程 + 单 upload 线程），避免手动换 USB。

## 关键决策

| 决策 | 选择 |
|------|------|
| Case 分配 | 用户给每台设备分配 N 个 DJI → 系统从 xlsm 起始 ID 开始连续分配 case_id |
| 执行模式 | 单队列串行：一个 pull 线程 + 一个 upload 线程，设备间自动切换 |
| 隔离范围 | DJI 目录隔离 + 服务器路径按设备 label 分 + 端口按设备分配 |
| 设备发现 | 启动时 `adb devices` 自动检测，用户手动分配标号 |
| xlsm 写入 | 复用现有乱序写入机制 |

### Case 分配示例

```
用户操作:
  M1_3: 放 10 个 DJI 到 tools/_dji_M1_3/
  M2_2: 放 12 个 DJI 到 tools/_dji_M2_2/

系统处理:
  xlsm 当前最终 case_id = 199
  → 随机选 M1_3 先分配: case_0200 ~ case_0209 (10个)
  → M2_2 继续: case_0210 ~ case_0221 (12个)
  → 写入 xlsm「获取列表」(22 个新行)
```

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
    port_base: int        # 端口范围起始 5555 / 5605
```

---

## 文件改动清单

### 1. `video_tagging_assistant/device_profile.py`（新建）

`DeviceProfile` dataclass 定义。

### 2. `video_tagging_assistant/device_manager.py`（新建）

- 启动时 `adb devices` 扫描
- 弹出设备标号对话框（用户分配 label + DJI 目录）
- 创建 DeviceProfile 字典 `{label: profile}`
- 查询方法 `get(label) -> DeviceProfile`

### 3. `video_tagging_assistant/gui/device_setup_dialog.py`（新建）

设备标号分配对话框。列表显示 `serial → [label输入] → [DJI目录选择]`。用户为每台设备指定 label 和 DJI 目录后确认。

### 4. `video_tagging_assistant/gui/main_window.py`

- 启动时调用 DeviceManager.setup() 弹出设备配置对话框
- 将 `devices: dict[label, DeviceProfile]` 传给 ExecutionWorker 和 TaggingTab

### 5. `video_tagging_assistant/gui/execution_worker.py`

- 新增 `_get_device(case) -> DeviceProfile`：根据 manifest 的 device_label 查找设备
- `_build_server_dest(manifest, device)`：服务器路径加 `label` 层级
- `_make_pull_args(manifest, device)`：构造带 `-s SERIAL` 的 adb 参数

### 6. `video_tagging_assistant/case_ingest_orchestrator.py`

- `pull_case`, `move_case`, `upload_case` 新增 `device: DeviceProfile` 参数
- 内部用 `device.serial` 构造 adb 命令
- `_alloc_forward_port` 用 `device.port_base`

### 7. `video_tagging_assistant/excel_workbook.py`

- `allocate_multi_device_cases()`：扫描各设备 DJI 目录 → 分配 case_id → 写入 xlsm

### 8. `video_tagging_assistant/gui/execution_tab.py`

- 队列项显示：`[M1_3] case_0204 pull 45% 650MB 217MB/s`
- 端口状态行显示各设备各自的端口

---

## 数据流

### 初始化

```
adb devices → 发现 2 台设备
    ↓
弹出对话框: 用户分配 label + DJI 目录
    serial1 → "M1_3"  + tools/_dji_M1_3/
    serial2 → "M2_2"  + tools/_dji_M2_2/
    ↓
创建 DeviceManager(profiles)
```

### 加载工作簿 + Case 分配

```
用户点击"加载工作簿"
    ↓
扫描各设备 DJI 目录: _dji_M1_3/ 有 10 个文件, _dji_M2_2/ 有 12 个文件
    ↓
读 xlsm → 下一个 case_id = 200
    ↓
M1_3: case_0200 ~ case_0209 (10个)
M2_2: case_0210 ~ case_0221 (12个)
    ↓
写入 xlsm「获取列表」22 行（RK_raw 待对齐，处理状态空）
    ↓
每个 manifest 带 device_label = "M1_3" 或 "M2_2"
```

### 执行

```
执行队列: [case_0200(M1_3), case_0201(M1_3), ... case_0210(M2_2), ...]
    ↓
pull 线程取 case_0200 → 查设备 M1_3 → adb -s SERIAL pull → server/M1_3/.../RK_raw
    ↓
move 线程: 从 _dji_M1_3/ 取 DJI → 本地 case 目录
    ↓
upload 线程: DJI + txt → server/M1_3/.../
    ↓
pull 线程取 case_0201 → ...（串行，设备自动切换）
```

---

## 服务器路径

```
server_upload_root/
  ├── M1_3/
  │   └── OV50H40_Action5Pro_DCG HDR/20260513/case_0200/
  │       ├── case_0200_RK_raw_117/
  │       ├── case_0200_dji.mp4
  │       └── case_0200.txt
  └── M2_2/
      └── .../
```

---

## 端口

每设备分配 50 端口（只用一个时不会冲突，多设备也隔离）：

| 设备 | 端口范围 |
|------|---------|
| 设备 0 | 5555 - 5604 |
| 设备 1 | 5605 - 5654 |

---

## 兼容性

- 单设备时：device_label=None，行为与当前完全一致
- 多设备时：device_label 路由 pull 目标
- `pull_mode` 不变
