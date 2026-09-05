from __future__ import annotations

from typing import Any

import pytest

from runner.core_orchestrator import WorkflowOrchestrator
from runner import mcp_prompt_file


@pytest.mark.parametrize("profile_id", ["local_codex_commander", ""])
def test_prompt_to_plan_preserves_profile_through_every_planning_continuation(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    profile_id: str,
) -> None:
    class PlanningBridge:
        @staticmethod
        def get_runner_status(_project_root: str) -> dict[str, Any]:
            return {"pending_count": 0, "pending_versions": []}

    class PromptManager:
        def __init__(self, project_root: str) -> None:
            assert project_root == str(tmp_path)

        def handle(self, action: str, _params: dict[str, Any]) -> dict[str, Any]:
            if action == "preview":
                return {"ok": True, "preview_id": "prompt_preview_123"}
            assert action == "apply"
            return {
                "ok": True,
                "target_file": str(tmp_path / "v1.md"),
                "plan_metadata": {
                    "name": "Persona propagation",
                    "description": "Keep the caller profile across continuations.",
                    "allowed_files": ["runner/core_orchestrator.py"],
                    "acceptance_commands": ["pytest -q"],
                },
            }

    monkeypatch.setattr(mcp_prompt_file, "MCPPromptFileManager", PromptManager)
    orchestrator = WorkflowOrchestrator.__new__(WorkflowOrchestrator)
    orchestrator.project_root = str(tmp_path)
    orchestrator._planning_bridge = PlanningBridge()

    def run_plan_action(action: str, _params: dict[str, Any]) -> dict[str, Any]:
        if action == "insert_from_prompt_file_preview":
            return {"ok": True, "patch_id": "plan_patch_123"}
        assert action == "apply_preview"
        return {"ok": True, "inserted_version": "v1"}

    orchestrator._run_plan_version_action = run_plan_action
    initial_params: dict[str, Any] = {"version": "v1", "content": "Do the work."}
    if profile_id:
        initial_params["profile_id"] = profile_id

    preview = orchestrator._prompt_to_plan_preview(initial_params)
    apply_all = orchestrator._prompt_to_plan_apply_all(preview.next_actions[0]["params"])
    planning_results = [
        preview,
        orchestrator._prompt_to_plan_apply({
            "preview_id": "prompt_preview_123",
            **({"profile_id": profile_id} if profile_id else {}),
        }),
        orchestrator._prompt_to_plan_plan_preview({
            "prompt_file": "v1.md",
            **({"profile_id": profile_id} if profile_id else {}),
        }),
        orchestrator._prompt_to_plan_plan_apply({
            "patch_id": "plan_patch_123",
            **({"profile_id": profile_id} if profile_id else {}),
        }),
        apply_all,
    ]

    assert [result.next_actions[0]["action"] for result in planning_results] == [
        "prompt_to_plan.apply_all",
        "prompt_to_plan.plan_preview",
        "prompt_to_plan.plan_apply",
        "prompt_to_plan.run_preview",
        "prompt_to_plan.run_preview",
    ]
    for result in planning_results:
        continuation_params = result.next_actions[0]["params"]
        if profile_id:
            assert continuation_params["profile_id"] == profile_id
        else:
            assert "profile_id" not in continuation_params


@pytest.mark.parametrize("profile_id", ["local_codex_commander", ""])
def test_prompt_to_plan_run_preview_preserves_only_explicit_profile(
    tmp_path,
    profile_id: str,
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    class PreviewManager:
        def __init__(self, project_root: str) -> None:
            assert project_root == str(tmp_path)

        def handle(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
            calls.append((action, dict(params)))
            if action == "preflight":
                return {"ok": True, "preflight_blocked": False}
            assert action == "run_once_preview"
            return {"ok": True, "preview_id": "executor_preview_prompt_123"}

    orchestrator = WorkflowOrchestrator.__new__(WorkflowOrchestrator)
    orchestrator.project_root = str(tmp_path)
    orchestrator._executor_workflow_factory = PreviewManager
    params = {"provider": "codex"}
    if profile_id:
        params["profile_id"] = profile_id

    result = orchestrator._prompt_to_plan_run_preview(params)

    assert result.ok is True
    preview_params = calls[-1][1]
    run_params = result.next_actions[0]["params"]
    if profile_id:
        assert preview_params["profile_id"] == profile_id
        assert run_params["profile_id"] == profile_id
    else:
        assert "profile_id" not in preview_params
        assert "profile_id" not in run_params


@pytest.mark.parametrize("profile_id", ["local_codex_commander", ""])
def test_prompt_to_plan_run_preserves_effective_profile_in_status_continuation(
    tmp_path,
    profile_id: str,
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    class RunManager:
        def __init__(self, project_root: str) -> None:
            assert project_root == str(tmp_path)

        def handle(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
            calls.append((action, dict(params)))
            assert action == "run_once"
            effective_profile = params.get("profile_id") or "web_gpt_commander"
            return {
                "ok": True,
                "status": "started",
                "run_id": "executor_run_prompt_123",
                "polling_guidance": {"profile_id": effective_profile},
            }

    orchestrator = WorkflowOrchestrator.__new__(WorkflowOrchestrator)
    orchestrator.project_root = str(tmp_path)
    orchestrator._executor_workflow_factory = RunManager
    params = {
        "provider": "codex",
        "preview_id": "executor_preview_prompt_123",
    }
    if profile_id:
        params["profile_id"] = profile_id

    result = orchestrator._prompt_to_plan_run(params)

    assert result.ok is True
    run_params = calls[0][1]
    status_params = result.next_actions[0]["params"]
    if profile_id:
        assert run_params["profile_id"] == profile_id
        assert status_params["profile_id"] == profile_id
    else:
        assert "profile_id" not in run_params
        assert status_params["profile_id"] == "web_gpt_commander"
