from pathlib import Path

from video_tagging_assistant.models import GenerationResult
from video_tagging_assistant.review_exporter import export_review_list


def test_export_review_list_writes_expected_sections(tmp_path: Path):
    output_path = tmp_path / "review.txt"
    result = GenerationResult(
        source_video_path=Path("videos/case_A_001/clip01.mp4"),
        summary_text="夜景道路画面，主体清晰。",
        tags=["夜景", "道路", "稳定"],
        notes="上下文完整",
        provider="mock",
        model="mock-video-tagger",
    )

    export_review_list([result], output_path)

    text = output_path.read_text(encoding="utf-8")
    assert "视频路径: videos/case_A_001/clip01.mp4" in text
    assert "建议简介: 夜景道路画面，主体清晰。" in text
    assert "建议标签: 夜景, 道路, 稳定" in text
    assert "审核状态: unreviewed" in text
