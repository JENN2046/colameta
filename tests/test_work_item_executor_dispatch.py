from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from runner.mcp_executor_workflow import MCPExecutorWorkflowManager
from runner.work_item_governance.ids import new_stable_id


def _git(project: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=project,
        capture_output=True,
        text=True,
        check=True,
    )


def _bound_managed_project(tmp_path: Path, *, governance_enabled: bool) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    _git(project, "init", "-q", "-b", "main")
    (project / "README.md").write_text("bound execution\n", encoding="utf-8")
    runner_dir = project / ".colameta"
    runner_dir.mkdir()
    binding = {
        "work_item_id": new_stable_id("work_item"),
        "task_version": 1,
        "attempt_id": new_stable_id("attempt"),
    }
    (runner_dir / "plan.json").write_text(
        json.dumps(
            {
                "project_name": "bound-execution",
                "versions": [
                    {
                        "version": "v1",
                        "name": "Bound execution",
                        "enabled": True,
                        "allowed_files": ["README.md"],
                        **binding,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (runner_dir / "state.json").write_text(
        json.dumps(
            {
                "project_name": "bound-execution",
                "status": "PROMPT_READY",
                "current_version": "v1",
                "current_version_index": 0,
                "versions": [
                    {"version": "v1", "name": "Bound execution", "status": "PROMPT_READY"}
                ],
            }
        ),
        encoding="utf-8",
    )
    (runner_dir / "settings.json").write_text(
        json.dumps(
            {
                "work_item_governance": {
                    "shadow_ledger_enabled": governance_enabled,
                    "gate_mode": "authoritative",
                }
            }
        ),
        encoding="utf-8",
    )
    _git(project, "add", "README.md", ".colameta")
    _git(
        project,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.com",
        "commit",
        "-q",
        "-m",
        "init",
    )
    return project


@pytest.mark.parametrize(
    ("governance_enabled", "expected_code"),
    [
        (False, "WORK_ITEM_ATTEMPT_GOVERNANCE_DISABLED"),
        (True, "WORK_ITEM_ATTEMPT_LEDGER_MISSING"),
    ],
)
def test_bound_attempt_fails_closed_without_available_governance(
    tmp_path: Path,
    governance_enabled: bool,
    expected_code: str,
) -> None:
    project = _bound_managed_project(tmp_path, governance_enabled=governance_enabled)
    manager = MCPExecutorWorkflowManager(str(project))

    preflight = manager.handle(
        "preflight",
        {"provider": "codex", "execution_mode": "run"},
    )
    run_preview = manager.handle(
        "run_once_preview",
        {"provider": "codex", "execution_mode": "run"},
    )

    assert preflight["preflight_blocked"] is True
    assert expected_code in {block["code"] for block in preflight["blocks"]}
    assert run_preview["ok"] is False
    assert run_preview["status"] == "blocked"
    assert expected_code in {block["code"] for block in run_preview["blocks"]}
    assert not (project / ".colameta" / "ledger").exists()
