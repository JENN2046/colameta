from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any


FIELD_RESULT_PRESENT = "present"
FIELD_RESULT_MISSING = "missing"
FIELD_RESULT_EMPTY = "empty"
FIELD_RESULT_MALFORMED = "malformed"
FIELD_RESULT_KNOWN_UNKNOWN = "known_unknown"
FIELD_RESULT_VALUES = (
    FIELD_RESULT_PRESENT,
    FIELD_RESULT_MISSING,
    FIELD_RESULT_EMPTY,
    FIELD_RESULT_MALFORMED,
    FIELD_RESULT_KNOWN_UNKNOWN,
)

VALIDATION_RESULT_PASSED = "passed"
VALIDATION_RESULT_FAILED_CLOSED = "failed_closed"
VALIDATION_RESULT_FAILED_REQUIRED_FIELDS = "failed_required_fields"
VALIDATION_RESULT_KNOWN_UNKNOWN = "known_unknown"

FAIL_CLOSED_RESULT_PASS = "pass"
FAIL_CLOSED_RESULT_FAIL_CLOSED = "fail_closed"

FORBIDDEN_VALIDATOR_RESULT_FIELDS = frozenset(
    {
        "delivery_state",
        "accepted",
        "executor_authorization",
        "active_master_authority",
        "review_decision_outcome",
        "gate_event",
    }
)


@dataclass(frozen=True)
class RequiredFieldSpec:
    field: str
    exact_keys: tuple[str, ...]
    anchor_texts: tuple[str, ...]
    fail_closed: bool = False


REQUIRED_FIELD_SPECS = (
    RequiredFieldSpec(
        field="project_final_goal",
        exact_keys=("project_final_goal",),
        anchor_texts=("Project Final Goal",),
        fail_closed=True,
    ),
    RequiredFieldSpec(
        field="mvp_stage_scope",
        exact_keys=("mvp_stage_scope", "mvp_shape_decision"),
        anchor_texts=("MVP Boundary", "Stage 0-6 Thin Governed Loop"),
    ),
    RequiredFieldSpec(
        field="master_stage_taskbook_architecture",
        exact_keys=("master_stage_taskbook_architecture", "taskbook_layer_responsibility_decision"),
        anchor_texts=("Three-Level Taskbook Hierarchy", "Layer Responsibility Contract"),
    ),
    RequiredFieldSpec(
        field="authority_boundaries",
        exact_keys=("authority_boundaries", "state_authority_contract_decision"),
        anchor_texts=("Separation Of Authority", "Authority Boundary"),
        fail_closed=True,
    ),
    RequiredFieldSpec(
        field="delivery_state_gate_boundary",
        exact_keys=("delivery_state_gate_boundary", "delivery_state_gate_minimum_contract"),
        anchor_texts=("Delivery State Gate Minimum Contract",),
        fail_closed=True,
    ),
    RequiredFieldSpec(
        field="review_decision_mapping_boundary",
        exact_keys=("review_decision_mapping_boundary", "review_decision_mapping"),
        anchor_texts=("Review Decision Mapping",),
    ),
    RequiredFieldSpec(
        field="evidence_package_minimum",
        exact_keys=("evidence_package_minimum", "evidence_package_minimum_contract"),
        anchor_texts=("Evidence Package Minimum Contract",),
    ),
    RequiredFieldSpec(
        field="stage_0_6_thin_governed_loop",
        exact_keys=("stage_0_6_thin_governed_loop", "stage_0_6_readiness_contract_decision"),
        anchor_texts=("Stage 0-6 Thin Governed Loop",),
    ),
    RequiredFieldSpec(
        field="forbidden_claims_or_boundary_law",
        exact_keys=("forbidden_claims_or_boundary_law",),
        anchor_texts=("Forbidden Claims / Boundary Law", "forbidden-claims-boundary-law"),
    ),
    RequiredFieldSpec(
        field="versioning_policy",
        exact_keys=("versioning_policy",),
        anchor_texts=("Versioning Policy",),
    ),
)


class MasterTaskbookValidatorError(ValueError):
    def __init__(self, error_code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.details = details or {}


def validate_master_taskbook_required_fields(reader_result: dict[str, Any] | None) -> dict[str, Any]:
    raw_content = _reader_raw_content_or_none(reader_result)
    if raw_content is None:
        result = _known_unknown_result("reader_result_missing", reader_result)
        _assert_no_forbidden_result_fields(result)
        return result

    raw_content_sha256 = hashlib.sha256(raw_content.encode("utf-8")).hexdigest()
    declared_sha256 = str(reader_result.get("raw_content_sha256", "")).strip() if reader_result else ""
    if declared_sha256 and declared_sha256 != raw_content_sha256:
        result = _known_unknown_result(
            "reader_result_hash_mismatch",
            reader_result,
            details={"expected_raw_content_sha256": declared_sha256, "actual_raw_content_sha256": raw_content_sha256},
        )
        _assert_no_forbidden_result_fields(result)
        return result

    checks = [_check_required_field(raw_content, spec) for spec in REQUIRED_FIELD_SPECS]
    fail_closed_violations = [
        check["field"]
        for check in checks
        if check["fail_closed"] and check["result"] != FIELD_RESULT_PRESENT
    ]
    required_field_violations = [
        check["field"]
        for check in checks
        if check["result"] != FIELD_RESULT_PRESENT
    ]
    if fail_closed_violations:
        validation_result = VALIDATION_RESULT_FAILED_CLOSED
        fail_closed_result = FAIL_CLOSED_RESULT_FAIL_CLOSED
    elif required_field_violations:
        validation_result = VALIDATION_RESULT_FAILED_REQUIRED_FIELDS
        fail_closed_result = FAIL_CLOSED_RESULT_PASS
    else:
        validation_result = VALIDATION_RESULT_PASSED
        fail_closed_result = FAIL_CLOSED_RESULT_PASS

    result = {
        "validator_status": "validated",
        "validation_result": validation_result,
        "fail_closed_result": fail_closed_result,
        "required_field_check_table": checks,
        "fail_closed_violations": fail_closed_violations,
        "required_field_violations": required_field_violations,
        "reader_result_input": _reader_result_summary(reader_result, raw_content_sha256),
        "not_validated": [],
        "remaining_risks": [
            "validator checks explicit field and section anchors only; it does not perform full semantic review",
            "validator result is evidence only and does not create review acceptance or Delivery State Gate authority",
        ],
        "failure_reason_or_none": None,
    }
    _assert_no_forbidden_result_fields(result)
    return result


def _reader_raw_content_or_none(reader_result: dict[str, Any] | None) -> str | None:
    if not isinstance(reader_result, dict):
        return None
    raw_content = reader_result.get("raw_content")
    if not isinstance(raw_content, str) or raw_content == "":
        return None
    return raw_content


def _known_unknown_result(
    reason: str,
    reader_result: dict[str, Any] | None,
    *,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    checks = [
        {
            "field": spec.field,
            "result": FIELD_RESULT_KNOWN_UNKNOWN,
            "fail_closed": spec.fail_closed,
            "matched_anchor": None,
            "line_number": None,
            "failure_reason_or_none": reason,
        }
        for spec in REQUIRED_FIELD_SPECS
    ]
    return {
        "validator_status": "known_unknown",
        "validation_result": VALIDATION_RESULT_KNOWN_UNKNOWN,
        "fail_closed_result": FAIL_CLOSED_RESULT_FAIL_CLOSED,
        "required_field_check_table": checks,
        "fail_closed_violations": [spec.field for spec in REQUIRED_FIELD_SPECS if spec.fail_closed],
        "required_field_violations": [spec.field for spec in REQUIRED_FIELD_SPECS],
        "reader_result_input": _reader_result_summary(reader_result, details=details),
        "not_validated": ["required_field_presence"],
        "remaining_risks": [
            "reader result was unavailable or unusable; validator did not re-read the Master Taskbook",
        ],
        "failure_reason_or_none": reason,
    }


def _reader_result_summary(
    reader_result: dict[str, Any] | None,
    raw_content_sha256: str | None = None,
    *,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    summary = {
        "reader_result_available": isinstance(reader_result, dict),
        "read_status": None,
        "raw_content_sha256": raw_content_sha256,
        "observed_git_head": None,
        "registry_review_status_boundary": None,
        "failure_reason_or_none": "reader_result_missing" if not isinstance(reader_result, dict) else None,
    }
    if isinstance(reader_result, dict):
        summary.update(
            {
                "read_status": reader_result.get("read_status"),
                "raw_content_sha256": raw_content_sha256 or reader_result.get("raw_content_sha256"),
                "observed_git_head": reader_result.get("observed_git_head"),
                "registry_review_status_boundary": reader_result.get("registry_review_status_boundary"),
                "failure_reason_or_none": reader_result.get("failure_reason_or_none"),
            }
        )
    if details:
        summary["integrity_details"] = details
    return summary


def _check_required_field(raw_content: str, spec: RequiredFieldSpec) -> dict[str, Any]:
    lines = raw_content.splitlines()
    exact_match = _find_exact_field(lines, spec)
    if exact_match is not None:
        line_index, key, value = exact_match
        result, reason = _classify_exact_field(lines, line_index, value)
        return {
            "field": spec.field,
            "result": result,
            "fail_closed": spec.fail_closed,
            "matched_anchor": key,
            "line_number": line_index + 1,
            "failure_reason_or_none": reason,
        }

    anchor_match = _find_anchor(raw_content, lines, spec.anchor_texts)
    if anchor_match is not None:
        line_index, anchor = anchor_match
        return {
            "field": spec.field,
            "result": FIELD_RESULT_PRESENT,
            "fail_closed": spec.fail_closed,
            "matched_anchor": anchor,
            "line_number": line_index + 1,
            "failure_reason_or_none": None,
        }

    return {
        "field": spec.field,
        "result": FIELD_RESULT_MISSING,
        "fail_closed": spec.fail_closed,
        "matched_anchor": None,
        "line_number": None,
        "failure_reason_or_none": "required_field_anchor_missing",
    }


def _find_exact_field(lines: list[str], spec: RequiredFieldSpec) -> tuple[int, str, str] | None:
    patterns = [
        (key, re.compile(rf"^\s*{re.escape(key)}\s*:\s*(.*)$"))
        for key in spec.exact_keys
    ]
    for line_index, line in enumerate(lines):
        for key, pattern in patterns:
            match = pattern.match(line)
            if match:
                return line_index, key, match.group(1)
    return None


def _find_anchor(raw_content: str, lines: list[str], anchors: tuple[str, ...]) -> tuple[int, str] | None:
    for anchor in anchors:
        if anchor not in raw_content:
            continue
        for line_index, line in enumerate(lines):
            if anchor in line:
                return line_index, anchor
    return None


def _classify_exact_field(lines: list[str], line_index: int, value: str) -> tuple[str, str | None]:
    stripped = value.strip()
    if _looks_malformed(stripped):
        return FIELD_RESULT_MALFORMED, "field_value_malformed"
    if stripped in {"", "[]", "{}"}:
        if _has_indented_body(lines, line_index):
            return FIELD_RESULT_PRESENT, None
        return FIELD_RESULT_EMPTY, "field_value_empty"
    return FIELD_RESULT_PRESENT, None


def _has_indented_body(lines: list[str], line_index: int) -> bool:
    current_indent = len(lines[line_index]) - len(lines[line_index].lstrip(" "))
    for line in lines[line_index + 1 :]:
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent > current_indent:
            return True
        return False
    return False


def _looks_malformed(value: str) -> bool:
    if not value:
        return False
    if value in {"<<malformed>>", "MALFORMED"}:
        return True
    pairs = (("[", "]"), ("{", "}"), ("'", "'"), ('"', '"'))
    for start, end in pairs:
        if value.startswith(start) and not value.endswith(end):
            return True
    return False


def _assert_no_forbidden_result_fields(result: dict[str, Any]) -> None:
    forbidden = sorted(key for key in result if key in FORBIDDEN_VALIDATOR_RESULT_FIELDS)
    if forbidden:
        raise MasterTaskbookValidatorError(
            "FORBIDDEN_VALIDATOR_RESULT_FIELD",
            "Validator result contains forbidden authority fields.",
            details={"forbidden_fields": forbidden},
        )
