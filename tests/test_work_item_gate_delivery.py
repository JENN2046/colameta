from __future__ import annotations

import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from runner.work_item_governance.errors import WorkItemGovernanceError
from runner.work_item_governance.principal import PrincipalContext, trusted_principal_context
from runner.work_item_governance.ids import new_stable_id
from runner.work_item_governance.service import WorkItemApplicationService
from runner.work_item_governance.schema_loader import validate_governance_record


def make_service(tmp_path: Path) -> tuple[WorkItemApplicationService, str]:
    service = WorkItemApplicationService(tmp_path, enabled=True, authoritative_transitions=True)
    preview = service.preview_work_item_create(
        {
            "origin": {
                "kind": "manual",
                "ref": "gate-test",
                "snapshot_digest": hashlib.sha256(b"gate-test").hexdigest(),
            }
        }
    )
    work_item_id = service.apply_work_item_create(preview["preview"])["work_item"]["work_item_id"]
    return service, work_item_id


def reviewer_principal(
    *,
    permissions: list[str] | None = None,
    principal_id: str = "reviewer",
) -> PrincipalContext:
    return trusted_principal_context(
        principal_id=principal_id,
        principal_kind="human",
        authenticated_by="commander",
        granted_permissions=permissions or [
            "work_item.ready",
            "work_item.start_delivery",
            "work_item.submit",
            "work_item.accept",
            "work_item.cancel",
            "work_item.return_for_revision",
        ],
        session_ref="commander:test-session",
    )


def transition_preview(
    service: WorkItemApplicationService,
    work_item_id: str,
    target: str,
    version: int,
    authority: str,
    *,
    decisions: list[str] | None = None,
    artifacts: list[str] | None = None,
    key: str | None = None,
    task_version: int = 1,
    principal_context: PrincipalContext | None = None,
) -> dict:
    return service.preview_work_item_transition(
        {
            "work_item_id": work_item_id,
            "task_version": task_version,
            "target_state": target,
            "expected_state_version": version,
            "decision_ids": decisions or [],
            "evidence_artifact_ids": artifacts or [],
            "idempotency_key": key or f"gate:{target}:{version}",
        },
        principal_context=principal_context or reviewer_principal(),
    )


def apply_transition(
    service: WorkItemApplicationService,
    work_item_id: str,
    target: str,
    version: int,
    authority: str,
    **kwargs,
) -> dict:
    principal_context = kwargs.pop("principal_context", None) or reviewer_principal()
    preview = transition_preview(
        service,
        work_item_id,
        target,
        version,
        authority,
        principal_context=principal_context,
        **kwargs,
    )
    return service.apply_work_item_transition(
        preview["preview"],
        principal_context=principal_context,
    )


def advance_to_in_delivery(service: WorkItemApplicationService, work_item_id: str) -> None:
    assert apply_transition(service, work_item_id, "ready", 0, "work_item.ready")["state_changed"]
    assert apply_transition(
        service, work_item_id, "in_delivery", 1, "work_item.start_delivery"
    )["state_changed"]


def artifact(service: WorkItemApplicationService, work_item_id: str) -> str:
    return service.register_artifact_reference(
        {
            "work_item_id": work_item_id,
            "task_version": 1,
            "kind": "test_report",
            "uri": "https://e.invalid/test-report",
            "immutable_ref": "test-report:commit:abc",
            "digest": "a" * 64,
            "source_event_key": "artifact:test-report",
        }
    )["artifact"]["artifact_id"]


def decision(
    service: WorkItemApplicationService,
    work_item_id: str,
    action: str,
    artifacts: list[str],
    *,
    principal_context: PrincipalContext | None = None,
) -> str:
    return service.record_review_decision(
        {
            "work_item_id": work_item_id,
            "task_version": 1,
            "action": action,
            "evidence_artifact_ids": artifacts,
            "reason": f"Decision: {action}",
            "source_event_key": f"decision:{action}",
        },
        principal_context=principal_context or reviewer_principal(),
    )["decision"]["decision_id"]


def test_runner_passed_and_completion_do_not_accept_work_item(tmp_path: Path) -> None:
    service, wi = make_service(tmp_path)
    advance_to_in_delivery(service, wi)
    attempt = service.create_execution_attempt(
        {
            "work_item_id": wi,
            "task_version": 1,
            "metadata": {"runner_status": "PASSED"},
            "source_event_key": "claim:passed",
        }
    )["attempt"]
    service.complete_execution_attempt(
        {
            "attempt_id": attempt["attempt_id"],
            "status": "completed",
            "metadata": {"runner_status": "PASSED"},
            "source_event_key": "completion:passed",
        }
    )
    current = service.get_work_item(wi)
    assert current["state"] == "in_delivery"
    assert current["runner_status_is_authority"] is False
    assert current["gate_events"][-1]["target_state"] == "in_delivery"


def test_caller_cannot_self_assert_commander_authority(tmp_path: Path) -> None:
    service, wi = make_service(tmp_path)
    with pytest.raises(WorkItemGovernanceError) as raised:
        service.preview_work_item_transition(
            {
                "work_item_id": wi,
                "task_version": 1,
                "target_state": "ready",
                "expected_state_version": 0,
                "decision_ids": [],
                "evidence_artifact_ids": [],
                "actor": {"id": "Jenn", "kind": "human"},
                "authority_basis": {"authority": "work_item.ready"},
            },
            principal_context=reviewer_principal(),
        )
    assert raised.value.code == "CALLER_ASSERTED_AUTHORITY_FORBIDDEN"


def test_untrusted_actor_cannot_record_accept_decision(tmp_path: Path) -> None:
    service = WorkItemApplicationService(tmp_path, enabled=True, authoritative_transitions=True)
    command = {
        "work_item_id": new_stable_id("work_item"),
        "task_version": 1,
        "action": "accept",
        "evidence_artifact_ids": [new_stable_id("artifact")],
        "reason": "Untrusted self-assertion",
        "source_event_key": "decision:untrusted",
    }
    with pytest.raises(WorkItemGovernanceError) as raised:
        service.record_review_decision(command, principal_context=None)
    assert raised.value.code == "TRUSTED_PRINCIPAL_REQUIRED"

    untrusted_dict = {
        "principal_id": "Jenn",
        "principal_kind": "human",
        "authenticated_by": "commander",
        "granted_permissions": ["work_item.accept"],
        "session_ref": "caller-body",
    }
    with pytest.raises(WorkItemGovernanceError) as raised:
        service.record_review_decision(command, principal_context=untrusted_dict)  # type: ignore[arg-type]
    assert raised.value.code == "TRUSTED_PRINCIPAL_REQUIRED"

    limited = reviewer_principal(permissions=["work_item.ready"])
    with pytest.raises(WorkItemGovernanceError) as raised:
        service.record_review_decision(command, principal_context=limited)
    assert raised.value.code == "PRINCIPAL_PERMISSION_DENIED"


def test_missing_evidence_and_decision_writes_rejection_without_state_change(tmp_path: Path) -> None:
    service, wi = make_service(tmp_path)
    advance_to_in_delivery(service, wi)
    preview = transition_preview(service, wi, "submitted", 2, "work_item.submit")
    assert preview["evaluation"]["eligible"] is False
    result = service.apply_work_item_transition(
        preview["preview"],
        principal_context=reviewer_principal(),
    )
    assert result["status"] == "transition_rejected"
    assert result["state_changed"] is False
    assert result["work_item"]["state"] == "in_delivery"
    assert result["gate_event"]["reason_code"] == "EVIDENCE_REQUIRED"


def test_blocker_is_independent_condition_and_blocks_delivery_start(tmp_path: Path) -> None:
    service, wi = make_service(tmp_path)
    assert apply_transition(service, wi, "ready", 0, "work_item.ready")["state_changed"]
    blocker = service.apply_blocker(
        {
            "work_item_id": wi,
            "task_version": 1,
            "reason": "Dependency unavailable",
            "actor": {"id": "operator", "kind": "human"},
            "source_event_key": "blocker:apply",
        }
    )["blocker_event"]
    assert service.get_work_item(wi)["blocked"] is True
    rejected = apply_transition(service, wi, "in_delivery", 1, "work_item.start_delivery")
    assert rejected["gate_event"]["reason_code"] == "ACTIVE_BLOCKERS"
    assert service.get_work_item(wi)["state"] == "ready"
    service.clear_blocker(
        {
            "blocker_id": blocker["blocker_id"],
            "work_item_id": wi,
            "task_version": 1,
            "reason": "Dependency restored",
            "actor": {"id": "operator", "kind": "human"},
            "source_event_key": "blocker:clear",
        }
    )
    assert service.get_work_item(wi)["blocked"] is False
    # The rejected Gate did not increment state_version.
    assert apply_transition(
        service, wi, "in_delivery", 1, "work_item.start_delivery", key="start:after-clear"
    )["state_changed"]


def test_submitted_task_cannot_add_new_version_without_revision_gate(tmp_path: Path) -> None:
    service, wi = make_service(tmp_path)
    advance_to_in_delivery(service, wi)
    evidence = artifact(service, wi)
    submit = decision(service, wi, "submit", [evidence])
    assert apply_transition(
        service,
        wi,
        "submitted",
        2,
        "work_item.submit",
        decisions=[submit],
        artifacts=[evidence],
    )["state_changed"]

    with pytest.raises(WorkItemGovernanceError) as raised:
        service.add_task_version(
            {
                "work_item_id": wi,
                "task_version": 2,
                "task": {"objective_ref": "objective://revision"},
                "source_event_key": "task:revision:blocked",
            }
        )
    assert raised.value.code == "REVISION_GATE_REQUIRED"


def test_returned_for_revision_requires_request_changes_decision(tmp_path: Path) -> None:
    service, wi = make_service(tmp_path)
    advance_to_in_delivery(service, wi)
    first_evidence = artifact(service, wi)
    submit = decision(service, wi, "submit", [first_evidence])
    apply_transition(
        service,
        wi,
        "submitted",
        2,
        "work_item.submit",
        decisions=[submit],
        artifacts=[first_evidence],
    )
    missing_decision = apply_transition(
        service,
        wi,
        "in_delivery",
        3,
        "work_item.return_for_revision",
        key="revision:missing-decision:isolated",
    )
    assert missing_decision["state_changed"] is False
    assert missing_decision["gate_event"]["reason_code"] == "REQUIRED_DECISION_MISSING"


def test_new_task_version_must_pass_submission_gate(tmp_path: Path) -> None:
    service, wi = make_service(tmp_path)
    advance_to_in_delivery(service, wi)
    first_evidence = artifact(service, wi)
    submit = decision(service, wi, "submit", [first_evidence])
    apply_transition(
        service,
        wi,
        "submitted",
        2,
        "work_item.submit",
        decisions=[submit],
        artifacts=[first_evidence],
    )

    missing_decision = apply_transition(
        service,
        wi,
        "in_delivery",
        3,
        "work_item.return_for_revision",
        key="revision:missing-decision",
    )
    assert missing_decision["state_changed"] is False
    assert missing_decision["gate_event"]["reason_code"] == "REQUIRED_DECISION_MISSING"

    revision_decision = service.record_review_decision(
        {
            "work_item_id": wi,
            "task_version": 1,
            "action": "request_changes",
            "evidence_artifact_ids": [],
            "reason": "Revise the implementation",
            "source_event_key": "decision:request-changes:v1",
        },
        principal_context=reviewer_principal(),
    )["decision"]
    returned = apply_transition(
        service,
        wi,
        "in_delivery",
        3,
        "work_item.return_for_revision",
        decisions=[revision_decision["decision_id"]],
        key="revision:applied",
    )
    assert returned["state_changed"] is True
    assert returned["gate_event"]["transition_result"] == "returned_for_revision"

    service.add_task_version(
        {
            "work_item_id": wi,
            "task_version": 2,
            "task": {"objective_ref": "objective://revision-v2"},
            "source_event_key": "task:revision:v2",
        }
    )
    direct_accept = apply_transition(
        service,
        wi,
        "accepted",
        5,
        "work_item.accept",
        key="revision:direct-accept",
    )
    assert direct_accept["state_changed"] is False
    assert direct_accept["gate_event"]["reason_code"] == "TRANSITION_NOT_ALLOWED"

    second_evidence = service.register_artifact_reference(
        {
            "work_item_id": wi,
            "task_version": 2,
            "kind": "test_report",
            "uri": "https://e.invalid/revision-v2/test-report",
            "immutable_ref": "revision-v2:test-report",
            "digest": "c" * 64,
            "source_event_key": "artifact:revision:v2",
        }
    )["artifact"]
    second_submit = service.record_review_decision(
        {
            "work_item_id": wi,
            "task_version": 2,
            "action": "submit",
            "evidence_artifact_ids": [second_evidence["artifact_id"]],
            "reason": "Submit revised Task Version",
            "source_event_key": "decision:submit:v2",
        },
        principal_context=reviewer_principal(),
    )["decision"]
    submitted = apply_transition(
        service,
        wi,
        "submitted",
        5,
        "work_item.submit",
        decisions=[second_submit["decision_id"]],
        artifacts=[second_evidence["artifact_id"]],
        key="revision:submit:v2",
        task_version=2,
    )
    assert submitted["state_changed"] is True
    second_accept = service.record_review_decision(
        {
            "work_item_id": wi,
            "task_version": 2,
            "action": "accept",
            "evidence_artifact_ids": [second_evidence["artifact_id"]],
            "reason": "Accept revised Task Version",
            "source_event_key": "decision:accept:v2",
        },
        principal_context=reviewer_principal(),
    )["decision"]
    accepted = apply_transition(
        service,
        wi,
        "accepted",
        6,
        "work_item.accept",
        decisions=[second_accept["decision_id"]],
        artifacts=[second_evidence["artifact_id"]],
        key="revision:accept:v2",
        task_version=2,
    )
    assert accepted["state_changed"] is True
    assert accepted["work_item"]["accepted_evidence_manifest"]["task_version"] == 2


def test_post_accept_artifact_not_part_of_acceptance_manifest(tmp_path: Path) -> None:
    service, wi = make_service(tmp_path)
    advance_to_in_delivery(service, wi)
    evidence = artifact(service, wi)
    submit = decision(service, wi, "submit", [evidence])
    apply_transition(
        service,
        wi,
        "submitted",
        2,
        "work_item.submit",
        decisions=[submit],
        artifacts=[evidence],
    )
    accept = decision(service, wi, "accept", [evidence])
    accepted = apply_transition(
        service,
        wi,
        "accepted",
        3,
        "work_item.accept",
        decisions=[accept],
        artifacts=[evidence],
    )["work_item"]
    frozen = accepted["accepted_evidence_manifest"]

    with pytest.raises(WorkItemGovernanceError) as raised:
        service.register_artifact_reference(
            {
                "work_item_id": wi,
                "task_version": 1,
                "kind": "git_commit",
                "uri": "git://commit/" + "f" * 40,
                "immutable_ref": "f" * 40,
                "digest": "f" * 64,
                "source_event_key": "artifact:post-accept",
            }
        )
    assert raised.value.code == "TERMINAL_ARTIFACT_SET_FROZEN"
    assert service.get_work_item(wi)["accepted_evidence_manifest"] == frozen

    # Even an out-of-band database tamper cannot silently change what accepted
    # means to downstream readers such as Stable Promotion.
    with service.ledger.write_transaction() as connection:
        connection.execute("DROP TRIGGER acceptance_manifests_no_update")
        connection.execute(
            "UPDATE acceptance_manifests SET artifact_manifest_digest=? WHERE work_item_id=?",
            ("0" * 64, wi),
        )
    with pytest.raises(WorkItemGovernanceError) as integrity_failure:
        service.get_work_item(wi)
    assert integrity_failure.value.code == "ACCEPTANCE_MANIFEST_INTEGRITY_FAILED"


def test_full_review_gate_is_idempotent_and_terminal_state_is_irreversible(tmp_path: Path) -> None:
    service, wi = make_service(tmp_path)
    advance_to_in_delivery(service, wi)
    evidence = artifact(service, wi)
    submit = decision(service, wi, "submit", [evidence])
    submit_preview = transition_preview(
        service,
        wi,
        "submitted",
        2,
        "work_item.submit",
        decisions=[submit],
        artifacts=[evidence],
    )["preview"]
    first = service.apply_work_item_transition(
        submit_preview,
        principal_context=reviewer_principal(),
    )
    replay = service.apply_work_item_transition(
        submit_preview,
        principal_context=reviewer_principal(),
    )
    assert first["state_changed"] is True
    assert replay["idempotent_replay"] is True
    assert replay["gate_event"]["gate_event_id"] == first["gate_event"]["gate_event_id"]

    accept = decision(service, wi, "accept", [evidence])
    accepted = apply_transition(
        service,
        wi,
        "accepted",
        3,
        "work_item.accept",
        decisions=[accept],
        artifacts=[evidence],
    )
    assert accepted["work_item"]["state"] == "accepted"
    validate_governance_record("decision_record.v1", accepted["work_item"]["decision_records"][-1])
    validate_governance_record("gate_event.v1", accepted["gate_event"])
    manifest = accepted["work_item"]["accepted_evidence_manifest"]
    validate_governance_record("acceptance_evidence_manifest.v1", manifest)
    assert manifest["gate_event_id"] == accepted["gate_event"]["gate_event_id"]
    assert manifest["artifact_ids"] == [evidence]
    terminal = apply_transition(
        service,
        wi,
        "cancelled",
        4,
        "work_item.cancel",
        key="terminal:cancel-attempt",
    )
    assert terminal["status"] == "transition_rejected"
    assert terminal["gate_event"]["reason_code"] == "TERMINAL_STATE"
    assert terminal["work_item"]["state"] == "accepted"


def test_competing_gate_previews_commit_one_cas_transition(tmp_path: Path) -> None:
    service, wi = make_service(tmp_path)
    previews = [
        transition_preview(
            service,
            wi,
            "ready",
            0,
            "work_item.ready",
            key=f"gate:competing:{index}",
        )["preview"]
        for index in range(2)
    ]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda preview: service.apply_work_item_transition(
                    preview,
                    principal_context=reviewer_principal(),
                ),
                previews,
            )
        )

    assert sum(result["state_changed"] is True for result in results) == 1
    assert {result["status"] for result in results} == {
        "transition_applied",
        "transition_rejected",
    }
    assert service.get_work_item(wi)["state"] == "ready"


def test_delivery_retry_and_ack_never_change_work_item_state(tmp_path: Path) -> None:
    service, wi = make_service(tmp_path)
    receipt = service.create_delivery_receipt(
        {
            "work_item_id": wi,
            "task_version": 1,
            "destination": "manual://reviewer",
            "payload_digest": "b" * 64,
            "idempotency_key": "delivery:create",
        }
    )["delivery_receipt"]
    failed = service.retry_delivery(
        {
            "delivery_receipt_id": receipt["delivery_receipt_id"],
            "source_event_key": "delivery:retry:1",
            "delivered": False,
            "error": "offline",
        }
    )
    assert failed["delivery_receipt"]["status"] == "retry_scheduled"
    assert failed["work_item_state_changed"] is False
    delivered = service.retry_delivery(
        {
            "delivery_receipt_id": receipt["delivery_receipt_id"],
            "source_event_key": "delivery:retry:2",
            "delivered": True,
        }
    )
    acknowledged = service.acknowledge_delivery(
        {
            "delivery_receipt_id": receipt["delivery_receipt_id"],
            "source": "manual",
            "source_event_key": "delivery:ack:1",
        }
    )
    assert delivered["delivery_receipt"]["status"] == "delivered"
    assert acknowledged["delivery_receipt"]["status"] == "acknowledged"
    validate_governance_record("delivery_receipt.v1", acknowledged["delivery_receipt"])
    assert service.get_work_item(wi)["state"] == "proposed"


def test_terminal_work_item_rejects_new_runtime_attempt(tmp_path: Path) -> None:
    service, wi = make_service(tmp_path)
    advance_to_in_delivery(service, wi)
    evidence = artifact(service, wi)
    submit = decision(service, wi, "submit", [evidence])
    apply_transition(
        service,
        wi,
        "submitted",
        2,
        "work_item.submit",
        decisions=[submit],
        artifacts=[evidence],
    )
    accept = decision(service, wi, "accept", [evidence])
    apply_transition(
        service,
        wi,
        "accepted",
        3,
        "work_item.accept",
        decisions=[accept],
        artifacts=[evidence],
    )

    with pytest.raises(WorkItemGovernanceError) as raised:
        service.create_execution_attempt(
            {
                "work_item_id": wi,
                "task_version": 1,
                "source_event_key": "attempt:after-accept",
            }
        )
    assert raised.value.code == "WORK_ITEM_TERMINAL"


def test_decision_gate_audit_and_inbox_tables_are_append_only(tmp_path: Path) -> None:
    service, wi = make_service(tmp_path)
    apply_transition(service, wi, "ready", 0, "work_item.ready")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        with service.ledger.write_transaction() as connection:
            connection.execute("UPDATE gate_events SET reason_code='changed' WHERE work_item_id=?", (wi,))
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        with service.ledger.write_transaction() as connection:
            connection.execute("DELETE FROM audit_events WHERE work_item_id=?", (wi,))


def test_shadow_gate_mode_never_writes_or_changes_state(tmp_path: Path) -> None:
    service = WorkItemApplicationService(tmp_path, enabled=True, authoritative_transitions=False)
    preview = service.preview_work_item_create(
        {
            "origin": {
                "kind": "manual",
                "ref": "shadow",
                "snapshot_digest": hashlib.sha256(b"shadow").hexdigest(),
            }
        }
    )
    wi = service.apply_work_item_create(preview["preview"])["work_item"]["work_item_id"]
    transition = transition_preview(service, wi, "ready", 0, "work_item.ready")
    result = service.apply_work_item_transition(
        transition["preview"],
        principal_context=reviewer_principal(),
    )
    assert result["status"] == "shadow_evaluated"
    assert result["gate_event_written"] is False
    current = service.get_work_item(wi)
    assert current["state"] == "proposed"
    assert current["gate_events"] == []


def test_gate_mode_off_keeps_reads_but_rejects_gate_evaluation(tmp_path: Path) -> None:
    settings_dir = tmp_path / ".colameta"
    settings_dir.mkdir()
    (settings_dir / "settings.json").write_text(
        json.dumps({"work_item_governance": {"shadow_ledger_enabled": True, "gate_mode": "off"}}),
        encoding="utf-8",
    )
    service = WorkItemApplicationService(tmp_path)
    preview = service.preview_work_item_create(
        {
            "origin": {
                "kind": "manual",
                "ref": "gate-off",
                "snapshot_digest": hashlib.sha256(b"gate-off").hexdigest(),
            }
        }
    )
    wi = service.apply_work_item_create(preview["preview"])["work_item"]["work_item_id"]
    assert service.status()["gate_mode"] == "off"
    assert service.get_work_item(wi)["gate_mode"] == "off"
    with pytest.raises(WorkItemGovernanceError) as raised:
        transition_preview(service, wi, "ready", 0, "work_item.ready")
    assert raised.value.code == "WORK_ITEM_GATES_DISABLED"
    assert service.get_work_item(wi)["state"] == "proposed"


def test_outbox_retry_dedupe_and_manual_recovery_do_not_change_state(tmp_path: Path) -> None:
    service, wi = make_service(tmp_path)
    apply_transition(service, wi, "ready", 0, "work_item.ready")
    event = service.list_outbox_events(status="pending")["events"][0]
    failed = service.record_outbox_delivery_result(
        {
            "outbox_event_id": event["outbox_event_id"],
            "source_event_key": "outbox:delivery:1",
            "delivered": False,
            "error": "transport offline",
        }
    )
    assert failed["outbox_event"]["status"] == "retry_scheduled"
    replay = service.record_outbox_delivery_result(
        {
            "outbox_event_id": event["outbox_event_id"],
            "source_event_key": "outbox:delivery:1",
            "delivered": False,
            "error": "transport offline",
        }
    )
    assert replay["idempotent_replay"] is True
    recovered = service.recover_outbox_event(
        {
            "outbox_event_id": event["outbox_event_id"],
            "source_event_key": "outbox:recovery:1",
            "reason": "Operator confirmed transport recovery",
        }
    )
    assert recovered["outbox_event"]["status"] == "pending"
    assert recovered["work_item_state_changed"] is False
    assert service.get_work_item(wi)["state"] == "ready"

    with pytest.raises(WorkItemGovernanceError) as raised:
        service.record_outbox_delivery_result(
            {
                "outbox_event_id": event["outbox_event_id"],
                "source_event_key": "outbox:delivery:1",
                "delivered": True,
            }
        )
    assert getattr(raised.value, "code", None) == "IDEMPOTENCY_CONFLICT"
