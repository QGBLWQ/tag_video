# Structured Tagging Output Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace free-form `summary/tags/notes` output with a strict structured single-choice tagging schema based on `tag_pic.png`, plus a free-text `画面描述` field.

**Architecture:** Keep the existing batch pipeline and Qwen video provider, but change the provider prompt contract, result normalization, and review export format to operate on a fixed structured schema. Store the allowed single-choice options in configuration, then have the provider build a constrained prompt that forces one value per field and returns only the defined keys.

**Tech Stack:** Python 3.8, `pytest`, `json`, `pathlib`, existing `video_tagging_assistant` package, DashScope OpenAI-compatible HTTP

---

## File Structure

**Modify:**
- `video_tagging_assistant/models.py` — extend result model to carry structured tag fields
- `video_tagging_assistant/providers/qwen_dashscope_provider.py` — change prompt contract and normalization for structured tag output
- `video_tagging_assistant/review_exporter.py` — export structured fields instead of free-form tags
- `video_tagging_assistant/default_config.json` — add structured tag option definitions and prompt config
- `tests/test_qwen_provider.py` — add structured parsing/prompt tests
- `tests/test_review_exporter.py` — update expected review output
- `tests/test_pipeline.py` — verify pipeline still wires provider selection and outputs

**Reuse:**
- `video_tagging_assistant/context_builder.py` — existing metadata extraction
- `video_tagging_assistant/orchestrator.py` — existing batch flow
- `video_tagging_assistant/compressor.py` — existing proxy video generation

**Do Not Modify Unless Required:**
- `video_tagging_assistant/providers/openai_compatible.py`
- `qwen_video_test.py`
- `qwen_video_compress_and_test.py`

---

### Task 1: Extend Result Model For Structured Fields

**Files:**
- Modify: `video_tagging_assistant/models.py`
- Create: `tests/test_structured_result_model.py`

- [ ] **Step 1: Write the failing structured result model test**

```python
from pathlib import Path

from video_tagging_assistant.models import GenerationResult


def test_generation_result_supports_structured_fields():
    result = GenerationResult(
        source_video_path=Path("videos/clip01.mp4"),
        structured_tags={
            "安装方式": "胸前",
            "运动模式": "步行",
            "运镜方式": "固定镜头",
            "光源": "自然光",
        },
        scene_description="画面亮度稳定，庭院细节清晰。",
        provider="qwen_dashscope",
        model="qwen3.6-flash",
    )

    assert result.structured_tags["安装方式"] == "胸前"
    assert result.scene_description == "画面亮度稳定，庭院细节清晰。"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_structured_result_model.py::test_generation_result_supports_structured_fields -v`
Expected: FAIL because `GenerationResult` does not accept `structured_tags` or `scene_description`.

- [ ] **Step 3: Extend `GenerationResult` in `video_tagging_assistant/models.py`**

```python
@dataclass
class GenerationResult:
    source_video_path: Path
    summary_text: str = ""
    tags: List[str] = field(default_factory=list)
    notes: str = ""
    structured_tags: Dict[str, str] = field(default_factory=dict)
    scene_description: str = ""
    provider: str = ""
    model: str = ""
    raw_response_excerpt: str = ""
    review_status: str = "unreviewed"
```

Also update imports to include `field`, `Dict`, and `List` if needed.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_structured_result_model.py::test_generation_result_supports_structured_fields -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add video_tagging_assistant/models.py tests/test_structured_result_model.py
git commit -m "feat: add structured tag fields to generation results"
```

### Task 2: Add Structured Tag Options To Config

**Files:**
- Modify: `video_tagging_assistant/default_config.json`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Write the failing config structure test**

```python
import json
from pathlib import Path

from video_tagging_assistant.config import load_config


def test_load_config_includes_structured_tag_options(tmp_path: Path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "input_dir": "videos",
                "output_dir": "output",
                "compression": {"width": 960, "video_bitrate": "700k", "audio_bitrate": "96k", "fps": 12},
                "provider": {"name": "qwen_dashscope", "model": "qwen3.6-flash", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "api_key_env": "DASHSCOPE_API_KEY"},
                "prompt_template": {
                    "system": "test",
                    "structured_tag_options": {
                        "安装方式": ["胸前", "手持"],
                        "运动模式": ["步行", "骑行"]
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert "structured_tag_options" in config["prompt_template"]
    assert config["prompt_template"]["structured_tag_options"]["安装方式"] == ["胸前", "手持"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py::test_load_config_includes_structured_tag_options -v`
Expected: FAIL because current test file does not include this assertion and default config doesn't yet document the structure.

- [ ] **Step 3: Update `video_tagging_assistant/default_config.json`**

Add a `structured_tag_options` object under `prompt_template`, for example:

```json
"prompt_template": {
  "system": "你是一个中文视频理解助手。请根据视频内容和标签规则输出结构化单选标签。",
  "structured_tag_options": {
    "安装方式": ["胸前", "头戴", "手持", "车把", "其他"],
    "运动模式": ["步行", "跑步", "骑行", "静止", "其他"],
    "运镜方式": ["固定镜头", "平移", "推进", "拉远", "跟拍", "其他"],
    "光源": ["自然光", "室内灯光", "逆光", "弱光", "混合光", "其他"]
  },
  "scene_description_instruction": "画面描述重点描述光亮变化、场景细节、主体运动和画面变化。"
}
```

Keep the provider section aligned with the user's current Qwen setup.

- [ ] **Step 4: Add the new test to `tests/test_config.py`**

Append the test from Step 1 to the file.

- [ ] **Step 5: Run both config tests**

Run: `pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add video_tagging_assistant/default_config.json tests/test_config.py
git commit -m "feat: add structured tag options to config"
```

### Task 3: Change Qwen Prompt Construction To Structured Single-Choice Output

**Files:**
- Modify: `video_tagging_assistant/providers/qwen_dashscope_provider.py`
- Modify: `tests/test_qwen_provider.py`

- [ ] **Step 1: Write the failing prompt-contract test**

```python
from pathlib import Path

from video_tagging_assistant.models import CompressedArtifact, VideoTask
from video_tagging_assistant.context_builder import build_prompt_context
from video_tagging_assistant.providers.qwen_dashscope_provider import QwenDashScopeVideoTagProvider


def test_qwen_prompt_mentions_single_choice_tag_constraints():
    task = VideoTask(
        source_video_path=Path("videos/DCG_HDR/case_A_001/clip01.mp4"),
        relative_path=Path("DCG_HDR/case_A_001/clip01.mp4"),
        file_name="clip01.mp4",
    )
    artifact = CompressedArtifact(
        source_video_path=task.source_video_path,
        compressed_video_path=Path("output/compressed/clip01_proxy.mp4"),
    )
    context = build_prompt_context(
        task,
        artifact,
        {
            "system": "请输出结构化标签",
            "structured_tag_options": {
                "安装方式": ["胸前", "手持"],
                "运动模式": ["步行", "骑行"],
                "运镜方式": ["固定镜头", "跟拍"],
                "光源": ["自然光", "弱光"],
            },
            "scene_description_instruction": "描述光亮变化和场景细节",
        },
    )
    provider = QwenDashScopeVideoTagProvider(
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key_env="DASHSCOPE_API_KEY",
        model="qwen3.6-flash",
    )

    prompt_text = provider._build_prompt_text(context)

    assert "每个字段必须且只能选择一个候选值" in prompt_text
    assert "安装方式: 胸前, 手持" in prompt_text
    assert "画面描述" in prompt_text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_qwen_provider.py::test_qwen_prompt_mentions_single_choice_tag_constraints -v`
Expected: FAIL because prompt text still describes `summary/tags/notes` output.

- [ ] **Step 3: Update `_build_prompt_text()` in `video_tagging_assistant/providers/qwen_dashscope_provider.py`**

Change it to build a structured prompt from `structured_tag_options`, e.g.:

```python
def _build_prompt_text(self, context: PromptContext) -> str:
    options = context.template_fields["structured_tag_options"]
    option_lines = [
        f"- {field_name}: {', '.join(values)}"
        for field_name, values in options.items()
    ]
    prompt_lines = [
        context.template_fields.get("system", "请根据视频内容输出结构化单选标签。"),
        "",
        "规则：",
        "1. 输出中文",
        "2. 每个字段必须且只能选择一个候选值",
        "3. 不允许输出候选值以外的内容",
        "4. 不允许增加额外字段",
        "5. 画面描述用于描述光亮变化、场景细节、主体运动和画面变化",
        "",
        "标签字段与候选值：",
        *option_lines,
        "",
        "附加上下文：",
        f"- case_id: {context.parsed_metadata.get('case_id')}",
        f"- mode: {context.parsed_metadata.get('mode')}",
        f"- file_name: {context.parsed_metadata.get('file_name')}",
        "",
        "返回格式：",
        '{"安装方式": "string", "运动模式": "string", "运镜方式": "string", "光源": "string", "画面描述": "string"}',
    ]
    return "\n".join(prompt_lines)
```

- [ ] **Step 4: Run the prompt test**

Run: `pytest tests/test_qwen_provider.py::test_qwen_prompt_mentions_single_choice_tag_constraints -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add video_tagging_assistant/providers/qwen_dashscope_provider.py tests/test_qwen_provider.py
git commit -m "feat: constrain qwen output to structured single-choice tags"
```

### Task 4: Parse Structured JSON Into Result Model

**Files:**
- Modify: `video_tagging_assistant/providers/qwen_dashscope_provider.py`
- Modify: `tests/test_qwen_provider.py`

- [ ] **Step 1: Write the failing structured normalization test**

```python
from pathlib import Path

from video_tagging_assistant.providers.qwen_dashscope_provider import normalize_response_payload


def test_normalize_response_payload_maps_structured_fields():
    payload = {
        "安装方式": "胸前",
        "运动模式": "步行",
        "运镜方式": "固定镜头",
        "光源": "自然光",
        "画面描述": "画面亮度稳定，庭院细节清晰。",
    }

    result = normalize_response_payload(payload, Path("videos/clip01.mp4"), "qwen_dashscope", "qwen3.6-flash")

    assert result.structured_tags == {
        "安装方式": "胸前",
        "运动模式": "步行",
        "运镜方式": "固定镜头",
        "光源": "自然光",
    }
    assert result.scene_description == "画面亮度稳定，庭院细节清晰。"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_qwen_provider.py::test_normalize_response_payload_maps_structured_fields -v`
Expected: FAIL because normalization still maps to `summary_text/tags/notes`.

- [ ] **Step 3: Update `normalize_response_payload()` in `video_tagging_assistant/providers/qwen_dashscope_provider.py`**

```python
def normalize_response_payload(payload: Dict, source_video_path: Path, provider_name: str, model: str) -> GenerationResult:
    structured_tags = {
        key: str(value).strip()
        for key, value in payload.items()
        if key != "画面描述"
    }
    return GenerationResult(
        source_video_path=source_video_path,
        structured_tags=structured_tags,
        scene_description=str(payload.get("画面描述", "")).strip(),
        provider=provider_name,
        model=model,
        raw_response_excerpt=json.dumps(payload, ensure_ascii=False)[:500],
    )
```

- [ ] **Step 4: Run the normalization test**

Run: `pytest tests/test_qwen_provider.py::test_normalize_response_payload_maps_structured_fields -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add video_tagging_assistant/providers/qwen_dashscope_provider.py tests/test_qwen_provider.py
git commit -m "feat: normalize qwen responses into structured tags"
```

### Task 5: Export Structured Review Checklist

**Files:**
- Modify: `video_tagging_assistant/review_exporter.py`
- Modify: `tests/test_review_exporter.py`

- [ ] **Step 1: Write the failing structured review export test**

```python
from pathlib import Path

from video_tagging_assistant.models import GenerationResult
from video_tagging_assistant.review_exporter import export_review_list


def test_export_review_list_writes_structured_fields(tmp_path: Path):
    output_path = tmp_path / "review.txt"
    result = GenerationResult(
        source_video_path=Path("videos/case_A_001/clip01.mp4"),
        structured_tags={
            "安装方式": "胸前",
            "运动模式": "步行",
            "运镜方式": "固定镜头",
            "光源": "自然光",
        },
        scene_description="画面亮度稳定，庭院细节清晰。",
        provider="qwen_dashscope",
        model="qwen3.6-flash",
    )

    export_review_list([result], output_path)

    text = output_path.read_text(encoding="utf-8")
    assert "安装方式: 胸前" in text
    assert "运动模式: 步行" in text
    assert "画面描述: 画面亮度稳定，庭院细节清晰。" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_review_exporter.py::test_export_review_list_writes_structured_fields -v`
Expected: FAIL because exporter still prints `建议简介/建议标签/备注`.

- [ ] **Step 3: Update `video_tagging_assistant/review_exporter.py`**

```python
def export_review_list(results: List[GenerationResult], output_path: Path) -> None:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    sections = []
    for index, result in enumerate(results, start=1):
        tag_lines = [f"{key}: {value}" for key, value in result.structured_tags.items()]
        sections.append(
            "\n".join(
                [
                    f"## 条目 {index}",
                    f"视频路径: {result.source_video_path.as_posix()}",
                    *tag_lines,
                    f"画面描述: {result.scene_description}",
                    f"审核状态: {result.review_status}",
                    f"模型: {result.provider}/{result.model}",
                ]
            )
        )

    output_path.write_text("\n\n---\n\n".join(sections) + "\n", encoding="utf-8")
```

- [ ] **Step 4: Run the exporter test**

Run: `pytest tests/test_review_exporter.py::test_export_review_list_writes_structured_fields -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add video_tagging_assistant/review_exporter.py tests/test_review_exporter.py
git commit -m "feat: export structured tag review checklist"
```

### Task 6: Verify Provider Selection And Batch Pipeline Still Work

**Files:**
- Modify: `tests/test_pipeline.py`

- [ ] **Step 1: Write the failing structured pipeline assertion**

```python
import json
from pathlib import Path

from video_tagging_assistant.orchestrator import run_batch
from video_tagging_assistant.models import GenerationResult


class StructuredStubProvider:
    provider_name = "qwen_dashscope"

    def generate(self, context):
        return GenerationResult(
            source_video_path=context.source_video_path,
            structured_tags={
                "安装方式": "胸前",
                "运动模式": "步行",
                "运镜方式": "固定镜头",
                "光源": "自然光",
            },
            scene_description="画面亮度稳定，庭院细节清晰。",
            provider="qwen_dashscope",
            model="qwen3.6-flash",
        )


def test_run_batch_persists_structured_results(tmp_path: Path):
    input_dir = tmp_path / "videos"
    output_dir = tmp_path / "output"
    (input_dir / "DCG_HDR" / "case_A_001").mkdir(parents=True)
    (input_dir / "DCG_HDR" / "case_A_001" / "clip01.mp4").write_bytes(b"data")

    config = {
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "compression": {"width": 960, "video_bitrate": "700k", "audio_bitrate": "96k", "fps": 12},
        "prompt_template": {
            "system": "describe",
            "structured_tag_options": {
                "安装方式": ["胸前", "手持"],
                "运动模式": ["步行", "骑行"],
                "运镜方式": ["固定镜头", "跟拍"],
                "光源": ["自然光", "弱光"],
            },
        },
    }

    from tests.test_pipeline import StubCompressor
    result = run_batch(config, compressor=StubCompressor(), provider=StructuredStubProvider())

    review_text = (output_dir / "review" / "review.txt").read_text(encoding="utf-8")
    intermediate = json.loads((output_dir / "intermediate" / "clip01.json").read_text(encoding="utf-8"))

    assert result["processed"] == 1
    assert "安装方式: 胸前" in review_text
    assert intermediate["structured_tags"]["安装方式"] == "胸前"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline.py::test_run_batch_persists_structured_results -v`
Expected: FAIL until exporter/model changes are complete.

- [ ] **Step 3: Add the new test to `tests/test_pipeline.py`**

Append the test from Step 1 to the file, reusing the existing `StubCompressor`.

- [ ] **Step 4: Run pipeline tests**

Run: `pytest tests/test_pipeline.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_pipeline.py
git commit -m "test: verify structured tagging batch pipeline"
```

### Task 7: Run Full Verification And Manual Qwen Check

**Files:**
- Modify: `video_tagging_assistant/default_config.json` (only if you need to finalize real tag options after implementation)

- [ ] **Step 1: Run the full focused test suite**

Run: `pytest tests/test_scanner.py tests/test_config.py tests/test_context_builder.py tests/test_review_exporter.py tests/test_provider.py tests/test_pipeline.py tests/test_qwen_provider.py tests/test_structured_result_model.py -v`
Expected: PASS

- [ ] **Step 2: Run the manual Qwen script**

Run: `python "C:\Users\19872\Desktop\work！\qwen_video_compress_and_test.py"`
Expected: Successful model response, now aligned with structured single-choice output (or the script must be updated separately before expecting that output).

- [ ] **Step 3: Run the main CLI**

Run: `python -m video_tagging_assistant.cli --config video_tagging_assistant/default_config.json`
Expected: Generates `output/review/review.txt` with structured fields and `output/intermediate/*.json` containing `structured_tags` and `scene_description`.

- [ ] **Step 4: Commit**

```bash
git add video_tagging_assistant/default_config.json
git commit -m "test: verify structured tagging output end to end"
```

## Self-Review

### Spec Coverage

- Structured single-choice fields from `tag_pic.png`: covered by Tasks 2, 3, and 4.
- Remove free-form `tags` array from first-version output contract: covered by Tasks 3 and 4.
- Add `画面描述`: covered by Tasks 1, 4, and 5.
- Update review checklist and intermediate JSON: covered by Tasks 5 and 6.
- Preserve current batch architecture: covered by file reuse and Task 6.

### Placeholder Scan

- No `TODO`, `TBD`, or placeholder implementation steps remain.
- Every code step includes concrete code.
- Every validation step includes explicit commands and expected outcomes.

### Type Consistency

- `structured_tags` and `scene_description` are introduced in Task 1 and reused consistently in provider normalization, exporter output, and pipeline tests.
- `parse_json_content`, `_build_prompt_text`, and `normalize_response_payload` names stay consistent with the current provider implementation.
