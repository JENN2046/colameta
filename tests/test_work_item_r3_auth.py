from __future__ import annotations

import json
import os
import socket
import threading
import time
import urllib.error
import urllib.request
from dataclasses import replace
from pathlib import Path

import pytest

import runner.work_item_governance.request_context as request_context_module
from runner.mcp_server import MCPPlanningBridgeServer
from runner.work_item_commands import WorkItemCommandGateway
from runner.work_item_governance.errors import WorkItemGovernanceError
from runner.work_item_governance.principal import trusted_principal_context
from runner.work_item_governance.request_context import (
    AuthenticatedTokenRequestProof,
    token_request_proof_signature,
)
from runner.work_item_principal_adapter import (
    current_authenticated_token_request_proof,
    work_item_authenticated_request_scope,
)
from work_item_r2_helpers import (
    _active_test_token_proof,
    all_permissions_principal,
    install_active_lease,
    make_fixture,
    simulated_active_transport_proof,
)


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _proof_status(_arguments: dict[str, object]) -> dict[str, object]:
    proof = current_authenticated_token_request_proof()
    return {
        "proof_present": proof is not None,
        "proof_active": bool(proof is not None and proof.active),
    }


def _forged_proof() -> AuthenticatedTokenRequestProof:
    return AuthenticatedTokenRequestProof(
        mode="token",
        lease_id="lease_fake",
        listener_instance_nonce="1" * 64,
        request_nonce="2" * 64,
        token_file_sha256="3" * 64,
        token_evidence_digest="4" * 64,
        signature="5" * 64,
    )


def test_plain_token_dict_and_forged_objects_cannot_mint_request_proof() -> None:
    assert not hasattr(
        request_context_module,
        "_issue_authenticated_token_transport_capability",
    )
    assert not hasattr(
        request_context_module,
        "_issue_authenticated_token_request_proof",
    )
    assert not hasattr(
        request_context_module,
        "_AuthenticatedTokenRequestProofRegistry",
    )
    with work_item_authenticated_request_scope({"mode": "token"}) as plain_dict_proof:
        assert plain_dict_proof is None
        assert current_authenticated_token_request_proof() is None

    forged_capability = object()
    with work_item_authenticated_request_scope(forged_capability) as forged_proof:
        assert forged_proof is None

    forged_proof = _forged_proof()
    object.__setattr__(forged_proof, "_issuer_seal", object())
    object.__setattr__(forged_proof, "_active_validator", lambda _proof: True)
    assert forged_proof.trusted is False
    assert forged_proof.active is False
    assert forged_proof.verify_signature("attacker-selected-token") is False
    with pytest.raises(TypeError):
        AuthenticatedTokenRequestProof(  # type: ignore[call-arg]
            mode="token",
            lease_id="lease_fake",
            listener_instance_nonce="1" * 64,
            request_nonce="2" * 64,
            token_file_sha256="3" * 64,
            token_evidence_digest="4" * 64,
            signature="5" * 64,
            _active_validator=lambda _proof: True,
        )


def test_lease_rejects_principal_with_different_authentication_method(
    tmp_path: Path,
) -> None:
    principal = all_permissions_principal()
    fixture, raw = make_fixture(tmp_path, principal)
    service = install_active_lease(tmp_path, fixture, principal)
    service.principal_context = trusted_principal_context(
        principal_id=principal.principal_id,
        principal_kind=principal.principal_kind,
        authenticated_by="oauth",
        granted_permissions=principal.granted_permissions,
        session_ref=principal.session_ref,
    )

    with pytest.raises(WorkItemGovernanceError) as exc_info:
        service.preview_work_item_create(raw["create"])

    assert exc_info.value.code == "ACTIVATION_PRINCIPAL_MISMATCH"


def test_agent_and_direct_python_token_dict_do_not_receive_transport_proof(tmp_path) -> None:
    server = MCPPlanningBridgeServer(
        str(tmp_path),
        exposure_profile="authoritative_canary",
    )
    server.tools["get_work_item_governance_status"] = _proof_status

    agent_result = server.call_tool_for_agent(
        "get_work_item_governance_status",
        {},
        auth_context={"mode": "token"},
    )
    assert agent_result["ok"] is False
    assert agent_result["error_code"] == "UNAUTHORIZED"

    direct_result = server._call_tool(
        "get_work_item_governance_status",
        {},
        auth_context={"mode": "token"},
    )
    assert direct_result["ok"] is False
    assert direct_result["error_code"] == "UNAUTHORIZED"
    forged_result = server.call_tool_for_agent(
        "get_work_item_governance_status",
        {},
        auth_context=_forged_proof(),  # type: ignore[arg-type]
    )
    assert forged_result["ok"] is False
    assert forged_result["error_code"] == "UNAUTHORIZED"


def test_guard_rejects_token_holder_forgery_and_copied_request_context(tmp_path: Path) -> None:
    principal = all_permissions_principal()
    fixture, raw = make_fixture(tmp_path, principal)
    service = install_active_lease(tmp_path, fixture, principal)
    guard = service.activation_guard
    assert guard is not None
    with service.ledger.read_connection() as connection:
        lease_id = str(connection.execute("SELECT lease_id FROM activation_leases").fetchone()[0])
        bindings = {
            str(row["key"]): str(row["value"])
            for row in connection.execute(
                "SELECT key,value FROM ledger_meta WHERE key LIKE 'authoritative_canary_token_%'"
            ).fetchall()
        }
    auth_file = Path(os.environ["XDG_CONFIG_HOME"]) / "colameta" / "auth.json"
    auth_token = str(json.loads(auth_file.read_text(encoding="utf-8"))["auth_token"])
    unsigned = {
        "schema_version": "authenticated_token_request_proof.v2",
        "mode": "token",
        "lease_id": lease_id,
        "listener_instance_nonce": "1" * 64,
        "request_nonce": "2" * 64,
        "token_file_sha256": bindings["authoritative_canary_token_file_sha256"],
        "token_evidence_digest": bindings["authoritative_canary_token_evidence_digest"],
    }
    forged = AuthenticatedTokenRequestProof(
        mode="token",
        lease_id=lease_id,
        listener_instance_nonce="1" * 64,
        request_nonce="2" * 64,
        token_file_sha256=bindings["authoritative_canary_token_file_sha256"],
        token_evidence_digest=bindings["authoritative_canary_token_evidence_digest"],
        signature=token_request_proof_signature(
            auth_token=auth_token,
            unsigned_record=unsigned,
        ),
    )
    assert forged.verify_signature(auth_token) is True
    assert forged.active is False
    with pytest.raises(WorkItemGovernanceError) as forged_error:
        guard.mint_request_context(proof=forged, principal_context=principal)
    assert forged_error.value.code == "AUTHENTICATED_REQUEST_CONTEXT_REQUIRED"

    copied_context = replace(service.request_context)
    service.request_context = copied_context
    with pytest.raises(WorkItemGovernanceError) as copied_error:
        service.preview_work_item_create(raw["create"])
    assert copied_error.value.code == "AUTHENTICATED_REQUEST_CONTEXT_REQUIRED"
    with service.ledger.read_connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM work_items").fetchone()[0] == 0


def test_guard_request_context_is_one_request_and_explicitly_retired(tmp_path: Path) -> None:
    principal = all_permissions_principal()
    fixture, _raw = make_fixture(tmp_path, principal)
    service = install_active_lease(tmp_path, fixture, principal)
    guard = service.activation_guard
    request_context = service.request_context
    assert guard is not None
    assert request_context is not None
    assert request_context.active is True
    assert request_context.trusted is True

    assert guard.retire_request_context(request_context) is True
    assert guard.retire_request_context(request_context) is False
    assert request_context.active is False
    assert request_context.trusted is False
    with pytest.raises(WorkItemGovernanceError) as retired_error:
        service.preview_work_item_create(_raw["create"])
    assert retired_error.value.code == "AUTHENTICATED_REQUEST_CONTEXT_REQUIRED"


def test_gateway_retires_context_and_never_reuses_consumed_proof(tmp_path: Path) -> None:
    principal = all_permissions_principal()
    fixture, raw = make_fixture(tmp_path, principal)
    seed = install_active_lease(tmp_path, fixture, principal)
    with seed.ledger.read_connection() as connection:
        row = connection.execute("SELECT lease_id FROM activation_leases").fetchone()
        bindings = {
            str(item["key"]): str(item["value"])
            for item in connection.execute(
                "SELECT key,value FROM ledger_meta WHERE key LIKE 'authoritative_canary_token_%'"
            ).fetchall()
        }
    auth_file = Path(os.environ["XDG_CONFIG_HOME"]) / "colameta" / "auth.json"
    auth_token = str(json.loads(auth_file.read_text(encoding="utf-8"))["auth_token"])
    proof = _active_test_token_proof(
        auth_token=auth_token,
        lease_id=str(row["lease_id"]),
        token_file_sha256=bindings["authoritative_canary_token_file_sha256"],
        token_evidence_digest=bindings["authoritative_canary_token_evidence_digest"],
    )
    gateway = WorkItemCommandGateway(
        tmp_path,
        authoritative_transitions=True,
        principal_context=principal,
        authoritative_canary=True,
        authenticated_request_proof=proof,
    )
    guard = gateway.service.activation_guard
    assert guard is not None
    captured_contexts = []
    original_mint = guard.mint_request_context

    def capture_context(**kwargs):
        context = original_mint(**kwargs)
        captured_contexts.append(context)
        return context

    guard.mint_request_context = capture_context  # type: ignore[method-assign]
    with simulated_active_transport_proof(proof):
        preview = gateway.execute("preview_work_item_create", {"command": raw["create"]})
    assert "preview" in preview
    assert len(captured_contexts) == 1
    assert captured_contexts[0].active is False
    assert gateway.service.request_context is None
    assert gateway.authenticated_request_proof is None

    with pytest.raises(WorkItemGovernanceError) as replay_error:
        gateway.execute("preview_work_item_create", {"command": raw["create"]})
    assert replay_error.value.code == "AUTHENTICATED_REQUEST_CONTEXT_REQUIRED"


def test_real_http_bearer_verification_mints_trusted_transport_proof(tmp_path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path))
    server.tools["get_agent_consumer_contract"] = _proof_status
    port = _free_loopback_port()
    bearer = "r3-private-http-token"
    thread = threading.Thread(
        target=server.serve_http,
        kwargs={
            "host": "127.0.0.1",
            "port": port,
            "auth_mode": "token",
            "auth_token": bearer,
        },
        daemon=True,
    )
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not hasattr(server, "_httpd"):
            if not thread.is_alive() or time.monotonic() >= deadline:
                raise AssertionError("HTTP test server failed to start")
            time.sleep(0.01)

        payload = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "get_agent_consumer_contract",
                "params": {},
            }
        ).encode("utf-8")
        wrong = urllib.request.Request(
            f"http://127.0.0.1:{port}/mcp",
            data=payload,
            headers={
                "Authorization": "Bearer wrong",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            urllib.request.urlopen(wrong, timeout=2)
        except urllib.error.HTTPError as exc:
            assert exc.code == 401
        else:
            raise AssertionError("wrong Bearer Token was accepted")

        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/mcp",
            data=payload,
            headers={
                "Authorization": f"Bearer {bearer}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            body = json.loads(response.read().decode("utf-8"))
        assert body["result"]["ok"] is True
        assert body["result"]["data"] == {
            "proof_present": True,
            "proof_active": True,
        }
    finally:
        httpd = getattr(server, "_httpd", None)
        if httpd is not None:
            httpd.shutdown()
        thread.join(timeout=5)
        assert not thread.is_alive()


def test_listener_capability_is_request_local_and_cannot_cross_servers(tmp_path) -> None:
    bearer_one = "r3-listener-one"
    bearer_two = "r3-listener-two"
    server_one = MCPPlanningBridgeServer(str(tmp_path / "one"))
    server_two = MCPPlanningBridgeServer(str(tmp_path / "two"))
    server_one.tools["get_agent_consumer_contract"] = _proof_status
    server_two.tools["get_work_item_governance_status"] = _proof_status
    captured: list[object] = []
    original_handle = server_one._handle_jsonrpc_request

    def capture_handle(request, auth_context=None):
        if auth_context is not None:
            captured.append(auth_context)
        return original_handle(request, auth_context=auth_context)

    server_one._handle_jsonrpc_request = capture_handle  # type: ignore[method-assign]
    port_one = _free_loopback_port()
    port_two = _free_loopback_port()
    thread_one = threading.Thread(
        target=server_one.serve_http,
        kwargs={
            "host": "127.0.0.1",
            "port": port_one,
            "auth_mode": "token",
            "auth_token": bearer_one,
        },
        daemon=True,
    )
    thread_two = threading.Thread(
        target=server_two.serve_http,
        kwargs={
            "host": "127.0.0.1",
            "port": port_two,
            "auth_mode": "token",
            "auth_token": bearer_two,
        },
        daemon=True,
    )
    thread_one.start()
    thread_two.start()
    try:
        deadline = time.monotonic() + 5
        while not hasattr(server_one, "_httpd") or not hasattr(server_two, "_httpd"):
            if not thread_one.is_alive() or not thread_two.is_alive() or time.monotonic() >= deadline:
                raise AssertionError("listener-boundary test servers failed to start")
            time.sleep(0.01)

        payload = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "get_agent_consumer_contract",
                "params": {},
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"http://127.0.0.1:{port_one}/mcp",
            data=payload,
            headers={
                "Authorization": f"Bearer {bearer_one}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            body = json.loads(response.read().decode("utf-8"))
        assert body["result"]["data"]["proof_active"] is True
        assert len(captured) == 1
        capability = captured[0]
        assert isinstance(capability, AuthenticatedTokenRequestProof)
        assert capability.active is False
        assert capability.verify_signature(bearer_one) is True
        assert capability.verify_signature(bearer_two) is False

        server_one.mcp_exposure_profile = "authoritative_canary"
        server_two.mcp_exposure_profile = "authoritative_canary"
        same_listener_replay = server_one.call_tool_for_agent(
            "get_work_item_governance_status",
            {},
            auth_context=capability,  # type: ignore[arg-type]
        )
        cross_listener_replay = server_two._call_tool(
            "get_work_item_governance_status",
            {},
            auth_context=capability,
        )
        assert same_listener_replay["error_code"] == "UNAUTHORIZED"
        assert cross_listener_replay["error_code"] == "UNAUTHORIZED"
    finally:
        for server in (server_one, server_two):
            httpd = getattr(server, "_httpd", None)
            if httpd is not None:
                httpd.shutdown()
        thread_one.join(timeout=5)
        thread_two.join(timeout=5)
        assert not thread_one.is_alive()
        assert not thread_two.is_alive()
