from __future__ import annotations

from typing import Any

from runner.review_feedback_schema import (
    EXPECTED_REVIEW_FEEDBACK_SCHEMA_VERSION,
    REVIEW_FEEDBACK_SCHEMA_CHECK_PASSED,
    example_review_feedback,
    validate_review_feedback_schema,
)


VALID_FOR_PREVIEW = "valid_for_preview"
INVALID_MISSING_REQUIRED_FIELD = "invalid_missing_required_field"
INVALID_BINDING_MISMATCH = "invalid_binding_mismatch"
INVALID_UNKNOWN_REVIEW_DECISION = "invalid_unknown_review_decision"
INVALID_PASS_ALIAS_POLICY_MISSING = "invalid_pass_alias_policy_missing"
INVALID_FORBIDDEN_AUTHORITY_CLAIM = "invalid_forbidden_authority_claim"
VALIDATION_STATUSES = (
    VALID_FOR_PREVIEW,
    INVALID_MISSING_REQUIRED_FIELD,
    INVALID_BINDING_MISMATCH,
    INVALID_UNKNOWN_REVIEW_DECISION,
    INVALID_PASS_ALIAS_POLICY_MISSING,
    INVALID_FORBIDDEN_AUTHORITY_CLAIM,
)
REQUIRED_CONTEXT_FIELDS = (
    "review_feedback_schema_ref",
    "expected_master_taskbook_hash",
    "expected_stage_taskbook_hash",
    "expected_version_taskbook_ref",
    "expected_reviewer_handoff_package_ref",
    "expected_workspace_snapshot_ref",
)
FORBIDDEN_OUTPUT_KEYS = frozenset(
    {
        "commander_decision_request",
        "commander_decision_request_created",
        "review_decision_record",
        "review_decision_created",
        "gate_event",
        "gate_event_emitted",
        "delivery_state_transition",
        "delivery_state_transitioned",
        "delivery_state_accepted",
    }
)


class ReviewFeedbackValidatorError(ValueError):
    def __init__(self, error_code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.details = details or {}


def validate_review_feedback_for_preview(review_feedback_candidate: dict[str, Any], validation_context: dict[str, Any]) -> dict[str, Any]:
    context_errors = _validate_context(validation_context)
    schema_result = validate_review_feedback_schema(review_feedback_candidate)
    binding_check = _binding_check(review_feedback_candidate if isinstance(review_feedback_candidate, dict) else {}, validation_context)
    pass_alias_policy_check = _pass_alias_policy_check(review_feedback_candidate if isinstance(review_feedback_candidate, dict) else {})
    forbidden_claim_check = {
        "status": "passed" if not _has_rejection_code(schema_result, "FORBIDDEN_REVIEW_FEEDBACK_AUTHORITY_CLAIM") else "failed_closed",
        "rejection_code": "FORBIDDEN_REVIEW_FEEDBACK_AUTHORITY_CLAIM"
        if _has_rejection_code(schema_result, "FORBIDDEN_REVIEW_FEEDBACK_AUTHORITY_CLAIM")
        else None,
    }

    validation_errors: list[dict[str, Any]] = []
    validation_errors.extend(context_errors)
    validation_errors.extend(schema_result.get("rejection_reasons", []))
    if binding_check["status"] != "passed":
        validation_errors.append(
            _reason(
                "BINDING_MISMATCH",
                "ReviewFeedback binding does not match expected validation context.",
                {"mismatches": binding_check["mismatches"]},
            )
        )

    validation_status = _validation_status(validation_errors, schema_result, binding_check, pass_alias_policy_check)
    result = {
        "validation_status": validation_status,
        "validation_errors": validation_errors,
        "normalized_review_decision_value": schema_result.get("normalized_review_decision_value") if validation_status == VALID_FOR_PREVIEW else None,
        "pass_alias_policy_check": pass_alias_policy_check,
        "binding_check": binding_check,
        "forbidden_claim_check": forbidden_claim_check,
        "schema_check_result": schema_result.get("review_feedback_schema_check_result"),
        "commander_decision_request_created": False,
        "review_decision_created": False,
        "gate_event_emitted": False,
        "delivery_state_transitioned": False,
    }
    assert_review_feedback_validator_result_contract(result)
    return result


def assert_review_feedback_validator_result_contract(result: dict[str, Any]) -> None:
    if not isinstance(result, dict):
        raise ReviewFeedbackValidatorError("REVIEW_FEEDBACK_VALIDATOR_RESULT_INVALID", "Validator result must be an object.")
    if result.get("validation_status") not in VALIDATION_STATUSES:
        raise ReviewFeedbackValidatorError(
            "REVIEW_FEEDBACK_VALIDATOR_STATUS_INVALID",
            "Validator result contains an unsupported validation_status.",
            details={"validation_status": result.get("validation_status")},
        )
    forbidden = _forbidden_truthy_outputs(result, "result")
    if forbidden:
        raise ReviewFeedbackValidatorError(
            "FORBIDDEN_REVIEW_FEEDBACK_VALIDATOR_OUTPUT",
            "Validator result contains forbidden next-state authority output.",
            details={"forbidden_outputs": forbidden},
        )


def example_validation_context() -> dict[str, Any]:
    return {
        "review_feedback_schema_ref": {"schema_version": EXPECTED_REVIEW_FEEDBACK_SCHEMA_VERSION},
        "expected_master_taskbook_hash": "1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34",
        "expected_stage_taskbook_hash": "c83c979d447a4ec645d380b6c1dc206730d12d5d644c08582b3cfd04f3e0009d",
        "expected_version_taskbook_ref": {"version_id": "stage_06_v6_1_review_feedback_schema_v1"},
        "expected_reviewer_handoff_package_ref": {"handoff_package_id": "handoff-package-example"},
        "expected_workspace_snapshot_ref": {"head": "a134b57"},
    }


def example_valid_feedback_for_preview() -> dict[str, Any]:
    feedback = example_review_feedback()
    feedback["version_taskbook_ref"] = {"version_id": "stage_06_v6_1_review_feedback_schema_v1"}
    feedback["reviewer_handoff_package_ref"] = {"handoff_package_id": "handoff-package-example"}
    feedback["workspace_snapshot_ref"] = {"head": "a134b57"}
    return feedback


def validator_rule_inventory() -> dict[str, Any]:
    return {
        "required_inputs": list(REQUIRED_CONTEXT_FIELDS) + ["review_feedback_candidate"],
        "valid_validation_statuses": list(VALIDATION_STATUSES),
        "forbidden_outputs": [
            "commander_decision_request",
            "review_decision_record",
            "gate_event",
            "delivery_state_transition",
        ],
    }


def _validate_context(validation_context: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(validation_context, dict):
        return [_reason("VALIDATION_CONTEXT_INVALID", "Validation context must be an object.", {"actual_type": type(validation_context).__name__})]
    missing = [field for field in REQUIRED_CONTEXT_FIELDS if field not in validation_context]
    if missing:
        return [_reason("VALIDATION_CONTEXT_REQUIRED_FIELD_MISSING", "Validation context is missing required fields.", {"missing_fields": missing})]
    return []


def _binding_check(feedback: dict[str, Any], validation_context: dict[str, Any]) -> dict[str, Any]:
    mismatches: list[dict[str, Any]] = []
    comparisons = (
        ("master_taskbook_hash", feedback.get("master_taskbook_hash"), validation_context.get("expected_master_taskbook_hash")),
        ("stage_taskbook_hash", feedback.get("stage_taskbook_hash"), validation_context.get("expected_stage_taskbook_hash")),
        ("version_taskbook_ref", feedback.get("version_taskbook_ref"), validation_context.get("expected_version_taskbook_ref")),
        (
            "reviewer_handoff_package_ref",
            feedback.get("reviewer_handoff_package_ref"),
            validation_context.get("expected_reviewer_handoff_package_ref"),
        ),
        ("workspace_snapshot_ref", feedback.get("workspace_snapshot_ref"), validation_context.get("expected_workspace_snapshot_ref")),
    )
    for field, actual, expected in comparisons:
        if actual != expected:
            mismatches.append({"field": field, "expected": expected, "actual": actual})
    return {"status": "passed" if not mismatches else "failed_closed", "mismatches": mismatches}


def _pass_alias_policy_check(feedback: dict[str, Any]) -> dict[str, Any]:
    if feedback.get("review_decision_value") != "PASS":
        return {"status": "not_used", "policy_ref_required": False, "policy_ref_present": False}
    present = isinstance(feedback.get("pass_alias_policy_id_when_used"), str) and bool(feedback.get("pass_alias_policy_id_when_used").strip())
    return {"status": "passed" if present else "failed_closed", "policy_ref_required": True, "policy_ref_present": present}


def _validation_status(
    validation_errors: list[dict[str, Any]],
    schema_result: dict[str, Any],
    binding_check: dict[str, Any],
    pass_alias_policy_check: dict[str, Any],
) -> str:
    if not validation_errors and schema_result.get("review_feedback_schema_check_result") == REVIEW_FEEDBACK_SCHEMA_CHECK_PASSED:
        return VALID_FOR_PREVIEW
    if any(item.get("code") in {"VALIDATION_CONTEXT_INVALID", "VALIDATION_CONTEXT_REQUIRED_FIELD_MISSING"} for item in validation_errors):
        return INVALID_MISSING_REQUIRED_FIELD
    if pass_alias_policy_check["status"] == "failed_closed":
        return INVALID_PASS_ALIAS_POLICY_MISSING
    if _has_rejection_code(schema_result, "FORBIDDEN_REVIEW_FEEDBACK_AUTHORITY_CLAIM"):
        return INVALID_FORBIDDEN_AUTHORITY_CLAIM
    if _has_rejection_code(schema_result, "REVIEW_DECISION_VALUE_UNSUPPORTED"):
        return INVALID_UNKNOWN_REVIEW_DECISION
    if binding_check["status"] != "passed":
        return INVALID_BINDING_MISMATCH
    return INVALID_MISSING_REQUIRED_FIELD


def _has_rejection_code(schema_result: dict[str, Any], code: str) -> bool:
    return any(item.get("code") == code for item in schema_result.get("rejection_reasons", []))


def _reason(code: str, message: str, details: dict[str, Any]) -> dict[str, Any]:
    return {"code": code, "message": message, "details": details}


def _forbidden_truthy_outputs(value: Any, path: str) -> list[dict[str, str]]:
    claims: list[dict[str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if str(key) in FORBIDDEN_OUTPUT_KEYS and _truthy_claim(child):
                claims.append({"path": child_path, "key": str(key)})
            claims.extend(_forbidden_truthy_outputs(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            claims.extend(_forbidden_truthy_outputs(child, f"{path}[{index}]"))
    return claims


def _truthy_claim(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "accepted", "created", "authorized"}
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value != 0
    return False
