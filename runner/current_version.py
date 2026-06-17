import json
import os
from typing import Any

from runner.runner_paths import resolve_project_runner_path


def load_current_version(project_root: str) -> str | None:
    try:
        state_file = resolve_project_runner_path(project_root, "state.json")
        if not os.path.isfile(state_file):
            return None
        with open(state_file, "r", encoding="utf-8") as handle:
            state: Any = json.load(handle)
        raw = state.get("current_version") if isinstance(state, dict) else None
        return str(raw).strip() if isinstance(raw, str) and raw.strip() else None
    except Exception:
        return None
