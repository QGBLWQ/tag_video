import re
from pathlib import Path
from typing import Optional

import pytest

from video_tagging_assistant.pipeline_models import CaseManifest
from video_tagging_assistant.rk_alignment_service import (
    RkCandidate,
    build_alignment_batch_state,
    clear_alignment,
    confirm_alignment,
    enable_rewrite_rows,
    scan_rk_candidates,
)


def _make_manifest(tmp_path: Path, row_index: int) -> CaseManifest:
    case_id = f"case_{row_index}"
    return CaseManifest(
        case_id=case_id,
        row_index=row_index,
        created_date="20260508",
        mode="mode_a",
        raw_path=tmp_path / f"{case_id}_RK_raw_unset",
        vs_normal_path=tmp_path / f"{case_id}_normal.MP4",
        vs_night_path=tmp_path / f"{case_id}_night.MP4",
        local_case_root=tmp_path / case_id,
        server_case_dir=tmp_path / "server" / case_id,
        remark="",
    )


def _make_candidate(root: Path, folder_name: str) -> RkCandidate:
    folder_path = root / folder_name
    preview_path = folder_path / "preview.jpg"
    return RkCandidate(
        folder_name=folder_name,
        folder_path=folder_path,
        preview_path=preview_path,
        numeric_value=int(_strip_x_suffix(folder_name)),
        has_x_suffix=folder_name.endswith("x"),
    )


def _mkdir_candidate(root: Path, folder_name: str, *, preview_name: Optional[str] = "preview.jpg") -> None:
    folder_path = root / folder_name
    folder_path.mkdir(parents=True)
    if preview_name is not None:
        (folder_path / preview_name).write_bytes(b"jpeg")


def _strip_x_suffix(value: str) -> str:
    return value[:-1] if value.endswith("x") else value


def test_scan_rk_candidates_prefers_temp_path_and_filters_missing_jpeg(tmp_path: Path):
    temp_root = tmp_path / "temp_root"
    dut_root = tmp_path / "dut_root"
    temp_root.mkdir()
    dut_root.mkdir()

    _mkdir_candidate(temp_root, "31")
    _mkdir_candidate(temp_root, "31x", preview_name="frame.jpeg")
    _mkdir_candidate(temp_root, "32x", preview_name=None)
    _mkdir_candidate(temp_root, "ignore_me")
    _mkdir_candidate(dut_root, "40")

    source_root, candidates, bad_logs = scan_rk_candidates(str(temp_root), str(dut_root))

    assert source_root == temp_root
    assert [candidate.folder_name for candidate in candidates] == ["31", "31x"]
    assert any("32x" in log for log in bad_logs)


def test_scan_rk_candidates_falls_back_to_dut_root_when_temp_path_has_no_candidates(tmp_path: Path):
    temp_root = tmp_path / "temp_root"
    dut_root = tmp_path / "dut_root"
    temp_root.mkdir()
    dut_root.mkdir()

    _mkdir_candidate(dut_root, "40")

    source_root, candidates, bad_logs = scan_rk_candidates(str(temp_root), str(dut_root))

    assert source_root == dut_root
    assert [candidate.folder_name for candidate in candidates] == ["40"]
    assert bad_logs == []


def test_build_alignment_batch_state_uses_historical_prefix_and_marks_pending_rows(tmp_path: Path):
    manifests = [_make_manifest(tmp_path, row_index) for row_index in (3, 4, 5)]
    candidates = [_make_candidate(tmp_path, folder_name) for folder_name in ("31", "32", "33", "34")]

    state = build_alignment_batch_state(
        manifests=manifests,
        rk_raw_by_row={3: "31", 4: "", 5: ""},
        candidates=candidates,
        bad_directory_logs=[],
    )

    assert [case.manifest.row_index for case in state.pending_cases] == [4, 5]
    assert [case.selected_candidate_index for case in state.pending_cases] == [1, 2]
    assert manifests[0].raw_path == Path("31")
    assert state.blocked_messages == []


def test_build_alignment_batch_state_blocks_unknown_historical_rk_value(tmp_path: Path):
    manifests = [_make_manifest(tmp_path, 3)]
    candidates = [_make_candidate(tmp_path, "31")]

    state = build_alignment_batch_state(
        manifests=manifests,
        rk_raw_by_row={3: "99"},
        candidates=candidates,
        bad_directory_logs=[],
    )

    assert "row 3 has RK_raw=99 but no valid RK candidate matches it" in state.blocked_messages


def test_confirm_clear_and_rewrite_guard_recompute_consumption_monotonically(tmp_path: Path):
    manifests = [_make_manifest(tmp_path, row_index) for row_index in (3, 4, 5)]
    candidates = [_make_candidate(tmp_path, folder_name) for folder_name in ("31", "32", "33")]

    state = build_alignment_batch_state(
        manifests=manifests,
        rk_raw_by_row={3: "", 4: "", 5: ""},
        candidates=candidates,
        bad_directory_logs=[],
    )
    state = confirm_alignment(state, row_index=3, candidate_name="31")
    state = confirm_alignment(state, row_index=4, candidate_name="32")
    state = confirm_alignment(state, row_index=5, candidate_name="33")
    state = enable_rewrite_rows(state, [3])

    with pytest.raises(
        ValueError,
        match=re.escape(
            "row 3 cannot be rewritten to RK 33 because later confirmed rows would no longer be strictly increasing"
        ),
    ):
        confirm_alignment(state, row_index=3, candidate_name="33")

    cleared = clear_alignment(state, row_index=4)

    assert cleared.rk_raw_by_row[4] == ""
    assert [case.manifest.row_index for case in cleared.pending_cases] == [4]
    assert cleared.pending_cases[0].rk_raw_value == ""
    assert cleared.pending_cases[0].selected_candidate_index == 1
