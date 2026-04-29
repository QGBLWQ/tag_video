import argparse
from datetime import date as date_cls
from pathlib import Path

from video_tagging_assistant.bat_parser import group_case_tasks
from video_tagging_assistant.case_ingest_orchestrator import run_case_ingest
from video_tagging_assistant.config import load_case_ingest_config, load_config
from video_tagging_assistant.gui.app import launch_case_pipeline_gui
from video_tagging_assistant.orchestrator import run_batch
from video_tagging_assistant.providers.mock_provider import MockVideoTagProvider
from video_tagging_assistant.providers.openai_compatible import OpenAICompatibleVideoTagProvider
from video_tagging_assistant.providers.qwen_dashscope_provider import QwenDashScopeVideoTagProvider


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


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config")
    subparsers = parser.add_subparsers(dest="command")

    case_ingest_parser = subparsers.add_parser("case-ingest")
    case_ingest_parser.add_argument("--config")
    case_ingest_parser.add_argument("--pull-bat")
    case_ingest_parser.add_argument("--move-bat")
    case_ingest_parser.add_argument("--date")
    case_ingest_parser.add_argument("--server-root")
    case_ingest_parser.add_argument("--skip-upload", action="store_true")

    case_pipeline_parser = subparsers.add_parser("case-pipeline-gui")
    case_pipeline_parser.add_argument("--workbook")

    args = parser.parse_args(argv)

    if args.command == "case-ingest":
        if args.config:
            today = date_cls.today().strftime("%Y%m%d")
            resolved = load_case_ingest_config(Path(args.config), cli_date=args.date, today=today)
            tasks = group_case_tasks(
                resolved["pull_bat"],
                resolved["move_bat"],
                resolved["server_root"],
                resolved["date"],
            )
            summary = run_case_ingest(
                tasks,
                skip_upload=bool(args.skip_upload or resolved.get("skip_upload", False)),
            )
        else:
            if not args.pull_bat or not args.move_bat or not args.server_root or not args.date:
                case_ingest_parser.error(
                    "either --config or all of --pull-bat --move-bat --server-root --date are required"
                )
            tasks = group_case_tasks(
                Path(args.pull_bat),
                Path(args.move_bat),
                Path(args.server_root),
                args.date,
            )
            summary = run_case_ingest(tasks, skip_upload=args.skip_upload)

        print(f"Processed {summary['processed']} cases")
        print(f"Uploaded {summary['uploaded']} cases")
        print(f"Skipped {summary['skipped']} cases")
        print(f"Failed {summary['failed']} cases")
        return 0

    if args.command == "case-pipeline-gui":
        return launch_case_pipeline_gui(workbook_path=getattr(args, "workbook", None))

    if not args.config:
        parser.error("--config is required unless using case-ingest")

    config = load_config(Path(args.config))
    provider = build_provider_from_config(config)
    summary = run_batch(config, provider=provider)
    print(f"Processed {summary['processed']} videos")
    print(f"Review list: {summary['review_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
