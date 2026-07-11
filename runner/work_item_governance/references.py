from __future__ import annotations

from typing import Any

from runner.work_item_governance.ids import is_stable_id


WORK_ITEM_REFERENCE_FIELDS = ("work_item_id", "task_version", "attempt_id", "artifact_refs")
PLAN_WORK_ITEM_REFERENCE_FIELDS = ("work_item_id", "task_version", "attempt_id")


def _reference_value(value: Any, field: str) -> Any:
    if isinstance(value, dict):
        return value.get(field)
    return getattr(value, field, None)


def optional_plan_work_item_reference_rejections(value: Any) -> list[dict[str, Any]]:
    """Validate a Plan-to-Task binding with an optional execution Attempt.

    A Plan can be associated with a Work Item and Task Version before any
    execution Attempt exists. Once an Attempt is supplied it must be a stable
    Attempt identifier. Explicit all-null fields remain the legacy-unbound
    representation.
    """

    if not isinstance(value, dict) and not all(
        hasattr(value, field) for field in PLAN_WORK_ITEM_REFERENCE_FIELDS
    ):
        return [{"code": "REFERENCE_CONTAINER_INVALID", "field": "<plan>"}]
    work_item_id = _reference_value(value, "work_item_id")
    task_version = _reference_value(value, "task_version")
    attempt_id = _reference_value(value, "attempt_id")
    if all(item is None for item in (work_item_id, task_version, attempt_id)):
        return []
    rejections: list[dict[str, Any]] = []
    if not is_stable_id(work_item_id, "work_item"):
        rejections.append({"code": "WORK_ITEM_ID_INVALID", "field": "work_item_id"})
    if isinstance(task_version, bool) or not isinstance(task_version, int) or task_version < 1:
        rejections.append({"code": "TASK_VERSION_INVALID", "field": "task_version"})
    if attempt_id is not None and not is_stable_id(attempt_id, "attempt"):
        rejections.append({"code": "ATTEMPT_ID_INVALID", "field": "attempt_id"})
    return rejections


def resolve_plan_work_item_reference(plan: Any, version: Any | None = None) -> dict[str, Any]:
    """Return a validated version binding, falling back to its containing Plan."""

    version_value = version
    if isinstance(version, str):
        version_value = next(
            (
                item
                for item in (getattr(plan, "versions", None) or [])
                if str(_reference_value(item, "version") or "") == version
            ),
            None,
        )
    candidates = (version_value, plan)
    for candidate in candidates:
        if candidate is None:
            continue
        values = {
            field: _reference_value(candidate, field)
            for field in PLAN_WORK_ITEM_REFERENCE_FIELDS
        }
        if all(item is None for item in values.values()):
            continue
        if optional_plan_work_item_reference_rejections(values):
            return {}
        return {field: item for field, item in values.items() if item is not None}
    return {}


def resolve_execution_attempt_binding(plan: Any, version: Any | None = None) -> dict[str, Any]:
    """Return only a complete Attempt binding suitable for Run/Report records."""

    reference = resolve_plan_work_item_reference(plan, version)
    if not all(reference.get(field) is not None for field in PLAN_WORK_ITEM_REFERENCE_FIELDS):
        return {}
    binding = {**reference, "artifact_refs": []}
    return binding if not optional_work_item_reference_rejections(binding) else {}


def optional_work_item_reference_rejections(value: Any) -> list[dict[str, Any]]:
    """Validate an optional all-or-none Work Item/Task/Attempt binding.

    The helper returns ordinary validation records so legacy receipt/report
    validators can remain fail-closed without acquiring state authority.
    """

    if not isinstance(value, dict):
        return [{"code": "REFERENCE_CONTAINER_INVALID", "field": "<record>"}]
    if not any(field in value for field in WORK_ITEM_REFERENCE_FIELDS):
        return []
    work_item_id = value.get("work_item_id")
    task_version = value.get("task_version")
    attempt_id = value.get("attempt_id")
    artifacts = value.get("artifact_refs", [])
    rejections: list[dict[str, Any]] = []
    if not is_stable_id(work_item_id, "work_item"):
        rejections.append({"code": "WORK_ITEM_ID_INVALID", "field": "work_item_id"})
    if isinstance(task_version, bool) or not isinstance(task_version, int) or task_version < 1:
        rejections.append({"code": "TASK_VERSION_INVALID", "field": "task_version"})
    if not is_stable_id(attempt_id, "attempt"):
        rejections.append({"code": "ATTEMPT_ID_INVALID", "field": "attempt_id"})
    if not isinstance(artifacts, list) or len(artifacts) > 1024:
        rejections.append({"code": "ARTIFACT_REFS_INVALID", "field": "artifact_refs"})
    else:
        invalid = [item for item in artifacts if not is_stable_id(item, "artifact")]
        if invalid or len(set(artifacts)) != len(artifacts):
            rejections.append({"code": "ARTIFACT_REFS_INVALID", "field": "artifact_refs"})
    return rejections


def optional_work_item_reference_projection(value: Any) -> dict[str, Any]:
    record = value if isinstance(value, dict) else {}
    bound = any(field in record for field in WORK_ITEM_REFERENCE_FIELDS)
    return {
        "work_item_id": record.get("work_item_id"),
        "task_version": record.get("task_version"),
        "attempt_id": record.get("attempt_id"),
        "artifact_refs": list(record.get("artifact_refs", [])) if isinstance(record.get("artifact_refs", []), list) else [],
        "work_item_bound": bound and not optional_work_item_reference_rejections(record),
        "creates_work_item": False,
        "writes_delivery_state": False,
    }
