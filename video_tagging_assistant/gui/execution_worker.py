import queue

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtWidgets import QApplication

from video_tagging_assistant.case_ingest_orchestrator import move_case, pull_case, upload_case
from video_tagging_assistant.pipeline_models import CaseManifest

_SENTINEL = None


class ExecutionWorker(QThread):
    """串行执行 pull→move→upload 的后台线程。

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

    def enqueue(self, manifest: CaseManifest) -> None:
        """将 manifest 加入执行队列（线程安全）。"""
        self._queue.put(manifest)

    def stop(self) -> None:
        """发送哨兵值，run() 循环在处理完当前 case 后退出。"""
        self._queue.put(_SENTINEL)

    def wait(self, msecs=None) -> bool:
        """等待线程结束，并在返回前处理挂起的 Qt 事件（确保跨线程信号送达槽函数）。"""
        result = super().wait() if msecs is None else super().wait(msecs)
        app = QApplication.instance()
        if app is not None:
            app.processEvents()
        return result

    def run(self) -> None:
        while True:
            item = self._queue.get()
            if item is _SENTINEL:
                break
            self._process(item)

    def _process(self, manifest: CaseManifest) -> None:
        steps = [
            ("pull", pull_case),
            ("move", move_case),
            ("upload", upload_case),
        ]
        for step_name, step_fn in steps:
            self.status_changed.emit(manifest.case_id, step_name, "started", "")
            try:
                step_fn(manifest, self._config)
                self.status_changed.emit(manifest.case_id, step_name, "completed", "")
            except Exception as exc:
                self.status_changed.emit(manifest.case_id, step_name, "failed", str(exc))
                return  # stop remaining steps for this case; continue queue
