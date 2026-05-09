"""执行队列后台线程。

负责串行执行 pull/move，并把 upload 投递到独立后台线程，
通过 Qt 信号把每一步状态与进度回传给执行页。
"""

import queue
import threading
from pathlib import Path

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtWidgets import QApplication

from video_tagging_assistant.case_ingest_orchestrator import move_case, pull_case, upload_case
from video_tagging_assistant.pipeline_models import CaseManifest

_SENTINEL = None


class ExecutionWorker(QThread):
    """执行页的后台 worker。"""

    status_changed = pyqtSignal(str, str, str, str)
    upload_progress = pyqtSignal(str, int, int, str)  # case_id, current, total, filename

    def __init__(self, config: dict, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._queue: queue.Queue = queue.Queue()
        self._upload_queue: queue.Queue = queue.Queue()
        self._abort = threading.Event()

    def enqueue(self, manifest: CaseManifest) -> None:
        """把一个 case 加入执行队列。"""
        self._queue.put(manifest)

    def stop(self) -> None:
        """请求主循环在处理完当前 case 后退出。"""
        self._abort.set()
        self._queue.put(_SENTINEL)

    def wait(self, msecs=None) -> bool:
        """等待线程退出，并顺带处理一次 Qt 事件。"""
        result = super().wait() if msecs is None else super().wait(msecs)
        app = QApplication.instance()
        if app is not None and QThread.currentThread() == app.thread():
            app.processEvents()
        return result

    def run(self) -> None:
        """启动上传线程，并循环处理执行队列。"""
        upload_thread = threading.Thread(target=self._upload_loop, daemon=True)
        upload_thread.start()

        while True:
            item = self._queue.get()
            if item is _SENTINEL:
                break
            self._pull_and_move(item)

        self._upload_queue.put(_SENTINEL)
        upload_thread.join()

        try:
            self.status_changed.disconnect()
            self.upload_progress.disconnect()
        except TypeError:
            pass

    def _pull_and_move(self, manifest: CaseManifest) -> None:
        """顺序执行单个 case 的 pull 与 move。"""
        for step_name, step_fn in [("pull", pull_case), ("move", move_case)]:
            self.status_changed.emit(manifest.case_id, step_name, "started", "")
            try:
                step_fn(manifest, self._config)
                self.status_changed.emit(manifest.case_id, step_name, "completed", "")
            except Exception as exc:
                self.status_changed.emit(manifest.case_id, step_name, "failed", str(exc))
                return
        self._upload_queue.put(manifest)

    def _upload_loop(self) -> None:
        """独立线程消费上传队列，并持续上报进度。"""
        while not self._abort.is_set():
            item = self._upload_queue.get()
            if item is _SENTINEL:
                break
            manifest = item
            if self._abort.is_set():
                break
            self.status_changed.emit(manifest.case_id, "upload", "started", "")
            try:
                def _cb(current, total, filename, cid=manifest.case_id):
                    if not self._abort.is_set():
                        self.upload_progress.emit(cid, current, total, filename)

                upload_case(manifest, self._config, progress_cb=_cb)
                # 先标记 R，再通知完成
                try:
                    from video_tagging_assistant.excel_workbook import mark_row_processed
                    workbook_path = Path(self._config.get("workbook_path", ""))
                    if workbook_path.exists():
                        mark_row_processed(workbook_path, "获取列表", manifest.row_index)
                except Exception as exc:
                    self.status_changed.emit(manifest.case_id, "upload", "completed", f"标记R失败: {exc}")
                    continue
                if not self._abort.is_set():
                    self.status_changed.emit(manifest.case_id, "upload", "completed", "")
            except Exception as exc:
                if not self._abort.is_set():
                    self.status_changed.emit(manifest.case_id, "upload", "failed", str(exc))
