import json
from pathlib import Path

from video_tagging_assistant.config import load_config


def test_load_config_includes_logging_and_reporting_sections(tmp_path: Path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "input_dir": "videos",
                "output_dir": "output",
                "compression": {"width": 960, "video_bitrate": "700k", "audio_bitrate": "96k", "fps": 12},
                "provider": {"name": "qwen_dashscope", "model": "qwen3.6-flash", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "api_key_env": "DASHSCOPE_API_KEY", "api_key": "sk-test", "fps": 2},
                "prompt_template": {"system": "x", "single_choice_fields": {}, "multi_choice_fields": {}},
                "logging": {"log_dir": "output/logs", "capture_ffmpeg_output": True, "quiet_terminal": True},
                "reporting": {"generate_html_report": True, "html_report_file": "output/report/index.html"}
            }
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config["logging"]["quiet_terminal"] is True
    assert config["reporting"]["html_report_file"] == "output/report/index.html"
