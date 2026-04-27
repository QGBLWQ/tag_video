import json
from pathlib import Path

from video_tagging_assistant.config import load_config


def test_load_config_reads_expected_sections(tmp_path: Path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "input_dir": "videos",
                "output_dir": "output",
                "compression": {"width": 960, "video_bitrate": "700k"},
                "provider": {"name": "mock", "model": "fake-model"},
                "prompt_template": {"system": "describe video"},
            }
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config["input_dir"] == "videos"
    assert config["provider"]["name"] == "mock"
    assert config["compression"]["width"] == 960


def test_load_config_keeps_optional_case_ingest_defaults(tmp_path: Path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "input_dir": "videos",
                "output_dir": "output",
                "compression": {"width": 960, "video_bitrate": "700k"},
                "provider": {"name": "mock", "model": "fake-model"},
                "prompt_template": {"system": "describe video"},
                "case_ingest": {"server_root": r"\\10.10.10.164\rk3668_capture"},
            }
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config["case_ingest"]["server_root"] == r"\\10.10.10.164\rk3668_capture"
    assert config["case_ingest"]["skip_upload"] is False
    assert config["case_ingest"]["upload_workers"] == 1
