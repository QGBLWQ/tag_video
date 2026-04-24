import argparse
from pathlib import Path

from video_tagging_assistant.config import load_config
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()

    config = load_config(Path(args.config))
    provider = build_provider_from_config(config)
    summary = run_batch(config, provider=provider)
    print(f"Processed {summary['processed']} videos")
    print(f"Review list: {summary['review_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
