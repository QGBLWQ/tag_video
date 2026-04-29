from pathlib import Path

from video_tagging_assistant.case_ingest_models import CaseTask, CopyTask, PullTask
from video_tagging_assistant.pipeline_models import CaseManifest


def build_case_task(manifest: CaseManifest) -> CaseTask:
    pull_dir_name = manifest.raw_path.name
    raw_suffix = pull_dir_name.split("_")[-1]
    pull_task = PullTask(
        case_id=manifest.case_id,
        device_path=f"/mnt/nvme/CapturedData/{raw_suffix}",
        local_name=pull_dir_name,
        move_src=str(Path.cwd() / pull_dir_name),
        move_dst=str(manifest.local_case_root / pull_dir_name),
    )
    copy_tasks = [
        CopyTask(
            case_id=manifest.case_id,
            source_path=manifest.vs_normal_path,
            target_path=manifest.local_case_root / f"{manifest.case_id}_{manifest.vs_normal_path.name}",
            kind="normal",
        ),
        CopyTask(
            case_id=manifest.case_id,
            source_path=manifest.vs_night_path,
            target_path=manifest.local_case_root / f"{manifest.case_id}_night_{manifest.vs_night_path.name}",
            kind="night",
        ),
    ]
    return CaseTask(
        case_id=manifest.case_id,
        pull_task=pull_task,
        copy_tasks=copy_tasks,
        case_root_dir=manifest.local_case_root,
        server_case_dir=manifest.server_case_dir,
    )
