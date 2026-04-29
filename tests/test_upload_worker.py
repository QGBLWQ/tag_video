from video_tagging_assistant.upload_worker import upload_case_directory


def test_upload_case_directory_skips_when_server_case_exists(tmp_path):
    local_case = tmp_path / "local" / "case_A_0078"
    server_case = tmp_path / "server" / "case_A_0078"
    local_case.mkdir(parents=True)
    server_case.mkdir(parents=True)

    result = upload_case_directory("case_A_0078", local_case, server_case)

    assert result.status == "upload_skipped_exists"


def test_upload_case_directory_copies_whole_case_when_missing(tmp_path):
    local_case = tmp_path / "local" / "case_A_0078"
    server_case = tmp_path / "server" / "case_A_0078"
    (local_case / "sub").mkdir(parents=True)
    (local_case / "sub" / "1.txt").write_text("ok", encoding="utf-8")

    result = upload_case_directory("case_A_0078", local_case, server_case)

    assert result.status == "uploaded"
    assert (server_case / "sub" / "1.txt").read_text(encoding="utf-8") == "ok"


def test_upload_case_directory_emits_start_and_finish_events(tmp_path):
    events = []
    source = tmp_path / "case_A_0105"
    source.mkdir()
    (source / "a.txt").write_text("a", encoding="utf-8")
    target = tmp_path / "server" / "case_A_0105"

    upload_case_directory("case_A_0105", source, target, progress_callback=events.append)

    assert events[0]["stage"] == "uploading"
    assert events[-1]["stage"] == "uploaded"
