from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json

from runner.mcp_result_artifacts import MCPResultArtifactStore
from runner.mcp_server import (
    COMMANDER_APP_WIDGET_URI,
    MCP_RESULT_ARTIFACT_RESOURCE_TEMPLATES,
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
    assert manifest["recommended_next_reads"][0] == {
        "kind": "mcp_resource",
        "tool": "resources/read",
        "arguments": {"uri": manifest["resource_uri"]},
        "reason": "结果已保存为短期分页 artifact；先读取第 1 页，再按 page_uri_template 续读。",
    }

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
    assert manifest["recommended_next_reads"][0]["tool"] == "resources/read"


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


def test_mcp_overflow_fallback_keeps_the_recoverable_artifact_handle(tmp_path, monkeypatch) -> None:
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
    assert manifest["package_mode"] == "artifact_continuation"
    assert manifest["artifact_id"]
    assert manifest["recommended_next_reads"] == [
        {
            "kind": "mcp_resource",
            "tool": "resources/read",
            "arguments": {"uri": manifest["resource_uri"]},
            "reason": "结果已保存为短期分页 artifact；先读取第 1 页，再按 page_uri_template 续读。",
        }
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


def test_actions_overflow_fallback_keeps_the_recoverable_artifact_handle(tmp_path, monkeypatch) -> None:
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
    assert manifest["package_mode"] == "artifact_continuation"
    assert manifest["artifact_id"]
    assert manifest["resource_uri"].startswith("colameta://result-artifact/")


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
