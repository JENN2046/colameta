from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json

from runner.mcp_result_artifacts import MCPResultArtifactStore
from runner.mcp_server import (
    COMMANDER_APP_WIDGET_URI,
    MCP_RESULT_ARTIFACT_RESOURCE_TEMPLATES,
    MCP_RESULT_ARTIFACT_WORKFLOW,
    MCPPlanningBridgeServer,
)


def test_result_artifact_store_pages_exact_json_and_expires() -> None:
    now = datetime(2026, 7, 22, tzinfo=timezone.utc)

    def now_fn() -> datetime:
        return now

    store = MCPResultArtifactStore(
        ttl_seconds=60,
        page_chars=10,
        now_fn=now_fn,
    )
    handle = store.put(tool="example", payload={"message": "你好", "values": list(range(8))})

    assert handle is not None
    pages = [store.read_page(handle.artifact_id, index) for index in range(1, handle.page_count + 1)]
    assert all(page is not None for page in pages)
    content = "".join(page.content for page in pages if page is not None)
    assert json.loads(content) == {"message": "你好", "values": list(range(8))}
    assert hashlib.sha256(content.encode("utf-8")).hexdigest() == handle.content_sha256

    now = now + timedelta(seconds=61)
    assert store.read_page(handle.artifact_id) is None


def test_packaged_mcp_result_exposes_a_paged_resource_continuation(tmp_path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path))
    raw_result = {
        "ok": True,
        "tool": "manage_files",
        "data": {"content": "x" * 30000},
    }
    params = {"action": "read", "file": "CURRENT_STATE.md"}

    shaped = server._shape_mcp_call_result(raw_result, params)
    manifest = shaped["structuredContent"]

    assert manifest["packaged"] is True
    assert manifest["artifact_id"]
    assert manifest["resource_uri"].startswith("colameta://result-artifact/")
    assert manifest["page_count"] > 1
    assert manifest["page_uri_template"].endswith("/pages/{page}")
    assert manifest["recommended_next_reads"][:3] == [
        {
            "kind": "mcp_tool",
            "tool": "read_result_artifact",
            "arguments": {
                "artifact_id": manifest["artifact_id"],
                "artifact_page": 1,
            },
            "reason": "通过 ChatGPT 可调用的 read_result_artifact 读取同一短期 artifact 页；保留 artifact_id、页码、SHA-256 与 expiry 合同。",
        },
        {
            "kind": "mcp_resource",
            "tool": "resources/read",
            "arguments": {"uri": manifest["resource_uri"]},
            "reason": "可选的标准 MCP 资源续读：支持动态 resources/read 的客户端可读取第 1 页，再按 page_uri_template 续读。",
        },
        {
            "kind": "mcp_tool_compatibility",
            "tool": "run_mcp_workflow",
            "arguments": {
                "workflow": MCP_RESULT_ARTIFACT_WORKFLOW,
                "phase": "read",
                "artifact_id": manifest["artifact_id"],
                "artifact_page": 1,
            },
            "reason": "旧客户端兼容：通过 run_mcp_workflow 的 result_artifact read 读取同一短期 artifact 页。",
        },
    ]

    pages: list[str] = []
    for page_number in range(1, manifest["page_count"] + 1):
        uri = manifest["resource_uri"] if page_number == 1 else manifest["page_uri_template"].format(page=page_number)
        response = server._handle_jsonrpc_request(
            {
                "jsonrpc": "2.0",
                "id": page_number,
                "method": "resources/read",
                "params": {"uri": uri},
            }
        )
        assert response is not None
        page_payload = json.loads(response["result"]["contents"][0]["text"])
        assert page_payload["page"] == page_number
        assert page_payload["content_sha256"] == manifest["content_sha256"]
        pages.append(page_payload["content"])

    restored = "".join(pages)
    assert json.loads(restored) == raw_result
    assert hashlib.sha256(restored.encode("utf-8")).hexdigest() == manifest["content_sha256"]


def test_actions_packaging_uses_the_same_recoverable_artifact_contract(tmp_path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path))
    raw_result = {
        "ok": True,
        "tool": "manage_files",
        "data": {"content": "x" * 70000},
    }
    params = {"action": "read", "file": "CURRENT_STATE.md"}

    manifest = server._package_actions_rest_response("manage_files", params, raw_result)

    assert manifest["packaged"] is True
    assert manifest["resource_uri"].startswith("colameta://result-artifact/")
    assert manifest["recommended_next_reads"][0]["tool"] == "read_result_artifact"
    assert manifest["recommended_next_reads"][1]["tool"] == "resources/read"
    assert manifest["recommended_next_reads"][2]["tool"] == "run_mcp_workflow"


def test_result_artifact_templates_are_static_and_artifact_ids_remain_opaque(tmp_path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path))
    shaped = server._shape_mcp_call_result(
        {"ok": True, "tool": "manage_files", "data": {"content": "x" * 30000}},
        {"action": "read", "file": "CURRENT_STATE.md"},
    )
    artifact_id = shaped["structuredContent"]["artifact_id"]

    response = server._handle_jsonrpc_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "resources/templates/list",
            "params": {},
        }
    )

    assert response is not None
    templates = response["result"]["resourceTemplates"]
    artifact_templates = templates[: len(MCP_RESULT_ARTIFACT_RESOURCE_TEMPLATES)]
    assert artifact_templates == [dict(item) for item in MCP_RESULT_ARTIFACT_RESOURCE_TEMPLATES]
    assert [item["uriTemplate"] for item in artifact_templates] == [
        "colameta://result-artifact/{artifact_id}",
        "colameta://result-artifact/{artifact_id}/pages/{page}",
    ]
    assert artifact_id not in json.dumps(templates)


def test_mcp_overflow_reduced_manifest_keeps_resource_and_typed_recoverable_continuations(tmp_path, monkeypatch) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path))
    raw_result = {
        "ok": True,
        "tool": "manage_files",
        "data": {"content": "x" * 30000},
    }

    monkeypatch.setattr(
        server,
        "_mcp_recommended_next_reads",
        lambda *_args: [{"reason": "x" * 100000}],
    )
    shaped = server._shape_mcp_call_result(
        raw_result,
        {"action": "read", "file": "CURRENT_STATE.md"},
    )

    manifest = shaped["structuredContent"]
    assert manifest["packaged"] is True
    assert manifest["package_mode"] == "manifest"
    assert manifest["artifact_id"]
    assert [item["tool"] for item in manifest["recommended_next_reads"]] == [
        "read_result_artifact",
        "resources/read",
    ]

    page_response = server._handle_jsonrpc_request(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "resources/read",
            "params": {"uri": manifest["resource_uri"]},
        }
    )
    assert page_response is not None
    page = json.loads(page_response["result"]["contents"][0]["text"])
    assert page["artifact_id"] == manifest["artifact_id"]
    assert page["content_sha256"] == manifest["content_sha256"]


def test_actions_overflow_reduced_manifest_keeps_resource_and_typed_recoverable_continuations(tmp_path, monkeypatch) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path))
    raw_result = {
        "ok": True,
        "tool": "manage_files",
        "data": {"content": "x" * 70000},
    }

    monkeypatch.setattr(
        server,
        "_actions_recommended_next_reads",
        lambda *_args: [{"reason": "x" * 100000}],
    )
    manifest = server._package_actions_rest_response(
        "manage_files",
        {"action": "read", "file": "CURRENT_STATE.md"},
        raw_result,
    )

    assert manifest["packaged"] is True
    assert manifest["package_mode"] == "manifest"
    assert manifest["artifact_id"]
    assert manifest["resource_uri"].startswith("colameta://result-artifact/")
    assert [item["tool"] for item in manifest["recommended_next_reads"]] == [
        "read_result_artifact",
        "resources/read",
    ]


def test_result_artifact_recovery_manifest_keeps_all_recoverable_continuations(tmp_path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path))
    artifact_fields = server._store_packaged_result_artifact(
        "manage_files",
        {"ok": True, "tool": "manage_files", "data": {"content": "x" * 30000}},
    )

    assert artifact_fields is not None
    manifest = server._result_artifact_recovery_manifest(
        tool_name="manage_files",
        ok=True,
        artifact_fields=artifact_fields,
    )

    assert manifest["packaged"] is True
    assert manifest["package_mode"] == "artifact_continuation"
    assert [item["tool"] for item in manifest["recommended_next_reads"]] == [
        "read_result_artifact",
        "resources/read",
        "run_mcp_workflow",
    ]


def test_result_artifact_compatibility_reads_exact_pages_and_sha_through_commander(tmp_path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="commander")
    payload = {
        "content": (
            "请读取colameta://result-artifact/opaque_handle_123_"
            "/pages/{page}。\n"
            + ("x" * 30000)
        ),
        "label": "paged compatibility fixture",
    }
    handle = server._mcp_result_artifact_store.put(tool="fixture", payload=payload)

    assert handle is not None
    assert handle.page_count > 1
    expected_content = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    pages: list[str] = []
    for page_number in range(1, handle.page_count + 1):
        response = server._handle_jsonrpc_request(
            {
                "jsonrpc": "2.0",
                "id": page_number,
                "method": "tools/call",
                "params": {
                    "name": "run_mcp_workflow",
                    "arguments": {
                        "workflow": MCP_RESULT_ARTIFACT_WORKFLOW,
                        "phase": "read",
                        "artifact_id": handle.artifact_id,
                        "artifact_page": page_number,
                    },
                },
            }
        )

        assert response is not None
        structured = response["result"]["structuredContent"]
        assert structured["ok"] is True
        contract = structured["data"]
        assert contract["schema_version"] == "commander_response.v1"
        assert contract["outcome"] == "completed"
        facts = contract["facts"]
        evidence = contract["evidence"]
        assert facts["workflow"] == MCP_RESULT_ARTIFACT_WORKFLOW
        assert facts["read_only"] is True
        assert facts["side_effects"] is False
        assert evidence["artifact_id"] == handle.artifact_id
        assert evidence["page_count"] == handle.page_count
        assert evidence["content_sha256"] == handle.content_sha256
        assert evidence["expires_at"] == handle.expires_at
        page = facts["artifact_page"]
        assert page["artifact_id"] == handle.artifact_id
        assert page["page"] == page_number
        assert page["content_sha256"] == handle.content_sha256
        assert page["expires_at"] == handle.expires_at
        pages.append(page["content"])
        if page_number < handle.page_count:
            assert contract["next_action"] == {
                "tool": "run_mcp_workflow",
                "arguments": {
                    "workflow": MCP_RESULT_ARTIFACT_WORKFLOW,
                    "phase": "read",
                    "artifact_id": handle.artifact_id,
                    "artifact_page": page_number + 1,
                },
                "reason": "继续读取同一短期 artifact 的下一页；artifact_id、expires_at 与 content_sha256 保持不变。",
            }
        else:
            assert contract["next_action"] is None

    restored = "".join(pages)
    assert restored == expected_content
    assert hashlib.sha256(restored.encode("utf-8")).hexdigest() == handle.content_sha256
    assert json.loads(restored) == payload


def test_commander_rejects_unsafe_artifact_across_tool_and_resource_reads(
    tmp_path,
) -> None:
    server = MCPPlanningBridgeServer(
        str(tmp_path),
        exposure_profile="commander",
    )
    serialized_probe = json.dumps(
        {"content": ""},
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    content_start = serialized_probe.index('""') + 1
    private_path = "/home/reviewer/example.md"
    prefix = "x" * (12_000 - content_start - 2)
    payload = {
        "content": f"{prefix}{private_path}\n",
        "oauth_token": "must-not-cross-the-public-boundary",
    }
    serialized_payload = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    private_path_start = serialized_payload.index(private_path)
    assert private_path_start < 12_000 < private_path_start + len(private_path)
    handle = server._mcp_result_artifact_store.put(
        tool="fixture",
        payload=payload,
    )

    assert handle is not None
    typed = server.call_tool_for_agent(
        "read_result_artifact",
        {"artifact_id": handle.artifact_id, "artifact_page": 1},
    )
    assert typed["ok"] is False
    assert typed["data"]["outcome"] == "blocked"
    assert typed["data"]["error"]["code"] == "EVIDENCE_UNAVAILABLE"
    assert "/home/" not in json.dumps(typed, ensure_ascii=False)
    assert "must-not-cross" not in json.dumps(typed, ensure_ascii=False)

    resource = server._handle_jsonrpc_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "resources/read",
            "params": {
                "uri": f"colameta://result-artifact/{handle.artifact_id}",
            },
        }
    )
    assert resource is not None
    assert resource["error"]["data"]["error_code"] == "evidence_unavailable"
    assert "/home/" not in json.dumps(resource, ensure_ascii=False)
    assert "must-not-cross" not in json.dumps(resource, ensure_ascii=False)


def test_commander_artifact_scan_rejects_unsafe_resource_reference_siblings(
    tmp_path,
) -> None:
    server = MCPPlanningBridgeServer(
        str(tmp_path),
        exposure_profile="commander",
    )
    payload = {
        "recommended_next_reads": [
            {
                "kind": "mcp_resource",
                "tool": "resources/read",
                "arguments": {
                    "uri": "colameta://result-artifact/abcdefghijklmnop",
                },
                "reason": "Read the opaque public evidence.",
                "project_root": "/home/reviewer/private-project",
                "oauth_token": "synthetic-token-must-not-cross",
                "diagnostics": {
                    "stderr": "synthetic diagnostic must not cross",
                },
            }
        ]
    }
    handle = server._mcp_result_artifact_store.put(
        tool="fixture",
        payload=payload,
    )

    assert handle is not None
    typed = server.call_tool_for_agent(
        "read_result_artifact",
        {"artifact_id": handle.artifact_id, "artifact_page": 1},
    )
    assert typed["ok"] is False
    assert typed["data"]["outcome"] == "blocked"
    assert typed["data"]["error"]["code"] == "EVIDENCE_UNAVAILABLE"
    rendered = json.dumps(typed, ensure_ascii=False)
    assert "/home/reviewer" not in rendered
    assert "synthetic-token-must-not-cross" not in rendered
    assert "synthetic diagnostic must not cross" not in rendered

    resource = server._handle_jsonrpc_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "resources/read",
            "params": {
                "uri": f"colameta://result-artifact/{handle.artifact_id}",
            },
        }
    )
    assert resource is not None
    assert resource["error"]["data"]["error_code"] == "evidence_unavailable"
    rendered_resource = json.dumps(resource, ensure_ascii=False)
    assert "/home/reviewer" not in rendered_resource
    assert "synthetic-token-must-not-cross" not in rendered_resource
    assert "synthetic diagnostic must not cross" not in rendered_resource


def test_typed_result_artifact_tool_reads_exact_pages_and_returns_typed_continuation(tmp_path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="commander")
    payload = {"content": "typed result artifact\n" + ("x" * 30000)}
    handle = server._mcp_result_artifact_store.put(tool="fixture", payload=payload)

    assert handle is not None
    assert "read_result_artifact" in server._visible_tool_names()
    assert server.get_required_scope_for_tool(
        "read_result_artifact",
        {"artifact_id": handle.artifact_id},
    ) == "mcp:read"

    pages: list[str] = []
    for page_number in range(1, handle.page_count + 1):
        result = server.call_tool_for_agent(
            "read_result_artifact",
            {"artifact_id": handle.artifact_id, "artifact_page": page_number},
        )
        assert result["ok"] is True
        contract = result["data"]
        facts = contract["facts"]
        evidence = contract["evidence"]
        assert facts["read_only"] is True
        assert facts["side_effects"] is False
        assert evidence["artifact_id"] == handle.artifact_id
        assert evidence["content_sha256"] == handle.content_sha256
        pages.append(facts["artifact_page"]["content"])
        if page_number < handle.page_count:
            assert contract["next_action"] == {
                "tool": "read_result_artifact",
                "arguments": {
                    "artifact_id": handle.artifact_id,
                    "artifact_page": page_number + 1,
                },
                "reason": "继续读取同一短期 artifact 的下一页；artifact_id、expires_at 与 content_sha256 保持不变。",
            }

    restored = "".join(pages)
    assert hashlib.sha256(restored.encode("utf-8")).hexdigest() == handle.content_sha256
    assert json.loads(restored) == payload


def test_typed_result_artifact_tool_requires_only_a_known_opaque_handle(tmp_path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="commander")
    tool = next(tool for tool in server.tool_defs if tool.name == "read_result_artifact")

    assert "phase" not in tool.input_schema["properties"]
    assert tool.input_schema["required"] == ["artifact_id"]

    missing = server.call_tool_for_agent("read_result_artifact", {})
    assert missing["ok"] is False
    assert missing["error_code"] == "RESOURCE_URI_INVALID"

    unknown = server.call_tool_for_agent(
        "read_result_artifact",
        {"artifact_id": "abcdefghijklmnopqrstuvwx", "artifact_page": 1},
    )
    assert unknown["ok"] is False
    assert unknown["error_code"] == "ARTIFACT_EXPIRED"

    invalid_phase = server.call_tool_for_agent(
        "read_result_artifact",
        {"artifact_id": "abcdefghijklmnopqrstuvwx", "phase": "verify"},
    )
    assert invalid_phase["ok"] is False
    assert invalid_phase["error_code"] == "WORKFLOW_NOT_SUPPORTED"


def test_result_artifact_compatibility_is_read_scoped_and_fails_closed(tmp_path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="commander")
    handle = server._mcp_result_artifact_store.put(
        tool="fixture",
        payload={"content": "x" * 30000},
    )

    assert handle is not None
    assert server.get_required_scope_for_tool(
        "run_mcp_workflow",
        {"workflow": MCP_RESULT_ARTIFACT_WORKFLOW, "phase": "read"},
    ) == "mcp:read"

    missing = server.call_tool_for_agent(
        "run_mcp_workflow",
        {"workflow": MCP_RESULT_ARTIFACT_WORKFLOW, "phase": "read"},
    )
    assert missing["ok"] is False
    assert missing["error_code"] == "RESOURCE_URI_INVALID"

    invalid_page = server.call_tool_for_agent(
        "run_mcp_workflow",
        {
            "workflow": MCP_RESULT_ARTIFACT_WORKFLOW,
            "phase": "read",
            "artifact_id": handle.artifact_id,
            "artifact_page": 0,
        },
    )
    assert invalid_page["ok"] is False
    assert invalid_page["error_code"] == "RESOURCE_URI_INVALID"

    missing_or_expired = server.call_tool_for_agent(
        "run_mcp_workflow",
        {
            "workflow": MCP_RESULT_ARTIFACT_WORKFLOW,
            "phase": "read",
            "artifact_id": "abcdefghijklmnopqrstuvwx",
            "artifact_page": 1,
        },
    )
    assert missing_or_expired["ok"] is False
    assert missing_or_expired["error_code"] == "ARTIFACT_EXPIRED"

    invalid_phase = server.call_tool_for_agent(
        "run_mcp_workflow",
        {
            "workflow": MCP_RESULT_ARTIFACT_WORKFLOW,
            "phase": "verify",
            "artifact_id": handle.artifact_id,
        },
    )
    assert invalid_phase["ok"] is False
    assert invalid_phase["error_code"] == "SCOPE_VIOLATION"


def test_result_artifact_compatibility_and_typed_read_allow_external_oauth_without_project_name(tmp_path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="commander")
    handle = server._mcp_result_artifact_store.put(
        tool="fixture",
        payload={"content": "x" * 30000},
    )

    assert handle is not None

    class _ScopeProvider:
        @staticmethod
        def validate_scope(token_payload: dict, scope: str) -> bool:
            return scope in str(token_payload.get("scope") or "").split()

    authorized = server.call_tool_for_agent(
        "run_mcp_workflow",
        {
            "workflow": MCP_RESULT_ARTIFACT_WORKFLOW,
            "phase": "read",
            "artifact_id": handle.artifact_id,
            "artifact_page": 1,
        },
        auth_context={
            "mode": "external-oauth",
            "oauth_provider": _ScopeProvider(),
            "token": {"scope": "mcp:read"},
        },
    )
    assert authorized["ok"] is True
    assert (
        authorized["data"]["facts"]["artifact_page"]["artifact_id"]
        == handle.artifact_id
    )

    typed_authorized = server.call_tool_for_agent(
        "read_result_artifact",
        {
            "artifact_id": handle.artifact_id,
            "artifact_page": 1,
        },
        auth_context={
            "mode": "external-oauth",
            "oauth_provider": _ScopeProvider(),
            "token": {"scope": "mcp:read"},
        },
    )
    assert typed_authorized["ok"] is True
    assert (
        typed_authorized["data"]["facts"]["artifact_page"]["artifact_id"]
        == handle.artifact_id
    )

    denied = server.call_tool_for_agent(
        "run_mcp_workflow",
        {
            "workflow": MCP_RESULT_ARTIFACT_WORKFLOW,
            "phase": "read",
            "artifact_id": handle.artifact_id,
            "artifact_page": 1,
        },
        auth_context={
            "mode": "external-oauth",
            "oauth_provider": _ScopeProvider(),
            "token": {"scope": "mcp:preview"},
        },
    )
    assert denied["ok"] is False
    assert denied["error_code"] == "SCOPE_VIOLATION"

    typed_denied = server.call_tool_for_agent(
        "read_result_artifact",
        {
            "artifact_id": handle.artifact_id,
            "artifact_page": 1,
        },
        auth_context={
            "mode": "external-oauth",
            "oauth_provider": _ScopeProvider(),
            "token": {"scope": "mcp:preview"},
        },
    )
    assert typed_denied["ok"] is False
    assert typed_denied["error_code"] == "SCOPE_VIOLATION"


def test_unavailable_artifact_store_never_returns_a_hollow_packaged_manifest(tmp_path, monkeypatch) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path))
    monkeypatch.setattr(server, "_store_packaged_result_artifact", lambda *_args: None)

    shaped = server._shape_mcp_call_result(
        {"ok": True, "tool": "manage_files", "data": {"content": "x" * 30000}},
        {"action": "read", "file": "CURRENT_STATE.md"},
    )

    result = shaped["structuredContent"]
    assert result["ok"] is False
    assert result["packaged"] is False
    assert result["error_code"] == "MCP_RESULT_ARTIFACT_UNAVAILABLE"
    assert "artifact_id" not in result


def test_result_artifacts_are_not_discoverable_and_require_read_scope_when_authenticated(tmp_path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path))
    shaped = server._shape_mcp_call_result(
        {"ok": True, "tool": "manage_files", "data": {"content": "x" * 30000}},
        {"action": "read", "file": "CURRENT_STATE.md"},
    )
    artifact_uri = shaped["structuredContent"]["resource_uri"]

    listed = server._handle_jsonrpc_request(
        {"jsonrpc": "2.0", "id": 1, "method": "resources/list", "params": {}}
    )
    assert listed is not None
    assert [resource["uri"] for resource in listed["result"]["resources"]] == [COMMANDER_APP_WIDGET_URI]

    class _ScopeProvider:
        @staticmethod
        def validate_scope(token_payload: dict, scope: str) -> bool:
            return scope in str(token_payload.get("scope") or "").split()

    denied = server._handle_jsonrpc_request(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "resources/read",
            "params": {"uri": artifact_uri},
        },
        auth_context={
            "mode": "external-oauth",
            "oauth_provider": _ScopeProvider(),
            "token": {"scope": "mcp:preview"},
        },
    )
    assert denied is not None
    assert denied["error"]["data"]["error_code"] == "resource_access_denied"

    relay_denied = server._handle_jsonrpc_request(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "resources/read",
            "params": {"uri": artifact_uri},
        },
        auth_context={"mode": "cloud-relay", "scopes": ["mcp:preview"]},
    )
    assert relay_denied is not None
    assert relay_denied["error"]["data"]["error_code"] == "resource_access_denied"

    missing = server._handle_jsonrpc_request(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "resources/read",
            "params": {"uri": "colameta://result-artifact/abcdefghijklmnop"},
        },
    )
    assert missing is not None
    assert missing["error"]["data"]["error_code"] == "result_artifact_not_found_or_expired"
