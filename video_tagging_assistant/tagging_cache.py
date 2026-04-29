import json
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, Optional

from video_tagging_assistant.pipeline_models import CaseManifest


def build_source_fingerprint(manifest: CaseManifest) -> str:
    payload = {
        "case_id": manifest.case_id,
        "created_date": manifest.created_date,
        "mode": manifest.mode,
        "raw_path": str(manifest.raw_path),
        "vs_normal_path": str(manifest.vs_normal_path),
        "vs_night_path": str(manifest.vs_night_path),
        "remark": manifest.remark,
        "labels": manifest.labels,
    }
    return sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def save_cached_result(cache_root: Path, manifest: CaseManifest, payload: Dict[str, Any]) -> None:
    case_dir = cache_root / manifest.case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    fingerprint = build_source_fingerprint(manifest)
    (case_dir / "manifest.json").write_text(
        json.dumps({"fingerprint": fingerprint}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (case_dir / "tagging_result.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_cached_result(cache_root: Path, manifest: CaseManifest) -> Optional[Dict[str, Any]]:
    case_dir = cache_root / manifest.case_id
    manifest_path = case_dir / "manifest.json"
    result_path = case_dir / "tagging_result.json"
    if not manifest_path.exists() or not result_path.exists():
        return None
    manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest_payload.get("fingerprint") != build_source_fingerprint(manifest):
        return None
    return json.loads(result_path.read_text(encoding="utf-8"))
