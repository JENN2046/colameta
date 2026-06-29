from __future__ import annotations

from typing import Any


VALIDATION_TRUTH_CHECK_PASSED = "validation_truth_check_passed"
VALIDATION_TRUTH_CHECK_FAILED_CLOSED = "validation_truth_check_failed_closed"
VALID_EXECUTION_STATUSES = frozenset({"passed", "failed", "blocked", "not_run", "unvalidated"})
REQUIRED_VALIDATION_TRUTH_FIELDS = (
    "validation_truth_id",
    "validation_command",
    "command_source_ref",
    "execution_status",
    "exit_code",
    "output_summary",
    "evidence_ref",
    "failure_reason",
    "blocker_reason",
    "known_gaps",
    "authority_boundary",
)
AUTHORITY_BOUNDARY_EXPECTATIONS = {
    "validation_truth_result_is_authority": False,
    "runtime_label_alone_as_truth": False,
    "validation_truth_self_accepts_review": False,
    "validation_truth_writes_delivery_state": False,
    "validation_truth_authorizes_executor_dispatch": False,
    "validation_truth_authorizes_plan_mutation": False,
    "creates_review_decision": False,
    "emits_gate_event": False,
}
FORBIDDEN_VALIDATION_TRUTH_CLAIM_KEYS = frozenset(
    {
        "failed_summarized_as_passed",
        "not_run_summarized_as_passed",
        "unvalidated_summarized_as_passed",
        "runtime_label_alone_as_truth",
        "delivery_state_accepted",
        "review_accepted",
        "review_acceptance",
        "validation_truth_result_is_authority",
        "validation_truth_self_accepts_review",
        "validation_truth_writes_delivery_state",
        "validation_truth_authorizes_executor_dispatch",
        "validation_truth_authorizes_plan_mutation",
        "creates_review_decision",
        "emits_gate_event",
        "writes_delivery_state",
    }
)


class ValidationTruthError(ValueError):
    def __init__(self, error_code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.details = details or {}


def validate_validation_truth(truth: dict[str, Any]) -> dict[str, Any]:
    rejected_fields: set[str] = set()
    rejection_reasons: list[dict[str, Any]] = []
    known_conflicts: list[dict[str, Any]] = []

    if not isinstance(truth, dict):
        return _validation_truth_result(
            truth={},
            rejected_fields=[],
            rejection_reasons=[
                _reason(
                    "VALIDATION_TRUTH_INVALID",
                    "Validation truth must be an object.",
                    {"actual_type": type(truth).__name__},
                )
            ],
            known_conflicts=[],
        )

    missing = [field for field in REQUIRED_VALIDATION_TRUTH_FIELDS if field not in truth]
    if missing:
        rejected_fields.update(missing)
        rejection_reasons.append(
            _reason("REQUIRED_FIELD_MISSING", "Validation truth is missing required fields.", {"missing_fields": missing})
        )

    execution_status = truth.get("execution_status")
    if execution_status not in VALID_EXECUTION_STATUSES:
        rejected_fields.add("execution_status")
        rejection_reasons.append(
            _reason(
                "EXECUTION_STATUS_UNSUPPORTED",
                "Validation truth execution_status is unsupported.",
                {"actual": execution_status, "valid_execution_statuses": sorted(VALID_EXECUTION_STATUSES)},
            )
        )

    if "command_source_ref" in truth and not _non_empty_dict(truth.get("command_source_ref")):
        rejected_fields.add("command_source_ref")
        rejection_reasons.append(
            _reason("COMMAND_SOURCE_REF_INVALID", "command_source_ref must be a non-empty object.", {})
        )
    if "evidence_ref" in truth and execution_status == "passed" and not _non_empty_dict(truth.get("evidence_ref")):
        rejected_fields.add("evidence_ref")
        rejection_reasons.append(_reason("PASSED_WITHOUT_EVIDENCE_REF", "Passed validation requires evidence_ref.", {}))

    exit_code = truth.get("exit_code")
    if execution_status == "passed" and exit_code != 0:
        rejected_fields.add("exit_code")
        rejection_reasons.append(_reason("PASSED_EXIT_CODE_INVALID", "Passed validation requires exit_code 0.", {"exit_code": exit_code}))
    if execution_status == "failed" and (not isinstance(exit_code, int) or exit_code == 0):
        rejected_fields.add("exit_code")
        rejection_reasons.append(
            _reason("FAILED_EXIT_CODE_INVALID", "Failed validation requires a non-zero integer exit_code.", {"exit_code": exit_code})
        )

    if execution_status == "failed" and not _non_empty_text(truth.get("failure_reason")):
        rejected_fields.add("failure_reason")
        rejection_reasons.append(_reason("FAILED_WITHOUT_FAILURE_REASON", "Failed validation requires failure_reason.", {}))
    if execution_status in {"blocked", "not_run"} and not _non_empty_text(truth.get("blocker_reason")):
        rejected_fields.add("blocker_reason")
        rejection_reasons.append(
            _reason("BLOCKED_OR_NOT_RUN_WITHOUT_BLOCKER_REASON", "Blocked and not_run validation require blocker_reason.", {})
        )
    if execution_status == "unvalidated" and not _non_empty_list(truth.get("known_gaps")):
        rejected_fields.add("known_gaps")
        rejection_reasons.append(_reason("UNVALIDATED_WITHOUT_KNOWN_GAP", "Unvalidated status requires known_gaps.", {}))

    summary_status = truth.get("summary_status")
    if summary_status == "passed" and execution_status in {"failed", "blocked", "not_run", "unvalidated"}:
        rejected_fields.add("summary_status")
        rejection_reasons.append(
            _reason(
                f"{execution_status.upper()}_SUMMARIZED_AS_PASSED",
                "Validation truth cannot summarize non-passed execution as passed.",
                {"execution_status": execution_status, "summary_status": summary_status},
            )
        )

    if truth.get("runtime_label") == "PASSED" and (not _non_empty_dict(truth.get("evidence_ref")) or not _non_empty_dict(truth.get("command_source_ref"))):
        rejected_fields.add("runtime_label")
        rejection_reasons.append(
            _reason(
                "RUNTIME_LABEL_ALONE_AS_TRUTH",
                "Runtime PASSED label alone is not validation truth.",
                {"runtime_label": truth.get("runtime_label")},
            )
        )

    if "authority_boundary" in truth and truth.get("authority_boundary") != AUTHORITY_BOUNDARY_EXPECTATIONS:
        rejected_fields.add("authority_boundary")
        rejection_reasons.append(
            _reason(
                "FORBIDDEN_VALIDATION_TRUTH_AUTHORITY_BOUNDARY",
                "Validation truth authority boundary must remain false.",
                {"unexpected_truthy_keys": _truthy_authority_boundary_keys(truth.get("authority_boundary"))},
            )
        )

    forbidden_claims = _forbidden_truthy_claims(truth, "validation_truth")
    if forbidden_claims:
        rejected_fields.update(item["path"] for item in forbidden_claims)
        rejection_reasons.append(
            _reason(
                "FORBIDDEN_VALIDATION_TRUTH_AUTHORITY_CLAIM",
                "Validation truth contains forbidden authority claims.",
                {"forbidden_claims": _safe_forbidden_claims(forbidden_claims)},
            )
        )
        known_conflicts.extend(
            {"conflict_type": "authority_boundary", "path": item["path"], "claim": item["key"]}
            for item in forbidden_claims
        )

    result = _validation_truth_result(
        truth=truth,
        rejected_fields=sorted(rejected_fields),
        rejection_reasons=rejection_reasons,
        known_conflicts=known_conflicts,
    )
    assert_validation_truth_result_contract(result)
    return result


def assert_validation_truth_result_contract(result: dict[str, Any]) -> None:
    if not isinstance(result, dict):
        raise ValidationTruthError("VALIDATION_TRUTH_RESULT_INVALID", "Validation truth result must be an object.")
    if result.get("authority_boundary") != AUTHORITY_BOUNDARY_EXPECTATIONS:
        raise ValidationTruthError(
            "FORBIDDEN_VALIDATION_TRUTH_RESULT_AUTHORITY_CLAIM",
            "Validation truth result authority boundary must remain false.",
            details={"expected": AUTHORITY_BOUNDARY_EXPECTATIONS, "actual": result.get("authority_boundary")},
        )
    forbidden_claims = _forbidden_truthy_claims(result, "result")
    if forbidden_claims:
        raise ValidationTruthError(
            "FORBIDDEN_VALIDATION_TRUTH_RESULT_CLAIM",
            "Validation truth result contains forbidden authority claims.",
            details={"forbidden_claims": _safe_forbidden_claims(forbidden_claims)},
        )


def _validation_truth_result(
    *,
    truth: dict[str, Any],
    rejected_fields: list[str],
    rejection_reasons: list[dict[str, Any]],
    known_conflicts: list[dict[str, Any]],
) -> dict[str, Any]:
    passed = not rejection_reasons
    return {
        "validation_truth_check_result": VALIDATION_TRUTH_CHECK_PASSED if passed else VALIDATION_TRUTH_CHECK_FAILED_CLOSED,
        "validation_result": "passed" if passed else "failed_closed",
        "recognized_fields": [field for field in REQUIRED_VALIDATION_TRUTH_FIELDS if field in truth],
        "rejected_fields": rejected_fields,
        "rejection_reasons": rejection_reasons,
        "known_conflicts": known_conflicts,
        "execution_status": truth.get("execution_status"),
        "summary_status": truth.get("summary_status"),
        "truth_boundary": {
            "runtime_label_alone_as_truth": False,
            "failed_can_be_summarized_as_passed": False,
            "not_run_can_be_summarized_as_passed": False,
            "unvalidated_can_be_summarized_as_passed": False,
            "validation_truth_accepts_delivery": False,
        },
        "authority_boundary": dict(AUTHORITY_BOUNDARY_EXPECTATIONS),
        "review_accepted": False,
        "delivery_state_accepted": False,
        "creates_review_decision": False,
        "emits_gate_event": False,
        "writes_delivery_state": False,
    }


def _reason(code: str, message: str, details: dict[str, Any]) -> dict[str, Any]:
    return {"code": code, "message": message, "details": details}


def _non_empty_dict(value: Any) -> bool:
    return isinstance(value, dict) and bool(value)


def _non_empty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _non_empty_list(value: Any) -> bool:
    return isinstance(value, list) and bool(value)


def _truthy_authority_boundary_keys(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return []
    return [str(key) for key, child in value.items() if key in AUTHORITY_BOUNDARY_EXPECTATIONS and _truthy_claim(child)]


def _forbidden_truthy_claims(value: Any, path: str = "validation_truth") -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if str(key) in FORBIDDEN_VALIDATION_TRUTH_CLAIM_KEYS and _truthy_claim(child):
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
        return value.strip().lower() in {"true", "yes", "accepted", "authorized", "allowed", "granted"}
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value != 0
    return False
