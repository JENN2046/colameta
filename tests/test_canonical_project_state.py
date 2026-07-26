from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import subprocess

from runner.canonical_project_state import (
    CANONICAL_PROJECT_STATE_SCHEMA_VERSION,
    build_canonical_project_state,
)
from runner.project_snapshot import ProjectSnapshotBuilder


def _make_git_checkout(tmp_path: Path) -> tuple[Path, str]:
    project = tmp_path / "canonical-state-project"
    project.mkdir()
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    subprocess.run(
        ["git", "-C", str(project), "config", "user.email", "state@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(project), "config", "user.name", "State Fixture"],
        check=True,
    )
    (project / "README.md").write_text("# State fixture\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(project), "add", "."], check=True)
    subprocess.run(["git", "-C", str(project), "commit", "-qm", "fixture"], check=True)
    head = subprocess.run(
        ["git", "-C", str(project), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return project, head


def _state(
    project: Path,
    head: str,
    *,
    delivery_clean: bool,
    runtime_observation: dict | None = None,
    connector_observation: dict | None = None,
) -> dict:
    return build_canonical_project_state(
        project_root=str(project),
        project_identity={"project_name": "canonical-state-project"},
        mode="runner_managed",
        git={
            "ok": True,
            "branch": "master",
            "head": head,
            "working_tree_clean": False,
            "blocking_working_tree_clean": delivery_clean,
            "ignored_runner_runtime_files": [".colameta/runtime/transient.json"],
        },
        runner={
            "has_runner_state": True,
            "current_version": "v1.0",
            "current_version_status": "PASSED",
            "pending_count": 0,
            "has_pending_versions": False,
        },
        plan={},
        executor={"has_session": False, "continuation_available": False},
        reports={
            "latest": {
                "status": "completed",
                "finished_at": "2026-07-22T00:00:00Z",
                "version": "v1.0",
            }
        },
        blockers=[],
        warnings=[],
        partial_errors=[],
        observed_at=datetime(2026, 7, 22, 1, 2, 3, tzinfo=timezone.utc),
        runtime_observation=runtime_observation,
        connector_observation=connector_observation,
    )


def test_canonical_state_separates_historical_truth_from_current_observation(tmp_path: Path) -> None:
    project, head = _make_git_checkout(tmp_path)
    state = _state(project, head, delivery_clean=True)

    assert state["schema_version"] == CANONICAL_PROJECT_STATE_SCHEMA_VERSION
    assert state["observed_at"] == "2026-07-22T01:02:03Z"
    assert state["historically_verified"]["latest_execution_report"] == {
        "status": "verified",
        "verified_at": "2026-07-22T00:00:00Z",
        "report_status": "completed",
        "version": "v1.0",
    }
    git = state["currently_observed"]["git"]
    assert git["raw_working_tree"] == "dirty"
    assert git["delivery_working_tree"] == "clean"
    assert git["reconciliation"] == "ignored_runner_runtime_only"
    assert state["currently_observed"]["runtime"] == {
        "status": "not_observed",
        "observed_at": None,
        "reason_code": "not_requested",
    }
    assert state["currently_observed"]["connector"]["status"] == "not_observed"
    assert state["freshness"]["current_observation"] == "freshness_required"
    assert state["freshness"]["unobserved_sources"] == ["runtime", "connector"]
    assert state["current_conclusion"] == {
        "status": "freshness_required",
        "scope": "full_project_and_external_observation",
        "reasons": ["runtime_not_observed", "connector_not_observed"],
        "project_checkout": {
            "status": "ready",
            "scope": "project_checkout_and_runner",
            "reasons": [],
        },
        "runtime_and_connector": {
            "status": "freshness_required",
            "scope": "runtime_and_connector",
            "reasons": ["runtime_not_observed", "connector_not_observed"],
        },
        "authorization": "observation_only",
    }
    assert state["authority_boundary"]["historical_verification_is_not_current_observation"] is True
    assert state["authority_boundary"]["not_observed_is_not_unavailable"] is True


def test_canonical_state_marks_delivery_dirty_as_current_action_required(tmp_path: Path) -> None:
    project, head = _make_git_checkout(tmp_path)
    state = _state(project, head, delivery_clean=False)

    assert state["currently_observed"]["git"]["reconciliation"] == "matched"
    assert state["current_conclusion"] == {
        "status": "action_required",
        "scope": "full_project_and_external_observation",
        "reasons": ["delivery_working_tree_dirty"],
        "project_checkout": {
            "status": "action_required",
            "scope": "project_checkout_and_runner",
            "reasons": ["delivery_working_tree_dirty"],
        },
        "runtime_and_connector": {
            "status": "freshness_required",
            "scope": "runtime_and_connector",
            "reasons": ["runtime_not_observed", "connector_not_observed"],
        },
        "authorization": "observation_only",
    }


def test_canonical_state_marks_full_conclusion_ready_with_fresh_external_observations(
    tmp_path: Path,
) -> None:
    project, head = _make_git_checkout(tmp_path)
    state = _state(
        project,
        head,
        delivery_clean=True,
        runtime_observation={
            "status": "healthy",
            "observed_at": "2026-07-22T01:02:00Z",
        },
        connector_observation={
            "status": "healthy",
            "observed_at": "2026-07-22T01:02:01Z",
        },
    )

    assert state["freshness"]["current_observation"] == "current"
    assert state["freshness"]["unobserved_sources"] == []
    assert state["current_conclusion"] == {
        "status": "ready",
        "scope": "full_project_and_external_observation",
        "reasons": [],
        "project_checkout": {
            "status": "ready",
            "scope": "project_checkout_and_runner",
            "reasons": [],
        },
        "runtime_and_connector": {
            "status": "observed",
            "scope": "runtime_and_connector",
            "reasons": [],
        },
        "authorization": "observation_only",
    }

    current = _state(
        project,
        head,
        delivery_clean=True,
        runtime_observation={
            "status": "current",
            "observed_at": "2026-07-22T01:02:00Z",
        },
        connector_observation={
            "status": "healthy",
            "observed_at": "2026-07-22T01:02:01Z",
        },
    )
    assert current["freshness"]["current_observation"] == "current"
    assert current["current_conclusion"]["status"] == "ready"


def test_canonical_state_never_projects_noncurrent_external_status_as_ready(
    tmp_path: Path,
) -> None:
    project, head = _make_git_checkout(tmp_path)

    for status in ("stale", "degraded", "unhealthy", "error"):
        state = _state(
            project,
            head,
            delivery_clean=True,
            runtime_observation={"status": status},
            connector_observation={"status": "healthy"},
        )
        assert state["freshness"]["current_observation"] == (
            "freshness_required"
        )
        assert state["current_conclusion"]["status"] == (
            "freshness_required"
        )
        assert state["current_conclusion"]["reasons"] == [
            "runtime_current_observation_not_healthy"
        ]

    partial = _state(
        project,
        head,
        delivery_clean=True,
        runtime_observation={"status": "partial"},
        connector_observation={"status": "healthy"},
    )
    assert partial["freshness"]["current_observation"] == "partial"
    assert partial["current_conclusion"]["status"] == "partial_observation"
    assert partial["current_conclusion"]["reasons"] == [
        "runtime_partial_observation"
    ]


def test_project_snapshot_projects_scalar_runner_status(
    tmp_path: Path,
) -> None:
    class PlanningBridgeFixture:
        @staticmethod
        def get_runner_status(_project_root: str) -> dict[str, object]:
            return {
                "ok": True,
                "runner_status": "READY",
                "current_version": "v1.19",
                "current_version_status": "PASSED",
                "pending_count": 0,
                "pending_versions": [],
            }

    partial_errors: list[dict[str, str]] = []
    runner = ProjectSnapshotBuilder(
        str(tmp_path),
        planning_bridge=PlanningBridgeFixture(),
    )._build_runner_status(
        mode="runner_managed",
        partial_errors=partial_errors,
    )

    assert partial_errors == []
    assert runner["runner_status"] == "READY"
    assert runner["current_version"] == "v1.19"
    assert runner["current_version_status"] == "PASSED"
