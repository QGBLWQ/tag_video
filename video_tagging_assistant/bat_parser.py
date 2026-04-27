import re
from pathlib import Path
from typing import List

from video_tagging_assistant.case_ingest_models import CaseTask, CopyTask, PullTask

CASE_PATTERN = re.compile(r"(case_[A-Z]_\d{4})", re.IGNORECASE)
PULL_PATTERN = re.compile(r"adb\s+pull\s+(\S+)\s+\.\\\s*(\S+)", re.IGNORECASE)
MOVE_PATTERN = re.compile(r'move\s+"([^"]+)"\s+"([^"]+)"', re.IGNORECASE)
COPY_PATTERN = re.compile(r'copy\s+"([^"]+)"\s+"([^"]+)"', re.IGNORECASE)


def detect_encoding(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gbk", "latin-1"):
        try:
            raw.decode(encoding)
            return encoding
        except UnicodeDecodeError:
            continue
    return "latin-1"


def _extract_case_id(text: str) -> str:
    match = CASE_PATTERN.search(text)
    if not match:
        raise ValueError(f"Unable to extract case id from: {text}")
    return match.group(1)


def parse_pull_bat(path: Path) -> List[PullTask]:
    rows = []
    pending = None
    with path.open(encoding=detect_encoding(path), errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            pull_match = PULL_PATTERN.search(line)
            if pull_match:
                pending = (pull_match.group(1), pull_match.group(2))
                continue
            move_match = MOVE_PATTERN.search(line)
            if move_match and pending:
                move_dst = move_match.group(2)
                rows.append(
                    PullTask(
                        case_id=_extract_case_id(move_dst),
                        device_path=pending[0],
                        local_name=pending[1],
                        move_src=move_match.group(1),
                        move_dst=move_dst,
                    )
                )
                pending = None
    return rows


def parse_move_bat(path: Path) -> List[CopyTask]:
    rows = []
    with path.open(encoding=detect_encoding(path), errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            copy_match = COPY_PATTERN.search(line)
            if not copy_match:
                continue
            target = Path(copy_match.group(2))
            name = target.name.lower()
            kind = "night" if "night" in name else "normal"
            rows.append(
                CopyTask(
                    case_id=_extract_case_id(str(target)),
                    source_path=Path(copy_match.group(1)),
                    target_path=target,
                    kind=kind,
                )
            )
    return rows


def group_case_tasks(pull_bat: Path, move_bat: Path, server_root: Path, date: str) -> List[CaseTask]:
    grouped = {}
    for pull_row in parse_pull_bat(pull_bat):
        case_root_dir = Path(pull_row.move_dst).parent
        grouped[pull_row.case_id] = CaseTask(
            case_id=pull_row.case_id,
            pull_task=pull_row,
            case_root_dir=case_root_dir,
            server_case_dir=server_root / date / pull_row.case_id,
        )

    for copy_row in parse_move_bat(move_bat):
        if copy_row.case_id in grouped:
            grouped[copy_row.case_id].copy_tasks.append(copy_row)

    return [grouped[key] for key in sorted(grouped)]
