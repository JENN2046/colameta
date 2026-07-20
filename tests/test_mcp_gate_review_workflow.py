from __future__ import annotations

import copy
import hashlib
import json
import socket
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt import PyJWKClient
from jwt.algorithms import RSAAlgorithm

from runner import mcp_server as mcp_server_module
from runner.core_orchestrator import WorkflowOrchestrator
from runner.mcp_gate_review_workflow import (
    GATE_REVIEW_MAX_BINDING_ID_CHARS,
    GATE_REVIEW_MAX_BINDING_IDS_PER_FIELD,
    GATE_REVIEW_MAX_COPYABLE_APPLY_CHARS,
    GATE_REVIEW_MAX_PREVIEW_WORKFLOW_CHARS,
    GateReviewWorkflowError,
    MCPGateReviewWorkflow,
)
from runner.mcp_private_operator import OperatorSettingsStore
from runner.mcp_server import MCPPlanningBridgeServer
from runner.project_registry import ProjectRegistry
from runner.thin_governed_loop import example_stage_3_6_inputs


class _PrivateOAuthProvider:
    issuer = "https://issuer.example/"
    audience = "https://mcp.example/mcp"
    resource = "https://mcp.example/mcp"
    scopes = ("mcp:read", "mcp:preview", "mcp:commit")

    def validate_scope(self, token_payload: dict, required_scope: str) -> bool:
        return required_scope in str(token_payload.get("scope") or "").split()

    def protected_resource_metadata_url(self) -> str:
        return "https://mcp.example/.well-known/oauth-protected-resource"


def _private_auth(*, subject: str = "auth0|jenn") -> dict:
    client = "https://chatgpt.example/private-colameta"
    return {
        "mode": "external-oauth",
        "oauth_provider": _PrivateOAuthProvider(),
        "token": {
            "iss": _PrivateOAuthProvider.issuer,
            "aud": _PrivateOAuthProvider.audience,
            "sub": subject,
            "azp": client,
            "client_id": client,
            "sid": "private-app-session:gate-review",
            "scope": "mcp:read mcp:preview mcp:commit",
            "work_item_permissions": ["work_item.ready"],
        },
    }


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _loopback_json_request(
    url: str,
    *,
    payload: dict | None = None,
    token: str | None = None,
    timeout: float = 2.0,
) -> tuple[int, dict]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Accept": "application/json"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        url,
        data=body,
        headers=headers,
        method="POST" if payload is not None else "GET",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=timeout) as response:
            return int(response.status), json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return int(exc.code), json.loads(exc.read().decode("utf-8"))


def _wait_for_loopback_service(url: str, thread: threading.Thread) -> None:
    deadline = time.monotonic() + 5.0
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if not thread.is_alive():
            raise AssertionError("loopback MCP service exited during startup")
        try:
            status, payload = _loopback_json_request(url, timeout=0.25)
            if status == 200 and payload.get("service") == "colameta-mcp":
                return
        except Exception as exc:
            last_error = exc
        time.sleep(0.05)
    raise AssertionError(f"loopback MCP service did not become ready: {last_error}")


def _enable_authoritative_work_item_gate(project_root: Path) -> None:
    settings_dir = project_root / ".colameta"
    settings_dir.mkdir()
    (settings_dir / "settings.json").write_text(
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


def _create_proposed_work_item(server: MCPPlanningBridgeServer) -> dict:
    preview = server.call_tool_for_agent(
        "preview_work_item_create",
        {
            "command": {
                "origin": {
                    "kind": "manual",
                    "ref": "gate-review-workflow-test",
                    "snapshot_digest": hashlib.sha256(b"gate-review-workflow-test").hexdigest(),
                }
            }
        },
    )
    assert preview["ok"] is True
    applied = server.call_tool_for_agent(
        "apply_work_item_create",
        {"preview": preview["data"]["preview"]},
    )
    assert applied["ok"] is True
    return applied["data"]["work_item"]


def _bounded_preview_params() -> dict:
    return {
        "workflow": "gate_review_request",
        "phase": "preview",
        "work_item_id": "work_item_bounded",
        "task_version": 1,
        "target_state": "ready",
        "expected_state_version": 0,
        "decision_ids": [],
        "evidence_artifact_ids": [],
    }


def _fake_preview_dispatch(padding_chars: int = 0):
    def dispatch(name: str, params: dict) -> dict:
        assert name == "preview_work_item_transition"
        return {
            "preview": {
                "preview_id": "preview_bounded",
                "command": params["command"],
                "signature": "s" * (64 + padding_chars),
            },
            "evaluation": {"status": "allowed"},
            "gate_mode": "authoritative",
        }

    return dispatch


def test_gate_review_binding_contract_accepts_boundary_and_rejects_overflow() -> None:
    boundary_id = "i" * GATE_REVIEW_MAX_BINDING_ID_CHARS
    boundary_params = _bounded_preview_params()
    boundary_params["decision_ids"] = [
        boundary_id for _ in range(GATE_REVIEW_MAX_BINDING_IDS_PER_FIELD)
    ]
    boundary_params["evidence_artifact_ids"] = [
        boundary_id for _ in range(GATE_REVIEW_MAX_BINDING_IDS_PER_FIELD)
    ]

    boundary = MCPGateReviewWorkflow(_fake_preview_dispatch()).handle(boundary_params)

    assert boundary["ok"] is True
    assert boundary["result"]["payload_contract"] == {
        "binding_ids_per_field_max": GATE_REVIEW_MAX_BINDING_IDS_PER_FIELD,
        "binding_id_chars_max": GATE_REVIEW_MAX_BINDING_ID_CHARS,
        "copyable_apply_chars": boundary["result"]["payload_contract"][
            "copyable_apply_chars"
        ],
        "copyable_apply_chars_max": GATE_REVIEW_MAX_COPYABLE_APPLY_CHARS,
        "preview_workflow_chars_max": GATE_REVIEW_MAX_PREVIEW_WORKFLOW_CHARS,
    }

    too_many = _bounded_preview_params()
    too_many["decision_ids"] = [
        "decision_id" for _ in range(GATE_REVIEW_MAX_BINDING_IDS_PER_FIELD + 1)
    ]
    with pytest.raises(GateReviewWorkflowError) as count_error:
        MCPGateReviewWorkflow(_fake_preview_dispatch()).handle(too_many)
    assert count_error.value.error_code == "GATE_REVIEW_BINDING_COUNT_EXCEEDED"

    too_long = _bounded_preview_params()
    too_long["evidence_artifact_ids"] = ["e" * (GATE_REVIEW_MAX_BINDING_ID_CHARS + 1)]
    with pytest.raises(GateReviewWorkflowError) as length_error:
        MCPGateReviewWorkflow(_fake_preview_dispatch()).handle(too_long)
    assert length_error.value.error_code == "GATE_REVIEW_BINDING_ID_TOO_LONG"


def test_gate_review_copyable_apply_size_boundary_stays_unpacked(tmp_path: Path) -> None:
    params = _bounded_preview_params()
    baseline = MCPGateReviewWorkflow(_fake_preview_dispatch()).handle(params)
    baseline_chars = baseline["result"]["payload_contract"]["copyable_apply_chars"]
    boundary_padding = GATE_REVIEW_MAX_COPYABLE_APPLY_CHARS - baseline_chars

    boundary = MCPGateReviewWorkflow(_fake_preview_dispatch(boundary_padding)).handle(params)

    contract = boundary["result"]["payload_contract"]
    assert contract["copyable_apply_chars"] == GATE_REVIEW_MAX_COPYABLE_APPLY_CHARS
    assert len(json.dumps(boundary, ensure_ascii=False)) <= GATE_REVIEW_MAX_PREVIEW_WORKFLOW_CHARS
    tool_result = {"ok": True, "tool": "run_mcp_workflow", "data": boundary}
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="commander")
    mcp_result = server._as_mcp_call_result(tool_result, params)
    actions_result = server._package_actions_rest_response(
        "run_mcp_workflow",
        params,
        tool_result,
    )
    assert mcp_result["structuredContent"].get("packaged") is not True
    assert mcp_result["structuredContent"]["data"]["result"]["copyable_apply_call"] == (
        boundary["result"]["copyable_apply_call"]
    )
    assert actions_result.get("packaged") is not True
    assert actions_result["data"]["result"]["copyable_apply_call"] == boundary["result"][
        "copyable_apply_call"
    ]

    with pytest.raises(GateReviewWorkflowError) as overflow_error:
        MCPGateReviewWorkflow(_fake_preview_dispatch(boundary_padding + 1)).handle(params)
    assert overflow_error.value.error_code == "GATE_REVIEW_COPYABLE_APPLY_TOO_LARGE"


def test_gate_review_tool_schema_declares_bounded_binding_contract(tmp_path: Path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="commander")
    workflow_tool = next(tool for tool in server.tool_defs if tool.name == "run_mcp_workflow")
    properties = workflow_tool.input_schema["properties"]

    assert properties["work_item_id"]["maxLength"] == GATE_REVIEW_MAX_BINDING_ID_CHARS
    for field in ("decision_ids", "evidence_artifact_ids"):
        assert properties[field]["maxItems"] == GATE_REVIEW_MAX_BINDING_IDS_PER_FIELD
        assert properties[field]["items"]["maxLength"] == GATE_REVIEW_MAX_BINDING_ID_CHARS
    assert properties["idempotency_key"]["maxLength"] == GATE_REVIEW_MAX_BINDING_ID_CHARS


def test_gate_review_workflow_reuses_signed_work_item_gate_preview(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _enable_authoritative_work_item_gate(tmp_path)
    monkeypatch.setenv("COLAMETA_WORK_ITEM_PRINCIPAL_ID", "local-gate-reviewer")
    monkeypatch.setenv("COLAMETA_WORK_ITEM_PERMISSIONS", "work_item.ready")
    monkeypatch.setenv("COLAMETA_WORK_ITEM_SESSION_REF", "local-session:gate-review-workflow")
    server = MCPPlanningBridgeServer(str(tmp_path))
    created = _create_proposed_work_item(server)
    work_item_id = created["work_item_id"]
    inspected = server.call_tool_for_agent(
        "run_mcp_workflow",
        {
            "workflow": "gate_review_request",
            "phase": "inspect",
            "work_item_id": work_item_id,
        },
    )
    assert inspected["ok"] is True
    assert inspected["data"]["result"]["backend"] == "work_item_governance"
    assert inspected["data"]["result"]["work_item"]["state"] == "proposed"
    assert inspected["data"]["result"]["side_effects"] is False

    previewed = server.call_tool_for_agent(
        "run_mcp_workflow",
        {
            "workflow": "gate_review_request",
            "phase": "preview",
            "work_item_id": work_item_id,
            "task_version": 1,
            "target_state": "ready",
            "expected_state_version": 0,
            "decision_ids": [],
            "evidence_artifact_ids": [],
        },
    )
    assert previewed["ok"] is True
    preview_data = previewed["data"]
    assert preview_data["status"] == "preview_ready"
    assert preview_data["requires_confirmation"] is True
    assert preview_data["result"]["state_changed"] is False
    assert preview_data["result"]["preview"]["command"]["principal_context"]["principal_id"] == (
        "local-gate-reviewer"
    )
    apply_call = preview_data["result"]["copyable_apply_call"]
    assert apply_call["tool"] == "run_mcp_workflow"
    assert apply_call["arguments"]["confirm_gate_review"] is True
    assert "idempotency_key" not in apply_call["arguments"]

    unconfirmed_arguments = copy.deepcopy(apply_call["arguments"])
    unconfirmed_arguments["confirm_gate_review"] = False
    unconfirmed = server.call_tool_for_agent(
        "run_mcp_workflow",
        unconfirmed_arguments,
    )
    assert unconfirmed["ok"] is False
    assert unconfirmed["error_code"] == "GATE_REVIEW_CONFIRMATION_REQUIRED"

    mismatched_arguments = copy.deepcopy(apply_call["arguments"])
    mismatched_arguments["task_version"] = 2
    mismatched = server.call_tool_for_agent(
        "run_mcp_workflow",
        mismatched_arguments,
    )
    assert mismatched["ok"] is False
    assert mismatched["error_code"] == "GATE_REVIEW_PREVIEW_BINDING_MISMATCH"

    monkeypatch.setenv("COLAMETA_WORK_ITEM_PRINCIPAL_ID", "different-gate-reviewer")
    wrong_principal = server.call_tool_for_agent(
        "run_mcp_workflow",
        apply_call["arguments"],
    )
    assert wrong_principal["ok"] is False
    assert wrong_principal["error_code"] == "PREVIEW_PRINCIPAL_MISMATCH"
    monkeypatch.setenv("COLAMETA_WORK_ITEM_PRINCIPAL_ID", "local-gate-reviewer")

    applied = server.call_tool_for_agent(
        "run_mcp_workflow",
        apply_call["arguments"],
    )
    assert applied["ok"] is True
    assert applied["data"]["result"]["side_effects"] is True
    assert applied["data"]["result"]["state_changed"] is True
    assert applied["data"]["result"]["gate_result"]["work_item"]["state"] == "ready"

    status = server.call_tool_for_agent(
        "run_mcp_workflow",
        {
            "workflow": "gate_review_request",
            "phase": "status",
            "work_item_id": work_item_id,
        },
    )
    assert status["ok"] is True
    assert status["data"]["result"]["work_item"]["state"] == "ready"
    assert status["data"]["result"]["timeline"]

    replayed = server.call_tool_for_agent(
        "run_mcp_workflow",
        apply_call["arguments"],
    )
    assert replayed["ok"] is True
    assert replayed["data"]["result"]["gate_result"]["idempotent_replay"] is True
    assert replayed["data"]["result"]["side_effects"] is False


def test_gate_review_preview_fails_closed_without_authoritative_principal(tmp_path: Path) -> None:
    _enable_authoritative_work_item_gate(tmp_path)
    server = MCPPlanningBridgeServer(str(tmp_path))
    created = _create_proposed_work_item(server)

    result = server.call_tool_for_agent(
        "run_mcp_workflow",
        {
            "workflow": "gate_review_request",
            "phase": "preview",
            "work_item_id": created["work_item_id"],
            "task_version": 1,
            "target_state": "ready",
            "expected_state_version": 0,
            "decision_ids": [],
            "evidence_artifact_ids": [],
        },
    )

    assert result["ok"] is False
    assert result["error_code"] == "TRUSTED_PRINCIPAL_REQUIRED"


def test_service_mode_private_auth_discovers_and_applies_gate_review(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = tmp_path / "managed-project"
    (project / ".git").mkdir(parents=True)
    _enable_authoritative_work_item_gate(project)
    created = _create_proposed_work_item(MCPPlanningBridgeServer(str(project)))

    registry = ProjectRegistry(
        registry_path=str(tmp_path / "project-registry.json"),
        user_settings_path=str(tmp_path / "registry-settings.json"),
    )
    registered = registry.register_project(
        str(project),
        project_name="private-gate-project",
        project_mode="managed",
    )
    assert registered["ok"] is True

    operator_store = OperatorSettingsStore(str(tmp_path / "operator-config"))
    enabled = operator_store.enable(
        "auth0|jenn",
        "https://chatgpt.example/private-colameta",
    )
    assert enabled["ok"] is True
    monkeypatch.setattr(mcp_server_module, "OperatorSettingsStore", lambda: operator_store)

    server = MCPPlanningBridgeServer(
        str(tmp_path),
        service_mode=True,
        exposure_profile="commander",
    )
    server.project_registry = registry
    auth_context = _private_auth()

    discovered = server.call_tool_for_agent(
        "run_mcp_workflow",
        {
            "workflow": "gate_review_request",
            "phase": "inspect",
            "project_name": "private-gate-project",
        },
        auth_context=auth_context,
    )
    assert discovered["ok"] is True
    assert discovered["data"]["result"]["candidate_count"] == 1
    assert discovered["data"]["result"]["work_item_candidates"][0]["work_item_id"] == (
        created["work_item_id"]
    )
    select_arguments = discovered["data"]["next_actions"][0]["arguments"]
    assert select_arguments == {
        "workflow": "gate_review_request",
        "phase": "inspect",
        "work_item_id": created["work_item_id"],
        "project_name": "private-gate-project",
    }

    selected = server.call_tool_for_agent(
        "run_mcp_workflow",
        select_arguments,
        auth_context=auth_context,
    )
    preview_arguments = selected["data"]["next_actions"][0]["arguments"]
    assert preview_arguments["target_state"] == "ready"
    assert preview_arguments["expected_state_version"] == 0
    assert preview_arguments["project_name"] == "private-gate-project"

    previewed = server.call_tool_for_agent(
        "run_mcp_workflow",
        preview_arguments,
        auth_context=auth_context,
    )
    assert previewed["ok"] is True
    apply_arguments = previewed["data"]["result"]["copyable_apply_call"]["arguments"]
    assert apply_arguments["project_name"] == "private-gate-project"

    denied = server.call_tool_for_agent(
        "run_mcp_workflow",
        apply_arguments,
        auth_context=_private_auth(subject="auth0|other"),
    )
    assert denied["ok"] is False
    assert denied["error_code"] == "OPERATOR_PRINCIPAL_DENIED"

    missing_work_item_authority = _private_auth()
    missing_work_item_authority["token"].pop("work_item_permissions")
    denied = server.call_tool_for_agent(
        "run_mcp_workflow",
        apply_arguments,
        auth_context=missing_work_item_authority,
    )
    assert denied["ok"] is False
    assert denied["error_code"] == "WORK_ITEM_PRIVATE_PRINCIPAL_REQUIRED"

    missing_commit_scope = _private_auth()
    missing_commit_scope["token"]["scope"] = "mcp:read mcp:preview"
    denied = server.call_tool_for_agent(
        "run_mcp_workflow",
        apply_arguments,
        auth_context=missing_commit_scope,
    )
    assert denied["ok"] is False
    assert denied["error_code"] == "INSUFFICIENT_SCOPE"

    generic_remote_commit = server.call_tool_for_agent(
        "run_mcp_workflow",
        {
            "workflow": "small_project_patch",
            "phase": "apply",
            "project_name": "private-gate-project",
        },
        auth_context=auth_context,
    )
    assert generic_remote_commit["ok"] is False
    assert generic_remote_commit["error_code"] == "REMOTE_POLICY_DENIED"

    applied = server.call_tool_for_agent(
        "run_mcp_workflow",
        apply_arguments,
        auth_context=auth_context,
    )
    assert applied["ok"] is True
    assert applied["data"]["status"] == "succeeded"
    assert applied["data"]["result"]["outcome"] == "transition_applied"
    assert applied["data"]["result"]["gate_result"]["work_item"]["state"] == "ready"


def test_loopback_service_mode_private_oauth_applies_real_signed_gate_review(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = tmp_path / "managed-project"
    (project / ".git").mkdir(parents=True)
    _enable_authoritative_work_item_gate(project)
    created = _create_proposed_work_item(MCPPlanningBridgeServer(str(project)))

    registry = ProjectRegistry(
        registry_path=str(tmp_path / "project-registry.json"),
        user_settings_path=str(tmp_path / "registry-settings.json"),
    )
    registered = registry.register_project(
        str(project),
        project_name="loopback-private-gate",
        project_mode="managed",
    )
    assert registered["ok"] is True

    client = "https://chatgpt.example/private-colameta"
    issuer = "https://issuer.example/"
    audience = "https://mcp.example/mcp"
    operator_store = OperatorSettingsStore(str(tmp_path / "operator-config"))
    assert operator_store.enable("auth0|jenn", client)["ok"] is True
    monkeypatch.setattr(mcp_server_module, "OperatorSettingsStore", lambda: operator_store)

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = json.loads(RSAAlgorithm.to_jwk(private_key.public_key()))
    public_jwk.update({"kid": "private-gate-key", "use": "sig", "alg": "RS256"})
    jwks = {"keys": [public_jwk]}
    monkeypatch.setattr(PyJWKClient, "fetch_data", lambda _self: jwks)
    now = int(time.time())
    bearer_token = jwt.encode(
        {
            "iss": issuer,
            "aud": audience,
            "sub": "auth0|jenn",
            "azp": client,
            "client_id": client,
            "sid": "private-app-session:loopback-gate-review",
            "iat": now,
            "nbf": now - 1,
            "exp": now + 600,
            "scope": "mcp:read mcp:preview mcp:commit",
            "work_item_permissions": ["work_item.ready"],
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "private-gate-key"},
    )

    port = _free_loopback_port()
    public_base_url = f"http://127.0.0.1:{port}"
    server = MCPPlanningBridgeServer(
        str(tmp_path),
        service_mode=True,
        exposure_profile="commander",
    )
    server.project_registry = registry
    service_errors: list[BaseException] = []

    def serve() -> None:
        try:
            server.serve_http(
                host="127.0.0.1",
                port=port,
                auth_mode="external-oauth",
                public_base_url=public_base_url,
                oauth_issuer=issuer,
                oauth_jwks_url=f"{issuer}.well-known/jwks.json",
                oauth_audience=audience,
                oauth_scopes=("mcp:read", "mcp:preview", "mcp:commit"),
                oauth_algorithms=("RS256",),
                oauth_token_leeway_seconds=0,
            )
        except BaseException as exc:  # pragma: no cover - asserted after join
            service_errors.append(exc)

    service_thread = threading.Thread(target=serve, name="private-gate-loopback", daemon=True)
    service_thread.start()
    health_url = f"{public_base_url}/healthz"
    action_url = f"{public_base_url}/api/run_mcp_workflow"
    try:
        _wait_for_loopback_service(health_url, service_thread)
        unauthorized_status, unauthorized = _loopback_json_request(
            action_url,
            payload={
                "workflow": "gate_review_request",
                "phase": "inspect",
                "project_name": "loopback-private-gate",
            },
        )
        assert unauthorized_status == 401
        assert unauthorized["error_code"] == "UNAUTHORIZED"

        status, discovered = _loopback_json_request(
            action_url,
            payload={
                "workflow": "gate_review_request",
                "phase": "inspect",
                "project_name": "loopback-private-gate",
            },
            token=bearer_token,
        )
        assert status == 200
        assert discovered["ok"] is True
        assert discovered["data"]["result"]["work_item_candidates"][0]["work_item_id"] == (
            created["work_item_id"]
        )

        select_arguments = discovered["data"]["next_actions"][0]["arguments"]
        status, selected = _loopback_json_request(
            action_url,
            payload=select_arguments,
            token=bearer_token,
        )
        assert status == 200
        preview_arguments = selected["data"]["next_actions"][0]["arguments"]
        status, previewed = _loopback_json_request(
            action_url,
            payload=preview_arguments,
            token=bearer_token,
        )
        assert status == 200
        apply_arguments = previewed["data"]["result"]["copyable_apply_call"]["arguments"]
        status, applied = _loopback_json_request(
            action_url,
            payload=apply_arguments,
            token=bearer_token,
        )
        assert status == 200
        assert applied["ok"] is True
        assert applied["data"]["status"] == "succeeded"
        assert applied["data"]["result"]["outcome"] == "transition_applied"
        assert applied["data"]["result"]["gate_result"]["work_item"]["state"] == "ready"
    finally:
        if server._httpd is not None:
            server._httpd.shutdown()
        service_thread.join(timeout=5)
    assert service_thread.is_alive() is False
    assert service_errors == []


def test_rejected_gate_apply_is_not_reported_as_success(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _enable_authoritative_work_item_gate(tmp_path)
    monkeypatch.setenv("COLAMETA_WORK_ITEM_PRINCIPAL_ID", "accept-reviewer")
    monkeypatch.setenv("COLAMETA_WORK_ITEM_PERMISSIONS", "work_item.accept")
    monkeypatch.setenv("COLAMETA_WORK_ITEM_SESSION_REF", "local-session:reject-test")
    server = MCPPlanningBridgeServer(str(tmp_path))
    created = _create_proposed_work_item(server)
    previewed = server.call_tool_for_agent(
        "run_mcp_workflow",
        {
            "workflow": "gate_review_request",
            "phase": "preview",
            "work_item_id": created["work_item_id"],
            "task_version": 1,
            "target_state": "accepted",
            "expected_state_version": 0,
            "decision_ids": [],
            "evidence_artifact_ids": [],
        },
    )

    applied = server.call_tool_for_agent(
        "run_mcp_workflow",
        previewed["data"]["result"]["copyable_apply_call"]["arguments"],
    )

    assert applied["ok"] is True
    assert applied["data"]["ok"] is False
    assert applied["data"]["status"] == "rejected"
    assert applied["data"]["result"]["ok"] is False
    assert applied["data"]["result"]["outcome"] == "transition_rejected"
    assert applied["data"]["result"]["state_changed"] is False
    assert applied["data"]["blockers"] == ["TRANSITION_NOT_ALLOWED"]


def test_shadow_gate_apply_is_not_reported_as_authoritative_success(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings_dir = tmp_path / ".colameta"
    settings_dir.mkdir()
    (settings_dir / "settings.json").write_text(
        json.dumps(
            {
                "work_item_governance": {
                    "shadow_ledger_enabled": True,
                    "gate_mode": "shadow",
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("COLAMETA_WORK_ITEM_PRINCIPAL_ID", "shadow-reviewer")
    monkeypatch.setenv("COLAMETA_WORK_ITEM_PERMISSIONS", "work_item.ready")
    monkeypatch.setenv("COLAMETA_WORK_ITEM_SESSION_REF", "local-session:shadow-test")
    server = MCPPlanningBridgeServer(str(tmp_path))
    created = _create_proposed_work_item(server)
    previewed = server.call_tool_for_agent(
        "run_mcp_workflow",
        {
            "workflow": "gate_review_request",
            "phase": "preview",
            "work_item_id": created["work_item_id"],
            "task_version": 1,
            "target_state": "ready",
            "expected_state_version": 0,
            "decision_ids": [],
            "evidence_artifact_ids": [],
        },
    )

    applied = server.call_tool_for_agent(
        "run_mcp_workflow",
        previewed["data"]["result"]["copyable_apply_call"]["arguments"],
    )

    assert applied["ok"] is True
    assert applied["data"]["ok"] is False
    assert applied["data"]["status"] == "shadow_evaluated"
    assert applied["data"]["result"]["ok"] is False
    assert applied["data"]["result"]["outcome"] == "shadow_evaluated"
    assert applied["data"]["result"]["side_effects"] is False
    assert applied["data"]["result"]["state_changed"] is False


def test_commander_projection_preserves_complete_signed_gate_preview(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _enable_authoritative_work_item_gate(tmp_path)
    monkeypatch.setenv("COLAMETA_WORK_ITEM_PRINCIPAL_ID", "commander-gate-reviewer")
    monkeypatch.setenv("COLAMETA_WORK_ITEM_PERMISSIONS", "work_item.ready")
    monkeypatch.setenv("COLAMETA_WORK_ITEM_SESSION_REF", "commander-session:gate-review")
    created = _create_proposed_work_item(MCPPlanningBridgeServer(str(tmp_path)))
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="commander")

    previewed = server.call_tool_for_agent(
        "run_mcp_workflow",
        {
            "workflow": "gate_review_request",
            "phase": "preview",
            "work_item_id": created["work_item_id"],
            "task_version": 1,
            "target_state": "ready",
            "expected_state_version": 0,
            "decision_ids": [],
            "evidence_artifact_ids": [],
        },
    )

    assert previewed["ok"] is True
    preview = previewed["data"]["result"]["preview"]
    assert set(preview) == {
        "schema_version",
        "preview_id",
        "operation",
        "project_binding",
        "issued_at",
        "expires_at",
        "ttl_seconds",
        "content_digest",
        "command",
        "generated_ids",
        "signature",
    }
    apply_arguments = previewed["data"]["result"]["copyable_apply_call"]["arguments"]
    assert apply_arguments["gate_preview"] == preview

    applied = server.call_tool_for_agent("run_mcp_workflow", apply_arguments)

    assert applied["ok"] is True
    assert applied["data"]["result"]["gate_result"]["work_item"]["state"] == "ready"


def test_accept_thin_loop_points_to_read_only_gate_review_inspection() -> None:
    project_root = str(Path(__file__).resolve().parents[1])
    inputs = example_stage_3_6_inputs()
    inputs["review_feedback"] = copy.deepcopy(inputs["review_feedback"])
    inputs["review_feedback"]["review_decision_value"] = "ACCEPT"
    inputs["review_feedback"]["task_completion"] = {"result": "complete"}

    output = WorkflowOrchestrator(project_root).handle(
        "thin_governed_loop_preview",
        {
            "phase": "preview",
            "input_mode": "provided",
            "current_head": inputs["current_head"],
            "external_taskbook_claim": inputs["external_taskbook_claim"],
            "execution_envelope": inputs["execution_envelope"],
            "local_execution_receipt": inputs["local_execution_receipt"],
            "review_feedback": inputs["review_feedback"],
        },
    )

    assert output.ok is True
    assert output.result["requested_commander_action"] == (
        "ask_whether_to_request_delivery_state_gate_review"
    )
    assert output.next_actions == [
        {
            "tool": "run_mcp_workflow",
            "arguments": {"workflow": "gate_review_request", "phase": "inspect"},
            "risk_level": "info",
            "requires_confirmation": False,
            "authority": "read_only",
        }
    ]
    assert output.result["thin_loop"]["delivery_state_accepted"] is False
    assert output.result["gate_review_request_entry"] == output.next_actions[0]
