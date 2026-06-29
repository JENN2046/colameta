from __future__ import annotations

from typing import Any

from runner.review_feedback_preview import PREVIEW_AVAILABLE
from runner.review_feedback_validator import VALID_FOR_PREVIEW


CLASSIFICATION_READY = "review_feedback_classification_ready"
CLASSIFICATION_FAILED_CLOSED = "review_feedback_classification_failed_closed"
CLASSIFICATION_BY_DECISION = {
    "ACCEPT": "accept_review_feedback",
    "NEEDS_FIX": "needs_fix_review_feedback",
    "PLAN_ADJUST": "plan_adjust_review_feedback",
    "ABORT": "abort_review_feedback",
}
REQUESTED_COMMANDER_ACTION_BY_CLASSIFICATION = {
    "accept_review_feedback": "ask_whether_to_request_delivery_state_gate_review",
    "needs_fix_review_feedback": "ask_whether_to_prepare_rework_or_gate_return",
    "plan_adjust_review_feedback": "ask_whether_to_prepare_plan_adjustment_draft",
    "abort_review_feedback": "ask_whether_to_prepare_abort_or_supersede_handling",
    "blocked_unclear_review_feedback": "ask_whether_to_return_for_clarification",
}
FORBIDDEN_CLASSIFICATION_CLAIM_KEYS = frozenset(
    {
        "classification_is_review_acceptance",
        "classification_is_delivery_state",
        "classification_authorizes_route",
        "classification_authorizes_executor",
        "commander_authorization_granted",
        "review_decision_created",
        "gate_event_emitted",
        "delivery_state_transitioned",
    }
)


class ReviewFeedbackClassificationError(ValueError):
    def __init__(self, error_code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.details = details or {}


def classify_review_feedback(
    validated_review_feedback: dict[str, Any],
    validation_status_ref: dict[str, Any],
    preview_ref: dict[str, Any],
    mapping_policy_ref: dict[str, Any],
) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    if not isinstance(validated_review_feedback, dict):
        errors.append(_reason("VALIDATED_FEEDBACK_INVALID", "Validated ReviewFeedback must be an object.", {}))
    if not isinstance(validation_status_ref, dict) or validation_status_ref.get("validation_status") != VALID_FOR_PREVIEW:
        errors.append(_reason("VALIDATION_STATUS_NOT_VALID_FOR_PREVIEW", "Classification requires valid_for_preview status.", {}))
    if not isinstance(preview_ref, dict) or preview_ref.get("preview_status") != PREVIEW_AVAILABLE:
        errors.append(_reason("PREVIEW_NOT_AVAILABLE", "Classification requires an available non-authoritative preview.", {}))
    if not isinstance(mapping_policy_ref, dict) or not mapping_policy_ref.get("mapping_policy_id"):
        errors.append(_reason("MAPPING_POLICY_REF_MISSING", "Classification requires a mapping policy ref.", {}))

    decision_value = validation_status_ref.get("normalized_review_decision_value") if isinstance(validation_status_ref, dict) else None
    classification = CLASSIFICATION_BY_DECISION.get(str(decision_value), "blocked_unclear_review_feedback")
    pass_alias_used = (
        bool(validation_status_ref.get("pass_alias_used")) if isinstance(validation_status_ref, dict) else False
    ) or (isinstance(validated_review_feedback, dict) and validated_review_feedback.get("review_decision_value") == "PASS")
    if pass_alias_used and not mapping_policy_ref.get("pass_alias_policy_ref"):
        errors.append(_reason("PASS_ALIAS_POLICY_REF_MISSING", "PASS alias classification requires a policy ref.", {}))

    forbidden_claims = _forbidden_truthy_claims(validated_review_feedback, "validated_review_feedback") if isinstance(validated_review_feedback, dict) else []
    if forbidden_claims:
        errors.append(
            _reason(
                "FORBIDDEN_CLASSIFICATION_AUTHORITY_CLAIM",
                "Validated ReviewFeedback contains forbidden classification authority claims.",
                {"forbidden_claims": forbidden_claims},
            )
        )

    ready = not errors and classification != "blocked_unclear_review_feedback"
    result = {
        "classification_status": CLASSIFICATION_READY if ready else CLASSIFICATION_FAILED_CLOSED,
        "classification_errors": errors,
        "normalized_classification": classification,
        "source_review_feedback_ref": {"review_feedback_id": validated_review_feedback.get("review_feedback_id")}
        if isinstance(validated_review_feedback, dict)
        else {},
        "source_review_decision_value": validated_review_feedback.get("review_decision_value") if isinstance(validated_review_feedback, dict) else None,
        "normalized_review_decision_value": decision_value,
        "requested_commander_action": REQUESTED_COMMANDER_ACTION_BY_CLASSIFICATION[classification],
        "pass_alias_handling": {
            "pass_alias_used": pass_alias_used,
            "maps_to": "accept_review_feedback" if pass_alias_used else None,
            "policy_ref": mapping_policy_ref.get("pass_alias_policy_ref") if isinstance(mapping_policy_ref, dict) else None,
        },
        "commander_authorization_granted": False,
        "review_decision_created": False,
        "gate_event_emitted": False,
        "delivery_state_transitioned": False,
    }
    assert_review_feedback_classification_contract(result)
    return result


def assert_review_feedback_classification_contract(result: dict[str, Any]) -> None:
    if not isinstance(result, dict):
        raise ReviewFeedbackClassificationError("REVIEW_FEEDBACK_CLASSIFICATION_RESULT_INVALID", "Classification result must be an object.")
    forbidden_claims = _forbidden_truthy_claims(result, "classification")
    if forbidden_claims:
        raise ReviewFeedbackClassificationError(
            "FORBIDDEN_REVIEW_FEEDBACK_CLASSIFICATION_CLAIM",
            "Classification result contains forbidden authority claims.",
            details={"forbidden_claims": forbidden_claims},
        )


def classification_mapping_inventory() -> dict[str, Any]:
    return {
        "classification_values": [
            "accept_review_feedback",
            "needs_fix_review_feedback",
            "plan_adjust_review_feedback",
            "abort_review_feedback",
            "blocked_unclear_review_feedback",
        ],
        "decision_mapping": dict(CLASSIFICATION_BY_DECISION),
        "requested_commander_action_mapping": dict(REQUESTED_COMMANDER_ACTION_BY_CLASSIFICATION),
        "forbidden_classification_claims": sorted(FORBIDDEN_CLASSIFICATION_CLAIM_KEYS),
    }


def _reason(code: str, message: str, details: dict[str, Any]) -> dict[str, Any]:
    return {"code": code, "message": message, "details": details}


def _forbidden_truthy_claims(value: Any, path: str) -> list[dict[str, str]]:
    claims: list[dict[str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if str(key) in FORBIDDEN_CLASSIFICATION_CLAIM_KEYS and _truthy_claim(child):
                claims.append({"path": child_path, "key": str(key)})
            claims.extend(_forbidden_truthy_claims(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            claims.extend(_forbidden_truthy_claims(child, f"{path}[{index}]"))
    return claims


def _truthy_claim(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "accepted", "created", "authorized"}
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value != 0
    return False
