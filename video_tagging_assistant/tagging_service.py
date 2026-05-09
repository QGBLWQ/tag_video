"""GUI 流水线中从 manifest 过渡到 provider 调用的桥接层。"""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional

from video_tagging_assistant.compressor import compress_video
from video_tagging_assistant.context_builder import build_prompt_context
from video_tagging_assistant.excel_models import ConfirmedCaseRow
from video_tagging_assistant.models import VideoTask
from video_tagging_assistant.pipeline_models import CaseManifest, PipelineEvent, RuntimeStage
from video_tagging_assistant.tagging_cache import load_cached_result, save_cached_result


@dataclass
class TaggingReviewRow:
    """GUI 打标阶段返回给审核页的精简结果对象。"""

    case_id: str
    auto_summary: str
    auto_tags: str
    auto_scene_description: str
    tag_source: str


def _manifest_to_video_task(manifest: CaseManifest) -> VideoTask:
    """把 GUI manifest 转换为独立打标流程使用的 `VideoTask`。"""
    return VideoTask(
        source_video_path=manifest.vs_normal_path,
        relative_path=Path(manifest.mode) / manifest.case_id / manifest.vs_normal_path.name,
        file_name=manifest.vs_normal_path.name,
        case_id=manifest.case_id,
        mode=manifest.mode,
    )


def _manifest_to_case_row(manifest: CaseManifest) -> ConfirmedCaseRow:
    """把 manifest 转换为构造提示词上下文用的台账行结构。"""
    return ConfirmedCaseRow(
        case_key=manifest.case_id,
        workbook_row_index=manifest.row_index,
        raw_path=str(manifest.raw_path),
        vs_normal_path=str(manifest.vs_normal_path),
        vs_night_path=str(manifest.vs_night_path),
        note=manifest.remark,
        attributes=manifest.labels,
    )


def _generate_with_retry(provider, context, concurrency: dict):
    """对 GUI 打标使用的 provider 调用加上重试逻辑。

    只有临时错误（网络超时、5xx）才重试；欠费/Key错等永久错误直接抛出。
    """
    max_retries = concurrency.get("max_retries", 3)
    delay = concurrency.get("retry_backoff_seconds", 2)
    multiplier = concurrency.get("retry_backoff_multiplier", 2)
    current_delay = float(delay)
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            return provider.generate(context)
        except Exception as exc:
            last_error = exc
            msg = str(exc)
            if "不可重试" in msg:
                raise
            if attempt >= max_retries:
                raise
            time.sleep(current_delay)
            current_delay *= multiplier
    raise last_error


_DEFAULT_COMPRESSION = {
    "width": 1280,
    "video_bitrate": "1500k",
    "audio_bitrate": "128k",
    "fps": 8,
}


def run_batch_tagging(
    manifests: List[CaseManifest],
    cache_root: Path,
    output_root: Path,
    provider,
    prompt_template,
    mode: str,
    event_callback: Callable[[PipelineEvent], None],
    compressor=compress_video,
    concurrency: Optional[Dict] = None,
    compression_config: Optional[Dict] = None,
) -> List[TaggingReviewRow]:
    """执行 GUI 批量打标流程，串起压缩、提示词构建、模型调用和缓存。

    Args:
        manifests: 从工作簿驱动的 GUI 流程中加载出的 case manifest 列表。
        cache_root: 打标缓存根目录。
        output_root: 代理视频和中间产物输出根目录。
        provider: 实际执行标签生成的 provider。
        prompt_template: 配置中的提示词模板结构。
        mode: `"fresh"` 或 `"cached"`，决定缓存复用策略。
        event_callback: 接收 `PipelineEvent` 的事件回调。
        compressor: 可注入的压缩实现。
        concurrency: 并发和重试相关配置。
        compression_config: 代理视频压缩配置。

    Returns:
        与输入 manifest 顺序一致的审核结果列表。
    """
    if concurrency is None:
        concurrency = {}
    if compression_config is None:
        compression_config = _DEFAULT_COMPRESSION

    compression_workers = concurrency.get("compression_workers", 2)
    provider_workers = concurrency.get("provider_workers", 2)

    cache_root = Path(cache_root)
    output_root = Path(output_root)
    compressed_dir = output_root / "compressed"
    compressed_dir.mkdir(parents=True, exist_ok=True)

    # Skip cached cases; collect remaining for fresh tagging
    to_tag: List[CaseManifest] = []
    cached_results: Dict[str, TaggingReviewRow] = {}
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
                cached_results[manifest.case_id] = TaggingReviewRow(
                    case_id=manifest.case_id,
                    auto_summary=cached.get("summary_text", ""),
                    auto_tags=";".join(cached.get("tags", [])),
                    auto_scene_description=cached.get("scene_description", ""),
                    tag_source="cache",
                )
                continue
        to_tag.append(manifest)

    # Combined pipeline: compress → immediately submit to AI
    artifacts_by_id: Dict[str, object] = {}
    fresh_results: Dict[str, TaggingReviewRow] = {}
    tasks_by_id: Dict[str, VideoTask] = {}
    total_to_tag = len(to_tag)
    compressed_count = 0
    tagged_count = 0

    with ThreadPoolExecutor(max_workers=max(1, compression_workers)) as compress_pool:
        compress_futures = {}
        for manifest in to_tag:
            task = _manifest_to_video_task(manifest)
            tasks_by_id[manifest.case_id] = task
            f = compress_pool.submit(compressor, task, compressed_dir, compression_config)
            compress_futures[f] = manifest
            event_callback(
                PipelineEvent(
                    case_id=manifest.case_id,
                    stage=RuntimeStage.TAGGING_RUNNING,
                    event_type="info",
                    message="compressing",
                    progress_current=compressed_count,
                    progress_total=total_to_tag,
                )
            )

        with ThreadPoolExecutor(max_workers=max(1, provider_workers)) as ai_pool:
            ai_futures = {}
            for f in as_completed(compress_futures):
                manifest = compress_futures[f]
                try:
                    artifacts_by_id[manifest.case_id] = f.result()
                    compressed_count += 1
                    event_callback(
                        PipelineEvent(
                            case_id=manifest.case_id,
                            stage=RuntimeStage.TAGGING_RUNNING,
                            event_type="info",
                            message="compressed",
                            progress_current=compressed_count,
                            progress_total=total_to_tag,
                        )
                    )
                except Exception as exc:
                    event_callback(
                        PipelineEvent(
                            case_id=manifest.case_id,
                            stage=RuntimeStage.TAGGING_RUNNING,
                            event_type="error",
                            message=f"压缩失败: {exc}",
                        )
                    )
                    continue  # skip AI for this case

                # Immediately submit AI task for this manifest
                task = tasks_by_id[manifest.case_id]
                artifact = artifacts_by_id[manifest.case_id]
                context = build_prompt_context(
                    task, artifact, prompt_template, case_row=_manifest_to_case_row(manifest)
                )
                event_callback(
                    PipelineEvent(
                        case_id=manifest.case_id,
                        stage=RuntimeStage.TAGGING_RUNNING,
                        event_type="info",
                        message="tagging",
                        progress_current=tagged_count,
                        progress_total=total_to_tag,
                    )
                )
                ai_f = ai_pool.submit(_generate_with_retry, provider, context, concurrency)
                ai_futures[ai_f] = manifest

            for ai_f in as_completed(ai_futures):
                manifest = ai_futures[ai_f]
                try:
                    generated = ai_f.result()
                    tagged_count += 1
                    event_callback(
                        PipelineEvent(
                            case_id=manifest.case_id,
                            stage=RuntimeStage.TAGGING_RUNNING,
                            event_type="info",
                            message="tagged",
                            progress_current=tagged_count,
                            progress_total=total_to_tag,
                        )
                    )
                except Exception as exc:
                    event_callback(
                        PipelineEvent(
                            case_id=manifest.case_id,
                            stage=RuntimeStage.TAGGING_RUNNING,
                            event_type="error",
                            message=f"AI 打标失败: {exc}",
                        )
                    )
                    continue

                payload = {
                    "summary_text": generated.summary_text,
                    "tags": [f"{key}={value}" for key, value in generated.structured_tags.items()],
                    "scene_description": generated.scene_description,
                    "structured_tags": generated.structured_tags,
                    "multi_select_tags": generated.multi_select_tags,
                }
                save_cached_result(cache_root, manifest, payload)
                fresh_results[manifest.case_id] = TaggingReviewRow(
                    case_id=manifest.case_id,
                    auto_summary=generated.summary_text,
                    auto_tags=";".join(payload["tags"]),
                    auto_scene_description=generated.scene_description,
                    tag_source="fresh",
                )

    # Return in original manifest order
    all_results: List[TaggingReviewRow] = []
    for manifest in manifests:
        if manifest.case_id in cached_results:
            all_results.append(cached_results[manifest.case_id])
        elif manifest.case_id in fresh_results:
            all_results.append(fresh_results[manifest.case_id])
    return all_results
