from pathlib import Path


def test_readme_points_users_to_core_entry_sections():
    text = Path("README.md").read_text(encoding="utf-8")

    assert "# 视频打标与 Case Ingest 工具" in text
    assert "## 快速开始" in text
    assert "run_case_ingest.bat" in text
    assert "configs/case_ingest.json" in text
    assert "docs/architecture.md" in text


def test_architecture_doc_covers_both_pipelines_and_cli_split():
    text = Path("docs/architecture.md").read_text(encoding="utf-8")

    assert "# 架构说明" in text
    assert "video_tagging_assistant/cli.py" in text
    assert "视频打标流程" in text
    assert "Case Ingest 流程" in text
    assert "video_tagging_assistant/orchestrator.py" in text
    assert "video_tagging_assistant/case_ingest_orchestrator.py" in text


def test_readme_focuses_on_usage_and_navigation():
    text = Path("README.md").read_text(encoding="utf-8")

    assert "## 项目能力概览" in text
    assert "## 环境要求" in text
    assert "## 关键配置文件" in text
    assert "## 输出位置" in text
    assert "video_tagging_assistant/default_config.json" in text
    assert "configs/case_ingest.json" in text
    assert "docs/case-ingest-usage.md" in text


def test_architecture_doc_covers_runtime_structure_and_limits():
    text = Path("docs/architecture.md").read_text(encoding="utf-8")

    assert "## 运行入口与分流" in text
    assert "## 视频打标流程架构" in text
    assert "## Case Ingest 流程架构" in text
    assert "## 关键文件职责" in text
    assert "## 配置与运行时关系" in text
    assert "## 当前实现边界与限制" in text
    assert "video_tagging_assistant/config.py" in text
    assert "video_tagging_assistant/bat_parser.py" in text


def test_docs_cross_reference_each_other_cleanly():
    readme = Path("README.md").read_text(encoding="utf-8")
    architecture = Path("docs/architecture.md").read_text(encoding="utf-8")

    assert "docs/architecture.md" in readme
    assert "README.md" in architecture
    assert "run_case_ingest.bat" in readme
    assert "configs/case_ingest.json" in architecture
