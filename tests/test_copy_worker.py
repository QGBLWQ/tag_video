from video_tagging_assistant.case_ingest_models import CopyTask
from video_tagging_assistant.copy_worker import copy_declared_files


def test_copy_declared_files_copies_all_sources(tmp_path):
    source_file = tmp_path / "DJI_0001.MP4"
    source_file.write_bytes(b"video")
    target_file = tmp_path / "case_A_0078" / "case_A_0078_DJI_0001.MP4"
    tasks = [
        CopyTask(
            case_id="case_A_0078",
            source_path=source_file,
            target_path=target_file,
            kind="normal",
        )
    ]

    copy_declared_files(tasks)

    assert target_file.exists()
    assert target_file.read_bytes() == b"video"
