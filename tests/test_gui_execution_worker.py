from pathlib import Path
from unittest.mock import patch

from PyQt5.QtWidgets import QApplication

from video_tagging_assistant.pipeline_models import CaseManifest
from video_tagging_assistant.gui.execution_worker import ExecutionWorker


_APP = QApplication.instance() or QApplication([])


def _make_manifest(case_id: str = "case_A_0078") -> CaseManifest:
    return CaseManifest(
        case_id=case_id,
        row_index=2,
        created_date="20260422",
        mode="OV50H40_Action5Pro_DCG HDR",
        raw_path=Path("/mnt/nvme/CapturedData/117"),
        vs_normal_path=Path("DJI_0001.MP4"),
        vs_night_path=Path("DJI_0021.MP4"),
        local_case_root=Path("/tmp/local/case"),
        server_case_dir=Path("/tmp/server/case"),
        remark="",
    )


def _make_config() -> dict:
    return {
        "adb_exe": "adb.exe",
        "dut_root": "/mnt/nvme/CapturedData",
        "local_case_root": "/tmp/local",
        "server_upload_root": "/tmp/server",
        "mode": "OV50H40_Action5Pro_DCG HDR",
    }


def test_worker_emits_started_and_completed_for_each_step():
    signals = []
    with patch("video_tagging_assistant.gui.execution_worker.pull_case"), \
         patch("video_tagging_assistant.gui.execution_worker.move_case"), \
         patch("video_tagging_assistant.gui.execution_worker.upload_case"):

        worker = ExecutionWorker(_make_config())
        worker.status_changed.connect(
            lambda case_id, step, status, msg: signals.append((case_id, step, status))
        )
        worker.enqueue(_make_manifest("case_A_0078"))
        worker.stop()
        worker.start()
        worker.wait(5000)

    assert ("case_A_0078", "pull", "started") in signals
    assert ("case_A_0078", "pull", "completed") in signals
    assert ("case_A_0078", "move", "started") in signals
    assert ("case_A_0078", "move", "completed") in signals
    assert ("case_A_0078", "upload", "started") in signals
    assert ("case_A_0078", "upload", "completed") in signals


def test_worker_emits_failed_on_exception_and_skips_remaining_steps():
    signals = []
    with patch("video_tagging_assistant.gui.execution_worker.pull_case",
               side_effect=RuntimeError("adb connection refused")), \
         patch("video_tagging_assistant.gui.execution_worker.move_case") as mock_move, \
         patch("video_tagging_assistant.gui.execution_worker.upload_case") as mock_upload:

        worker = ExecutionWorker(_make_config())
        worker.status_changed.connect(
            lambda case_id, step, status, msg: signals.append((case_id, step, status))
        )
        worker.enqueue(_make_manifest("case_A_0001"))
        worker.stop()
        worker.start()
        worker.wait(5000)

    assert ("case_A_0001", "pull", "started") in signals
    assert ("case_A_0001", "pull", "failed") in signals
    assert ("case_A_0001", "move", "started") not in signals
    mock_move.assert_not_called()
    mock_upload.assert_not_called()


def test_worker_continues_to_next_case_after_failure():
    signals = []
    pull_calls = []

    def pull_side_effect(manifest, config):
        pull_calls.append(manifest.case_id)
        if manifest.case_id == "case_A_0001":
            raise RuntimeError("first case fails")

    with patch("video_tagging_assistant.gui.execution_worker.pull_case",
               side_effect=pull_side_effect), \
         patch("video_tagging_assistant.gui.execution_worker.move_case"), \
         patch("video_tagging_assistant.gui.execution_worker.upload_case"):

        worker = ExecutionWorker(_make_config())
        worker.status_changed.connect(
            lambda case_id, step, status, msg: signals.append((case_id, step, status))
        )
        worker.enqueue(_make_manifest("case_A_0001"))
        worker.enqueue(_make_manifest("case_A_0002"))
        worker.stop()
        worker.start()
        worker.wait(5000)

    assert ("case_A_0001", "pull", "failed") in signals
    assert ("case_A_0002", "pull", "completed") in signals
    assert pull_calls == ["case_A_0001", "case_A_0002"]
