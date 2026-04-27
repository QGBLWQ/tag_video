from pathlib import Path


def test_deployment_package_contains_runtime_code():
    base = Path("deployment_package")
    assert (base / "video_tagging_assistant" / "cli.py").exists()
    assert (base / "video_tagging_assistant" / "orchestrator.py").exists()
    assert (base / "qwen_video_compress_and_test.py").exists()
    assert (base / "pytest.ini").exists()
