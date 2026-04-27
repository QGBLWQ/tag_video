from dataclasses import dataclass, field
from pathlib import Path
from typing import List


@dataclass
class PullTask:
    case_id: str
    device_path: str
    local_name: str
    move_src: str
    move_dst: str


@dataclass
class CopyTask:
    case_id: str
    source_path: Path
    target_path: Path
    kind: str


@dataclass
class CaseTask:
    case_id: str
    pull_task: PullTask
    case_root_dir: Path
    server_case_dir: Path
    copy_tasks: List[CopyTask] = field(default_factory=list)
    status: str = "pending"
    message: str = ""


@dataclass
class UploadResult:
    case_id: str
    status: str
    message: str = ""
