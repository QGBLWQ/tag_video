from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Mapping, Sequence, Set, Tuple

from video_tagging_assistant.pipeline_models import CaseManifest


_RK_DIR_PATTERN = re.compile(r"^\d+x?$")


@dataclass(frozen=True)
class RkCandidate:
    folder_name: str
    folder_path: Path
    preview_path: Path
    numeric_value: int
    has_x_suffix: bool


@dataclass
class AlignmentViewCase:
    manifest: CaseManifest
    rk_raw_value: str
    selected_candidate_index: int
    status: str


@dataclass
class AlignmentBatchState:
    manifests: list[CaseManifest]
    candidates: list[RkCandidate]
    bad_directory_logs: list[str]
    rk_raw_by_row: Dict[int, str]
    pending_cases: list[AlignmentViewCase]
    aligned_cases: list[AlignmentViewCase]
    blocked_messages: list[str]
    rewrite_row_indices: Set[int] = field(default_factory=set)
    base_raw_paths: Dict[int, Path] = field(default_factory=dict)


def scan_rk_candidates(temp_root: str, dut_root: str) -> Tuple[Path, list[RkCandidate], list[str]]:
    temp_path = _optional_root_path(temp_root)
    dut_path = _optional_root_path(dut_root) or Path(dut_root)

    temp_candidates, temp_logs = _scan_candidate_root(temp_path)
    if temp_candidates:
        return temp_path, temp_candidates, temp_logs

    dut_candidates, dut_logs = _scan_candidate_root(dut_path)
    return dut_path, dut_candidates, temp_logs + dut_logs


def build_alignment_batch_state(
    manifests: Sequence[CaseManifest],
    rk_raw_by_row: Mapping[int, str],
    candidates: Sequence[RkCandidate],
    bad_directory_logs: Sequence[str],
) -> AlignmentBatchState:
    ordered_manifests = sorted(manifests, key=lambda manifest: manifest.row_index)
    base_raw_paths = {manifest.row_index: Path(manifest.raw_path) for manifest in ordered_manifests}
    normalized_rk_raw = {int(row_index): _normalize_rk_raw(value) for row_index, value in rk_raw_by_row.items()}
    for manifest in ordered_manifests:
        normalized_rk_raw.setdefault(manifest.row_index, "")
    sorted_candidates = sorted(candidates, key=_candidate_sort_key)
    return _recompute_state(
        manifests=ordered_manifests,
        base_raw_paths=base_raw_paths,
        rk_raw_by_row=normalized_rk_raw,
        candidates=sorted_candidates,
        bad_directory_logs=list(bad_directory_logs),
        rewrite_row_indices=set(),
    )


def confirm_alignment(state: AlignmentBatchState, row_index: int, candidate_name: str) -> AlignmentBatchState:
    candidate_indices = _candidate_index_by_name(state.candidates)
    candidate_index = candidate_indices.get(candidate_name)
    if candidate_index is None:
        raise ValueError(f"RK candidate {candidate_name} does not exist")
    _manifest_by_row(state.manifests, row_index)
    _validate_confirm_alignment(state, row_index, candidate_name, candidate_index, candidate_indices)
    updated_rk_raw = dict(state.rk_raw_by_row)
    updated_rk_raw[row_index] = candidate_name
    updated_rewrite_rows = set(state.rewrite_row_indices)
    updated_rewrite_rows.discard(row_index)
    return _recompute_state(
        manifests=state.manifests,
        base_raw_paths=state.base_raw_paths,
        rk_raw_by_row=updated_rk_raw,
        candidates=state.candidates,
        bad_directory_logs=state.bad_directory_logs,
        rewrite_row_indices=updated_rewrite_rows,
    )


def clear_alignment(state: AlignmentBatchState, row_index: int) -> AlignmentBatchState:
    _manifest_by_row(state.manifests, row_index)
    updated_rk_raw = dict(state.rk_raw_by_row)
    updated_rk_raw[row_index] = ""
    return _recompute_state(
        manifests=state.manifests,
        base_raw_paths=state.base_raw_paths,
        rk_raw_by_row=updated_rk_raw,
        candidates=state.candidates,
        bad_directory_logs=state.bad_directory_logs,
        rewrite_row_indices=set(state.rewrite_row_indices),
    )


def enable_rewrite_rows(state: AlignmentBatchState, row_indices: list[int]) -> AlignmentBatchState:
    aligned_rows = {
        row_index
        for row_index in row_indices
        if _normalize_rk_raw(state.rk_raw_by_row.get(row_index, ""))
    }
    return _recompute_state(
        manifests=state.manifests,
        base_raw_paths=state.base_raw_paths,
        rk_raw_by_row=state.rk_raw_by_row,
        candidates=state.candidates,
        bad_directory_logs=state.bad_directory_logs,
        rewrite_row_indices=aligned_rows,
    )


def _scan_candidate_root(root: Path | None) -> Tuple[list[RkCandidate], list[str]]:
    if root is None or not root.exists() or not root.is_dir():
        return [], []

    candidates = []
    bad_logs = []
    for child in root.iterdir():
        if not child.is_dir() or not _RK_DIR_PATTERN.fullmatch(child.name):
            continue
        preview_path = _find_preview_path(child)
        if preview_path is None:
            bad_logs.append(f"{child.name} is missing a preview jpg/jpeg file")
            continue
        has_x_suffix = child.name.endswith("x")
        candidates.append(
            RkCandidate(
                folder_name=child.name,
                folder_path=child,
                preview_path=preview_path,
                numeric_value=int(_strip_x_suffix(child.name)),
                has_x_suffix=has_x_suffix,
            )
        )
    candidates.sort(key=_candidate_sort_key)
    return candidates, bad_logs


def _find_preview_path(folder_path: Path) -> Path | None:
    for child in sorted(folder_path.iterdir(), key=lambda path: path.name.lower()):
        if child.is_file() and child.suffix.lower() in {".jpg", ".jpeg"}:
            return child
    return None


def _recompute_state(
    manifests: Sequence[CaseManifest],
    base_raw_paths: Mapping[int, Path],
    rk_raw_by_row: Mapping[int, str],
    candidates: Sequence[RkCandidate],
    bad_directory_logs: Sequence[str],
    rewrite_row_indices: Set[int],
) -> AlignmentBatchState:
    candidate_indices = _candidate_index_by_name(candidates)
    blocked_messages = []
    pending_cases = []
    aligned_cases = []
    cursor = 0

    for manifest in manifests:
        manifest.raw_path = Path(base_raw_paths[manifest.row_index])

    manifest_row_indices = {manifest.row_index for manifest in manifests}
    filtered_rewrite_rows = {row_index for row_index in rewrite_row_indices if row_index in manifest_row_indices}

    normalized_rk_raw = dict(rk_raw_by_row)
    for manifest in manifests:
        row_index = manifest.row_index
        rk_raw_value = _normalize_rk_raw(normalized_rk_raw.get(row_index, ""))
        normalized_rk_raw[row_index] = rk_raw_value
        if rk_raw_value:
            candidate_index = candidate_indices.get(rk_raw_value)
            if candidate_index is None:
                blocked_messages.append(
                    f"row {row_index} has RK_raw={rk_raw_value} but no valid RK candidate matches it"
                )
                manifest.raw_path = Path(rk_raw_value)
                aligned_cases.append(
                    AlignmentViewCase(
                        manifest=manifest,
                        rk_raw_value=rk_raw_value,
                        selected_candidate_index=-1,
                        status="blocked_aligned",
                    )
                )
                continue
            if candidate_index < cursor:
                blocked_messages.append(
                    f"row {row_index} has RK_raw={rk_raw_value} but it is not strictly after earlier confirmed rows"
                )
            manifest.raw_path = Path(rk_raw_value)
            aligned_cases.append(
                AlignmentViewCase(
                    manifest=manifest,
                    rk_raw_value=rk_raw_value,
                    selected_candidate_index=candidate_index,
                    status=_aligned_status(row_index, filtered_rewrite_rows),
                )
            )
            if candidate_index >= cursor:
                cursor = candidate_index + 1
            continue

        selected_candidate_index = cursor if cursor < len(candidates) else -1
        pending_cases.append(
            AlignmentViewCase(
                manifest=manifest,
                rk_raw_value="",
                selected_candidate_index=selected_candidate_index,
                status=_pending_status(row_index, filtered_rewrite_rows),
            )
        )
        if selected_candidate_index == -1:
            blocked_messages.append(f"row {row_index} has no remaining RK candidates to assign")
            continue
        cursor = selected_candidate_index + 1

    return AlignmentBatchState(
        manifests=list(manifests),
        candidates=list(candidates),
        bad_directory_logs=list(bad_directory_logs),
        rk_raw_by_row=normalized_rk_raw,
        pending_cases=pending_cases,
        aligned_cases=aligned_cases,
        blocked_messages=blocked_messages,
        rewrite_row_indices=filtered_rewrite_rows,
        base_raw_paths=dict(base_raw_paths),
    )


def _candidate_sort_key(candidate: RkCandidate) -> tuple[int, int, str]:
    return candidate.numeric_value, 1 if candidate.has_x_suffix else 0, candidate.folder_name


def _candidate_index_by_name(candidates: Sequence[RkCandidate]) -> Dict[str, int]:
    return {candidate.folder_name: index for index, candidate in enumerate(candidates)}


def _validate_confirm_alignment(
    state: AlignmentBatchState,
    row_index: int,
    candidate_name: str,
    candidate_index: int,
    candidate_indices: Mapping[str, int],
) -> None:
    earlier_index, later_index = _confirmed_neighbor_bounds(state, row_index, candidate_indices)
    if earlier_index is not None and candidate_index <= earlier_index:
        raise ValueError(
            f"row {row_index} cannot be {_confirm_verb(state, row_index)} to RK {candidate_name} "
            f"because it is not strictly after earlier confirmed rows"
        )
    if later_index is not None and candidate_index >= later_index:
        raise ValueError(
            f"row {row_index} cannot be {_confirm_verb(state, row_index)} to RK {candidate_name} "
            f"because later confirmed rows would no longer be strictly increasing"
        )


def _confirmed_neighbor_bounds(
    state: AlignmentBatchState,
    row_index: int,
    candidate_indices: Mapping[str, int],
) -> Tuple[int | None, int | None]:
    earlier_index = None
    later_index = None
    ordered_manifests = sorted(state.manifests, key=lambda manifest: manifest.row_index)

    for manifest in ordered_manifests:
        current_row_index = manifest.row_index
        if current_row_index == row_index:
            continue
        rk_raw_value = _normalize_rk_raw(state.rk_raw_by_row.get(current_row_index, ""))
        if not rk_raw_value:
            continue
        current_candidate_index = candidate_indices.get(rk_raw_value)
        if current_candidate_index is None:
            continue
        if current_row_index < row_index:
            if earlier_index is None:
                earlier_index = current_candidate_index
            else:
                earlier_index = max(earlier_index, current_candidate_index)
            continue
        later_index = current_candidate_index
        break

    return earlier_index, later_index


def _confirm_verb(state: AlignmentBatchState, row_index: int) -> str:
    if row_index in state.rewrite_row_indices:
        return "rewritten"
    return "confirmed"


def _manifest_by_row(manifests: Sequence[CaseManifest], row_index: int) -> CaseManifest:
    for manifest in manifests:
        if manifest.row_index == row_index:
            return manifest
    raise ValueError(f"row {row_index} does not exist in the alignment batch")


def _normalize_rk_raw(value: object) -> str:
    return str(value or "").strip()


def _strip_x_suffix(value: str) -> str:
    return value[:-1] if value.endswith("x") else value


def _optional_root_path(root_value: str) -> Path | None:
    normalized = str(root_value or "").strip()
    if not normalized:
        return None
    return Path(normalized)


def _aligned_status(row_index: int, rewrite_row_indices: Set[int]) -> str:
    if row_index in rewrite_row_indices:
        return "rewrite_aligned"
    return "aligned"


def _pending_status(row_index: int, rewrite_row_indices: Set[int]) -> str:
    if row_index in rewrite_row_indices:
        return "rewrite_pending"
    return "pending"


__all__ = [
    "AlignmentBatchState",
    "AlignmentViewCase",
    "RkCandidate",
    "build_alignment_batch_state",
    "clear_alignment",
    "confirm_alignment",
    "enable_rewrite_rows",
    "scan_rk_candidates",
]
