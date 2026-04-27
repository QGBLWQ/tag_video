# Concurrency And Deployment Packaging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add adaptive concurrency to compression and Qwen analysis, strengthen the scene-description rule to ignore the fixed phone-time opening shot, and package the project into a deployment folder with a README for use on other machines.

**Architecture:** Keep the current batch pipeline but split execution into two stages: concurrent compression followed by bounded-concurrency provider calls with retry/backoff. Move runtime-sensitive paths and concurrency limits into configuration, then emit a deployable folder containing the package, config, helper scripts, and documentation.

**Tech Stack:** Python 3.8, `pytest`, `pathlib`, `json`, `concurrent.futures`, existing `video_tagging_assistant` package, DashScope OpenAI-compatible HTTP

---

## File Structure

**Modify:**
- `video_tagging_assistant/default_config.json` — add concurrency settings and finalize prompt rules
- `video_tagging_assistant/orchestrator.py` — add concurrent compression, bounded provider concurrency, and retry/backoff handling
- `video_tagging_assistant/providers/qwen_dashscope_provider.py` — strengthen the ignore-opening prompt rule and surface provider errors cleanly
- `tests/test_pipeline.py` — verify configurable paths and mixed-schema pipeline with concurrency-aware orchestration
- `tests/test_qwen_provider_multiselect.py` — verify stronger scene-description prompt constraints

**Create:**
- `deployment_package/README.md`
- `deployment_package/default_config.json`
- `deployment_package/run_cli.bat`
- `deployment_package/requirements.txt`

**Copy Into Deployment Package:**
- `video_tagging_assistant/`
- `qwen_video_compress_and_test.py`
- `pytest.ini` (optional if keeping tests in the package)

---

### Task 1: Add Concurrency Config To Default Configuration

**Files:**
- Modify: `video_tagging_assistant/default_config.json`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Write the failing concurrency config test**

```python
import json
from pathlib import Path

from video_tagging_assistant.config import load_config


def test_load_config_includes_concurrency_settings(tmp_path: Path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "input_dir": "videos",
                "output_dir": "output",
                "compression": {"width": 960, "video_bitrate": "700k", "audio_bitrate": "96k", "fps": 12},
                "provider": {"name": "qwen_dashscope", "model": "qwen3.6-flash", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "api_key_env": "DASHSCOPE_API_KEY", "api_key": "sk-test", "fps": 2},
                "prompt_template": {"system": "x", "single_choice_fields": {}, "multi_choice_fields": {}},
                "concurrency": {
                    "compression_workers": 2,
                    "provider_workers": 2,
                    "max_retries": 3,
                    "retry_backoff_seconds": 2,
                    "retry_backoff_multiplier": 2
                }
            }
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config["concurrency"]["compression_workers"] == 2
    assert config["concurrency"]["provider_workers"] == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py::test_load_config_includes_concurrency_settings -v`
Expected: FAIL because the current default config does not include the `concurrency` section.

- [ ] **Step 3: Update `video_tagging_assistant/default_config.json`**

Add:

```json
"concurrency": {
  "compression_workers": 2,
  "provider_workers": 2,
  "max_retries": 3,
  "retry_backoff_seconds": 2,
  "retry_backoff_multiplier": 2
}
```

Place it at top level next to `compression`, `provider`, and `prompt_template`.

- [ ] **Step 4: Add the new test to `tests/test_config.py`**

Append the test from Step 1.

- [ ] **Step 5: Run config tests**

Run: `pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add video_tagging_assistant/default_config.json tests/test_config.py
git commit -m "feat: add concurrency settings to config"
```

### Task 2: Strengthen Scene Description Prompt Rule

**Files:**
- Modify: `video_tagging_assistant/providers/qwen_dashscope_provider.py`
- Modify: `tests/test_qwen_provider_multiselect.py`

- [ ] **Step 1: Write the failing ignore-opening prompt test**

```python
from pathlib import Path

from video_tagging_assistant.context_builder import build_prompt_context
from video_tagging_assistant.models import CompressedArtifact, VideoTask
from video_tagging_assistant.providers.qwen_dashscope_provider import QwenDashScopeVideoTagProvider


def test_qwen_prompt_explicitly_excludes_phone_time_opening():
    task = VideoTask(
        source_video_path=Path("videos/DCG_HDR/case_A_001/clip01.mp4"),
        relative_path=Path("DCG_HDR/case_A_001/clip01.mp4"),
        file_name="clip01.mp4",
    )
    artifact = CompressedArtifact(task.source_video_path, Path("output/compressed/clip01_proxy.mp4"))
    context = build_prompt_context(
        task,
        artifact,
        {
            "system": "请输出结构化标签",
            "single_choice_fields": {"安装方式": ["胸前"]},
            "multi_choice_fields": {"画面特征": ["重复纹理"]},
            "ignore_opening_instruction": "画面描述必须忽略视频开头固定出现的手持手机展示时间特写，不得将其写入描述。",
            "scene_description_instruction": "画面描述可以更详细。",
        },
    )
    provider = QwenDashScopeVideoTagProvider(
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key_env="DASHSCOPE_API_KEY",
        model="qwen3.6-flash",
    )

    prompt_text = provider._build_prompt_text(context)

    assert "不得将其写入描述" in prompt_text
    assert "画面描述应从真正进入测试场景之后开始" in prompt_text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_qwen_provider_multiselect.py::test_qwen_prompt_explicitly_excludes_phone_time_opening -v`
Expected: FAIL because the prompt currently only carries a softer ignore instruction.

- [ ] **Step 3: Update `_build_prompt_text()` in `video_tagging_assistant/providers/qwen_dashscope_provider.py`**

Strengthen the prompt wording by incorporating the configured ignore instruction and adding an explicit rule such as:

```python
f"6. {ignore_opening_instruction}",
"7. 画面描述应从真正进入测试场景之后开始，不要把固定的手机时间展示开场算作有效画面内容。",
f"8. {scene_instruction}",
```

- [ ] **Step 4: Run the prompt test**

Run: `pytest tests/test_qwen_provider_multiselect.py::test_qwen_prompt_explicitly_excludes_phone_time_opening -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add video_tagging_assistant/providers/qwen_dashscope_provider.py tests/test_qwen_provider_multiselect.py
git commit -m "feat: strengthen opening-shot exclusion in qwen prompt"
```

### Task 3: Add Concurrent Compression Stage

**Files:**
- Modify: `video_tagging_assistant/orchestrator.py`
- Modify: `tests/test_pipeline.py`

- [ ] **Step 1: Write the failing concurrent compression orchestration test**

```python
from pathlib import Path

from video_tagging_assistant.orchestrator import run_batch
from video_tagging_assistant.models import GenerationResult, CompressedArtifact


class RecordingCompressor:
    def __init__(self):
        self.calls = []

    def __call__(self, task, output_dir, compression_config):
        self.calls.append(task.file_name)
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
            scene_description="描述",
            provider="qwen_dashscope",
            model="qwen3.6-flash",
        )


def test_run_batch_uses_all_tasks_for_compression(tmp_path: Path):
    input_dir = tmp_path / "videos"
    (input_dir / "a").mkdir(parents=True)
    (input_dir / "a" / "clip01.mp4").write_bytes(b"1")
    (input_dir / "a" / "clip02.mp4").write_bytes(b"2")

    compressor = RecordingCompressor()
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
        "concurrency": {"compression_workers": 2, "provider_workers": 1, "max_retries": 1, "retry_backoff_seconds": 1, "retry_backoff_multiplier": 2},
    }

    run_batch(config, compressor=compressor, provider=StaticProvider())

    assert sorted(compressor.calls) == ["clip01.mp4", "clip02.mp4"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline.py::test_run_batch_uses_all_tasks_for_compression -v`
Expected: FAIL until the orchestration logic is reworked for staged execution.

- [ ] **Step 3: Update `video_tagging_assistant/orchestrator.py` to compress first with a thread pool**

Implement a staged approach such as:

```python
from concurrent.futures import ThreadPoolExecutor, as_completed
import time


def _compress_tasks(tasks, compressed_dir, compression_config, compressor, workers):
    artifacts = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {
            executor.submit(compressor, task, compressed_dir, compression_config): task
            for task in tasks
        }
        for future in as_completed(future_map):
            task = future_map[future]
            artifacts[task.source_video_path] = future.result()
    return artifacts
```

Use this inside `run_batch()` before provider calls.

- [ ] **Step 4: Run the compression orchestration test**

Run: `pytest tests/test_pipeline.py::test_run_batch_uses_all_tasks_for_compression -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add video_tagging_assistant/orchestrator.py tests/test_pipeline.py
git commit -m "feat: add concurrent compression stage"
```

### Task 4: Add Provider Concurrency With Retry/Backoff

**Files:**
- Modify: `video_tagging_assistant/orchestrator.py`
- Modify: `tests/test_pipeline.py`

- [ ] **Step 1: Write the failing retry/backoff provider test**

```python
from pathlib import Path

from video_tagging_assistant.orchestrator import run_batch
from video_tagging_assistant.models import GenerationResult, CompressedArtifact


class StubCompressor:
    def __call__(self, task, output_dir, compression_config):
        output_dir.mkdir(parents=True, exist_ok=True)
        proxy = output_dir / f"{Path(task.file_name).stem}_proxy.mp4"
        proxy.write_bytes(b"proxy")
        return CompressedArtifact(task.source_video_path, proxy)


class FlakyProvider:
    def __init__(self):
        self.calls = 0
        self.provider_name = "qwen_dashscope"

    def generate(self, context):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("temporary failure")
        return GenerationResult(
            source_video_path=context.source_video_path,
            structured_tags={"安装方式": "胸前"},
            multi_select_tags={"画面特征": ["重复纹理"]},
            scene_description="描述",
            provider="qwen_dashscope",
            model="qwen3.6-flash",
        )


def test_run_batch_retries_provider_failures(tmp_path: Path):
    input_dir = tmp_path / "videos"
    (input_dir / "a").mkdir(parents=True)
    (input_dir / "a" / "clip01.mp4").write_bytes(b"1")

    provider = FlakyProvider()
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
        "concurrency": {"compression_workers": 1, "provider_workers": 1, "max_retries": 2, "retry_backoff_seconds": 0, "retry_backoff_multiplier": 2},
    }

    summary = run_batch(config, compressor=StubCompressor(), provider=provider)

    assert summary["processed"] == 1
    assert provider.calls == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline.py::test_run_batch_retries_provider_failures -v`
Expected: FAIL because current orchestration does not retry provider failures.

- [ ] **Step 3: Add retry/backoff wrapper inside `video_tagging_assistant/orchestrator.py`**

Implement a helper similar to:

```python
def _generate_with_retry(provider, context, concurrency_config):
    max_retries = concurrency_config.get("max_retries", 3)
    delay = concurrency_config.get("retry_backoff_seconds", 2)
    multiplier = concurrency_config.get("retry_backoff_multiplier", 2)

    last_error = None
    for attempt in range(max_retries + 1):
        try:
            return provider.generate(context)
        except Exception as exc:
            last_error = exc
            if attempt >= max_retries:
                raise
            time.sleep(delay)
            delay *= multiplier
    raise last_error
```

Then use a second `ThreadPoolExecutor(max_workers=provider_workers)` to run provider calls after compression completes.

- [ ] **Step 4: Run the retry test**

Run: `pytest tests/test_pipeline.py::test_run_batch_retries_provider_failures -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add video_tagging_assistant/orchestrator.py tests/test_pipeline.py
git commit -m "feat: add provider retry and bounded concurrency"
```

### Task 5: Create Deployment Package Layout And README

**Files:**
- Create: `deployment_package/README.md`
- Create: `deployment_package/default_config.json`
- Create: `deployment_package/run_cli.bat`
- Create: `deployment_package/requirements.txt`

- [ ] **Step 1: Write the failing deployment artifact existence test**

```python
from pathlib import Path


def test_deployment_package_files_exist():
    base = Path("deployment_package")
    assert (base / "README.md").exists()
    assert (base / "default_config.json").exists()
    assert (base / "run_cli.bat").exists()
    assert (base / "requirements.txt").exists()
```

Save as `tests/test_deployment_package.py`.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_deployment_package.py::test_deployment_package_files_exist -v`
Expected: FAIL because the deployment package does not exist yet.

- [ ] **Step 3: Create `deployment_package/default_config.json`**

Copy the runtime-ready config shape from `video_tagging_assistant/default_config.json`, keeping placeholders where the deployer should customize machine-specific paths.

- [ ] **Step 4: Create `deployment_package/requirements.txt`**

```text
openai
pytest
```

Keep it minimal; add only packages the project actually uses.

- [ ] **Step 5: Create `deployment_package/run_cli.bat`**

```bat
@echo off
python -m video_tagging_assistant.cli --config default_config.json
pause
```

- [ ] **Step 6: Create `deployment_package/README.md`**

Write concise instructions covering:
- Purpose of the tool
- Python and `ffmpeg.exe` requirements
- Where to put videos
- Which config keys to update on a new machine
- How to run the CLI
- Where `review.txt` and intermediate JSON appear
- Security note about `provider.api_key`

- [ ] **Step 7: Add the test file `tests/test_deployment_package.py`**

Use the test code from Step 1.

- [ ] **Step 8: Run deployment package test**

Run: `pytest tests/test_deployment_package.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add deployment_package/README.md deployment_package/default_config.json deployment_package/run_cli.bat deployment_package/requirements.txt tests/test_deployment_package.py
git commit -m "docs: add deployment package and setup guide"
```

### Task 6: Full Verification

**Files:**
- Modify: `tests/test_pipeline.py` (if needed after final end-to-end adjustments)

- [ ] **Step 1: Run the full focused suite**

Run: `pytest tests/test_scanner.py tests/test_config.py tests/test_context_builder.py tests/test_review_exporter.py tests/test_provider.py tests/test_pipeline.py tests/test_qwen_provider.py tests/test_qwen_provider_multiselect.py tests/test_structured_result_model.py tests/test_multiselect_result_model.py tests/test_review_exporter_structured.py tests/test_review_exporter_multiselect.py tests/test_deployment_package.py -v`
Expected: PASS

- [ ] **Step 2: Run the real CLI**

Run: `python -m video_tagging_assistant.cli --config video_tagging_assistant/default_config.json`
Expected: Processes available videos successfully and writes the configured review file.

- [ ] **Step 3: Inspect the generated review output**

Run: `python - <<'PY'
from pathlib import Path
print(Path('output/review/review.txt').read_text(encoding='utf-8')[:2000])
PY`
Expected: `画面描述` no longer includes the fixed phone-time opening as the main scene description, and single/multi-select fields render correctly.

- [ ] **Step 4: Commit**

```bash
git add tests/test_pipeline.py
git commit -m "test: verify concurrency and deployment workflow"
```

## Self-Review

### Spec Coverage

- Compression concurrency: Task 3.
- Provider concurrency with retry/backoff: Task 4.
- Configurable concurrency parameters: Task 1.
- Stronger ignore-opening rule in scene description: Task 2.
- Deployment package and README: Task 5.
- End-to-end verification: Task 6.

### Placeholder Scan

- No `TODO` / `TBD` placeholders remain.
- Every code-writing step includes explicit code.
- Every verification step includes an exact command and expected result.

### Type Consistency

- `compression_workers`, `provider_workers`, `max_retries`, `retry_backoff_seconds`, and `retry_backoff_multiplier` are introduced in config and reused consistently in orchestration tasks.
- Prompt fields `ignore_opening_instruction` and `scene_description_instruction` stay consistent with the current provider design.
