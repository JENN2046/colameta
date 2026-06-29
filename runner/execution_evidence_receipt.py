from __future__ import annotations

import re
from typing import Any

from runner.executor_report import (
    EXECUTOR_REPORT_READY,
    ExecutorReportError,
    assert_executor_report_contract,
)


EVIDENCE_RECEIPT_READY = "execution_evidence_receipt_ready"
EVIDENCE_RECEIPT_FAILED_CLOSED = "execution_evidence_receipt_failed_closed"
EXPECTED_EVIDENCE_RECEIPT_SCHEMA_VERSION = "execution_evidence_receipt.v1"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")

REQUIRED_EVIDENCE_RECEIPT_FIELDS = frozenset(
    {
        "evidence_receipt_id",
        "evidence_receipt_schema_version",
        "version_taskbook_ref",
        "master_taskbook_hash",
        "stage_taskbook_hash",
        "executor_report_refs",
        "execution_receipt_refs",
        "changed_files_summary_ref",
        "validation_truth_summary_ref",
        "scope_summary_ref",
        "evidence_hashes",
        "known_gaps",
        "remaining_risks",
        "authority_boundary",
    }
)
AUTHORITY_BOUNDARY_EXPECTATIONS = {
    "evidence_receipt_result_is_authority": False,
    "evidence_receipt_self_accepts_review": False,
    "evidence_receipt_writes_delivery_state": False,
    "evidence_receipt_authorizes_executor_dispatch": False,
    "evidence_receipt_authorizes_plan_mutation": False,
    "evidence_receipt_authorizes_commit": False,
    "evidence_receipt_authorizes_push": False,
    "creates_review_decision": False,
    "emits_gate_event": False,
}
FORBIDDEN_EVIDENCE_RECEIPT_CLAIM_KEYS = frozenset(
    {
        "review_accepted",
        "review_acceptance",
        "delivery_state_accepted",
        "executor_self_acceptance",
        "validation_passed_without_command_evidence",
        "evidence_receipt_result_is_authority",
        "evidence_receipt_self_accepts_review",
        "evidence_receipt_writes_delivery_state",
        "evidence_receipt_authorizes_executor_dispatch",
        "evidence_receipt_authorizes_plan_mutation",
        "evidence_receipt_authorizes_commit",
        "evidence_receipt_authorizes_push",
        "creates_review_decision",
        "emits_gate_event",
        "writes_delivery_state",
        "dispatch_authorized",
        "plan_mutation_authorized",
        "commit_authorized",
        "push_authorized",
    }
)


class ExecutionEvidenceReceiptError(ValueError):
    def __init__(self, error_code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.details = details or {}


def build_execution_evidence_receipt(
    *,
    evidence_receipt_id: str,
    version_taskbook_ref: dict[str, Any],
    master_taskbook_hash: str,
    stage_taskbook_hash: str,
    executor_report_records: list[dict[str, Any]],
    evidence_hashes: dict[str, Any],
) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    executor_report_refs: list[dict[str, Any]] = []
    execution_receipt_refs: list[dict[str, Any]] = []
    known_gaps: list[dict[str, Any]] = []
    remaining_risks: list[dict[str, Any]] = []
    known_conflicts: list[dict[str, Any]] = []
    changed_files_count = 0
    validation_truth_count = 0
    scope_summary_count = 0

    if not executor_report_records:
        blockers.append(_blocker("executor_report_records_missing", "Evidence receipt requires at least one executor report record.", {}))

    invalid_hashes = _invalid_hashes(evidence_hashes)
    if invalid_hashes:
        blockers.append(
            _blocker(
                "evidence_hashes_invalid",
                "Evidence receipt requires non-empty lowercase sha256 evidence hashes.",
                {"invalid_hash_keys": invalid_hashes},
            )
        )

    for index, record in enumerate(executor_report_records):
        if not isinstance(record, dict):
            blockers.append(_blocker("executor_report_record_invalid", "Executor report record must be an object.", {"index": index}))
            continue

        report_ref = record.get("executor_report_ref")
        report = record.get("executor_report")
        if not _non_empty_dict(report_ref):
            blockers.append(_blocker("executor_report_ref_missing", "Executor report record requires executor_report_ref.", {"index": index}))
        if not isinstance(report, dict):
            blockers.append(_blocker("executor_report_missing", "Executor report record requires executor_report.", {"index": index}))
            continue

        try:
            assert_executor_report_contract(report)
        except ExecutorReportError as exc:
            blockers.append(
                _blocker(
                    "executor_report_contract_failed",
                    "Executor report failed its authority-boundary contract.",
                    {"index": index, "executor_report_error_code": exc.error_code},
                )
            )
            known_conflicts.append(
                {
                    "conflict_type": "executor_report_contract",
                    "record_index": index,
                    "executor_report_error_code": exc.error_code,
                }
            )

        if report.get("report_status") != EXECUTOR_REPORT_READY:
            blockers.append(
                _blocker(
                    "executor_report_not_ready",
                    "Evidence receipt requires ready executor reports.",
                    {"index": index, "report_status": report.get("report_status")},
                )
            )

        forbidden_claims = _forbidden_truthy_claims(report, f"executor_report_records[{index}].executor_report")
        if forbidden_claims:
            blockers.append(
                _blocker(
                    "forbidden_evidence_receipt_authority_claim",
                    "Executor report contains forbidden authority claims for an evidence receipt.",
                    {"index": index, "forbidden_claims": _safe_forbidden_claims(forbidden_claims)},
                )
            )
            known_conflicts.extend(
                {"conflict_type": "authority_boundary", "path": item["path"], "claim": item["key"]}
                for item in forbidden_claims
            )

        if _non_empty_dict(report_ref):
            executor_report_refs.append(report_ref)

        report_receipt_refs = _list_or_empty(report.get("receipt_refs"))
        if not report_receipt_refs:
            blockers.append(_blocker("execution_receipt_refs_missing", "Executor report must expose execution receipt refs.", {"index": index}))
        execution_receipt_refs.extend(_with_report_ref(report_ref, item) for item in report_receipt_refs)
        changed_files_count += len(_list_or_empty(report.get("changed_files_summary")))
        validation_truth_count += len(_list_or_empty(report.get("validation_truth_summary")))
        scope_summary_count += len(_list_or_empty(report.get("scope_check_summary")))
        known_gaps.extend(_with_report_ref(report_ref, item) for item in _list_or_empty(report.get("known_gaps")))
        remaining_risks.extend(_with_report_ref(report_ref, item) for item in _list_or_empty(report.get("remaining_risks")))

    if changed_files_count == 0:
        blockers.append(_blocker("changed_files_summary_missing", "Evidence receipt requires a changed files summary ref.", {}))
    if validation_truth_count == 0:
        blockers.append(_blocker("validation_truth_summary_missing", "Evidence receipt requires a validation truth summary ref.", {}))
    if scope_summary_count == 0:
        blockers.append(_blocker("scope_summary_missing", "Evidence receipt requires a scope summary ref.", {}))

    receipt = {
        "evidence_receipt_id": evidence_receipt_id,
        "evidence_receipt_schema_version": EXPECTED_EVIDENCE_RECEIPT_SCHEMA_VERSION,
        "evidence_receipt_status": EVIDENCE_RECEIPT_FAILED_CLOSED if blockers else EVIDENCE_RECEIPT_READY,
        "version_taskbook_ref": version_taskbook_ref,
        "master_taskbook_hash": master_taskbook_hash,
        "stage_taskbook_hash": stage_taskbook_hash,
        "executor_report_refs": executor_report_refs,
        "execution_receipt_refs": execution_receipt_refs,
        "changed_files_summary_ref": {"source": "executor_report.changed_files_summary", "item_count": changed_files_count},
        "validation_truth_summary_ref": {"source": "executor_report.validation_truth_summary", "item_count": validation_truth_count},
        "scope_summary_ref": {"source": "executor_report.scope_check_summary", "item_count": scope_summary_count},
        "evidence_hashes": evidence_hashes if isinstance(evidence_hashes, dict) else {},
        "known_gaps": known_gaps,
        "remaining_risks": remaining_risks,
        "failures_and_blockers": blockers,
        "known_conflicts": known_conflicts,
        "authority_boundary": dict(AUTHORITY_BOUNDARY_EXPECTATIONS),
        "review_accepted": False,
        "delivery_state_accepted": False,
        "executor_self_acceptance": False,
        "dispatch_authorized": False,
        "plan_mutation_authorized": False,
        "commit_authorized": False,
        "push_authorized": False,
        "creates_review_decision": False,
        "emits_gate_event": False,
        "writes_delivery_state": False,
    }
    assert_execution_evidence_receipt_contract(receipt)
    return receipt


def assert_execution_evidence_receipt_contract(receipt: dict[str, Any]) -> None:
    if not isinstance(receipt, dict):
        raise ExecutionEvidenceReceiptError("EVIDENCE_RECEIPT_INVALID", "Execution evidence receipt must be an object.")
    missing = sorted(REQUIRED_EVIDENCE_RECEIPT_FIELDS - set(receipt))
    if missing:
        raise ExecutionEvidenceReceiptError(
            "EVIDENCE_RECEIPT_REQUIRED_FIELD_MISSING",
            "Execution evidence receipt is missing required fields.",
            details={"missing_fields": missing},
        )
    status = receipt.get("evidence_receipt_status")
    if status not in {EVIDENCE_RECEIPT_READY, EVIDENCE_RECEIPT_FAILED_CLOSED}:
        raise ExecutionEvidenceReceiptError(
            "EVIDENCE_RECEIPT_STATUS_INVALID",
            "Execution evidence receipt status is unsupported.",
            details={"evidence_receipt_status": status},
        )
    blockers = _list_or_empty(receipt.get("failures_and_blockers"))
    if status == EVIDENCE_RECEIPT_READY and blockers:
        raise ExecutionEvidenceReceiptError(
            "EVIDENCE_RECEIPT_READY_WITH_BLOCKERS",
            "Ready evidence receipt must not include blockers.",
            details={"blocking_codes": [item.get("code") for item in blockers if isinstance(item, dict)]},
        )
    if status == EVIDENCE_RECEIPT_FAILED_CLOSED and not blockers:
        raise ExecutionEvidenceReceiptError(
            "EVIDENCE_RECEIPT_FAILED_WITHOUT_BLOCKERS",
            "Failed evidence receipt must include at least one blocker.",
        )
    if receipt.get("authority_boundary") != AUTHORITY_BOUNDARY_EXPECTATIONS:
        raise ExecutionEvidenceReceiptError(
            "FORBIDDEN_EVIDENCE_RECEIPT_AUTHORITY_CLAIM",
            "Execution evidence receipt authority boundary must remain false.",
            details={"expected": AUTHORITY_BOUNDARY_EXPECTATIONS, "actual": receipt.get("authority_boundary")},
        )
    forbidden_claims = _forbidden_truthy_claims(receipt, "evidence_receipt")
    if forbidden_claims:
        raise ExecutionEvidenceReceiptError(
            "FORBIDDEN_EVIDENCE_RECEIPT_RESULT_CLAIM",
            "Execution evidence receipt contains forbidden authority claims.",
            details={"forbidden_claims": _safe_forbidden_claims(forbidden_claims)},
        )


def _invalid_hashes(value: Any) -> list[str]:
    if not isinstance(value, dict) or not value:
        return ["<missing>"]
    return [str(key) for key, child in value.items() if not (isinstance(child, str) and SHA256_PATTERN.fullmatch(child))]


def _with_report_ref(report_ref: Any, item: Any) -> dict[str, Any]:
    return {"executor_report_ref": report_ref if isinstance(report_ref, dict) else {}, "item": item}


def _blocker(code: str, message: str, details: dict[str, Any]) -> dict[str, Any]:
    return {"code": code, "message": message, "details": details, "blocking": True}


def _non_empty_dict(value: Any) -> bool:
    return isinstance(value, dict) and bool(value)


def _list_or_empty(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _forbidden_truthy_claims(value: Any, path: str = "evidence_receipt") -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if str(key) in FORBIDDEN_EVIDENCE_RECEIPT_CLAIM_KEYS and _truthy_claim(child):
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
