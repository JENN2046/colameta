from __future__ import annotations

import json
import subprocess
from pathlib import Path

from runner.executor_run_reports import ExecutorRunReportStore
from runner.mcp_executor_workflow import MCPExecutorWorkflowManager
from runner.mcp_stage_parallel_executor_group import MCPStageParallelExecutorGroupManager
from runner.mcp_stage_parallel_executor_runs import (
    FRESH_EXECUTOR_STAGE_PARALLEL_START_NEW_UNSUPPORTED_R0,
    MCPStageParallelExecutorRunGroupManager,
)
from runner.mcp_stage_parallel_merges import MCPStageParallelMergeManager
from runner.mcp_stage_parallel_shard_inputs import MCPStageParallelShardInputManager
from runner.mcp_stage_parallel_worktrees import MCPStageParallelWorktreeManager
from runner.stage_parallel_executor_results import build_stage_parallel_executor_results_packet
from runner.stage_parallel_next_action import build_stage_parallel_next_action_packet


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
                "default_acceptance_commands": [
                    {
                        "command": "python3 -m compileall -q .",
                        "timeout_seconds": 600,
                        "continue_on_failure": False,
                    }
                ],
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


def _init_managed_repo_with_ignored_state(tmp_path):
    project = tmp_path / "repo_ignored_state"
    project.mkdir()
    _git(project, "init", "-q", "-b", "main")
    (project / "README.md").write_text("demo\n", encoding="utf-8")
    (project / ".gitignore").write_text(".colameta/state.json\n.colameta/runtime/\n", encoding="utf-8")
    runner_dir = project / ".colameta"
    runner_dir.mkdir()
    (runner_dir / "plan.json").write_text(
        json.dumps(
            {
                "project_name": "demo",
                "default_acceptance_commands": [
                    {
                        "command": "python3 -m compileall -q .",
                        "timeout_seconds": 600,
                        "continue_on_failure": False,
                    }
                ],
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
                "status": "VERSION_PASSED",
                "current_version": "v1",
                "current_version_index": 0,
                "versions": [{"version": "v1", "name": "One", "status": "PASSED"}],
            }
        ),
        encoding="utf-8",
    )
    _git(project, "add", "README.md", ".gitignore", ".colameta/plan.json")
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


def _materialize_shard_inputs(project, *, stage_id: str = "stage_parallel_dev") -> dict:
    manager = MCPStageParallelShardInputManager(str(project))
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
    return applied["materialized_inputs"][0]


def _create_executor_preview(project, *, stage_id: str = "stage_parallel_dev") -> dict:
    _create_worktree(project, stage_id=stage_id)
    _materialize_shard_inputs(project, stage_id=stage_id)
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


def test_stage_parallel_shard_inputs_overlay_unblocks_missing_state_worktree(tmp_path) -> None:
    project = _init_managed_repo_with_ignored_state(tmp_path)
    created = _create_worktree(project)
    worktree_path = created["worktree_path"]
    group_manager = MCPStageParallelExecutorGroupManager(str(project))

    before = group_manager.handle(
        "preview",
        {
            "stage_id": "stage_parallel_dev",
            "task_intents": _task_intents(),
            "provider": "codex",
        },
    )
    assert before["ok"] is True
    assert before["status"] == "blocked"
    assert before["blockers"][0]["code"] == "EXECUTOR_PREFLIGHT_BLOCKED"
    assert before["blockers"][0]["blocks"][0]["code"] == "NO_STATE_FILE"

    materialized = _materialize_shard_inputs(project)

    assert materialized["worktree_path"] == worktree_path
    assert materialized["runner_input_source"] == "stage_parallel_shard_overlay"
    assert Path(materialized["manifest_file"]).is_file()
    assert Path(materialized["plan_file"]).is_file()
    assert Path(materialized["state_file"]).is_file()
    assert Path(materialized["prompt_file"]).is_file()
    status_lines = [
        line
        for line in _git(Path(worktree_path), "status", "--short", "--untracked-files=all").stdout.splitlines()
        if line.strip()
    ]
    assert status_lines == []

    preflight = MCPExecutorWorkflowManager(worktree_path).handle(
        "preflight",
        {"provider": "codex", "execution_mode": "run"},
    )
    assert preflight["preflight_blocked"] is False
    assert preflight["runner_input_source"] == "stage_parallel_shard_overlay"
    assert preflight["runner_input_overlay"]["task_id"] == "one"
    assert preflight["current_version"] == "stage_parallel_one"

    after = group_manager.handle(
        "preview",
        {
            "stage_id": "stage_parallel_dev",
            "task_intents": _task_intents(),
            "provider": "codex",
        },
    )
    assert after["ok"] is True
    assert after["status"] == "preview_ready"


def test_stage_parallel_next_action_packet_points_to_worktree_gate_when_missing(tmp_path) -> None:
    project = _init_managed_repo(tmp_path)

    result = build_stage_parallel_next_action_packet(
        project_root=str(project),
        stage_id="stage_parallel_dev",
        task_intents=_task_intents(),
        provider="codex",
    )

    assert result["ok"] is True
    assert result["read_only"] is True
    assert result["phase"] == "worktrees_missing"
    assert result["status"] == "needs_worktrees"
    assert result["next_action"]["tool"] == "manage_stage_parallel_worktrees"
    assert result["next_action"]["arguments"]["action"] == "preview"
    assert result["authority_boundary"]["does_not_create_preview_artifact"] is True


def test_stage_parallel_next_action_packet_points_to_shard_inputs_after_worktree(tmp_path) -> None:
    project = _init_managed_repo(tmp_path)
    _create_worktree(project)

    result = build_stage_parallel_next_action_packet(
        project_root=str(project),
        stage_id="stage_parallel_dev",
        task_intents=_task_intents(),
        provider="codex",
    )

    assert result["phase"] == "shard_inputs_missing"
    assert result["status"] == "needs_shard_inputs"
    assert result["next_action"]["tool"] == "manage_stage_parallel_shard_inputs"
    assert result["copyable_tool_call"]["arguments"]["action"] == "preview"


def test_stage_parallel_next_action_packet_points_to_executor_group_after_inputs(tmp_path) -> None:
    project = _init_managed_repo(tmp_path)
    _create_worktree(project)
    _materialize_shard_inputs(project)

    result = build_stage_parallel_next_action_packet(
        project_root=str(project),
        stage_id="stage_parallel_dev",
        task_intents=_task_intents(),
        provider="codex",
    )

    assert result["phase"] == "executor_previews_missing"
    assert result["status"] == "needs_executor_previews"
    assert result["next_action"]["tool"] == "manage_stage_parallel_executor_group"
    assert result["next_action"]["arguments"]["action"] == "preview"


def test_stage_parallel_next_action_packet_points_to_executor_runs_after_preview(tmp_path) -> None:
    project = _init_managed_repo(tmp_path)
    _create_executor_preview(project)

    result = build_stage_parallel_next_action_packet(
        project_root=str(project),
        stage_id="stage_parallel_dev",
        task_intents=_task_intents(),
        provider="codex",
    )

    assert result["phase"] == "executor_runs_not_started"
    assert result["status"] == "needs_executor_runs"
    assert result["next_action"]["tool"] == "manage_stage_parallel_executor_runs"
    assert result["next_action"]["arguments"]["action"] == "preview"


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




def _executor_preview_worktree_path(project) -> Path:
    parallel_root = project / ".colameta" / "runtime" / "parallel-worktrees"
    groups = sorted(parallel_root.iterdir()) if parallel_root.is_dir() else []
    assert groups, "no parallel worktree group created"
    shards = sorted((groups[-1]).iterdir()) if (groups[-1]).is_dir() else []
    assert shards, "no shard worktree created"
    return shards[-1]

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


def test_stage_parallel_executor_runs_preview_blocks_fresh_start_r0(tmp_path) -> None:
    """R0: stage parallel executor fresh start is explicitly unsupported.

    Every shard operation selects executor_session_mode=start_new, which R0
    cannot authorize without per-shard fresh authority wiring.  Preview must
    fail closed BEFORE any preview_id is minted or any shard is started.
    """
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
    assert result["status"] == "blocked"
    assert result["can_apply"] is False
    assert "preview_id" not in result
    assert result["authority_boundary"]["does_not_start_executor"] is True
    assert result["authority_boundary"]["starts_executor_runs_on_apply"] is False
    assert result["planned_operations"][0]["executor_preview_id"] == created["executor_preview_id"]
    codes = [str(b.get("code") or "") for b in result.get("blockers", [])]
    assert FRESH_EXECUTOR_STAGE_PARALLEL_START_NEW_UNSUPPORTED_R0 in codes


def test_stage_parallel_executor_runs_apply_blocks_fresh_start_without_merge_or_push(tmp_path, monkeypatch) -> None:
    """R0: no shard may start for a fresh stage parallel run group.

    Preview is blocked (no preview_id), so apply cannot proceed; even a direct
    apply attempt must not start any worker, create any claim, or invoke any
    provider.
    """
    project = _init_managed_repo(tmp_path)
    _create_executor_preview(project)
    manager = MCPStageParallelExecutorRunGroupManager(str(project))

    preview = manager.handle(
        "preview",
        {
            "stage_id": "stage_parallel_dev",
            "task_intents": _task_intents(),
            "provider": "codex",
        },
    )
    assert preview["ok"] is True
    assert preview["status"] == "blocked"
    assert "preview_id" not in preview

    started_calls = []

    def fake_start(self, **kwargs):
        started_calls.append({"project_root": self.project_root, **kwargs})

    monkeypatch.setattr(MCPExecutorWorkflowManager, "_start_run_once_background_worker", fake_start)

    result = manager.handle("apply", {"preview_id": "does-not-exist"})

    assert result["ok"] is False
    assert result["error_code"] == "PREVIEW_NOT_FOUND"
    assert started_calls == []
    worktree_path = _executor_preview_worktree_path(project)
    claims_dir = worktree_path / ".colameta" / "runtime" / "executor-workflow-previews" / "claims"
    assert not claims_dir.exists() or list(claims_dir.glob("*.json")) == []


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


def _seed_running_claim(project, created) -> tuple[Path, str]:
    """Seed a RUNNING executor claim directly (no stage parallel apply).

    Stage parallel executor fresh start is R0-unsupported; results-packet
    coverage must construct its claim/report fixtures directly instead of
    going through the blocked apply path.
    """
    worktree_path = Path(created["worktree_path"])
    preview_id = str(created["executor_preview_id"])
    manager = MCPExecutorWorkflowManager(str(worktree_path))
    artifact = manager._read_preview_artifact(preview_id)
    assert artifact is not None
    claim = manager._claims.acquire_claim(
        preview_id=preview_id,
        artifact=artifact,
        provider="codex",
        execution_mode="run",
    )
    assert claim["ok"] is True, claim
    return worktree_path, preview_id


def test_stage_parallel_executor_results_packet_reports_running_claim(tmp_path) -> None:
    project = _init_managed_repo(tmp_path)
    created = _create_executor_preview(project)
    _seed_running_claim(project, created)

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


def test_stage_parallel_executor_results_packet_reports_completed_validated_report(tmp_path) -> None:
    project = _init_managed_repo(tmp_path)
    created = _create_executor_preview(project)
    worktree_path, preview_id = _seed_running_claim(project, created)

    report = ExecutorRunReportStore(str(worktree_path)).record_report(
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
        worktree_path
        / ".colameta"
        / "runtime"
        / "executor-workflow-previews"
        / "claims"
        / f"{preview_id}.json"
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


def test_stage_parallel_executor_runs_apply_blocks_stale_start_new_preview(tmp_path, monkeypatch) -> None:
    """Apply-time gate: a stale pre-upgrade apply preview must fail closed.

    A preview record written before the R0 contract (operations requesting
    start_new) must be blocked at apply, before any shard starts, with no
    claims created and no provider invoked.
    """
    project = _init_managed_repo(tmp_path)
    created = _create_executor_preview(project)
    manager = MCPStageParallelExecutorRunGroupManager(str(project))
    plan = manager._build_plan(
        {
            "stage_id": "stage_parallel_dev",
            "task_intents": _task_intents(),
            "provider": "codex",
        }
    )
    validations = manager._executor_group._validate_plan(plan)
    operations, _ = manager._planned_operations(plan, validations)
    assert operations
    stale_preview_id = "stale_start_new_r0_preview"
    record = {
        "preview_id": stale_preview_id,
        "artifact_kind": "stage_parallel_executor_run_group_apply_preview",
        "action": "manage_stage_parallel_executor_runs.apply",
        "tool": "manage_stage_parallel_executor_runs",
        "params": {"action": "apply", "preview_id": stale_preview_id},
        "project_root": str(project),
        "stage_id": "stage_parallel_dev",
        "parallel_group_id": plan.get("parallel_group_id"),
        "provider": "codex",
        "base_branch": plan.get("base_branch"),
        "run_preview": plan,
        "validations": validations,
        "planned_operations": operations,
        "created_at": "2026-07-20T00:00:00+00:00",
        "expires_at": "2099-01-01T00:00:00+00:00",
        "reason": "",
        "requires_confirmation": True,
    }
    manager._store.write(stale_preview_id, record)

    started_calls = []
    monkeypatch.setattr(
        MCPExecutorWorkflowManager,
        "_start_run_once_background_worker",
        lambda self, **kwargs: started_calls.append(kwargs),
    )

    result = manager.handle("apply", {"preview_id": stale_preview_id})

    assert result["ok"] is False
    assert result["error_code"] == "APPLY_STATE_MISMATCH"
    codes = [str(b.get("code") or "") for b in result.get("blockers", [])]
    assert FRESH_EXECUTOR_STAGE_PARALLEL_START_NEW_UNSUPPORTED_R0 in codes
    assert started_calls == []
    worktree_path = _executor_preview_worktree_path(project)
    claims_dir = worktree_path / ".colameta" / "runtime" / "executor-workflow-previews" / "claims"
    assert not claims_dir.exists() or list(claims_dir.glob("*.json")) == []


def test_stage_parallel_merge_gate_preview_blocks_until_results_are_ready(tmp_path) -> None:
    project = _init_managed_repo(tmp_path)
    manager = MCPStageParallelMergeManager(str(project))

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
    assert result["authority_boundary"]["does_not_merge_parallel_results"] is True


def test_stage_parallel_merge_gate_apply_merges_local_branch_without_push(tmp_path) -> None:
    project = _init_managed_repo(tmp_path)
    created = _create_worktree(project)
    worktree = Path(created["worktree_path"])
    readme = worktree / "README.md"
    readme.write_text("demo\nparallel change\n", encoding="utf-8")
    _git(worktree, "add", "README.md")
    _git(worktree, "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "parallel change", "-q")
    source_head = _git(worktree, "rev-parse", "HEAD").stdout.strip()
    manager = MCPStageParallelMergeManager(str(project))
    executor_results = [
        {
            "task_id": "one",
            "status": "succeeded",
            "validation_status": "passed",
            "head": source_head,
            "changed_files": ["README.md"],
        }
    ]
    preview = manager.handle(
        "preview",
        {
            "stage_id": "stage_parallel_dev",
            "task_intents": _task_intents(),
            "provider": "codex",
            "executor_results": executor_results,
        },
    )
    assert preview["ok"] is True
    assert preview["status"] == "preview_ready"
    assert preview["planned_operations"][0]["source_branch"] == created["branch_name"]
    assert preview["authority_boundary"]["does_not_merge_parallel_results"] is True

    result = manager.handle("apply", {"preview_id": preview["preview_id"]})

    assert result["ok"] is True
    assert result["status"] == "succeeded"
    assert result["merged_count"] == 1
    assert result["authority_boundary"]["creates_local_merge_commits_on_apply"] is True
    assert result["authority_boundary"]["does_not_push"] is True
    assert "parallel change" in (project / "README.md").read_text(encoding="utf-8")


def test_stage_parallel_merge_gate_apply_requires_preview_id(tmp_path) -> None:
    project = _init_managed_repo(tmp_path)
    manager = MCPStageParallelMergeManager(str(project))

    result = manager.handle("apply", {})

    assert result["ok"] is False
    assert result["error_code"] == "PREVIEW_ID_REQUIRED"
