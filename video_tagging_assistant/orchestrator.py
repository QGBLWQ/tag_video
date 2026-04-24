import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict

from video_tagging_assistant.compressor import compress_video
from video_tagging_assistant.context_builder import build_prompt_context
from video_tagging_assistant.review_exporter import export_review_list
from video_tagging_assistant.scanner import scan_videos


def _json_default(value: Any):
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Unsupported type: {type(value)!r}")


def _compress_tasks(tasks, compressed_dir, compression_config, compressor, workers):
    artifacts = {}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        future_map = {
            executor.submit(compressor, task, compressed_dir, compression_config): task
            for task in tasks
        }
        for future in as_completed(future_map):
            task = future_map[future]
            artifacts[task.source_video_path] = future.result()
    return artifacts


def _generate_with_retry(provider, context, concurrency_config):
    max_retries = concurrency_config.get("max_retries", 3)
    delay = concurrency_config.get("retry_backoff_seconds", 2)
    multiplier = concurrency_config.get("retry_backoff_multiplier", 2)

    last_error = None
    current_delay = delay
    for attempt in range(max_retries + 1):
        try:
            return provider.generate(context)
        except Exception as exc:
            last_error = exc
            if attempt >= max_retries:
                raise
            time.sleep(current_delay)
            current_delay *= multiplier
    raise last_error


def run_batch(config: Dict, compressor=compress_video, provider=None) -> Dict[str, Any]:
    if provider is None:
        raise ValueError("provider is required")

    input_dir = Path(config["input_dir"])
    output_dir = Path(config["output_dir"])
    paths = config.get("paths", {})
    concurrency = config.get("concurrency", {})
    compressed_dir = Path(paths.get("compressed_dir", str(output_dir / "compressed")))
    intermediate_dir = Path(paths.get("intermediate_dir", str(output_dir / "intermediate")))
    review_path = Path(paths.get("review_file", str(output_dir / "review" / "review.txt")))

    intermediate_dir.mkdir(parents=True, exist_ok=True)

    tasks = scan_videos(input_dir)
    compression_workers = concurrency.get("compression_workers", 1)
    provider_workers = concurrency.get("provider_workers", 1)
    artifacts = _compress_tasks(tasks, compressed_dir, config["compression"], compressor, compression_workers)
    results = []

    with ThreadPoolExecutor(max_workers=max(1, provider_workers)) as executor:
        future_map = {}
        for task in tasks:
            artifact = artifacts[task.source_video_path]
            context = build_prompt_context(task, artifact, config["prompt_template"])
            future = executor.submit(_generate_with_retry, provider, context, concurrency)
            future_map[future] = task

        for future in as_completed(future_map):
            task = future_map[future]
            result = future.result()
            results.append(result)
            intermediate_path = intermediate_dir / f"{task.source_video_path.stem}.json"
            intermediate_path.write_text(
                json.dumps(asdict(result), ensure_ascii=False, indent=2, default=_json_default),
                encoding="utf-8",
            )

    export_review_list(results, review_path)
    return {"processed": len(results), "review_path": str(review_path)}
