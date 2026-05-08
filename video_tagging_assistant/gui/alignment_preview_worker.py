from __future__ import annotations

import hashlib
import threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtWidgets import QApplication

from video_tagging_assistant.alignment_preview import (
    build_dji_preview_frames,
    resolve_alignment_preview_settings,
)


class AlignmentPreviewWorker(QThread):
    preview_result = pyqtSignal(object)
    log_message = pyqtSignal(str)

    def __init__(self, config: dict, manifests: list, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._manifests = list(manifests)
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()
        self.requestInterruption()

    def wait(self, msecs=None) -> bool:
        result = super().wait() if msecs is None else super().wait(msecs)
        app = QApplication.instance()
        if app is not None:
            app.processEvents()
        return result

    def run(self) -> None:
        frame_count, skip_frames, worker_count, logs = resolve_alignment_preview_settings(self._config)
        for message in logs:
            if self._stop_event.is_set():
                return
            self.log_message.emit(message)

        if not self._manifests:
            return

        pending_manifests = list(self._manifests)
        active_futures = {}
        executor = ThreadPoolExecutor(max_workers=worker_count)
        try:
            while (pending_manifests or active_futures) and not self._stop_event.is_set():
                while pending_manifests and len(active_futures) < worker_count and not self._stop_event.is_set():
                    manifest = pending_manifests.pop(0)
                    future = executor.submit(self._prepare_case_preview, manifest, frame_count, skip_frames)
                    active_futures[future] = manifest

                if not active_futures:
                    break

                done_futures, _ = wait(active_futures, timeout=0.1, return_when=FIRST_COMPLETED)
                for future in done_futures:
                    active_futures.pop(future, None)
                    if self._stop_event.is_set():
                        continue
                    self.preview_result.emit(future.result())
        finally:
            for future in active_futures:
                future.cancel()
            executor.shutdown(wait=True)

    def _prepare_case_preview(self, manifest, frame_count: int, skip_frames: int) -> dict:
        cache_key = _preview_cache_key(manifest)
        cache_root = Path("artifacts") / "alignment_previews" / cache_key
        ffprobe_exe = self._config.get("ffprobe_exe", "ffprobe")
        ffmpeg_exe = self._config.get("ffmpeg_exe", "ffmpeg")
        normal_source = Path(manifest.vs_normal_path)
        night_source = Path(manifest.vs_night_path)
        try:
            normal_frames = build_dji_preview_frames(
                normal_source,
                cache_root / "normal",
                ffprobe_exe,
                ffmpeg_exe,
                frame_count=frame_count,
                skip_frames=skip_frames,
            )
            night_frames = build_dji_preview_frames(
                night_source,
                cache_root / "night",
                ffprobe_exe,
                ffmpeg_exe,
                frame_count=frame_count,
                skip_frames=skip_frames,
            )
        except Exception as exc:
            return {
                "row_index": manifest.row_index,
                "case_id": manifest.case_id,
                "cache_key": cache_key,
                "status": "failed",
                "normal_source": normal_source,
                "night_source": night_source,
                "normal_exists": normal_source.exists(),
                "night_exists": night_source.exists(),
                "error": str(exc),
            }

        return {
            "row_index": manifest.row_index,
            "case_id": manifest.case_id,
            "cache_key": cache_key,
            "status": "prepared",
            "normal_source": normal_source,
            "night_source": night_source,
            "normal_frames": list(normal_frames),
            "night_frames": list(night_frames),
        }


def _preview_cache_key(manifest) -> str:
    identity = "|".join(
        [
            str(manifest.case_id),
            str(manifest.vs_normal_path),
            str(manifest.vs_night_path),
        ]
    )
    digest = hashlib.sha1(identity.encode("utf-8")).hexdigest()[:12]
    return f"{manifest.case_id}_{digest}"
