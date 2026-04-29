from pathlib import Path

from video_tagging_assistant.pipeline_models import (
    CaseManifest,
    ExcelCaseRecord,
    PipelineEvent,
    RuntimeStage,
    TaggingCacheRecord,
)


def test_excel_case_record_exposes_case_id_and_row():
    row = ExcelCaseRecord(
        row_index=12,
        case_id="case_A_0105",
        created_date="20260428",
        remark="场景备注",
        raw_path=r"E:\DV\case_A_0105\case_A_0105_RK_raw_117",
        vs_normal_path=r"E:\DV\case_A_0105\case_A_0105_DJI_normal.MP4",
        vs_night_path=r"E:\DV\case_A_0105\case_A_0105_night_DJI.MP4",
        labels={"安装方式": "手持", "运动模式": "行走"},
        pipeline_status="",
    )
    assert row.case_id == "case_A_0105"
    assert row.row_index == 12


def test_manifest_builds_cache_dir_from_case_id(tmp_path: Path):
    manifest = CaseManifest(
        case_id="case_A_0105",
        row_index=12,
        created_date="20260428",
        mode="OV50H40_Action5Pro_DCG HDR",
        raw_path=Path(tmp_path / "case_A_0105_RK_raw_117"),
        vs_normal_path=Path(tmp_path / "normal.MP4"),
        vs_night_path=Path(tmp_path / "night.MP4"),
        local_case_root=tmp_path / "case_A_0105",
        server_case_dir=Path(r"\\10.10.10.164\rk3668_capture\OV50H40_Action5Pro_DCG HDR\20260428\case_A_0105"),
        remark="场景备注",
        labels={"安装方式": "手持"},
    )
    assert manifest.cache_dir_name == "case_A_0105"


def test_pipeline_event_carries_progress_fields():
    event = PipelineEvent(
        case_id="case_A_0105",
        stage=RuntimeStage.PULLING,
        event_type="progress",
        message="pulling raw",
        progress_current=7,
        progress_total=20,
    )
    assert event.progress_current == 7
    assert event.progress_total == 20


def test_tagging_cache_record_reports_cache_ready(tmp_path: Path):
    record = TaggingCacheRecord(
        case_id="case_A_0105",
        manifest_path=tmp_path / "manifest.json",
        tagging_result_path=tmp_path / "tagging_result.json",
        review_result_path=tmp_path / "review_result.json",
        source_fingerprint="abc123",
    )
    assert record.is_complete is False
