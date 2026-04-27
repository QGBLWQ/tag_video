# Logging And Visual Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce noisy terminal output, capture detailed ffmpeg/provider logs to files, and generate a local HTML summary report while preserving the existing text review output.

**Architecture:** Keep the existing review exporter for text output and add a separate HTML export path. Update compression and orchestration so terminal output is summary-oriented while raw ffmpeg/provider details go to log files. Make logging/reporting fully configurable via the existing config file.

**Tech Stack:** Python 3.8, `pytest`, `json`, `pathlib`, `subprocess`, existing `video_tagging_assistant` package, local static HTML generation

---

## File Structure

**Modify:**
- `video_tagging_assistant/default_config.json` — add `logging` and `reporting` sections
- `video_tagging_assistant/compressor.py` — support quiet terminal mode and ffmpeg log capture
- `video_tagging_assistant/orchestrator.py` — add summary progress output, log paths, and HTML report integration
- `video_tagging_assistant/review_exporter.py` — keep text export but add an HTML export function or companion helper
- `tests/test_pipeline.py` — verify logging/reporting config and HTML report generation hooks

**Create:**
- `tests/test_html_report.py`
- `tests/test_logging_behavior.py`

---

### Task 1: Add Logging And Reporting Config

**Files:**
- Modify: `video_tagging_assistant/default_config.json`
- Create: `tests/test_logging_config.py`

- [ ] **Step 1: Write the failing logging/reporting config test**

```python
import json
from pathlib import Path

from video_tagging_assistant.config import load_config


def test_load_config_includes_logging_and_reporting_sections(tmp_path: Path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "input_dir": "videos",
                "output_dir": "output",
                "compression": {"width": 960, "video_bitrate": "700k", "audio_bitrate": "96k", "fps": 12},
                "provider": {"name": "qwen_dashscope", "model": "qwen3.6-flash", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "api_key_env": "DASHSCOPE_API_KEY", "api_key": "sk-test", "fps": 2},
                "prompt_template": {"system": "x", "single_choice_fields": {}, "multi_choice_fields": {}},
                "logging": {"log_dir": "output/logs", "capture_ffmpeg_output": True, "quiet_terminal": True},
                "reporting": {"generate_html_report": True, "html_report_file": "output/report/index.html"}
            }
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config["logging"]["quiet_terminal"] is True
    assert config["reporting"]["html_report_file"] == "output/report/index.html"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_logging_config.py::test_load_config_includes_logging_and_reporting_sections -v`
Expected: FAIL because the current default config does not include these sections.

- [ ] **Step 3: Update `video_tagging_assistant/default_config.json`**

Add:

```json
"logging": {
  "log_dir": "output/logs",
  "capture_ffmpeg_output": true,
  "quiet_terminal": true
},
"reporting": {
  "generate_html_report": true,
  "html_report_file": "output/report/index.html"
}
```

- [ ] **Step 4: Create `tests/test_logging_config.py`**

Write the test from Step 1 into the new file.

- [ ] **Step 5: Run the config test**

Run: `pytest tests/test_logging_config.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add video_tagging_assistant/default_config.json tests/test_logging_config.py
git commit -m "feat: add logging and reporting configuration"
```

### Task 2: Capture ffmpeg Output To Log Files And Quiet The Terminal

**Files:**
- Modify: `video_tagging_assistant/compressor.py`
- Create: `tests/test_logging_behavior.py`

- [ ] **Step 1: Write the failing ffmpeg log path test**

```python
from pathlib import Path

from video_tagging_assistant.compressor import build_ffmpeg_command


def test_build_ffmpeg_command_keeps_video_target_unchanged():
    command = build_ffmpeg_command(
        source=Path("videos/clip01.mp4"),
        target=Path("output/compressed/clip01_proxy.mp4"),
        compression_config={"width": 960, "video_bitrate": "700k", "audio_bitrate": "96k", "fps": 12},
    )

    assert command[-1].endswith("clip01_proxy.mp4")
```

Write a second failing test in `tests/test_logging_behavior.py` for the new log helper:

```python
from pathlib import Path

from video_tagging_assistant.compressor import get_ffmpeg_log_path


def test_get_ffmpeg_log_path_uses_log_directory(tmp_path: Path):
    log_path = get_ffmpeg_log_path(tmp_path / "logs", Path("videos/clip01.mp4"))
    assert log_path.name == "clip01.log"
    assert log_path.parent == tmp_path / "logs" / "compression"
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_logging_behavior.py -v`
Expected: FAIL because `get_ffmpeg_log_path()` does not exist.

- [ ] **Step 3: Update `video_tagging_assistant/compressor.py`**

Add helpers and quiet/log-aware execution, e.g.:

```python
import subprocess
from pathlib import Path
from typing import Dict, List

from video_tagging_assistant.models import CompressedArtifact, VideoTask


def get_ffmpeg_log_path(log_dir: Path, source_video_path: Path) -> Path:
    compression_dir = Path(log_dir) / "compression"
    compression_dir.mkdir(parents=True, exist_ok=True)
    return compression_dir / f"{source_video_path.stem}.log"


def compress_video(task: VideoTask, output_dir: Path, compression_config: Dict) -> CompressedArtifact:
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"{task.source_video_path.stem}_proxy.mp4"
    command = build_ffmpeg_command(task.source_video_path, target, compression_config)

    logging_config = compression_config.get("logging", {})
    log_dir = logging_config.get("log_dir")
    capture_ffmpeg_output = logging_config.get("capture_ffmpeg_output", False)

    stdout_handle = None
    stderr_handle = None
    try:
        if capture_ffmpeg_output and log_dir:
            log_path = get_ffmpeg_log_path(Path(log_dir), task.source_video_path)
            stdout_handle = open(log_path, "w", encoding="utf-8", errors="replace")
            stderr_handle = subprocess.STDOUT
        subprocess.run(command, check=True, stdout=stdout_handle, stderr=stderr_handle)
    finally:
        if stdout_handle is not None:
            stdout_handle.close()

    return CompressedArtifact(...)
```

Keep `build_ffmpeg_command()` compatible with existing tests.

- [ ] **Step 4: Run the logging behavior test**

Run: `pytest tests/test_logging_behavior.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add video_tagging_assistant/compressor.py tests/test_logging_behavior.py
git commit -m "feat: capture ffmpeg logs and quiet terminal output"
```

### Task 3: Add HTML Report Export

**Files:**
- Modify: `video_tagging_assistant/review_exporter.py`
- Create: `tests/test_html_report.py`

- [ ] **Step 1: Write the failing HTML report test**

```python
from pathlib import Path

from video_tagging_assistant.models import GenerationResult
from video_tagging_assistant.review_exporter import export_html_report


def test_export_html_report_writes_summary_and_rows(tmp_path: Path):
    output_path = tmp_path / "report" / "index.html"
    results = [
        GenerationResult(
            source_video_path=Path("videos/clip01.mp4"),
            structured_tags={"安装方式": "胸前", "光源": "自然光"},
            multi_select_tags={"画面特征": ["重复纹理"], "影像表达": ["建筑空间"]},
            scene_description="详细描述",
            provider="qwen_dashscope",
            model="qwen3.6-flash",
        )
    ]

    export_html_report(results, output_path)

    html = output_path.read_text(encoding="utf-8")
    assert "总视频数" in html
    assert "安装方式" in html
    assert "画面特征" in html
    assert "详细描述" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_html_report.py::test_export_html_report_writes_summary_and_rows -v`
Expected: FAIL because `export_html_report()` does not exist.

- [ ] **Step 3: Add `export_html_report()` to `video_tagging_assistant/review_exporter.py`**

Implement a simple static HTML generator, e.g.:

```python
def export_html_report(results: List[GenerationResult], output_path: Path) -> None:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    success_count = len(results)
    rows = []
    for result in results:
        rows.append(f"""
        <div class='item'>
          <h2>{result.source_video_path.as_posix()}</h2>
          <p><strong>安装方式</strong>: {result.structured_tags.get('安装方式', '')}</p>
          <p><strong>运动模式</strong>: {result.structured_tags.get('运动模式', '')}</p>
          <p><strong>运镜方式</strong>: {result.structured_tags.get('运镜方式', '')}</p>
          <p><strong>光源</strong>: {result.structured_tags.get('光源', '')}</p>
          <p><strong>画面特征</strong>: {', '.join(result.multi_select_tags.get('画面特征', []))}</p>
          <p><strong>影像表达</strong>: {', '.join(result.multi_select_tags.get('影像表达', []))}</p>
          <p><strong>画面描述</strong>: {result.scene_description}</p>
          <p><strong>审核状态</strong>: {result.review_status}</p>
          <p><strong>模型</strong>: {result.provider}/{result.model}</p>
        </div>
        """)

    html = f"""
    <html><head><meta charset='utf-8'><title>Video Tagging Report</title></head>
    <body>
      <h1>视频打标汇总报告</h1>
      <p>总视频数: {len(results)}</p>
      <p>成功数: {success_count}</p>
      {''.join(rows)}
    </body></html>
    """
    output_path.write_text(html, encoding="utf-8")
```

- [ ] **Step 4: Run the HTML report test**

Run: `pytest tests/test_html_report.py::test_export_html_report_writes_summary_and_rows -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add video_tagging_assistant/review_exporter.py tests/test_html_report.py
git commit -m "feat: add local html summary report"
```

### Task 4: Add Terminal Summary Output And Reporting Integration

**Files:**
- Modify: `video_tagging_assistant/orchestrator.py`
- Modify: `tests/test_pipeline.py`

- [ ] **Step 1: Write the failing HTML report integration test**

```python
import json
from pathlib import Path

from video_tagging_assistant.models import GenerationResult, CompressedArtifact
from video_tagging_assistant.orchestrator import run_batch


class StubCompressor:
    def __call__(self, task, output_dir, compression_config):
        output_dir.mkdir(parents=True, exist_ok=True)
        proxy = output_dir / f"{Path(task.file_name).stem}_proxy.mp4"
        proxy.write_bytes(b"proxy")
        return CompressedArtifact(task.source_video_path, proxy)


class StaticProvider:
    provider_name = "qwen_dashscope"

    def generate(self, context):
        return GenerationResult(
            source_video_path=context.source_video_path,
            structured_tags={"安装方式": "胸前"},
            multi_select_tags={"画面特征": ["重复纹理"]},
            scene_description="详细描述",
            provider="qwen_dashscope",
            model="qwen3.6-flash",
        )


def test_run_batch_generates_html_report_when_enabled(tmp_path: Path):
    input_dir = tmp_path / "videos"
    (input_dir / "a").mkdir(parents=True)
    (input_dir / "a" / "clip01.mp4").write_bytes(b"1")

    config = {
        "input_dir": str(input_dir),
        "output_dir": str(tmp_path / "output"),
        "paths": {
            "compressed_dir": str(tmp_path / "output" / "compressed"),
            "intermediate_dir": str(tmp_path / "output" / "intermediate"),
            "review_file": str(tmp_path / "output" / "review" / "review.txt"),
        },
        "compression": {"width": 960, "video_bitrate": "700k", "audio_bitrate": "96k", "fps": 12},
        "prompt_template": {"system": "x", "single_choice_fields": {}, "multi_choice_fields": {}},
        "concurrency": {"compression_workers": 1, "provider_workers": 1, "max_retries": 1, "retry_backoff_seconds": 0, "retry_backoff_multiplier": 2},
        "logging": {"log_dir": str(tmp_path / "output" / "logs"), "capture_ffmpeg_output": False, "quiet_terminal": True},
        "reporting": {"generate_html_report": True, "html_report_file": str(tmp_path / "output" / "report" / "index.html")},
    }

    summary = run_batch(config, compressor=StubCompressor(), provider=StaticProvider())

    assert Path(summary["html_report_path"]).exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline.py::test_run_batch_generates_html_report_when_enabled -v`
Expected: FAIL because `run_batch()` does not generate HTML or return its path.

- [ ] **Step 3: Update `video_tagging_assistant/orchestrator.py`**

Add:
- logging/reporting config reads
- compression config enrichment with `logging`
- summary prints guarded by `quiet_terminal`
- `export_html_report()` call when enabled
- return payload including `html_report_path`

Skeleton:

```python
from video_tagging_assistant.review_exporter import export_review_list, export_html_report

...
logging_config = config.get("logging", {})
reporting_config = config.get("reporting", {})
compression_config = dict(config["compression"])
compression_config["logging"] = logging_config

if not logging_config.get("quiet_terminal", False):
    print(f"Found {len(tasks)} videos")

...
html_report_path = None
if reporting_config.get("generate_html_report", False):
    html_report_path = Path(reporting_config["html_report_file"])
    export_html_report(results, html_report_path)

return {
    "processed": len(results),
    "review_path": str(review_path),
    "html_report_path": str(html_report_path) if html_report_path else "",
}
```

- [ ] **Step 4: Add the test from Step 1 to `tests/test_pipeline.py`**

- [ ] **Step 5: Run pipeline tests**

Run: `pytest tests/test_pipeline.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add video_tagging_assistant/orchestrator.py tests/test_pipeline.py
git commit -m "feat: add html report integration and quieter terminal output"
```

### Task 5: Verify End-To-End Logging And Reporting Workflow

**Files:**
- Modify: `deployment_package/default_config.json` (if needed to mirror new logging/reporting defaults)
- Modify: `deployment_package/README.md` (if needed to document HTML/log usage)

- [ ] **Step 1: Run the full focused suite**

Run: `pytest tests/test_scanner.py tests/test_config.py tests/test_context_builder.py tests/test_review_exporter.py tests/test_provider.py tests/test_pipeline.py tests/test_qwen_provider.py tests/test_qwen_provider_multiselect.py tests/test_qwen_prompt_ignore_opening.py tests/test_structured_result_model.py tests/test_multiselect_result_model.py tests/test_review_exporter_structured.py tests/test_review_exporter_multiselect.py tests/test_compression_concurrency.py tests/test_provider_retry.py tests/test_deployment_package.py tests/test_logging_config.py tests/test_logging_behavior.py tests/test_html_report.py -v`
Expected: PASS

- [ ] **Step 2: Run the real CLI**

Run: `python -m video_tagging_assistant.cli --config video_tagging_assistant/default_config.json`
Expected: Processes videos successfully while keeping terminal output concise.

- [ ] **Step 3: Verify log and report artifacts exist**

Run: `python - <<'PY'
from pathlib import Path
print((Path('output/report/index.html')).exists())
print((Path('output/logs')).exists())
PY`
Expected: `True` for the HTML report path; log directory exists when capture is enabled.

- [ ] **Step 4: Update deployment package docs/config**

Mirror the new logging/reporting sections into `deployment_package/default_config.json` and add a README section describing:
- where logs go
- where the HTML report is written
- how to keep the terminal quiet

- [ ] **Step 5: Commit**

```bash
git add deployment_package/default_config.json deployment_package/README.md
git commit -m "docs: document html reporting and quiet logging"
```

## Self-Review

### Spec Coverage

- Quiet terminal output and ffmpeg log capture: Tasks 1 and 2.
- HTML report generation: Tasks 3 and 4.
- Configurable log/report paths: Tasks 1 and 4.
- Retain text review output: preserved throughout exporter changes.
- Deployment docs updated: Task 5.

### Placeholder Scan

- No `TODO` / `TBD` placeholders remain.
- Every code step includes explicit code or concrete file contents.
- Every verification step includes an exact command and expected outcome.

### Type Consistency

- `logging.log_dir`, `logging.capture_ffmpeg_output`, `logging.quiet_terminal`, `reporting.generate_html_report`, and `reporting.html_report_file` are introduced consistently and reused in orchestration and deployment docs.
