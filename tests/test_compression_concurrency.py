from pathlib import Path

from video_tagging_assistant.orchestrator import run_batch
from video_tagging_assistant.models import GenerationResult, CompressedArtifact


class RecordingCompressor:
    def __init__(self):
        self.calls = []

    def __call__(self, task, output_dir, compression_config):
        self.calls.append(task.file_name)
        output_dir.mkdir(parents=True, exist_ok=True)
        proxy = output_dir / f"{Path(task.file_name).stem}_proxy.mp4"
        proxy.write_bytes(b"proxy")
        return CompressedArtifact(task.source_video_path, proxy)


class StaticProvider:
    provider_name = "qwen_dashscope"

    def generate(self, context):
        return GenerationResult(
            source_video_path=context.source_video_path,
            structured_tags={"安装方式": "胸前"},
            multi_select_tags={"画面特征": ["重复纹理"]},
            scene_description="描述",
            provider="qwen_dashscope",
            model="qwen3.6-flash",
        )


def test_run_batch_uses_all_tasks_for_compression(tmp_path: Path):
    input_dir = tmp_path / "videos"
    (input_dir / "a").mkdir(parents=True)
    (input_dir / "a" / "clip01.mp4").write_bytes(b"1")
    (input_dir / "a" / "clip02.mp4").write_bytes(b"2")

    compressor = RecordingCompressor()
    config = {
        "input_dir": str(input_dir),
        "output_dir": str(tmp_path / "output"),
        "paths": {
            "compressed_dir": str(tmp_path / "output" / "compressed"),
            "intermediate_dir": str(tmp_path / "output" / "intermediate"),
            "review_file": str(tmp_path / "output" / "review" / "review.txt"),
        },
        "compression": {"width": 960, "video_bitrate": "700k", "audio_bitrate": "96k", "fps": 12},
        "prompt_template": {"system": "x", "single_choice_fields": {}, "multi_choice_fields": {}},
        "concurrency": {"compression_workers": 2, "provider_workers": 1, "max_retries": 1, "retry_backoff_seconds": 1, "retry_backoff_multiplier": 2},
    }

    run_batch(config, compressor=compressor, provider=StaticProvider())

    assert sorted(compressor.calls) == ["clip01.mp4", "clip02.mp4"]
