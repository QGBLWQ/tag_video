from collections import deque
from dataclasses import dataclass
from typing import Callable, Optional

from video_tagging_assistant.case_task_factory import build_case_task
from video_tagging_assistant.copy_worker import copy_declared_files
from video_tagging_assistant.pipeline_models import PipelineEvent, RuntimeStage
from video_tagging_assistant.pull_worker import run_resumable_pull
from video_tagging_assistant.upload_worker import upload_case_directory


@dataclass
class CaseRuntimeState:
    manifest: object
    stage: RuntimeStage = RuntimeStage.QUEUED


class PipelineController:
    def __init__(
        self,
        pull_runner=run_resumable_pull,
        copy_runner=copy_declared_files,
        upload_runner=upload_case_directory,
        event_callback: Optional[Callable[[PipelineEvent], None]] = None,
    ):
        self._cases = {}
        self._execution_queue = deque()
        self._pull_runner = pull_runner
        self._copy_runner = copy_runner
        self._upload_runner = upload_runner
        self._event_callback = event_callback

    def _emit(self, case_id: str, stage: RuntimeStage, message: str, event_type: str = "info") -> None:
        if self._event_callback is not None:
            self._event_callback(
                PipelineEvent(case_id=case_id, stage=stage, event_type=event_type, message=message)
            )

    def register_manifests(self, manifests):
        for manifest in manifests:
            self._cases[manifest.case_id] = CaseRuntimeState(manifest=manifest)

    def has_execution_case(self) -> bool:
        return bool(self._execution_queue)

    def mark_tagging_finished(self, case_id: str):
        self._cases[case_id].stage = RuntimeStage.AWAITING_REVIEW
        self._emit(case_id, RuntimeStage.AWAITING_REVIEW, "awaiting review")

    def approve_case(self, case_id: str):
        state = self._cases[case_id]
        if state.stage in {
            RuntimeStage.REVIEW_PASSED,
            RuntimeStage.PULLING,
            RuntimeStage.COPYING,
            RuntimeStage.UPLOADING,
            RuntimeStage.COMPLETED,
        }:
            return False
        state.stage = RuntimeStage.REVIEW_PASSED
        self._execution_queue.append(state.manifest)
        self._emit(case_id, RuntimeStage.REVIEW_PASSED, "case approved")
        return True

    def dequeue_execution_case(self):
        return self._execution_queue.popleft()

    def get_case_state(self, case_id: str):
        return self._cases[case_id]

    def run_next_execution_case(self):
        manifest = self.dequeue_execution_case()
        case_task = build_case_task(manifest)
        try:
            self._cases[manifest.case_id].stage = RuntimeStage.PULLING
            self._emit(manifest.case_id, RuntimeStage.PULLING, "pull started")
            self._pull_runner(case_task.pull_task)

            self._cases[manifest.case_id].stage = RuntimeStage.COPYING
            self._emit(manifest.case_id, RuntimeStage.COPYING, "copy started")
            self._copy_runner(case_task.copy_tasks)

            self._cases[manifest.case_id].stage = RuntimeStage.UPLOADING
            self._emit(manifest.case_id, RuntimeStage.UPLOADING, "upload started")
            self._upload_runner(case_task.case_id, case_task.case_root_dir, case_task.server_case_dir)

            self._cases[manifest.case_id].stage = RuntimeStage.COMPLETED
            self._emit(manifest.case_id, RuntimeStage.COMPLETED, "case completed")
        except Exception as exc:
            self._cases[manifest.case_id].stage = RuntimeStage.FAILED
            self._emit(manifest.case_id, RuntimeStage.FAILED, str(exc), event_type="error")
