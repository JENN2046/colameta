from __future__ import annotations

from typing import Any

from runner.review_feedback_classification import CLASSIFICATION_READY


COMMANDER_DECISION_REQUEST_AVAILABLE = "commander_decision_request_available"
COMMANDER_DECISION_REQUEST_FAILED_CLOSED = "commander_decision_request_failed_closed"
COMMANDER_DECISION_REQUEST_SCHEMA_VERSION = "commander_decision_request.v1"
ALLOWED_COMMANDER_RESPONSES = (
    "AUTHORIZE_GATE_REVIEW_REQUEST",
    "AUTHORIZE_REWORK_PLANNING",
    "AUTHORIZE_PLAN_ADJUSTMENT_DRAFT",
    "AUTHORIZE_ABORT_HANDLING_DRAFT",
    "RETURN_FOR_CLARIFICATION",
    "REJECT_REQUEST",
)
REQUIRED_REQUEST_FIELDS = (
    "commander_decision_request_id",
    "request_schema_version",
    "source_review_feedback_ref",
    "source_review_decision_value",
    "normalized_classification",
    "reviewer_handoff_package_ref",
    "version_taskbook_ref",
    "execution_report_ref",
    "workspace_snapshot_ref",
    "master_taskbook_hash",
    "stage_taskbook_hash",
    "requested_commander_action",
    "allowed_commander_responses",
    "non_authority_notice",
)
NON_AUTHORITY_NOTICE = {
    "request_is_not_commander_authorization": True,
    "request_does_not_execute_requested_action": True,
    "request_does_not_mutate_plan": True,
    "request_does_not_emit_gate_event": True,
    "request_does_not_continue_executor": True,
    "request_does_not_commit_or_push": True,
}
FORBIDDEN_REQUEST_EFFECT_KEYS = frozenset(
    {
        "commander_authorization_granted",
        "execute_requested_action",
        "mutate_plan",
        "emit_gate_event",
        "continue_executor",
        "commit_or_push",
        "review_decision_created",
        "gate_event_emitted",
        "delivery_state_transitioned",
    }
)


class CommanderDecisionRequestError(ValueError):
    def __init__(self, error_code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.details = details or {}


def build_commander_decision_request(classification_result: dict[str, Any], validated_review_feedback: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(classification_result, dict) or classification_result.get("classification_status") != CLASSIFICATION_READY:
        return _failed_request("CLASSIFICATION_NOT_READY", "CommanderDecisionRequest requires a ready classification.", {})
    if not isinstance(validated_review_feedback, dict):
        return _failed_request("VALIDATED_FEEDBACK_INVALID", "Validated ReviewFeedback must be an object.", {})

    request = {
        "request_status": COMMANDER_DECISION_REQUEST_AVAILABLE,
        "commander_decision_request_id": f"cdr-{validated_review_feedback.get('review_feedback_id', 'unknown')}",
        "request_schema_version": COMMANDER_DECISION_REQUEST_SCHEMA_VERSION,
        "source_review_feedback_ref": classification_result.get("source_review_feedback_ref"),
        "source_review_decision_value": classification_result.get("source_review_decision_value"),
        "normalized_classification": classification_result.get("normalized_classification"),
        "reviewer_handoff_package_ref": validated_review_feedback.get("reviewer_handoff_package_ref"),
        "version_taskbook_ref": validated_review_feedback.get("version_taskbook_ref"),
        "execution_report_ref": validated_review_feedback.get("execution_report_ref"),
        "workspace_snapshot_ref": validated_review_feedback.get("workspace_snapshot_ref"),
        "master_taskbook_hash": validated_review_feedback.get("master_taskbook_hash"),
        "stage_taskbook_hash": validated_review_feedback.get("stage_taskbook_hash"),
        "requested_commander_action": classification_result.get("requested_commander_action"),
        "allowed_commander_responses": list(ALLOWED_COMMANDER_RESPONSES),
        "non_authority_notice": dict(NON_AUTHORITY_NOTICE),
        "commander_authorization_granted": False,
        "execute_requested_action": False,
        "mutate_plan": False,
        "emit_gate_event": False,
        "continue_executor": False,
        "commit_or_push": False,
        "review_decision_created": False,
        "gate_event_emitted": False,
        "delivery_state_transitioned": False,
    }
    assert_commander_decision_request_contract(request)
    return request


def assert_commander_decision_request_contract(request: dict[str, Any]) -> None:
    if not isinstance(request, dict):
        raise CommanderDecisionRequestError("COMMANDER_DECISION_REQUEST_INVALID", "CommanderDecisionRequest result must be an object.")
    if request.get("request_status") == COMMANDER_DECISION_REQUEST_AVAILABLE:
        missing = [field for field in REQUIRED_REQUEST_FIELDS if field not in request or request.get(field) in (None, "", [])]
        if missing:
            raise CommanderDecisionRequestError(
                "COMMANDER_DECISION_REQUEST_FIELD_MISSING",
                "CommanderDecisionRequest is missing required fields.",
                details={"missing_fields": missing},
            )
        if request.get("allowed_commander_responses") != list(ALLOWED_COMMANDER_RESPONSES):
            raise CommanderDecisionRequestError(
                "COMMANDER_RESPONSES_MISMATCH",
                "CommanderDecisionRequest allowed responses must match the bounded set.",
                details={"actual": request.get("allowed_commander_responses")},
            )
        missing_notice = [key for key, expected in NON_AUTHORITY_NOTICE.items() if request.get("non_authority_notice", {}).get(key) != expected]
        if missing_notice:
            raise CommanderDecisionRequestError(
                "COMMANDER_DECISION_REQUEST_NOTICE_MISSING",
                "CommanderDecisionRequest is missing non-authority notices.",
                details={"missing_notice": missing_notice},
            )
    forbidden = _forbidden_truthy_effects(request, "commander_decision_request")
    if forbidden:
        raise CommanderDecisionRequestError(
            "FORBIDDEN_COMMANDER_DECISION_REQUEST_EFFECT",
            "CommanderDecisionRequest contains forbidden effect claims.",
            details={"forbidden_effects": forbidden},
        )


def commander_decision_request_field_inventory() -> dict[str, Any]:
    return {
        "request_schema_version": COMMANDER_DECISION_REQUEST_SCHEMA_VERSION,
        "required_fields": list(REQUIRED_REQUEST_FIELDS),
        "allowed_commander_responses": list(ALLOWED_COMMANDER_RESPONSES),
        "forbidden_request_effects": sorted(FORBIDDEN_REQUEST_EFFECT_KEYS),
    }


def _failed_request(code: str, message: str, details: dict[str, Any]) -> dict[str, Any]:
    request = {
        "request_status": COMMANDER_DECISION_REQUEST_FAILED_CLOSED,
        "commander_decision_request_id": None,
        "request_errors": [{"code": code, "message": message, "details": details}],
        "commander_authorization_granted": False,
        "execute_requested_action": False,
        "mutate_plan": False,
        "emit_gate_event": False,
        "continue_executor": False,
        "commit_or_push": False,
        "review_decision_created": False,
        "gate_event_emitted": False,
        "delivery_state_transitioned": False,
    }
    assert_commander_decision_request_contract(request)
    return request


def _forbidden_truthy_effects(value: Any, path: str) -> list[dict[str, str]]:
    claims: list[dict[str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if str(key) in FORBIDDEN_REQUEST_EFFECT_KEYS and _truthy_claim(child):
                claims.append({"path": child_path, "key": str(key)})
            claims.extend(_forbidden_truthy_effects(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            claims.extend(_forbidden_truthy_effects(child, f"{path}[{index}]"))
    return claims


def _truthy_claim(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "accepted", "created", "authorized", "executed"}
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value != 0
    return False

