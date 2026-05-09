"""RK 与 DJI 序列对齐服务。

负责扫描 RK 候选目录、维护对齐批次状态，以及在人工确认时
校验“严格递增且一一对应”的业务约束。
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Mapping, Sequence, Set, Tuple

from video_tagging_assistant.pipeline_models import CaseManifest


_RK_DIR_PATTERN = re.compile(r"^\d+x?$")


def _translate_adb_stderr(stderr: str) -> str:
    text = stderr.lower()
    for keyword, chinese in [
        ("device not found", "设备未连接，请检查 USB 线缆并确认 adb devices 可见"),
        ("no devices", "设备未连接，请检查 USB 线缆并确认 adb devices 可见"),
        ("permission denied", "权限不足，请在设备端执行 adb root"),
        ("no such file or directory", "远端路径不存在，请检查 dut_root 配置"),
        ("timeout", "设备响应超时，请重启 adb server（adb kill-server）"),
        ("timed out", "设备响应超时，请重启 adb server（adb kill-server）"),
        ("offline", "设备离线，请重新插拔 USB 并等待设备上线"),
    ]:
        if keyword in text:
            return f"{chinese}（原始错误: {stderr.strip()}）"
    return f"adb 命令失败: {stderr.strip()}"


@dataclass(frozen=True)
class RkCandidate:
    """一个可用于对齐的 RK 候选目录。"""

    folder_name: str
    folder_path: Path
    numeric_value: int
    has_x_suffix: bool
    preview_path: Path | None = None
    file_count: int = 0


@dataclass
class AlignmentViewCase:
    """对齐页中展示的一条 case 视图状态。"""

    manifest: CaseManifest
    rk_raw_value: str
    selected_candidate_index: int
    status: str


@dataclass
class AlignmentBatchState:
    """整批对齐任务的完整运行状态。"""

    manifests: list[CaseManifest]
    candidates: list[RkCandidate]
    bad_directory_logs: list[str]
    rk_raw_by_row: Dict[int, str]
    pending_cases: list[AlignmentViewCase]
    aligned_cases: list[AlignmentViewCase]
    blocked_messages: list[str]
    rewrite_row_indices: Set[int] = field(default_factory=set)
    base_raw_paths: Dict[int, Path] = field(default_factory=dict)


def scan_rk_candidates(temp_root: str, dut_root: str, adb_exe: str = "adb") -> Tuple[Path | None, list[RkCandidate], list[str]]:
    """扫描 temp_root / dut_root，返回可用 RK 候选和日志。"""
    temp_path = _optional_root_path(temp_root)
    dut_path = _optional_root_path(dut_root)
    normalized_dut_root = str(dut_root or "").strip()
    dut_is_remote = dut_path is not None and normalized_dut_root and (not dut_path.exists() or not dut_path.is_dir())

    temp_candidates, temp_logs = _scan_candidate_root(temp_path)
    if temp_candidates:
        return temp_path, temp_candidates, temp_logs

    if dut_path is not None and dut_path.exists() and dut_path.is_dir():
        dut_candidates, dut_logs = _scan_candidate_root(dut_path)
    elif dut_is_remote:
        dut_candidates, dut_logs = _scan_remote_candidate_root(normalized_dut_root, adb_exe)
    else:
        dut_candidates, dut_logs = [], []

    if dut_is_remote:
        return dut_path, dut_candidates, temp_logs + dut_logs

    if dut_path is not None:
        logs = temp_logs + dut_logs
        if not dut_candidates:
            logs.append(_empty_candidate_summary(dut_path))
        return dut_path, dut_candidates, logs

    if temp_path is not None and not temp_candidates:
        return temp_path, temp_candidates, temp_logs + [_empty_candidate_summary(temp_path)]
    return temp_path, temp_candidates, temp_logs


def build_alignment_batch_state(
    manifests: Sequence[CaseManifest],
    rk_raw_by_row: Mapping[int, str],
    candidates: Sequence[RkCandidate],
    bad_directory_logs: Sequence[str],
) -> AlignmentBatchState:
    """基于 manifest、已写入的 RK_raw 与候选目录构建初始对齐状态。"""
    ordered_manifests = sorted(manifests, key=lambda manifest: manifest.row_index)
    base_raw_paths = {manifest.row_index: Path(manifest.raw_path) for manifest in ordered_manifests}
    normalized_rk_raw = {int(row_index): _normalize_rk_raw(value) for row_index, value in rk_raw_by_row.items()}
    for manifest in ordered_manifests:
        normalized_rk_raw.setdefault(manifest.row_index, "")
    sorted_candidates = sorted(candidates, key=_candidate_sort_key)
    return _recompute_state(
        manifests=ordered_manifests,
        base_raw_paths=base_raw_paths,
        rk_raw_by_row=normalized_rk_raw,
        candidates=sorted_candidates,
        bad_directory_logs=list(bad_directory_logs),
        rewrite_row_indices=set(),
    )


def confirm_alignment(state: AlignmentBatchState, row_index: int, candidate_name: str) -> AlignmentBatchState:
    """确认某一行与指定 RK 候选对齐，并返回新的批次状态。"""
    candidate_indices = _candidate_index_by_name(state.candidates)
    candidate_index = candidate_indices.get(candidate_name)
    if candidate_index is None:
        raise ValueError(f"RK candidate {candidate_name} does not exist")
    _manifest_by_row(state.manifests, row_index)
    _validate_confirm_alignment(state, row_index, candidate_name, candidate_index, candidate_indices)
    updated_rk_raw = dict(state.rk_raw_by_row)
    updated_rk_raw[row_index] = candidate_name
    updated_rewrite_rows = set(state.rewrite_row_indices)
    updated_rewrite_rows.discard(row_index)
    return _recompute_state(
        manifests=state.manifests,
        base_raw_paths=state.base_raw_paths,
        rk_raw_by_row=updated_rk_raw,
        candidates=state.candidates,
        bad_directory_logs=state.bad_directory_logs,
        rewrite_row_indices=updated_rewrite_rows,
    )


def clear_alignment(state: AlignmentBatchState, row_index: int) -> AlignmentBatchState:
    """清空指定行的对齐结果，并重新计算批次状态。"""
    _manifest_by_row(state.manifests, row_index)
    updated_rk_raw = dict(state.rk_raw_by_row)
    updated_rk_raw[row_index] = ""
    return _recompute_state(
        manifests=state.manifests,
        base_raw_paths=state.base_raw_paths,
        rk_raw_by_row=updated_rk_raw,
        candidates=state.candidates,
        bad_directory_logs=state.bad_directory_logs,
        rewrite_row_indices=set(state.rewrite_row_indices),
    )


def enable_rewrite_rows(state: AlignmentBatchState, row_indices: list[int]) -> AlignmentBatchState:
    """把指定已对齐行切换为“可重写”状态。"""
    aligned_rows = {
        row_index
        for row_index in row_indices
        if _normalize_rk_raw(state.rk_raw_by_row.get(row_index, ""))
    }
    return _recompute_state(
        manifests=state.manifests,
        base_raw_paths=state.base_raw_paths,
        rk_raw_by_row=state.rk_raw_by_row,
        candidates=state.candidates,
        bad_directory_logs=state.bad_directory_logs,
        rewrite_row_indices=aligned_rows,
    )


def _scan_candidate_root(root: Path | None) -> Tuple[list[RkCandidate], list[str]]:
    """扫描本地 RK 根目录，收集包含 jpg/jpeg 预览图的候选目录。"""
    if root is None or not root.exists() or not root.is_dir():
        return [], []

    candidates = []
    bad_logs = []
    for child in root.iterdir():
        if not child.is_dir() or not _RK_DIR_PATTERN.fullmatch(child.name):
            continue
        preview_path = _find_preview_path(child)
        if preview_path is None:
            bad_logs.append(f"RK candidate {child.name} under {root} is missing a preview jpg/jpeg file")
            continue
        has_x_suffix = child.name.endswith("x")
        candidates.append(
            RkCandidate(
                folder_name=child.name,
                folder_path=child,
                preview_path=preview_path,
                numeric_value=int(_strip_x_suffix(child.name)),
                has_x_suffix=has_x_suffix,
                file_count=sum(1 for f in child.iterdir() if f.is_file()),
            )
        )
    candidates.sort(key=_candidate_sort_key)
    return candidates, bad_logs


def _find_preview_path(folder_path: Path) -> Path | None:
    """在单个 RK 目录下寻找第一张可用的 jpg/jpeg 预览图。"""
    for child in sorted(folder_path.iterdir(), key=lambda path: path.name.lower()):
        if child.is_file() and child.suffix.lower() in {".jpg", ".jpeg"}:
            return child
    return None


def _scan_remote_candidate_root(root_value: str, adb_exe: str) -> Tuple[list[RkCandidate], list[str]]:
    """通过 adb 扫描远端 RK 候选目录（仅列目录，不拉取预览图）。

    预览图由 AlignmentPreviewWorker 异步拉取以保持 UI 响应。
    """
    entries = _adb_find(adb_exe, root_value, ["-mindepth", "1", "-maxdepth", "1", "-type", "d", "-print"])
    candidates = []
    bad_logs = []
    matched_directory_names = [Path(entry).name for entry in entries if _RK_DIR_PATTERN.fullmatch(Path(entry).name)]

    for folder_name in matched_directory_names:
        has_x_suffix = folder_name.endswith("x")
        candidates.append(
            RkCandidate(
                folder_name=folder_name,
                folder_path=Path(root_value) / folder_name,
                numeric_value=int(_strip_x_suffix(folder_name)),
                has_x_suffix=has_x_suffix,
                preview_path=None,
            )
        )

    bad_logs.append(
        f"RK scan root {root_value}: found {len(matched_directory_names)} numeric directories, "
        f"{len(candidates)} RK candidates (previews pending)"
    )
    candidates.sort(key=_candidate_sort_key)
    return candidates, bad_logs


def _adb_find(adb_exe: str, target_path: str, extra_args: list[str]) -> list[str]:
    """调用 `adb shell find` 并返回非空输出行。"""
    try:
        result = subprocess.run(
            [adb_exe, "shell", "find", target_path, *extra_args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"adb shell find {target_path} 超时，请检查设备连接状态") from None
    if result.returncode != 0:
        stderr_text = (result.stderr or "").strip()
        stdout_text = (result.stdout or "").strip()
        raw = stderr_text or stdout_text or f"adb shell find failed for {target_path}"
        raise RuntimeError(_translate_adb_stderr(raw))
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def find_remote_preview_name(adb_exe: str, root_value: str, folder_name: str) -> str | None:
    """在远端 RK 目录内寻找第一张可用预览图文件名。"""
    for child_name in sorted(
        _adb_find(adb_exe, f"{root_value}/{folder_name}", ["-mindepth", "1", "-maxdepth", "1", "-type", "f", "-print"]),
        key=str.lower,
    ):
        suffix = Path(child_name).suffix.lower()
        if suffix in {".jpg", ".jpeg"}:
            return Path(child_name).name
    return None


def pull_remote_preview(adb_exe: str, root_value: str, folder_name: str, preview_name: str) -> Path:
    """把远端 RK 预览图拉到本地缓存目录，并返回本地路径。"""
    cache_dir = _remote_preview_cache_dir(root_value, folder_name)
    cache_dir.mkdir(parents=True, exist_ok=True)
    local_preview_path = cache_dir / preview_name

    remote_preview_path = f"{root_value}/{folder_name}/{preview_name}"
    subprocess.run(
        [adb_exe, "pull", remote_preview_path, str(local_preview_path)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    return local_preview_path


def _remote_preview_cache_dir(root_value: str, folder_name: str) -> Path:
    """根据远端根目录和文件夹名生成稳定的本地缓存目录。"""
    root_namespace = hashlib.sha1(_normalize_remote_root(root_value).encode("utf-8")).hexdigest()[:12]
    return Path("artifacts") / "alignment_rk_previews" / root_namespace / folder_name


def _matched_candidate_directory_count(root: object) -> int:
    """统计本地根目录下命中 RK 命名规则的子目录数量。"""
    if not isinstance(root, Path):
        return 0
    if root is None or not root.exists() or not root.is_dir():
        return 0
    return sum(1 for child in root.iterdir() if child.is_dir() and _RK_DIR_PATTERN.fullmatch(child.name))


def _empty_candidate_summary(root: object) -> str:
    """生成“未发现有效 RK 候选”摘要日志。"""
    matched_directory_count = _matched_candidate_directory_count(root)
    return f"RK scan root {root}: found {matched_directory_count} numeric directories, 0 valid RK candidates"


def _normalize_remote_root(root_value: str) -> str:
    """规范化远端根目录字符串，去掉尾部多余斜杠。"""
    normalized = str(root_value or "").strip()
    while normalized.endswith("/") and normalized != "/":
        normalized = normalized[:-1]
    return normalized


def _recompute_state(
    manifests: Sequence[CaseManifest],
    base_raw_paths: Mapping[int, Path],
    rk_raw_by_row: Mapping[int, str],
    candidates: Sequence[RkCandidate],
    bad_directory_logs: Sequence[str],
    rewrite_row_indices: Set[int],
) -> AlignmentBatchState:
    """根据当前 RK_raw 写回值重新推导待对齐、已对齐与阻塞状态。"""
    candidate_indices = _candidate_index_by_name(candidates)
    blocked_messages = []
    pending_cases = []
    aligned_cases = []
    cursor = 0

    for manifest in manifests:
        manifest.raw_path = Path(base_raw_paths[manifest.row_index])

    manifest_row_indices = {manifest.row_index for manifest in manifests}
    filtered_rewrite_rows = {row_index for row_index in rewrite_row_indices if row_index in manifest_row_indices}

    normalized_rk_raw = dict(rk_raw_by_row)
    for manifest in manifests:
        row_index = manifest.row_index
        rk_raw_value = _normalize_rk_raw(normalized_rk_raw.get(row_index, ""))
        normalized_rk_raw[row_index] = rk_raw_value
        if rk_raw_value:
            candidate_index = candidate_indices.get(rk_raw_value)
            if candidate_index is None:
                blocked_messages.append(
                    f"row {row_index} has RK_raw={rk_raw_value} but no valid RK candidate matches it"
                )
                manifest.raw_path = Path(rk_raw_value)
                aligned_cases.append(
                    AlignmentViewCase(
                        manifest=manifest,
                        rk_raw_value=rk_raw_value,
                        selected_candidate_index=-1,
                        status="blocked_aligned",
                    )
                )
                continue
            if candidate_index < cursor:
                blocked_messages.append(
                    f"row {row_index} has RK_raw={rk_raw_value} but it is not strictly after earlier confirmed rows"
                )
            manifest.raw_path = Path(rk_raw_value)
            aligned_cases.append(
                AlignmentViewCase(
                    manifest=manifest,
                    rk_raw_value=rk_raw_value,
                    selected_candidate_index=candidate_index,
                    status=_aligned_status(row_index, filtered_rewrite_rows),
                )
            )
            if candidate_index >= cursor:
                cursor = candidate_index + 1
            continue

        selected_candidate_index = cursor if cursor < len(candidates) else -1
        pending_cases.append(
            AlignmentViewCase(
                manifest=manifest,
                rk_raw_value="",
                selected_candidate_index=selected_candidate_index,
                status=_pending_status(row_index, filtered_rewrite_rows),
            )
        )
        if selected_candidate_index == -1:
            blocked_messages.append(f"row {row_index} has no remaining RK candidates to assign")
            continue
        cursor = selected_candidate_index + 1

    return AlignmentBatchState(
        manifests=list(manifests),
        candidates=list(candidates),
        bad_directory_logs=list(bad_directory_logs),
        rk_raw_by_row=normalized_rk_raw,
        pending_cases=pending_cases,
        aligned_cases=aligned_cases,
        blocked_messages=blocked_messages,
        rewrite_row_indices=filtered_rewrite_rows,
        base_raw_paths=dict(base_raw_paths),
    )


def _candidate_sort_key(candidate: RkCandidate) -> tuple[int, int, str]:
    """按数字序、x 后缀、原始文件夹名排序 RK 候选。"""
    return candidate.numeric_value, 1 if candidate.has_x_suffix else 0, candidate.folder_name


def _candidate_index_by_name(candidates: Sequence[RkCandidate]) -> Dict[str, int]:
    """构造 `folder_name -> candidate_index` 映射。"""
    return {candidate.folder_name: index for index, candidate in enumerate(candidates)}


def _validate_confirm_alignment(
    state: AlignmentBatchState,
    row_index: int,
    candidate_name: str,
    candidate_index: int,
    candidate_indices: Mapping[str, int],
) -> None:
    """校验新确认的 RK 候选不会破坏整体严格递增约束。"""
    earlier_index, later_index = _confirmed_neighbor_bounds(state, row_index, candidate_indices)
    if earlier_index is not None and candidate_index <= earlier_index:
        raise ValueError(
            f"row {row_index} cannot be {_confirm_verb(state, row_index)} to RK {candidate_name} "
            f"because it is not strictly after earlier confirmed rows"
        )
    if later_index is not None and candidate_index >= later_index:
        raise ValueError(
            f"row {row_index} cannot be {_confirm_verb(state, row_index)} to RK {candidate_name} "
            f"because later confirmed rows would no longer be strictly increasing"
        )


def _confirmed_neighbor_bounds(
    state: AlignmentBatchState,
    row_index: int,
    candidate_indices: Mapping[str, int],
) -> Tuple[int | None, int | None]:
    """计算目标行前后最近已确认对齐项的候选索引边界。"""
    earlier_index = None
    later_index = None
    ordered_manifests = sorted(state.manifests, key=lambda manifest: manifest.row_index)

    for manifest in ordered_manifests:
        current_row_index = manifest.row_index
        if current_row_index == row_index:
            continue
        rk_raw_value = _normalize_rk_raw(state.rk_raw_by_row.get(current_row_index, ""))
        if not rk_raw_value:
            continue
        current_candidate_index = candidate_indices.get(rk_raw_value)
        if current_candidate_index is None:
            continue
        if current_row_index < row_index:
            if earlier_index is None:
                earlier_index = current_candidate_index
            else:
                earlier_index = max(earlier_index, current_candidate_index)
            continue
        if later_index is None:
            later_index = current_candidate_index
        else:
            later_index = min(later_index, current_candidate_index)

    return earlier_index, later_index


def _confirm_verb(state: AlignmentBatchState, row_index: int) -> str:
    """根据是否处于重写模式返回日志动词。"""
    if row_index in state.rewrite_row_indices:
        return "rewritten"
    return "confirmed"


def _manifest_by_row(manifests: Sequence[CaseManifest], row_index: int) -> CaseManifest:
    """按 Excel 行号定位对应的 manifest。"""
    for manifest in manifests:
        if manifest.row_index == row_index:
            return manifest
    raise ValueError(f"row {row_index} does not exist in the alignment batch")


def _normalize_rk_raw(value: object) -> str:
    """把 RK_raw 单元格值规范化为去空白字符串。"""
    return str(value or "").strip()


def _strip_x_suffix(value: str) -> str:
    """去掉 RK 候选目录名尾部的 `x` 标记。"""
    return value[:-1] if value.endswith("x") else value


def _optional_root_path(root_value: str) -> Path | None:
    """把可选根目录字符串转换为 `Path`，空值返回 None。"""
    normalized = str(root_value or "").strip()
    if not normalized:
        return None
    return Path(normalized)


def _aligned_status(row_index: int, rewrite_row_indices: Set[int]) -> str:
    """返回已对齐行在 UI 中使用的状态文案。"""
    if row_index in rewrite_row_indices:
        return "rewrite_aligned"
    return "aligned"


def _pending_status(row_index: int, rewrite_row_indices: Set[int]) -> str:
    """返回待对齐行在 UI 中使用的状态文案。"""
    if row_index in rewrite_row_indices:
        return "rewrite_pending"
    return "pending"


__all__ = [
    "AlignmentBatchState",
    "AlignmentViewCase",
    "RkCandidate",
    "build_alignment_batch_state",
    "clear_alignment",
    "confirm_alignment",
    "enable_rewrite_rows",
    "find_remote_preview_name",
    "pull_remote_preview",
    "scan_rk_candidates",
]
