from __future__ import annotations

import fnmatch
from typing import Any


SCOPE_PACK_READY = "scope_evidence_pack_ready"
SCOPE_PACK_FAILED_CLOSED = "scope_evidence_pack_failed_closed"
VALID_SCOPE_RESULTS = frozenset({"in_scope", "out_of_scope", "unknown_needs_review"})
REQUIRED_SCOPE_PACK_FIELDS = frozenset(
    {
        "scope_pack_id",
        "version_taskbook_ref",
        "execution_envelope_ref",
        "allowed_files",
        "forbidden_files",
        "observed_touched_files",
        "observed_mutations",
        "generated_files",
        "ignored_runtime_files",
        "scope_violations",
        "known_gaps",
        "remaining_risks",
        "authority_boundary",
    }
)
AUTHORITY_BOUNDARY_EXPECTATIONS = {
    "scope_pack_result_is_authority": False,
    "scope_pass_implies_review_acceptance": False,
    "scope_pack_writes_delivery_state": False,
    "scope_pack_authorizes_executor_dispatch": False,
    "scope_pack_authorizes_plan_mutation": False,
    "creates_review_decision": False,
    "emits_gate_event": False,
}
FORBIDDEN_SCOPE_PACK_CLAIM_KEYS = frozenset(
    {
        "out_of_scope_summarized_as_in_scope",
        "unknown_summarized_as_in_scope",
        "scope_pass_implies_review_acceptance",
        "delivery_state_accepted",
        "review_accepted",
        "review_acceptance",
        "scope_pack_result_is_authority",
        "scope_pack_writes_delivery_state",
        "scope_pack_authorizes_executor_dispatch",
        "scope_pack_authorizes_plan_mutation",
        "creates_review_decision",
        "emits_gate_event",
        "writes_delivery_state",
    }
)


class ScopeEvidencePackError(ValueError):
    def __init__(self, error_code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.details = details or {}


def build_scope_evidence_pack(
    *,
    scope_pack_id: str,
    version_taskbook_ref: dict[str, Any],
    execution_envelope_ref: dict[str, Any],
    allowed_files: list[str],
    forbidden_files: list[str],
    observed_touched_files: list[str],
    observed_mutations: list[dict[str, Any]],
    generated_files: list[str],
    ignored_runtime_files: list[str],
    known_gaps: list[dict[str, Any]],
    remaining_risks: list[dict[str, Any]],
    declared_scope_result: str | None = None,
    authority_boundary: dict[str, bool] | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    known_conflicts: list[dict[str, Any]] = []

    for field, value in (
        ("allowed_files", allowed_files),
        ("forbidden_files", forbidden_files),
        ("observed_touched_files", observed_touched_files),
        ("observed_mutations", observed_mutations),
        ("generated_files", generated_files),
        ("ignored_runtime_files", ignored_runtime_files),
        ("known_gaps", known_gaps),
        ("remaining_risks", remaining_risks),
    ):
        if not isinstance(value, list):
            blockers.append(_blocker("SCOPE_FIELD_INVALID", f"{field} must be a list.", {"field": field}))

    if not allowed_files:
        blockers.append(_blocker("ALLOWED_FILES_MISSING", "Scope pack requires allowed_files.", {}))

    ignored = set(ignored_runtime_files if isinstance(ignored_runtime_files, list) else [])
    paths_to_check = _dedupe(
        [path for path in _string_list(observed_touched_files) if path not in ignored]
        + [path for path in _string_list(generated_files) if path not in ignored]
        + [path for path in _mutation_paths(observed_mutations) if path not in ignored]
    )
    scope_violations = _scope_violations(paths_to_check, _string_list(allowed_files), _string_list(forbidden_files))
    scope_result = _scope_result(paths_to_check, scope_violations, known_gaps)

    if declared_scope_result is not None and declared_scope_result not in VALID_SCOPE_RESULTS:
        blockers.append(
            _blocker(
                "DECLARED_SCOPE_RESULT_UNSUPPORTED",
                "declared_scope_result is unsupported.",
                {"declared_scope_result": declared_scope_result, "valid_scope_results": sorted(VALID_SCOPE_RESULTS)},
            )
        )
    if declared_scope_result == "in_scope" and scope_result == "out_of_scope":
        blockers.append(
            _blocker(
                "OUT_OF_SCOPE_SUMMARIZED_AS_IN_SCOPE",
                "Scope pack cannot summarize out_of_scope evidence as in_scope.",
                {"computed_scope_result": scope_result, "declared_scope_result": declared_scope_result},
            )
        )
    if declared_scope_result == "in_scope" and scope_result == "unknown_needs_review":
        blockers.append(
            _blocker(
                "UNKNOWN_SUMMARIZED_AS_IN_SCOPE",
                "Scope pack cannot summarize unknown scope evidence as in_scope.",
                {"computed_scope_result": scope_result, "declared_scope_result": declared_scope_result},
            )
        )

    boundary = authority_boundary if authority_boundary is not None else dict(AUTHORITY_BOUNDARY_EXPECTATIONS)
    if boundary != AUTHORITY_BOUNDARY_EXPECTATIONS:
        blockers.append(
            _blocker(
                "FORBIDDEN_SCOPE_PACK_AUTHORITY_BOUNDARY",
                "Scope evidence pack authority boundary must remain false.",
                {"unexpected_truthy_keys": _truthy_authority_boundary_keys(boundary)},
            )
        )

    claims_source = extra_claims if isinstance(extra_claims, dict) else {}
    forbidden_claims = _forbidden_truthy_claims(claims_source, "extra_claims")
    if forbidden_claims:
        blockers.append(
            _blocker(
                "FORBIDDEN_SCOPE_PACK_AUTHORITY_CLAIM",
                "Scope evidence pack contains forbidden authority claims.",
                {"forbidden_claims": _safe_forbidden_claims(forbidden_claims)},
            )
        )
        known_conflicts.extend(
            {"conflict_type": "authority_boundary", "path": item["path"], "claim": item["key"]}
            for item in forbidden_claims
        )

    pack = {
        "scope_pack_id": scope_pack_id,
        "scope_pack_status": SCOPE_PACK_FAILED_CLOSED if blockers else SCOPE_PACK_READY,
        "version_taskbook_ref": version_taskbook_ref,
        "execution_envelope_ref": execution_envelope_ref,
        "allowed_files": allowed_files,
        "forbidden_files": forbidden_files,
        "observed_touched_files": observed_touched_files,
        "observed_mutations": observed_mutations,
        "generated_files": generated_files,
        "ignored_runtime_files": ignored_runtime_files,
        "scope_result": scope_result,
        "declared_scope_result": declared_scope_result,
        "scope_violations": scope_violations,
        "known_gaps": known_gaps,
        "remaining_risks": remaining_risks,
        "failures_and_blockers": blockers,
        "known_conflicts": known_conflicts,
        "authority_boundary": dict(AUTHORITY_BOUNDARY_EXPECTATIONS),
        "review_accepted": False,
        "delivery_state_accepted": False,
        "creates_review_decision": False,
        "emits_gate_event": False,
        "writes_delivery_state": False,
    }
    assert_scope_evidence_pack_contract(pack)
    return pack


def assert_scope_evidence_pack_contract(pack: dict[str, Any]) -> None:
    if not isinstance(pack, dict):
        raise ScopeEvidencePackError("SCOPE_PACK_INVALID", "Scope evidence pack must be an object.")
    missing = sorted(REQUIRED_SCOPE_PACK_FIELDS - set(pack))
    if missing:
        raise ScopeEvidencePackError(
            "SCOPE_PACK_REQUIRED_FIELD_MISSING",
            "Scope evidence pack is missing required fields.",
            details={"missing_fields": missing},
        )
    if pack.get("scope_result") not in VALID_SCOPE_RESULTS:
        raise ScopeEvidencePackError(
            "SCOPE_RESULT_UNSUPPORTED",
            "Scope result is unsupported.",
            details={"scope_result": pack.get("scope_result"), "valid_scope_results": sorted(VALID_SCOPE_RESULTS)},
        )
    status = pack.get("scope_pack_status")
    blockers = _list_or_empty(pack.get("failures_and_blockers"))
    if status == SCOPE_PACK_READY and blockers:
        raise ScopeEvidencePackError(
            "SCOPE_PACK_READY_WITH_BLOCKERS",
            "Ready scope pack must not include blockers.",
            details={"blocking_codes": [item.get("code") for item in blockers if isinstance(item, dict)]},
        )
    if status == SCOPE_PACK_FAILED_CLOSED and not blockers:
        raise ScopeEvidencePackError(
            "SCOPE_PACK_FAILED_WITHOUT_BLOCKERS",
            "Failed scope pack must include at least one blocker.",
        )
    if status not in {SCOPE_PACK_READY, SCOPE_PACK_FAILED_CLOSED}:
        raise ScopeEvidencePackError(
            "SCOPE_PACK_STATUS_INVALID",
            "Scope pack status is unsupported.",
            details={"scope_pack_status": status},
        )
    if pack.get("authority_boundary") != AUTHORITY_BOUNDARY_EXPECTATIONS:
        raise ScopeEvidencePackError(
            "FORBIDDEN_SCOPE_PACK_AUTHORITY_CLAIM",
            "Scope pack authority boundary must remain false.",
            details={"expected": AUTHORITY_BOUNDARY_EXPECTATIONS, "actual": pack.get("authority_boundary")},
        )
    forbidden_claims = _forbidden_truthy_claims(pack, "scope_pack")
    if forbidden_claims:
        raise ScopeEvidencePackError(
            "FORBIDDEN_SCOPE_PACK_RESULT_CLAIM",
            "Scope pack contains forbidden authority claims.",
            details={"forbidden_claims": _safe_forbidden_claims(forbidden_claims)},
        )


def _scope_result(paths_to_check: list[str], scope_violations: list[dict[str, Any]], known_gaps: Any) -> str:
    if scope_violations:
        return "out_of_scope"
    if not paths_to_check and _has_known_gap(known_gaps):
        return "unknown_needs_review"
    return "in_scope"


def _scope_violations(paths: list[str], allowed_patterns: list[str], forbidden_patterns: list[str]) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    for path in paths:
        forbidden_matches = [pattern for pattern in forbidden_patterns if _matches(path, pattern)]
        if forbidden_matches:
            violations.append({"path": path, "violation_type": "forbidden_file_touched", "matched_patterns": forbidden_matches})
            continue
        if not any(_matches(path, pattern) for pattern in allowed_patterns):
            violations.append({"path": path, "violation_type": "outside_allowed_files", "matched_patterns": []})
    return violations


def _mutation_paths(value: Any) -> list[str]:
    paths: list[str] = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict) and isinstance(item.get("path"), str):
                paths.append(item["path"])
    return paths


def _matches(path: str, pattern: str) -> bool:
    return fnmatch.fnmatchcase(path, pattern)


def _has_known_gap(value: Any) -> bool:
    return isinstance(value, list) and bool(value)


def _string_list(value: Any) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _blocker(code: str, message: str, details: dict[str, Any]) -> dict[str, Any]:
    return {"code": code, "message": message, "details": details, "blocking": True}


def _list_or_empty(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _truthy_authority_boundary_keys(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return []
    return [str(key) for key, child in value.items() if key in AUTHORITY_BOUNDARY_EXPECTATIONS and _truthy_claim(child)]


def _forbidden_truthy_claims(value: Any, path: str = "scope_pack") -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if str(key) in FORBIDDEN_SCOPE_PACK_CLAIM_KEYS and _truthy_claim(child):
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
