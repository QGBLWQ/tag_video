from pathlib import Path

from video_tagging_assistant.pipeline_models import CaseManifest
from video_tagging_assistant.tagging_cache import build_source_fingerprint, load_cached_result, save_cached_result


def build_manifest(tmp_path: Path) -> CaseManifest:
    return CaseManifest(
        case_id="case_A_0105",
        row_index=12,
        created_date="20260428",
        mode="OV50H40_Action5Pro_DCG HDR",
        raw_path=tmp_path / "raw",
        vs_normal_path=tmp_path / "normal.MP4",
        vs_night_path=tmp_path / "night.MP4",
        local_case_root=tmp_path / "case_A_0105",
        server_case_dir=tmp_path / "server" / "case_A_0105",
        remark="场景备注",
        labels={"安装方式": "手持"},
    )


def test_build_source_fingerprint_changes_when_input_changes(tmp_path: Path):
    manifest = build_manifest(tmp_path)
    first = build_source_fingerprint(manifest)
    manifest.remark = "新备注"
    second = build_source_fingerprint(manifest)
    assert first != second


def test_save_and_load_cached_result_round_trip(tmp_path: Path):
    manifest = build_manifest(tmp_path)
    payload = {
        "summary_text": "自动简介",
        "tags": ["手持"],
        "scene_description": "画面描述",
    }
    save_cached_result(tmp_path, manifest, payload)
    loaded = load_cached_result(tmp_path, manifest)
    assert loaded["summary_text"] == "自动简介"
    assert loaded["scene_description"] == "画面描述"


def test_load_cached_result_returns_none_for_mismatched_fingerprint(tmp_path: Path):
    manifest = build_manifest(tmp_path)
    save_cached_result(tmp_path, manifest, {"summary_text": "自动简介"})
    manifest.remark = "不同备注"
    assert load_cached_result(tmp_path, manifest) is None
