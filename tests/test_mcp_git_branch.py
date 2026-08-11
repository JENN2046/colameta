from __future__ import annotations

import copy
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from runner.commander_contract import validate_commander_response
from runner.mcp_commander_public import COMMANDER_EXPOSED_TOOLS
from runner.mcp_git_branch import MCPGitBranchManager
from runner.mcp_server import MCPPlanningBridgeServer
from runner.project_context_binding import collect_project_context_binding
from runner.project_registry import ProjectRegistry


PROJECT_NAME = "branch-admission-project"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _repo(tmp_path: Path, *, branch: str = "main") -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("baseline\n", encoding="utf-8")
    (repo / ".gitignore").write_text(".colameta/runtime/**\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "add", ".gitignore")
    _git(repo, "commit", "-m", "baseline")
    _git(repo, "branch", "-M", branch)
    return repo


def _dirty_repo(repo: Path) -> None:
    (repo / "README.md").write_text("unstaged change\n", encoding="utf-8")
    (repo / "staged.txt").write_text("staged change\n", encoding="utf-8")
    _git(repo, "add", "staged.txt")
    (repo / "untracked.txt").write_text("untracked change\n", encoding="utf-8")


def test_topic_branch_preview_and_apply_preserve_complete_worktree(tmp_path) -> None:
    repo = _repo(tmp_path)
    _dirty_repo(repo)
    manager = MCPGitBranchManager(str(repo))
    branch_before = _git(repo, "branch", "--show-current")
    head_before = _git(repo, "rev-parse", "HEAD")
    status_before = _git(repo, "status", "--porcelain=v1", "--untracked-files=all")
    contents_before = {
        path: (repo / path).read_bytes()
        for path in ("README.md", "staged.txt", "untracked.txt")
    }

    preview = manager.topic_branch_preview("codex/delivery-test")

    assert preview["ok"] is True
    assert preview["requires_confirmation"] is True
    assert preview["working_tree_preserved_on_apply"] is True
    assert preview["expires_at"]
    assert _git(repo, "branch", "--show-current") == branch_before
    assert _git(repo, "rev-parse", "HEAD") == head_before
    assert _git(repo, "status", "--porcelain=v1", "--untracked-files=all") == status_before

    applied = manager.topic_branch_apply(preview["preview_id"])

    assert applied["ok"] is True
    assert applied["preview_consumed"] is True
    assert applied["source_branch"] == "main"
    assert applied["current_branch"] == "codex/delivery-test"
    assert applied["head_before"] == applied["head_after"] == head_before
    assert applied["working_tree_fingerprint_before"] == applied[
        "working_tree_fingerprint_after"
    ]
    assert _git(repo, "status", "--porcelain=v1", "--untracked-files=all") == status_before
    assert {
        path: (repo / path).read_bytes()
        for path in ("README.md", "staged.txt", "untracked.txt")
    } == contents_before
    replay = manager.topic_branch_apply(preview["preview_id"])
    assert replay["ok"] is False
    assert replay["error_code"] == "PREVIEW_CONSUMED"
    assert _git(repo, "branch", "--show-current") == "codex/delivery-test"


@pytest.mark.parametrize(
    ("branch_name", "error_code"),
    [
        ("not codex", "INVALID_TOPIC_BRANCH"),
        ("feature/delivery", "TOPIC_BRANCH_NOT_DELIVERY_SAFE"),
        ("main", "TOPIC_BRANCH_NOT_DELIVERY_SAFE"),
    ],
)
def test_topic_branch_preview_rejects_invalid_or_disallowed_target(
    tmp_path,
    branch_name: str,
    error_code: str,
) -> None:
    manager = MCPGitBranchManager(str(_repo(tmp_path)))

    result = manager.topic_branch_preview(branch_name)

    assert result["ok"] is False
    assert result["error_code"] == error_code


def test_topic_branch_preview_rejects_existing_target(tmp_path) -> None:
    repo = _repo(tmp_path)
    _git(repo, "branch", "codex/delivery-existing")

    result = MCPGitBranchManager(str(repo)).topic_branch_preview(
        "codex/delivery-existing"
    )

    assert result["error_code"] == "TOPIC_BRANCH_ALREADY_EXISTS"


def test_topic_branch_preview_rejects_delivery_safe_source(tmp_path) -> None:
    repo = _repo(tmp_path, branch="codex/already-safe")

    result = MCPGitBranchManager(str(repo)).topic_branch_preview(
        "codex/delivery-unneeded"
    )

    assert result["error_code"] == "SOURCE_BRANCH_ALREADY_DELIVERY_SAFE"


def test_topic_branch_preview_rejects_detached_head(tmp_path) -> None:
    repo = _repo(tmp_path)
    _git(repo, "checkout", "--detach")

    result = MCPGitBranchManager(str(repo)).topic_branch_preview(
        "codex/delivery-detached"
    )

    assert result["error_code"] == "DETACHED_HEAD"


def test_topic_branch_preview_rejects_git_operation_in_progress(tmp_path) -> None:
    repo = _repo(tmp_path)
    marker = Path(_git(repo, "rev-parse", "--git-path", "MERGE_HEAD"))
    if not marker.is_absolute():
        marker = repo / marker
    marker.write_text(_git(repo, "rev-parse", "HEAD") + "\n", encoding="utf-8")

    result = MCPGitBranchManager(str(repo)).topic_branch_preview(
        "codex/delivery-operation"
    )

    assert result["error_code"] == "GIT_OPERATION_IN_PROGRESS"


@pytest.mark.parametrize(
    ("drift", "error_code"),
    [
        ("head", "SOURCE_HEAD_DRIFT"),
        ("branch", "SOURCE_BRANCH_DRIFT"),
        ("tracked", "WORKING_TREE_DRIFT"),
        ("staged", "WORKING_TREE_DRIFT"),
        ("untracked", "WORKING_TREE_DRIFT"),
    ],
)
def test_topic_branch_apply_rejects_preview_drift(
    tmp_path,
    drift: str,
    error_code: str,
) -> None:
    repo = _repo(tmp_path)
    if drift == "untracked":
        (repo / "untracked.txt").write_text("before\n", encoding="utf-8")
    manager = MCPGitBranchManager(str(repo))
    preview = manager.topic_branch_preview(f"codex/delivery-{drift}")
    assert preview["ok"] is True

    if drift == "head":
        (repo / "head.txt").write_text("head drift\n", encoding="utf-8")
        _git(repo, "add", "head.txt")
        _git(repo, "commit", "-m", "head drift")
    elif drift == "branch":
        _git(repo, "switch", "-c", "other-branch")
    elif drift == "tracked":
        (repo / "README.md").write_text("tracked drift\n", encoding="utf-8")
    elif drift == "staged":
        (repo / "staged.txt").write_text("staged drift\n", encoding="utf-8")
        _git(repo, "add", "staged.txt")
    else:
        (repo / "untracked.txt").write_text("after\n", encoding="utf-8")

    result = manager.topic_branch_apply(preview["preview_id"])

    assert result["ok"] is False
    assert result["error_code"] == error_code
    assert _git(repo, "branch", "--show-current") != f"codex/delivery-{drift}"


def test_topic_branch_apply_rejects_expired_and_target_created_after_preview(
    tmp_path,
) -> None:
    repo = _repo(tmp_path)
    manager = MCPGitBranchManager(str(repo))
    expired = manager.topic_branch_preview("codex/delivery-expired")
    preview_path = Path(manager.preview_dir) / f"{expired['preview_id']}.json"
    payload = json.loads(preview_path.read_text(encoding="utf-8"))
    payload["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    preview_path.write_text(json.dumps(payload), encoding="utf-8")
    assert manager.topic_branch_apply(expired["preview_id"])["error_code"] == "PREVIEW_EXPIRED"

    existing = manager.topic_branch_preview("codex/delivery-late-existing")
    _git(repo, "branch", "codex/delivery-late-existing")
    result = manager.topic_branch_apply(existing["preview_id"])
    assert result["error_code"] == "TOPIC_BRANCH_ALREADY_EXISTS"


def test_topic_branch_apply_rejects_git_operation_started_after_preview(
    tmp_path,
) -> None:
    repo = _repo(tmp_path)
    manager = MCPGitBranchManager(str(repo))
    preview = manager.topic_branch_preview("codex/delivery-operation-drift")
    marker = Path(_git(repo, "rev-parse", "--git-path", "CHERRY_PICK_HEAD"))
    if not marker.is_absolute():
        marker = repo / marker
    marker.write_text(_git(repo, "rev-parse", "HEAD") + "\n", encoding="utf-8")

    result = manager.topic_branch_apply(preview["preview_id"])

    assert result["error_code"] == "GIT_OPERATION_IN_PROGRESS"


@pytest.mark.parametrize("dirty", [False, True])
def test_commander_manage_git_topic_branch_confirmation_and_continuation(
    tmp_path,
    dirty: bool,
) -> None:
    repo = _repo(tmp_path)
    if dirty:
        (repo / "README.md").write_text("accepted change\n", encoding="utf-8")
    registry = ProjectRegistry(
        registry_path=str(tmp_path / "projects.json"),
        user_settings_path=str(tmp_path / "settings.json"),
    )
    assert registry.register_project(
        str(repo),
        project_name=PROJECT_NAME,
        project_mode="managed",
    )["ok"] is True
    server = MCPPlanningBridgeServer(
        str(repo),
        service_mode=True,
        exposure_profile="commander",
    )
    server.project_registry = registry
    assert tuple(
        tool.name
        for tool in server._filter_tools_by_exposure_profile(server.tool_defs)
    ) == COMMANDER_EXPOSED_TOOLS
    assert len(COMMANDER_EXPOSED_TOOLS) == 9
    assert server.get_required_scope_for_tool(
        "manage_git",
        {"action": "topic_branch_preview"},
    ) == "mcp:preview"
    assert server.get_required_scope_for_tool(
        "manage_git",
        {"action": "topic_branch_apply"},
    ) == "mcp:commit"
    binding = collect_project_context_binding(
        str(repo),
        project_name=PROJECT_NAME,
        review_unit="operation:git_topic_branch",
        workflow_intent="git_topic_branch",
    )

    preview = server._call_tool(
        "manage_git",
        {
            "action": "topic_branch_preview",
            "branch_name": "codex/delivery-commander",
            "project_name": PROJECT_NAME,
            "context_binding": binding,
        },
    )

    assert "data" in preview, preview
    validate_commander_response(preview["data"])
    assert preview["data"]["outcome"] == "confirmation_required"
    assert preview["data"]["next_action"]["tool"] == "manage_git"
    apply_arguments = preview["data"]["next_action"]["arguments"]
    assert apply_arguments["action"] == "topic_branch_apply"
    assert apply_arguments["context_binding"]["branch"] == "main"
    head_before = _git(repo, "rev-parse", "HEAD")

    applied = server._call_tool("manage_git", apply_arguments)

    validate_commander_response(applied["data"])
    assert _git(repo, "branch", "--show-current") == "codex/delivery-commander"
    assert _git(repo, "rev-parse", "HEAD") == head_before
    next_action = applied["data"]["next_action"]
    assert next_action["tool"] == "manage_git"
    assert next_action["arguments"]["action"] == (
        "commit_readiness" if dirty else "push_status"
    )
    assert next_action["arguments"]["context_binding"]["branch"] == (
        "codex/delivery-commander"
    )


def test_commander_topic_branch_apply_rejects_wrong_context_binding(tmp_path) -> None:
    repo = _repo(tmp_path)
    registry = ProjectRegistry(
        registry_path=str(tmp_path / "projects.json"),
        user_settings_path=str(tmp_path / "settings.json"),
    )
    assert registry.register_project(
        str(repo),
        project_name=PROJECT_NAME,
        project_mode="managed",
    )["ok"] is True
    server = MCPPlanningBridgeServer(
        str(repo),
        service_mode=True,
        exposure_profile="commander",
    )
    server.project_registry = registry
    binding = collect_project_context_binding(
        str(repo),
        project_name=PROJECT_NAME,
        review_unit="operation:git_topic_branch",
        workflow_intent="git_topic_branch",
    )
    preview = server._call_tool(
        "manage_git",
        {
            "action": "topic_branch_preview",
            "branch_name": "codex/delivery-context-bound",
            "project_name": PROJECT_NAME,
            "context_binding": binding,
        },
    )
    apply_arguments = copy.deepcopy(preview["data"]["next_action"]["arguments"])
    apply_arguments["context_binding"]["head"] = "0" * 40

    rejected = server._call_tool("manage_git", apply_arguments)

    assert rejected["ok"] is False
    assert rejected["error_code"] == "CONTEXT_BINDING_MISMATCH"
    assert _git(repo, "branch", "--show-current") == "main"
