from __future__ import annotations

from typing import Any


ENVELOPE_CHECK_PASSED = "envelope_check_passed"
ENVELOPE_CHECK_FAILED_CLOSED = "envelope_check_failed_closed"

REQUIRED_ENVELOPE_FIELDS = (
    "envelope_id",
    "envelope_schema_version",
    "version_taskbook_ref",
    "master_taskbook_ref",
    "stage_taskbook_ref",
    "authority_mode",
    "local_execution_authorization_ref",
    "imported_receipt_authorization_ref",
    "allowed_files",
    "forbidden_files",
    "allowed_commands",
    "validation_commands",
    "timeout_limits",
    "network_policy",
    "secrets_policy",
    "destructive_operation_policy",
    "retry_policy",
    "stop_conditions",
)
VALID_AUTHORITY_MODES = frozenset({"local_execution", "imported_receipt", "validation_only"})
EXPECTED_ENVELOPE_SCHEMA_VERSION = "execution_envelope.v1"
EXPECTED_MASTER_TASKBOOK_REF = {
    "path": "PROJECT_MASTER_TASKBOOK.md",
    "raw_snapshot_sha256": "1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34",
    "review_status": "freeze_candidate_confirmed_for_exact_hash",
}
EXPECTED_STAGE_TASKBOOK_REF = {
    "path": "docs/taskbooks/stages/STAGE_04_BOUNDED_EXECUTION_AND_EVIDENCE.md",
    "raw_snapshot_sha256": "05e6114a666942c0641c635905c2295feaa62b98bd9e7b5166babd662e015a41",
    "stage_id": "stage_04_bounded_execution_and_evidence",
}
EXPECTED_VERSION_TASKBOOK_REF = {
    "path": "docs/taskbooks/versions/stage-04/VERSION_STAGE_04_V4_1_MACHINE_CHECKABLE_EXECUTION_ENVELOPE_V1.md",
    "raw_snapshot_sha256": "22e99e01a854c6d8fe1fc4f0ceba38f5d2b1ce28d796596f80f4292459071dfa",
    "version_id": "stage_04_v4_1_machine_checkable_execution_envelope_v1",
}

AUTHORITY_BOUNDARY_EXPECTATIONS = {
    "envelope_result_is_authority": False,
    "envelope_existence_authorizes_dispatch": False,
    "envelope_authorizes_allowed_files_expansion": False,
    "envelope_authorizes_plan_mutation": False,
    "envelope_authorizes_commit": False,
    "envelope_authorizes_push": False,
    "envelope_writes_delivery_state": False,
    "creates_review_decision": False,
    "emits_gate_event": False,
}
FORBIDDEN_ENVELOPE_CLAIM_KEYS = frozenset(
    {
        "dispatch_authorized_by_envelope_existence",
        "executor_dispatch_authorized",
        "allowed_files_expansion_authorized",
        "plan_mutation_authorized",
        "commit_authorized",
        "push_authorized",
        "delivery_state_accepted",
        "review_acceptance",
        "review_accepted",
        "envelope_result_is_authority",
        "envelope_existence_authorizes_dispatch",
        "envelope_authorizes_allowed_files_expansion",
        "envelope_authorizes_plan_mutation",
        "envelope_authorizes_commit",
        "envelope_authorizes_push",
        "envelope_writes_delivery_state",
        "creates_review_decision",
        "emits_gate_event",
        "writes_delivery_state",
    }
)


class ExecutionEnvelopeError(ValueError):
    def __init__(self, error_code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.details = details or {}


def validate_execution_envelope(
    envelope: dict[str, Any],
    *,
    expected_version_taskbook_ref: dict[str, str] | None = None,
    expected_master_taskbook_ref: dict[str, str] | None = None,
    expected_stage_taskbook_ref: dict[str, str] | None = None,
) -> dict[str, Any]:
    expected_version_ref = expected_version_taskbook_ref or EXPECTED_VERSION_TASKBOOK_REF
    expected_master_ref = expected_master_taskbook_ref or EXPECTED_MASTER_TASKBOOK_REF
    expected_stage_ref = expected_stage_taskbook_ref or EXPECTED_STAGE_TASKBOOK_REF
    rejected_fields: set[str] = set()
    rejection_reasons: list[dict[str, Any]] = []
    known_conflicts: list[dict[str, Any]] = []

    if not isinstance(envelope, dict):
        return _envelope_result(
            envelope={},
            rejected_fields=[],
            rejection_reasons=[
                _reason(
                    "ENVELOPE_INVALID",
                    "ExecutionEnvelope must be an object.",
                    {"actual_type": type(envelope).__name__},
                )
            ],
            known_conflicts=[],
        )

    missing = [field for field in REQUIRED_ENVELOPE_FIELDS if field not in envelope]
    if missing:
        rejected_fields.update(missing)
        rejection_reasons.append(
            _reason(
                "REQUIRED_FIELD_MISSING",
                "ExecutionEnvelope is missing required fields.",
                {"missing_fields": missing},
            )
        )

    if envelope.get("envelope_schema_version") != EXPECTED_ENVELOPE_SCHEMA_VERSION:
        rejected_fields.add("envelope_schema_version")
        rejection_reasons.append(
            _reason(
                "ENVELOPE_SCHEMA_VERSION_UNSUPPORTED",
                "ExecutionEnvelope schema version is unsupported.",
                {
                    "expected": EXPECTED_ENVELOPE_SCHEMA_VERSION,
                    "actual": envelope.get("envelope_schema_version"),
                },
            )
        )

    _validate_ref(envelope.get("version_taskbook_ref"), expected_version_ref, "version_taskbook_ref", rejected_fields, rejection_reasons, known_conflicts)
    _validate_ref(envelope.get("master_taskbook_ref"), expected_master_ref, "master_taskbook_ref", rejected_fields, rejection_reasons, known_conflicts)
    _validate_ref(envelope.get("stage_taskbook_ref"), expected_stage_ref, "stage_taskbook_ref", rejected_fields, rejection_reasons, known_conflicts)

    authority_mode = envelope.get("authority_mode")
    if authority_mode not in VALID_AUTHORITY_MODES:
        rejected_fields.add("authority_mode")
        rejection_reasons.append(
            _reason(
                "AUTHORITY_MODE_UNSUPPORTED",
                "ExecutionEnvelope authority_mode is unsupported.",
                {"actual": authority_mode, "valid_authority_modes": sorted(VALID_AUTHORITY_MODES)},
            )
        )

    if authority_mode == "local_execution" and not _non_empty_dict(envelope.get("local_execution_authorization_ref")):
        rejected_fields.add("local_execution_authorization_ref")
        rejection_reasons.append(
            _reason(
                "LOCAL_EXECUTION_AUTHORIZATION_REF_REQUIRED",
                "local_execution mode requires local_execution_authorization_ref.",
                {"authority_mode": authority_mode},
            )
        )
    if authority_mode == "imported_receipt" and not _non_empty_dict(envelope.get("imported_receipt_authorization_ref")):
        rejected_fields.add("imported_receipt_authorization_ref")
        rejection_reasons.append(
            _reason(
                "IMPORTED_RECEIPT_AUTHORIZATION_REF_REQUIRED",
                "imported_receipt mode requires imported_receipt_authorization_ref.",
                {"authority_mode": authority_mode},
            )
        )

    for field in ("allowed_files", "allowed_commands", "validation_commands", "stop_conditions"):
        if field in envelope and not _non_empty_string_list(envelope.get(field)):
            rejected_fields.add(field)
            rejection_reasons.append(
                _reason(
                    "FIELD_LIST_EMPTY_OR_INVALID",
                    f"{field} must be a non-empty list of strings.",
                    {"field": field, "actual": envelope.get(field)},
                )
            )
    if "forbidden_files" in envelope and not _string_list(envelope.get("forbidden_files")):
        rejected_fields.add("forbidden_files")
        rejection_reasons.append(
            _reason(
                "FORBIDDEN_FILES_INVALID",
                "forbidden_files must be a list of strings.",
                {"actual": envelope.get("forbidden_files")},
            )
        )

    for field in ("timeout_limits", "network_policy", "secrets_policy", "destructive_operation_policy", "retry_policy"):
        if field in envelope and not _non_empty_dict(envelope.get(field)):
            rejected_fields.add(field)
            rejection_reasons.append(
                _reason(
                    "POLICY_FIELD_INVALID",
                    f"{field} must be a non-empty object.",
                    {"field": field, "actual": envelope.get(field)},
                )
            )

    forbidden_claims = _forbidden_truthy_claims(envelope, "envelope")
    if forbidden_claims:
        rejected_fields.update(item["path"] for item in forbidden_claims)
        rejection_reasons.append(
            _reason(
                "FORBIDDEN_ENVELOPE_AUTHORITY_CLAIM",
                "ExecutionEnvelope contains forbidden authority claims.",
                {"forbidden_claims": forbidden_claims},
            )
        )
        known_conflicts.extend(
            {"conflict_type": "authority_boundary", "path": item["path"], "claim": item["key"]}
            for item in forbidden_claims
        )

    result = _envelope_result(
        envelope=envelope,
        rejected_fields=sorted(rejected_fields),
        rejection_reasons=rejection_reasons,
        known_conflicts=known_conflicts,
    )
    assert_execution_envelope_result_contract(result)
    return result


def assert_execution_envelope_result_contract(result: dict[str, Any]) -> None:
    if not isinstance(result, dict):
        raise ExecutionEnvelopeError("ENVELOPE_RESULT_INVALID", "ExecutionEnvelope result must be an object.")
    if result.get("authority_boundary") != AUTHORITY_BOUNDARY_EXPECTATIONS:
        raise ExecutionEnvelopeError(
            "FORBIDDEN_ENVELOPE_RESULT_AUTHORITY_CLAIM",
            "ExecutionEnvelope result authority boundary must remain false.",
            details={"expected": AUTHORITY_BOUNDARY_EXPECTATIONS, "actual": result.get("authority_boundary")},
        )
    forbidden_claims = _forbidden_truthy_claims(result, "result")
    if forbidden_claims:
        raise ExecutionEnvelopeError(
            "FORBIDDEN_ENVELOPE_RESULT_CLAIM",
            "ExecutionEnvelope result contains forbidden authority claims.",
            details={"forbidden_claims": forbidden_claims},
        )


def _envelope_result(
    *,
    envelope: dict[str, Any],
    rejected_fields: list[str],
    rejection_reasons: list[dict[str, Any]],
    known_conflicts: list[dict[str, Any]],
) -> dict[str, Any]:
    passed = not rejection_reasons
    return {
        "envelope_check_result": ENVELOPE_CHECK_PASSED if passed else ENVELOPE_CHECK_FAILED_CLOSED,
        "validation_result": "passed" if passed else "failed_closed",
        "recognized_fields": [field for field in REQUIRED_ENVELOPE_FIELDS if field in envelope],
        "rejected_fields": rejected_fields,
        "rejection_reasons": rejection_reasons,
        "known_conflicts": known_conflicts,
        "authority_mode": envelope.get("authority_mode"),
        "version_taskbook_ref": envelope.get("version_taskbook_ref", {}),
        "master_taskbook_ref": envelope.get("master_taskbook_ref", {}),
        "stage_taskbook_ref": envelope.get("stage_taskbook_ref", {}),
        "authority_boundary": dict(AUTHORITY_BOUNDARY_EXPECTATIONS),
        "dispatch_authorized_by_envelope_existence": False,
        "executor_dispatch_authorized": False,
        "allowed_files_expansion_authorized": False,
        "plan_mutation_authorized": False,
        "commit_authorized": False,
        "push_authorized": False,
        "delivery_state_accepted": False,
        "creates_review_decision": False,
        "emits_gate_event": False,
        "writes_delivery_state": False,
    }


def _validate_ref(
    actual: Any,
    expected: dict[str, str],
    field: str,
    rejected_fields: set[str],
    rejection_reasons: list[dict[str, Any]],
    known_conflicts: list[dict[str, Any]],
) -> None:
    if not isinstance(actual, dict):
        rejected_fields.add(field)
        rejection_reasons.append(_reason("REFERENCE_MISSING", f"{field} must be an object.", {"field": field}))
        return
    for key, expected_value in expected.items():
        actual_value = actual.get(key)
        if actual_value != expected_value:
            rejected_fields.add(field)
            rejection_reasons.append(
                _reason(
                    "REFERENCE_MISMATCH",
                    f"{field}.{key} does not match expected reference.",
                    {"field": field, "key": key, "expected": expected_value, "actual": actual_value},
                )
            )
            known_conflicts.append(
                {"conflict_type": "reference_mismatch", "field": f"{field}.{key}", "expected": expected_value, "actual": actual_value}
            )


def _reason(code: str, message: str, details: dict[str, Any]) -> dict[str, Any]:
    return {"code": code, "message": message, "details": details}


def _non_empty_dict(value: Any) -> bool:
    return isinstance(value, dict) and bool(value)


def _string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) and item.strip() for item in value)


def _non_empty_string_list(value: Any) -> bool:
    return _string_list(value) and bool(value)


def _forbidden_truthy_claims(value: Any, path: str = "envelope") -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if str(key) in FORBIDDEN_ENVELOPE_CLAIM_KEYS and _truthy_claim(child):
                claims.append({"path": child_path, "key": str(key), "value": child})
            claims.extend(_forbidden_truthy_claims(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            claims.extend(_forbidden_truthy_claims(child, f"{path}[{index}]"))
    return claims


def _truthy_claim(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "accepted", "authorized", "allowed", "granted"}
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value != 0
    return False
