from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess

from runner.mcp_server import MCP_REVIEW_MANIFEST_RESOURCE_TEMPLATES, MCPPlanningBridgeServer
from runner.project_registry import ProjectRegistry
from runner.review_manifest import (
    REVIEW_MANIFEST_SCHEMA_VERSION,
    ReviewManifestStore,
    collect_review_context_binding,
    inspect_review_manifest,
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


def test_review_manifest_resource_templates_advertise_only_static_uri_shapes(tmp_path: Path) -> None:
    project = _make_git_checkout(tmp_path)
    server = MCPPlanningBridgeServer(str(project))

    listed = _resource_templates_list(server)
    templates = listed["result"]["resourceTemplates"]
    assert templates == [dict(item) for item in MCP_REVIEW_MANIFEST_RESOURCE_TEMPLATES]
    assert [item["uriTemplate"] for item in templates] == [
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
