# Video Tagging Assistant Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local batch tool that compresses videos, sends them with structured context to a configurable low-cost LLM provider, and exports a local text review list for human approval.

**Architecture:** Add a new focused Python package alongside the existing scripts rather than rewriting `pull.py`, `check.py`, or `count_rk.py`. The package is organized around a small orchestration pipeline with isolated modules for scanning, compression, context building, provider abstraction, and review export, with tests covering parsing, prompt construction, response normalization, and end-to-end dry-run behavior.

**Tech Stack:** Python 3, `pytest`, `pathlib`, `dataclasses`, `subprocess`/`ffmpeg`, JSON, text export, optional HTTP client for provider adapters

---

## File Structure

**Create:**
- `video_tagging_assistant/__init__.py` — package marker and version surface
- `video_tagging_assistant/config.py` — load and validate local config
- `video_tagging_assistant/models.py` — dataclasses for tasks, artifacts, context, results
- `video_tagging_assistant/scanner.py` — discover supported video files and build `VideoTask`
- `video_tagging_assistant/compressor.py` — create compressed proxy videos via `ffmpeg`
- `video_tagging_assistant/context_builder.py` — derive metadata from path/name and build prompt payload
- `video_tagging_assistant/providers/__init__.py` — provider registry exports
- `video_tagging_assistant/providers/base.py` — provider protocol / abstract base class
- `video_tagging_assistant/providers/mock_provider.py` — deterministic local provider for tests and dry runs
- `video_tagging_assistant/providers/openai_compatible.py` — configurable OpenAI-compatible provider adapter
- `video_tagging_assistant/review_exporter.py` — write local text review checklist
- `video_tagging_assistant/orchestrator.py` — batch pipeline coordination, retries, status transitions
- `video_tagging_assistant/cli.py` — command-line entrypoint for running the pipeline
- `video_tagging_assistant/default_config.json` — starter config template
- `tests/test_scanner.py` — scanner behavior tests
- `tests/test_context_builder.py` — metadata extraction and prompt assembly tests
- `tests/test_review_exporter.py` — text export format tests
- `tests/test_orchestrator.py` — batch dry-run orchestration tests
- `tests/test_provider_openai_compatible.py` — response normalization tests

**Modify:**
- `docs/superpowers/specs/2026-04-24-video-tagging-design.md:1` — only if plan review reveals a spec mismatch

**Do Not Modify Initially:**
- `pull.py`
- `check.py`
- `count_rk.py`
- `PC_A_采集记录表v2.1.xlsm`

### Planned Runtime Layout

The new package should produce outputs under a user-configured working directory such as:

- `output/compressed/` — proxy videos
- `output/intermediate/` — per-video JSON artifacts
- `output/review/` — consolidated text review list
- `output/logs/` — run logs

---

### Task 1: Create Package Skeleton And Core Data Models

**Files:**
- Create: `video_tagging_assistant/__init__.py`
- Create: `video_tagging_assistant/models.py`
- Create: `tests/test_scanner.py`

- [ ] **Step 1: Write the failing model-driven scanner test**

```python
from pathlib import Path

from video_tagging_assistant.scanner import scan_videos


def test_scan_videos_discovers_supported_files(tmp_path: Path):
    (tmp_path / "case_a").mkdir()
    (tmp_path / "case_a" / "clip01.mp4").write_bytes(b"data")
    (tmp_path / "case_a" / "ignore.txt").write_text("x", encoding="utf-8")

    tasks = scan_videos(tmp_path)

    assert len(tasks) == 1
    assert tasks[0].file_name == "clip01.mp4"
    assert tasks[0].relative_path.as_posix() == "case_a/clip01.mp4"
    assert tasks[0].status == "pending"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_scanner.py::test_scan_videos_discovers_supported_files -v`
Expected: FAIL with `ModuleNotFoundError` or `ImportError` because package/modules do not exist yet.

- [ ] **Step 3: Create package marker**

```python
__all__ = ["__version__"]
__version__ = "0.1.0"
```

Write this to `video_tagging_assistant/__init__.py`.

- [ ] **Step 4: Create core dataclasses in `video_tagging_assistant/models.py`**

```python
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class VideoTask:
    source_video_path: Path
    relative_path: Path
    file_name: str
    case_id: str | None = None
    mode: str | None = None
    device_info: str | None = None
    status: str = "pending"


@dataclass
class CompressedArtifact:
    source_video_path: Path
    compressed_video_path: Path
    duration: float | None = None
    resolution: str | None = None
    size_bytes: int | None = None
    compression_profile: str | None = None


@dataclass
class PromptContext:
    source_video_path: Path
    compressed_video_path: Path
    parsed_metadata: dict[str, Any]
    template_fields: dict[str, Any]
    prompt_payload: dict[str, Any]
    context_warnings: list[str] = field(default_factory=list)


@dataclass
class GenerationResult:
    source_video_path: Path
    summary_text: str
    tags: list[str]
    notes: str = ""
    provider: str = ""
    model: str = ""
    raw_response_excerpt: str = ""
    review_status: str = "unreviewed"
```

- [ ] **Step 5: Create minimal scanner in `video_tagging_assistant/scanner.py`**

```python
from pathlib import Path

from video_tagging_assistant.models import VideoTask

SUPPORTED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi"}


def scan_videos(root: Path) -> list[VideoTask]:
    root = Path(root)
    tasks: list[VideoTask] = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS:
            tasks.append(
                VideoTask(
                    source_video_path=path,
                    relative_path=path.relative_to(root),
                    file_name=path.name,
                )
            )
    return tasks
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/test_scanner.py::test_scan_videos_discovers_supported_files -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add video_tagging_assistant/__init__.py video_tagging_assistant/models.py video_tagging_assistant/scanner.py tests/test_scanner.py
git commit -m "feat: add video task models and scanner"
```

### Task 2: Add Config Loading For Batch Runs

**Files:**
- Create: `video_tagging_assistant/config.py`
- Create: `video_tagging_assistant/default_config.json`
- Test: `tests/test_orchestrator.py`

- [ ] **Step 1: Write the failing config load test**

```python
import json
from pathlib import Path

from video_tagging_assistant.config import load_config


def test_load_config_reads_expected_sections(tmp_path: Path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "input_dir": "videos",
                "output_dir": "output",
                "compression": {"width": 960, "video_bitrate": "700k"},
                "provider": {"name": "mock", "model": "fake-model"},
                "prompt_template": {"system": "describe video"},
            }
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config["input_dir"] == "videos"
    assert config["provider"]["name"] == "mock"
    assert config["compression"]["width"] == 960
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_orchestrator.py::test_load_config_reads_expected_sections -v`
Expected: FAIL with `ImportError` because `load_config` does not exist.

- [ ] **Step 3: Create `video_tagging_assistant/default_config.json`**

```json
{
  "input_dir": "videos",
  "output_dir": "output",
  "compression": {
    "width": 960,
    "video_bitrate": "700k",
    "audio_bitrate": "96k",
    "fps": 12
  },
  "provider": {
    "name": "mock",
    "model": "mock-video-tagger",
    "base_url": "",
    "api_key_env": "VIDEO_TAGGER_API_KEY"
  },
  "prompt_template": {
    "system": "You generate short Chinese video summaries and concise tags.",
    "tag_rules": ["Return 3 to 5 tags", "Avoid repeating the filename"]
  }
}
```

- [ ] **Step 4: Implement config loader in `video_tagging_assistant/config.py`**

```python
import json
from pathlib import Path

REQUIRED_TOP_LEVEL_KEYS = {
    "input_dir",
    "output_dir",
    "compression",
    "provider",
    "prompt_template",
}


def load_config(config_path: Path) -> dict:
    config_path = Path(config_path)
    data = json.loads(config_path.read_text(encoding="utf-8"))
    missing = REQUIRED_TOP_LEVEL_KEYS - set(data)
    if missing:
        missing_list = ", ".join(sorted(missing))
        raise ValueError(f"Missing config keys: {missing_list}")
    return data
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_orchestrator.py::test_load_config_reads_expected_sections -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add video_tagging_assistant/config.py video_tagging_assistant/default_config.json tests/test_orchestrator.py
git commit -m "feat: add config loading for batch runs"
```

### Task 3: Build Context Extraction And Prompt Assembly

**Files:**
- Create: `video_tagging_assistant/context_builder.py`
- Create: `tests/test_context_builder.py`

- [ ] **Step 1: Write the failing context builder test**

```python
from pathlib import Path

from video_tagging_assistant.context_builder import build_prompt_context
from video_tagging_assistant.models import CompressedArtifact, VideoTask


def test_build_prompt_context_extracts_case_and_mode():
    task = VideoTask(
        source_video_path=Path("videos/DCG_HDR/case_A_001/clip01.mp4"),
        relative_path=Path("DCG_HDR/case_A_001/clip01.mp4"),
        file_name="clip01.mp4",
    )
    artifact = CompressedArtifact(
        source_video_path=task.source_video_path,
        compressed_video_path=Path("output/compressed/clip01_proxy.mp4"),
    )
    template = {
        "system": "请为视频生成简介和标签",
        "tag_rules": ["返回 3 到 5 个标签"],
    }

    context = build_prompt_context(task, artifact, template)

    assert context.parsed_metadata["case_id"] == "case_A_001"
    assert context.parsed_metadata["mode"] == "DCG_HDR"
    assert context.prompt_payload["template"]["system"] == "请为视频生成简介和标签"
    assert context.context_warnings == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_context_builder.py::test_build_prompt_context_extracts_case_and_mode -v`
Expected: FAIL because `build_prompt_context` does not exist.

- [ ] **Step 3: Implement context builder in `video_tagging_assistant/context_builder.py`**

```python
from pathlib import Path

from video_tagging_assistant.models import CompressedArtifact, PromptContext, VideoTask


def build_prompt_context(
    task: VideoTask,
    artifact: CompressedArtifact,
    template_fields: dict,
) -> PromptContext:
    parent_parts = list(task.relative_path.parts[:-1])
    parsed_metadata = {
        "case_id": next((part for part in parent_parts if part.lower().startswith("case_")), None),
        "mode": parent_parts[0] if parent_parts else None,
        "device_info": parent_parts[1] if len(parent_parts) > 2 else None,
        "file_name": task.file_name,
        "relative_path": task.relative_path.as_posix(),
    }

    warnings: list[str] = []
    if parsed_metadata["case_id"] is None:
        warnings.append("missing_case_id")
    if parsed_metadata["mode"] is None:
        warnings.append("missing_mode")

    prompt_payload = {
        "template": template_fields,
        "video": {
            "source_path": str(task.source_video_path),
            "compressed_path": str(artifact.compressed_video_path),
        },
        "metadata": parsed_metadata,
    }

    return PromptContext(
        source_video_path=task.source_video_path,
        compressed_video_path=artifact.compressed_video_path,
        parsed_metadata=parsed_metadata,
        template_fields=template_fields,
        prompt_payload=prompt_payload,
        context_warnings=warnings,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_context_builder.py::test_build_prompt_context_extracts_case_and_mode -v`
Expected: PASS

- [ ] **Step 5: Add missing-context regression test**

```python
from pathlib import Path

from video_tagging_assistant.context_builder import build_prompt_context
from video_tagging_assistant.models import CompressedArtifact, VideoTask


def test_build_prompt_context_marks_missing_metadata():
    task = VideoTask(
        source_video_path=Path("videos/clip01.mp4"),
        relative_path=Path("clip01.mp4"),
        file_name="clip01.mp4",
    )
    artifact = CompressedArtifact(
        source_video_path=task.source_video_path,
        compressed_video_path=Path("output/compressed/clip01_proxy.mp4"),
    )

    context = build_prompt_context(task, artifact, {"system": "x"})

    assert "missing_case_id" in context.context_warnings
    assert "missing_mode" in context.context_warnings
```

- [ ] **Step 6: Run both tests**

Run: `pytest tests/test_context_builder.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add video_tagging_assistant/context_builder.py tests/test_context_builder.py
git commit -m "feat: add prompt context construction"
```

### Task 4: Add Text Review Export

**Files:**
- Create: `video_tagging_assistant/review_exporter.py`
- Create: `tests/test_review_exporter.py`

- [ ] **Step 1: Write the failing review export test**

```python
from pathlib import Path

from video_tagging_assistant.models import GenerationResult
from video_tagging_assistant.review_exporter import export_review_list


def test_export_review_list_writes_expected_sections(tmp_path: Path):
    output_path = tmp_path / "review.txt"
    result = GenerationResult(
        source_video_path=Path("videos/case_A_001/clip01.mp4"),
        summary_text="夜景道路画面，主体清晰。",
        tags=["夜景", "道路", "稳定"],
        notes="上下文完整",
        provider="mock",
        model="mock-video-tagger",
    )

    export_review_list([result], output_path)

    text = output_path.read_text(encoding="utf-8")
    assert "视频路径: videos/case_A_001/clip01.mp4" in text
    assert "建议简介: 夜景道路画面，主体清晰。" in text
    assert "建议标签: 夜景, 道路, 稳定" in text
    assert "审核状态: unreviewed" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_review_exporter.py::test_export_review_list_writes_expected_sections -v`
Expected: FAIL because `export_review_list` does not exist.

- [ ] **Step 3: Implement `video_tagging_assistant/review_exporter.py`**

```python
from pathlib import Path

from video_tagging_assistant.models import GenerationResult


def export_review_list(results: list[GenerationResult], output_path: Path) -> None:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    sections: list[str] = []
    for index, result in enumerate(results, start=1):
        sections.append(
            "\n".join(
                [
                    f"## 条目 {index}",
                    f"视频路径: {result.source_video_path.as_posix()}",
                    f"建议简介: {result.summary_text}",
                    f"建议标签: {', '.join(result.tags)}",
                    f"备注: {result.notes}",
                    f"审核状态: {result.review_status}",
                    f"模型: {result.provider}/{result.model}",
                ]
            )
        )

    output_path.write_text("\n\n---\n\n".join(sections) + "\n", encoding="utf-8")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_review_exporter.py::test_export_review_list_writes_expected_sections -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add video_tagging_assistant/review_exporter.py tests/test_review_exporter.py
git commit -m "feat: add text review export"
```

### Task 5: Add Provider Abstraction And Deterministic Mock Provider

**Files:**
- Create: `video_tagging_assistant/providers/__init__.py`
- Create: `video_tagging_assistant/providers/base.py`
- Create: `video_tagging_assistant/providers/mock_provider.py`
- Test: `tests/test_provider_openai_compatible.py`

- [ ] **Step 1: Write the failing provider interface test**

```python
from pathlib import Path

from video_tagging_assistant.models import PromptContext
from video_tagging_assistant.providers.mock_provider import MockVideoTagProvider


def test_mock_provider_returns_normalized_result():
    context = PromptContext(
        source_video_path=Path("videos/clip01.mp4"),
        compressed_video_path=Path("output/compressed/clip01_proxy.mp4"),
        parsed_metadata={"mode": "DCG_HDR", "case_id": "case_A_001"},
        template_fields={"system": "请生成简介"},
        prompt_payload={"template": {"system": "请生成简介"}},
        context_warnings=[],
    )

    provider = MockVideoTagProvider(model="mock-video-tagger")
    result = provider.generate(context)

    assert result.provider == "mock"
    assert result.model == "mock-video-tagger"
    assert len(result.tags) >= 1
    assert result.summary_text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_provider_openai_compatible.py::test_mock_provider_returns_normalized_result -v`
Expected: FAIL because provider modules do not exist.

- [ ] **Step 3: Implement provider base in `video_tagging_assistant/providers/base.py`**

```python
from abc import ABC, abstractmethod

from video_tagging_assistant.models import GenerationResult, PromptContext


class VideoTagProvider(ABC):
    provider_name: str

    @abstractmethod
    def generate(self, context: PromptContext) -> GenerationResult:
        raise NotImplementedError
```

- [ ] **Step 4: Implement mock provider in `video_tagging_assistant/providers/mock_provider.py`**

```python
from video_tagging_assistant.models import GenerationResult, PromptContext
from video_tagging_assistant.providers.base import VideoTagProvider


class MockVideoTagProvider(VideoTagProvider):
    provider_name = "mock"

    def __init__(self, model: str = "mock-video-tagger") -> None:
        self.model = model

    def generate(self, context: PromptContext) -> GenerationResult:
        mode = context.parsed_metadata.get("mode") or "unknown"
        case_id = context.parsed_metadata.get("case_id") or "unknown-case"
        return GenerationResult(
            source_video_path=context.source_video_path,
            summary_text=f"{mode} 模式下的 {case_id} 视频，建议人工复核。",
            tags=[mode, case_id, "待审核"],
            notes="mock provider result",
            provider=self.provider_name,
            model=self.model,
            raw_response_excerpt="mock-response",
        )
```

- [ ] **Step 5: Implement provider exports in `video_tagging_assistant/providers/__init__.py`**

```python
from video_tagging_assistant.providers.mock_provider import MockVideoTagProvider

__all__ = ["MockVideoTagProvider"]
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/test_provider_openai_compatible.py::test_mock_provider_returns_normalized_result -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add video_tagging_assistant/providers/__init__.py video_tagging_assistant/providers/base.py video_tagging_assistant/providers/mock_provider.py tests/test_provider_openai_compatible.py
git commit -m "feat: add provider abstraction and mock provider"
```

### Task 6: Implement OpenAI-Compatible Provider Adapter

**Files:**
- Create: `video_tagging_assistant/providers/openai_compatible.py`
- Modify: `tests/test_provider_openai_compatible.py`

- [ ] **Step 1: Add the failing response normalization test**

```python
from pathlib import Path

from video_tagging_assistant.providers.openai_compatible import normalize_response_payload


def test_normalize_response_payload_extracts_summary_and_tags():
    payload = {
        "summary": "白天街道视频，主体稳定。",
        "tags": ["白天", "街道", "稳定"],
        "notes": "目录信息完整",
    }

    result = normalize_response_payload(payload, Path("videos/clip01.mp4"), "demo", "cheap-model")

    assert result.summary_text == "白天街道视频，主体稳定。"
    assert result.tags == ["白天", "街道", "稳定"]
    assert result.provider == "demo"
    assert result.model == "cheap-model"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_provider_openai_compatible.py::test_normalize_response_payload_extracts_summary_and_tags -v`
Expected: FAIL because normalization helper does not exist.

- [ ] **Step 3: Implement normalization helper and adapter skeleton in `video_tagging_assistant/providers/openai_compatible.py`**

```python
import json
import os
from pathlib import Path
from urllib import request

from video_tagging_assistant.models import GenerationResult, PromptContext
from video_tagging_assistant.providers.base import VideoTagProvider


def normalize_response_payload(
    payload: dict,
    source_video_path: Path,
    provider_name: str,
    model: str,
) -> GenerationResult:
    return GenerationResult(
        source_video_path=source_video_path,
        summary_text=str(payload.get("summary", "")).strip(),
        tags=[str(tag).strip() for tag in payload.get("tags", []) if str(tag).strip()],
        notes=str(payload.get("notes", "")).strip(),
        provider=provider_name,
        model=model,
        raw_response_excerpt=json.dumps(payload, ensure_ascii=False)[:500],
    )


class OpenAICompatibleVideoTagProvider(VideoTagProvider):
    provider_name = "openai_compatible"

    def __init__(self, base_url: str, api_key_env: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key_env = api_key_env
        self.model = model

    def generate(self, context: PromptContext) -> GenerationResult:
        api_key = os.environ[self.api_key_env]
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": context.template_fields.get("system", "")},
                {"role": "user", "content": json.dumps(context.prompt_payload, ensure_ascii=False)},
            ],
            "response_format": {"type": "json_object"},
        }
        req = request.Request(
            url=f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        with request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        content = body["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        return normalize_response_payload(parsed, context.source_video_path, self.provider_name, self.model)
```

- [ ] **Step 4: Run the normalization test**

Run: `pytest tests/test_provider_openai_compatible.py::test_normalize_response_payload_extracts_summary_and_tags -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add video_tagging_assistant/providers/openai_compatible.py tests/test_provider_openai_compatible.py
git commit -m "feat: add openai-compatible provider adapter"
```

### Task 7: Add Compression Module Around `ffmpeg`

**Files:**
- Create: `video_tagging_assistant/compressor.py`
- Modify: `tests/test_orchestrator.py`

- [ ] **Step 1: Write the failing command construction test**

```python
from pathlib import Path

from video_tagging_assistant.compressor import build_ffmpeg_command


def test_build_ffmpeg_command_uses_expected_scaling_and_bitrate():
    command = build_ffmpeg_command(
        source=Path("videos/clip01.mp4"),
        target=Path("output/compressed/clip01_proxy.mp4"),
        compression_config={"width": 960, "video_bitrate": "700k", "audio_bitrate": "96k", "fps": 12},
    )

    assert command[0] == "ffmpeg"
    assert "scale=960:-2" in command
    assert "700k" in command
    assert command[-1] == "output/compressed/clip01_proxy.mp4"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_orchestrator.py::test_build_ffmpeg_command_uses_expected_scaling_and_bitrate -v`
Expected: FAIL because compressor module does not exist.

- [ ] **Step 3: Implement command builder and runner in `video_tagging_assistant/compressor.py`**

```python
import subprocess
from pathlib import Path

from video_tagging_assistant.models import CompressedArtifact, VideoTask


def build_ffmpeg_command(source: Path, target: Path, compression_config: dict) -> list[str]:
    width = compression_config["width"]
    video_bitrate = compression_config["video_bitrate"]
    audio_bitrate = compression_config["audio_bitrate"]
    fps = compression_config["fps"]
    return [
        "ffmpeg",
        "-y",
        "-i",
        str(source),
        "-vf",
        f"scale={width}:-2",
        "-r",
        str(fps),
        "-b:v",
        video_bitrate,
        "-b:a",
        audio_bitrate,
        str(target),
    ]


def compress_video(task: VideoTask, output_dir: Path, compression_config: dict) -> CompressedArtifact:
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"{task.source_video_path.stem}_proxy.mp4"
    command = build_ffmpeg_command(task.source_video_path, target, compression_config)
    subprocess.run(command, check=True)
    return CompressedArtifact(
        source_video_path=task.source_video_path,
        compressed_video_path=target,
        size_bytes=target.stat().st_size if target.exists() else None,
        compression_profile=f"{compression_config['width']}px/{compression_config['video_bitrate']}",
    )
```

- [ ] **Step 4: Run the command test**

Run: `pytest tests/test_orchestrator.py::test_build_ffmpeg_command_uses_expected_scaling_and_bitrate -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add video_tagging_assistant/compressor.py tests/test_orchestrator.py
git commit -m "feat: add ffmpeg compression module"
```

### Task 8: Build Orchestrator With Intermediate Artifacts

**Files:**
- Create: `video_tagging_assistant/orchestrator.py`
- Modify: `tests/test_orchestrator.py`

- [ ] **Step 1: Add the failing dry-run orchestration test**

```python
import json
from pathlib import Path

from video_tagging_assistant.orchestrator import run_batch


class StubCompressor:
    def __call__(self, task, output_dir, compression_config):
        proxy_path = output_dir / f"{Path(task.file_name).stem}_proxy.mp4"
        output_dir.mkdir(parents=True, exist_ok=True)
        proxy_path.write_bytes(b"proxy")
        from video_tagging_assistant.models import CompressedArtifact
        return CompressedArtifact(task.source_video_path, proxy_path)


class StubProvider:
    provider_name = "stub"

    def generate(self, context):
        from video_tagging_assistant.models import GenerationResult
        return GenerationResult(
            source_video_path=context.source_video_path,
            summary_text="测试简介",
            tags=["测试", "待审核"],
            provider="stub",
            model="stub-model",
        )


def test_run_batch_creates_intermediate_and_review_outputs(tmp_path: Path):
    input_dir = tmp_path / "videos"
    output_dir = tmp_path / "output"
    (input_dir / "case_A_001").mkdir(parents=True)
    (input_dir / "case_A_001" / "clip01.mp4").write_bytes(b"data")

    config = {
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "compression": {"width": 960, "video_bitrate": "700k", "audio_bitrate": "96k", "fps": 12},
        "prompt_template": {"system": "describe"},
    }

    result = run_batch(config, compressor=StubCompressor(), provider=StubProvider())

    review_text = (output_dir / "review" / "review.txt").read_text(encoding="utf-8")
    intermediate = json.loads((output_dir / "intermediate" / "clip01.json").read_text(encoding="utf-8"))

    assert result["processed"] == 1
    assert "测试简介" in review_text
    assert intermediate["summary_text"] == "测试简介"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_orchestrator.py::test_run_batch_creates_intermediate_and_review_outputs -v`
Expected: FAIL because `run_batch` does not exist.

- [ ] **Step 3: Implement orchestrator in `video_tagging_assistant/orchestrator.py`**

```python
import json
from dataclasses import asdict
from pathlib import Path

from video_tagging_assistant.compressor import compress_video
from video_tagging_assistant.context_builder import build_prompt_context
from video_tagging_assistant.review_exporter import export_review_list
from video_tagging_assistant.scanner import scan_videos


def _json_default(value):
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Unsupported type: {type(value)!r}")


def run_batch(config: dict, compressor=compress_video, provider=None) -> dict:
    if provider is None:
        raise ValueError("provider is required")

    input_dir = Path(config["input_dir"])
    output_dir = Path(config["output_dir"])
    compressed_dir = output_dir / "compressed"
    intermediate_dir = output_dir / "intermediate"
    review_path = output_dir / "review" / "review.txt"

    intermediate_dir.mkdir(parents=True, exist_ok=True)

    tasks = scan_videos(input_dir)
    results = []

    for task in tasks:
        artifact = compressor(task, compressed_dir, config["compression"])
        context = build_prompt_context(task, artifact, config["prompt_template"])
        result = provider.generate(context)
        results.append(result)

        intermediate_path = intermediate_dir / f"{task.source_video_path.stem}.json"
        intermediate_path.write_text(
            json.dumps(asdict(result), ensure_ascii=False, indent=2, default=_json_default),
            encoding="utf-8",
        )

    export_review_list(results, review_path)
    return {"processed": len(results), "review_path": str(review_path)}
```

- [ ] **Step 4: Run the dry-run orchestration test**

Run: `pytest tests/test_orchestrator.py::test_run_batch_creates_intermediate_and_review_outputs -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add video_tagging_assistant/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: add batch orchestration and intermediate outputs"
```

### Task 9: Add CLI Entry Point For Local Operation

**Files:**
- Create: `video_tagging_assistant/cli.py`
- Modify: `video_tagging_assistant/providers/__init__.py`
- Modify: `tests/test_orchestrator.py`

- [ ] **Step 1: Add the failing CLI provider selection test**

```python
import json
from pathlib import Path

from video_tagging_assistant.cli import build_provider_from_config


def test_build_provider_from_config_returns_mock_provider():
    config = {
        "provider": {
            "name": "mock",
            "model": "mock-video-tagger",
            "base_url": "",
            "api_key_env": "VIDEO_TAGGER_API_KEY",
        }
    }

    provider = build_provider_from_config(config)

    assert provider.provider_name == "mock"
    assert provider.model == "mock-video-tagger"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_orchestrator.py::test_build_provider_from_config_returns_mock_provider -v`
Expected: FAIL because CLI module does not exist.

- [ ] **Step 3: Implement `video_tagging_assistant/cli.py`**

```python
import argparse
from pathlib import Path

from video_tagging_assistant.config import load_config
from video_tagging_assistant.orchestrator import run_batch
from video_tagging_assistant.providers.mock_provider import MockVideoTagProvider
from video_tagging_assistant.providers.openai_compatible import OpenAICompatibleVideoTagProvider


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
```

- [ ] **Step 4: Run the CLI provider test**

Run: `pytest tests/test_orchestrator.py::test_build_provider_from_config_returns_mock_provider -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add video_tagging_assistant/cli.py tests/test_orchestrator.py
git commit -m "feat: add cli entry point for video tagging assistant"
```

### Task 10: Verify End-To-End Dry Run And Document Usage

**Files:**
- Modify: `tests/test_orchestrator.py`
- Modify: `video_tagging_assistant/default_config.json`

- [ ] **Step 1: Add a failing smoke test for review file location**

```python
from pathlib import Path

from video_tagging_assistant.review_exporter import export_review_list
from video_tagging_assistant.models import GenerationResult


def test_review_exporter_uses_review_directory(tmp_path: Path):
    review_dir = tmp_path / "output" / "review"
    target = review_dir / "review.txt"
    result = GenerationResult(
        source_video_path=Path("videos/example.mp4"),
        summary_text="示例简介",
        tags=["示例"],
    )

    export_review_list([result], target)

    assert target.exists()
```

- [ ] **Step 2: Run the smoke test to verify current behavior**

Run: `pytest tests/test_orchestrator.py::test_review_exporter_uses_review_directory -v`
Expected: PASS after earlier tasks; if it fails, fix path creation before continuing.

- [ ] **Step 3: Run the focused test suite**

Run: `pytest tests/test_scanner.py tests/test_context_builder.py tests/test_review_exporter.py tests/test_provider_openai_compatible.py tests/test_orchestrator.py -v`
Expected: PASS

- [ ] **Step 4: Run a manual dry run using mock provider**

Run: `python -m video_tagging_assistant.cli --config video_tagging_assistant/default_config.json`
Expected: Either `Processed 0 videos` if `videos/` is empty, or a positive processed count plus a printed review list path.

- [ ] **Step 5: Commit**

```bash
git add tests/test_orchestrator.py video_tagging_assistant/default_config.json
git commit -m "test: verify end-to-end dry run workflow"
```

## Self-Review

### Spec Coverage

- Batch local tool: covered by Tasks 1, 2, 8, and 9.
- Video compression before model calls: covered by Task 7.
- Context from path/name plus template: covered by Task 3.
- Multi-provider support through unified adapter: covered by Tasks 5, 6, and 9.
- Local text review list for manual approval: covered by Task 4 and validated again in Task 10.
- Intermediate artifacts and rerun-friendly structure: covered by Task 8.
- Human keeps filling Excel manually: enforced by file boundaries and no Excel-writing task.

### Placeholder Scan

- No `TODO`, `TBD`, or “implement later” placeholders remain.
- Each code-writing step includes concrete code.
- Each verification step includes exact commands and expected outcomes.

### Type Consistency

- Shared dataclasses are introduced in Task 1 and reused consistently.
- `build_prompt_context`, `compress_video`, `run_batch`, and `build_provider_from_config` names stay consistent across later tasks.
- `GenerationResult.summary_text`, `tags`, `provider`, and `model` are used consistently across exporter, provider, and orchestration tasks.
