from __future__ import annotations

from types import SimpleNamespace

from runner.mcp_server import MCPPlanningBridgeServer


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
        {"type": "oauth2", "scopes": ["mcp:preview", "mcp:read"]}
    ]
    assert tools["run_mcp_workflow"]["securitySchemes"] == remote_workflow_scheme
    assert tools["manage_git"]["securitySchemes"] == remote_workflow_scheme
    for tool in tools.values():
        advertised = tool["securitySchemes"][0]["scopes"]
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
