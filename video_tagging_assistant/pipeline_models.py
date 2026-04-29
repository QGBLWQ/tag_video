from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict


class RuntimeStage(str, Enum):
    QUEUED = "queued"
    TAGGING_PREPARING = "tagging_preparing"
    TAGGING_RUNNING = "tagging_running"
    TAGGING_FINISHED = "tagging_finished"
    TAGGING_SKIPPED_USING_CACHED = "tagging_skipped_using_cached"
    AWAITING_REVIEW = "awaiting_review"
    REVIEW_PASSED = "review_passed"
    REVIEW_REJECTED = "review_rejected"
    PULLING = "pulling"
    COPYING = "copying"
    UPLOADING = "uploading"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ExcelCaseRecord:
    row_index: int
    case_id: str
    created_date: str
    remark: str
    raw_path: str
    vs_normal_path: str
    vs_night_path: str
    labels: Dict[str, str] = field(default_factory=dict)
    pipeline_status: str = ""


@dataclass
class CaseManifest:
    case_id: str
    row_index: int
    created_date: str
    mode: str
    raw_path: Path
    vs_normal_path: Path
    vs_night_path: Path
    local_case_root: Path
    server_case_dir: Path
    remark: str
    labels: Dict[str, str] = field(default_factory=dict)

    @property
    def cache_dir_name(self) -> str:
        return self.case_id


@dataclass
class TaggingCacheRecord:
    case_id: str
    manifest_path: Path
    tagging_result_path: Path
    review_result_path: Path
    source_fingerprint: str

    @property
    def is_complete(self) -> bool:
        return (
            self.manifest_path.exists()
            and self.tagging_result_path.exists()
            and self.review_result_path.exists()
        )


@dataclass
class PipelineEvent:
    case_id: str
    stage: RuntimeStage
    event_type: str
    message: str
    progress_current: int = 0
    progress_total: int = 0
    current_file: str = ""
    error: str = ""
