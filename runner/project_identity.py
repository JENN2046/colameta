import json
import os
from pathlib import Path
from typing import Any

from runner._internal_utils import run_git as _run_git_base
from runner.runner_paths import resolve_project_runner_plan_path


def _run_git(args: list[str], cwd: str, timeout: int = 5) -> str | None:
    rc, stdout, _ = _run_git_base(args, cwd, timeout=timeout)
    if rc != 0:
        return None
    return stdout.strip()


def build_project_identity(project_root: str) -> dict[str, Any]:
    project_basename = os.path.basename(project_root)

    plan_project_name: str | None = None
    plan_file = resolve_project_runner_plan_path(project_root)
    if os.path.isfile(plan_file):
        try:
            data = json.loads(Path(plan_file).read_text(encoding="utf-8"))
            name = data.get("project_name")
            if isinstance(name, str) and name.strip():
                plan_project_name = name.strip()
        except Exception:
            pass

    project_name = plan_project_name or project_basename

    git_branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], project_root)
    git_head = _run_git(["rev-parse", "HEAD"], project_root)
    git_head_short = git_head[:7] if git_head else None
    dirty_raw = _run_git(["status", "--short"], project_root)
    git_dirty: bool | None = None
    if dirty_raw is not None:
        git_dirty = bool(dirty_raw.strip())

    branch_part = f"@{git_branch}" if git_branch else ""
    mcp_display_hint = f"Project:{project_name}{branch_part}"

    return {
        "project_root": project_root,
        "project_name": project_name,
        "project_basename": project_basename,
        "plan_project_name": plan_project_name,
        "git_branch": git_branch,
        "git_head": git_head,
        "git_head_short": git_head_short,
        "git_dirty": git_dirty,
        "mcp_display_hint": mcp_display_hint,
    }
