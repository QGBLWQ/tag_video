import json
from pathlib import Path
from typing import Dict, Set

REQUIRED_TOP_LEVEL_KEYS: Set[str] = {
    "input_dir",
    "output_dir",
    "compression",
    "provider",
    "prompt_template",
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
