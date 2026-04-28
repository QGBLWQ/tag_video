import json
from pathlib import Path
from typing import Dict, Optional, Set

REQUIRED_TOP_LEVEL_KEYS: Set[str] = {
    "input_dir",
    "output_dir",
    "compression",
    "provider",
    "prompt_template",
}

CASE_INGEST_REQUIRED_KEYS: Set[str] = {
    "pull_bat",
    "move_bat",
    "server_root",
}

CASE_INGEST_DEFAULTS = {
    "skip_upload": False,
    "upload_workers": 1,
}


def load_config(config_path: Path) -> Dict:
    config_path = Path(config_path)
    data = json.loads(config_path.read_text(encoding="utf-8"))
    missing = REQUIRED_TOP_LEVEL_KEYS - set(data)
    if missing:
        missing_list = ", ".join(sorted(missing))
        raise ValueError(f"Missing config keys: {missing_list}")

    if "case_ingest" in data:
        case_ingest = dict(CASE_INGEST_DEFAULTS)
        case_ingest.update(data["case_ingest"])
        data["case_ingest"] = case_ingest

    return data


def _resolve_config_path(base_dir: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()


def load_case_ingest_config(
    config_path: Path,
    cli_date: Optional[str] = None,
    today: Optional[str] = None,
) -> Dict:
    config_path = Path(config_path).resolve()
    data = json.loads(config_path.read_text(encoding="utf-8"))
    missing = CASE_INGEST_REQUIRED_KEYS - set(data)
    if missing:
        missing_list = ", ".join(sorted(missing))
        raise ValueError(f"Missing case-ingest config keys: {missing_list}")

    base_dir = config_path.parent
    resolved = dict(CASE_INGEST_DEFAULTS)
    resolved.update(data)
    resolved["pull_bat"] = _resolve_config_path(base_dir, resolved["pull_bat"])
    resolved["move_bat"] = _resolve_config_path(base_dir, resolved["move_bat"])
    resolved["server_root"] = _resolve_config_path(base_dir, resolved["server_root"])

    if not resolved["pull_bat"].exists():
        raise ValueError(f"Resolved pull_bat does not exist: {resolved['pull_bat']}")
    if not resolved["move_bat"].exists():
        raise ValueError(f"Resolved move_bat does not exist: {resolved['move_bat']}")
    if not resolved["server_root"].exists():
        raise ValueError(f"Resolved server_root does not exist: {resolved['server_root']}")

    resolved["date"] = cli_date or resolved.get("date") or today
    return resolved
