from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TypedDict, cast


class NextAction(TypedDict, total=False):
    action: str
    label: str
    reason: str
    tool: str
    params: dict[str, Any]
    risk_level: str
    requires_confirmation: bool


@dataclass
class ResultFacts:
    recommended_next_actions: list[NextAction] = field(default_factory=list)
    requires_confirmation: bool = False
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    confirmation: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "recommended_next_actions": [dict(item) for item in self.recommended_next_actions],
            "requires_confirmation": self.requires_confirmation,
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "confirmation": dict(self.confirmation) if isinstance(self.confirmation, dict) else None,
        }


def normalize_next_actions(value: Any) -> list[NextAction]:
    data = _as_result_mapping(value)
    nested = data.get("result") if isinstance(data.get("result"), dict) else {}

    actions: list[NextAction] = []
    _extend_actions(actions, data.get("recommended_next_actions"))
    _extend_actions(actions, data.get("next_actions"))
    if not actions:
        _extend_actions(actions, nested.get("recommended_next_actions"))
    if not actions:
        _append_recommended_action(actions, data.get("recommended_next_action"))
        _append_recommended_action(actions, nested.get("recommended_next_action"))

    return actions


def normalize_result_facts(value: Any) -> ResultFacts:
    data = _as_result_mapping(value)
    nested = data.get("result") if isinstance(data.get("result"), dict) else {}
    actions = normalize_next_actions(data)

    blockers: list[str] = []
    warnings: list[str] = []
    _extend_unique_strings(blockers, data.get("blockers"))
    _extend_unique_strings(blockers, data.get("commit_blockers"))
    _extend_unique_strings(blockers, nested.get("blockers"))
    _extend_unique_strings(blockers, nested.get("commit_blockers"))
    _extend_unique_strings(warnings, data.get("warnings"))
    _extend_unique_strings(warnings, data.get("commit_warnings"))
    _extend_unique_strings(warnings, nested.get("warnings"))
    _extend_unique_strings(warnings, nested.get("commit_warnings"))

    steps = data.get("steps")
    if isinstance(steps, list):
        for step in steps:
            if not isinstance(step, dict):
                continue
            _extend_unique_strings(blockers, step.get("blockers"))
            _extend_unique_strings(warnings, step.get("warnings"))

    confirmation = data.get("confirmation")
    if not isinstance(confirmation, dict):
        confirmation = nested.get("confirmation")
    if not isinstance(confirmation, dict):
        confirmation = None

    if isinstance(confirmation, dict):
        from runner.core_confirmation import normalize_confirmation_fact
        fact = normalize_confirmation_fact(confirmation)
        if fact is not None:
            confirmation = fact.to_dict()

    # Try Core confirmation adapters when no explicit confirmation dict found
    if confirmation is None:
        confirmation = _confirmation_from_result_data(data, nested, actions)

    requires_confirmation = bool(data.get("requires_confirmation"))
    if not requires_confirmation and confirmation is not None:
        requires_confirmation = True
    if not requires_confirmation:
        requires_confirmation = any(bool(action.get("requires_confirmation")) for action in actions)

    if requires_confirmation and confirmation is None:
        confirmation = {"required": True}
        preview_ids = _preview_ids_from_result(data)
        if preview_ids:
            confirmation["preview_ids"] = preview_ids

    return ResultFacts(
        recommended_next_actions=actions,
        requires_confirmation=requires_confirmation,
        blockers=blockers,
        warnings=warnings,
        confirmation=confirmation,
    )


def _confirmation_from_result_data(
    data: dict[str, Any],
    nested: dict[str, Any],
    actions: list[NextAction],
) -> dict[str, Any] | None:
    from runner.core_confirmation import (
        confirmation_fact_from_preview_result,
        confirmation_fact_from_next_action,
    )
    _non_preview_keys = frozenset({
        "ok", "status", "error_code", "message", "source", "action", "risk_level",
        "steps", "changed_files", "next_actions", "recommended_next_actions",
        "recommended_next_action", "blockers", "warnings", "commit_blockers",
        "commit_warnings", "confirmation", "requires_confirmation",
        "partial", "selected_workflow", "selection_reason", "confidence",
        "stop_reason", "unified_status", "display_summary", "audit", "fact_snapshot",
        "workflow", "phase", "tool", "result",
    })
    def _strip(data: dict[str, Any]) -> dict[str, Any]:
        stripped: dict[str, Any] = {}
        for k, v in data.items():
            if k in _non_preview_keys:
                continue
            if k == "preview_ids" and isinstance(v, list) and not v:
                continue
            stripped[k] = v
        return stripped

    fact = confirmation_fact_from_preview_result(_strip(data))
    if fact is not None:
        return fact.to_dict()
    fact = confirmation_fact_from_preview_result(_strip(nested))
    if fact is not None:
        return fact.to_dict()
    for action in actions:
        fact = confirmation_fact_from_next_action(dict(action))
        if fact is not None:
            return fact.to_dict()
    return None


def normalize_fact_snapshot_facts(value: Any) -> ResultFacts:
    data = _as_result_mapping(value)
    return normalize_result_facts(data)


def _as_result_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    keys = (
        "recommended_next_actions", "recommended_next_action", "next_actions",
        "requires_confirmation", "blockers", "commit_blockers", "warnings",
        "commit_warnings", "confirmation", "result", "steps", "preview_id",
        "preview_ids",
    )
    return {key: getattr(value, key) for key in keys if hasattr(value, key)}


def _extend_actions(target: list[NextAction], value: Any) -> None:
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                _append_unique_action(target, item)


def _append_recommended_action(target: list[NextAction], value: Any) -> None:
    if isinstance(value, dict):
        _append_unique_action(target, value)
    elif isinstance(value, str) and value.strip():
        _append_unique_action(target, {"action": value.strip()})


def _append_unique_action(target: list[NextAction], action: dict[str, Any]) -> None:
    candidate = dict(action)
    if candidate not in target:
        target.append(cast(NextAction, candidate))


def _extend_unique_strings(target: list[str], value: Any) -> None:
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str) and item not in target:
                target.append(item)


def _preview_ids_from_result(data: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    preview_id = data.get("preview_id")
    if isinstance(preview_id, str) and preview_id.strip():
        ids.append(preview_id.strip())
    preview_ids = data.get("preview_ids")
    if isinstance(preview_ids, list):
        for item in preview_ids:
            if isinstance(item, str) and item.strip() and item.strip() not in ids:
                ids.append(item.strip())
    return ids
