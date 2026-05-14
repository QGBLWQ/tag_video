"""GUI、打标、执行阶段共用的运行时模型。"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict


class RuntimeStage(str, Enum):
    """对外暴露给日志和界面的高层 case 阶段枚举。"""

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
    """从 Excel 中读取出的单条 case 行数据。"""

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
    """单个 case 的输入、输出和路径信息总表。"""

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
    rk_on_server: bool = False

    @property
    def cache_dir_name(self) -> str:
        """返回当前 case 使用的缓存目录名。"""
        return self.case_id


@dataclass
class TaggingCacheRecord:
    """描述一个 case 缓存结果由哪些文件组成。"""

    case_id: str
    manifest_path: Path
    tagging_result_path: Path
    review_result_path: Path
    source_fingerprint: str

    @property
    def is_complete(self) -> bool:
        """判断复用该缓存所需的文件是否齐全。"""
        return (
            self.manifest_path.exists()
            and self.tagging_result_path.exists()
            and self.review_result_path.exists()
        )


@dataclass
class PipelineEvent:
    """打标和执行阶段向外发出的结构化事件。"""

    case_id: str
    stage: RuntimeStage
    event_type: str
    message: str
    progress_current: int = 0
    progress_total: int = 0
    current_file: str = ""
    error: str = ""
