from pathlib import Path
from typing import Any, Dict, List, Optional

from video_tagging_assistant.excel_models import ConfirmedCaseRow
from video_tagging_assistant.models import CompressedArtifact, PromptContext, VideoTask


def build_prompt_context(
    task: VideoTask,
    artifact: CompressedArtifact,
    template_fields: Dict[str, Any],
    case_row: Optional[ConfirmedCaseRow] = None,
) -> PromptContext:
    parent_parts = list(task.relative_path.parts[:-1])
    parsed_metadata = {
        "case_id": task.case_id or next((part for part in parent_parts if part.lower().startswith("case_")), None),
        "mode": task.mode or (parent_parts[0] if parent_parts else None),
        "device_info": task.device_info or (parent_parts[1] if len(parent_parts) > 2 else None),
        "file_name": task.file_name,
        "relative_path": task.relative_path.as_posix(),
    }

    warnings: List[str] = []
    if parsed_metadata["case_id"] is None:
        warnings.append("missing_case_id")
    if parsed_metadata["mode"] is None:
        warnings.append("missing_mode")

    workbook_payload = {}
    if case_row is not None:
        workbook_payload = {
            "文件夹名": case_row.case_key,
            "备注": case_row.note,
            "Raw存放路径": case_row.raw_path,
            "VS_Nomal": case_row.vs_normal_path,
            "VS_Night": case_row.vs_night_path,
            "已确认属性": case_row.attributes,
        }

    prompt_payload = {
        "template": template_fields,
        "video": {
            "source_path": str(task.source_video_path),
            "compressed_path": str(artifact.compressed_video_path),
        },
        "metadata": parsed_metadata,
        "workbook": workbook_payload,
    }

    return PromptContext(
        source_video_path=task.source_video_path,
        compressed_video_path=artifact.compressed_video_path,
        parsed_metadata=parsed_metadata,
        template_fields=template_fields,
        prompt_payload=prompt_payload,
        context_warnings=warnings,
    )
