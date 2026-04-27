from pathlib import Path

from video_tagging_assistant.context_builder import build_prompt_context
from video_tagging_assistant.models import CompressedArtifact, VideoTask
from video_tagging_assistant.providers.qwen_dashscope_provider import QwenDashScopeVideoTagProvider


def test_qwen_prompt_explicitly_excludes_phone_time_opening():
    task = VideoTask(
        source_video_path=Path("videos/DCG_HDR/case_A_001/clip01.mp4"),
        relative_path=Path("DCG_HDR/case_A_001/clip01.mp4"),
        file_name="clip01.mp4",
    )
    artifact = CompressedArtifact(task.source_video_path, Path("output/compressed/clip01_proxy.mp4"))
    context = build_prompt_context(
        task,
        artifact,
        {
            "system": "请输出结构化标签",
            "single_choice_fields": {"安装方式": ["胸前"]},
            "multi_choice_fields": {"画面特征": ["重复纹理"]},
            "ignore_opening_instruction": "画面描述必须忽略视频开头固定出现的手持手机展示时间特写，不得将其写入描述。",
            "scene_description_instruction": "画面描述可以更详细。",
        },
    )
    provider = QwenDashScopeVideoTagProvider(
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key_env="DASHSCOPE_API_KEY",
        model="qwen3.6-flash",
    )

    prompt_text = provider._build_prompt_text(context)

    assert "不得将其写入描述" in prompt_text
    assert "画面描述应从真正进入测试场景之后开始" in prompt_text
