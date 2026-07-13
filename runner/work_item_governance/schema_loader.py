from __future__ import annotations

import json
import re
from datetime import datetime
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
    "work_item_activation_envelope.v1": "activation-envelope.v1.schema.json",
    "work_item_synthetic_fixture_contract.v1": "synthetic-fixture-contract.v1.schema.json",
    "work_item_authoritative_canary_preflight_receipt.v1": "preflight-receipt.v1.schema.json",
    "work_item_activation_lease.v1": "activation-lease.v1.schema.json",
    "work_item_activation_lease_event.v1": "activation-lease-event.v1.schema.json",
    "wig_p3_canary_a1_r2_closeout_receipt.v1": "r2-closeout-receipt.v1.schema.json",
    "pilot_execution_attempt_slot.v1": "execution-attempt-slot.v1.schema.json",
    "pilot_execution_authorization_receipt.v2": "execution-authorization-receipt.v2.schema.json",
    "pilot_activation_lease.v4": "pilot-activation-lease.v4.schema.json",
    "pilot_activation_lease_event.v4": "pilot-activation-lease-event.v4.schema.json",
    "pilot_authorization.v4": "pilot-authorization.v4.schema.json",
    "pilot_closeout.v4": "pilot-closeout.v4.schema.json",
    "pilot_preflight.v4": "pilot-preflight.v4.schema.json",
    "pilot_scope_envelope.v4": "pilot-scope-envelope.v4.schema.json",
    "pilot_semantic_validation_receipt.v3": "pilot-semantic-validation-receipt.v3.schema.json",
    "pilot_authentication_conformance_receipt.v1": "pilot-authentication-conformance-receipt.v1.schema.json",
    "pilot_expiry_conformance_receipt.v1": "pilot-expiry-conformance-receipt.v1.schema.json",
}

CONTRACT_FILES = {
    "authoritative_canary_tool_allowlist.v1": "authoritative-canary-tool-allowlist.v1.json",
    "work_item_write_command_matrix.v1": "work-item-write-command-matrix.v1.json",
    "pilot_fact_reconciliation.v2": "pilot-fact-reconciliation.v2.json",
    "pilot_semantic_rules.v4": "pilot-semantic-rules.v4.json",
    "pilot_storage_schema_v6.v2": "pilot-storage-schema-v6.v2.json",
    "pilot_storage_schema_v7.v1": "pilot-storage-schema-v7.v1.json",
    "pilot_negative_test_matrix.v4": "pilot-negative-test-matrix.v4.json",
    "pilot_tool_allowlist.v3": "pilot-tool-allowlist.v3.json",
    "pilot_write_command_matrix.v3": "pilot-write-command-matrix.v3.json",
    "pilot_write_path_inventory.v3": "pilot-write-path-inventory.v3.json",
}

_RFC3339_PATTERN = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,9})?(?:Z|[+-][0-9]{2}:[0-9]{2})$"
)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON object key: {key}")
        value[key] = item
    return value


def _strict_rfc3339(value: Any) -> bool:
    if not isinstance(value, str):
        return True
    if _RFC3339_PATTERN.fullmatch(value) is None:
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _load_resource_json(filename: str) -> Any:
    resource = resources.files("schemas").joinpath("work_item_governance", filename)
    return json.loads(
        resource.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_keys,
    )


def load_governance_schema(schema_version: str) -> dict[str, Any]:
    filename = SCHEMA_FILES.get(schema_version)
    if filename is None:
        raise WorkItemGovernanceError(
            "SCHEMA_VERSION_UNSUPPORTED",
            "Work Item Governance schema version is unsupported.",
            details={"schema_version": schema_version, "supported": sorted(SCHEMA_FILES)},
        )
    try:
        value = _load_resource_json(filename)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
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


def load_governance_contract(contract_version: str) -> dict[str, Any]:
    filename = CONTRACT_FILES.get(contract_version)
    if filename is None:
        raise WorkItemGovernanceError(
            "CONTRACT_VERSION_UNSUPPORTED",
            "Work Item Governance contract version is unsupported.",
            details={"contract_version": contract_version, "supported": sorted(CONTRACT_FILES)},
        )
    try:
        value = _load_resource_json(filename)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise WorkItemGovernanceError(
            "CONTRACT_LOAD_FAILED",
            "Work Item Governance contract could not be loaded.",
            details={"contract_version": contract_version, "reason": str(exc)},
        ) from exc
    if not isinstance(value, dict):
        raise WorkItemGovernanceError("CONTRACT_INVALID", "Work Item Governance contract must be an object.")
    return value


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
    format_checker = FormatChecker()
    format_checker.checks("date-time", raises=())(_strict_rfc3339)
    validator = Draft202012Validator(schema, registry=registry, format_checker=format_checker)
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
