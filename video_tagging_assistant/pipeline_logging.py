from dataclasses import dataclass

from video_tagging_assistant.pipeline_models import RuntimeStage


@dataclass
class CaseRuntimeState:
    manifest: object
    stage: RuntimeStage = RuntimeStage.QUEUED
