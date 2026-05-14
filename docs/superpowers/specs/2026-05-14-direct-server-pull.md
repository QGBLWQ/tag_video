# RK Raw 直传服务器设计文档

> **基线 commit**: `f543504` — RNDIS HTTP pull speed test

## 目标

消除 pull 流程中 RK raw 数据的本地磁盘中转：设备端数据直接写入服务器目录，不再先落本地再 copy 到服务器。

## 决策记录

| 决策 | 选择 |
|------|------|
| 跳过范围 | 仅 RK raw，DJI 视频保留本地 |
| 执行步骤 | 保持 pull → move → upload 三步 UI 不变 |
| 服务器不可用 | 自动降级到本地模式 |
| DJI 上传 | upload 步骤负责 DJI + txt 补传到服务器 |
| 配置控制 | `direct_server_pull: bool = True` 开关 |

---

## 数据流

### 场景 1：正常（服务器可用）

```
pull:  设备 → 直接解压到服务器 case_xxx_RK_raw/
move:  本地 DJI normal/night → 本地 case 目录（跳过 RK move）
upload: 本地 DJI + txt → 服务器 case 目录 + 写 R
```

### 场景 2：服务器不可用（降级）

```
pull:  检测到服务器不可用 → 本地 case_xxx_RK_raw/（现有逻辑）
move:  本地 RK + DJI → 本地 case 目录（现有逻辑）
upload: 本地 case 目录 → 服务器（现有逻辑）
```

### 场景 3：传输中途失败

```
处理: 清理服务器上不完整的 case_xxx_RK_raw/ 目录
      报错给执行队列（failed 状态）
      用户点重试 → 自动降级到本地模式重传
```

---

## 文件改动

### `video_tagging_assistant/pipeline_models.py`

- `CaseManifest` 新增字段：`rk_on_server: bool = False`

### `video_tagging_assistant/case_ingest_orchestrator.py`

**`pull_case(manifest, config, progress_cb, server_dest=None)`**
- 新增可选参数 `server_dest: Optional[Path]`
- 若 `server_dest` 不为 None 且路径可达（父目录可创建），则 pul dest 直接填 server 目录
- 成功后将 `manifest.rk_on_server = True`
- 否则走现有本地逻辑，`rk_on_server = False`

**`move_case(manifest, config)`**
- 新增判断 `if manifest.rk_on_server`：
  - 只创建本地 case 目录，只 copy DJI normal/night
  - 跳过 RK raw 的 `shutil.move`
- 否则走现有逻辑

**`upload_case(manifest, config, progress_cb)`**
- 新增判断 `if manifest.rk_on_server`：
  - 只上传 DJI normal/night 文件 + txt
  - 跳过整个目录的 `_copytree_with_progress`
- 否则走现有逻辑

**新增辅助函数**：
- `_server_reachable(server_path: Path) -> bool` — 尝试 `server_path.parent.mkdir(exist_ok=True)` + 写一个小测试文件验证可达性

### `video_tagging_assistant/gui/execution_worker.py`

**`run()` 方法**：
- pull 之前构造 `server_dest`：
  ```python
  server_dest = _build_server_dest(manifest, self._config)
  ```
- 传递给 `pull_case(manifest, config, progress_cb, server_dest=server_dest)`

**新增 `_build_server_dest(manifest, config)`**：
- 从 `config["server_upload_root"]` + `manifest.mode` + `manifest.created_date` + `manifest.case_id` + `_RK_raw_{suffix}` 拼路径
- 检查 `_server_reachable` → 返回 Path 或 None

### `video_tagging_assistant/config.py` (或对应 config 读取处)

- 新增配置项：`direct_server_pull: bool = True`（默认开启直传）

---

## 错误处理

| 场景 | 处理 |
|------|------|
| server 不可达（pull 前） | `server_dest = None`，走本地降级 |
| server 中途断开（pull 中） | 捕获 Exception → 清理 server 残留目录 → emit pull failed |
| 重试按钮 | 走本地降级（不再尝试 server） |
| `direct_server_pull = False` | 完全跳过直传，和现有行为一致 |

---

## 兼容性

- `pull_mode` 的三种模式（tcp/tar/adb）全部兼容
- 各模式的 dest 参数统一改为可接受 server 路径
- 现有 `_pull_via_adb` / `_pull_via_tar` / `_pull_via_tcp` 的 dest 参数直接填 server 路径即可，无需修改内部实现
- 如果 server 是 UNC 路径（`\\server\share\...`），Windows tar / 7-Zip 解压到 UNC 路径正常
