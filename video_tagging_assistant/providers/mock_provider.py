from video_tagging_assistant.models import GenerationResult, PromptContext
from video_tagging_assistant.providers.base import VideoTagProvider


class MockVideoTagProvider(VideoTagProvider):
    provider_name = "mock"

    def __init__(self, model: str = "mock-video-tagger") -> None:
        self.model = model

    def generate(self, context: PromptContext) -> GenerationResult:
        mode = context.parsed_metadata.get("mode") or "unknown"
        case_id = context.parsed_metadata.get("case_id") or "unknown-case"
        return GenerationResult(
            source_video_path=context.source_video_path,
            summary_text=f"{mode} 模式下的 {case_id} 视频，建议人工复核。",
            tags=[mode, case_id, "待审核"],
            notes="mock provider result",
            provider=self.provider_name,
            model=self.model,
            raw_response_excerpt="mock-response",
        )
