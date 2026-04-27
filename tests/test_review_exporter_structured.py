from pathlib import Path

from video_tagging_assistant.models import GenerationResult
from video_tagging_assistant.review_exporter import export_review_list


def test_export_review_list_writes_structured_fields(tmp_path: Path):
    output_path = tmp_path / "review.txt"
    result = GenerationResult(
        source_video_path=Path("videos/case_A_001/clip01.mp4"),
        structured_tags={
            "安装方式": "胸前",
            "运动模式": "步行",
            "运镜方式": "固定镜头",
            "光源": "自然光",
        },
        scene_description="画面亮度稳定，庭院细节清晰。",
        provider="qwen_dashscope",
        model="qwen3.6-flash",
    )

    export_review_list([result], output_path)

    text = output_path.read_text(encoding="utf-8")
    assert "安装方式: 胸前" in text
    assert "运动模式: 步行" in text
    assert "画面描述: 画面亮度稳定，庭院细节清晰。" in text
