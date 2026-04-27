from abc import ABC, abstractmethod

from video_tagging_assistant.models import GenerationResult, PromptContext


class VideoTagProvider(ABC):
    provider_name = ""

    @abstractmethod
    def generate(self, context: PromptContext) -> GenerationResult:
        raise NotImplementedError
