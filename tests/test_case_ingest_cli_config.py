import json
from pathlib import Path

import pytest

from video_tagging_assistant.config import load_case_ingest_config


def test_load_case_ingest_config_resolves_paths_relative_to_config_file(tmp_path: Path):
    config_dir = tmp_path / "configs"
    scripts_dir = tmp_path / "scripts"
    server_dir = tmp_path / "server"
    config_dir.mkdir()
    scripts_dir.mkdir()
    server_dir.mkdir()

    (scripts_dir / "pull.bat").write_text("pull", encoding="utf-8")
    (scripts_dir / "move.bat").write_text("move", encoding="utf-8")

    config_path = config_dir / "case_ingest.json"
    config_path.write_text(
        json.dumps(
            {
                "pull_bat": "../scripts/pull.bat",
                "move_bat": "../scripts/move.bat",
                "server_root": "../server",
                "skip_upload": True,
            }
        ),
        encoding="utf-8",
    )

    resolved = load_case_ingest_config(config_path)

    assert resolved["pull_bat"] == (scripts_dir / "pull.bat").resolve()
    assert resolved["move_bat"] == (scripts_dir / "move.bat").resolve()
    assert resolved["server_root"] == server_dir.resolve()
    assert resolved["skip_upload"] is True


def test_load_case_ingest_config_uses_explicit_date_before_today(tmp_path: Path):
    config_path = tmp_path / "case_ingest.json"
    config_path.write_text(
        json.dumps(
            {
                "pull_bat": "pull.bat",
                "move_bat": "move.bat",
                "server_root": "server",
                "date": "20260420",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "pull.bat").write_text("pull", encoding="utf-8")
    (tmp_path / "move.bat").write_text("move", encoding="utf-8")
    (tmp_path / "server").mkdir()

    resolved = load_case_ingest_config(config_path, cli_date="20260428", today="20260429")

    assert resolved["date"] == "20260428"


def test_load_case_ingest_config_falls_back_to_today_when_date_missing(tmp_path: Path):
    config_path = tmp_path / "case_ingest.json"
    config_path.write_text(
        json.dumps(
            {
                "pull_bat": "pull.bat",
                "move_bat": "move.bat",
                "server_root": "server",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "pull.bat").write_text("pull", encoding="utf-8")
    (tmp_path / "move.bat").write_text("move", encoding="utf-8")
    (tmp_path / "server").mkdir()

    resolved = load_case_ingest_config(config_path, today="20260429")

    assert resolved["date"] == "20260429"


def test_load_case_ingest_config_raises_for_missing_required_key(tmp_path: Path):
    config_path = tmp_path / "case_ingest.json"
    config_path.write_text(json.dumps({"pull_bat": "pull.bat"}), encoding="utf-8")

    with pytest.raises(ValueError, match="Missing case-ingest config keys: move_bat, server_root"):
        load_case_ingest_config(config_path)


def test_case_ingest_cli_uses_config_mode(monkeypatch, tmp_path: Path, capsys):
    from video_tagging_assistant import cli

    config_path = tmp_path / "case_ingest.json"
    config_path.write_text("{}", encoding="utf-8")

    captured = {}

    monkeypatch.setattr(
        cli,
        "load_case_ingest_config",
        lambda path, cli_date=None, today=None: {
            "pull_bat": Path("C:/data/pull.bat"),
            "move_bat": Path("C:/data/move.bat"),
            "server_root": Path("C:/server/root"),
            "date": "20260428",
            "skip_upload": True,
        },
    )
    monkeypatch.setattr(
        cli,
        "group_case_tasks",
        lambda pull_bat, move_bat, server_root, date: captured.update(
            {
                "pull_bat": pull_bat,
                "move_bat": move_bat,
                "server_root": server_root,
                "date": date,
            }
        )
        or ["task-a", "task-b"],
    )
    monkeypatch.setattr(
        cli,
        "run_case_ingest",
        lambda tasks, skip_upload=False: {
            "processed": len(tasks),
            "uploaded": 0,
            "skipped": 2,
            "failed": 0,
        },
    )

    result = cli.main([
        "case-ingest",
        "--config",
        str(config_path),
    ])

    assert result == 0
    assert captured == {
        "pull_bat": Path("C:/data/pull.bat"),
        "move_bat": Path("C:/data/move.bat"),
        "server_root": Path("C:/server/root"),
        "date": "20260428",
    }
    out = capsys.readouterr().out
    assert "Processed 2 cases" in out
    assert "Skipped 2 cases" in out


def test_case_ingest_cli_keeps_legacy_argument_mode(monkeypatch, capsys):
    from video_tagging_assistant import cli

    captured = {}

    monkeypatch.setattr(
        cli,
        "group_case_tasks",
        lambda pull_bat, move_bat, server_root, date: captured.update(
            {
                "pull_bat": pull_bat,
                "move_bat": move_bat,
                "server_root": server_root,
                "date": date,
            }
        )
        or ["task-a"],
    )
    monkeypatch.setattr(
        cli,
        "run_case_ingest",
        lambda tasks, skip_upload=False: {
            "processed": len(tasks),
            "uploaded": 1,
            "skipped": 0,
            "failed": 0,
        },
    )

    result = cli.main([
        "case-ingest",
        "--pull-bat",
        "pull.bat",
        "--move-bat",
        "move.bat",
        "--date",
        "20260428",
        "--server-root",
        "server",
    ])

    assert result == 0
    assert captured == {
        "pull_bat": Path("pull.bat"),
        "move_bat": Path("move.bat"),
        "server_root": Path("server"),
        "date": "20260428",
    }
    out = capsys.readouterr().out
    assert "Processed 1 cases" in out
    assert "Uploaded 1 cases" in out


def test_case_ingest_example_config_contains_expected_keys():
    text = Path("configs/case_ingest.example.json").read_text(encoding="utf-8")

    assert '"pull_bat"' in text
    assert '"move_bat"' in text
    assert '"server_root"' in text
    assert '"date"' in text
    assert '"skip_upload"' in text


def test_case_ingest_launcher_uses_own_directory_to_find_config():
    text = Path("run_case_ingest.bat").read_text(encoding="utf-8")

    assert "%~dp0" in text
    assert "configs\\case_ingest.json" in text
    assert "python -m video_tagging_assistant.cli case-ingest --config" in text


def test_case_ingest_example_launcher_mentions_customization_points():
    text = Path("run_case_ingest.example.bat").read_text(encoding="utf-8")

    assert "set \"PYTHON_EXE=" in text
    assert "set \"CONFIG_PATH=" in text
    assert "-m video_tagging_assistant.cli case-ingest --config" in text


def test_load_case_ingest_config_reports_missing_pull_bat_file(tmp_path: Path):
    config_path = tmp_path / "case_ingest.json"
    config_path.write_text(
        json.dumps(
            {
                "pull_bat": "missing_pull.bat",
                "move_bat": "move.bat",
                "server_root": "server",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "move.bat").write_text("move", encoding="utf-8")
    (tmp_path / "server").mkdir()

    with pytest.raises(ValueError, match="Resolved pull_bat does not exist"):
        load_case_ingest_config(config_path, today="20260429")


def test_load_case_ingest_config_reports_missing_move_bat_file(tmp_path: Path):
    config_path = tmp_path / "case_ingest.json"
    config_path.write_text(
        json.dumps(
            {
                "pull_bat": "pull.bat",
                "move_bat": "missing_move.bat",
                "server_root": "server",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "pull.bat").write_text("pull", encoding="utf-8")
    (tmp_path / "server").mkdir()

    with pytest.raises(ValueError, match="Resolved move_bat does not exist"):
        load_case_ingest_config(config_path, today="20260429")
