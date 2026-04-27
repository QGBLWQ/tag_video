from pathlib import Path

from video_tagging_assistant.case_ingest_models import CaseTask, CopyTask, PullTask, UploadResult


def test_case_task_defaults_to_pending_status():
    task = CaseTask(
        case_id="case_A_0078",
        pull_task=PullTask(
            case_id="case_A_0078",
            device_path="/mnt/nvme/CapturedData/117",
            local_name="case_A_0078_RK_raw_117",
            move_src=r"E:\\DV\\case_A_0078_RK_raw_117",
            move_dst=r"E:\\DV\\OV50\\20260427\\case_A_0078\\case_A_0078_RK_raw_117",
        ),
        case_root_dir=Path(r"E:\\DV\\OV50\\20260427\\case_A_0078"),
        server_case_dir=Path(r"\\\\10.10.10.164\\rk3668_capture\\OV50\\20260427\\case_A_0078"),
    )

    assert task.status == "pending"
    assert task.copy_tasks == []


def test_upload_result_preserves_skip_exists_state():
    result = UploadResult(case_id="case_A_0078", status="upload_skipped_exists", message="exists")

    assert result.status == "upload_skipped_exists"
    assert result.message == "exists"
