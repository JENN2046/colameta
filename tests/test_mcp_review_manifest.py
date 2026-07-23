from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from runner.mcp_server import (
    MCP_RESULT_ARTIFACT_RESOURCE_TEMPLATES,
    MCP_REVIEW_MANIFEST_RESOURCE_TEMPLATES,
    MCP_TOOL_POLICIES,
    MCPPlanningBridgeServer,
)
from runner.project_registry import ProjectRegistry
from runner.review_manifest import (
    REVIEW_MANIFEST_SCHEMA_VERSION,
    ReviewManifestStore,
    collect_review_context_binding,
    inspect_review_manifest,
)
from runner.review_manifest_validation import (
    canonical_manifest_validation_sha256,
    manifest_validation_contract_from_artifact,
)


def _make_git_checkout(tmp_path: Path, *, managed: bool = False) -> Path:
    project = tmp_path / "review-project"
    project.mkdir()
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    subprocess.run(["git", "-C", str(project), "config", "user.email", "review@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(project), "config", "user.name", "Review Fixture"], check=True)
    docs_dir = project / "docs"
    docs_dir.mkdir()
    (docs_dir / "review-input.md").write_text("# Review input\n\nA bounded subject.\n", encoding="utf-8")
    (docs_dir / "review-contract.yaml").write_text("review: independent\n", encoding="utf-8")
    if managed:
        runner_dir = project / ".colameta"
        runner_dir.mkdir()
        (runner_dir / "plan.json").write_text(
            json.dumps({"project_name": "managed-review", "versions": []}),
            encoding="utf-8",
        )
        (runner_dir / "state.json").write_text(
            json.dumps({"current_version": "v9.9"}),
            encoding="utf-8",
        )
    subprocess.run(["git", "-C", str(project), "add", "."], check=True)
    subprocess.run(["git", "-C", str(project), "commit", "-qm", "review fixture"], check=True)
    return project


def _manifest(project: Path, *, project_name: str | None = None) -> dict:
    binding = collect_review_context_binding(str(project), project_name=project_name)
    subjects = []
    for path in ("docs/review-input.md", "docs/review-contract.yaml"):
        subjects.append(
            {
                "path": path,
                "sha256": hashlib.sha256((project / path).read_bytes()).hexdigest(),
            }
        )
    return {
        "schema_version": REVIEW_MANIFEST_SCHEMA_VERSION,
        "review_unit": "independent-review-001",
        "workflow_intent": "independent_review",
        **binding,
        "subjects": subjects,
        "acceptance_commands": [
            {"command": "git diff --check", "timeout_seconds": 60},
        ],
    }


def _resource_read(server: MCPPlanningBridgeServer, uri: str, *, auth_context: dict | None = None) -> dict:
    response = server._handle_jsonrpc_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "resources/read",
            "params": {"uri": uri},
        },
        auth_context=auth_context,
    )
    assert response is not None
    return response


def _resource_templates_list(server: MCPPlanningBridgeServer) -> dict:
    response = server._handle_jsonrpc_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "resources/templates/list",
            "params": {},
        }
    )
    assert response is not None
    return response


def _tool_call(server: MCPPlanningBridgeServer, arguments: dict) -> dict:
    response = server._handle_jsonrpc_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "run_mcp_workflow", "arguments": arguments},
        }
    )
    assert response is not None
    return response


def test_review_manifest_binds_inputs_and_exposes_only_subject_resources(tmp_path: Path) -> None:
    project = _make_git_checkout(tmp_path, managed=True)
    server = MCPPlanningBridgeServer(str(project))

    template = server.call_tool_for_agent(
        "run_mcp_workflow",
        {"workflow": "review_manifest", "phase": "inspect"},
    )
    assert template["ok"] is True
    assert template["data"]["status"] == "template_ready"
    assert template["data"]["context_binding"]["current_version"] == "v9.9"
    assert template["data"]["authority_boundary"]["does_not_read_files"] is True

    result = server.call_tool_for_agent(
        "run_mcp_workflow",
        {"workflow": "review_manifest", "phase": "inspect", "review_manifest": _manifest(project)},
    )

    assert result["ok"] is True
    data = result["data"]
    assert data["workflow"] == "review_manifest"
    assert data["read_only"] is True
    assert data["side_effects"] is False
    assert data["context_binding"]["current_version"] == "v9.9"
    assert data["context_binding"]["runner_plan"]["mode"] == "managed"
    assert data["subject_count"] == 2
    assert all("content" not in subject for subject in data["subjects"])
    assert data["independent_review_packet"]["validation_preview"]["commands_executed"] is False
    assert data["independent_review_packet"]["authority_boundary"]["does_not_read_unlisted_files"] is True

    summary_response = _resource_read(server, data["manifest_resource_uri"])
    summary = json.loads(summary_response["result"]["contents"][0]["text"])
    assert summary["review_manifest_id"] == data["review_manifest_id"]
    assert summary["subjects"][0]["resource_uri"] == data["subjects"][0]["resource_uri"]

    subject_response = _resource_read(server, data["subjects"][0]["resource_uri"])
    subject_page = json.loads(subject_response["result"]["contents"][0]["text"])
    assert subject_page["path"] == "docs/review-input.md"
    assert subject_page["content"] == "# Review input\n\nA bounded subject.\n"
    assert subject_page["sha256"] == data["subjects"][0]["sha256"]

    verified = server.call_tool_for_agent(
        "run_mcp_workflow",
        {
            "workflow": "review_manifest",
            "phase": "verify",
            "review_manifest_id": data["review_manifest_id"],
        },
    )
    assert verified["ok"] is True
    assert verified["data"]["verification"]["context_binding"] == "matched"
    assert verified["data"]["verification"]["subject_hashes"] == "matched"


def test_manifest_bound_validation_preview_and_run_keep_the_review_contract(tmp_path: Path) -> None:
    project = _make_git_checkout(tmp_path)
    server = MCPPlanningBridgeServer(str(project))
    inspected = server.call_tool_for_agent(
        "run_mcp_workflow",
        {"workflow": "review_manifest", "phase": "inspect", "review_manifest": _manifest(project)},
    )
    assert inspected["ok"] is True

    preview = server.call_tool_for_agent(
        "manage_validation_run",
        {
            "action": "preview",
            "review_manifest_id": inspected["data"]["review_manifest_id"],
        },
    )
    assert preview["ok"] is True
    data = preview["data"]
    assert data["scope"] == "manifest_bound"
    assert data["strategy"] == "manifest_acceptance"
    assert data["can_run"] is True
    assert data["command_summary"] == ["git diff --check"]
    contract = data["manifest_validation"]
    assert contract["manifest_sha256"] == inspected["data"]["manifest_sha256"]
    assert contract["subjects"] == [
        {"path": item["path"], "sha256": item["sha256"]}
        for item in inspected["data"]["subjects"]
    ]
    assert contract["command_specs"] == [{
        "argv": ["git", "diff", "--check"],
        "timeout_seconds": 60,
        "continue_on_failure": False,
    }]
    assert len(contract["contract_sha256"]) == 64
    run_action = data["next_actions"][0]
    assert run_action["params"]["context_binding"] == data["context_binding"]

    started = server.call_tool_for_agent("manage_validation_run", run_action["params"])
    assert started["ok"] is True
    run_id = started["data"]["run_id"]
    assert started["data"]["manifest_validation"]["contract_sha256"] == contract["contract_sha256"]

    final: dict | None = None
    for _ in range(100):
        status = server.call_tool_for_agent(
            "manage_validation_run",
            {"action": "status", "run_id": run_id},
        )
        assert status["ok"] is True
        final = status["data"]
        if final["status"] != "running":
            break
        time.sleep(0.01)
    assert final is not None
    assert final["status"] == "passed"
    assert final["passed"] is True
    assert final["manifest_validation"]["contract_sha256"] == contract["contract_sha256"]


def test_manifest_bound_validation_rechecks_subjects_and_rejects_unsafe_commands(tmp_path: Path) -> None:
    project = _make_git_checkout(tmp_path)
    server = MCPPlanningBridgeServer(str(project))
    inspected = server.call_tool_for_agent(
        "run_mcp_workflow",
        {"workflow": "review_manifest", "phase": "inspect", "review_manifest": _manifest(project)},
    )
    assert inspected["ok"] is True
    preview = server.call_tool_for_agent(
        "manage_validation_run",
        {
            "action": "preview",
            "review_manifest_id": inspected["data"]["review_manifest_id"],
        },
    )
    assert preview["ok"] is True
    (project / "docs" / "review-input.md").write_text("changed after preview\n", encoding="utf-8")
    blocked = server.call_tool_for_agent(
        "manage_validation_run",
        {
            "action": "run",
            "preview_id": preview["data"]["preview_id"],
            "context_binding": preview["data"]["context_binding"],
        },
    )
    assert blocked["ok"] is False
    assert blocked["error_code"] == "REVIEW_MANIFEST_SUBJECT_HASH_MISMATCH"

    unsafe_manifest = _manifest(project)
    unsafe_manifest["subjects"] = [
        {
            "path": "docs/review-contract.yaml",
            "sha256": hashlib.sha256(
                (project / "docs" / "review-contract.yaml").read_bytes()
            ).hexdigest(),
        }
    ]
    unsafe_manifest["acceptance_commands"] = [{
        "command": "git diff --check && echo should-not-run",
        "timeout_seconds": 60,
    }]
    unsafe_inspected = server.call_tool_for_agent(
        "run_mcp_workflow",
        {
            "workflow": "review_manifest",
            "phase": "inspect",
            "review_manifest": unsafe_manifest,
        },
    )
    assert unsafe_inspected["ok"] is True
    unsafe_preview = server.call_tool_for_agent(
        "manage_validation_run",
        {
            "action": "preview",
            "review_manifest_id": unsafe_inspected["data"]["review_manifest_id"],
        },
    )
    assert unsafe_preview["ok"] is True
    unsafe_data = unsafe_preview["data"]
    assert unsafe_data["can_run"] is False
    assert unsafe_data["blockers"] == ["MANIFEST_VALIDATION_COMMAND_REJECTED"]
    assert unsafe_data["manifest_validation_rejections"] == [{
        "command_index": 1,
        "reason": "command_not_allowed",
    }]
    unsafe_run = server.call_tool_for_agent(
        "manage_validation_run",
        {
            "action": "run",
            "preview_id": unsafe_data["preview_id"],
            "context_binding": unsafe_data["context_binding"],
        },
    )
    # Validation-manager errors remain a successful transport envelope with a
    # bounded manager result, matching the legacy preview/run contract.
    assert unsafe_run["ok"] is True
    assert unsafe_run["data"]["error_code"] == "PREVIEW_BLOCKED"


def test_manifest_validation_contract_rejects_an_out_of_policy_timeout(tmp_path: Path) -> None:
    project = _make_git_checkout(tmp_path)
    server = MCPPlanningBridgeServer(str(project))
    inspected = server.call_tool_for_agent(
        "run_mcp_workflow",
        {"workflow": "review_manifest", "phase": "inspect", "review_manifest": _manifest(project)},
    )
    preview = server.call_tool_for_agent(
        "manage_validation_run",
        {
            "action": "preview",
            "review_manifest_id": inspected["data"]["review_manifest_id"],
        },
    )
    assert preview["ok"] is True

    # Model a locally altered preview artifact whose hashes were recomputed.
    # Structural hashing alone must not let it lower the execution timeout
    # below the normal validation policy's 10-second floor.
    contract = copy.deepcopy(preview["data"]["manifest_validation"])
    contract["command_specs"][0]["timeout_seconds"] = 1
    contract["command_specs_sha256"] = canonical_manifest_validation_sha256(
        contract["command_specs"]
    )
    unsigned_contract = {
        key: value
        for key, value in contract.items()
        if key != "contract_sha256"
    }
    contract["contract_sha256"] = canonical_manifest_validation_sha256(unsigned_contract)

    assert manifest_validation_contract_from_artifact({"manifest_validation": contract}) is None


def test_manifest_bound_validation_preview_supports_registered_source_only_projects(tmp_path: Path) -> None:
    project = _make_git_checkout(tmp_path)
    registry = ProjectRegistry(
        registry_path=str(tmp_path / "registry.json"),
        user_settings_path=str(tmp_path / "settings.json"),
    )
    registered = registry.register_project(str(project), project_name="review-target")
    assert registered["project"]["project_mode"] == "source-only"
    server = MCPPlanningBridgeServer(str(tmp_path), service_mode=True)
    server.project_registry = registry

    inspected = server.call_tool_for_agent(
        "run_mcp_workflow",
        {
            "workflow": "review_manifest",
            "phase": "inspect",
            "project_name": "review-target",
            "review_manifest": _manifest(project, project_name="review-target"),
        },
    )
    assert inspected["ok"] is True
    preview = server.call_tool_for_agent(
        "manage_validation_run",
        {
            "action": "preview",
            "project_name": "review-target",
            "review_manifest_id": inspected["data"]["review_manifest_id"],
        },
    )
    assert preview["ok"] is True
    data = preview["data"]
    assert data["project_name"] == "review-target"
    assert data["context_binding"]["project_name"] == "review-target"
    assert data["next_actions"][0]["params"]["project_name"] == "review-target"

    started = server.call_tool_for_agent(
        "manage_validation_run",
        data["next_actions"][0]["params"],
    )
    assert started["ok"] is True
    run_id = started["data"]["run_id"]
    final: dict | None = None
    for _ in range(100):
        status = server.call_tool_for_agent(
            "manage_validation_run",
            {
                "action": "status",
                "project_name": "review-target",
                "run_id": run_id,
            },
        )
        assert status["ok"] is True
        final = status["data"]
        if final["status"] != "running":
            break
        time.sleep(0.01)
    assert final is not None
    assert final["status"] == "passed"
    assert final["project_name"] == "review-target"
    assert final["manifest_validation"]["manifest_sha256"] == data["manifest_validation"]["manifest_sha256"]


def test_commander_schema_advertises_manifest_bound_validation_preview(tmp_path: Path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="commander")
    tools = {tool.name: tool for tool in server._filter_tools_by_exposure_profile(server.tool_defs)}
    schema = tools["manage_validation_run"].input_schema

    assert "review_manifest_id" in schema["properties"]
    assert "action=preview" in schema["properties"]["review_manifest_id"]["description"]
    assert MCP_TOOL_POLICIES["manage_validation_run"].scope_for({
        "action": "preview",
        "review_manifest_id": "opaque-review-manifest-handle",
    }) == "mcp:preview"
    assert MCP_TOOL_POLICIES["manage_validation_run"].scope_for({
        "action": "run",
    }) == "mcp:commit"


def test_resource_templates_advertise_only_static_uri_shapes(tmp_path: Path) -> None:
    project = _make_git_checkout(tmp_path)
    server = MCPPlanningBridgeServer(str(project))

    listed = _resource_templates_list(server)
    templates = listed["result"]["resourceTemplates"]
    assert templates == [
        *[dict(item) for item in MCP_RESULT_ARTIFACT_RESOURCE_TEMPLATES],
        *[dict(item) for item in MCP_REVIEW_MANIFEST_RESOURCE_TEMPLATES],
    ]
    assert [item["uriTemplate"] for item in templates] == [
        "colameta://result-artifact/{artifact_id}",
        "colameta://result-artifact/{artifact_id}/pages/{page}",
        "colameta://review-manifest/{review_manifest_id}",
        "colameta://review-manifest/{review_manifest_id}/subjects/{subject_index}",
        "colameta://review-manifest/{review_manifest_id}/subjects/{subject_index}/pages/{page}",
    ]
    assert all("path" not in item["uriTemplate"] for item in templates)
    assert all("review-project" not in repr(item) for item in templates)

    inspected = server.call_tool_for_agent(
        "run_mcp_workflow",
        {"workflow": "review_manifest", "phase": "inspect", "review_manifest": _manifest(project)},
    )
    assert inspected["ok"] is True
    descriptor = inspected["data"]["subjects"][0]
    assert descriptor["resource_uri"].startswith(
        "colameta://review-manifest/"
    )
    assert descriptor["page_uri_template"].endswith("/subjects/1/pages/{page}")


def test_commander_mcp_surface_keeps_review_manifest_continuation_handles(tmp_path: Path) -> None:
    project = _make_git_checkout(tmp_path)
    server = MCPPlanningBridgeServer(str(project), exposure_profile="commander")

    response = _tool_call(
        server,
        {"workflow": "review_manifest", "phase": "inspect", "review_manifest": _manifest(project)},
    )

    structured = response["result"]["structuredContent"]
    assert structured["ok"] is True
    data = structured["data"]
    assert data["review_manifest_id"]
    assert data["manifest_resource_uri"].startswith("colameta://review-manifest/")
    assert data["subjects"][0]["resource_uri"].startswith("colameta://review-manifest/")
    assert data["subjects"][0]["page_uri_template"].endswith("/pages/{page}")


def test_review_manifest_requires_a_git_context_template(tmp_path: Path) -> None:
    project = tmp_path / "not-a-git-checkout"
    project.mkdir()
    server = MCPPlanningBridgeServer(str(project))

    result = server.call_tool_for_agent(
        "run_mcp_workflow",
        {"workflow": "review_manifest", "phase": "inspect"},
    )

    assert result["ok"] is False
    assert result["error_code"] == "REVIEW_MANIFEST_CONTEXT_UNAVAILABLE"
    assert result["details"] == {"missing_context_fields": ["branch", "head"]}


def test_review_manifest_rejects_stale_or_missing_context_binding(tmp_path: Path) -> None:
    project = _make_git_checkout(tmp_path)
    server = MCPPlanningBridgeServer(str(project))
    manifest = _manifest(project)
    actual_head = manifest["head"]
    manifest["head"] = "b" * 40

    stale = server.call_tool_for_agent(
        "run_mcp_workflow",
        {"workflow": "review_manifest", "phase": "inspect", "review_manifest": manifest},
    )

    assert stale["ok"] is False
    assert stale["error_code"] == "CONTEXT_BINDING_MISMATCH"
    assert stale["details"]["mismatches"] == [
        {"field": "head", "expected": "b" * 40, "actual": actual_head}
    ]

    missing = copy.deepcopy(_manifest(project))
    missing.pop("current_version")
    missing_result = server.call_tool_for_agent(
        "run_mcp_workflow",
        {"workflow": "review_manifest", "phase": "inspect", "review_manifest": missing},
    )
    assert missing_result["ok"] is False
    assert missing_result["error_code"] == "CONTEXT_BINDING_MISMATCH"


def test_commander_keeps_safe_review_manifest_mismatch_details(tmp_path: Path) -> None:
    project = _make_git_checkout(tmp_path)
    server = MCPPlanningBridgeServer(str(project), exposure_profile="commander")
    manifest = _manifest(project)
    actual_head = manifest["head"]
    manifest["head"] = "b" * 40

    result = server.call_tool_for_agent(
        "run_mcp_workflow",
        {"workflow": "review_manifest", "phase": "inspect", "review_manifest": manifest},
    )

    assert result["ok"] is False
    assert result["error_code"] == "CONTEXT_BINDING_MISMATCH"
    assert result["details"]["mismatches"] == [
        {"field": "head", "expected": "b" * 40, "actual": actual_head}
    ]


def test_review_manifest_fails_closed_when_checkout_or_subject_changes(tmp_path: Path) -> None:
    project = _make_git_checkout(tmp_path)
    server = MCPPlanningBridgeServer(str(project))
    result = server.call_tool_for_agent(
        "run_mcp_workflow",
        {"workflow": "review_manifest", "phase": "inspect", "review_manifest": _manifest(project)},
    )
    assert result["ok"] is True
    subject_uri = result["data"]["subjects"][0]["resource_uri"]

    initial_head = result["data"]["context_binding"]["head"]
    (project / "docs" / "other.md").write_text("moves the checkout\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(project), "add", "docs/other.md"], check=True)
    subprocess.run(["git", "-C", str(project), "commit", "-qm", "move checkout"], check=True)
    moved_checkout = _resource_read(server, subject_uri)
    assert moved_checkout["error"]["data"]["error_code"] == "CONTEXT_BINDING_MISMATCH"
    assert moved_checkout["error"]["data"]["details"]["mismatches"] == [
        {
            "field": "head",
            "expected": initial_head,
            "actual": subprocess.run(
                ["git", "-C", str(project), "rev-parse", "HEAD"],
                check=True,
                text=True,
                capture_output=True,
            ).stdout.strip(),
        }
    ]

    subprocess.run(["git", "-C", str(project), "reset", "--hard", initial_head], check=True)
    (project / "docs" / "review-input.md").write_text("changed\n", encoding="utf-8")
    changed_subject = server.call_tool_for_agent(
        "run_mcp_workflow",
        {
            "workflow": "review_manifest",
            "phase": "verify",
            "review_manifest_id": result["data"]["review_manifest_id"],
        },
    )
    assert changed_subject["ok"] is False
    assert changed_subject["error_code"] == "REVIEW_MANIFEST_SUBJECT_HASH_MISMATCH"


def test_review_manifest_fails_closed_when_managed_plan_or_version_changes(tmp_path: Path) -> None:
    project = _make_git_checkout(tmp_path, managed=True)
    server = MCPPlanningBridgeServer(str(project))
    result = server.call_tool_for_agent(
        "run_mcp_workflow",
        {"workflow": "review_manifest", "phase": "inspect", "review_manifest": _manifest(project)},
    )
    assert result["ok"] is True
    review_manifest_id = result["data"]["review_manifest_id"]

    state_path = project / ".colameta" / "state.json"
    state_path.write_text(json.dumps({"current_version": "v9.10"}), encoding="utf-8")
    version_changed = server.call_tool_for_agent(
        "run_mcp_workflow",
        {"workflow": "review_manifest", "phase": "verify", "review_manifest_id": review_manifest_id},
    )
    assert version_changed["ok"] is False
    assert version_changed["error_code"] == "CONTEXT_BINDING_MISMATCH"
    assert version_changed["details"]["mismatches"] == [
        {"field": "current_version", "expected": "v9.9", "actual": "v9.10"}
    ]

    state_path.write_text(json.dumps({"current_version": "v9.9"}), encoding="utf-8")
    plan_path = project / ".colameta" / "plan.json"
    plan_path.write_text(
        json.dumps({"project_name": "managed-review", "versions": [{"id": "v9.10"}]}),
        encoding="utf-8",
    )
    plan_changed = server.call_tool_for_agent(
        "run_mcp_workflow",
        {"workflow": "review_manifest", "phase": "verify", "review_manifest_id": review_manifest_id},
    )
    assert plan_changed["ok"] is False
    assert plan_changed["error_code"] == "CONTEXT_BINDING_MISMATCH"
    mismatch = plan_changed["details"]["mismatches"]
    assert [item["field"] for item in mismatch] == ["runner_plan"]
    assert mismatch[0]["expected"]["mode"] == "managed"
    assert mismatch[0]["actual"]["mode"] == "managed"


def test_review_manifest_read_fails_closed_when_context_changes(tmp_path: Path) -> None:
    project = _make_git_checkout(tmp_path, managed=True)
    server = MCPPlanningBridgeServer(str(project))
    inspected = server.call_tool_for_agent(
        "run_mcp_workflow",
        {"workflow": "review_manifest", "phase": "inspect", "review_manifest": _manifest(project)},
    )
    assert inspected["ok"] is True

    state_path = project / ".colameta" / "state.json"
    state_path.write_text(json.dumps({"current_version": "v9.10"}), encoding="utf-8")
    read = server.call_tool_for_agent(
        "run_mcp_workflow",
        {
            "workflow": "review_manifest",
            "phase": "read",
            "review_manifest_id": inspected["data"]["review_manifest_id"],
            "review_manifest_subject_index": 1,
        },
    )

    assert read["ok"] is False
    assert read["error_code"] == "CONTEXT_BINDING_MISMATCH"
    assert read["details"]["mismatches"] == [
        {"field": "current_version", "expected": "v9.9", "actual": "v9.10"}
    ]


def test_review_manifest_subjects_are_paged_and_require_read_scope(tmp_path: Path) -> None:
    project = _make_git_checkout(tmp_path)
    content = "page-bound review input\n" * 900
    (project / "docs" / "review-input.md").write_text(content, encoding="utf-8")
    server = MCPPlanningBridgeServer(str(project))
    result = server.call_tool_for_agent(
        "run_mcp_workflow",
        {"workflow": "review_manifest", "phase": "inspect", "review_manifest": _manifest(project)},
    )
    assert result["ok"] is True
    descriptor = result["data"]["subjects"][0]
    assert descriptor["page_count"] > 1

    class _ScopeProvider:
        @staticmethod
        def validate_scope(token_payload: dict, scope: str) -> bool:
            return scope in str(token_payload.get("scope") or "").split()

    denied = _resource_read(
        server,
        descriptor["resource_uri"],
        auth_context={
            "mode": "external-oauth",
            "oauth_provider": _ScopeProvider(),
            "token": {"scope": "mcp:preview"},
        },
    )
    assert denied["error"]["data"]["error_code"] == "resource_access_denied"

    pages: list[str] = []
    for page in range(1, descriptor["page_count"] + 1):
        uri = descriptor["resource_uri"] if page == 1 else descriptor["page_uri_template"].format(page=page)
        response = _resource_read(server, uri)
        page_data = json.loads(response["result"]["contents"][0]["text"])
        assert page_data["page"] == page
        pages.append(page_data["content"])
    assert "".join(pages) == content
    assert hashlib.sha256(content.encode("utf-8")).hexdigest() == descriptor["sha256"]


def test_review_manifest_read_phase_returns_only_reverified_bound_pages(tmp_path: Path) -> None:
    project = _make_git_checkout(tmp_path)
    content = "page-bound compatibility read\n" * 900
    (project / "docs" / "review-input.md").write_text(content, encoding="utf-8")
    server = MCPPlanningBridgeServer(str(project))
    inspected = server.call_tool_for_agent(
        "run_mcp_workflow",
        {"workflow": "review_manifest", "phase": "inspect", "review_manifest": _manifest(project)},
    )
    assert inspected["ok"] is True
    descriptor = inspected["data"]["subjects"][0]
    read_call = descriptor["read_call"]
    assert read_call["tool"] == "run_mcp_workflow"
    assert read_call["arguments"]["review_manifest_subject_index"] == 1
    assert read_call["arguments"]["review_manifest_page"] == 1

    pages: list[str] = []
    for page in range(1, descriptor["page_count"] + 1):
        result = server.call_tool_for_agent(
            "run_mcp_workflow",
            {
                "workflow": "review_manifest",
                "phase": "read",
                "review_manifest_id": inspected["data"]["review_manifest_id"],
                "review_manifest_subject_index": 1,
                "review_manifest_page": page,
            },
        )
        assert result["ok"] is True
        data = result["data"]
        assert data["read_only"] is True
        assert data["side_effects"] is False
        assert data["verification"] == {
            "context_binding": "matched",
            "subject_hash": "matched",
            "subject_index": 1,
        }
        subject_page = data["subject_page"]
        assert subject_page["page"] == page
        assert subject_page["sha256"] == descriptor["sha256"]
        pages.append(subject_page["content"])
    assert "".join(pages) == content

    missing_subject = server.call_tool_for_agent(
        "run_mcp_workflow",
        {
            "workflow": "review_manifest",
            "phase": "read",
            "review_manifest_id": inspected["data"]["review_manifest_id"],
        },
    )
    assert missing_subject["ok"] is False
    assert missing_subject["error_code"] == "REVIEW_MANIFEST_SUBJECT_INDEX_REQUIRED"

    invalid_page = server.call_tool_for_agent(
        "run_mcp_workflow",
        {
            "workflow": "review_manifest",
            "phase": "read",
            "review_manifest_id": inspected["data"]["review_manifest_id"],
            "review_manifest_subject_index": 1,
            "review_manifest_page": descriptor["page_count"] + 1,
        },
    )
    assert invalid_page["ok"] is False
    assert invalid_page["error_code"] == "REVIEW_MANIFEST_PAGE_NOT_FOUND"

    (project / "docs" / "review-input.md").write_text("changed after inspect\n", encoding="utf-8")
    changed_subject = server.call_tool_for_agent(
        "run_mcp_workflow",
        {
            "workflow": "review_manifest",
            "phase": "read",
            "review_manifest_id": inspected["data"]["review_manifest_id"],
            "review_manifest_subject_index": 1,
        },
    )
    assert changed_subject["ok"] is False
    assert changed_subject["error_code"] == "REVIEW_MANIFEST_SUBJECT_HASH_MISMATCH"


def test_commander_manifest_read_preserves_exact_bound_content(tmp_path: Path) -> None:
    project = _make_git_checkout(tmp_path)
    content = "Literal source text: /home/reviewer/example.md\n"
    (project / "docs" / "review-input.md").write_text(content, encoding="utf-8")
    server = MCPPlanningBridgeServer(str(project), exposure_profile="commander")

    inspected = _tool_call(
        server,
        {"workflow": "review_manifest", "phase": "inspect", "review_manifest": _manifest(project)},
    )
    inspection_data = inspected["result"]["structuredContent"]["data"]
    read = _tool_call(
        server,
        {
            "workflow": "review_manifest",
            "phase": "read",
            "review_manifest_id": inspection_data["review_manifest_id"],
            "review_manifest_subject_index": 1,
        },
    )
    subject_page = read["result"]["structuredContent"]["data"]["subject_page"]
    assert subject_page["content"] == content
    assert subject_page["sha256"] == inspection_data["subjects"][0]["sha256"]


def test_review_manifest_routes_source_only_registered_projects_without_opening_arbitrary_paths(tmp_path: Path) -> None:
    project = _make_git_checkout(tmp_path)
    registry = ProjectRegistry(
        registry_path=str(tmp_path / "registry.json"),
        user_settings_path=str(tmp_path / "settings.json"),
    )
    registered = registry.register_project(str(project), project_name="review-target")
    assert registered["project"]["project_mode"] == "source-only"

    server = MCPPlanningBridgeServer(str(tmp_path), service_mode=True)
    server.project_registry = registry
    result = server.call_tool_for_agent(
        "run_mcp_workflow",
        {
            "workflow": "review_manifest",
            "phase": "inspect",
            "project_name": "review-target",
            "review_manifest": _manifest(project, project_name="review-target"),
        },
    )
    assert result["ok"] is True
    assert result["data"]["context_binding"]["project_name"] == "review-target"
    read_call = result["data"]["subjects"][0]["read_call"]
    assert read_call["arguments"]["project_name"] == "review-target"
    read_result = server.call_tool_for_agent("run_mcp_workflow", read_call["arguments"])
    assert read_result["ok"] is True
    assert read_result["data"]["subject_page"]["path"] == "docs/review-input.md"

    denied_manifest = _manifest(project, project_name="review-target")
    denied_manifest["subjects"] = [
        {
            "path": ".env",
            "sha256": hashlib.sha256(b"not-read").hexdigest(),
        }
    ]
    denied = server.call_tool_for_agent(
        "run_mcp_workflow",
        {
            "workflow": "review_manifest",
            "phase": "inspect",
            "project_name": "review-target",
            "review_manifest": denied_manifest,
        },
    )
    assert denied["ok"] is False
    assert denied["error_code"] == "REVIEW_MANIFEST_SUBJECT_DENIED"

    high_risk_manifest = _manifest(project, project_name="review-target")
    high_risk_manifest["subjects"] = [
        {
            "path": "config/production.yaml",
            "sha256": hashlib.sha256(b"not-read").hexdigest(),
        }
    ]
    high_risk = server.call_tool_for_agent(
        "run_mcp_workflow",
        {
            "workflow": "review_manifest",
            "phase": "inspect",
            "project_name": "review-target",
            "review_manifest": high_risk_manifest,
        },
    )
    assert high_risk["ok"] is False
    assert high_risk["error_code"] == "REVIEW_MANIFEST_SUBJECT_DENIED"


def test_review_manifest_service_read_continuation_keeps_project_name(tmp_path: Path) -> None:
    project = _make_git_checkout(tmp_path)
    content = "service compatibility page\n" * 900
    (project / "docs" / "review-input.md").write_text(content, encoding="utf-8")
    registry = ProjectRegistry(
        registry_path=str(tmp_path / "registry.json"),
        user_settings_path=str(tmp_path / "settings.json"),
    )
    registered = registry.register_project(str(project), project_name="review-target")
    assert registered["ok"] is True
    server = MCPPlanningBridgeServer(str(tmp_path), service_mode=True)
    server.project_registry = registry

    inspected = server.call_tool_for_agent(
        "run_mcp_workflow",
        {
            "workflow": "review_manifest",
            "phase": "inspect",
            "project_name": "review-target",
            "review_manifest": _manifest(project, project_name="review-target"),
        },
    )
    assert inspected["ok"] is True
    descriptor = inspected["data"]["subjects"][0]
    assert descriptor["page_count"] > 1

    first_read = server.call_tool_for_agent("run_mcp_workflow", descriptor["read_call"]["arguments"])
    assert first_read["ok"] is True
    next_reads = first_read["data"]["recommended_next_reads"]
    assert len(next_reads) == 1
    next_call = next_reads[0]
    assert next_call["kind"] == "mcp_tool"
    assert next_call["tool"] == "run_mcp_workflow"
    assert next_call["arguments"]["project_name"] == "review-target"
    assert next_call["arguments"]["review_manifest_subject_index"] == 1
    assert next_call["arguments"]["review_manifest_page"] == 2

    second_read = server.call_tool_for_agent("run_mcp_workflow", next_call["arguments"])
    assert second_read["ok"] is True
    assert second_read["data"]["subject_page"]["page"] == 2


def test_review_manifest_rejects_symlink_subject_aliases(tmp_path: Path) -> None:
    project = _make_git_checkout(tmp_path)
    (project / "docs" / "review-alias.md").symlink_to("review-input.md")
    (project / "linked-docs").symlink_to("docs", target_is_directory=True)
    server = MCPPlanningBridgeServer(str(project))
    digest = hashlib.sha256((project / "docs" / "review-input.md").read_bytes()).hexdigest()
    for alias_path in ("docs/review-alias.md", "linked-docs/review-input.md"):
        manifest = _manifest(project)
        manifest["subjects"] = [{"path": alias_path, "sha256": digest}]
        result = server.call_tool_for_agent(
            "run_mcp_workflow",
            {"workflow": "review_manifest", "phase": "inspect", "review_manifest": manifest},
        )
        assert result["ok"] is False
        assert result["error_code"] == "REVIEW_MANIFEST_SUBJECT_UNSAFE"


def test_review_manifest_rejects_non_regular_subjects_without_blocking(tmp_path: Path) -> None:
    if not hasattr(os, "mkfifo"):
        return
    project = _make_git_checkout(tmp_path)
    fifo = project / "docs" / "review-input-fifo.md"
    os.mkfifo(fifo)
    server = MCPPlanningBridgeServer(str(project))
    manifest = _manifest(project)
    manifest["subjects"] = [
        {
            "path": "docs/review-input-fifo.md",
            "sha256": hashlib.sha256(b"not-read").hexdigest(),
        }
    ]

    result = server.call_tool_for_agent(
        "run_mcp_workflow",
        {"workflow": "review_manifest", "phase": "inspect", "review_manifest": manifest},
    )
    assert result["ok"] is False
    assert result["error_code"] == "REVIEW_MANIFEST_SUBJECT_UNSAFE"


def test_review_manifest_session_expires_without_persisting_subject_content(tmp_path: Path) -> None:
    project = _make_git_checkout(tmp_path)
    context_binding = collect_review_context_binding(str(project))
    inspection = inspect_review_manifest(
        _manifest(project),
        project_root=str(project),
        context_binding=context_binding,
    )
    clock = [datetime(2026, 7, 22, tzinfo=timezone.utc)]
    store = ReviewManifestStore(ttl_seconds=60, now_fn=lambda: clock[0])
    handle = store.put(project_root=str(project), inspection=inspection)

    assert store.get(handle.review_manifest_id) is not None
    clock[0] += timedelta(seconds=60)
    assert store.get(handle.review_manifest_id) is None
