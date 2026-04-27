from pathlib import Path

from video_tagging_assistant.context_builder import build_prompt_context
from video_tagging_assistant.excel_models import ConfirmedCaseRow
from video_tagging_assistant.models import CompressedArtifact, VideoTask


def test_build_prompt_context_extracts_case_and_mode():
    task = VideoTask(
        source_video_path=Path("videos/DCG_HDR/case_A_001/clip01.mp4"),
        relative_path=Path("DCG_HDR/case_A_001/clip01.mp4"),
        file_name="clip01.mp4",
    )
    artifact = CompressedArtifact(
        source_video_path=task.source_video_path,
        compressed_video_path=Path("output/compressed/clip01_proxy.mp4"),
    )
    template = {
        "system": "请为视频生成简介和标签",
        "tag_rules": ["返回 3 到 5 个标签"],
    }

    context = build_prompt_context(task, artifact, template)

    assert context.parsed_metadata["case_id"] == "case_A_001"
    assert context.parsed_metadata["mode"] == "DCG_HDR"
    assert context.prompt_payload["template"]["system"] == "请为视频生成简介和标签"
    assert context.context_warnings == []


def test_build_prompt_context_marks_missing_metadata():
    task = VideoTask(
        source_video_path=Path("videos/clip01.mp4"),
        relative_path=Path("clip01.mp4"),
        file_name="clip01.mp4",
    )
    artifact = CompressedArtifact(
        source_video_path=task.source_video_path,
        compressed_video_path=Path("output/compressed/clip01_proxy.mp4"),
    )

    context = build_prompt_context(task, artifact, {"system": "x"})

    assert "missing_case_id" in context.context_warnings
    assert "missing_mode" in context.context_warnings


def test_build_prompt_context_includes_excel_case_metadata():
    task = VideoTask(
        source_video_path=Path("videos/DCG_HDR/case_A_0001/clip01.mp4"),
        relative_path=Path("DCG_HDR/case_A_0001/clip01.mp4"),
        file_name="clip01.mp4",
        case_id="case_A_0001",
    )
    artifact = CompressedArtifact(
        source_video_path=task.source_video_path,
        compressed_video_path=Path("output/compressed/clip01_proxy.mp4"),
    )
    case_row = ConfirmedCaseRow(
        case_key="case_A_0001",
        workbook_row_index=2,
        raw_path="raw/path",
        vs_normal_path="videos/case_A_0001/clip01.mp4",
        vs_night_path="videos/case_A_0001/night.mp4",
        note="场景备注",
        attributes={"安装方式": "手持", "运动模式": "行走"},
    )

    context = build_prompt_context(task, artifact, {"system": "describe"}, case_row=case_row)

    assert context.prompt_payload["workbook"]["文件夹名"] == "case_A_0001"
    assert context.prompt_payload["workbook"]["备注"] == "场景备注"
