from __future__ import annotations

from typing import Any

SUPPORTED_CORE_WORKFLOWS: frozenset[str] = frozenset({
    "auto_preview", "project_status", "source_onboarding", "plan_update",
    "small_project_patch", "docs_update", "git_commit",
    "git_restore_file", "git_revert", "git_undo_version", "agent_dispatch",
    "prompt_to_plan", "thin_governed_loop_preview",
})


def normalize_workflow_name(value: Any) -> str:
    if isinstance(value, str):
        return value.strip().lower()
    return ""


def is_supported_core_workflow(name: str) -> bool:
    return name in SUPPORTED_CORE_WORKFLOWS
