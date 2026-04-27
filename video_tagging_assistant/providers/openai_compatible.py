import json
import os
from pathlib import Path
from urllib import request

from video_tagging_assistant.models import GenerationResult, PromptContext
from video_tagging_assistant.providers.base import VideoTagProvider


def normalize_response_payload(
    payload: dict,
    source_video_path: Path,
    provider_name: str,
    model: str,
) -> GenerationResult:
    return GenerationResult(
        source_video_path=source_video_path,
        summary_text=str(payload.get("summary", "")).strip(),
        tags=[str(tag).strip() for tag in payload.get("tags", []) if str(tag).strip()],
        notes=str(payload.get("notes", "")).strip(),
        provider=provider_name,
        model=model,
        raw_response_excerpt=json.dumps(payload, ensure_ascii=False)[:500],
    )


class OpenAICompatibleVideoTagProvider(VideoTagProvider):
    provider_name = "openai_compatible"

    def __init__(self, base_url: str, api_key_env: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key_env = api_key_env
        self.model = model

    def generate(self, context: PromptContext) -> GenerationResult:
        api_key = os.environ[self.api_key_env]
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": context.template_fields.get("system", "")},
                {"role": "user", "content": json.dumps(context.prompt_payload, ensure_ascii=False)},
            ],
            "response_format": {"type": "json_object"},
        }
        req = request.Request(
            url=f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        with request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        content = body["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        return normalize_response_payload(parsed, context.source_video_path, self.provider_name, self.model)
