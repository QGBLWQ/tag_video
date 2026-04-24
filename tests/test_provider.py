from pathlib import Path

from video_tagging_assistant.models import PromptContext
from video_tagging_assistant.providers.mock_provider import MockVideoTagProvider


def test_mock_provider_returns_normalized_result():
    context = PromptContext(
        source_video_path=Path("videos/clip01.mp4"),
        compressed_video_path=Path("output/compressed/clip01_proxy.mp4"),
        parsed_metadata={"mode": "DCG_HDR", "case_id": "case_A_001"},
        template_fields={"system": "请生成简介"},
        prompt_payload={"template": {"system": "请生成简介"}},
        context_warnings=[],
    )

    provider = MockVideoTagProvider(model="mock-video-tagger")
    result = provider.generate(context)

    assert result.provider == "mock"
    assert result.model == "mock-video-tagger"
    assert len(result.tags) >= 1
    assert result.summary_text


def test_normalize_response_payload_extracts_summary_and_tags():
    from video_tagging_assistant.providers.openai_compatible import normalize_response_payload

    payload = {
        "summary": "白天街道视频，主体稳定。",
        "tags": ["白天", "街道", "稳定"],
        "notes": "目录信息完整",
    }

    result = normalize_response_payload(payload, Path("videos/clip01.mp4"), "demo", "cheap-model")

    assert result.summary_text == "白天街道视频，主体稳定。"
    assert result.tags == ["白天", "街道", "稳定"]
    assert result.provider == "demo"
    assert result.model == "cheap-model"
