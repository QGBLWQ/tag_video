# RK-DJI Alignment Design

## Background

Current GUI pipeline assumes `获取列表` sheet already contains a usable `RK_raw` value for each DJI `normal/night` pair. That assumption blocks the next workflow stage when `RK_raw` is empty, even though DJI videos are still valid and can already enter AI tagging.

At the same time, RK source folders under `/mnt/nvme/CapturedData` or mirrored `temp_path` have two important realities:

- folder names can be plain numeric (`32`) or numeric plus `x` (`32x`)
- a folder without a preview jpeg is considered unusable for manual alignment

The new requirement is to add a manual RK-DJI alignment stage that runs in parallel with AI tagging. Operators should align each DJI `normal/night` pair to exactly one valid RK folder, write the selected RK folder name back to `RK_raw`, and only enter the existing review stage after both batch tagging and batch alignment are complete.

## Goals

- Allow batch tagging to start even when `RK_raw` is blank.
- Add a dedicated alignment UI that resolves blank `RK_raw` values by comparing DJI previews against RK jpeg previews.
- Keep RK selection monotonic and consumption-based across the batch.
- Reuse existing `.xlsm -> .xlsx` writeback behavior.
- Preserve the existing review, execution, auto-mode, and upload flows after the alignment gate.

## Non-Goals

- No change to the downstream review UI semantics after review begins.
- No attempt to auto-detect DJI-RK matches without operator confirmation.
- No RK multi-frame preview generation. RK stays single-jpeg preview only.
- No automatic cascade rewrite of later cases when an earlier aligned case is changed.
- No change to the existing full-suite smoke test baseline unrelated to this feature.

## Confirmed Product Decisions

- Only rows with empty `RK_raw` automatically enter the alignment queue.
- Already aligned rows do not auto-enter alignment; rewriting uses a dedicated entry point inside the alignment page.
- Review unlock is a strict batch gate: both batch tagging and batch alignment must be complete.
- RK candidate discovery prefers `temp_path` when available, and falls back to `dut_root` (`/mnt/nvme/CapturedData`).
- An RK folder is valid if and only if it contains a preview `jpeg/jpg`; folders without jpeg are excluded and logged as bad directories.
- Candidate ordering is consumption-based. When a case confirms an RK folder, that candidate is consumed and later cases default from the next candidate forward.
- Historical non-empty `RK_raw` values in earlier workbook rows must participate in the default consumption cursor, even if those rows are not re-opened for alignment.
- Rewriting a previously aligned case is allowed only when the new choice preserves strict monotonic unique assignment for later already-confirmed cases. Otherwise the rewrite is blocked and the user must first clear later affected cases.
- DJI preview generation uses ffmpeg to build a uniformly sampled preview strip from the video pair. RK preview is the single existing jpeg from the folder.

## User Workflow

### 1. Load Workbook

The operator loads the workbook from the existing `打标` tab. The system continues to:

- build the full batch of DJI cases from `获取列表`
- create or reuse the `.xlsx` writeback copy when the source workbook is `.xlsm`
- compute the next `case_id` sequence as it does today

In addition, the load step now also initializes the alignment batch:

- identify all workbook rows where DJI `normal/night` are present and `RK_raw` is blank
- scan the RK source root and construct the valid RK candidate pool
- record bad RK directories in an alignment log
- enable the new `对齐` tab with the pending alignment queue

### 2. Run Tagging and Alignment in Parallel

The operator may:

- start AI tagging from the `打标` tab
- switch to the `对齐` tab and manually resolve pending `RK_raw` rows

These two activities are intentionally independent. Tagging completion does not auto-open review. Alignment completion does not auto-open review.

### 3. Confirm Alignment

For each pending alignment case, the operator sees:

- DJI `normal` preview strip
- DJI `night` preview strip
- the currently selected RK jpeg preview

The operator keeps DJI fixed and moves only the RK candidate:

- previous RK
- next RK
- confirm current alignment
- clear current alignment
- save and move to the next pending case

Confirming an alignment immediately writes the selected RK folder name into `RK_raw` in the shared `.xlsx` writeback target.

### 4. Rewrite Previously Aligned Cases

The alignment page exposes a dedicated `重写已对齐 case` entry point. This loads already aligned rows into a rewrite view without mixing them into the normal pending queue.

Rewriting follows the same preview and confirmation UI, but applies the monotonic uniqueness guard:

- safe rewrite: allow overwrite of `RK_raw`
- unsafe rewrite: block and instruct the user to clear later conflicting cases first

### 5. Enter Review

The existing review page remains disabled until both conditions are true:

- all tagging work for the current batch has finished
- all required alignment rows for the current batch have been confirmed

Once both conditions are true, the current review flow starts unchanged, followed by the existing execution pipeline.

## RK Candidate Discovery Rules

### Source Priority

Use the first usable source root in this order:

1. `temp_path`
2. `dut_root`

`temp_path` is expected to mirror `/mnt/nvme/CapturedData` and may be used fully offline.

### Directory Inclusion

Scan only first-level RK subdirectories whose names match:

- `^\d+$`
- `^\d+x$`

Examples:

- valid name shape: `32`, `32x`
- ignored: `abc`, `32_tmp`, nested subfolders

### Validity Check

For each candidate folder:

- if a `.jpg` or `.jpeg` file exists, the candidate is valid
- otherwise the candidate is bad and excluded

Bad directories must be surfaced in the alignment log, for example:

- `32x: missing preview jpeg, excluded from alignment`
- `45: missing preview jpeg, excluded from alignment`

### Ordering

Sort candidates by:

1. numeric part ascending
2. plain numeric before `x` variant when numeric part is equal

Example ordering:

- `31`
- `31x`
- `32`
- `32x`
- `33`

`32` and `32x` are distinct candidates if both contain jpeg previews.

## DJI Preview Generation

### Preview Inputs

Each alignment case uses the DJI `normal` and `night` videos already loaded from the workbook row.

### Preview Output

Generate preview strips under a local cache directory rooted at:

- `artifacts/alignment_previews/<case_id>/`

For each case:

- `normal/` contains evenly sampled preview frames from the normal video
- `night/` contains evenly sampled preview frames from the night video

### Sampling Rule

Use ffmpeg to extract up to 30 evenly distributed frames across the full video duration.

Behavior:

- long video: 30 evenly distributed preview frames
- short video: fewer frames if the source cannot provide 30 distinct samples

This keeps preview generation stable across different clip lengths and avoids over-biasing the opening segment.

### RK Preview Output

RK preview generation does not create derived images. The alignment page reads the existing jpeg directly from the currently selected RK candidate folder.

## Workbook Data Model Changes

### Existing `获取列表` Handling

The current `打标` flow must continue to load DJI rows even when `RK_raw` is blank.

This requires loosening the early assumption that `CaseManifest.raw_path` is already meaningful at tagging time. During tagging and pre-review alignment:

- unresolved rows may carry an empty or placeholder RK path in memory
- the real RK folder name is injected into the manifest only after alignment confirmation

No downstream stage may consume unresolved manifests. The review gate prevents that.

### Shared Writeback Target

There must be one shared batch writeback workbook path:

- source `.xlsx`: write back directly
- source `.xlsm`: create or reuse sibling `.xlsx` copy and write everything there

Both tagging-side workbook writes and alignment-side `RK_raw` writes use the same resolved path.

### `RK_raw` Writeback Format

Alignment confirmation writes only the raw folder name into `获取列表.RK_raw`, for example:

- `32`
- `32x`

This stage does not write server paths or case root paths.

## Alignment State Model

Introduce a batch-level alignment state that lives outside the review and execution pipeline.

Recommended logical entities:

- `RkCandidate`
  - folder name
  - numeric index
  - x-suffix flag
  - preview jpeg path
  - source root path
- `AlignmentCase`
  - workbook row index
  - `case_id`
  - DJI normal path
  - DJI night path
  - current alignment status
  - currently selected candidate index
  - confirmed candidate, if any
- `AlignmentBatchState`
  - all valid candidates
  - bad directory log entries
  - pending case list
  - rewrite case list
  - confirmed count
  - blocked flag

These do not need to be persisted as separate files. They only need to exist in memory for the loaded batch and drive UI state plus workbook writeback.

## Default Cursor and Consumption Rules

### Prefix-Based Cursor Reconstruction

Default alignment is not guessed per row in isolation. It is reconstructed from the workbook prefix.

Algorithm:

1. Walk the workbook rows in DJI order.
2. For each earlier row with non-empty `RK_raw`, map that folder name to a valid RK candidate.
3. Treat that candidate as consumed and advance the cursor.
4. For the next row whose `RK_raw` is blank, default to the current cursor position.

This preserves continuity even when alignment resumes mid-batch.

If an earlier non-empty `RK_raw` cannot be mapped to a valid current candidate pool entry:

- mark the alignment batch blocked
- emit a log entry naming the problematic workbook row and RK value
- keep review locked until the operator fixes or clears that historical value through the rewrite flow

### Confirming a Pending Case

When the operator confirms a candidate for a pending case:

1. write the folder name into workbook `RK_raw`
2. update the in-memory alignment state
3. update the corresponding manifest `raw_path`
4. mark the candidate consumed
5. advance later pending defaults from the next candidate

### Clearing a Confirmed Case

Clearing a case:

- removes the workbook `RK_raw` value for that case from the writeback target
- marks the case pending again
- decreases the batch confirmed count
- recomputes the cursor/defaults for later pending cases
- closes the batch review gate if it was previously open

## Rewrite Rules

The rewrite entry point loads already aligned cases explicitly selected for rework.

When the operator proposes a new RK candidate for an earlier case:

- if the new assignment preserves strict monotonic unique ordering across later already-confirmed cases, allow the overwrite
- if not, reject it with a clear message such as:
  - `Changing case_A_0120 to RK 34 would conflict with later confirmed cases. Clear later aligned cases first.`

The system must not silently reassign later cases.

## Main Window Coordination

### Tab Layout

The main window becomes:

1. `打标`
2. `对齐`
3. `审核`
4. `执行队列`

`审核` and `执行队列` remain disabled at load time.

### New Coordination Responsibilities

`MainWindow` becomes the batch coordinator for the pre-review stage and owns:

- current shared workbook writeback path
- batch tagging completion status
- batch alignment completion status
- pending review payload

### Review Gate

Add a single gate function conceptually equivalent to:

- `maybe_enter_review()`

It enables review only when:

- tagging finished for the batch
- alignment confirmed count equals required alignment total
- alignment batch is not blocked by missing valid candidates or unresolved preview/write failures

Until then:

- tagging completion stores results but does not call `ReviewTab.load_cases(...)`
- alignment completion updates state but does not call `ReviewTab.load_cases(...)`

Once the gate opens:

- manifests have resolved `raw_path`
- current review page loads exactly once for the batch
- downstream review/execution behavior stays unchanged

## UI Design for Alignment Tab

### Layout

Use a two-pane layout:

- left: alignment queue
- right: current case detail and preview panel

### Left Pane

Show pending cases only:

- `case_id`
- DJI normal filename
- status

Statuses:

- `待对齐`
- `已确认`
- `重写中`
- `预览生成失败`

Also provide:

- a dedicated action to load already aligned cases for rewrite

### Right Pane

Show:

- current case header
- current RK candidate label
- previous/next RK buttons
- DJI normal preview strip
- DJI night preview strip
- RK jpeg preview
- confirm / clear / save-and-next actions
- persistent alignment log panel

## Logging and Error Handling

The alignment tab owns a visible log panel. At minimum it records:

- bad RK directories excluded due to missing jpeg
- preview generation failures
- candidate exhaustion
- successful confirmations
- rewrites
- blocked rewrite attempts

Examples:

- `32x missing preview jpeg, excluded`
- `case_A_0123 normal preview generation failed`
- `Remaining valid RK candidates are insufficient for pending alignment cases`
- `case_A_0120 aligned to RK 33`
- `case_A_0120 rewrite blocked: later confirmed cases would conflict`

## Failure Semantics

### Candidate Exhaustion

If valid RK candidates are fewer than required unresolved cases:

- mark alignment batch blocked
- keep review gate closed
- show a persistent error in the alignment log

### Preview Failure

If a DJI preview strip fails to generate:

- mark only that case as preview-failed
- allow explicit retry from the alignment tab
- do not count the case as aligned

### Workbook Write Failure

If writing `RK_raw` fails:

- keep the current case unconfirmed
- do not consume the candidate
- keep later cursor/defaults unchanged
- show the error in the status area and alignment log

## File and Module Impact

### New Files

- `video_tagging_assistant/rk_alignment_service.py`
  - RK candidate discovery
  - bad directory detection
  - ordering
  - prefix cursor reconstruction
  - safe rewrite validation
- `video_tagging_assistant/alignment_preview.py`
  - DJI preview strip generation
  - preview cache path handling
- `video_tagging_assistant/gui/alignment_tab.py`
  - dedicated alignment UI

### Modified Files

- `video_tagging_assistant/gui/main_window.py`
  - add alignment tab
  - hold pre-review batch state
  - gate review entry on tagging + alignment completion
- `video_tagging_assistant/gui/tagging_tab.py`
  - emit workbook/batch load context needed by the alignment tab
  - continue allowing tagging when `RK_raw` is blank
- `video_tagging_assistant/excel_workbook.py`
  - load pending alignment rows
  - load rewrite rows
  - write/clear `RK_raw`
  - validate rewrite monotonicity
- `docs/config-reference.md`
  - document alignment behavior using existing `temp_path` and `dut_root`
  - document preview cache location if surfaced to operators

### Existing Files Intentionally Kept Stable

- `video_tagging_assistant/gui/review_tab.py`
- `video_tagging_assistant/gui/execution_tab.py`
- `video_tagging_assistant/gui/execution_worker.py`
- `video_tagging_assistant/case_ingest_orchestrator.py`

These should not absorb alignment-specific complexity beyond consuming manifests whose `raw_path` is already resolved before review begins.

## Testing Strategy

### Unit Tests

Add pure logic coverage for:

- candidate scan and bad-directory filtering
- candidate ordering (`32`, `32x`, `33`)
- prefix cursor reconstruction from historical `RK_raw`
- confirm/clear cursor updates
- rewrite conflict detection

### Workbook Tests

Cover:

- load only blank `RK_raw` rows into pending alignment
- `.xlsm -> .xlsx` writeback reuse
- write `RK_raw`
- clear `RK_raw`
- reject unsafe rewrite

### GUI Tests

Cover:

- alignment tab queue population
- bad-directory log rendering
- RK candidate switching
- confirmation updates status and writeback
- clear returns case to pending
- rewrite entry path loads already aligned cases without polluting the normal pending queue

### Main Window Tests

Cover:

- tagging finished only -> review stays locked
- alignment finished only -> review stays locked
- both finished -> review opens
- alignment clear after completion -> review gate closes again

## Recommended Implementation Order

1. Add workbook read/write helpers for pending alignment and `RK_raw` updates.
2. Add pure RK alignment service and unit tests.
3. Add DJI preview generation helper and cache behavior.
4. Add `AlignmentTab` with the minimal pending-case workflow.
5. Wire `MainWindow` gating so review waits for both subsystems.
6. Add rewrite entry and monotonic conflict blocking.
7. Document operator-facing behavior and logs.

## Why This Design

This design keeps the new complexity isolated to the stage before review:

- tagging can proceed immediately on valid DJI input
- alignment becomes a dedicated, operator-driven tab instead of leaking into review
- review/execution remain mostly unchanged
- workbook writeback stays centralized and consistent

The result matches the product requirement without forcing a redesign of the already working review and execution pipeline.
