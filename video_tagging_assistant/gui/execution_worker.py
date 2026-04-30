import queue
import threading

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtWidgets import QApplication

from video_tagging_assistant.case_ingest_orchestrator import move_case, pull_case, upload_case
from video_tagging_assistant.pipeline_models import CaseManifest

_SENTINEL = None


class ExecutionWorker(QThread):
    """pull/move 在主工作线程串行执行；upload 在独立后台线程并发执行。

    流程：
        主循环：case1.pull → case1.move → enqueue(case1) → case2.pull → case2.move → ...
        upload线程：                    case1.upload              case2.upload ...

    信号：
        status_changed(case_id, step, status, message)
            step   : "pull" | "move" | "upload"
            status : "started" | "completed" | "failed"
    """

    status_changed = pyqtSignal(str, str, str, str)

    def __init__(self, config: dict, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._queue: queue.Queue = queue.Queue()
        self._upload_queue: queue.Queue = queue.Queue()

    def enqueue(self, manifest: CaseManifest) -> None:
        """将 manifest 加入执行队列（线程安全）。"""
        self._queue.put(manifest)

    def stop(self) -> None:
        """发送哨兵值，run() 循环在处理完当前 case 后退出。"""
        self._queue.put(_SENTINEL)

    def wait(self, msecs=None) -> bool:
        result = super().wait() if msecs is None else super().wait(msecs)
        app = QApplication.instance()
        if app is not None:
            app.processEvents()
        return result

    def run(self) -> None:
        upload_thread = threading.Thread(target=self._upload_loop, daemon=True)
        upload_thread.start()

        while True:
            item = self._queue.get()
            if item is _SENTINEL:
                break
            self._pull_and_move(item)

        self._upload_queue.put(_SENTINEL)
        upload_thread.join()

    def _pull_and_move(self, manifest: CaseManifest) -> None:
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
        while True:
            item = self._upload_queue.get()
            if item is _SENTINEL:
                break
            manifest = item
            self.status_changed.emit(manifest.case_id, "upload", "started", "")
            try:
                upload_case(manifest, self._config)
                self.status_changed.emit(manifest.case_id, "upload", "completed", "")
            except Exception as exc:
                self.status_changed.emit(manifest.case_id, "upload", "failed", str(exc))
