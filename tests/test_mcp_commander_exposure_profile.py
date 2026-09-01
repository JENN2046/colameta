from __future__ import annotations

import json

from runner.mcp_server import (
    COMMANDER_EXPOSED_TOOLS,
    COMMANDER_PUBLIC_RESPONSE_MINIMIZATION_VERSION,
    MCP_EXPOSURE_PROFILE_OWNER,
    NORMAL_EXPOSED_TOOLS,
    MCPPlanningBridgeServer,
)
from runner.mcp_private_operator import OperatorSettingsStore
from runner.mcp_commander_public import (
    COMMANDER_CLIENT_EXPERIENCE_CONTRACT_VERSION,
    COMMANDER_LOCAL_CODEX_ADVANCED_TOOL_EXAMPLES,
)

GIT_HEAD = "c" * 40
PLAN_SHA256 = "b" * 64
MANIFEST_SHA256 = "d" * 64


def _base_context_binding() -> dict[str, object]:
    return {
        "project_name": "colameta-self-dev",
        "branch": "codex/nuobao-commander-contract-v1",
        "head": GIT_HEAD,
        "runner_plan": {
            "mode": "managed",
            "plan_sha256": PLAN_SHA256,
        },
        "current_version": "N1",
    }


def _operation_context_binding() -> dict[str, object]:
    return {
        **_base_context_binding(),
        "review_unit": "commander-contract-preview",
        "workflow_intent": "continue-bound-operation",
    }


def _nested_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        keys = set(value)
        for nested in value.values():
            keys.update(_nested_keys(nested))
        return keys
    if isinstance(value, list):
        keys = set()
        for nested in value:
            keys.update(_nested_keys(nested))
        return keys
    return set()


def test_commander_profile_exposes_nine_high_level_tools_with_typed_review_reads(tmp_path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="commander")

    assert tuple(server._visible_tool_names()) == COMMANDER_EXPOSED_TOOLS
    assert len(server._visible_tool_names()) == 9
    assert "list_registered_projects" in server._visible_tool_names()
    assert "get_apps_connector_smoke_packet" in server._visible_tool_names()
    assert "review_manifest" in server._visible_tool_names()
    assert "read_result_artifact" in server._visible_tool_names()
    assert all(
        tool.output_schema and tool.annotations
        for tool in server._filter_tools_by_exposure_profile(server.tool_defs)
    )


def test_commander_profile_allows_cached_read_only_smoke_tool(tmp_path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="commander")

    result = server._call_tool("get_apps_connector_smoke_packet", {})

    assert result["ok"] is True
    assert server.get_required_scope_for_tool("get_apps_connector_smoke_packet", {}) == "mcp:read"


def test_commander_preserves_only_valid_opaque_resource_read_continuations(tmp_path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="commander")
    valid_uri = "colameta://result-artifact/abcdefghijklmnop_"

    projected = server._commander_public_sanitize(
        {
            "recommended_next_reads": [
                {
                    "kind": "mcp_resource",
                    "tool": "resources/read",
                    "arguments": {"uri": valid_uri},
                    "reason": (
                        f"Read {valid_uri}; "
                        "compare /home/example/src/private-project; "
                        "oauth_token=synthetic-reason-secret"
                    ),
                    "project_root": "/home/example/src/private-project",
                    "oauth_token": "synthetic-token-must-not-leak",
                    "diagnostics": {
                        "stderr": "synthetic diagnostic must not leak",
                    },
                },
                {
                    "kind": "mcp_resource",
                    "tool": "resources/read",
                    "arguments": {"uri": "file:///private/path"},
                },
                {
                    "kind": "mcp_tool",
                    "tool": "manage_files",
                    "arguments": {"action": "read", "path": "README.md"},
                },
            ]
        },
        compact=False,
    )

    assert projected == {
        "recommended_next_reads": [
            {
                "kind": "mcp_resource",
                "tool": "resources/read",
                "arguments": {"uri": valid_uri},
                "reason": "<sensitive>",
            }
        ]
    }


def test_commander_profile_denies_hidden_tools_even_if_client_cached_them(tmp_path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="commander")

    result = server._call_tool("manage_files", {"action": "read", "path": "README.md"})

    assert result["ok"] is False
    assert result["error_code"] == "TOOL_NOT_EXPOSED"

    shaped = server._as_mcp_call_result(result, {"action": "read", "path": "README.md"})
    assert shaped["structuredContent"]["tool"] == "<internal-tool>"
    assert shaped["structuredContent"]["error_code"] == "TOOL_NOT_EXPOSED"
    assert "manage_files" not in json.dumps(
        shaped["structuredContent"],
        ensure_ascii=False,
    )


def test_normal_profile_preserves_complete_advanced_catalog(tmp_path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="normal")

    assert set(server._visible_tool_names()) == set(NORMAL_EXPOSED_TOOLS)
    assert len(server._visible_tool_names()) == 85
    assert "manage_files" in server._visible_tool_names()
    assert "manage_p1_release_evidence" in server._visible_tool_names()
    assert "manage_p1_release_evidence" not in COMMANDER_EXPOSED_TOOLS


def test_agent_contract_makes_chatgpt_and_local_codex_surfaces_explicit(tmp_path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="normal")

    result = server.call_tool_for_agent("get_agent_consumer_contract", {})

    assert result["ok"] is True
    partition = result["data"]["client_experience_partition"]
    assert partition["schema_version"] == COMMANDER_CLIENT_EXPERIENCE_CONTRACT_VERSION
    chatgpt = partition["chatgpt_commander"]
    assert chatgpt["visible_tool_count"] == 9
    assert tuple(chatgpt["visible_tools"]) == COMMANDER_EXPOSED_TOOLS
    assert chatgpt["resources_read"]["required"] is False
    local_codex = partition["local_codex_loopback"]
    assert tuple(local_codex["advanced_tool_examples"]) == COMMANDER_LOCAL_CODEX_ADVANCED_TOOL_EXAMPLES
    assert set(COMMANDER_LOCAL_CODEX_ADVANCED_TOOL_EXAMPLES) <= set(server._visible_tool_names())
    assert not (set(COMMANDER_LOCAL_CODEX_ADVANCED_TOOL_EXAMPLES) & set(COMMANDER_EXPOSED_TOOLS))


def test_commander_profile_can_be_selected_from_environment(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("MCP_EXPOSURE_PROFILE", "commander")

    server = MCPPlanningBridgeServer(str(tmp_path))

    assert server.mcp_exposure_profile == "commander"


class _OwnerOAuthProvider:
    issuer = "https://issuer.example/"
    audience = "https://mcp.example/mcp"
    resource = "https://mcp.example/mcp"
    scopes = ("mcp:read", "mcp:preview", "mcp:plan", "mcp:commit")

    @staticmethod
    def validate_scope(token: dict[str, object], scope: str) -> bool:
        raw = token.get("scope")
        return isinstance(raw, str) and scope in raw.split()


def _owner_auth(
    *,
    subject: str = "auth0|jenn",
    client: str = "https://chatgpt.example/owner",
    scopes: str = "mcp:read mcp:preview mcp:plan mcp:commit",
) -> dict[str, object]:
    return {
        "mode": "external-oauth",
        "oauth_provider": _OwnerOAuthProvider(),
        "token": {
            "iss": "https://issuer.example/",
            "aud": "https://mcp.example/mcp",
            "sub": subject,
            "azp": client,
            "client_id": client,
            "scope": scopes,
        },
    }


def _install_owner_settings(monkeypatch, tmp_path) -> OperatorSettingsStore:
    store = OperatorSettingsStore(str(tmp_path / "owner-config"))
    assert store.enable(
        "auth0|jenn",
        "https://chatgpt.example/owner",
    )["ok"] is True
    monkeypatch.setattr(
        "runner.mcp_server.OperatorSettingsStore",
        lambda: store,
    )
    return store


def test_owner_profile_exposes_full_advanced_catalog_only_to_exact_owner(
    monkeypatch,
    tmp_path,
) -> None:
    _install_owner_settings(monkeypatch, tmp_path)
    server = MCPPlanningBridgeServer(
        str(tmp_path),
        exposure_profile=MCP_EXPOSURE_PROFILE_OWNER,
    )

    non_owner_tools = server._tool_defs_payload(
        auth_context=_owner_auth(subject="auth0|other")
    )
    tools = server._tool_defs_payload(auth_context=_owner_auth())
    names = {item["name"] for item in tools}

    assert {item["name"] for item in non_owner_tools} == set(server.tools)
    assert names == set(server.tools)
    assert len(names) == 123
    assert "manage_executor_workflow" in names
    assert "manage_stable_promotion_evidence" in names
    assert "manage_git" in names
    assert "run_mcp_workflow" in names
    assert "manage_runner_record" in names
    assert "get_runner_workbench_context" in names


def test_owner_profile_allows_bound_advanced_write_but_preserves_scope_gate(
    monkeypatch,
    tmp_path,
) -> None:
    _install_owner_settings(monkeypatch, tmp_path)
    server = MCPPlanningBridgeServer(
        str(tmp_path),
        exposure_profile=MCP_EXPOSURE_PROFILE_OWNER,
    )
    calls: list[dict[str, object]] = []
    server.tools["manage_executor_workflow"] = lambda params: (
        calls.append(dict(params))
        or {"ok": True, "run_id": "run_owner_123"}
    )
    params = {
        "action": "run_once",
        "project_name": "owner-project",
        "preview_id": "preview_owner_123",
    }

    denied = server._call_tool(
        "manage_executor_workflow",
        params,
        auth_context=_owner_auth(scopes="mcp:read mcp:preview"),
    )
    assert denied["ok"] is False
    assert denied["error_code"] == "INSUFFICIENT_SCOPE"
    assert calls == []

    allowed = server._call_tool(
        "manage_executor_workflow",
        params,
        auth_context=_owner_auth(),
    )
    assert allowed["ok"] is True
    assert allowed["data"]["run_id"] == "run_owner_123"
    assert len(calls) == 1


def test_owner_profile_denies_non_owner_before_dispatch_and_keeps_output_public_safe(
    monkeypatch,
    tmp_path,
) -> None:
    _install_owner_settings(monkeypatch, tmp_path)
    server = MCPPlanningBridgeServer(
        str(tmp_path),
        exposure_profile=MCP_EXPOSURE_PROFILE_OWNER,
    )
    calls = 0

    def handler(_params):
        nonlocal calls
        calls += 1
        return {
            "ok": True,
            "project_root": "/home/example/private/project",
            "access_token": "synthetic-secret-must-not-leak",
            "run_id": "run_owner_safe",
        }

    server.tools["manage_executor_workflow"] = handler
    params = {
        "action": "status",
        "project_name": "owner-project",
        "run_id": "run_owner_safe",
    }

    denied = server._call_tool(
        "manage_executor_workflow",
        params,
        auth_context=_owner_auth(subject="auth0|other"),
    )
    assert denied["ok"] is False
    assert denied["error_code"] == "OWNER_PRINCIPAL_REQUIRED"
    assert calls == 0

    allowed = server._call_tool(
        "manage_executor_workflow",
        params,
        auth_context=_owner_auth(),
    )
    serialized = json.dumps(allowed, ensure_ascii=False)
    assert allowed["ok"] is True
    assert allowed["data"]["run_id"] == "run_owner_safe"
    assert "/home/example/private/project" not in serialized
    assert "synthetic-secret-must-not-leak" not in serialized
    assert calls == 1


def test_owner_profile_does_not_change_commander_hidden_tool_boundary(
    monkeypatch,
    tmp_path,
) -> None:
    _install_owner_settings(monkeypatch, tmp_path)
    server = MCPPlanningBridgeServer(
        str(tmp_path),
        exposure_profile="commander",
    )

    result = server._call_tool(
        "manage_executor_workflow",
        {
            "action": "status",
            "project_name": "owner-project",
            "run_id": "run_owner_safe",
        },
        auth_context=_owner_auth(),
    )

    assert result["ok"] is False
    assert result["error_code"] == "TOOL_NOT_EXPOSED"


def test_owner_profile_keeps_gate_review_work_item_authority_and_resource_gate(
    monkeypatch,
    tmp_path,
) -> None:
    _install_owner_settings(monkeypatch, tmp_path)
    server = MCPPlanningBridgeServer(
        str(tmp_path),
        exposure_profile=MCP_EXPOSURE_PROFILE_OWNER,
    )

    gate_error = server._external_oauth_remote_policy_error(
        "run_mcp_workflow",
        {
            "workflow": "gate_review_request",
            "phase": "apply",
            "project_name": "owner-project",
        },
        _owner_auth(),
    )
    assert gate_error is not None
    assert gate_error["error_code"] == "WORK_ITEM_PRIVATE_PRINCIPAL_REQUIRED"

    denied_resources = server._handle_jsonrpc_request(
        {"jsonrpc": "2.0", "id": 1, "method": "resources/list"},
        auth_context=_owner_auth(subject="auth0|other"),
    )
    assert denied_resources is not None
    assert denied_resources["error"]["data"]["error_code"] == "owner_principal_required"


def test_owner_profile_can_be_selected_from_environment(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("MCP_EXPOSURE_PROFILE", MCP_EXPOSURE_PROFILE_OWNER)

    server = MCPPlanningBridgeServer(str(tmp_path))

    assert server.mcp_exposure_profile == MCP_EXPOSURE_PROFILE_OWNER


def test_commander_public_project_list_returns_only_selection_fields(tmp_path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="commander")
    server.tools["list_registered_projects"] = lambda _: {
        "ok": True,
        "registry_path": "/home/example/.config/colameta/projects.json",
        "project_count": 1,
        "projects": [
            {
                "project_id": "prj_internal",
                "project_name": "colameta-self-dev",
                "display_name": "ColaMeta",
                "project_root": "/home/example/src/colameta-dev",
                "project_mode": "managed",
                "available": True,
                "runner_managed": True,
                "updated_at": "2026-07-19T00:00:00Z",
                "last_selected_at": "2026-07-19T00:00:00Z",
            }
        ],
    }

    result = server._call_tool("list_registered_projects", {})

    assert COMMANDER_PUBLIC_RESPONSE_MINIMIZATION_VERSION == "commander_public_minimal.v1"
    contract = result["data"]
    assert contract["schema_version"] == "commander_response.v1"
    assert contract["outcome"] == "completed"
    assert contract["journey_stage"] == "connect"
    assert contract["context_binding"] is None
    assert contract["facts"] == {
        "project_count": 1,
        "projects": [
            {
                "project_name": "colameta-self-dev",
                "display_name": "ColaMeta",
                "project_mode": "managed",
                "available": True,
                "runner_managed": True,
            }
        ],
    }


def test_commander_public_compact_tools_omit_local_diagnostics_and_hidden_actions(tmp_path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="commander")
    forbidden_keys = {
        "project_id",
        "project_root",
        "project_identity",
        "pid",
        "updated_at",
        "last_observed_at",
        "recent_commits",
        "project_checkout_head",
        "loaded_runtime_head",
        "evidence_path",
        "ignored_files",
    }
    fixture = {
        "ok": True,
        "project_id": "prj_internal",
        "project_root": "/home/example/src/project",
        "project_identity": {"project_root": "/home/example/src/project"},
        "pid": 321,
        "updated_at": "2026-07-19T00:00:00Z",
        "last_observed_at": "2026-07-19T00:00:00Z",
        "recent_commits": [{"commit": "abc123", "subject": "internal subject"}],
        "project_checkout_head": "abc123",
        "loaded_runtime_head": "abc123",
        "evidence_path": "/home/example/src/project/.colameta/evidence.json",
        "ignored_files": [".colameta/runtime/private.json"],
        "safe_action": {"tool": "manage_git", "arguments": {"action": "status"}},
        "hidden_action": {"tool": "manage_files", "arguments": {"action": "read"}},
        "context_binding": _base_context_binding(),
    }

    for tool_name in (
        "get_apps_connector_smoke_packet",
        "render_commander_app",
        "analyze_project_state",
    ):
        projected = server._commander_public_project_tool_result(
            {"ok": True, "tool": tool_name, "data": fixture},
            {"project_name": "colameta-self-dev"},
        )
        assert not (_nested_keys(projected) & forbidden_keys)
        contract = projected["data"]
        assert contract["schema_version"] == "commander_response.v1"
        assert contract["outcome"] == "completed"
        assert contract["facts"]["safe_action"]["tool"] == "manage_git"
        assert "hidden_action" not in contract["facts"]


def test_commander_public_projection_preserves_cc_s01_contract_facts(tmp_path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="commander")
    canonical = {
        "ok": True,
        "schema_version": "executor_continuation_decision.v1",
        "classification": "active_operation_head_mismatch",
        "resume_allowed": False,
        "start_new_allowed": False,
        "recommended_action": "human_review",
        "reason": "operation_running",
        "severity": "blocked",
        "decision_source": "runner.executor_session.build_canonical_continuation_decision",
        "head_mismatch_classification": {
            "status": "active_operation_head_mismatch",
            "session_head": "a" * 40,
            "current_head": "b" * 40,
            "evidence": {
                "head_mismatch": True,
                "session_id": "private-session-id",
                "raw_logs": "private-raw-log",
            },
        },
        "hard_blockers": ["inspect /etc/colameta/private-state.json"],
        "project_root": "/home/example/src/private-project",
        "manifest_file": "/home/example/src/private-project/.colameta/session.json",
    }
    provenance = {
        "schema_version": "evidence_provenance.v1",
        "provenance_status": "verified",
        "legacy_read_parse_only": False,
        "eligible_for_acceptance": True,
        "entries": [
            {
                "subject_path": "$.master_taskbook_hash",
                "evidence_kind": "observed",
                "evidence_subject": "hash_binding",
                "subject_requires_execution": False,
                "subject_operation_completed": True,
                "execution_performed": False,
                "eligible_for_acceptance": True,
                "binding_status": "verified",
                "session_id": "private-session-id",
                "raw_logs": "private-raw-log",
                "binding": {
                    "record_id": "private-record-id",
                    "record_schema_version": "review_feedback.v1",
                    "subject_path": "$.master_taskbook_hash",
                    "content_sha256": "f" * 64,
                    "raw_logs": "private-raw-log",
                },
            }
        ],
        "authority_boundary": {
            "eligible_means_accepted": False,
            "creates_review_decision": False,
            "emits_gate_event": False,
            "writes_delivery_state": False,
        },
    }

    projected = server._commander_public_project_tool_result(
        {
            "ok": True,
            "tool": "analyze_project_state",
            "data": {
                "executor": {"canonical_continuation_decision": canonical},
                "evidence_provenance": provenance,
                "authority_boundary": {"does_not_authorize_executor_run": True},
                "context_binding": _base_context_binding(),
            },
        },
        {"project_name": "colameta-self-dev"},
    )

    contract = projected["data"]
    assert contract["outcome"] == "completed"
    assert contract["context_binding"] == _base_context_binding()
    public_decision = contract["facts"]["executor"]["canonical_continuation_decision"]
    assert public_decision["recommended_action"] == "human_review"
    assert public_decision["resume_allowed"] is False
    assert public_decision["start_new_allowed"] is False
    assert "project_root" not in public_decision
    assert "manifest_file" not in public_decision
    assert public_decision["hard_blockers"] == ["inspect <local-path>"]
    public_classification = public_decision["head_mismatch_classification"]
    assert "session_head" not in public_classification
    assert "current_head" not in public_classification
    assert "session_id" not in public_classification["evidence"]
    assert "raw_logs" not in public_classification["evidence"]
    public_provenance = contract["facts"]["evidence_provenance"]
    assert public_provenance["entries"][0]["subject_path"] == "$.master_taskbook_hash"
    assert public_provenance["entries"][0]["execution_performed"] is False
    assert "session_id" not in public_provenance["entries"][0]
    assert "raw_logs" not in public_provenance["entries"][0]
    assert "record_id" not in public_provenance["entries"][0]["binding"]
    assert public_provenance["authority_boundary"]["eligible_means_accepted"] is False
    assert contract["facts"]["authority_boundary"]["does_not_authorize_executor_run"] is True


def test_commander_public_smoke_replaces_runtime_heads_with_alignment_fact(tmp_path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="commander")
    projected = server._commander_public_project_tool_result(
        {
            "ok": True,
            "tool": "get_apps_connector_smoke_packet",
            "data": {
                "ok": True,
                "runtime": {
                    "project_checkout_head": "abc123",
                    "loaded_runtime_head": "abc123",
                    "runtime_loaded_code_stale": False,
                    "reload_needed_for_verification": False,
                    "reload_awareness_reason": "installed_package_matches_project_checkout",
                },
            },
        },
        {"project_name": "colameta-self-dev"},
    )

    assert projected["data"]["facts"]["runtime"] == {
        "runtime_aligned": True,
        "runtime_loaded_code_stale": False,
        "reload_needed_for_verification": False,
        "reload_awareness_reason": "installed_package_matches_project_checkout",
    }


def test_commander_public_operational_tools_keep_required_continuation_fields(tmp_path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="commander")
    workflow = server._commander_public_project_tool_result(
        {
            "ok": True,
            "tool": "run_mcp_workflow",
            "data": {
                "ok": True,
                "context_binding": _base_context_binding(),
                "changed_files": ["runner/mcp_server.py"],
                "message": "Prepared from /home/example/src/project without applying changes.",
                "next_action": {
                    "tool": "manage_validation_run",
                    "arguments": {"action": "inspect"},
                },
                "hidden_action": {"tool": "manage_files", "arguments": {"action": "read"}},
                "workflow_id": "internal_record_id",
                "updated_at": "2026-07-19T00:00:00Z",
                "project_root": "/home/example/src/project",
            },
        },
        {"workflow": "docs_update", "project_name": "colameta-self-dev"},
    )
    workflow_contract = workflow["data"]
    assert workflow_contract["outcome"] == "completed"
    assert workflow_contract["facts"]["changed_files"] == ["runner/mcp_server.py"]
    assert workflow_contract["next_action"]["tool"] == "manage_validation_run"
    assert "hidden_action" not in workflow_contract["facts"]

    validation = server._commander_public_project_tool_result(
        {
            "ok": True,
            "tool": "manage_validation_run",
            "data": {
                "ok": True,
                "status": "running",
                "run_id": "validation_required_for_status",
                "context_binding": _base_context_binding(),
            },
        },
        {"action": "status", "project_name": "colameta-self-dev"},
    )
    validation_contract = validation["data"]
    assert validation_contract["outcome"] == "in_progress"
    assert validation_contract["next_action"] == {
        "tool": "manage_validation_run",
        "arguments": {
            "action": "status",
            "run_id": "validation_required_for_status",
            "project_name": "colameta-self-dev",
        },
        "reason": "查询当前验证运行状态。",
    }
    assert "run_id" not in validation_contract["facts"]

    git_preview = server._commander_public_project_tool_result(
        {
            "ok": True,
            "tool": "manage_git",
            "data": {
                "ok": True,
                "requires_confirmation": True,
                "preview_id": "preview_required_for_followup",
                "context_binding": _operation_context_binding(),
                "changed_files": ["runner/mcp_server.py"],
            },
        },
        {
            "action": "commit_preview",
            "project_name": "colameta-self-dev",
        },
    )
    git_contract = git_preview["data"]
    assert git_contract["outcome"] == "confirmation_required"
    assert git_contract["confirmation"]["preview_id"] == "preview_required_for_followup"
    assert git_contract["next_action"]["tool"] == "manage_git"
    assert git_contract["next_action"]["arguments"]["action"] == "commit_apply"
    assert git_contract["facts"]["changed_files"] == ["runner/mcp_server.py"]
    assert not (
        _nested_keys(workflow_contract)
        & {"workflow_id", "updated_at", "project_root", "hidden_action"}
    )


def test_commander_public_review_manifest_preserves_expiry_contract(tmp_path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="commander")
    expiry = "2026-07-24T02:54:41.298082+00:00"
    manifest_id = "manifest_contract_fixture"

    def manifest_result(phase: str) -> dict[str, object]:
        return {
            "ok": True,
            "workflow": "review_manifest",
            "phase": phase,
            "review_manifest_id": manifest_id,
            "manifest_resource_uri": f"colameta://review-manifest/{manifest_id}",
            "manifest_sha256": MANIFEST_SHA256,
            "expires_at": expiry,
            "context_binding": _operation_context_binding(),
        }

    inspected = server._commander_public_project_tool_result(
        {
            "ok": True,
            "tool": "review_manifest",
            "data": manifest_result("inspect"),
        },
        {"phase": "inspect"},
    )
    assert inspected["data"]["evidence"]["expires_at"] == expiry

    verified = server._commander_public_project_tool_result(
        {
            "ok": True,
            "tool": "review_manifest",
            "data": manifest_result("verify"),
        },
        {"phase": "verify"},
    )
    assert verified["data"]["evidence"]["expires_at"] == expiry

    read_data = manifest_result("read")
    read_data["subject_page"] = {
        "review_manifest_id": manifest_id,
        "review_unit": "commander-contract-preview",
        "subject_index": 1,
        "path": "runner/mcp_commander_public.py",
        "sha256": "e" * 64,
        "page": 1,
        "page_count": 1,
        "page_char_start": 0,
        "page_char_end": 12,
        "expires_at": expiry,
        "content": "bounded text",
    }
    read = server._commander_public_project_tool_result(
        {
            "ok": True,
            "tool": "review_manifest",
            "data": read_data,
        },
        {"phase": "read"},
    )

    assert read["data"]["evidence"]["expires_at"] == expiry
    assert read["data"]["facts"]["subject_page"]["expires_at"] == expiry
    assert read["data"]["facts"]["subject_page"]["content"] == "bounded text"

    mcp_read = server._as_mcp_call_result(read, {"phase": "read"})
    mcp_data = mcp_read["structuredContent"]["data"]
    assert mcp_data["evidence"]["expires_at"] == expiry
    assert mcp_data["facts"]["subject_page"]["expires_at"] == expiry


def test_commander_public_path_redaction_covers_all_absolute_local_roots(
    tmp_path,
) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="commander")
    message = (
        "failed at /etc/colameta/config.json, /root/private.txt, "
        "/run/colameta/service.sock, /proc/123/status, and D:\\private\\operator.json; "
        "docs https://example.com/etc/config and relative runner/mcp_server.py"
    )

    projected = server._commander_public_project_tool_result(
        {
            "ok": False,
            "tool": "manage_git",
            "data": {
                "ok": False,
                "error_code": "WORKTREE_DIRTY",
                "message": message,
            },
        },
        {"project_name": "colameta-self-dev"},
    )

    assert projected["data"]["outcome"] == "blocked"
    public_message = projected["data"]["error"]["message"]
    assert public_message.count("<local-path>") == 5
    for private_path in (
        "/etc/colameta/config.json",
        "/root/private.txt",
        "/run/colameta/service.sock",
        "/proc/123/status",
        "D:\\private\\operator.json",
    ):
        assert private_path not in public_message
    assert "https://example.com/etc/config" in public_message
    assert "runner/mcp_server.py" in public_message


def test_commander_legacy_agent_error_omits_internal_details(tmp_path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="commander")

    def fail_with_private_diagnostics(_: dict[str, object]) -> dict[str, object]:
        raise RuntimeError(
            r"provider failed at file:///etc/colameta/private.json and "
            r"\\operator-host\private-share\diagnostic.json"
        )

    server.tools["manage_git"] = fail_with_private_diagnostics

    result = server.call_tool_for_agent("manage_git", {"action": "status"})

    assert result["ok"] is False
    assert result["tool"] == "manage_git"
    assert result["error_code"] == "INTERNAL_ERROR"
    assert result["message"] == "工具执行失败，内部诊断未公开。"
    assert result["data"]["schema_version"] == "commander_response.v1"
    assert result["data"]["outcome"] == "failed"
    assert result["data"]["error"]["code"] == "INTERNAL_ERROR"


def test_normal_legacy_agent_error_keeps_existing_diagnostics(tmp_path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="normal")
    diagnostic = "normal-profile diagnostic"

    def fail_with_diagnostics(_: dict[str, object]) -> dict[str, object]:
        raise RuntimeError(diagnostic)

    server.tools["manage_git"] = fail_with_diagnostics

    result = server.call_tool_for_agent("manage_git", {"action": "status"})

    assert result["details"] == {"message": diagnostic}


def test_commander_file_uri_and_unc_redaction_applies_to_all_three_envelopes(
    tmp_path,
) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="commander")
    params = {"action": "status", "project_name": "colameta-self-dev"}
    private_file_uri = "file:///etc/colameta/private.json"
    private_unc = r"\\operator-host\private-share\diagnostic.json"
    message = (
        f"local evidence {private_file_uri} and {private_unc}; "
        "docs https://example.com/operator/help"
    )
    data = {
        "ok": True,
        "message": message,
        "context_binding": _base_context_binding(),
    }
    raw_result = {"ok": True, "tool": "manage_git", "data": data}
    server.tools["manage_git"] = lambda _: data

    legacy = server.call_tool_for_agent("manage_git", params)
    mcp = server._as_mcp_call_result(raw_result, params)["structuredContent"]
    actions = server._package_actions_rest_response("manage_git", params, raw_result)

    for envelope in (legacy, mcp, actions):
        public_message = envelope["data"]["summary"]
        assert public_message.count("<local-path>") == 2
        assert private_file_uri not in public_message
        assert private_unc not in public_message
        assert "https://example.com/operator/help" in public_message


def test_commander_projection_applies_to_mcp_and_actions_envelopes(tmp_path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="commander")
    result = {
        "ok": True,
        "tool": "render_commander_app",
        "data": {
            "ok": True,
            "app_manifest_version": "colameta_commander_app.v1",
            "project_name": "colameta-self-dev",
            "project_root": "/home/example/src/project",
            "pid": 321,
            "safe_action": {"tool": "manage_git", "arguments": {"action": "status"}},
        },
        "_meta": {
            "ui": {"resourceUri": "ui://colameta/commander/v1.html"},
            "commander_app": {"project_name": "colameta-self-dev"},
        },
    }

    shaped = server._as_mcp_call_result(result, {"project_name": "colameta-self-dev"})
    shaped_contract = shaped["structuredContent"]["data"]
    assert shaped_contract["schema_version"] == "commander_response.v1"
    assert shaped_contract["facts"]["project_name"] == "colameta-self-dev"
    assert "project_root" not in shaped_contract["facts"]
    assert "pid" not in shaped_contract["facts"]
    assert shaped["_meta"]["ui"]["resourceUri"] == "ui://colameta/commander/v1.html"

    actions = server._package_actions_rest_response(
        "render_commander_app",
        {"project_name": "colameta-self-dev"},
        result,
    )
    assert "project_root" not in actions["data"]["facts"]
    assert "pid" not in actions["data"]["facts"]
    assert actions["data"]["facts"]["safe_action"]["tool"] == "manage_git"


def test_normal_profile_keeps_full_result_without_public_projection(tmp_path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="normal")
    result = {
        "ok": True,
        "tool": "analyze_project_state",
        "data": {
            "project_root": "/home/example/src/project",
            "pid": 321,
            "updated_at": "2026-07-19T00:00:00Z",
        },
    }

    assert server._commander_public_project_tool_result(result) is result
