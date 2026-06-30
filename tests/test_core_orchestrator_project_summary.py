from runner.core_orchestrator import WorkflowOrchestrator


def test_runner_managed_summary_distinguishes_empty_pending_from_no_versions() -> None:
    orchestrator = WorkflowOrchestrator("/tmp/project")

    summary = orchestrator._summarize_analyzed_state(
        "runner_managed",
        True,
        True,
        True,
        {
            "has_runner_state": True,
            "pending_count": 0,
            "current_version": "v1.10",
            "current_version_status": "PASSED",
        },
        {"has_session": True},
        plan={"plan_summary": {"version_count": 12, "enabled_version_count": 12}},
    )

    assert "尚无开发版本" not in summary["one_line"]
    assert "计划中有 12 个版本" in summary["one_line"]
    assert "当前版本 v1.10 状态为 PASSED" in summary["one_line"]
    assert summary["plan_version_count"] == 12
    assert summary["enabled_plan_version_count"] == 12
    assert summary["has_plan_versions"] is True
    assert summary["recommended_primary_action"] == "manage_prompt_file preview"


def test_runner_managed_summary_still_reports_no_versions_for_empty_plan() -> None:
    orchestrator = WorkflowOrchestrator("/tmp/project")

    summary = orchestrator._summarize_analyzed_state(
        "runner_managed",
        True,
        True,
        True,
        {"has_runner_state": True, "pending_count": 0},
        {"has_session": False},
        plan={"plan_summary": {"version_count": 0, "enabled_version_count": 0}},
    )

    assert "尚无开发版本" in summary["one_line"]
    assert summary["plan_version_count"] == 0
    assert summary["enabled_plan_version_count"] == 0
    assert summary["has_plan_versions"] is False
