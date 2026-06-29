from __future__ import annotations

from typing import Any


HASH_BINDING_RESULT_MATCH = "match"
HASH_BINDING_RESULT_MISMATCH = "mismatch"
HASH_BINDING_RESULT_MISSING_INPUT = "missing_input"
HASH_BINDING_RESULT_KNOWN_UNKNOWN = "known_unknown"
HASH_BINDING_RESULT_VALUES = (
    HASH_BINDING_RESULT_MATCH,
    HASH_BINDING_RESULT_MISMATCH,
    HASH_BINDING_RESULT_MISSING_INPUT,
    HASH_BINDING_RESULT_KNOWN_UNKNOWN,
)

FAIL_CLOSED_RESULT_PASS = "pass"
FAIL_CLOSED_RESULT_FAIL_CLOSED = "fail_closed"

FORBIDDEN_HASH_BINDING_RESULT_FIELDS = frozenset(
    {
        "delivery_state",
        "accepted",
        "executor_authorization",
        "active_master_authority",
        "review_decision_outcome",
        "gate_event",
        "canonical_payload_hash",
        "canonical_receipt_hash",
    }
)


class MasterTaskbookHashBindingError(ValueError):
    def __init__(self, error_code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.details = details or {}


def bind_master_hashes(
    *,
    registry_input: dict[str, Any] | None,
    reader_result: dict[str, Any] | None,
    validator_result: dict[str, Any] | None,
    observed_git_head: str | None = None,
    source_version_taskbook_refs: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    registry_hash = _registry_master_hash(registry_input)
    reader_hash = _reader_master_hash(reader_result)
    validator_hash = _validator_input_hash(validator_result)
    inputs = {
        "registry_master_raw_snapshot_sha256": registry_hash,
        "reader_raw_content_sha256": reader_hash,
        "validator_input_raw_content_sha256": validator_hash,
    }
    missing_inputs = sorted(name for name, value in inputs.items() if not _is_sha256(value))
    known_unknown_inputs = _known_unknown_inputs(registry_input, reader_result, validator_result)

    if missing_inputs:
        binding_result = HASH_BINDING_RESULT_MISSING_INPUT
        fail_closed_result = FAIL_CLOSED_RESULT_FAIL_CLOSED
        failure_reason = "required_hash_input_missing"
    elif known_unknown_inputs:
        binding_result = HASH_BINDING_RESULT_KNOWN_UNKNOWN
        fail_closed_result = FAIL_CLOSED_RESULT_FAIL_CLOSED
        failure_reason = "upstream_input_known_unknown"
    else:
        unique_hashes = set(inputs.values())
        if len(unique_hashes) == 1:
            binding_result = HASH_BINDING_RESULT_MATCH
            fail_closed_result = FAIL_CLOSED_RESULT_PASS
            failure_reason = None
        else:
            binding_result = HASH_BINDING_RESULT_MISMATCH
            fail_closed_result = FAIL_CLOSED_RESULT_FAIL_CLOSED
            failure_reason = "master_hash_inputs_do_not_match"

    result = {
        "hash_binding_status": "evaluated",
        "hash_binding_result": binding_result,
        "fail_closed_result": fail_closed_result,
        "registry_master_raw_snapshot_sha256": registry_hash,
        "reader_raw_content_sha256": reader_hash,
        "validator_input_raw_content_sha256": validator_hash,
        "observed_git_head": _first_non_empty(
            observed_git_head,
            _dict_get(reader_result, "observed_git_head"),
            _dict_get(_dict_get(validator_result, "reader_result_input"), "observed_git_head"),
        ),
        "source_version_taskbook_refs": [dict(item) for item in source_version_taskbook_refs or []],
        "missing_inputs": missing_inputs,
        "known_unknown_inputs": known_unknown_inputs,
        "failure_reason_or_none": failure_reason,
        "canonical_receipt_generation": "deferred_not_generated",
        "canonical_payload_hash_finalization": "deferred_not_finalized",
        "binding_result_is_authority": False,
        "forbidden_authority_claims_present": [],
    }
    _assert_no_forbidden_result_fields(result)
    return result


def _registry_master_hash(registry_input: dict[str, Any] | None) -> str | None:
    if not isinstance(registry_input, dict):
        return None
    direct = _dict_get(registry_input, "registry_master_raw_snapshot_sha256")
    if direct is not None:
        return str(direct).strip()
    expected = _dict_get(registry_input, "master_expected_sha256")
    if expected is not None:
        return str(expected).strip()
    record = _dict_get(registry_input, "record")
    record_hash = _dict_get(record, "master_raw_snapshot_sha256")
    if record_hash is not None:
        return str(record_hash).strip()
    raw = _dict_get(registry_input, "master_raw_snapshot_sha256")
    return str(raw).strip() if raw is not None else None


def _reader_master_hash(reader_result: dict[str, Any] | None) -> str | None:
    raw = _dict_get(reader_result, "raw_content_sha256")
    return str(raw).strip() if raw is not None else None


def _validator_input_hash(validator_result: dict[str, Any] | None) -> str | None:
    direct = _dict_get(validator_result, "validator_input_raw_content_sha256")
    if direct is not None:
        return str(direct).strip()
    reader_input = _dict_get(validator_result, "reader_result_input")
    raw = _dict_get(reader_input, "raw_content_sha256")
    return str(raw).strip() if raw is not None else None


def _known_unknown_inputs(
    registry_input: dict[str, Any] | None,
    reader_result: dict[str, Any] | None,
    validator_result: dict[str, Any] | None,
) -> list[str]:
    known_unknown = []
    if _dict_get(registry_input, "hash_binding_input_status") == HASH_BINDING_RESULT_KNOWN_UNKNOWN:
        known_unknown.append("registry_input")
    if _dict_get(reader_result, "read_status") == HASH_BINDING_RESULT_KNOWN_UNKNOWN:
        known_unknown.append("reader_result")
    if _dict_get(validator_result, "validation_result") == HASH_BINDING_RESULT_KNOWN_UNKNOWN:
        known_unknown.append("validator_result")
    if _dict_get(validator_result, "validator_status") == HASH_BINDING_RESULT_KNOWN_UNKNOWN:
        known_unknown.append("validator_result")
    return sorted(set(known_unknown))


def _dict_get(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return None


def _first_non_empty(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _is_sha256(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    clean = value.strip()
    return len(clean) == 64 and all(char in "0123456789abcdef" for char in clean)


def _assert_no_forbidden_result_fields(result: dict[str, Any]) -> None:
    forbidden = sorted(key for key in result if key in FORBIDDEN_HASH_BINDING_RESULT_FIELDS)
    if forbidden:
        raise MasterTaskbookHashBindingError(
            "FORBIDDEN_HASH_BINDING_RESULT_FIELD",
            "Hash binding result contains forbidden authority or receipt fields.",
            details={"forbidden_fields": forbidden},
        )
