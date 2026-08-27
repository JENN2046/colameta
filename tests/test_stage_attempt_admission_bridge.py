from __future__ import annotations

import copy
from pathlib import Path

import pytest

import runner.mcp_server as mcp_server_module
from runner.confirmation_store import ConfirmationStore
from runner.mcp_server import MCPPlanningBridgeServer, MCPToolInputError
from runner.stage_attempt_admission_bridge import (
    GRANTS_RELATIVE_DIR,
    GRANT_TTL_SECONDS,
    StageAttemptAdmissionBridge,
    StageAttemptAdmissionGrantIssuer,
)
from runner.work_item_governance.canonical import canonical_sha256
from runner.work_item_governance.errors import WorkItemGovernanceError
from runner.work_item_governance.ids import new_stable_id
from runner.work_item_governance.principal import trusted_principal_context
from runner.work_item_governance.request_context import AuthenticatedTokenRequestProof
from runner.work_item_governance.service import WorkItemApplicationService


def _principal(name: str = "stage-operator"):
    return trusted_principal_context(
        principal_id=name,
        principal_kind="human",
        authenticated_by="local_session",
        granted_permissions={"work_item.start_delivery"},
        session_ref=f"session:{name}",
    )


def _context(task_id: str = "task-a", *, group: str = "group-a") -> dict[str, str]:
    return {
        "kind": "stage_parallel_task",
        "stage_id": "stage-a",
        "parallel_group_id": group,
        "task_id": task_id,
        "stage_preview_sha256": "1" * 64,
        "base_head": "2" * 64,
        "runner_plan_sha256": "3" * 64,
    }


def _service(project_root: Path) -> tuple[WorkItemApplicationService, str]:
    service = WorkItemApplicationService(project_root, enabled=True)
    preview = service.preview_work_item_create(
        {
            "origin": {
                "kind": "manual",
                "ref": "test://stage-attempt-bridge",
                "snapshot_digest": "a" * 64,
            },
            "objective": "stage attempt bridge",
            "idempotency_key": "create:stage-attempt-bridge",
        }
    )["preview"]
    work_item = service.apply_work_item_create(preview)["work_item"]
    return service, work_item["work_item_id"]


def _command(work_item_id: str) -> dict[str, object]:
    return {
        "work_item_id": work_item_id,
        "task_version": 1,
        "status": "claimed",
        "objective_ref": "objective://stage-task-a",
        "metadata": {"source": "stage-admission"},
        "external_refs": [],
    }


def _fixture(tmp_path: Path):
    service, work_item_id = _service(tmp_path)
    actor = _principal()
    store = ConfirmationStore(str(tmp_path), GRANTS_RELATIVE_DIR, GRANT_TTL_SECONDS)
    issuer = StageAttemptAdmissionGrantIssuer(str(tmp_path), store=store)
    bridge = StageAttemptAdmissionBridge(
        str(tmp_path),
        store=store,
        inspect_signed_transport=lambda preview, context: (
            service.inspect_execution_attempt_create_preview_transport(
                preview, expected_execution_context=context
            )
        ),
        resolve_attempt_artifacts=lambda work_item_id, task_version, attempt_id: (
            service.resolve_execution_attempt_artifact_refs(
                work_item_id=work_item_id,
                task_version=task_version,
                attempt_id=attempt_id,
            )
        ),
    )
    preview_result = service.preview_execution_attempt_create(
        _command(work_item_id),
        execution_context=_context(),
        principal_context=actor,
    )
    grant = issuer.store_signed_preview(preview_result)
    return service, work_item_id, actor, store, issuer, bridge, grant


def _apply_authoritatively(service, actor, issuer, grant_id, context):
    preview = issuer.load_signed_preview_for_apply(
        grant_id, expected_execution_context=context
    )
    prepared = service.prepare_execution_attempt_create_apply(
        preview,
        expected_execution_context=context,
        principal_context=actor,
    )
    result = service.create_execution_attempt(
        prepared["attempt_command"],
        expected_mutable_reality=prepared["expected_mutable_reality"],
    )
    result = {
        **result,
        "preview_id": prepared["preview_id"],
        "execution_context": prepared["execution_context"],
    }
    issuer.record_attempt_admission(
        grant_id,
        expected_execution_context=context,
        apply_result=result,
    )
    return result


def _attempt_count(service: WorkItemApplicationService) -> int:
    with service.ledger.read_connection() as connection:
        return int(connection.execute("SELECT COUNT(*) FROM execution_attempts").fetchone()[0])


def test_stage_bridge_is_read_only_and_missing_admission_requires_authoritative_action(
    tmp_path: Path,
) -> None:
    service, work_item_id, _, _, _, bridge, grant = _fixture(tmp_path)
    inspected = bridge.inspect_task_grant(
        grant["grant_id"], expected_execution_context=_context()
    )
    admission = bridge.inspect_task_attempt_admission(
        grant["grant_id"], expected_execution_context=_context()
    )
    assert inspected["work_item_id"] == work_item_id
    assert admission["status"] == "governance_admission_required"
    assert _attempt_count(service) == 0
    assert not hasattr(bridge, "apply_task_attempt_admission")
    assert not any(
        token in key.lower()
        for key in vars(bridge)
        for token in ("principal", "proof", "request_context", "gateway", "apply")
    )


def test_authoritative_apply_records_exact_attempt_and_replay(tmp_path: Path) -> None:
    service, work_item_id, actor, _, issuer, bridge, grant = _fixture(tmp_path)
    first = _apply_authoritatively(
        service, actor, issuer, grant["grant_id"], _context()
    )
    replay = _apply_authoritatively(
        service, actor, issuer, grant["grant_id"], _context()
    )
    inspected = bridge.inspect_task_attempt_admission(
        grant["grant_id"], expected_execution_context=_context()
    )
    artifacts = bridge.resolve_task_attempt_artifacts(
        grant["grant_id"],
        expected_execution_context=_context(),
        attempt_id=first["attempt"]["attempt_id"],
    )
    assert first["attempt"]["work_item_id"] == work_item_id
    assert replay["attempt"]["attempt_id"] == first["attempt"]["attempt_id"]
    assert replay["idempotent_replay"] is True
    assert inspected["attempt"]["attempt_id"] == first["attempt"]["attempt_id"]
    assert artifacts["artifact_refs"] == []
    assert artifacts["ledger_backed"] is True
    assert artifacts["synthetic_empty"] is False
    assert _attempt_count(service) == 1


@pytest.mark.parametrize(
    ("field", "value"),
    (("task_id", "task-b"), ("parallel_group_id", "group-b"), ("stage_id", "stage-b")),
)
def test_grant_rejects_stage_context_substitution_without_write(
    tmp_path: Path, field: str, value: str
) -> None:
    service, _, _, _, _, bridge, grant = _fixture(tmp_path)
    wrong = {**_context(), field: value}
    with pytest.raises(WorkItemGovernanceError) as rejected:
        bridge.inspect_task_attempt_admission(
            grant["grant_id"], expected_execution_context=wrong
        )
    assert rejected.value.code == "STAGE_ATTEMPT_GRANT_CONTEXT_MISMATCH"
    assert _attempt_count(service) == 0


def test_transport_tamper_and_cross_project_use_fail_closed(tmp_path: Path) -> None:
    service, _, _, store, _, bridge, grant = _fixture(tmp_path)
    record = store.read(grant["grant_id"])
    assert record is not None
    tampered = copy.deepcopy(record)
    tampered["nested_preview"]["command"]["attempt_command"]["task_version"] = 2
    tampered["nested_preview_sha256"] = canonical_sha256(tampered["nested_preview"])
    store.write(grant["grant_id"], tampered)
    with pytest.raises(WorkItemGovernanceError) as altered:
        bridge.inspect_task_grant(
            grant["grant_id"], expected_execution_context=_context()
        )
    assert altered.value.code == "PREVIEW_SIGNATURE_INVALID"
    assert _attempt_count(service) == 0
    store.write(grant["grant_id"], record)
    other = StageAttemptAdmissionBridge(
        str(tmp_path / "other"),
        inspect_signed_transport=lambda _preview, _context: {},
        resolve_attempt_artifacts=lambda _work_item, _version, _attempt: {},
    )
    with pytest.raises(WorkItemGovernanceError):
        other.inspect_task_grant(
            grant["grant_id"], expected_execution_context=_context()
        )


def test_attempt_admission_cross_layer_swap_fails_closed(tmp_path: Path) -> None:
    service, _, actor, store, issuer, bridge, grant = _fixture(tmp_path)
    _apply_authoritatively(service, actor, issuer, grant["grant_id"], _context())
    record = store.read(grant["grant_id"])
    assert record is not None
    record["attempt_admission"]["attempt_id"] = new_stable_id("attempt")
    store.write(grant["grant_id"], record)
    with pytest.raises(WorkItemGovernanceError) as rejected:
        bridge.inspect_task_attempt_admission(
            grant["grant_id"], expected_execution_context=_context()
        )
    assert rejected.value.code == "STAGE_ATTEMPT_ADMISSION_RECORD_INVALID"
    assert _attempt_count(service) == 1


def _proof(seed: str) -> AuthenticatedTokenRequestProof:
    return AuthenticatedTokenRequestProof(
        mode="token",
        lease_id="lease-test",
        listener_instance_nonce=seed * 64,
        request_nonce=seed.upper() * 64,
        token_file_sha256="a" * 64,
        token_evidence_digest="b" * 64,
        signature="c" * 64,
    )


@pytest.mark.parametrize("pilot", [False, True], ids=["canary", "pilot"])
def test_production_mcp_preview_and_apply_route_uses_fresh_governance_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pilot: bool
) -> None:
    actor = _principal()
    proofs = iter((_proof("d"), _proof("e")))
    monkeypatch.setattr(mcp_server_module, "current_work_item_principal", lambda: actor)
    monkeypatch.setattr(
        mcp_server_module,
        "current_authenticated_token_request_proof",
        lambda: next(proofs),
    )
    calls: list[tuple[str, object]] = []
    preview_id = new_stable_id("preview")
    attempt_id = new_stable_id("attempt")
    work_item_id = new_stable_id("work_item")

    def execute_stub(project_root, operation, params, **kwargs):
        calls.append((operation, kwargs.get("authenticated_request_proof")))
        if operation == "preview_execution_attempt_create":
            return {
                "status": "preview_ready",
                "preview": {
                    "preview_id": preview_id,
                    "issued_at": "2026-01-01T00:00:00Z",
                    "expires_at": "2099-01-01T00:00:00Z",
                    "command": {
                        "attempt_command": {
                            "work_item_id": work_item_id,
                            "task_version": 1,
                        },
                        "execution_context": _context(),
                    },
                },
            }
        assert params["preview"]["preview_id"] == preview_id
        return {
            "status": "attempt_created",
            "attempt": {
                "work_item_id": work_item_id,
                "task_version": 1,
                "attempt_id": attempt_id,
                "source_event_key": "stage:test",
            },
            "preview_id": preview_id,
            "idempotent_replay": False,
        }

    monkeypatch.setattr(mcp_server_module, "execute_work_item_mcp_command", execute_stub)
    server = MCPPlanningBridgeServer(
        str(tmp_path),
        exposure_profile="authoritative_canary",
        work_item_scope_mode=("bounded_single_project_pilot.v1" if pilot else None),
    )
    server._token_transport_proof_validator = lambda _context: True
    preview_dispatch = server._call_tool(
        "preview_execution_attempt_create",
        {"command": {"work_item_id": work_item_id}, "execution_context": _context()},
        auth_context={"mode": "token"},
    )
    assert preview_dispatch["ok"] is True, preview_dispatch
    grant = preview_dispatch["data"]
    apply_dispatch = server._call_tool(
        "apply_execution_attempt_create",
        {"grant_id": grant["grant_id"], "execution_context": _context()},
        auth_context={"mode": "token"},
    )
    assert apply_dispatch["ok"] is True, apply_dispatch
    applied = apply_dispatch["data"]
    assert grant["grant_id"] == preview_id
    assert "preview" not in grant
    assert applied["attempt"]["attempt_id"] == attempt_id
    assert [name for name, _ in calls] == [
        "preview_execution_attempt_create",
        "apply_execution_attempt_create",
    ]
    assert calls[0][1] is not calls[1][1]
    stage_bridge = MCPPlanningBridgeServer(
        str(tmp_path), exposure_profile="normal"
    )._stage_task_attempt_admission_bridge()
    assert isinstance(stage_bridge, StageAttemptAdmissionBridge)
    assert not hasattr(stage_bridge, "apply_task_attempt_admission")


@pytest.mark.parametrize("profile", ["normal", "maintainer", "legacy"])
@pytest.mark.parametrize(
    "primitive", ["preview_execution_attempt_create", "apply_execution_attempt_create"]
)
def test_authority_primitive_handler_self_defends_outside_authoritative_composition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    profile: str,
    primitive: str,
) -> None:
    calls: list[str] = []

    def execute_stub(_project_root, operation, _params, **_kwargs):
        calls.append(operation)
        return {"unexpected": True}

    monkeypatch.setattr(mcp_server_module, "execute_work_item_mcp_command", execute_stub)
    server = MCPPlanningBridgeServer(str(tmp_path / profile), exposure_profile=profile)

    with pytest.raises(MCPToolInputError) as rejected:
        server._tool_work_item_command(primitive, {})

    assert rejected.value.error_code == "AUTHORITY_PRIMITIVE_COMPOSITION_REQUIRED"
    assert calls == []
    assert not (tmp_path / profile / ".colameta").exists()


def test_profile_contracts_are_exact_16_without_stage_tool() -> None:
    for pilot in (False, True):
        server = MCPPlanningBridgeServer(
            ".",
            exposure_profile="authoritative_canary",
            work_item_scope_mode=("bounded_single_project_pilot.v1" if pilot else None),
        )
        names = [
            tool.name
            for tool in server._filter_tools_by_exposure_profile(server.tool_defs)
        ]
        assert len(names) == 16
        assert "preview_execution_attempt_create" in names
        assert "apply_execution_attempt_create" in names
        assert "manage_stage_parallel_executor_group" not in names
