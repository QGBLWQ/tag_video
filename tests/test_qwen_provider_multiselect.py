from pathlib import Path

from video_tagging_assistant.context_builder import build_prompt_context
from video_tagging_assistant.models import CompressedArtifact, VideoTask
from video_tagging_assistant.providers.qwen_dashscope_provider import QwenDashScopeVideoTagProvider, normalize_response_payload


def test_qwen_prompt_mentions_single_and_multiselect_rules():
    task = VideoTask(
        source_video_path=Path("videos/DCG_HDR/case_A_001/clip01.mp4"),
        relative_path=Path("DCG_HDR/case_A_001/clip01.mp4"),
        file_name="clip01.mp4",
    )
    artifact = CompressedArtifact(
        source_video_path=task.source_video_path,
        compressed_video_path=Path("output/compressed/clip01_proxy.mp4"),
    )
    context = build_prompt_context(
        task,
        artifact,
        {
            "system": "请输出结构化标签",
            "single_choice_fields": {
                "安装方式": ["胸前", "手持"],
                "光源": ["自然光", "弱光"],
            },
            "multi_choice_fields": {
                "画面特征": ["重复纹理", "反射与透视"],
                "影像表达": ["建筑空间", "风景录像"],
            },
            "ignore_opening_instruction": "不要描述手机时间特写开场。",
            "scene_description_instruction": "画面描述可以更详细。",
        },
    )
    provider = QwenDashScopeVideoTagProvider(
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key_env="DASHSCOPE_API_KEY",
        model="qwen3.6-flash",
    )

    prompt_text = provider._build_prompt_text(context)

    assert "单选字段必须且只能选择一个候选值" in prompt_text
    assert "多选字段可以选择多个候选值" in prompt_text
    assert "不要描述手机时间特写开场。" in prompt_text
    assert "- 画面特征: 重复纹理, 反射与透视" in prompt_text


def test_normalize_response_payload_maps_mixed_schema():
    payload = {
        "安装方式": "胸前",
        "运动模式": "步行",
        "运镜方式": "固定镜头",
        "光源": "自然光",
        "画面特征": ["重复纹理", "边缘特征_强弱"],
        "影像表达": ["建筑空间", "风景录像"],
        "画面描述": "光亮变化明显，庭院结构细节清晰，不描述手机时间开场。",
    }

    result = normalize_response_payload(payload, Path("videos/clip01.mp4"), "qwen_dashscope", "qwen3.6-flash")

    assert result.structured_tags["安装方式"] == "胸前"
    assert result.multi_select_tags["画面特征"] == ["重复纹理", "边缘特征_强弱"]
    assert result.multi_select_tags["影像表达"] == ["建筑空间", "风景录像"]
    assert result.scene_description.startswith("光亮变化明显")
