import json
from pathlib import Path

from video_tagging_assistant.config import load_config
from video_tagging_assistant.compressor import build_ffmpeg_command
from video_tagging_assistant.orchestrator import run_batch
from video_tagging_assistant.cli import build_provider_from_config
from video_tagging_assistant.review_exporter import export_review_list
from video_tagging_assistant.models import GenerationResult


class StubCompressor:
    def __call__(self, task, output_dir, compression_config):
        proxy_path = output_dir / f"{Path(task.file_name).stem}_proxy.mp4"
        output_dir.mkdir(parents=True, exist_ok=True)
        proxy_path.write_bytes(b"proxy")
        from video_tagging_assistant.models import CompressedArtifact
        return CompressedArtifact(task.source_video_path, proxy_path)


class StubProvider:
    provider_name = "stub"

    def generate(self, context):
        return GenerationResult(
            source_video_path=context.source_video_path,
            summary_text="测试简介",
            tags=["测试", "待审核"],
            provider="stub",
            model="stub-model",
        )


class StructuredStubProvider:
    provider_name = "qwen_dashscope"

    def generate(self, context):
        return GenerationResult(
            source_video_path=context.source_video_path,
            structured_tags={
                "安装方式": "胸前",
                "运动模式": "步行",
                "运镜方式": "固定镜头",
                "光源": "自然光",
            },
            scene_description="画面亮度稳定，庭院细节清晰。",
            provider="qwen_dashscope",
            model="qwen3.6-flash",
        )


def test_build_ffmpeg_command_uses_expected_scaling_and_bitrate():
    command = build_ffmpeg_command(
        source=Path("videos/clip01.mp4"),
        target=Path("output/compressed/clip01_proxy.mp4"),
        compression_config={"width": 960, "video_bitrate": "700k", "audio_bitrate": "96k", "fps": 12},
    )

    assert command[0] == "ffmpeg"
    assert "scale=960:-2" in command
    assert "700k" in command
    assert Path(command[-1]).as_posix() == "output/compressed/clip01_proxy.mp4"


def test_run_batch_creates_intermediate_and_review_outputs(tmp_path: Path):
    input_dir = tmp_path / "videos"
    output_dir = tmp_path / "output"
    (input_dir / "DCG_HDR" / "case_A_001").mkdir(parents=True)
    (input_dir / "DCG_HDR" / "case_A_001" / "clip01.mp4").write_bytes(b"data")

    config = {
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "compression": {"width": 960, "video_bitrate": "700k", "audio_bitrate": "96k", "fps": 12},
        "prompt_template": {"system": "describe"},
    }

    result = run_batch(config, compressor=StubCompressor(), provider=StubProvider())

    review_text = (output_dir / "review" / "review.txt").read_text(encoding="utf-8")
    intermediate = json.loads((output_dir / "intermediate" / "clip01.json").read_text(encoding="utf-8"))

    assert result["processed"] == 1
    assert "测试简介" in review_text
    assert intermediate["summary_text"] == "测试简介"


def test_run_batch_persists_structured_results(tmp_path: Path):
    input_dir = tmp_path / "videos"
    output_dir = tmp_path / "output"
    (input_dir / "DCG_HDR" / "case_A_001").mkdir(parents=True)
    (input_dir / "DCG_HDR" / "case_A_001" / "clip01.mp4").write_bytes(b"data")

    config = {
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "compression": {"width": 960, "video_bitrate": "700k", "audio_bitrate": "96k", "fps": 12},
        "prompt_template": {
            "system": "describe",
            "structured_tag_options": {
                "安装方式": ["胸前", "手持"],
                "运动模式": ["步行", "骑行"],
                "运镜方式": ["固定镜头", "跟拍"],
                "光源": ["自然光", "弱光"]
            },
            "scene_description_instruction": "描述光亮变化和场景细节"
        },
    }

    result = run_batch(config, compressor=StubCompressor(), provider=StructuredStubProvider())

    review_text = (output_dir / "review" / "review.txt").read_text(encoding="utf-8")
    intermediate = json.loads((output_dir / "intermediate" / "clip01.json").read_text(encoding="utf-8"))

    assert result["processed"] == 1
    assert "安装方式: 胸前" in review_text
    assert intermediate["structured_tags"]["安装方式"] == "胸前"


def test_build_provider_from_config_returns_mock_provider():
    config = {
        "provider": {
            "name": "mock",
            "model": "mock-video-tagger",
            "base_url": "",
            "api_key_env": "VIDEO_TAGGER_API_KEY",
        }
    }

    provider = build_provider_from_config(config)

    assert provider.provider_name == "mock"
    assert provider.model == "mock-video-tagger"


def test_build_provider_from_config_returns_qwen_provider():
    config = {
        "provider": {
            "name": "qwen_dashscope",
            "model": "qwen3.6-flash",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "api_key_env": "DASHSCOPE_API_KEY",
            "fps": 2,
        }
    }

    provider = build_provider_from_config(config)

    assert provider.provider_name == "qwen_dashscope"
    assert provider.model == "qwen3.6-flash"


def test_review_exporter_uses_review_directory(tmp_path: Path):
    review_dir = tmp_path / "output" / "review"
    target = review_dir / "review.txt"
    result = GenerationResult(
        source_video_path=Path("videos/example.mp4"),
        summary_text="示例简介",
        tags=["示例"],
    )

    export_review_list([result], target)

    assert target.exists()
