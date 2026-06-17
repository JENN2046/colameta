from dataclasses import dataclass
from typing import Any


@dataclass
class CoreResult:
    ok: bool
    workflow: str
    status: str
    risk_level: str
    steps: list[dict]
    changed_files: list[str]
    preview_ids: list[str]
    next_actions: list[dict]
    requires_confirmation: bool
    blockers: list[str]
    warnings: list[str]
    result: dict | None = None
    error_code: str | None = None
    message: str | None = None
    phase: str | None = None
    selected_workflow: str | None = None
    selection_reason: str | None = None
    confidence: float | None = None
    stop_reason: str | None = None
    partial: bool | None = None
    fact_snapshot: Any | None = None
