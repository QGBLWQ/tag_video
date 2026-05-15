"""GUI 主窗口。

负责把打标、对齐、审核、执行四个环节串成一个完整流水线，
并在各个 Tab 之间同步状态、写回结果与投递执行任务。
"""

from copy import deepcopy
import shutil
from pathlib import Path

from PyQt5.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTableView,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from video_tagging_assistant.excel_workbook import (
    find_written_dji_names,
    load_dut_info,
    load_rk_raw_values,
    upsert_create_record_row,
    write_case_txt,
)
from video_tagging_assistant.gui.alignment_tab import AlignmentTab
from video_tagging_assistant.gui.execution_tab import ExecutionTab
from video_tagging_assistant.gui.execution_worker import ExecutionWorker
from video_tagging_assistant.gui.review_panel import ReviewPanel
from video_tagging_assistant.gui.review_tab import ReviewTab
from video_tagging_assistant.gui.table_models import CaseTableModel
from video_tagging_assistant.gui.tagging_tab import TaggingTab
from video_tagging_assistant.rk_alignment_service import build_alignment_batch_state, scan_rk_candidates


class MainWindow(QMainWindow):
    """新版三 Tab 流水线主窗口。"""

    def __init__(self, config: dict, tag_options: dict, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._tag_options = tag_options
        self._workbook_path = Path(config.get("workbook_path", ""))
        self._auto_execution_enabled = False
        self._locked_device_info = None
        self._tagging_finished = False
        self._alignment_ready = False
        self._alignment_blocked = False
        self._alignment_confirmed = 0
        self._alignment_total = 0
        self._loaded_manifests = []
        self._pending_tagging_results = []
        self._review_loaded = False
        self._approved_case_ids = set()
        self._enqueued_case_ids = set()

        self.setWindowTitle("go work!")

        self._worker = ExecutionWorker(config)
        self._worker.start()

        self._tagging_tab = TaggingTab(config)
        self._tagging_tab.set_auto_start_validator(self._validate_auto_start)
        self._alignment_tab = AlignmentTab(config)
        self._review_tab = ReviewTab(config, tag_options)
        self._execution_tab = ExecutionTab(self._worker)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._tagging_tab, "标定")
        self._tabs.addTab(self._alignment_tab, "\u5bf9\u9f50")
        self._tabs.addTab(self._review_tab, "审核")
        self._tabs.addTab(self._execution_tab, "执行队列")
        self._tabs.setTabEnabled(1, False)
        self._tabs.setTabEnabled(2, False)
        self._tabs.setTabEnabled(3, False)

        # 顶部 ADB 状态栏 + tabs
        self._adb_status_label = QLabel("ADB 状态: 检测中...")
        self._adb_status_label.setStyleSheet("padding: 4px 8px; background: #f0f0f0;")
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)
        container_layout.addWidget(self._adb_status_label)
        container_layout.addWidget(self._tabs)
        self.setCentralWidget(container)

        # 启动 ADB 状态服务
        from video_tagging_assistant.gui.adb_status_service import AdbStatusService
        self._adb_status = AdbStatusService(
            adb_exe=config.get("adb_exe", "adb"), parent=self,
        )
        self._adb_status.status_changed.connect(self._on_adb_status_changed)

        self._tagging_tab.batch_loaded.connect(self._on_batch_loaded)
        self._tagging_tab.tagging_complete.connect(self._on_tagging_complete)
        self._tagging_tab.auto_exec_requested.connect(self._on_auto_exec_requested)
        self._alignment_tab.alignment_state_changed.connect(self._on_alignment_state_changed)
        self._alignment_tab.refresh_requested.connect(self._on_alignment_refresh_requested)
        self._review_tab.case_approved.connect(self._on_case_approved)
        self._worker.status_changed.connect(self._execution_tab.on_status_changed)
        self._worker.upload_progress.connect(self._execution_tab.on_upload_progress)
        self._worker.pull_progress.connect(self._execution_tab.on_pull_progress)

    def _apply_device_info_to_manifest(self, manifest, device_info) -> None:
        """把设备信息写回 manifest，并同步更新本地/服务器目标路径。"""
        if not isinstance(device_info, dict):
            return

        module_model = str(device_info.get("模组型号", "")).strip()
        capture_mode = str(device_info.get("采集模式", "")).strip()
        if not module_model or not capture_mode:
            return

        new_mode = f"{module_model}_{capture_mode}"
        manifest.mode = new_mode
        manifest.local_case_root = (
            Path(self._config["local_case_root"]) / new_mode / manifest.created_date / manifest.case_id
        )

        server_upload_root = self._config.get("server_upload_root", "")
        if server_upload_root:
            manifest.server_case_dir = (
                Path(server_upload_root) / new_mode / manifest.created_date / manifest.case_id
            )

    def _write_review_outputs(self, manifest, tag_result) -> Path:
        """将审核通过后的 xlsx/txt 产物写入本地 case 目录。"""
        print(f"[WRITE_OUTPUTS] cid={manifest.case_id} local_root={manifest.local_case_root} "
              f"desc={tag_result.scene_description[:30]}")

        # 校验：本地目录名应包含 case_id
        local_dir = str(manifest.local_case_root)
        if manifest.case_id not in local_dir:
            msg = (f"数据异常！manifest.case_id={manifest.case_id} 但 "
                   f"local_case_root={local_dir} 不包含该 case_id，拒绝写入！")
            print(f"[WRITE_OUTPUTS] ERROR: {msg}")
            raise RuntimeError(msg)

        # 校验：对比 AI 缓存中的画面描述，不一致则警告
        try:
            from pathlib import Path as _P
            from video_tagging_assistant.tagging_cache import load_cached_result
            cache_root = _P(self._config.get("cache_root", "artifacts/cache"))
            cached = load_cached_result(cache_root, manifest)
            if cached:
                expected = cached.get("scene_description", "")
                if expected and expected != tag_result.scene_description:
                    print(f"[WRITE_OUTPUTS] WARNING: cid={manifest.case_id} "
                          f"desc mismatch! cache='{expected[:30]}' vs "
                          f"input='{tag_result.scene_description[:30]}'")
        except Exception:
            pass  # 缓存不可用时不拦截

        if self._workbook_path.exists():
            try:
                upsert_create_record_row(self._workbook_path, manifest, tag_result)
            except Exception as exc:
                raise RuntimeError(f"写回失败: {exc}") from exc

        try:
            txt_path = write_case_txt(manifest, tag_result)
        except Exception as exc:
            raise RuntimeError(f"txt 生成失败: {exc}") from exc

        self.statusBar().showMessage(f"已写入 {manifest.case_id}", 3000)
        return txt_path

    def _sync_case_txt_to_server(self, manifest, txt_path) -> None:
        """在全自动模式下，把刚写出的 txt 补传到服务器 case 目录。

        txt 可能比 rkraw 先到服务器，此时负责创建目录。
        """
        server_case_dir = Path(manifest.server_case_dir)
        if not isinstance(txt_path, Path) or not txt_path.exists():
            return

        dest = server_case_dir / txt_path.name
        print(f"[SYNC_TXT] src={txt_path} -> dest={dest}")
        try:
            server_case_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(txt_path), str(dest))
        except Exception as exc:
            raise RuntimeError(f"txt 上传失败: {exc}") from exc

    def _on_batch_loaded(self, payload: dict) -> None:
        """响应打标页的批次加载事件，初始化对齐页状态。"""
        self._loaded_manifests = list(payload.get("manifests", []))
        self._workbook_path = Path(payload["writeback_workbook"])
        self._tagging_finished = False
        self._alignment_ready = False
        self._alignment_blocked = False
        self._alignment_confirmed = 0
        self._alignment_total = 0
        self._pending_tagging_results = []
        self._review_loaded = False
        self._approved_case_ids = set()
        self._enqueued_case_ids = set()

        try:
            rk_raw_by_row = load_rk_raw_values(self._workbook_path, source_sheet="\u83b7\u53d6\u5217\u8868")
            _, candidates, bad_logs = scan_rk_candidates(
                temp_root=str(self._config.get("temp_path", "")),
                dut_root=str(self._config.get("dut_root", "")),
                adb_exe=str(self._config.get("adb_exe", "adb")),
            )
            initial_state = build_alignment_batch_state(
                manifests=self._loaded_manifests,
                rk_raw_by_row=rk_raw_by_row,
                candidates=candidates,
                bad_directory_logs=bad_logs,
            )
        except Exception as exc:
            initial_state = build_alignment_batch_state(
                manifests=self._loaded_manifests,
                rk_raw_by_row={},
                candidates=[],
                bad_directory_logs=[f"alignment init failed: {exc}"],
            )

        self._tabs.setTabEnabled(1, True)
        self._tabs.setTabEnabled(2, False)
        self._tabs.setTabEnabled(3, False)
        self._alignment_tab.load_batch(
            manifests=self._loaded_manifests,
            workbook_path=Path(payload["source_workbook"]),
            writeback_workbook_path=self._workbook_path,
            initial_state=initial_state,
        )

    def _on_alignment_state_changed(self, confirmed: int, total: int, blocked: bool) -> None:
        """接收对齐页状态变化，并决定审核页是否允许进入。"""
        self._alignment_confirmed = confirmed
        self._alignment_total = total
        self._alignment_blocked = blocked
        self._alignment_ready = bool(self._loaded_manifests) and not blocked and confirmed == total

        if not self._alignment_ready:
            self._tabs.setTabEnabled(2, False)
            self._review_loaded = False
            self._review_tab.setEnabled(False)
            if self._tabs.currentIndex() in (2, 3) and self._tabs.isTabEnabled(1):
                self._tabs.setCurrentIndex(1)
        else:
            self._review_tab.setEnabled(True)

        self._maybe_enter_review()

    def _validate_auto_start(self) -> bool:
        """全自动模式启动前检查对齐是否完成。"""
        if not self._alignment_ready:
            self.statusBar().showMessage("请先完成全部 case 对齐后再开启自动执行", 5000)
        return bool(self._alignment_ready)

    def _on_auto_exec_requested(self) -> None:
        """全自动模式：打标开始时立即入队（与打标并行执行 pull+upload）。"""
        device_info = self._tagging_tab.selected_device_info()
        locked_device = device_info if isinstance(device_info, dict) else None
        for manifest in self._loaded_manifests:
            self._apply_device_info_to_manifest(manifest, locked_device)
            if manifest.case_id not in self._enqueued_case_ids:
                self._tabs.setTabEnabled(3, True)
                self._execution_tab.add_case(deepcopy(manifest))
                self._enqueued_case_ids.add(manifest.case_id)

    def _on_tagging_complete(self, results: list) -> None:
        """保存打标结果与模式选择，等待进入审核阶段。"""
        self._workbook_path = self._tagging_tab._writeback_path or Path(self._tagging_tab._workbook_edit.text().strip())

        self._auto_execution_enabled = self._tagging_tab.auto_execution_enabled()
        selected_device_info = self._tagging_tab.selected_device_info()
        self._locked_device_info = selected_device_info if isinstance(selected_device_info, dict) else None

        self._pending_tagging_results = list(results)
        self._tagging_finished = True

        if self._review_loaded:
            self._review_tab.update_case_results(results)
            return

        self._maybe_enter_review()

    def _maybe_enter_review(self) -> None:
        """在打标和对齐都完成后，正式装载审核页。"""
        if self._review_loaded:
            return
        if not self._tagging_finished or not self._alignment_ready:
            return

        remaining_results = [
            result
            for result in self._pending_tagging_results
            if result["manifest"].case_id not in self._approved_case_ids
        ]
        if not remaining_results:
            return

        manifests = [result["manifest"] for result in remaining_results]
        tagging_results = {
            result["manifest"].case_id: result["ai_result"]
            for result in remaining_results
        }

        # 检测"已写入但未执行"的 case：DJI 文件名已在"创建记录"VS_Nomal 中，
        # 但"获取列表"处理状态未 R（manifests 已排除 R 行，所以这里全都是未 R 的）
        written_names = find_written_dji_names(self._workbook_path)
        # VS_Nomal 存的是 "{case_id}_{dji_name}"。
        # 不能拼 manifest.case_id，因为重启后 get_next_case_sequence 会跳过已审批的序号，
        # 导致同一个 DJI 被分配新的 case_id。改用 DJI 文件名做 endswith 匹配。
        already_written = []
        print(f"[DETECT_WRITTEN] checking {len(manifests)} manifests "
              f"against {len(written_names)} written names")
        for m in manifests:
            dji_name = m.vs_normal_path.name
            hit = any(w.endswith(dji_name) for w in written_names)
            print(f"[DETECT_WRITTEN]   manifest={m.case_id} dji={dji_name} hit={hit}")
            if hit:
                already_written.append(m)
        if not already_written:
            print(f"[DETECT_WRITTEN] no matches found")
        if already_written:
            lines = "\n".join(f"  • {m.case_id}  ({m.vs_normal_path.name})"
                              for m in already_written)
            reply = QMessageBox.question(
                self,
                "检测到已写入记录的 case",
                (f"以下 {len(already_written)} 个 case 在"
                 f"'创建记录'中已存在记录，但未标记为已执行：\n\n"
                 f"{lines}\n\n"
                 "是否直接加入执行队列（跳过重新审核）？"),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if reply == QMessageBox.Yes:
                # 这些 case 直接入队，不进审核
                for manifest in already_written:
                    if self._auto_execution_enabled and self._locked_device_info:
                        self._apply_device_info_to_manifest(
                            manifest, self._locked_device_info)
                    if manifest.case_id not in self._enqueued_case_ids:
                        self._tabs.setTabEnabled(3, True)
                        self._execution_tab.add_case(deepcopy(manifest))
                        self._enqueued_case_ids.add(manifest.case_id)
                    self._approved_case_ids.add(manifest.case_id)
                # 从审核队列剔除
                skip_ids = {m.case_id for m in already_written}
                manifests = [m for m in manifests if m.case_id not in skip_ids]
                tagging_results = {cid: r for cid, r in tagging_results.items()
                                   if cid not in skip_ids}

        if not manifests:
            # 全部被直接入队，不需要再进审核
            return

        dut_devices = []
        try:
            dut_devices = load_dut_info(self._workbook_path)
        except Exception:
            pass

        if self._auto_execution_enabled and self._locked_device_info:
            for manifest in manifests:
                self._apply_device_info_to_manifest(manifest, self._locked_device_info)

        self._tabs.setTabEnabled(2, True)
        self._tabs.setCurrentIndex(2)
        self._review_tab.load_cases(
            manifests,
            tagging_results,
            dut_devices=dut_devices,
            auto_mode=self._auto_execution_enabled,
            locked_device=self._locked_device_info,
        )

        if not self._auto_execution_enabled and not dut_devices:
            self._review_tab._device_combo.clear()
            self._review_tab._device_combo.setEnabled(True)

        self._review_loaded = True

    def _on_case_approved(self, manifest, tag_result) -> None:
        """处理单个 case 审核通过后的写回、补传与执行入队。"""
        if not self._alignment_ready:
            self._review_tab._awaiting_parent_confirmation = False
            self._review_tab._sync_action_buttons()
            self.statusBar().showMessage("alignment is no longer ready", 0)
            return

        if not self._auto_execution_enabled:
            self._apply_device_info_to_manifest(manifest, tag_result.device_info)

        try:
            txt_path = self._write_review_outputs(manifest, tag_result)
            if self._auto_execution_enabled:
                self._sync_case_txt_to_server(manifest, txt_path)
        except Exception as exc:
            self._review_tab._awaiting_parent_confirmation = False
            self._review_tab._sync_action_buttons()
            self.statusBar().showMessage(str(exc), 0)
            return

        self._approved_case_ids.add(manifest.case_id)
        self._review_tab.advance_after_approval()

        # 非自动模式：审核通过后入队执行；自动模式已在 _maybe_enter_review 入队
        if not self._auto_execution_enabled and manifest.case_id not in self._enqueued_case_ids:
            self._tabs.setTabEnabled(3, True)
            self._execution_tab.add_case(deepcopy(manifest))
            self._enqueued_case_ids.add(manifest.case_id)

    def _on_adb_status_changed(self, connected: bool, serial: str) -> None:
        """ADB 设备状态变化时更新顶部状态栏。"""
        if connected:
            self._adb_status_label.setText(f"ADB 状态: 🟢 已连接  (序列号: {serial})")
            self._adb_status_label.setStyleSheet(
                "padding: 4px 8px; background: #e8f5e9; color: #1b5e20;")
        else:
            self._adb_status_label.setText("ADB 状态: 🔴 未连接 — 请检查 USB 线缆")
            self._adb_status_label.setStyleSheet(
                "padding: 4px 8px; background: #ffebee; color: #b71c1c;")

    def _on_alignment_refresh_requested(self) -> None:
        """对齐页"刷新设备"按钮：重新扫描 RK 候选并重建对齐状态。"""
        if not self._loaded_manifests:
            self.statusBar().showMessage("尚未加载批次，无法刷新", 3000)
            return
        try:
            rk_raw_by_row = load_rk_raw_values(
                self._workbook_path, source_sheet="获取列表")
            _, candidates, bad_logs = scan_rk_candidates(
                temp_root=str(self._config.get("temp_path", "")),
                dut_root=str(self._config.get("dut_root", "")),
                adb_exe=str(self._config.get("adb_exe", "adb")),
            )
            new_state = build_alignment_batch_state(
                manifests=self._loaded_manifests,
                rk_raw_by_row=rk_raw_by_row,
                candidates=candidates,
                bad_directory_logs=bad_logs,
            )
        except Exception as exc:
            self.statusBar().showMessage(f"刷新失败: {exc}", 5000)
            return
        self._alignment_tab.load_batch(
            manifests=self._loaded_manifests,
            workbook_path=self._workbook_path,
            writeback_workbook_path=self._workbook_path,
            initial_state=new_state,
        )
        self.statusBar().showMessage(
            f"已刷新，找到 {len(candidates)} 个 RK 候选", 3000)

    def closeEvent(self, event) -> None:
        """窗口关闭时优雅停止对齐预处理线程与执行线程。"""
        if hasattr(self, "_adb_status"):
            self._adb_status.stop()
        alignment_tab = getattr(self, "_alignment_tab", None)
        shutdown_error = None
        try:
            if alignment_tab is not None and hasattr(alignment_tab, "shutdown"):
                alignment_tab.shutdown()
        except Exception as exc:
            shutdown_error = exc

        self._worker.stop()
        if not self._worker.wait(3000):
            self._worker.terminate()
            self._worker.wait(1000)

        if shutdown_error is not None:
            event.ignore()
            self.statusBar().showMessage(f"alignment shutdown failed: {shutdown_error}", 0)
            return

        super().closeEvent(event)


# ---------------------------------------------------------------------------
# 旧版窗口：仅为兼容历史 app.py 调用方式和旧测试保留
# ---------------------------------------------------------------------------


class PipelineMainWindow(QMainWindow):
    """旧版简化流水线窗口。"""

    def __init__(
        self,
        workbook_path=None,
        scan_cases=None,
        start_tagging=None,
        refresh_excel_reviews=None,
        run_execution_case=None,
        controller=None,
    ):
        super().__init__()
        self.workbook_path = workbook_path
        self._scan_cases = scan_cases
        self._start_tagging = start_tagging
        self._refresh_excel_reviews = refresh_excel_reviews
        self._run_execution_case = run_execution_case
        self._controller = controller
        self._manifests_by_case_id = {}
        self._review_rows_by_case_id = {}

        self.setWindowTitle("Case Pipeline")
        self.queue_model = CaseTableModel([])
        self.queue_table = QTableView()
        self.queue_table.setModel(self.queue_model)
        self.review_panel = ReviewPanel(
            on_approve=self._handle_approve,
            on_approve_after_edit=self._handle_approve_after_edit,
            on_reject=self._handle_reject,
            on_refresh_excel_reviews=self._handle_refresh_excel_reviews,
        )

        self.tabs = QTabWidget()
        self.tabs.addTab(self.queue_table, "今日队列")
        self.tabs.addTab(self.review_panel, "打标审核")
        self.tabs.addTab(self._placeholder_tab("执行监控"), "执行监控")
        self.tabs.addTab(self._placeholder_tab("失败重试"), "失败重试")

        self.tagging_mode_combo = QComboBox()
        self.tagging_mode_combo.addItems(["重新打标", "复用旧打标结果"])
        self.scan_button = QPushButton("扫描新增记录")
        self.start_button = QPushButton("启动流水线")
        self.log_panel = QTextEdit()
        self.log_panel.setReadOnly(True)

        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.addWidget(self.tagging_mode_combo)
        header_layout.addWidget(self.scan_button)
        header_layout.addWidget(self.start_button)

        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.addWidget(header)
        layout.addWidget(self.tabs)
        layout.addWidget(self.log_panel)
        self.setCentralWidget(wrapper)

        self.scan_button.clicked.connect(self._handle_scan)
        self.start_button.clicked.connect(self._handle_start)

    def _selected_tagging_mode(self) -> str:
        """把界面文案转换成旧流程内部使用的模式值。"""
        return "cached" if self.tagging_mode_combo.currentText() == "复用旧打标结果" else "fresh"

    def _handle_pipeline_event(self, event) -> None:
        """接收旧控制器事件并写入日志面板。"""
        stage_value = getattr(event.stage, "value", str(event.stage))
        self.append_log_line(f"{event.case_id} [{stage_value}] {event.message}")

    def _handle_scan(self):
        """扫描可处理 case，并刷新旧版队列表格。"""
        manifests = self._scan_cases() if self._scan_cases is not None else []
        self._manifests_by_case_id = {manifest.case_id: manifest for manifest in manifests}
        self.queue_model.set_rows(
            [
                {
                    "case_id": manifest.case_id,
                    "stage": "queued",
                    "tag_source": "",
                    "message": manifest.remark,
                }
                for manifest in manifests
            ]
        )
        self.append_log_line(f"Scanned {len(manifests)} cases")

    def _handle_start(self):
        """按旧流程启动打标，并把首个结果加载进审核面板。"""
        manifests = list(self._manifests_by_case_id.values())
        if not manifests or self._start_tagging is None:
            return
        results = self._start_tagging(manifests, self._selected_tagging_mode(), self._handle_pipeline_event)
        self._review_rows_by_case_id = {row.case_id: row for row in results}
        if results:
            self.review_panel.set_review_row(results[0])
            self.tabs.setCurrentIndex(1)

    def _approve_case(self, case_id: str, label: str) -> None:
        """通过旧控制器确认 case，并在成功后触发执行。"""
        if self._controller is None:
            return
        approved = self._controller.approve_case(case_id)
        self.append_log_line(f"{case_id} {label}")
        if approved and self._run_execution_case is not None:
            self._run_execution_case(case_id)

    def _handle_approve(self):
        """处理旧审核面板的直接通过操作。"""
        payload = self.review_panel.current_review_payload()
        self._approve_case(payload["case_id"], "approved in gui")

    def _handle_approve_after_edit(self):
        """处理旧审核面板的修改后通过操作。"""
        payload = self.review_panel.current_review_payload()
        self._approve_case(payload["case_id"], "approved after edit in gui")

    def _handle_reject(self):
        """记录旧审核面板的驳回动作。"""
        payload = self.review_panel.current_review_payload()
        self.append_log_line(f"{payload['case_id']} rejected in gui")

    def _handle_refresh_excel_reviews(self):
        """从 Excel 读取外部审核结果，并回灌到旧执行流程。"""
        rows = self._refresh_excel_reviews() if self._refresh_excel_reviews is not None else []
        for row in rows:
            self._approve_case(row["case_id"], f"approved from excel: {row['review_decision']}")

    def _placeholder_tab(self, text: str):
        """构造旧版占位页。"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addWidget(QLabel(text))
        return widget

    def append_log_line(self, line: str):
        """向旧版日志面板追加一行文本。"""
        self.log_panel.append(line)
