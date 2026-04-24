from pathlib import Path
from typing import Any, Dict, List

from video_tagging_assistant.models import CompressedArtifact, PromptContext, VideoTask


def build_prompt_context(
    task: VideoTask,
    artifact: CompressedArtifact,
    template_fields: Dict[str, Any],
) -> PromptContext:
    parent_parts = list(task.relative_path.parts[:-1])
    parsed_metadata = {
        "case_id": next((part for part in parent_parts if part.lower().startswith("case_")), None),
        "mode": parent_parts[0] if parent_parts else None,
        "device_info": parent_parts[1] if len(parent_parts) > 2 else None,
        "file_name": task.file_name,
        "relative_path": task.relative_path.as_posix(),
    }

    warnings: List[str] = []
    if parsed_metadata["case_id"] is None:
        warnings.append("missing_case_id")
    if parsed_metadata["mode"] is None:
        warnings.append("missing_mode")

    prompt_payload = {
        "template": template_fields,
        "video": {
            "source_path": str(task.source_video_path),
            "compressed_path": str(artifact.compressed_video_path),
        },
        "metadata": parsed_metadata,
    }

    return PromptContext(
        source_video_path=task.source_video_path,
        compressed_video_path=artifact.compressed_video_path,
        parsed_metadata=parsed_metadata,
        template_fields=template_fields,
        prompt_payload=prompt_payload,
        context_warnings=warnings,
    )
