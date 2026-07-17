from __future__ import annotations

import json
import os
import re
import secrets
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.request
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

import pytest

import runner.work_item_governance.pilot_candidate as candidate_module
import runner.work_item_governance.pilot_bootstrap as bootstrap_module
import runner.work_item_governance.pilot as pilot_module
import runner.mcp_server as mcp_server_module

from runner.mcp_server import (
    AUTHORITATIVE_CANARY_PRIVATE_CREDENTIAL_SOURCE,
    MCPPlanningBridgeServer,
    PlanningBridgeError,
)
from runner.work_item_pilot_conformance import (
    build_pilot_authentication_conformance_receipt,
    capture_pilot_safety_snapshot,
    measure_pilot_http_authentication,
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
    PILOT_TABLE_COUNT_QUERIES,
    PILOT_TOOLS,
    PilotActivationControlPlane,
    PilotActivationGuard,
    build_pilot_semantic_validation_receipt,
    build_pilot_execution_context,
    build_pilot_ledger_state,
    canonical_path_digest,
    verify_pilot_frozen_contract_resources,
    initial_execution_slot_usage,
    require_pilot_preflight_conformance_baseline,
    validate_pilot_durable_source_binding,
    validate_execution_authorization_receipt,
    verify_pilot_event_chain,
)
from runner.work_item_governance.pilot_bootstrap import (
    PilotBootstrapPaths,
    bootstrap_fresh_pilot_ledger,
    build_fresh_pilot_preflight_receipt,
)
from runner.work_item_governance.pilot_candidate import (
    write_validated_pilot_candidate_records,
)
from runner.work_item_governance.pilot_snapshot import (
    governed_pilot_conformance_ledger_snapshot,
)
from runner.work_item_governance.pilot_authorization import (
    ConsumedPilotAuthorization,
    PilotAuthorizationDecisionConsumer,
    consume_pilot_authorization_capability,
    require_consumed_pilot_authorization,
)
from runner.work_item_governance.preview import isoformat_utc, parse_timestamp, utc_now
from runner.work_item_governance.repository import MIGRATIONS, SQLiteWorkItemLedger
from runner.work_item_governance.schema_loader import (
    load_all_governance_schemas,
    load_governance_contract,
    validate_governance_record,
)
from runner.work_item_governance.source_binding import CORE_BASELINE_COMMIT


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


def test_execution_context_distinguishes_venv_launcher_from_resolved_interpreter(tmp_path: Path) -> None:
    interpreter_target = Path(sys.executable).resolve()
    interpreter_link = tmp_path / "runtime/bin/python"
    interpreter_link.parent.mkdir(parents=True)
    interpreter_link.symlink_to(interpreter_target)
    working_directory = tmp_path / "target"
    working_directory.mkdir()
    working_directory_link = tmp_path / "target-link"
    working_directory_link.symlink_to(working_directory, target_is_directory=True)
    source_binding = {
        "implementation_commit": "1" * 40,
        "implementation_tree": "2" * 40,
        "wheel_sha256": "3" * 64,
        "installed_inventory_sha256": "4" * 64,
        "durable_artifact_evidence_digest": "5" * 64,
        "durable_checkout_path_digest": "6" * 64,
        "durable_wheel_path_digest": "7" * 64,
    }

    linked_context = build_pilot_execution_context(
        source_binding=source_binding,
        python_executable=interpreter_link,
        cwd=working_directory_link,
    )
    resolved_context = build_pilot_execution_context(
        source_binding=source_binding,
        python_executable=interpreter_target,
        cwd=working_directory,
    )

    assert linked_context["python_executable"] == interpreter_link.as_posix()
    assert resolved_context["python_executable"] == interpreter_target.as_posix()
    assert linked_context["cwd"] == working_directory_link.as_posix()
    assert resolved_context["cwd"] == working_directory.as_posix()
    assert linked_context["runtime_binding_digest"] != resolved_context["runtime_binding_digest"]


def test_durable_source_binding_reproduces_candidate_inventory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = {
        "implementation_commit": "1" * 40,
        "implementation_tree": "2" * 40,
        "wheel_sha256": "3" * 64,
        "installed_inventory_sha256": "4" * 64,
        "durable_artifact_evidence_digest": "5" * 64,
        "durable_checkout_path_digest": "6" * 64,
        "durable_wheel_path_digest": "7" * 64,
    }

    class Attestation:
        source_binding = {
            "core_baseline_commit": pilot_module.CORE_BASELINE_COMMIT,
            "implementation_commit": expected["implementation_commit"],
            "implementation_tree": expected["implementation_tree"],
            "wheel_sha256": expected["wheel_sha256"],
        }
        file_manifest_digest = expected["installed_inventory_sha256"]

        @staticmethod
        def public_evidence() -> dict[str, str]:
            return {
                "artifact_evidence_digest": expected["durable_artifact_evidence_digest"],
                "checkout_path_digest": expected["durable_checkout_path_digest"],
                "wheel_path_digest": expected["durable_wheel_path_digest"],
            }

    observed: list[dict[str, str]] = []

    def reverify(_ledger: object, *, expected_source_binding: dict[str, str]) -> Attestation:
        observed.append(dict(expected_source_binding))
        return Attestation()

    monkeypatch.setattr(pilot_module, "reverify_runtime_source_binding", reverify)
    assert (
        validate_pilot_durable_source_binding(
            tmp_path,
            expected_source_binding=expected,
        )
        == expected
    )
    assert observed == [
        {
            "core_baseline_commit": pilot_module.CORE_BASELINE_COMMIT,
            "implementation_commit": expected["implementation_commit"],
            "implementation_tree": expected["implementation_tree"],
            "wheel_sha256": expected["wheel_sha256"],
        }
    ]

    Attestation.file_manifest_digest = "5" * 64
    with pytest.raises(WorkItemGovernanceError) as mismatch:
        validate_pilot_durable_source_binding(
            tmp_path,
            expected_source_binding=expected,
        )
    assert mismatch.value.code == "PILOT_DURABLE_SOURCE_BINDING_MISMATCH"
    assert mismatch.value.details == {"failed_bindings": ["installed_inventory_sha256"]}

    Attestation.file_manifest_digest = expected["installed_inventory_sha256"]
    original_public_evidence = Attestation.public_evidence
    Attestation.public_evidence = staticmethod(
        lambda: {
            **original_public_evidence(),
            "wheel_path_digest": "8" * 64,
        }
    )
    with pytest.raises(WorkItemGovernanceError) as path_mismatch:
        validate_pilot_durable_source_binding(
            tmp_path,
            expected_source_binding=expected,
        )
    assert path_mismatch.value.code == "PILOT_DURABLE_SOURCE_BINDING_MISMATCH"
    assert path_mismatch.value.details == {"failed_bindings": ["durable_wheel_path_digest"]}


def _v7_ledger(root: Path) -> SQLiteWorkItemLedger:
    legacy = SQLiteWorkItemLedger(root)
    legacy.initialize()
    legacy.migrate_to_v6()
    SQLiteWorkItemLedger(root, target_schema_version=6).migrate_to_v7()
    return SQLiteWorkItemLedger(root, target_schema_version=7)


def _ledger_physical_state(project: Path) -> list[dict[str, object]]:
    ledger_dir = project / ".colameta/ledger"
    directory = ledger_dir.stat()
    state: list[dict[str, object]] = [
        {
            "name": ".",
            "mode": directory.st_mode,
            "size": directory.st_size,
            "mtime_ns": directory.st_mtime_ns,
            "ctime_ns": directory.st_ctime_ns,
        }
    ]
    for path in sorted(ledger_dir.iterdir(), key=lambda value: value.name):
        measured = path.stat()
        state.append(
            {
                "name": path.name,
                "mode": measured.st_mode,
                "size": measured.st_size,
                "mtime_ns": measured.st_mtime_ns,
                "ctime_ns": measured.st_ctime_ns,
                "sha256": sha256_file(path),
            }
        )
    return state


@contextmanager
def _running_preflight_listener(
    *,
    server: MCPPlanningBridgeServer,
    project: Path,
    snapshot_parent: Path,
    token: str,
    token_file_sha256: str,
    token_evidence_digest: str,
    timeout_seconds: float = 10,
):
    snapshot_parent.mkdir(mode=0o700)
    source_before = _ledger_physical_state(project)
    with governed_pilot_conformance_ledger_snapshot(
        project,
        snapshot_parent=snapshot_parent,
    ) as ledger_snapshot:
        listener_errors: list[BaseException] = []

        def serve() -> None:
            try:
                server.serve_http(
                    host="127.0.0.1",
                    port=0,
                    auth_token=token,
                    auth_token_source=AUTHORITATIVE_CANARY_PRIVATE_CREDENTIAL_SOURCE,
                    auth_token_file_sha256=token_file_sha256,
                    auth_token_evidence_digest=token_evidence_digest,
                    auth_mode="token",
                    preflight_conformance=True,
                    preflight_conformance_timeout_seconds=timeout_seconds,
                    preflight_conformance_ledger_snapshot=ledger_snapshot,
                )
            except BaseException as exc:
                listener_errors.append(exc)

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 5
            while getattr(server, "_httpd", None) is None or not callable(server._token_transport_proof_validator):
                if listener_errors:
                    raise listener_errors[0]
                if not thread.is_alive() or time.monotonic() >= deadline:
                    raise AssertionError("actual Pilot MCP listener failed to start")
                time.sleep(0.01)
            port = int(server._httpd.server_address[1])
            yield ledger_snapshot, f"http://127.0.0.1:{port}", port
        finally:
            if getattr(server, "_httpd", None) is not None:
                server._httpd.shutdown()
            thread.join(timeout=5)
            assert not thread.is_alive()
            assert not listener_errors
    assert _ledger_physical_state(project) == source_before


def test_governed_conformance_snapshot_keeps_os_readonly_source_physically_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "pilot-project"
    project.mkdir()
    _v7_ledger(project)
    ledger_dir = project / ".colameta/ledger"
    for path in ledger_dir.iterdir():
        path.chmod(0o400)
    ledger_dir.chmod(0o500)
    source_before = _ledger_physical_state(project)
    snapshot_parent = tmp_path / "snapshots"
    snapshot_parent.mkdir(mode=0o700)
    import runner.work_item_governance.repository as repository_module

    real_connect = repository_module.sqlite3.connect
    sqlite_targets: list[str] = []

    def traced_connect(database: object, *args: object, **kwargs: object) -> sqlite3.Connection:
        sqlite_targets.append(str(database))
        return real_connect(database, *args, **kwargs)

    monkeypatch.setattr(repository_module.sqlite3, "connect", traced_connect)
    try:
        with governed_pilot_conformance_ledger_snapshot(
            project,
            snapshot_parent=snapshot_parent,
        ) as snapshot:
            snapshot.require_bound_to(project)
            evidence = snapshot.public_evidence()
            assert evidence["source_sqlite_opened"] is False
            assert evidence["copy_method"] == ("exclusive-maintenance-lock+O_RDONLY+O_NOFOLLOW+byte-copy")
            baseline = require_pilot_preflight_conformance_baseline(snapshot.project_root)
            assert not any(baseline["zero_fact_baseline"].values())
            assert _ledger_physical_state(project) == source_before
        assert _ledger_physical_state(project) == source_before
        assert list(snapshot_parent.iterdir()) == []
        assert sqlite_targets
        source_ledger = str(project / ".colameta/ledger/work-items.sqlite3")
        assert all(source_ledger not in target for target in sqlite_targets)
    finally:
        ledger_dir.chmod(0o700)
        for path in ledger_dir.iterdir():
            path.chmod(0o600)


def test_governed_conformance_snapshot_rejects_snapshot_byte_tampering(
    tmp_path: Path,
) -> None:
    project = tmp_path / "pilot-project"
    project.mkdir()
    _v7_ledger(project)
    source_before = _ledger_physical_state(project)
    snapshot_parent = tmp_path / "snapshots"
    snapshot_parent.mkdir(mode=0o700)
    with pytest.raises(WorkItemGovernanceError) as tamper_error:
        with governed_pilot_conformance_ledger_snapshot(
            project,
            snapshot_parent=snapshot_parent,
        ) as snapshot:
            snapshot_main = snapshot.project_root / ".colameta/ledger/work-items.sqlite3"
            with snapshot_main.open("r+b") as stream:
                stream.seek(100)
                original = stream.read(1)
                stream.seek(100)
                stream.write(bytes([original[0] ^ 1]))
    assert tamper_error.value.code == "PILOT_CONFORMANCE_SNAPSHOT_CHANGED"
    assert _ledger_physical_state(project) == source_before
    assert list(snapshot_parent.iterdir()) == []


@pytest.mark.parametrize(
    "invalid_path",
    [
        "{absolute}",
        "subdir/../fixture.txt",
        "./fixture.txt",
        "subdir//fixture.txt",
        "fixture.txt/",
        r"subdir\fixture.txt",
    ],
)
def test_pilot_path_manifests_require_canonical_relative_paths(
    tmp_path: Path,
    invalid_path: str,
) -> None:
    fixture = tmp_path / "fixture.txt"
    fixture.write_text("pilot\n", encoding="utf-8")
    if invalid_path == "{absolute}":
        invalid_path = str(fixture.resolve())
    manifests = {
        "protected": {"paths": [{"path": "fixture.txt", "sha256": sha256_file(fixture)}]},
        "allowed_read": {"paths": [invalid_path]},
        "allowed_write": {"paths": ["output"]},
    }

    with pytest.raises(WorkItemGovernanceError) as raised:
        bootstrap_module._measure_path_manifests(tmp_path.resolve(), manifests)

    assert raised.value.code == "PILOT_PROJECT_SNAPSHOT_MISMATCH"


def _write_test_pilot_candidate(
    monkeypatch: pytest.MonkeyPatch,
    output: Path,
    *,
    authorization: dict[str, object],
    scope: dict[str, object],
    execution: dict[str, object],
) -> Path:
    monkeypatch.setattr(
        candidate_module,
        "validate_execution_authorization_receipt",
        lambda value: value,
    )
    monkeypatch.setattr(
        candidate_module,
        "validate_pilot_scope_envelope",
        lambda value, **kwargs: value,
    )
    monkeypatch.setattr(
        candidate_module,
        "validate_pilot_authorization",
        lambda value, **kwargs: value,
    )
    write_validated_pilot_candidate_records(
        output,
        {
            "execution-authorization-receipt.json": execution,
            "scope-envelope.json": scope,
            "PILOT_AUTHORIZATION_TEMPLATE.json": authorization,
        },
    )
    return output


def _consumed_authority(
    monkeypatch: pytest.MonkeyPatch,
    root: Path,
    lease: dict[str, object],
) -> object:
    import runner.work_item_governance.pilot as pilot_module
    import runner.work_item_governance.pilot_authorization as authorization_module

    authorization = {
        "gate_id": lease["authorization_id"],
        "bindings": {
            "candidate_manifest_sha256": SHA,
            "authentication_conformance_receipt_digest": canonical_sha256({}),
        },
        "target": {
            "bind_address": lease["runtime_binding"]["bind_address"],
            "port": lease["runtime_binding"]["port"],
            "exposure_profile": lease["runtime_binding"]["exposure_profile"],
            "scope_mode": lease["runtime_binding"]["scope_mode"],
        },
    }
    ledger = SQLiteWorkItemLedger(root, target_schema_version=7)
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
            "authorization_receipt_schema_sha256": lease["scope_binding"][
                "execution_authorization_receipt_schema_sha256"
            ],
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
        "ledger": {
            "schema_version": 7,
            "database_generation": generation,
            "path_digest": canonical_path_digest(ledger.path),
        },
        "backup": {"database_generation": generation, "receipt_digest": SHA, "sha256": SHA},
    }
    monkeypatch.setattr(authorization_module, "validate_pilot_scope_envelope", lambda *args, **kwargs: args[0])
    monkeypatch.setattr(authorization_module, "validate_pilot_preflight", lambda value: value)
    monkeypatch.setattr(authorization_module, "validate_pilot_authorization", lambda value, **kwargs: value)
    monkeypatch.setattr(
        authorization_module,
        "validate_pilot_conformance_authorization_source",
        lambda *args, **kwargs: None,
    )
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
    candidate_dir = _write_test_pilot_candidate(
        monkeypatch,
        root / "candidate",
        authorization=authorization,
        scope=scope,
        execution=execution,
    )
    return PilotAuthorizationDecisionConsumer(
        candidate_dir=candidate_dir,
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
            "durable_artifact_evidence_digest": SHA,
            "durable_checkout_path_digest": SHA,
            "durable_wheel_path_digest": SHA,
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
            name: connection.execute("SELECT sql FROM sqlite_schema WHERE type='table' AND name=?", (name,)).fetchone()[
                0
            ]
            for name in ("activation_leases", "activation_lease_events")
        }
    legacy.migrate_to_v6()
    pilot = SQLiteWorkItemLedger(tmp_path, target_schema_version=6)
    assert pilot.schema_version() == 6
    with sqlite3.connect(pilot.path) as connection:
        after = {
            name: connection.execute("SELECT sql FROM sqlite_schema WHERE type='table' AND name=?", (name,)).fetchone()[
                0
            ]
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
        assert (
            connection.execute("SELECT COUNT(*) FROM sqlite_schema WHERE name='pilot_activation_leases'").fetchone()[0]
            == 0
        )


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
        assert (
            connection.execute("SELECT COUNT(*) FROM sqlite_schema WHERE name='pilot_activation_leases'").fetchone()[0]
            == 0
        )


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
        assert (
            connection.execute("SELECT COUNT(*) FROM sqlite_schema WHERE name='pilot_activation_leases'").fetchone()[0]
            == 0
        )


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


def test_schema_v7_authority_migration_is_explicit_atomic_and_append_only(tmp_path: Path) -> None:
    legacy = SQLiteWorkItemLedger(tmp_path)
    legacy.initialize()
    legacy.migrate_to_v6()
    with pytest.raises(WorkItemGovernanceError) as implicit:
        SQLiteWorkItemLedger(tmp_path, target_schema_version=7).initialize()
    assert implicit.value.code == "PILOT_AUTHORITY_EXPLICIT_MIGRATION_REQUIRED"
    receipt = SQLiteWorkItemLedger(tmp_path, target_schema_version=6).migrate_to_v7()
    assert receipt["from_schema_version"] == 6
    assert receipt["to_schema_version"] == 7
    ledger = SQLiteWorkItemLedger(tmp_path, target_schema_version=7)
    assert ledger.schema_version() == 7
    with sqlite3.connect(ledger.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM pilot_authorization_facts").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM pilot_authorization_claims").fetchone()[0] == 0


@pytest.mark.parametrize("metadata_mutation", ["missing", "mismatched"])
def test_schema_v7_migration_rejects_inconsistent_schema_metadata_atomically(
    tmp_path: Path,
    metadata_mutation: str,
) -> None:
    ledger = SQLiteWorkItemLedger(tmp_path)
    ledger.initialize()
    ledger.migrate_to_v6()
    with sqlite3.connect(ledger.path) as connection:
        if metadata_mutation == "missing":
            connection.execute("DELETE FROM ledger_meta WHERE key='schema_version'")
        else:
            connection.execute("UPDATE ledger_meta SET value='5' WHERE key='schema_version'")
        connection.commit()

    with pytest.raises(WorkItemGovernanceError) as error:
        SQLiteWorkItemLedger(tmp_path, target_schema_version=6).migrate_to_v7()
    assert error.value.code == "PILOT_AUTHORITY_MIGRATION_SOURCE_VERSION_INVALID"
    with sqlite3.connect(ledger.path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 6
        assert (
            connection.execute("SELECT COUNT(*) FROM sqlite_schema WHERE name='pilot_authorization_facts'").fetchone()[
                0
            ]
            == 0
        )


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
    ledger = _v7_ledger(tmp_path)
    lease = _lease(new_stable_id("work_item"))
    PilotActivationControlPlane(ledger).prepare_lease(
        lease, authority=_consumed_authority(monkeypatch, tmp_path, lease)
    )
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
    ledger = _v7_ledger(tmp_path)
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
    ledger = _v7_ledger(tmp_path)
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

    ledger = _v7_ledger(tmp_path)
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
        observed_listeners=[("127.0.0.1", 8799)],
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


def test_pilot_runtime_status_fails_closed_after_utc_or_monotonic_expiry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from runner.work_item_governance.activation import process_identity_inputs

    ledger = _v7_ledger(tmp_path)
    lease = _lease(new_stable_id("work_item"))
    lease["runtime_binding"]["expected_process_identity"] = process_identity_inputs(str(tmp_path))[
        "expected_process_identity"
    ]
    control = PilotActivationControlPlane(ledger)
    control.prepare_lease(lease, authority=_consumed_authority(monkeypatch, tmp_path, lease))
    claimed = control.claim_prepared_lease(
        lease_id=lease["lease_id"],
        envelope_path=str(tmp_path / "lease.json"),
        claimed_envelope_path=str(tmp_path / "lease.claimed.json"),
    )
    control.attest_listener(
        lease_id=lease["lease_id"],
        bind_address="127.0.0.1",
        port=8799,
        observed_listeners=[("127.0.0.1", 8799)],
    )
    deadline = claimed["runtime_binding"]["monotonic_deadline_ns"]
    assert isinstance(deadline, int)
    within_window = parse_timestamp(str(lease["window"]["not_before"]), "not_before") + timedelta(seconds=1)
    utc_expired = parse_timestamp(str(lease["window"]["expires_at"]), "expires_at")

    active_guard = PilotActivationGuard(
        ledger,
        now=lambda: within_window,
        monotonic_ns=lambda: deadline - 1,
    )
    assert active_guard.runtime_status()["effective_active"] is True
    assert active_guard.dispatch_authority_active() is True

    for expired_guard in (
        PilotActivationGuard(
            ledger,
            now=lambda: utc_expired,
            monotonic_ns=lambda: deadline - 1,
        ),
        PilotActivationGuard(
            ledger,
            now=lambda: within_window,
            monotonic_ns=lambda: deadline,
        ),
    ):
        status = expired_guard.runtime_status()
        assert status["status"] == "active"
        assert status["effective_active"] is False
        assert expired_guard.dispatch_authority_active() is False


def test_v6_raw_repository_write_and_maintenance_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ledger = _v7_ledger(tmp_path)
    lease = _lease(new_stable_id("work_item"))
    PilotActivationControlPlane(ledger).prepare_lease(
        lease, authority=_consumed_authority(monkeypatch, tmp_path, lease)
    )
    with pytest.raises(WorkItemGovernanceError) as error:
        with ledger.write_transaction() as connection:
            connection.execute("INSERT INTO ledger_meta(key,value,updated_at) VALUES('raw','x','2026-01-01T00:00:00Z')")
    assert error.value.code == "ACTIVATION_REPOSITORY_WRITE_DENIED"


def test_pilot_controller_capability_rejects_subclass_and_direct_service_bypass(tmp_path: Path) -> None:
    ledger = _v7_ledger(tmp_path)

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


def test_public_authorization_consumer_cannot_mint_repository_write_authority(tmp_path: Path) -> None:
    from runner.work_item_governance.pilot_authorization import _PilotAuthorizationPersistenceController

    ledger = _v7_ledger(tmp_path)
    consumer = PilotAuthorizationDecisionConsumer(
        candidate_dir=tmp_path / "candidate",
        decision_path=tmp_path / "decision.json",
        tombstone_path=tmp_path / "decision.tombstone.json",
        ledger=ledger,
    )
    assert not hasattr(consumer, "_authorize_control_write")
    with pytest.raises(WorkItemGovernanceError) as binding:
        ledger._bind_activation_controller(consumer)
    assert binding.value.code == "ACTIVATION_CONTROLLER_BINDING_INVALID"
    with pytest.raises(TypeError, match="internal one-operation capabilities"):
        _PilotAuthorizationPersistenceController(
            ledger=ledger,
            table="pilot_authorization_facts",
            _factory_seal=object(),
        )


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


def test_pilot_mcp_command_selects_only_bounded_pilot_composition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[dict[str, object]] = []

    def execute_stub(
        project_root: str,
        name: str,
        params: dict[str, object],
        **kwargs: object,
    ) -> dict[str, object]:
        observed.append(
            {
                "project_root": project_root,
                "name": name,
                "params": params,
                **kwargs,
            }
        )
        return {"result": "PASS"}

    monkeypatch.setattr(mcp_server_module, "execute_work_item_mcp_command", execute_stub)
    server = MCPPlanningBridgeServer(
        str(tmp_path),
        exposure_profile="authoritative_canary",
        work_item_scope_mode=PILOT_SCOPE_MODE,
    )

    assert server._tool_work_item_command("get_work_item_governance_status", {}) == {"result": "PASS"}
    assert observed == [
        {
            "project_root": str(tmp_path),
            "name": "get_work_item_governance_status",
            "params": {},
            "principal_context": None,
            "authoritative_canary": False,
            "bounded_single_project_pilot": True,
            "authenticated_request_proof": None,
        }
    ]


def test_frozen_storage_contract_matches_runtime_ddl() -> None:
    verify_pilot_frozen_contract_resources()
    assert PILOT_FROZEN_CONTRACT_DIGESTS["spec_manifest_digest"] == canonical_sha256(PILOT_FROZEN_RESOURCE_DIGESTS)
    contract = load_governance_contract("pilot_storage_schema_v6.v2")
    assert contract["migration"]["from_schema_version"] == 5
    assert contract["migration"]["to_schema_version"] == 6
    assert set(contract["new_tables"]) == {
        "pilot_activation_leases",
        "pilot_activation_lease_events",
    }
    assert len(contract["required_ddl"]) == len(MIGRATIONS[6])
    authority_contract = load_governance_contract("pilot_storage_schema_v7.v1")
    assert authority_contract["migration"]["from_schema_version"] == 6
    assert authority_contract["migration"]["to_schema_version"] == 7
    assert set(authority_contract["new_tables"]) == {
        "pilot_authorization_facts",
        "pilot_authorization_claims",
    }
    assert len(authority_contract["required_ddl"]) == len(MIGRATIONS[7])
    negative = load_governance_contract("pilot_negative_test_matrix.v4")
    assert len(negative["tests"]) == 96
    assert len({item["id"] for item in negative["tests"]}) == 96
    assert all(isinstance(item["expected"], str) and item["expected"] for item in negative["tests"])


def test_pilot_scope_schema_uses_runtime_attested_core_baseline() -> None:
    schema = load_all_governance_schemas()["pilot_scope_envelope.v4"]
    source_properties = schema["properties"]["source_binding"]["properties"]

    assert source_properties["core_baseline_commit"]["const"] == CORE_BASELINE_COMMIT
    assert source_properties["implementation_commit"]["allOf"][1]["not"]["const"] == CORE_BASELINE_COMMIT


def test_pilot_create_preview_uses_scope_preallocated_work_item_id(tmp_path: Path) -> None:
    from runner.work_item_governance.service import WorkItemApplicationService

    proposed_work_item_id = new_stable_id("work_item")

    class ScopedPreviewGuard:
        def authorize_preview(self, **kwargs: object) -> str:
            assert kwargs["command_name"] == "apply_work_item_create"
            return proposed_work_item_id

    service = WorkItemApplicationService(tmp_path, enabled=True, authoritative_transitions=True)
    service.activation_guard = ScopedPreviewGuard()  # type: ignore[assignment]

    result = service.preview_work_item_create(
        {
            "origin": {"kind": "manual", "ref": "pilot-scoped-preview", "snapshot_digest": SHA},
            "objective": "pilot scoped create",
        }
    )

    assert result["proposed_work_item_id"] == proposed_work_item_id
    assert result["preview"]["generated_ids"] == {"work_item_id": proposed_work_item_id}


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
            failed_rules=[
                {"rule_id": "ART-001", "error_code": "PILOT_ARTIFACT_POLICY_VIOLATION", "evidence_digest": SHA}
            ],
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
                "fact_reconciliation_contract_digest": PILOT_FROZEN_CONTRACT_DIGESTS[
                    "fact_reconciliation_contract_digest"
                ],
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
        assert set(PILOT_DENIED_WRITES).issuperset({"create_delivery_receipt", "record_outbox_delivery_result"})
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

        def public_evidence(self) -> dict[str, object]:
            return {
                "artifact_evidence_digest": self.evidence_digest,
                "checkout_path_digest": canonical_sha256({"resolved_posix_path": self.checkout_root.as_posix()}),
                "wheel_path_digest": canonical_sha256({"resolved_posix_path": self.wheel_artifact.as_posix()}),
            }

    attestation = FakeAttestation()
    monkeypatch.setattr(bootstrap_module, "verify_runtime_source_artifacts", lambda **_kwargs: attestation)
    receipt = bootstrap_fresh_pilot_ledger(
        paths=paths,
        port=48791,
        source_checkout=project,
        wheel_artifact=wheel,
    )
    assert receipt["database_generation"] == receipt["backup"]["database_generation"] == 1
    assert receipt["backup"]["schema_version"] == 7
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
        "durable_artifact_evidence_digest": attestation.evidence_digest,
        "durable_checkout_path_digest": attestation.public_evidence()["checkout_path_digest"],
        "durable_wheel_path_digest": attestation.public_evidence()["wheel_path_digest"],
    }
    execution_context = build_pilot_execution_context(
        source_binding=source_binding,
        python_executable=sys.executable,
        cwd=project,
    )
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
    ledger_state = build_pilot_ledger_state(
        path_digest=receipt["ledger_path_digest"],
        schema_version=7,
        database_generation=receipt["database_generation"],
        zero_fact_baseline=receipt["zero_fact_baseline"],
        integrity_check="ok",
        foreign_key_violations=[],
        token_evidence_digest=receipt["token_evidence_digest"],
        source_artifact_evidence_digest=attestation.evidence_digest,
    )
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
        "execution_authorization_receipt_schema_sha256": PILOT_FROZEN_CONTRACT_DIGESTS[
            "execution_authorization_receipt_schema_sha256"
        ],
        "execution_authorization_receipt_digest": SHA,
        "authentication_conformance_receipt_schema_sha256": PILOT_FROZEN_CONTRACT_DIGESTS[
            "authentication_conformance_receipt_schema_sha256"
        ],
        "expiry_conformance_receipt_schema_sha256": PILOT_FROZEN_CONTRACT_DIGESTS[
            "expiry_conformance_receipt_schema_sha256"
        ],
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
            "no_token_response_digest": SHA,
            "wrong_token_response_digest": SHA,
            "correct_token_response_digest": SHA,
            "request_capability_non_json": True,
            "request_capability_single_use": True,
            "proof_issued_delta": 2,
            "proof_activated_delta": 2,
            "proof_retired_delta": 2,
            "active_proof_count_after": 0,
        },
        "surface": {
            "exposure_profile": "authoritative_canary",
            "scope_mode": PILOT_SCOPE_MODE,
            "preflight_conformance_only": True,
            "authenticated_tool_call_error_code": "PREFLIGHT_CONFORMANCE_TOOL_CALL_DENIED",
            "visible_tool_count": len(PILOT_TOOLS),
            "visible_tool_set_digest": canonical_sha256(list(PILOT_TOOLS)),
            "tool_list_response_digest": SHA,
            "resources_list_response_digest": SHA,
            "resource_read_error_code": "resources_disabled",
            "hidden_tool_error_code": "TOOL_NOT_EXPOSED",
            "alternate_dispatch_error_code": "legacy_method_alias_disabled",
            "actions_response_digest": SHA,
            "actions_error_code": "ACTIONS_DISABLED",
            "listener_instance_digest": SHA,
            "server_binding_digest": SHA,
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
    runtime_bin = root / "runtime/bin"
    runtime_bin.mkdir(parents=True, mode=0o700)
    (runtime_bin / "python").symlink_to(Path(sys.executable).resolve())
    snapshot_parent = root / "preflight-snapshots"
    snapshot_parent.mkdir(mode=0o700)
    snapshot_manager = governed_pilot_conformance_ledger_snapshot(
        project,
        snapshot_parent=snapshot_parent,
    )
    ledger_snapshot = snapshot_manager.__enter__()
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
        ledger_snapshot=ledger_snapshot,
    )
    import runner.work_item_governance.repository as repository_module

    real_connect = repository_module.sqlite3.connect
    sqlite_targets: list[str] = []

    def traced_connect(database: object, *args: object, **kwargs: object) -> sqlite3.Connection:
        sqlite_targets.append(str(database))
        return real_connect(database, *args, **kwargs)

    monkeypatch.setattr(repository_module.sqlite3, "connect", traced_connect)
    preflight = build_fresh_pilot_preflight_receipt(**preflight_kwargs)
    assert preflight["result"] == "PASS"
    assert preflight["ledger"]["path"] == receipt["ledger_path"]
    assert preflight["authentication"]["principal_binding_digest"] == canonical_sha256(principal_binding)
    assert preflight["execution_context"] == execution_context
    assert ledger_snapshot.public_evidence()["source_sqlite_opened"] is False
    assert sqlite_targets
    assert all(str(Path(receipt["ledger_path"])) not in target for target in sqlite_targets)
    assert any(str(ledger_snapshot.project_root) in target for target in sqlite_targets)
    mismatched_snapshot = replace(ledger_snapshot, source_project_root=root / "wrong-project")
    with pytest.raises(WorkItemGovernanceError) as snapshot_error:
        build_fresh_pilot_preflight_receipt(
            **{**preflight_kwargs, "ledger_snapshot": mismatched_snapshot}
        )
    assert snapshot_error.value.code == "PILOT_CONFORMANCE_SNAPSHOT_INVALID"
    forged_context = {**execution_context, "runtime_binding_digest": SHA}
    with pytest.raises(WorkItemGovernanceError) as runtime_error:
        build_fresh_pilot_preflight_receipt(**{**preflight_kwargs, "execution_context": forged_context})
    assert runtime_error.value.code == "PILOT_PREFLIGHT_MEASUREMENT_FAILED"
    legacy_context = {
        **execution_context,
        "runtime_dependency_attestation_digest": SHA,
    }
    with pytest.raises(WorkItemGovernanceError) as legacy_context_error:
        build_fresh_pilot_preflight_receipt(
            **{**preflight_kwargs, "execution_context": legacy_context}
        )
    assert legacy_context_error.value.code == "PILOT_PREFLIGHT_MEASUREMENT_FAILED"
    executable_link = root / "legacy-runtime-python"
    executable_link.symlink_to(Path(sys.executable).resolve())
    unresolved_context = dict(execution_context)
    unresolved_context["python_executable"] = executable_link.absolute().as_posix()
    unresolved_context["runtime_binding_digest"] = canonical_sha256(
        {key: value for key, value in unresolved_context.items() if key != "runtime_binding_digest"}
    )
    with pytest.raises(WorkItemGovernanceError) as path_context_error:
        build_fresh_pilot_preflight_receipt(
            **{**preflight_kwargs, "execution_context": unresolved_context}
        )
    assert path_context_error.value.code == "PILOT_PREFLIGHT_MEASUREMENT_FAILED"
    mismatched_conformance = json.loads(json.dumps(authentication_receipt))
    mismatched_conformance["runtime_binding"]["runtime_binding_digest"] = SHA
    mismatched_conformance_bindings = {
        **bindings,
        "authentication_conformance_receipt_digest": canonical_sha256(mismatched_conformance),
    }
    with pytest.raises(WorkItemGovernanceError) as receipt_context_error:
        build_fresh_pilot_preflight_receipt(
            **{
                **preflight_kwargs,
                "authentication_conformance_receipt": mismatched_conformance,
                "bindings": mismatched_conformance_bindings,
            }
        )
    assert receipt_context_error.value.code == "PILOT_PREFLIGHT_MEASUREMENT_FAILED"
    forged_project = {**measured_project, "snapshot_digest": SHA}
    with pytest.raises(WorkItemGovernanceError) as project_error:
        build_fresh_pilot_preflight_receipt(**{**preflight_kwargs, "project": forged_project})
    assert project_error.value.code == "PILOT_PREFLIGHT_MEASUREMENT_FAILED"
    leaked_token = json.loads(paths.token_file.read_text(encoding="utf-8"))["auth_token"]
    leaked_evidence = root / "evidence/leaked-token.txt"
    leaked_evidence.write_text(leaked_token, encoding="utf-8")
    leaked_evidence.chmod(0o600)
    with pytest.raises(WorkItemGovernanceError) as token_error:
        build_fresh_pilot_preflight_receipt(**preflight_kwargs)
    assert token_error.value.code == "PILOT_PREFLIGHT_MEASUREMENT_FAILED"
    leaked_evidence.unlink()
    leaked_log = paths.xdg_state_home / "pilot.log"
    leaked_log.write_text(leaked_token, encoding="utf-8")
    leaked_log.chmod(0o600)
    with pytest.raises(WorkItemGovernanceError) as log_error:
        build_fresh_pilot_preflight_receipt(**preflight_kwargs)
    assert log_error.value.code == "PILOT_PREFLIGHT_MEASUREMENT_FAILED"
    leaked_log.unlink()
    leaked_data = paths.xdg_data_home / "closeout.json"
    leaked_data.write_text(leaked_token, encoding="utf-8")
    leaked_data.chmod(0o600)
    with pytest.raises(WorkItemGovernanceError) as bundle_error:
        build_fresh_pilot_preflight_receipt(**preflight_kwargs)
    assert bundle_error.value.code == "PILOT_PREFLIGHT_MEASUREMENT_FAILED"
    leaked_data.unlink()
    public_evidence = root / "evidence/public.txt"
    public_evidence.write_text("secret-free", encoding="utf-8")
    public_evidence.chmod(0o644)
    with pytest.raises(WorkItemGovernanceError) as evidence_mode_error:
        build_fresh_pilot_preflight_receipt(**preflight_kwargs)
    assert evidence_mode_error.value.code == "PILOT_PREFLIGHT_MEASUREMENT_FAILED"
    public_evidence.unlink()
    oversized_evidence = root / "evidence/oversized-token.log"
    with oversized_evidence.open("wb") as handle:
        handle.truncate(16 * 1024 * 1024 + 1)
        handle.seek(0)
        handle.write(leaked_token.encode("utf-8"))
    oversized_evidence.chmod(0o600)
    with pytest.raises(WorkItemGovernanceError) as oversized_error:
        build_fresh_pilot_preflight_receipt(**preflight_kwargs)
    assert oversized_error.value.code == "PILOT_PREFLIGHT_MEASUREMENT_FAILED"
    oversized_evidence.unlink()
    suffix_bypass = root / "evidence/token-leak-wal"
    suffix_bypass.write_text(leaked_token, encoding="utf-8")
    suffix_bypass.chmod(0o600)
    with pytest.raises(WorkItemGovernanceError) as suffix_error:
        build_fresh_pilot_preflight_receipt(**preflight_kwargs)
    assert suffix_error.value.code == "PILOT_PREFLIGHT_MEASUREMENT_FAILED"
    suffix_bypass.unlink()
    outside_evidence = tmp_path / "outside-evidence"
    outside_evidence.mkdir(mode=0o700)
    outside_payload = outside_evidence / "credential.log"
    outside_payload.write_text(leaked_token, encoding="utf-8")
    outside_payload.chmod(0o600)
    symlink_escape = root / "evidence/escaped-evidence"
    symlink_escape.symlink_to(outside_evidence, target_is_directory=True)
    with pytest.raises(WorkItemGovernanceError) as symlink_error:
        build_fresh_pilot_preflight_receipt(**preflight_kwargs)
    assert symlink_error.value.code == "PILOT_PREFLIGHT_MEASUREMENT_FAILED"
    symlink_escape.unlink()
    race_directory = root / "evidence/race"
    race_directory.mkdir(mode=0o700)
    race_payload = race_directory / "safe.txt"
    race_payload.write_text("secret-free", encoding="utf-8")
    race_payload.chmod(0o600)
    displaced_directory = root / "evidence/race-original"
    original_open = os.open
    swapped = False

    def swap_directory_before_open(
        path: str | bytes | int,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        if path == "race" and dir_fd is not None and not swapped:
            swapped = True
            race_directory.rename(displaced_directory)
            race_directory.symlink_to(outside_evidence, target_is_directory=True)
        return original_open(path, flags, mode, dir_fd=dir_fd)

    try:
        with monkeypatch.context() as race_patch:
            race_patch.setattr(bootstrap_module.os, "open", swap_directory_before_open)
            with pytest.raises(WorkItemGovernanceError) as directory_race_error:
                build_fresh_pilot_preflight_receipt(**preflight_kwargs)
        assert directory_race_error.value.code == "PILOT_PREFLIGHT_MEASUREMENT_FAILED"
        assert swapped is True
    finally:
        if race_directory.is_symlink():
            race_directory.unlink()
        if displaced_directory.exists():
            displaced_directory.rename(race_directory)
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
    snapshot_manager.__exit__(None, None, None)
    assert list(snapshot_parent.iterdir()) == []
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
    surface = {
        **measure_pilot_transport_surface(server),
        "preflight_conformance_only": True,
        "authenticated_tool_call_error_code": "PREFLIGHT_CONFORMANCE_TOOL_CALL_DENIED",
        "actions_response_digest": SHA,
        "actions_error_code": "ACTIONS_DISABLED",
        "listener_instance_digest": SHA,
        "server_binding_digest": SHA,
    }
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
            "durable_artifact_evidence_digest": SHA,
            "durable_checkout_path_digest": SHA,
            "durable_wheel_path_digest": SHA,
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
            "no_token_response_digest": SHA,
            "wrong_token_response_digest": SHA,
            "correct_token_response_digest": SHA,
            "request_capability_non_json": True,
            "request_capability_single_use": True,
            "proof_issued_delta": 2,
            "proof_activated_delta": 2,
            "proof_retired_delta": 2,
            "active_proof_count_after": 0,
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


def test_http_authentication_conformance_is_measured_from_loopback_responses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = f"mvr_{secrets.token_urlsafe(32)}"
    project = tmp_path / "pilot-project"
    project.mkdir()
    ledger = _v7_ledger(project)
    token_file = tmp_path / "auth.json"
    token_file.write_text(json.dumps({"schema_version": 1, "auth_token": token}), encoding="utf-8")
    token_file.chmod(0o600)
    token_file_sha256 = sha256_file(token_file)
    token_evidence_digest = canonical_sha256(
        {"token_file_sha256": token_file_sha256, "token_file_path_digest": canonical_path_digest(token_file)}
    )
    with ledger.write_transaction() as connection:
        connection.execute(
            "INSERT INTO ledger_meta(key,value,updated_at) VALUES(?,?,?)",
            ("authoritative_canary_token_file_sha256", token_file_sha256, isoformat_utc(utc_now())),
        )
        connection.execute(
            "INSERT INTO ledger_meta(key,value,updated_at) VALUES(?,?,?)",
            ("authoritative_canary_token_evidence_digest", token_evidence_digest, isoformat_utc(utc_now())),
        )
    safety = {
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
    }
    import runner.work_item_pilot_conformance as conformance_module

    monkeypatch.setattr(conformance_module, "measure_pilot_safety_conformance", lambda **_kwargs: safety)
    durable_source_checks: list[dict[str, object]] = []
    monkeypatch.setattr(
        conformance_module,
        "validate_pilot_durable_source_binding",
        lambda _project_root, *, expected_source_binding: durable_source_checks.append(dict(expected_source_binding)),
    )
    server = MCPPlanningBridgeServer(
        str(project),
        exposure_profile="authoritative_canary",
        work_item_scope_mode=PILOT_SCOPE_MODE,
    )
    conformance_source_binding = {
        "implementation_commit": "1" * 40,
        "implementation_tree": "2" * 40,
        "wheel_sha256": SHA,
        "installed_inventory_sha256": SHA,
        "durable_artifact_evidence_digest": SHA,
        "durable_checkout_path_digest": SHA,
        "durable_wheel_path_digest": SHA,
    }
    conformance_execution_context = build_pilot_execution_context(
        source_binding=conformance_source_binding,
        python_executable=sys.executable,
        cwd=project,
    )
    with _running_preflight_listener(
        server=server,
        project=project,
        snapshot_parent=tmp_path / "http-conformance-snapshots",
        token=token,
        token_file_sha256=token_file_sha256,
        token_evidence_digest=token_evidence_digest,
    ) as (ledger_snapshot, endpoint, port):
        conformance_baseline = require_pilot_preflight_conformance_baseline(ledger_snapshot.project_root)
        conformance_ledger_state = build_pilot_ledger_state(
            path_digest=ledger_snapshot.source_ledger_path_digest,
            schema_version=conformance_baseline["schema_version"],
            database_generation=conformance_baseline["database_generation"],
            zero_fact_baseline=conformance_baseline["zero_fact_baseline"],
            integrity_check=conformance_baseline["integrity_check"],
            foreign_key_violations=conformance_baseline["foreign_key_violations"],
            token_evidence_digest=token_evidence_digest,
            source_artifact_evidence_digest=conformance_source_binding["durable_artifact_evidence_digest"],
        )
        legacy_execution_context = {
            **conformance_execution_context,
            "runtime_dependency_attestation_digest": SHA,
        }
        with pytest.raises(WorkItemGovernanceError) as noncanonical_context:
            build_pilot_authentication_conformance_receipt(
                server=server,
                endpoint=endpoint,
                correct_token=token,
                token_file=token_file,
                token_binding={
                    "authoritative_canary_token_file_sha256": token_file_sha256,
                    "authoritative_canary_token_evidence_digest": token_evidence_digest,
                },
                source_binding=conformance_source_binding,
                execution_context=legacy_execution_context,
                runtime_binding={
                    "runtime_binding_digest": conformance_execution_context["runtime_binding_digest"],
                    "scope_envelope_digest": SHA,
                    "ledger_state_digest": canonical_sha256(conformance_ledger_state),
                    "token_file_path_digest": canonical_path_digest(token_file),
                },
                expected_safety_snapshot=safety,
                project_root=project,
                registry_path=tmp_path / "registry.json",
                stable_promotion_root=tmp_path / "stable",
                port=port,
                ledger_snapshot=ledger_snapshot,
            )
        assert noncanonical_context.value.code == "PILOT_AUTHENTICATION_CONFORMANCE_INVALID"
        receipt = build_pilot_authentication_conformance_receipt(
            server=server,
            endpoint=endpoint,
            correct_token=token,
            token_file=token_file,
            token_binding={
                "authoritative_canary_token_file_sha256": token_file_sha256,
                "authoritative_canary_token_evidence_digest": token_evidence_digest,
            },
            source_binding=conformance_source_binding,
            execution_context=conformance_execution_context,
            runtime_binding={
                "runtime_binding_digest": conformance_execution_context["runtime_binding_digest"],
                "scope_envelope_digest": SHA,
                "ledger_state_digest": canonical_sha256(conformance_ledger_state),
                "token_file_path_digest": canonical_path_digest(token_file),
            },
            expected_safety_snapshot=safety,
            project_root=project,
            registry_path=tmp_path / "registry.json",
            stable_promotion_root=tmp_path / "stable",
            port=port,
            ledger_snapshot=ledger_snapshot,
        )

        def reject_durable_source(
            _project_root: object,
            *,
            expected_source_binding: dict[str, object],
        ) -> None:
            del expected_source_binding
            raise WorkItemGovernanceError(
                "RUNTIME_SOURCE_EVIDENCE_MISMATCH",
                "test durable source mismatch",
            )

        monkeypatch.setattr(
            conformance_module,
            "validate_pilot_durable_source_binding",
            reject_durable_source,
        )
        with pytest.raises(WorkItemGovernanceError) as durable_source_mismatch:
            build_pilot_authentication_conformance_receipt(
                server=server,
                endpoint=endpoint,
                correct_token=token,
                token_file=token_file,
                token_binding={
                    "authoritative_canary_token_file_sha256": token_file_sha256,
                    "authoritative_canary_token_evidence_digest": token_evidence_digest,
                },
                source_binding=receipt["source_binding"],
                execution_context=conformance_execution_context,
                runtime_binding=receipt["runtime_binding"],
                expected_safety_snapshot=safety,
                project_root=project,
                registry_path=tmp_path / "registry.json",
                stable_promotion_root=tmp_path / "stable",
                port=port,
                ledger_snapshot=ledger_snapshot,
            )
        assert durable_source_mismatch.value.code == "RUNTIME_SOURCE_EVIDENCE_MISMATCH"
        with pytest.raises(WorkItemGovernanceError) as durable_mismatch:
            build_pilot_authentication_conformance_receipt(
                server=server,
                endpoint=endpoint,
                correct_token=token,
                token_file=token_file,
                token_binding={
                    "authoritative_canary_token_file_sha256": token_file_sha256,
                    "authoritative_canary_token_evidence_digest": "f" * 64,
                },
                source_binding=conformance_source_binding,
                execution_context=conformance_execution_context,
                runtime_binding={
                    "runtime_binding_digest": conformance_execution_context["runtime_binding_digest"],
                    "scope_envelope_digest": SHA,
                    "ledger_state_digest": canonical_sha256(conformance_ledger_state),
                    "token_file_path_digest": canonical_path_digest(token_file),
                },
                expected_safety_snapshot=safety,
                project_root=project,
                registry_path=tmp_path / "registry.json",
                stable_promotion_root=tmp_path / "stable",
                port=port,
                ledger_snapshot=ledger_snapshot,
            )
        assert durable_mismatch.value.code == "PILOT_AUTHENTICATION_CONFORMANCE_INVALID"
    assert receipt["result"] == "PASS"
    assert receipt["authentication"]["token_ledger_binding_valid"] is True
    assert receipt["authentication"]["proof_issued_delta"] == 2
    assert receipt["authentication"]["proof_retired_delta"] == 2
    assert durable_source_checks == [receipt["source_binding"]]


def test_preflight_conformance_listener_closes_authority_ordering_without_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = f"mvr_{secrets.token_urlsafe(32)}"
    project = tmp_path / "pilot-project"
    project.mkdir()
    ledger = _v7_ledger(project)
    token_file = tmp_path / "auth.json"
    token_file.write_text(json.dumps({"schema_version": 1, "auth_token": token}), encoding="utf-8")
    token_file.chmod(0o600)
    token_file_sha256 = sha256_file(token_file)
    token_evidence_digest = canonical_sha256(
        {"token_file_sha256": token_file_sha256, "token_file_path_digest": canonical_path_digest(token_file)}
    )
    with ledger.write_transaction() as connection:
        connection.execute(
            "INSERT INTO ledger_meta(key,value,updated_at) VALUES(?,?,?)",
            ("authoritative_canary_token_file_sha256", token_file_sha256, isoformat_utc(utc_now())),
        )
        connection.execute(
            "INSERT INTO ledger_meta(key,value,updated_at) VALUES(?,?,?)",
            ("authoritative_canary_token_evidence_digest", token_evidence_digest, isoformat_utc(utc_now())),
        )
    safety = {
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
    }
    import runner.work_item_pilot_conformance as conformance_module

    monkeypatch.setattr(conformance_module, "measure_pilot_safety_conformance", lambda **_kwargs: safety)
    monkeypatch.setattr(
        conformance_module,
        "validate_pilot_durable_source_binding",
        lambda _project_root, *, expected_source_binding: dict(expected_source_binding),
    )
    server = MCPPlanningBridgeServer(
        str(project),
        exposure_profile="authoritative_canary",
        work_item_scope_mode=PILOT_SCOPE_MODE,
    )
    rejected_lease_server = MCPPlanningBridgeServer(
        str(project),
        exposure_profile="authoritative_canary",
        work_item_scope_mode=PILOT_SCOPE_MODE,
    )
    ordering_source_binding = {
        "implementation_commit": "1" * 40,
        "implementation_tree": "2" * 40,
        "wheel_sha256": SHA,
        "installed_inventory_sha256": SHA,
        "durable_artifact_evidence_digest": SHA,
        "durable_checkout_path_digest": SHA,
        "durable_wheel_path_digest": SHA,
    }
    ordering_execution_context = build_pilot_execution_context(
        source_binding=ordering_source_binding,
        python_executable=sys.executable,
        cwd=project,
    )
    with pytest.raises(PlanningBridgeError, match="forbids Activation Lease inputs"):
        rejected_lease_server.serve_http(
            host="127.0.0.1",
            port=0,
            auth_token=token,
            auth_token_source=AUTHORITATIVE_CANARY_PRIVATE_CREDENTIAL_SOURCE,
            auth_token_file_sha256=token_file_sha256,
            auth_token_evidence_digest=token_evidence_digest,
            auth_mode="token",
            activation_lease_id="lease_forbidden",
            preflight_conformance=True,
        )
    with _running_preflight_listener(
        server=server,
        project=project,
        snapshot_parent=tmp_path / "ordering-conformance-snapshots",
        token=token,
        token_file_sha256=token_file_sha256,
        token_evidence_digest=token_evidence_digest,
    ) as (ledger_snapshot, endpoint, port):
        baseline = require_pilot_preflight_conformance_baseline(ledger_snapshot.project_root)
        assert not any(baseline["zero_fact_baseline"].values())
        listener_snapshot = server._pilot_http_conformance_snapshot()
        assert listener_snapshot["preflight_conformance_only"] is True
        assert listener_snapshot["ledger_snapshot_binding_digest"] == ledger_snapshot.binding_digest
        ordering_ledger_state = build_pilot_ledger_state(
            path_digest=ledger_snapshot.source_ledger_path_digest,
            schema_version=baseline["schema_version"],
            database_generation=baseline["database_generation"],
            zero_fact_baseline=baseline["zero_fact_baseline"],
            integrity_check=baseline["integrity_check"],
            foreign_key_violations=baseline["foreign_key_violations"],
            token_evidence_digest=token_evidence_digest,
            source_artifact_evidence_digest=ordering_source_binding["durable_artifact_evidence_digest"],
        )

        receipt = build_pilot_authentication_conformance_receipt(
            server=server,
            endpoint=endpoint,
            correct_token=token,
            token_file=token_file,
            token_binding={
                "authoritative_canary_token_file_sha256": token_file_sha256,
                "authoritative_canary_token_evidence_digest": token_evidence_digest,
            },
            source_binding=ordering_source_binding,
            execution_context=ordering_execution_context,
            runtime_binding={
                "runtime_binding_digest": ordering_execution_context["runtime_binding_digest"],
                "scope_envelope_digest": SHA,
                "ledger_state_digest": canonical_sha256(ordering_ledger_state),
                "token_file_path_digest": canonical_path_digest(token_file),
            },
            expected_safety_snapshot=safety,
            project_root=project,
            registry_path=tmp_path / "registry.json",
            stable_promotion_root=tmp_path / "stable",
            port=port,
            ledger_snapshot=ledger_snapshot,
        )
        assert receipt["result"] == "PASS"
        assert receipt["surface"]["authenticated_tool_call_error_code"] == "PREFLIGHT_CONFORMANCE_TOOL_CALL_DENIED"

        original_call_tool = server._call_tool
        monkeypatch.setattr(
            server,
            "_call_tool",
            lambda name, _arguments, **_kwargs: {
                "ok": True,
                "tool": name,
                "data": {"unexpected_dispatch": True},
            },
        )
        with pytest.raises(WorkItemGovernanceError) as live_denial_error:
            measure_pilot_http_authentication(endpoint=endpoint, correct_token=token)
        assert live_denial_error.value.code == "PILOT_HTTP_CONFORMANCE_FAILED"
        monkeypatch.setattr(server, "_call_tool", original_call_tool)

        def invoke_visible_write(sequence: int) -> str:
            payload = json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": sequence,
                    "method": "tools/call",
                    "params": {
                        "name": "apply_work_item_create",
                        "arguments": {"preview_id": f"preview_{sequence}"},
                    },
                }
            ).encode("utf-8")
            request = urllib.request.Request(
                f"{endpoint}/mcp",
                data=payload,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=5) as response:  # nosec B310 - loopback endpoint
                body = json.loads(response.read().decode("utf-8"))
            return str(body["result"]["structuredContent"]["error_code"])

        with ThreadPoolExecutor(max_workers=4) as executor:
            codes = list(executor.map(invoke_visible_write, range(8)))
        assert codes == ["PREFLIGHT_CONFORMANCE_TOOL_CALL_DENIED"] * 8
        direct = server._call_tool("apply_work_item_create", {"preview_id": "direct-bypass"})
        assert direct["error_code"] == "PREFLIGHT_CONFORMANCE_TOOL_CALL_DENIED"
        after = require_pilot_preflight_conformance_baseline(ledger_snapshot.project_root)
        assert after["zero_fact_baseline"] == baseline["zero_fact_baseline"]
    assert server._preflight_conformance_only is False

    timeout_server = MCPPlanningBridgeServer(
        str(project),
        exposure_profile="authoritative_canary",
        work_item_scope_mode=PILOT_SCOPE_MODE,
    )
    timeout_parent = tmp_path / "timeout-conformance-snapshots"
    timeout_parent.mkdir(mode=0o700)
    timeout_source_before = _ledger_physical_state(project)
    with governed_pilot_conformance_ledger_snapshot(
        project,
        snapshot_parent=timeout_parent,
    ) as timeout_snapshot:
        timeout_thread = threading.Thread(
            target=timeout_server.serve_http,
            kwargs={
                "host": "127.0.0.1",
                "port": 0,
                "auth_token": token,
                "auth_token_source": AUTHORITATIVE_CANARY_PRIVATE_CREDENTIAL_SOURCE,
                "auth_token_file_sha256": token_file_sha256,
                "auth_token_evidence_digest": token_evidence_digest,
                "auth_mode": "token",
                "preflight_conformance": True,
                "preflight_conformance_timeout_seconds": 0.2,
                "preflight_conformance_ledger_snapshot": timeout_snapshot,
            },
            daemon=True,
        )
        timeout_thread.start()
        timeout_thread.join(timeout=3)
        assert not timeout_thread.is_alive()
    assert timeout_server._preflight_conformance_only is False
    assert _ledger_physical_state(project) == timeout_source_before


def test_preflight_conformance_fails_closed_on_profile_lease_timeout_and_nonzero_facts(
    tmp_path: Path,
) -> None:
    normal = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="normal")
    with pytest.raises(PlanningBridgeError, match="exact bounded authoritative Pilot profile"):
        normal.serve_http(preflight_conformance=True)

    missing = tmp_path / "missing-ledger"
    missing.mkdir()
    missing_path = missing / ".colameta/ledger/work-items.sqlite3"
    with pytest.raises(WorkItemGovernanceError) as missing_error:
        require_pilot_preflight_conformance_baseline(missing)
    assert missing_error.value.code == "PILOT_PREFLIGHT_CONFORMANCE_BASELINE_INVALID"
    assert not missing_path.exists()
    missing_server = MCPPlanningBridgeServer(
        str(missing),
        exposure_profile="authoritative_canary",
        work_item_scope_mode=PILOT_SCOPE_MODE,
    )
    with pytest.raises(PlanningBridgeError, match="requires one governed isolated Ledger snapshot"):
        missing_server.serve_http(
            host="127.0.0.1",
            port=0,
            auth_token=f"mvr_{secrets.token_urlsafe(32)}",
            auth_token_source=AUTHORITATIVE_CANARY_PRIVATE_CREDENTIAL_SOURCE,
            auth_token_file_sha256=SHA,
            auth_token_evidence_digest=SHA,
            auth_mode="token",
            preflight_conformance=True,
        )
    missing_snapshot_parent = tmp_path / "missing-snapshots"
    missing_snapshot_parent.mkdir(mode=0o700)
    with pytest.raises(WorkItemGovernanceError) as missing_snapshot_error:
        with governed_pilot_conformance_ledger_snapshot(
            missing,
            snapshot_parent=missing_snapshot_parent,
        ):
            pass
    assert missing_snapshot_error.value.code == "LEDGER_FILE_MISSING"
    assert not missing_path.exists()

    project = tmp_path / "pilot-project"
    project.mkdir()
    ledger = _v7_ledger(project)
    server = MCPPlanningBridgeServer(
        str(project),
        exposure_profile="authoritative_canary",
        work_item_scope_mode=PILOT_SCOPE_MODE,
    )
    with pytest.raises(PlanningBridgeError, match="at most 120 seconds"):
        server.serve_http(preflight_conformance=True, preflight_conformance_timeout_seconds=121)

    now = isoformat_utc(utc_now())
    with sqlite3.connect(ledger.path) as connection:
        connection.execute(
            """
            INSERT INTO work_items(
                work_item_id,schema_version,state,state_version,origin_kind,origin_ref,
                origin_snapshot_digest,imported,current_task_version,attributes_json,
                content_digest,creation_operation,creation_preview_id,
                creation_idempotency_key,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                new_stable_id("work_item"),
                "work_item.v1",
                "proposed",
                0,
                "manual",
                "synthetic://preflight-negative",
                SHA,
                0,
                1,
                "{}",
                SHA,
                "create",
                "preview_negative",
                "preflight-negative",
                now,
                now,
            ),
        )
        connection.commit()
    nonzero_parent = tmp_path / "nonzero-snapshots"
    nonzero_parent.mkdir(mode=0o700)
    source_before = _ledger_physical_state(project)
    with governed_pilot_conformance_ledger_snapshot(
        project,
        snapshot_parent=nonzero_parent,
    ) as nonzero_snapshot:
        with pytest.raises(WorkItemGovernanceError) as baseline_error:
            require_pilot_preflight_conformance_baseline(nonzero_snapshot.project_root)
        assert baseline_error.value.code == "PILOT_PREFLIGHT_CONFORMANCE_BASELINE_INVALID"
        assert baseline_error.value.details == {
            "nonzero_tables": ["work_items"],
            "foreign_key_violations": 0,
        }
        snapshot_ledger = SQLiteWorkItemLedger(nonzero_snapshot.project_root, target_schema_version=7)
        with snapshot_ledger.read_connection() as connection:
            counts = {
                table: int(connection.execute(query).fetchone()[0])
                for table, query in PILOT_TABLE_COUNT_QUERIES.items()
            }
        assert counts["work_items"] == 1
        assert sum(counts.values()) == 1
    assert _ledger_physical_state(project) == source_before


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
        "bindings": {
            "candidate_manifest_sha256": SHA,
            "authentication_conformance_receipt_digest": canonical_sha256({}),
        },
    }
    scope = {"scope": "test", "target_project": {"project_snapshot_digest": SHA}}
    execution: dict[str, object] = {}
    decision_path = tmp_path / "decision.json"
    tombstone_path = tmp_path / "decision.tombstone.json"
    decision_path.write_text(json.dumps(decision), encoding="utf-8")
    decision_path.chmod(0o600)
    monkeypatch.setattr(module, "validate_pilot_authorization", lambda value, scope_envelope: value)
    monkeypatch.setattr(module, "validate_pilot_scope_envelope", lambda value, **kwargs: value)
    monkeypatch.setattr(module, "validate_pilot_preflight", lambda value: value)
    monkeypatch.setattr(
        module,
        "validate_pilot_conformance_authorization_source",
        lambda *args, **kwargs: None,
    )

    def mutate_caller_inputs(*args: object, **kwargs: object) -> None:
        scope["scope"] = "mutated-during-consumption"
        execution["mutated"] = True

    monkeypatch.setattr(module, "validate_pilot_authority_chain", mutate_caller_inputs)

    def semantic_receipt(**kwargs: object) -> dict[str, str]:
        now = kwargs.get("now")
        assert isinstance(now, datetime)
        return {
            "result": "PASS",
            "validated_at": isoformat_utc(now),
        }

    monkeypatch.setattr(module, "build_pilot_semantic_validation_receipt", semantic_receipt)
    candidate_dir = _write_test_pilot_candidate(
        monkeypatch,
        tmp_path / "candidate",
        authorization=decision,
        scope=scope,
        execution=execution,
    )
    ledger = _v7_ledger(tmp_path)
    consumer = PilotAuthorizationDecisionConsumer(
        candidate_dir=candidate_dir,
        decision_path=decision_path,
        tombstone_path=tombstone_path,
        ledger=ledger,
    )

    def mutate_decision_before_persistence(**kwargs: object) -> dict[str, str]:
        del kwargs
        changed = {**decision, "gate_id": "changed-during-consumption"}
        decision_path.write_text(json.dumps(changed), encoding="utf-8")
        decision_path.chmod(0o600)
        return {"result": "PASS"}

    monkeypatch.setattr(
        module,
        "build_pilot_semantic_validation_receipt",
        mutate_decision_before_persistence,
    )
    with pytest.raises(WorkItemGovernanceError) as changed_decision:
        consumer.consume(
            scope_envelope=scope,
            execution_authorization_receipt=execution,
            preflight_receipt={"execution_context": {}, "ledger": {}},
            authentication_conformance_receipt={},
            preflight_semantic_validation_receipt={},
            expected_authorization_digest=canonical_sha256(decision),
        )
    assert changed_decision.value.code == "PILOT_AUTHORIZATION_FILE_UNTRUSTED"
    assert not tombstone_path.exists()
    with ledger.read_connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM pilot_authorization_facts").fetchone()[0] == 0

    decision_path.write_text(json.dumps(decision), encoding="utf-8")
    decision_path.chmod(0o600)
    scope["scope"] = "test"
    execution.clear()
    monkeypatch.setattr(
        module,
        "build_pilot_semantic_validation_receipt",
        semantic_receipt,
    )
    persist_authorization_fact = module._persist_authorization_fact

    def fail_fact_persistence(*args: object, **kwargs: object) -> None:
        raise sqlite3.OperationalError("injected authorization fact failure")

    monkeypatch.setattr(
        module,
        "_persist_authorization_fact",
        fail_fact_persistence,
    )
    with pytest.raises(sqlite3.OperationalError):
        consumer.consume(
            scope_envelope=scope,
            execution_authorization_receipt=execution,
            preflight_receipt={"execution_context": {}, "ledger": {}},
            authentication_conformance_receipt={},
            preflight_semantic_validation_receipt={},
            expected_authorization_digest=canonical_sha256(decision),
        )
    assert decision_path.is_file()
    assert not tombstone_path.exists()
    with ledger.read_connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM pilot_authorization_facts").fetchone()[0] == 0

    monkeypatch.setattr(
        module,
        "_persist_authorization_fact",
        persist_authorization_fact,
    )
    scope["scope"] = "test"
    execution.clear()
    replace = module.os.replace

    def fail_tombstone_publication(*args: object, **kwargs: object) -> None:
        raise OSError("injected Tombstone publication failure")

    monkeypatch.setattr(module.os, "replace", fail_tombstone_publication)
    with pytest.raises(OSError):
        consumer.consume(
            scope_envelope=scope,
            execution_authorization_receipt=execution,
            preflight_receipt={"execution_context": {}, "ledger": {}},
            authentication_conformance_receipt={},
            preflight_semantic_validation_receipt={},
            expected_authorization_digest=canonical_sha256(decision),
        )
    assert decision_path.is_file()
    assert not tombstone_path.exists()
    assert not tombstone_path.with_suffix(".json.tmp").exists()
    with ledger.read_connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM pilot_authorization_facts").fetchone()[0] == 1

    monkeypatch.setattr(module.os, "replace", replace)
    scope["scope"] = "test"
    execution.clear()
    tombstone = consumer.consume(
        scope_envelope=scope,
        execution_authorization_receipt=execution,
        preflight_receipt={"execution_context": {}, "ledger": {}},
        authentication_conformance_receipt={},
        preflight_semantic_validation_receipt={},
        expected_authorization_digest=canonical_sha256(decision),
    )
    assert tombstone.tombstone["decision"] == "CONSUMED"
    assert tombstone.tombstone["retry_allowed"] is False
    assert scope["scope"] == "mutated-during-consumption"
    assert execution == {"mutated": True}
    assert tombstone.scope_envelope["scope"] == "test"
    assert tombstone.execution_receipt == {}
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
    with ledger.read_connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM pilot_authorization_facts").fetchone()[0] == 1
    with pytest.raises(WorkItemGovernanceError) as error:
        consumer.consume(
            scope_envelope=tombstone.scope_envelope,
            execution_authorization_receipt=tombstone.execution_receipt,
            preflight_receipt=tombstone.preflight,
            authentication_conformance_receipt=tombstone.authentication_conformance,
            preflight_semantic_validation_receipt=tombstone.preflight_semantic_receipt,
            expected_authorization_digest=canonical_sha256(tombstone.authorization),
        )
    assert error.value.code == "PILOT_AUTHORIZATION_ALREADY_CONSUMED"


def test_persisted_authority_detects_mutation_reflection_and_one_shot_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = _v7_ledger(tmp_path)
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
    other_ledger = _v7_ledger(other_root)
    other_lease = _lease(new_stable_id("work_item"))
    other = _consumed_authority(monkeypatch, other_root, other_lease)
    original_candidate_receipt = other._candidate_validation_receipt_json
    object.__setattr__(other, "_candidate_validation_receipt_json", "{}")
    with pytest.raises(WorkItemGovernanceError) as candidate_receipt_mutated:
        require_consumed_pilot_authorization(other)
    assert candidate_receipt_mutated.value.code == "PILOT_AUTHORIZATION_CAPABILITY_INVALID"
    object.__setattr__(other, "_candidate_validation_receipt_json", original_candidate_receipt)
    object.__setattr__(other, "_authorization_json", "{}")
    with pytest.raises(WorkItemGovernanceError) as mutated:
        require_consumed_pilot_authorization(other)
    assert mutated.value.code == "PILOT_AUTHORIZATION_CAPABILITY_INVALID"
    assert ledger.schema_version() == other_ledger.schema_version() == 7


def test_persisted_authority_claim_cannot_be_reset_by_repository_or_raw_sqlite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = _v7_ledger(tmp_path)
    authority = _consumed_authority(monkeypatch, tmp_path, _lease(new_stable_id("work_item")))
    consume_pilot_authorization_capability(authority)
    with pytest.raises(WorkItemGovernanceError) as repository_reset:
        with ledger.write_transaction() as connection:
            connection.execute("DELETE FROM pilot_authorization_claims")
    assert repository_reset.value.code == "ACTIVATION_REPOSITORY_WRITE_DENIED"
    with sqlite3.connect(ledger.path) as connection:
        with pytest.raises(sqlite3.DatabaseError):
            connection.execute("DELETE FROM pilot_authorization_claims")
        with pytest.raises(sqlite3.DatabaseError):
            connection.execute("UPDATE pilot_authorization_facts SET issued_at='reset'")
    with pytest.raises(WorkItemGovernanceError) as replay:
        consume_pilot_authorization_capability(authority)
    assert replay.value.code == "PILOT_AUTHORIZATION_CAPABILITY_CONSUMED"


def test_persisted_authority_allows_exactly_one_concurrent_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _v7_ledger(tmp_path)
    authority = _consumed_authority(monkeypatch, tmp_path, _lease(new_stable_id("work_item")))
    barrier = threading.Barrier(2)

    def claim() -> str:
        barrier.wait(timeout=5)
        try:
            consume_pilot_authorization_capability(authority)
        except WorkItemGovernanceError as exc:
            return exc.code
        return "CLAIMED"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(claim) for _ in range(2)]
        results = sorted(future.result() for future in futures)
    assert results == ["CLAIMED", "PILOT_AUTHORIZATION_CAPABILITY_CONSUMED"]


@pytest.mark.parametrize("replacement", [None, "{}"])
def test_persisted_authority_claim_requires_exact_permanent_tombstone(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    replacement: str | None,
) -> None:
    ledger = _v7_ledger(tmp_path)
    authority = _consumed_authority(monkeypatch, tmp_path, _lease(new_stable_id("work_item")))
    tombstone = tmp_path / "authority/decision.tombstone.json"
    if replacement is None:
        tombstone.unlink()
    else:
        tombstone.write_text(replacement, encoding="utf-8")
        tombstone.chmod(0o600)
    with pytest.raises(WorkItemGovernanceError) as error:
        consume_pilot_authorization_capability(authority)
    assert error.value.code == "PILOT_AUTHORIZATION_TOMBSTONE_INVALID"
    with ledger.read_connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM pilot_authorization_claims").fetchone()[0] == 0
