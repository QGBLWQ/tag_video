from dataclasses import dataclass, field
from typing import Dict


@dataclass
class ConfirmedCaseRow:
    case_key: str
    workbook_row_index: int
    raw_path: str
    vs_normal_path: str
    vs_night_path: str
    note: str
    attributes: Dict[str, str] = field(default_factory=dict)


@dataclass
class ReviewSheetRow:
    case_key: str
    workbook_row_index: int
    raw_path: str
    video_path: str
    auto_summary: str = ""
    auto_tags: str = ""
    auto_scene_description: str = ""
    manual_summary: str = ""
    manual_tags: str = ""
    review_decision: str = "待审核"
    review_note: str = ""
    reviewer: str = ""
    reviewed_at: str = ""
    sync_status: str = "待同步"
    archive_status: str = "待归档"
    archive_target_path: str = ""

    @property
    def final_summary(self) -> str:
        return self.manual_summary.strip() or self.auto_summary.strip()

    @property
    def final_tags(self) -> str:
        return self.manual_tags.strip() or self.auto_tags.strip()
