# Multiselect Tagging And Full Configurability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the current structured tagging workflow so that base fields remain single-choice, `画面特征` and `影像表达` become multi-select fields, `画面描述` becomes more detailed while ignoring the fixed phone-time opening shot, and all path/prompt/tag options are configurable for deployment on other machines.

**Architecture:** Build on the existing Qwen structured-tag provider instead of replacing it. Split the configuration into explicit path settings plus separate single-choice and multi-choice field definitions, then update prompt construction, result normalization, and review export to honor the mixed output schema.

**Tech Stack:** Python 3.8, `pytest`, `json`, `pathlib`, existing `video_tagging_assistant` package, DashScope OpenAI-compatible HTTP

---

## File Structure

**Modify:**
- `video_tagging_assistant/models.py` — extend result model for mixed single-choice and multi-choice tag fields
- `video_tagging_assistant/providers/qwen_dashscope_provider.py` — update prompt generation and response normalization for mixed schema and opening-shot exclusion
- `video_tagging_assistant/review_exporter.py` — export mixed single/multi tag fields and detailed scene description
- `video_tagging_assistant/orchestrator.py` — honor configurable output paths instead of hardcoding from `output_dir`
- `video_tagging_assistant/default_config.json` — add `paths`, `single_choice_fields`, `multi_choice_fields`, and opening-shot rules
- `tests/test_qwen_provider.py` — add multi-select prompt and normalization tests
- `tests/test_pipeline.py` — add path configuration and mixed schema pipeline tests
- `tests/test_review_exporter_structured.py` — verify multi-select field rendering

**Reuse:**
- `video_tagging_assistant/context_builder.py`
- `video_tagging_assistant/compressor.py`
- `video_tagging_assistant/cli.py`

---

### Task 1: Extend Result Model For Multi-Select Fields

**Files:**
- Modify: `video_tagging_assistant/models.py`
- Create: `tests/test_multiselect_result_model.py`

- [ ] **Step 1: Write the failing mixed-schema result model test**

```python
from pathlib import Path

from video_tagging_assistant.models import GenerationResult


def test_generation_result_supports_multiselect_fields():
    result = GenerationResult(
        source_video_path=Path("videos/clip01.mp4"),
        structured_tags={
            "安装方式": "胸前",
            "运动模式": "步行",
            "运镜方式": "固定镜头",
            "光源": "自然光",
        },
        multi_select_tags={
            "画面特征": ["重复纹理", "边缘特征_强弱"],
            "影像表达": ["建筑空间", "风景录像"],
        },
        scene_description="画面亮度变化明显，但不描述手机时间开场。",
    )

    assert result.multi_select_tags["画面特征"] == ["重复纹理", "边缘特征_强弱"]
    assert "手机时间开场" in result.scene_description
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_multiselect_result_model.py::test_generation_result_supports_multiselect_fields -v`
Expected: FAIL because `GenerationResult` does not accept `multi_select_tags`.

- [ ] **Step 3: Update `GenerationResult` in `video_tagging_assistant/models.py`**

```python
@dataclass
class GenerationResult:
    source_video_path: Path
    summary_text: str = ""
    tags: List[str] = field(default_factory=list)
    notes: str = ""
    structured_tags: Dict[str, str] = field(default_factory=dict)
    multi_select_tags: Dict[str, List[str]] = field(default_factory=dict)
    scene_description: str = ""
    provider: str = ""
    model: str = ""
    raw_response_excerpt: str = ""
    review_status: str = "unreviewed"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_multiselect_result_model.py::test_generation_result_supports_multiselect_fields -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add video_tagging_assistant/models.py tests/test_multiselect_result_model.py
git commit -m "feat: add multiselect tag fields to generation results"
```

### Task 2: Make Paths Explicitly Configurable

**Files:**
- Modify: `video_tagging_assistant/default_config.json`
- Modify: `video_tagging_assistant/orchestrator.py`
- Modify: `tests/test_pipeline.py`

- [ ] **Step 1: Write the failing configurable paths pipeline test**

```python
import json
from pathlib import Path

from video_tagging_assistant.models import GenerationResult
from video_tagging_assistant.orchestrator import run_batch


class StubCompressor:
    def __call__(self, task, output_dir, compression_config):
        proxy_path = output_dir / f"{Path(task.file_name).stem}_proxy.mp4"
        output_dir.mkdir(parents=True, exist_ok=True)
        proxy_path.write_bytes(b"proxy")
        from video_tagging_assistant.models import CompressedArtifact
        return CompressedArtifact(task.source_video_path, proxy_path)


class StructuredStubProvider:
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


def test_run_batch_honors_explicit_output_paths(tmp_path: Path):
    input_dir = tmp_path / "videos"
    (input_dir / "case_A_001").mkdir(parents=True)
    (input_dir / "case_A_001" / "clip01.mp4").write_bytes(b"data")

    config = {
        "input_dir": str(input_dir),
        "output_dir": str(tmp_path / "output"),
        "paths": {
            "compressed_dir": str(tmp_path / "custom" / "compressed"),
            "intermediate_dir": str(tmp_path / "custom" / "intermediate"),
            "review_file": str(tmp_path / "custom" / "review" / "review.txt"),
        },
        "compression": {"width": 960, "video_bitrate": "700k", "audio_bitrate": "96k", "fps": 12},
        "prompt_template": {"system": "x", "single_choice_fields": {}, "multi_choice_fields": {}},
    }

    summary = run_batch(config, compressor=StubCompressor(), provider=StructuredStubProvider())

    assert Path(summary["review_path"]).as_posix().endswith("custom/review/review.txt")
    assert (tmp_path / "custom" / "intermediate" / "clip01.json").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline.py::test_run_batch_honors_explicit_output_paths -v`
Expected: FAIL because `run_batch()` still derives everything from `output_dir`.

- [ ] **Step 3: Update `video_tagging_assistant/default_config.json`**

Restructure it to include explicit `paths`, e.g.:

```json
"paths": {
  "compressed_dir": "output/compressed",
  "intermediate_dir": "output/intermediate",
  "review_file": "output/review/review.txt"
}
```

Also replace `structured_tag_options` with:

```json
"single_choice_fields": {
  "安装方式": ["胸前", "头戴", "手持", "车把", "其他"],
  "运动模式": ["步行", "跑步", "骑行", "静止", "其他"],
  "运镜方式": ["固定镜头", "平移", "推进", "拉远", "跟拍", "其他"],
  "光源": ["自然光", "室内灯光", "逆光", "弱光", "混合光", "其他"]
},
"multi_choice_fields": {
  "画面特征": ["纹理_高低频", "重复纹理", "边缘特征_强弱", "运动对焦", "人物肤色", "景深远近切换", "反射与透视"],
  "影像表达": ["风景录像", "建筑空间", "美食游街", "运动跟拍", "主题拍摄", "赛事舞台", "多目标分散运镜", "交互叙事"]
},
"ignore_opening_instruction": "不要描述开头固定出现的手持手机展示时间特写镜头。",
"scene_description_instruction": "画面描述可更详细，重点描述光亮变化、场景细节、主体运动和画面变化。"
```

- [ ] **Step 4: Update `video_tagging_assistant/orchestrator.py`**

```python
def run_batch(config: Dict, compressor=compress_video, provider=None) -> Dict[str, Any]:
    if provider is None:
        raise ValueError("provider is required")

    input_dir = Path(config["input_dir"])
    output_dir = Path(config["output_dir"])
    paths = config.get("paths", {})
    compressed_dir = Path(paths.get("compressed_dir", str(output_dir / "compressed")))
    intermediate_dir = Path(paths.get("intermediate_dir", str(output_dir / "intermediate")))
    review_path = Path(paths.get("review_file", str(output_dir / "review" / "review.txt")))
    ...
```

Keep the rest of the batching logic unchanged.

- [ ] **Step 5: Add the test from Step 1 to `tests/test_pipeline.py`**

- [ ] **Step 6: Run pipeline tests**

Run: `pytest tests/test_pipeline.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add video_tagging_assistant/default_config.json video_tagging_assistant/orchestrator.py tests/test_pipeline.py
git commit -m "feat: add explicit path configuration for deployment"
```

### Task 3: Update Prompt Contract For Single-Choice + Multi-Choice Fields

**Files:**
- Modify: `video_tagging_assistant/providers/qwen_dashscope_provider.py`
- Modify: `tests/test_qwen_provider.py`

- [ ] **Step 1: Write the failing mixed prompt contract test**

```python
from pathlib import Path

from video_tagging_assistant.context_builder import build_prompt_context
from video_tagging_assistant.models import CompressedArtifact, VideoTask
from video_tagging_assistant.providers.qwen_dashscope_provider import QwenDashScopeVideoTagProvider


def test_qwen_prompt_mentions_single_and_multiselect_rules():
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
            "single_choice_fields": {
                "安装方式": ["胸前", "手持"],
                "光源": ["自然光", "弱光"],
            },
            "multi_choice_fields": {
                "画面特征": ["重复纹理", "反射与透视"],
                "影像表达": ["建筑空间", "风景录像"],
            },
            "ignore_opening_instruction": "不要描述手机时间特写开场。",
            "scene_description_instruction": "画面描述可以更详细。",
        },
    )
    provider = QwenDashScopeVideoTagProvider(
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key_env="DASHSCOPE_API_KEY",
        model="qwen3.6-flash",
    )

    prompt_text = provider._build_prompt_text(context)

    assert "单选字段必须且只能选择一个候选值" in prompt_text
    assert "多选字段可以选择多个候选值" in prompt_text
    assert "不要描述手机时间特写开场。" in prompt_text
    assert "- 画面特征: 重复纹理, 反射与透视" in prompt_text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_qwen_provider.py::test_qwen_prompt_mentions_single_and_multiselect_rules -v`
Expected: FAIL because provider currently only knows `structured_tag_options` single-choice fields.

- [ ] **Step 3: Update `_build_prompt_text()` in `video_tagging_assistant/providers/qwen_dashscope_provider.py`**

Change it to use `single_choice_fields`, `multi_choice_fields`, `ignore_opening_instruction`, and `scene_description_instruction`, e.g.:

```python
def _build_prompt_text(self, context: PromptContext) -> str:
    single_fields = context.template_fields.get("single_choice_fields", {})
    multi_fields = context.template_fields.get("multi_choice_fields", {})
    single_lines = [f"- {name}: {', '.join(values)}" for name, values in single_fields.items()]
    multi_lines = [f"- {name}: {', '.join(values)}" for name, values in multi_fields.items()]

    prompt_lines = [
        context.template_fields.get("system", "请根据视频内容输出结构化标签。"),
        "",
        "规则：",
        "1. 输出中文",
        "2. 单选字段必须且只能选择一个候选值",
        "3. 多选字段可以选择多个候选值",
        "4. 所有值必须来自给定候选列表",
        "5. 不允许输出未定义字段",
        f"6. {context.template_fields.get('ignore_opening_instruction', '')}",
        f"7. {context.template_fields.get('scene_description_instruction', '')}",
        "",
        "单选字段：",
        *single_lines,
        "",
        "多选字段：",
        *multi_lines,
        "",
        "附加上下文：",
        f"- case_id: {context.parsed_metadata.get('case_id')}",
        f"- mode: {context.parsed_metadata.get('mode')}",
        f"- file_name: {context.parsed_metadata.get('file_name')}",
        "",
        "返回格式：",
        '{"安装方式": "string", "运动模式": "string", "运镜方式": "string", "光源": "string", "画面特征": ["string"], "影像表达": ["string"], "画面描述": "string"}',
    ]
    return "\n".join([line for line in prompt_lines if line])
```

- [ ] **Step 4: Run the prompt test**

Run: `pytest tests/test_qwen_provider.py::test_qwen_prompt_mentions_single_and_multiselect_rules -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add video_tagging_assistant/providers/qwen_dashscope_provider.py tests/test_qwen_provider.py
git commit -m "feat: support multiselect tag prompt rules"
```

### Task 4: Normalize Mixed Single-Choice And Multi-Choice Results

**Files:**
- Modify: `video_tagging_assistant/providers/qwen_dashscope_provider.py`
- Modify: `tests/test_qwen_provider.py`

- [ ] **Step 1: Write the failing mixed-schema normalization test**

```python
from pathlib import Path

from video_tagging_assistant.providers.qwen_dashscope_provider import normalize_response_payload


def test_normalize_response_payload_maps_mixed_schema():
    payload = {
        "安装方式": "胸前",
        "运动模式": "步行",
        "运镜方式": "固定镜头",
        "光源": "自然光",
        "画面特征": ["重复纹理", "边缘特征_强弱"],
        "影像表达": ["建筑空间", "风景录像"],
        "画面描述": "光亮变化明显，庭院结构细节清晰，不描述手机时间开场。",
    }

    result = normalize_response_payload(payload, Path("videos/clip01.mp4"), "qwen_dashscope", "qwen3.6-flash")

    assert result.structured_tags["安装方式"] == "胸前"
    assert result.multi_select_tags["画面特征"] == ["重复纹理", "边缘特征_强弱"]
    assert result.multi_select_tags["影像表达"] == ["建筑空间", "风景录像"]
    assert result.scene_description.startswith("光亮变化明显")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_qwen_provider.py::test_normalize_response_payload_maps_mixed_schema -v`
Expected: FAIL because current normalization treats everything except `画面描述` as single-choice strings.

- [ ] **Step 3: Update `normalize_response_payload()` in `video_tagging_assistant/providers/qwen_dashscope_provider.py`**

```python
def normalize_response_payload(payload: Dict, source_video_path: Path, provider_name: str, model: str) -> GenerationResult:
    multi_select_field_names = {"画面特征", "影像表达"}
    structured_tags = {}
    multi_select_tags = {}

    for key, value in payload.items():
        if key == "画面描述":
            continue
        if key in multi_select_field_names:
            values = value if isinstance(value, list) else [value]
            multi_select_tags[key] = [str(item).strip() for item in values if str(item).strip()]
        else:
            structured_tags[key] = str(value).strip()

    return GenerationResult(
        source_video_path=source_video_path,
        structured_tags=structured_tags,
        multi_select_tags=multi_select_tags,
        scene_description=str(payload.get("画面描述", "")).strip(),
        provider=provider_name,
        model=model,
        raw_response_excerpt=json.dumps(payload, ensure_ascii=False)[:500],
    )
```

- [ ] **Step 4: Run the normalization test**

Run: `pytest tests/test_qwen_provider.py::test_normalize_response_payload_maps_mixed_schema -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add video_tagging_assistant/providers/qwen_dashscope_provider.py tests/test_qwen_provider.py
git commit -m "feat: normalize mixed single and multiselect tag output"
```

### Task 5: Export Multi-Select Fields In Review Output

**Files:**
- Modify: `video_tagging_assistant/review_exporter.py`
- Modify: `tests/test_review_exporter_structured.py`

- [ ] **Step 1: Write the failing multi-select review export test**

```python
from pathlib import Path

from video_tagging_assistant.models import GenerationResult
from video_tagging_assistant.review_exporter import export_review_list


def test_export_review_list_renders_multiselect_fields(tmp_path: Path):
    output_path = tmp_path / "review.txt"
    result = GenerationResult(
        source_video_path=Path("videos/case_A_001/clip01.mp4"),
        structured_tags={"安装方式": "胸前", "光源": "自然光"},
        multi_select_tags={
            "画面特征": ["重复纹理", "边缘特征_强弱"],
            "影像表达": ["建筑空间", "风景录像"],
        },
        scene_description="详细描述，有效画面信息，不写手机时间开场。",
        provider="qwen_dashscope",
        model="qwen3.6-flash",
    )

    export_review_list([result], output_path)

    text = output_path.read_text(encoding="utf-8")
    assert "画面特征: 重复纹理, 边缘特征_强弱" in text
    assert "影像表达: 建筑空间, 风景录像" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_review_exporter_structured.py::test_export_review_list_renders_multiselect_fields -v`
Expected: FAIL because exporter currently only emits `structured_tags` and `画面描述`.

- [ ] **Step 3: Update `video_tagging_assistant/review_exporter.py`**

```python
def export_review_list(results: List[GenerationResult], output_path: Path) -> None:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    sections = []
    for index, result in enumerate(results, start=1):
        single_lines = [f"{key}: {value}" for key, value in result.structured_tags.items()]
        multi_lines = [f"{key}: {', '.join(values)}" for key, values in result.multi_select_tags.items()]
        fallback_lines = []
        if not single_lines and not multi_lines:
            fallback_lines = [
                f"建议简介: {result.summary_text}",
                f"建议标签: {', '.join(result.tags)}",
                f"备注: {result.notes}",
            ]

        sections.append(
            "\n".join(
                [
                    f"## 条目 {index}",
                    f"视频路径: {result.source_video_path.as_posix()}",
                    *single_lines,
                    *multi_lines,
                    *fallback_lines,
                    f"画面描述: {result.scene_description}",
                    f"审核状态: {result.review_status}",
                    f"模型: {result.provider}/{result.model}",
                ]
            )
        )

    output_path.write_text("\n\n---\n\n".join(sections) + "\n", encoding="utf-8")
```

- [ ] **Step 4: Run review exporter tests**

Run: `pytest tests/test_review_exporter_structured.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add video_tagging_assistant/review_exporter.py tests/test_review_exporter_structured.py
git commit -m "feat: export multiselect tagging fields in review output"
```

### Task 6: Verify End-To-End Mixed Schema Workflow

**Files:**
- Modify: `tests/test_pipeline.py`
- Modify: `tests/test_qwen_provider.py`

- [ ] **Step 1: Add the failing mixed-schema pipeline test**

```python
import json
from pathlib import Path

from video_tagging_assistant.models import GenerationResult
from video_tagging_assistant.orchestrator import run_batch


class MixedSchemaStubProvider:
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
            multi_select_tags={
                "画面特征": ["重复纹理", "边缘特征_强弱"],
                "影像表达": ["建筑空间", "风景录像"],
            },
            scene_description="更详细的描述，不包含手机时间开场。",
            provider="qwen_dashscope",
            model="qwen3.6-flash",
        )


def test_run_batch_persists_mixed_schema_results(tmp_path: Path):
    input_dir = tmp_path / "videos"
    output_root = tmp_path / "output"
    (input_dir / "DCG_HDR" / "case_A_001").mkdir(parents=True)
    (input_dir / "DCG_HDR" / "case_A_001" / "clip01.mp4").write_bytes(b"data")

    config = {
        "input_dir": str(input_dir),
        "output_dir": str(output_root),
        "paths": {
            "compressed_dir": str(output_root / "compressed"),
            "intermediate_dir": str(output_root / "intermediate"),
            "review_file": str(output_root / "review" / "review.txt"),
        },
        "compression": {"width": 960, "video_bitrate": "700k", "audio_bitrate": "96k", "fps": 12},
        "prompt_template": {
            "system": "describe",
            "single_choice_fields": {},
            "multi_choice_fields": {},
        },
    }

    from tests.test_pipeline import StubCompressor
    summary = run_batch(config, compressor=StubCompressor(), provider=MixedSchemaStubProvider())

    review_text = (output_root / "review" / "review.txt").read_text(encoding="utf-8")
    intermediate = json.loads((output_root / "intermediate" / "clip01.json").read_text(encoding="utf-8"))

    assert summary["processed"] == 1
    assert "画面特征: 重复纹理, 边缘特征_强弱" in review_text
    assert intermediate["multi_select_tags"]["影像表达"] == ["建筑空间", "风景录像"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline.py::test_run_batch_persists_mixed_schema_results -v`
Expected: FAIL until multi-select exporter and normalization changes are complete.

- [ ] **Step 3: Add the test from Step 1 to `tests/test_pipeline.py`**

- [ ] **Step 4: Run the mixed-schema test**

Run: `pytest tests/test_pipeline.py::test_run_batch_persists_mixed_schema_results -v`
Expected: PASS

- [ ] **Step 5: Run the full focused suite**

Run: `pytest tests/test_scanner.py tests/test_config.py tests/test_context_builder.py tests/test_review_exporter.py tests/test_provider.py tests/test_pipeline.py tests/test_qwen_provider.py tests/test_structured_result_model.py tests/test_review_exporter_structured.py tests/test_multiselect_result_model.py -v`
Expected: PASS

- [ ] **Step 6: Run the real CLI**

Run: `python -m video_tagging_assistant.cli --config video_tagging_assistant/default_config.json`
Expected: Generates structured review output with base single-choice tags, multi-select `画面特征` / `影像表达`, and detailed `画面描述` while using configured paths and provider key.

- [ ] **Step 7: Commit**

```bash
git add tests/test_pipeline.py tests/test_qwen_provider.py
git commit -m "test: verify mixed tagging workflow end to end"
```

## Self-Review

### Spec Coverage

- Base single-choice fields retained: Tasks 3 and 4.
- New multi-select fields `画面特征` / `影像表达`: Tasks 1, 3, 4, 5, and 6.
- `画面描述` more detailed and excludes phone-time opening: Task 3 prompt changes, Task 4 normalization, Task 5 review output.
- Full configurability for deployment paths and tag templates: Task 2.
- Other-machine deployment via config-only edits: Task 2 and Task 6.

### Placeholder Scan

- No `TODO` / `TBD` placeholders remain.
- Every implementation step contains concrete code.
- Every verification step contains an exact command and expected outcome.

### Type Consistency

- `multi_select_tags` is introduced in Task 1 and reused consistently in normalization, exporter, and pipeline tests.
- `single_choice_fields`, `multi_choice_fields`, `ignore_opening_instruction`, and `scene_description_instruction` are used consistently in prompt construction and config updates.
