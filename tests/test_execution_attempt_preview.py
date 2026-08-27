from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from runner.work_item_governance.errors import WorkItemGovernanceError
from runner.work_item_governance.ids import new_stable_id
from runner.work_item_governance.principal import trusted_principal_context
from runner.work_item_governance.service import WorkItemApplicationService


class MutableClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.value


def principal(
    name: str = "stage-operator",
    *,
    permissions: set[str] | None = None,
):
    return trusted_principal_context(
        principal_id=name,
        principal_kind="human",
        authenticated_by="local_session",
        granted_permissions=permissions or {"work_item.start_delivery"},
        session_ref=f"session:{name}",
    )


def make_service(tmp_path: Path, *, now=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    service = WorkItemApplicationService(
        tmp_path,
        enabled=True,
        authoritative_transitions=True,
        now=now or (lambda: datetime.now(timezone.utc)),
    )
    create_preview = service.preview_work_item_create(
        {
            "origin": {
                "kind": "manual",
                "ref": "test://stage-attempt-preview",
                "snapshot_digest": "a" * 64,
            },
            "objective": "stage attempt preview",
            "idempotency_key": "create:stage-attempt-preview",
        }
    )["preview"]
    item = service.apply_work_item_create(create_preview)["work_item"]
    return service, item["work_item_id"]


def context(task_id: str = "task-a", *, group: str = "group-a") -> dict[str, str]:
    return {
        "kind": "stage_parallel_task",
        "stage_id": "stage-a",
        "parallel_group_id": group,
        "task_id": task_id,
        "stage_preview_sha256": "1" * 64,
        "base_head": "2" * 64,
        "runner_plan_sha256": "3" * 64,
    }


def attempt_command(work_item_id: str) -> dict[str, object]:
    return {
        "work_item_id": work_item_id,
        "task_version": 1,
        "status": "claimed",
        "objective_ref": "objective://stage-task-a",
        "metadata": {"source": "stage-admission"},
        "external_refs": [],
    }


def domain_counts(service: WorkItemApplicationService) -> tuple[int, int, int]:
    with service.ledger.read_connection() as connection:
        return tuple(
            int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in ("execution_attempts", "attempt_events", "artifact_refs")
        )


def apply_attempt(
    service: WorkItemApplicationService,
    preview: dict[str, object],
    *,
    expected_execution_context: dict[str, str],
    principal_context,
) -> dict[str, object]:
    prepared = service.prepare_execution_attempt_create_apply(
        preview,
        expected_execution_context=expected_execution_context,
        principal_context=principal_context,
    )
    result = service.create_execution_attempt(
        prepared["attempt_command"],
        expected_mutable_reality=prepared["expected_mutable_reality"],
    )
    return {
        **result,
        "preview_id": prepared["preview_id"],
        "execution_context": prepared["execution_context"],
    }


def transition(
    service: WorkItemApplicationService,
    work_item_id: str,
    *,
    target: str,
    state_version: int,
    actor,
    decision_ids: list[str] | None = None,
    artifact_ids: list[str] | None = None,
) -> None:
    preview = service.preview_work_item_transition(
        {
            "work_item_id": work_item_id,
            "task_version": 1,
            "target_state": target,
            "expected_state_version": state_version,
            "decision_ids": decision_ids or [],
            "evidence_artifact_ids": artifact_ids or [],
            "idempotency_key": f"transition:{target}:{state_version}",
        },
        principal_context=actor,
    )["preview"]
    service.apply_work_item_transition(preview, principal_context=actor)


def test_attempt_preview_is_zero_write_and_apply_replays_same_attempt(tmp_path: Path) -> None:
    service, work_item_id = make_service(tmp_path)
    before = domain_counts(service)

    preview_result = service.preview_execution_attempt_create(
        attempt_command(work_item_id),
        execution_context=context(),
        principal_context=principal(),
    )

    assert domain_counts(service) == before == (0, 0, 0)
    assert preview_result["execution_attempt_created"] is False
    signed_attempt = preview_result["preview"]["command"]["attempt_command"]
    assert signed_attempt["attempt_id"] is None
    assert signed_attempt["source_event_key"].startswith("stage_attempt_admission:")

    first = apply_attempt(
        service,
        preview_result["preview"],
        expected_execution_context=context(),
        principal_context=principal(),
    )
    replay = apply_attempt(
        service,
        preview_result["preview"],
        expected_execution_context=context(),
        principal_context=principal(),
    )

    assert first["idempotent_replay"] is False
    assert replay["idempotent_replay"] is True
    assert replay["attempt"]["attempt_id"] == first["attempt"]["attempt_id"]
    assert domain_counts(service) == (1, 1, 0)


def test_attempt_preview_binds_context_principal_and_canonical_event_key(tmp_path: Path) -> None:
    service, work_item_id = make_service(tmp_path)
    first = service.preview_execution_attempt_create(
        attempt_command(work_item_id),
        execution_context=context(),
        principal_context=principal(),
    )["preview"]
    same = service.preview_execution_attempt_create(
        attempt_command(work_item_id),
        execution_context=context(),
        principal_context=principal(),
    )["preview"]
    other = service.preview_execution_attempt_create(
        attempt_command(work_item_id),
        execution_context=context("task-b"),
        principal_context=principal(),
    )["preview"]
    second_create = service.preview_work_item_create(
        {
            "origin": {
                "kind": "manual",
                "ref": "test://stage-attempt-preview/second-target",
                "snapshot_digest": "b" * 64,
            },
            "objective": "second target",
            "idempotency_key": "create:stage-attempt-preview:second-target",
        }
    )["preview"]
    second_work_item_id = service.apply_work_item_create(second_create)["work_item"]["work_item_id"]
    other_target = service.preview_execution_attempt_create(
        attempt_command(second_work_item_id),
        execution_context=context(),
        principal_context=principal(),
    )["preview"]

    first_key = first["command"]["attempt_command"]["source_event_key"]
    assert same["command"]["attempt_command"]["source_event_key"] == first_key
    assert other["command"]["attempt_command"]["source_event_key"] != first_key
    assert other_target["command"]["attempt_command"]["source_event_key"] != first_key

    with pytest.raises(WorkItemGovernanceError) as wrong_context:
        service.inspect_execution_attempt_create_preview(
            first,
            expected_execution_context=context("task-b"),
            principal_context=principal(),
        )
    assert wrong_context.value.code == "STAGE_ATTEMPT_GRANT_CONTEXT_MISMATCH"

    with pytest.raises(WorkItemGovernanceError) as wrong_principal:
        apply_attempt(
            service,
            first,
            expected_execution_context=context(),
            principal_context=principal("another-operator"),
        )
    assert wrong_principal.value.code == "PREVIEW_PRINCIPAL_MISMATCH"
    assert domain_counts(service) == (0, 0, 0)


def test_attempt_preview_rejects_caller_attempt_id_and_tampering(tmp_path: Path) -> None:
    service, work_item_id = make_service(tmp_path)
    supplied = {**attempt_command(work_item_id), "attempt_id": new_stable_id("attempt")}
    with pytest.raises(WorkItemGovernanceError) as caller_id:
        service.preview_execution_attempt_create(
            supplied,
            execution_context=context(),
            principal_context=principal(),
        )
    assert caller_id.value.code == "STAGE_ATTEMPT_ID_CALLER_SUPPLIED"

    preview = service.preview_execution_attempt_create(
        attempt_command(work_item_id),
        execution_context=context(),
        principal_context=principal(),
    )["preview"]
    tampered = copy.deepcopy(preview)
    tampered["command"]["execution_context"]["base_head"] = "4" * 64
    with pytest.raises(WorkItemGovernanceError) as changed:
        apply_attempt(
            service,
            tampered,
            expected_execution_context=context(),
            principal_context=principal(),
        )
    assert changed.value.code == "PREVIEW_SIGNATURE_INVALID"
    assert domain_counts(service) == (0, 0, 0)


def test_attempt_preview_expiry_wrong_project_and_task_version_drift_fail_closed(tmp_path: Path) -> None:
    clock = MutableClock()
    service, work_item_id = make_service(tmp_path / "a", now=clock)
    preview = service.preview_execution_attempt_create(
        attempt_command(work_item_id),
        execution_context=context(),
        principal_context=principal(),
        ttl_seconds=1,
    )["preview"]

    other, _ = make_service(tmp_path / "b", now=clock)
    with pytest.raises(WorkItemGovernanceError) as wrong_project:
        other.inspect_execution_attempt_create_preview(
            preview,
            expected_execution_context=context(),
            principal_context=principal(),
        )
    assert wrong_project.value.code in {"PREVIEW_PROJECT_MISMATCH", "PREVIEW_SIGNATURE_INVALID"}

    clock.value += timedelta(seconds=2)
    with pytest.raises(WorkItemGovernanceError) as expired:
        apply_attempt(
            service,
            preview,
            expected_execution_context=context(),
            principal_context=principal(),
        )
    assert expired.value.code == "PREVIEW_EXPIRED"

    fresh_service, fresh_work_item = make_service(tmp_path / "c")
    fresh_preview = fresh_service.preview_execution_attempt_create(
        attempt_command(fresh_work_item),
        execution_context=context(),
        principal_context=principal(),
    )["preview"]
    fresh_service.add_task_version(
        {
            "work_item_id": fresh_work_item,
            "task_version": 2,
            "task": {"objective_ref": "objective://v2"},
            "source_event_key": "task:v2:stage-preview-drift",
        }
    )
    with pytest.raises(WorkItemGovernanceError) as stale:
        apply_attempt(
            fresh_service,
            fresh_preview,
            expected_execution_context=context(),
            principal_context=principal(),
        )
    assert stale.value.code == "TASK_VERSION_STALE"
    assert domain_counts(fresh_service) == (0, 0, 0)


def test_attempt_preview_requires_start_delivery_permission(tmp_path: Path) -> None:
    service, work_item_id = make_service(tmp_path)
    unauthorized = principal("reader", permissions={"work_item.ready"})

    with pytest.raises(WorkItemGovernanceError) as denied:
        service.preview_execution_attempt_create(
            attempt_command(work_item_id),
            execution_context=context(),
            principal_context=unauthorized,
        )
    assert denied.value.code == "PRINCIPAL_PERMISSION_DENIED"
    assert domain_counts(service) == (0, 0, 0)


def test_attempt_apply_rechecks_terminal_and_submitted_state(tmp_path: Path) -> None:
    permissions = {
        "work_item.ready",
        "work_item.start_delivery",
        "work_item.submit",
        "work_item.cancel",
    }

    terminal_service, terminal_id = make_service(tmp_path / "terminal")
    terminal_actor = principal(permissions=permissions)
    terminal_preview = terminal_service.preview_execution_attempt_create(
        attempt_command(terminal_id),
        execution_context=context(),
        principal_context=terminal_actor,
    )["preview"]
    cancel_decision = terminal_service.record_review_decision(
        {
            "work_item_id": terminal_id,
            "task_version": 1,
            "action": "cancel",
            "evidence_artifact_ids": [],
            "reason": "cancel for terminal state-drift test",
            "source_event_key": "decision:cancel:stage-attempt",
        },
        principal_context=terminal_actor,
    )["decision"]["decision_id"]
    transition(
        terminal_service,
        terminal_id,
        target="cancelled",
        state_version=0,
        actor=terminal_actor,
        decision_ids=[cancel_decision],
    )
    with pytest.raises(WorkItemGovernanceError) as terminal:
        apply_attempt(
            terminal_service,
            terminal_preview,
            expected_execution_context=context(),
            principal_context=terminal_actor,
        )
    assert terminal.value.code == "WORK_ITEM_TERMINAL"
    assert domain_counts(terminal_service) == (0, 0, 0)

    submitted_service, submitted_id = make_service(tmp_path / "submitted")
    submitted_actor = principal(permissions=permissions)
    submitted_preview = submitted_service.preview_execution_attempt_create(
        attempt_command(submitted_id),
        execution_context=context(),
        principal_context=submitted_actor,
    )["preview"]
    transition(
        submitted_service,
        submitted_id,
        target="ready",
        state_version=0,
        actor=submitted_actor,
    )
    transition(
        submitted_service,
        submitted_id,
        target="in_delivery",
        state_version=1,
        actor=submitted_actor,
    )
    artifact = submitted_service.register_artifact_reference(
        {
            "work_item_id": submitted_id,
            "task_version": 1,
            "kind": "test_report",
            "uri": "https://e.invalid/stage-attempt",
            "immutable_ref": "test-report:stage-attempt",
            "digest": "9" * 64,
            "source_event_key": "artifact:stage-attempt",
        }
    )["artifact"]["artifact_id"]
    decision = submitted_service.record_review_decision(
        {
            "work_item_id": submitted_id,
            "task_version": 1,
            "action": "submit",
            "evidence_artifact_ids": [artifact],
            "reason": "submit for state-drift test",
            "source_event_key": "decision:submit:stage-attempt",
        },
        principal_context=submitted_actor,
    )["decision"]["decision_id"]
    transition(
        submitted_service,
        submitted_id,
        target="submitted",
        state_version=2,
        actor=submitted_actor,
        decision_ids=[decision],
        artifact_ids=[artifact],
    )
    with pytest.raises(WorkItemGovernanceError) as submitted:
        apply_attempt(
            submitted_service,
            submitted_preview,
            expected_execution_context=context(),
            principal_context=submitted_actor,
        )
    assert submitted.value.code == "REVISION_GATE_REQUIRED"
    assert domain_counts(submitted_service) == (0, 0, 1)


def test_attempt_apply_rejects_nonterminal_state_version_drift(tmp_path: Path) -> None:
    service, work_item_id = make_service(tmp_path)
    actor = principal(permissions={"work_item.ready", "work_item.start_delivery"})
    preview = service.preview_execution_attempt_create(
        attempt_command(work_item_id),
        execution_context=context(),
        principal_context=actor,
    )["preview"]
    transition(
        service,
        work_item_id,
        target="ready",
        state_version=0,
        actor=actor,
    )

    with pytest.raises(WorkItemGovernanceError) as drift:
        apply_attempt(
            service,
            preview,
            expected_execution_context=context(),
            principal_context=actor,
        )
    assert drift.value.code == "WORK_ITEM_REALITY_DRIFT"
    assert domain_counts(service) == (0, 0, 0)


def test_attempt_apply_rechecks_signed_reality_inside_canonical_write_transaction(
    tmp_path: Path,
) -> None:
    actor = principal(permissions={"work_item.ready", "work_item.start_delivery"})

    class RacingService(WorkItemApplicationService):
        armed = False
        work_item_id = ""

        def create_execution_attempt(
            self,
            command: dict[str, object],
            *,
            expected_mutable_reality: dict[str, object] | None = None,
        ) -> dict[str, object]:
            if self.armed:
                self.armed = False
                transition(
                    self,
                    self.work_item_id,
                    target="ready",
                    state_version=0,
                    actor=actor,
                )
            return super().create_execution_attempt(
                command,
                expected_mutable_reality=expected_mutable_reality,
            )

    _service, work_item_id = make_service(tmp_path)
    racing = RacingService(tmp_path, enabled=True, authoritative_transitions=True)
    racing.work_item_id = work_item_id
    preview = racing.preview_execution_attempt_create(
        attempt_command(work_item_id),
        execution_context=context(),
        principal_context=actor,
    )["preview"]
    racing.armed = True

    with pytest.raises(WorkItemGovernanceError) as race:
        apply_attempt(
            racing,
            preview,
            expected_execution_context=context(),
            principal_context=actor,
        )
    assert race.value.code == "WORK_ITEM_REALITY_DRIFT"
    assert domain_counts(racing) == (0, 0, 0)
