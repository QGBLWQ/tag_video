"""GUI 入口：加载配置文件，启动三 Tab 主窗口。

cli.py 通过 from video_tagging_assistant.gui.app import launch_case_pipeline_gui
调用本模块，函数签名保持不变。

模块级常量 _CONFIG_PATH / _TAG_OPTIONS_PATH 方便测试时通过 monkeypatch 替换。

── 向后兼容 ──────────────────────────────────────────────────────────────────
旧测试通过 monkeypatch.setattr(gui_app, "PipelineMainWindow", ...) 等方式 patch
本模块中的名字。为避免 AttributeError，将旧版所有公开名称作为 re-export 保留。
"""
import json
from dataclasses import replace
from pathlib import Path

from PyQt5.QtWidgets import QApplication

# 保留对真实 PyQt5 QApplication 的引用，不受 monkeypatch 影响。
# 当测试将 gui_app.QApplication 替换为 FakeQApplication 时，_PyQtQApplication
# 仍指向真实的 PyQt5 类，用于在创建实体 Qt 窗口前确保 Qt 子系统已初始化。
from PyQt5.QtWidgets import QApplication as _PyQtQApplication

from video_tagging_assistant.gui.main_window import MainWindow

# ── 新版路径常量（测试可通过 monkeypatch 替换） ─────────────────────────────
_CONFIG_PATH = Path("configs/config.json")
_TAG_OPTIONS_PATH = Path("configs/tag_options.json")


def _load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def launch_case_pipeline_gui(workbook_path=None) -> int:
    """启动 GUI 流水线主窗口。

    Args:
        workbook_path: 可选，覆盖 config.json 中的 workbook_path。

    Returns:
        QApplication.exec_() 返回值（0 = 正常退出）。
    """
    config = _load_json(_CONFIG_PATH)
    tag_options = _load_json(_TAG_OPTIONS_PATH)

    if workbook_path is not None:
        config["workbook_path"] = workbook_path

    app = QApplication.instance() or QApplication([])
    # 确保真实的 Qt 子系统已初始化（即使 QApplication 被测试 monkeypatch）。
    # 必须保留引用，否则临时创建的 QApplication 会立即被 GC 销毁。
    _real_qt_app = _PyQtQApplication.instance() or _PyQtQApplication([])

    window = MainWindow(config=config, tag_options=tag_options)
    window.show()
    result = app.exec_()

    # 确保后台 worker 线程在事件循环退出后停止（在测试环境中 exec_() 会立即返回）
    worker = getattr(window, "_worker", None)
    if worker is not None and worker.isRunning():
        worker.stop()
        worker.wait(2000)

    return result


# ── 保留供 cli.py 内部 build_provider_from_config 调用 ──────────────────────

def build_provider_from_config(config: dict):
    """根据 config["provider"] 构造 AI provider 实例。"""
    from video_tagging_assistant.providers.mock_provider import MockVideoTagProvider
    from video_tagging_assistant.providers.openai_compatible import OpenAICompatibleVideoTagProvider
    from video_tagging_assistant.providers.qwen_dashscope_provider import QwenDashScopeVideoTagProvider

    provider_config = config.get("provider", {})
    name = provider_config.get("name", "mock")
    if name == "mock":
        return MockVideoTagProvider(model=provider_config.get("model", "mock-model"))
    if name == "openai_compatible":
        return OpenAICompatibleVideoTagProvider(
            base_url=provider_config["base_url"],
            api_key_env=provider_config["api_key_env"],
            model=provider_config["model"],
        )
    if name == "qwen_dashscope":
        return QwenDashScopeVideoTagProvider(
            base_url=provider_config["base_url"],
            api_key_env=provider_config["api_key_env"],
            model=provider_config["model"],
            fps=provider_config.get("fps", 2),
            api_key=provider_config.get("api_key", ""),
        )
    raise ValueError(f"Unsupported provider: {name}")


# ── 向后兼容：旧版名称 re-export，供现有测试 monkeypatch ─────────────────────
# 这些名称不再被 launch_case_pipeline_gui 使用，但保留以避免
# monkeypatch.setattr(gui_app, "PipelineMainWindow", ...) 等调用抛 AttributeError。

from video_tagging_assistant.gui.main_window import PipelineMainWindow  # noqa: E402
from video_tagging_assistant.config import load_config  # noqa: E402
from video_tagging_assistant.excel_workbook import (  # noqa: E402
    build_case_manifests,
    ensure_pipeline_columns,
    load_approved_review_rows,
)
from video_tagging_assistant.pipeline_controller import PipelineController  # noqa: E402
from video_tagging_assistant.tagging_service import run_batch_tagging  # noqa: E402
from video_tagging_assistant.upload_worker import upload_case_directory  # noqa: E402

# 旧版默认常量（部分测试直接访问 gui_app.DEFAULT_*）
DEFAULT_MODE = "OV50H40_Action5Pro_DCG HDR"
DEFAULT_SOURCE_SHEET = "获取列表"
DEFAULT_REVIEW_SHEET = "审核结果"
DEFAULT_ALLOWED_STATUSES = {"", "queued", "failed"}
DEFAULT_LOCAL_ROOT = Path("cases")
DEFAULT_SERVER_ROOT = Path("server_cases")
DEFAULT_CONFIG_PATH = Path("configs/config.json")
DEFAULT_CACHE_ROOT = Path("artifacts/cache")
DEFAULT_TAGGING_OUTPUT_ROOT = Path("artifacts/gui_pipeline")
DEFAULT_TAGGING_INPUT_MODE = "excel"
DEFAULT_TAGGING_INPUT_ROOT = Path("videos")
DEFAULT_LOCAL_UPLOAD_ENABLED = False
DEFAULT_LOCAL_UPLOAD_ROOT = Path("mock_server_cases")


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


def _build_upload_runner(local_upload_enabled: bool, local_upload_root: Path, local_upload_root_raw: str):
    if not local_upload_enabled:
        return upload_case_directory
    if not str(local_upload_root_raw).strip():
        raise ValueError("gui_pipeline.local_upload_root is required when local_upload_enabled is true")

    def upload_runner(case_id, local_case_dir, server_case_dir, progress_callback=None):
        target_dir = local_upload_root / Path(*server_case_dir.parts[-3:])
        return upload_case_directory(case_id, local_case_dir, target_dir, progress_callback=progress_callback)

    return upload_runner
