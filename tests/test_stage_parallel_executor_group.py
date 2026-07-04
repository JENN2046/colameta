from __future__ import annotations

import json
import subprocess

from runner.executor_run_reports import ExecutorRunReportStore
from runner.mcp_executor_workflow import MCPExecutorWorkflowManager
from runner.mcp_stage_parallel_executor_group import MCPStageParallelExecutorGroupManager
from runner.mcp_stage_parallel_executor_runs import MCPStageParallelExecutorRunGroupManager
from runner.mcp_stage_parallel_worktrees import MCPStageParallelWorktreeManager
from runner.stage_parallel_executor_results import build_stage_parallel_executor_results_packet


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


def _create_executor_preview(project, *, stage_id: str = "stage_parallel_dev") -> dict:
    _create_worktree(project, stage_id=stage_id)
    manager = MCPStageParallelExecutorGroupManager(str(project))
    preview = manager.handle(
        "preview",
        {
            "stage_id": stage_id,
            "task_intents": _task_intents(),
            "provider": "codex",
        },
    )
    assert preview["ok"] is True
    assert preview["status"] == "preview_ready"
    applied = manager.handle("apply", {"preview_id": preview["preview_id"]})
    assert applied["ok"] is True
    return applied["created_executor_previews"][0]


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


def test_stage_parallel_executor_runs_preview_blocks_until_executor_preview_exists(tmp_path) -> None:
    project = _init_managed_repo(tmp_path)
    _create_worktree(project)
    manager = MCPStageParallelExecutorRunGroupManager(str(project))

    result = manager.handle(
        "preview",
        {
            "stage_id": "stage_parallel_dev",
            "task_intents": _task_intents(),
            "provider": "codex",
        },
    )

    assert result["ok"] is True
    assert result["status"] == "blocked"
    assert result["can_apply"] is False
    assert result["blockers"][0]["code"] == "EXECUTOR_PREVIEW_NOT_FOUND"


def test_stage_parallel_executor_runs_preview_writes_group_preview_without_claiming(tmp_path) -> None:
    project = _init_managed_repo(tmp_path)
    created = _create_executor_preview(project)
    manager = MCPStageParallelExecutorRunGroupManager(str(project))

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
    assert result["side_effect_scope"] == "preview_artifact_only"
    assert result["authority_boundary"]["does_not_start_executor"] is True
    assert result["planned_operations"][0]["executor_preview_id"] == created["executor_preview_id"]
    claim_file = (
        project
        / ".colameta"
        / "runtime"
        / "parallel-worktrees"
        / result["parallel_group_id"]
        / "one"
        / ".colameta"
        / "runtime"
        / "executor-workflow-previews"
        / "claims"
        / f"{created['executor_preview_id']}.json"
    )
    assert not claim_file.exists()

    status = manager.handle("status", {"preview_id": result["preview_id"]})
    assert status["ok"] is True
    assert status["status"] == "preview_ready"
    assert status["confirmation"]["preview_id"] == result["preview_id"]


def test_stage_parallel_executor_runs_apply_starts_claims_without_merge_or_push(tmp_path, monkeypatch) -> None:
    project = _init_managed_repo(tmp_path)
    created = _create_executor_preview(project)
    manager = MCPStageParallelExecutorRunGroupManager(str(project))
    preview = manager.handle(
        "preview",
        {
            "stage_id": "stage_parallel_dev",
            "task_intents": _task_intents(),
            "provider": "codex",
        },
    )
    started_calls = []

    def fake_start(self, **kwargs):
        started_calls.append({"project_root": self.project_root, **kwargs})

    monkeypatch.setattr(MCPExecutorWorkflowManager, "_start_run_once_background_worker", fake_start)

    result = manager.handle("apply", {"preview_id": preview["preview_id"]})

    assert result["ok"] is True
    assert result["action"] == "apply"
    assert result["status"] == "started"
    assert result["started_count"] == 1
    assert result["authority_boundary"]["starts_executor_runs_on_apply"] is True
    assert result["authority_boundary"]["does_not_commit_to_main"] is True
    assert result["authority_boundary"]["does_not_push"] is True
    assert result["started_executor_runs"][0]["executor_preview_id"] == created["executor_preview_id"]
    assert started_calls
    claim_file = (
        project
        / ".colameta"
        / "runtime"
        / "parallel-worktrees"
        / preview["parallel_group_id"]
        / "one"
        / ".colameta"
        / "runtime"
        / "executor-workflow-previews"
        / "claims"
        / f"{created['executor_preview_id']}.json"
    )
    claim = json.loads(claim_file.read_text(encoding="utf-8"))
    assert claim["status"] == "RUNNING"
    assert claim["preview_id"] == created["executor_preview_id"]

    status = manager.handle("status", {"preview_id": preview["preview_id"]})
    assert status["ok"] is False
    assert status["error_code"] == "PREVIEW_NOT_FOUND"


def test_stage_parallel_executor_runs_apply_requires_preview_id(tmp_path) -> None:
    project = _init_managed_repo(tmp_path)
    manager = MCPStageParallelExecutorRunGroupManager(str(project))

    result = manager.handle("apply", {})

    assert result["ok"] is False
    assert result["error_code"] == "PREVIEW_ID_REQUIRED"


def test_stage_parallel_executor_results_packet_reports_planned_preview(tmp_path) -> None:
    project = _init_managed_repo(tmp_path)
    _create_executor_preview(project)

    result = build_stage_parallel_executor_results_packet(
        project_root=str(project),
        stage_id="stage_parallel_dev",
        task_intents=_task_intents(),
        provider="codex",
    )

    assert result["ok"] is True
    assert result["read_only"] is True
    assert result["authority_boundary"]["does_not_read_raw_logs"] is True
    assert result["result_summary"]["planned"] == 1
    assert result["executor_results"][0]["status"] == "planned"
    assert result["executor_results"][0]["validation_status"] == "not_run"
    assert result["group_status_preview"]["status"] == "waiting_for_executor_results"


def test_stage_parallel_executor_results_packet_reports_running_claim(tmp_path, monkeypatch) -> None:
    project = _init_managed_repo(tmp_path)
    _create_executor_preview(project)
    run_manager = MCPStageParallelExecutorRunGroupManager(str(project))
    preview = run_manager.handle(
        "preview",
        {
            "stage_id": "stage_parallel_dev",
            "task_intents": _task_intents(),
            "provider": "codex",
        },
    )

    monkeypatch.setattr(MCPExecutorWorkflowManager, "_start_run_once_background_worker", lambda self, **kwargs: None)
    started = run_manager.handle("apply", {"preview_id": preview["preview_id"]})
    assert started["ok"] is True

    result = build_stage_parallel_executor_results_packet(
        project_root=str(project),
        stage_id="stage_parallel_dev",
        task_intents=_task_intents(),
        provider="codex",
    )

    assert result["result_summary"]["running"] == 1
    assert result["executor_results"][0]["status"] == "running"
    assert result["executor_results"][0]["validation_status"] == "running"
    assert result["group_status_preview"]["status"] == "waiting_for_executor_results"


def test_stage_parallel_executor_results_packet_reports_completed_validated_report(tmp_path, monkeypatch) -> None:
    project = _init_managed_repo(tmp_path)
    _create_executor_preview(project)
    run_manager = MCPStageParallelExecutorRunGroupManager(str(project))
    preview = run_manager.handle(
        "preview",
        {
            "stage_id": "stage_parallel_dev",
            "task_intents": _task_intents(),
            "provider": "codex",
        },
    )

    monkeypatch.setattr(MCPExecutorWorkflowManager, "_start_run_once_background_worker", lambda self, **kwargs: None)
    started = run_manager.handle("apply", {"preview_id": preview["preview_id"]})
    assert started["ok"] is True
    executor_preview_id = started["started_executor_runs"][0]["executor_preview_id"]
    worktree_path = started["started_executor_runs"][0]["worktree_path"]
    report = ExecutorRunReportStore(worktree_path).record_report(
        version="v1",
        version_name="One",
        provider="codex",
        execution_mode="run",
        status="completed",
        commit_head_before="abc",
        commit_head_after="def",
        changed_files=["README.md"],
        summary_validation_results=["PASSED: pytest"],
    )
    assert report["ok"] is True
    claim_file = (
        project
        / ".colameta"
        / "runtime"
        / "parallel-worktrees"
        / preview["parallel_group_id"]
        / "one"
        / ".colameta"
        / "runtime"
        / "executor-workflow-previews"
        / "claims"
        / f"{executor_preview_id}.json"
    )
    claim = json.loads(claim_file.read_text(encoding="utf-8"))
    claim["status"] = "COMPLETED"
    claim["report_id"] = report["report_id"]
    claim_file.write_text(json.dumps(claim), encoding="utf-8")

    result = build_stage_parallel_executor_results_packet(
        project_root=str(project),
        stage_id="stage_parallel_dev",
        task_intents=_task_intents(),
        provider="codex",
    )

    assert result["result_summary"]["succeeded"] == 1
    assert result["executor_results"][0]["status"] == "succeeded"
    assert result["executor_results"][0]["validation_status"] == "passed"
    assert result["executor_results"][0]["changed_files"] == ["README.md"]
    assert result["group_status_preview"]["status"] == "merge_ready"
