from __future__ import annotations

from typing import Any

from runner.validation_truth import (
    legacy_evidence_provenance_projection,
    validate_evidence_provenance,
)
from runner.work_item_governance.references import (
    optional_work_item_reference_projection,
    optional_work_item_reference_rejections,
)


RECEIPT_CHECK_PASSED = "receipt_check_passed"
RECEIPT_CHECK_FAILED_CLOSED = "receipt_check_failed_closed"
EXPECTED_RECEIPT_SCHEMA_VERSION = "local_execution_receipt.v1"
EXPECTED_RECEIPT_KIND = "local_execution_receipt"
REQUIRED_RECEIPT_FIELDS = (
    "receipt_id",
    "receipt_schema_version",
    "receipt_kind",
    "local_execution_authorization_ref",
    "execution_envelope_ref",
    "run_preview_ref",
    "version_taskbook_ref",
    "master_taskbook_hash",
    "stage_taskbook_hash",
    "started_at",
    "completed_at",
    "execution_result",
    "command_attempts",
    "touched_files",
    "observed_mutations",
    "validation_commands",
    "validation_results",
    "scope_check_result",
    "blocked_or_failed_reasons",
    "known_gaps",
    "remaining_risks",
)
VALID_EXECUTION_RESULTS = frozenset(
    {
        "executed",
        "executed_with_failures",
        "blocked_before_execution",
        "failed_scope_check",
    }
)
VALID_VALIDATION_RESULTS = frozenset({"passed", "failed", "blocked", "not_run", "unvalidated"})
AUTHORITY_BOUNDARY_EXPECTATIONS = {
    "receipt_result_is_authority": False,
    "receipt_self_accepts_review": False,
    "receipt_writes_delivery_state": False,
    "receipt_authorizes_plan_mutation": False,
    "receipt_authorizes_commit": False,
    "receipt_authorizes_push": False,
    "creates_review_decision": False,
    "emits_gate_event": False,
}
FORBIDDEN_RECEIPT_CLAIM_KEYS = frozenset(
    {
        "review_accepted",
        "delivery_state_accepted",
        "plan_mutation_authorized",
        "commit_authorized",
        "push_authorized",
        "review_acceptance",
        "receipt_result_is_authority",
        "receipt_self_accepts_review",
        "receipt_writes_delivery_state",
        "receipt_authorizes_plan_mutation",
        "receipt_authorizes_commit",
        "receipt_authorizes_push",
        "creates_review_decision",
        "emits_gate_event",
        "writes_delivery_state",
    }
)


class LocalExecutionReceiptError(ValueError):
    def __init__(self, error_code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.details = details or {}


def validate_local_execution_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    rejected_fields: set[str] = set()
    rejection_reasons: list[dict[str, Any]] = []
    known_conflicts: list[dict[str, Any]] = []
    if not isinstance(receipt, dict):
        return _receipt_result(
            receipt={},
            rejected_fields=[],
            rejection_reasons=[
                _reason("RECEIPT_INVALID", "Local execution receipt must be an object.", {"actual_type": type(receipt).__name__})
            ],
            known_conflicts=[],
        )

    missing = [field for field in REQUIRED_RECEIPT_FIELDS if field not in receipt]
    if missing:
        rejected_fields.update(missing)
        rejection_reasons.append(
            _reason("REQUIRED_FIELD_MISSING", "Local execution receipt is missing required fields.", {"missing_fields": missing})
        )

    if receipt.get("receipt_schema_version") != EXPECTED_RECEIPT_SCHEMA_VERSION:
        rejected_fields.add("receipt_schema_version")
        rejection_reasons.append(
            _reason(
                "RECEIPT_SCHEMA_VERSION_UNSUPPORTED",
                "Local execution receipt schema version is unsupported.",
                {"expected": EXPECTED_RECEIPT_SCHEMA_VERSION, "actual": receipt.get("receipt_schema_version")},
            )
        )
    if receipt.get("receipt_kind") != EXPECTED_RECEIPT_KIND:
        rejected_fields.add("receipt_kind")
        rejection_reasons.append(
            _reason(
                "RECEIPT_KIND_UNSUPPORTED",
                "Local execution receipt kind is unsupported.",
                {"expected": EXPECTED_RECEIPT_KIND, "actual": receipt.get("receipt_kind")},
            )
        )

    execution_result = receipt.get("execution_result")
    if execution_result not in VALID_EXECUTION_RESULTS:
        rejected_fields.add("execution_result")
        rejection_reasons.append(
            _reason(
                "EXECUTION_RESULT_UNSUPPORTED",
                "Local execution receipt execution_result is unsupported.",
                {"actual": execution_result, "valid_execution_results": sorted(VALID_EXECUTION_RESULTS)},
            )
        )

    for field in ("local_execution_authorization_ref", "execution_envelope_ref", "run_preview_ref", "version_taskbook_ref"):
        if field in receipt and not _non_empty_dict(receipt.get(field)):
            rejected_fields.add(field)
            rejection_reasons.append(_reason("REFERENCE_FIELD_INVALID", f"{field} must be a non-empty object.", {"field": field}))

    work_item_rejections = optional_work_item_reference_rejections(receipt)
    for rejection in work_item_rejections:
        rejected_fields.add(str(rejection["field"]))
        rejection_reasons.append(
            _reason(
                str(rejection["code"]),
                "Optional Work Item receipt binding is invalid or incomplete.",
                {"field": rejection["field"]},
            )
        )

    command_attempts = receipt.get("command_attempts")
    if execution_result in {"executed", "executed_with_failures"} and not _non_empty_list(command_attempts):
        rejected_fields.add("command_attempts")
        rejection_reasons.append(
            _reason("COMMAND_ATTEMPTS_MISSING", "Executed receipts must include command attempts.", {"execution_result": execution_result})
        )

    touched_files = receipt.get("touched_files")
    if not isinstance(touched_files, list):
        rejected_fields.add("touched_files")
        rejection_reasons.append(_reason("TOUCHED_FILES_INVALID", "touched_files must be a list.", {"actual": touched_files}))
    elif touched_files == [] and not _known_gap_present(receipt, "touched_files_unknown"):
        rejected_fields.add("touched_files")
        rejection_reasons.append(
            _reason(
                "TOUCHED_FILES_UNKNOWN_WITHOUT_KNOWN_GAP",
                "Empty touched_files must be explained as a known gap.",
                {"known_gaps": receipt.get("known_gaps")},
            )
        )

    if "observed_mutations" in receipt and not isinstance(receipt.get("observed_mutations"), list):
        rejected_fields.add("observed_mutations")
        rejection_reasons.append(_reason("OBSERVED_MUTATIONS_INVALID", "observed_mutations must be a list.", {}))

    validation_results = receipt.get("validation_results")
    invalid_validation_results = _invalid_validation_results(validation_results)
    if invalid_validation_results:
        rejected_fields.add("validation_results")
        rejection_reasons.append(
            _reason(
                "VALIDATION_RESULTS_INVALID",
                "validation_results must list supported validation result values.",
                {"invalid_validation_results": invalid_validation_results},
            )
        )
    if _has_failed_validation(validation_results) and receipt.get("validation_summary") == "passed":
        rejected_fields.add("validation_summary")
        rejection_reasons.append(
            _reason(
                "VALIDATION_FAILED_BUT_SUMMARY_CLAIMS_PASSED",
                "Receipt cannot summarize validation as passed when validation_results include failure.",
                {"validation_summary": receipt.get("validation_summary")},
            )
        )

    if "scope_check_result" in receipt and receipt.get("scope_check_result") not in {"passed", "failed", "blocked", "not_run"}:
        rejected_fields.add("scope_check_result")
        rejection_reasons.append(
            _reason(
                "SCOPE_CHECK_RESULT_UNSUPPORTED",
                "scope_check_result is unsupported.",
                {"actual": receipt.get("scope_check_result")},
            )
        )

    forbidden_claims = _forbidden_truthy_claims(receipt, "receipt")
    if forbidden_claims:
        rejected_fields.update(item["path"] for item in forbidden_claims)
        rejection_reasons.append(
            _reason(
                "FORBIDDEN_RECEIPT_AUTHORITY_CLAIM",
                "Local execution receipt contains forbidden authority claims.",
                {"forbidden_claims": forbidden_claims},
            )
        )
        known_conflicts.extend(
            {"conflict_type": "authority_boundary", "path": item["path"], "claim": item["key"]}
            for item in forbidden_claims
        )

    provenance = validate_evidence_provenance(
        receipt,
        record_id=receipt.get("receipt_id"),
        record_schema_version=receipt.get("receipt_schema_version"),
        subject_specs={
            "$": {
                "evidence_subject": "execution",
                "subject_operation_completed": execution_result
                in {"executed", "executed_with_failures"},
            }
        },
        base_valid=not rejection_reasons,
    )
    if provenance["rejection_reasons"]:
        rejected_fields.add("evidence_provenance")
        rejection_reasons.extend(provenance["rejection_reasons"])
        known_conflicts.extend(provenance["known_conflicts"])

    result = _receipt_result(
        receipt=receipt,
        rejected_fields=sorted(rejected_fields),
        rejection_reasons=rejection_reasons,
        known_conflicts=known_conflicts,
        evidence_provenance=provenance["projection"],
    )
    assert_local_execution_receipt_result_contract(result)
    return result


def assert_local_execution_receipt_result_contract(result: dict[str, Any]) -> None:
    if not isinstance(result, dict):
        raise LocalExecutionReceiptError("RECEIPT_RESULT_INVALID", "Local execution receipt result must be an object.")
    if result.get("authority_boundary") != AUTHORITY_BOUNDARY_EXPECTATIONS:
        raise LocalExecutionReceiptError(
            "FORBIDDEN_RECEIPT_RESULT_AUTHORITY_CLAIM",
            "Local execution receipt result authority boundary must remain false.",
            details={"expected": AUTHORITY_BOUNDARY_EXPECTATIONS, "actual": result.get("authority_boundary")},
        )
    forbidden_claims = _forbidden_truthy_claims(result, "result")
    if forbidden_claims:
        raise LocalExecutionReceiptError(
            "FORBIDDEN_RECEIPT_RESULT_CLAIM",
            "Local execution receipt result contains forbidden authority claims.",
            details={"forbidden_claims": forbidden_claims},
        )


def _receipt_result(
    *,
    receipt: dict[str, Any],
    rejected_fields: list[str],
    rejection_reasons: list[dict[str, Any]],
    known_conflicts: list[dict[str, Any]],
    evidence_provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    passed = not rejection_reasons
    result = {
        "receipt_check_result": RECEIPT_CHECK_PASSED if passed else RECEIPT_CHECK_FAILED_CLOSED,
        "validation_result": "passed" if passed else "failed_closed",
        "recognized_fields": [field for field in REQUIRED_RECEIPT_FIELDS if field in receipt],
        "rejected_fields": rejected_fields,
        "rejection_reasons": rejection_reasons,
        "known_conflicts": known_conflicts,
        "evidence_provenance": evidence_provenance or legacy_evidence_provenance_projection(),
        "execution_result": receipt.get("execution_result"),
        "validation_results": receipt.get("validation_results", []),
        "scope_check_result": receipt.get("scope_check_result"),
        "truth_distinction": {
            "executed_is_reviewed": False,
            "validated_is_reviewed": False,
            "reviewed_is_accepted": False,
            "receipt_self_accepts_delivery": False,
        },
        "authority_boundary": dict(AUTHORITY_BOUNDARY_EXPECTATIONS),
        "review_accepted": False,
        "delivery_state_accepted": False,
        "plan_mutation_authorized": False,
        "commit_authorized": False,
        "push_authorized": False,
        "creates_review_decision": False,
        "emits_gate_event": False,
        "writes_delivery_state": False,
    }
    result.update(optional_work_item_reference_projection(receipt))
    return result


def _invalid_validation_results(value: Any) -> list[Any]:
    if not isinstance(value, list):
        return [{"reason": "not_list", "actual": value}]
    invalid = []
    for item in value:
        if not isinstance(item, dict) or item.get("result") not in VALID_VALIDATION_RESULTS:
            invalid.append(item)
    return invalid


def _has_failed_validation(value: Any) -> bool:
    return isinstance(value, list) and any(isinstance(item, dict) and item.get("result") == "failed" for item in value)


def _known_gap_present(receipt: dict[str, Any], gap_id: str) -> bool:
    gaps = receipt.get("known_gaps")
    return isinstance(gaps, list) and any(isinstance(item, dict) and item.get("gap_id") == gap_id for item in gaps)


def _reason(code: str, message: str, details: dict[str, Any]) -> dict[str, Any]:
    return {"code": code, "message": message, "details": details}


def _non_empty_dict(value: Any) -> bool:
    return isinstance(value, dict) and bool(value)


def _non_empty_list(value: Any) -> bool:
    return isinstance(value, list) and bool(value)


def _forbidden_truthy_claims(value: Any, path: str = "receipt") -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if str(key) in FORBIDDEN_RECEIPT_CLAIM_KEYS and _truthy_claim(child):
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
