from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterable

from video_tagging_assistant.compressor import compress_video
from video_tagging_assistant.config import load_config
from video_tagging_assistant.context_builder import build_prompt_context
from video_tagging_assistant.models import GenerationResult, VideoTask
from video_tagging_assistant.review_exporter import export_html_report, export_intermediate_result, export_review_list
from video_tagging_assistant.scanner import scan_videos


def _retry_generate(provider, context, max_retries: int, retry_backoff_seconds: float, retry_backoff_multiplier: float):
    attempt = 0
    delay = retry_backoff_seconds
    last_exc = None
    while attempt < max_retries:
        try:
            return provider.generate(context)
        except Exception as exc:
            last_exc = exc
            attempt += 1
            if attempt >= max_retries:
                break
            import time

            time.sleep(delay)
            delay *= retry_backoff_multiplier
    raise last_exc


def _process_task(task, config, provider, output_dir: Path):
    compression = config["compression"]
    concurrency = config.get("concurrency", {})
    compressed_dir = output_dir / "compressed"
    intermediate_dir = output_dir / "intermediate"
    compressed_dir.mkdir(parents=True, exist_ok=True)
    intermediate_dir.mkdir(parents=True, exist_ok=True)

    artifact = compress_video(
        task,
        compressed_dir,
        width=compression["width"],
        video_bitrate=compression["video_bitrate"],
        audio_bitrate=compression["audio_bitrate"],
        fps=compression["fps"],
    )
    context = build_prompt_context(task, artifact, config["prompt_template"])
    result = _retry_generate(
        provider,
        context,
        max_retries=concurrency.get("max_retries", 3),
        retry_backoff_seconds=concurrency.get("retry_backoff_seconds", 2),
        retry_backoff_multiplier=concurrency.get("retry_backoff_multiplier", 2),
    )
    export_intermediate_result(result, intermediate_dir / f"{task.file_name}.json")
    return result


def run_batch(config: dict, provider) -> dict:
    input_dir = Path(config["input_dir"])
    output_dir = Path(config["output_dir"])
    review_path = Path(config["paths"]["review_file"])
    tasks = scan_videos(input_dir)
    concurrency = config.get("concurrency", {})
    compression_workers = max(1, concurrency.get("compression_workers", 1))
    provider_workers = max(1, concurrency.get("provider_workers", 1))
    max_workers = max(compression_workers, provider_workers)

    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_process_task, task, config, provider, output_dir) for task in tasks]
        for future in as_completed(futures):
            results.append(future.result())

    review_path.parent.mkdir(parents=True, exist_ok=True)
    export_review_list(results, review_path)
    export_html_report(results, review_path.with_suffix(".html"))
    return {"processed": len(tasks), "review_path": review_path}
