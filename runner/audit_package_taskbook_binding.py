from __future__ import annotations

from typing import Any


AUDIT_PACKAGE_READY = "audit_package_ready"
AUDIT_PACKAGE_FAILED_CLOSED = "audit_package_failed_closed"
READY_FOR_REVIEWER_HANDOFF = "ready_for_reviewer_handoff"
BLOCKED_MISSING_EVIDENCE = "blocked_missing_evidence"
BLOCKED_SCOPE_VIOLATION = "blocked_scope_violation"
BLOCKED_VALIDATION_FAILURE = "blocked_validation_failure"
BLOCKED_UNKNOWN_NEEDS_REVIEW = "blocked_unknown_needs_review"
VALID_HANDOFF_READINESS = frozenset(
    {
        READY_FOR_REVIEWER_HANDOFF,
        BLOCKED_MISSING_EVIDENCE,
        BLOCKED_SCOPE_VIOLATION,
        BLOCKED_VALIDATION_FAILURE,
        BLOCKED_UNKNOWN_NEEDS_REVIEW,
    }
)
REQUIRED_AUDIT_PACKAGE_FIELDS = frozenset(
    {
        "audit_package_id",
        "version_taskbook_ref",
        "master_taskbook_hash",
        "stage_taskbook_hash",
        "execution_envelope_ref",
        "run_preview_ref",
        "execution_receipt_refs",
        "executor_report_ref",
        "execution_evidence_receipt_ref",
        "validation_truth_summary_ref",
        "scope_evidence_pack_ref",
        "known_gaps",
        "remaining_risks",
        "handoff_readiness",
        "authority_boundary",
    }
)
AUTHORITY_BOUNDARY_EXPECTATIONS = {
    "audit_package_result_is_authority": False,
    "audit_package_completes_reviewer_handoff": False,
    "audit_package_self_accepts_review": False,
    "audit_package_writes_delivery_state": False,
    "audit_package_authorizes_executor_dispatch": False,
    "audit_package_authorizes_plan_mutation": False,
    "creates_review_decision": False,
    "emits_gate_event": False,
}
FORBIDDEN_AUDIT_PACKAGE_CLAIM_KEYS = frozenset(
    {
        "reviewer_handoff_completed",
        "review_accepted",
        "review_acceptance",
        "delivery_state_accepted",
        "executor_self_acceptance",
        "audit_package_result_is_authority",
        "audit_package_completes_reviewer_handoff",
        "audit_package_self_accepts_review",
        "audit_package_writes_delivery_state",
        "audit_package_authorizes_executor_dispatch",
        "audit_package_authorizes_plan_mutation",
        "creates_review_decision",
        "emits_gate_event",
        "writes_delivery_state",
    }
)


class AuditPackageTaskbookBindingError(ValueError):
    def __init__(self, error_code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.details = details or {}


def build_audit_package_taskbook_binding(
    *,
    audit_package_id: str,
    version_taskbook_ref: dict[str, Any],
    master_taskbook_hash: str,
    stage_taskbook_hash: str,
    execution_envelope_ref: dict[str, Any],
    run_preview_ref: dict[str, Any],
    execution_receipt_refs: list[dict[str, Any]],
    executor_report_ref: dict[str, Any],
    execution_evidence_receipt_ref: dict[str, Any],
    validation_truth_summary_ref: dict[str, Any],
    scope_evidence_pack_ref: dict[str, Any],
    validation_truth_statuses: list[str],
    scope_result: str,
    known_gaps: list[dict[str, Any]],
    remaining_risks: list[dict[str, Any]],
    extra_claims: dict[str, Any] | None = None,
    authority_boundary: dict[str, bool] | None = None,
) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    known_conflicts: list[dict[str, Any]] = []

    missing_refs = _missing_refs(
        {
            "version_taskbook_ref": version_taskbook_ref,
            "execution_envelope_ref": execution_envelope_ref,
            "run_preview_ref": run_preview_ref,
            "executor_report_ref": executor_report_ref,
            "execution_evidence_receipt_ref": execution_evidence_receipt_ref,
            "validation_truth_summary_ref": validation_truth_summary_ref,
            "scope_evidence_pack_ref": scope_evidence_pack_ref,
        },
        execution_receipt_refs,
    )
    handoff_readiness = _handoff_readiness(missing_refs, validation_truth_statuses, scope_result)

    if not isinstance(validation_truth_statuses, list):
        blockers.append(_blocker("VALIDATION_TRUTH_STATUSES_INVALID", "validation_truth_statuses must be a list.", {}))
    if not isinstance(known_gaps, list):
        blockers.append(_blocker("KNOWN_GAPS_INVALID", "known_gaps must be a list.", {}))
    if not isinstance(remaining_risks, list):
        blockers.append(_blocker("REMAINING_RISKS_INVALID", "remaining_risks must be a list.", {}))
    if scope_result not in {"in_scope", "out_of_scope", "unknown_needs_review"}:
        blockers.append(_blocker("SCOPE_RESULT_UNSUPPORTED", "scope_result is unsupported.", {"scope_result": scope_result}))

    boundary = authority_boundary if authority_boundary is not None else dict(AUTHORITY_BOUNDARY_EXPECTATIONS)
    if boundary != AUTHORITY_BOUNDARY_EXPECTATIONS:
        blockers.append(
            _blocker(
                "FORBIDDEN_AUDIT_PACKAGE_AUTHORITY_BOUNDARY",
                "Audit package authority boundary must remain false.",
                {"unexpected_truthy_keys": _truthy_authority_boundary_keys(boundary)},
            )
        )

    claims_source = extra_claims if isinstance(extra_claims, dict) else {}
    forbidden_claims = _forbidden_truthy_claims(claims_source, "extra_claims")
    if forbidden_claims:
        blockers.append(
            _blocker(
                "FORBIDDEN_AUDIT_PACKAGE_AUTHORITY_CLAIM",
                "Audit package contains forbidden authority claims.",
                {"forbidden_claims": _safe_forbidden_claims(forbidden_claims)},
            )
        )
        known_conflicts.extend(
            {"conflict_type": "authority_boundary", "path": item["path"], "claim": item["key"]}
            for item in forbidden_claims
        )

    package = {
        "audit_package_id": audit_package_id,
        "audit_package_status": AUDIT_PACKAGE_FAILED_CLOSED if blockers else AUDIT_PACKAGE_READY,
        "version_taskbook_ref": version_taskbook_ref,
        "master_taskbook_hash": master_taskbook_hash,
        "stage_taskbook_hash": stage_taskbook_hash,
        "execution_envelope_ref": execution_envelope_ref,
        "run_preview_ref": run_preview_ref,
        "execution_receipt_refs": execution_receipt_refs,
        "executor_report_ref": executor_report_ref,
        "execution_evidence_receipt_ref": execution_evidence_receipt_ref,
        "validation_truth_summary_ref": validation_truth_summary_ref,
        "scope_evidence_pack_ref": scope_evidence_pack_ref,
        "validation_truth_statuses": validation_truth_statuses,
        "scope_result": scope_result,
        "known_gaps": known_gaps,
        "remaining_risks": remaining_risks,
        "handoff_readiness": handoff_readiness,
        "missing_evidence_refs": missing_refs,
        "failures_and_blockers": blockers,
        "known_conflicts": known_conflicts,
        "authority_boundary": dict(AUTHORITY_BOUNDARY_EXPECTATIONS),
        "reviewer_handoff_completed": False,
        "review_accepted": False,
        "delivery_state_accepted": False,
        "executor_self_acceptance": False,
        "creates_review_decision": False,
        "emits_gate_event": False,
        "writes_delivery_state": False,
    }
    assert_audit_package_taskbook_binding_contract(package)
    return package


def assert_audit_package_taskbook_binding_contract(package: dict[str, Any]) -> None:
    if not isinstance(package, dict):
        raise AuditPackageTaskbookBindingError("AUDIT_PACKAGE_INVALID", "Audit package must be an object.")
    missing = sorted(REQUIRED_AUDIT_PACKAGE_FIELDS - set(package))
    if missing:
        raise AuditPackageTaskbookBindingError(
            "AUDIT_PACKAGE_REQUIRED_FIELD_MISSING",
            "Audit package is missing required fields.",
            details={"missing_fields": missing},
        )
    if package.get("handoff_readiness") not in VALID_HANDOFF_READINESS:
        raise AuditPackageTaskbookBindingError(
            "HANDOFF_READINESS_UNSUPPORTED",
            "Audit package handoff_readiness is unsupported.",
            details={"handoff_readiness": package.get("handoff_readiness")},
        )
    status = package.get("audit_package_status")
    blockers = _list_or_empty(package.get("failures_and_blockers"))
    if status == AUDIT_PACKAGE_READY and blockers:
        raise AuditPackageTaskbookBindingError(
            "AUDIT_PACKAGE_READY_WITH_BLOCKERS",
            "Ready audit package must not include hard blockers.",
            details={"blocking_codes": [item.get("code") for item in blockers if isinstance(item, dict)]},
        )
    if status == AUDIT_PACKAGE_FAILED_CLOSED and not blockers:
        raise AuditPackageTaskbookBindingError(
            "AUDIT_PACKAGE_FAILED_WITHOUT_BLOCKERS",
            "Failed audit package must include at least one blocker.",
        )
    if status not in {AUDIT_PACKAGE_READY, AUDIT_PACKAGE_FAILED_CLOSED}:
        raise AuditPackageTaskbookBindingError(
            "AUDIT_PACKAGE_STATUS_INVALID",
            "Audit package status is unsupported.",
            details={"audit_package_status": status},
        )
    if package.get("authority_boundary") != AUTHORITY_BOUNDARY_EXPECTATIONS:
        raise AuditPackageTaskbookBindingError(
            "FORBIDDEN_AUDIT_PACKAGE_AUTHORITY_CLAIM",
            "Audit package authority boundary must remain false.",
            details={"expected": AUTHORITY_BOUNDARY_EXPECTATIONS, "actual": package.get("authority_boundary")},
        )
    forbidden_claims = _forbidden_truthy_claims(package, "audit_package")
    if forbidden_claims:
        raise AuditPackageTaskbookBindingError(
            "FORBIDDEN_AUDIT_PACKAGE_RESULT_CLAIM",
            "Audit package contains forbidden authority claims.",
            details={"forbidden_claims": _safe_forbidden_claims(forbidden_claims)},
        )


def _handoff_readiness(missing_refs: list[str], validation_truth_statuses: Any, scope_result: str) -> str:
    if missing_refs:
        return BLOCKED_MISSING_EVIDENCE
    if scope_result == "out_of_scope":
        return BLOCKED_SCOPE_VIOLATION
    if isinstance(validation_truth_statuses, list) and any(status == "failed" for status in validation_truth_statuses):
        return BLOCKED_VALIDATION_FAILURE
    if scope_result == "unknown_needs_review":
        return BLOCKED_UNKNOWN_NEEDS_REVIEW
    return READY_FOR_REVIEWER_HANDOFF


def _missing_refs(refs: dict[str, Any], execution_receipt_refs: Any) -> list[str]:
    missing = [name for name, value in refs.items() if not _non_empty_dict(value)]
    if not isinstance(execution_receipt_refs, list) or not execution_receipt_refs:
        missing.append("execution_receipt_refs")
    return missing


def _blocker(code: str, message: str, details: dict[str, Any]) -> dict[str, Any]:
    return {"code": code, "message": message, "details": details, "blocking": True}


def _non_empty_dict(value: Any) -> bool:
    return isinstance(value, dict) and bool(value)


def _list_or_empty(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _truthy_authority_boundary_keys(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return []
    return [str(key) for key, child in value.items() if key in AUTHORITY_BOUNDARY_EXPECTATIONS and _truthy_claim(child)]


def _forbidden_truthy_claims(value: Any, path: str = "audit_package") -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if str(key) in FORBIDDEN_AUDIT_PACKAGE_CLAIM_KEYS and _truthy_claim(child):
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
        return value.strip().lower() in {"true", "yes", "accepted", "authorized", "allowed", "granted", "completed"}
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value != 0
    return False
