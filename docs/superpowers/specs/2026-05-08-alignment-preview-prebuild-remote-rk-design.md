# RK-DJI Alignment Preview Prebuild and Remote RK Scan Design

## Scope

This document is an incremental design addendum for the existing RK-DJI alignment workflow.

It supersedes the preview-generation and RK-scan portions of:

- `docs/superpowers/specs/2026-05-08-rk-dji-alignment-design.md`

Everything not explicitly changed here remains as defined in the earlier alignment design.

## Background

The current alignment implementation still has two practical gaps:

1. `dut_root=/mnt/nvme/CapturedData` is a DUT-side path, but the GUI process may be running on Windows. Treating that path as a local `Path` makes RK scan return zero candidates even when the DUT contains valid numeric folders.
2. DJI preview generation currently happens lazily when the operator clicks into an alignment case. That blocks the alignment interaction on `ffprobe/ffmpeg`, makes the UI feel stalled, and does not match the existing batch-oriented tagging flow.

The requested behavior is:

- keep RK candidate discovery working when the source is remote on the DUT
- move DJI preview generation earlier into a background batch-preparation phase
- make preview extraction configurable by frame count and fixed frame-skip stride
- keep the GUI responsive while preview generation runs
- surface preparation logs in the alignment page

## Goals

- Fix RK candidate scan so `/mnt/nvme/CapturedData` can be scanned from the Windows GUI through `adb`.
- Prebuild all DJI alignment previews in the background as soon as the batch is loaded.
- Prevent alignment interaction from depending on on-demand `ffprobe/ffmpeg` execution in the UI thread.
- Make preview extraction behavior configurable from `config`.
- Emit preparation progress and failure logs in the alignment UI.

## Non-Goals

- No automatic RK-DJI matching.
- No streaming alignment before previews are ready.
- No RK multi-frame preview generation. RK still uses the single existing jpeg.
- No change to downstream review or execution semantics.
- No attempt to optimize preview generation beyond simple bounded multithreading.

## Confirmed Product Decisions

- Use the previously approved alignment flow and only change the scan and preview-preparation mechanics.
- `temp_path` still has highest priority. It remains a local consumable mirror of `/mnt/nvme/CapturedData`.
- If `temp_path` yields no valid RK candidates, scan `dut_root`.
- If `dut_root` is not a real local directory, treat it as a DUT-side path and scan it through `adb`.
- DJI preview generation starts immediately after batch load, not when the user clicks a case.
- Alignment interaction begins only after the preview-preparation phase for the batch has finished.
- Preview extraction is controlled by fixed frame stepping, not duration-based uniform sampling.
- The two user-requested sampling knobs are configurable:
  - how many preview frames to keep
  - how many source frames to skip after each selected frame
- Multithreaded preview generation is allowed and should be bounded by a configurable worker count.

## User Workflow

### 1. Load Batch

When the operator loads the workbook from the tagging tab, the system now performs three independent setup actions:

1. build the tagging batch exactly as before
2. initialize RK alignment state and candidate discovery
3. start a background DJI preview-preparation job for all alignment cases

The GUI must return control immediately after starting the background job. The main window must remain responsive.

### 2. Preparation Phase

The alignment tab enters a preparation state for the current batch.

During this state:

- the log panel shows RK scan diagnostics and preview-generation progress
- the queue may be visible, but confirm/clear/alignment actions remain disabled
- the user can continue using the tagging tab

Preparation is considered complete only when every alignment case has reached one of these terminal states:

- preview ready
- preview failed

### 3. Alignment Phase

After the preparation phase finishes:

- cases with ready previews become alignable
- cases with failed previews remain visible with failure logs
- alignment confirmation still writes `RK_raw` immediately to the writeback workbook
- the existing monotonic-consumption alignment rules remain unchanged

## RK Candidate Discovery

### Source Priority

RK scan uses this priority:

1. local `temp_path`
2. local `dut_root`, if it exists as a real local directory
3. remote `dut_root` through `adb`, if `dut_root` is configured but not locally accessible

### Remote DUT Scan Rule

When `dut_root` is remote, RK scan must not attempt local `Path.exists()` semantics beyond deciding that the path is not locally usable.

Instead:

- enumerate first-level entries on the DUT through `adb`
- keep only names matching `^\d+x?$`
- inspect each matching directory through `adb`
- accept the candidate only if it contains at least one `.jpg` or `.jpeg`
- pull only the preview jpeg to a local cache directory for UI display

Recommended local cache root:

- `artifacts/alignment_rk_previews/<rk_folder_name>/`

### Remote Scan Logging

The alignment log must record a summary such as:

- `RK scan root /mnt/nvme/CapturedData: found 33 numeric directories, 30 valid RK candidates`

and per-directory exclusions such as:

- `RK candidate 31x under /mnt/nvme/CapturedData is missing a preview jpg/jpeg file`

If `adb` scan itself fails, the error must be surfaced directly in the alignment log and the batch remains blocked.

## DJI Preview Preparation

### Output Layout

Continue using a local cache rooted at:

- `artifacts/alignment_previews/<case_cache_key>/normal/`
- `artifacts/alignment_previews/<case_cache_key>/night/`

The cache key should remain stable for the case identity and source video paths so repeated loads can reuse existing outputs when still valid.

### Config Additions

Add these config entries:

- `alignment_preview_frame_count`
  - integer
  - meaning: maximum number of preview frames to keep for each DJI video
  - recommended default: `30`
- `alignment_preview_skip_frames`
  - integer
  - meaning: after selecting one source frame, skip this many source frames before selecting the next one
  - recommended default: `2`
- `alignment_preview_workers`
  - integer
  - meaning: maximum concurrent DJI preview-generation tasks across the batch
  - recommended default: `2`

If a value is absent, invalid, or less than `1` where not allowed, fall back to the default and log the fallback once.

### Sampling Semantics

Preview extraction uses fixed frame stepping.

Definitions:

- `frame_count = alignment_preview_frame_count`
- `skip_frames = alignment_preview_skip_frames`
- `step = skip_frames + 1`

Frame selection semantics:

- keep source frame `0`
- then keep source frame `step`
- then keep source frame `2 * step`
- continue until `frame_count` frames have been written or the source ends

Example:

- `frame_count=30`
- `skip_frames=2`
- selected source frames are `0, 3, 6, 9, ...`

This replaces the earlier duration-based evenly distributed sampling rule.

### ffprobe/ffmpeg Usage

Preview generation should still use the existing `ffprobe_exe` and `ffmpeg_exe` config entries.

Recommended responsibilities:

- `ffprobe` verifies the video stream can be opened and provides stream metadata for logging
- `ffmpeg` performs frame extraction with a fixed-step frame-selection filter

The implementation should prefer a frame-index-based `ffmpeg` filter rather than duration-derived FPS sampling.

## Background Execution Model

### Worker Structure

Use a dedicated alignment preview background worker owned by the GUI layer.

Recommended shape:

- one PyQt worker thread responsible for lifecycle and signal emission
- inside that worker, a bounded `ThreadPoolExecutor` for per-video preview generation

This keeps all `ffprobe/ffmpeg` work off the UI thread while avoiding a large UI refactor.

### Unit of Parallelism

The simplest useful parallelism unit is one DJI video path.

Each alignment case contributes two preview tasks:

- normal video preview build
- night video preview build

The worker tracks per-case completion and marks a case ready only when both tasks succeed.

### UI Contract

The alignment tab must no longer call `ffprobe/ffmpeg` when the current row changes.

Instead:

- when a case is selected before preparation completes, show a waiting or preparing state
- when previews are ready, load the cached frame images immediately
- when preview generation failed, show the failure state and keep confirm disabled

## Logging

The alignment tab log panel should include:

- RK scan summary
- bad RK directory exclusions
- preview-preparation job start
- per-case preview start
- per-case normal/night source paths
- per-case success summary
- per-case failure summary with executable names and exception text
- final preparation summary

Example final summary:

- `alignment preview prepare complete: 28 cases ready, 2 cases failed`

The log must remain append-only for the current batch so failures can be diagnosed after preparation finishes.

## Failure Handling

### RK Scan Failure

If neither `temp_path` nor local/remote `dut_root` yields valid candidates:

- keep the alignment batch loaded
- show the scan logs
- mark alignment as blocked
- do not unlock review

### Preview Generation Failure

If `ffprobe` or `ffmpeg` cannot be executed, or a source video cannot be read:

- mark only the affected case as preview failed
- log the full source path and executable names
- keep the case non-confirmable
- keep batch review locked until the failed alignment cases are resolved in a later rerun

This preserves the strict gate that every required alignment case must be valid before review.

## Testing Impact

Add or update tests for:

- remote RK candidate scan through `adb` when `dut_root` is not local
- remote RK preview jpeg pull into the local cache
- config-driven fixed-step preview sampling behavior
- config fallback when preview settings are absent or invalid
- background preview preparation not invoking `ffprobe/ffmpeg` from row-selection handlers
- alignment tab disabled confirmation while preparation is running
- alignment tab logs preparation progress and failure messages

## Migration Notes

This addendum changes two earlier assumptions:

1. RK scan is not purely local anymore.
2. DJI preview generation is not click-triggered and not duration-sampled anymore.

Existing user instructions and README content should be updated during implementation so operators know:

- `adb` must be available when `dut_root` points to the DUT
- `ffprobe_exe` and `ffmpeg_exe` must be configured or available in `PATH`
- alignment preview behavior now depends on the new preview config fields
