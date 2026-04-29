from pathlib import Path

from video_tagging_assistant.pipeline_controller import PipelineController
from video_tagging_assistant.pipeline_models import CaseManifest


def build_manifest(tmp_path: Path, case_id: str) -> CaseManifest:
    return CaseManifest(
        case_id=case_id,
        row_index=12,
        created_date="20260428",
        mode="OV50H40_Action5Pro_DCG HDR",
        raw_path=tmp_path / f"{case_id}_RK_raw_117",
        vs_normal_path=tmp_path / f"{case_id}_normal.MP4",
        vs_night_path=tmp_path / f"{case_id}_night.MP4",
        local_case_root=tmp_path / case_id,
        server_case_dir=tmp_path / "server" / case_id,
        remark="场景备注",
        labels={"安装方式": "手持"},
    )


def test_controller_moves_approved_case_into_execution_queue(tmp_path: Path):
    controller = PipelineController()
    manifest = build_manifest(tmp_path, "case_A_0105")

    controller.register_manifests([manifest])
    controller.mark_tagging_finished("case_A_0105")
    controller.approve_case("case_A_0105")

    queued = controller.dequeue_execution_case()
    assert queued.case_id == "case_A_0105"


def test_controller_does_not_block_on_other_reviews(tmp_path: Path):
    controller = PipelineController()
    first = build_manifest(tmp_path, "case_A_0105")
    second = build_manifest(tmp_path, "case_A_0106")

    controller.register_manifests([first, second])
    controller.mark_tagging_finished("case_A_0105")
    controller.mark_tagging_finished("case_A_0106")
    controller.approve_case("case_A_0105")

    queued = controller.dequeue_execution_case()
    assert queued.case_id == "case_A_0105"
    assert controller.get_case_state("case_A_0106").stage.value == "awaiting_review"


def test_execute_approved_case_runs_pull_copy_upload_in_order(tmp_path: Path):
    calls = []
    controller = PipelineController(
        pull_runner=lambda task, progress_callback=None: calls.append(("pull", task.case_id)),
        copy_runner=lambda tasks: calls.append(("copy", tasks[0].case_id)),
        upload_runner=lambda case_id, local_case_dir, server_case_dir, progress_callback=None: calls.append(("upload", case_id)),
    )
    manifest = build_manifest(tmp_path, "case_A_0105")
    controller.register_manifests([manifest])
    controller.mark_tagging_finished(manifest.case_id)
    controller.approve_case(manifest.case_id)

    controller.run_next_execution_case()

    assert calls == [
        ("pull", "case_A_0105"),
        ("copy", "case_A_0105"),
        ("upload", "case_A_0105"),
    ]
