from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

from runner.runner_paths import resolve_project_runner_dir
from runner.workspace import ProjectWorkspace


VALID_TARGET_TYPES = frozenset({"mainline"})
VALID_MAINLINE_IDS = frozenset({"main"})


class DevelopmentTargetError(ValueError):
    pass


@dataclass
class DevelopmentTargetRequest:
    target_type: str = "mainline"
    target_id: str = "main"


@dataclass
class ResolvedDevelopmentTarget:
    project_root: str
    workspace_path: str
    runner_dir: str
    runtime_dir: str
    logs_dir: str
    plan_file: str
    state_file: str
    executor_session_manifest_path: str
    current_version: str | None
    current_version_index: int
    current_version_plan: dict[str, Any] | None


def validate_target_request(request: DevelopmentTargetRequest) -> None:
    if request.target_type not in VALID_TARGET_TYPES:
        raise DevelopmentTargetError(
            f"不支持的 target_type: {request.target_type!r}，"
            f"仅支持 {sorted(VALID_TARGET_TYPES)}。"
        )
    if request.target_type == "mainline" and request.target_id not in VALID_MAINLINE_IDS:
        raise DevelopmentTargetError(
            f"mainline 不支持 target_id={request.target_id!r}，"
            f"仅支持 {sorted(VALID_MAINLINE_IDS)}。"
        )


def resolve_mainline_target(
    project_root: str,
    workspace: ProjectWorkspace | None = None,
) -> ResolvedDevelopmentTarget:
    if workspace is None:
        workspace = ProjectWorkspace.from_project_path(project_root)

    plan_file = workspace.plan_file
    state_file = workspace.state_file

    current_version: str | None = None
    current_version_index = -1
    current_version_plan: dict[str, Any] | None = None

    plan_data: dict[str, Any] | None = None
    state_data: dict[str, Any] | None = None

    if os.path.isfile(plan_file):
        try:
            with open(plan_file, "r", encoding="utf-8") as f:
                plan_data = json.load(f)
        except Exception:
            plan_data = None

    if os.path.isfile(state_file):
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                state_data = json.load(f)
        except Exception:
            state_data = None

    if isinstance(state_data, dict):
        raw_version = state_data.get("current_version")
        current_version = raw_version if isinstance(raw_version, str) and raw_version.strip() else None
        try:
            current_version_index = int(state_data.get("current_version_index", -1))
        except (ValueError, TypeError):
            current_version_index = -1

    if isinstance(plan_data, dict):
        plan_versions = plan_data.get("versions", [])
        if isinstance(plan_versions, list) and 0 <= current_version_index < len(plan_versions):
            candidate = plan_versions[current_version_index]
            if isinstance(candidate, dict):
                current_version_plan = candidate

    runner_dir = workspace.runner_dir
    runtime_dir = workspace.runtime_dir
    logs_dir = workspace.logs_dir

    executor_session_manifest_path = os.path.join(runtime_dir, "executor-session.json")

    return ResolvedDevelopmentTarget(
        project_root=workspace.workspace_root,
        workspace_path=workspace.workspace_root,
        runner_dir=runner_dir,
        runtime_dir=runtime_dir,
        logs_dir=logs_dir,
        plan_file=plan_file,
        state_file=state_file,
        executor_session_manifest_path=executor_session_manifest_path,
        current_version=current_version,
        current_version_index=current_version_index,
        current_version_plan=current_version_plan,
    )


def resolve_development_target(
    project_root: str,
    request: DevelopmentTargetRequest | None = None,
    workspace: ProjectWorkspace | None = None,
) -> ResolvedDevelopmentTarget:
    if request is None:
        request = DevelopmentTargetRequest()
    validate_target_request(request)

    if request.target_type == "mainline":
        return resolve_mainline_target(project_root, workspace=workspace)

    raise DevelopmentTargetError(f"不支持的 target_type: {request.target_type!r}。")
