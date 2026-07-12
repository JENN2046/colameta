from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class WorkItemGovernanceSettings:
    shadow_ledger_enabled: bool = False
    gate_mode: str = "shadow"
    authoritative_canary: bool = False

    @property
    def transitions_authoritative(self) -> bool:
        return self.gate_mode == "authoritative"


def load_work_item_governance_settings(project_root: str | Path) -> WorkItemGovernanceSettings:
    root = Path(project_root).expanduser().resolve()
    data: dict[str, Any] = {}
    for name in ("runner-settings.json", "settings.json"):
        path = root / ".colameta" / name
        if not path.is_file():
            continue
        try:
            candidate = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(candidate, dict):
            data.update(candidate)
    section = data.get("work_item_governance")
    if not isinstance(section, dict):
        section = {}
    enabled = section.get("shadow_ledger_enabled", data.get("work_item_shadow_ledger_enabled", False)) is True
    gate_mode = section.get("gate_mode", "shadow")
    if gate_mode not in {"off", "shadow", "authoritative"}:
        gate_mode = "shadow"
    authoritative_canary = section.get("authoritative_canary") is True
    return WorkItemGovernanceSettings(
        shadow_ledger_enabled=enabled,
        gate_mode=gate_mode,
        authoritative_canary=authoritative_canary,
    )
