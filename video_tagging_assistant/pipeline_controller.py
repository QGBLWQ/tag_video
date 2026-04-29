from collections import deque
from dataclasses import dataclass

from video_tagging_assistant.case_task_factory import build_case_task
from video_tagging_assistant.copy_worker import copy_declared_files
from video_tagging_assistant.pipeline_models import RuntimeStage
from video_tagging_assistant.pull_worker import run_resumable_pull
from video_tagging_assistant.upload_worker import upload_case_directory


@dataclass
class CaseRuntimeState:
    manifest: object
    stage: RuntimeStage = RuntimeStage.QUEUED


class PipelineController:
    def __init__(self, pull_runner=run_resumable_pull, copy_runner=copy_declared_files, upload_runner=upload_case_directory):
        self._cases = {}
        self._execution_queue = deque()
        self._pull_runner = pull_runner
        self._copy_runner = copy_runner
        self._upload_runner = upload_runner

    def register_manifests(self, manifests):
        for manifest in manifests:
            self._cases[manifest.case_id] = CaseRuntimeState(manifest=manifest)

    def mark_tagging_finished(self, case_id: str):
        self._cases[case_id].stage = RuntimeStage.AWAITING_REVIEW

    def approve_case(self, case_id: str):
        state = self._cases[case_id]
        state.stage = RuntimeStage.REVIEW_PASSED
        self._execution_queue.append(state.manifest)

    def dequeue_execution_case(self):
        return self._execution_queue.popleft()

    def get_case_state(self, case_id: str):
        return self._cases[case_id]

    def run_next_execution_case(self):
        manifest = self.dequeue_execution_case()
        case_task = build_case_task(manifest)
        self._cases[manifest.case_id].stage = RuntimeStage.PULLING
        self._pull_runner(case_task.pull_task)
        self._cases[manifest.case_id].stage = RuntimeStage.COPYING
        self._copy_runner(case_task.copy_tasks)
        self._cases[manifest.case_id].stage = RuntimeStage.UPLOADING
        self._upload_runner(case_task.case_id, case_task.case_root_dir, case_task.server_case_dir)
        self._cases[manifest.case_id].stage = RuntimeStage.COMPLETED
