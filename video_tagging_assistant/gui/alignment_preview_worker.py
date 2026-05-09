"""对齐页 DJI 预览预处理线程。

负责在后台并行抽帧，避免用户点到某个 case 时才同步调用 ffmpeg/ffprobe，
从而阻塞主界面。
"""

from __future__ import annotations

import hashlib
import threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, as_completed, wait
from pathlib import Path

from PyQt5.QtCore import Qt, QByteArray, QBuffer, QIODevice, QThread, pyqtSignal
from PyQt5.QtGui import QImage
from PyQt5.QtWidgets import QApplication

from video_tagging_assistant.alignment_preview import (
    build_dji_preview_frames,
    resolve_alignment_preview_settings,
)


class AlignmentPreviewWorker(QThread):
    """后台批量生成 DJI normal/night 预览帧。"""

    preview_result = pyqtSignal(object)
    log_message = pyqtSignal(str)
    rk_preview_ready = pyqtSignal(object)

    def __init__(self, config: dict, manifests: list, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._manifests = list(manifests)
        self._stop_event = threading.Event()
        self._rk_pull_thread = None

    def stop(self) -> None:
        """请求线程尽快停止，并中断后续任务提交。"""
        self._stop_event.set()
        self.requestInterruption()

    def wait(self, msecs=None) -> bool:
        """等待线程退出，并在 GUI 环境下顺带处理一次事件。"""
        result = super().wait() if msecs is None else super().wait(msecs)
        app = QApplication.instance()
        if app is not None:
            app.processEvents()
        return result

    def run(self) -> None:
        """按配置并发生成整批 case 的预览帧。"""
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
                    self.log_message.emit(f"开始抽帧: {manifest.case_id}")

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
        """为单个 case 生成 normal/night 两组预览帧。"""
        cache_key = _preview_cache_key(manifest)
        cache_root = Path("artifacts") / "alignment_previews" / cache_key
        ffprobe_exe = self._config.get("ffprobe_exe", "ffprobe")
        ffmpeg_exe = self._config.get("ffmpeg_exe", "ffmpeg")
        self.log_message.emit(f"抽帧中: {manifest.case_id}")
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

        # 在后台线程预加载缩略图，避免主线程 I/O 阻塞
        thumbnails: list[bytes] = []
        for frame in list(normal_frames) + list(night_frames):
            img = QImage(str(frame))
            if not img.isNull():
                img = img.scaled(120, 90, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                buf = QBuffer()
                buf.open(QIODevice.WriteOnly)
                img.save(buf, "PNG")
                thumbnails.append(bytes(buf.data()))
                buf.close()
            else:
                thumbnails.append(b"")

        return {
            "row_index": manifest.row_index,
            "case_id": manifest.case_id,
            "cache_key": cache_key,
            "status": "prepared",
            "normal_source": normal_source,
            "night_source": night_source,
            "normal_frames": list(normal_frames),
            "night_frames": list(night_frames),
            "thumbnails": thumbnails,
        }


    def pull_rk_previews(self, candidates, dut_root, adb_exe) -> None:
        """启动后台线程并行拉取远端 RK 预览图。"""
        if self._rk_pull_thread is not None and self._rk_pull_thread.is_alive():
            return
        self._rk_pull_thread = threading.Thread(
            target=self._pull_rk_previews_impl,
            args=(list(candidates), dut_root, adb_exe),
            daemon=True,
        )
        self._rk_pull_thread.start()

    def _pull_rk_previews_impl(self, candidates, dut_root, adb_exe) -> None:
        from video_tagging_assistant.rk_alignment_service import (
            find_remote_preview_name,
            pull_remote_preview,
        )

        with ThreadPoolExecutor(max_workers=4) as executor:
            future_to_candidate = {
                executor.submit(
                    self._pull_single_rk_preview,
                    c,
                    dut_root,
                    adb_exe,
                    find_remote_preview_name,
                    pull_remote_preview,
                ): c
                for c in candidates
            }
            for future in as_completed(future_to_candidate):
                try:
                    result = future.result()
                except Exception as exc:
                    candidate = future_to_candidate[future]
                    result = {
                        "folder_name": candidate.folder_name,
                        "preview_path": None,
                        "status": "failed",
                        "log": f"RK candidate {candidate.folder_name} preview pull failed: {exc}",
                    }
                self.rk_preview_ready.emit(result)

    @staticmethod
    def _pull_single_rk_preview(candidate, dut_root, adb_exe, find_fn, pull_fn) -> dict:
        root_value = str(dut_root)
        folder_name = candidate.folder_name
        try:
            preview_name = find_fn(adb_exe, root_value, folder_name)
            if preview_name is None:
                return {
                    "folder_name": folder_name,
                    "preview_path": None,
                    "status": "no_preview",
                    "log": f"RK candidate {folder_name} under {root_value} is missing a preview jpg/jpeg file",
                }
            preview_path = pull_fn(adb_exe, root_value, folder_name, preview_name)
            return {
                "folder_name": folder_name,
                "preview_path": str(preview_path),
                "status": "ready",
            }
        except Exception as exc:
            return {
                "folder_name": folder_name,
                "preview_path": None,
                "status": "failed",
                "log": f"RK candidate {folder_name} under {root_value} failed during remote scan: {exc}",
            }


def _preview_cache_key(manifest) -> str:
    """基于 case 标识和视频路径生成稳定缓存键。"""
    identity = "|".join(
        [
            str(manifest.case_id),
            str(manifest.vs_normal_path),
            str(manifest.vs_night_path),
        ]
    )
    digest = hashlib.sha1(identity.encode("utf-8")).hexdigest()[:12]
    return f"{manifest.case_id}_{digest}"
