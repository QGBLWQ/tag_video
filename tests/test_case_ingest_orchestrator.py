from pathlib import Path
from queue import Empty

from video_tagging_assistant.case_ingest_models import CaseTask, PullTask, UploadResult
from video_tagging_assistant.case_ingest_orchestrator import run_case_ingest


class StubPullWorker:
    def __init__(self):
        self.calls = []

    def __call__(self, pull_task):
        self.calls.append(pull_task.case_id)
        final_dir = Path(pull_task.move_dst)
        final_dir.mkdir(parents=True, exist_ok=True)
        (final_dir / "1.txt").write_text("ok", encoding="utf-8")
        return final_dir


class StubCopyWorker:
    def __call__(self, copy_tasks):
        for copy_task in copy_tasks:
            copy_task.target_path.parent.mkdir(parents=True, exist_ok=True)
            copy_task.target_path.write_text("copied", encoding="utf-8")


class StubUploader:
    def __call__(self, case_id, local_case_dir, server_case_dir):
        return UploadResult(case_id=case_id, status="uploaded")


class RecordingUploadWorker:
    def __init__(self, order):
        self.order = order

    def __call__(self, task_queue, result_queue, stop_event):
        while True:
            try:
                case_task, upload_runner = task_queue.get(timeout=0.1)
            except Empty:
                if stop_event.is_set() and task_queue.empty():
                    break
                continue

            self.order.append(("upload-start", case_task.case_id))
            result = upload_runner(case_task.case_id, case_task.case_root_dir, case_task.server_case_dir)
            self.order.append(("upload-finish", case_task.case_id))
            result_queue.put(result)
            task_queue.task_done()


def noop_wait_for_device():
    return None


def build_case_task(tmp_path: Path, case_id: str) -> CaseTask:
    case_root = tmp_path / "local" / case_id
    server_case = tmp_path / "server" / case_id
    return CaseTask(
        case_id=case_id,
        pull_task=PullTask(
            case_id=case_id,
            device_path=f"/mnt/nvme/CapturedData/{case_id}",
            local_name=str(case_root / f"{case_id}_RK_raw"),
            move_src=str(case_root / f"{case_id}_RK_raw"),
            move_dst=str(case_root / f"{case_id}_RK_raw"),
        ),
        case_root_dir=case_root,
        server_case_dir=server_case,
    )


def test_run_case_ingest_processes_case_and_reports_uploaded(tmp_path: Path):
    task = build_case_task(tmp_path, "case_A_0078")

    summary = run_case_ingest(
        [task],
        pull_runner=StubPullWorker(),
        copy_runner=StubCopyWorker(),
        upload_runner=StubUploader(),
        wait_for_device_runner=noop_wait_for_device,
        skip_upload=False,
    )

    assert summary["processed"] == 1
    assert summary["uploaded"] == 1
    assert summary["failed"] == 0


def test_run_case_ingest_counts_existing_server_case_as_skipped(tmp_path: Path):
    task = build_case_task(tmp_path, "case_A_0078")
    task.server_case_dir.mkdir(parents=True)

    summary = run_case_ingest(
        [task],
        pull_runner=StubPullWorker(),
        copy_runner=StubCopyWorker(),
        wait_for_device_runner=noop_wait_for_device,
        skip_upload=False,
    )

    assert summary["processed"] == 1
    assert summary["uploaded"] == 0
    assert summary["skipped"] == 1
    assert summary["upload_results"]["case_A_0078"].status == "upload_skipped_exists"


def test_run_case_ingest_queues_next_case_before_first_upload_finishes(tmp_path: Path):
    order = []
    pull_worker = StubPullWorker()

    class OrderedPullWorker(StubPullWorker):
        def __call__(self, pull_task):
            order.append(("pull", pull_task.case_id))
            return super().__call__(pull_task)

    class OrderedUploader(StubUploader):
        def __call__(self, case_id, local_case_dir, server_case_dir):
            return UploadResult(case_id=case_id, status="uploaded")

    tasks = [
        build_case_task(tmp_path, "case_A_0078"),
        build_case_task(tmp_path, "case_A_0079"),
    ]

    summary = run_case_ingest(
        tasks,
        pull_runner=OrderedPullWorker(),
        copy_runner=StubCopyWorker(),
        upload_runner=OrderedUploader(),
        upload_worker=RecordingUploadWorker(order),
        wait_for_device_runner=noop_wait_for_device,
        skip_upload=False,
    )

    assert summary["processed"] == 2
    assert summary["uploaded"] == 2
    assert order[0] == ("pull", "case_A_0078")
    assert order[1] == ("pull", "case_A_0079")
    assert ("upload-start", "case_A_0078") in order
