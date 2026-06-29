from __future__ import annotations

from typing import Any

from runner.review_feedback_validator import VALID_FOR_PREVIEW


PREVIEW_AVAILABLE = "review_feedback_preview_available"
PREVIEW_FAILED_CLOSED = "review_feedback_preview_failed_closed"
CANDIDATE_CLASSIFICATION_BY_DECISION = {
    "ACCEPT": "candidate_accept_path",
    "NEEDS_FIX": "candidate_needs_fix_path",
    "PLAN_ADJUST": "candidate_plan_adjust_path",
    "ABORT": "candidate_abort_path",
}
PREVIEW_QUESTION_BY_PATH = {
    "candidate_accept_path": "Ask Commander whether to request Delivery State Gate review.",
    "candidate_needs_fix_path": "Ask Commander whether to request rework or return work through the gate.",
    "candidate_plan_adjust_path": "Ask Commander whether planning changes should be prepared.",
    "candidate_abort_path": "Ask Commander whether stop or supersede handling is needed.",
}
REQUIRED_BOUNDARY_NOTICE = {
    "preview_is_not_commander_decision_request": True,
    "preview_is_not_review_decision": True,
    "preview_is_not_gate_event": True,
    "preview_is_not_delivery_state_transition": True,
    "preview_is_not_plan_mutation": True,
    "preview_is_not_executor_continuation": True,
}
FORBIDDEN_PREVIEW_OUTPUT_KEYS = frozenset(
    {
        "commander_decision_request_id",
        "review_decision_record",
        "gate_event",
        "delivery_state_transition",
        "plan_mutation",
        "executor_continuation",
        "commander_decision_request_created",
        "review_decision_created",
        "gate_event_emitted",
        "delivery_state_transitioned",
    }
)


class ReviewFeedbackPreviewError(ValueError):
    def __init__(self, error_code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.details = details or {}


def build_review_feedback_preview(validated_review_feedback: dict[str, Any], validation_status_ref: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(validated_review_feedback, dict) or not isinstance(validation_status_ref, dict):
        return _failed_preview("PREVIEW_INPUT_INVALID", "Validated feedback and validation status ref must be objects.", {})

    if validation_status_ref.get("validation_status") != VALID_FOR_PREVIEW:
        return _failed_preview(
            "VALIDATION_STATUS_NOT_VALID_FOR_PREVIEW",
            "ReviewFeedback preview requires valid_for_preview validation status.",
            {"validation_status": validation_status_ref.get("validation_status")},
        )

    decision_value = validation_status_ref.get("normalized_review_decision_value")
    candidate_classification = CANDIDATE_CLASSIFICATION_BY_DECISION.get(str(decision_value))
    if candidate_classification is None:
        return _failed_preview(
            "PREVIEW_DECISION_MAPPING_MISSING",
            "Preview cannot map the normalized review decision value.",
            {"normalized_review_decision_value": decision_value},
        )

    source_feedback_ref = {"review_feedback_id": validated_review_feedback.get("review_feedback_id")}
    preview = {
        "preview_status": PREVIEW_AVAILABLE,
        "preview_id": f"preview-{validated_review_feedback.get('review_feedback_id', 'unknown')}",
        "source_feedback_ref": source_feedback_ref,
        "validation_status_ref": {
            "validation_status": validation_status_ref.get("validation_status"),
            "normalized_review_decision_value": decision_value,
            "pass_alias_used": validation_status_ref.get("pass_alias_used", False),
        },
        "candidate_classification": candidate_classification,
        "candidate_commander_decision_request_shape": {
            "request_type": "candidate_only",
            "candidate_path": candidate_classification,
            "preview_question": PREVIEW_QUESTION_BY_PATH[candidate_classification],
            "required_confirmation_fields": [
                "target_feedback_ref",
                "target_validation_status_ref",
                "candidate_classification",
                "exact_commander_confirmation",
            ],
            "commander_decision_request_id_created": False,
        },
        "missing_information": list(validated_review_feedback.get("missing_information", [])),
        "boundary_notice": dict(REQUIRED_BOUNDARY_NOTICE),
        "alias_mapping_notice": _alias_mapping_notice(validated_review_feedback, validation_status_ref),
        "commander_decision_request_created": False,
        "review_decision_created": False,
        "gate_event_emitted": False,
        "delivery_state_transitioned": False,
    }
    assert_review_feedback_preview_contract(preview)
    return preview


def assert_review_feedback_preview_contract(preview: dict[str, Any]) -> None:
    if not isinstance(preview, dict):
        raise ReviewFeedbackPreviewError("REVIEW_FEEDBACK_PREVIEW_INVALID", "Preview result must be an object.")
    if preview.get("preview_status") == PREVIEW_AVAILABLE:
        missing_notices = [key for key, expected in REQUIRED_BOUNDARY_NOTICE.items() if preview.get("boundary_notice", {}).get(key) != expected]
        if missing_notices:
            raise ReviewFeedbackPreviewError(
                "PREVIEW_BOUNDARY_NOTICE_MISSING",
                "Preview result is missing required boundary notices.",
                details={"missing_notices": missing_notices},
            )
    forbidden = _forbidden_preview_outputs(preview, "preview")
    if forbidden:
        raise ReviewFeedbackPreviewError(
            "FORBIDDEN_REVIEW_FEEDBACK_PREVIEW_OUTPUT",
            "Preview result contains forbidden actionable output.",
            details={"forbidden_outputs": forbidden},
        )


def preview_mapping_inventory() -> dict[str, Any]:
    return {
        "candidate_classification_values": [
            "candidate_accept_path",
            "candidate_needs_fix_path",
            "candidate_plan_adjust_path",
            "candidate_abort_path",
            "candidate_blocked_unclear_feedback",
        ],
        "decision_mapping": dict(CANDIDATE_CLASSIFICATION_BY_DECISION),
        "forbidden_outputs": [
            "commander_decision_request_id",
            "review_decision_record",
            "gate_event",
            "delivery_state_transition",
            "plan_mutation",
            "executor_continuation",
        ],
    }


def _alias_mapping_notice(validated_review_feedback: dict[str, Any], validation_status_ref: dict[str, Any]) -> dict[str, Any]:
    pass_alias_used = validation_status_ref.get("pass_alias_used") is True or validated_review_feedback.get("review_decision_value") == "PASS"
    if not pass_alias_used:
        return {"pass_alias_used": False}
    return {
        "pass_alias_used": True,
        "maps_to": "ACCEPT",
        "policy_ref": validated_review_feedback.get("pass_alias_policy_id_when_used"),
        "does_not_mean_delivery_state_accepted": True,
    }


def _failed_preview(code: str, message: str, details: dict[str, Any]) -> dict[str, Any]:
    result = {
        "preview_status": PREVIEW_FAILED_CLOSED,
        "preview_id": None,
        "source_feedback_ref": {},
        "validation_status_ref": {},
        "candidate_classification": "candidate_blocked_unclear_feedback",
        "candidate_commander_decision_request_shape": None,
        "missing_information": [{"code": code, "message": message, "details": details}],
        "boundary_notice": dict(REQUIRED_BOUNDARY_NOTICE),
        "commander_decision_request_created": False,
        "review_decision_created": False,
        "gate_event_emitted": False,
        "delivery_state_transitioned": False,
    }
    assert_review_feedback_preview_contract(result)
    return result


def _forbidden_preview_outputs(value: Any, path: str) -> list[dict[str, str]]:
    claims: list[dict[str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if str(key) in FORBIDDEN_PREVIEW_OUTPUT_KEYS and _truthy_or_present_actionable_key(child, str(key)):
                claims.append({"path": child_path, "key": str(key)})
            claims.extend(_forbidden_preview_outputs(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            claims.extend(_forbidden_preview_outputs(child, f"{path}[{index}]"))
    return claims


def _truthy_or_present_actionable_key(value: Any, key: str) -> bool:
    if key == "commander_decision_request_id":
        return value is not None
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "accepted", "created", "authorized"}
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value != 0
    return False

