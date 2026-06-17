from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CoreOutput:
    ok: bool
    source: str
    action: str
    workflow: str | None = None
    phase: str | None = None
    status: str = "unknown"
    risk_level: str = "info"

    fact_snapshot: Any | None = None
    action_outcome: dict[str, Any] | None = None
    result: dict[str, Any] | None = None

    steps: list[dict[str, Any]] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    preview_ids: list[str] = field(default_factory=list)
    next_actions: list[dict[str, Any]] = field(default_factory=list)
    requires_confirmation: bool = False
    confirmation: dict[str, Any] | None = None
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    partial: bool | None = None
    selected_workflow: str | None = None
    selection_reason: str | None = None
    confidence: float | None = None
    stop_reason: str | None = None

    unified_status: dict[str, Any] | None = None
    display_summary: dict[str, Any] | None = None
    audit: dict[str, Any] | None = None
    legacy_views: dict[str, Any] | None = None
