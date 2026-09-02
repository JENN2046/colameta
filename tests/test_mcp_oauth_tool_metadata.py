from __future__ import annotations

import json
import socket
import threading
import time
from types import SimpleNamespace
from urllib.request import urlopen

from runner.mcp_external_oauth import ExternalOAuthConfig, ExternalOAuthProvider
from runner.mcp_oauth import DEFAULT_SCOPES
from runner.mcp_server import (
    MCP_EXPOSURE_PROFILE_OWNER,
    MCPPlanningBridgeServer,
    _external_oauth_scopes_for_profile,
)


def _listed_tools(tmp_path, *, mode: str, scopes: tuple[str, ...]) -> dict[str, dict[str, object]]:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="commander")
    response = server._handle_jsonrpc_request(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        auth_context={
            "mode": mode,
            "oauth_provider": SimpleNamespace(scopes=scopes),
            "token": {},
        },
    )
    return {tool["name"]: tool for tool in response["result"]["tools"]}


def test_external_oauth_tools_publish_chatgpt_security_scheme_mirrors(tmp_path) -> None:
    tools = _listed_tools(
        tmp_path,
        mode="external-oauth",
        scopes=("mcp:read", "mcp:preview", "mcp:commit", "mcp:plan"),
    )

    read_scheme = [{"type": "oauth2", "scopes": ["mcp:read"]}]
    assert tools["list_registered_projects"]["securitySchemes"] == read_scheme
    assert tools["get_apps_connector_smoke_packet"]["securitySchemes"] == read_scheme
    assert tools["analyze_project_state"]["securitySchemes"] == read_scheme
    assert tools["analyze_project_state"]["_meta"]["securitySchemes"] == read_scheme

    remote_workflow_scheme = [
        {"type": "oauth2", "scopes": ["mcp:commit", "mcp:plan", "mcp:preview", "mcp:read"]}
    ]
    assert tools["run_mcp_workflow"]["securitySchemes"] == remote_workflow_scheme
    assert tools["manage_git"]["securitySchemes"] == [
        {"type": "oauth2", "scopes": ["mcp:preview", "mcp:read"]}
    ]
    for name in ("list_registered_projects", "get_apps_connector_smoke_packet", "render_commander_app", "analyze_project_state"):
        advertised = tools[name]["securitySchemes"][0]["scopes"]
        assert "mcp:commit" not in advertised
        assert "mcp:plan" not in advertised


def test_oauth_tool_security_schemes_respect_configured_scope_allowlist(tmp_path) -> None:
    tools = _listed_tools(
        tmp_path,
        mode="oauth",
        scopes=("mcp:read",),
    )

    expected = [{"type": "oauth2", "scopes": ["mcp:read"]}]
    assert tools["list_registered_projects"]["securitySchemes"] == expected
    assert tools["run_mcp_workflow"]["securitySchemes"] == expected


def test_builtin_oauth_without_scope_attribute_publishes_policy_scopes(tmp_path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="commander")

    response = server._handle_jsonrpc_request(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        auth_context={
            "mode": "oauth",
            "oauth_provider": SimpleNamespace(),
            "token": {},
        },
    )
    tools = {tool["name"]: tool for tool in response["result"]["tools"]}

    expected = [{"type": "oauth2", "scopes": ["mcp:read"]}]
    assert tools["list_registered_projects"]["securitySchemes"] == expected


def test_non_oauth_tool_list_does_not_claim_oauth_security(tmp_path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="commander")

    tools = server._tool_defs_payload(auth_context={"mode": "token"})

    assert all("securitySchemes" not in tool for tool in tools)
    assert all("securitySchemes" not in tool.get("_meta", {}) for tool in tools)


def test_insufficient_scope_returns_chatgpt_reauthorization_challenge(tmp_path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="commander")
    provider = SimpleNamespace(
        validate_scope=lambda _token, _scope: False,
        protected_resource_metadata_url=lambda: (
            "https://colameta-mcp.example.com/.well-known/oauth-protected-resource"
        ),
    )

    tool_error = server._oauth_scope_error(
        "list_registered_projects",
        {},
        {"mode": "external-oauth", "oauth_provider": provider, "token": {}},
    )

    assert tool_error is not None
    assert tool_error["error_code"] == "INSUFFICIENT_SCOPE"
    assert tool_error["details"]["required_scope"] == "mcp:read"
    challenge = tool_error["_meta"]["mcp/www_authenticate"][0]
    assert 'scope="mcp:read"' in challenge
    assert 'error="insufficient_scope"' in challenge
    shaped = server._as_mcp_call_result(tool_error)
    assert shaped["_meta"] == tool_error["_meta"]


def test_owner_external_oauth_scope_metadata_includes_commit_without_changing_commander() -> None:
    configured = "mcp:read,mcp:preview"

    assert _external_oauth_scopes_for_profile("commander", configured) == configured
    assert _external_oauth_scopes_for_profile(
        MCP_EXPOSURE_PROFILE_OWNER,
        configured,
    ) == ("mcp:read", "mcp:preview", "mcp:commit")


def test_owner_external_oauth_scope_metadata_preserves_defaults_when_unconfigured() -> None:
    for configured in (None, "", " , ", [], (), ["", " "]):
        assert _external_oauth_scopes_for_profile(
            MCP_EXPOSURE_PROFILE_OWNER,
            configured,
        ) == DEFAULT_SCOPES


def test_owner_external_oauth_provider_validates_default_scopes_when_unconfigured() -> None:
    scopes = _external_oauth_scopes_for_profile(MCP_EXPOSURE_PROFILE_OWNER, None)
    assert isinstance(scopes, tuple)
    provider = ExternalOAuthProvider(
        ExternalOAuthConfig(
            public_base_url="https://colameta-mcp.example.com",
            issuer="https://issuer.example.com/",
            jwks_url="https://issuer.example.com/.well-known/jwks.json",
            scopes=scopes,
        )
    )
    token = {"scope": " ".join(DEFAULT_SCOPES)}

    assert provider.scopes == DEFAULT_SCOPES
    assert all(provider.validate_scope(token, scope) for scope in DEFAULT_SCOPES)


def test_owner_external_oauth_http_metadata_publishes_incremental_commit_scope(tmp_path) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = MCPPlanningBridgeServer(
        str(tmp_path),
        exposure_profile=MCP_EXPOSURE_PROFILE_OWNER,
    )
    service_errors: list[BaseException] = []

    def serve() -> None:
        try:
            server.serve_http(
                host="127.0.0.1",
                port=port,
                auth_mode="external-oauth",
                public_base_url="https://colameta-mcp.example.com",
                oauth_issuer="https://issuer.example.com/",
                oauth_jwks_url="https://issuer.example.com/.well-known/jwks.json",
                oauth_scopes="mcp:read,mcp:preview",
            )
        except BaseException as exc:  # pragma: no cover - asserted after join
            service_errors.append(exc)

    thread = threading.Thread(target=serve, name="owner-oauth-metadata", daemon=True)
    thread.start()
    metadata_url = f"http://127.0.0.1:{port}/.well-known/oauth-protected-resource"
    try:
        deadline = time.monotonic() + 5
        while True:
            try:
                with urlopen(metadata_url, timeout=1) as response:
                    metadata = json.loads(response.read())
                break
            except OSError:
                if service_errors or time.monotonic() >= deadline:
                    raise
                time.sleep(0.02)
        assert metadata["scopes_supported"] == [
            "mcp:read",
            "mcp:preview",
            "mcp:commit",
        ]
    finally:
        httpd = getattr(server, "_httpd", None)
        if httpd is not None:
            httpd.shutdown()
        thread.join(timeout=5)
    assert not thread.is_alive()
    assert service_errors == []


def test_workflow_apply_reauthorization_preserves_existing_scopes(tmp_path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="commander")
    provider = SimpleNamespace(
        scopes=("mcp:read", "mcp:preview", "mcp:commit", "mcp:plan"),
        validate_scope=lambda token, scope: scope in str(token.get("scope") or "").split(),
        protected_resource_metadata_url=lambda: (
            "https://colameta-mcp.example.com/.well-known/oauth-protected-resource"
        ),
    )
    params = {"workflow": "small_project_patch", "phase": "apply"}
    old_context = {
        "mode": "external-oauth",
        "oauth_provider": provider,
        "token": {"scope": "openid mcp:read mcp:preview untrusted:scope"},
    }

    tool_error = server._oauth_scope_error("run_mcp_workflow", params, old_context)

    assert tool_error is not None
    assert tool_error["details"]["required_scope"] == "mcp:commit"
    challenge = tool_error["_meta"]["mcp/www_authenticate"][0]
    assert 'scope="mcp:read mcp:preview mcp:commit"' in challenge
    assert "openid" not in challenge
    assert "untrusted:scope" not in challenge

    reconnected_context = {
        **old_context,
        "token": {"scope": "mcp:read mcp:preview mcp:commit"},
    }
    assert server._oauth_scope_error(
        "run_mcp_workflow",
        params,
        reconnected_context,
    ) is None
    assert server._oauth_scope_error(
        "run_mcp_workflow",
        {"workflow": "project_status", "phase": "inspect"},
        reconnected_context,
    ) is None
    assert server._oauth_scope_error(
        "run_mcp_workflow",
        {"workflow": "auto_preview", "phase": "preview"},
        reconnected_context,
    ) is None
