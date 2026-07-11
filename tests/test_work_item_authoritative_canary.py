from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import runner.mcp_server as mcp_server_module
from runner.mcp_server import MCPPlanningBridgeServer, PlanningBridgeError
from runner.work_item_governance.activation import (
    AUTHORITATIVE_CANARY_TOOLS,
    validate_runtime_policy_contracts,
    validate_synthetic_fixture_semantics,
)
from runner.work_item_governance.canonical import canonical_sha256
from runner.work_item_governance.closeout import (
    _load_strict_json,
    _verify_exported_event_chain,
)
from runner.work_item_governance.errors import WorkItemGovernanceError
from runner.work_item_governance.ids import new_stable_id
from runner.work_item_governance.principal import trusted_principal_context
from runner.work_item_governance.repository import SQLiteWorkItemLedger
from runner.work_item_governance.repository import MIGRATIONS
from runner.work_item_governance.service import WorkItemApplicationService
from work_item_r2_helpers import (
    all_permissions_principal,
    install_active_lease,
    lease_row,
    make_fixture,
    transition_apply,
)


def test_schema_v5_and_frozen_runtime_policy_contracts(tmp_path: Path) -> None:
    ledger = SQLiteWorkItemLedger(tmp_path)
    ledger.initialize()
    assert ledger.schema_version() == 5
    assert ledger.integrity_check()["ok"] is True
    with ledger.read_connection() as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert {"activation_leases", "activation_lease_events"}.issubset(tables)
        columns = {row[1] for row in connection.execute("PRAGMA table_info(activation_leases)")}
        assert "fixture_bindings_json" in columns
    policy = validate_runtime_policy_contracts()
    assert policy["tool_count"] == 14
    assert policy["allowed_write_count"] == 7
    assert policy["denied_write_count"] == 9


def test_schema_v5_forward_migration_and_failure_rollback(tmp_path: Path) -> None:
    project = tmp_path / "upgrade"
    project.mkdir()
    _create_v4_ledger(project)
    upgraded = SQLiteWorkItemLedger(project)
    upgraded.initialize()
    assert upgraded.schema_version() == 5
    with upgraded.read_connection() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='activation_leases'"
        ).fetchone()[0] == 1

    broken_project = tmp_path / "rollback"
    broken_project.mkdir()
    _create_v4_ledger(broken_project)
    migrations = dict(MIGRATIONS)
    migrations[5] = (MIGRATIONS[5][0], "THIS IS NOT SQL")
    broken = SQLiteWorkItemLedger(broken_project, migrations=migrations)
    with pytest.raises(WorkItemGovernanceError) as exc_info:
        broken.initialize()
    assert exc_info.value.code == "LEDGER_MIGRATION_FAILED"
    with sqlite3.connect(broken.path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 4
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='activation_leases'"
        ).fetchone()[0] == 0

    strict_project = tmp_path / "strict-startup"
    strict_project.mkdir()
    _create_v4_ledger(strict_project)
    with pytest.raises(WorkItemGovernanceError) as strict_error:
        WorkItemApplicationService(
            strict_project,
            enabled=True,
            authoritative_transitions=True,
            authoritative_canary=True,
        )
    assert strict_error.value.code == "ACTIVATION_LEDGER_SCHEMA_MISMATCH"
    with sqlite3.connect(strict_project / ".colameta/ledger/work-items.sqlite3") as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 4


def test_synthetic_fixture_cross_field_semantics(tmp_path: Path) -> None:
    fixture, _raw = make_fixture(tmp_path, all_permissions_principal())
    result = validate_synthetic_fixture_semantics(fixture)
    assert result["command_slot_count"] == 17
    assert result["generated_binding_count"] == 15
    mutated = json.loads(json.dumps(fixture))
    mutated["command_slots"][0]["normalized_command_digest"] = "0" * 64
    with pytest.raises(WorkItemGovernanceError) as exc_info:
        validate_synthetic_fixture_semantics(mutated)
    assert exc_info.value.code == "SYNTHETIC_FIXTURE_SEMANTICS_INVALID"


def test_transactional_lease_executes_revision_lifecycle_and_exact_replay(tmp_path: Path) -> None:
    principal = all_permissions_principal()
    fixture, raw = make_fixture(tmp_path, principal)
    service = install_active_lease(tmp_path, fixture, principal)

    create_preview = service.preview_work_item_create(raw["create"])["preview"]
    work_item_id = service.apply_work_item_create(create_preview)["work_item"]["work_item_id"]
    before_replay = lease_row(service)
    replay = service.apply_work_item_create(create_preview)
    assert replay["idempotent_replay"] is True
    assert lease_row(service)["usage_json"] == before_replay["usage_json"]

    _gate(service, principal, work_item_id, 1, "ready", 0, "r2:gate:1")
    _gate(service, principal, work_item_id, 1, "in_delivery", 1, "r2:gate:2")
    attempt_one = service.create_execution_attempt(
        {
            "work_item_id": work_item_id,
            "task_version": 1,
            "status": "claimed",
            "objective_ref": "synthetic://WIG-P3-AUTH-CANARY-A1-R2/objective/v1",
            "metadata": {},
            "external_refs": [],
            "source_event_key": "r2:attempt:1",
        }
    )["attempt"]["attempt_id"]
    service.complete_execution_attempt(
        {
            "attempt_id": attempt_one,
            "status": "completed",
            "source_event_key": "r2:complete:1",
            "metadata": {},
            "artifacts": [],
        }
    )
    artifact_one_command = dict(raw["artifact_one"])
    artifact_one_command.pop("artifact_id")
    artifact_one_command.update({"work_item_id": work_item_id, "attempt_id": attempt_one})
    artifact_one = service.register_artifact_reference(artifact_one_command)["artifact"]["artifact_id"]
    decision_one = _decision(
        service,
        principal,
        work_item_id,
        1,
        "submit",
        [artifact_one],
        "submit v1",
        "r2:decision:1",
    )
    _gate(
        service,
        principal,
        work_item_id,
        1,
        "submitted",
        2,
        "r2:gate:3",
        [decision_one],
        [artifact_one],
    )
    decision_two = _decision(
        service,
        principal,
        work_item_id,
        1,
        "request_changes",
        [],
        "revise",
        "r2:decision:2",
    )
    returned = _gate(
        service,
        principal,
        work_item_id,
        1,
        "in_delivery",
        3,
        "r2:gate:4",
        [decision_two],
    )
    assert returned["gate_event"]["transition_result"] == "returned_for_revision"
    service.add_task_version(
        {
            "work_item_id": work_item_id,
            "task_version": 2,
            "task": raw["task_two"],
            "source_event_key": "r2:task:2",
        }
    )
    attempt_two = service.create_execution_attempt(
        {
            "work_item_id": work_item_id,
            "task_version": 2,
            "status": "claimed",
            "objective_ref": "synthetic://WIG-P3-AUTH-CANARY-A1-R2/objective/v2",
            "metadata": {},
            "external_refs": [],
            "source_event_key": "r2:attempt:2",
        }
    )["attempt"]["attempt_id"]
    artifact_two_command = dict(raw["artifact_two"])
    artifact_two_command.pop("artifact_id")
    artifact_two_command.update({"work_item_id": work_item_id, "attempt_id": attempt_two})
    completion = service.complete_execution_attempt(
        {
            "attempt_id": attempt_two,
            "status": "completed",
            "source_event_key": "r2:complete:2",
            "metadata": {},
            "artifacts": [artifact_two_command],
        }
    )
    artifact_two = completion["artifacts"][0]["artifact_id"]
    decision_three = _decision(
        service,
        principal,
        work_item_id,
        2,
        "submit",
        [artifact_two],
        "submit v2",
        "r2:decision:3",
    )
    _gate(
        service,
        principal,
        work_item_id,
        2,
        "submitted",
        5,
        "r2:gate:5",
        [decision_three],
        [artifact_two],
    )
    decision_four = _decision(
        service,
        principal,
        work_item_id,
        2,
        "accept",
        [artifact_two],
        "accept v2",
        "r2:decision:4",
    )
    accepted_preview = service.preview_work_item_transition(
        {
            "work_item_id": work_item_id,
            "task_version": 2,
            "target_state": "accepted",
            "expected_state_version": 6,
            "decision_ids": [decision_four],
            "evidence_artifact_ids": [artifact_two],
            "idempotency_key": "r2:gate:6",
        },
        principal_context=principal,
    )["preview"]
    accepted = service.apply_work_item_transition(accepted_preview, principal_context=principal)
    assert accepted["work_item"]["state"] == "accepted"
    lease_before_replay = lease_row(service)
    accepted_replay = service.apply_work_item_transition(accepted_preview, principal_context=principal)
    assert accepted_replay["idempotent_replay"] is True
    final_lease = lease_row(service)
    assert final_lease["usage_json"] == lease_before_replay["usage_json"]
    assert final_lease["usage_json"] == {
        "new_work_items": 1,
        "task_versions": 2,
        "runtime_attempts": 2,
        "artifacts": 2,
        "decisions": 4,
        "applied_gate_events": 6,
        "rejected_gate_events": 0,
        "gate_events_total": 6,
        "lease_events": 20,
    }
    assert {key: len(value) for key, value in final_lease["fixture_bindings_json"].items()} == {
        "attempt_ids": 2,
        "artifact_ids": 2,
        "decision_ids": 4,
        "gate_event_ids": 6,
    }
    with service.ledger.read_connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM acceptance_manifests").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM activation_lease_events").fetchone()[0] == 20


def test_concurrent_first_create_binds_only_one_work_item(tmp_path: Path) -> None:
    principal = all_permissions_principal()
    fixture, raw = make_fixture(tmp_path, principal)
    service = install_active_lease(tmp_path, fixture, principal)
    preview = service.preview_work_item_create(raw["create"])["preview"]

    def apply_once() -> dict[str, object]:
        return service.apply_work_item_create(preview)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [future.result() for future in (pool.submit(apply_once), pool.submit(apply_once))]
    ids = {result["work_item"]["work_item_id"] for result in results}  # type: ignore[index]
    assert len(ids) == 1
    assert sorted(result["created"] for result in results) == [False, True]
    with service.ledger.read_connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM work_items").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM activation_lease_events").fetchone()[0] == 4


def test_denied_command_freezes_lease_without_domain_fact(tmp_path: Path) -> None:
    principal = all_permissions_principal()
    fixture, _raw = make_fixture(tmp_path, principal)
    service = install_active_lease(tmp_path, fixture, principal)
    with pytest.raises(WorkItemGovernanceError) as exc_info:
        service.apply_blocker({})
    assert exc_info.value.code == "ACTIVATION_COMMAND_DENIED"
    with service.ledger.read_connection() as connection:
        row = connection.execute("SELECT status FROM activation_leases").fetchone()
        assert row["status"] == "write_frozen"
        assert connection.execute("SELECT COUNT(*) FROM blocker_events").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM activation_lease_events").fetchone()[0] == 4
    with pytest.raises(sqlite3.IntegrityError):
        with service.ledger.write_transaction() as connection:
            connection.execute("UPDATE activation_lease_events SET reason_code='tampered'")
    with pytest.raises(sqlite3.IntegrityError):
        with service.ledger.write_transaction() as connection:
            connection.execute("DELETE FROM activation_lease_events")


@pytest.mark.parametrize(
    ("method_name", "argument"),
    (
        ("apply_legacy_work_item_import", {}),
        ("bind_historical_execution_attempt", {}),
        ("apply_blocker", {}),
        ("clear_blocker", {}),
        ("create_delivery_receipt", {}),
        ("retry_delivery", {}),
        ("acknowledge_delivery", {}),
        ("record_outbox_delivery_result", {}),
        ("recover_outbox_event", {}),
    ),
)
def test_all_nine_denied_write_commands_fail_before_domain_mutation(
    tmp_path: Path,
    method_name: str,
    argument: dict[str, object],
) -> None:
    principal = all_permissions_principal()
    fixture, _raw = make_fixture(tmp_path, principal)
    service = install_active_lease(tmp_path, fixture, principal)
    with pytest.raises(WorkItemGovernanceError) as exc_info:
        getattr(service, method_name)(argument)
    assert exc_info.value.code == "ACTIVATION_COMMAND_DENIED"
    with service.ledger.read_connection() as connection:
        assert connection.execute("SELECT status FROM activation_leases").fetchone()[0] == "write_frozen"
        for table in ("work_items", "execution_attempts", "blocker_events", "delivery_receipts", "inbox_events"):
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_wrong_fixture_order_freezes_before_domain_lookup(tmp_path: Path) -> None:
    principal = all_permissions_principal()
    fixture, _raw = make_fixture(tmp_path, principal)
    service = install_active_lease(tmp_path, fixture, principal)
    with pytest.raises(WorkItemGovernanceError) as exc_info:
        service.create_execution_attempt(
            {
                "work_item_id": "wi_01900000-0000-7000-8000-000000000000",
                "task_version": 1,
                "status": "claimed",
                "objective_ref": "synthetic://WIG-P3-AUTH-CANARY-A1-R2/objective/v1",
                "metadata": {},
                "external_refs": [],
                "source_event_key": "r2:attempt:1",
            }
        )
    assert exc_info.value.code == "ACTIVATION_FIXTURE_MISMATCH"
    with service.ledger.read_connection() as connection:
        assert connection.execute("SELECT status FROM activation_leases").fetchone()[0] == "write_frozen"
        assert connection.execute("SELECT COUNT(*) FROM execution_attempts").fetchone()[0] == 0


def test_expired_lease_is_persistently_terminal_on_write(tmp_path: Path) -> None:
    principal = all_permissions_principal()
    fixture, raw = make_fixture(tmp_path, principal)
    service = install_active_lease(tmp_path, fixture, principal)
    preview = service.preview_work_item_create(raw["create"])["preview"]
    with service.ledger.write_transaction() as connection:
        connection.execute(
            """
            UPDATE activation_leases
            SET not_before='2000-01-01T00:00:00Z',expires_at='2000-01-01T00:10:00Z'
            """
        )
    with pytest.raises(WorkItemGovernanceError) as exc_info:
        service.apply_work_item_create(preview)
    assert exc_info.value.code == "ACTIVATION_LEASE_EXPIRED"
    with service.ledger.read_connection() as connection:
        assert connection.execute("SELECT status FROM activation_leases").fetchone()[0] == "expired"
        assert connection.execute("SELECT COUNT(*) FROM work_items").fetchone()[0] == 0
        assert connection.execute("SELECT event_type FROM activation_lease_events ORDER BY sequence DESC LIMIT 1").fetchone()[0] == "lease_expired"


def test_monotonic_deadline_expires_without_watchdog(tmp_path: Path) -> None:
    principal = all_permissions_principal()
    fixture, raw = make_fixture(tmp_path, principal)
    service = install_active_lease(tmp_path, fixture, principal)
    preview = service.preview_work_item_create(raw["create"])["preview"]
    with service.ledger.write_transaction() as connection:
        connection.execute(
            "UPDATE activation_leases SET monotonic_deadline_ns=monotonic_claim_ns+1"
        )
    with pytest.raises(WorkItemGovernanceError) as exc_info:
        service.apply_work_item_create(preview)
    assert exc_info.value.code == "ACTIVATION_LEASE_EXPIRED"
    with service.ledger.read_connection() as connection:
        assert connection.execute("SELECT status FROM activation_leases").fetchone()[0] == "expired"
        assert connection.execute("SELECT COUNT(*) FROM work_items").fetchone()[0] == 0


@pytest.mark.parametrize(
    "assignment",
        (
            "monotonic_deadline_ns=NULL",
            "monotonic_claim_ns=0",
        "monotonic_deadline_ns=monotonic_claim_ns",
        "monotonic_deadline_ns=monotonic_claim_ns+1800000000001",
    ),
)
def test_invalid_monotonic_deadline_freezes_authoritative_writes(
    tmp_path: Path,
    assignment: str,
) -> None:
    principal = all_permissions_principal()
    fixture, raw = make_fixture(tmp_path, principal)
    service = install_active_lease(tmp_path, fixture, principal)
    preview = service.preview_work_item_create(raw["create"])["preview"]
    with service.ledger.write_transaction() as connection:
        connection.execute(f"UPDATE activation_leases SET {assignment}")
    with pytest.raises(WorkItemGovernanceError) as exc_info:
        service.apply_work_item_create(preview)
    assert exc_info.value.code == "ACTIVATION_MONOTONIC_DEADLINE_INVALID"
    with service.ledger.read_connection() as connection:
        assert connection.execute("SELECT status FROM activation_leases").fetchone()[0] == "write_frozen"
        assert connection.execute("SELECT COUNT(*) FROM work_items").fetchone()[0] == 0


def test_active_lease_without_request_capability_rejects_without_mutation(tmp_path: Path) -> None:
    principal = all_permissions_principal()
    fixture, raw = make_fixture(tmp_path, principal)
    service = install_active_lease(tmp_path, fixture, principal)
    service.request_context = None
    with pytest.raises(WorkItemGovernanceError) as exc_info:
        service.preview_work_item_create(raw["create"])
    assert exc_info.value.code == "AUTHENTICATED_REQUEST_CONTEXT_REQUIRED"
    with service.ledger.read_connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM work_items").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM activation_lease_events").fetchone()[0] == 3


def test_principal_mismatch_freezes_before_domain_mutation(tmp_path: Path) -> None:
    principal = all_permissions_principal()
    fixture, raw = make_fixture(tmp_path, principal)
    service = install_active_lease(tmp_path, fixture, principal)
    preview = service.preview_work_item_create(raw["create"])["preview"]
    service.principal_context = trusted_principal_context(
        principal_id=principal.principal_id,
        principal_kind=principal.principal_kind,
        authenticated_by="local_session",
        granted_permissions=principal.granted_permissions,
        session_ref="different-session",
    )
    with pytest.raises(WorkItemGovernanceError) as exc_info:
        service.apply_work_item_create(preview)
    assert exc_info.value.code == "ACTIVATION_PRINCIPAL_MISMATCH"
    with service.ledger.read_connection() as connection:
        assert connection.execute("SELECT status FROM activation_leases").fetchone()[0] == "write_frozen"
        assert connection.execute("SELECT COUNT(*) FROM work_items").fetchone()[0] == 0


def test_request_context_from_another_lease_freezes_before_domain_mutation(tmp_path: Path) -> None:
    principal = all_permissions_principal()
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    first_fixture, first_raw = make_fixture(first, principal)
    second_fixture, _second_raw = make_fixture(second, principal)
    service = install_active_lease(first, first_fixture, principal)
    other_service = install_active_lease(second, second_fixture, principal)
    preview = service.preview_work_item_create(first_raw["create"])["preview"]
    service.request_context = other_service.request_context
    with pytest.raises(WorkItemGovernanceError) as exc_info:
        service.apply_work_item_create(preview)
    assert exc_info.value.code == "REQUEST_CONTEXT_BINDING_MISMATCH"
    with service.ledger.read_connection() as connection:
        assert connection.execute("SELECT status FROM activation_leases").fetchone()[0] == "write_frozen"
        assert connection.execute("SELECT COUNT(*) FROM work_items").fetchone()[0] == 0


def test_process_restart_cannot_reuse_active_lease(tmp_path: Path) -> None:
    principal = all_permissions_principal()
    fixture, _raw = make_fixture(tmp_path, principal)
    install_active_lease(tmp_path, fixture, principal)
    script = r'''
from pathlib import Path
from runner.work_item_governance.activation import AuthoritativeCanaryGuard
from runner.work_item_governance.errors import WorkItemGovernanceError
from runner.work_item_governance.principal import trusted_principal_context
from runner.work_item_governance.repository import SQLiteWorkItemLedger
from runner.work_item_governance.request_context import _issue_authenticated_token_request_proof
import os
principal=trusted_principal_context(principal_id="r2-canary-operator",principal_kind="human",authenticated_by="local_session",granted_permissions={"work_item.ready","work_item.start_delivery","work_item.submit","work_item.accept","work_item.cancel","work_item.return_for_revision","work_item.approve"},session_ref="r2-session")
try:
 AuthoritativeCanaryGuard(SQLiteWorkItemLedger(Path(os.environ["PROJECT_ROOT"]))).mint_request_context(proof=_issue_authenticated_token_request_proof(),principal_context=principal)
except WorkItemGovernanceError as exc:
 print(exc.code)
 raise SystemExit(0 if exc.code == "ACTIVATION_PROCESS_RESTARTED" else 2)
raise SystemExit(3)
'''
    completed = subprocess.run(
        [sys.executable, "-c", script],
        env={**os.environ, "PROJECT_ROOT": str(tmp_path), "PYTHONPATH": str(Path(__file__).resolve().parents[1])},
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "ACTIVATION_PROCESS_RESTARTED"


def test_process_identity_mismatch_removes_attempt_dispatch_authority(tmp_path: Path) -> None:
    principal = all_permissions_principal()
    fixture, raw = make_fixture(tmp_path, principal)
    service = install_active_lease(tmp_path, fixture, principal)
    work_item_id = service.apply_work_item_create(
        service.preview_work_item_create(raw["create"])["preview"]
    )["work_item"]["work_item_id"]
    _gate(service, principal, work_item_id, 1, "ready", 0, "r2:gate:1")
    _gate(service, principal, work_item_id, 1, "in_delivery", 1, "r2:gate:2")
    attempt_id = service.create_execution_attempt(
        {
            "work_item_id": work_item_id,
            "task_version": 1,
            "status": "claimed",
            "objective_ref": "synthetic://WIG-P3-AUTH-CANARY-A1-R2/objective/v1",
            "metadata": {},
            "external_refs": [],
            "source_event_key": "r2:attempt:1",
        }
    )["attempt"]["attempt_id"]
    authority = service.get_execution_attempt_dispatch_authority(
        attempt_id=attempt_id,
        work_item_id=work_item_id,
        task_version=1,
    )
    assert authority["dispatch_authorized"] is True
    service.activation_guard.process_identity_provider = lambda _nonce: {
        "expected_process_identity": "0" * 64
    }
    authority = service.get_execution_attempt_dispatch_authority(
        attempt_id=attempt_id,
        work_item_id=work_item_id,
        task_version=1,
    )
    assert authority["dispatch_authorized"] is False
    assert "ACTIVATION_LEASE_INACTIVE" in authority["reason_codes"]
    assert service.activation_guard.runtime_status()["effective_active"] is False


def test_restore_is_not_an_authoritative_endpoint_write(tmp_path: Path) -> None:
    principal = all_permissions_principal()
    fixture, _raw = make_fixture(tmp_path, principal)
    service = install_active_lease(tmp_path, fixture, principal)
    with pytest.raises(WorkItemGovernanceError) as exc_info:
        service.restore_ledger(tmp_path / "missing.sqlite3", expected_database_generation=1)
    assert exc_info.value.code == "ACTIVATION_LEDGER_RESTORE_DENIED"


def test_direct_canary_service_without_sealed_request_context_fails_closed(tmp_path: Path) -> None:
    ledger = SQLiteWorkItemLedger(tmp_path)
    ledger.initialize()
    ledger.get_or_create_signing_key()
    service = WorkItemApplicationService(
        tmp_path,
        enabled=True,
        authoritative_transitions=True,
        authoritative_canary=True,
        principal_context=all_permissions_principal(),
    )
    with pytest.raises(WorkItemGovernanceError) as exc_info:
        service.preview_work_item_create(
            {
                "origin": {"kind": "manual", "ref": "synthetic://x", "snapshot_digest": "1" * 64},
                "objective": "x",
                "idempotency_key": "x",
            }
        )
    assert exc_info.value.code == "ACTIVE_ACTIVATION_LEASE_REQUIRED"
    with ledger.read_connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM work_items").fetchone()[0] == 0


def test_authoritative_canary_mcp_profile_is_exact_and_default_deny(
    tmp_path: Path,
) -> None:
    server = MCPPlanningBridgeServer(
        str(tmp_path),
        exposure_profile="authoritative_canary",
    )
    assert tuple(server._visible_tool_names()) == AUTHORITATIVE_CANARY_TOOLS
    assert len(server._tool_defs_payload()) == 14
    denied = server._call_tool("manage_git", {}, auth_context={"mode": "token"})
    assert denied["error_code"] == "TOOL_NOT_EXPOSED"
    agent_denied = server.call_tool_for_agent(
        "manage_git",
        {},
        auth_context={"mode": "token"},
    )
    assert agent_denied["error_code"] == "TOOL_NOT_EXPOSED"
    direct = server._handle_jsonrpc_request(
        {"jsonrpc": "2.0", "id": 1, "method": "get_work_item", "params": {}},
        auth_context={"mode": "token"},
    )
    assert direct["error"]["data"]["error_code"] == "direct_tool_method_disabled"
    resources = server._handle_jsonrpc_request(
        {"jsonrpc": "2.0", "id": 2, "method": "resources/list"},
        auth_context={"mode": "token"},
    )
    assert resources["result"] == {"resources": []}
    resource_read = server._handle_jsonrpc_request(
        {"jsonrpc": "2.0", "id": 3, "method": "resources/read", "params": {"uri": "x"}},
        auth_context={"mode": "token"},
    )
    assert resource_read["error"]["data"]["error_code"] == "resources_disabled"
    unknown = server._handle_jsonrpc_request(
        {"jsonrpc": "2.0", "id": 4, "method": "unknown/method", "params": {}},
        auth_context={"mode": "token"},
    )
    assert unknown["error"]["data"]["error_code"] == "method_not_found"
    with pytest.raises(PlanningBridgeError):
        server.serve_http(host="0.0.0.0", port=48788, auth_token="x" * 43, auth_mode="token")
    with pytest.raises(PlanningBridgeError):
        server.serve_http(host="127.0.0.1", port=48788, auth_token="weak", auth_mode="token")


def test_authoritative_canary_startup_refuses_frozen_tool_set_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        mcp_server_module,
        "AUTHORITATIVE_CANARY_MCP_TOOLS",
        (*AUTHORITATIVE_CANARY_TOOLS, "unexpected_tool"),
    )
    with pytest.raises(PlanningBridgeError, match="frozen exact allowlist"):
        MCPPlanningBridgeServer(str(tmp_path), exposure_profile="authoritative_canary")


def test_fresh_bootstrap_preflight_runs_under_isolated_process(tmp_path: Path) -> None:
    root = tmp_path / "canary"
    runtime = root / "runtime" / "python"
    runtime.parent.mkdir(parents=True)
    root.chmod(0o700)
    shutil.copy2(Path(sys.executable).resolve(), runtime)
    project = root / "project"
    project.mkdir(parents=True)
    script = r'''
import json, os, sys
from pathlib import Path
from runner.work_item_governance.bootstrap import FreshCanaryPaths, bootstrap_fresh_canary_preflight, provision_private_bearer_token
from runner.work_item_governance.ids import new_stable_id
root=Path(os.environ["CANARY_ROOT"]).resolve(); project=root/"project"
paths=FreshCanaryPaths(
 canary_root=root, home=root/"home", xdg_config=root/"xdg-config", xdg_state=root/"xdg-state",
 xdg_cache=root/"xdg-cache", registry=root/"xdg-config/colameta/project-registry.json",
 project_root=project, settings=project/".colameta/settings.json",
 ledger=project/".colameta/ledger/work-items.sqlite3", backup=root/"evidence/pre-activation.sqlite3",
 token_file=root/"xdg-config/colameta/auth.json", activation_envelope=root/"control/activation.json",
 claimed_activation_envelope=root/"control/claimed.json", fixture_root=project/"synthetic-fixtures",
 runtime_executable=Path(sys.executable).resolve(), cwd=project,
)
token=provision_private_bearer_token(xdg_config_home=paths.xdg_config)
receipt=bootstrap_fresh_canary_preflight(
 paths=paths, authorization_id="WIG-P3-CANARY-A1-R2-TEST", authorization_digest="a"*64,
 activation_lease_id=new_stable_id("activation_lease"), runtime_instance_nonce="n"*32,
 source_binding={"core_baseline_commit":"53d8939af22b019b2df2b555b85869ac39c5bba2","implementation_commit":"d"*40,"implementation_tree":"e"*40,"wheel_sha256":"f"*64},
 principal_binding={"principal_id":"r2-canary-operator","principal_kind":"human","session_ref":"r2-session","authenticated_by":"local_session","permissions":["work_item.accept","work_item.approve","work_item.cancel","work_item.ready","work_item.return_for_revision","work_item.start_delivery","work_item.submit"]},
 project_name="r2-canary", port=48789, token_provisioning=token,
)
print(json.dumps({"result":receipt["result"],"schema":receipt["fresh_ledger"]["schema_version"],"facts":receipt["fresh_ledger"]["business_fact_counts"],"backup":receipt["pre_activation_backup"]["api"]},sort_keys=True))
'''
    env = {
        **os.environ,
        "CANARY_ROOT": str(root),
        "HOME": str(root / "home"),
        "XDG_CONFIG_HOME": str(root / "xdg-config"),
        "XDG_STATE_HOME": str(root / "xdg-state"),
        "XDG_CACHE_HOME": str(root / "xdg-cache"),
        "PYTHONPATH": os.pathsep.join(
            (
                str(Path(__file__).resolve().parents[1]),
                str(Path(sys.prefix) / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"),
            )
        ),
    }
    completed = subprocess.run(
        [str(runtime), "-c", script],
        cwd=project,
        env=env,
        check=False,
        text=True,
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["result"] == "PASS"
    assert result["schema"] == 5
    assert all(value == 0 for value in result["facts"].values())
    assert result["backup"] == "sqlite3.Connection.backup"
    assert not (tmp_path / ".colameta" / "ledger").exists()


def test_failed_single_use_envelope_claim_is_never_reusable(tmp_path: Path) -> None:
    root = tmp_path / "claim-canary"
    runtime = root / "runtime" / "python"
    runtime.parent.mkdir(parents=True)
    root.chmod(0o700)
    shutil.copy2(Path(sys.executable).resolve(), runtime)
    project = root / "project"
    project.mkdir(parents=True)
    script = r'''
import json, os, sys
from datetime import timedelta
from pathlib import Path
from runner.work_item_governance.activation import ActivationLeaseControlPlane
from runner.work_item_governance.bootstrap import FreshCanaryPaths, bootstrap_fresh_canary_preflight, build_activation_envelope, provision_private_bearer_token, revoke_private_bearer_token
from runner.work_item_governance.canonical import canonical_json
from runner.work_item_governance.errors import WorkItemGovernanceError
from runner.work_item_governance.ids import new_stable_id
from runner.work_item_governance.preview import isoformat_utc, utc_now
from runner.work_item_governance.repository import SQLiteWorkItemLedger
from work_item_r2_helpers import all_permissions_principal, make_fixture
root=Path(os.environ["CANARY_ROOT"]).resolve(); project=root/"project"
paths=FreshCanaryPaths(
 canary_root=root, home=root/"home", xdg_config=root/"xdg-config", xdg_state=root/"xdg-state",
 xdg_cache=root/"xdg-cache", registry=root/"xdg-config/colameta/project-registry.json",
 project_root=project, settings=project/".colameta/settings.json",
 ledger=project/".colameta/ledger/work-items.sqlite3", backup=root/"evidence/pre-activation.sqlite3",
 token_file=root/"xdg-config/colameta/auth.json", activation_envelope=root/"control/activation.json",
 claimed_activation_envelope=root/"control/claimed.json", fixture_root=project/"synthetic-fixtures",
 runtime_executable=Path(sys.executable).resolve(), cwd=project,
)
token=provision_private_bearer_token(xdg_config_home=paths.xdg_config); lease_id=new_stable_id("activation_lease")
source={"core_baseline_commit":"53d8939af22b019b2df2b555b85869ac39c5bba2","implementation_commit":"d"*40,"implementation_tree":"e"*40,"wheel_sha256":"f"*64}
principal=all_permissions_principal(); binding={"principal_id":principal.principal_id,"principal_kind":principal.principal_kind,"session_ref":principal.session_ref,"authenticated_by":"local_session","permissions":sorted(principal.granted_permissions)}
receipt=bootstrap_fresh_canary_preflight(paths=paths,authorization_id="WIG-P3-CANARY-A1-R2-TEST",authorization_digest="a"*64,activation_lease_id=lease_id,runtime_instance_nonce="n"*32,source_binding=source,principal_binding=binding,project_name="claim-test",port=48790,token_provisioning=token)
fixture,_raw=make_fixture(project,principal); now=utc_now()
envelope=build_activation_envelope(preflight_receipt=receipt,synthetic_fixture=fixture,instance_id="claim-test",project_name="claim-test",issued_at=isoformat_utc(now),not_before=isoformat_utc(now),expires_at=isoformat_utc(now+timedelta(seconds=1790)))
ledger=SQLiteWorkItemLedger(project); control=ActivationLeaseControlPlane(ledger,canary_root=root)
control.issue_prepared_lease(activation_envelope=envelope,synthetic_fixture=fixture,preflight_receipt=receipt,envelope_path=paths.activation_envelope)
tampered=json.loads(paths.activation_envelope.read_text(encoding="utf-8")); tampered["authorization_digest"]="9"*64
paths.activation_envelope.write_text(canonical_json(tampered),encoding="utf-8")
codes=[]
for _index in range(2):
 try:
  control.claim_prepared_lease(lease_id=lease_id,envelope_path=paths.activation_envelope,claimed_envelope_path=paths.claimed_activation_envelope)
 except WorkItemGovernanceError as exc:
  codes.append(exc.code)
with ledger.read_connection() as connection:
 status=connection.execute("SELECT status FROM activation_leases WHERE lease_id=?",(lease_id,)).fetchone()[0]
revoke_private_bearer_token(auth_file=paths.token_file,canary_root=root)
print(json.dumps({"codes":codes,"status":status,"source_exists":paths.activation_envelope.exists(),"claimed_exists":paths.claimed_activation_envelope.exists()},sort_keys=True))
'''
    completed = subprocess.run(
        [str(runtime), "-c", script],
        cwd=project,
        env=_isolated_subprocess_env(root),
        check=False,
        text=True,
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result == {
        "claimed_exists": True,
        "codes": [
            "ACTIVATION_ENVELOPE_DIGEST_MISMATCH",
            "ACTIVATION_ENVELOPE_NOT_CLAIMABLE",
        ],
        "source_exists": False,
        "status": "revoked",
    }


def test_loopback_conformance_requires_token_and_exposes_exact_surface(tmp_path: Path) -> None:
    root = tmp_path / "runtime-canary"
    runtime = root / "runtime" / "python"
    runtime.parent.mkdir(parents=True)
    root.chmod(0o700)
    shutil.copy2(Path(sys.executable).resolve(), runtime)
    project = root / "project"
    project.mkdir(parents=True)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])
    script = r'''
import os, sys
from datetime import timedelta
from pathlib import Path
from runner.work_item_canary_runtime import serve_prepared_authoritative_canary
from runner.work_item_governance.activation import ActivationLeaseControlPlane
from runner.work_item_governance.bootstrap import FreshCanaryPaths, bootstrap_fresh_canary_preflight, build_activation_envelope, provision_private_bearer_token, revoke_private_bearer_token
from runner.work_item_governance.ids import new_stable_id
from runner.work_item_governance.preview import isoformat_utc, utc_now
from runner.work_item_governance.repository import SQLiteWorkItemLedger
from work_item_r2_helpers import all_permissions_principal, make_fixture
root=Path(os.environ["CANARY_ROOT"]).resolve(); project=root/"project"; port=int(os.environ["CANARY_PORT"])
paths=FreshCanaryPaths(
 canary_root=root, home=root/"home", xdg_config=root/"xdg-config", xdg_state=root/"xdg-state",
 xdg_cache=root/"xdg-cache", registry=root/"xdg-config/colameta/project-registry.json",
 project_root=project, settings=project/".colameta/settings.json",
 ledger=project/".colameta/ledger/work-items.sqlite3", backup=root/"evidence/pre-activation.sqlite3",
 token_file=root/"xdg-config/colameta/auth.json", activation_envelope=root/"control/activation.json",
 claimed_activation_envelope=root/"control/claimed.json", fixture_root=project/"synthetic-fixtures",
 runtime_executable=Path(sys.executable).resolve(), cwd=project,
)
token=provision_private_bearer_token(xdg_config_home=paths.xdg_config); lease_id=new_stable_id("activation_lease")
source={"core_baseline_commit":"53d8939af22b019b2df2b555b85869ac39c5bba2","implementation_commit":"d"*40,"implementation_tree":"e"*40,"wheel_sha256":"f"*64}
principal=all_permissions_principal(); principal_binding={"principal_id":principal.principal_id,"principal_kind":principal.principal_kind,"session_ref":principal.session_ref,"authenticated_by":"local_session","permissions":sorted(principal.granted_permissions)}
receipt=bootstrap_fresh_canary_preflight(paths=paths,authorization_id="WIG-P3-CANARY-A1-R2-TEST",authorization_digest="a"*64,activation_lease_id=lease_id,runtime_instance_nonce="n"*32,source_binding=source,principal_binding=principal_binding,project_name="r2-canary",port=port,token_provisioning=token)
fixture,_raw=make_fixture(project,principal); now=utc_now()
envelope=build_activation_envelope(preflight_receipt=receipt,synthetic_fixture=fixture,instance_id="r2-conformance",project_name="r2-canary",issued_at=isoformat_utc(now),not_before=isoformat_utc(now),expires_at=isoformat_utc(now+timedelta(seconds=1790)))
ledger=SQLiteWorkItemLedger(project); control=ActivationLeaseControlPlane(ledger,canary_root=root)
control.issue_prepared_lease(activation_envelope=envelope,synthetic_fixture=fixture,preflight_receipt=receipt,envelope_path=paths.activation_envelope)
os.environ["COLAMETA_WORK_ITEM_PRINCIPAL_ID"]=principal.principal_id
os.environ["COLAMETA_WORK_ITEM_PRINCIPAL_KIND"]=principal.principal_kind
os.environ["COLAMETA_WORK_ITEM_SESSION_REF"]=str(principal.session_ref)
os.environ["COLAMETA_WORK_ITEM_PERMISSIONS"]=" ".join(sorted(principal.granted_permissions))
serve_prepared_authoritative_canary(canary_root=root,project_root=project,lease_id=lease_id,activation_envelope_path=paths.activation_envelope,claimed_activation_envelope_path=paths.claimed_activation_envelope,port=port)
control.close(lease_id=lease_id,reason="ephemeral_conformance_complete")
evidence=control.export_closeout_evidence(lease_id=lease_id,destination=root/"evidence/lease")
revoke_private_bearer_token(auth_file=paths.token_file,canary_root=root)
(root/"evidence/closed.ok").write_text(str(evidence["lease_event_chain_verified"]).lower(),encoding="utf-8")
'''
    env = _isolated_subprocess_env(root)
    env.update({"CANARY_PORT": str(port)})
    process = subprocess.Popen(
        [str(runtime), "-c", script],
        cwd=project,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        auth_file = root / "xdg-config" / "colameta" / "auth.json"
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                pytest.fail(f"conformance process exited early: {stdout}\n{stderr}")
            if auth_file.is_file():
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=0.2):
                        break
                except (OSError, urllib.error.URLError):
                    pass
            time.sleep(0.05)
        else:
            pytest.fail("conformance process did not become ready")
        token = json.loads(auth_file.read_text(encoding="utf-8"))["auth_token"]
        assert _process_tcp_listeners(process.pid) == [("127.0.0.1", port)]
        assert _http_jsonrpc_status(port, None, "tools/list") == 401
        assert _http_jsonrpc_status(port, "wrong-token", "tools/list") == 401
        status, listed = _http_jsonrpc(port, token, "tools/list")
        assert status == 200
        assert tuple(item["name"] for item in listed["result"]["tools"]) == AUTHORITATIVE_CANARY_TOOLS
        _, status_call = _http_jsonrpc(
            port,
            token,
            "tools/call",
            {"name": "get_work_item_governance_status", "arguments": {}},
        )
        assert status_call["result"]["isError"] is False, status_call
        assert status_call["result"]["structuredContent"]["data"]["authoritative_canary"] is True
        assert status_call["result"]["structuredContent"]["data"]["gate_mode"] == "authoritative"
        _, hidden = _http_jsonrpc(
            port,
            token,
            "tools/call",
            {"name": "manage_git", "arguments": {}},
        )
        assert hidden["result"]["isError"] is True
        assert "denied by the active server exposure profile" in hidden["result"]["content"][0]["text"]
        _, direct = _http_jsonrpc(port, token, "get_work_item", {})
        assert direct["error"]["data"]["error_code"] == "direct_tool_method_disabled"
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/get_work_item_governance_status",
            data=b"{}",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(request, timeout=2)
        assert exc_info.value.code == 404
        with sqlite3.connect(
            root / "project" / ".colameta" / "ledger" / "work-items.sqlite3"
        ) as connection:
            assert connection.execute("SELECT COUNT(*) FROM work_items").fetchone()[0] == 0
            assert connection.execute("SELECT COUNT(*) FROM activation_lease_events").fetchone()[0] == 3
        _, guard_failure = _http_jsonrpc(
            port,
            token,
            "tools/call",
            {
                "name": "create_execution_attempt",
                "arguments": {
                    "command": {
                        "work_item_id": "wi_01900000-0000-7000-8000-000000000000",
                        "task_version": 1,
                        "status": "claimed",
                        "objective_ref": "synthetic://WIG-P3-AUTH-CANARY-A1-R2/objective/v1",
                        "metadata": {},
                        "external_refs": [],
                        "source_event_key": "r2:attempt:1",
                    }
                },
            },
        )
        assert guard_failure["result"]["isError"] is True
        stop_deadline = time.monotonic() + 5
        while process.poll() is None and time.monotonic() < stop_deadline:
            time.sleep(0.05)
        assert process.poll() == 0
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGINT)
        try:
            stdout, stderr = process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            pytest.fail(f"conformance process did not close: {stdout}\n{stderr}")
    assert process.returncode == 0, stderr
    assert (root / "evidence" / "closed.ok").read_text(encoding="utf-8") == "true"
    assert not (root / "xdg-config" / "colameta" / "auth.json").exists()
    with sqlite3.connect(root / "project" / ".colameta" / "ledger" / "work-items.sqlite3") as connection:
        assert connection.execute("SELECT status FROM activation_leases").fetchone()[0] == "closed"


def test_exported_lease_event_chain_is_independently_recomputed() -> None:
    events, snapshot, receipt = _closed_lease_event_chain()
    violations: list[str] = []
    _verify_exported_event_chain(
        events=events,
        snapshot=snapshot,
        lease_receipt=receipt,
        violations=violations,
    )
    assert violations == []

    events[2]["event_digest"] = "0" * 64
    violations = []
    _verify_exported_event_chain(
        events=events,
        snapshot=snapshot,
        lease_receipt=receipt,
        violations=violations,
    )
    assert "lease_event_digest:3" in violations
    assert "lease_event_chain:4" in violations
    assert "lease_event_root" in violations


@pytest.mark.parametrize(
    "payload",
    (
        '{"key":1,"key":2}',
        '{"value":NaN}',
    ),
)
def test_closeout_evidence_rejects_duplicate_keys_and_nonfinite_json(
    tmp_path: Path,
    payload: str,
) -> None:
    target = tmp_path / "invalid.json"
    target.write_text(payload, encoding="utf-8")
    with pytest.raises(ValueError):
        _load_strict_json(target)


def _gate(
    service: WorkItemApplicationService,
    principal: object,
    work_item_id: str,
    task_version: int,
    target_state: str,
    expected_state_version: int,
    idempotency_key: str,
    decision_ids: list[str] | None = None,
    artifact_ids: list[str] | None = None,
) -> dict[str, object]:
    return transition_apply(
        service,
        principal,  # type: ignore[arg-type]
        {
            "work_item_id": work_item_id,
            "task_version": task_version,
            "target_state": target_state,
            "expected_state_version": expected_state_version,
            "decision_ids": decision_ids or [],
            "evidence_artifact_ids": artifact_ids or [],
            "idempotency_key": idempotency_key,
        },
    )


def _decision(
    service: WorkItemApplicationService,
    principal: object,
    work_item_id: str,
    task_version: int,
    action: str,
    evidence: list[str],
    reason: str,
    source_event_key: str,
) -> str:
    return service.record_review_decision(
        {
            "work_item_id": work_item_id,
            "task_version": task_version,
            "action": action,
            "evidence_artifact_ids": evidence,
            "reason": reason,
            "source_event_key": source_event_key,
        },
        principal_context=principal,  # type: ignore[arg-type]
    )["decision"]["decision_id"]


def _isolated_subprocess_env(root: Path) -> dict[str, str]:
    return {
        **os.environ,
        "CANARY_ROOT": str(root),
        "HOME": str(root / "home"),
        "XDG_CONFIG_HOME": str(root / "xdg-config"),
        "XDG_STATE_HOME": str(root / "xdg-state"),
        "XDG_CACHE_HOME": str(root / "xdg-cache"),
        "PYTHONPATH": os.pathsep.join(
            (
                str(Path(__file__).resolve().parents[1]),
                str(Path(__file__).resolve().parent),
                str(Path(sys.prefix) / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"),
            )
        ),
    }


def _http_jsonrpc_status(port: int, token: str | None, method: str) -> int:
    try:
        return _http_jsonrpc(port, token, method)[0]
    except urllib.error.HTTPError as exc:
        return exc.code


def _http_jsonrpc(
    port: int,
    token: str | None,
    method: str,
    params: dict[str, object] | None = None,
) -> tuple[int, dict[str, object]]:
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    ).encode("utf-8")
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/mcp",
        data=body,
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=3) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def _process_tcp_listeners(pid: int) -> list[tuple[str, int]]:
    inodes: set[str] = set()
    for descriptor in (Path("/proc") / str(pid) / "fd").iterdir():
        try:
            target = os.readlink(descriptor)
        except OSError:
            continue
        if target.startswith("socket:[") and target.endswith("]"):
            inodes.add(target[8:-1])
    listeners: list[tuple[str, int]] = []
    for line in (Path("/proc") / str(pid) / "net" / "tcp").read_text(encoding="utf-8").splitlines()[1:]:
        fields = line.split()
        if fields[3] != "0A" or fields[9] not in inodes:
            continue
        address_hex, port_hex = fields[1].split(":")
        octets = bytes.fromhex(address_hex)
        address = ".".join(str(value) for value in reversed(octets))
        listeners.append((address, int(port_hex, 16)))
    return sorted(listeners)


def _create_v4_ledger(project: Path) -> None:
    ledger = SQLiteWorkItemLedger(project)
    ledger._ensure_storage_path()
    with sqlite3.connect(ledger.path, isolation_level=None) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        for version in range(1, 5):
            connection.execute("BEGIN IMMEDIATE")
            for statement in MIGRATIONS[version]:
                connection.execute(statement)
            connection.execute(f"PRAGMA user_version={version}")
            if version == 1:
                connection.execute(
                    "INSERT INTO ledger_meta(key,value,updated_at) VALUES('schema_version',?,'now')",
                    (str(version),),
                )
            else:
                connection.execute(
                    "UPDATE ledger_meta SET value=? WHERE key='schema_version'",
                    (str(version),),
                )
            connection.commit()


def _closed_lease_event_chain() -> tuple[list[dict[str, object]], dict[str, object], dict[str, object]]:
    lease_id = new_stable_id("activation_lease")
    identity = "1" * 64
    listener = "2" * 64
    request_context = "3" * 64
    definitions = (
        ("lease_issued", None, "prepared", 0, 0, None, None, None, None),
        ("process_claimed", "prepared", "claimed", 0, 1, identity, None, None, None),
        ("listener_attested", "claimed", "active", 1, 2, identity, listener, request_context, None),
        ("lease_write_frozen", "active", "write_frozen", 2, 3, identity, listener, request_context, "test_freeze"),
        ("lease_closed", "write_frozen", "closed", 3, 4, identity, listener, request_context, "test_close"),
    )
    events: list[dict[str, object]] = []
    previous: str | None = None
    for sequence, definition in enumerate(definitions, 1):
        event_type, before, after, version_before, version_after, claimed, attested, context, reason = definition
        event: dict[str, object] = {
            "schema_version": "work_item_activation_lease_event.v1",
            "lease_event_id": new_stable_id("activation_lease_event"),
            "lease_id": lease_id,
            "sequence": sequence,
            "event_type": event_type,
            "status_before": before,
            "status_after": after,
            "state_version_before": version_before,
            "state_version_after": version_after,
            "claimed_process_identity": claimed,
            "listener_attestation_digest": attested,
            "authenticated_request_context_binding_digest": context,
            "command_name": None,
            "source_event_key_digest": None,
            "domain_fact_delta_digest": None,
            "principal_binding_digest": None,
            "reason_code": reason,
            "previous_event_digest": previous,
            "event_digest_algorithm": "sha256(canonical_json(event_without_event_digest))",
            "created_at": "2026-07-12T00:00:00Z",
        }
        event["event_digest"] = canonical_sha256(event)
        previous = str(event["event_digest"])
        events.append(event)
    receipt = {
        "lease_id": lease_id,
        "lease_event_count": len(events),
        "lease_event_root_sha256": canonical_sha256([event["event_digest"] for event in events]),
        "final_status": "closed",
        "final_state_version": 4,
    }
    snapshot = {"status": "closed", "state_version": 4, "usage": {"lease_events": 5}}
    return events, snapshot, receipt
