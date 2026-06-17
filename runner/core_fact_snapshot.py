from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CoreFactSnapshot:
    project_identity: dict[str, Any]
    current_version: str | None
    next_version: str | None
    plan_status: dict[str, Any]
    git_status: dict[str, Any]
    active_preview: dict[str, Any] | None
    active_run: dict[str, Any]
    latest_report: dict[str, Any]
    can_continue: bool
    can_commit: bool
    requires_confirmation: bool
    recommended_next_actions: list[dict[str, Any]]
    blockers: list[str]
    warnings: list[str]
    risk_level: str
    mode: str
    summary: dict[str, Any]
    unreconciled_direct_version_count: int
    unreconciled_direct_versions: list[str]
    has_pending_versions: bool = False
    pending_versions: list[dict] = field(default_factory=list)
    pending_count: int = 0
    next_not_started_version: str | None = None
    partial_errors: list[dict[str, str]] = field(default_factory=list)
    _runner_raw: dict[str, Any] = field(default_factory=dict)
    _executor_raw: dict[str, Any] = field(default_factory=dict)
    _plan_raw: dict[str, Any] = field(default_factory=dict)
    _git_raw: dict[str, Any] = field(default_factory=dict)
    _reports_raw: dict[str, Any] = field(default_factory=dict)
