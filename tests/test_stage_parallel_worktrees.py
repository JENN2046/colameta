from __future__ import annotations

import subprocess

from runner.mcp_stage_parallel_worktrees import MCPStageParallelWorktreeManager


def _git(project, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=project,
        capture_output=True,
        text=True,
        check=True,
    )


def _init_repo(tmp_path):
    project = tmp_path / "repo"
    project.mkdir()
    _git(project, "init", "-q", "-b", "main")
    (project / "README.md").write_text("demo\n", encoding="utf-8")
    _git(project, "add", "README.md")
    _git(project, "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "init", "-q")
    return project


def test_stage_parallel_worktree_preview_writes_preview_without_creating_worktree(tmp_path) -> None:
    project = _init_repo(tmp_path)
    manager = MCPStageParallelWorktreeManager(str(project))

    result = manager.handle(
        "preview",
        {
            "stage_id": "stage_parallel_dev",
            "task_intents": [
                {"task_id": "one", "title": "One", "allowed_files": ["runner/one.py"]},
            ],
        },
    )

    assert result["ok"] is True
    assert result["action"] == "preview"
    assert result["status"] == "preview_ready"
    assert result["can_apply"] is True
    assert result["side_effect_scope"] == "preview_artifact_only"
    assert result["authority_boundary"]["does_not_create_branch_or_worktree"] is True
    assert result["planned_operations"][0]["branch_name"] == "colameta/stage_parallel_dev/one"
    assert not (project / ".colameta" / "runtime" / "parallel-worktrees").exists()

    status = manager.handle("status", {"preview_id": result["preview_id"]})
    assert status["ok"] is True
    assert status["status"] == "preview_ready"
    assert status["can_apply"] is True
    assert status["confirmation"]["preview_id"] == result["preview_id"]


def test_stage_parallel_worktree_apply_requires_preview_id(tmp_path) -> None:
    project = _init_repo(tmp_path)
    manager = MCPStageParallelWorktreeManager(str(project))

    result = manager.handle("apply", {})

    assert result["ok"] is False
    assert result["error_code"] == "PREVIEW_ID_REQUIRED"


def test_stage_parallel_worktree_apply_creates_isolated_worktree_only(tmp_path) -> None:
    project = _init_repo(tmp_path)
    manager = MCPStageParallelWorktreeManager(str(project))
    preview = manager.handle(
        "preview",
        {
            "stage_id": "stage_parallel_dev",
            "task_intents": [
                {"task_id": "one", "title": "One", "allowed_files": ["runner/one.py"]},
            ],
        },
    )

    result = manager.handle("apply", {"preview_id": preview["preview_id"]})

    assert result["ok"] is True
    assert result["action"] == "apply"
    assert result["status"] == "succeeded"
    assert result["created_count"] == 1
    assert result["authority_boundary"]["does_not_authorize_executor_run"] is True
    assert result["authority_boundary"]["does_not_commit"] is True
    created = result["created_worktrees"][0]
    assert created["branch_name"] == "colameta/stage_parallel_dev/one"
    assert (project / ".colameta" / "runtime" / "parallel-worktrees").exists()
    assert (project / ".git" / "worktrees").exists()
    branch = _git(project, "rev-parse", "--verify", "colameta/stage_parallel_dev/one").stdout.strip()
    main = _git(project, "rev-parse", "--verify", "main").stdout.strip()
    assert branch == main

    status = manager.handle("status", {"preview_id": preview["preview_id"]})
    assert status["ok"] is False
    assert status["error_code"] == "PREVIEW_NOT_FOUND"


def test_stage_parallel_worktree_preview_blocks_dirty_checkout(tmp_path) -> None:
    project = _init_repo(tmp_path)
    (project / "untracked.txt").write_text("dirty\n", encoding="utf-8")
    manager = MCPStageParallelWorktreeManager(str(project))

    result = manager.handle(
        "preview",
        {
            "stage_id": "stage_parallel_dev",
            "task_intents": [
                {"task_id": "one", "title": "One", "allowed_files": ["runner/one.py"]},
            ],
        },
    )

    assert result["ok"] is True
    assert result["status"] == "blocked"
    assert result["can_apply"] is False
    assert "preview_id" not in result
    assert result["blockers"][0]["code"] == "WORKTREE_NOT_CLEAN"
