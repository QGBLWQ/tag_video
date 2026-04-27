import json
from pathlib import Path

from video_tagging_assistant.models import GenerationResult, CompressedArtifact
from video_tagging_assistant.orchestrator import run_batch


class StubCompressor:
    def __call__(self, task, output_dir, compression_config):
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
            scene_description="详细描述",
            provider="qwen_dashscope",
            model="qwen3.6-flash",
        )


def test_run_batch_generates_html_report_when_enabled(tmp_path: Path):
    input_dir = tmp_path / "videos"
    (input_dir / "a").mkdir(parents=True)
    (input_dir / "a" / "clip01.mp4").write_bytes(b"1")

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
        "concurrency": {"compression_workers": 1, "provider_workers": 1, "max_retries": 1, "retry_backoff_seconds": 0, "retry_backoff_multiplier": 2},
        "logging": {"log_dir": str(tmp_path / "output" / "logs"), "capture_ffmpeg_output": False, "quiet_terminal": True},
        "reporting": {"generate_html_report": True, "html_report_file": str(tmp_path / "output" / "report" / "index.html")},
    }

    summary = run_batch(config, compressor=StubCompressor(), provider=StaticProvider())

    assert Path(summary["html_report_path"]).exists()
