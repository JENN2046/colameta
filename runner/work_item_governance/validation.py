from __future__ import annotations

from typing import Any

from runner.work_item_governance.canonical import canonical_sha256
from runner.work_item_governance.contracts import (
    MAX_TEXT_LENGTH,
    ORIGIN_KINDS,
    SHA256_PATTERN,
)
from runner.work_item_governance.errors import WorkItemGovernanceError
from runner.work_item_governance.ids import is_stable_id


def require_object(value: Any, field: str, *, non_empty: bool = False) -> dict[str, Any]:
    if not isinstance(value, dict) or (non_empty and not value):
        raise WorkItemGovernanceError(
            "FIELD_OBJECT_REQUIRED",
            f"{field} must be {'a non-empty ' if non_empty else 'an '}object.",
            details={"field": field},
        )
    return dict(value)


def require_metadata_object(value: Any, field: str) -> dict[str, Any]:
    metadata = require_object(value, field)
    if len(metadata) > 128:
        raise WorkItemGovernanceError(
            "METADATA_TOO_LARGE",
            f"{field} has too many top-level properties.",
            details={"field": field, "max_properties": 128, "actual_properties": len(metadata)},
        )
    return metadata


def require_text(
    value: Any,
    field: str,
    *,
    nullable: bool = False,
    max_length: int = MAX_TEXT_LENGTH,
) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not value.strip():
        raise WorkItemGovernanceError(
            "FIELD_TEXT_REQUIRED",
            f"{field} must be a non-empty string.",
            details={"field": field},
        )
    normalized = value.strip()
    if len(normalized) > max_length:
        raise WorkItemGovernanceError(
            "FIELD_TEXT_TOO_LONG",
            f"{field} exceeds the allowed length.",
            details={"field": field, "max_length": max_length, "actual_length": len(normalized)},
        )
    return normalized


def optional_text(value: Any, field: str, *, max_length: int = MAX_TEXT_LENGTH) -> str | None:
    if value is None:
        return None
    return require_text(value, field, nullable=True, max_length=max_length)


def require_positive_integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise WorkItemGovernanceError(
            "POSITIVE_INTEGER_REQUIRED",
            f"{field} must be a positive integer.",
            details={"field": field, "actual": value},
        )
    return value


def require_non_negative_integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise WorkItemGovernanceError(
            "NON_NEGATIVE_INTEGER_REQUIRED",
            f"{field} must be a non-negative integer.",
            details={"field": field, "actual": value},
        )
    return value


def require_sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None:
        raise WorkItemGovernanceError(
            "SHA256_REQUIRED",
            f"{field} must be a lowercase SHA-256 digest.",
            details={"field": field},
        )
    return value


def require_stable_id(value: Any, kind: str, field: str | None = None) -> str:
    if not is_stable_id(value, kind):
        raise WorkItemGovernanceError(
            "STABLE_ID_INVALID",
            f"{field or kind} must be a valid {kind} UUIDv7 identifier.",
            details={"field": field or kind, "kind": kind},
        )
    return str(value)


def normalize_origin(value: Any, *, imported: bool | None = None) -> dict[str, Any]:
    origin = require_object(value, "origin", non_empty=True)
    unknown = sorted(set(origin) - {"kind", "ref", "snapshot_digest"})
    if unknown:
        raise WorkItemGovernanceError(
            "ORIGIN_FIELD_UNSUPPORTED",
            "Origin contains unsupported fields.",
            details={"unsupported_fields": unknown},
        )
    kind = origin.get("kind")
    if kind not in ORIGIN_KINDS:
        raise WorkItemGovernanceError(
            "ORIGIN_KIND_UNSUPPORTED",
            "Origin kind is unsupported.",
            details={"kind": kind, "supported": sorted(ORIGIN_KINDS)},
        )
    if imported is True and kind != "imported":
        raise WorkItemGovernanceError("IMPORT_ORIGIN_REQUIRED", "Legacy import must use origin.kind=imported.")
    if imported is False and kind == "imported":
        raise WorkItemGovernanceError(
            "IMPORT_COMMAND_REQUIRED",
            "origin.kind=imported must use the explicit legacy import preview/apply command.",
        )
    ref = origin.get("ref")
    if ref is not None:
        ref = require_text(ref, "origin.ref", max_length=2048)
    return {
        "kind": kind,
        "ref": ref,
        "snapshot_digest": require_sha256(origin.get("snapshot_digest"), "origin.snapshot_digest"),
    }


def normalize_actor(value: Any, field: str = "actor") -> dict[str, Any]:
    if isinstance(value, str):
        value = {"id": value, "kind": "user"}
    actor = require_object(value, field, non_empty=True)
    unknown = sorted(set(actor) - {"id", "kind", "display_name"})
    if unknown:
        raise WorkItemGovernanceError(
            "ACTOR_FIELD_UNSUPPORTED",
            f"{field} contains unsupported fields.",
            details={"unsupported_fields": unknown},
        )
    return {
        "id": require_text(actor.get("id"), f"{field}.id", max_length=512),
        "kind": require_text(actor.get("kind", "user"), f"{field}.kind", max_length=128),
        "display_name": optional_text(actor.get("display_name"), f"{field}.display_name", max_length=512),
    }


def normalize_authority_basis(value: Any, *, expected_authority: str | None = None) -> dict[str, Any]:
    basis = require_object(value, "authority_basis", non_empty=True)
    if len(basis) > 32:
        raise WorkItemGovernanceError("AUTHORITY_BASIS_TOO_LARGE", "Authority basis has too many fields.")
    if expected_authority is not None:
        actual = basis.get("authority") or basis.get("permission") or basis.get("kind")
        if actual != expected_authority:
            raise WorkItemGovernanceError(
                "AUTHORITY_BASIS_INSUFFICIENT",
                "Authority basis does not authorize the requested transition.",
                details={"expected": expected_authority, "actual": actual},
            )
    canonical_sha256(basis)
    return basis


def normalize_string_list(
    value: Any,
    field: str,
    *,
    default: list[str] | None = None,
    max_items: int = 1024,
    max_item_length: int = 8192,
) -> list[str]:
    if value is None:
        return list(default or [])
    if not isinstance(value, list) or len(value) > max_items:
        raise WorkItemGovernanceError(
            "STRING_LIST_INVALID",
            f"{field} must be a bounded list of strings.",
            details={"field": field, "max_items": max_items},
        )
    normalized = [require_text(item, f"{field}[]", max_length=max_item_length) for item in value]
    if len(set(normalized)) != len(normalized):
        raise WorkItemGovernanceError(
            "STRING_LIST_DUPLICATE",
            f"{field} must not contain duplicates.",
            details={"field": field},
        )
    return [str(item) for item in normalized]


def normalize_initial_task(value: Any, *, fallback_objective: Any = None) -> dict[str, Any]:
    task = {} if value is None else require_object(value, "task")
    allowed = {
        "objective_ref",
        "plan_version_refs",
        "artifact_contract",
        "approval_requirements",
        "reporting_destination",
        "expected_receipt_contract",
        "payload",
    }
    unknown = sorted(set(task) - allowed)
    if unknown:
        raise WorkItemGovernanceError(
            "TASK_FIELD_UNSUPPORTED",
            "Initial Task Version contains unsupported fields.",
            details={"unsupported_fields": unknown},
        )
    objective = task.get("objective_ref", fallback_objective)
    normalized = {
        "objective_ref": optional_text(objective, "task.objective_ref", max_length=8192),
        "plan_version_refs": normalize_string_list(task.get("plan_version_refs"), "task.plan_version_refs"),
        "artifact_contract": require_metadata_object(task.get("artifact_contract", {}), "task.artifact_contract"),
        "approval_requirements": require_metadata_object(
            task.get("approval_requirements", {}), "task.approval_requirements"
        ),
        "reporting_destination": require_metadata_object(
            task.get("reporting_destination", {}), "task.reporting_destination"
        ),
        "expected_receipt_contract": require_metadata_object(
            task.get("expected_receipt_contract", {}), "task.expected_receipt_contract"
        ),
        "payload": require_metadata_object(task.get("payload", {}), "task.payload"),
    }
    canonical_sha256(normalized)
    return normalized
