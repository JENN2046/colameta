from __future__ import annotations

from runner.stage_parallel_plan import (
    build_stage_parallel_closeout_packet,
    build_stage_parallel_executor_group_preview,
    build_stage_parallel_group_status,
    build_stage_parallel_merge_preview,
    build_stage_parallel_plan_preview,
    build_stage_parallel_run_preview,
    build_stage_parallel_worktree_assignment_preview,
)


def test_default_stage_parallel_plan_preview_is_read_only_and_actionable(tmp_path) -> None:
    result = build_stage_parallel_plan_preview(project_root=str(tmp_path), project_name="demo-project")

    assert result["ok"] is True
    assert result["source"] == "stage_parallel_plan_preview"
    assert result["read_only"] is True
    assert result["side_effects"] is False
    assert result["status"] == "preview_ready"
    assert result["task_source"] == "default_automation_roadmap"
    assert result["parallelism"]["planned_task_count"] == 3
    assert result["risk_level"] == "low"
    assert result["suggested_next_action"] == "ready_for_parallel_run_preview"
    assert result["authority_boundary"]["does_not_authorize_executor_run"] is True
    assert result["authority_boundary"]["does_not_create_branch_or_worktree"] is True
    assert result["authority_boundary"]["does_not_commit"] is True
    assert result["authority_boundary"]["does_not_push"] is True
    assert result["authority_boundary"]["does_not_replace_stable_service"] is True


def test_stage_parallel_plan_preview_blocks_overlapping_file_boundaries(tmp_path) -> None:
    result = build_stage_parallel_plan_preview(
        project_root=str(tmp_path),
        task_intents=[
            {
                "task_id": "mcp",
                "title": "MCP entry",
                "allowed_files": ["runner/mcp_server.py"],
                "surfaces": ["MCP"],
            },
            {
                "task_id": "apps",
                "title": "Apps entry",
                "allowed_files": ["runner/mcp_server.py", "docs/USAGE.md"],
                "surfaces": ["MCP", "docs"],
            },
        ],
    )

    assert result["risk_level"] == "blocked"
    assert result["suggested_next_action"] == "refine_task_boundaries"
    assert result["blocking_reasons"][0]["code"] == "PARALLEL_FILE_BOUNDARY_OVERLAP"
    assert result["file_overlap_risks"] == [
        {"path": "runner/mcp_server.py", "task_ids": ["mcp", "apps"], "risk": "write_conflict"}
    ]
    assert result["authority_boundary"]["does_not_authorize_executor_run"] is True


def test_stage_parallel_plan_preview_limits_candidate_task_count(tmp_path) -> None:
    result = build_stage_parallel_plan_preview(
        project_root=str(tmp_path),
        max_parallel_tasks=2,
        task_intents=[
            {"task_id": "one", "title": "One", "allowed_files": ["runner/one.py"]},
            {"task_id": "two", "title": "Two", "allowed_files": ["runner/two.py"]},
            {"task_id": "three", "title": "Three", "allowed_files": ["runner/three.py"]},
        ],
    )

    assert result["parallelism"]["effective_max_parallel_tasks"] == 2
    assert result["parallelism"]["candidate_task_count"] == 3
    assert result["parallelism"]["planned_task_count"] == 2
    assert result["parallelism"]["skipped_task_count"] == 1
    assert result["risk_level"] == "moderate"


def test_stage_parallel_run_preview_builds_isolated_executor_requests(tmp_path) -> None:
    result = build_stage_parallel_run_preview(
        project_root=str(tmp_path),
        project_name="demo-project",
        stage_id="stage_parallel_dev",
        task_intents=[
            {
                "task_id": "mcp_entry",
                "title": "MCP entry",
                "allowed_files": ["runner/mcp_server.py"],
                "surfaces": ["MCP"],
            },
            {
                "task_id": "docs_entry",
                "title": "Docs entry",
                "allowed_files": ["docs/USAGE.md"],
                "surfaces": ["docs"],
            },
        ],
        provider="codex",
        base_branch="main",
    )

    assert result["ok"] is True
    assert result["source"] == "stage_parallel_run_preview"
    assert result["read_only"] is True
    assert result["side_effects"] is False
    assert result["status"] == "preview_ready"
    assert result["parallel_group_id"].startswith("parallel_group_stage_parallel_dev_")
    assert result["parallelism"]["planned_task_count"] == 2
    assert result["parallelism"]["requires_isolated_worktrees"] is True
    assert result["suggested_next_action"] == "create_isolated_worktree_preview"
    first = result["run_shards"][0]
    assert first["isolation"]["strategy"] == "git_worktree_required"
    assert first["isolation"]["created"] is False
    assert first["isolation"]["branch_name"] == "colameta/stage_parallel_dev/mcp_entry"
    assert first["executor_preview_request"]["status"] == "not_created"
    assert first["executor_preview_request"]["arguments"]["action"] == "run_once_preview"
    assert first["executor_preview_request"]["arguments"]["executor_session_mode"] == "start_new"
    assert result["authority_boundary"]["does_not_create_executor_preview"] is True
    assert result["authority_boundary"]["does_not_authorize_executor_run"] is True
    assert result["authority_boundary"]["does_not_create_branch_or_worktree"] is True


def test_stage_parallel_run_preview_blocks_when_plan_has_overlaps(tmp_path) -> None:
    result = build_stage_parallel_run_preview(
        project_root=str(tmp_path),
        task_intents=[
            {"task_id": "one", "title": "One", "allowed_files": ["runner/mcp_server.py"]},
            {"task_id": "two", "title": "Two", "allowed_files": ["runner/mcp_server.py"]},
        ],
    )

    assert result["status"] == "blocked"
    assert result["risk_level"] == "blocked"
    assert result["suggested_next_action"] == "refine_task_boundaries"
    assert result["parallelism"]["max_concurrency"] == 0
    assert result["blocking_reasons"][0]["code"] == "PARALLEL_FILE_BOUNDARY_OVERLAP"
    assert result["authority_boundary"]["does_not_authorize_executor_run"] is True


def test_stage_parallel_worktree_assignment_preview_checks_paths_without_creating(tmp_path) -> None:
    result = build_stage_parallel_worktree_assignment_preview(
        project_root=str(tmp_path),
        project_name="demo-project",
        stage_id="stage_parallel_dev",
        task_intents=[
            {
                "task_id": "mcp_entry",
                "title": "MCP entry",
                "allowed_files": ["runner/mcp_server.py"],
                "surfaces": ["MCP"],
            }
        ],
    )

    assert result["ok"] is True
    assert result["source"] == "stage_parallel_worktree_assignment_preview"
    assert result["status"] == "preview_ready"
    assert result["read_only"] is True
    assert result["side_effects"] is False
    assert result["assignment_summary"]["planned_assignment_count"] == 1
    assert result["assignment_summary"]["assignable_count"] == 1
    assignment = result["worktree_assignments"][0]
    assert assignment["assignment_status"] == "assignable"
    assert assignment["path_exists"] is False
    assert assignment["path_within_project_runtime"] is True
    assert assignment["branch_name"] == "colameta/stage_parallel_dev/mcp_entry"
    assert result["authority_boundary"]["does_not_create_branch_or_worktree"] is True
    assert not tmp_path.joinpath(".colameta").exists()


def test_stage_parallel_worktree_assignment_preview_blocks_existing_path(tmp_path) -> None:
    first = build_stage_parallel_worktree_assignment_preview(
        project_root=str(tmp_path),
        stage_id="stage_parallel_dev",
        task_intents=[{"task_id": "one", "title": "One", "allowed_files": ["runner/one.py"]}],
    )
    existing_path = tmp_path / ".colameta" / "runtime" / "parallel-worktrees"
    existing_path = existing_path / first["parallel_group_id"] / "one"
    existing_path.mkdir(parents=True)

    result = build_stage_parallel_worktree_assignment_preview(
        project_root=str(tmp_path),
        stage_id="stage_parallel_dev",
        task_intents=[{"task_id": "one", "title": "One", "allowed_files": ["runner/one.py"]}],
    )

    assert result["status"] == "blocked"
    assert result["worktree_assignments"][0]["path_exists"] is True
    assert result["blocking_reasons"][0]["code"] == "WORKTREE_PATH_ALREADY_EXISTS"
    assert result["authority_boundary"]["does_not_create_branch_or_worktree"] is True


def test_stage_parallel_executor_group_and_status_wait_for_results(tmp_path) -> None:
    group = build_stage_parallel_executor_group_preview(
        project_root=str(tmp_path),
        project_name="demo-project",
        task_intents=[
            {"task_id": "one", "title": "One", "allowed_files": ["runner/one.py"]},
            {"task_id": "two", "title": "Two", "allowed_files": ["docs/two.md"]},
        ],
    )
    status = build_stage_parallel_group_status(
        project_root=str(tmp_path),
        project_name="demo-project",
        task_intents=[
            {"task_id": "one", "title": "One", "allowed_files": ["runner/one.py"]},
            {"task_id": "two", "title": "Two", "allowed_files": ["docs/two.md"]},
        ],
    )

    assert group["source"] == "stage_parallel_executor_group_preview"
    assert group["status"] == "preview_ready"
    assert group["executor_preview_summary"]["planned_preview_count"] == 2
    assert group["executor_preview_summary"]["created_preview_count"] == 0
    assert group["authority_boundary"]["does_not_create_executor_preview"] is True
    assert group["suggested_next_action"] == "preview_executor_run_group"
    assert group["next_capability_steps"][0] == "executor_run_group_preview"
    assert group["safe_next_actions"][0]["action_id"] == "preview_executor_run_group"
    assert status["source"] == "stage_parallel_group_status"
    assert status["status"] == "waiting_for_executor_results"
    assert status["status_counts"]["planned"] == 2
    assert status["merge_readiness"]["ready"] is False
    assert status["suggested_next_action"] == "wait_for_executor_results"

    running_status = build_stage_parallel_group_status(
        project_root=str(tmp_path),
        project_name="demo-project",
        task_intents=[
            {"task_id": "one", "title": "One", "allowed_files": ["runner/one.py"]},
            {"task_id": "two", "title": "Two", "allowed_files": ["docs/two.md"]},
        ],
        executor_results=[
            {"task_id": "one", "status": "running", "validation_status": "running"},
            {"task_id": "two", "status": "planned", "validation_status": "not_run"},
        ],
    )
    assert running_status["status"] == "waiting_for_executor_results"
    assert running_status["status_counts"]["running"] == 1


def test_stage_parallel_merge_preview_and_closeout_accept_sanitized_results(tmp_path) -> None:
    task_intents = [
        {"task_id": "one", "title": "One", "allowed_files": ["runner/one.py"]},
        {"task_id": "two", "title": "Two", "allowed_files": ["docs/two.md"]},
    ]
    executor_results = [
        {
            "task_id": "one",
            "status": "succeeded",
            "validation_status": "passed",
            "head": "abc123",
            "changed_files": ["runner/one.py"],
        },
        {
            "task_id": "two",
            "status": "succeeded",
            "validation_status": "passed",
            "head": "def456",
            "changed_files": ["docs/two.md"],
        },
    ]

    group_status = build_stage_parallel_group_status(
        project_root=str(tmp_path),
        project_name="demo-project",
        task_intents=task_intents,
        executor_results=executor_results,
    )
    merge = build_stage_parallel_merge_preview(
        project_root=str(tmp_path),
        project_name="demo-project",
        task_intents=task_intents,
        executor_results=executor_results,
    )
    closeout = build_stage_parallel_closeout_packet(
        project_root=str(tmp_path),
        project_name="demo-project",
        task_intents=task_intents,
        executor_results=executor_results,
    )

    assert group_status["status"] == "merge_ready"
    assert group_status["merge_readiness"]["ready"] is True
    assert merge["source"] == "stage_parallel_merge_preview"
    assert merge["status"] == "preview_ready"
    assert merge["merge_plan"]["merge_allowed_now"] is False
    assert len(merge["merge_plan"]["merge_sequence"]) == 2
    assert merge["authority_boundary"]["does_not_merge_parallel_results"] is True
    assert closeout["source"] == "stage_parallel_closeout_packet"
    assert closeout["status"] == "ready_for_human_review"
    assert closeout["closeout_summary"]["stable_replacement_in_scope"] is False
    assert closeout["authority_boundary"]["does_not_write_delivery_accepted"] is True
