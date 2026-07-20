from __future__ import annotations

import json
from typing import Any, Callable


GATE_REVIEW_WORKFLOW = "gate_review_request"
GATE_REVIEW_PHASES = frozenset({"inspect", "preview", "apply", "status"})
WORK_ITEM_STATES = frozenset(
    {"proposed", "ready", "in_delivery", "submitted", "accepted", "cancelled"}
)
_FORWARD_TARGET_STATE = {
    "proposed": "ready",
    "ready": "in_delivery",
    "in_delivery": "submitted",
    "submitted": "accepted",
}
GATE_REVIEW_MAX_BINDING_IDS_PER_FIELD = 16
GATE_REVIEW_MAX_BINDING_ID_CHARS = 256
GATE_REVIEW_MAX_COPYABLE_APPLY_CHARS = 26_000
GATE_REVIEW_MAX_PREVIEW_WORKFLOW_CHARS = 56_000


class GateReviewWorkflowError(ValueError):
    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.details = details or {}


class MCPGateReviewWorkflow:
    """Seven-tool adapter over the authoritative Work Item Gate backend.

    The adapter owns no Gate state and performs no direct ledger writes. It
    only normalizes the high-level workflow request, delegates to the existing
    Work Item application commands, and keeps preview/apply bindings explicit.
    """

    def __init__(self, dispatch: Callable[[str, dict[str, Any]], dict[str, Any]]) -> None:
        self._dispatch = dispatch

    def handle(self, params: dict[str, Any]) -> dict[str, Any]:
        phase = _clean_text(params.get("phase")).lower()
        if phase not in GATE_REVIEW_PHASES:
            raise GateReviewWorkflowError(
                "GATE_REVIEW_PHASE_UNSUPPORTED",
                "gate_review_request phase must be inspect, preview, apply, or status.",
                details={"phase": phase, "supported_phases": sorted(GATE_REVIEW_PHASES)},
            )
        if phase == "inspect":
            return self._inspect(params)
        if phase == "status":
            return self._status(params)
        if phase == "preview":
            return self._preview(params)
        return self._apply(params)

    def _inspect(self, params: dict[str, Any]) -> dict[str, Any]:
        governance = self._dispatch("get_work_item_governance_status", {})
        work_item_id = _optional_text(params.get("work_item_id"), "work_item_id")
        work_item = None
        candidates: list[dict[str, Any]] = []
        next_actions: list[dict[str, Any]] = []
        if work_item_id is not None:
            work_item = self._dispatch("get_work_item", {"work_item_id": work_item_id})
            next_action = _preview_action_for_work_item(work_item)
            if next_action is not None:
                next_actions.append(next_action)
        elif governance.get("ledger_schema_version") is not None:
            listing = self._dispatch("list_work_items", {"limit": 20})
            items = listing.get("items") if isinstance(listing, dict) else None
            if isinstance(items, list):
                candidates = [
                    summary
                    for item in items
                    if isinstance(item, dict)
                    for summary in [_work_item_candidate(item)]
                ]
                next_actions = [
                    {
                        "tool": "run_mcp_workflow",
                        "arguments": {
                            "workflow": GATE_REVIEW_WORKFLOW,
                            "phase": "inspect",
                            "work_item_id": candidate["work_item_id"],
                        },
                        "authority": "read_only",
                    }
                    for candidate in candidates
                ]
        return _workflow_result(
            phase="inspect",
            status="succeeded",
            risk_level="info",
            requires_confirmation=False,
            next_actions=next_actions,
            result={
                "ok": True,
                "read_only": True,
                "side_effects": False,
                "backend": "work_item_governance",
                "governance": governance,
                "work_item": work_item,
                "work_item_candidates": candidates,
                "candidate_count": len(candidates),
                "required_preview_bindings": list(_PUBLIC_TRANSITION_FIELDS),
                "next_action": next_actions[0] if len(next_actions) == 1 else None,
                "selection_required": work_item is None and len(candidates) > 1,
                "authority_boundary": _authority_boundary(),
            },
        )

    def _status(self, params: dict[str, Any]) -> dict[str, Any]:
        work_item_id = _require_text(params.get("work_item_id"), "work_item_id")
        work_item = self._dispatch("get_work_item", {"work_item_id": work_item_id})
        timeline = self._dispatch("get_work_item_timeline", {"work_item_id": work_item_id})
        return _workflow_result(
            phase="status",
            status="succeeded",
            risk_level="info",
            requires_confirmation=False,
            result={
                "ok": True,
                "read_only": True,
                "side_effects": False,
                "backend": "work_item_governance",
                "work_item": work_item,
                "timeline": timeline,
                "authority_boundary": _authority_boundary(),
            },
        )

    def _preview(self, params: dict[str, Any]) -> dict[str, Any]:
        command = _transition_command(params)
        ttl_seconds = _optional_integer(params.get("ttl_seconds"), "ttl_seconds")
        delegate_params: dict[str, Any] = {"command": command}
        if ttl_seconds is not None:
            if ttl_seconds < 1 or ttl_seconds > 900:
                raise GateReviewWorkflowError(
                    "GATE_REVIEW_TTL_INVALID",
                    "ttl_seconds must be between 1 and 900.",
                )
            delegate_params["ttl_seconds"] = ttl_seconds
        backend = self._dispatch("preview_work_item_transition", delegate_params)
        preview = backend.get("preview") if isinstance(backend, dict) else None
        if not isinstance(preview, dict):
            raise GateReviewWorkflowError(
                "GATE_REVIEW_PREVIEW_MISSING",
                "Work Item Gate backend did not return a signed preview.",
            )
        preview_id = _require_text(preview.get("preview_id"), "preview.preview_id")
        apply_arguments = {
            "workflow": GATE_REVIEW_WORKFLOW,
            "phase": "apply",
            **command,
            "gate_preview": preview,
            "confirm_gate_review": True,
        }
        if apply_arguments.get("idempotency_key") is None:
            apply_arguments.pop("idempotency_key")
        apply_call = {
            "tool": "run_mcp_workflow",
            "arguments": apply_arguments,
            "authority": "explicit_commit_scope_and_matching_principal_required",
        }
        apply_call_chars = _json_char_count(apply_call)
        if apply_call_chars > GATE_REVIEW_MAX_COPYABLE_APPLY_CHARS:
            raise GateReviewWorkflowError(
                "GATE_REVIEW_COPYABLE_APPLY_TOO_LARGE",
                "The complete signed Gate apply call exceeds the bounded response contract.",
                details={
                    "actual_chars": apply_call_chars,
                    "max_chars": GATE_REVIEW_MAX_COPYABLE_APPLY_CHARS,
                },
            )
        workflow_result = _workflow_result(
            phase="preview",
            status="preview_ready",
            risk_level="preview",
            requires_confirmation=True,
            preview_ids=[preview_id],
            result={
                "ok": True,
                "read_only": False,
                "side_effects": False,
                "backend": "work_item_governance",
                "preview": preview,
                "evaluation": backend.get("evaluation"),
                "gate_mode": backend.get("gate_mode"),
                "state_changed": False,
                "copyable_apply_call": apply_call,
                "payload_contract": {
                    "binding_ids_per_field_max": GATE_REVIEW_MAX_BINDING_IDS_PER_FIELD,
                    "binding_id_chars_max": GATE_REVIEW_MAX_BINDING_ID_CHARS,
                    "copyable_apply_chars": apply_call_chars,
                    "copyable_apply_chars_max": GATE_REVIEW_MAX_COPYABLE_APPLY_CHARS,
                    "preview_workflow_chars_max": GATE_REVIEW_MAX_PREVIEW_WORKFLOW_CHARS,
                },
                "authority_boundary": _authority_boundary(),
            },
        )
        workflow_chars = _json_char_count(workflow_result)
        if workflow_chars > GATE_REVIEW_MAX_PREVIEW_WORKFLOW_CHARS:
            raise GateReviewWorkflowError(
                "GATE_REVIEW_PREVIEW_RESPONSE_TOO_LARGE",
                "The signed Gate preview exceeds the bounded workflow response contract.",
                details={
                    "actual_chars": workflow_chars,
                    "max_chars": GATE_REVIEW_MAX_PREVIEW_WORKFLOW_CHARS,
                },
            )
        return workflow_result

    def _apply(self, params: dict[str, Any]) -> dict[str, Any]:
        if params.get("confirm_gate_review") is not True:
            raise GateReviewWorkflowError(
                "GATE_REVIEW_CONFIRMATION_REQUIRED",
                "gate_review_request apply requires confirm_gate_review=true.",
            )
        command = _transition_command(params)
        preview = params.get("gate_preview")
        if not isinstance(preview, dict):
            raise GateReviewWorkflowError(
                "GATE_REVIEW_PREVIEW_REQUIRED",
                "gate_review_request apply requires the complete signed gate_preview object.",
            )
        signed_command = preview.get("command")
        if not isinstance(signed_command, dict):
            raise GateReviewWorkflowError(
                "GATE_REVIEW_PREVIEW_INVALID",
                "gate_preview does not contain a signed transition command.",
            )
        mismatches = [
            {
                "field": field,
                "expected_from_preview": signed_command.get(field),
                "actual_apply_value": command.get(field),
            }
            for field in _PUBLIC_TRANSITION_FIELDS
            if signed_command.get(field) != command.get(field)
        ]
        if mismatches:
            raise GateReviewWorkflowError(
                "GATE_REVIEW_PREVIEW_BINDING_MISMATCH",
                "Apply bindings do not match the signed Gate preview.",
                details={"mismatches": mismatches},
            )
        backend = self._dispatch("apply_work_item_transition", {"preview": preview})
        backend_status = _clean_text(backend.get("status")) if isinstance(backend, dict) else ""
        applied = backend_status == "transition_applied"
        rejected = backend_status == "transition_rejected"
        shadow_evaluated = backend_status == "shadow_evaluated"
        durable_mutation = (
            backend_status in {"transition_applied", "transition_rejected"}
            and backend.get("idempotent_replay") is not True
        )
        if applied:
            workflow_status = "succeeded"
            blockers: list[str] = []
        elif rejected:
            workflow_status = "rejected"
            gate_event = backend.get("gate_event")
            reason_code = gate_event.get("reason_code") if isinstance(gate_event, dict) else None
            blockers = [str(reason_code or "Work Item Gate rejected the requested transition.")]
        elif shadow_evaluated:
            workflow_status = "shadow_evaluated"
            blockers = ["Work Item Gate is in shadow mode; no authoritative transition was applied."]
        else:
            workflow_status = "blocked"
            blockers = ["Work Item Gate backend did not return a terminal apply result."]
        return _workflow_result(
            phase="apply",
            status=workflow_status,
            risk_level="write",
            requires_confirmation=False,
            blockers=blockers,
            result={
                "ok": applied,
                "read_only": False,
                "side_effects": durable_mutation,
                "backend": "work_item_governance",
                "outcome": backend_status,
                "gate_result": backend,
                "state_changed": bool(backend.get("state_changed")) if isinstance(backend, dict) else False,
                "authority_boundary": _authority_boundary(),
                "next_action": {
                    "tool": "run_mcp_workflow",
                    "arguments": {
                        "workflow": GATE_REVIEW_WORKFLOW,
                        "phase": "status",
                        "work_item_id": command["work_item_id"],
                    },
                    "authority": "read_only",
                },
            },
        )


_PUBLIC_TRANSITION_FIELDS = (
    "work_item_id",
    "task_version",
    "target_state",
    "expected_state_version",
    "decision_ids",
    "evidence_artifact_ids",
    "idempotency_key",
)


def _transition_command(params: dict[str, Any]) -> dict[str, Any]:
    target_state = _require_text(params.get("target_state"), "target_state")
    if target_state not in WORK_ITEM_STATES:
        raise GateReviewWorkflowError(
            "GATE_REVIEW_TARGET_STATE_INVALID",
            "target_state is not a supported Work Item state.",
            details={"target_state": target_state, "supported_states": sorted(WORK_ITEM_STATES)},
        )
    return {
        "work_item_id": _require_bounded_text(params.get("work_item_id"), "work_item_id"),
        "task_version": _require_positive_integer(params.get("task_version"), "task_version"),
        "target_state": target_state,
        "expected_state_version": _require_non_negative_integer(
            params.get("expected_state_version"), "expected_state_version"
        ),
        "decision_ids": _bounded_string_list(params.get("decision_ids", []), "decision_ids"),
        "evidence_artifact_ids": _bounded_string_list(
            params.get("evidence_artifact_ids", []), "evidence_artifact_ids"
        ),
        "idempotency_key": _optional_bounded_text(
            params.get("idempotency_key"), "idempotency_key"
        ),
    }


def _workflow_result(
    *,
    phase: str,
    status: str,
    risk_level: str,
    requires_confirmation: bool,
    result: dict[str, Any],
    preview_ids: list[str] | None = None,
    blockers: list[str] | None = None,
    next_actions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "ok": status not in {"blocked", "failed", "rejected", "shadow_evaluated"},
        "workflow": GATE_REVIEW_WORKFLOW,
        "phase": phase,
        "status": status,
        "risk_level": risk_level,
        "requires_confirmation": requires_confirmation,
        "changed_files": [],
        "preview_ids": list(preview_ids or []),
        "next_actions": list(next_actions or []),
        "blockers": list(blockers or []),
        "warnings": [],
        "result": result,
    }


def _work_item_candidate(work_item: dict[str, Any]) -> dict[str, Any]:
    state = _clean_text(work_item.get("state"))
    return {
        "work_item_id": _require_text(work_item.get("work_item_id"), "work_item.work_item_id"),
        "state": state,
        "state_version": work_item.get("state_version"),
        "current_task_version": work_item.get("current_task_version"),
        "blocked": work_item.get("blocked") is True,
        "recommended_target_state": _FORWARD_TARGET_STATE.get(state),
    }


def _preview_action_for_work_item(work_item: dict[str, Any]) -> dict[str, Any] | None:
    state = _clean_text(work_item.get("state"))
    target_state = _FORWARD_TARGET_STATE.get(state)
    if target_state is None:
        return None
    decision_records = work_item.get("decision_records")
    artifact_refs = work_item.get("artifact_refs")
    decision_ids = [
        item["decision_id"]
        for item in decision_records if isinstance(item, dict) and isinstance(item.get("decision_id"), str)
    ] if isinstance(decision_records, list) else []
    evidence_artifact_ids = [
        item["artifact_id"]
        for item in artifact_refs if isinstance(item, dict) and isinstance(item.get("artifact_id"), str)
    ] if isinstance(artifact_refs, list) else []
    return {
        "tool": "run_mcp_workflow",
        "arguments": {
            "workflow": GATE_REVIEW_WORKFLOW,
            "phase": "preview",
            "work_item_id": _require_text(work_item.get("work_item_id"), "work_item.work_item_id"),
            "task_version": _require_positive_integer(
                work_item.get("current_task_version"), "work_item.current_task_version"
            ),
            "target_state": target_state,
            "expected_state_version": _require_non_negative_integer(
                work_item.get("state_version"), "work_item.state_version"
            ),
            "decision_ids": decision_ids,
            "evidence_artifact_ids": evidence_artifact_ids,
        },
        "authority": "preview_only",
    }


def _authority_boundary() -> dict[str, Any]:
    return {
        "adapter_owns_gate_state": False,
        "direct_ledger_write": False,
        "backend": "work_item_governance",
        "apply_requires_signed_preview": True,
        "apply_requires_explicit_confirmation": True,
        "apply_requires_matching_principal": True,
        "apply_requires_commit_scope": True,
        "preview_does_not_change_state": True,
    }


def _clean_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _require_text(value: Any, field: str) -> str:
    text = _clean_text(value)
    if not text:
        raise GateReviewWorkflowError(
            "GATE_REVIEW_FIELD_REQUIRED",
            f"{field} must be a non-empty string.",
            details={"field": field},
        )
    return text


def _optional_text(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _require_text(value, field)


def _require_bounded_text(value: Any, field: str) -> str:
    text = _require_text(value, field)
    if len(text) > GATE_REVIEW_MAX_BINDING_ID_CHARS:
        raise GateReviewWorkflowError(
            "GATE_REVIEW_BINDING_ID_TOO_LONG",
            f"{field} exceeds the bounded Gate identifier length.",
            details={
                "field": field,
                "actual_chars": len(text),
                "max_chars": GATE_REVIEW_MAX_BINDING_ID_CHARS,
            },
        )
    return text


def _optional_bounded_text(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _require_bounded_text(value, field)


def _optional_integer(value: Any, field: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise GateReviewWorkflowError(
            "GATE_REVIEW_INTEGER_REQUIRED",
            f"{field} must be an integer.",
            details={"field": field},
        )
    return value


def _require_positive_integer(value: Any, field: str) -> int:
    integer = _optional_integer(value, field)
    if integer is None or integer < 1:
        raise GateReviewWorkflowError(
            "GATE_REVIEW_POSITIVE_INTEGER_REQUIRED",
            f"{field} must be a positive integer.",
            details={"field": field},
        )
    return integer


def _require_non_negative_integer(value: Any, field: str) -> int:
    integer = _optional_integer(value, field)
    if integer is None or integer < 0:
        raise GateReviewWorkflowError(
            "GATE_REVIEW_NON_NEGATIVE_INTEGER_REQUIRED",
            f"{field} must be a non-negative integer.",
            details={"field": field},
        )
    return integer


def _bounded_string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise GateReviewWorkflowError(
            "GATE_REVIEW_STRING_LIST_REQUIRED",
            f"{field} must be a list of non-empty strings.",
            details={"field": field},
        )
    if len(value) > GATE_REVIEW_MAX_BINDING_IDS_PER_FIELD:
        raise GateReviewWorkflowError(
            "GATE_REVIEW_BINDING_COUNT_EXCEEDED",
            f"{field} exceeds the bounded Gate identifier count.",
            details={
                "field": field,
                "actual_items": len(value),
                "max_items": GATE_REVIEW_MAX_BINDING_IDS_PER_FIELD,
            },
        )
    return [_require_bounded_text(item, f"{field}[{index}]") for index, item in enumerate(value)]


def _json_char_count(value: Any) -> int:
    try:
        return len(json.dumps(value, ensure_ascii=False))
    except (TypeError, ValueError):
        return 10**9
