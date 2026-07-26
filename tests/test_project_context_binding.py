from __future__ import annotations

import json
from pathlib import Path
import subprocess

from runner.project_context_binding import (
    ProjectContextBindingError,
    collect_project_context_binding,
    require_operation_context_binding,
)


def _make_managed_checkout(tmp_path: Path) -> Path:
    project = tmp_path / "binding-project"
    project.mkdir()
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    subprocess.run(
        ["git", "-C", str(project), "config", "user.email", "binding@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(project), "config", "user.name", "Binding Fixture"],
        check=True,
    )
    runner_dir = project / ".colameta"
    runner_dir.mkdir()
    (runner_dir / "plan.json").write_text(
        json.dumps({"project_name": "binding-project", "versions": []}),
        encoding="utf-8",
    )
    (runner_dir / "state.json").write_text(
        json.dumps({"current_version": "v1.0"}),
        encoding="utf-8",
    )
    (project / "README.md").write_text("# Binding fixture\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(project), "add", "."], check=True)
    subprocess.run(["git", "-C", str(project), "commit", "-qm", "fixture"], check=True)
    return project


def test_operation_context_binding_rechecks_plan_and_operation_identity(tmp_path: Path) -> None:
    project = _make_managed_checkout(tmp_path)
    binding = collect_project_context_binding(
        str(project),
        review_unit="operation:validation_run",
        workflow_intent="validation_run",
    )

    accepted = require_operation_context_binding(
        binding,
        project_root=str(project),
        project_name=None,
        review_unit="operation:validation_run",
        workflow_intent="validation_run",
    )
    assert accepted == binding

    try:
        require_operation_context_binding(
            binding,
            project_root=str(project),
            project_name=None,
            review_unit="operation:another_run",
            workflow_intent="another_run",
        )
    except ProjectContextBindingError as exc:
        assert exc.error_code == "CONTEXT_BINDING_MISMATCH"
        assert {item["field"] for item in exc.details["mismatches"]} == {
            "review_unit",
            "workflow_intent",
        }
    else:  # pragma: no cover - the assertion documents the fail-closed contract
        raise AssertionError("a binding must not be reusable for another operation")

    (project / ".colameta" / "plan.json").write_text(
        json.dumps({"project_name": "binding-project", "versions": [{"version": "v1.1"}]}),
        encoding="utf-8",
    )

    try:
        require_operation_context_binding(
            binding,
            project_root=str(project),
            project_name=None,
            review_unit="operation:validation_run",
            workflow_intent="validation_run",
        )
    except ProjectContextBindingError as exc:
        assert exc.error_code == "CONTEXT_BINDING_MISMATCH"
        assert exc.details["mismatches"] == [
            {
                "field": "runner_plan",
                "expected": binding["runner_plan"],
                "actual": collect_project_context_binding(
                    str(project),
                    review_unit="operation:validation_run",
                    workflow_intent="validation_run",
                )["runner_plan"],
            }
        ]
    else:  # pragma: no cover - the assertion documents the fail-closed contract
        raise AssertionError("a changed Runner plan must invalidate a confirmation")
