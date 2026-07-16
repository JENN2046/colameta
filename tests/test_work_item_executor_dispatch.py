from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from runner.mcp_executor_workflow import MCPExecutorWorkflowManager
from runner.work_item_governance.ids import new_stable_id
from runner.work_item_governance.service import WorkItemApplicationService


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


def _dispatchable_bound_project(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    project = _bound_managed_project(tmp_path, governance_enabled=True)
    service = WorkItemApplicationService(project)
    create_preview = service.preview_work_item_create(
        {
            "origin": {
                "kind": "manual",
                "ref": "executor-binding-test",
                "snapshot_digest": "a" * 64,
            }
        }
    )
    work_item_id = service.apply_work_item_create(create_preview["preview"])["work_item"]["work_item_id"]
    attempts = [
        service.create_execution_attempt(
            {
                "work_item_id": work_item_id,
                "task_version": 1,
                "source_event_key": f"executor-binding-test:{index}",
            }
        )["attempt"]
        for index in (1, 2)
    ]
    plan_path = project / ".colameta" / "plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["versions"][0].update(
        {
            "work_item_id": work_item_id,
            "task_version": 1,
            "attempt_id": attempts[0]["attempt_id"],
        }
    )
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    _git(project, "add", ".colameta/plan.json")
    _git(
        project,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.com",
        "commit",
        "-q",
        "-m",
        "bind attempt",
    )
    return project, {
        "work_item_id": work_item_id,
        "task_version": 1,
        "attempt_id": attempts[1]["attempt_id"],
    }


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


@pytest.mark.parametrize("mutation", ["replace", "remove"])
def test_confirmed_execution_rejects_work_item_binding_drift(
    tmp_path: Path,
    mutation: str,
) -> None:
    project, replacement = _dispatchable_bound_project(tmp_path)
    manager = MCPExecutorWorkflowManager(str(project))
    once_preview = manager.handle(
        "run_once_preview",
        {"provider": "codex", "execution_mode": "run"},
    )
    bounded_preview = manager.handle(
        "run_bounded_preview",
        {"provider": "codex", "max_iterations": 1},
    )
    assert once_preview["ok"] is True
    assert bounded_preview["ok"] is True

    plan_path = project / ".colameta" / "plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    version = plan["versions"][0]
    if mutation == "replace":
        version.update(replacement)
        expected_code = "ATTEMPT_ID_MISMATCH"
    else:
        for field in ("work_item_id", "task_version", "attempt_id"):
            version.pop(field)
        expected_code = "WORK_ITEM_ID_MISMATCH"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    once_result = manager.handle(
        "run_once",
        {
            "preview_id": once_preview["preview_id"],
            "provider": "codex",
            "execution_mode": "run",
        },
    )
    bounded_result = manager.handle(
        "run_bounded",
        {
            "preview_id": bounded_preview["preview_id"],
            "provider": "codex",
        },
    )

    assert once_result["ok"] is False
    assert once_result["error_code"] == expected_code
    assert bounded_result["ok"] is False
    assert bounded_result["error_code"] == expected_code
