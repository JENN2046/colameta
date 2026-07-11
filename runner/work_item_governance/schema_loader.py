from __future__ import annotations

import json
from importlib import resources
from typing import Any

from runner.work_item_governance.errors import WorkItemGovernanceError


SCHEMA_FILES = {
    "definitions.v1": "definitions.v1.schema.json",
    "work_item.v1": "work-item.v1.schema.json",
    "task_version.v1": "task-version.v1.schema.json",
    "execution_attempt.v1": "execution-attempt.v1.schema.json",
    "artifact_reference.v1": "artifact-reference.v1.schema.json",
    "decision_record.v1": "decision-record.v1.schema.json",
    "gate_event.v1": "gate-event.v1.schema.json",
    "delivery_receipt.v1": "delivery-receipt.v1.schema.json",
    "acceptance_evidence_manifest.v1": "acceptance-evidence-manifest.v1.schema.json",
    "execution_envelope.v2": "execution-envelope.v2.schema.json",
}


def load_governance_schema(schema_version: str) -> dict[str, Any]:
    filename = SCHEMA_FILES.get(schema_version)
    if filename is None:
        raise WorkItemGovernanceError(
            "SCHEMA_VERSION_UNSUPPORTED",
            "Work Item Governance schema version is unsupported.",
            details={"schema_version": schema_version, "supported": sorted(SCHEMA_FILES)},
        )
    resource = resources.files("schemas").joinpath("work_item_governance", filename)
    try:
        value = json.loads(resource.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkItemGovernanceError(
            "SCHEMA_LOAD_FAILED",
            "Work Item Governance schema could not be loaded.",
            details={"schema_version": schema_version, "reason": str(exc)},
        ) from exc
    if not isinstance(value, dict) or value.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        raise WorkItemGovernanceError(
            "SCHEMA_INVALID",
            "Work Item Governance schema is not a Draft 2020-12 object.",
            details={"schema_version": schema_version},
        )
    return value


def load_all_governance_schemas() -> dict[str, dict[str, Any]]:
    return {version: load_governance_schema(version) for version in SCHEMA_FILES}


def validate_governance_record(schema_version: str, value: Any) -> Any:
    """Validate a record with a local, network-free Draft 2020-12 registry."""

    try:
        from jsonschema import Draft202012Validator, FormatChecker
        from referencing import Registry, Resource
    except ImportError as exc:
        raise WorkItemGovernanceError(
            "JSON_SCHEMA_VALIDATOR_UNAVAILABLE",
            "Install the ColaMeta test extra to validate governance records.",
        ) from exc
    schemas = load_all_governance_schemas()
    schema = schemas.get(schema_version)
    if schema is None:
        raise WorkItemGovernanceError(
            "SCHEMA_VERSION_UNSUPPORTED",
            "Work Item Governance schema version is unsupported.",
            details={"schema_version": schema_version},
        )
    resources = [
        (candidate["$id"], Resource.from_contents(candidate))
        for candidate in schemas.values()
    ]
    registry = Registry().with_resources(resources)
    validator = Draft202012Validator(schema, registry=registry, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(value), key=lambda item: list(item.absolute_path))
    if errors:
        first = errors[0]
        raise WorkItemGovernanceError(
            "SCHEMA_VALIDATION_FAILED",
            "Record does not satisfy its Work Item Governance JSON Schema.",
            details={
                "schema_version": schema_version,
                "path": [str(item) for item in first.absolute_path],
                "message": first.message,
                "error_count": len(errors),
            },
        )
    return value
