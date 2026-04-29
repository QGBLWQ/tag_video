import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from video_tagging_assistant.pipeline_models import CaseManifest
from video_tagging_assistant.case_ingest_orchestrator import pull_case, move_case, upload_case


def _make_manifest(tmp_path: Path) -> CaseManifest:
    return CaseManifest(
        case_id="case_A_0078",
        row_index=2,
        created_date="20260422",
        mode="OV50H40_Action5Pro_DCG HDR",
        raw_path=Path("/mnt/nvme/CapturedData/117"),  # name = "117"
        vs_normal_path=Path("DJI_20260422151829_0001_D.MP4"),
        vs_night_path=Path("DJI_20260422151916_0021_D.MP4"),
        local_case_root=tmp_path / "cases" / "OV50H40_Action5Pro_DCG HDR" / "20260422" / "case_A_0078",
        server_case_dir=tmp_path / "server" / "OV50H40_Action5Pro_DCG HDR" / "20260422" / "case_A_0078",
        remark="",
    )


def _make_config(tmp_path: Path) -> dict:
    return {
        "adb_exe": "adb.exe",
        "dut_root": "/mnt/nvme/CapturedData",
        "local_case_root": str(tmp_path),
        "server_upload_root": str(tmp_path / "server"),
        "mode": "OV50H40_Action5Pro_DCG HDR",
    }


def test_pull_case_calls_adb_with_correct_args(tmp_path: Path):
    manifest = _make_manifest(tmp_path)
    config = _make_config(tmp_path)

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        pull_case(manifest, config)

    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert cmd[0] == "adb.exe"
    assert cmd[1] == "pull"
    assert "/mnt/nvme/CapturedData/117" in cmd[2]
    assert "case_A_0078_RK_raw_117" in cmd[3]


def test_move_case_moves_to_structured_directory(tmp_path: Path):
    manifest = _make_manifest(tmp_path)
    config = _make_config(tmp_path)
    # pull_case would create this directory
    src = tmp_path / "case_A_0078_RK_raw_117"
    src.mkdir(parents=True)
    (src / "data.bin").write_bytes(b"rawdata")

    move_case(manifest, config)

    dest = (tmp_path / "OV50H40_Action5Pro_DCG HDR" / "20260422"
            / "case_A_0078" / "case_A_0078_RK_raw_117")
    assert dest.exists()
    assert (dest / "data.bin").read_bytes() == b"rawdata"
    assert not src.exists()


def test_upload_case_copies_directory_to_server(tmp_path: Path):
    manifest = _make_manifest(tmp_path)
    config = _make_config(tmp_path)
    case_dir = (tmp_path / "OV50H40_Action5Pro_DCG HDR" / "20260422" / "case_A_0078")
    case_dir.mkdir(parents=True)
    (case_dir / "payload.bin").write_bytes(b"upload")

    upload_case(manifest, config)

    dest = (tmp_path / "server" / "OV50H40_Action5Pro_DCG HDR"
            / "20260422" / "case_A_0078" / "payload.bin")
    assert dest.exists()
    assert dest.read_bytes() == b"upload"


def test_upload_case_raises_if_destination_exists(tmp_path: Path):
    manifest = _make_manifest(tmp_path)
    config = _make_config(tmp_path)
    case_dir = (tmp_path / "OV50H40_Action5Pro_DCG HDR" / "20260422" / "case_A_0078")
    case_dir.mkdir(parents=True)
    dest = (tmp_path / "server" / "OV50H40_Action5Pro_DCG HDR"
            / "20260422" / "case_A_0078")
    dest.mkdir(parents=True)

    with pytest.raises(RuntimeError, match="already exists"):
        upload_case(manifest, config)
