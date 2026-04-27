import shutil
from queue import Empty
from pathlib import Path

from video_tagging_assistant.case_ingest_models import UploadResult


def upload_case_directory(case_id: str, local_case_dir: Path, server_case_dir: Path) -> UploadResult:
    if server_case_dir.exists():
        return UploadResult(case_id=case_id, status="upload_skipped_exists", message="server case already exists")

    server_case_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(local_case_dir, server_case_dir)
    return UploadResult(case_id=case_id, status="uploaded")


def upload_worker_loop(task_queue, result_queue, stop_event) -> None:
    while True:
        try:
            payload = task_queue.get(timeout=0.1)
        except Empty:
            if stop_event.is_set() and task_queue.empty():
                break
            continue

        try:
            if isinstance(payload, tuple):
                case_task, upload_runner = payload
                result = upload_runner(
                    case_task.case_id,
                    case_task.case_root_dir,
                    case_task.server_case_dir,
                )
            else:
                case_task = payload
                result = upload_case_directory(
                    case_task.case_id,
                    case_task.case_root_dir,
                    case_task.server_case_dir,
                )
        except Exception as exc:
            result = UploadResult(case_id=case_task.case_id, status="failed", message=str(exc))

        result_queue.put(result)
        task_queue.task_done()
