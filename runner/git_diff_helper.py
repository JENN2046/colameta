import subprocess
from typing import Iterable

from runner.runner_paths import is_project_runner_path


def normalize_repo_path(path: str) -> str:
    cleaned = (path or "").strip().replace("\\", "/")
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    if cleaned.startswith("/"):
        cleaned = cleaned.lstrip("/")
    return cleaned


def is_root_runner_path(path: str) -> bool:
    normalized = normalize_repo_path(path)
    return is_project_runner_path(normalized)


def sort_unique_repo_paths(paths: Iterable[str] | None) -> list[str]:
    if not paths:
        return []
    return sorted({
        normalized
        for normalized in (normalize_repo_path(path) for path in paths)
        if normalized
    })


def filter_business_diff_paths(paths: Iterable[str] | None) -> list[str]:
    return [
        path
        for path in sort_unique_repo_paths(paths)
        if not is_root_runner_path(path)
    ]


def collect_git_diff_name_paths(
    project_root: str,
    *,
    timeout_seconds: int = 10,
) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only"],
            cwd=project_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
        )
        if result.returncode != 0:
            return []
        return sort_unique_repo_paths((result.stdout or "").splitlines())
    except Exception:
        return []


def collect_business_git_diff_name_paths(
    project_root: str,
    *,
    timeout_seconds: int = 10,
) -> list[str]:
    return filter_business_diff_paths(
        collect_git_diff_name_paths(project_root, timeout_seconds=timeout_seconds)
    )
