from dataclasses import replace
from pathlib import Path

from PyQt5.QtWidgets import QApplication

from video_tagging_assistant.config import load_config
from video_tagging_assistant.excel_workbook import (
    build_case_manifests,
    ensure_pipeline_columns,
    load_approved_review_rows,
)
from video_tagging_assistant.gui.main_window import PipelineMainWindow
from video_tagging_assistant.pipeline_controller import PipelineController
from video_tagging_assistant.providers.mock_provider import MockVideoTagProvider
from video_tagging_assistant.providers.openai_compatible import OpenAICompatibleVideoTagProvider
from video_tagging_assistant.providers.qwen_dashscope_provider import QwenDashScopeVideoTagProvider
from video_tagging_assistant.tagging_service import run_batch_tagging

DEFAULT_MODE = "OV50H40_Action5Pro_DCG HDR"
DEFAULT_SOURCE_SHEET = "创建记录"
DEFAULT_REVIEW_SHEET = "审核结果"
DEFAULT_ALLOWED_STATUSES = {"", "queued", "failed"}
DEFAULT_LOCAL_ROOT = Path("cases")
DEFAULT_SERVER_ROOT = Path("server_cases")
DEFAULT_CONFIG_PATH = Path("configs/config.json")
DEFAULT_CACHE_ROOT = Path("artifacts/cache")
DEFAULT_TAGGING_OUTPUT_ROOT = Path("artifacts/gui_pipeline")
DEFAULT_TAGGING_INPUT_MODE = "excel"
DEFAULT_TAGGING_INPUT_ROOT = Path("videos")


def build_provider_from_config(config: dict):
    provider_config = config["provider"]
    if provider_config["name"] == "mock":
        return MockVideoTagProvider(model=provider_config["model"])
    if provider_config["name"] == "openai_compatible":
        return OpenAICompatibleVideoTagProvider(
            base_url=provider_config["base_url"],
            api_key_env=provider_config["api_key_env"],
            model=provider_config["model"],
        )
    if provider_config["name"] == "qwen_dashscope":
        return QwenDashScopeVideoTagProvider(
            base_url=provider_config["base_url"],
            api_key_env=provider_config["api_key_env"],
            model=provider_config["model"],
            fps=provider_config.get("fps", 2),
            api_key=provider_config.get("api_key", ""),
        )
    raise ValueError(f"Unsupported provider: {provider_config['name']}")


def _resolve_tagging_manifests(manifests, tagging_input_mode: str, tagging_input_root: Path):
    if tagging_input_mode == "excel":
        return manifests
    if tagging_input_mode != "local_root":
        raise ValueError(f"Unsupported gui_pipeline.tagging_input_mode: {tagging_input_mode}")

    resolved = []
    for manifest in manifests:
        local_normal = tagging_input_root / manifest.vs_normal_path.name
        local_night = tagging_input_root / manifest.vs_night_path.name
        if not local_normal.exists():
            raise FileNotFoundError(
                f"Local tagging input not found for {manifest.case_id}: {local_normal}"
            )
        if not local_night.exists():
            raise FileNotFoundError(
                f"Local tagging input not found for {manifest.case_id}: {local_night}"
            )
        resolved.append(
            replace(
                manifest,
                vs_normal_path=local_normal,
                vs_night_path=local_night,
            )
        )
    return resolved


def launch_case_pipeline_gui(workbook_path=None):
    app = QApplication.instance() or QApplication([])
    workbook = Path(workbook_path) if workbook_path else None
    controller = PipelineController()
    config = load_config(DEFAULT_CONFIG_PATH)
    gui_pipeline = config.get("gui_pipeline", {})

    source_sheet = gui_pipeline.get("source_sheet", DEFAULT_SOURCE_SHEET)
    review_sheet = gui_pipeline.get("review_sheet", DEFAULT_REVIEW_SHEET)
    mode_name = gui_pipeline.get("mode", DEFAULT_MODE)
    allowed_statuses = set(gui_pipeline.get("allowed_statuses", list(DEFAULT_ALLOWED_STATUSES)))
    local_root = Path(gui_pipeline.get("local_root", str(DEFAULT_LOCAL_ROOT)))
    server_root = Path(gui_pipeline.get("server_root", str(DEFAULT_SERVER_ROOT)))
    cache_root = Path(gui_pipeline.get("cache_root", str(DEFAULT_CACHE_ROOT)))
    tagging_output_root = Path(gui_pipeline.get("tagging_output_root", str(DEFAULT_TAGGING_OUTPUT_ROOT)))
    tagging_input_mode = gui_pipeline.get("tagging_input_mode", DEFAULT_TAGGING_INPUT_MODE)
    tagging_input_root = Path(gui_pipeline.get("tagging_input_root", str(DEFAULT_TAGGING_INPUT_ROOT)))

    def scan_cases():
        if workbook is None or not workbook.exists():
            return []
        ensure_pipeline_columns(workbook, source_sheet=source_sheet)
        return build_case_manifests(
            workbook,
            source_sheet=source_sheet,
            allowed_statuses=allowed_statuses,
            local_root=local_root,
            server_root=server_root,
            mode=mode_name,
        )

    def refresh_excel_reviews():
        if workbook is None or not workbook.exists():
            return []
        return load_approved_review_rows(workbook, review_sheet=review_sheet)

    def run_execution_case(case_id):
        if controller.has_execution_case():
            controller.run_next_execution_case()

    def start_tagging(manifests, mode, event_callback):
        provider = build_provider_from_config(config)
        runtime_manifests = _resolve_tagging_manifests(
            manifests,
            tagging_input_mode=tagging_input_mode,
            tagging_input_root=tagging_input_root,
        )
        return run_batch_tagging(
            manifests=runtime_manifests,
            cache_root=cache_root,
            output_root=tagging_output_root,
            provider=provider,
            prompt_template=config["prompt_template"],
            mode=mode,
            event_callback=event_callback,
        )

    window = PipelineMainWindow(
        workbook_path=str(workbook) if workbook else None,
        scan_cases=scan_cases,
        start_tagging=start_tagging,
        refresh_excel_reviews=refresh_excel_reviews,
        run_execution_case=run_execution_case,
        controller=controller,
    )
    window.show()
    return app.exec_()
