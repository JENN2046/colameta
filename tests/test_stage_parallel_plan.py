from __future__ import annotations

from runner.stage_parallel_plan import build_stage_parallel_plan_preview


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
