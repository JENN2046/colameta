from __future__ import annotations

import hashlib
import json
from typing import Any


VALIDATION_TRUTH_CHECK_PASSED = "validation_truth_check_passed"
VALIDATION_TRUTH_CHECK_FAILED_CLOSED = "validation_truth_check_failed_closed"
VALIDATION_TRUTH_RECORD_SCHEMA_VERSION = "validation_truth.v1"
VALID_EXECUTION_STATUSES = frozenset({"passed", "failed", "blocked", "not_run", "unvalidated"})
EVIDENCE_PROVENANCE_SCHEMA_VERSION = "evidence_provenance.v1"
EVIDENCE_PROVENANCE_MAX_ENTRIES = 32
EVIDENCE_SUBJECT_REQUIRES_EXECUTION = {
    "execution": True,
    "validation": True,
    "review": False,
    "hash_binding": False,
    "read_only_observation": False,
}
_EVIDENCE_KINDS = frozenset({"observed", "draft", "simulated", "placeholder"})
_PROVENANCE_ENTRY_KEYS = frozenset(
    {
        "subject_path",
        "evidence_kind",
        "binding",
        "claimed_evidence_subject",
        "claimed_subject_requires_execution",
        "claimed_subject_operation_completed",
        "claimed_execution_performed",
        "claimed_eligible_for_acceptance",
    }
)
_PROVENANCE_BINDING_KEYS = frozenset(
    {"record_id", "record_schema_version", "subject_path", "content_sha256"}
)
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

    provenance = validate_evidence_provenance(
        truth,
        record_id=truth.get("validation_truth_id"),
        record_schema_version=VALIDATION_TRUTH_RECORD_SCHEMA_VERSION,
        subject_specs={
            "$": {
                "evidence_subject": "validation",
                "subject_operation_completed": execution_status in {"passed", "failed"},
            }
        },
        base_valid=not rejection_reasons,
    )
    if provenance["rejection_reasons"]:
        rejected_fields.add("evidence_provenance")
        rejection_reasons.extend(provenance["rejection_reasons"])
        known_conflicts.extend(provenance["known_conflicts"])

    result = _validation_truth_result(
        truth=truth,
        rejected_fields=sorted(rejected_fields),
        rejection_reasons=rejection_reasons,
        known_conflicts=known_conflicts,
        evidence_provenance=provenance["projection"],
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
    evidence_provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    passed = not rejection_reasons
    return {
        "validation_truth_check_result": VALIDATION_TRUTH_CHECK_PASSED if passed else VALIDATION_TRUTH_CHECK_FAILED_CLOSED,
        "validation_result": "passed" if passed else "failed_closed",
        "recognized_fields": [field for field in REQUIRED_VALIDATION_TRUTH_FIELDS if field in truth],
        "rejected_fields": rejected_fields,
        "rejection_reasons": rejection_reasons,
        "known_conflicts": known_conflicts,
        "evidence_provenance": evidence_provenance
        or legacy_evidence_provenance_projection(),
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


def evidence_record_sha256(bound_object: dict[str, Any]) -> str:
    """Digest the current record without binding its provenance envelope to itself."""

    payload = {
        key: value for key, value in bound_object.items() if key != "evidence_provenance"
    }
    canonical = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def legacy_evidence_provenance_projection() -> dict[str, Any]:
    return {
        "schema_version": EVIDENCE_PROVENANCE_SCHEMA_VERSION,
        "provenance_status": "legacy_unclassified",
        "legacy_read_parse_only": True,
        "eligible_for_acceptance": False,
        "entries": [],
        "authority_boundary": _provenance_authority_boundary(),
    }


def validate_evidence_provenance(
    bound_object: dict[str, Any],
    *,
    record_id: Any,
    record_schema_version: Any,
    subject_specs: dict[str, dict[str, Any]],
    base_valid: bool,
) -> dict[str, Any]:
    """Validate a versioned sibling provenance envelope.

    ``subject_specs`` is validator-owned. It binds an exact JSON path to one
    subject and an operation-completion fact derived from the current record or
    its authoritative operation record. Caller ``claimed_*`` values are only
    compared with those derived facts.
    """

    envelope = bound_object.get("evidence_provenance")
    if envelope is None:
        return {
            "projection": legacy_evidence_provenance_projection(),
            "rejection_reasons": [],
            "known_conflicts": [],
        }

    reasons: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    normalized_entries: list[dict[str, Any]] = []
    if not isinstance(record_id, str) or not record_id.strip() or not isinstance(
        record_schema_version, str
    ) or not record_schema_version.strip():
        reasons.append(
            _reason(
                "EVIDENCE_PROVENANCE_BINDING_CONTEXT_INVALID",
                "Evidence provenance requires a non-empty validator-owned record id and schema version.",
                {},
            )
        )
    if not isinstance(envelope, dict):
        reasons.append(
            _reason(
                "EVIDENCE_PROVENANCE_INVALID",
                "evidence_provenance must be an object.",
                {"actual_type": type(envelope).__name__},
            )
        )
        return _provenance_validation_result(reasons, conflicts, normalized_entries)
    if set(envelope) != {"schema_version", "entries"}:
        reasons.append(
            _reason(
                "EVIDENCE_PROVENANCE_SHAPE_INVALID",
                "evidence_provenance must contain exactly schema_version and entries.",
                {"actual_fields": sorted(str(key) for key in envelope)},
            )
        )
    if envelope.get("schema_version") != EVIDENCE_PROVENANCE_SCHEMA_VERSION:
        reasons.append(
            _reason(
                "EVIDENCE_PROVENANCE_VERSION_UNSUPPORTED",
                "Evidence provenance schema version is unsupported.",
                {
                    "expected": EVIDENCE_PROVENANCE_SCHEMA_VERSION,
                    "actual": envelope.get("schema_version"),
                },
            )
        )
    entries = envelope.get("entries")
    if (
        not isinstance(entries, list)
        or not entries
        or len(entries) > EVIDENCE_PROVENANCE_MAX_ENTRIES
    ):
        reasons.append(
            _reason(
                "EVIDENCE_PROVENANCE_ENTRIES_INVALID",
                "Evidence provenance entries must be a non-empty bounded list.",
                {
                    "max_entries": EVIDENCE_PROVENANCE_MAX_ENTRIES,
                    "actual_count": len(entries) if isinstance(entries, list) else None,
                },
            )
        )
        entries = entries if isinstance(entries, list) else []

    try:
        expected_digest = evidence_record_sha256(bound_object)
    except (TypeError, ValueError):
        reasons.append(
            _reason(
                "EVIDENCE_PROVENANCE_CONTENT_NOT_CANONICAL",
                "Bound evidence content must be JSON-canonicalizable.",
                {},
            )
        )
        return _provenance_validation_result(reasons, conflicts, normalized_entries)
    seen_paths: set[str] = set()
    for index, entry in enumerate(entries[:EVIDENCE_PROVENANCE_MAX_ENTRIES]):
        entry_path = f"evidence_provenance.entries[{index}]"
        if not isinstance(entry, dict):
            reasons.append(
                _reason(
                    "EVIDENCE_PROVENANCE_ENTRY_INVALID",
                    "Evidence provenance entry must be an object.",
                    {"entry_path": entry_path},
                )
            )
            continue
        if not set(entry).issubset(_PROVENANCE_ENTRY_KEYS) or not {
            "subject_path",
            "evidence_kind",
            "binding",
        }.issubset(entry):
            reasons.append(
                _reason(
                    "EVIDENCE_PROVENANCE_ENTRY_SHAPE_INVALID",
                    "Evidence provenance entry fields are invalid.",
                    {
                        "entry_path": entry_path,
                        "actual_fields": sorted(str(key) for key in entry),
                    },
                )
            )
        subject_path = entry.get("subject_path")
        if not isinstance(subject_path, str) or subject_path not in subject_specs:
            reasons.append(
                _reason(
                    "EVIDENCE_PROVENANCE_PATH_MISMATCH",
                    "Evidence provenance subject_path is not validator-owned for this record.",
                    {"entry_path": entry_path, "subject_path": subject_path},
                )
            )
            conflicts.append(
                {"conflict_type": "provenance_path", "path": entry_path, "claim": subject_path}
            )
            continue
        if subject_path in seen_paths:
            reasons.append(
                _reason(
                    "EVIDENCE_PROVENANCE_DUPLICATE_PATH",
                    "Evidence provenance subject_path must be unique.",
                    {"entry_path": entry_path, "subject_path": subject_path},
                )
            )
            continue
        seen_paths.add(subject_path)
        spec = subject_specs[subject_path]
        evidence_subject = spec.get("evidence_subject")
        if evidence_subject not in EVIDENCE_SUBJECT_REQUIRES_EXECUTION:
            reasons.append(
                _reason(
                    "EVIDENCE_PROVENANCE_SUBJECT_UNKNOWN",
                    "Validator-owned evidence subject is unsupported.",
                    {"entry_path": entry_path, "subject_path": subject_path},
                )
            )
            continue
        requires_execution = EVIDENCE_SUBJECT_REQUIRES_EXECUTION[evidence_subject]
        operation_completed = spec.get("subject_operation_completed") is True
        evidence_kind = entry.get("evidence_kind")
        if not isinstance(evidence_kind, str) or evidence_kind not in _EVIDENCE_KINDS:
            reasons.append(
                _reason(
                    "EVIDENCE_PROVENANCE_KIND_INVALID",
                    "Evidence kind is unsupported.",
                    {"entry_path": entry_path, "evidence_kind": evidence_kind},
                )
            )
        elif evidence_kind != "observed":
            reasons.append(
                _reason(
                    "EVIDENCE_PROVENANCE_NON_OBSERVED_INELIGIBLE",
                    "Draft, simulated, and placeholder evidence cannot enter an acceptance-aware path.",
                    {"entry_path": entry_path, "evidence_kind": evidence_kind},
                )
            )
        binding_valid = _validate_provenance_binding(
            entry.get("binding"),
            record_id=record_id,
            record_schema_version=record_schema_version,
            subject_path=subject_path,
            content_sha256=expected_digest,
            entry_path=entry_path,
            reasons=reasons,
        )
        if evidence_kind != "observed" and operation_completed:
            reasons.append(
                _reason(
                    "EVIDENCE_PROVENANCE_KIND_COMPLETION_CONFLICT",
                    "Completed bound evidence cannot be labelled draft, simulated, or placeholder.",
                    {"entry_path": entry_path, "evidence_kind": evidence_kind},
                )
            )
        execution_performed = bool(
            evidence_kind == "observed" and requires_execution and operation_completed
        )
        eligible = bool(
            evidence_kind == "observed"
            and operation_completed
            and binding_valid
            and base_valid
            and spec.get("subject_valid", True) is True
        )
        derived = {
            "evidence_subject": evidence_subject,
            "subject_requires_execution": requires_execution,
            "subject_operation_completed": operation_completed,
            "execution_performed": execution_performed,
            "eligible_for_acceptance": eligible,
        }
        normalized_entries.append(
            {
                "subject_path": subject_path,
                "evidence_kind": evidence_kind,
                **derived,
                "binding_status": "verified" if binding_valid else "failed_closed",
            }
        )
        _compare_provenance_claims(
            entry,
            derived=derived,
            entry_path=entry_path,
            reasons=reasons,
            conflicts=conflicts,
        )

    missing_subject_paths = sorted(set(subject_specs) - seen_paths)
    if missing_subject_paths:
        reasons.append(
            _reason(
                "EVIDENCE_PROVENANCE_SUBJECT_COVERAGE_INCOMPLETE",
                "Evidence provenance must cover every validator-owned subject path.",
                {"missing_subject_paths": missing_subject_paths},
            )
        )

    return _provenance_validation_result(reasons, conflicts, normalized_entries)


def _validate_provenance_binding(
    binding: Any,
    *,
    record_id: Any,
    record_schema_version: Any,
    subject_path: str,
    content_sha256: str,
    entry_path: str,
    reasons: list[dict[str, Any]],
) -> bool:
    expected = {
        "record_id": record_id,
        "record_schema_version": record_schema_version,
        "subject_path": subject_path,
        "content_sha256": content_sha256,
    }
    if not isinstance(binding, dict) or set(binding) != _PROVENANCE_BINDING_KEYS:
        reasons.append(
            _reason(
                "EVIDENCE_PROVENANCE_BINDING_INVALID",
                "Evidence provenance binding shape is invalid.",
                {"entry_path": entry_path},
            )
        )
        return False
    mismatches = [key for key, value in expected.items() if binding.get(key) != value]
    if mismatches:
        reasons.append(
            _reason(
                "EVIDENCE_PROVENANCE_BINDING_MISMATCH",
                "Evidence provenance binding does not match the current record.",
                {"entry_path": entry_path, "mismatched_fields": mismatches},
            )
        )
        return False
    return True


def _compare_provenance_claims(
    entry: dict[str, Any],
    *,
    derived: dict[str, Any],
    entry_path: str,
    reasons: list[dict[str, Any]],
    conflicts: list[dict[str, Any]],
) -> None:
    claim_map = {
        "claimed_evidence_subject": ("evidence_subject", "EVIDENCE_PROVENANCE_SUBJECT_DOWNGRADE"),
        "claimed_subject_requires_execution": (
            "subject_requires_execution",
            "EVIDENCE_PROVENANCE_EXECUTION_REQUIREMENT_MISMATCH",
        ),
        "claimed_subject_operation_completed": (
            "subject_operation_completed",
            "EVIDENCE_PROVENANCE_COMPLETION_MISMATCH",
        ),
        "claimed_execution_performed": (
            "execution_performed",
            "EVIDENCE_PROVENANCE_EXECUTION_FACT_MISMATCH",
        ),
        "claimed_eligible_for_acceptance": (
            "eligible_for_acceptance",
            "EVIDENCE_PROVENANCE_ELIGIBILITY_MISMATCH",
        ),
    }
    for claim_key, (derived_key, code) in claim_map.items():
        if claim_key not in entry:
            continue
        claim = entry.get(claim_key)
        expected = derived[derived_key]
        if claim == expected and type(claim) is type(expected):
            continue
        reasons.append(
            _reason(
                code,
                "Caller provenance claim does not match the validator-derived fact.",
                {"entry_path": entry_path, "claim": claim_key, "derived_field": derived_key},
            )
        )
        conflicts.append(
            {"conflict_type": "provenance_claim", "path": entry_path, "claim": claim_key}
        )


def _provenance_validation_result(
    reasons: list[dict[str, Any]],
    conflicts: list[dict[str, Any]],
    entries: list[dict[str, Any]],
) -> dict[str, Any]:
    passed = not reasons
    if not passed:
        entries = [
            {**entry, "eligible_for_acceptance": False}
            for entry in entries
        ]
    projection = {
        "schema_version": EVIDENCE_PROVENANCE_SCHEMA_VERSION,
        "provenance_status": "verified" if passed else "failed_closed",
        "legacy_read_parse_only": False,
        "eligible_for_acceptance": bool(entries)
        and passed
        and all(entry.get("eligible_for_acceptance") is True for entry in entries),
        "entries": entries,
        "authority_boundary": _provenance_authority_boundary(),
    }
    return {
        "projection": projection,
        "rejection_reasons": reasons,
        "known_conflicts": conflicts,
    }


def _provenance_authority_boundary() -> dict[str, bool]:
    return {
        "eligible_means_accepted": False,
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
