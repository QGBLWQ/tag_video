from pathlib import Path

from video_tagging_assistant.models import GenerationResult


def test_generation_result_supports_structured_fields():
    result = GenerationResult(
        source_video_path=Path("videos/clip01.mp4"),
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

    assert result.structured_tags["安装方式"] == "胸前"
    assert result.scene_description == "画面亮度稳定，庭院细节清晰。"
