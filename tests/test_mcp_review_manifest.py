from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

import runner.mcp_server as mcp_server_module
from runner.commander_contract import validate_commander_response
from runner.mcp_server import (
    MCP_RESULT_ARTIFACT_RESOURCE_TEMPLATES,
    MCP_REVIEW_MANIFEST_RESOURCE_TEMPLATES,
    MCP_TOOL_POLICIES,
    MCPPlanningBridgeServer,
)
from runner.mcp_validation_run import (
    MCPValidationRunManager,
    VALIDATION_RUN_RESULT_SCHEMA_VERSION,
    canonical_validation_result_sha256,
)
from runner.project_registry import ProjectRegistry
from runner.review_manifest import (
    REVIEW_MANIFEST_PAGE_CHARS,
    REVIEW_MANIFEST_SCHEMA_VERSION,
    ReviewManifestStore,
    collect_review_context_binding,
    inspect_review_manifest,
)
from runner.review_manifest_validation import (
    canonical_manifest_validation_sha256,
    manifest_validation_contract_from_artifact,
)


def _make_git_checkout(
    tmp_path: Path,
    *,
    managed: bool = False,
    object_format: str | None = None,
) -> Path:
    project = tmp_path / "review-project"
    project.mkdir()
    init_command = ["git", "init", "-q"]
    if object_format is not None:
        init_command.append(f"--object-format={object_format}")
    subprocess.run([*init_command, str(project)], check=True)
    subprocess.run(["git", "-C", str(project), "config", "user.email", "review@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(project), "config", "user.name", "Review Fixture"], check=True)
    docs_dir = project / "docs"
    docs_dir.mkdir()
    (project / ".gitignore").write_text(
        ".pytest_cache/\n.venv/\n",
        encoding="utf-8",
    )
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


def _completed_manifest_validation(
    project: Path,
) -> tuple[MCPValidationRunManager, str, dict, Path]:
    server = MCPPlanningBridgeServer(str(project))
    inspected = server.call_tool_for_agent(
        "run_mcp_workflow",
        {
            "workflow": "review_manifest",
            "phase": "inspect",
            "review_manifest": _manifest(project),
        },
    )
    preview = server.call_tool_for_agent(
        "manage_validation_run",
        {
            "action": "preview",
            "review_manifest_id": inspected["data"]["review_manifest_id"],
        },
    )
    started = server.call_tool_for_agent(
        "manage_validation_run",
        preview["data"]["next_actions"][0]["params"],
    )
    run_id = started["data"]["run_id"]
    final: dict | None = None
    for _ in range(100):
        status = server.call_tool_for_agent(
            "manage_validation_run",
            {"action": "status", "run_id": run_id},
        )
        final = status["data"]
        if final["status"] != "running":
            break
        time.sleep(0.01)
    assert final is not None and final["status"] == "passed"
    manager = MCPValidationRunManager(str(project))
    path = (
        project
        / ".colameta"
        / "runtime"
        / "validation-runs"
        / f"{run_id}.json"
    )
    return manager, run_id, final, path


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


def test_legacy_review_manifest_defaults_omitted_phase_to_inspect(
    tmp_path: Path,
) -> None:
    project = _make_git_checkout(tmp_path, managed=True)
    server = MCPPlanningBridgeServer(str(project))

    template = server.call_tool_for_agent(
        "run_mcp_workflow",
        {"workflow": "review_manifest"},
    )

    assert template["ok"] is True
    assert template["data"]["status"] == "template_ready"
    assert template["data"]["authority_boundary"]["does_not_read_files"] is True


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
    assert final["schema_version"] == VALIDATION_RUN_RESULT_SCHEMA_VERSION
    assert final["integrity_classification"] == "verified"
    assert len(final["validation_result_sha256"]) == 64
    assert final["manifest_validation"]["contract_sha256"] == contract["contract_sha256"]
    assert final["command_results"][0]["executed_command"] == " ".join(
        [
            "git",
            "diff-tree",
            "--check",
            "--root",
            "-r",
            "-m",
            "--no-commit-id",
            "--no-ext-diff",
            "--no-textconv",
            inspected["data"]["context_binding"]["head"],
        ]
    )
    checkout = final["output_summary"]["checkout_provenance"]
    assert checkout["mode"] == "isolated_detached_worktree"
    assert checkout["candidate_head"] == inspected["data"]["context_binding"]["head"]
    assert checkout["source_before"] == checkout["source_after"]
    assert checkout["source_binding_match"] is True
    assert checkout["isolated_from_project_worktree"] is True
    assert checkout["cleanup_complete"] is True
    worktrees = subprocess.run(
        ["git", "-C", str(project), "worktree", "list", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert worktrees.count("worktree ") == 1


def test_manifest_bound_validation_accepts_sha256_git_object_ids(
    tmp_path: Path,
) -> None:
    project = _make_git_checkout(tmp_path, object_format="sha256")
    candidate_head = subprocess.run(
        ["git", "-C", str(project), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert len(candidate_head) == 64

    server = MCPPlanningBridgeServer(str(project))
    inspected = server.call_tool_for_agent(
        "run_mcp_workflow",
        {
            "workflow": "review_manifest",
            "phase": "inspect",
            "review_manifest": _manifest(project),
        },
    )
    assert inspected["ok"] is True
    assert inspected["data"]["context_binding"]["head"] == candidate_head

    preview = server.call_tool_for_agent(
        "manage_validation_run",
        {
            "action": "preview",
            "review_manifest_id": inspected["data"]["review_manifest_id"],
        },
    )
    assert preview["ok"] is True
    started = server.call_tool_for_agent(
        "manage_validation_run",
        preview["data"]["next_actions"][0]["params"],
    )
    assert started["ok"] is True

    final: dict | None = None
    for _ in range(100):
        status = server.call_tool_for_agent(
            "manage_validation_run",
            {
                "action": "status",
                "run_id": started["data"]["run_id"],
            },
        )
        assert status["ok"] is True
        final = status["data"]
        if final["status"] != "running":
            break
        time.sleep(0.01)

    assert final is not None
    assert final["status"] == "passed"
    checkout = final["output_summary"]["checkout_provenance"]
    assert checkout["candidate_head"] == candidate_head
    assert checkout["source_before"]["git_object_format"] == "sha256"
    assert checkout["source_after"]["git_object_format"] == "sha256"


def test_manifest_bound_git_diff_checks_the_candidate_commit(
    tmp_path: Path,
) -> None:
    project = _make_git_checkout(tmp_path)
    subject = project / "docs" / "review-input.md"
    subject.write_text(
        "# Review input\n\nCommitted trailing whitespace.  \n",
        encoding="utf-8",
    )
    subprocess.run(["git", "-C", str(project), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(project), "commit", "-qm", "bad whitespace"],
        check=True,
    )
    candidate_head = subprocess.run(
        ["git", "-C", str(project), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    server = MCPPlanningBridgeServer(str(project))
    inspected = server.call_tool_for_agent(
        "run_mcp_workflow",
        {
            "workflow": "review_manifest",
            "phase": "inspect",
            "review_manifest": _manifest(project),
        },
    )
    preview = server.call_tool_for_agent(
        "manage_validation_run",
        {
            "action": "preview",
            "review_manifest_id": inspected["data"]["review_manifest_id"],
        },
    )
    started = server.call_tool_for_agent(
        "manage_validation_run",
        preview["data"]["next_actions"][0]["params"],
    )

    final: dict | None = None
    for _ in range(100):
        status = server.call_tool_for_agent(
            "manage_validation_run",
            {
                "action": "status",
                "run_id": started["data"]["run_id"],
            },
        )
        assert status["ok"] is True
        final = status["data"]
        if final["status"] != "running":
            break
        time.sleep(0.01)

    assert final is not None
    assert final["status"] == "failed"
    assert final["passed"] is False
    command_result = final["command_results"][0]
    assert command_result["returncode"] != 0
    assert command_result["executed_command"].endswith(candidate_head)
    assert "diff-tree --check --root" in command_result["executed_command"]
    assert "trailing whitespace" in (
        command_result["stdout"] + command_result["stderr"]
    )


def test_manifest_validation_isolated_checkout_ignores_transient_source_checkout_changes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = _make_git_checkout(tmp_path)
    subject = project / "docs" / "review-input.md"
    original_subject = subject.read_text(encoding="utf-8")
    execution_roots: list[str] = []
    original_run_command = MCPValidationRunManager._run_command

    def run_command(
        self,
        command,
        *,
        timeout_seconds,
        cwd=None,
    ):
        assert cwd is not None
        execution_roots.append(cwd)
        subject.write_text("transient unrelated checkout change\n", encoding="utf-8")
        try:
            return original_run_command(
                self,
                command,
                timeout_seconds=timeout_seconds,
                cwd=cwd,
            )
        finally:
            subject.write_text(original_subject, encoding="utf-8")

    monkeypatch.setattr(
        MCPValidationRunManager,
        "_run_command",
        run_command,
    )
    _manager, _run_id, final, _path = _completed_manifest_validation(
        project
    )

    assert final["status"] == "passed"
    assert execution_roots
    assert all(
        os.path.realpath(root) != os.path.realpath(project)
        for root in execution_roots
    )
    assert subject.read_text(encoding="utf-8") == original_subject
    checkout = final["output_summary"]["checkout_provenance"]
    assert checkout["source_binding_match"] is True
    assert checkout["cleanup_complete"] is True


def test_manifest_validation_isolated_checkout_binds_toolchain_and_cleans_generated_overlays(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = _make_git_checkout(tmp_path)
    venv_bin = project / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    (venv_bin / "python").symlink_to(Path(sys.executable).resolve())
    observed_venv_targets: list[Path] = []
    original_run_command = MCPValidationRunManager._run_command

    def run_command(
        self,
        command,
        *,
        timeout_seconds,
        cwd=None,
    ):
        assert cwd is not None
        checkout = Path(cwd)
        checkout_venv = checkout / ".venv"
        assert checkout_venv.is_symlink()
        observed_venv_targets.append(checkout_venv.resolve())
        generated = checkout / ".pytest_cache"
        generated.mkdir()
        (generated / "validation-cache").write_text(
            "generated\n",
            encoding="utf-8",
        )
        return original_run_command(
            self,
            command,
            timeout_seconds=timeout_seconds,
            cwd=cwd,
        )

    monkeypatch.setattr(
        MCPValidationRunManager,
        "_run_command",
        run_command,
    )
    _manager, _run_id, final, _path = _completed_manifest_validation(
        project
    )

    assert final["status"] == "passed"
    assert observed_venv_targets == [(project / ".venv").resolve()]
    checkout = final["output_summary"]["checkout_provenance"]
    assert checkout["source_before"] == checkout["source_after"]
    assert checkout["source_binding_match"] is True
    assert checkout["cleanup_complete"] is True


def test_validation_result_status_detects_semantic_tampering_but_not_key_order(
    tmp_path: Path,
) -> None:
    project = _make_git_checkout(tmp_path)
    manager, run_id, _final, path = _completed_manifest_validation(project)
    stored = json.loads(path.read_text(encoding="utf-8"))

    reordered = dict(reversed(list(stored.items())))
    path.write_text(json.dumps(reordered), encoding="utf-8")
    verified = manager.status({"run_id": run_id})
    assert verified["ok"] is True
    assert verified["integrity_classification"] == "verified"

    reordered["output_summary"]["total_output_chars"] += 1
    path.write_text(json.dumps(reordered), encoding="utf-8")
    tampered = manager.status({"run_id": run_id})
    assert tampered["ok"] is False
    assert tampered["error_code"] == "RUN_RESULT_DIGEST_MISMATCH"
    assert tampered["integrity_classification"] == "integrity_failure"


def test_validation_result_status_enforces_closed_terminal_and_running_schemas(
    tmp_path: Path,
) -> None:
    project = _make_git_checkout(tmp_path)
    manager, run_id, _final, path = _completed_manifest_validation(project)
    terminal = json.loads(path.read_text(encoding="utf-8"))

    missing = dict(terminal)
    missing.pop("output_summary")
    path.write_text(json.dumps(missing), encoding="utf-8")
    assert manager.status({"run_id": run_id})["error_code"] == "RUN_RESULT_INVALID"

    extra = dict(terminal)
    extra["response_only"] = True
    path.write_text(json.dumps(extra), encoding="utf-8")
    assert manager.status({"run_id": run_id})["error_code"] == "RUN_RESULT_INVALID"

    invalid_contract = copy.deepcopy(terminal)
    invalid_contract["manifest_validation"]["command_specs_sha256"] = "0" * 64
    invalid_contract["validation_result_sha256"] = (
        canonical_validation_result_sha256(invalid_contract)
    )
    path.write_text(json.dumps(invalid_contract), encoding="utf-8")
    contract_status = manager.status({"run_id": run_id})
    assert contract_status["ok"] is False
    assert contract_status["error_code"] == "RUN_RESULT_INVALID"
    assert (
        contract_status["integrity_classification"]
        == "integrity_failure"
    )

    legacy = dict(terminal)
    legacy.pop("schema_version")
    legacy.pop("validation_result_sha256")
    path.write_text(json.dumps(legacy), encoding="utf-8")
    legacy_status = manager.status({"run_id": run_id})
    assert legacy_status["ok"] is False
    assert legacy_status["error_code"] == "RUN_RESULT_UNVERIFIED_LEGACY"
    assert legacy_status["integrity_classification"] == "unverified_legacy"
    assert "validation_result_sha256" not in json.loads(path.read_text(encoding="utf-8"))

    running = {
        key: value
        for key, value in terminal.items()
        if key != "validation_result_sha256"
    }
    running.update(
        {
            "status": "running",
            "passed": None,
            "command_results": [],
            "failed_command_indexes": [],
            "failed_command_index": None,
            "completed_at": None,
            "duration_seconds": None,
        }
    )
    path.write_text(json.dumps(running), encoding="utf-8")
    running_status = manager.status({"run_id": run_id})
    assert running_status["ok"] is True
    assert running_status["status"] == "running"
    assert running_status["integrity_classification"] == "non_terminal"

    running["validation_result_sha256"] = terminal["validation_result_sha256"]
    path.write_text(json.dumps(running), encoding="utf-8")
    invalid_running = manager.status({"run_id": run_id})
    assert invalid_running["ok"] is False
    assert invalid_running["error_code"] == "RUN_RESULT_INVALID"
    assert invalid_running["integrity_classification"] == "integrity_failure"


def test_validation_result_status_binds_intrinsic_run_identity_and_action(
    tmp_path: Path,
) -> None:
    project = _make_git_checkout(tmp_path)
    manager, run_id, _final, path = _completed_manifest_validation(project)
    terminal = json.loads(path.read_text(encoding="utf-8"))

    alias_run_id = "validation_run_alias_123"
    alias_path = path.with_name(f"{alias_run_id}.json")
    alias_path.write_bytes(path.read_bytes())
    aliased = manager.status({"run_id": alias_run_id})
    assert aliased["ok"] is False
    assert aliased["error_code"] == "RUN_RESULT_INVALID"
    assert aliased["integrity_classification"] == "integrity_failure"

    for field, value in (
        ("run_id", f" {run_id} "),
        ("preview_id", None),
        ("preview_id", f" {terminal['preview_id']} "),
        ("preview_id", "invalid/preview"),
        ("action", "inspect"),
    ):
        invalid = copy.deepcopy(terminal)
        invalid[field] = value
        invalid["validation_result_sha256"] = (
            canonical_validation_result_sha256(invalid)
        )
        path.write_text(json.dumps(invalid), encoding="utf-8")
        status = manager.status({"run_id": run_id})
        assert status["ok"] is False
        assert status["error_code"] == "RUN_RESULT_INVALID"
        assert status["integrity_classification"] == "integrity_failure"


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


@pytest.mark.parametrize(
    "command",
    [
        'sh -c "rm -rf /some/path"',
        'bash -c "echo bypass"',
        'python3 -c "print(1)"',
        '.venv/bin/python -c "print(1)"',
        'node -e "console.log(1)"',
        'env sh -c "echo bypass"',
        ".venv/bin/python -m pytest --rootdir=/tmp",
        "python3 -m compileall --invalidation-mode checked-hash runner",
        ".venv/bin/python -m ruff check --config=/tmp/ruff.toml runner",
    ],
)
def test_manifest_validation_rejects_command_indirection(
    tmp_path: Path,
    command: str,
) -> None:
    project = _make_git_checkout(tmp_path)
    server = MCPPlanningBridgeServer(str(project))
    manifest = _manifest(project)
    manifest["acceptance_commands"] = [
        {
            "command": command,
            "timeout_seconds": 60,
        }
    ]
    inspected = server.call_tool_for_agent(
        "run_mcp_workflow",
        {
            "workflow": "review_manifest",
            "phase": "inspect",
            "review_manifest": manifest,
        },
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
    assert preview["data"]["can_run"] is False
    assert preview["data"]["blockers"] == [
        "MANIFEST_VALIDATION_COMMAND_REJECTED"
    ]
    assert preview["data"]["manifest_validation_rejections"] == [
        {
            "command_index": 1,
            "reason": "command_not_allowed",
        }
    ]


def test_manifest_validation_accepts_only_supported_command_families(
    tmp_path: Path,
) -> None:
    project = _make_git_checkout(tmp_path)
    server = MCPPlanningBridgeServer(str(project))
    manifest = _manifest(project)
    manifest["acceptance_commands"] = [
        {
            "command": ".venv/bin/python -m pytest -q",
            "timeout_seconds": 900,
        },
        {
            "command": ".venv/bin/python scripts/self_hosting_smoke.py",
            "timeout_seconds": 900,
        },
        {
            "command": (
                ".venv/bin/python -m compileall -q "
                "adapters runner schemas scripts tests"
            ),
            "timeout_seconds": 600,
        },
        {
            "command": (
                ".venv/bin/python -m ruff check "
                "adapters runner schemas scripts tests"
            ),
            "timeout_seconds": 600,
        },
        {
            "command": "git diff --check",
            "timeout_seconds": 600,
        },
    ]
    inspected = server.call_tool_for_agent(
        "run_mcp_workflow",
        {
            "workflow": "review_manifest",
            "phase": "inspect",
            "review_manifest": manifest,
        },
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
    assert preview["data"]["can_run"] is True
    assert preview["data"]["command_count"] == 5
    assert preview["data"]["manifest_validation_rejections"] == []


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


def test_commander_mcp_surface_keeps_review_manifest_continuation_handles(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "runner.review_manifest.secrets.token_urlsafe",
        lambda _length: "review_manifest_handle_ending_",
    )
    project = _make_git_checkout(tmp_path)
    uri = (
        "colameta://review-manifest/opaque_handle_123_"
        "/subjects/1/pages/{page}"
    )
    combining_mark_prose_json = json.dumps(
        {"note": f"नमस्ते{uri}; مُرَاجَعَةَ{uri}; cafe\u0301{uri}"}
    )
    escaped_space_json = json.dumps({"note": f"{uri}\\u0020Next"})
    zero_width_space_json = json.dumps({"note": f"{uri}\u200bNext"})
    bom_prefix_json = json.dumps({"note": f"\ufeff{uri}"})
    short_escape_left_boundary = json.dumps(
        {"content": f"\n{uri}"}
    )
    nested_short_escape_left_boundary = json.dumps(
        {"nested": json.dumps({"content": f"\t{uri}"})}
    )
    dash_boundaries = f"before—{uri}–continue"
    serialized_dash_boundaries = json.dumps(
        {"note": dash_boundaries}
    )
    paired_punctuation_boundaries = (
        f"before」{uri}「continue; before”{uri}“continue"
    )
    serialized_paired_punctuation_boundaries = json.dumps(
        {"note": f"before）{uri}（continue"}
    )
    ascii_opening_boundaries = (
        f"{uri}(see page 2); {uri}[details]; "
        f"{uri}{{details}}; {uri}<details>"
    )
    escaped_ascii_opening_boundaries = (
        f"{uri}\\u0028see page 2\\u0029; "
        f"{uri}\\u005bdetails\\u005d; "
        f"{uri}\\u007bdetails\\u007d; "
        f"{uri}\\u003cdetails\\u003e"
    )
    content = (
        f"\ufeff{uri}\n"
        f"\\ufeff{uri}\n"
        f"{bom_prefix_json}\n"
        f"请读取{uri}。\n"
        f"Read {uri}。Next\n"
        f"📎{uri}✅Next\n"
        f"请读取{uri}继续\n"
        f"❤️{uri}👩‍💻Next\n"
        f"1️⃣{uri}#️⃣Next\n"
        f"↔️{uri}〰️Next\n"
        f"Read {uri}✅,Next\n"
        f"Read {uri}」.Next\n"
        f"नमस्ते{uri}\n"
        f"مُرَاجَعَةَ{uri}\n"
        f"cafe\u0301{uri}\n"
        "safe\\/relative.txt\n"
        "1\\/2\n"
        "https:\\/\\/example.com\n"
        f"Read {uri}\\u0020Next\n"
        f"{escaped_space_json}\n"
        f"Read {uri}\u200bNext\n"
        f"Read {uri}\\u200bNext\n"
        f"{zero_width_space_json}\n"
        f"{short_escape_left_boundary}\n"
        f"{nested_short_escape_left_boundary}\n"
        f"{dash_boundaries}\n"
        f"{serialized_dash_boundaries}\n"
        f"{paired_punctuation_boundaries}\n"
        f"{serialized_paired_punctuation_boundaries}\n"
        f"{ascii_opening_boundaries}\n"
        f"{escaped_ascii_opening_boundaries}\n"
        f"{json.dumps({'nested': json.dumps({'uri': uri})})}\n"
        f"{json.dumps({'note': f'取{uri}继续'})}\n"
        f"{json.dumps({'note': f'📎{uri}✅Next'})}\n"
        f"{json.dumps({'note': f'❤️{uri}👩‍💻Next'})}\n"
        f"{json.dumps({'note': f'1️⃣{uri}#️⃣Next'})}\n"
        f"{json.dumps({'note': f'↔️{uri}〰️Next'})}\n"
        f"{json.dumps({'note': f'{uri}✅,Next; {uri}」.Next'})}\n"
        f"{combining_mark_prose_json}\n"
    )
    (project / "docs" / "review-input.md").write_text(content, encoding="utf-8")
    server = MCPPlanningBridgeServer(str(project), exposure_profile="commander")

    response = _tool_call(
        server,
        {"workflow": "review_manifest", "phase": "inspect", "review_manifest": _manifest(project)},
    )

    structured = response["result"]["structuredContent"]
    assert structured["ok"] is True
    contract = structured["data"]
    assert contract["schema_version"] == "commander_response.v1"
    assert contract["outcome"] == "completed"
    evidence = contract["evidence"]
    facts = contract["facts"]
    assert evidence["review_manifest_id"]
    assert evidence["resource_uri"].startswith("colameta://review-manifest/")
    assert facts["subjects"][0]["resource_uri"].startswith("colameta://review-manifest/")
    assert facts["subjects"][0]["page_uri_template"] == (
        "colameta://review-manifest/review_manifest_handle_ending_"
        "/subjects/1/pages/{page}"
    )
    manifest_resource = _resource_read(server, evidence["resource_uri"])
    manifest_summary = json.loads(
        manifest_resource["result"]["contents"][0]["text"]
    )
    assert manifest_summary["review_manifest_id"] == evidence[
        "review_manifest_id"
    ]
    read = _tool_call(
        server,
        {
            "workflow": "review_manifest",
            "phase": "read",
            "review_manifest_id": evidence["review_manifest_id"],
            "review_manifest_subject_index": 1,
        },
    )
    read_structured = read["result"]["structuredContent"]
    assert read_structured["ok"] is True
    assert read_structured["data"]["facts"]["subject_page"]["content"] == content

    resource = _resource_read(server, facts["subjects"][0]["resource_uri"])
    resource_page = json.loads(resource["result"]["contents"][0]["text"])
    assert resource_page["content"] == content


def test_commander_resources_read_validates_whole_subject_before_paging(
    tmp_path: Path,
) -> None:
    project = _make_git_checkout(tmp_path)
    resource_uri = (
        "colameta://review-manifest/opaque_handle_123_"
        "/subjects/1/pages/{page}"
    )
    uri_start = REVIEW_MANIFEST_PAGE_CHARS - (len(resource_uri) // 2)
    content = f"{'x' * (uri_start - 1)} {resource_uri}\n"
    assert content.index(resource_uri) < REVIEW_MANIFEST_PAGE_CHARS
    assert (
        content.index(resource_uri) + len(resource_uri)
        > REVIEW_MANIFEST_PAGE_CHARS
    )
    (project / "docs" / "review-input.md").write_text(content, encoding="utf-8")
    server = MCPPlanningBridgeServer(str(project), exposure_profile="commander")

    inspected = _tool_call(
        server,
        {
            "workflow": "review_manifest",
            "phase": "inspect",
            "review_manifest": _manifest(project),
        },
    )
    inspection_data = inspected["result"]["structuredContent"]["data"]
    descriptor = inspection_data["facts"]["subjects"][0]
    assert descriptor["page_count"] == 2

    typed_pages: list[str] = []
    pages: list[str] = []
    for page_number in (1, 2):
        typed = server.call_tool_for_agent(
            "review_manifest",
            {
                "phase": "read",
                "review_manifest_id": inspection_data["evidence"][
                    "review_manifest_id"
                ],
                "review_manifest_subject_index": 1,
                "review_manifest_page": page_number,
            },
        )
        assert typed["ok"] is True
        typed_contract = typed["data"]
        validate_commander_response(
            typed_contract,
            exact_evidence_prevalidated=True,
        )
        typed_page = typed_contract["facts"]["subject_page"]
        assert typed_page["page"] == page_number
        typed_pages.append(typed_page["content"])

        response = _resource_read(
            server,
            f"{descriptor['resource_uri']}/pages/{page_number}",
        )
        assert "error" not in response
        page = json.loads(response["result"]["contents"][0]["text"])
        assert page["page"] == page_number
        pages.append(page["content"])

    assert pages[0] == content[:REVIEW_MANIFEST_PAGE_CHARS]
    assert pages[1] == content[REVIEW_MANIFEST_PAGE_CHARS:]
    assert typed_pages == pages
    assert "".join(pages) == content


def test_commander_resources_read_rejects_unsafe_whole_subject_across_pages(
    tmp_path: Path,
) -> None:
    project = _make_git_checkout(tmp_path)
    unsafe_uri = "Colameta://review-manifest/opaque_handle_123_"
    uri_start = REVIEW_MANIFEST_PAGE_CHARS - (len(unsafe_uri) // 2)
    content = f"{'x' * (uri_start - 1)} {unsafe_uri}\n"
    assert content.index(unsafe_uri) < REVIEW_MANIFEST_PAGE_CHARS
    assert content.index(unsafe_uri) + len(unsafe_uri) > REVIEW_MANIFEST_PAGE_CHARS
    (project / "docs" / "review-input.md").write_text(content, encoding="utf-8")
    server = MCPPlanningBridgeServer(str(project), exposure_profile="commander")

    inspected = _tool_call(
        server,
        {
            "workflow": "review_manifest",
            "phase": "inspect",
            "review_manifest": _manifest(project),
        },
    )
    descriptor = inspected["result"]["structuredContent"]["data"]["facts"][
        "subjects"
    ][0]
    review_manifest_id = inspected["result"]["structuredContent"]["data"][
        "evidence"
    ]["review_manifest_id"]
    assert descriptor["page_count"] == 2

    for page_number in (1, 2):
        typed = server.call_tool_for_agent(
            "review_manifest",
            {
                "phase": "read",
                "review_manifest_id": review_manifest_id,
                "review_manifest_subject_index": 1,
                "review_manifest_page": page_number,
            },
        )
        assert typed["ok"] is False
        assert typed["data"]["outcome"] == "blocked"
        assert typed["data"]["error"]["code"] == "EVIDENCE_UNAVAILABLE"
        assert unsafe_uri not in json.dumps(typed, ensure_ascii=False)

        response = _resource_read(
            server,
            f"{descriptor['resource_uri']}/pages/{page_number}",
        )
        assert response["error"]["data"]["error_code"] == "evidence_unavailable"
        assert unsafe_uri not in json.dumps(response, ensure_ascii=False)


def test_commander_resources_read_caches_whole_subject_safety_by_hash(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = _make_git_checkout(tmp_path)
    content = (
        '{"content":"'
        + ("\\" * (REVIEW_MANIFEST_PAGE_CHARS * 2))
        + 'relative.txt"}\n'
    )
    (project / "docs" / "review-input.md").write_text(content, encoding="utf-8")
    server = MCPPlanningBridgeServer(str(project), exposure_profile="commander")
    inspected = _tool_call(
        server,
        {
            "workflow": "review_manifest",
            "phase": "inspect",
            "review_manifest": _manifest(project),
        },
    )
    descriptor = inspected["result"]["structuredContent"]["data"]["facts"][
        "subjects"
    ][0]
    assert descriptor["page_count"] == 3

    scans = 0
    original_safety = (
        server._commander_public_review_manifest_content_safety
    )

    def counting_safety(value: str) -> bool:
        nonlocal scans
        scans += 1
        return original_safety(value)

    monkeypatch.setattr(
        server,
        "_commander_public_review_manifest_content_safety",
        counting_safety,
    )

    pages: list[str] = []
    for page_number in range(1, descriptor["page_count"] + 1):
        response = _resource_read(
            server,
            f"{descriptor['resource_uri']}/pages/{page_number}",
        )
        assert "error" not in response
        page = json.loads(response["result"]["contents"][0]["text"])
        pages.append(page["content"])
    repeated = _resource_read(
        server,
        f"{descriptor['resource_uri']}/pages/1",
    )

    assert "error" not in repeated
    assert "".join(pages) == content
    assert scans == 1
    assert list(
        server._commander_public_review_manifest_safety_cache
    ) == [descriptor["sha256"]]


def test_commander_concurrent_resource_reads_share_one_manifest_safety_scan(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = _make_git_checkout(tmp_path)
    content = (
        '{"content":"'
        + ("\\" * (REVIEW_MANIFEST_PAGE_CHARS * 2))
        + 'relative.txt"}\n'
    )
    (project / "docs" / "review-input.md").write_text(
        content,
        encoding="utf-8",
    )
    server = MCPPlanningBridgeServer(
        str(project),
        exposure_profile="commander",
    )
    inspected = _tool_call(
        server,
        {
            "workflow": "review_manifest",
            "phase": "inspect",
            "review_manifest": _manifest(project),
        },
    )
    descriptor = inspected["result"]["structuredContent"]["data"]["facts"][
        "subjects"
    ][0]
    assert descriptor["page_count"] == 3

    waiter_entered = threading.Event()

    class ObservedFuture(Future):
        def result(self, timeout=None):
            waiter_entered.set()
            return super().result(timeout=timeout)

    monkeypatch.setattr(mcp_server_module, "Future", ObservedFuture)

    scan_entered = threading.Event()
    release_scan = threading.Event()
    scan_lock = threading.Lock()
    scans = 0
    original_safety = (
        server._commander_public_review_manifest_content_safety
    )

    def blocking_safety(value: str) -> bool:
        nonlocal scans
        with scan_lock:
            scans += 1
        scan_entered.set()
        assert release_scan.wait(timeout=5)
        return original_safety(value)

    monkeypatch.setattr(
        server,
        "_commander_public_review_manifest_content_safety",
        blocking_safety,
    )

    def read_page(page: int) -> dict:
        return _resource_read(
            server,
            f"{descriptor['resource_uri']}/pages/{page}",
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(read_page, 1)
        assert scan_entered.wait(timeout=5)
        second = pool.submit(read_page, 2)
        try:
            assert waiter_entered.wait(timeout=5)
            assert scans == 1
        finally:
            release_scan.set()
        responses = [first.result(timeout=5), second.result(timeout=5)]

    assert all("error" not in response for response in responses)
    assert scans == 1
    assert not server._commander_public_review_manifest_safety_inflight
    assert list(
        server._commander_public_review_manifest_safety_cache
    ) == [descriptor["sha256"]]


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
    assert result["error_code"] == "PROJECT_CONTEXT_MISMATCH"
    assert result["data"]["outcome"] == "blocked"
    assert result["data"]["error"]["code"] == "PROJECT_CONTEXT_MISMATCH"
    assert "details" not in result
    assert actual_head not in repr(result)


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


def test_typed_review_manifest_tool_keeps_the_same_bound_read_and_verify_contract(tmp_path: Path) -> None:
    project = _make_git_checkout(tmp_path)
    server = MCPPlanningBridgeServer(str(project), exposure_profile="commander")

    tools = {tool.name: tool for tool in server._filter_tools_by_exposure_profile(server.tool_defs)}
    assert "review_manifest" in tools
    assert "workflow" not in tools["review_manifest"].input_schema["properties"]
    assert tools["review_manifest"].annotations["readOnlyHint"] is True
    assert server.get_required_scope_for_tool("review_manifest", {"phase": "inspect"}) == "mcp:read"

    template = server.call_tool_for_agent("review_manifest", {"phase": "inspect"})
    assert template["ok"] is True
    assert template["data"]["outcome"] == "completed"
    assert template["data"]["facts"]["status"] == "template_ready"

    inspected = server.call_tool_for_agent(
        "review_manifest",
        {"phase": "inspect", "review_manifest": _manifest(project)},
    )
    assert inspected["ok"] is True
    contract = inspected["data"]
    data = contract["facts"]
    manifest_id = contract["evidence"]["review_manifest_id"]
    descriptor = data["subjects"][0]
    assert contract["next_action"] == {
        "tool": "review_manifest",
        "arguments": {
            "phase": "read",
            "review_manifest_id": manifest_id,
            "review_manifest_subject_index": 1,
            "review_manifest_page": 1,
        },
        "reason": "通过 ChatGPT 可调用的 review_manifest 读取同一绑定下的第 1 个 subject 第 1 页；上下文和 SHA-256 会复核。",
    }
    assert descriptor["read_call"] == {
        "tool": "review_manifest",
        "arguments": {
            "phase": "read",
            "review_manifest_id": manifest_id,
            "review_manifest_subject_index": 1,
            "review_manifest_page": 1,
        },
    }

    read = server.call_tool_for_agent("review_manifest", descriptor["read_call"]["arguments"])
    assert read["ok"] is True
    assert read["data"]["facts"]["verification"] == {
        "context_binding": "matched",
        "subject_hash": "matched",
        "subject_index": 1,
    }
    assert read["data"]["facts"]["read_call"]["tool"] == "review_manifest"

    verified = server.call_tool_for_agent(
        "review_manifest",
        {"phase": "verify", "review_manifest_id": manifest_id},
    )
    assert verified["ok"] is True
    assert verified["data"]["facts"]["verification"]["context_binding"] == "matched"
    assert verified["data"]["facts"]["verification"]["subject_hashes"] == "matched"

    (project / "docs" / "review-input.md").write_text(
        "changed after Commander inspect\n",
        encoding="utf-8",
    )
    changed_subject = server.call_tool_for_agent(
        "review_manifest",
        {"phase": "verify", "review_manifest_id": manifest_id},
    )
    assert changed_subject["ok"] is False
    assert changed_subject["error_code"] == "STALE_CONTEXT"
    assert changed_subject["data"]["outcome"] == "blocked"
    assert changed_subject["data"]["error"]["code"] == "STALE_CONTEXT"


def test_commander_manifest_resource_read_maps_subject_drift_to_stale_context(
    tmp_path: Path,
) -> None:
    project = _make_git_checkout(tmp_path)
    server = MCPPlanningBridgeServer(
        str(project),
        exposure_profile="commander",
    )
    inspected = server.call_tool_for_agent(
        "review_manifest",
        {
            "phase": "inspect",
            "review_manifest": _manifest(project),
        },
    )
    subject_uri = inspected["data"]["facts"]["subjects"][0]["resource_uri"]
    (project / "docs" / "review-input.md").write_text(
        "changed after Commander inspect\n",
        encoding="utf-8",
    )

    response = _resource_read(server, subject_uri)

    assert response["error"]["data"]["error_code"] == "STALE_CONTEXT"
    assert "REVIEW_MANIFEST_SUBJECT_HASH_MISMATCH" not in repr(response)


def test_typed_review_manifest_tool_routes_registered_service_projects(tmp_path: Path) -> None:
    project = _make_git_checkout(tmp_path)
    registry = ProjectRegistry(
        registry_path=str(tmp_path / "registry.json"),
        user_settings_path=str(tmp_path / "settings.json"),
    )
    registered = registry.register_project(str(project), project_name="review-target")
    assert registered["ok"] is True
    server = MCPPlanningBridgeServer(str(tmp_path), service_mode=True, exposure_profile="commander")
    server.project_registry = registry

    missing_project = server.call_tool_for_agent("review_manifest", {"phase": "inspect"})
    assert missing_project["ok"] is False
    assert missing_project["error_code"] == "PROJECT_REQUIRED"

    inspected = server.call_tool_for_agent(
        "review_manifest",
        {
            "phase": "inspect",
            "project_name": "review-target",
            "review_manifest": _manifest(project, project_name="review-target"),
        },
    )
    assert inspected["ok"] is True
    contract = inspected["data"]
    assert contract["context_binding"]["project_name"] == "review-target"
    read_call = contract["facts"]["subjects"][0]["read_call"]
    assert read_call["tool"] == "review_manifest"
    assert read_call["arguments"]["project_name"] == "review-target"

    read = server.call_tool_for_agent("review_manifest", read_call["arguments"])
    assert read["ok"] is True
    assert read["data"]["facts"]["subject_page"]["path"] == "docs/review-input.md"


def test_commander_manifest_read_rejects_private_path_content(tmp_path: Path) -> None:
    project = _make_git_checkout(tmp_path)
    content = "Literal source text: /home/reviewer/example.md\n"
    (project / "docs" / "review-input.md").write_text(content, encoding="utf-8")
    server = MCPPlanningBridgeServer(str(project), exposure_profile="commander")

    inspected = _tool_call(
        server,
        {"workflow": "review_manifest", "phase": "inspect", "review_manifest": _manifest(project)},
    )
    inspection_data = inspected["result"]["structuredContent"]["data"]
    manifest_id = inspection_data["evidence"]["review_manifest_id"]
    read = _tool_call(
        server,
        {
            "workflow": "review_manifest",
            "phase": "read",
            "review_manifest_id": manifest_id,
            "review_manifest_subject_index": 1,
        },
    )
    structured = read["result"]["structuredContent"]
    contract = structured["data"]
    assert structured["ok"] is False
    assert contract["outcome"] == "blocked"
    assert contract["error"]["code"] == "EVIDENCE_UNAVAILABLE"
    assert "/home/reviewer" not in json.dumps(structured, ensure_ascii=False)


@pytest.mark.parametrize(
    "unsafe_uri",
    [
        (
            "colameta://review-manifest/opaque_handle_123_"
            "/subjects/1/pages/{page}??）query"
        ),
        (
            "colameta://review-manifest/opaque_handle_123_"
            "/subjects/1/pages/{page}(/home/reviewer/private.txt)"
        ),
        (
            "colameta://review-manifest/opaque_handle_123_"
            "/subjects/1/pages/{page}∕private"
        ),
        (
            "colameta://review-manifest/opaque_handle_123_"
            "/subjects/1/pages/{page}\\u2215private"
        ),
        (
            "colameta://review-manifest/opaque_handle_123_"
            "/subjects/1/pages/{page}.\\n/home/reviewer/private.txt"
        ),
        (
            "colameta://review-manifest/opaque_handle_123_"
            "/subjects/1/pages/{page}.\\u000a/home/reviewer/private.txt"
        ),
        (
            "colameta://review-manifest/opaque_handle_123_"
            "/subjects/1/pages/{page}.\\n\\u002fhome/reviewer/private.txt"
        ),
        (
            "colameta://review-manifest/opaque_handle_123_"
            "/subjects/1/pages/{page}.\\nC:\\u005cUsers"
            "\\u005cReviewer\\u005cprivate.txt"
        ),
        '{"reason":"\\u002fhome/reviewer/private.txt"}',
        '{"reason":"\\u005cu002fhome/reviewer/private.txt"}',
        r"\\server/share\private.txt",
        "//server/share/private.txt",
        "///server/share/private.txt",
        json.dumps({"reason": r"\\server/share\private.txt"}),
        json.dumps({"reason": r"\\server\share\private.txt"}),
        json.dumps({"reason": "//server/share/private.txt"}),
        json.dumps(
            {
                "nested": json.dumps(
                    {"reason": "//server/share/private.txt"}
                )
            }
        ),
        '{"reason":"\\/\\/server\\/share\\/private.txt"}',
        (
            '{"reason":"\\u002f\\u002fserver\\u002fshare'
            '\\u002fprivate.txt"}'
        ),
        (
            '{"reason":"safe C:\\u005cUsers\\u005cReviewer'
            '\\u005cprivate.txt"}'
        ),
        "C:/Users/Reviewer/private.txt",
        r"C:/Users\Reviewer/private.txt",
        '{"reason":"C:\\u002fUsers\\u002fReviewer\\u002fprivate.txt"}',
        '{"oauth\\u005ftoken":"synthetic-secret-value"}',
        'password="alpha beta gamma"',
        r'{\"client_secret\":\"alpha beta gamma\"}',
        "Authorization: Basic dXNlcjpwYXNzd29yZA==",
        "Basic dXNlcjpwYXNzd29yZA==",
        (
            '{"reason":"Authorization: '
            '\\u0042asic dXNlcjpwYXNzd29yZA=="}'
        ),
        '{"reason":"\\u0042asic dXNlcjpwYXNzd29yZA=="}',
        "Cookie: session=abc; csrf=def",
        (
            'Authorization: Digest username="Mufasa", '
            'response="deadbeef"'
        ),
        r'{\"Cookie\":\"session=abc; csrf=def\"}',
        (
            '{"reason":"Authorization: \\u0044igest '
            'username=\\"Mufasa\\", response=\\"deadbeef\\""}'
        ),
        '{"reason":"\\u0042earer abcdefghijklmnop"}',
        '{"reason":"manage\\u005ffiles"}',
        json.dumps(
            {"reason": '{"tool":"manage\\u005fexecutor\\u005fworkflow"}'}
        ),
        '{"uri":"colameta:\\/\\/review-manifest\\/short"}',
        (
            '{"uri":"colameta:\\u002f\\u002freview-manifest'
            '\\u002fshort"}'
        ),
        "Colameta://review-manifest/opaque_handle_123_",
        (
            '{"uri":"Colameta:\\/\\/review-manifest\\/'
            'opaque_handle_123_"}'
        ),
        (
            '{"uri":"COLAMETA:\\u002f\\u002freview-manifest'
            '\\u002fopaque_handle_123_"}'
        ),
        (
            "colameta://review-manifest/opaque_handle_123_"
            "/subjects/1/pages/{page}\\u0020Colameta:\\u002f\\u002f"
            "result-artifact\\u002fshort"
        ),
        json.dumps(
            {
                "note": (
                    "colameta://review-manifest/opaque_handle_123_"
                    "/subjects/1/pages/{page}\\u0020"
                    "Colameta:\\u002f\\u002fresult-artifact\\u002fshort"
                )
            }
        ),
    ],
)
def test_commander_manifest_read_rejects_unsafe_uri_boundaries(
    tmp_path: Path,
    unsafe_uri: str,
) -> None:
    project = _make_git_checkout(tmp_path)
    (project / "docs" / "review-input.md").write_text(
        f"{unsafe_uri}\n",
        encoding="utf-8",
    )
    server = MCPPlanningBridgeServer(str(project), exposure_profile="commander")

    inspected = _tool_call(
        server,
        {
            "workflow": "review_manifest",
            "phase": "inspect",
            "review_manifest": _manifest(project),
        },
    )
    inspection_data = inspected["result"]["structuredContent"]["data"]
    subject_resource_uri = inspection_data["facts"]["subjects"][0][
        "resource_uri"
    ]
    read = _tool_call(
        server,
        {
            "workflow": "review_manifest",
            "phase": "read",
            "review_manifest_id": inspection_data["evidence"]["review_manifest_id"],
            "review_manifest_subject_index": 1,
        },
    )

    structured = read["result"]["structuredContent"]
    assert structured["ok"] is False
    assert structured["data"]["outcome"] == "blocked"
    assert structured["data"]["error"]["code"] == "EVIDENCE_UNAVAILABLE"
    assert unsafe_uri not in json.dumps(structured, ensure_ascii=False)

    resource = _resource_read(server, subject_resource_uri)
    assert resource["error"]["data"]["error_code"] == "evidence_unavailable"
    assert unsafe_uri not in json.dumps(resource, ensure_ascii=False)


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
