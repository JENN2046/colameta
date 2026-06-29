from __future__ import annotations

from typing import Any

from runner.reviewer_handoff_schema import (
    ALLOWED_REVIEW_DECISIONS,
    HANDOFF_SCHEMA_CHECK_PASSED,
    validate_reviewer_handoff_package,
)


HANDOFF_PACKAGE_GENERATED = "reviewer_handoff_package_generated"
BLOCKED_FOR_REVIEWER_HANDOFF = "blocked_for_reviewer_handoff"
HANDOFF_GENERATION_FAILED_CLOSED = "reviewer_handoff_generation_failed_closed"
REQUIRED_GENERATOR_INPUTS = (
    "reviewer_handoff_schema_ref",
    "master_taskbook_ref",
    "stage_taskbook_ref",
    "version_taskbook_ref",
    "stage_4_audit_package_ref",
    "validation_truth",
    "changed_files",
    "scope_evidence",
    "known_risks",
    "known_gaps",
    "reviewer_questions",
    "generated_at",
)
EMPTY_LIST_ALLOWED_INPUTS = frozenset({"known_risks", "known_gaps"})
AUTHORITY_BOUNDARY_EXPECTATIONS = {
    "generator_result_is_authority": False,
    "generator_recommends_accept": False,
    "generator_creates_review_decision": False,
    "generator_emits_gate_event": False,
    "generator_writes_delivery_state": False,
    "generator_authorizes_next_route": False,
}
FORBIDDEN_GENERATOR_CLAIM_KEYS = frozenset(
    {
        "recommend_accept",
        "infer_review_decision",
        "create_review_decision_record",
        "emit_gate_event",
        "mutate_delivery_state",
        "hide_validation_failure",
        "delivery_state_accepted",
        "review_accepted",
        "review_acceptance",
        "commander_authorized_next_route",
    }
)


class ReviewerHandoffGeneratorError(ValueError):
    def __init__(self, error_code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.details = details or {}


def generate_reviewer_handoff_package(inputs: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(inputs, dict):
        result = _generator_result(
            package={},
            schema_validation_result={},
            missing_inputs=list(REQUIRED_GENERATOR_INPUTS),
            blockers=[_blocker("GENERATOR_INPUTS_INVALID", "Generator inputs must be an object.", {})],
            known_conflicts=[],
        )
        assert_reviewer_handoff_generator_result_contract(result)
        return result

    missing_inputs = [
        field
        for field in REQUIRED_GENERATOR_INPUTS
        if field not in inputs or (field not in EMPTY_LIST_ALLOWED_INPUTS and not _input_present(inputs.get(field)))
    ]
    blockers: list[dict[str, Any]] = []
    known_conflicts: list[dict[str, Any]] = []

    forbidden_claims = _forbidden_truthy_claims(inputs, "generator_inputs")
    if forbidden_claims:
        blockers.append(
            _blocker(
                "FORBIDDEN_GENERATOR_INPUT_CLAIM",
                "Generator inputs contain forbidden authority claims.",
                {"forbidden_claims": _safe_forbidden_claims(forbidden_claims)},
            )
        )
        known_conflicts.extend(
            {"conflict_type": "authority_boundary", "path": item["path"], "claim": item["key"]}
            for item in forbidden_claims
        )

    package = {
        "handoff_package_id": inputs.get("handoff_package_id", "reviewer-handoff-package"),
        "handoff_schema_version": "reviewer_handoff_package.v1",
        "master_taskbook_ref": _dict_or_empty(inputs.get("master_taskbook_ref")),
        "stage_taskbook_ref": _dict_or_empty(inputs.get("stage_taskbook_ref")),
        "version_taskbook_ref": _dict_or_empty(inputs.get("version_taskbook_ref")),
        "stage_4_audit_package_ref": _dict_or_empty(inputs.get("stage_4_audit_package_ref")),
        "execution_receipt_refs": _list_or_empty(inputs.get("execution_receipt_refs")),
        "claim_summary": _dict_or_empty(inputs.get("claim_summary")),
        "changed_files": _list_or_empty(inputs.get("changed_files")),
        "validation_truth": _list_or_empty(inputs.get("validation_truth")),
        "scope_evidence": _list_or_empty(inputs.get("scope_evidence")),
        "known_risks": _list_or_empty(inputs.get("known_risks")),
        "known_gaps": _list_or_empty(inputs.get("known_gaps")),
        "reviewer_questions": _list_or_empty(inputs.get("reviewer_questions")),
        "allowed_review_decisions": list(ALLOWED_REVIEW_DECISIONS),
        "forbidden_generator_claims": [
            "recommend_accept",
            "delivery_state_accepted",
            "review_acceptance_recorded",
            "commander_authorized_next_route",
            "scope_aligned_without_reviewer_judgment",
        ],
        "generated_at": inputs.get("generated_at"),
    }
    schema_validation_result = validate_reviewer_handoff_package(package)
    if schema_validation_result.get("handoff_schema_check_result") != HANDOFF_SCHEMA_CHECK_PASSED:
        blockers.append(
            _blocker(
                "GENERATED_PACKAGE_SCHEMA_INVALID",
                "Generated reviewer handoff package failed the v5.1 schema.",
                {"rejected_fields": schema_validation_result.get("rejected_fields")},
            )
        )

    result = _generator_result(
        package=package,
        schema_validation_result=schema_validation_result,
        missing_inputs=missing_inputs,
        blockers=blockers,
        known_conflicts=known_conflicts,
    )
    assert_reviewer_handoff_generator_result_contract(result)
    return result


def assert_reviewer_handoff_generator_result_contract(result: dict[str, Any]) -> None:
    if not isinstance(result, dict):
        raise ReviewerHandoffGeneratorError("HANDOFF_GENERATOR_RESULT_INVALID", "Generator result must be an object.")
    if result.get("authority_boundary") != AUTHORITY_BOUNDARY_EXPECTATIONS:
        raise ReviewerHandoffGeneratorError(
            "FORBIDDEN_HANDOFF_GENERATOR_AUTHORITY_CLAIM",
            "Generator result authority boundary must remain false.",
            details={"expected": AUTHORITY_BOUNDARY_EXPECTATIONS, "actual": result.get("authority_boundary")},
        )
    forbidden_claims = _forbidden_truthy_claims(result, "generator_result")
    if forbidden_claims:
        raise ReviewerHandoffGeneratorError(
            "FORBIDDEN_HANDOFF_GENERATOR_RESULT_CLAIM",
            "Generator result contains forbidden authority claims.",
            details={"forbidden_claims": _safe_forbidden_claims(forbidden_claims)},
        )


def _generator_result(
    *,
    package: dict[str, Any],
    schema_validation_result: dict[str, Any],
    missing_inputs: list[str],
    blockers: list[dict[str, Any]],
    known_conflicts: list[dict[str, Any]],
) -> dict[str, Any]:
    if blockers:
        status = HANDOFF_GENERATION_FAILED_CLOSED
    elif missing_inputs:
        status = BLOCKED_FOR_REVIEWER_HANDOFF
    else:
        status = HANDOFF_PACKAGE_GENERATED
    return {
        "generation_status": status,
        "reviewer_handoff_package": package,
        "generation_summary": {
            "schema_consumed": True,
            "allowed_review_decisions_preserved": package.get("allowed_review_decisions") == list(ALLOWED_REVIEW_DECISIONS),
            "reviewer_decision_created": False,
            "gate_event_emitted": False,
            "delivery_state_transitioned": False,
        },
        "missing_input_report": {"missing_inputs": missing_inputs, "blocked_for_reviewer_handoff": bool(missing_inputs)},
        "forbidden_claim_check": {"forbidden_claims_present": bool(known_conflicts), "known_conflicts": known_conflicts},
        "schema_validation_result": schema_validation_result,
        "failures_and_blockers": blockers,
        "authority_boundary": dict(AUTHORITY_BOUNDARY_EXPECTATIONS),
        "recommended_decision": None,
        "review_decision_created": False,
        "gate_event_emitted": False,
        "delivery_state_accepted": False,
        "commander_authorized_next_route": False,
    }


def _input_present(value: Any) -> bool:
    if isinstance(value, (dict, list, str)):
        return bool(value)
    return value is not None


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_or_empty(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _blocker(code: str, message: str, details: dict[str, Any]) -> dict[str, Any]:
    return {"code": code, "message": message, "details": details, "blocking": True}


def _forbidden_truthy_claims(value: Any, path: str = "generator") -> list[dict[str, Any]]:
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
        return value.strip().lower() in {"true", "yes", "accepted", "authorized", "allowed", "granted", "created"}
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value != 0
    return False
