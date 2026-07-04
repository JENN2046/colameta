from __future__ import annotations

import json
import subprocess

from runner.mcp_stage_parallel_executor_group import MCPStageParallelExecutorGroupManager
from runner.mcp_stage_parallel_worktrees import MCPStageParallelWorktreeManager


def _git(project, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=project,
        capture_output=True,
        text=True,
        check=True,
    )


def _init_managed_repo(tmp_path):
    project = tmp_path / "repo"
    project.mkdir()
    _git(project, "init", "-q", "-b", "main")
    (project / "README.md").write_text("demo\n", encoding="utf-8")
    runner_dir = project / ".colameta"
    runner_dir.mkdir()
    (runner_dir / "plan.json").write_text(
        json.dumps(
            {
                "project_name": "demo",
                "versions": [
                    {
                        "version": "v1",
                        "name": "One",
                        "enabled": True,
                        "allowed_files": ["README.md"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (runner_dir / "state.json").write_text(
        json.dumps(
            {
                "project_name": "demo",
                "status": "READY",
                "current_version": "v1",
                "current_version_index": 0,
                "versions": [{"version": "v1", "name": "One", "status": "PROMPT_READY"}],
            }
        ),
        encoding="utf-8",
    )
    _git(project, "add", "README.md", ".colameta/plan.json", ".colameta/state.json")
    _git(project, "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "init", "-q")
    return project


def _task_intents() -> list[dict[str, object]]:
    return [{"task_id": "one", "title": "One", "allowed_files": ["README.md"]}]


def _create_worktree(project, *, stage_id: str = "stage_parallel_dev") -> dict:
    manager = MCPStageParallelWorktreeManager(str(project))
    preview = manager.handle(
        "preview",
        {
            "stage_id": stage_id,
            "task_intents": _task_intents(),
        },
    )
    assert preview["ok"] is True
    assert preview["status"] == "preview_ready"
    applied = manager.handle("apply", {"preview_id": preview["preview_id"]})
    assert applied["ok"] is True
    return applied["created_worktrees"][0]


def test_stage_parallel_executor_group_preview_blocks_until_worktree_exists(tmp_path) -> None:
    project = _init_managed_repo(tmp_path)
    manager = MCPStageParallelExecutorGroupManager(str(project))

    result = manager.handle(
        "preview",
        {
            "stage_id": "stage_parallel_dev",
            "task_intents": _task_intents(),
        },
    )

    assert result["ok"] is True
    assert result["status"] == "blocked"
    assert result["can_apply"] is False
    assert "preview_id" not in result
    assert result["blockers"][0]["code"] == "WORKTREE_PATH_NOT_FOUND"


def test_stage_parallel_executor_group_preview_writes_group_preview_only(tmp_path) -> None:
    project = _init_managed_repo(tmp_path)
    created = _create_worktree(project)
    worktree_path = created["worktree_path"]
    manager = MCPStageParallelExecutorGroupManager(str(project))

    result = manager.handle(
        "preview",
        {
            "stage_id": "stage_parallel_dev",
            "task_intents": _task_intents(),
            "provider": "codex",
        },
    )

    assert result["ok"] is True
    assert result["status"] == "preview_ready"
    assert result["can_apply"] is True
    assert result["side_effect_scope"] == "preview_artifact_only"
    assert result["authority_boundary"]["does_not_create_executor_preview"] is True
    assert result["planned_operations"][0]["worktree_path"] == worktree_path
    executor_preview_dir = project / ".colameta" / "runtime" / "parallel-worktrees"
    executor_preview_dir = executor_preview_dir / result["parallel_group_id"] / "one" / ".colameta" / "runtime" / "executor-workflow-previews"
    assert list(executor_preview_dir.glob("*.json")) == []

    status = manager.handle("status", {"preview_id": result["preview_id"]})
    assert status["ok"] is True
    assert status["status"] == "preview_ready"
    assert status["confirmation"]["preview_id"] == result["preview_id"]


def test_stage_parallel_executor_group_apply_creates_executor_previews_without_runs(tmp_path) -> None:
    project = _init_managed_repo(tmp_path)
    created = _create_worktree(project)
    worktree_path = created["worktree_path"]
    manager = MCPStageParallelExecutorGroupManager(str(project))
    preview = manager.handle(
        "preview",
        {
            "stage_id": "stage_parallel_dev",
            "task_intents": _task_intents(),
            "provider": "codex",
        },
    )

    result = manager.handle("apply", {"preview_id": preview["preview_id"]})

    assert result["ok"] is True
    assert result["action"] == "apply"
    assert result["status"] == "succeeded"
    assert result["created_count"] == 1
    assert result["side_effect_scope"] == "executor_preview_artifacts_only"
    assert result["authority_boundary"]["does_not_authorize_executor_run"] is True
    assert result["authority_boundary"]["does_not_commit"] is True
    executor_preview = result["created_executor_previews"][0]
    preview_id = executor_preview["executor_preview_id"]
    preview_file = (
        project
        / ".colameta"
        / "runtime"
        / "parallel-worktrees"
        / preview["parallel_group_id"]
        / "one"
        / ".colameta"
        / "runtime"
        / "executor-workflow-previews"
        / f"{preview_id}.json"
    )
    assert preview_file.is_file()
    claim_dir = preview_file.parent / "claims"
    assert not claim_dir.exists() or list(claim_dir.glob("*.json")) == []
    assert executor_preview["worktree_path"] == worktree_path

    status = manager.handle("status", {"preview_id": preview["preview_id"]})
    assert status["ok"] is False
    assert status["error_code"] == "PREVIEW_NOT_FOUND"


def test_stage_parallel_executor_group_apply_requires_preview_id(tmp_path) -> None:
    project = _init_managed_repo(tmp_path)
    manager = MCPStageParallelExecutorGroupManager(str(project))

    result = manager.handle("apply", {})

    assert result["ok"] is False
    assert result["error_code"] == "PREVIEW_ID_REQUIRED"
