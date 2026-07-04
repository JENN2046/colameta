from __future__ import annotations

from runner.stage_parallel_plan import build_stage_parallel_plan_preview, build_stage_parallel_run_preview


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
