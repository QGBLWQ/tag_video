from pathlib import Path

from video_tagging_assistant.case_task_factory import build_case_task
from video_tagging_assistant.pipeline_models import CaseManifest


def test_build_case_task_maps_manifest_paths():
    manifest = CaseManifest(
        case_id="case_A_0105",
        row_index=12,
        created_date="20260428",
        mode="OV50H40_Action5Pro_DCG HDR",
        raw_path=Path(r"E:\DV\case_A_0105\case_A_0105_RK_raw_117"),
        vs_normal_path=Path(r"E:\DV\source\DJI_normal.MP4"),
        vs_night_path=Path(r"E:\DV\source\DJI_night.MP4"),
        local_case_root=Path(r"E:\DV\OV50H40_Action5Pro_DCG HDR\20260428\case_A_0105"),
        server_case_dir=Path(r"\\10.10.10.164\rk3668_capture\OV50H40_Action5Pro_DCG HDR\20260428\case_A_0105"),
        remark="场景备注",
        labels={"安装方式": "手持"},
    )

    case_task = build_case_task(manifest)

    assert case_task.case_id == "case_A_0105"
    assert case_task.case_root_dir == manifest.local_case_root
    assert case_task.server_case_dir == manifest.server_case_dir
    assert case_task.pull_task.move_dst.endswith("case_A_0105_RK_raw_117")
    assert len(case_task.copy_tasks) == 2
