from pathlib import Path

from video_tagging_assistant.context_builder import build_prompt_context
from video_tagging_assistant.models import CompressedArtifact, VideoTask
from video_tagging_assistant.providers.qwen_dashscope_provider import (
    QwenDashScopeVideoTagProvider,
    build_qwen_multimodal_message,
    normalize_response_payload,
    parse_json_content,
)


def test_parse_json_content_handles_fenced_json():
    content = """```json\n{\n  \"安装方式\": \"胸前\",\n  \"运动模式\": \"步行\",\n  \"运镜方式\": \"固定镜头\",\n  \"光源\": \"自然光\",\n  \"画面描述\": \"示例描述\"\n}\n```"""

    parsed = parse_json_content(content)

    assert parsed["安装方式"] == "胸前"
    assert parsed["运动模式"] == "步行"
    assert parsed["画面描述"] == "示例描述"


def test_build_qwen_multimodal_message_contains_video_and_text():
    message = build_qwen_multimodal_message(
        video_data_url="data:video/mp4;base64,AAAA",
        prompt_text="请生成结构化标签",
        fps=2,
    )

    assert message["role"] == "user"
    assert message["content"][0]["type"] == "video_url"
    assert message["content"][0]["video_url"]["url"].startswith("data:video/mp4;base64,")
    assert message["content"][0]["fps"] == 2
    assert message["content"][1]["type"] == "text"
    assert message["content"][1]["text"] == "请生成结构化标签"


def test_qwen_prompt_mentions_single_choice_tag_constraints():
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
                "运动模式": ["步行", "骑行"],
                "运镜方式": ["固定镜头", "跟拍"],
                "光源": ["自然光", "弱光"],
            },
            "multi_choice_fields": {},
            "scene_description_instruction": "描述光亮变化和场景细节",
        },
    )
    provider = QwenDashScopeVideoTagProvider(
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key_env="DASHSCOPE_API_KEY",
        model="qwen3.6-flash",
    )

    prompt_text = provider._build_prompt_text(context)

    assert "单选字段必须且只能选择一个候选值" in prompt_text
    assert "- 安装方式: 胸前, 手持" in prompt_text
    assert "画面描述" in prompt_text


def test_normalize_response_payload_maps_structured_fields():
    payload = {
        "安装方式": "胸前",
        "运动模式": "步行",
        "运镜方式": "固定镜头",
        "光源": "自然光",
        "画面描述": "画面亮度稳定，庭院细节清晰。",
    }

    result = normalize_response_payload(payload, Path("videos/clip01.mp4"), "qwen_dashscope", "qwen3.6-flash")

    assert result.structured_tags == {
        "安装方式": "胸前",
        "运动模式": "步行",
        "运镜方式": "固定镜头",
        "光源": "自然光",
    }
    assert result.scene_description == "画面亮度稳定，庭院细节清晰。"
