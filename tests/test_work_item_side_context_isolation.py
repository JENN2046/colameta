from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from runner.app_submission_work_items import AppSubmissionWorkItemCommands
from runner.commander_projections import CommanderProjectionService
from runner.stable_promotion_work_item import StablePromotionWorkItemReader
from runner.work_item_governance.service import WorkItemApplicationService
from runner.work_item_governance.principal import PrincipalContext, trusted_principal_context
from runner.work_item_governance.errors import WorkItemGovernanceError
from runner.work_item_governance.ids import new_stable_id


def enable(tmp_path: Path) -> None:
    settings = tmp_path / ".colameta"
    settings.mkdir(exist_ok=True)
    (settings / "settings.json").write_text(
        json.dumps(
            {
                "work_item_governance": {
                    "shadow_ledger_enabled": True,
                    "gate_mode": "authoritative",
                }
            }
        ),
        encoding="utf-8",
    )


def commander_principal() -> PrincipalContext:
    return trusted_principal_context(
        principal_id="reviewer",
        principal_kind="human",
        authenticated_by="commander",
        granted_permissions=[
            "work_item.ready",
            "work_item.start_delivery",
            "work_item.submit",
            "work_item.accept",
        ],
        session_ref="commander:side-context-test",
    )


def transition(
    service: WorkItemApplicationService,
    wi: str,
    target: str,
    version: int,
    authority: str,
    decisions: list[str] | None = None,
    artifacts: list[str] | None = None,
) -> None:
    principal = commander_principal()
    preview = service.preview_work_item_transition(
        {
            "work_item_id": wi,
            "task_version": 1,
            "target_state": target,
            "expected_state_version": version,
            "decision_ids": decisions or [],
            "evidence_artifact_ids": artifacts or [],
            "idempotency_key": f"side:{target}",
        },
        principal_context=principal,
    )
    assert service.apply_work_item_transition(
        preview["preview"],
        principal_context=principal,
    )["state_changed"] is True


def test_app_submission_uses_explicit_formal_preview_apply(tmp_path: Path) -> None:
    enable(tmp_path)
    adapter = AppSubmissionWorkItemCommands(tmp_path)
    preview = adapter.preview_create(
        submission_ref="submission://app/1",
        snapshot_digest=hashlib.sha256(b"submission-1").hexdigest(),
        attributes={"app_name": "ColaMeta"},
    )
    assert preview["creates_work_item"] is False
    assert adapter.gateway.execute("list_work_items", {})["count"] == 0
    applied = adapter.apply_create(preview["preview"])
    assert applied["created"] is True
    reference = adapter.reference_existing(applied["work_item"]["work_item_id"])
    assert reference["can_write_ledger_directly"] is False


def test_connector_projection_failure_does_not_change_work_item_state(tmp_path: Path) -> None:
    enable(tmp_path)
    app = AppSubmissionWorkItemCommands(tmp_path)
    preview = app.preview_create(
        submission_ref="submission://app/connector",
        snapshot_digest=hashlib.sha256(b"connector").hexdigest(),
    )
    wi = app.apply_create(preview["preview"])["work_item"]["work_item_id"]
    projection = CommanderProjectionService(
        tmp_path,
        service_operations_reader=lambda: {"connector": "failed", "oauth": "unavailable"},
        app_submission_reader=lambda: {"submission": "draft"},
    ).project()
    assert projection["sections"]["service_operations"]["can_write_work_item_state"] is False
    assert projection["sections"]["core"]["work_items"]["items"][0]["state"] == "proposed"
    assert app.gateway.execute("get_work_item", {"work_item_id": wi})["state"] == "proposed"


def test_connector_projection_exception_isolated_from_commander_core(tmp_path: Path) -> None:
    enable(tmp_path)
    app = AppSubmissionWorkItemCommands(tmp_path)
    preview = app.preview_create(
        submission_ref="submission://app/connector-exception",
        snapshot_digest=hashlib.sha256(b"connector-exception").hexdigest(),
    )
    wi = app.apply_create(preview["preview"])["work_item"]["work_item_id"]

    def unavailable_connector() -> dict:
        raise RuntimeError("connector transport failed")

    projection = CommanderProjectionService(
        tmp_path,
        service_operations_reader=unavailable_connector,
    ).project()
    sections = projection["sections"]
    assert sections["service_operations"]["read_model"]["status"] == "unavailable"
    assert sections["core"]["work_items"]["items"][0]["work_item_id"] == wi
    assert app.gateway.execute("get_work_item", {"work_item_id": wi})["state"] == "proposed"


def test_stable_promotion_rejects_artifact_not_bound_to_acceptance_gate(tmp_path: Path) -> None:
    enable(tmp_path)
    app = AppSubmissionWorkItemCommands(tmp_path)
    preview = app.preview_create(
        submission_ref="submission://app/promotion",
        snapshot_digest=hashlib.sha256(b"promotion").hexdigest(),
    )
    wi = app.apply_create(preview["preview"])["work_item"]["work_item_id"]
    reader = StablePromotionWorkItemReader(tmp_path)
    blocked = reader.build_candidate(
        work_item_id=wi,
        exact_commit="a" * 40,
        artifact_manifest=[],
        deployment_authorization={"exact_commit": "a" * 40, "authorized_by": "operator"},
    )
    assert blocked["eligible"] is False
    assert {item["code"] for item in blocked["blockers"]} >= {
        "WORK_ITEM_NOT_ACCEPTED",
        "ARTIFACT_MANIFEST_REQUIRED",
        "EXACT_COMMIT_ARTIFACT_REQUIRED",
    }

    service = WorkItemApplicationService(tmp_path)
    transition(service, wi, "ready", 0, "work_item.ready")
    transition(service, wi, "in_delivery", 1, "work_item.start_delivery")
    artifact = service.register_artifact_reference(
        {
            "work_item_id": wi,
            "task_version": 1,
            "kind": "git_commit",
            "uri": "git://commit/" + "a" * 40,
            "immutable_ref": "a" * 40,
            "digest": "b" * 64,
            "source_event_key": "promotion:artifact",
        }
    )["artifact"]
    submit = service.record_review_decision(
        {
            "work_item_id": wi,
            "task_version": 1,
            "action": "submit",
            "evidence_artifact_ids": [artifact["artifact_id"]],
            "reason": "Submit",
            "source_event_key": "promotion:submit",
        },
        principal_context=commander_principal(),
    )["decision"]
    transition(
        service,
        wi,
        "submitted",
        2,
        "work_item.submit",
        [submit["decision_id"]],
        [artifact["artifact_id"]],
    )
    accept = service.record_review_decision(
        {
            "work_item_id": wi,
            "task_version": 1,
            "action": "accept",
            "evidence_artifact_ids": [artifact["artifact_id"]],
            "reason": "Accept",
            "source_event_key": "promotion:accept",
        },
        principal_context=commander_principal(),
    )["decision"]
    transition(
        service,
        wi,
        "accepted",
        3,
        "work_item.accept",
        [accept["decision_id"]],
        [artifact["artifact_id"]],
    )
    candidate = reader.build_candidate(
        work_item_id=wi,
        exact_commit="a" * 40,
        artifact_manifest=[{"artifact_id": artifact["artifact_id"], "digest": artifact["digest"]}],
        deployment_authorization={"exact_commit": "a" * 40, "authorized_by": "operator"},
    )
    assert candidate["eligible"] is True
    inspection = reader.inspect_accepted_candidate(
        work_item_id=wi,
        exact_commit="a" * 40,
    )
    assert inspection["acceptance_binding_valid"] is True
    assert inspection["deployment_authorization_present"] is False
    assert inspection["eligible"] is False
    assert candidate["authority_boundary"]["can_write_work_item_state"] is False
    assert candidate["authority_boundary"]["promotion_triggered"] is False
    accepted_item = service.get_work_item(wi)
    assert accepted_item["state"] == "accepted"
    assert accepted_item["accepted_evidence_manifest"]["artifact_ids"] == [artifact["artifact_id"]]

    with pytest.raises(WorkItemGovernanceError) as raised:
        service.register_artifact_reference(
            {
                "work_item_id": wi,
                "task_version": 1,
                "kind": "git_commit",
                "uri": "git://commit/" + "c" * 40,
                "immutable_ref": "c" * 40,
                "digest": "d" * 64,
                "source_event_key": "promotion:post-accept-artifact",
            }
        )
    assert raised.value.code == "TERMINAL_ARTIFACT_SET_FROZEN"
    assert service.get_work_item(wi)["accepted_evidence_manifest"] == accepted_item["accepted_evidence_manifest"]

    unbound = reader.build_candidate(
        work_item_id=wi,
        exact_commit="c" * 40,
        artifact_manifest=[{"artifact_id": new_stable_id("artifact"), "digest": "d" * 64}],
        deployment_authorization={"exact_commit": "c" * 40, "authorized_by": "operator"},
    )
    assert unbound["eligible"] is False
    assert "ARTIFACT_NOT_IN_ACCEPTANCE_MANIFEST" in {
        blocker["code"] for blocker in unbound["blockers"]
    }
