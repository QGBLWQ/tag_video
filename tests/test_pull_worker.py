import pytest

from video_tagging_assistant.case_ingest_models import PullTask
from video_tagging_assistant.pull_worker import (
    consume_temp_pull_source,
    merge_tmp_into_final,
    run_resumable_pull,
    validate_pull_counts,
)


def test_consume_temp_pull_source_moves_matching_rk_dir_into_final(tmp_path):
    temp_root = tmp_path / "temp_pull_cache"
    source_dir = temp_root / "117"
    (source_dir / "nested").mkdir(parents=True)
    (source_dir / "nested" / "a.txt").write_text("ok", encoding="utf-8")
    final_dir = tmp_path / "case_A_0078_RK_raw_117"

    consumed = consume_temp_pull_source(temp_root, "117", final_dir)

    assert consumed is True
    assert (final_dir / "nested" / "a.txt").read_text(encoding="utf-8") == "ok"
    assert not source_dir.exists()


def test_consume_temp_pull_source_keeps_source_when_final_is_already_complete(tmp_path):
    temp_root = tmp_path / "temp_pull_cache"
    source_dir = temp_root / "117"
    final_dir = tmp_path / "case_A_0078_RK_raw_117"
    source_dir.mkdir(parents=True)
    final_dir.mkdir(parents=True)
    (source_dir / "a.txt").write_text("temp", encoding="utf-8")
    (final_dir / "a.txt").write_text("final", encoding="utf-8")

    consumed = consume_temp_pull_source(temp_root, "117", final_dir)

    assert consumed is True
    assert source_dir.exists()
    assert (final_dir / "a.txt").read_text(encoding="utf-8") == "final"


def test_consume_temp_pull_source_returns_false_for_missing_or_empty_dir(tmp_path):
    temp_root = tmp_path / "temp_pull_cache"
    (temp_root / "117").mkdir(parents=True)
    final_dir = tmp_path / "case_A_0078_RK_raw_117"

    assert consume_temp_pull_source(temp_root, "118", final_dir) is False
    assert consume_temp_pull_source(temp_root, "117", final_dir) is False


def test_consume_temp_pull_source_raises_when_post_merge_count_mismatches(tmp_path, monkeypatch):
    temp_root = tmp_path / "temp_pull_cache"
    source_dir = temp_root / "117"
    source_dir.mkdir(parents=True)
    (source_dir / "a.txt").write_text("a", encoding="utf-8")
    (source_dir / "b.txt").write_text("b", encoding="utf-8")
    final_dir = tmp_path / "case_A_0078_RK_raw_117"

    def fake_merge(tmp_dir, target_dir):
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "a.txt").write_text("partial", encoding="utf-8")

    monkeypatch.setattr("video_tagging_assistant.pull_worker.merge_tmp_into_final", fake_merge)

    with pytest.raises(RuntimeError, match="temp_path validation failed for rk_suffix=117"):
        consume_temp_pull_source(temp_root, "117", final_dir)


def test_merge_tmp_into_final_moves_missing_files_only(tmp_path):
    final_dir = tmp_path / "case_A_0078_RK_raw_117"
    tmp_dir = tmp_path / "case_A_0078_RK_raw_117_tmp"
    (final_dir / "a").mkdir(parents=True)
    (tmp_dir / "a").mkdir(parents=True)
    (final_dir / "a" / "1.txt").write_text("old", encoding="utf-8")
    (tmp_dir / "a" / "1.txt").write_text("new", encoding="utf-8")
    (tmp_dir / "a" / "2.txt").write_text("new", encoding="utf-8")

    merge_tmp_into_final(tmp_dir, final_dir)

    assert (final_dir / "a" / "1.txt").read_text(encoding="utf-8") == "old"
    assert (final_dir / "a" / "2.txt").read_text(encoding="utf-8") == "new"
    assert not tmp_dir.exists()


def test_validate_pull_counts_returns_true_when_equal(tmp_path):
    final_dir = tmp_path / "case_A_0078_RK_raw_117"
    final_dir.mkdir()
    (final_dir / "1.txt").write_text("1", encoding="utf-8")
    (final_dir / "2.txt").write_text("2", encoding="utf-8")

    assert validate_pull_counts(2, final_dir) is True


def test_run_resumable_pull_uses_move_dst_as_final_directory(monkeypatch, tmp_path):
    move_dst = tmp_path / "case_A_0078" / "case_A_0078_RK_raw_117"
    task = PullTask(
        case_id="case_A_0078",
        device_path="/mnt/nvme/CapturedData/117",
        local_name="case_A_0078_RK_raw_117",
        move_src=str(move_dst),
        move_dst=str(move_dst),
    )

    monkeypatch.setattr("video_tagging_assistant.pull_worker.count_remote_files", lambda device_path: 1)

    def fake_run(command, check=False, **kwargs):
        target = move_dst.parent / f"{move_dst.name}_tmp"
        target.mkdir(parents=True, exist_ok=True)
        (target / "1.txt").write_text("ok", encoding="utf-8")
        class Result:
            returncode = 0
            stdout = ""
            stderr = ""
        return Result()

    monkeypatch.setattr("video_tagging_assistant.pull_worker.subprocess.run", fake_run)

    result = run_resumable_pull(task)

    assert result == move_dst
    assert (move_dst / "1.txt").exists()


def test_run_resumable_pull_emits_progress_events(tmp_path, monkeypatch):
    events = []
    final_dir = tmp_path / "case_A_0105_RK_raw_117"

    monkeypatch.setattr("video_tagging_assistant.pull_worker.count_remote_files", lambda path: 2)
    monkeypatch.setattr("video_tagging_assistant.pull_worker.validate_pull_counts", lambda remote_count, path: True)
    monkeypatch.setattr("video_tagging_assistant.pull_worker.subprocess.run", lambda *args, **kwargs: None)

    task = PullTask(
        case_id="case_A_0105",
        device_path="/mnt/nvme/CapturedData/117",
        local_name="case_A_0105_RK_raw_117",
        move_src=str(tmp_path / "case_A_0105_RK_raw_117"),
        move_dst=str(final_dir),
    )

    run_resumable_pull(task, progress_callback=events.append)

    assert any(event["stage"] == "pulling" for event in events)
