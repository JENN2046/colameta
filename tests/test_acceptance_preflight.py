from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import runner.acceptance_command_policy as acceptance_policy
from runner.executor_run_workflow import ExecutorRunOnceService
from runner.mcp_runner_plan import MCPRunnerPlanManager
from runner.mcp_server import MCPPlanningBridgeServer
from runner.planning_bridge import PlanningBridge, PlanningBridgeError


def _git(repo: Path, *args: str) -> None:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def _managed_repo(tmp_path: Path, command: str) -> Path:
    repo = tmp_path / "repo"
    runner_dir = repo / ".colameta"
    prompts_dir = runner_dir / "prompts"
    prompts_dir.mkdir(parents=True)
    plan = {
        "project_name": "demo",
        "project_root": str(repo),
        "versions": [
            {
                "version": "v1",
                "name": "Acceptance policy",
                "prompt_file": ".colameta/prompts/v1.md",
                "enabled": True,
                "allowed_files": ["runner/**"],
                "acceptance_commands": [
                    {
                        "command": command,
                        "timeout_seconds": 120,
                        "continue_on_failure": False,
                    }
                ],
            }
        ],
    }
    state = {"current_version": "v1", "current_version_index": 0, "status": "NOT_STARTED"}
    (runner_dir / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    (runner_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
    (prompts_dir / "v1.md").write_text("proof\n", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "tests@example.invalid")
    _git(repo, "config", "user.name", "ColaMeta Tests")
    _git(repo, "add", ".colameta/plan.json", ".colameta/prompts/v1.md")
    _git(repo, "commit", "-qm", "initial")
    return repo


def _force_user_owned_external_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    runtime = tmp_path / "external-python"
    runtime.write_text("not executed\n", encoding="utf-8")
    runtime.chmod(0o700)
    monkeypatch.setattr(acceptance_policy, "_DISALLOWED_TEMP_ROOTS", ())
    monkeypatch.setattr(
        acceptance_policy,
        "_path_components",
        lambda path: [path],
    )
    monkeypatch.setattr(acceptance_policy.sys, "executable", str(runtime))
    monkeypatch.setattr(acceptance_policy.sys, "_base_executable", str(runtime))
    return runtime


def test_preflight_blocks_current_unsafe_acceptance_command(tmp_path: Path) -> None:
    repo = _managed_repo(tmp_path, 'test -z "$(git status --porcelain=v1)"')

    result = ExecutorRunOnceService(str(repo)).preflight(provider="codex")

    assert result["preflight_blocked"] is True
    assert "ACCEPTANCE_COMMAND_NOT_EXECUTABLE" in {
        block["code"] for block in result["blocks"]
    }


def test_preflight_accepts_shell_free_current_command(tmp_path: Path) -> None:
    repo = _managed_repo(tmp_path, "git diff --check")

    result = ExecutorRunOnceService(str(repo)).preflight(provider="codex")

    assert "ACCEPTANCE_COMMAND_NOT_EXECUTABLE" not in {
        block["code"] for block in result["blocks"]
    }


def test_preflight_blocks_untrusted_executable_path(tmp_path: Path) -> None:
    repo = _managed_repo(tmp_path, "/tmp/python --version")

    result = ExecutorRunOnceService(str(repo)).preflight(provider="codex")

    blockers = [
        block for block in result["blocks"]
        if block["code"] == "ACCEPTANCE_COMMAND_NOT_EXECUTABLE"
    ]
    assert len(blockers) == 1
    assert "ACCEPTANCE_COMMAND_EXECUTABLE_PATH_NOT_TRUSTED" in blockers[0]["message"]


def test_plan_preview_normalization_rejects_unsafe_new_command(tmp_path: Path) -> None:
    manager = MCPRunnerPlanManager(str(tmp_path))
    blockers: list[str] = []

    normalized = manager._normalize_acceptance_commands(
        ['test -z "$(git status --porcelain=v1)"'],
        blockers=blockers,
    )

    assert normalized == []
    assert blockers == [
        "acceptance_command_not_executable_0_acceptance_command_shell_operator"
    ]


def test_plan_preview_normalization_rejects_clean_worktree_helper(
    tmp_path: Path,
) -> None:
    script = tmp_path / "scripts" / "check_clean_worktree.py"
    script.parent.mkdir()
    script.write_text("raise SystemExit(0)\n", encoding="utf-8")
    manager = MCPRunnerPlanManager(str(tmp_path))
    blockers: list[str] = []

    normalized = manager._normalize_acceptance_commands(
        ["python3 scripts/check_clean_worktree.py"],
        blockers=blockers,
    )

    assert normalized == []
    assert blockers == [
        "acceptance_command_not_executable_0_"
        "acceptance_command_python_grammar_not_allowed"
    ]


def test_plan_preview_normalization_rejects_untrusted_executable_path(
    tmp_path: Path,
) -> None:
    manager = MCPRunnerPlanManager(str(tmp_path))
    blockers: list[str] = []

    normalized = manager._normalize_acceptance_commands(
        ["/tmp/python --version"],
        blockers=blockers,
    )

    assert normalized == []
    assert blockers == [
        "acceptance_command_not_executable_0_"
        "acceptance_command_executable_path_not_trusted"
    ]


def test_plan_preview_normalization_rejects_user_owned_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _force_user_owned_external_runtime(tmp_path, monkeypatch)
    project = tmp_path / "project"
    project.mkdir()
    manager = MCPRunnerPlanManager(str(project))
    blockers: list[str] = []

    normalized = manager._normalize_acceptance_commands(
        ["python3 --version"],
        blockers=blockers,
    )

    assert normalized == []
    assert blockers == [
        "acceptance_command_not_executable_0_"
        "acceptance_command_executable_owner_not_trusted"
    ]


def _write_managed_plan(project: Path) -> dict:
    runner_dir = project / ".colameta"
    runner_dir.mkdir(parents=True)
    plan = {
        "versions": [
            {
                "version": "v1",
                "name": "Existing",
                "description": "existing version",
                "prompt_file": ".colameta/prompts/v1.md",
                "enabled": True,
                "allowed_files": ["runner/**"],
                "acceptance_commands": ["git diff --check"],
            }
        ]
    }
    (runner_dir / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    return plan


def _insert_params(command: str) -> dict:
    return {
        "action": "insert_preview",
        "insert_after": "v1",
        "version": "v2",
        "name": "Policy parity",
        "description": "exercise the real MCP insert route",
        "prompt": "Implement policy parity.",
        "allowed_files": ["runner/**"],
        "acceptance_commands": [command],
    }


@pytest.mark.parametrize(
    ("action", "command"),
    [
        ("insert_preview", "git diff --check && git status"),
        ("insert_preview", 'test -z "$(git status --porcelain)"'),
        ("insert_preview", "/tmp/python --version"),
        ("insert_preview", "python3 -c pass"),
        ("insert_preview", "python3 -m compileall -q runner"),
        ("insert_preview", "python3 -I -m compileall -q runner"),
        ("insert_preview", "python3 scripts/check_clean_worktree.py"),
        ("insert_preview", "node --eval console.log(1)"),
        ("insert_preview", "npm test"),
        ("insert_preview", "make test"),
        ("update_preview", "git diff --check && git status"),
        ("update_preview", 'test -z "$(git status --porcelain)"'),
        ("update_preview", "project-controlled/python --version"),
        ("update_preview", "python3 -m compileall -q runner"),
        ("update_preview", "python3 /tmp/external.py"),
        ("update_preview", "python3 scripts/check_clean_worktree.py"),
        ("update_preview", "npx pytest"),
        ("update_preview", "go test ./..."),
        ("update_preview", "cargo test"),
    ],
)
def test_real_mcp_plan_version_preview_rejects_unsafe_acceptance_commands(
    tmp_path: Path,
    action: str,
    command: str,
) -> None:
    project = tmp_path / "project"
    _write_managed_plan(project)
    server = MCPPlanningBridgeServer(str(project))
    params = (
        _insert_params(command)
        if action == "insert_preview"
        else {
            "action": "update_preview",
            "version": "v1",
            "acceptance_commands": [command],
        }
    )

    result = server.call_tool_for_agent("manage_plan_version", params)

    assert result["ok"] is False
    assert result["error_code"] == "ACCEPTANCE_COMMAND_NOT_EXECUTABLE"
    assert command not in json.dumps(result)
    assert not list((project / ".colameta" / "plan-patches").glob("*.json"))


@pytest.mark.parametrize("action", ["insert_preview", "update_preview"])
def test_real_mcp_plan_version_preview_accepts_exact_git_diff_command(
    tmp_path: Path,
    action: str,
) -> None:
    project = tmp_path / "project"
    _write_managed_plan(project)
    server = MCPPlanningBridgeServer(str(project))
    params = (
        _insert_params("git diff --check")
        if action == "insert_preview"
        else {
            "action": "update_preview",
            "version": "v1",
            "acceptance_commands": ["git diff --check"],
        }
    )

    result = server.call_tool_for_agent("manage_plan_version", params)

    assert result["ok"] is True
    assert result["data"]["ok"] is True
    assert result["data"]["patch_id"]


def test_planning_bridge_preview_uses_same_acceptance_policy(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _write_managed_plan(project)
    bridge = PlanningBridge()

    with pytest.raises(PlanningBridgeError) as error:
        bridge.preview_insert_version(
            str(project),
            {
                **_insert_params("/tmp/private-python --version"),
                "action": "unused-by-bridge",
            },
        )

    assert str(error.value).startswith("ACCEPTANCE_COMMAND_NOT_EXECUTABLE:")
    assert "/tmp/private-python" not in str(error.value)


@pytest.mark.parametrize("action", ["insert_preview", "update_preview"])
def test_planning_bridge_previews_reject_user_owned_runtime_with_parity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
) -> None:
    project = tmp_path / "project"
    _write_managed_plan(project)
    _force_user_owned_external_runtime(tmp_path, monkeypatch)
    bridge = PlanningBridge()

    with pytest.raises(PlanningBridgeError) as error:
        if action == "insert_preview":
            bridge.preview_insert_version(
                str(project),
                _insert_params("python3 --version"),
            )
        else:
            bridge.preview_update_version(
                str(project),
                {
                    "version": "v1",
                    "acceptance_commands": ["python3 --version"],
                },
            )

    assert error.value.error_code == "ACCEPTANCE_COMMAND_NOT_EXECUTABLE"
    assert "ACCEPTANCE_COMMAND_EXECUTABLE_OWNER_NOT_TRUSTED" in str(error.value)


def test_bootstrap_preview_rejects_unsafe_acceptance_command(tmp_path: Path) -> None:
    result = MCPRunnerPlanManager(str(tmp_path)).bootstrap_preview(
        project_name="demo",
        goal="Add the first governed version",
        first_version="v1",
        first_version_name="First",
        first_version_prompt="Implement the version.",
        allowed_files=["runner/**"],
        acceptance_commands=["git diff --check && git status"],
    )

    assert result["can_apply"] is False
    assert any(
        blocker.endswith("acceptance_command_shell_operator")
        for blocker in result["blockers"]
    )


def test_real_mcp_runner_import_preview_rejects_unsafe_plan_command(
    tmp_path: Path,
) -> None:
    plan = _write_managed_plan(tmp_path)
    plan["versions"][0]["acceptance_commands"] = ["/tmp/private-python --version"]
    server = MCPPlanningBridgeServer(str(tmp_path))

    result = server.call_tool_for_agent(
        "manage_runner_plan",
        {"action": "import_preview", "plan_json": json.dumps(plan)},
    )

    assert result["ok"] is True
    preview = result["data"]
    assert preview["can_apply"] is False
    assert any(
        "acceptance_command_executable_path_not_trusted" in blocker
        for blocker in preview["blockers"]
    )
    assert "/tmp/private-python" not in json.dumps(preview["blockers"])


def test_real_mcp_runner_import_preview_rejects_user_owned_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    plan = _write_managed_plan(project)
    plan["versions"][0]["acceptance_commands"] = ["python3 --version"]
    _force_user_owned_external_runtime(tmp_path, monkeypatch)

    result = MCPRunnerPlanManager(str(project)).import_preview(json.dumps(plan))

    assert result["can_apply"] is False
    assert any(
        "acceptance_command_executable_owner_not_trusted" in blocker
        for blocker in result["blockers"]
    )


def test_real_mcp_runner_apply_revalidates_preview_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    manager = MCPRunnerPlanManager(str(project))
    preview = manager.bootstrap_preview(
        project_name="demo",
        goal="Add the first governed version",
        first_version="v1",
        first_version_name="First",
        first_version_prompt="Implement the version.",
        allowed_files=["runner/**"],
        acceptance_commands=["git diff --check"],
    )
    assert preview["can_apply"] is True, preview
    _force_user_owned_external_runtime(tmp_path, monkeypatch)
    preview_path = project / preview["preview_file"]
    payload = json.loads(preview_path.read_text(encoding="utf-8"))
    payload["plan_data"]["versions"][0]["acceptance_commands"][0][
        "command"
    ] = "python3 --version"
    payload["can_apply"] = True
    preview_path.write_text(json.dumps(payload), encoding="utf-8")
    server = MCPPlanningBridgeServer(str(project))

    result = server.call_tool_for_agent(
        "manage_runner_plan",
        {"action": "apply", "preview_id": preview["preview_id"]},
    )

    assert result["ok"] is True
    apply_result = result["data"]
    assert apply_result["ok"] is False
    assert apply_result["error_code"] == "ACCEPTANCE_COMMAND_NOT_EXECUTABLE"
    assert not (project / ".colameta" / "plan.json").exists()


@pytest.mark.parametrize("operation", ["insert_version", "update_version"])
def test_real_mcp_plan_version_apply_revalidates_legacy_patch_policy(
    tmp_path: Path,
    operation: str,
) -> None:
    project = tmp_path / "project"
    original_plan = _write_managed_plan(project)
    bridge = PlanningBridge()
    paths = bridge._paths(str(project))
    patch_id = f"legacy-{operation}"
    patch_payload = {
        "patch_id": patch_id,
        "operation": operation,
        "project_root": str(project),
        "project_path": str(project),
        "base_plan_signature": bridge._file_signature(paths.plan_file),
    }
    if operation == "insert_version":
        patch_payload["spec"] = {
            **_insert_params("/tmp/private-python --version"),
            "action": "unused-by-bridge",
        }
    else:
        patch_payload["version"] = "v1"
        patch_payload["updates"] = {
            "acceptance_commands": ["/tmp/private-python --version"]
        }
    patch_dir = project / ".colameta" / "plan-patches"
    patch_dir.mkdir()
    (patch_dir / f"{patch_id}.json").write_text(
        json.dumps(patch_payload),
        encoding="utf-8",
    )
    server = MCPPlanningBridgeServer(str(project))

    result = server.call_tool_for_agent(
        "manage_plan_version",
        {"action": "apply_preview", "patch_id": patch_id},
    )

    assert result["ok"] is True
    apply_result = result["data"]
    assert apply_result["ok"] is False
    assert apply_result["error_code"] == "ACCEPTANCE_COMMAND_NOT_EXECUTABLE"
    assert "/tmp/private-python" not in json.dumps(apply_result)
    assert json.loads((project / ".colameta" / "plan.json").read_text()) == original_plan


def test_plan_patch_batch_apply_revalidates_legacy_policy(tmp_path: Path) -> None:
    project = tmp_path / "project"
    original_plan = _write_managed_plan(project)
    bridge = PlanningBridge()
    paths = bridge._paths(str(project))
    patch_id = "legacy-batch-policy"
    patch_payload = {
        "patch_id": patch_id,
        "operation": "update_version",
        "created_at": "2026-08-24T00:00:00+00:00",
        "project_root": str(project),
        "project_path": str(project),
        "base_plan_signature": bridge._file_signature(paths.plan_file),
        "version": "v1",
        "updates": {
            "acceptance_commands": ["/tmp/private-python --version"]
        },
    }
    patch_dir = project / ".colameta" / "plan-patches"
    patch_dir.mkdir()
    (patch_dir / f"{patch_id}.json").write_text(
        json.dumps(patch_payload),
        encoding="utf-8",
    )

    result = bridge.auto_apply_pending_plan_patches(str(project))

    assert result["applied_count"] == 0
    assert result["failed_count"] == 1
    assert result["results"][0]["error_code"] == (
        "ACCEPTANCE_COMMAND_NOT_EXECUTABLE"
    )
    assert "/tmp/private-python" not in json.dumps(result)
    assert json.loads((project / ".colameta" / "plan.json").read_text()) == original_plan
