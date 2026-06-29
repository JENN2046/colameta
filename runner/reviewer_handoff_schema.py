from __future__ import annotations

from typing import Any


HANDOFF_SCHEMA_CHECK_PASSED = "reviewer_handoff_schema_check_passed"
HANDOFF_SCHEMA_CHECK_FAILED_CLOSED = "reviewer_handoff_schema_check_failed_closed"
EXPECTED_HANDOFF_SCHEMA_VERSION = "reviewer_handoff_package.v1"
ALLOWED_REVIEW_DECISIONS = ("ACCEPT", "NEEDS_FIX", "PLAN_ADJUST", "ABORT")
REQUIRED_HANDOFF_PACKAGE_FIELDS = (
    "handoff_package_id",
    "handoff_schema_version",
    "master_taskbook_ref",
    "stage_taskbook_ref",
    "version_taskbook_ref",
    "stage_4_audit_package_ref",
    "execution_receipt_refs",
    "claim_summary",
    "changed_files",
    "validation_truth",
    "scope_evidence",
    "known_risks",
    "known_gaps",
    "reviewer_questions",
    "allowed_review_decisions",
    "forbidden_generator_claims",
    "generated_at",
)
AUTHORITY_BOUNDARY_EXPECTATIONS = {
    "handoff_package_result_is_authority": False,
    "handoff_package_creates_review_decision": False,
    "handoff_package_emits_gate_event": False,
    "handoff_package_writes_delivery_state": False,
    "handoff_package_authorizes_next_route": False,
    "handoff_package_recommends_accept": False,
}
FORBIDDEN_GENERATOR_CLAIM_KEYS = frozenset(
    {
        "recommend_accept",
        "delivery_state_accepted",
        "review_acceptance_recorded",
        "commander_authorized_next_route",
        "scope_aligned_without_reviewer_judgment",
        "review_accepted",
        "review_acceptance",
        "creates_review_decision",
        "emits_gate_event",
        "writes_delivery_state",
        "handoff_package_result_is_authority",
        "handoff_package_creates_review_decision",
        "handoff_package_emits_gate_event",
        "handoff_package_writes_delivery_state",
        "handoff_package_authorizes_next_route",
        "handoff_package_recommends_accept",
    }
)


class ReviewerHandoffSchemaError(ValueError):
    def __init__(self, error_code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.details = details or {}


def validate_reviewer_handoff_package(package: dict[str, Any]) -> dict[str, Any]:
    rejected_fields: set[str] = set()
    rejection_reasons: list[dict[str, Any]] = []
    known_conflicts: list[dict[str, Any]] = []

    if not isinstance(package, dict):
        return _handoff_result(
            package={},
            rejected_fields=[],
            rejection_reasons=[
                _reason(
                    "HANDOFF_PACKAGE_INVALID",
                    "Reviewer handoff package must be an object.",
                    {"actual_type": type(package).__name__},
                )
            ],
            known_conflicts=[],
        )

    missing = [field for field in REQUIRED_HANDOFF_PACKAGE_FIELDS if field not in package]
    if missing:
        rejected_fields.update(missing)
        rejection_reasons.append(
            _reason("REQUIRED_FIELD_MISSING", "Reviewer handoff package is missing required fields.", {"missing_fields": missing})
        )

    if package.get("handoff_schema_version") != EXPECTED_HANDOFF_SCHEMA_VERSION:
        rejected_fields.add("handoff_schema_version")
        rejection_reasons.append(
            _reason(
                "HANDOFF_SCHEMA_VERSION_UNSUPPORTED",
                "Reviewer handoff package schema version is unsupported.",
                {"expected": EXPECTED_HANDOFF_SCHEMA_VERSION, "actual": package.get("handoff_schema_version")},
            )
        )

    for field in ("master_taskbook_ref", "stage_taskbook_ref", "version_taskbook_ref", "stage_4_audit_package_ref"):
        if field in package and not _non_empty_dict(package.get(field)):
            rejected_fields.add(field)
            rejection_reasons.append(_reason("REQUIRED_REF_MISSING", f"{field} must be a non-empty object.", {"field": field}))

    for field in ("execution_receipt_refs", "changed_files", "validation_truth", "scope_evidence", "reviewer_questions"):
        if field in package and not _non_empty_list(package.get(field)):
            rejected_fields.add(field)
            rejection_reasons.append(_reason("REQUIRED_LIST_EMPTY", f"{field} must be a non-empty list.", {"field": field}))

    for field in ("known_risks", "known_gaps", "forbidden_generator_claims"):
        if field in package and not isinstance(package.get(field), list):
            rejected_fields.add(field)
            rejection_reasons.append(_reason("LIST_FIELD_INVALID", f"{field} must be a list.", {"field": field}))

    allowed_decisions = package.get("allowed_review_decisions")
    if list(allowed_decisions) != list(ALLOWED_REVIEW_DECISIONS) if isinstance(allowed_decisions, list) else True:
        rejected_fields.add("allowed_review_decisions")
        rejection_reasons.append(
            _reason(
                "ALLOWED_REVIEW_DECISIONS_MISMATCH",
                "allowed_review_decisions must exactly match the Stage 5 minimum set.",
                {"expected": list(ALLOWED_REVIEW_DECISIONS), "actual": allowed_decisions},
            )
        )

    if package.get("recommended_decision") == "ACCEPT":
        rejected_fields.add("recommended_decision")
        rejection_reasons.append(
            _reason(
                "GENERATOR_RECOMMENDS_ACCEPT",
                "Generator must not recommend ACCEPT.",
                {"recommended_decision": package.get("recommended_decision")},
            )
        )

    forbidden_claims = _forbidden_truthy_claims(package, "handoff_package")
    if forbidden_claims:
        rejected_fields.update(item["path"] for item in forbidden_claims)
        rejection_reasons.append(
            _reason(
                "FORBIDDEN_GENERATOR_AUTHORITY_CLAIM",
                "Reviewer handoff package contains forbidden generator claims.",
                {"forbidden_claims": _safe_forbidden_claims(forbidden_claims)},
            )
        )
        known_conflicts.extend(
            {"conflict_type": "authority_boundary", "path": item["path"], "claim": item["key"]}
            for item in forbidden_claims
        )

    result = _handoff_result(
        package=package,
        rejected_fields=sorted(rejected_fields),
        rejection_reasons=rejection_reasons,
        known_conflicts=known_conflicts,
    )
    assert_reviewer_handoff_schema_result_contract(result)
    return result


def assert_reviewer_handoff_schema_result_contract(result: dict[str, Any]) -> None:
    if not isinstance(result, dict):
        raise ReviewerHandoffSchemaError("HANDOFF_SCHEMA_RESULT_INVALID", "Handoff schema result must be an object.")
    if result.get("authority_boundary") != AUTHORITY_BOUNDARY_EXPECTATIONS:
        raise ReviewerHandoffSchemaError(
            "FORBIDDEN_HANDOFF_SCHEMA_RESULT_AUTHORITY_CLAIM",
            "Handoff schema result authority boundary must remain false.",
            details={"expected": AUTHORITY_BOUNDARY_EXPECTATIONS, "actual": result.get("authority_boundary")},
        )
    forbidden_claims = _forbidden_truthy_claims(result, "result")
    if forbidden_claims:
        raise ReviewerHandoffSchemaError(
            "FORBIDDEN_HANDOFF_SCHEMA_RESULT_CLAIM",
            "Handoff schema result contains forbidden authority claims.",
            details={"forbidden_claims": _safe_forbidden_claims(forbidden_claims)},
        )


def _handoff_result(
    *,
    package: dict[str, Any],
    rejected_fields: list[str],
    rejection_reasons: list[dict[str, Any]],
    known_conflicts: list[dict[str, Any]],
) -> dict[str, Any]:
    passed = not rejection_reasons
    return {
        "handoff_schema_check_result": HANDOFF_SCHEMA_CHECK_PASSED if passed else HANDOFF_SCHEMA_CHECK_FAILED_CLOSED,
        "validation_result": "passed" if passed else "failed_closed",
        "recognized_fields": [field for field in REQUIRED_HANDOFF_PACKAGE_FIELDS if field in package],
        "rejected_fields": rejected_fields,
        "rejection_reasons": rejection_reasons,
        "known_conflicts": known_conflicts,
        "allowed_review_decisions": list(ALLOWED_REVIEW_DECISIONS),
        "authority_boundary": dict(AUTHORITY_BOUNDARY_EXPECTATIONS),
        "review_decision_created": False,
        "review_acceptance_recorded": False,
        "delivery_state_accepted": False,
        "commander_authorized_next_route": False,
        "creates_review_decision": False,
        "emits_gate_event": False,
        "writes_delivery_state": False,
    }


def _reason(code: str, message: str, details: dict[str, Any]) -> dict[str, Any]:
    return {"code": code, "message": message, "details": details}


def _non_empty_dict(value: Any) -> bool:
    return isinstance(value, dict) and bool(value)


def _non_empty_list(value: Any) -> bool:
    return isinstance(value, list) and bool(value)


def _forbidden_truthy_claims(value: Any, path: str = "handoff_package") -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if str(key) in FORBIDDEN_GENERATOR_CLAIM_KEYS and _truthy_claim(child):
                claims.append({"path": child_path, "key": str(key), "value": child})
            claims.extend(_forbidden_truthy_claims(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            claims.extend(_forbidden_truthy_claims(child, f"{path}[{index}]"))
    return claims


def _safe_forbidden_claims(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"path": item.get("path"), "key": item.get("key")} for item in claims]


def _truthy_claim(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "accepted", "authorized", "allowed", "granted", "recorded"}
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value != 0
    return False
