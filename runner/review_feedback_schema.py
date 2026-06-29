from __future__ import annotations

import re
from typing import Any


REVIEW_FEEDBACK_SCHEMA_CHECK_PASSED = "review_feedback_schema_check_passed"
REVIEW_FEEDBACK_SCHEMA_CHECK_FAILED_CLOSED = "review_feedback_schema_check_failed_closed"
EXPECTED_REVIEW_FEEDBACK_SCHEMA_VERSION = "review_feedback.v1"
LEGACY_PASS_ALIAS_POLICY_SCOPE = "legacy_alias_only_not_delivery_state_accepted"
ALLOWED_REVIEW_DECISION_VALUES = ("ACCEPT", "NEEDS_FIX", "PLAN_ADJUST", "ABORT")
REQUIRED_REVIEW_FEEDBACK_FIELDS = (
    "review_feedback_id",
    "review_feedback_schema_version",
    "reviewer_identity_or_source",
    "reviewer_authority_scope",
    "reviewer_attestation",
    "reviewer_handoff_package_ref",
    "version_taskbook_ref",
    "execution_report_ref",
    "workspace_snapshot_ref",
    "master_taskbook_hash",
    "stage_taskbook_hash",
    "review_decision_value",
    "pass_alias_policy_id_when_used",
    "charter_alignment",
    "task_completion",
    "scope_assessment",
    "reviewer_notes",
    "submitted_at",
)
REQUIRED_REF_FIELDS = (
    "reviewer_handoff_package_ref",
    "version_taskbook_ref",
    "execution_report_ref",
    "workspace_snapshot_ref",
)
REQUIRED_HASH_FIELDS = ("master_taskbook_hash", "stage_taskbook_hash")
AUTHORITY_BOUNDARY_EXPECTATIONS = {
    "review_feedback_writes_delivery_state": False,
    "review_feedback_mutates_plan": False,
    "review_feedback_authorizes_executor_continuation": False,
    "accept_means_delivery_state_accepted": False,
    "review_decision_created": False,
    "gate_event_emitted": False,
    "delivery_state_transitioned": False,
}
FORBIDDEN_REVIEW_FEEDBACK_CLAIM_KEYS = frozenset(
    {
        "review_feedback_writes_delivery_state",
        "review_feedback_mutates_plan",
        "review_feedback_authorizes_executor_continuation",
        "accept_means_delivery_state_accepted",
        "review_decision_created",
        "gate_event_emitted",
        "delivery_state_transitioned",
        "delivery_state_accepted",
        "plan_mutated",
        "executor_continuation_authorized",
        "review_accepted",
        "accepted_delivery_state",
    }
)


class ReviewFeedbackSchemaError(ValueError):
    def __init__(self, error_code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.details = details or {}


def validate_review_feedback_schema(feedback: dict[str, Any]) -> dict[str, Any]:
    rejected_fields: set[str] = set()
    rejection_reasons: list[dict[str, Any]] = []
    known_conflicts: list[dict[str, Any]] = []

    if not isinstance(feedback, dict):
        return _schema_result(
            feedback={},
            rejected_fields=[],
            rejection_reasons=[
                _reason(
                    "REVIEW_FEEDBACK_INVALID",
                    "ReviewFeedback must be an object.",
                    {"actual_type": type(feedback).__name__},
                )
            ],
            known_conflicts=[],
            normalized_review_decision_value=None,
            pass_alias_used=False,
        )

    missing = [field for field in REQUIRED_REVIEW_FEEDBACK_FIELDS if field not in feedback]
    if missing:
        rejected_fields.update(missing)
        rejection_reasons.append(_reason("REQUIRED_FIELD_MISSING", "ReviewFeedback is missing required fields.", {"missing_fields": missing}))

    if feedback.get("review_feedback_schema_version") != EXPECTED_REVIEW_FEEDBACK_SCHEMA_VERSION:
        rejected_fields.add("review_feedback_schema_version")
        rejection_reasons.append(
            _reason(
                "REVIEW_FEEDBACK_SCHEMA_VERSION_UNSUPPORTED",
                "ReviewFeedback schema version is unsupported.",
                {"expected": EXPECTED_REVIEW_FEEDBACK_SCHEMA_VERSION, "actual": feedback.get("review_feedback_schema_version")},
            )
        )

    for field in REQUIRED_REF_FIELDS:
        if field in feedback and not _non_empty_dict(feedback.get(field)):
            rejected_fields.add(field)
            rejection_reasons.append(_reason("REQUIRED_REF_MISSING", f"{field} must be a non-empty object.", {"field": field}))

    for field in REQUIRED_HASH_FIELDS:
        if field in feedback and not _sha256_hex(feedback.get(field)):
            rejected_fields.add(field)
            rejection_reasons.append(_reason("REQUIRED_HASH_INVALID", f"{field} must be a sha256 hex string.", {"field": field}))

    for field in (
        "review_feedback_id",
        "reviewer_identity_or_source",
        "reviewer_authority_scope",
        "reviewer_attestation",
        "charter_alignment",
        "task_completion",
        "scope_assessment",
        "reviewer_notes",
        "submitted_at",
    ):
        if field in feedback and _empty(feedback.get(field)):
            rejected_fields.add(field)
            rejection_reasons.append(_reason("REQUIRED_VALUE_EMPTY", f"{field} must not be empty.", {"field": field}))

    normalized_review_decision_value = _normalize_review_decision(feedback.get("review_decision_value"), feedback.get("pass_alias_policy_id_when_used"))
    if normalized_review_decision_value is None:
        rejected_fields.add("review_decision_value")
        rejection_reasons.append(
            _reason(
                "REVIEW_DECISION_VALUE_UNSUPPORTED",
                "Review decision must be ACCEPT, NEEDS_FIX, PLAN_ADJUST, ABORT, or PASS with an explicit alias policy ref.",
                {
                    "actual": feedback.get("review_decision_value"),
                    "pass_alias_policy_id_when_used": feedback.get("pass_alias_policy_id_when_used"),
                },
            )
        )

    forbidden_claims = _forbidden_truthy_claims(feedback, "review_feedback")
    if forbidden_claims:
        rejected_fields.update(item["path"] for item in forbidden_claims)
        rejection_reasons.append(
            _reason(
                "FORBIDDEN_REVIEW_FEEDBACK_AUTHORITY_CLAIM",
                "ReviewFeedback contains forbidden authority claims.",
                {"forbidden_claims": _safe_forbidden_claims(forbidden_claims)},
            )
        )
        known_conflicts.extend(
            {"conflict_type": "authority_boundary", "path": item["path"], "claim": item["key"]}
            for item in forbidden_claims
        )

    result = _schema_result(
        feedback=feedback,
        rejected_fields=sorted(rejected_fields),
        rejection_reasons=rejection_reasons,
        known_conflicts=known_conflicts,
        normalized_review_decision_value=normalized_review_decision_value,
        pass_alias_used=feedback.get("review_decision_value") == "PASS",
    )
    assert_review_feedback_schema_result_contract(result)
    return result


def assert_review_feedback_schema_result_contract(result: dict[str, Any]) -> None:
    if not isinstance(result, dict):
        raise ReviewFeedbackSchemaError("REVIEW_FEEDBACK_SCHEMA_RESULT_INVALID", "ReviewFeedback schema result must be an object.")
    if result.get("authority_boundary") != AUTHORITY_BOUNDARY_EXPECTATIONS:
        raise ReviewFeedbackSchemaError(
            "FORBIDDEN_REVIEW_FEEDBACK_SCHEMA_RESULT_AUTHORITY_CLAIM",
            "ReviewFeedback schema result authority boundary must remain false.",
            details={"expected": AUTHORITY_BOUNDARY_EXPECTATIONS, "actual": result.get("authority_boundary")},
        )
    forbidden_claims = _forbidden_truthy_claims(result, "result")
    if forbidden_claims:
        raise ReviewFeedbackSchemaError(
            "FORBIDDEN_REVIEW_FEEDBACK_SCHEMA_RESULT_CLAIM",
            "ReviewFeedback schema result contains forbidden authority claims.",
            details={"forbidden_claims": _safe_forbidden_claims(forbidden_claims)},
        )


def review_feedback_field_inventory() -> dict[str, Any]:
    return {
        "schema_version": EXPECTED_REVIEW_FEEDBACK_SCHEMA_VERSION,
        "required_fields": list(REQUIRED_REVIEW_FEEDBACK_FIELDS),
        "allowed_review_decision_values": list(ALLOWED_REVIEW_DECISION_VALUES),
        "legacy_aliases": {
            "PASS": {
                "maps_to": "ACCEPT",
                "requires_policy_ref": True,
                "policy_scope": LEGACY_PASS_ALIAS_POLICY_SCOPE,
            }
        },
        "authority_boundary": dict(AUTHORITY_BOUNDARY_EXPECTATIONS),
    }


def example_review_feedback(*, review_decision_value: str = "NEEDS_FIX", pass_alias_policy_id_when_used: str | None = None) -> dict[str, Any]:
    return {
        "review_feedback_id": "review-feedback-example",
        "review_feedback_schema_version": EXPECTED_REVIEW_FEEDBACK_SCHEMA_VERSION,
        "reviewer_identity_or_source": {"source_type": "manual_reviewer", "display_name": "Reviewer"},
        "reviewer_authority_scope": {"scope": "review_feedback_only"},
        "reviewer_attestation": {"attested": True, "basis": "reviewed handoff package"},
        "reviewer_handoff_package_ref": {"handoff_package_id": "handoff-package-example"},
        "version_taskbook_ref": {"version_id": "stage_06_v6_1_review_feedback_schema_v1"},
        "execution_report_ref": {"path": "docs/taskbooks/versions/stage-05/evidence/example.md"},
        "workspace_snapshot_ref": {"head": "a134b57"},
        "master_taskbook_hash": "1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34",
        "stage_taskbook_hash": "c83c979d447a4ec645d380b6c1dc206730d12d5d644c08582b3cfd04f3e0009d",
        "review_decision_value": review_decision_value,
        "pass_alias_policy_id_when_used": pass_alias_policy_id_when_used,
        "charter_alignment": {"result": "aligned"},
        "task_completion": {"result": "partial"},
        "scope_assessment": {"result": "in_scope"},
        "reviewer_notes": "Example feedback for schema validation.",
        "submitted_at": "2026-06-30T00:00:00+08:00",
    }


def _schema_result(
    *,
    feedback: dict[str, Any],
    rejected_fields: list[str],
    rejection_reasons: list[dict[str, Any]],
    known_conflicts: list[dict[str, Any]],
    normalized_review_decision_value: str | None,
    pass_alias_used: bool,
) -> dict[str, Any]:
    passed = not rejection_reasons
    return {
        "review_feedback_schema_check_result": REVIEW_FEEDBACK_SCHEMA_CHECK_PASSED if passed else REVIEW_FEEDBACK_SCHEMA_CHECK_FAILED_CLOSED,
        "validation_result": "passed" if passed else "failed_closed",
        "recognized_fields": [field for field in REQUIRED_REVIEW_FEEDBACK_FIELDS if field in feedback],
        "rejected_fields": rejected_fields,
        "rejection_reasons": rejection_reasons,
        "known_conflicts": known_conflicts,
        "allowed_review_decision_values": list(ALLOWED_REVIEW_DECISION_VALUES),
        "normalized_review_decision_value": normalized_review_decision_value,
        "pass_alias_used": pass_alias_used,
        "authority_boundary": dict(AUTHORITY_BOUNDARY_EXPECTATIONS),
        "review_decision_created": False,
        "gate_event_emitted": False,
        "delivery_state_transitioned": False,
        "plan_mutated": False,
        "executor_continuation_authorized": False,
    }


def _normalize_review_decision(value: Any, pass_alias_policy_id_when_used: Any) -> str | None:
    if value in ALLOWED_REVIEW_DECISION_VALUES:
        return str(value)
    if value == "PASS" and isinstance(pass_alias_policy_id_when_used, str) and pass_alias_policy_id_when_used.strip():
        return "ACCEPT"
    return None


def _reason(code: str, message: str, details: dict[str, Any]) -> dict[str, Any]:
    return {"code": code, "message": message, "details": details}


def _non_empty_dict(value: Any) -> bool:
    return isinstance(value, dict) and bool(value)


def _empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, (list, dict, str)):
        return len(value) == 0
    return False


def _sha256_hex(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _forbidden_truthy_claims(value: Any, path: str = "review_feedback") -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if str(key) in FORBIDDEN_REVIEW_FEEDBACK_CLAIM_KEYS and _truthy_claim(child):
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


def _safe_forbidden_claims(claims: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [{"path": str(item["path"]), "key": str(item["key"])} for item in claims]

