from __future__ import annotations

import json
import hashlib
import secrets
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from importlib import resources
from typing import Any, Callable

from runner.work_item_governance.activation import (
    ActivationWriteSession,
    AUTHORITATIVE_TOKEN_EVIDENCE_DIGEST_META_KEY,
    AUTHORITATIVE_TOKEN_FILE_SHA256_META_KEY,
    _activation_domain_fact_counts,
    canonical_path_digest,
    require_authoritative_token_file_binding,
    request_context_binding_digest,
)
from runner.work_item_governance.canonical import canonical_json, canonical_sha256, sha256_file
from runner.work_item_governance.errors import CommitWorkItemRejection, WorkItemGovernanceError
from runner.work_item_governance.ids import new_stable_id
from runner.work_item_governance.preview import isoformat_utc, parse_timestamp, utc_now
from runner.work_item_governance.principal import PrincipalContext
from runner.work_item_governance.repository import SQLiteWorkItemLedger
from runner.work_item_governance.request_context import (
    AuthenticatedTokenRequestProof,
    AuthoritativeCanaryRequestContext,
    _mint_authoritative_request_context,
)
from runner.work_item_governance.schema_loader import load_governance_contract, validate_governance_record


PILOT_SCOPE_MODE = "bounded_single_project_pilot.v1"
PILOT_LEASE_SCHEMA = "wig_p3_bounded_single_project_pilot_activation_lease.v4"
PILOT_EVENT_SCHEMA = "wig_p3_bounded_single_project_pilot_activation_lease_event.v4"
PILOT_FROZEN_CONTRACT_DIGESTS = {
    "spec_manifest_digest": "7d7b265e0afe6492a3ef90d366ef9849c522959290f30003f1cd75dac2733b91",
    "storage_schema_contract_digest": "fbaac247078f8c89869968e8e9aadceb598f53ee1afb137fef36645140ea2ba8",
    "fact_reconciliation_contract_digest": "9b69f886377a2849524744c64f620822bf7459c9f660c80c64b4f72fe923a09f",
    "semantic_rules_digest": "80c628c020e78498f4d70964a820f963ca339b52bd84ecbb4c7d5b9e570f4857",
    "tool_allowlist_digest": "fae456a0ed7aa3cbfa925ffc9de367d6d8cc103793ef973e69a6a7fea66fd985",
    "write_matrix_digest": "e5a1a6e8c4d196c8600f2c436b93c4334355e885995907f8555af2922cc80bdd",
    "execution_attempt_slot_schema_sha256": "3e0fe0bb6995bc28c097cb10abc1cf9feb32c5aa796415fc1a1493567e1958b1",
    "execution_authorization_receipt_schema_sha256": "2c60d519c5294bde20675964288e15681025f16ce0cfaf01ae2d3af1d4f2a7d4",
    "authentication_conformance_receipt_schema_sha256": "19ab8e804385a2b7783e0bd82ba9213b21fc7ef3138ef59d0c9f4630bf3e9c69",
    "expiry_conformance_receipt_schema_sha256": "d0b7b801a4d79fbeb76960c7c13f84568ea0f62154218351a9767c2724bf0bd2",
}
PILOT_AUTHORIZATION_FROZEN_BINDINGS = {
    "remediated_spec_manifest_sha256": PILOT_FROZEN_CONTRACT_DIGESTS["spec_manifest_digest"],
    "scope_schema_sha256": "4cc1aa87d04adccff37b7d08289339d764a20f096de7b0100623366835c190c2",
    "storage_schema_contract_sha256": PILOT_FROZEN_CONTRACT_DIGESTS["storage_schema_contract_digest"],
    "activation_lease_schema_sha256": "359b82d7eba0e9c3018cc6c17573aa54dca312d4fe4fcd0af9ec20fce8f77c9c",
    "lease_event_schema_sha256": "c871099663b640acd7a0b4f3ae9e0ed21c1ff30e8fd180f255bb05062fa63380",
    "fact_reconciliation_contract_sha256": PILOT_FROZEN_CONTRACT_DIGESTS["fact_reconciliation_contract_digest"],
    "semantic_rules_sha256": PILOT_FROZEN_CONTRACT_DIGESTS["semantic_rules_digest"],
    "semantic_validation_receipt_schema_sha256": "1149bbbf14016e9a910e1605b29a73949b15f4dd6f2d27b235af3403b05b69db",
    "execution_attempt_slot_schema_sha256": PILOT_FROZEN_CONTRACT_DIGESTS["execution_attempt_slot_schema_sha256"],
    "execution_authorization_receipt_schema_sha256": PILOT_FROZEN_CONTRACT_DIGESTS["execution_authorization_receipt_schema_sha256"],
    "authentication_conformance_receipt_schema_sha256": PILOT_FROZEN_CONTRACT_DIGESTS["authentication_conformance_receipt_schema_sha256"],
    "expiry_conformance_receipt_schema_sha256": PILOT_FROZEN_CONTRACT_DIGESTS["expiry_conformance_receipt_schema_sha256"],
    "tool_allowlist_sha256": PILOT_FROZEN_CONTRACT_DIGESTS["tool_allowlist_digest"],
    "write_matrix_sha256": PILOT_FROZEN_CONTRACT_DIGESTS["write_matrix_digest"],
    "write_path_inventory_sha256": "bcdc4d68fe580166750e32934d2a7c6ff86b48a5b3fc84b19ba1b126fc6ab30f",
    "preflight_schema_sha256": "b1ef40b640b0218441efaed3da6f2ea01f6a997d60eb78c13cbee288b8f7a7f1",
    "closeout_schema_sha256": "6ac9888da62d60480419bf137e18679212ecf54fa90b0c6eaf5d89b97c992c4f",
    "negative_test_matrix_sha256": "c32f0c3d735139fb11881dc70d03fc713c8a6a0379550e3dfd11ed76d3a6a2fd",
}


def measure_pilot_durable_token_binding(project_root: str | Path) -> dict[str, str]:
    """Read the exact durable Token binding through the Pilot core read boundary."""

    ledger = SQLiteWorkItemLedger(project_root, target_schema_version=7)
    binding: dict[str, str] = {}
    with ledger.read_connection() as connection:
        for key in (
            AUTHORITATIVE_TOKEN_EVIDENCE_DIGEST_META_KEY,
            AUTHORITATIVE_TOKEN_FILE_SHA256_META_KEY,
        ):
            rows = connection.execute(
                "SELECT value FROM ledger_meta WHERE key=?",
                (key,),
            ).fetchall()
            if len(rows) != 1:
                raise WorkItemGovernanceError(
                    "PILOT_AUTHENTICATION_CONFORMANCE_INVALID",
                    "Pilot Token binding requires one exact durable Ledger metadata row.",
                    details={"key": key, "row_count": len(rows)},
                )
            binding[key] = str(rows[0]["value"])
    return binding


def require_pilot_preflight_conformance_baseline(
    project_root: str | Path,
) -> dict[str, Any]:
    """Fail closed unless a Pilot Ledger is an untouched preflight baseline.

    A preflight-only HTTP listener has no authorization to create or claim a
    Lease.  This read boundary is deliberately checked before bind and is also
    useful to prove that conformance traffic left no durable facts behind.
    """

    ledger = SQLiteWorkItemLedger(project_root, target_schema_version=7)
    if not ledger.path.is_file() or ledger.path.is_symlink():
        raise WorkItemGovernanceError(
            "PILOT_PREFLIGHT_CONFORMANCE_BASELINE_INVALID",
            "Preflight conformance requires an existing non-symlink Schema v7 Ledger.",
        )
    if ledger.schema_version() != 7:
        raise WorkItemGovernanceError(
            "PILOT_PREFLIGHT_CONFORMANCE_BASELINE_INVALID",
            "Preflight conformance requires an exact Schema v7 Ledger.",
        )
    with ledger.read_connection() as connection:
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        counts = {
            table: int(connection.execute(query).fetchone()[0])
            for table, query in PILOT_TABLE_COUNT_QUERIES.items()
        }
    if integrity != "ok" or foreign_keys or any(counts.values()):
        raise WorkItemGovernanceError(
            "PILOT_PREFLIGHT_CONFORMANCE_BASELINE_INVALID",
            "Preflight conformance requires an integrity-clean zero-fact Ledger.",
            details={
                "nonzero_tables": sorted(table for table, count in counts.items() if count),
                "foreign_key_violations": len(foreign_keys),
            },
        )
    return {
        "schema_version": 7,
        "database_generation": ledger.database_generation(),
        "integrity_check": integrity,
        "foreign_key_violations": [],
        "zero_fact_baseline": counts,
    }


PILOT_FROZEN_RESOURCE_DIGESTS = {
    "pilot-semantic-rules.v4.json": PILOT_FROZEN_CONTRACT_DIGESTS["semantic_rules_digest"],
    "pilot-storage-schema-v6.v2.json": "72305af12e47eba743b84d40f786bd077315ee8e222e5e0241f723b38f5a19ef",
    "pilot-storage-schema-v7.v1.json": PILOT_FROZEN_CONTRACT_DIGESTS["storage_schema_contract_digest"],
    "pilot-fact-reconciliation.v2.json": PILOT_FROZEN_CONTRACT_DIGESTS["fact_reconciliation_contract_digest"],
    "pilot-tool-allowlist.v3.json": PILOT_FROZEN_CONTRACT_DIGESTS["tool_allowlist_digest"],
    "pilot-write-command-matrix.v3.json": PILOT_FROZEN_CONTRACT_DIGESTS["write_matrix_digest"],
    "execution-attempt-slot.v1.schema.json": PILOT_FROZEN_CONTRACT_DIGESTS["execution_attempt_slot_schema_sha256"],
    "execution-authorization-receipt.v2.schema.json": PILOT_FROZEN_CONTRACT_DIGESTS["execution_authorization_receipt_schema_sha256"],
    "pilot-authentication-conformance-receipt.v1.schema.json": PILOT_FROZEN_CONTRACT_DIGESTS["authentication_conformance_receipt_schema_sha256"],
    "pilot-expiry-conformance-receipt.v1.schema.json": PILOT_FROZEN_CONTRACT_DIGESTS["expiry_conformance_receipt_schema_sha256"],
    "pilot-semantic-validation-receipt.v3.schema.json": "1149bbbf14016e9a910e1605b29a73949b15f4dd6f2d27b235af3403b05b69db",
    "pilot-write-path-inventory.v3.json": PILOT_AUTHORIZATION_FROZEN_BINDINGS["write_path_inventory_sha256"],
    "pilot-scope-envelope.v4.schema.json": PILOT_AUTHORIZATION_FROZEN_BINDINGS["scope_schema_sha256"],
    "pilot-authorization.v4.schema.json": "4df85cd005ae005d7fe5b84a999eded308571abd63cb31fd687bc984036e7225",
    "pilot-activation-lease.v4.schema.json": PILOT_AUTHORIZATION_FROZEN_BINDINGS["activation_lease_schema_sha256"],
    "pilot-activation-lease-event.v4.schema.json": PILOT_AUTHORIZATION_FROZEN_BINDINGS["lease_event_schema_sha256"],
    "pilot-preflight.v4.schema.json": PILOT_AUTHORIZATION_FROZEN_BINDINGS["preflight_schema_sha256"],
    "pilot-closeout.v4.schema.json": PILOT_AUTHORIZATION_FROZEN_BINDINGS["closeout_schema_sha256"],
    "pilot-negative-test-matrix.v4.json": PILOT_AUTHORIZATION_FROZEN_BINDINGS["negative_test_matrix_sha256"],
}


def verify_pilot_frozen_contract_resources() -> None:
    root = resources.files("schemas").joinpath("work_item_governance")
    mismatches = []
    for filename, expected in PILOT_FROZEN_RESOURCE_DIGESTS.items():
        actual = hashlib.sha256(root.joinpath(filename).read_bytes()).hexdigest()
        if actual != expected:
            mismatches.append({"filename": filename, "expected": expected, "actual": actual})
    if mismatches:
        raise WorkItemGovernanceError(
            "PILOT_FROZEN_CONTRACT_DIGEST_MISMATCH",
            "Packaged Pilot machine contracts differ from the independently frozen bytes.",
            details={"mismatches": mismatches},
        )
PILOT_ALLOWED_WRITES = frozenset(
    {
        "apply_work_item_create",
        "add_task_version",
        "create_execution_attempt",
        "complete_execution_attempt",
        "register_artifact_reference",
        "record_review_decision",
        "apply_work_item_transition",
    }
)
PILOT_DENIED_WRITES = frozenset(
    {
        "apply_legacy_work_item_import",
        "bind_historical_execution_attempt",
        "apply_blocker",
        "clear_blocker",
        "create_delivery_receipt",
        "retry_delivery",
        "acknowledge_delivery",
        "record_outbox_delivery_result",
        "recover_outbox_event",
    }
)
PILOT_TOOLS = (
    "get_work_item_governance_status",
    "get_work_item",
    "list_work_items",
    "get_work_item_timeline",
    "get_execution_attempt_dispatch_authority",
    "preview_work_item_create",
    "preview_work_item_transition",
    "apply_work_item_create",
    "add_task_version",
    "create_execution_attempt",
    "complete_execution_attempt",
    "register_artifact_reference",
    "record_review_decision",
    "apply_work_item_transition",
)
PILOT_FACT_KEYS = (
    "new_work_items",
    "task_versions",
    "runtime_attempts",
    "attempt_events",
    "artifacts",
    "decisions",
    "applied_gate_events",
    "rejected_gate_events",
    "gate_events_total",
    "audit_events",
    "outbox_events",
    "acceptance_manifests",
)
PILOT_FACT_TO_QUOTA = {
    "new_work_items": "maximum_new_work_items",
    "task_versions": "maximum_task_versions",
    "runtime_attempts": "maximum_runtime_attempts",
    "attempt_events": "maximum_attempt_events",
    "artifacts": "maximum_artifacts",
    "decisions": "maximum_decisions",
    "applied_gate_events": "maximum_applied_gate_events",
    "rejected_gate_events": "maximum_rejected_gate_events",
    "gate_events_total": "maximum_gate_events_total",
    "audit_events": "maximum_audit_events",
    "outbox_events": "maximum_outbox_events",
    "acceptance_manifests": "maximum_acceptance_manifests",
}
DOMAIN_TO_USAGE = {
    "work_items": "new_work_items",
    "task_versions": "task_versions",
    "runtime_attempts": "runtime_attempts",
    "attempt_events": "attempt_events",
    "artifacts": "artifacts",
    "decisions": "decisions",
    "applied_gate_events": "applied_gate_events",
    "rejected_gate_events": "rejected_gate_events",
    "audit_events": "audit_events",
    "outbox_events": "outbox_events",
    "acceptance_manifests": "acceptance_manifests",
}
PILOT_FRESH_TABLES = (
    "work_items",
    "task_versions",
    "execution_attempts",
    "attempt_events",
    "artifact_refs",
    "decision_records",
    "gate_events",
    "acceptance_manifests",
    "activation_leases",
    "activation_lease_events",
    "pilot_activation_leases",
    "pilot_activation_lease_events",
    "external_associations",
    "delivery_receipts",
    "blocker_events",
    "audit_events",
    "outbox_events",
    "inbox_events",
)
PILOT_TABLE_COUNT_QUERIES = {
    "work_items": "SELECT COUNT(*) FROM work_items",
    "task_versions": "SELECT COUNT(*) FROM task_versions",
    "execution_attempts": "SELECT COUNT(*) FROM execution_attempts",
    "attempt_events": "SELECT COUNT(*) FROM attempt_events",
    "artifact_refs": "SELECT COUNT(*) FROM artifact_refs",
    "decision_records": "SELECT COUNT(*) FROM decision_records",
    "gate_events": "SELECT COUNT(*) FROM gate_events",
    "acceptance_manifests": "SELECT COUNT(*) FROM acceptance_manifests",
    "activation_leases": "SELECT COUNT(*) FROM activation_leases",
    "activation_lease_events": "SELECT COUNT(*) FROM activation_lease_events",
    "pilot_authorization_facts": "SELECT COUNT(*) FROM pilot_authorization_facts",
    "pilot_authorization_claims": "SELECT COUNT(*) FROM pilot_authorization_claims",
    "pilot_activation_leases": "SELECT COUNT(*) FROM pilot_activation_leases",
    "pilot_activation_lease_events": "SELECT COUNT(*) FROM pilot_activation_lease_events",
    "external_associations": "SELECT COUNT(*) FROM external_associations",
    "delivery_receipts": "SELECT COUNT(*) FROM delivery_receipts",
    "blocker_events": "SELECT COUNT(*) FROM blocker_events",
    "audit_events": "SELECT COUNT(*) FROM audit_events",
    "outbox_events": "SELECT COUNT(*) FROM outbox_events",
    "inbox_events": "SELECT COUNT(*) FROM inbox_events",
}


def _json(row: sqlite3.Row, field: str) -> dict[str, Any]:
    value = json.loads(str(row[field]))
    if not isinstance(value, dict):
        raise WorkItemGovernanceError("PILOT_LEASE_INVALID", f"{field} must contain an object.")
    return value


def _zero_delta() -> dict[str, int]:
    return {key: 0 for key in PILOT_FACT_KEYS}


def _lease_record(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "schema_version": str(row["schema_version"]),
        "lease_id": str(row["lease_id"]),
        "authorization_id": str(row["authorization_id"]),
        "authorization_digest": str(row["authorization_digest"]),
        "scope_envelope_digest": str(row["scope_envelope_digest"]),
        "spec_manifest_digest": str(row["spec_manifest_digest"]),
        "storage_schema_contract_digest": str(row["storage_schema_contract_digest"]),
        "fact_reconciliation_contract_digest": str(row["fact_reconciliation_contract_digest"]),
        "semantic_rules_digest": str(row["semantic_rules_digest"]),
        "tool_allowlist_digest": str(row["tool_allowlist_digest"]),
        "write_matrix_digest": str(row["write_matrix_digest"]),
        "execution_attempt_slot_schema_sha256": str(row["execution_attempt_slot_schema_sha256"]),
        "execution_authorization_receipt_schema_sha256": str(row["execution_authorization_receipt_schema_sha256"]),
        "authentication_conformance_receipt_schema_sha256": str(row["authentication_conformance_receipt_schema_sha256"]),
        "expiry_conformance_receipt_schema_sha256": str(row["expiry_conformance_receipt_schema_sha256"]),
        "source_binding": _json(row, "source_binding_json"),
        "runtime_binding": _json(row, "runtime_binding_json"),
        "principal_binding": _json(row, "principal_binding_json"),
        "scope_binding": _json(row, "scope_binding_json"),
        "window": {
            "issued_at": str(row["issued_at"]),
            "not_before": str(row["not_before"]),
            "expires_at": str(row["expires_at"]),
            "maximum_runtime_seconds": int(row["maximum_runtime_seconds"]),
            "maximum_preflight_age_seconds": 120,
        },
        "quotas": _json(row, "quotas_json"),
        "usage": _json(row, "usage_json"),
        "policy": _json(row, "policy_json"),
        "maintenance": _json(row, "maintenance_json"),
        "failure_behavior": _json(row, "failure_behavior_json"),
        "status": str(row["status"]),
        "state_version": int(row["state_version"]),
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
    }


def validate_execution_authorization_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    validate_governance_record("pilot_execution_authorization_receipt.v2", receipt)
    slots = receipt["scope"]["attempt_slots"]
    ordinals = [slot["ordinal"] for slot in slots]
    identifiers = [slot["slot_id"] for slot in slots]
    if ordinals != list(range(1, len(slots) + 1)) or len(set(identifiers)) != len(identifiers):
        raise WorkItemGovernanceError(
            "PILOT_EXECUTION_SLOT_SEQUENCE_INVALID",
            "Execution Attempt Slots require unique IDs and contiguous ordinals.",
        )
    by_id = {slot["slot_id"]: slot for slot in slots}
    for slot in slots:
        predecessor = slot["retry_of_slot_id"]
        if predecessor is not None:
            prior = by_id.get(predecessor)
            if (
                prior is None
                or int(prior["ordinal"]) >= int(slot["ordinal"])
                or prior["task_version_payload_digest"] != slot["task_version_payload_digest"]
                or prior["objective_digest"] != slot["objective_digest"]
            ):
                raise WorkItemGovernanceError(
                    "PILOT_EXECUTION_SLOT_RETRY_INVALID",
                    "Retry Slots must reference an earlier authorized Slot.",
                )
    if int(receipt["one_shot"]["maximum_attempts"]) != len(slots):
        raise WorkItemGovernanceError(
            "PILOT_EXECUTION_SLOT_COUNT_MISMATCH",
            "Execution authorization maximum_attempts must equal the Slot count.",
        )
    return receipt


def initial_execution_slot_usage(receipt: dict[str, Any]) -> list[dict[str, Any]]:
    validate_execution_authorization_receipt(receipt)
    return [
        {
            "slot_id": slot["slot_id"],
            "ordinal": slot["ordinal"],
            "task_version": slot["task_version"],
            "task_version_payload_digest": slot["task_version_payload_digest"],
            "objective_digest": slot["objective_digest"],
            "retry_of_slot_id": slot["retry_of_slot_id"],
            "maximum_attempt_runtime_seconds": slot["maximum_attempt_runtime_seconds"],
            "status": "available",
            "attempt_id": None,
            "bound_at": None,
            "completed_at": None,
        }
        for slot in receipt["scope"]["attempt_slots"]
    ]


def validate_pilot_scope_envelope(
    envelope: dict[str, Any],
    *,
    execution_authorization_receipt: dict[str, Any],
) -> dict[str, Any]:
    validate_governance_record("pilot_scope_envelope.v4", envelope)
    receipt = validate_execution_authorization_receipt(execution_authorization_receipt)
    target = envelope["target_project"]
    isolation = envelope["pilot_isolation"]
    work_item = envelope["work_item_scope"]
    execution = envelope["execution_scope"]
    errors: list[str] = []
    if canonical_path_digest(target["project_root"]) != target["project_root_path_digest"]:
        errors.append("project_root_path_digest")
    if canonical_path_digest(isolation["pilot_root"]) != isolation["pilot_root_path_digest"]:
        errors.append("pilot_root_path_digest")
    if canonical_sha256(work_item["objective_ref"]) != work_item["objective_digest"]:
        errors.append("objective_digest")
    if canonical_sha256(receipt) != execution["authorization_receipt_digest"]:
        errors.append("execution_authorization_receipt_digest")
    receipt_scope = receipt["scope"]
    if receipt_scope["project_id"] != target["project_id"]:
        errors.append("execution_project_id")
    if receipt_scope["project_snapshot_digest"] != target["project_snapshot_digest"]:
        errors.append("execution_project_snapshot_digest")
    if receipt_scope["work_item_id"] != work_item["proposed_work_item_id"]:
        errors.append("execution_work_item_id")
    if receipt_scope["attempt_slot_schema_sha256"] != execution["attempt_slot_schema_sha256"]:
        errors.append("execution_attempt_slot_schema_sha256")
    if receipt_scope["executor_identity"] != execution["executor_identity"]:
        errors.append("execution_executor_identity")
    for field in (
        "allowed_read_path_manifest_digest",
        "allowed_write_path_manifest_digest",
        "protected_path_manifest_digest",
    ):
        if receipt_scope[field] != execution[field] or receipt_scope[field] != target[field]:
            errors.append(f"execution_{field}")
    slot_payloads = {slot["task_version_payload_digest"] for slot in receipt_scope["attempt_slots"]}
    if not slot_payloads.issubset(set(work_item["task_version_payload_digests"])):
        errors.append("execution_task_version_payload_digests")
    if any(
        int(slot["maximum_attempt_runtime_seconds"]) > int(execution["maximum_attempt_runtime_seconds"])
        for slot in receipt_scope["attempt_slots"]
    ):
        errors.append("execution_maximum_attempt_runtime_seconds")
    if errors:
        error_code = (
            "PILOT_EXECUTION_AUTHORIZATION_INVALID"
            if any(item.startswith("execution_") for item in errors)
            else "PILOT_SCOPE_DIGEST_MISMATCH"
        )
        raise WorkItemGovernanceError(
            error_code,
            "Pilot Scope Envelope cross-bindings are inconsistent.",
            details={"failed_rules": sorted(set(errors))},
        )
    return envelope


def validate_pilot_authorization(
    authorization: dict[str, Any],
    *,
    scope_envelope: dict[str, Any],
) -> dict[str, Any]:
    validate_governance_record("pilot_authorization.v4", authorization)
    bindings = authorization["bindings"]
    source = authorization["source"]
    target = authorization["target"]
    scope_source = scope_envelope["source_binding"]
    scope_target = scope_envelope["target_project"]
    scope_isolation = scope_envelope["pilot_isolation"]
    scope_principal = scope_envelope["principal_binding"]
    digest = canonical_sha256(scope_envelope)
    errors: list[str] = []
    for field, expected in PILOT_AUTHORIZATION_FROZEN_BINDINGS.items():
        if bindings[field] != expected:
            errors.append(f"bindings:{field}")
    if bindings["scope_envelope_sha256"] != digest or bindings["authorized_scope_digest"] != digest:
        errors.append("scope_envelope_digest")
    if bindings["project_snapshot_digest"] != scope_target["project_snapshot_digest"]:
        errors.append("bindings:project_snapshot_digest")
    for field in ("implementation_commit", "implementation_tree", "wheel_sha256", "installed_inventory_sha256"):
        if source[field] != scope_source[field]:
            errors.append(f"source:{field}")
    if scope_source["storage_schema_contract_digest"] != bindings["storage_schema_contract_sha256"]:
        errors.append("source:storage_schema_contract_digest")
    if scope_source["fact_reconciliation_contract_digest"] != bindings["fact_reconciliation_contract_sha256"]:
        errors.append("source:fact_reconciliation_contract_digest")
    if target["project_id"] != scope_target["project_id"]:
        errors.append("target:project_id")
    if target["project_root_path_digest"] != scope_target["project_root_path_digest"]:
        errors.append("target:project_root_path_digest")
    if target["pilot_root_path_digest"] != scope_isolation["pilot_root_path_digest"]:
        errors.append("target:pilot_root_path_digest")
    principal = authorization["principal"]
    principal_pairs = {
        "principal_id": "principal_id",
        "principal_kind": "principal_kind",
        "session_ref": "session_ref",
        "caller_auth_mode": "caller_auth_mode",
        "authenticated_by": "principal_authenticated_by",
        "permissions": "permissions",
        "combined_operator_reviewer_role_explicitly_authorized": "combined_operator_reviewer_role_explicitly_authorized",
    }
    for auth_field, scope_field in principal_pairs.items():
        if principal[auth_field] != scope_principal[scope_field]:
            errors.append(f"principal:{auth_field}")
    if authorization["window"] != scope_envelope["window"]:
        errors.append("window")
    if errors:
        error_code = (
            "PILOT_SCOPE_DIGEST_MISMATCH"
            if "scope_envelope_digest" in errors
            else (
                "PILOT_COMBINED_ROLE_NOT_AUTHORIZED"
                if any(item.startswith("principal:") for item in errors)
                else "PILOT_PROJECT_SNAPSHOT_MISMATCH"
            )
        )
        raise WorkItemGovernanceError(
            error_code,
            "Pilot one-shot Authorization differs from its exact Scope Envelope.",
            details={"failed_rules": sorted(set(errors))},
        )
    return authorization


def validate_pilot_authority_chain(
    authorization: dict[str, Any],
    *,
    scope_envelope: dict[str, Any],
    execution_authorization_receipt: dict[str, Any],
    preflight_receipt: dict[str, Any],
    authentication_conformance_receipt: dict[str, Any],
    semantic_validation_receipt: dict[str, Any],
) -> None:
    """Exhaustively cross-bind every authority input before capability minting."""

    validate_pilot_scope_envelope(
        scope_envelope,
        execution_authorization_receipt=execution_authorization_receipt,
    )
    validate_pilot_preflight(preflight_receipt)
    validate_governance_record(
        "pilot_authentication_conformance_receipt.v1",
        authentication_conformance_receipt,
    )
    validate_governance_record(
        "pilot_semantic_validation_receipt.v3",
        semantic_validation_receipt,
    )
    validate_pilot_authorization(authorization, scope_envelope=scope_envelope)
    bindings = authorization["bindings"]
    preflight_bindings = preflight_receipt["bindings"]
    source = authorization["source"]
    scope_source = scope_envelope["source_binding"]
    scope_target = scope_envelope["target_project"]
    isolation = scope_envelope["pilot_isolation"]
    errors: list[str] = []
    expected = {
        "authorization_digest": canonical_sha256(authorization),
        "scope_envelope_digest": canonical_sha256(scope_envelope),
        "candidate_manifest_sha256": bindings["candidate_manifest_sha256"],
        "file_list_root_sha256": bindings["file_list_root_sha256"],
        "storage_schema_contract_digest": bindings["storage_schema_contract_sha256"],
        "fact_reconciliation_contract_digest": bindings["fact_reconciliation_contract_sha256"],
        "semantic_rules_digest": bindings["semantic_rules_sha256"],
        "project_snapshot_digest": bindings["project_snapshot_digest"],
        "execution_attempt_slot_schema_sha256": bindings["execution_attempt_slot_schema_sha256"],
        "execution_authorization_receipt_schema_sha256": bindings["execution_authorization_receipt_schema_sha256"],
        "execution_authorization_receipt_digest": canonical_sha256(execution_authorization_receipt),
        "authentication_conformance_receipt_schema_sha256": bindings["authentication_conformance_receipt_schema_sha256"],
        "authentication_conformance_receipt_digest": canonical_sha256(authentication_conformance_receipt),
        "expiry_conformance_receipt_schema_sha256": bindings["expiry_conformance_receipt_schema_sha256"],
    }
    if set(preflight_bindings) != set(expected):
        errors.append("preflight:binding_keyset")
    for field, value in expected.items():
        if preflight_bindings.get(field) != value:
            errors.append(f"preflight:{field}")
    if bindings["execution_authorization_receipt_digest"] != expected["execution_authorization_receipt_digest"]:
        errors.append("bindings:execution_authorization_receipt_digest")
    if bindings["authentication_conformance_receipt_digest"] != expected["authentication_conformance_receipt_digest"]:
        errors.append("bindings:authentication_conformance_receipt_digest")
    context = preflight_receipt["execution_context"]
    for field in ("implementation_commit", "implementation_tree", "wheel_sha256", "installed_inventory_sha256"):
        if context[field] != source[field] or context[field] != scope_source[field]:
            errors.append(f"execution_context:{field}")
    project = preflight_receipt["project"]
    for field in ("project_id", "project_root"):
        if project[field] != scope_target[field]:
            errors.append(f"project:{field}")
    if project["snapshot_digest"] != scope_target["project_snapshot_digest"]:
        errors.append("project:snapshot_digest")
    if preflight_receipt["isolation"]["pilot_root"] != isolation["pilot_root"]:
        errors.append("isolation:pilot_root")
    if preflight_receipt["ledger"]["path_digest"] != isolation["ledger_path_digest"]:
        errors.append("ledger:path_digest")
    target = authorization["target"]
    if preflight_receipt["runtime"]["bind_address"] != target["bind_address"]:
        errors.append("runtime:bind_address")
    if preflight_receipt["runtime"]["port"] != target["port"]:
        errors.append("runtime:port")
    if preflight_receipt["surface"]["exposure_profile"] != target["exposure_profile"]:
        errors.append("surface:exposure_profile")
    if preflight_receipt["surface"]["scope_mode"] != target["scope_mode"]:
        errors.append("surface:scope_mode")
    if preflight_receipt["authentication"]["caller_auth_mode"] != authorization["principal"]["caller_auth_mode"]:
        errors.append("authentication:caller_auth_mode")
    principal_digest = canonical_sha256(scope_envelope["principal_binding"])
    if preflight_receipt["authentication"]["principal_binding_digest"] != principal_digest:
        errors.append("authentication:principal_binding_digest")
    if preflight_receipt["authentication"]["authentication_conformance_receipt_digest"] != canonical_sha256(
        authentication_conformance_receipt
    ):
        errors.append("authentication:conformance_receipt_digest")
    if preflight_receipt["semantic_validation"]["receipt_digest"] != canonical_sha256(semantic_validation_receipt):
        errors.append("semantic_validation:receipt_digest")
    runtime_context = dict(context)
    reported_runtime_digest = runtime_context.pop("runtime_binding_digest")
    if reported_runtime_digest != canonical_sha256(runtime_context):
        errors.append("execution_context:runtime_binding_digest")
    if errors:
        raise WorkItemGovernanceError(
            "PILOT_AUTHORITY_BINDING_MISMATCH",
            "Pilot Authorization, Scope, Execution, Preflight, and frozen contracts do not form one authority chain.",
            details={"failed_bindings": sorted(set(errors))},
        )


def validate_pilot_preflight(receipt: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    validate_governance_record("pilot_preflight.v4", receipt)
    observed = parse_timestamp(receipt["observed_at"], "preflight.observed_at")
    valid_until = parse_timestamp(receipt["valid_until"], "preflight.valid_until")
    errors: list[str] = []
    if valid_until <= observed or (valid_until - observed).total_seconds() > 120:
        errors.append("preflight_window")
    current = (now or utc_now()).astimezone(timezone.utc)
    if current < observed or current > valid_until or (current - observed).total_seconds() > 120:
        errors.append("preflight_freshness")
    if receipt["backup"]["database_generation"] != receipt["ledger"]["database_generation"]:
        errors.append("backup_generation")
    if receipt["backup"]["schema_version"] != receipt["ledger"]["schema_version"]:
        errors.append("backup_schema_version")
    if receipt["bindings"]["project_snapshot_digest"] != receipt["project"]["snapshot_digest"]:
        errors.append("project_snapshot_digest")
    root = Path(receipt["isolation"]["pilot_root"]).resolve()
    for field in (
        "home",
        "xdg_config_home",
        "xdg_state_home",
        "xdg_cache_home",
        "xdg_data_home",
        "registry_path",
        "token_file_path",
    ):
        try:
            Path(receipt["isolation"][field]).resolve().relative_to(root)
        except ValueError:
            errors.append(f"isolation:{field}")
    if errors:
        if any(item.startswith("preflight_") for item in errors):
            error_code = "PILOT_PREFLIGHT_STALE"
        elif any(item.startswith("backup_") for item in errors):
            error_code = "PILOT_BACKUP_GENERATION_MISMATCH"
        elif "project_snapshot_digest" in errors:
            error_code = "PILOT_PROJECT_SNAPSHOT_MISMATCH"
        else:
            error_code = "PILOT_PRIVATE_PATH_ESCAPE"
        raise WorkItemGovernanceError(
            error_code,
            "Pilot Preflight semantic bindings are inconsistent.",
            details={"failed_rules": sorted(set(errors))},
        )
    return receipt


def build_pilot_semantic_validation_receipt(
    *,
    stage: str,
    input_bindings: dict[str, Any],
    failed_rules: list[dict[str, str]] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build a schema-valid receipt for the exact frozen rules applicable to one stage."""

    rules = load_governance_contract("pilot_semantic_rules.v4")
    rules_bytes = resources.files("schemas").joinpath(
        "work_item_governance", "pilot-semantic-rules.v4.json"
    ).read_bytes()
    if hashlib.sha256(rules_bytes).hexdigest() != PILOT_FROZEN_CONTRACT_DIGESTS["semantic_rules_digest"]:
        raise WorkItemGovernanceError(
            "PILOT_SEMANTIC_RECEIPT_INVALID",
            "Packaged Pilot semantic rules differ from the frozen contract digest.",
        )
    if rules.get("schema_version") != "wig_p3_bounded_single_project_pilot_semantic_rules.v4":
        raise WorkItemGovernanceError("PILOT_SEMANTIC_RECEIPT_INVALID", "Unknown Pilot semantic rule set.")
    applicable = [rule["id"] for rule in rules["rules"] if stage in rule["stages"]]
    failures = list(failed_rules or [])
    failed_ids = [item["rule_id"] for item in failures]
    if len(set(failed_ids)) != len(failed_ids) or not set(failed_ids).issubset(applicable):
        raise WorkItemGovernanceError(
            "PILOT_SEMANTIC_RECEIPT_INVALID",
            "Semantic failures must be unique rules applicable to the evaluated stage.",
        )
    passed = [rule_id for rule_id in applicable if rule_id not in set(failed_ids)]
    receipt = {
        "schema_version": "wig_p3_bounded_single_project_pilot_semantic_validation_receipt.v3",
        "gate_id": str(rules["gate_id"]),
        "validated_at": isoformat_utc(now or utc_now()),
        "stage": stage,
        "rules_digest": PILOT_FROZEN_CONTRACT_DIGESTS["semantic_rules_digest"],
        "input_bindings": input_bindings,
        "applicable_rule_ids": applicable,
        "passed_rule_ids": passed,
        "failed_rules": failures,
        "result": "FAIL" if failures else "PASS",
    }
    validate_governance_record("pilot_semantic_validation_receipt.v3", receipt)
    if receipt["result"] == "PASS" and set(passed) != set(applicable):
        raise WorkItemGovernanceError(
            "PILOT_SEMANTIC_RECEIPT_INVALID",
            "A PASS receipt must pass every applicable semantic rule.",
        )
    return receipt


def _validate_pilot_lease_authority_semantics(
    lease: dict[str, Any],
    *,
    capability: Any,
    ledger: SQLiteWorkItemLedger,
    now: datetime,
) -> None:
    issued = parse_timestamp(lease["window"]["issued_at"], "lease.window.issued_at")
    not_before = parse_timestamp(lease["window"]["not_before"], "lease.window.not_before")
    expires = parse_timestamp(lease["window"]["expires_at"], "lease.window.expires_at")
    if not (issued <= not_before < expires) or (expires - not_before).total_seconds() > 14400:
        raise WorkItemGovernanceError("PILOT_WINDOW_INVALID", "Pilot Lease time window is invalid.")
    if now.astimezone(timezone.utc) < not_before or now.astimezone(timezone.utc) >= expires:
        raise WorkItemGovernanceError("PILOT_WINDOW_INVALID", "Pilot Lease is not currently authorized.")
    preflight = capability.preflight
    if (
        int(preflight["ledger"]["schema_version"]) != 7
        or int(preflight["ledger"]["database_generation"]) != ledger.database_generation()
        or int(preflight["backup"]["database_generation"]) != ledger.database_generation()
    ):
        raise WorkItemGovernanceError(
            "PILOT_BACKUP_GENERATION_MISMATCH",
            "Pilot Lease, Ledger, and generation-bound Backup do not identify one fact domain.",
        )
    scope = capability.scope_envelope
    expected_ledger = Path(scope["target_project"]["project_root"]).resolve() / ".colameta/ledger/work-items.sqlite3"
    if ledger.path.resolve() != expected_ledger or canonical_path_digest(ledger.path) != scope["pilot_isolation"]["ledger_path_digest"]:
        raise WorkItemGovernanceError(
            "PILOT_LEDGER_PATH_MISMATCH",
            "Pilot Ledger is not the exact target-project Ledger bound by Scope.",
        )
    if lease["source_binding"] != {
        key: scope["source_binding"][key]
        for key in ("implementation_commit", "implementation_tree", "wheel_sha256", "installed_inventory_sha256")
    }:
        raise WorkItemGovernanceError(
            "PILOT_PROJECT_SNAPSHOT_MISMATCH",
            "Pilot Lease source binding differs from the authorized Scope.",
        )
    authorization = capability.authorization
    if lease["authorization_id"] != authorization["gate_id"]:
        raise WorkItemGovernanceError(
            "PILOT_AUTHORITY_BINDING_MISMATCH",
            "Pilot Lease authorization ID differs from the consumed decision.",
        )
    scope_principal = scope["principal_binding"]
    if lease["principal_binding"] != scope_principal:
        raise WorkItemGovernanceError(
            "PILOT_COMBINED_ROLE_NOT_AUTHORIZED",
            "Pilot Lease Principal differs from the explicitly authorized role binding.",
        )
    expected_scope_binding = {
        "project_id": scope["target_project"]["project_id"],
        "project_snapshot_digest": scope["target_project"]["project_snapshot_digest"],
        "proposed_work_item_id": scope["work_item_scope"]["proposed_work_item_id"],
        "authorized_work_item_id": scope["work_item_scope"]["authorized_work_item_id"],
        "origin_digest": canonical_sha256(scope["work_item_scope"]["origin"]),
        "authorized_create_command_digest": scope["work_item_scope"]["authorized_create_command_digest"],
        "objective_digest": scope["work_item_scope"]["objective_digest"],
        "task_version_payload_digests": scope["work_item_scope"]["task_version_payload_digests"],
        "execution_attempt_slot_schema_sha256": scope["execution_scope"]["attempt_slot_schema_sha256"],
        "execution_authorization_receipt_schema_sha256": scope["execution_scope"]["authorization_receipt_schema_sha256"],
        "execution_authorization_receipt_digest": scope["execution_scope"]["authorization_receipt_digest"],
        "artifact_policy_digest": canonical_sha256(scope["artifact_policy"]),
        "protected_path_manifest_digest": scope["target_project"]["protected_path_manifest_digest"],
        "allowed_write_path_manifest_digest": scope["target_project"]["allowed_write_path_manifest_digest"],
    }
    if lease["scope_binding"] != expected_scope_binding:
        failed = sorted(
            field
            for field in set(lease["scope_binding"]) | set(expected_scope_binding)
            if lease["scope_binding"].get(field) != expected_scope_binding.get(field)
        )
        raise WorkItemGovernanceError(
            "PILOT_AUTHORITY_BINDING_MISMATCH",
            f"Pilot Lease scope binding differs from the exact authorized Work Item and project scope: {failed}.",
            details={"failed_bindings": [f"scope_binding:{field}" for field in failed]},
        )
    preflight_isolation = preflight["isolation"]
    expected_runtime = {
        "bind_address": authorization["target"]["bind_address"],
        "port": authorization["target"]["port"],
        "exposure_profile": authorization["target"]["exposure_profile"],
        "scope_mode": authorization["target"]["scope_mode"],
        "pilot_root_path_digest": canonical_path_digest(preflight_isolation["pilot_root"]),
        "project_root_path_digest": canonical_path_digest(preflight["project"]["project_root"]),
        "ledger_path_digest": preflight["ledger"]["path_digest"],
        "token_file_path_digest": canonical_path_digest(preflight_isolation["token_file_path"]),
        "database_generation": preflight["ledger"]["database_generation"],
        "preflight_receipt_digest": canonical_sha256(preflight),
        "preflight_observed_at": preflight["observed_at"],
        "preflight_valid_until": preflight["valid_until"],
        "backup_receipt_digest": preflight["backup"]["receipt_digest"],
        "backup_sha256": preflight["backup"]["sha256"],
    }
    for field, expected_value in expected_runtime.items():
        if lease["runtime_binding"][field] != expected_value:
            raise WorkItemGovernanceError(
                "PILOT_AUTHORITY_BINDING_MISMATCH",
                "Pilot Lease runtime binding differs from the exact measured Preflight.",
                details={"failed_binding": f"runtime_binding:{field}"},
            )
    if lease["window"] != scope["window"] or lease["quotas"] != scope["quotas"]:
        raise WorkItemGovernanceError(
            "PILOT_AUTHORITY_BINDING_MISMATCH",
            "Pilot Lease window or quotas differ from the exact authorized Scope.",
        )
    if lease["usage"]["execution_slots"] != initial_execution_slot_usage(capability.execution_receipt):
        raise WorkItemGovernanceError(
            "PILOT_EXECUTION_AUTHORIZATION_INVALID",
            "Pilot Lease execution slots differ from the exact execution authority.",
        )


class PilotActivationControlPlane:
    """The only controller allowed to create and transition Pilot v4 Leases."""

    def __init__(self, ledger: SQLiteWorkItemLedger, *, now: Callable[[], datetime] = utc_now) -> None:
        verify_pilot_frozen_contract_resources()
        self.ledger = ledger
        self.now = now
        self.__repository_control_binding = ledger._bind_activation_controller(self)
        self.__process_claim_capability = object()
        self.__listener_attestation_capability = object()
        self.last_semantic_validation_receipt: dict[str, Any] | None = None

    def prepare_lease(self, lease: dict[str, Any], *, authority: Any) -> dict[str, Any]:
        from runner.work_item_governance.pilot_authorization import consume_pilot_authorization_capability

        # Burn the process capability before any validation or database work.
        # A failed or concurrent prepare therefore requires renewed external
        # authorization and cannot replay the already-tombstoned decision.
        capability = consume_pilot_authorization_capability(authority)
        validate_governance_record("pilot_activation_lease.v4", lease)
        validate_pilot_authority_chain(
            capability.authorization,
            scope_envelope=capability.scope_envelope,
            execution_authorization_receipt=capability.execution_receipt,
            preflight_receipt=capability.preflight,
            authentication_conformance_receipt=capability.authentication_conformance,
            semantic_validation_receipt=capability.preflight_semantic_receipt,
        )
        binding_errors: list[str] = []
        expected_bindings = {
            "authorization_digest": canonical_sha256(capability.authorization),
            "scope_envelope_digest": canonical_sha256(capability.scope_envelope),
        }
        for field, expected in expected_bindings.items():
            if lease[field] != expected or capability.tombstone[field] != expected:
                binding_errors.append(field)
        execution_digest = canonical_sha256(capability.execution_receipt)
        preflight_digest = canonical_sha256(capability.preflight)
        if capability.tombstone["execution_authorization_receipt_digest"] != execution_digest:
            binding_errors.append("execution_authorization_tombstone")
        if capability.tombstone["preflight_receipt_digest"] != preflight_digest:
            binding_errors.append("preflight_tombstone")
        if capability.tombstone["authentication_conformance_receipt_digest"] != canonical_sha256(
            capability.authentication_conformance
        ):
            binding_errors.append("authentication_conformance_tombstone")
        if capability.tombstone["preflight_semantic_validation_receipt_digest"] != canonical_sha256(
            capability.preflight_semantic_receipt
        ):
            binding_errors.append("preflight_semantic_tombstone")
        if lease["scope_binding"]["execution_authorization_receipt_digest"] != execution_digest:
            binding_errors.append("execution_authorization_receipt_digest")
        if lease["runtime_binding"]["preflight_receipt_digest"] != preflight_digest:
            binding_errors.append("preflight_receipt_digest")
        for field, expected in PILOT_FROZEN_CONTRACT_DIGESTS.items():
            if lease[field] != expected:
                binding_errors.append(field)
        if binding_errors:
            raise WorkItemGovernanceError(
                "PILOT_AUTHORITY_BINDING_MISMATCH",
                "Pilot Lease does not match the consumed Authorization, Scope, Preflight, and frozen contracts.",
                details={"failed_bindings": sorted(set(binding_errors))},
            )
        _validate_pilot_lease_authority_semantics(
            lease,
            capability=capability,
            ledger=self.ledger,
            now=self.now(),
        )
        if lease["status"] != "prepared" or lease["state_version"] != 1:
            raise WorkItemGovernanceError("PILOT_LEASE_INITIAL_STATE_INVALID", "A new Pilot Lease must be prepared at state version 1.")
        if lease["scope_binding"]["authorized_work_item_id"] is not None:
            raise WorkItemGovernanceError("PILOT_WORK_ITEM_PREBIND_DENIED", "Fresh Pilot Leases bind their Work Item atomically after create.")
        usage = lease["usage"]
        if any(int(usage[key]) != 0 for key in PILOT_FACT_KEYS) or int(usage["lease_events"]) != 1:
            raise WorkItemGovernanceError("PILOT_LEASE_USAGE_NOT_FRESH", "A new Pilot Lease requires zero domain usage and one issuance Event.")
        with self.ledger.write_transaction() as connection:
            session = self.ledger.authorize_activation_control_write(
                connection, controller=self, controller_binding=self.__repository_control_binding
            )
            try:
                nonzero = {
                    table: int(connection.execute(PILOT_TABLE_COUNT_QUERIES[table]).fetchone()[0])
                    for table in PILOT_FRESH_TABLES
                }
                nonzero = {table: count for table, count in nonzero.items() if count}
                if nonzero:
                    raise WorkItemGovernanceError(
                        "PILOT_LEDGER_NOT_FRESH",
                        "A bounded Pilot requires a fresh domain and Lease fact baseline.",
                        details={"nonzero_tables": nonzero},
                    )
                self.last_semantic_validation_receipt = build_pilot_semantic_validation_receipt(
                    stage="lease_prepare",
                    input_bindings={
                        "candidate_manifest_sha256": capability.authorization["bindings"]["candidate_manifest_sha256"],
                        "scope_envelope_digest": canonical_sha256(capability.scope_envelope),
                        "storage_schema_contract_digest": lease["storage_schema_contract_digest"],
                        "fact_reconciliation_contract_digest": lease["fact_reconciliation_contract_digest"],
                        "authorization_digest": canonical_sha256(capability.authorization),
                        "project_snapshot_digest": capability.scope_envelope["target_project"]["project_snapshot_digest"],
                        "runtime_binding_digest": canonical_sha256(lease["runtime_binding"]),
                        "ledger_state_digest": canonical_sha256(nonzero),
                    },
                    now=self.now(),
                )
                scope = dict(lease["scope_binding"])
                values = (
                    lease["lease_id"], lease["schema_version"], lease["authorization_id"], lease["authorization_digest"],
                    lease["scope_envelope_digest"], lease["spec_manifest_digest"], lease["storage_schema_contract_digest"],
                    lease["fact_reconciliation_contract_digest"], lease["semantic_rules_digest"], lease["tool_allowlist_digest"],
                    lease["write_matrix_digest"], lease["execution_attempt_slot_schema_sha256"],
                    lease["execution_authorization_receipt_schema_sha256"],
                    lease["authentication_conformance_receipt_schema_sha256"],
                    lease["expiry_conformance_receipt_schema_sha256"], scope["authorized_work_item_id"],
                    canonical_json(lease["source_binding"]), canonical_json(lease["runtime_binding"]),
                    canonical_json(lease["principal_binding"]), canonical_json(scope),
                    lease["window"]["issued_at"], lease["window"]["not_before"], lease["window"]["expires_at"],
                    lease["window"]["maximum_runtime_seconds"], canonical_json(lease["quotas"]),
                    canonical_json(usage), canonical_json(lease["policy"]), canonical_json(lease["maintenance"]),
                    canonical_json(lease["failure_behavior"]), lease["status"], lease["state_version"],
                    lease["created_at"], lease["updated_at"],
                )
                connection.execute(
                    "INSERT INTO pilot_activation_leases("
                    "lease_id,schema_version,authorization_id,authorization_digest,"
                    "scope_envelope_digest,spec_manifest_digest,storage_schema_contract_digest,"
                    "fact_reconciliation_contract_digest,semantic_rules_digest,tool_allowlist_digest,"
                    "write_matrix_digest,execution_attempt_slot_schema_sha256,"
                    "execution_authorization_receipt_schema_sha256,"
                    "authentication_conformance_receipt_schema_sha256,"
                    "expiry_conformance_receipt_schema_sha256,authorized_work_item_id,"
                    "source_binding_json,runtime_binding_json,principal_binding_json,scope_binding_json,"
                    "issued_at,not_before,expires_at,maximum_runtime_seconds,quotas_json,usage_json,"
                    "policy_json,maintenance_json,failure_behavior_json,status,state_version,created_at,updated_at"
                    ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    values,
                )
                row = connection.execute(
                    "SELECT * FROM pilot_activation_leases WHERE lease_id=?", (lease["lease_id"],)
                ).fetchone()
                _append_event(connection, row, event_type="lease_issued", status_before=None, status_after="prepared")
            finally:
                self.ledger.finalize_activation_control_write(connection, session=session)
        return lease

    def _transition_runtime(
        self,
        lease_id: str,
        *,
        event_type: str,
        process_identity_digest: str,
        listener_attestation_digest: str | None = None,
        request_context_binding: str | None = None,
        monotonic_claim_ns: int | None = None,
        monotonic_deadline_ns: int | None = None,
        _capability: object | None = None,
    ) -> dict[str, Any]:
        transitions = {"process_claimed": ("prepared", "claimed"), "listener_attested": ("claimed", "active")}
        if event_type not in transitions:
            raise WorkItemGovernanceError("PILOT_RUNTIME_TRANSITION_INVALID", "Unsupported Pilot runtime transition.")
        expected_capability = (
            self.__process_claim_capability
            if event_type == "process_claimed"
            else self.__listener_attestation_capability
        )
        if _capability is not expected_capability:
            raise WorkItemGovernanceError(
                "PILOT_RUNTIME_TRANSITION_CAPABILITY_INVALID",
                "Runtime transitions require the exact verified process-claim or listener-attestation capability.",
            )
        before, after = transitions[event_type]
        with self.ledger.write_transaction() as connection:
            session = self.ledger.authorize_activation_control_write(
                connection, controller=self, controller_binding=self.__repository_control_binding
            )
            try:
                row = connection.execute("SELECT * FROM pilot_activation_leases WHERE lease_id=?", (lease_id,)).fetchone()
                if row is None or row["status"] != before:
                    raise WorkItemGovernanceError("PILOT_LEASE_STATE_CONFLICT", "Pilot runtime transition state is stale.")
                runtime = _json(row, "runtime_binding_json")
                runtime["claimed_process_identity"] = process_identity_digest
                if event_type == "process_claimed":
                    runtime["monotonic_claim_ns"] = monotonic_claim_ns
                    runtime["monotonic_deadline_ns"] = monotonic_deadline_ns
                else:
                    runtime["listener_attested_at"] = isoformat_utc(self.now())
                    runtime["listener_attestation_digest"] = listener_attestation_digest
                    runtime["request_context_binding_digest"] = request_context_binding
                usage = _json(row, "usage_json")
                usage["lease_events"] = int(usage["lease_events"]) + 1
                version = int(row["state_version"]) + 1
                now_text = isoformat_utc(self.now())
                connection.execute(
                    "UPDATE pilot_activation_leases SET runtime_binding_json=?,usage_json=?,status=?,state_version=?,updated_at=? WHERE lease_id=? AND state_version=?",
                    (canonical_json(runtime), canonical_json(usage), after, version, now_text, lease_id, int(row["state_version"])),
                )
                current = connection.execute("SELECT * FROM pilot_activation_leases WHERE lease_id=?", (lease_id,)).fetchone()
                _append_event(
                    connection, current, event_type=event_type, status_before=before, status_after=after,
                    process_identity_digest=process_identity_digest,
                    listener_attestation_digest=listener_attestation_digest,
                    state_version_before=int(row["state_version"]),
                )
            finally:
                self.ledger.finalize_activation_control_write(connection, session=session)
        return _lease_record(current)

    def claim_prepared_lease(
        self,
        *,
        lease_id: str,
        envelope_path: str,
        claimed_envelope_path: str,
    ) -> dict[str, Any]:
        from runner.work_item_governance.activation import process_identity_inputs

        if Path(envelope_path).resolve() == Path(claimed_envelope_path).resolve():
            raise WorkItemGovernanceError("PILOT_CLAIM_PATH_INVALID", "Claim input and consumed output paths must differ.")
        identity = process_identity_inputs(str(self.ledger.project_root))
        monotonic_claim = time.monotonic_ns()
        with self.ledger.read_connection() as connection:
            row = connection.execute("SELECT * FROM pilot_activation_leases WHERE lease_id=?", (lease_id,)).fetchone()
        if row is None:
            raise WorkItemGovernanceError("PILOT_ACTIVATION_LEASE_REQUIRED", "Pilot Lease does not exist.")
        runtime = _json(row, "runtime_binding_json")
        if identity["expected_process_identity"] != runtime["expected_process_identity"]:
            raise WorkItemGovernanceError("PILOT_PROCESS_IDENTITY_MISMATCH", "Runtime process differs from the exact Pilot binding.")
        return self._transition_runtime(
            lease_id,
            event_type="process_claimed",
            process_identity_digest=identity["expected_process_identity"],
            monotonic_claim_ns=monotonic_claim,
            monotonic_deadline_ns=monotonic_claim + int(row["maximum_runtime_seconds"]) * 1_000_000_000,
            _capability=self.__process_claim_capability,
        )

    def attest_listener(
        self,
        *,
        lease_id: str,
        bind_address: str,
        port: int,
        observed_listeners: list[tuple[str, int]],
    ) -> dict[str, Any]:
        if bind_address != "127.0.0.1":
            raise WorkItemGovernanceError("PILOT_LISTENER_BINDING_INVALID", "Pilot listener must use strict loopback.")
        observed = sorted((str(address), int(listener_port)) for address, listener_port in observed_listeners)
        if observed != [(bind_address, port)]:
            raise WorkItemGovernanceError("PILOT_LISTENER_ATTESTATION_FAILED", "Exactly one Pilot listener must be observed.")
        with self.ledger.read_connection() as connection:
            row = connection.execute("SELECT * FROM pilot_activation_leases WHERE lease_id=?", (lease_id,)).fetchone()
        runtime = _json(row, "runtime_binding_json")
        principal = _json(row, "principal_binding_json")
        listener_digest = canonical_sha256({"bind_address": bind_address, "port": port, "observed": observed})
        context_digest = request_context_binding_digest(
            lease_id=lease_id,
            authorization_digest=str(row["authorization_digest"]),
            claimed_process_identity=str(runtime["claimed_process_identity"]),
            runtime_instance_nonce=str(runtime["runtime_instance_nonce"]),
            listener_digest=listener_digest,
            principal_id=str(principal["principal_id"]),
            session_ref=str(principal["session_ref"]),
        )
        return self._transition_runtime(
            lease_id,
            event_type="listener_attested",
            process_identity_digest=str(runtime["claimed_process_identity"]),
            listener_attestation_digest=listener_digest,
            request_context_binding=context_digest,
            _capability=self.__listener_attestation_capability,
        )

    def revoke(self, *, lease_id: str, reason: str) -> dict[str, Any]:
        _ = reason
        with self.ledger.write_transaction() as connection:
            session = self.ledger.authorize_activation_control_write(
                connection, controller=self, controller_binding=self.__repository_control_binding
            )
            try:
                row = connection.execute("SELECT * FROM pilot_activation_leases WHERE lease_id=?", (lease_id,)).fetchone()
                if row is None or row["status"] not in {"prepared", "claimed", "active", "write_frozen"}:
                    raise WorkItemGovernanceError("PILOT_LEASE_STATE_CONFLICT", "Only a nonterminal Pilot Lease may be revoked.")
                before = str(row["status"])
                usage = _json(row, "usage_json")
                usage["lease_events"] = int(usage["lease_events"]) + 1
                version = int(row["state_version"]) + 1
                now_text = isoformat_utc(self.now())
                connection.execute(
                    "UPDATE pilot_activation_leases SET status='revoked',usage_json=?,state_version=?,updated_at=? WHERE lease_id=? AND state_version=?",
                    (canonical_json(usage), version, now_text, lease_id, int(row["state_version"])),
                )
                current = connection.execute("SELECT * FROM pilot_activation_leases WHERE lease_id=?", (lease_id,)).fetchone()
                _append_event(
                    connection, current, event_type="lease_revoked", status_before=before,
                    status_after="revoked", rejection_code="PILOT_LEASE_REVOKED",
                    state_version_before=int(row["state_version"]),
                )
            finally:
                self.ledger.finalize_activation_control_write(connection, session=session)
        return _lease_record(current)

    def close(self, *, lease_id: str, reason: str) -> dict[str, Any]:
        _ = reason
        return self._terminal_transition(
            lease_id=lease_id,
            allowed={"active", "write_frozen"},
            status="closed",
            event_type="lease_closed",
            rejection_code=None,
        )

    def freeze(self, *, lease_id: str, reason: str) -> dict[str, Any]:
        _ = reason
        with self.ledger.write_transaction() as connection:
            session = self.ledger.authorize_activation_control_write(
                connection, controller=self, controller_binding=self.__repository_control_binding
            )
            try:
                row = connection.execute("SELECT * FROM pilot_activation_leases WHERE lease_id=?", (lease_id,)).fetchone()
                if row is None or row["status"] != "active":
                    raise WorkItemGovernanceError("PILOT_LEASE_STATE_CONFLICT", "Only an active Pilot Lease may freeze writes.")
                usage = _json(row, "usage_json")
                usage["lease_events"] = int(usage["lease_events"]) + 1
                version = int(row["state_version"]) + 1
                now_text = isoformat_utc(self.now())
                connection.execute(
                    "UPDATE pilot_activation_leases SET status='write_frozen',usage_json=?,state_version=?,updated_at=? WHERE lease_id=? AND state_version=?",
                    (canonical_json(usage), version, now_text, lease_id, int(row["state_version"])),
                )
                current = connection.execute("SELECT * FROM pilot_activation_leases WHERE lease_id=?", (lease_id,)).fetchone()
                _append_event(
                    connection,
                    current,
                    event_type="lease_write_frozen",
                    status_before="active",
                    status_after="write_frozen",
                    command_name="runtime_stop",
                    source_event_key=canonical_sha256({"lease_id": lease_id, "reason": reason}),
                    request_context_digest=_json(row, "runtime_binding_json")["request_context_binding_digest"],
                    principal_digest=canonical_sha256(_json(row, "principal_binding_json")),
                    rejection_code="PILOT_AUTHORITY_WRITE_FROZEN",
                    state_version_before=int(row["state_version"]),
                )
            finally:
                self.ledger.finalize_activation_control_write(connection, session=session)
        return _lease_record(current)

    def expire(self, *, lease_id: str) -> dict[str, Any]:
        return self._terminal_transition(
            lease_id=lease_id,
            allowed={"prepared", "claimed", "active", "write_frozen"},
            status="expired",
            event_type="lease_expired",
            rejection_code="PILOT_LEASE_EXPIRED",
        )

    def _terminal_transition(
        self,
        *,
        lease_id: str,
        allowed: set[str],
        status: str,
        event_type: str,
        rejection_code: str | None,
    ) -> dict[str, Any]:
        with self.ledger.write_transaction() as connection:
            session = self.ledger.authorize_activation_control_write(
                connection, controller=self, controller_binding=self.__repository_control_binding
            )
            try:
                row = connection.execute("SELECT * FROM pilot_activation_leases WHERE lease_id=?", (lease_id,)).fetchone()
                if row is None or row["status"] not in allowed:
                    raise WorkItemGovernanceError("PILOT_LEASE_STATE_CONFLICT", "Pilot terminal transition is not allowed.")
                before = str(row["status"])
                usage = _json(row, "usage_json")
                usage["lease_events"] = int(usage["lease_events"]) + 1
                version = int(row["state_version"]) + 1
                now_text = isoformat_utc(self.now())
                connection.execute(
                    "UPDATE pilot_activation_leases SET status=?,usage_json=?,state_version=?,updated_at=? WHERE lease_id=? AND state_version=?",
                    (status, canonical_json(usage), version, now_text, lease_id, int(row["state_version"])),
                )
                current = connection.execute("SELECT * FROM pilot_activation_leases WHERE lease_id=?", (lease_id,)).fetchone()
                _append_event(
                    connection,
                    current,
                    event_type=event_type,
                    status_before=before,
                    status_after=status,
                    rejection_code=rejection_code,
                    state_version_before=int(row["state_version"]),
                )
            finally:
                self.ledger.finalize_activation_control_write(connection, session=session)
        return _lease_record(current)


class PilotActivationGuard:
    """Transactional, single-Work-Item authority for the bounded Pilot."""

    def __init__(
        self,
        ledger: SQLiteWorkItemLedger,
        *,
        now: Callable[[], datetime] = utc_now,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        verify_pilot_frozen_contract_resources()
        self.ledger = ledger
        self.now = now
        self.monotonic_ns = monotonic_ns
        self.__write_session_seal = secrets.token_bytes(32)
        self.__request_context_seal = object()
        self.__issued_write_sessions: dict[int, ActivationWriteSession] = {}
        self.__issued_request_contexts: dict[int, AuthoritativeCanaryRequestContext] = {}
        self.__consumed_request_proofs: dict[int, AuthenticatedTokenRequestProof] = {}
        self.__repository_control_binding = ledger._bind_activation_controller(self)

    def _is_issued_write_session(self, session: ActivationWriteSession) -> bool:
        return bool(
            session.guard is self
            and self.__issued_write_sessions.get(id(session)) is session
            and isinstance(session._trust_seal, bytes)
            and secrets.compare_digest(session._trust_seal, self.__write_session_seal)
            and not session.finalized
        )

    def _discard_write_session(self, session: ActivationWriteSession) -> None:
        self.__issued_write_sessions.pop(id(session), None)

    def _is_issued_request_context(self, context: AuthoritativeCanaryRequestContext) -> bool:
        return bool(
            context._trust_seal is self.__request_context_seal
            and self.__issued_request_contexts.get(id(context)) is context
        )

    def retire_request_context(self, request_context: AuthoritativeCanaryRequestContext | None) -> bool:
        if type(request_context) is not AuthoritativeCanaryRequestContext:
            return False
        return self.__issued_request_contexts.pop(id(request_context), None) is request_context

    def mint_request_context(self, *, proof: Any, principal_context: PrincipalContext | None) -> AuthoritativeCanaryRequestContext:
        if (
            type(proof) is not AuthenticatedTokenRequestProof
            or not proof.structurally_valid()
            or not proof.active
            or self.__consumed_request_proofs.get(id(proof)) is proof
        ):
            raise WorkItemGovernanceError(
                "AUTHENTICATED_REQUEST_CONTEXT_REQUIRED",
                "The bounded Pilot requires one fresh verified Bearer Token request.",
            )
        with self.ledger.read_connection() as connection:
            row = self._active(connection)
            principal = self._principal(row, principal_context)
            bindings = {
                str(item["key"]): str(item["value"])
                for item in connection.execute(
                    "SELECT key,value FROM ledger_meta WHERE key IN (?,?)",
                    (AUTHORITATIVE_TOKEN_FILE_SHA256_META_KEY, AUTHORITATIVE_TOKEN_EVIDENCE_DIGEST_META_KEY),
                ).fetchall()
            }
        if (
            proof.lease_id != row["lease_id"]
            or proof.token_file_sha256 != bindings.get(AUTHORITATIVE_TOKEN_FILE_SHA256_META_KEY)
            or proof.token_evidence_digest != bindings.get(AUTHORITATIVE_TOKEN_EVIDENCE_DIGEST_META_KEY)
        ):
            raise WorkItemGovernanceError("AUTHENTICATED_REQUEST_PROOF_BINDING_MISMATCH", "Bearer proof differs from the Pilot Token binding.")
        runtime = _json(row, "runtime_binding_json")
        config_home = Path(str(__import__("os").environ.get("XDG_CONFIG_HOME") or "")).expanduser().resolve()
        auth_file = config_home / "colameta" / "auth.json"
        if runtime["token_file_path_digest"] != canonical_path_digest(auth_file):
            raise WorkItemGovernanceError("ACTIVATION_TOKEN_PATH_BINDING_MISMATCH", "Pilot Token path differs from runtime binding.")
        token = require_authoritative_token_file_binding(
            self.ledger, auth_file, expected_evidence_digest=proof.token_evidence_digest
        )
        if not proof.verify_signature(token):
            raise WorkItemGovernanceError("AUTHENTICATED_REQUEST_PROOF_INVALID", "Bearer proof signature is invalid.")
        expected = request_context_binding_digest(
            lease_id=str(row["lease_id"]),
            authorization_digest=str(row["authorization_digest"]),
            claimed_process_identity=str(runtime["claimed_process_identity"]),
            runtime_instance_nonce=str(runtime["runtime_instance_nonce"]),
            listener_digest=str(runtime["listener_attestation_digest"]),
            principal_id=principal.principal_id,
            session_ref=str(principal.session_ref),
        )
        if expected != runtime["request_context_binding_digest"]:
            raise WorkItemGovernanceError("REQUEST_CONTEXT_BINDING_MISMATCH", "Pilot request-context runtime binding is invalid.")
        context = _mint_authoritative_request_context(
            proof=proof,
            lease_id=str(row["lease_id"]),
            authorization_digest=str(row["authorization_digest"]),
            claimed_process_identity=str(runtime["claimed_process_identity"]),
            runtime_instance_nonce=str(runtime["runtime_instance_nonce"]),
            listener_attestation_digest=str(runtime["listener_attestation_digest"]),
            principal_id=principal.principal_id,
            session_ref=str(principal.session_ref),
            binding_digest=expected,
            trust_seal=self.__request_context_seal,
            active_validator=self._is_issued_request_context,
        )
        self.__issued_request_contexts[id(context)] = context
        self.__consumed_request_proofs[id(proof)] = proof
        return context

    def _latest(self, connection: sqlite3.Connection) -> sqlite3.Row:
        row = connection.execute("SELECT * FROM pilot_activation_leases ORDER BY created_at DESC LIMIT 1").fetchone()
        if row is None:
            raise WorkItemGovernanceError("PILOT_ACTIVATION_LEASE_REQUIRED", "A Pilot Activation Lease is required.")
        return row

    def _active(self, connection: sqlite3.Connection) -> sqlite3.Row:
        row = self._latest(connection)
        if row["status"] != "active":
            raise WorkItemGovernanceError("PILOT_ACTIVE_LEASE_REQUIRED", "Pilot writes require an active Lease.")
        self._require_active_time_window(row)
        return row

    def _require_active_time_window(self, row: sqlite3.Row) -> None:
        now = self.now().astimezone(timezone.utc)
        if now < parse_timestamp(str(row["not_before"]), "not_before") or now >= parse_timestamp(str(row["expires_at"]), "expires_at"):
            raise WorkItemGovernanceError("PILOT_LEASE_EXPIRED", "Pilot Lease is outside its authorized UTC window.")
        runtime = _json(row, "runtime_binding_json")
        deadline = runtime.get("monotonic_deadline_ns")
        if isinstance(deadline, int) and self.monotonic_ns() >= deadline:
            raise WorkItemGovernanceError("PILOT_LEASE_EXPIRED", "Pilot Lease monotonic deadline has expired.")

    @staticmethod
    def _principal(row: sqlite3.Row, principal: PrincipalContext | None) -> PrincipalContext:
        if not isinstance(principal, PrincipalContext) or not principal.trusted:
            raise WorkItemGovernanceError("TRUSTED_PRINCIPAL_REQUIRED", "Pilot authority requires a trusted Principal capability.")
        binding = _json(row, "principal_binding_json")
        if (
            principal.principal_id != binding["principal_id"]
            or principal.principal_kind != binding["principal_kind"]
            or principal.session_ref != binding["session_ref"]
            or sorted(principal.granted_permissions) != sorted(binding["permissions"])
        ):
            raise WorkItemGovernanceError("PILOT_PRINCIPAL_MISMATCH", "Principal differs from the Pilot Lease binding.")
        return principal

    def _request(self, row: sqlite3.Row, principal: PrincipalContext | None, context: AuthoritativeCanaryRequestContext | None) -> PrincipalContext:
        trusted = self._principal(row, principal)
        runtime = _json(row, "runtime_binding_json")
        if (
            not isinstance(context, AuthoritativeCanaryRequestContext)
            or not context.active
            or not self._is_issued_request_context(context)
        ):
            raise WorkItemGovernanceError("AUTHENTICATED_REQUEST_CONTEXT_REQUIRED", "Pilot commands require a live token-authenticated request capability.")
        if context.lease_id != row["lease_id"] or context.principal_id != trusted.principal_id:
            raise WorkItemGovernanceError("PILOT_REQUEST_CONTEXT_MISMATCH", "Request capability differs from the Pilot Lease binding.")
        if context.binding_digest != runtime.get("request_context_binding_digest"):
            raise WorkItemGovernanceError("PILOT_REQUEST_CONTEXT_MISMATCH", "Request capability digest differs from the Pilot runtime binding.")
        return trusted

    def authorized_work_item_id(self) -> str | None:
        with self.ledger.read_connection() as connection:
            row = self._latest(connection)
        return None if row["authorized_work_item_id"] is None else str(row["authorized_work_item_id"])

    def assert_read_scope(self, work_item_id: str) -> None:
        if self.authorized_work_item_id() != work_item_id:
            raise WorkItemGovernanceError("PILOT_WORK_ITEM_SCOPE_VIOLATION", "Read is outside the Pilot Work Item scope.")

    def runtime_status(self) -> dict[str, Any]:
        with self.ledger.read_connection() as connection:
            try:
                row = self._latest(connection)
            except WorkItemGovernanceError:
                return {"present": False, "status": None, "effective_active": False}
        effective_active = str(row["status"]) == "active"
        if effective_active:
            try:
                self._require_active_time_window(row)
            except WorkItemGovernanceError:
                effective_active = False
        return {
            "present": True,
            "lease_id": str(row["lease_id"]),
            "status": str(row["status"]),
            "effective_active": effective_active,
            "authorized_work_item_id": row["authorized_work_item_id"],
            "scope_mode": PILOT_SCOPE_MODE,
        }

    def dispatch_authority_active(self) -> bool:
        with self.ledger.read_connection() as connection:
            try:
                self._active(connection)
            except WorkItemGovernanceError:
                return False
        return True

    def assert_attempt_dispatch_authority(self, attempt_id: str, work_item_id: str, task_version: int) -> None:
        with self.ledger.read_connection() as connection:
            row = self._active(connection)
            usage = _json(row, "usage_json")
            matches = [
                slot for slot in usage["execution_slots"]
                if slot["attempt_id"] == attempt_id and int(slot["task_version"]) == task_version and slot["status"] == "bound"
            ]
            if len(matches) != 1:
                raise WorkItemGovernanceError("PILOT_ATTEMPT_DISPATCH_DENIED", "Attempt lacks one active Pilot execution Slot.")
            attempt = connection.execute(
                "SELECT * FROM execution_attempts WHERE attempt_id=?", (attempt_id,)
            ).fetchone()
            task = connection.execute(
                "SELECT payload_digest FROM task_versions WHERE work_item_id=? AND task_version=?",
                (work_item_id, task_version),
            ).fetchone()
            work_item = connection.execute(
                "SELECT current_task_version,state FROM work_items WHERE work_item_id=?", (work_item_id,)
            ).fetchone()
            slot = matches[0]
            if (
                attempt is None
                or task is None
                or work_item is None
                or attempt["work_item_id"] != work_item_id
                or int(attempt["task_version"]) != task_version
                or attempt["status"] not in {"claimed", "running"}
                or canonical_sha256(attempt["objective_ref"]) != slot["objective_digest"]
                or str(task["payload_digest"]) != slot["task_version_payload_digest"]
                or int(work_item["current_task_version"]) != task_version
                or work_item["state"] in {"submitted", "accepted", "cancelled"}
            ):
                raise WorkItemGovernanceError(
                    "PILOT_ATTEMPT_DISPATCH_DENIED",
                    "Attempt runtime facts differ from its exact Pilot execution Slot.",
                )

    def authorize_preview(self, *, command_name: str, normalized_command: dict[str, Any], principal_context: PrincipalContext | None, request_context: AuthoritativeCanaryRequestContext | None) -> str | None:
        if command_name not in {"apply_work_item_create", "apply_work_item_transition"}:
            raise WorkItemGovernanceError("PILOT_COMMAND_DENIED", "Preview command is outside the Pilot allowlist.")
        with self.ledger.read_connection() as connection:
            row = self._active(connection)
            self._request(row, principal_context, request_context)
            self._reconcile(connection, row)
            if command_name == "apply_work_item_create":
                return str(_json(row, "scope_binding_json")["proposed_work_item_id"])
        return None

    def begin_write(
        self,
        connection: sqlite3.Connection,
        *,
        command_name: str,
        normalized_command: dict[str, Any],
        source_event_key: str,
        principal_context: PrincipalContext | None,
        request_context: AuthoritativeCanaryRequestContext | None,
    ) -> ActivationWriteSession:
        if command_name not in PILOT_ALLOWED_WRITES:
            raise WorkItemGovernanceError("PILOT_COMMAND_DENIED", "Write command is outside the Pilot allowlist.")
        control = self.ledger.authorize_activation_control_write(
            connection, controller=self, controller_binding=self.__repository_control_binding
        )
        try:
            row = self._active(connection)
            principal = self._request(row, principal_context, request_context)
            self._reconcile(connection, row)
            source_digest = canonical_sha256({"command_name": command_name, "source_event_key": source_event_key})
        finally:
            self.ledger.finalize_activation_control_write(connection, session=control)
        connection.execute("SAVEPOINT pilot_domain_write")
        session = ActivationWriteSession(
            guard=self,
            connection=connection,
            row=row,
            command_name=command_name,
            normalized_command=normalized_command,
            source_event_key_digest=source_digest,
            principal_binding_digest=canonical_sha256(principal.to_record()),
            baseline_fact_counts=_activation_domain_fact_counts(connection),
            _trust_seal=self.__write_session_seal,
        )
        self.__issued_write_sessions[id(session)] = session
        self.ledger.authorize_activation_domain_write(connection, session=session)
        return session

    def deny_command(self, connection: sqlite3.Connection, *, command_name: str, principal_context: PrincipalContext | None, request_context: AuthoritativeCanaryRequestContext | None) -> None:
        control = self.ledger.authorize_activation_control_write(
            connection, controller=self, controller_binding=self.__repository_control_binding
        )
        try:
            row = self._active(connection)
            principal = self._request(row, principal_context, request_context)
            self._freeze_and_raise(
                connection,
                row,
                error=WorkItemGovernanceError(
                    "PILOT_COMMAND_DENIED",
                    "Command is denied by the bounded Pilot matrix.",
                    details={"command": command_name},
                ),
                command_name=command_name,
                source_event_key=canonical_sha256({"denied_command": command_name}),
                request_context_digest=request_context.binding_digest,
                principal_digest=canonical_sha256(principal.to_record()),
            )
        finally:
            if not self.ledger.activation_control_write_finalized(connection, session=control):
                self.ledger.finalize_activation_control_write(connection, session=control)

    def _authorize_new(self, session: ActivationWriteSession, *, work_item_id: str | None, fact_delta: dict[str, int], domain_fact_delta: dict[str, int] | None) -> None:
        try:
            self._authorize_new_checked(
                session,
                work_item_id=work_item_id,
                fact_delta=fact_delta,
                domain_fact_delta=domain_fact_delta,
            )
        except WorkItemGovernanceError as exc:
            self._freeze_and_raise(
                session.connection,
                session.row,
                error=exc,
                command_name=session.command_name,
                source_event_key=session.source_event_key_digest,
                request_context_digest=_json(session.row, "runtime_binding_json")["request_context_binding_digest"],
                principal_digest=session.principal_binding_digest,
                session=session,
            )

    def _authorize_new_checked(self, session: ActivationWriteSession, *, work_item_id: str | None, fact_delta: dict[str, int], domain_fact_delta: dict[str, int] | None) -> None:
        row = session.row
        scope = _json(row, "scope_binding_json")
        bound = row["authorized_work_item_id"]
        if session.command_name == "apply_work_item_create":
            if bound is not None:
                raise WorkItemGovernanceError("PILOT_SECOND_WORK_ITEM_DENIED", "Pilot Lease already owns its Work Item.")
            proposed = scope["proposed_work_item_id"]
            if work_item_id is not None and work_item_id != proposed:
                raise WorkItemGovernanceError("PILOT_WORK_ITEM_SCOPE_VIOLATION", "Create differs from the preallocated Work Item.")
            command = session.normalized_command
            objective = command.get("attributes", {}).get("objective")
            if (
                canonical_sha256(command) != scope["authorized_create_command_digest"]
                or canonical_sha256(command.get("origin")) != scope["origin_digest"]
                or canonical_sha256(objective) != scope["objective_digest"]
                or canonical_sha256(command.get("task")) != scope["task_version_payload_digests"][0]
            ):
                raise WorkItemGovernanceError(
                    "PILOT_WORK_ITEM_SCOPE_VIOLATION",
                    "Create command, Origin, objective, or initial Task differs from the Pilot Scope.",
                )
        elif bound is None or work_item_id != bound:
            raise WorkItemGovernanceError("PILOT_WORK_ITEM_SCOPE_VIOLATION", "Command is outside the Pilot Work Item scope.")
        if session.command_name == "add_task_version":
            version = int(session.normalized_command["task_version"])
            payloads = scope["task_version_payload_digests"]
            if version > len(payloads) or canonical_sha256(session.normalized_command["task"]) != payloads[version - 1]:
                raise WorkItemGovernanceError(
                    "PILOT_TASK_VERSION_SCOPE_VIOLATION",
                    "Task Version payload is not the next preauthorized Pilot payload.",
                )
        if session.command_name == "create_execution_attempt" and session.normalized_command.get("external_refs"):
            raise WorkItemGovernanceError(
                "PILOT_EXTERNAL_ASSOCIATION_DENIED",
                "The bounded Pilot forbids external execution associations.",
            )
        if session.command_name in {"register_artifact_reference", "complete_execution_attempt"}:
            artifacts = (
                [session.normalized_command]
                if session.command_name == "register_artifact_reference"
                else list(session.normalized_command.get("artifacts", []))
            )
            for artifact in artifacts:
                self._validate_artifact_policy(artifact)
        actual_delta = dict(domain_fact_delta or {})
        if set(actual_delta) != set(_activation_domain_fact_counts(session.connection)):
            raise WorkItemGovernanceError("PILOT_FACT_DELTA_INVALID", "Pilot command must declare the complete domain fact delta.")
        usage = _json(row, "usage_json")
        quotas = _json(row, "quotas_json")
        for domain_key, value in actual_delta.items():
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise WorkItemGovernanceError("PILOT_FACT_DELTA_INVALID", "Pilot fact deltas must be non-negative integers.")
            usage_key = DOMAIN_TO_USAGE[domain_key]
            quota_key = PILOT_FACT_TO_QUOTA[usage_key]
            if int(usage[usage_key]) + value > int(quotas[quota_key]):
                raise WorkItemGovernanceError("PILOT_QUOTA_EXCEEDED", "Pilot fact quota would be exceeded.", details={"quota": quota_key})
        if int(usage["lease_events"]) >= int(quotas["maximum_lease_events"]) - 1:
            raise WorkItemGovernanceError("PILOT_LEASE_EVENT_LIMIT", "Pilot reserves its last Lease Event for closeout.")
        if session.command_name == "create_execution_attempt":
            self._select_attempt_slot(session, usage)
        elif session.command_name == "complete_execution_attempt":
            attempt_id = str(session.normalized_command.get("attempt_id") or "")
            candidates = [slot for slot in usage["execution_slots"] if slot["attempt_id"] == attempt_id and slot["status"] == "bound"]
            if len(candidates) != 1:
                raise WorkItemGovernanceError("PILOT_EXECUTION_SLOT_MISMATCH", "Completion does not target one bound execution Slot.")
            session.fixture_slot = {"pilot_execution_slot_id": candidates[0]["slot_id"]}
        session.fact_delta = {key: int(fact_delta.get(key, 0)) for key in fact_delta}
        session.domain_fact_delta = actual_delta

    @staticmethod
    def _validate_artifact_policy(artifact: dict[str, Any]) -> None:
        allowed_kinds = {
            "evidence_receipt",
            "file",
            "git_commit",
            "git_diff",
            "report",
            "test_report",
            "validation",
        }
        uri = str(artifact.get("uri") or "")
        scheme = "project" if uri.startswith("project://") else ("file" if uri.startswith("file://") else "relative")
        immutable_ref = str(artifact.get("immutable_ref") or "")
        mutable_names = {"main", "master", "head", "latest", "current"}
        if (
            artifact.get("kind") not in allowed_kinds
            or scheme not in {"project", "file", "relative"}
            or not immutable_ref
            or immutable_ref.strip().lower() in mutable_names
        ):
            raise WorkItemGovernanceError(
                "PILOT_ARTIFACT_POLICY_VIOLATION",
                "Artifact kind, URI scheme, or immutable reference violates the Pilot policy.",
            )

    def _select_attempt_slot(self, session: ActivationWriteSession, usage: dict[str, Any]) -> None:
        command = session.normalized_command
        task_version = int(command["task_version"])
        task = session.connection.execute(
            "SELECT payload_digest FROM task_versions WHERE work_item_id=? AND task_version=?",
            (command["work_item_id"], task_version),
        ).fetchone()
        if task is None:
            raise WorkItemGovernanceError("PILOT_TASK_VERSION_NOT_AUTHORIZED", "Execution Slot Task Version is absent.")
        objective_digest = canonical_sha256(command.get("objective_ref"))
        candidates = sorted(
            (
                slot for slot in usage["execution_slots"]
                if slot["status"] == "available"
                and int(slot["task_version"]) == task_version
                and slot["task_version_payload_digest"] == str(task["payload_digest"])
                and slot["objective_digest"] == objective_digest
            ),
            key=lambda slot: int(slot["ordinal"]),
        )
        if not candidates:
            raise WorkItemGovernanceError("PILOT_EXECUTION_SLOT_MISMATCH", "No authorized execution Slot matches the current Task Version and objective.")
        slot = candidates[0]
        predecessor = slot["retry_of_slot_id"]
        if predecessor is not None:
            prior = next((item for item in usage["execution_slots"] if item["slot_id"] == predecessor), None)
            if prior is None or prior["status"] != "completed":
                raise WorkItemGovernanceError("PILOT_RETRY_SLOT_PREDECESSOR_INCOMPLETE", "Retry Slot predecessor is not completed.")
        session.fixture_slot = {"pilot_execution_slot_id": slot["slot_id"]}

    def _authorize_replay(self, session: ActivationWriteSession, *, work_item_id: str) -> None:
        if session.row["authorized_work_item_id"] != work_item_id:
            raise WorkItemGovernanceError("PILOT_WORK_ITEM_SCOPE_VIOLATION", "Replay is outside Pilot scope.")
        event = session.connection.execute(
            "SELECT 1 FROM pilot_activation_lease_events WHERE lease_id=? AND source_event_key_digest=?",
            (session.row["lease_id"], session.source_event_key_digest),
        ).fetchone()
        if event is None:
            raise WorkItemGovernanceError("PILOT_REPLAY_NOT_AUTHORIZED", "Replay has no committed Pilot event.")
        session.connection.execute("RELEASE SAVEPOINT pilot_domain_write")
        self.ledger.finalize_activation_domain_write(session.connection, session=session)
        session._finalized = True
        self._discard_write_session(session)

    def _commit_new(self, session: ActivationWriteSession, *, work_item_id: str, event_type: str, generated_ids: dict[str, list[str]] | None) -> None:
        try:
            self._commit_new_checked(
                session,
                work_item_id=work_item_id,
                event_type=event_type,
                generated_ids=generated_ids,
            )
        except CommitWorkItemRejection:
            raise
        except WorkItemGovernanceError as exc:
            self._freeze_and_raise(
                session.connection,
                session.row,
                error=exc,
                command_name=session.command_name,
                source_event_key=session.source_event_key_digest,
                request_context_digest=_json(session.row, "runtime_binding_json")["request_context_binding_digest"],
                principal_digest=session.principal_binding_digest,
                session=session,
            )

    def _commit_new_checked(self, session: ActivationWriteSession, *, work_item_id: str, event_type: str, generated_ids: dict[str, list[str]] | None) -> None:
        if session.fact_delta is None or session.domain_fact_delta is None:
            raise WorkItemGovernanceError("PILOT_WRITE_NOT_AUTHORIZED", "Pilot write was not transactionally authorized.")
        connection = session.connection
        actual_counts = _activation_domain_fact_counts(connection)
        actual_delta = {key: int(actual_counts[key]) - int(session.baseline_fact_counts[key]) for key in actual_counts}
        if actual_delta != session.domain_fact_delta:
            raise WorkItemGovernanceError("PILOT_FACT_RECONCILIATION_FAILED", "Committed facts differ from the transaction declaration.", details={"expected": session.domain_fact_delta, "actual": actual_delta})
        row = connection.execute("SELECT * FROM pilot_activation_leases WHERE lease_id=?", (session.row["lease_id"],)).fetchone()
        if row is None or row["status"] != "active" or int(row["state_version"]) != int(session.row["state_version"]):
            raise WorkItemGovernanceError("PILOT_LEASE_CAS_CONFLICT", "Pilot Lease changed concurrently.")
        usage = _json(row, "usage_json")
        for domain_key, value in actual_delta.items():
            usage[DOMAIN_TO_USAGE[domain_key]] = int(usage[DOMAIN_TO_USAGE[domain_key]]) + value
        usage["gate_events_total"] = int(usage["applied_gate_events"]) + int(usage["rejected_gate_events"])
        usage["lease_events"] = int(usage["lease_events"]) + 1
        scope = _json(row, "scope_binding_json")
        bound = row["authorized_work_item_id"]
        if session.command_name == "apply_work_item_create":
            if work_item_id != scope["proposed_work_item_id"]:
                raise WorkItemGovernanceError("PILOT_WORK_ITEM_SCOPE_VIOLATION", "Created Work Item differs from the authorized ID.")
            bound = work_item_id
            scope["authorized_work_item_id"] = work_item_id
        if session.command_name == "create_execution_attempt":
            attempt_ids = (generated_ids or {}).get("attempt_ids", [])
            if len(attempt_ids) != 1:
                raise WorkItemGovernanceError("PILOT_EXECUTION_SLOT_BINDING_INVALID", "Attempt creation must bind exactly one generated Attempt ID.")
            self._update_slot(usage, session.fixture_slot, status="bound", attempt_id=attempt_ids[0])
        elif session.command_name == "complete_execution_attempt":
            self._update_slot(usage, session.fixture_slot, status="completed", attempt_id=str(session.normalized_command["attempt_id"]))
        now_text = isoformat_utc(self.now())
        next_version = int(row["state_version"]) + 1
        changed = connection.execute(
            "UPDATE pilot_activation_leases SET authorized_work_item_id=?,scope_binding_json=?,usage_json=?,state_version=?,updated_at=? WHERE lease_id=? AND state_version=?",
            (bound, canonical_json(scope), canonical_json(usage), next_version, now_text, row["lease_id"], int(row["state_version"])),
        ).rowcount
        if changed != 1:
            raise WorkItemGovernanceError("PILOT_LEASE_CAS_CONFLICT", "Pilot Lease usage CAS failed.")
        current = connection.execute("SELECT * FROM pilot_activation_leases WHERE lease_id=?", (row["lease_id"],)).fetchone()
        event_fact_delta = {DOMAIN_TO_USAGE[key]: value for key, value in actual_delta.items()}
        event_fact_delta["gate_events_total"] = (
            event_fact_delta["applied_gate_events"] + event_fact_delta["rejected_gate_events"]
        )
        _append_event(
            connection,
            current,
            event_type=event_type,
            status_before="active",
            status_after="active",
            command_name=session.command_name,
            source_event_key=session.source_event_key_digest,
            request_context_digest=_json(row, "runtime_binding_json")["request_context_binding_digest"],
            principal_digest=session.principal_binding_digest,
            fact_delta=event_fact_delta,
            rejection_code=("PILOT_DOMAIN_REJECTED" if event_type == "domain_rejected" else None),
            state_version_before=int(row["state_version"]),
        )
        connection.execute("RELEASE SAVEPOINT pilot_domain_write")
        self.ledger.finalize_activation_domain_write(connection, session=session)
        session._finalized = True
        self._discard_write_session(session)

    def _freeze_and_raise(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        *,
        error: WorkItemGovernanceError,
        command_name: str,
        source_event_key: str,
        request_context_digest: str,
        principal_digest: str,
        session: ActivationWriteSession | None = None,
    ) -> None:
        if session is not None:
            connection.execute("ROLLBACK TO SAVEPOINT pilot_domain_write")
            connection.execute("RELEASE SAVEPOINT pilot_domain_write")
        current = connection.execute("SELECT * FROM pilot_activation_leases WHERE lease_id=?", (row["lease_id"],)).fetchone()
        if current is not None and current["status"] == "active":
            version = int(current["state_version"]) + 1
            now_text = isoformat_utc(self.now())
            usage = _json(current, "usage_json")
            usage["lease_events"] = int(usage["lease_events"]) + 1
            connection.execute(
                "UPDATE pilot_activation_leases SET status='write_frozen',usage_json=?,state_version=?,updated_at=? WHERE lease_id=? AND state_version=?",
                (canonical_json(usage), version, now_text, current["lease_id"], int(current["state_version"])),
            )
            frozen = connection.execute("SELECT * FROM pilot_activation_leases WHERE lease_id=?", (current["lease_id"],)).fetchone()
            _append_event(
                connection,
                frozen,
                event_type="lease_write_frozen",
                status_before="active",
                status_after="write_frozen",
                command_name=command_name,
                source_event_key=source_event_key,
                request_context_digest=request_context_digest,
                principal_digest=principal_digest,
                rejection_code="PILOT_AUTHORITY_WRITE_FROZEN",
                state_version_before=int(current["state_version"]),
            )
        if session is not None:
            self.ledger.finalize_activation_domain_write(connection, session=session)
            session._finalized = True
            self._discard_write_session(session)
        raise CommitWorkItemRejection(error)

    def _update_slot(self, usage: dict[str, Any], binding: dict[str, Any] | None, *, status: str, attempt_id: str) -> None:
        slot_id = None if binding is None else binding.get("pilot_execution_slot_id")
        matches = [slot for slot in usage["execution_slots"] if slot["slot_id"] == slot_id]
        if len(matches) != 1:
            raise WorkItemGovernanceError("PILOT_EXECUTION_SLOT_BINDING_INVALID", "Execution Slot binding is unavailable.")
        slot = matches[0]
        now_text = isoformat_utc(self.now())
        if status == "bound":
            if slot["status"] != "available":
                raise WorkItemGovernanceError("PILOT_EXECUTION_SLOT_ALREADY_CONSUMED", "Execution Slot was already consumed.")
            slot.update(status="bound", attempt_id=attempt_id, bound_at=now_text)
        else:
            if slot["status"] != "bound" or slot["attempt_id"] != attempt_id:
                raise WorkItemGovernanceError("PILOT_EXECUTION_SLOT_BINDING_INVALID", "Attempt completion differs from its execution Slot.")
            slot.update(status="completed", completed_at=now_text)

    def _reconcile(self, connection: sqlite3.Connection, row: sqlite3.Row) -> None:
        counts = _activation_domain_fact_counts(connection)
        usage = _json(row, "usage_json")
        mismatches = {
            domain: {"actual": int(counts[domain]), "recorded": int(usage[usage_key])}
            for domain, usage_key in DOMAIN_TO_USAGE.items()
            if int(counts[domain]) != int(usage[usage_key])
        }
        if int(usage["gate_events_total"]) != int(usage["applied_gate_events"]) + int(usage["rejected_gate_events"]):
            mismatches["gate_events_total"] = {"actual": counts["applied_gate_events"] + counts["rejected_gate_events"], "recorded": usage["gate_events_total"]}
        event_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM pilot_activation_lease_events WHERE lease_id=?",
                (row["lease_id"],),
            ).fetchone()[0]
        )
        if event_count != int(usage["lease_events"]):
            mismatches["lease_events"] = {"actual": event_count, "recorded": usage["lease_events"]}
        denied_queries = {
            "historical_attempts": "SELECT COUNT(*) FROM execution_attempts WHERE attempt_kind='historical'",
            "external_associations": "SELECT COUNT(*) FROM external_associations",
            "delivery_receipts": "SELECT COUNT(*) FROM delivery_receipts",
            "blocker_events": "SELECT COUNT(*) FROM blocker_events",
            "inbox_events": "SELECT COUNT(*) FROM inbox_events",
            "legacy_activation_leases": "SELECT COUNT(*) FROM activation_leases",
            "legacy_activation_lease_events": "SELECT COUNT(*) FROM activation_lease_events",
        }
        for name, query in denied_queries.items():
            count = int(connection.execute(query).fetchone()[0])
            if count:
                mismatches[name] = {"actual": count, "recorded": 0}
        if mismatches:
            raise WorkItemGovernanceError("PILOT_FACT_RECONCILIATION_FAILED", "Pilot Lease usage differs from Ledger facts.", details=mismatches)


def _append_event(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
    *,
    event_type: str,
    status_before: str | None,
    status_after: str,
    process_identity_digest: str | None = None,
    listener_attestation_digest: str | None = None,
    command_name: str | None = None,
    source_event_key: str | None = None,
    request_context_digest: str | None = None,
    principal_digest: str | None = None,
    fact_delta: dict[str, int] | None = None,
    rejection_code: str | None = None,
    state_version_before: int | None = None,
) -> dict[str, Any]:
    prior = connection.execute(
        "SELECT sequence,event_digest FROM pilot_activation_lease_events WHERE lease_id=? ORDER BY sequence DESC LIMIT 1",
        (row["lease_id"],),
    ).fetchone()
    sequence = 1 if prior is None else int(prior["sequence"]) + 1
    runtime = _json(row, "runtime_binding_json")
    before = 0 if state_version_before is None and sequence == 1 else int(state_version_before if state_version_before is not None else row["state_version"] - 1)
    event = {
        "schema_version": PILOT_EVENT_SCHEMA,
        "lease_event_id": new_stable_id("activation_lease_event"),
        "lease_id": str(row["lease_id"]),
        "sequence": sequence,
        "authorization_digest": str(row["authorization_digest"]),
        "event_type": event_type,
        "previous_event_digest": None if prior is None else str(prior["event_digest"]),
        "event_digest": "0" * 64,
        "state_version_before": before,
        "state_version_after": int(row["state_version"]),
        "status_before": status_before,
        "status_after": status_after,
        "authorized_work_item_id": row["authorized_work_item_id"],
        "process_identity_digest": process_identity_digest or runtime.get("claimed_process_identity"),
        "listener_attestation_digest": listener_attestation_digest or runtime.get("listener_attestation_digest"),
        "command_name": command_name,
        "source_event_key": source_event_key,
        "request_context_digest": request_context_digest,
        "principal_digest": principal_digest,
        "fact_delta": {**_zero_delta(), **(fact_delta or {})},
        "rejection_code": rejection_code,
        "created_at": str(row["updated_at"]),
    }
    digest_input = dict(event)
    digest_input.pop("event_digest")
    event["event_digest"] = canonical_sha256(digest_input)
    validate_governance_record("pilot_activation_lease_event.v4", event)
    connection.execute(
        """
        INSERT INTO pilot_activation_lease_events(
          lease_event_id,schema_version,lease_id,sequence,event_type,status_before,status_after,
          state_version_before,state_version_after,authorization_digest,authorized_work_item_id,
          process_identity_digest,listener_attestation_digest,command_name,source_event_key_digest,
          request_context_digest,principal_digest,fact_delta_json,rejection_code,previous_event_digest,
          event_digest,event_json,created_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            event["lease_event_id"], event["schema_version"], event["lease_id"], event["sequence"],
            event["event_type"], event["status_before"], event["status_after"], event["state_version_before"],
            event["state_version_after"], event["authorization_digest"], event["authorized_work_item_id"],
            event["process_identity_digest"], event["listener_attestation_digest"], event["command_name"],
            event["source_event_key"] if event["source_event_key"] is not None else None,
            event["request_context_digest"], event["principal_digest"], canonical_json(event["fact_delta"]),
            event["rejection_code"], event["previous_event_digest"], event["event_digest"], canonical_json(event),
            event["created_at"],
        ),
    )
    return event


def validate_pilot_closeout(closeout: dict[str, Any]) -> dict[str, Any]:
    """Validate both the JSON shape and the frozen stage/fact truth table."""

    validate_governance_record("pilot_closeout.v4", closeout)
    stage = closeout["stage_reached"]
    work_item = closeout["work_item"]
    lease = closeout["lease"]
    ledger = closeout["ledger"]
    if stage == "pre_import" and any(value is not None for value in (ledger, lease, work_item)):
        raise WorkItemGovernanceError("PILOT_CLOSEOUT_STAGE_CONTRADICTION", "pre_import closeout cannot claim Ledger, Lease, or Work Item facts.")
    if stage == "lifecycle_completed":
        state = None if work_item is None else work_item["state"]
        if state not in {"accepted", "cancelled"}:
            raise WorkItemGovernanceError("PILOT_CLOSEOUT_STAGE_CONTRADICTION", "Completed lifecycle requires accepted or cancelled.")
        expected = 1 if state == "accepted" else 0
        if int(work_item["acceptance_manifest_count"]) != expected:
            raise WorkItemGovernanceError("PILOT_CLOSEOUT_STAGE_CONTRADICTION", "Acceptance Manifest count contradicts terminal state.")
    if closeout["result"] in {"PASS", "PASS_WITH_GAPS"} and (
        work_item is None or work_item["state"] != "accepted"
    ):
        raise WorkItemGovernanceError("PILOT_CLOSEOUT_RESULT_INVALID", "Successful Pilot closeout requires an accepted Work Item.")
    return closeout


def verify_pilot_event_chain(connection: sqlite3.Connection, lease_id: str) -> dict[str, Any]:
    rows = connection.execute(
        "SELECT * FROM pilot_activation_lease_events WHERE lease_id=? ORDER BY sequence",
        (lease_id,),
    ).fetchall()
    previous: str | None = None
    events: list[dict[str, Any]] = []
    for expected_sequence, row in enumerate(rows, 1):
        event = json.loads(str(row["event_json"]))
        validate_governance_record("pilot_activation_lease_event.v4", event)
        digest_input = dict(event)
        claimed_digest = digest_input.pop("event_digest")
        if (
            int(row["sequence"]) != expected_sequence
            or int(event["sequence"]) != expected_sequence
            or event["previous_event_digest"] != previous
            or canonical_sha256(digest_input) != claimed_digest
            or claimed_digest != row["event_digest"]
            or int(event["state_version_after"]) != int(event["state_version_before"]) + 1
        ):
            raise WorkItemGovernanceError(
                "PILOT_LEASE_EVENT_CHAIN_INVALID",
                "Pilot Lease Event sequence, digest chain, or state version is invalid.",
                details={"sequence": expected_sequence},
            )
        previous = str(claimed_digest)
        events.append(event)
    if len(events) > 64:
        raise WorkItemGovernanceError("PILOT_LEASE_EVENT_CHAIN_INVALID", "Pilot Lease Event chain exceeds 64 Events.")
    return {
        "lease_id": lease_id,
        "event_count": len(events),
        "last_event_digest": previous,
        "verified": True,
        "events": events,
    }
