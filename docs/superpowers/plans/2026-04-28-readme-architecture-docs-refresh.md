# README And Architecture Docs Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite `README.md` into a concise usage-entry document and add `docs/architecture.md` summarizing the current runtime framework and implementation structure.

**Architecture:** Keep all changes in documentation only. Restructure existing validated content so `README.md` focuses on first-run usage and navigation, while `docs/architecture.md` becomes the maintainer-facing map of both pipelines, CLI dispatch, modules, configuration, and implementation limits.

**Tech Stack:** Markdown, existing repository docs, current Python module structure

---

## File Structure

**Create:**
- `docs/architecture.md` — current runtime framework, module boundaries, data flow, and implementation limits

**Modify:**
- `README.md` — rewrite as the project entry document for daily users

**Reference Only:**
- `docs/case-ingest-usage.md` — existing detailed case-ingest usage and behavior notes
- `video_tagging_assistant/cli.py` — CLI split between video tagging and case-ingest
- `video_tagging_assistant/orchestrator.py` — video tagging runtime orchestration
- `video_tagging_assistant/case_ingest_orchestrator.py` — case-ingest runtime orchestration
- `video_tagging_assistant/config.py` — video tagging config and case-ingest config loading
- `video_tagging_assistant/bat_parser.py` — case-ingest bat parsing behavior

---

### Task 1: Add A Documentation Structure Test That Locks The New Boundaries

**Files:**
- Create: `tests/test_docs_structure.py`
- Modify: `README.md`
- Create: `docs/architecture.md`

- [ ] **Step 1: Write the failing documentation structure tests**

Write this file to `tests/test_docs_structure.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_docs_structure.py -v`
Expected: FAIL because `docs/architecture.md` does not exist and the current `README.md` does not match the new structure.

- [ ] **Step 3: Create a minimal first-pass `README.md` and `docs/architecture.md`**

Replace `README.md` with this initial structure:

```md
# 视频打标与 Case Ingest 工具

## 项目简介

该项目包含两条主流程：

- 视频打标：扫描本地视频、压缩代理视频、调用模型生成标签和画面描述、输出审核结果。
- Case Ingest：读取 bat 任务、执行 pull / copy / upload，并把分散的归档流程整合到统一入口。

## 快速开始

### 视频打标

```bash
python -m video_tagging_assistant.cli --config video_tagging_assistant/default_config.json
```

### Case Ingest

推荐直接运行：

- `run_case_ingest.bat`

或使用命令行：

```bash
python -m video_tagging_assistant.cli case-ingest --config configs/case_ingest.json
```

## 延伸阅读

- 架构与运行框架：`docs/architecture.md`
- Case Ingest 细节说明：`docs/case-ingest-usage.md`
```

Create `docs/architecture.md` with this initial structure:

```md
# 架构说明

## 系统概览

当前项目包含两条主流程：视频打标流程与 Case Ingest 流程。

统一入口位于 `video_tagging_assistant/cli.py`：

- 默认模式运行视频打标流程
- `case-ingest` 子命令运行 Case Ingest 流程

## 视频打标流程

主流程由以下模块组成：

- `video_tagging_assistant/orchestrator.py`
- `video_tagging_assistant/scanner.py`
- `video_tagging_assistant/compressor.py`
- `video_tagging_assistant/context_builder.py`
- `video_tagging_assistant/review_exporter.py`

## Case Ingest 流程

主流程由以下模块组成：

- `video_tagging_assistant/bat_parser.py`
- `video_tagging_assistant/case_ingest_models.py`
- `video_tagging_assistant/pull_worker.py`
- `video_tagging_assistant/copy_worker.py`
- `video_tagging_assistant/upload_worker.py`
- `video_tagging_assistant/case_ingest_orchestrator.py`
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_docs_structure.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_docs_structure.py README.md docs/architecture.md
git commit -m "test: lock documentation entry structure"
```

### Task 2: Rewrite README As The User-Facing Entry Document

**Files:**
- Modify: `README.md`
- Test: `tests/test_docs_structure.py`

- [ ] **Step 1: Expand the README structure test with user-facing sections**

Append this test to `tests/test_docs_structure.py`:

```python
def test_readme_focuses_on_usage_and_navigation():
    text = Path("README.md").read_text(encoding="utf-8")

    assert "## 项目能力概览" in text
    assert "## 环境要求" in text
    assert "## 关键配置文件" in text
    assert "## 输出位置" in text
    assert "video_tagging_assistant/default_config.json" in text
    assert "configs/case_ingest.json" in text
    assert "docs/case-ingest-usage.md" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_docs_structure.py::test_readme_focuses_on_usage_and_navigation -v`
Expected: FAIL because the initial README does not yet contain all required sections.

- [ ] **Step 3: Rewrite `README.md` with the final user-facing structure**

Replace `README.md` with this content:

```md
# 视频打标与 Case Ingest 工具

## 项目简介

这个项目用于支持两条日常流程：

- **视频打标**：扫描本地视频，压缩代理文件，调用模型生成标签与画面描述，并输出审核结果。
- **Case Ingest**：读取既有 bat 任务，执行 pull / copy / upload，把 case 采集归档流程统一到一个入口。

## 项目能力概览

### 视频打标流程

当前支持：

- 扫描待处理视频目录
- 压缩送模视频
- 组装结构化上下文
- 调用模型生成标签和画面描述
- 输出 review 文本和中间结果

### Case Ingest 流程

当前支持：

- 读取 `pull.bat` 和 `move.bat`
- 按 `case_A_xxxx` 聚合任务
- 执行 RK raw pull
- 复制 DJI normal / night 文件
- 上传整个 case 目录到服务器日期目录
- 支持可重跑的断点续传

## 环境要求

- Windows
- Python 3.8+
- `ffmpeg.exe`
- `adb.exe`（Case Ingest 需要）
- 可访问模型接口的网络环境（视频打标需要）
- 可访问目标共享目录的网络环境（Case Ingest 上传需要）

## 快速开始

### 视频打标

```bash
python -m video_tagging_assistant.cli --config video_tagging_assistant/default_config.json
```

也可以直接运行：

- `run_cli.bat`

### Case Ingest

推荐直接运行：

- `run_case_ingest.bat`

它会读取：

- `configs/case_ingest.json`

如果需要命令行运行：

```bash
python -m video_tagging_assistant.cli case-ingest --config configs/case_ingest.json
```

## 关键配置文件

### 视频打标

- `video_tagging_assistant/default_config.json`

重点配置：

- 输入目录：`input_dir`
- 输出目录：`output_dir`
- review 文件：`paths.review_file`
- 模型配置：`provider`

### Case Ingest

- `configs/case_ingest.json`

重点配置：

- `pull_bat`
- `move_bat`
- `server_root`
- `date`
- `skip_upload`

## 输出位置

### 视频打标

- 压缩视频：`output/compressed/`
- 中间结果：`output/intermediate/`
- 审核清单：`output/review/review.txt`

### Case Ingest

- 本地 RK raw 归档目录：由 `pull.bat` 中 `move_dst` 决定
- 本地 DJI 目标路径：由 `move.bat` 中目标路径决定
- 服务器目录：`<server_root>/<date>/case_A_xxxx`

## 延伸阅读

- 当前运行框架与模块职责：`docs/architecture.md`
- Case Ingest 详细使用说明：`docs/case-ingest-usage.md`
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_docs_structure.py::test_readme_focuses_on_usage_and_navigation -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add README.md tests/test_docs_structure.py
git commit -m "docs: rewrite readme as usage entrypoint"
```

### Task 3: Add The Maintainer-Facing Architecture Document

**Files:**
- Create: `docs/architecture.md`
- Test: `tests/test_docs_structure.py`

- [ ] **Step 1: Expand the architecture test with implementation sections**

Append this test to `tests/test_docs_structure.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_docs_structure.py::test_architecture_doc_covers_runtime_structure_and_limits -v`
Expected: FAIL because the initial architecture document is too shallow.

- [ ] **Step 3: Replace `docs/architecture.md` with the final maintainer-facing document**

Write this content to `docs/architecture.md`:

```md
# 架构说明

## 系统概览

当前项目包含两条主流程：

1. **视频打标流程**
   - 面向本地视频理解与审核输出
2. **Case Ingest 流程**
   - 面向 case 采集归档、补拷与上传

统一入口位于 `video_tagging_assistant/cli.py`。

## 运行入口与分流

CLI 有两种主要模式：

- 默认模式：运行视频打标流程
  - `python -m video_tagging_assistant.cli --config video_tagging_assistant/default_config.json`
- 子命令模式：运行 Case Ingest
  - `python -m video_tagging_assistant.cli case-ingest --config configs/case_ingest.json`

其中：

- 视频打标主要依赖 JSON 配置文件
- Case Ingest 既支持直接命令行参数，也支持通过 `configs/case_ingest.json` 读取运行参数
- `run_case_ingest.bat` 是当前推荐的 Case Ingest 启动入口

## 视频打标流程架构

视频打标主流程由 `video_tagging_assistant/orchestrator.py` 串联，核心模块如下：

- `video_tagging_assistant/scanner.py`
  - 扫描输入目录，识别待处理视频
- `video_tagging_assistant/compressor.py`
  - 生成送模压缩视频
- `video_tagging_assistant/context_builder.py`
  - 组装目录、文件名、模板信息，形成提示上下文
- `video_tagging_assistant/providers/*`
  - 屏蔽不同模型提供方的调用差异
- `video_tagging_assistant/review_exporter.py`
  - 输出 review 文本、HTML 报告和中间结果
- `video_tagging_assistant/orchestrator.py`
  - 负责整体批处理编排、并发与结果汇总

数据流顺序是：

`输入视频目录 -> scanner -> compressor -> context_builder -> provider -> review_exporter`

## Case Ingest 流程架构

Case Ingest 主流程由 `video_tagging_assistant/case_ingest_orchestrator.py` 串联，核心模块如下：

- `video_tagging_assistant/bat_parser.py`
  - 解析 `pull.bat` 与 `move.bat`
  - 提取 `case_A_xxxx`、pull 任务和 copy 任务
- `video_tagging_assistant/case_ingest_models.py`
  - 定义 `PullTask`、`CopyTask`、`CaseTask`、`UploadResult`
- `video_tagging_assistant/pull_worker.py`
  - 执行 ADB pull、文件数校验、临时目录合并
- `video_tagging_assistant/copy_worker.py`
  - 执行 DJI 文件补拷
- `video_tagging_assistant/upload_worker.py`
  - 执行整 case 目录上传与跳过逻辑
- `video_tagging_assistant/case_ingest_orchestrator.py`
  - 负责编排 pull / copy / upload

数据流顺序是：

`pull.bat + move.bat -> bat_parser -> CaseTask -> pull_worker -> copy_worker -> upload_worker`

## 关键文件职责

### 入口与配置

- `video_tagging_assistant/cli.py`
  - 项目统一入口，负责在视频打标与 Case Ingest 之间分流
- `video_tagging_assistant/config.py`
  - 加载视频打标配置与 Case Ingest 配置

### 视频打标主链路

- `video_tagging_assistant/scanner.py`
- `video_tagging_assistant/compressor.py`
- `video_tagging_assistant/context_builder.py`
- `video_tagging_assistant/review_exporter.py`
- `video_tagging_assistant/orchestrator.py`

### Case Ingest 主链路

- `video_tagging_assistant/bat_parser.py`
- `video_tagging_assistant/case_ingest_models.py`
- `video_tagging_assistant/pull_worker.py`
- `video_tagging_assistant/copy_worker.py`
- `video_tagging_assistant/upload_worker.py`
- `video_tagging_assistant/case_ingest_orchestrator.py`

## 配置与运行时关系

### 视频打标配置

视频打标主要通过 `video_tagging_assistant/default_config.json` 决定：

- 输入目录
- 输出目录
- review 输出路径
- provider 选择
- 并发参数
- prompt 模板

### Case Ingest 配置

Case Ingest 当前推荐通过 `configs/case_ingest.json` 运行，主要包括：

- `pull_bat`
- `move_bat`
- `server_root`
- `date`
- `skip_upload`

相对路径默认相对配置文件自身解析。

### bat 与最终目录关系

- `pull.bat` 提供 RK raw pull 来源路径与本地最终归档路径
- `move.bat` 提供 DJI 文件复制来源路径与目标路径
- `server_root` 与 `date` 共同决定服务器上传目标目录

## 当前实现边界与限制

### 视频打标流程

- 当前主目标是生成本地审核结果，不是直接写回 Excel
- provider 调用能力已抽象，但仍依赖当前支持的接口实现

### Case Ingest 流程

- 当前上传策略是：服务器同名 case 已存在时直接跳过
- 当前不会自动修复服务器端半成品 case
- 断点续传主要针对 RK raw pull 阶段
- bat 仍然是 Case Ingest 数据来源的一部分，不是完全脱离 bat 的新体系

## 相关文档

- 使用入口：`README.md`
- Case Ingest 详细用法：`docs/case-ingest-usage.md`
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_docs_structure.py::test_architecture_doc_covers_runtime_structure_and_limits -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add docs/architecture.md tests/test_docs_structure.py
git commit -m "docs: add runtime architecture overview"
```

### Task 4: Verify Documentation Consistency And Navigation

**Files:**
- Modify: `README.md` (only if consistency review finds a mismatch)
- Modify: `docs/architecture.md` (only if consistency review finds a mismatch)
- Test: `tests/test_docs_structure.py`

- [ ] **Step 1: Add a final consistency test**

Append this test to `tests/test_docs_structure.py`:

```python
def test_docs_cross_reference_each_other_cleanly():
    readme = Path("README.md").read_text(encoding="utf-8")
    architecture = Path("docs/architecture.md").read_text(encoding="utf-8")

    assert "docs/architecture.md" in readme
    assert "README.md" in architecture
    assert "run_case_ingest.bat" in readme
    assert "configs/case_ingest.json" in architecture
```

- [ ] **Step 2: Run test to verify it passes**

Run: `pytest tests/test_docs_structure.py -v`
Expected: PASS

- [ ] **Step 3: Manually verify the rewritten docs**

Read both files and confirm:

- `README.md` is shorter and more entry-oriented than before.
- `docs/architecture.md` carries the runtime-structure detail.
- Commands and file paths match the current codebase.
- There is no obvious contradiction between the two documents.

- [ ] **Step 4: Commit**

```bash
git add README.md docs/architecture.md tests/test_docs_structure.py
git commit -m "docs: clarify user guide and architecture map"
```

---

## Self-Review

- **Spec coverage:** Task 2 covers the README rewrite, Task 3 covers `docs/architecture.md`, and Task 4 verifies cross-document consistency and file/path correctness.
- **Placeholder scan:** All tasks include exact file paths, concrete markdown content, and explicit test commands.
- **Type consistency:** The documents consistently reference `run_case_ingest.bat`, `configs/case_ingest.json`, `video_tagging_assistant/cli.py`, `video_tagging_assistant/orchestrator.py`, and `video_tagging_assistant/case_ingest_orchestrator.py`.
