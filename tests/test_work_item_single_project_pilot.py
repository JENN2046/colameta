from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from runner.mcp_server import MCPPlanningBridgeServer
from runner.work_item_pilot_conformance import (
    capture_pilot_safety_snapshot,
    measure_pilot_safety_conformance,
    measure_pilot_transport_surface,
)
from runner.work_item_governance.canonical import canonical_sha256, sha256_file
from runner.work_item_governance.errors import WorkItemGovernanceError
from runner.work_item_governance.ids import new_stable_id
from runner.work_item_governance.pilot import (
    PILOT_AUTHORIZATION_FROZEN_BINDINGS,
    PILOT_FROZEN_CONTRACT_DIGESTS,
    PILOT_FROZEN_RESOURCE_DIGESTS,
    PILOT_DENIED_WRITES,
    PILOT_SCOPE_MODE,
    PILOT_TOOLS,
    PilotActivationControlPlane,
    build_pilot_semantic_validation_receipt,
    canonical_path_digest,
    verify_pilot_frozen_contract_resources,
    initial_execution_slot_usage,
    validate_execution_authorization_receipt,
    verify_pilot_event_chain,
)
from runner.work_item_governance.pilot_bootstrap import (
    PilotBootstrapPaths,
    bootstrap_fresh_pilot_ledger,
    build_fresh_pilot_preflight_receipt,
)
from runner.work_item_governance.pilot_authorization import (
    ConsumedPilotAuthorization,
    PilotAuthorizationDecisionConsumer,
    consume_pilot_authorization_capability,
    require_consumed_pilot_authorization,
)
from runner.work_item_governance.preview import isoformat_utc, utc_now
from runner.work_item_governance.repository import MIGRATIONS, SQLiteWorkItemLedger
from runner.work_item_governance.schema_loader import (
    load_all_governance_schemas,
    load_governance_contract,
    validate_governance_record,
)


SHA = "a" * 64
NEGATIVE_CASES = load_governance_contract("pilot_negative_test_matrix.v4")["tests"]
DESCRIPTIVE_NEGATIVE_CATEGORIES = frozenset(
    {
        "application_bypass",
        "artifact",
        "authentication",
        "closeout",
        "execution",
        "expiry",
        "fact_reconciliation",
        "generation",
        "git",
        "idempotency",
        "lease",
        "lease_event",
        "lifecycle",
        "maintenance",
        "manifest",
        "one_shot",
        "path",
        "principal",
        "quota",
        "scope",
        "semantic_receipt",
        "storage",
        "surface",
        "task_version",
        "time",
    }
)


def _v6_ledger(root: Path) -> SQLiteWorkItemLedger:
    legacy = SQLiteWorkItemLedger(root)
    legacy.initialize()
    legacy.migrate_to_v6()
    return SQLiteWorkItemLedger(root, target_schema_version=6)


def _consumed_authority(
    monkeypatch: pytest.MonkeyPatch,
    root: Path,
    lease: dict[str, object],
) -> object:
    import runner.work_item_governance.pilot as pilot_module
    import runner.work_item_governance.pilot_authorization as authorization_module

    authorization = {
        "gate_id": lease["authorization_id"],
        "bindings": {"candidate_manifest_sha256": SHA},
        "target": {
            "bind_address": lease["runtime_binding"]["bind_address"],
            "port": lease["runtime_binding"]["port"],
            "exposure_profile": lease["runtime_binding"]["exposure_profile"],
            "scope_mode": lease["runtime_binding"]["scope_mode"],
        },
    }
    ledger = SQLiteWorkItemLedger(root, target_schema_version=6)
    origin = {"kind": "manual", "ref": "synthetic://pilot-test", "snapshot_digest": SHA}
    artifact_policy = {"policy": "pilot-test"}
    scope: dict[str, object] = {
        "source_binding": dict(lease["source_binding"]),
        "target_project": {
            "project_id": lease["scope_binding"]["project_id"],
            "project_root": str(root.resolve()),
            "project_snapshot_digest": SHA,
            "protected_path_manifest_digest": SHA,
            "allowed_write_path_manifest_digest": SHA,
        },
        "pilot_isolation": {
            "pilot_root": str(root.resolve()),
            "ledger_path_digest": canonical_path_digest(ledger.path),
        },
        "principal_binding": dict(lease["principal_binding"]),
        "work_item_scope": {
            "proposed_work_item_id": lease["scope_binding"]["proposed_work_item_id"],
            "authorized_work_item_id": None,
            "origin": origin,
            "authorized_create_command_digest": lease["scope_binding"]["authorized_create_command_digest"],
            "objective_digest": lease["scope_binding"]["objective_digest"],
            "task_version_payload_digests": lease["scope_binding"]["task_version_payload_digests"],
        },
        "execution_scope": {
            "attempt_slot_schema_sha256": lease["scope_binding"]["execution_attempt_slot_schema_sha256"],
            "authorization_receipt_schema_sha256": lease["scope_binding"]["execution_authorization_receipt_schema_sha256"],
            "authorization_receipt_digest": lease["scope_binding"]["execution_authorization_receipt_digest"],
        },
        "artifact_policy": artifact_policy,
        "window": dict(lease["window"]),
        "quotas": dict(lease["quotas"]),
    }
    execution = _receipt(str(lease["scope_binding"]["proposed_work_item_id"]))
    generation = ledger.database_generation()
    preflight: dict[str, object] = {
        "execution_context": {},
        "observed_at": lease["runtime_binding"]["preflight_observed_at"],
        "valid_until": lease["runtime_binding"]["preflight_valid_until"],
        "isolation": {"pilot_root": str(root.resolve()), "token_file_path": str((root / "auth.json").resolve())},
        "project": {"project_root": str(root.resolve())},
        "ledger": {"schema_version": 6, "database_generation": generation, "path_digest": canonical_path_digest(ledger.path)},
        "backup": {"database_generation": generation, "receipt_digest": SHA, "sha256": SHA},
    }
    monkeypatch.setattr(authorization_module, "validate_pilot_scope_envelope", lambda *args, **kwargs: args[0])
    monkeypatch.setattr(authorization_module, "validate_pilot_preflight", lambda value: value)
    monkeypatch.setattr(authorization_module, "validate_pilot_authorization", lambda value, **kwargs: value)
    monkeypatch.setattr(authorization_module, "validate_pilot_authority_chain", lambda *args, **kwargs: None)
    monkeypatch.setattr(pilot_module, "validate_pilot_scope_envelope", lambda *args, **kwargs: args[0])
    monkeypatch.setattr(pilot_module, "validate_pilot_preflight", lambda value: value)
    monkeypatch.setattr(pilot_module, "validate_pilot_authorization", lambda value, **kwargs: value)
    monkeypatch.setattr(pilot_module, "validate_pilot_authority_chain", lambda *args, **kwargs: None)
    auth_dir = root / "authority"
    auth_dir.mkdir(mode=0o700, exist_ok=True)
    decision_path = auth_dir / "decision.json"
    tombstone_path = auth_dir / "decision.tombstone.json"
    decision_path.write_text(json.dumps(authorization), encoding="utf-8")
    decision_path.chmod(0o600)
    lease["authorization_digest"] = canonical_sha256(authorization)
    lease["scope_binding"]["execution_authorization_receipt_digest"] = canonical_sha256(execution)
    scope["execution_scope"]["authorization_receipt_digest"] = canonical_sha256(execution)
    lease["scope_binding"]["origin_digest"] = canonical_sha256(origin)
    lease["scope_binding"]["artifact_policy_digest"] = canonical_sha256(artifact_policy)
    lease["runtime_binding"]["preflight_receipt_digest"] = canonical_sha256(preflight)
    lease["runtime_binding"]["pilot_root_path_digest"] = canonical_path_digest(root)
    lease["runtime_binding"]["project_root_path_digest"] = canonical_path_digest(root)
    lease["runtime_binding"]["ledger_path_digest"] = canonical_path_digest(ledger.path)
    lease["runtime_binding"]["token_file_path_digest"] = canonical_path_digest(root / "auth.json")
    lease["runtime_binding"]["database_generation"] = generation
    lease["runtime_binding"]["backup_receipt_digest"] = SHA
    lease["runtime_binding"]["backup_sha256"] = SHA
    lease["scope_envelope_digest"] = canonical_sha256(scope)
    for field, digest in PILOT_FROZEN_CONTRACT_DIGESTS.items():
        lease[field] = digest
    return PilotAuthorizationDecisionConsumer(
        decision_path=decision_path,
        tombstone_path=tombstone_path,
        ledger=ledger,
    ).consume(
        scope_envelope=scope,
        execution_authorization_receipt=execution,
        preflight_receipt=preflight,
        authentication_conformance_receipt={},
        preflight_semantic_validation_receipt={},
        expected_authorization_digest=canonical_sha256(authorization),
    )


def _receipt(work_item_id: str, *, payloads: tuple[str, ...] = ("b" * 64, "c" * 64)) -> dict[str, object]:
    now = utc_now()
    slots = [
        {
            "slot_id": f"exec_slot_slot_{index:08d}",
            "ordinal": index,
            "task_version": index,
            "task_version_payload_digest": payload,
            "objective_digest": canonical_sha256(f"objective-{index}"),
            "attempt_binding_mode": "bind_after_atomic_create",
            "attempt_id": None,
            "retry_of_slot_id": None,
            "maximum_attempt_runtime_seconds": 600,
        }
        for index, payload in enumerate(payloads, 1)
    ]
    return {
        "schema_version": "wig_p3_pilot_execution_authorization_receipt.v2",
        "authorization_id": "exec_auth_pilot_test_0001",
        "decision": "AUTHORIZED",
        "issued_at": isoformat_utc(now),
        "not_before": isoformat_utc(now),
        "expires_at": isoformat_utc(now + timedelta(hours=4)),
        "issuer": {
            "principal_id": "pilot-reviewer",
            "principal_kind": "human",
            "authority_basis": "pilot.external_execution.authorize",
            "decision_digest": SHA,
        },
        "scope": {
            "project_id": "pilot-project",
            "project_snapshot_digest": SHA,
            "work_item_id": work_item_id,
            "attempt_slot_schema_sha256": SHA,
            "attempt_slots": slots,
            "executor_identity": "pilot-executor",
            "allowed_read_path_manifest_digest": SHA,
            "allowed_write_path_manifest_digest": SHA,
            "protected_path_manifest_digest": SHA,
        },
        "one_shot": {
            "maximum_attempts": len(slots),
            "consumption_key": "pilot-consumption-key-0001",
            "retry_requires_next_authorized_slot": True,
            "revocation_check_required": True,
        },
        "authority": {
            "create_runtime_attempt": True,
            "dispatch_exact_attempt": True,
            "historical_binding": False,
            "delivery": False,
            "push": False,
            "stable_promotion": False,
        },
    }


def _lease(work_item_id: str) -> dict[str, object]:
    now = utc_now()
    receipt = _receipt(work_item_id)
    usage = {
        "new_work_items": 0,
        "task_versions": 0,
        "runtime_attempts": 0,
        "attempt_events": 0,
        "artifacts": 0,
        "decisions": 0,
        "applied_gate_events": 0,
        "rejected_gate_events": 0,
        "gate_events_total": 0,
        "audit_events": 0,
        "outbox_events": 0,
        "acceptance_manifests": 0,
        "lease_events": 1,
        "execution_slots": initial_execution_slot_usage(receipt),
    }
    quotas = {
        "maximum_new_work_items": 1,
        "maximum_task_versions": 3,
        "maximum_runtime_attempts": 4,
        "maximum_attempt_events": 8,
        "maximum_artifacts": 12,
        "maximum_decisions": 8,
        "maximum_applied_gate_events": 10,
        "maximum_rejected_gate_events": 10,
        "maximum_gate_events_total": 20,
        "maximum_audit_events": 20,
        "maximum_outbox_events": 20,
        "maximum_acceptance_manifests": 1,
        "maximum_lease_events": 64,
    }
    return {
        "schema_version": "wig_p3_bounded_single_project_pilot_activation_lease.v4",
        "lease_id": new_stable_id("activation_lease"),
        "authorization_id": "WIG-P3-AUTHORITATIVE-SINGLE-PROJECT-PILOT-TEST",
        "authorization_digest": SHA,
        "scope_envelope_digest": SHA,
        "spec_manifest_digest": SHA,
        "storage_schema_contract_digest": SHA,
        "fact_reconciliation_contract_digest": SHA,
        "semantic_rules_digest": SHA,
        "tool_allowlist_digest": SHA,
        "write_matrix_digest": SHA,
        "execution_attempt_slot_schema_sha256": SHA,
        "execution_authorization_receipt_schema_sha256": SHA,
        "authentication_conformance_receipt_schema_sha256": SHA,
        "expiry_conformance_receipt_schema_sha256": SHA,
        "source_binding": {
            "implementation_commit": "1" * 40,
            "implementation_tree": "2" * 40,
            "wheel_sha256": SHA,
            "installed_inventory_sha256": SHA,
        },
        "runtime_binding": {
            "instance_id": "pilot-instance",
            "runtime_instance_nonce": "n" * 32,
            "expected_process_identity": SHA,
            "claimed_process_identity": None,
            "listener_attested_at": None,
            "listener_attestation_digest": None,
            "request_context_binding_digest": None,
            "bind_address": "127.0.0.1",
            "port": 8799,
            "exposure_profile": "authoritative_canary",
            "scope_mode": PILOT_SCOPE_MODE,
            "pilot_root_path_digest": SHA,
            "project_root_path_digest": SHA,
            "ledger_path_digest": SHA,
            "token_file_path_digest": SHA,
            "database_generation": 1,
            "preflight_receipt_digest": SHA,
            "preflight_observed_at": isoformat_utc(now),
            "preflight_valid_until": isoformat_utc(now + timedelta(seconds=120)),
            "backup_receipt_digest": SHA,
            "backup_sha256": SHA,
            "monotonic_claim_ns": None,
            "monotonic_deadline_ns": None,
        },
        "principal_binding": {
            "principal_id": "pilot-operator",
            "principal_kind": "human",
            "session_ref": "pilot-session",
            "caller_auth_mode": "token",
            "principal_authenticated_by": "local_session",
            "permissions": [
                "work_item.accept",
                "work_item.approve",
                "work_item.cancel",
                "work_item.ready",
                "work_item.return_for_revision",
                "work_item.start_delivery",
                "work_item.submit",
            ],
            "combined_operator_reviewer_role_explicitly_authorized": True,
        },
        "scope_binding": {
            "project_id": "pilot-project",
            "project_snapshot_digest": SHA,
            "proposed_work_item_id": work_item_id,
            "authorized_work_item_id": None,
            "origin_digest": SHA,
            "authorized_create_command_digest": SHA,
            "objective_digest": SHA,
            "task_version_payload_digests": ["b" * 64, "c" * 64],
            "execution_attempt_slot_schema_sha256": SHA,
            "execution_authorization_receipt_schema_sha256": SHA,
            "execution_authorization_receipt_digest": canonical_sha256(receipt),
            "artifact_policy_digest": SHA,
            "protected_path_manifest_digest": SHA,
            "allowed_write_path_manifest_digest": SHA,
        },
        "window": {
            "issued_at": isoformat_utc(now),
            "not_before": isoformat_utc(now),
            "expires_at": isoformat_utc(now + timedelta(hours=4)),
            "maximum_runtime_seconds": 14400,
            "maximum_preflight_age_seconds": 120,
        },
        "quotas": quotas,
        "usage": usage,
        "policy": {
            "transaction_mode": "BEGIN_IMMEDIATE",
            "atomic_first_work_item_binding": True,
            "idempotent_replay_charges_quota": False,
            "exact_replay_writes_lease_event": False,
            "actual_fact_reconciliation": True,
            "unknown_command": "deny",
            "direct_service_bypass": "deny_without_exact_lease_and_request_context",
            "expiry_without_watchdog": "fail_closed",
        },
        "maintenance": {
            "restore": "deny_while_nonterminal",
            "migration": "deny_after_prepared",
            "backup": "control_plane_only",
            "delivery": "deny",
            "outbox_dispatch": "deny",
            "stable_promotion": "deny",
            "push": "deny",
        },
        "failure_behavior": {
            "reject_domain_transaction": True,
            "freeze_authoritative_writes": True,
            "preserve_append_only_evidence": True,
            "restore_shadow_on_closeout": True,
            "automatic_retry": False,
        },
        "status": "prepared",
        "state_version": 1,
        "created_at": isoformat_utc(now),
        "updated_at": isoformat_utc(now),
    }


def test_schema_v6_is_explicit_and_preserves_v5_tables(tmp_path: Path) -> None:
    legacy = SQLiteWorkItemLedger(tmp_path)
    legacy.initialize()
    assert legacy.schema_version() == 5
    with sqlite3.connect(legacy.path) as connection:
        before = {
            name: connection.execute(
                "SELECT sql FROM sqlite_schema WHERE type='table' AND name=?", (name,)
            ).fetchone()[0]
            for name in ("activation_leases", "activation_lease_events")
        }
    legacy.migrate_to_v6()
    pilot = SQLiteWorkItemLedger(tmp_path, target_schema_version=6)
    assert pilot.schema_version() == 6
    with sqlite3.connect(pilot.path) as connection:
        after = {
            name: connection.execute(
                "SELECT sql FROM sqlite_schema WHERE type='table' AND name=?", (name,)
            ).fetchone()[0]
            for name in before
        }
        assert after == before
        assert connection.execute("SELECT COUNT(*) FROM pilot_activation_leases").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM pilot_activation_lease_events").fetchone()[0] == 0


def test_exclusive_migration_receipt_binds_legacy_history(tmp_path: Path) -> None:
    ledger = SQLiteWorkItemLedger(tmp_path)
    ledger.initialize()
    receipt = ledger.migrate_to_v6()
    assert receipt["from_schema_version"] == 5
    assert receipt["to_schema_version"] == 6
    assert receipt["maintenance_lock"] == "exclusive"
    assert receipt["legacy_table_digests_unchanged"] is True
    assert receipt["legacy_before"] == receipt["legacy_after"]


def test_schema_v6_rejects_nonterminal_legacy_lease(tmp_path: Path) -> None:
    ledger = SQLiteWorkItemLedger(tmp_path)
    ledger.initialize()
    with sqlite3.connect(ledger.path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        # A minimal row is generated from the accepted v5 helper path in a separate
        # test suite; here the precondition is exercised without bypassing constraints.
        connection.execute("DROP TABLE activation_lease_events")
        connection.execute("DROP TABLE activation_leases")
        connection.execute("CREATE TABLE activation_leases(lease_id TEXT,status TEXT)")
        connection.execute("CREATE TABLE activation_lease_events(event_id TEXT)")
        connection.execute("INSERT INTO activation_leases VALUES('legacy','active')")
        connection.commit()
    with pytest.raises(WorkItemGovernanceError) as error:
        ledger.migrate_to_v6()
    assert error.value.code == "PILOT_MIGRATION_LEGACY_LEASE_NONTERMINAL"
    with sqlite3.connect(ledger.path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 5
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_schema WHERE name='pilot_activation_leases'"
        ).fetchone()[0] == 0


def test_schema_v6_failure_rolls_back_all_schema_and_version_state(tmp_path: Path) -> None:
    legacy = SQLiteWorkItemLedger(tmp_path)
    legacy.initialize()
    broken = {
        **MIGRATIONS,
        6: (
            "CREATE TABLE pilot_activation_leases(lease_id TEXT PRIMARY KEY)",
            "THIS IS NOT VALID SQL",
        ),
    }
    with pytest.raises(WorkItemGovernanceError) as error:
        SQLiteWorkItemLedger(
            tmp_path,
            migrations=broken,
        ).migrate_to_v6()
    assert error.value.code == "LEDGER_MIGRATION_FAILED"
    with sqlite3.connect(legacy.path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 5
        assert connection.execute("SELECT value FROM ledger_meta WHERE key='schema_version'").fetchone()[0] == "5"
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_schema WHERE name='pilot_activation_leases'"
        ).fetchone()[0] == 0


def test_schema_v6_postcondition_failure_rolls_back_version_and_ddl(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = SQLiteWorkItemLedger(tmp_path)
    ledger.initialize()
    original = ledger._legacy_activation_history_digest
    calls = 0

    def changed_after(connection: sqlite3.Connection) -> dict[str, object]:
        nonlocal calls
        calls += 1
        result = original(connection)
        if calls == 2:
            result = {**result, "aggregate_sha256": "f" * 64}
        return result

    monkeypatch.setattr(ledger, "_legacy_activation_history_digest", changed_after)
    with pytest.raises(WorkItemGovernanceError) as error:
        ledger.migrate_to_v6()
    assert error.value.code == "PILOT_MIGRATION_POSTCONDITION_FAILED"
    with sqlite3.connect(ledger.path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 5
        assert connection.execute("SELECT value FROM ledger_meta WHERE key='schema_version'").fetchone()[0] == "5"
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_schema WHERE name='pilot_activation_leases'"
        ).fetchone()[0] == 0


def test_generic_initialize_cannot_implicitly_cross_v5_to_v6(tmp_path: Path) -> None:
    SQLiteWorkItemLedger(tmp_path).initialize()
    with pytest.raises(WorkItemGovernanceError) as error:
        SQLiteWorkItemLedger(tmp_path, target_schema_version=6).initialize()
    assert error.value.code == "PILOT_EXPLICIT_MIGRATION_REQUIRED"


def test_empty_ledger_cannot_implicitly_initialize_directly_to_v6(tmp_path: Path) -> None:
    with pytest.raises(WorkItemGovernanceError) as error:
        SQLiteWorkItemLedger(tmp_path, target_schema_version=6).initialize()
    assert error.value.code == "PILOT_EXPLICIT_MIGRATION_REQUIRED"
    with sqlite3.connect(tmp_path / ".colameta/ledger/work-items.sqlite3") as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 0


def test_multi_version_execution_receipt_and_retry_rules() -> None:
    work_item_id = new_stable_id("work_item")
    receipt = _receipt(work_item_id)
    assert validate_execution_authorization_receipt(receipt) is receipt
    slots = initial_execution_slot_usage(receipt)
    assert [slot["task_version"] for slot in slots] == [1, 2]
    assert all(slot["status"] == "available" and slot["attempt_id"] is None for slot in slots)
    invalid = json.loads(json.dumps(receipt))
    invalid["scope"]["attempt_slots"][1]["retry_of_slot_id"] = "exec_slot_unknown_0001"
    with pytest.raises(WorkItemGovernanceError) as error:
        validate_execution_authorization_receipt(invalid)
    assert error.value.code == "PILOT_EXECUTION_SLOT_RETRY_INVALID"


def test_pilot_control_plane_issues_append_only_v4_lease(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ledger = _v6_ledger(tmp_path)
    lease = _lease(new_stable_id("work_item"))
    PilotActivationControlPlane(ledger).prepare_lease(lease, authority=_consumed_authority(monkeypatch, tmp_path, lease))
    with ledger.read_connection() as connection:
        row = connection.execute("SELECT * FROM pilot_activation_leases").fetchone()
        event = connection.execute("SELECT * FROM pilot_activation_lease_events").fetchone()
        assert row["schema_version"].endswith(".v4")
        assert event["sequence"] == 1
        assert event["event_type"] == "lease_issued"
    with sqlite3.connect(ledger.path) as connection:
        with pytest.raises(sqlite3.DatabaseError):
            connection.execute("UPDATE pilot_activation_lease_events SET event_type='lease_closed'")


def test_pilot_lease_prepare_rejects_missing_or_fabricated_authority(tmp_path: Path) -> None:
    ledger = _v6_ledger(tmp_path)
    control = PilotActivationControlPlane(ledger)
    lease = _lease(new_stable_id("work_item"))
    with pytest.raises(WorkItemGovernanceError) as missing:
        control.prepare_lease(lease, authority=None)
    assert missing.value.code == "PILOT_AUTHORIZATION_CAPABILITY_INVALID"
    with pytest.raises(WorkItemGovernanceError) as fabricated:
        control.prepare_lease(lease, authority={"decision": "CONSUMED"})
    assert fabricated.value.code == "PILOT_AUTHORIZATION_CAPABILITY_INVALID"
    with ledger.read_connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM pilot_activation_leases").fetchone()[0] == 0


def test_private_runtime_transition_cannot_be_called_without_verified_capability(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = _v6_ledger(tmp_path)
    lease = _lease(new_stable_id("work_item"))
    control = PilotActivationControlPlane(ledger)
    control.prepare_lease(lease, authority=_consumed_authority(monkeypatch, tmp_path, lease))
    with pytest.raises(WorkItemGovernanceError) as error:
        control._transition_runtime(
            lease["lease_id"],
            event_type="process_claimed",
            process_identity_digest=SHA,
        )
    assert error.value.code == "PILOT_RUNTIME_TRANSITION_CAPABILITY_INVALID"


def test_pilot_control_plane_event_chain_and_terminal_close(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from runner.work_item_governance.activation import process_identity_inputs

    ledger = _v6_ledger(tmp_path)
    lease = _lease(new_stable_id("work_item"))
    lease["runtime_binding"]["expected_process_identity"] = process_identity_inputs(str(tmp_path))[
        "expected_process_identity"
    ]
    control = PilotActivationControlPlane(ledger)
    control.prepare_lease(lease, authority=_consumed_authority(monkeypatch, tmp_path, lease))
    control.claim_prepared_lease(
        lease_id=lease["lease_id"],
        envelope_path=str(tmp_path / "lease.json"),
        claimed_envelope_path=str(tmp_path / "lease.claimed.json"),
    )
    control.attest_listener(
        lease_id=lease["lease_id"],
        bind_address="127.0.0.1",
        port=8799,
        observed_listeners=[{"address": "127.0.0.1", "port": 8799}],
    )
    closed = control.close(lease_id=lease["lease_id"], reason="test_complete")
    assert closed["status"] == "closed"
    assert closed["usage"]["lease_events"] == 4
    with ledger.read_connection() as connection:
        events = connection.execute(
            "SELECT sequence,event_type,previous_event_digest,event_digest FROM pilot_activation_lease_events ORDER BY sequence"
        ).fetchall()
        verified = verify_pilot_event_chain(connection, lease["lease_id"])
    assert verified["verified"] is True
    assert verified["event_count"] == 4
    assert [row["event_type"] for row in events] == [
        "lease_issued",
        "process_claimed",
        "listener_attested",
        "lease_closed",
    ]
    assert [row["sequence"] for row in events] == [1, 2, 3, 4]
    assert events[0]["previous_event_digest"] is None
    assert all(events[index]["previous_event_digest"] == events[index - 1]["event_digest"] for index in range(1, 4))


def test_v6_raw_repository_write_and_maintenance_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ledger = _v6_ledger(tmp_path)
    lease = _lease(new_stable_id("work_item"))
    PilotActivationControlPlane(ledger).prepare_lease(lease, authority=_consumed_authority(monkeypatch, tmp_path, lease))
    with pytest.raises(WorkItemGovernanceError) as error:
        with ledger.write_transaction() as connection:
            connection.execute("INSERT INTO ledger_meta(key,value,updated_at) VALUES('raw','x','2026-01-01T00:00:00Z')")
    assert error.value.code == "ACTIVATION_REPOSITORY_WRITE_DENIED"


def test_pilot_controller_capability_rejects_subclass_and_direct_service_bypass(tmp_path: Path) -> None:
    ledger = _v6_ledger(tmp_path)

    class FakePilotControl(PilotActivationControlPlane):
        pass

    fake = object.__new__(FakePilotControl)
    fake.ledger = ledger
    with pytest.raises(WorkItemGovernanceError) as error:
        ledger._bind_activation_controller(fake)
    assert error.value.code == "ACTIVATION_CONTROLLER_BINDING_INVALID"

    with ledger.write_transaction() as connection:
        connection.execute(
            "INSERT INTO ledger_meta(key,value,updated_at) VALUES('preview_signing_key',?,'2026-01-01T00:00:00Z')",
            ("1" * 64,),
        )

    from runner.work_item_governance.service import WorkItemApplicationService

    service = WorkItemApplicationService(
        tmp_path,
        enabled=True,
        authoritative_transitions=True,
        bounded_single_project_pilot=True,
        ledger=ledger,
    )
    with pytest.raises(WorkItemGovernanceError) as missing:
        service.preview_work_item_create(
            {
                "origin": {"kind": "manual", "ref": "pilot", "snapshot_digest": SHA},
                "objective": "pilot",
            }
        )
    assert missing.value.code == "PILOT_ACTIVATION_LEASE_REQUIRED"


def test_pilot_mcp_surface_is_exact_and_default_deny(tmp_path: Path) -> None:
    server = MCPPlanningBridgeServer(
        str(tmp_path),
        exposure_profile="authoritative_canary",
        work_item_scope_mode=PILOT_SCOPE_MODE,
    )
    assert tuple(server._visible_tool_names()) == PILOT_TOOLS
    assert len(server._visible_tool_names()) == 14
    assert "list_outbox_events" not in server._visible_tool_names()
    assert "manage_git" not in server._visible_tool_names()


def test_frozen_storage_contract_matches_runtime_ddl() -> None:
    verify_pilot_frozen_contract_resources()
    assert PILOT_FROZEN_CONTRACT_DIGESTS["spec_manifest_digest"] == canonical_sha256(
        PILOT_FROZEN_RESOURCE_DIGESTS
    )
    contract = load_governance_contract("pilot_storage_schema_v6.v2")
    assert contract["migration"]["from_schema_version"] == 5
    assert contract["migration"]["to_schema_version"] == 6
    assert set(contract["new_tables"]) == {
        "pilot_activation_leases",
        "pilot_activation_lease_events",
    }
    negative = load_governance_contract("pilot_negative_test_matrix.v4")
    assert len(negative["tests"]) == 96
    assert len({item["id"] for item in negative["tests"]}) == 96
    assert all(isinstance(item["expected"], str) and item["expected"] for item in negative["tests"])


def test_authorization_binding_contract_has_no_unclassified_fields() -> None:
    required = set(load_all_governance_schemas()["pilot_authorization.v4"]["properties"]["bindings"]["required"])
    dynamic = {
        "candidate_manifest_sha256",
        "file_list_root_sha256",
        "scope_envelope_sha256",
        "authorized_scope_digest",
        "project_snapshot_digest",
        "execution_authorization_receipt_digest",
        "authentication_conformance_receipt_digest",
    }
    assert set(PILOT_AUTHORIZATION_FROZEN_BINDINGS) | dynamic == required


def test_semantic_receipt_uses_exact_applicable_rules_and_rejects_nonapplicable_failure() -> None:
    bindings = {
        "candidate_manifest_sha256": SHA,
        "scope_envelope_digest": SHA,
        "storage_schema_contract_digest": PILOT_FROZEN_CONTRACT_DIGESTS["storage_schema_contract_digest"],
        "fact_reconciliation_contract_digest": PILOT_FROZEN_CONTRACT_DIGESTS["fact_reconciliation_contract_digest"],
        "authorization_digest": SHA,
        "project_snapshot_digest": SHA,
        "runtime_binding_digest": SHA,
        "ledger_state_digest": SHA,
    }
    receipt = build_pilot_semantic_validation_receipt(stage="lease_prepare", input_bindings=bindings)
    assert receipt["result"] == "PASS"
    assert set(receipt["passed_rule_ids"]) == set(receipt["applicable_rule_ids"])
    assert len(receipt["applicable_rule_ids"]) == 14
    with pytest.raises(WorkItemGovernanceError) as error:
        build_pilot_semantic_validation_receipt(
            stage="lease_prepare",
            input_bindings=bindings,
            failed_rules=[{"rule_id": "ART-001", "error_code": "PILOT_ARTIFACT_POLICY_VIOLATION", "evidence_digest": SHA}],
        )
    assert error.value.code == "PILOT_SEMANTIC_RECEIPT_INVALID"


@pytest.mark.parametrize("case", NEGATIVE_CASES, ids=[item["id"] for item in NEGATIVE_CASES])
def test_every_frozen_negative_scenario_has_executable_semantic_or_boundary_mapping(
    case: dict[str, object],
) -> None:
    """Execute all 96 matrix rows; unknown codes/categories fail closed."""

    rules = load_governance_contract("pilot_semantic_rules.v4")["rules"]
    rules_by_error = {rule["error_code"]: rule for rule in rules}
    expected = str(case["expected"])
    error_codes = re.findall(r"PILOT_[A-Z0-9_]+", expected)
    if error_codes:
        for error_code in error_codes:
            rule = rules_by_error.get(error_code)
            assert rule is not None, f"{case['id']} names an error absent from the frozen semantic rules"
            stage = rule["stages"][0]
            bindings = {
                "candidate_manifest_sha256": SHA,
                "scope_envelope_digest": SHA,
                "storage_schema_contract_digest": PILOT_FROZEN_CONTRACT_DIGESTS["storage_schema_contract_digest"],
                "fact_reconciliation_contract_digest": PILOT_FROZEN_CONTRACT_DIGESTS["fact_reconciliation_contract_digest"],
                "authorization_digest": SHA,
                "project_snapshot_digest": SHA,
                "runtime_binding_digest": SHA,
                "ledger_state_digest": SHA,
            }
            receipt = build_pilot_semantic_validation_receipt(
                stage=stage,
                input_bindings=bindings,
                failed_rules=[
                    {
                        "rule_id": rule["id"],
                        "error_code": error_code,
                        "evidence_digest": canonical_sha256(case),
                    }
                ],
            )
            assert receipt["result"] == "FAIL"
            assert receipt["failed_rules"][0]["error_code"] == error_code
        return
    assert case["category"] in DESCRIPTIVE_NEGATIVE_CATEGORIES
    assert str(case["scenario"]).strip()
    assert expected.strip()
    if case["category"] == "surface":
        assert len(PILOT_TOOLS) == 14
    elif case["category"] == "maintenance":
        assert set(PILOT_DENIED_WRITES).issuperset(
            {"create_delivery_receipt", "record_outbox_delivery_result"}
        )
    elif case["category"] in {"storage", "generation"}:
        storage = load_governance_contract("pilot_storage_schema_v6.v2")
        assert storage["migration"]["from_schema_version"] == 5
        assert storage["migration"]["to_schema_version"] == 6
        assert storage["migration"]["direction"] == "forward_only"
        assert storage["migration"]["transactional"] is True
        assert storage["migration"]["failure_rolls_back_schema_version"] is True
    else:
        category_prefix = {
            "artifact": "ART-",
            "authentication": "AUTH-",
            "closeout": "CLOSE-",
            "execution": "EXEC-",
            "expiry": "TIME-",
            "fact_reconciliation": "LEASE-",
            "git": "GIT-",
            "idempotency": "LEASE-",
            "lease": "LEASE-",
            "lease_event": "EVENT-",
            "lifecycle": "SCOPE-",
            "manifest": "ART-",
            "one_shot": "AUTH-",
            "path": "PATH-",
            "principal": "ROLE-",
            "quota": "LEASE-",
            "scope": "SCOPE-",
            "semantic_receipt": "VALID-",
            "task_version": "SCOPE-",
            "time": "TIME-",
            "application_bypass": "AUTH-",
        }.get(str(case["category"]))
        assert category_prefix is not None
        assert any(str(rule["id"]).startswith(category_prefix) for rule in rules)


def test_fresh_pilot_bootstrap_is_shadow_zero_fact_and_generation_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import runner.work_item_governance.pilot_bootstrap as bootstrap_module

    root = tmp_path / "pilot"
    project = tmp_path / "project"
    paths = PilotBootstrapPaths(
        pilot_root=root,
        project_root=project,
        home=root / "home",
        xdg_config_home=root / "xdg-config",
        xdg_state_home=root / "xdg-state",
        xdg_cache_home=root / "xdg-cache",
        xdg_data_home=root / "xdg-data",
        registry_path=root / "xdg-config/colameta/project-registry.json",
        token_file=root / "xdg-config/colameta/auth.json",
        backup_path=root / "evidence/pre-activation.sqlite3",
    )
    project.mkdir()
    subprocess.run(["git", "-C", str(project), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(project), "config", "user.email", "pilot@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(project), "config", "user.name", "Pilot Test"], check=True)
    (project / ".gitignore").write_text(".colameta/\n", encoding="utf-8")
    fixture = project / "fixture.txt"
    fixture.write_text("pilot\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(project), "add", ".gitignore", "fixture.txt"], check=True)
    subprocess.run(["git", "-C", str(project), "commit", "-qm", "pilot fixture"], check=True)
    head = subprocess.run(
        ["git", "-C", str(project), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    tree = subprocess.run(
        ["git", "-C", str(project), "rev-parse", "HEAD^{tree}"], check=True, capture_output=True, text=True
    ).stdout.strip()
    index = subprocess.run(
        ["git", "-C", str(project), "ls-files", "--stage", "-z"], check=True, capture_output=True, text=True
    ).stdout.rstrip("\n")
    wheel = root / "artifacts/colameta-test.whl"
    wheel.parent.mkdir(parents=True, mode=0o700)
    wheel.write_bytes(b"reviewed wheel fixture")

    class FakeAttestation:
        source_binding = {
            "core_baseline_commit": "53d8939af22b019b2df2b555b85869ac39c5bba2",
            "implementation_commit": head,
            "implementation_tree": tree,
            "wheel_sha256": sha256_file(wheel),
        }
        checkout_root = project.resolve()
        wheel_artifact = wheel.resolve()
        evidence_digest = canonical_sha256({"fixture": "source-evidence"})
        file_manifest_digest = canonical_sha256({"fixture": "installed-inventory"})

        @staticmethod
        def require_trusted() -> None:
            return None

    attestation = FakeAttestation()
    monkeypatch.setattr(bootstrap_module, "verify_runtime_source_artifacts", lambda **_kwargs: attestation)
    receipt = bootstrap_fresh_pilot_ledger(
        paths=paths,
        port=48791,
        source_checkout=project,
        wheel_artifact=wheel,
    )
    assert receipt["database_generation"] == receipt["backup"]["database_generation"] == 1
    assert receipt["backup"]["schema_version"] == 6
    assert receipt["backup"]["mode"] == "0600"
    assert not any(receipt["zero_fact_baseline"].values())
    assert receipt["runtime"]["gate_mode"] == "shadow"
    assert receipt["runtime"]["authoritative"] is False
    paths.registry_path.parent.mkdir(parents=True, exist_ok=True)
    paths.registry_path.write_text(
        json.dumps({"schema_version": 1, "projects": [{"project_id": "pilot-project", "project_root": str(project)}]}),
        encoding="utf-8",
    )
    paths.registry_path.chmod(0o600)
    protected_manifest = {"paths": [{"path": "fixture.txt", "sha256": sha256_file(fixture)}]}
    read_manifest = {"paths": ["fixture.txt"]}
    write_manifest = {"paths": ["output"]}
    manifest_digests = {
        "protected": canonical_sha256(protected_manifest),
        "allowed_read": canonical_sha256(read_manifest),
        "allowed_write": canonical_sha256(write_manifest),
    }
    source_binding = {
        "implementation_commit": head,
        "implementation_tree": tree,
        "wheel_sha256": attestation.source_binding["wheel_sha256"],
        "installed_inventory_sha256": attestation.file_manifest_digest,
    }
    execution_context = {
        **source_binding,
        "python_executable": str(Path(sys.executable).resolve()),
        "cwd": str(project.resolve()),
    }
    execution_context["runtime_binding_digest"] = canonical_sha256(execution_context)
    snapshot_record = {
        "project_id": "pilot-project",
        "project_root_path_digest": canonical_path_digest(project),
        "head_commit": head,
        "head_tree": tree,
        "tracked_changes_digest": canonical_sha256(""),
        "untracked_changes_digest": canonical_sha256(""),
        "index_digest": canonical_sha256(index),
        "protected_assets_digest": manifest_digests["protected"],
        "protected_path_manifest_digest": manifest_digests["protected"],
        "allowed_read_path_manifest_digest": manifest_digests["allowed_read"],
        "allowed_write_path_manifest_digest": manifest_digests["allowed_write"],
    }
    measured_project = {
        "project_id": "pilot-project",
        "project_root": str(project),
        "registry_project_count": 1,
        "snapshot_digest": canonical_sha256(snapshot_record),
        "head_commit": head,
        "head_tree": tree,
        "index_digest": canonical_sha256(index),
        "protected_path_manifest_digest": manifest_digests["protected"],
        "allowed_read_path_manifest_digest": manifest_digests["allowed_read"],
        "allowed_write_path_manifest_digest": manifest_digests["allowed_write"],
        "ledger_git_ignored": True,
        "ledger_not_tracked": True,
        "ledger_not_staged": True,
        "root_override_disabled": True,
    }
    ledger_state = {
        "path_digest": receipt["ledger_path_digest"],
        "schema_version": 6,
        "database_generation": receipt["database_generation"],
        "zero_fact_baseline": receipt["zero_fact_baseline"],
        "integrity_check": "ok",
        "foreign_key_violations": [],
        "token_evidence_digest": receipt["token_evidence_digest"],
        "source_artifact_evidence_digest": attestation.evidence_digest,
    }
    authorization_digest = canonical_sha256({})
    bindings = {
        "authorization_digest": authorization_digest,
        "scope_envelope_digest": SHA,
        "candidate_manifest_sha256": SHA,
        "file_list_root_sha256": SHA,
        "storage_schema_contract_digest": PILOT_FROZEN_CONTRACT_DIGESTS["storage_schema_contract_digest"],
        "fact_reconciliation_contract_digest": PILOT_FROZEN_CONTRACT_DIGESTS["fact_reconciliation_contract_digest"],
        "semantic_rules_digest": PILOT_FROZEN_CONTRACT_DIGESTS["semantic_rules_digest"],
        "project_snapshot_digest": measured_project["snapshot_digest"],
        "execution_attempt_slot_schema_sha256": PILOT_FROZEN_CONTRACT_DIGESTS["execution_attempt_slot_schema_sha256"],
        "execution_authorization_receipt_schema_sha256": PILOT_FROZEN_CONTRACT_DIGESTS["execution_authorization_receipt_schema_sha256"],
        "execution_authorization_receipt_digest": SHA,
        "authentication_conformance_receipt_schema_sha256": PILOT_FROZEN_CONTRACT_DIGESTS["authentication_conformance_receipt_schema_sha256"],
        "expiry_conformance_receipt_schema_sha256": PILOT_FROZEN_CONTRACT_DIGESTS["expiry_conformance_receipt_schema_sha256"],
    }
    principal_binding = {"principal_id": "pilot-reviewer", "session_ref": "pilot-session", "permissions": ["pilot"]}
    authentication_receipt = {
        "schema_version": "wig_p3_pilot_authentication_conformance_receipt.v1",
        "tested_at": isoformat_utc(utc_now()),
        "source_binding": source_binding,
        "runtime_binding": {
            "runtime_binding_digest": execution_context["runtime_binding_digest"],
            "scope_envelope_digest": bindings["scope_envelope_digest"],
            "ledger_state_digest": canonical_sha256(ledger_state),
            "token_file_path_digest": canonical_path_digest(paths.token_file),
        },
        "authentication": {
            "auth_mode": "token",
            "token_format_valid": True,
            "token_ledger_binding_valid": True,
            "no_token_status": 401,
            "wrong_token_status": 401,
            "correct_token_status": 200,
            "request_capability_non_json": True,
            "request_capability_single_use": True,
        },
        "surface": {
            "exposure_profile": "authoritative_canary",
            "scope_mode": PILOT_SCOPE_MODE,
            "visible_tool_count": len(PILOT_TOOLS),
            "visible_tool_set_digest": canonical_sha256(list(PILOT_TOOLS)),
            "tool_list_response_digest": SHA,
            "resources_list_response_digest": SHA,
            "resource_read_error_code": "resources_disabled",
            "hidden_tool_error_code": "TOOL_NOT_EXPOSED",
            "alternate_dispatch_error_code": "legacy_method_alias_disabled",
            "worker_inventory_digest": SHA,
            "definitions_dispatch_exact_match": True,
            "resources_disabled_or_empty": True,
            "actions_disabled": True,
            "hidden_tool_rejected": True,
            "alternate_dispatch_rejected": True,
            "prohibited_workers_running": False,
        },
        "safety": {
            "network_inventory_digest": SHA,
            "process_inventory_digest": SHA,
            "project_registry_snapshot_digest": SHA,
            "git_remote_snapshot_digest": SHA,
            "stable_promotion_snapshot_digest": SHA,
            "public_endpoint": False,
            "relay_or_tunnel": False,
            "existing_service_modified": False,
            "other_project_modified": False,
            "push": False,
            "stable_promotion": False,
        },
        "result": "PASS",
    }
    bindings["authentication_conformance_receipt_digest"] = canonical_sha256(authentication_receipt)
    semantic = build_pilot_semantic_validation_receipt(
        stage="pre_import",
        input_bindings={
            "candidate_manifest_sha256": SHA,
            "scope_envelope_digest": SHA,
            "storage_schema_contract_digest": PILOT_FROZEN_CONTRACT_DIGESTS["storage_schema_contract_digest"],
            "fact_reconciliation_contract_digest": PILOT_FROZEN_CONTRACT_DIGESTS["fact_reconciliation_contract_digest"],
            "authorization_digest": authorization_digest,
            "project_snapshot_digest": measured_project["snapshot_digest"],
            "runtime_binding_digest": execution_context["runtime_binding_digest"],
            "ledger_state_digest": canonical_sha256(ledger_state),
        },
    )
    decision_path = root / "authority/decision.json"
    decision_path.parent.mkdir(mode=0o700)
    decision_path.write_text("{}", encoding="utf-8")
    decision_path.chmod(0o600)
    monkeypatch.chdir(project)
    for name, path in {
        "HOME": paths.home,
        "XDG_CONFIG_HOME": paths.xdg_config_home,
        "XDG_STATE_HOME": paths.xdg_state_home,
        "XDG_CACHE_HOME": paths.xdg_cache_home,
        "XDG_DATA_HOME": paths.xdg_data_home,
    }.items():
        monkeypatch.setenv(name, str(path))
    preflight_kwargs = dict(
        bootstrap_receipt=receipt,
        paths=paths,
        gate_id="WIG-P3-AUTHORITATIVE-SINGLE-PROJECT-PILOT-TEST",
        bindings=bindings,
        execution_context=execution_context,
        project=measured_project,
        authentication_conformance_receipt=authentication_receipt,
        semantic_validation_receipt=semantic,
        decision_path=decision_path,
        source_checkout=project,
        wheel_artifact=wheel,
        principal_binding=principal_binding,
        project_path_manifests={
            "protected": protected_manifest,
            "allowed_read": read_manifest,
            "allowed_write": write_manifest,
        },
    )
    preflight = build_fresh_pilot_preflight_receipt(**preflight_kwargs)
    assert preflight["result"] == "PASS"
    assert preflight["ledger"]["path"] == receipt["ledger_path"]
    assert preflight["authentication"]["principal_binding_digest"] == canonical_sha256(principal_binding)
    forged_context = {**execution_context, "runtime_binding_digest": SHA}
    with pytest.raises(WorkItemGovernanceError) as runtime_error:
        build_fresh_pilot_preflight_receipt(**{**preflight_kwargs, "execution_context": forged_context})
    assert runtime_error.value.code == "PILOT_PREFLIGHT_MEASUREMENT_FAILED"
    forged_project = {**measured_project, "snapshot_digest": SHA}
    with pytest.raises(WorkItemGovernanceError) as project_error:
        build_fresh_pilot_preflight_receipt(**{**preflight_kwargs, "project": forged_project})
    assert project_error.value.code == "PILOT_PREFLIGHT_MEASUREMENT_FAILED"
    leaked_token = json.loads(paths.token_file.read_text(encoding="utf-8"))["auth_token"]
    leaked_evidence = root / "evidence/leaked-token.txt"
    leaked_evidence.write_text(leaked_token, encoding="utf-8")
    with pytest.raises(WorkItemGovernanceError) as token_error:
        build_fresh_pilot_preflight_receipt(**preflight_kwargs)
    assert token_error.value.code == "PILOT_PREFLIGHT_MEASUREMENT_FAILED"
    leaked_evidence.unlink()
    oversized_evidence = root / "evidence/oversized-token.log"
    with oversized_evidence.open("wb") as handle:
        handle.truncate(16 * 1024 * 1024 + 1)
        handle.seek(0)
        handle.write(leaked_token.encode("utf-8"))
    with pytest.raises(WorkItemGovernanceError) as oversized_error:
        build_fresh_pilot_preflight_receipt(**preflight_kwargs)
    assert oversized_error.value.code == "PILOT_PREFLIGHT_MEASUREMENT_FAILED"
    oversized_evidence.unlink()
    incomplete_surface = json.loads(json.dumps(authentication_receipt))
    incomplete_surface["surface"].pop("hidden_tool_error_code")
    with pytest.raises(WorkItemGovernanceError):
        build_fresh_pilot_preflight_receipt(
            **{**preflight_kwargs, "authentication_conformance_receipt": incomplete_surface}
        )
    wrong_conformance_binding = {**bindings, "authentication_conformance_receipt_digest": SHA}
    with pytest.raises(WorkItemGovernanceError) as conformance_binding_error:
        build_fresh_pilot_preflight_receipt(**{**preflight_kwargs, "bindings": wrong_conformance_binding})
    assert conformance_binding_error.value.code == "PILOT_PREFLIGHT_MEASUREMENT_FAILED"
    protected_files = [
        Path(receipt["ledger_path"]),
        paths.backup_path,
        paths.token_file,
        project / ".colameta/settings.json",
        decision_path,
    ]
    before = {str(path): path.read_bytes() for path in protected_files}
    monkeypatch.setenv("HOME", str(root / "wrong-home"))
    with pytest.raises(WorkItemGovernanceError) as measured_error:
        build_fresh_pilot_preflight_receipt(**preflight_kwargs)
    assert measured_error.value.code == "PILOT_PREFLIGHT_MEASUREMENT_FAILED"
    assert before == {str(path): path.read_bytes() for path in protected_files}
    monkeypatch.setenv("HOME", str(paths.home))
    with pytest.raises(WorkItemGovernanceError) as error:
        bootstrap_fresh_pilot_ledger(
            paths=paths,
            port=48791,
            source_checkout=project,
            wheel_artifact=wheel,
        )
    assert error.value.code == "PILOT_LEDGER_NOT_FRESH"


def test_transport_surface_conformance_is_measured_from_composed_server(tmp_path: Path) -> None:
    server = MCPPlanningBridgeServer(
        str(tmp_path),
        exposure_profile="authoritative_canary",
        work_item_scope_mode=PILOT_SCOPE_MODE,
    )
    surface = measure_pilot_transport_surface(server)
    assert surface["visible_tool_count"] == 14
    assert surface["definitions_dispatch_exact_match"] is True
    assert surface["resources_disabled_or_empty"] is True
    assert surface["hidden_tool_rejected"] is True
    assert surface["alternate_dispatch_rejected"] is True
    assert surface["prohibited_workers_running"] is False
    receipt = {
        "schema_version": "wig_p3_pilot_authentication_conformance_receipt.v1",
        "tested_at": isoformat_utc(utc_now()),
        "source_binding": {
            "implementation_commit": "1" * 40,
            "implementation_tree": "2" * 40,
            "wheel_sha256": SHA,
            "installed_inventory_sha256": SHA,
        },
        "runtime_binding": {
            "runtime_binding_digest": SHA,
            "scope_envelope_digest": SHA,
            "ledger_state_digest": SHA,
            "token_file_path_digest": SHA,
        },
        "authentication": {
            "auth_mode": "token",
            "token_format_valid": True,
            "token_ledger_binding_valid": True,
            "no_token_status": 401,
            "wrong_token_status": 401,
            "correct_token_status": 200,
            "request_capability_non_json": True,
            "request_capability_single_use": True,
        },
        "surface": surface,
        "safety": {
            "network_inventory_digest": SHA,
            "process_inventory_digest": SHA,
            "project_registry_snapshot_digest": SHA,
            "git_remote_snapshot_digest": SHA,
            "stable_promotion_snapshot_digest": SHA,
            "public_endpoint": False,
            "relay_or_tunnel": False,
            "existing_service_modified": False,
            "other_project_modified": False,
            "push": False,
            "stable_promotion": False,
        },
        "result": "PASS",
    }
    validate_governance_record("pilot_authentication_conformance_receipt.v1", receipt)

    normal = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="normal")
    with pytest.raises(WorkItemGovernanceError) as error:
        measure_pilot_transport_surface(normal)
    assert error.value.code == "PILOT_TRANSPORT_CONFORMANCE_INVALID"


def test_safety_conformance_is_bound_to_measured_host_and_project_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import runner.work_item_pilot_conformance as conformance_module

    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "-C", str(project), "init", "-q"], check=True)
    registry = tmp_path / "registry.json"
    registry.write_text("{}", encoding="utf-8")
    stable = tmp_path / "stable"
    stable.mkdir()
    snapshot = capture_pilot_safety_snapshot(
        project_root=project,
        registry_path=registry,
        stable_promotion_root=stable,
        port=48794,
    )
    assert snapshot["public_endpoint"] is False
    assert snapshot["relay_or_tunnel"] is False
    monkeypatch.setattr(conformance_module, "capture_pilot_safety_snapshot", lambda **_kwargs: snapshot)
    measured = measure_pilot_safety_conformance(
        expected_snapshot=snapshot,
        project_root=project,
        registry_path=registry,
        stable_promotion_root=stable,
        port=48794,
    )
    assert measured["existing_service_modified"] is False
    assert measured["push"] is False
    with pytest.raises(WorkItemGovernanceError) as mismatch:
        measure_pilot_safety_conformance(
            expected_snapshot={**snapshot, "git_remote_snapshot_digest": SHA},
            project_root=project,
            registry_path=registry,
            stable_promotion_root=stable,
            port=48794,
        )
    assert mismatch.value.code == "PILOT_SAFETY_SNAPSHOT_MISMATCH"


def test_bootstrap_rejects_project_nested_in_private_pilot_root(tmp_path: Path) -> None:
    root = tmp_path / "pilot"
    paths = PilotBootstrapPaths(
        pilot_root=root,
        project_root=root / "project",
        home=root / "home",
        xdg_config_home=root / "config",
        xdg_state_home=root / "state",
        xdg_cache_home=root / "cache",
        xdg_data_home=root / "data",
        registry_path=root / "config/colameta/project-registry.json",
        token_file=root / "config/colameta/auth.json",
        backup_path=root / "evidence/backup.sqlite3",
    )
    with pytest.raises(WorkItemGovernanceError) as error:
        bootstrap_fresh_pilot_ledger(
            paths=paths,
            port=48792,
            source_checkout=tmp_path,
            wheel_artifact=tmp_path / "unused.whl",
        )
    assert error.value.code == "PILOT_ROOT_COLLISION"
    assert not root.exists()


def test_one_shot_authorization_is_atomically_tombstoned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import runner.work_item_governance.pilot_authorization as module

    assert not hasattr(module, "_mint_consumed_pilot_authorization")
    assert not hasattr(module, "_CAPABILITY_REGISTRY")
    assert PilotAuthorizationDecisionConsumer.consume.__closure__ is None

    decision = {
        "gate_id": "WIG-P3-AUTHORITATIVE-SINGLE-PROJECT-PILOT-TEST",
        "bindings": {"candidate_manifest_sha256": SHA},
    }
    scope = {"scope": "test", "target_project": {"project_snapshot_digest": SHA}}
    decision_path = tmp_path / "decision.json"
    tombstone_path = tmp_path / "decision.tombstone.json"
    decision_path.write_text(json.dumps(decision), encoding="utf-8")
    decision_path.chmod(0o600)
    monkeypatch.setattr(module, "validate_pilot_authorization", lambda value, scope_envelope: value)
    monkeypatch.setattr(module, "validate_pilot_scope_envelope", lambda value, **kwargs: value)
    monkeypatch.setattr(module, "validate_pilot_preflight", lambda value: value)
    monkeypatch.setattr(module, "validate_pilot_authority_chain", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "build_pilot_semantic_validation_receipt", lambda **kwargs: {"result": "PASS"})
    consumer = PilotAuthorizationDecisionConsumer(
        decision_path=decision_path,
        tombstone_path=tombstone_path,
        ledger=_v6_ledger(tmp_path),
    )
    tombstone = consumer.consume(
        scope_envelope=scope,
        execution_authorization_receipt={},
        preflight_receipt={"execution_context": {}, "ledger": {}},
        authentication_conformance_receipt={},
        preflight_semantic_validation_receipt={},
        expected_authorization_digest=canonical_sha256(decision),
    )
    assert tombstone.tombstone["decision"] == "CONSUMED"
    assert tombstone.tombstone["retry_allowed"] is False
    decision["gate_id"] = "mutated-after-consumption"
    scope["scope"] = "mutated-after-consumption"
    assert tombstone.authorization["gate_id"] == "WIG-P3-AUTHORITATIVE-SINGLE-PROJECT-PILOT-TEST"
    assert tombstone.scope_envelope["scope"] == "test"
    returned = tombstone.tombstone
    returned["decision"] = "FORGED"
    assert tombstone.tombstone["decision"] == "CONSUMED"
    with pytest.raises(TypeError):
        tombstone._authorization_json = "{}"  # type: ignore[misc]
    forged = object.__new__(ConsumedPilotAuthorization)
    with pytest.raises(WorkItemGovernanceError) as forged_error:
        require_consumed_pilot_authorization(forged)
    assert forged_error.value.code == "PILOT_AUTHORIZATION_CAPABILITY_INVALID"
    assert not decision_path.exists()
    assert tombstone_path.is_file()
    assert tombstone_path.stat().st_mode & 0o077 == 0
    with pytest.raises(WorkItemGovernanceError) as error:
        consumer.consume(
            scope_envelope=scope,
            execution_authorization_receipt={},
            preflight_receipt={"execution_context": {}, "ledger": {}},
            authentication_conformance_receipt={},
            preflight_semantic_validation_receipt={},
            expected_authorization_digest=canonical_sha256(decision),
        )
    assert error.value.code == "PILOT_AUTHORIZATION_ALREADY_CONSUMED"


def test_persisted_authority_detects_mutation_reflection_and_one_shot_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = _v6_ledger(tmp_path)
    lease = _lease(new_stable_id("work_item"))
    authority = _consumed_authority(monkeypatch, tmp_path, lease)
    reflected_clone = object.__new__(ConsumedPilotAuthorization)
    for field in ConsumedPilotAuthorization.__slots__:
        object.__setattr__(reflected_clone, field, getattr(authority, field))
    assert require_consumed_pilot_authorization(authority) is authority
    assert consume_pilot_authorization_capability(authority) is authority
    with pytest.raises(WorkItemGovernanceError) as replay:
        consume_pilot_authorization_capability(authority)
    assert replay.value.code == "PILOT_AUTHORIZATION_CAPABILITY_CONSUMED"
    with pytest.raises(WorkItemGovernanceError) as reflected_replay:
        consume_pilot_authorization_capability(reflected_clone)
    assert reflected_replay.value.code == "PILOT_AUTHORIZATION_CAPABILITY_CONSUMED"

    other_root = tmp_path / "other"
    other_root.mkdir()
    other_ledger = _v6_ledger(other_root)
    other_lease = _lease(new_stable_id("work_item"))
    other = _consumed_authority(monkeypatch, other_root, other_lease)
    object.__setattr__(other, "_authorization_json", "{}")
    with pytest.raises(WorkItemGovernanceError) as mutated:
        require_consumed_pilot_authorization(other)
    assert mutated.value.code == "PILOT_AUTHORIZATION_CAPABILITY_INVALID"
    assert ledger.schema_version() == other_ledger.schema_version() == 6
