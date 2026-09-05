from __future__ import annotations

from typing import Any

import pytest

from runner.core_orchestrator import WorkflowOrchestrator


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
