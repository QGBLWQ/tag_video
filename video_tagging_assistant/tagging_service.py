from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List

from video_tagging_assistant.compressor import compress_video
from video_tagging_assistant.context_builder import build_prompt_context
from video_tagging_assistant.excel_models import ConfirmedCaseRow
from video_tagging_assistant.models import VideoTask
from video_tagging_assistant.pipeline_models import CaseManifest, PipelineEvent, RuntimeStage
from video_tagging_assistant.tagging_cache import load_cached_result, save_cached_result


@dataclass
class TaggingReviewRow:
    case_id: str
    auto_summary: str
    auto_tags: str
    auto_scene_description: str
    tag_source: str


def _manifest_to_video_task(manifest: CaseManifest) -> VideoTask:
    return VideoTask(
        source_video_path=manifest.vs_normal_path,
        relative_path=Path(manifest.mode) / manifest.case_id / manifest.vs_normal_path.name,
        file_name=manifest.vs_normal_path.name,
        case_id=manifest.case_id,
        mode=manifest.mode,
    )


def _manifest_to_case_row(manifest: CaseManifest) -> ConfirmedCaseRow:
    return ConfirmedCaseRow(
        case_key=manifest.case_id,
        workbook_row_index=manifest.row_index,
        raw_path=str(manifest.raw_path),
        vs_normal_path=str(manifest.vs_normal_path),
        vs_night_path=str(manifest.vs_night_path),
        note=manifest.remark,
        attributes=manifest.labels,
    )


def run_batch_tagging(
    manifests: List[CaseManifest],
    cache_root: Path,
    output_root: Path,
    provider,
    prompt_template,
    mode: str,
    event_callback: Callable[[PipelineEvent], None],
    compressor=compress_video,
) -> List[TaggingReviewRow]:
    results: List[TaggingReviewRow] = []
    cache_root = Path(cache_root)
    output_root = Path(output_root)
    compressed_dir = output_root / "compressed"
    compression_config = {
        "width": 1280,
        "video_bitrate": "1500k",
        "audio_bitrate": "128k",
        "fps": 8,
    }

    for manifest in manifests:
        if mode == "cached":
            cached = load_cached_result(cache_root, manifest)
            if cached is not None:
                event_callback(
                    PipelineEvent(
                        case_id=manifest.case_id,
                        stage=RuntimeStage.TAGGING_SKIPPED_USING_CACHED,
                        event_type="info",
                        message="loaded cache",
                    )
                )
                results.append(
                    TaggingReviewRow(
                        case_id=manifest.case_id,
                        auto_summary=cached.get("summary_text", ""),
                        auto_tags=";".join(cached.get("tags", [])),
                        auto_scene_description=cached.get("scene_description", ""),
                        tag_source="cache",
                    )
                )
                continue

        event_callback(
            PipelineEvent(
                case_id=manifest.case_id,
                stage=RuntimeStage.TAGGING_RUNNING,
                event_type="info",
                message="tagging",
            )
        )
        task = _manifest_to_video_task(manifest)
        artifact = compressor(task, compressed_dir, compression_config)
        context = build_prompt_context(task, artifact, prompt_template, case_row=_manifest_to_case_row(manifest))
        generated = provider.generate(context)
        payload = {
            "summary_text": generated.summary_text,
            "tags": [f"{key}={value}" for key, value in generated.structured_tags.items()],
            "scene_description": generated.scene_description,
        }
        save_cached_result(cache_root, manifest, payload)
        results.append(
            TaggingReviewRow(
                case_id=manifest.case_id,
                auto_summary=generated.summary_text,
                auto_tags=";".join(payload["tags"]),
                auto_scene_description=generated.scene_description,
                tag_source="fresh",
            )
        )

    return results
