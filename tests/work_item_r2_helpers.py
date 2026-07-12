from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from datetime import timedelta
from pathlib import Path
from typing import Any

from runner.runner_global_config import RunnerGlobalConfigStore
from runner.work_item_governance.activation import (
    AUTHORITATIVE_TOKEN_EVIDENCE_DIGEST_META_KEY,
    AUTHORITATIVE_TOKEN_FILE_SHA256_META_KEY,
    DEFAULT_QUOTAS,
    EMPTY_USAGE,
    R2_SPEC_FREEZE_MANIFEST_SHA256,
    canonical_path_digest,
    listener_attestation_digest,
    process_identity_inputs,
    read_authoritative_token_file,
    request_context_binding_digest,
)
from runner.work_item_governance.canonical import canonical_json, canonical_sha256, sha256_file
from runner.work_item_governance.ids import new_stable_id
from runner.work_item_governance.preview import isoformat_utc, utc_now
from runner.work_item_governance.principal import PrincipalContext, authorize_principal
from runner.work_item_governance.request_context import (
    AuthenticatedTokenRequestProof,
    AUTHENTICATED_REQUEST_PROOF_SCHEMA_VERSION,
    token_request_proof_signature,
)
from runner.work_item_governance.service import WorkItemApplicationService


def _active_test_token_proof(
    *,
    auth_token: str,
    lease_id: str,
    token_file_sha256: str,
    token_evidence_digest: str,
) -> AuthenticatedTokenRequestProof:
    unsigned = {
        "schema_version": AUTHENTICATED_REQUEST_PROOF_SCHEMA_VERSION,
        "mode": "token",
        "lease_id": lease_id,
        "listener_instance_nonce": "6" * 64,
        "request_nonce": "7" * 64,
        "token_file_sha256": token_file_sha256,
        "token_evidence_digest": token_evidence_digest,
    }
    return AuthenticatedTokenRequestProof(
        mode="token",
        lease_id=lease_id,
        listener_instance_nonce=unsigned["listener_instance_nonce"],
        request_nonce=unsigned["request_nonce"],
        token_file_sha256=token_file_sha256,
        token_evidence_digest=token_evidence_digest,
        signature=token_request_proof_signature(
            auth_token=auth_token,
            unsigned_record=unsigned,
        ),
        _active_validator=lambda _proof: True,
    )


def all_permissions_principal() -> PrincipalContext:
    from runner.work_item_governance.principal import trusted_principal_context

    return trusted_principal_context(
        principal_id="r2-canary-operator",
        principal_kind="human",
        authenticated_by="local_session",
        granted_permissions={
            "work_item.ready",
            "work_item.start_delivery",
            "work_item.submit",
            "work_item.accept",
            "work_item.cancel",
            "work_item.return_for_revision",
            "work_item.approve",
        },
        session_ref="r2-session",
    )


def domain_delta(**overrides: int) -> dict[str, int]:
    value = {
        "work_items": 0,
        "task_versions": 0,
        "runtime_attempts": 0,
        "attempt_events": 0,
        "artifacts": 0,
        "decisions": 0,
        "applied_gate_events": 0,
        "rejected_gate_events": 0,
        "audit_events": 0,
        "outbox_events": 0,
        "acceptance_manifests": 0,
    }
    value.update(overrides)
    return value


def make_fixture(project: Path, principal: PrincipalContext) -> tuple[dict[str, Any], dict[str, Any]]:
    helper = WorkItemApplicationService(project, enabled=True)
    fixture_root = project / "synthetic-fixtures"
    fixture_root.mkdir(parents=True, exist_ok=True)
    artifact_one = fixture_root / "v1-validation.json"
    artifact_two = fixture_root / "v2-test-report.json"
    artifact_one.write_text('{"version":1}', encoding="utf-8")
    artifact_two.write_text('{"version":2}', encoding="utf-8")
    objective_one = "synthetic://WIG-P3-AUTH-CANARY-A1-R2/objective/v1"
    objective_two = "synthetic://WIG-P3-AUTH-CANARY-A1-R2/objective/v2"
    task_one = helper._normalize_create_command(
        {
            "origin": {
                "kind": "manual",
                "ref": "synthetic://WIG-P3-AUTH-CANARY-A1-R2/item/one",
                "snapshot_digest": "1" * 64,
            },
            "objective": "synthetic canary",
            "task": {"objective_ref": objective_one},
            "idempotency_key": "r2:create",
        },
        imported=False,
    )
    task_two = helper._normalize_create_command(
        {
            "origin": {
                "kind": "manual",
                "ref": "synthetic://WIG-P3-AUTH-CANARY-A1-R2/item/unused",
                "snapshot_digest": "2" * 64,
            },
            "task": {"objective_ref": objective_two},
        },
        imported=False,
    )["task"]
    principal_record = principal.to_record()
    actor = principal.actor_record()

    def authority(permission: str) -> dict[str, Any]:
        _principal, _actor, basis = authorize_principal(principal, permission)
        return basis

    def transition(
        *,
        task_version: int,
        target: str,
        expected: int,
        key: str,
        permission: str,
        decisions: list[str] | None = None,
        artifacts: list[str] | None = None,
    ) -> dict[str, Any]:
        return {
            "work_item_id": "$work_item",
            "task_version": task_version,
            "target_state": target,
            "expected_state_version": expected,
            "decision_ids": decisions or [],
            "evidence_artifact_ids": artifacts or [],
            "idempotency_key": key,
            "actor": actor,
            "authority_basis": authority(permission),
            "principal_context": principal_record,
        }

    def decision(
        *,
        task_version: int,
        action: str,
        evidence: list[str],
        reason: str,
        key: str,
        permission: str,
    ) -> dict[str, Any]:
        return {
            "decision_id": None,
            "work_item_id": "$work_item",
            "task_version": task_version,
            "action": action,
            "evidence_artifact_ids": evidence,
            "reason": reason,
            "supersedes_decision_id": None,
            "source_event_key": key,
            "actor": actor,
            "authority_basis": authority(permission),
            "principal_context": principal_record,
        }

    artifact_one_command = {
        "artifact_id": None,
        "work_item_id": "$work_item",
        "task_version": 1,
        "attempt_id": "$attempt_1",
        "kind": "validation",
        "uri": f"file://{artifact_one}",
        "immutable_ref": "synthetic-v1-validation",
        "digest": sha256_file(artifact_one),
        "metadata": {},
        "source_event_key": "r2:artifact:1",
    }
    artifact_two_command = {
        "artifact_id": None,
        "work_item_id": "$work_item",
        "task_version": 2,
        "attempt_id": "$attempt_2",
        "kind": "test_report",
        "uri": f"file://{artifact_two}",
        "immutable_ref": "synthetic-v2-test-report",
        "digest": sha256_file(artifact_two),
        "metadata": {},
        "source_event_key": "r2:artifact:2",
    }
    commands: list[tuple[str, dict[str, Any], str, dict[str, int], list[str]]] = [
        (
            "apply_work_item_create",
            task_one,
            "r2:create",
            domain_delta(work_items=1, task_versions=1),
            ["$work_item"],
        ),
        (
            "apply_work_item_transition",
            transition(task_version=1, target="ready", expected=0, key="r2:gate:1", permission="work_item.ready"),
            "r2:gate:1",
            domain_delta(applied_gate_events=1, audit_events=1, outbox_events=1),
            ["$gate_1"],
        ),
        (
            "apply_work_item_transition",
            transition(
                task_version=1,
                target="in_delivery",
                expected=1,
                key="r2:gate:2",
                permission="work_item.start_delivery",
            ),
            "r2:gate:2",
            domain_delta(applied_gate_events=1, audit_events=1, outbox_events=1),
            ["$gate_2"],
        ),
        (
            "create_execution_attempt",
            {
                "work_item_id": "$work_item",
                "task_version": 1,
                "attempt_id": None,
                "status": "claimed",
                "objective_ref": objective_one,
                "metadata": {},
                "external_refs": [],
                "attempt_kind": "runtime",
                "dispatch_authorized": True,
                "source_event_key": "r2:attempt:1",
            },
            "r2:attempt:1",
            domain_delta(runtime_attempts=1, attempt_events=1),
            ["$attempt_1"],
        ),
        (
            "complete_execution_attempt",
            {
                "attempt_id": "$attempt_1",
                "status": "completed",
                "source_event_key": "r2:complete:1",
                "metadata": {},
                "artifacts": [],
            },
            "r2:complete:1",
            domain_delta(attempt_events=1),
            [],
        ),
        (
            "register_artifact_reference",
            artifact_one_command,
            "r2:artifact:1",
            domain_delta(artifacts=1),
            ["$artifact_1"],
        ),
        (
            "record_review_decision",
            decision(
                task_version=1,
                action="submit",
                evidence=["$artifact_1"],
                reason="submit v1",
                key="r2:decision:1",
                permission="work_item.submit",
            ),
            "r2:decision:1",
            domain_delta(decisions=1),
            ["$decision_1"],
        ),
        (
            "apply_work_item_transition",
            transition(
                task_version=1,
                target="submitted",
                expected=2,
                key="r2:gate:3",
                permission="work_item.submit",
                decisions=["$decision_1"],
                artifacts=["$artifact_1"],
            ),
            "r2:gate:3",
            domain_delta(applied_gate_events=1, audit_events=1, outbox_events=1),
            ["$gate_3"],
        ),
        (
            "record_review_decision",
            decision(
                task_version=1,
                action="request_changes",
                evidence=[],
                reason="revise",
                key="r2:decision:2",
                permission="work_item.return_for_revision",
            ),
            "r2:decision:2",
            domain_delta(decisions=1),
            ["$decision_2"],
        ),
        (
            "apply_work_item_transition",
            transition(
                task_version=1,
                target="in_delivery",
                expected=3,
                key="r2:gate:4",
                permission="work_item.return_for_revision",
                decisions=["$decision_2"],
            ),
            "r2:gate:4",
            domain_delta(applied_gate_events=1, audit_events=1, outbox_events=1),
            ["$gate_4"],
        ),
        (
            "add_task_version",
            {
                "work_item_id": "$work_item",
                "task_version": 2,
                "task": task_two,
                "source_event_key": "r2:task:2",
            },
            "r2:task:2",
            domain_delta(task_versions=1),
            [],
        ),
        (
            "create_execution_attempt",
            {
                "work_item_id": "$work_item",
                "task_version": 2,
                "attempt_id": None,
                "status": "claimed",
                "objective_ref": objective_two,
                "metadata": {},
                "external_refs": [],
                "attempt_kind": "runtime",
                "dispatch_authorized": True,
                "source_event_key": "r2:attempt:2",
            },
            "r2:attempt:2",
            domain_delta(runtime_attempts=1, attempt_events=1),
            ["$attempt_2"],
        ),
        (
            "complete_execution_attempt",
            {
                "attempt_id": "$attempt_2",
                "status": "completed",
                "source_event_key": "r2:complete:2",
                "metadata": {},
                "artifacts": [artifact_two_command],
            },
            "r2:complete:2",
            domain_delta(attempt_events=1, artifacts=1),
            ["$artifact_2"],
        ),
        (
            "record_review_decision",
            decision(
                task_version=2,
                action="submit",
                evidence=["$artifact_2"],
                reason="submit v2",
                key="r2:decision:3",
                permission="work_item.submit",
            ),
            "r2:decision:3",
            domain_delta(decisions=1),
            ["$decision_3"],
        ),
        (
            "apply_work_item_transition",
            transition(
                task_version=2,
                target="submitted",
                expected=5,
                key="r2:gate:5",
                permission="work_item.submit",
                decisions=["$decision_3"],
                artifacts=["$artifact_2"],
            ),
            "r2:gate:5",
            domain_delta(applied_gate_events=1, audit_events=1, outbox_events=1),
            ["$gate_5"],
        ),
        (
            "record_review_decision",
            decision(
                task_version=2,
                action="accept",
                evidence=["$artifact_2"],
                reason="accept v2",
                key="r2:decision:4",
                permission="work_item.accept",
            ),
            "r2:decision:4",
            domain_delta(decisions=1),
            ["$decision_4"],
        ),
        (
            "apply_work_item_transition",
            transition(
                task_version=2,
                target="accepted",
                expected=6,
                key="r2:gate:6",
                permission="work_item.accept",
                decisions=["$decision_4"],
                artifacts=["$artifact_2"],
            ),
            "r2:gate:6",
            domain_delta(
                applied_gate_events=1,
                audit_events=1,
                outbox_events=1,
                acceptance_manifests=1,
            ),
            ["$gate_6"],
        ),
    ]
    slots = []
    for sequence, (name, command, source_key, delta, generated) in enumerate(commands, 1):
        slots.append(
            {
                "sequence": sequence,
                "command_name": name,
                "normalized_command": command,
                "normalized_command_digest": canonical_sha256(command),
                "idempotency_binding_digest": canonical_sha256(
                    {"command_name": name, "source_event_key": source_key}
                ),
                "expected_outcome": "new_fact",
                "expected_fact_delta": delta,
                "generated_binding_slots": generated,
                "exact_replay_allowed": True,
            }
        )
    fixture = {
        "schema_version": "work_item_synthetic_fixture_contract.v1",
        "authorization_id": "WIG-P3-CANARY-A1-R2-TEST",
        "origin": {"kind": "manual", "ref": task_one["origin"]["ref"]},
        "objective_ref_prefix": "synthetic://WIG-P3-AUTH-CANARY-A1-R2/objective/",
        "fixture_root_path_digest": canonical_sha256(
            {"resolved_posix_path": fixture_root.resolve().as_posix()}
        ),
        "lifecycle_scenario": "returned_for_revision_then_accepted",
        "normalized_create": {
            "normalized_command": task_one,
            "normalized_command_digest": canonical_sha256(task_one),
        },
        "task_versions": [
            {
                "slot": 1,
                "normalized_payload": task_one["task"],
                "normalized_payload_digest": canonical_sha256(task_one["task"]),
            },
            {
                "slot": 2,
                "normalized_payload": task_two,
                "normalized_payload_digest": canonical_sha256(task_two),
            },
        ],
        "runtime_attempts": [
            {
                "slot": 1,
                "task_version_slot": 1,
                "objective_ref": objective_one,
                "objective_ref_digest": canonical_sha256(objective_one),
                "mode": "runtime",
                "imported": False,
            },
            {
                "slot": 2,
                "task_version_slot": 2,
                "objective_ref": objective_two,
                "objective_ref_digest": canonical_sha256(objective_two),
                "mode": "runtime",
                "imported": False,
            },
        ],
        "decision_actions": ["submit", "request_changes", "submit", "accept"],
        "required_lifecycle_transitions": [
            {"sequence": 1, "task_version_slot": 1, "from_state": "proposed", "to_state": "ready", "expected_gate_result": "transition_applied"},
            {"sequence": 2, "task_version_slot": 1, "from_state": "ready", "to_state": "in_delivery", "expected_gate_result": "transition_applied"},
            {"sequence": 3, "task_version_slot": 1, "from_state": "in_delivery", "to_state": "submitted", "expected_gate_result": "transition_applied"},
            {"sequence": 4, "task_version_slot": 1, "from_state": "submitted", "to_state": "in_delivery", "expected_gate_result": "returned_for_revision"},
            {"sequence": 5, "task_version_slot": 2, "from_state": "in_delivery", "to_state": "submitted", "expected_gate_result": "transition_applied"},
            {"sequence": 6, "task_version_slot": 2, "from_state": "submitted", "to_state": "accepted", "expected_gate_result": "transition_applied"},
        ],
        "required_command_names": [
            "apply_work_item_create",
            "add_task_version",
            "create_execution_attempt",
            "complete_execution_attempt",
            "register_artifact_reference",
            "record_review_decision",
            "apply_work_item_transition",
        ],
        "command_slots": slots,
        "artifact_files": [
            {"slot": 1, "relative_path": artifact_one.name, "kind": "validation", "sha256": sha256_file(artifact_one), "task_version_slot": 1, "attempt_slot": 1},
            {"slot": 2, "relative_path": artifact_two.name, "kind": "test_report", "sha256": sha256_file(artifact_two), "task_version_slot": 2, "attempt_slot": 2},
        ],
        "generated_id_placeholders": {
            "work_item": "$work_item",
            "attempts": ["$attempt_1", "$attempt_2"],
            "artifacts": ["$artifact_1", "$artifact_2"],
            "decisions": ["$decision_1", "$decision_2", "$decision_3", "$decision_4"],
            "gate_events": ["$gate_1", "$gate_2", "$gate_3", "$gate_4", "$gate_5", "$gate_6"],
        },
        "allowed_artifact_kinds": ["evidence_receipt", "report", "test_report", "validation"],
        "artifact_uri_scheme": "file",
        "artifact_path_policy": "resolved_path_must_be_below_fixture_root",
        "artifact_digest_required": True,
        "artifact_coverage_policy": "at_least_one_verified_artifact_per_task_version",
        "external_associations": [],
        "plan_version_refs": [],
        "external_associations_allowed": False,
        "plan_version_refs_allowed": False,
        "real_git_commit_artifacts_allowed": False,
    }
    raw = {
        "create": task_one,
        "task_two": task_two,
        "artifact_one": artifact_one_command,
        "artifact_two": artifact_two_command,
    }
    return fixture, raw


def install_active_lease(
    project: Path,
    fixture: dict[str, Any],
    principal: PrincipalContext,
) -> WorkItemApplicationService:
    seed = WorkItemApplicationService(project, enabled=True)
    seed.ledger.get_or_create_signing_key()
    token_bytes = hashlib.sha256(str(project.resolve()).encode("utf-8")).digest()
    auth_token = "mvr_" + base64.urlsafe_b64encode(token_bytes).rstrip(b"=").decode("ascii")
    test_xdg_config = project / ".test-xdg-config"
    os.environ["XDG_CONFIG_HOME"] = str(test_xdg_config)
    token_store = RunnerGlobalConfigStore(config_dir=str(test_xdg_config / "colameta"))
    saved_token = token_store.save_auth_token(auth_token)
    assert saved_token["ok"] is True
    auth_file = Path(str(saved_token["path"])).resolve()
    auth_file.parent.chmod(0o700)
    _saved_token, token_file_evidence = read_authoritative_token_file(auth_file)
    assert _saved_token == auth_token
    token_evidence_digest = canonical_sha256(
        {
            "algorithm": "r3_test_token_binding",
            "token_file_sha256": token_file_evidence["token_sha256"],
            "auth_file_path_digest": token_file_evidence["auth_file_path_digest"],
        }
    )
    lease_id = new_stable_id("activation_lease")
    nonce = "n" * 32
    identity = process_identity_inputs(nonce)
    listener_digest = listener_attestation_digest(
        claimed_process_identity=identity["expected_process_identity"],
        bind_address="127.0.0.1",
        port=48787,
        process_listener_count=1,
    )
    authorization_digest = "a" * 64
    context_digest = request_context_binding_digest(
        lease_id=lease_id,
        authorization_digest=authorization_digest,
        claimed_process_identity=identity["expected_process_identity"],
        runtime_instance_nonce=nonce,
        listener_digest=listener_digest,
        principal_id=principal.principal_id,
        session_ref=str(principal.session_ref),
    )
    now = utc_now()
    principal_binding = {
        "principal_id": principal.principal_id,
        "principal_kind": principal.principal_kind,
        "session_ref": principal.session_ref,
        "caller_auth_mode": "token",
        "principal_authenticated_by": "local_session",
        "permissions": sorted(principal.granted_permissions),
    }
    runtime = {
        "runtime_instance_nonce": nonce,
        "bind_address": "127.0.0.1",
        "port": 48787,
        "token_file_path_digest": canonical_path_digest(auth_file),
    }
    claim_ns = time.monotonic_ns()
    with seed.ledger.write_transaction() as connection:
        connection.executemany(
            "INSERT INTO ledger_meta(key,value,updated_at) VALUES(?,?,?)",
            (
                (
                    AUTHORITATIVE_TOKEN_FILE_SHA256_META_KEY,
                    token_file_evidence["token_sha256"],
                    isoformat_utc(now),
                ),
                (
                    AUTHORITATIVE_TOKEN_EVIDENCE_DIGEST_META_KEY,
                    token_evidence_digest,
                    isoformat_utc(now),
                ),
            ),
        )
        connection.execute(
            """
            INSERT INTO activation_leases(
              lease_id,schema_version,authorization_id,authorization_digest,activation_envelope_digest,
              spec_manifest_digest,expected_process_identity,claimed_process_identity,listener_attested_at,
              listener_attestation_digest,request_context_binding_digest,monotonic_claim_ns,monotonic_deadline_ns,
              not_before,expires_at,maximum_runtime_seconds,authorized_work_item_id,source_binding_json,
              runtime_binding_json,principal_binding_json,bootstrap_json,scope_json,fixture_json,quotas_json,
              fixture_bindings_json,usage_json,policy_json,maintenance_json,failure_behavior_json,status,state_version,
              created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                lease_id,
                "work_item_activation_lease.v1",
                fixture["authorization_id"],
                authorization_digest,
                "b" * 64,
                R2_SPEC_FREEZE_MANIFEST_SHA256,
                identity["expected_process_identity"],
                identity["expected_process_identity"],
                isoformat_utc(now),
                listener_digest,
                context_digest,
                claim_ns,
                claim_ns + 1_800_000_000_000,
                isoformat_utc(now - timedelta(seconds=1)),
                isoformat_utc(now + timedelta(seconds=1790)),
                1800,
                None,
                canonical_json({"implementation_commit": "c" * 40}),
                canonical_json(runtime),
                canonical_json(principal_binding),
                canonical_json({}),
                canonical_json({}),
                canonical_json(fixture),
                canonical_json(DEFAULT_QUOTAS),
                canonical_json({"attempt_ids": [], "artifact_ids": [], "decision_ids": [], "gate_event_ids": []}),
                canonical_json({**EMPTY_USAGE, "lease_events": 3}),
                canonical_json({}),
                canonical_json({}),
                canonical_json({}),
                "active",
                2,
                isoformat_utc(now),
                isoformat_utc(now),
            ),
        )
        for sequence, event_type in enumerate(("lease_issued", "process_claimed", "listener_attested"), 1):
            connection.execute(
                """
                INSERT INTO activation_lease_events(
                  lease_event_id,schema_version,lease_id,sequence,event_type,status_before,status_after,
                  state_version_before,state_version_after,event_digest,event_json,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    new_stable_id("activation_lease_event"),
                    "work_item_activation_lease_event.v1",
                    lease_id,
                    sequence,
                    event_type,
                    None if sequence == 1 else ("prepared" if sequence == 2 else "claimed"),
                    "prepared" if sequence == 1 else ("claimed" if sequence == 2 else "active"),
                    max(0, sequence - 1),
                    max(0, sequence - 1),
                    f"{sequence:064x}",
                    "{}",
                    isoformat_utc(now),
                ),
            )
    service = WorkItemApplicationService(
        project,
        enabled=True,
        authoritative_transitions=True,
        authoritative_canary=True,
        principal_context=principal,
    )
    guard = service.activation_guard
    assert guard is not None
    service.request_context = guard.mint_request_context(
        proof=_active_test_token_proof(
            auth_token=auth_token,
            lease_id=lease_id,
            token_file_sha256=token_file_evidence["token_sha256"],
            token_evidence_digest=token_evidence_digest,
        ),
        principal_context=principal,
    )
    return service


def transition_apply(
    service: WorkItemApplicationService,
    principal: PrincipalContext,
    command: dict[str, Any],
) -> dict[str, Any]:
    preview = service.preview_work_item_transition(command, principal_context=principal)["preview"]
    return service.apply_work_item_transition(preview, principal_context=principal)


def lease_row(service: WorkItemApplicationService) -> dict[str, Any]:
    with service.ledger.read_connection() as connection:
        row = connection.execute("SELECT * FROM activation_leases").fetchone()
    assert row is not None
    result = dict(row)
    for key in ("usage_json", "fixture_bindings_json"):
        result[key] = json.loads(result[key])
    return result
