from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
import copy
from dataclasses import replace
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

import runner.mcp_review_manifest as mcp_review_manifest_module
import runner.mcp_server as mcp_server_module
from runner.commander_contract import (
    COMMANDER_PUBLIC_MAX_DEPTH,
    validate_commander_response,
)
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


def _percent_encode_layers(value: str, layers: int) -> str:
    encoded = value
    for _ in range(layers):
        encoded = "".join(
            character
            if character.isalnum()
            else f"%{ord(character):02X}"
            for character in encoded
        )
    return encoded


def _nest_json_containers(value: object) -> object:
    nested = value
    for _ in range(COMMANDER_PUBLIC_MAX_DEPTH + 1):
        nested = {"layer": nested}
    return nested


SYNTHETIC_JWT = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJzdWIiOiJzeW50aGV0aWMtdXNlciIsInNjb3BlIjoicmVhZCJ9."
    "c3ludGhldGljLXNpZ25hdHVyZS1ieXRlcw"
)
ESCAPED_SYNTHETIC_JWT = SYNTHETIC_JWT.replace(".", "\\u002e")
SYNTHETIC_AGE_X25519_IDENTITY = (
    "AGE-SECRET-KEY-1" + ("Q" * 58)
)
ESCAPED_SYNTHETIC_AGE_X25519_IDENTITY = (
    SYNTHETIC_AGE_X25519_IDENTITY.replace(
        "AGE-SECRET-KEY-",
        "\\u0041GE-SECRET-KEY-",
    )
)
SYNTHETIC_GITHUB_PAT = "ghp_" + ("A1" * 18)
SYNTHETIC_HUGGING_FACE_TOKEN = "hf_" + ("A1" * 17)
ESCAPED_SYNTHETIC_HUGGING_FACE_TOKEN = (
    SYNTHETIC_HUGGING_FACE_TOKEN.replace("hf_", "\\u0068f_")
)
SYNTHETIC_DIGITALOCEAN_TOKEN = "dop_v1_" + ("a1" * 32)
ESCAPED_SYNTHETIC_DIGITALOCEAN_TOKEN = (
    SYNTHETIC_DIGITALOCEAN_TOKEN.replace(
        "dop_v1_",
        "\\u0064op_v1_",
    )
)
SYNTHETIC_DATABRICKS_PAT = "dapi" + ("a1" * 16)
ESCAPED_SYNTHETIC_DATABRICKS_PAT = SYNTHETIC_DATABRICKS_PAT.replace(
    "dapi",
    "\\u0064api",
)
SYNTHETIC_VAULT_SERVICE_TOKEN = "hvs." + ("A1" * 12)
SYNTHETIC_VAULT_BATCH_TOKEN = "hvb." + ("B2" * 12)
SYNTHETIC_VAULT_RECOVERY_TOKEN = "hvr." + ("C3" * 12)
ESCAPED_SYNTHETIC_VAULT_SERVICE_TOKEN = (
    SYNTHETIC_VAULT_SERVICE_TOKEN.replace("hvs.", "\\u0068vs\\u002e")
)
SYNTHETIC_ONEPASSWORD_SERVICE_ACCOUNT_TOKEN = "ops_" + ("Ab1_" * 16)
ESCAPED_SYNTHETIC_ONEPASSWORD_SERVICE_ACCOUNT_TOKEN = (
    SYNTHETIC_ONEPASSWORD_SERVICE_ACCOUNT_TOKEN.replace(
        "ops_",
        "\\u006fps\\u005f",
    )
)
SYNTHETIC_SHOPIFY_ACCESS_TOKEN = "shpat_" + ("a1" * 16)
ESCAPED_SYNTHETIC_SHOPIFY_ACCESS_TOKEN = (
    SYNTHETIC_SHOPIFY_ACCESS_TOKEN.replace(
        "shpat_",
        "\\u0073hpat_",
    )
)
ESCAPED_SYNTHETIC_GITHUB_PAT = SYNTHETIC_GITHUB_PAT.replace(
    "ghp_",
    "\\u0067hp_",
)
SYNTHETIC_NPM_ACCESS_TOKEN = "npm_" + ("A1" * 18)
ESCAPED_SYNTHETIC_NPM_ACCESS_TOKEN = (
    SYNTHETIC_NPM_ACCESS_TOKEN.replace(
        "npm_",
        "\\u006epm_",
    )
)
SYNTHETIC_DOCKER_PAT = "dckr_pat_" + (("Ab1_-" * 5) + "Z9")
ESCAPED_SYNTHETIC_DOCKER_PAT = SYNTHETIC_DOCKER_PAT.replace(
    "dckr_pat_",
    "\\u0064ckr_pat_",
)
SYNTHETIC_PYPI_API_TOKEN = "pypi-" + ("Ab1_-" * 17)
SYNTHETIC_LONG_PYPI_API_TOKEN = "pypi-" + ("B2" * 160)
ESCAPED_SYNTHETIC_PYPI_API_TOKEN = (
    SYNTHETIC_PYPI_API_TOKEN.replace(
        "pypi-",
        "\\u0070ypi-",
    )
)
SYNTHETIC_SENDGRID_API_KEY = (
    f"SG.{'A' * 22}.{'B' * 43}"
)
TOKEN_LIKE_OPAQUE_ID = "sk-" + ("R" * 29)
ESCAPED_SYNTHETIC_SENDGRID_API_KEY = (
    SYNTHETIC_SENDGRID_API_KEY.replace(".", "\\u002e")
)
SYNTHETIC_GITLAB_PAT = "glpat-" + ("A1" * 10)
ESCAPED_SYNTHETIC_GITLAB_PAT = SYNTHETIC_GITLAB_PAT.replace(
    "glpat-",
    "\\u0067lpat-",
)
SYNTHETIC_GOOGLE_API_KEY = "AIza" + ("Ab1_-" * 7)
ESCAPED_SYNTHETIC_GOOGLE_API_KEY = SYNTHETIC_GOOGLE_API_KEY.replace(
    "AIza",
    "\\u0041Iza",
)
SYNTHETIC_GOOGLE_OAUTH_CLIENT_SECRET = (
    "GOCSPX-" + ("Ab1_-" * 5) + "Z9Q"
)
ESCAPED_SYNTHETIC_GOOGLE_OAUTH_CLIENT_SECRET = (
    SYNTHETIC_GOOGLE_OAUTH_CLIENT_SECRET.replace(
        "GOCSPX-",
        "\\u0047OCSPX-",
    )
)
SYNTHETIC_AWS_ACCESS_KEY_ID = "AKIA" + ("A1" * 8)
SYNTHETIC_AWS_TEMPORARY_ACCESS_KEY_ID = "ASIA" + ("B2" * 8)
ESCAPED_SYNTHETIC_AWS_ACCESS_KEY_ID = (
    SYNTHETIC_AWS_ACCESS_KEY_ID.replace(
        "AKIA",
        "\\u0041KIA",
    )
)
SYNTHETIC_STRIPE_SECRET_KEY = "sk_live_" + ("A1" * 12)
SYNTHETIC_STRIPE_RESTRICTED_KEY = "rk_test_" + ("B2" * 12)
SYNTHETIC_STRIPE_WEBHOOK_SECRET = "whsec_" + ("C3_" * 16)
ESCAPED_SYNTHETIC_STRIPE_SECRET_KEY = (
    SYNTHETIC_STRIPE_SECRET_KEY.replace(
        "sk_live_",
        "\\u0073k_live_",
    )
)
SYNTHETIC_SLACK_TOKEN = (
    "xoxb-123456789012-123456789012-" + ("Ab" * 24)
)
SYNTHETIC_SLACK_WEBHOOK_URL = (
    "https://hooks.slack.com/services/"
    "T0123456789/B1001010101/7IsoQTrixdUtE971O1xQTm4T"
)
SYNTHETIC_DISCORD_WEBHOOK_URL = (
    "https://discord.com/api/webhooks/123456789012345678/"
    + ("Ab1_" * 16)
)
ESCAPED_SYNTHETIC_SLACK_TOKEN = SYNTHETIC_SLACK_TOKEN.replace(
    "xoxb-",
    "\\u0078oxb-",
)
SYNTHETIC_OPENAI_PROJECT_KEY = "sk-proj-" + ("Ab1_" * 24)
ESCAPED_SYNTHETIC_OPENAI_PROJECT_KEY = (
    SYNTHETIC_OPENAI_PROJECT_KEY.replace(
        "sk-proj-",
        "\\u0073k-proj-",
    )
)
MAX_BUDGET_PERCENT_ENCODED_SAFE_PROSE = _percent_encode_layers(
    "public_key=visible",
    15,
)
EXHAUSTING_PERCENT_ENCODED_SAFE_PROSE = _percent_encode_layers(
    "public_key=visible",
    16,
)
EXHAUSTING_PERCENT_ENCODED_SENSITIVE_ASSIGNMENT = (
    _percent_encode_layers(
        "api_key=synthetic-budget-manifest-secret",
        16,
    )
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


def test_commander_typed_manifest_read_rejects_sensitive_bound_page_metadata(
    tmp_path: Path,
) -> None:
    project = _make_git_checkout(tmp_path)
    server = MCPPlanningBridgeServer(
        str(project),
        exposure_profile="commander",
    )
    manifest = _manifest(project)
    manifest["review_unit"] = "password=synthetic-review-unit-secret"

    inspected = _tool_call(
        server,
        {
            "workflow": "review_manifest",
            "phase": "inspect",
            "review_manifest": manifest,
        },
    )
    inspection_contract = inspected["result"]["structuredContent"]["data"]
    manifest_id = inspection_contract["evidence"]["review_manifest_id"]

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
    assert structured["ok"] is False
    assert structured["error_code"] == "INTERNAL_RESULT_INVALID"
    assert "synthetic-review-unit-secret" not in json.dumps(
        structured,
        ensure_ascii=False,
    )
    validate_commander_response(structured["data"])


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
    ascii_closing_boundaries = (
        f"before){uri}; before]{uri}; before}}{uri}"
    )
    escaped_ascii_closing_boundaries = (
        f"before\\u0029{uri}; before\\u005d{uri}; "
        f"before\\u007d{uri}"
    )
    ascii_left_separator_boundaries = " ".join(
        f"{separator}{uri}" for separator in ",;!?"
    )
    escaped_ascii_left_separator_boundaries = " ".join(
        f"{separator}{uri}"
        for separator in ("\\u002c", "\\u003b", "\\u0021", "\\u003f")
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
        f"{ascii_closing_boundaries}\n"
        f"{escaped_ascii_closing_boundaries}\n"
        f"{ascii_left_separator_boundaries}\n"
        f"{escaped_ascii_left_separator_boundaries}\n"
        f"*{uri}* **{uri}** _{uri}_ __{uri}__\n"
        f"\\u002a\\u002a{uri}\\u002a\\u002a\n"
        "publicKey=synthetic-public-value\n"
        "-----BEGIN PUBLIC KEY-----\n"
        "-----BEGIN PGP PUBLIC KEY BLOCK-----\n"
        "https://example.com/repo\n"
        "https://alice@example.com/repo\n"
        "tool --username alice --region us-east-1\n"
        "tool --password --verbose\n"
        "tool --password\\u0020\\u002d\\u002dverbose\n"
        "tool --passphrase --prompt\n"
        "Use a passphrase prompt.\n"
        "PuTTY-User-Key-File-3 ssh-ed25519\n"
        f"AGE-SECRET-KEY-1{'Q' * 57}\n"
        f"AGE-SECRET-KEY-1{'Q' * 59}\n"
        "AGE-SECRET-KEY-1<redacted>\n"
        f"age1{'q' * 58}\n"
        "header.payload.signature\n"
        "c3ludGhldGlj.aGVhZGVy.c2lnbmF0dXJl\n"
        "_author=Jenn\n"
        "_authorship=public\n"
        "https://provider.example.invalid/callback"
        "?topic=api%5Fkey&api%5Fkeyboard=public\n"
        "https://provider.example.invalid/callback?api%5Fkey\n"
        "npm_short\n"
        "npm_<redacted>\n"
        f"npm_{'A' * 37}\n"
        f"dckr_pat_{'A' * 26}\n"
        "dckr_pat_<redacted>\n"
        f"dckr_pat_{'A' * 28}\n"
        f"dop_v1_{'a' * 63}\n"
        "dop_v1_<redacted>\n"
        f"dop_v1_{'a' * 65}\n"
        f"xdop_v1_{'a' * 64}\n"
        f"dop_v1_{'g' * 64}\n"
        "pypi-short\n"
        "pypi-<redacted>\n"
        f"pypi-{'A' * 84}\n"
        f"SG.{'A' * 21}.{'B' * 43}\n"
        f"SG.{'A' * 22}.{'B' * 42}\n"
        f"SG.{'A' * 22}.{'B' * 44}\n"
        "SG.<redacted>.<redacted>\n"
        f"{MAX_BUDGET_PERCENT_ENCODED_SAFE_PROSE}\n"
        "tool --user alice:note\n"
        "curl --user alice https://example.invalid\n"
        "curl -e https://example.test/page https://example.invalid\n"
        '{"command":"curl\\u0020-e\\u0020'
        'https:\\/\\/example.test/page\\u0020'
        'https:\\/\\/example.invalid"}\n'
        "curl --user <user:password> https://example.invalid\n"
        "curl --proxy-user alice https://example.invalid\n"
        "curl --proxy-user <user:password> https://example.invalid\n"
        "curl -U\n"
        f"colameta://review-manifest/{TOKEN_LIKE_OPAQUE_ID}"
        "/subjects/1/pages/{page}\n"
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


@pytest.mark.parametrize(
    "token_like_opaque_id",
    [
        TOKEN_LIKE_OPAQUE_ID,
        SYNTHETIC_DOCKER_PAT,
        SYNTHETIC_DIGITALOCEAN_TOKEN,
        SYNTHETIC_SHOPIFY_ACCESS_TOKEN,
    ],
)
def test_commander_manifest_preserves_token_like_opaque_handles(
    tmp_path: Path,
    monkeypatch,
    token_like_opaque_id: str,
) -> None:
    monkeypatch.setattr(
        "runner.review_manifest.secrets.token_urlsafe",
        lambda _length: token_like_opaque_id,
    )
    project = _make_git_checkout(tmp_path)
    content = (
        "# Review input\n\n"
        "A bounded subject.\n\n"
        "//example.test/docs/page\n"
        '{"url":"\\/\\/example.test\\/docs\\/page"}\n'
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
    inspection = inspected["result"]["structuredContent"]
    assert inspection["ok"] is True
    contract = inspection["data"]
    assert contract["evidence"]["review_manifest_id"] == token_like_opaque_id
    assert contract["evidence"]["resource_uri"] == (
        f"colameta://review-manifest/{token_like_opaque_id}"
    )
    subject_uri = contract["facts"]["subjects"][0]["resource_uri"]
    assert subject_uri == (
        f"colameta://review-manifest/{token_like_opaque_id}/subjects/1"
    )
    assert contract["next_action"]["arguments"]["review_manifest_id"] == (
        token_like_opaque_id
    )

    root_resource = _resource_read(
        server,
        contract["evidence"]["resource_uri"],
    )
    assert "error" not in root_resource
    root_summary = json.loads(
        root_resource["result"]["contents"][0]["text"]
    )
    assert root_summary["review_manifest_id"] == token_like_opaque_id
    assert root_summary["manifest_resource_uri"] == (
        f"colameta://review-manifest/{token_like_opaque_id}"
    )
    assert all(
        subject["read_call"]["arguments"]["review_manifest_id"]
        == token_like_opaque_id
        for subject in root_summary["subjects"]
    )

    typed = _tool_call(
        server,
        {
            "workflow": "review_manifest",
            "phase": "read",
            "review_manifest_id": token_like_opaque_id,
            "review_manifest_subject_index": 1,
        },
    )
    assert typed["result"]["structuredContent"]["ok"] is True
    assert typed["result"]["structuredContent"]["data"]["facts"][
        "subject_page"
    ]["content"] == content

    resource = _resource_read(server, subject_uri)
    resource_page = json.loads(resource["result"]["contents"][0]["text"])
    assert resource_page["content"] == content


@pytest.mark.parametrize(
    "tampering",
    [
        "root_id",
        "subject_read_id",
        "sensitive_sibling",
        "mime_type",
        "content_item_extra",
    ],
)
def test_commander_manifest_root_resource_rejects_unbound_ids_and_siblings(
    tmp_path: Path,
    monkeypatch,
    tampering: str,
) -> None:
    monkeypatch.setattr(
        "runner.review_manifest.secrets.token_urlsafe",
        lambda _length: TOKEN_LIKE_OPAQUE_ID,
    )
    project = _make_git_checkout(tmp_path)
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
    contract = inspected["result"]["structuredContent"]["data"]
    root_uri = contract["evidence"]["resource_uri"]
    original_read = server._review_manifest_resource_read_result
    injected_value = "other_review_manifest_handle_1234567890"
    if tampering == "sensitive_sibling":
        injected_value = SYNTHETIC_GITHUB_PAT
    elif tampering == "mime_type":
        injected_value = "text/html"
    elif tampering == "content_item_extra":
        injected_value = "unexpected-resource-metadata"

    def tampered_read(uri: str) -> dict | None:
        result = original_read(uri)
        if result is None or uri != root_uri:
            return result
        candidate = copy.deepcopy(result)
        summary = json.loads(candidate["contents"][0]["text"])
        if tampering == "root_id":
            summary["review_manifest_id"] = injected_value
        elif tampering == "subject_read_id":
            summary["subjects"][0]["read_call"]["arguments"][
                "review_manifest_id"
            ] = injected_value
        elif tampering == "mime_type":
            candidate["contents"][0]["mimeType"] = injected_value
        elif tampering == "content_item_extra":
            candidate["contents"][0]["debug"] = injected_value
        else:
            summary["preview_id"] = injected_value
        candidate["contents"][0]["text"] = json.dumps(
            summary,
            ensure_ascii=False,
        )
        return candidate

    monkeypatch.setattr(
        server,
        "_review_manifest_resource_read_result",
        tampered_read,
    )
    resource = _resource_read(server, root_uri)

    assert resource["error"]["data"]["error_code"] == "evidence_unavailable"
    assert injected_value not in json.dumps(resource, ensure_ascii=False)


@pytest.mark.parametrize(
    "tampering",
    ["page_content", "page_resource", "mime_type", "content_item_extra"],
)
def test_commander_manifest_subject_root_binds_first_page(
    tmp_path: Path,
    monkeypatch,
    tampering: str,
) -> None:
    project = _make_git_checkout(tmp_path)
    page_two_marker = "synthetic-page-two-only-marker"
    (project / "docs" / "review-input.md").write_text(
        ("a" * REVIEW_MANIFEST_PAGE_CHARS) + page_two_marker,
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
    contract = inspected["result"]["structuredContent"]["data"]
    subject = contract["facts"]["subjects"][0]
    subject_uri = subject["resource_uri"]
    page_two_uri = subject["page_uri_template"].replace("{page}", "2")
    original_read = server._review_manifest_resource_read_result
    page_one_resource = original_read(subject_uri)
    page_two_resource = original_read(page_two_uri)

    assert page_one_resource is not None
    assert page_two_resource is not None
    page_two = json.loads(page_two_resource["contents"][0]["text"])
    assert page_two["page"] == 2
    assert page_two_marker in page_two["content"]

    def tampered_read(uri: str) -> dict | None:
        if uri != subject_uri:
            return original_read(uri)
        if tampering == "page_resource":
            return copy.deepcopy(page_two_resource)
        candidate = copy.deepcopy(page_one_resource)
        if tampering == "mime_type":
            candidate["contents"][0]["mimeType"] = "text/html"
        elif tampering == "content_item_extra":
            candidate["contents"][0]["debug"] = (
                "unexpected-resource-metadata"
            )
        else:
            candidate["contents"][0]["text"] = page_two_resource[
                "contents"
            ][0]["text"]
        return candidate

    monkeypatch.setattr(
        server,
        "_review_manifest_resource_read_result",
        tampered_read,
    )
    resource = _resource_read(server, subject_uri)

    assert resource["error"]["data"]["error_code"] == "evidence_unavailable"
    assert page_two_marker not in json.dumps(resource, ensure_ascii=False)


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


def test_commander_manifest_reads_bind_returned_bytes_to_preflight(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = _make_git_checkout(tmp_path)
    content = "safe manifest subject " + ("x" * 256)
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
    inspection = inspected["result"]["structuredContent"]["data"]
    review_manifest_id = inspection["evidence"][
        "review_manifest_id"
    ]
    subject_uri = inspection["facts"]["subjects"][0][
        "resource_uri"
    ]
    stored = server._review_manifest_store.get(review_manifest_id)

    assert stored is not None
    original_read_page = (
        mcp_review_manifest_module.read_stored_review_manifest_page
    )
    stored_page = original_read_page(
        stored,
        subject_index=1,
        page=1,
    )
    parsed_subject = server._parse_mcp_review_manifest_uri(
        subject_uri
    )
    assert parsed_subject is not None
    assert (
        server._commander_public_review_manifest_subject_safety(
            parsed_subject
        )
        is True
    )
    assert len(stored_page.content) > len(SYNTHETIC_DIGITALOCEAN_TOKEN)
    replacement_content = (
        SYNTHETIC_DIGITALOCEAN_TOKEN
        + (
            "!"
            * (
                len(stored_page.content)
                - len(SYNTHETIC_DIGITALOCEAN_TOKEN)
            )
        )
    )
    replacement_page = replace(
        stored_page,
        content=replacement_content,
    )
    assert len(replacement_page.content) == len(stored_page.content)
    assert replacement_page.page == stored_page.page
    assert replacement_page.sha256 == stored_page.sha256

    def read_replaced_page(
        candidate_stored,
        *,
        subject_index: int,
        page: int,
    ):
        if (
            candidate_stored.handle.review_manifest_id
            == review_manifest_id
            and subject_index == 1
            and page == 1
        ):
            return replacement_page
        return original_read_page(
            candidate_stored,
            subject_index=subject_index,
            page=page,
        )

    monkeypatch.setattr(
        mcp_review_manifest_module,
        "read_stored_review_manifest_page",
        read_replaced_page,
    )

    typed = server.call_tool_for_agent(
        "review_manifest",
        {
            "phase": "read",
            "review_manifest_id": review_manifest_id,
            "review_manifest_subject_index": 1,
            "review_manifest_page": 1,
        },
    )

    assert typed["ok"] is False
    assert typed["data"]["outcome"] == "failed"
    assert typed["data"]["error"]["code"] == "INTERNAL_RESULT_INVALID"
    assert SYNTHETIC_DIGITALOCEAN_TOKEN not in json.dumps(
        typed,
        ensure_ascii=False,
    )

    resource = _resource_read(server, subject_uri)
    assert (
        resource["error"]["data"]["error_code"]
        == "evidence_unavailable"
    )
    assert SYNTHETIC_DIGITALOCEAN_TOKEN not in json.dumps(
        resource,
        ensure_ascii=False,
    )


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
    subject = inspected["data"]["facts"]["subjects"][0]
    subject_uri = subject["resource_uri"]
    arguments = subject["read_call"]["arguments"]
    (project / "docs" / "review-input.md").write_text(
        "changed after Commander inspect\n",
        encoding="utf-8",
    )

    for method in ("tools/call", "call_tool", "review_manifest"):
        params = (
            {"name": "review_manifest", "arguments": arguments}
            if method in {"tools/call", "call_tool"}
            else arguments
        )
        tool_response = server._handle_jsonrpc_request(
            {
                "jsonrpc": "2.0",
                "id": method,
                "method": method,
                "params": params,
            }
        )

        assert tool_response is not None
        result = tool_response["result"]
        structured = (
            result["structuredContent"]
            if method == "tools/call"
            else result
        )
        assert structured["ok"] is False
        contract = structured["data"]
        assert contract["schema_version"] == "commander_response.v1"
        assert contract["outcome"] == "blocked"
        assert contract["error"]["code"] == "STALE_CONTEXT"
        assert "REVIEW_MANIFEST_SUBJECT_HASH_MISMATCH" not in repr(
            tool_response
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


def test_commander_manifest_reads_reject_private_jwk_material(
    tmp_path: Path,
) -> None:
    project = _make_git_checkout(tmp_path)
    private_coordinate = "synthetic-manifest-private-jwk-coordinate"
    content = json.dumps(
        {
            "keys": [
                {
                    "kty": "EC",
                    "crv": "P-256",
                    "x": "synthetic-public-x",
                    "y": "synthetic-public-y",
                    "d": private_coordinate,
                }
            ]
        }
    )
    (project / "docs" / "review-input.md").write_text(
        content,
        encoding="utf-8",
    )
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

    assert inspected["ok"] is True
    subject = inspected["data"]["facts"]["subjects"][0]
    typed = server.call_tool_for_agent(
        "review_manifest",
        subject["read_call"]["arguments"],
    )
    assert typed["ok"] is False
    assert typed["data"]["outcome"] == "blocked"
    assert typed["data"]["error"]["code"] == "EVIDENCE_UNAVAILABLE"
    assert private_coordinate not in json.dumps(
        typed,
        ensure_ascii=False,
    )

    resource = _resource_read(server, subject["resource_uri"])
    assert (
        resource["error"]["data"]["error_code"]
        == "evidence_unavailable"
    )
    assert private_coordinate not in json.dumps(
        resource,
        ensure_ascii=False,
    )


def test_commander_manifest_reads_reject_oauth_device_authorization(
    tmp_path: Path,
) -> None:
    project = _make_git_checkout(tmp_path)
    device_secret = "synthetic-manifest-device-secret"
    content = json.dumps(
        {
            "device_code": device_secret,
            "user_code": "ABCD-EFGH",
            "expires_in": 600,
        }
    )
    (project / "docs" / "review-input.md").write_text(
        content,
        encoding="utf-8",
    )
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

    assert inspected["ok"] is True
    subject = inspected["data"]["facts"]["subjects"][0]
    typed = server.call_tool_for_agent(
        "review_manifest",
        subject["read_call"]["arguments"],
    )
    assert typed["ok"] is False
    assert typed["data"]["outcome"] == "blocked"
    assert typed["data"]["error"]["code"] == "EVIDENCE_UNAVAILABLE"
    assert device_secret not in json.dumps(typed, ensure_ascii=False)

    resource = _resource_read(server, subject["resource_uri"])
    assert (
        resource["error"]["data"]["error_code"]
        == "evidence_unavailable"
    )
    assert device_secret not in json.dumps(
        resource,
        ensure_ascii=False,
    )


@pytest.mark.parametrize(
    "credential_kind",
    ("private-jwk", "oauth-device"),
)
def test_commander_manifest_reads_fail_closed_at_structured_depth_limit(
    tmp_path: Path,
    credential_kind: str,
) -> None:
    project = _make_git_checkout(tmp_path)
    secret = f"synthetic-depth-{credential_kind}-secret"
    credential = (
        {"kty": "EC", "d": secret}
        if credential_kind == "private-jwk"
        else {"device_code": secret, "expires_in": 600}
    )
    content = json.dumps(_nest_json_containers(credential))
    (project / "docs" / "review-input.md").write_text(
        content,
        encoding="utf-8",
    )
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

    assert inspected["ok"] is True
    subject = inspected["data"]["facts"]["subjects"][0]
    typed = server.call_tool_for_agent(
        "review_manifest",
        subject["read_call"]["arguments"],
    )
    assert typed["ok"] is False
    assert typed["data"]["outcome"] == "blocked"
    assert typed["data"]["error"]["code"] == "EVIDENCE_UNAVAILABLE"
    assert secret not in json.dumps(typed, ensure_ascii=False)

    resource = _resource_read(server, subject["resource_uri"])
    assert (
        resource["error"]["data"]["error_code"]
        == "evidence_unavailable"
    )
    assert secret not in json.dumps(resource, ensure_ascii=False)


@pytest.mark.parametrize(
    "assignment",
    (
        "password[]=synthetic-manifest-bracket-secret",
        (
            "database[password]="
            "synthetic-manifest-nested-bracket-secret"
        ),
    ),
)
def test_commander_manifest_reads_reject_bracket_assignments(
    tmp_path: Path,
    assignment: str,
) -> None:
    project = _make_git_checkout(tmp_path)
    (project / "docs" / "review-input.md").write_text(
        assignment,
        encoding="utf-8",
    )
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

    assert inspected["ok"] is True
    subject = inspected["data"]["facts"]["subjects"][0]
    typed = server.call_tool_for_agent(
        "review_manifest",
        subject["read_call"]["arguments"],
    )
    assert typed["ok"] is False
    assert typed["data"]["outcome"] == "blocked"
    assert typed["data"]["error"]["code"] == "EVIDENCE_UNAVAILABLE"
    assert "synthetic-manifest" not in json.dumps(
        typed,
        ensure_ascii=False,
    )

    resource = _resource_read(server, subject["resource_uri"])
    assert (
        resource["error"]["data"]["error_code"]
        == "evidence_unavailable"
    )
    assert "synthetic-manifest" not in json.dumps(
        resource,
        ensure_ascii=False,
    )


def test_commander_manifest_reads_preserve_markdown_resource_link_label(
    tmp_path: Path,
) -> None:
    project = _make_git_checkout(tmp_path)
    opaque_uri = (
        "colameta://review-manifest/opaque_handle_123_"
        "/subjects/1/pages/{page}"
    )
    content = f"[{opaque_uri}](https://example.test/evidence)"
    (project / "docs" / "review-input.md").write_text(
        content,
        encoding="utf-8",
    )
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

    assert inspected["ok"] is True
    subject = inspected["data"]["facts"]["subjects"][0]
    typed = server.call_tool_for_agent(
        "review_manifest",
        subject["read_call"]["arguments"],
    )
    assert typed["ok"] is True
    assert typed["data"]["facts"]["subject_page"]["content"] == content

    resource = _resource_read(server, subject["resource_uri"])
    resource_page = json.loads(
        resource["result"]["contents"][0]["text"]
    )
    assert resource_page["content"] == content


def test_commander_manifest_reads_preserve_safe_xml_and_token_metrics(
    tmp_path: Path,
) -> None:
    project = _make_git_checkout(tmp_path)
    content = (
        "<status>public-ready</status>\n"
        "<ns:status>namespace-ready</ns:status>\n"
        "&lt;status&gt;entity-ready&lt;/status&gt;\n"
        '<property name="public-key" value="public-material"/>\n'
        '<property name="password" value=""/>\n'
        '<property name="password"> \n\t </property>\n'
        '<entry key="public-key" value="public-material"/>\n'
        '<entry key="password" value=""/>\n'
        '<entry key="password"> \n\t </entry>\n'
        '<property name="public-key">public-material</property>\n'
        "<password></password>\n"
        "<password> \n\t </password>\n"
        "<password/>\n"
        "<config:password></config:password>\n"
        "token_count: 42\n"
        "prompt_token_count=21\n"
        "token_budget=1000\n"
        '{"output_token_count":12}\n'
        "password:\n"
        "password=\n"
        "password: # supplied locally\n"
        '"client_secret": ""\n'
        "config[password]=\n"
        '{"code":"SUCCESS","state":"completed"}\n'
        "{'kty': 'RSA', 'n': 'synthetic-python-public-modulus', "
        "'e': 'AQAB'}\n"
    )
    (project / "docs" / "review-input.md").write_text(
        content,
        encoding="utf-8",
    )
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

    assert inspected["ok"] is True
    subject = inspected["data"]["facts"]["subjects"][0]
    typed = server.call_tool_for_agent(
        "review_manifest",
        subject["read_call"]["arguments"],
    )
    assert typed["ok"] is True
    assert typed["data"]["facts"]["subject_page"]["content"] == content

    resource = _resource_read(server, subject["resource_uri"])
    resource_page = json.loads(
        resource["result"]["contents"][0]["text"]
    )
    assert resource_page["content"] == content


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
        r"\Users\Jenn\secret.txt",
        json.dumps({"reason": r"\Windows\System32\config\SAM"}),
        (
            '{"reason":"\\u005cUsers\\u005cJenn'
            '\\u005csecret.txt"}'
        ),
        json.dumps(
            {
                "nested": json.dumps(
                    {"reason": r"\Users\Jenn\secret.txt"}
                )
            }
        ),
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
        '{"apiKey":"synthetic-secret-value"}',
        '{"API Key":"synthetic-spaced-secret"}',
        "api key: synthetic-unquoted-manifest-secret",
        (
            r"api\u0020key\u003a "
            "synthetic-encoded-unquoted-manifest-secret"
        ),
        "AWS_ACCESS_KEY_ID=synthetic-aws-access-id",
        "apiKey=delta epsilon zeta",
        "private-key=synthetic-private-key-value",
        "<password>synthetic-xml-manifest-secret</password>",
        (
            '<property name="password" '
            'value="synthetic-xml-attribute-manifest-secret"/>'
        ),
        (
            '<add key="ClientSecret" '
            'value="synthetic-xml-key-manifest-secret"/>'
        ),
        (
            '<property name="password">'
            "synthetic-xml-body-manifest-secret"
            "</property>"
        ),
        (
            "<property><name>password</name>"
            "<value>synthetic-xml-sibling-manifest-secret"
            "</value></property>"
        ),
        (
            "<property><type>password</type>"
            "<value>synthetic-xml-type-sibling-manifest-secret"
            "</value></property>"
        ),
        (
            "<RSAKeyValue><Modulus>synthetic-public-modulus</Modulus>"
            "<Exponent>AQAB</Exponent>"
            "<D>synthetic-rsa-private-manifest-d</D></RSAKeyValue>"
        ),
        (
            '{"xml":"\\u003cclientSecret\\u003e'
            'synthetic-encoded-xml-manifest-secret'
            '\\u003c/clientSecret\\u003e"}'
        ),
        (
            "&lt;password&gt;"
            "synthetic-named-entity-xml-manifest-secret"
            "&lt;/password&gt;"
        ),
        (
            "&#60;clientSecret&#62;"
            "synthetic-decimal-entity-xml-manifest-secret"
            "&#60;&#47;clientSecret&#62;"
        ),
        (
            '{"xml":"\\u0026amp;lt;password\\u0026amp;gt;'
            'synthetic-nested-entity-xml-manifest-secret'
            '\\u0026amp;lt;/password\\u0026amp;gt;"}'
        ),
        (
            "&#37;26lt&#37;3Bpassword&#37;26gt&#37;3B"
            "synthetic-entity-percent-xml-manifest-secret"
            "&#37;26lt&#37;3B/password&#37;26gt&#37;3B"
        ),
        (
            '{"kty":"EC",'
            '"d":"synthetic-duplicate-manifest-coordinate","d":""}'
        ),
        (
            '{"device_code":"synthetic-duplicate-manifest-device",'
            '"device_code":"","expires_in":600}'
        ),
        (
            "client-key-data: "
            "c3ludGhldGljLW1hbmlmZXN0LWt1YmUta2V5"
        ),
        "AWS_SECRET_ACCESS_KEY=synthetic-aws-secret-value",
        r'{\"apiKey\":\"synthetic-escaped-secret\"}',
        (
            "-----BEGIN OPENSSH PRIVATE KEY-----\n"
            "synthetic-private-key-material\n"
            "-----END OPENSSH PRIVATE KEY-----"
        ),
        SYNTHETIC_AGE_X25519_IDENTITY,
        (
            '{"identity":"'
            f"{ESCAPED_SYNTHETIC_AGE_X25519_IDENTITY}"
            '"}'
        ),
        (
            '{"pem":"-----BEGIN \\u0050RIVATE KEY-----'
            '\\nsynthetic-encoded-key-material"}'
        ),
        (
            "-----BEGIN PGP PRIVATE KEY BLOCK-----\n"
            "synthetic-pgp-key-material\n"
            "-----END PGP PRIVATE KEY BLOCK-----"
        ),
        (
            "---- BEGIN SSH2 ENCRYPTED PRIVATE KEY ----\n"
            "synthetic-ssh2-private-key-material\n"
            "---- END SSH2 ENCRYPTED PRIVATE KEY ----"
        ),
        (
            '{"armor":"-----BEGIN PGP \\u0050RIVATE KEY '
            '\\u0042LOCK-----\\nsynthetic-encoded-pgp-material"}'
        ),
        "passphrase=synthetic-passphrase-value",
        '{"passPhrase":"synthetic-camel-passphrase"}',
        "--passphrase synthetic-cli-passphrase",
        (
            "PuTTY-User-Key-File-3: ssh-ed25519\n"
            "Encryption: aes256-cbc\n"
            "Private-Lines: 1\n"
            "synthetic-putty-private-material"
        ),
        (
            '{"ppk":"PuTTY-User-Key-File-\\u0032\\u003a ssh-rsa'
            '\\nPrivate-Lines: 1'
            '\\nsynthetic-encoded-putty-private-material"}'
        ),
        SYNTHETIC_JWT,
        f'{{"access":"{ESCAPED_SYNTHETIC_JWT}"}}',
        json.dumps(
            {
                "wrapped": json.dumps(
                    {"access": ESCAPED_SYNTHETIC_JWT}
                )
            }
        ),
        SYNTHETIC_GITHUB_PAT,
        f'{{"access":"{ESCAPED_SYNTHETIC_GITHUB_PAT}"}}',
        json.dumps(
            {
                "wrapped": json.dumps(
                    {"access": ESCAPED_SYNTHETIC_GITHUB_PAT}
                )
            }
        ),
        SYNTHETIC_HUGGING_FACE_TOKEN,
        f'{{"access":"{ESCAPED_SYNTHETIC_HUGGING_FACE_TOKEN}"}}',
        json.dumps(
            {
                "wrapped": json.dumps(
                    {"access": ESCAPED_SYNTHETIC_HUGGING_FACE_TOKEN}
                )
            }
        ),
        SYNTHETIC_DIGITALOCEAN_TOKEN,
        (
            "https://cloud.digitalocean.com/account/api/tokens"
            f"?token={SYNTHETIC_DIGITALOCEAN_TOKEN}"
        ),
        SYNTHETIC_DIGITALOCEAN_TOKEN.replace(
            "dop_v1_",
            "dop%5Fv1%5F",
        ),
        f'{{"access":"{ESCAPED_SYNTHETIC_DIGITALOCEAN_TOKEN}"}}',
        json.dumps(
            {
                "wrapped": json.dumps(
                    {"access": ESCAPED_SYNTHETIC_DIGITALOCEAN_TOKEN}
                )
            }
        ),
        SYNTHETIC_DATABRICKS_PAT,
        SYNTHETIC_DATABRICKS_PAT.replace("dapi", "d%61pi"),
        f'{{"access":"{ESCAPED_SYNTHETIC_DATABRICKS_PAT}"}}',
        json.dumps(
            {
                "wrapped": json.dumps(
                    {"access": ESCAPED_SYNTHETIC_DATABRICKS_PAT}
                )
            }
        ),
        SYNTHETIC_VAULT_SERVICE_TOKEN,
        SYNTHETIC_VAULT_BATCH_TOKEN,
        SYNTHETIC_VAULT_RECOVERY_TOKEN,
        SYNTHETIC_VAULT_SERVICE_TOKEN.replace("hvs.", "hvs%2E"),
        SYNTHETIC_VAULT_BATCH_TOKEN.replace("hvb.", "hvb%2E"),
        f'{{"access":"{ESCAPED_SYNTHETIC_VAULT_SERVICE_TOKEN}"}}',
        json.dumps(
            {
                "wrapped": json.dumps(
                    {"access": ESCAPED_SYNTHETIC_VAULT_SERVICE_TOKEN}
                )
            }
        ),
        SYNTHETIC_ONEPASSWORD_SERVICE_ACCOUNT_TOKEN,
        SYNTHETIC_ONEPASSWORD_SERVICE_ACCOUNT_TOKEN.replace(
            "ops_",
            "ops%5F",
        ),
        f'{{"access":"{ESCAPED_SYNTHETIC_ONEPASSWORD_SERVICE_ACCOUNT_TOKEN}"}}',
        SYNTHETIC_SHOPIFY_ACCESS_TOKEN,
        (
            "https://shop.example.invalid/admin?token="
            f"{SYNTHETIC_SHOPIFY_ACCESS_TOKEN}"
        ),
        SYNTHETIC_SHOPIFY_ACCESS_TOKEN.replace("shpat_", "shpat%5F"),
        f'{{"access":"{ESCAPED_SYNTHETIC_SHOPIFY_ACCESS_TOKEN}"}}',
        json.dumps(
            {
                "wrapped": json.dumps(
                    {"access": ESCAPED_SYNTHETIC_SHOPIFY_ACCESS_TOKEN}
                )
            }
        ),
        SYNTHETIC_NPM_ACCESS_TOKEN,
        (
            "https://registry.npmjs.org/callback?token="
            f"{SYNTHETIC_NPM_ACCESS_TOKEN}"
        ),
        f'{{"access":"{ESCAPED_SYNTHETIC_NPM_ACCESS_TOKEN}"}}',
        json.dumps(
            {
                "wrapped": json.dumps(
                    {"access": ESCAPED_SYNTHETIC_NPM_ACCESS_TOKEN}
                )
            }
        ),
        SYNTHETIC_DOCKER_PAT,
        SYNTHETIC_DOCKER_PAT.replace("dckr_pat_", "dckr%5Fpat%5F"),
        f'{{"access":"{ESCAPED_SYNTHETIC_DOCKER_PAT}"}}',
        json.dumps(
            {
                "wrapped": json.dumps(
                    {"access": ESCAPED_SYNTHETIC_DOCKER_PAT}
                )
            }
        ),
        SYNTHETIC_PYPI_API_TOKEN,
        SYNTHETIC_LONG_PYPI_API_TOKEN,
        (
            "https://upload.pypi.org/legacy/?token="
            f"{SYNTHETIC_PYPI_API_TOKEN}"
        ),
        SYNTHETIC_PYPI_API_TOKEN.replace("pypi-", "pypi%2D"),
        f'{{"access":"{ESCAPED_SYNTHETIC_PYPI_API_TOKEN}"}}',
        json.dumps(
            {
                "wrapped": json.dumps(
                    {"access": ESCAPED_SYNTHETIC_PYPI_API_TOKEN}
                )
            }
        ),
        SYNTHETIC_SENDGRID_API_KEY,
        (
            "https://api.sendgrid.com/v3/?access="
            f"{SYNTHETIC_SENDGRID_API_KEY}"
        ),
        SYNTHETIC_SENDGRID_API_KEY.replace(".", "%2E"),
        f'{{"access":"{ESCAPED_SYNTHETIC_SENDGRID_API_KEY}"}}',
        json.dumps(
            {
                "wrapped": json.dumps(
                    {"access": ESCAPED_SYNTHETIC_SENDGRID_API_KEY}
                )
            }
        ),
        SYNTHETIC_GITLAB_PAT,
        f'{{"access":"{ESCAPED_SYNTHETIC_GITLAB_PAT}"}}',
        json.dumps(
            {
                "wrapped": json.dumps(
                    {"access": ESCAPED_SYNTHETIC_GITLAB_PAT}
                )
            }
        ),
        SYNTHETIC_GOOGLE_API_KEY,
        f'{{"access":"{ESCAPED_SYNTHETIC_GOOGLE_API_KEY}"}}',
        json.dumps(
            {
                "wrapped": json.dumps(
                    {"access": ESCAPED_SYNTHETIC_GOOGLE_API_KEY}
                )
            }
        ),
        SYNTHETIC_GOOGLE_OAUTH_CLIENT_SECRET,
        SYNTHETIC_GOOGLE_OAUTH_CLIENT_SECRET.replace("-", "%2D"),
        (
            '{"access":"'
            f"{ESCAPED_SYNTHETIC_GOOGLE_OAUTH_CLIENT_SECRET}"
            '"}'
        ),
        json.dumps(
            {
                "wrapped": json.dumps(
                    {
                        "access": (
                            ESCAPED_SYNTHETIC_GOOGLE_OAUTH_CLIENT_SECRET
                        )
                    }
                )
            }
        ),
        SYNTHETIC_AWS_ACCESS_KEY_ID,
        SYNTHETIC_AWS_TEMPORARY_ACCESS_KEY_ID,
        f'{{"access":"{ESCAPED_SYNTHETIC_AWS_ACCESS_KEY_ID}"}}',
        json.dumps(
            {
                "wrapped": json.dumps(
                    {"access": ESCAPED_SYNTHETIC_AWS_ACCESS_KEY_ID}
                )
            }
        ),
        SYNTHETIC_STRIPE_SECRET_KEY,
        SYNTHETIC_STRIPE_RESTRICTED_KEY,
        SYNTHETIC_STRIPE_WEBHOOK_SECRET,
        SYNTHETIC_STRIPE_WEBHOOK_SECRET.replace("_", "%5F"),
        f'{{"access":"{ESCAPED_SYNTHETIC_STRIPE_SECRET_KEY}"}}',
        json.dumps(
            {
                "wrapped": json.dumps(
                    {"access": ESCAPED_SYNTHETIC_STRIPE_SECRET_KEY}
                )
            }
        ),
        SYNTHETIC_SLACK_TOKEN,
        SYNTHETIC_SLACK_WEBHOOK_URL,
        SYNTHETIC_SLACK_WEBHOOK_URL.replace("/", "%2F"),
        SYNTHETIC_DISCORD_WEBHOOK_URL,
        SYNTHETIC_DISCORD_WEBHOOK_URL.replace("/", "%2F"),
        f'{{"access":"{ESCAPED_SYNTHETIC_SLACK_TOKEN}"}}',
        json.dumps(
            {
                "wrapped": json.dumps(
                    {"access": ESCAPED_SYNTHETIC_SLACK_TOKEN}
                )
            }
        ),
        SYNTHETIC_OPENAI_PROJECT_KEY,
        f'{{"access":"{ESCAPED_SYNTHETIC_OPENAI_PROJECT_KEY}"}}',
        json.dumps(
            {
                "wrapped": json.dumps(
                    {"access": ESCAPED_SYNTHETIC_OPENAI_PROJECT_KEY}
                )
            }
        ),
        "AccountKey=synthetic-azure-account-key",
        '{"Account\\u004bey":"synthetic-encoded-account-key"}',
        json.dumps(
            {
                "wrapped": (
                    "SharedAccess\\u0053ignature="
                    "sv=synthetic-version&sig=synthetic-nested-sas"
                )
            }
        ),
        (
            "https://account.blob.core.windows.net/container/blob"
            "?sv=2024-11-04&sp=r&sig=synthetic-sas-url-signature"
        ),
        "?sv=2024-11-04&ss=b&sp=rl&sig=synthetic-standalone-sas",
        "sig=synthetic-form-sas&sp=r&sv=2024-11-04",
        "%3Fsv%3D2024-11-04%26sig%3Dsynthetic-percent-sas",
        (
            '{"url":"https:\\/\\/account.blob.core.windows.net'
            '\\/container\\/blob?sv\\u003d2024-11-04'
            '\\u0026sig\\u003dsynthetic-encoded-sas-signature"}'
        ),
        json.dumps(
            {
                "wrapped": (
                    "https:\\u002f\\u002faccount.blob.core.windows.net"
                    "/container/blob?sig=synthetic-nested-sas-signature"
                    "\\u0026sv=2024-11-04"
                )
            }
        ),
        "client_secret: alpha beta gamma",
        "password: correct horse battery staple",
        "PASSWORD=#synthetic-punctuation-manifest-secret",
        '{"shell":"PASSWORD\\u003d#synthetic-encoded-manifest-secret"}',
        "_auth=dXNlcjpwYXNz",
        '{"\\u005fauth":"dXNlcjpwYXNz"}',
        json.dumps(
            {
                "wrapped": (
                    "//registry.npmjs.org/:"
                    "\\u005fauthToken=synthetic-nested-npm-token"
                )
            }
        ),
        (
            "https://provider.example.invalid/callback"
            "?api%5Fkey=synthetic-percent-manifest-secret"
        ),
        (
            '{"url":"https:\\/\\/provider.example.invalid\\/callback'
            '?api\\u00255Fkey=synthetic-json-percent-manifest-secret"}'
        ),
        json.dumps(
            {
                "wrapped": json.dumps(
                    {
                        "url": (
                            "https://provider.example.invalid/callback"
                            "?api%255Fkey="
                            "synthetic-nested-percent-manifest-secret"
                        )
                    }
                )
            }
        ),
        (
            "https://provider.example.invalid/callback"
            "?api+key=synthetic-form-manifest-secret"
        ),
        (
            '{"url":"https:\\/\\/provider.example.invalid\\/callback'
            '?api\\u00252Bkey='
            'synthetic-encoded-form-manifest-secret"}'
        ),
        (
            "https://client.example.invalid/callback"
            "?code=synthetic-oauth-manifest-code"
            "&state=synthetic-oauth-manifest-state"
        ),
        (
            "https://client.example.invalid/callback"
            "?code=synthetic-oauth-empty-state-manifest-code&state="
        ),
        (
            '{"url":"https:\\/\\/client.example.invalid\\/callback'
            '?code\\u003dsynthetic-encoded-oauth-manifest-code'
            '\\u0026state\\u003d'
            'synthetic-encoded-oauth-manifest-state"}'
        ),
        (
            '{"code":"synthetic-structured-oauth-manifest-code",'
            '"state":"synthetic-structured-oauth-manifest-state"}'
        ),
        (
            "{'code': 'synthetic-python-oauth-manifest-code', "
            "'state': 'synthetic-python-oauth-manifest-state'}"
        ),
        (
            "grant_type=authorization_code"
            "&code=synthetic-oauth-token-form-manifest-code"
        ),
        (
            "grant_type=authorization_code&padding="
            + ("a" * 8_192)
            + "&code=synthetic-overflow-token-form-manifest-code"
        ),
        (
            '{"body":"grant_type\\u003dauthorization_code'
            '\\u0026code\\u003d'
            'synthetic-encoded-token-form-manifest-code"}'
        ),
        (
            "https://distribution.example.invalid/"
            + ("b" * 8193)
            + "?Expires=2147483647"
            "&Signature=synthetic-overflow-manifest-signature"
            "&Key-Pair-Id=synthetic-overflow-manifest-key-pair"
        ),
        (
            "https://distribution.example.invalid/private/report.pdf"
            "?Expires=2147483647"
            "&Signature=synthetic-cloudfront-manifest-signature"
            "&Key-Pair-Id=synthetic-cloudfront-manifest-key-pair"
        ),
        json.dumps(
            {
                "CloudFront-Policy": "synthetic-cloudfront-manifest-policy",
                "CloudFront-Signature": (
                    "synthetic-cloudfront-cookie-manifest-signature"
                ),
                "CloudFront-Key-Pair-Id": (
                    "synthetic-cloudfront-cookie-manifest-key-pair"
                ),
            }
        ),
        (
            "CloudFront-Expires=2147483647; "
            "CloudFront-Signature=synthetic-bare-cookie-manifest-signature; "
            "CloudFront-Key-Pair-Id=synthetic-bare-cookie-manifest-key"
        ),
        (
            "https://storage.googleapis.com/example/object"
            "?GoogleAccessId=synthetic-gcs-manifest-access-id"
            "&Expires=2147483647"
            "&Signature=synthetic-gcs-manifest-signature"
        ),
        "token_count=synthetic-token-metric-manifest-secret",
        "token_count_secret=123456",
        "token_budget_password: 987654",
        "token_count=" + ("9" * 5_000),
        (
            "{'kty': 'RSA', "
            "'d': 'synthetic-python-manifest-private-coordinate'}"
        ),
        (
            "{'device_code': 'synthetic-python-manifest-device-code', "
            "'user_code': 'MNFT-REPR'}"
        ),
        (
            '<property name="password" filler="'
            + ("x" * 4_097)
            + '" value="synthetic-overflow-xml-manifest-secret"/>'
        ),
        (
            "localhost:5432:mydb:alice:"
            "synthetic-pgpass-manifest-password"
        ),
        (
            '{"pgpass":"localhost\\u003a5432\\u003amydb'
            '\\u003aalice\\u003a'
            'synthetic-encoded-pgpass-manifest-password"}'
        ),
        "PGPASSWORD=synthetic-postgres-manifest-password",
        (
            '{"env":"PGPASSWORD\\u003d'
            'synthetic-encoded-postgres-manifest-password"}'
        ),
        "MYSQL_PWD=synthetic-mysql-manifest-password",
        (
            '{"env":"MYSQL\\u005fPWD\\u003d'
            'synthetic-encoded-mysql-manifest-password"}'
        ),
        "SQLCMDPASSWORD=synthetic-sqlcmd-manifest-password",
        (
            '{"env":"SQLCMDPASSWORD\\u003d'
            'synthetic-encoded-sqlcmd-manifest-password"}'
        ),
        json.dumps(
            {
                "wrapped": (
                    "MYSQL%255FPWD%253D"
                    "synthetic-nested-mysql-manifest-password"
                )
            }
        ),
        "123456789:" + ("A" * 35),
        "https://api.telegram.org/bot123456789:"
        + ("A" * 35)
        + "/getMe",
        "https:%2F%2Fapi.telegram.org%2Fbot123456789%3A"
        + ("A" * 35)
        + "%2FsendMessage",
        '{"access":"123456789\\u003a' + ("B" * 35) + '"}',
        (
            "machine example.com login alice "
            "password synthetic-netrc-manifest-secret"
        ),
        (
            "machine example.com\n"
            "  login alice\n"
            "  password synthetic-multiline-netrc-manifest-secret"
        ),
        (
            '{"netrc":"machine example.com login alice '
            'password\\u0020synthetic-encoded-netrc-manifest-secret"}'
        ),
        json.dumps(
            {
                "wrapped": (
                    "machine example.com\\u0020login alice"
                    "\\u0020password synthetic-nested-netrc-manifest-secret"
                )
            }
        ),
        "redis://cache:synthetic-password@cache.example/0",
        "//cache:synthetic-relative-password@cache.example/0",
        (
            '{"url":"postgresql:\\u002f\\u002fdbuser:'
            'synthetic-db-password@db.example/app"}'
        ),
        (
            '{"url":"redis:\\u002f\\u002fcache\\u003a'
            'synthetic-encoded-authority\\u0040cache.example/0"}'
        ),
        "--password synthetic-cli-password",
        "tool --api-key synthetic-cli-secret --verbose",
        (
            'curl --oauth2-bearer "synthetic-manifest-bearer-token" '
            "https://example.test"
        ),
        (
            "curl -u alice:synthetic-curl-manifest-password "
            "https://example.invalid"
        ),
        (
            "curl --user=alice:synthetic-equals-curl-manifest-password "
            "https://example.invalid"
        ),
        (
            "curl -U alice:synthetic-curl-proxy-manifest-password "
            "https://example.invalid"
        ),
        (
            "curl --proxy-user=alice:"
            "synthetic-equals-proxy-manifest-password "
            "https://example.invalid"
        ),
        (
            '{"command":"curl\\u0020--user\\u0020alice\\u003a'
            'synthetic-encoded-curl-manifest-password '
            'https:\\/\\/example.invalid"}'
        ),
        (
            '{"command":"curl\\u0020--proxy-user\\u0020alice\\u003a'
            'synthetic-encoded-proxy-manifest-password '
            'https:\\/\\/example.invalid"}'
        ),
        json.dumps(
            {
                "wrapped": (
                    "curl%20-ualice%3A"
                    "synthetic-nested-curl-manifest-password%20"
                    "https%3A%2F%2Fexample.invalid"
                )
            }
        ),
        json.dumps(
            {
                "wrapped": (
                    "curl%20--proxy-user%3Dalice%3A"
                    "synthetic-nested-proxy-manifest-password%20"
                    "https%3A%2F%2Fexample.invalid"
                )
            }
        ),
        (
            "curl -E client.pem:synthetic-manifest-cert-password "
            "https://example.invalid"
        ),
        (
            "curl --cert=client.pem:synthetic-manifest-cert-password "
            "https://example.invalid"
        ),
        (
            '{"command":"curl\\u0020--proxy-pass\\u003d'
            'synthetic-encoded-manifest-passphrase '
            'https:\\/\\/example.invalid"}'
        ),
        (
            "https://example.test/download"
            "?file=%2Fhome%2Fjenn%2Fmanifest-secret.txt"
        ),
        (
            '{"url":"https:\\/\\/example.test\\/download'
            '?file=\\u00252Fhome\\u00252Fjenn'
            '\\u00252Fmanifest-secret.txt"}'
        ),
        "root:/home/jenn/manifest-labeled-secret.txt",
        (
            '{"note":"root:\\u005cUsers\\u005cJenn'
            '\\u005cmanifest-labeled-secret.txt"}'
        ),
        EXHAUSTING_PERCENT_ENCODED_SAFE_PROSE,
        EXHAUSTING_PERCENT_ENCODED_SENSITIVE_ASSIGNMENT,
        (
            '{"command":"tool --api-key\\u0020'
            'synthetic-encoded-space-cli-secret"}'
        ),
        (
            '{"command":"tool --client\\u002dsecret '
            'synthetic-encoded-cli-secret"}'
        ),
        json.dumps(
            {
                "wrapped": (
                    '{"command":"tool --refresh\\u002dtoken '
                    'synthetic-nested-cli-secret"}'
                )
            }
        ),
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
        '{"reason":"%6danage_files"}',
        '{"reason":"%256danage%255ffiles"}',
        json.dumps(
            {"reason": '{"tool":"manage\\u005fexecutor\\u005fworkflow"}'}
        ),
        '{"uri":"colameta:\\/\\/review-manifest\\/short"}',
        (
            '{"uri":"colameta:\\u002f\\u002freview-manifest'
            '\\u002fshort"}'
        ),
        "Colameta://review-manifest/opaque_handle_123_",
        "colameta%3A%2F%2Finternal-tool%2Fsecret",
        "colameta%253A%252F%252Finternal-tool%252Fsecret",
        (
            "colameta://review-manifest/opaque_handle_123_"
            "/subjects/1/pages/{page}%20"
            "colameta%3A%2F%2Finternal-tool%2Fsecret"
        ),
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
