"""执行队列后台线程。

负责串行执行 pull/move，并把 upload 投递到独立后台线程，
通过 Qt 信号把每一步状态与进度回传给执行页。
"""

import queue
import threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
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
    pull_progress = pyqtSignal(str, int, int, str)  # case_id, current, total, message

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
        """流式执行：入队即拉，pull 并发，move 按完成顺序串行，upload 独立线程。"""
        upload_thread = threading.Thread(target=self._upload_loop, daemon=True)
        upload_thread.start()

        pull_workers = int(self._config.get("pull_workers", 2))
        pull_pool = ThreadPoolExecutor(max_workers=pull_workers)
        pending_pulls: dict = {}  # future -> (manifest, move_done_flag)
        move_lock = threading.Lock()

        def _make_pull_cb(cid):
            def _cb(current, total, msg):
                if not self._abort.is_set():
                    self.pull_progress.emit(cid, current, total, msg)
            return _cb

        try:
            while not self._abort.is_set():
                try:
                    item = self._queue.get(timeout=0.5)
                except queue.Empty:
                    # 没有新 case 时，检查已有的 pull 是否完成
                    self._process_completed_pulls(pending_pulls, move_lock)
                    continue

                if item is _SENTINEL:
                    break

                manifest = item
                self.status_changed.emit(manifest.case_id, "pull", "started", "")
                f = pull_pool.submit(pull_case, manifest, self._config,
                                     progress_cb=_make_pull_cb(manifest.case_id))
                pending_pulls[f] = manifest

            # 哨兵收到后等所有 pull 完成
            while pending_pulls:
                self._process_completed_pulls(pending_pulls, move_lock, block=True)

        finally:
            pull_pool.shutdown(wait=False)

        self._upload_queue.put(_SENTINEL)
        upload_thread.join()

        try:
            self.status_changed.disconnect()
            self.upload_progress.disconnect()
            self.pull_progress.disconnect()
        except TypeError:
            pass

    def _process_completed_pulls(self, pending_pulls: dict, lock: threading.Lock,
                                  block: bool = False) -> None:
        """处理已完成的 pull：emit 状态 → move → 入上传队列。"""
        from concurrent.futures import wait, FIRST_COMPLETED

        if not pending_pulls:
            return

        if block:
            done, _ = wait(pending_pulls, return_when=FIRST_COMPLETED)
        else:
            done, _ = wait(pending_pulls, timeout=0.1, return_when=FIRST_COMPLETED)

        for f in done:
            manifest = pending_pulls.pop(f, None)
            if manifest is None:
                continue
            try:
                f.result()
                self.status_changed.emit(manifest.case_id, "pull", "completed", "")
            except Exception as exc:
                self.status_changed.emit(manifest.case_id, "pull", "failed", str(exc))
                continue

            # move 必须串行（同一本地目录操作）
            with lock:
                try:
                    self.status_changed.emit(manifest.case_id, "move", "started", "")
                    move_case(manifest, self._config)
                    self.status_changed.emit(manifest.case_id, "move", "completed", "")
                    self._upload_queue.put(manifest)
                except Exception as exc:
                    self.status_changed.emit(manifest.case_id, "move", "failed", str(exc))

    def _upload_loop(self) -> None:
        """用线程池并发上传，充分利用千兆带宽。"""
        upload_concurrency = int(self._config.get("upload_concurrency", 2))
        upload_pool = ThreadPoolExecutor(max_workers=upload_concurrency)
        pending_uploads: dict = {}

        def _make_upload_cb(manifest):
            def _cb(step, current, total, filename, cid=manifest.case_id):
                if not self._abort.is_set():
                    self.upload_progress.emit(cid, current, total, filename)
            return _cb

        def _do_upload(manifest):
            if self._abort.is_set():
                return
            self.status_changed.emit(manifest.case_id, "upload", "started", "")
            try:
                upload_case(manifest, self._config, progress_cb=_make_upload_cb(manifest))
                try:
                    from video_tagging_assistant.excel_workbook import mark_row_processed
                    workbook_path = Path(self._config.get("workbook_path", ""))
                    if workbook_path.exists():
                        mark_row_processed(workbook_path, "获取列表", manifest.row_index)
                except Exception as exc:
                    self.status_changed.emit(manifest.case_id, "upload", "completed", f"标记R失败: {exc}")
                    return
                if not self._abort.is_set():
                    self.status_changed.emit(manifest.case_id, "upload", "completed", "")
            except Exception as exc:
                if not self._abort.is_set():
                    self.status_changed.emit(manifest.case_id, "upload", "failed", str(exc))

        try:
            while not self._abort.is_set():
                item = self._upload_queue.get()
                if item is _SENTINEL:
                    break
                manifest = item
                f = upload_pool.submit(_do_upload, manifest)
                pending_uploads[f] = manifest
                # 清理已完成的
                done = [f for f in pending_uploads if f.done()]
                for f in done:
                    pending_uploads.pop(f, None)
        finally:
            upload_pool.shutdown(wait=True)
            # 消费队列中剩余（哨兵之后可能还有）
            while not self._upload_queue.empty():
                item = self._upload_queue.get()
                if item is not _SENTINEL:
                    _do_upload(item)
