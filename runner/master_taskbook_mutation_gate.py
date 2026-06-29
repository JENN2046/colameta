from __future__ import annotations

import posixpath
from typing import Any


MUTATION_ATTEMPT_CLASS_NO_MASTER_MUTATION = "no_master_mutation"
MUTATION_ATTEMPT_CLASS_READ_ONLY_MASTER_ACCESS = "read_only_master_access"
MUTATION_ATTEMPT_CLASS_UNAUTHORIZED_MASTER_MUTATION = "unauthorized_master_mutation_attempt"
MUTATION_ATTEMPT_CLASS_COMMANDER_AUTHORIZED_CANDIDATE = "commander_authorized_master_mutation_candidate"
MUTATION_ATTEMPT_CLASS_UNKNOWN_RISK = "unknown_master_mutation_risk"

GATE_RESULT_ALLOW_READ_ONLY = "allow_read_only"
GATE_RESULT_BLOCK_UNAUTHORIZED_MUTATION = "block_unauthorized_mutation"
GATE_RESULT_REQUIRE_COMMANDER_HARD_GATE = "require_commander_hard_gate"
GATE_RESULT_KNOWN_UNKNOWN = "known_unknown"

FAIL_CLOSED_RESULT_PASS = "pass"
FAIL_CLOSED_RESULT_FAIL_CLOSED = "fail_closed"

DEFAULT_PROTECTED_PATHS = (
    "PROJECT_MASTER_TASKBOOK.md",
    "PROJECT_MASTER_TASKBOOK.zh-CN.md",
    "FREEZE_CANDIDATE_REVIEW_PACKET.md",
    "FREEZE_CANDIDATE_REVIEW_PACKET.zh-CN.md",
)

READ_ONLY_ACTIONS = frozenset(
    {
        "read",
        "inspect",
        "sha256sum",
        "hash",
        "diff_read",
        "status",
        "stat",
        "exists_check",
    }
)

MUTATION_ACTIONS = frozenset(
    {
        "write",
        "modify",
        "create",
        "delete",
        "remove",
        "rename",
        "move",
        "replace",
        "patch",
        "stage",
        "commit",
    }
)

FORBIDDEN_MUTATION_GATE_RESULT_FIELDS = frozenset(
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

PROJECT_ROOT_MARKER = "/home/jenn/src/colameta-dev/"

SAFE_SOURCE_VERSION_TASKBOOK_REF_FIELDS = frozenset(
    {
        "path",
        "version",
        "version_id",
        "sha256",
        "raw_snapshot_sha256",
    }
)


class MasterTaskbookMutationGateError(ValueError):
    def __init__(self, error_code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.details = details or {}


def evaluate_master_mutation_gate(
    *,
    candidate_changes: list[dict[str, Any]] | None,
    commander_authorization: dict[str, Any] | None = None,
    protected_paths: tuple[str, ...] | list[str] | None = None,
    observed_git_head: str | None = None,
    source_version_taskbook_ref: dict[str, str] | None = None,
) -> dict[str, Any]:
    effective_protected_paths = tuple(protected_paths or DEFAULT_PROTECTED_PATHS)
    normalized_protected_paths = tuple(_normalize_path(path) for path in effective_protected_paths)
    normalized_protected_paths = tuple(path for path in normalized_protected_paths if path)
    normalized_changes = _normalize_candidate_changes(candidate_changes)
    unknown_change_inputs = _unknown_change_inputs(normalized_changes)
    protected_change_rows = [
        row for row in normalized_changes if row["normalized_path"] in normalized_protected_paths
    ]
    protected_mutations = [
        row for row in protected_change_rows if _is_mutation_action(row["attempted_action"])
    ]
    protected_read_only = [
        row for row in protected_change_rows if _is_read_only_action(row["attempted_action"])
    ]

    token = _authorization_token(commander_authorization)
    scope_hash = _authorization_scope_hash(commander_authorization)
    authorization_matches = _authorization_matches(
        commander_authorization=commander_authorization,
        protected_mutations=protected_mutations,
    )

    if candidate_changes is None:
        mutation_attempt_class = MUTATION_ATTEMPT_CLASS_UNKNOWN_RISK
        gate_result = GATE_RESULT_KNOWN_UNKNOWN
        failure_reason = "candidate_changes_missing"
    elif unknown_change_inputs:
        mutation_attempt_class = MUTATION_ATTEMPT_CLASS_UNKNOWN_RISK
        gate_result = GATE_RESULT_KNOWN_UNKNOWN
        failure_reason = "candidate_change_unclassifiable"
    elif protected_mutations and authorization_matches:
        mutation_attempt_class = MUTATION_ATTEMPT_CLASS_COMMANDER_AUTHORIZED_CANDIDATE
        gate_result = GATE_RESULT_REQUIRE_COMMANDER_HARD_GATE
        failure_reason = "commander_hard_gate_required_for_master_mutation"
    elif protected_mutations:
        mutation_attempt_class = MUTATION_ATTEMPT_CLASS_UNAUTHORIZED_MASTER_MUTATION
        gate_result = GATE_RESULT_BLOCK_UNAUTHORIZED_MUTATION
        failure_reason = "protected_master_path_mutation_without_commander_hard_gate"
    elif protected_read_only:
        mutation_attempt_class = MUTATION_ATTEMPT_CLASS_READ_ONLY_MASTER_ACCESS
        gate_result = GATE_RESULT_ALLOW_READ_ONLY
        failure_reason = None
    else:
        mutation_attempt_class = MUTATION_ATTEMPT_CLASS_NO_MASTER_MUTATION
        gate_result = GATE_RESULT_ALLOW_READ_ONLY
        failure_reason = None

    fail_closed_result = (
        FAIL_CLOSED_RESULT_PASS
        if gate_result == GATE_RESULT_ALLOW_READ_ONLY
        else FAIL_CLOSED_RESULT_FAIL_CLOSED
    )
    blocked_attempt = _blocked_attempt_or_none(protected_mutations, gate_result)
    result = {
        "mutation_gate_status": "evaluated",
        "mutation_attempt_class": mutation_attempt_class,
        "gate_result": gate_result,
        "fail_closed_result": fail_closed_result,
        "protected_paths": list(normalized_protected_paths),
        "protected_path_check": _protected_path_check_rows(normalized_changes, normalized_protected_paths),
        "mutation_attempt_classification": {
            "protected_mutation_count": len(protected_mutations),
            "protected_read_only_count": len(protected_read_only),
            "unknown_change_input_count": len(unknown_change_inputs),
        },
        "commander_hard_gate_requirement_check": {
            "commander_authorization_token_present": token is not None,
            "authorization_scope_hash_present": scope_hash is not None,
            "authorization_scope_matches_candidate": authorization_matches,
            "gate_does_not_generate_commander_token": True,
        },
        "commander_authorization_token_present": token is not None,
        "authorization_scope_hash_or_none": scope_hash,
        "failure_reason_or_none": failure_reason,
        "blocked_attempt_or_none": blocked_attempt,
        "unknown_change_inputs": unknown_change_inputs,
        "observed_git_head": observed_git_head,
        "source_version_taskbook_ref": _safe_source_version_taskbook_ref(source_version_taskbook_ref),
        "canonical_receipt_generation": "deferred_not_generated",
        "canonical_payload_hash_finalization": "deferred_not_finalized",
        "mutation_gate_result_is_authority": False,
        "forbidden_authority_claims_present": [],
    }
    _assert_no_forbidden_result_fields(result)
    return result


def _normalize_candidate_changes(candidate_changes: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if candidate_changes is None:
        return []
    if not isinstance(candidate_changes, list):
        return [
            {
                "protected_path": None,
                "attempted_action": None,
                "detected_from": "candidate_changes",
                "normalized_path": None,
                "input_status": "invalid_candidate_changes_type",
            }
        ]

    rows = []
    for index, change in enumerate(candidate_changes):
        if not isinstance(change, dict):
            rows.append(
                {
                    "protected_path": None,
                    "attempted_action": None,
                    "detected_from": f"candidate_changes[{index}]",
                    "normalized_path": None,
                    "input_status": "invalid_change_type",
                }
            )
            continue
        raw_path = _dict_get(change, "protected_path")
        if raw_path is None:
            raw_path = _dict_get(change, "path")
        if raw_path is None:
            raw_path = _dict_get(change, "file")
        action = _normalize_action(_dict_get(change, "attempted_action") or _dict_get(change, "action"))
        detected_from = _first_non_empty(_dict_get(change, "detected_from"), f"candidate_changes[{index}]")
        normalized_path = _normalize_path(raw_path)
        rows.append(
            {
                "protected_path": str(raw_path).strip() if raw_path is not None else None,
                "attempted_action": action,
                "detected_from": detected_from,
                "normalized_path": normalized_path,
                "input_status": "ok" if normalized_path and action else "missing_path_or_action",
            }
        )
    return rows


def _unknown_change_inputs(normalized_changes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unknown = []
    for row in normalized_changes:
        if row["input_status"] != "ok":
            unknown.append(dict(row))
            continue
        action = row["attempted_action"]
        if not _is_read_only_action(action) and not _is_mutation_action(action):
            unknown.append(dict(row))
    return unknown


def _protected_path_check_rows(
    normalized_changes: list[dict[str, Any]],
    protected_paths: tuple[str, ...],
) -> list[dict[str, Any]]:
    rows = []
    for change in normalized_changes:
        rows.append(
            {
                "protected_path": change["normalized_path"],
                "attempted_action": change["attempted_action"],
                "detected_from": change["detected_from"],
                "is_protected_path": change["normalized_path"] in protected_paths,
            }
        )
    return rows


def _blocked_attempt_or_none(
    protected_mutations: list[dict[str, Any]],
    gate_result: str,
) -> dict[str, Any] | None:
    if gate_result not in {
        GATE_RESULT_BLOCK_UNAUTHORIZED_MUTATION,
        GATE_RESULT_REQUIRE_COMMANDER_HARD_GATE,
    }:
        return None
    if not protected_mutations:
        return None
    first = protected_mutations[0]
    return {
        "protected_path": first["normalized_path"],
        "attempted_action": first["attempted_action"],
        "detected_from": first["detected_from"],
    }


def _authorization_matches(
    *,
    commander_authorization: dict[str, Any] | None,
    protected_mutations: list[dict[str, Any]],
) -> bool:
    if not protected_mutations or not isinstance(commander_authorization, dict):
        return False
    if _authorization_token(commander_authorization) is None:
        return False
    if _authorization_scope_hash(commander_authorization) is None:
        return False
    if str(_dict_get(commander_authorization, "authorization_status") or "").strip() not in {
        "commander_hard_gate_authorized",
        "hash_specific_commander_hard_gate_authorized",
    }:
        return False

    authorized_paths = {
        path for path in (_normalize_path(item) for item in _list_value(commander_authorization, "authorized_paths")) if path
    }
    authorized_actions = {
        action for action in (_normalize_action(item) for item in _list_value(commander_authorization, "authorized_actions")) if action
    }
    if not authorized_paths or not authorized_actions:
        return False
    return all(
        row["normalized_path"] in authorized_paths and row["attempted_action"] in authorized_actions
        for row in protected_mutations
    )


def _authorization_token(commander_authorization: dict[str, Any] | None) -> str | None:
    token = _dict_get(commander_authorization, "authorization_token")
    if token is None:
        token = _dict_get(commander_authorization, "commander_authorization_token")
    return _clean_non_empty_string(token)


def _authorization_scope_hash(commander_authorization: dict[str, Any] | None) -> str | None:
    scope_hash = _dict_get(commander_authorization, "authorization_scope_hash")
    if scope_hash is None:
        scope_hash = _dict_get(commander_authorization, "scope_sha256")
    clean = _clean_non_empty_string(scope_hash)
    return clean if _is_sha256(clean) else None


def _normalize_path(value: Any) -> str | None:
    clean = _clean_non_empty_string(value)
    if clean is None:
        return None
    clean = clean.replace("\\", "/")
    if clean.startswith(PROJECT_ROOT_MARKER):
        clean = clean[len(PROJECT_ROOT_MARKER) :]
    while clean.startswith("./"):
        clean = clean[2:]
    clean = posixpath.normpath(clean)
    if clean in {"", "."}:
        return None
    return clean.strip("/") if clean else None


def _normalize_action(value: Any) -> str | None:
    clean = _clean_non_empty_string(value)
    return clean.lower().replace("-", "_") if clean else None


def _dict_get(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return None


def _list_value(value: dict[str, Any], key: str) -> list[Any]:
    raw = value.get(key)
    return raw if isinstance(raw, list) else []


def _clean_non_empty_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    clean = value.strip()
    return clean or None


def _first_non_empty(*values: Any) -> str:
    for value in values:
        clean = _clean_non_empty_string(value)
        if clean is not None:
            return clean
    return "unknown"


def _is_read_only_action(action: str | None) -> bool:
    return action in READ_ONLY_ACTIONS


def _is_mutation_action(action: str | None) -> bool:
    return action in MUTATION_ACTIONS


def _is_sha256(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    clean = value.strip()
    return len(clean) == 64 and all(char in "0123456789abcdef" for char in clean)


def _safe_source_version_taskbook_ref(value: dict[str, Any] | None) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    safe_ref = {}
    for key in SAFE_SOURCE_VERSION_TASKBOOK_REF_FIELDS:
        raw = value.get(key)
        clean = _clean_non_empty_string(raw)
        if clean is not None:
            safe_ref[key] = clean
    return safe_ref


def _assert_no_forbidden_result_fields(result: dict[str, Any]) -> None:
    forbidden = sorted(_forbidden_field_paths(result))
    if forbidden:
        raise MasterTaskbookMutationGateError(
            "FORBIDDEN_MUTATION_GATE_RESULT_FIELD",
            "Mutation gate result contains forbidden authority or receipt fields.",
            details={"forbidden_fields": forbidden},
        )


def _forbidden_field_paths(value: Any, prefix: str = "") -> list[str]:
    if isinstance(value, dict):
        paths = []
        for key, nested_value in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if key in FORBIDDEN_MUTATION_GATE_RESULT_FIELDS:
                paths.append(path)
            paths.extend(_forbidden_field_paths(nested_value, path))
        return paths
    if isinstance(value, list):
        paths = []
        for index, item in enumerate(value):
            path = f"{prefix}[{index}]" if prefix else f"[{index}]"
            paths.extend(_forbidden_field_paths(item, path))
        return paths
    return []
