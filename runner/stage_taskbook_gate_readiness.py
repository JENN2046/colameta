from __future__ import annotations

from pathlib import Path
from typing import Any

from runner.stage_taskbook_registry import (
    EXPECTED_MASTER_TASKBOOK_REF,
    EXPECTED_SOURCE_VERSION_TASKBOOK_REF,
    StageTaskbookRegistryError,
    load_stage_taskbook_registry,
    sha256_file,
)
from runner.stage_to_master_binding import (
    DEFAULT_STAGE_ID,
    StageToMasterBindingError,
    validate_stage_to_master_binding,
)


DEFAULT_EVIDENCE_PACKAGE_REL_PATH = (
    "docs/taskbooks/versions/stage-02/evidence/"
    "VERSION_STAGE_02_V2_3_STAGE_TO_MASTER_BINDING_REPORT.md"
)
EXPECTED_V2_3_EVIDENCE_PACKAGE_SHA256 = "f1184ed0d55202e90a1c2535f278704b6c4a48197ae645620a7797d7e8187cbe"

READINESS_GATE_READY = "gate_ready"
READINESS_NOT_GATE_READY = "not_gate_ready"
READINESS_BLOCKED_NEEDS_REVIEW = "blocked_needs_review"
VALID_READINESS_RESULTS = frozenset(
    {
        READINESS_GATE_READY,
        READINESS_NOT_GATE_READY,
        READINESS_BLOCKED_NEEDS_REVIEW,
    }
)

REQUIRED_RESULT_FIELDS = frozenset(
    {
        "readiness_result",
        "stage_id",
        "stage_taskbook_ref",
        "master_taskbook_ref",
        "evidence_package_ref",
        "blocking_reasons",
        "authority_boundary",
    }
)

AUTHORITY_BOUNDARY_EXPECTATIONS = {
    "readiness_result_is_authority": False,
    "gate_ready_is_accepted_delivery_state": False,
    "gate_ready_authorizes_execution": False,
    "gate_ready_authorizes_executor_dispatch": False,
    "gate_ready_authorizes_route_transition": False,
    "gate_ready_authorizes_registry_mutation": False,
    "creates_review_decision": False,
    "emits_gate_event": False,
    "writes_delivery_state": False,
}
FORBIDDEN_RESULT_CLAIM_KEYS = frozenset(
    {
        "accepted_delivery_state",
        "delivery_state_accepted",
        "execution_authorized",
        "executor_dispatch_authorized",
        "route_transition_authorized",
        "registry_mutation_authorized",
        "review_acceptance",
        "review_accepted",
        "creates_review_decision",
        "emits_gate_event",
        "writes_delivery_state",
    }
)


class StageTaskbookGateReadinessError(ValueError):
    def __init__(self, error_code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.details = details or {}


def evaluate_stage_taskbook_gate_readiness(
    project_root: str | Path,
    registry_path: str | Path | None = None,
    *,
    stage_id: str = DEFAULT_STAGE_ID,
    stage_taskbook_ref: dict[str, str] | None = None,
    evidence_package_path: str | Path | None = None,
    evidence_package_known_unknown_reason: str | None = None,
    expected_evidence_package_sha256: str | None = EXPECTED_V2_3_EVIDENCE_PACKAGE_SHA256,
    expected_master_taskbook_ref: dict[str, str] | None = None,
    expected_registry_source_ref: dict[str, str] | None = None,
) -> dict[str, Any]:
    root = Path(project_root).expanduser().resolve()
    expected_master_ref = expected_master_taskbook_ref or EXPECTED_MASTER_TASKBOOK_REF
    expected_source_ref = expected_registry_source_ref or EXPECTED_SOURCE_VERSION_TASKBOOK_REF
    authority_boundary = _authority_boundary()
    blocking_reasons: list[dict[str, Any]] = []
    registry_result: dict[str, Any] | None = None
    binding_result: dict[str, Any] | None = None

    try:
        registry_result = load_stage_taskbook_registry(
            root,
            registry_path,
            expected_master_taskbook_ref=expected_master_ref,
            expected_source_version_ref=expected_source_ref,
        )
    except StageTaskbookRegistryError as exc:
        blocking_reasons.append(
            _blocking_reason(
                "registry_record_missing_or_invalid",
                "Stage Taskbook registry result is missing or invalid.",
                {"registry_error_code": exc.error_code, "registry_error_details": exc.details},
            )
        )

    try:
        binding_result = validate_stage_to_master_binding(
            root,
            registry_path,
            stage_id=stage_id,
            expected_master_taskbook_ref=expected_master_ref,
            expected_registry_source_ref=expected_source_ref,
        )
    except StageToMasterBindingError as exc:
        blocking_reasons.append(
            _blocking_reason(
                "master_binding_failed_or_missing",
                "Stage-to-Master binding result is missing or invalid.",
                {"binding_error_code": exc.error_code, "binding_error_details": exc.details},
            )
        )

    record = _registry_record(registry_result, stage_id)
    if registry_result is not None and record is None:
        blocking_reasons.append(
            _blocking_reason(
                "stage_taskbook_ref_is_unregistered",
                "Requested Stage Taskbook reference is not registered.",
                {"stage_id": stage_id, "registered_stage_ids": registry_result.get("stage_ids", [])},
            )
        )

    validator_result = _validator_result(record)
    if validator_result is None:
        blocking_reasons.append(
            _blocking_reason(
                "validator_result_failed_or_missing",
                "Stage registry record does not expose a validator result.",
                {"stage_id": stage_id},
            )
        )
    elif not _validator_passed(validator_result):
        blocking_reasons.append(
            _blocking_reason(
                "validator_result_failed_or_missing",
                "Stage Taskbook validator result is not passed.",
                {
                    "validation_result": validator_result.get("validation_result"),
                    "fail_closed_result": validator_result.get("fail_closed_result"),
                    "fail_closed_violations": validator_result.get("fail_closed_violations"),
                    "required_field_violations": validator_result.get("required_field_violations"),
                },
            )
        )

    non_goals_summary = record.get("non_goals_summary") if isinstance(record, dict) else None
    if not isinstance(non_goals_summary, list) or not non_goals_summary:
        blocking_reasons.append(
            _blocking_reason(
                "non_goals_summary_missing",
                "Gate-readiness requires an explicit non_goals_summary.",
                {"stage_id": stage_id},
            )
        )

    actual_stage_ref = _stage_ref_from(binding_result, record, stage_id, stage_taskbook_ref)
    if stage_taskbook_ref is not None and binding_result is not None:
        expected_stage_ref = binding_result["source_stage_taskbook_ref"]
        if not _stage_refs_equal(stage_taskbook_ref, expected_stage_ref):
            blocking_reasons.append(
                _blocking_reason(
                    "stage_taskbook_ref_hash_mismatch",
                    "Provided stage_taskbook_ref does not match the registered, Master-bound Stage Taskbook.",
                    {"provided": stage_taskbook_ref, "expected": expected_stage_ref},
                )
            )

    evidence_package_ref = _evidence_package_ref(
        root=root,
        evidence_package_path=evidence_package_path,
        expected_sha256=expected_evidence_package_sha256,
        known_unknown_reason=evidence_package_known_unknown_reason,
        blocking_reasons=blocking_reasons,
    )

    readiness_result = _readiness_result(blocking_reasons)
    result = {
        "readiness_result": readiness_result,
        "stage_id": stage_id,
        "stage_taskbook_ref": actual_stage_ref,
        "master_taskbook_ref": _master_ref_from(binding_result, expected_master_ref),
        "evidence_package_ref": evidence_package_ref,
        "blocking_reasons": blocking_reasons,
        "authority_boundary": authority_boundary,
        "validator_result_ref": _validator_result_ref(validator_result),
        "registry_record_ref": _registry_record_ref(binding_result),
        "master_binding_result_ref": _binding_result_ref(binding_result),
        "stage_taskbook_ref_consumption_rule": {
            "may_reference": readiness_result == READINESS_GATE_READY,
            "must_reject_when_not_gate_ready": True,
            "must_reject_when_hash_mismatch": True,
            "must_reject_when_authority_boundary_invalid": True,
        },
        "known_unknowns": _known_unknowns(evidence_package_ref),
    }
    assert_gate_readiness_result_contract(result)
    return result


def assert_gate_readiness_result_contract(result: dict[str, Any]) -> None:
    if not isinstance(result, dict):
        raise StageTaskbookGateReadinessError("READINESS_RESULT_INVALID", "Gate-readiness result must be an object.")
    missing = sorted(REQUIRED_RESULT_FIELDS - set(result))
    if missing:
        raise StageTaskbookGateReadinessError(
            "READINESS_RESULT_REQUIRED_FIELD_MISSING",
            "Gate-readiness result is missing required fields.",
            details={"missing_fields": missing},
        )
    readiness_result = result.get("readiness_result")
    if readiness_result not in VALID_READINESS_RESULTS:
        raise StageTaskbookGateReadinessError(
            "READINESS_RESULT_VALUE_INVALID",
            "Gate-readiness result has an unsupported readiness_result.",
            details={"readiness_result": readiness_result, "valid_values": sorted(VALID_READINESS_RESULTS)},
        )
    blocking_reasons = result.get("blocking_reasons")
    if not isinstance(blocking_reasons, list):
        raise StageTaskbookGateReadinessError(
            "BLOCKING_REASONS_INVALID",
            "Gate-readiness blocking_reasons must be a list.",
        )
    if readiness_result == READINESS_GATE_READY and blocking_reasons:
        raise StageTaskbookGateReadinessError(
            "GATE_READY_WITH_BLOCKING_REASONS",
            "gate_ready result must not include blocking reasons.",
            details={"blocking_reasons": blocking_reasons},
        )
    _reject_forbidden_result_claims(result)
    _validate_authority_boundary(result.get("authority_boundary"))


def assert_stage_taskbook_ref_consumable(result: dict[str, Any], stage_taskbook_ref: dict[str, str]) -> dict[str, Any]:
    assert_gate_readiness_result_contract(result)
    if result["readiness_result"] != READINESS_GATE_READY:
        raise StageTaskbookGateReadinessError(
            "STAGE_TASKBOOK_REF_NOT_GATE_READY",
            "Stage Taskbook reference cannot be consumed until readiness_result is gate_ready.",
            details={"readiness_result": result["readiness_result"], "blocking_reasons": result["blocking_reasons"]},
        )
    if not _stage_refs_equal(stage_taskbook_ref, result["stage_taskbook_ref"]):
        raise StageTaskbookGateReadinessError(
            "STAGE_TASKBOOK_REF_MISMATCH",
            "Provided Stage Taskbook reference does not match the gate-ready result.",
            details={"provided": stage_taskbook_ref, "expected": result["stage_taskbook_ref"]},
        )
    return {
        "can_reference": True,
        "stage_id": result["stage_id"],
        "stage_taskbook_ref": result["stage_taskbook_ref"],
        "authority_boundary_checked": True,
        "delivery_state_accepted": False,
        "execution_authorized": False,
    }


def _authority_boundary() -> dict[str, bool]:
    return dict(AUTHORITY_BOUNDARY_EXPECTATIONS)


def _validate_authority_boundary(value: Any) -> None:
    if not isinstance(value, dict):
        raise StageTaskbookGateReadinessError("AUTHORITY_BOUNDARY_INVALID", "authority_boundary must be an object.")
    unsupported = sorted(str(key) for key in value if key not in AUTHORITY_BOUNDARY_EXPECTATIONS)
    if unsupported:
        raise StageTaskbookGateReadinessError(
            "AUTHORITY_BOUNDARY_UNSUPPORTED_FIELD",
            "authority_boundary contains unsupported fields.",
            details={"unsupported_fields": unsupported},
        )
    for key, expected in AUTHORITY_BOUNDARY_EXPECTATIONS.items():
        if value.get(key) is not expected:
            raise StageTaskbookGateReadinessError(
                "FORBIDDEN_GATE_READY_AUTHORITY_CLAIM",
                "Gate-readiness result contains a forbidden authority claim.",
                details={"field": key, "expected": expected, "actual": value.get(key)},
            )


def _reject_forbidden_result_claims(value: Any, path: str = "result") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            lower_key = str(key).strip().lower()
            if lower_key in FORBIDDEN_RESULT_CLAIM_KEYS and _truthy_claim(child):
                raise StageTaskbookGateReadinessError(
                    "FORBIDDEN_GATE_READY_RESULT_CLAIM",
                    "Gate-readiness result contains a forbidden result claim.",
                    details={"path": child_path, "value": child},
                )
            _reject_forbidden_result_claims(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_forbidden_result_claims(child, f"{path}[{index}]")


def _truthy_claim(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "accepted", "authorized", "allowed", "granted"}
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value != 0
    return False


def _blocking_reason(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"code": code, "message": message, "details": details or {}}


def _registry_record(registry_result: dict[str, Any] | None, stage_id: str) -> dict[str, Any] | None:
    if not isinstance(registry_result, dict):
        return None
    records = registry_result.get("records")
    if not isinstance(records, dict):
        return None
    record = records.get(stage_id)
    return record if isinstance(record, dict) else None


def _validator_result(record: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(record, dict):
        return None
    value = record.get("validator_result")
    return value if isinstance(value, dict) else None


def _validator_passed(value: dict[str, Any]) -> bool:
    return (
        value.get("validation_result") == "passed"
        and value.get("fail_closed_result") == "pass"
        and value.get("fail_closed_violations") == []
        and value.get("required_field_violations") == []
    )


def _stage_ref_from(
    binding_result: dict[str, Any] | None,
    record: dict[str, Any] | None,
    stage_id: str,
    fallback: dict[str, str] | None,
) -> dict[str, str | None]:
    if isinstance(binding_result, dict) and isinstance(binding_result.get("source_stage_taskbook_ref"), dict):
        return dict(binding_result["source_stage_taskbook_ref"])
    if isinstance(record, dict):
        return {
            "path": record.get("stage_taskbook_path"),
            "raw_snapshot_sha256": record.get("stage_taskbook_hash"),
            "stage_id": stage_id,
        }
    if isinstance(fallback, dict):
        return dict(fallback)
    return {"path": None, "raw_snapshot_sha256": None, "stage_id": stage_id}


def _master_ref_from(binding_result: dict[str, Any] | None, expected_master_ref: dict[str, str]) -> dict[str, str]:
    if isinstance(binding_result, dict) and isinstance(binding_result.get("master_taskbook_ref"), dict):
        return dict(binding_result["master_taskbook_ref"])
    return dict(expected_master_ref)


def _registry_record_ref(binding_result: dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(binding_result, dict) and isinstance(binding_result.get("source_registry_record_ref"), dict):
        return dict(binding_result["source_registry_record_ref"])
    return {
        "path": None,
        "raw_snapshot_sha256": None,
        "registry_record_id": None,
        "record_key": "stage_id",
        "stage_id": None,
    }


def _binding_result_ref(binding_result: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(binding_result, dict):
        return {"binding_status": None, "validation_result": None, "fail_closed_result": None}
    return {
        "binding_status": binding_result.get("binding_status"),
        "validation_result": binding_result.get("validation_result"),
        "fail_closed_result": binding_result.get("fail_closed_result"),
    }


def _validator_result_ref(value: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {
            "validation_result": None,
            "fail_closed_result": None,
            "stage_taskbook_hash": None,
        }
    return {
        "validation_result": value.get("validation_result"),
        "fail_closed_result": value.get("fail_closed_result"),
        "stage_taskbook_hash": value.get("stage_taskbook_hash"),
    }


def _evidence_package_ref(
    *,
    root: Path,
    evidence_package_path: str | Path | None,
    expected_sha256: str | None,
    known_unknown_reason: str | None,
    blocking_reasons: list[dict[str, Any]],
) -> dict[str, Any]:
    raw_path = evidence_package_path or DEFAULT_EVIDENCE_PACKAGE_REL_PATH
    candidate = Path(raw_path).expanduser()
    path = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        blocking_reasons.append(
            _blocking_reason(
                "evidence_package_path_outside_project",
                "Evidence package reference must stay inside the project.",
                {"path": str(path), "project_root": str(root)},
            )
        )
        return {
            "path": str(raw_path),
            "raw_snapshot_sha256": None,
            "exists": False,
            "known_unknown_reason": known_unknown_reason,
        }
    rel_path = path.relative_to(root).as_posix()
    if not path.is_file():
        code = "evidence_package_known_unknown_documented" if known_unknown_reason else "evidence_package_missing_without_known_unknown"
        blocking_reasons.append(
            _blocking_reason(
                code,
                "Evidence package is missing.",
                {"path": rel_path, "known_unknown_reason": known_unknown_reason},
            )
        )
        return {
            "path": rel_path,
            "raw_snapshot_sha256": None,
            "exists": False,
            "known_unknown_reason": known_unknown_reason,
        }
    actual_sha = sha256_file(path)
    if expected_sha256 and actual_sha != expected_sha256:
        blocking_reasons.append(
            _blocking_reason(
                "evidence_package_hash_mismatch",
                "Evidence package hash does not match the expected reference.",
                {"path": rel_path, "expected": expected_sha256, "actual": actual_sha},
            )
        )
    return {
        "path": rel_path,
        "raw_snapshot_sha256": actual_sha,
        "exists": True,
        "known_unknown_reason": None,
    }


def _readiness_result(blocking_reasons: list[dict[str, Any]]) -> str:
    if not blocking_reasons:
        return READINESS_GATE_READY
    codes = {str(item.get("code")) for item in blocking_reasons}
    if codes == {"evidence_package_known_unknown_documented"}:
        return READINESS_BLOCKED_NEEDS_REVIEW
    return READINESS_NOT_GATE_READY


def _known_unknowns(evidence_package_ref: dict[str, Any]) -> list[dict[str, str]]:
    reason = evidence_package_ref.get("known_unknown_reason")
    if not reason:
        return []
    return [{"field": "evidence_package_ref", "reason": str(reason)}]


def _stage_refs_equal(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return (
        left.get("path") == right.get("path")
        and left.get("raw_snapshot_sha256") == right.get("raw_snapshot_sha256")
        and left.get("stage_id") == right.get("stage_id")
    )
