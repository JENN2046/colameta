from __future__ import annotations

from typing import Any

from runner.work_item_governance.references import optional_work_item_reference_rejections


EXECUTOR_REPORT_READY = "executor_report_ready"
EXECUTOR_REPORT_FAILED_CLOSED = "executor_report_failed_closed"
EXPECTED_REPORT_SCHEMA_VERSION = "executor_report.v1"
VALID_AUTHORITY_MODES = frozenset({"local_execution", "imported_execution"})
REQUIRED_EXECUTOR_REPORT_FIELDS = frozenset(
    {
        "executor_report_id",
        "report_schema_version",
        "version_taskbook_ref",
        "master_taskbook_hash",
        "stage_taskbook_hash",
        "receipt_refs",
        "authority_modes",
        "command_result_summary",
        "changed_files_summary",
        "validation_truth_summary",
        "scope_check_summary",
        "failures_and_blockers",
        "known_gaps",
        "remaining_risks",
        "authority_boundary",
    }
)

AUTHORITY_BOUNDARY_EXPECTATIONS = {
    "executor_report_result_is_authority": False,
    "executor_report_authorizes_executor_dispatch": False,
    "executor_report_authorizes_local_execution": False,
    "executor_report_adopts_imported_receipt": False,
    "executor_report_self_accepts_review": False,
    "executor_report_writes_delivery_state": False,
    "executor_report_authorizes_plan_mutation": False,
    "executor_report_authorizes_commit": False,
    "executor_report_authorizes_push": False,
    "creates_review_decision": False,
    "emits_gate_event": False,
}
FORBIDDEN_EXECUTOR_REPORT_CLAIM_KEYS = frozenset(
    {
        "receipt_without_ref",
        "validation_passed_without_command_evidence",
        "review_accepted",
        "review_acceptance",
        "delivery_state_accepted",
        "executor_self_acceptance",
        "executor_report_result_is_authority",
        "executor_report_authorizes_executor_dispatch",
        "executor_report_authorizes_local_execution",
        "executor_report_adopts_imported_receipt",
        "executor_report_self_accepts_review",
        "executor_report_writes_delivery_state",
        "executor_report_authorizes_plan_mutation",
        "executor_report_authorizes_commit",
        "executor_report_authorizes_push",
        "creates_review_decision",
        "emits_gate_event",
        "writes_delivery_state",
        "dispatch_authorized",
        "local_execution_authorized",
        "imported_receipt_adopted_as_fact",
        "plan_mutation_authorized",
        "commit_authorized",
        "push_authorized",
    }
)


class ExecutorReportError(ValueError):
    def __init__(self, error_code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.details = details or {}


def build_executor_report(
    *,
    executor_report_id: str,
    version_taskbook_ref: dict[str, Any],
    master_taskbook_hash: str,
    stage_taskbook_hash: str,
    receipt_records: list[dict[str, Any]],
    work_item_id: str | None = None,
    task_version: int | None = None,
    attempt_id: str | None = None,
    artifact_refs: list[str] | None = None,
) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    receipt_refs: list[dict[str, Any]] = []
    authority_modes: set[str] = set()
    command_result_summary: list[dict[str, Any]] = []
    changed_files_summary: list[dict[str, Any]] = []
    validation_truth_summary: list[dict[str, Any]] = []
    scope_check_summary: list[dict[str, Any]] = []
    failures_and_blockers: list[dict[str, Any]] = []
    known_gaps: list[dict[str, Any]] = []
    remaining_risks: list[dict[str, Any]] = []
    known_conflicts: list[dict[str, Any]] = []

    work_item_binding: dict[str, Any] = {}
    if any(value is not None for value in (work_item_id, task_version, attempt_id, artifact_refs)):
        work_item_binding = {
            "work_item_id": work_item_id,
            "task_version": task_version,
            "attempt_id": attempt_id,
            "artifact_refs": list(artifact_refs or []),
        }
        for rejection in optional_work_item_reference_rejections(work_item_binding):
            blockers.append(
                _blocker(
                    str(rejection["code"]).lower(),
                    "Executor report Work Item binding is invalid or incomplete.",
                    {"field": rejection["field"]},
                )
            )

    if not receipt_records:
        blockers.append(_blocker("receipt_records_missing", "Executor report requires at least one receipt record.", {}))

    for index, record in enumerate(receipt_records):
        if not isinstance(record, dict):
            blockers.append(_blocker("receipt_record_invalid", "Receipt record must be an object.", {"index": index}))
            continue

        receipt_ref = record.get("receipt_ref")
        authority_mode = record.get("authority_mode")
        receipt = record.get("receipt")
        receipt_validation_result = record.get("receipt_validation_result")

        if not _non_empty_dict(receipt_ref):
            blockers.append(_blocker("receipt_ref_missing", "Every report claim must bind to a receipt_ref.", {"index": index}))
        if authority_mode not in VALID_AUTHORITY_MODES:
            blockers.append(
                _blocker(
                    "authority_mode_unsupported",
                    "Receipt record authority_mode is unsupported.",
                    {"index": index, "authority_mode": authority_mode, "valid_authority_modes": sorted(VALID_AUTHORITY_MODES)},
                )
            )
        else:
            authority_modes.add(authority_mode)
        if not isinstance(receipt, dict):
            blockers.append(_blocker("receipt_missing", "Receipt record must include the source receipt object.", {"index": index}))
        if not isinstance(receipt_validation_result, dict):
            blockers.append(
                _blocker("receipt_validation_result_missing", "Receipt record must include receipt_validation_result.", {"index": index})
            )

        forbidden_claims = _forbidden_truthy_claims(record, f"receipt_records[{index}]")
        if forbidden_claims:
            blockers.append(
                _blocker(
                    "forbidden_report_authority_claim",
                    "Receipt record contains forbidden authority claims.",
                    {"index": index, "forbidden_claims": _safe_forbidden_claims(forbidden_claims)},
                )
            )
            known_conflicts.extend(
                {"conflict_type": "authority_boundary", "path": item["path"], "claim": item["key"]}
                for item in forbidden_claims
            )

        if not (_non_empty_dict(receipt_ref) and authority_mode in VALID_AUTHORITY_MODES and isinstance(receipt, dict)):
            continue

        validation_result = receipt_validation_result if isinstance(receipt_validation_result, dict) else {}
        receipt_refs.append(
            {
                "receipt_ref": receipt_ref,
                "authority_mode": authority_mode,
                "receipt_check_result": _receipt_check_result(validation_result),
            }
        )

        commands = _commands_for_mode(authority_mode, receipt)
        changed_files = _changed_files_for_mode(authority_mode, receipt)
        validation_items = _validation_items_for_mode(authority_mode, receipt)
        claim_status = "observed" if authority_mode == "local_execution" else "claimed"
        command_result_summary.append(
            {
                "receipt_ref": receipt_ref,
                "authority_mode": authority_mode,
                "claim_status": claim_status,
                "commands": commands,
            }
        )
        changed_files_summary.append(
            {
                "receipt_ref": receipt_ref,
                "authority_mode": authority_mode,
                "claim_status": claim_status,
                "files": changed_files,
            }
        )
        validation_truth_summary.append(
            {
                "receipt_ref": receipt_ref,
                "authority_mode": authority_mode,
                "claim_status": claim_status,
                "receipt_validation_result": validation_result.get("validation_result"),
                "validation_items": validation_items,
            }
        )
        scope_check_summary.append(
            {
                "receipt_ref": receipt_ref,
                "authority_mode": authority_mode,
                "scope_check_result": _scope_check_result_for_mode(authority_mode, receipt, validation_result),
            }
        )

        if _validation_claims_passed(validation_items) and not commands:
            blockers.append(
                _blocker(
                    "validation_passed_without_command_evidence",
                    "Executor report cannot summarize validation as passed without command evidence.",
                    {"index": index, "receipt_ref": receipt_ref},
                )
            )

        failures_and_blockers.extend(_failure_items(receipt_ref, authority_mode, receipt, validation_result))
        known_gaps.extend(_tagged_items(receipt_ref, authority_mode, receipt.get("known_gaps")))
        remaining_risks.extend(_tagged_items(receipt_ref, authority_mode, receipt.get("remaining_risks")))

    report = {
        "executor_report_id": executor_report_id,
        "report_schema_version": EXPECTED_REPORT_SCHEMA_VERSION,
        "report_status": EXECUTOR_REPORT_FAILED_CLOSED if blockers else EXECUTOR_REPORT_READY,
        "version_taskbook_ref": version_taskbook_ref,
        "master_taskbook_hash": master_taskbook_hash,
        "stage_taskbook_hash": stage_taskbook_hash,
        "receipt_refs": receipt_refs,
        "authority_modes": sorted(authority_modes),
        "command_result_summary": command_result_summary,
        "changed_files_summary": changed_files_summary,
        "validation_truth_summary": validation_truth_summary,
        "scope_check_summary": scope_check_summary,
        "failures_and_blockers": failures_and_blockers + blockers,
        "known_gaps": known_gaps,
        "remaining_risks": remaining_risks,
        "known_conflicts": known_conflicts,
        "authority_boundary": dict(AUTHORITY_BOUNDARY_EXPECTATIONS),
        "review_accepted": False,
        "delivery_state_accepted": False,
        "executor_self_acceptance": False,
        "dispatch_authorized": False,
        "local_execution_authorized": False,
        "imported_receipt_adopted_as_fact": False,
        "plan_mutation_authorized": False,
        "commit_authorized": False,
        "push_authorized": False,
        "creates_review_decision": False,
        "emits_gate_event": False,
        "writes_delivery_state": False,
    }
    report.update(work_item_binding)
    assert_executor_report_contract(report)
    return report


def assert_executor_report_contract(report: dict[str, Any]) -> None:
    if not isinstance(report, dict):
        raise ExecutorReportError("EXECUTOR_REPORT_INVALID", "Executor report must be an object.")
    missing = sorted(REQUIRED_EXECUTOR_REPORT_FIELDS - set(report))
    if missing:
        raise ExecutorReportError(
            "EXECUTOR_REPORT_REQUIRED_FIELD_MISSING",
            "Executor report is missing required fields.",
            details={"missing_fields": missing},
        )
    status = report.get("report_status")
    if status not in {EXECUTOR_REPORT_READY, EXECUTOR_REPORT_FAILED_CLOSED}:
        raise ExecutorReportError(
            "EXECUTOR_REPORT_STATUS_INVALID",
            "Executor report status is unsupported.",
            details={"report_status": status},
        )
    binding_rejections = optional_work_item_reference_rejections(report)
    if binding_rejections and status == EXECUTOR_REPORT_READY:
        raise ExecutorReportError(
            "EXECUTOR_REPORT_WORK_ITEM_BINDING_INVALID",
            "Ready Executor report Work Item binding is invalid or incomplete.",
            details={"rejections": binding_rejections},
        )
    blockers = report.get("failures_and_blockers")
    if not isinstance(blockers, list):
        raise ExecutorReportError("EXECUTOR_REPORT_BLOCKERS_INVALID", "failures_and_blockers must be a list.")
    if status == EXECUTOR_REPORT_READY and _blocking_items(blockers):
        raise ExecutorReportError(
            "EXECUTOR_REPORT_READY_WITH_BLOCKERS",
            "executor_report_ready must not include blocking failures.",
            details={"blocking_codes": [item.get("code") for item in _blocking_items(blockers)]},
        )
    if status == EXECUTOR_REPORT_FAILED_CLOSED and not _blocking_items(blockers):
        raise ExecutorReportError(
            "EXECUTOR_REPORT_FAILED_WITHOUT_BLOCKERS",
            "Failed executor report must include at least one blocking failure.",
        )
    if report.get("authority_boundary") != AUTHORITY_BOUNDARY_EXPECTATIONS:
        raise ExecutorReportError(
            "FORBIDDEN_EXECUTOR_REPORT_AUTHORITY_CLAIM",
            "Executor report authority boundary must remain false.",
            details={"expected": AUTHORITY_BOUNDARY_EXPECTATIONS, "actual": report.get("authority_boundary")},
        )
    forbidden_claims = _forbidden_truthy_claims(report, "report")
    if forbidden_claims:
        raise ExecutorReportError(
            "FORBIDDEN_EXECUTOR_REPORT_RESULT_CLAIM",
            "Executor report contains forbidden authority claims.",
            details={"forbidden_claims": _safe_forbidden_claims(forbidden_claims)},
        )


def _commands_for_mode(authority_mode: str, receipt: dict[str, Any]) -> list[Any]:
    if authority_mode == "local_execution":
        return _list_or_empty(receipt.get("command_attempts"))
    return _list_or_empty(receipt.get("claimed_commands"))


def _changed_files_for_mode(authority_mode: str, receipt: dict[str, Any]) -> list[Any]:
    if authority_mode == "local_execution":
        return _list_or_empty(receipt.get("touched_files"))
    return _list_or_empty(receipt.get("claimed_touched_files"))


def _validation_items_for_mode(authority_mode: str, receipt: dict[str, Any]) -> list[Any]:
    if authority_mode == "local_execution":
        return _list_or_empty(receipt.get("validation_results"))
    return _list_or_empty(receipt.get("claimed_validation_results"))


def _scope_check_result_for_mode(authority_mode: str, receipt: dict[str, Any], validation_result: dict[str, Any]) -> Any:
    if authority_mode == "local_execution":
        return receipt.get("scope_check_result") or validation_result.get("scope_check_result")
    return "imported_claim_only"


def _validation_claims_passed(items: list[Any]) -> bool:
    for item in items:
        if isinstance(item, dict) and item.get("result") == "passed":
            return True
    return False


def _receipt_check_result(validation_result: dict[str, Any]) -> Any:
    return validation_result.get("receipt_check_result") or validation_result.get("imported_receipt_check_result")


def _failure_items(
    receipt_ref: dict[str, Any],
    authority_mode: str,
    receipt: dict[str, Any],
    validation_result: dict[str, Any],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for reason in _list_or_empty(receipt.get("blocked_or_failed_reasons")):
        items.append({"receipt_ref": receipt_ref, "authority_mode": authority_mode, "source": "receipt", "item": reason})
    for reason in _list_or_empty(validation_result.get("rejection_reasons")):
        items.append({"receipt_ref": receipt_ref, "authority_mode": authority_mode, "source": "validation_result", "item": reason})
    return items


def _tagged_items(receipt_ref: dict[str, Any], authority_mode: str, value: Any) -> list[dict[str, Any]]:
    return [{"receipt_ref": receipt_ref, "authority_mode": authority_mode, "item": item} for item in _list_or_empty(value)]


def _blocker(code: str, message: str, details: dict[str, Any]) -> dict[str, Any]:
    return {"code": code, "message": message, "details": details, "blocking": True}


def _blocking_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict) and item.get("blocking") is True]


def _non_empty_dict(value: Any) -> bool:
    return isinstance(value, dict) and bool(value)


def _list_or_empty(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _forbidden_truthy_claims(value: Any, path: str = "report") -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if str(key) in FORBIDDEN_EXECUTOR_REPORT_CLAIM_KEYS and _truthy_claim(child):
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
        return value.strip().lower() in {"true", "yes", "accepted", "authorized", "allowed", "granted", "adopted"}
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value != 0
    return False
