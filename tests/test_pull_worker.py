from video_tagging_assistant.case_ingest_models import PullTask
from video_tagging_assistant.pull_worker import merge_tmp_into_final, run_resumable_pull, validate_pull_counts


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
