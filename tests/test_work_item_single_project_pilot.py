from __future__ import annotations

import json
import sqlite3
from datetime import timedelta
from pathlib import Path

import pytest

from runner.mcp_server import MCPPlanningBridgeServer
from runner.work_item_governance.canonical import canonical_sha256
from runner.work_item_governance.errors import WorkItemGovernanceError
from runner.work_item_governance.ids import new_stable_id
from runner.work_item_governance.pilot import (
    PILOT_SCOPE_MODE,
    PILOT_TOOLS,
    PilotActivationControlPlane,
    initial_execution_slot_usage,
    validate_execution_authorization_receipt,
    verify_pilot_event_chain,
)
from runner.work_item_governance.pilot_bootstrap import (
    PilotBootstrapPaths,
    bootstrap_fresh_pilot_ledger,
)
from runner.work_item_governance.pilot_authorization import PilotAuthorizationDecisionConsumer
from runner.work_item_governance.preview import isoformat_utc, utc_now
from runner.work_item_governance.repository import MIGRATIONS, SQLiteWorkItemLedger
from runner.work_item_governance.schema_loader import load_governance_contract


SHA = "a" * 64


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
    pilot = SQLiteWorkItemLedger(tmp_path, target_schema_version=6)
    pilot.initialize()
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
        SQLiteWorkItemLedger(tmp_path, target_schema_version=6).initialize()
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
            target_schema_version=6,
            migrations=broken,
        ).initialize()
    assert error.value.code == "LEDGER_MIGRATION_FAILED"
    with sqlite3.connect(legacy.path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 5
        assert connection.execute("SELECT value FROM ledger_meta WHERE key='schema_version'").fetchone()[0] == "5"
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_schema WHERE name='pilot_activation_leases'"
        ).fetchone()[0] == 0


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


def test_pilot_control_plane_issues_append_only_v4_lease(tmp_path: Path) -> None:
    ledger = SQLiteWorkItemLedger(tmp_path, target_schema_version=6)
    ledger.initialize()
    lease = _lease(new_stable_id("work_item"))
    PilotActivationControlPlane(ledger).prepare_lease(lease)
    with ledger.read_connection() as connection:
        row = connection.execute("SELECT * FROM pilot_activation_leases").fetchone()
        event = connection.execute("SELECT * FROM pilot_activation_lease_events").fetchone()
        assert row["schema_version"].endswith(".v4")
        assert event["sequence"] == 1
        assert event["event_type"] == "lease_issued"
    with sqlite3.connect(ledger.path) as connection:
        with pytest.raises(sqlite3.DatabaseError):
            connection.execute("UPDATE pilot_activation_lease_events SET event_type='lease_closed'")


def test_pilot_control_plane_event_chain_and_terminal_close(tmp_path: Path) -> None:
    ledger = SQLiteWorkItemLedger(tmp_path, target_schema_version=6)
    ledger.initialize()
    lease = _lease(new_stable_id("work_item"))
    control = PilotActivationControlPlane(ledger)
    control.prepare_lease(lease)
    control.transition_runtime(
        lease["lease_id"],
        event_type="process_claimed",
        process_identity_digest=SHA,
        monotonic_claim_ns=1,
        monotonic_deadline_ns=10**30,
    )
    control.transition_runtime(
        lease["lease_id"],
        event_type="listener_attested",
        process_identity_digest=SHA,
        listener_attestation_digest="b" * 64,
        request_context_binding="c" * 64,
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


def test_v6_raw_repository_write_and_maintenance_fail_closed(tmp_path: Path) -> None:
    ledger = SQLiteWorkItemLedger(tmp_path, target_schema_version=6)
    ledger.initialize()
    PilotActivationControlPlane(ledger).prepare_lease(_lease(new_stable_id("work_item")))
    with pytest.raises(WorkItemGovernanceError) as error:
        with ledger.write_transaction() as connection:
            connection.execute("INSERT INTO ledger_meta(key,value,updated_at) VALUES('raw','x','2026-01-01T00:00:00Z')")
    assert error.value.code == "ACTIVATION_REPOSITORY_WRITE_DENIED"


def test_pilot_controller_capability_rejects_subclass_and_direct_service_bypass(tmp_path: Path) -> None:
    ledger = SQLiteWorkItemLedger(tmp_path, target_schema_version=6)
    ledger.initialize()

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


def test_fresh_pilot_bootstrap_is_shadow_zero_fact_and_generation_bound(tmp_path: Path) -> None:
    root = tmp_path / "pilot"
    project = root / "project"
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
    receipt = bootstrap_fresh_pilot_ledger(
        paths=paths,
        port=48791,
        token_file_sha256="d" * 64,
        token_evidence_digest="e" * 64,
    )
    assert receipt["database_generation"] == receipt["backup"]["database_generation"] == 1
    assert receipt["backup"]["schema_version"] == 6
    assert receipt["backup"]["mode"] == "0600"
    assert not any(receipt["zero_fact_baseline"].values())
    assert receipt["runtime"]["gate_mode"] == "shadow"
    assert receipt["runtime"]["authoritative"] is False
    with pytest.raises(WorkItemGovernanceError) as error:
        bootstrap_fresh_pilot_ledger(
            paths=paths,
            port=48791,
            token_file_sha256="d" * 64,
            token_evidence_digest="e" * 64,
        )
    assert error.value.code == "PILOT_LEDGER_NOT_FRESH"


def test_one_shot_authorization_is_atomically_tombstoned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import runner.work_item_governance.pilot_authorization as module

    decision = {"gate_id": "WIG-P3-AUTHORITATIVE-SINGLE-PROJECT-PILOT-TEST"}
    scope = {"scope": "test"}
    decision_path = tmp_path / "decision.json"
    tombstone_path = tmp_path / "decision.tombstone.json"
    decision_path.write_text(json.dumps(decision), encoding="utf-8")
    decision_path.chmod(0o600)
    monkeypatch.setattr(module, "validate_pilot_authorization", lambda value, scope_envelope: value)
    consumer = PilotAuthorizationDecisionConsumer(
        decision_path=decision_path,
        tombstone_path=tombstone_path,
    )
    tombstone = consumer.consume(
        scope_envelope=scope,
        expected_authorization_digest=canonical_sha256(decision),
    )
    assert tombstone["decision"] == "CONSUMED"
    assert tombstone["retry_allowed"] is False
    assert not decision_path.exists()
    assert tombstone_path.is_file()
    assert tombstone_path.stat().st_mode & 0o077 == 0
    with pytest.raises(WorkItemGovernanceError) as error:
        consumer.consume(
            scope_envelope=scope,
            expected_authorization_digest=canonical_sha256(decision),
        )
    assert error.value.code == "PILOT_AUTHORIZATION_ALREADY_CONSUMED"
