from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


DEFAULT_REGISTRY_REL_PATH = ".colameta/taskbooks/master_taskbook_registry.json"
EXPECTED_SCHEMA_VERSION = "master_taskbook_registry.v1"
EXPECTED_REGISTRY_RECORD_ID = "master_taskbook.current"
EXPECTED_PROJECT = "ColaMeta"
EXPECTED_MASTER_REVIEW_STATUS = "freeze_candidate_confirmed_for_exact_hash"
EXPECTED_PROJECT_FINAL_GOAL_REF = {
    "source_document": "PROJECT_MASTER_TASKBOOK.md",
    "field_name": "project_final_goal",
    "authority_boundary": "hash_bound_reference_only",
}
DEFAULT_EXPECTED_SOURCE_REFS = {
    "source_stage_taskbook_ref": {
        "path": "docs/taskbooks/stages/STAGE_01_MASTER_TASKBOOK_ANCHORING.md",
        "raw_snapshot_sha256": "f880585ed8d37639d215c9f440b37750defa9201f265b2fb7bd63cfdacf6c326",
        "id_field": "stage_id",
        "id": "stage_01_master_taskbook_anchoring",
    },
    "source_version_taskbook_ref": {
        "path": "docs/taskbooks/versions/stage-01/VERSION_STAGE_01_V1_1_MASTER_TASKBOOK_REGISTRY_V1.md",
        "raw_snapshot_sha256": "503af0ff7cdac71c55b9fa3d47a09d3fc484c851daffb244a52385ac0dd2b896",
        "id_field": "version_id",
        "id": "stage_01_v1_1_master_taskbook_registry_v1",
    },
}
EXPECTED_FORBIDDEN_AUTHORITY_CLAIMS = (
    "master_is_active_execution_authority",
    "master_is_accepted_delivery_state",
    "freeze_candidate_implies_executor_authority",
    "registry_record_can_mutate_master",
    "registry_record_can_override_delivery_state_gate",
)

REQUIRED_FIELDS = (
    "schema_version",
    "registry_record_id",
    "project",
    "workspace",
    "master_taskbook_path",
    "master_raw_snapshot_sha256",
    "master_review_status",
    "master_authority_boundary",
    "project_final_goal_ref",
    "source_stage_taskbook_ref",
    "source_version_taskbook_ref",
    "observed_git_head",
    "observed_origin_main_local_tracking_ref",
    "ahead_behind_from_local_refs",
    "live_remote_status_not_validated",
    "mutation_boundary",
    "forbidden_authority_claims",
    "created_at",
)
OPTIONAL_FIELDS: tuple[str, ...] = ()
ALLOWED_TOP_LEVEL_FIELDS = frozenset((*REQUIRED_FIELDS, *OPTIONAL_FIELDS))

AUTHORITY_BOUNDARY_EXPECTATIONS = {
    "review_status_is_reference_only": True,
    "active_execution_authority": False,
    "executor_authority": False,
    "route_transition_authority": False,
    "delivery_state_authority": False,
    "review_acceptance_authority": False,
    "freeze_candidate_implies_accepted": False,
}

MUTATION_BOUNDARY_EXPECTATIONS = {
    "master_taskbook_mutation_allowed": False,
    "registry_can_mutate_master": False,
    "requires_separate_hash_specific_authorization": True,
}
ALLOWED_AHEAD_BEHIND_FIELDS = frozenset({"ahead", "behind", "source"})
ALLOWED_TRUE_AUTHORITY_KEYS = frozenset(
    {
        "review_status_is_reference_only",
        "requires_separate_hash_specific_authorization",
        "live_remote_status_not_validated",
    }
)
FORBIDDEN_AUTHORITY_KEY_MARKERS = (
    "authority",
    "authorized",
    "authorization",
    "accepted",
    "execution",
    "executor",
    "dispatch",
    "route_transition",
    "delivery_state",
    "review_acceptance",
    "can_mutate",
    "mutation_allowed",
    "can_override",
)


class MasterTaskbookRegistryError(ValueError):
    def __init__(self, error_code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.details = details or {}


def default_master_taskbook_registry_path(project_root: str | Path) -> Path:
    return Path(project_root).expanduser().resolve() / DEFAULT_REGISTRY_REL_PATH


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_master_taskbook_registry(
    project_root: str | Path,
    registry_path: str | Path | None = None,
    *,
    verify_master_hash: bool = True,
    expected_source_refs: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    root = Path(project_root).expanduser().resolve()
    path = _resolve_registry_path(root, registry_path)
    if not path.is_file():
        raise MasterTaskbookRegistryError(
            "REGISTRY_FILE_MISSING",
            f"Master Taskbook registry file does not exist: {path}",
            details={"registry_path": str(path)},
        )

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MasterTaskbookRegistryError(
            "REGISTRY_JSON_INVALID",
            f"Master Taskbook registry JSON is invalid: {exc}",
            details={"registry_path": str(path)},
        ) from exc

    return validate_master_taskbook_registry(
        payload,
        project_root=root,
        registry_path=path,
        verify_master_hash=verify_master_hash,
        expected_source_refs=expected_source_refs,
    )


def validate_master_taskbook_registry(
    record: dict[str, Any],
    *,
    project_root: str | Path,
    registry_path: str | Path | None = None,
    verify_master_hash: bool = True,
    expected_source_refs: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise MasterTaskbookRegistryError("REGISTRY_RECORD_INVALID", "Master Taskbook registry must be a JSON object.")

    missing = [field for field in REQUIRED_FIELDS if field not in record]
    if missing:
        raise MasterTaskbookRegistryError(
            "REQUIRED_FIELD_MISSING",
            "Master Taskbook registry is missing required fields.",
            details={"missing_fields": missing},
        )
    unsupported = sorted(str(field) for field in record if field not in ALLOWED_TOP_LEVEL_FIELDS)
    if unsupported:
        raise MasterTaskbookRegistryError(
            "UNSUPPORTED_REGISTRY_FIELD",
            "Master Taskbook registry contains unsupported top-level fields.",
            details={"unsupported_fields": unsupported},
        )
    _reject_forbidden_authority_claims(record)

    root = Path(project_root).expanduser().resolve()
    if registry_path is None:
        registry_path = default_master_taskbook_registry_path(root)
    registry = _resolve_registry_path(root, registry_path)

    workspace = _required_str(record, "workspace")
    if Path(workspace).expanduser().resolve() != root:
        raise MasterTaskbookRegistryError(
            "WORKSPACE_MISMATCH",
            "Registry workspace does not match the current project root.",
            details={"workspace": workspace, "project_root": str(root)},
        )
    _require_exact_str(record, "schema_version", EXPECTED_SCHEMA_VERSION)
    _require_exact_str(record, "registry_record_id", EXPECTED_REGISTRY_RECORD_ID)
    _require_exact_str(record, "project", EXPECTED_PROJECT)
    _validate_exact_object(
        record=_required_dict(record, "project_final_goal_ref"),
        field="project_final_goal_ref",
        expected=EXPECTED_PROJECT_FINAL_GOAL_REF,
    )

    expected_hash = _required_sha256(record, "master_raw_snapshot_sha256")
    master_path = _resolve_project_relpath(root, _required_str(record, "master_taskbook_path"), "master_taskbook_path")
    actual_hash = None
    if verify_master_hash:
        if not master_path.is_file():
            raise MasterTaskbookRegistryError(
                "MASTER_TASKBOOK_MISSING",
                "Master Taskbook file declared by registry does not exist.",
                details={"master_taskbook_path": str(master_path)},
            )
        actual_hash = sha256_file(master_path)
        if actual_hash != expected_hash:
            raise MasterTaskbookRegistryError(
                "MASTER_HASH_MISMATCH",
                "Master Taskbook hash does not match registry binding.",
                details={"expected": expected_hash, "actual": actual_hash},
            )

    review_status = _required_str(record, "master_review_status")
    if review_status != EXPECTED_MASTER_REVIEW_STATUS:
        raise MasterTaskbookRegistryError(
            "MASTER_REVIEW_STATUS_UNSUPPORTED",
            "Registry must preserve the exact Master freeze-candidate review status.",
            details={"master_review_status": review_status},
        )

    _validate_boolean_expectations(
        record=_required_dict(record, "master_authority_boundary"),
        field="master_authority_boundary",
        expectations=AUTHORITY_BOUNDARY_EXPECTATIONS,
    )
    _validate_boolean_expectations(
        record=_required_dict(record, "mutation_boundary"),
        field="mutation_boundary",
        expectations=MUTATION_BOUNDARY_EXPECTATIONS,
    )
    _validate_ahead_behind(_required_dict(record, "ahead_behind_from_local_refs"))
    source_refs = expected_source_refs or DEFAULT_EXPECTED_SOURCE_REFS
    _validate_source_ref(
        root=root,
        value=_required_dict(record, "source_stage_taskbook_ref"),
        field="source_stage_taskbook_ref",
        expected=source_refs["source_stage_taskbook_ref"],
    )
    _validate_source_ref(
        root=root,
        value=_required_dict(record, "source_version_taskbook_ref"),
        field="source_version_taskbook_ref",
        expected=source_refs["source_version_taskbook_ref"],
    )
    _validate_forbidden_authority_claims(record.get("forbidden_authority_claims"))

    if record.get("live_remote_status_not_validated") is not True:
        raise MasterTaskbookRegistryError(
            "REMOTE_STATUS_BOUNDARY_INVALID",
            "Registry must record that live remote status was not validated under this local-only slice.",
        )

    _required_sha_like(record, "observed_git_head")
    _required_sha_like(record, "observed_origin_main_local_tracking_ref")

    return {
        "ok": True,
        "registry_path": str(registry),
        "project_root": str(root),
        "master_taskbook_path": str(master_path),
        "master_expected_sha256": expected_hash,
        "master_actual_sha256": actual_hash,
        "master_hash_verified": verify_master_hash,
        "record": record,
    }


def _resolve_registry_path(root: Path, registry_path: str | Path | None) -> Path:
    if registry_path is None:
        path = default_master_taskbook_registry_path(root).resolve()
    else:
        candidate = Path(registry_path).expanduser()
        path = candidate if candidate.is_absolute() else root / candidate
        path = path.resolve()
    _ensure_inside_project(root, path, "registry_path")
    return path


def _resolve_project_relpath(root: Path, raw_path: str, field: str) -> Path:
    if not raw_path.strip():
        raise MasterTaskbookRegistryError("FIELD_EMPTY", f"{field} must be a non-empty path.")
    candidate = Path(raw_path)
    if candidate.is_absolute():
        raise MasterTaskbookRegistryError("ABSOLUTE_PATH_FORBIDDEN", f"{field} must be project-relative.")
    resolved = (root / candidate).resolve()
    _ensure_inside_project(root, resolved, field)
    return resolved


def _ensure_inside_project(root: Path, path: Path, field: str) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise MasterTaskbookRegistryError(
            "PATH_OUTSIDE_PROJECT",
            f"{field} must stay inside the project root.",
            details={"field": field, "path": str(path), "project_root": str(root)},
        ) from exc


def _required_str(record: dict[str, Any], field: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        raise MasterTaskbookRegistryError("FIELD_INVALID", f"{field} must be a non-empty string.")
    return value.strip()


def _require_exact_str(record: dict[str, Any], field: str, expected: str) -> None:
    value = _required_str(record, field)
    if value != expected:
        raise MasterTaskbookRegistryError(
            "FIELD_VALUE_UNSUPPORTED",
            f"{field} must be {expected!r}.",
            details={"field": field, "expected": expected, "actual": value},
        )


def _required_dict(record: dict[str, Any], field: str) -> dict[str, Any]:
    value = record.get(field)
    if not isinstance(value, dict):
        raise MasterTaskbookRegistryError("FIELD_INVALID", f"{field} must be an object.")
    return value


def _required_sha256(record: dict[str, Any], field: str) -> str:
    value = _required_str(record, field)
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise MasterTaskbookRegistryError("FIELD_INVALID", f"{field} must be a lowercase sha256 hex string.")
    return value


def _required_sha_like(record: dict[str, Any], field: str) -> str:
    value = _required_str(record, field)
    if len(value) < 7 or any(char not in "0123456789abcdef" for char in value):
        raise MasterTaskbookRegistryError("FIELD_INVALID", f"{field} must be a lowercase git hash string.")
    return value


def _validate_boolean_expectations(
    *,
    record: dict[str, Any],
    field: str,
    expectations: dict[str, bool],
) -> None:
    unsupported = sorted(str(key) for key in record if key not in expectations)
    if unsupported:
        raise MasterTaskbookRegistryError(
            "AUTHORITY_BOUNDARY_UNSUPPORTED_FIELD",
            f"{field} contains unsupported fields.",
            details={"field": field, "unsupported_fields": unsupported},
        )
    for key, expected in expectations.items():
        if record.get(key) is not expected:
            raise MasterTaskbookRegistryError(
                "AUTHORITY_BOUNDARY_INVALID",
                f"{field}.{key} must be {expected!r}.",
                details={"field": field, "key": key, "expected": expected, "actual": record.get(key)},
            )


def _validate_ahead_behind(value: dict[str, Any]) -> None:
    unsupported = sorted(str(key) for key in value if key not in ALLOWED_AHEAD_BEHIND_FIELDS)
    if unsupported:
        raise MasterTaskbookRegistryError(
            "AHEAD_BEHIND_UNSUPPORTED_FIELD",
            "ahead_behind_from_local_refs contains unsupported fields.",
            details={"unsupported_fields": unsupported},
        )
    for key in ("ahead", "behind"):
        if not isinstance(value.get(key), int) or value[key] < 0:
            raise MasterTaskbookRegistryError(
                "AHEAD_BEHIND_INVALID",
                f"ahead_behind_from_local_refs.{key} must be a non-negative integer.",
            )


def _validate_source_ref(*, root: Path, value: dict[str, Any], field: str, expected: dict[str, str]) -> None:
    id_field = expected["id_field"]
    allowed_fields = frozenset({"path", "raw_snapshot_sha256", id_field})
    unsupported = sorted(str(key) for key in value if key not in allowed_fields)
    if unsupported:
        raise MasterTaskbookRegistryError(
            "SOURCE_REF_UNSUPPORTED_FIELD",
            f"{field} contains unsupported fields.",
            details={"field": field, "unsupported_fields": unsupported},
        )
    _validate_exact_object(
        record=value,
        field=field,
        expected={
            "path": expected["path"],
            "raw_snapshot_sha256": expected["raw_snapshot_sha256"],
            id_field: expected["id"],
        },
    )
    source_path = _resolve_project_relpath(root, str(value["path"]), f"{field}.path")
    if not source_path.is_file():
        raise MasterTaskbookRegistryError(
            "SOURCE_REF_FILE_MISSING",
            f"{field}.path does not exist.",
            details={"field": field, "path": str(source_path)},
        )
    actual_hash = sha256_file(source_path)
    if actual_hash != expected["raw_snapshot_sha256"]:
        raise MasterTaskbookRegistryError(
            "SOURCE_REF_HASH_MISMATCH",
            f"{field}.raw_snapshot_sha256 does not match current file content.",
            details={
                "field": field,
                "path": str(source_path),
                "expected": expected["raw_snapshot_sha256"],
                "actual": actual_hash,
            },
        )


def _validate_exact_object(*, record: dict[str, Any], field: str, expected: dict[str, str]) -> None:
    unsupported = sorted(str(key) for key in record if key not in expected)
    if unsupported:
        raise MasterTaskbookRegistryError(
            "OBJECT_UNSUPPORTED_FIELD",
            f"{field} contains unsupported fields.",
            details={"field": field, "unsupported_fields": unsupported},
        )
    missing = [key for key in expected if key not in record]
    if missing:
        raise MasterTaskbookRegistryError(
            "OBJECT_REQUIRED_FIELD_MISSING",
            f"{field} is missing required fields.",
            details={"field": field, "missing_fields": missing},
        )
    for key, expected_value in expected.items():
        actual = record.get(key)
        if actual != expected_value:
            raise MasterTaskbookRegistryError(
                "OBJECT_FIELD_VALUE_UNSUPPORTED",
                f"{field}.{key} must be {expected_value!r}.",
                details={"field": field, "key": key, "expected": expected_value, "actual": actual},
            )


def _validate_forbidden_authority_claims(value: Any) -> None:
    if not isinstance(value, list):
        raise MasterTaskbookRegistryError(
            "FORBIDDEN_AUTHORITY_CLAIMS_INVALID",
            "forbidden_authority_claims must be a list.",
        )
    if value != list(EXPECTED_FORBIDDEN_AUTHORITY_CLAIMS):
        raise MasterTaskbookRegistryError(
            "FORBIDDEN_AUTHORITY_CLAIMS_UNSUPPORTED",
            "forbidden_authority_claims must preserve the exact Stage 1 / v1.1 boundary list.",
            details={"expected": list(EXPECTED_FORBIDDEN_AUTHORITY_CLAIMS), "actual": value},
        )


def _reject_forbidden_authority_claims(value: Any, path: str = "record") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            clean_key = str(key).strip()
            lower_key = clean_key.lower()
            if _is_truthy_authority_claim(lower_key, child):
                raise MasterTaskbookRegistryError(
                    "FORBIDDEN_AUTHORITY_CLAIM",
                    "Registry contains a forbidden authority claim.",
                    details={"path": f"{path}.{clean_key}", "value": child},
                )
            _reject_forbidden_authority_claims(child, f"{path}.{clean_key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_forbidden_authority_claims(child, f"{path}[{index}]")


def _is_truthy_authority_claim(key: str, value: Any) -> bool:
    if key in ALLOWED_TRUE_AUTHORITY_KEYS:
        return False
    if not any(marker in key for marker in FORBIDDEN_AUTHORITY_KEY_MARKERS):
        return False
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "allowed", "active", "accepted", "authorized"}
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value != 0
    return False
