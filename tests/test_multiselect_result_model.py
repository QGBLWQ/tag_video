from pathlib import Path

from video_tagging_assistant.models import GenerationResult


def test_generation_result_supports_multiselect_fields():
    result = GenerationResult(
        source_video_path=Path("videos/clip01.mp4"),
        structured_tags={
            "安装方式": "胸前",
            "运动模式": "步行",
            "运镜方式": "固定镜头",
            "光源": "自然光",
        },
        multi_select_tags={
            "画面特征": ["重复纹理", "边缘特征_强弱"],
            "影像表达": ["建筑空间", "风景录像"],
        },
        scene_description="画面亮度变化明显，但不描述手机时间开场。",
    )

    assert result.multi_select_tags["画面特征"] == ["重复纹理", "边缘特征_强弱"]
    assert "手机时间开场" in result.scene_description
