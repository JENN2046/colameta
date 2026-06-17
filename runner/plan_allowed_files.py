import json
import os
from pathlib import PurePosixPath
from typing import Any, Callable

from runner.path_glob import match as glob_match


def normalize_repo_relative_path(raw_path: str) -> str | None:
    value = raw_path.strip().replace("\\", "/")
    while value.startswith("./"):
        value = value[2:]
    if not value:
        return None
    pure = PurePosixPath(value)
    if pure.is_absolute():
        return None
    if any(part in ("", ".", "..") for part in pure.parts):
        return None
    return str(pure)


def current_plan_allowed_patterns(project_root: str) -> list[str]:
    try:
        root = os.path.abspath(os.path.expanduser(project_root))
        runner_dir = resolve_project_runner_dir(root)
        plan_file = os.path.join(runner_dir, "plan.json")
        state_file = os.path.join(runner_dir, "state.json")
        if not os.path.isfile(plan_file) or not os.path.isfile(state_file):
            return []

        with open(state_file, "r", encoding="utf-8") as f:
            state_data = json.load(f)
        current_version = state_data.get("current_version") if isinstance(state_data, dict) else None
        if not isinstance(current_version, str) or not current_version.strip():
            return []

        with open(plan_file, "r", encoding="utf-8") as f:
            plan_data = json.load(f)
        versions = plan_data.get("versions") if isinstance(plan_data, dict) else None
        if not isinstance(versions, list):
            return []

        for version_spec in versions:
            if not isinstance(version_spec, dict):
                continue
            if version_spec.get("version") != current_version.strip():
                continue
            allowed_files = version_spec.get("allowed_files")
            if not isinstance(allowed_files, list):
                return []
            patterns: list[str] = []
            for item in allowed_files:
                pattern = normalize_plan_allowed_pattern(item)
                if pattern:
                    patterns.append(pattern)
            return patterns
    except Exception:
        return []
    return []


def is_allowed_by_current_plan(
    project_root: str,
    rel_path: str,
    *,
    deny_predicate: Callable[[str], bool] | None = None,
) -> bool:
    normalized = normalize_repo_relative_path(rel_path)
    if normalized is None:
        return False
    if deny_predicate is not None and deny_predicate(normalized):
        return False
    return any(glob_match(pattern, normalized) for pattern in current_plan_allowed_patterns(project_root))


def normalize_plan_allowed_pattern(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    pattern = value.strip().replace("\\", "/")
    while pattern.startswith("./"):
        pattern = pattern[2:]
    if not pattern or pattern.startswith("/"):
        return None
    if pattern.endswith("/"):
        pattern = pattern.rstrip("/") + "/**"
    parts = PurePosixPath(pattern).parts
    if any(part in ("", ".", "..") for part in parts):
        return None
    return pattern
from runner.runner_paths import resolve_project_runner_dir
