from __future__ import annotations

import json
from typing import Any

from runner.functional_mvp_contract import (
    FUNCTIONAL_MVP_POLLING_PROFILE,
    FUNCTIONAL_MVP_SECURITY_PROFILE,
)
from runner.mcp_commander_public import COMMANDER_EXPOSED_TOOLS, CommanderPublicProjector
from runner.mcp_functional_mvp import MCPFunctionalMVPWorkflow
from runner.mcp_server import MCPPlanningBridgeServer
from runner.executor_run_workflow import ExecutorRunOnceService
from runner.core_orchestrator import WorkflowOrchestrator


RUN_ID = "exec_run_functional_mvp_123456"


class FakeRouter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def handle(self, workflow: str, params: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((workflow, dict(params)))
        phase = params["phase"]
        if phase == "preview":
            return {"ok": True, "preview_ids": ["plan_preview_functional_123"]}
        if phase == "apply":
            return {"ok": True, "result": {"inserted_version": "R0.functional"}}
        if phase == "run_preview":
            return {"ok": True, "preview_ids": ["executor_preview_functional_123"]}
        if phase == "run":
            return {
                "ok": True,
                "status": "started",
                "result": {
                    "run_id": RUN_ID,
                    "next_poll_after_seconds": 3,
                },
            }
        raise AssertionError(phase)


class FakeManager:
    status_payload: dict[str, Any] = {}

    def __init__(self, project_root: str) -> None:
        self.project_root = project_root
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def latest_active_run_id(self) -> str:
        return RUN_ID

    def handle(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((action, dict(params)))
        if action == "preflight":
            return {
                "ok": True,
                "preflight_blocked": False,
                "runner_status": "PROMPT_READY",
            }
        if action == "status":
            return {"ok": True, "next_poll_after_seconds": 3, **self.status_payload}
        raise AssertionError(action)


class FakeReportStore:
    def __init__(self, project_root: str) -> None:
        self.project_root = project_root

    def get_report(self, **params: Any) -> dict[str, Any]:
        assert params["report_id"] == "report-functional-123"
        return {
            "ok": True,
            "report": {
                "provider": "codex",
                "project_root": "/private/should-not-escape",
                "changed_files": [
                    "runner/public.py",
                    "/private/should-not-escape/secret.py",
                    "../outside.py",
                ],
                "summary": {
                    "changed_files": [
                        "runner/public.py",
                        "/private/should-not-escape/secret.py",
                    ],
                    "validation_status_summary": "passed",
                    "validation_sample": ["pytest: PASS"],
                    "validation_failed_command_count": 0,
                    "risk_and_followups": ["No automatic delivery."],
                },
                "token_usage": {"input_tokens": 12, "output_tokens": 34},
            },
            "report_markdown": "Implemented the bounded functional route.",
        }


def _workflow(tmp_path, *, router: FakeRouter | None = None) -> MCPFunctionalMVPWorkflow:
    actual_router = router or FakeRouter()
    return MCPFunctionalMVPWorkflow(
        str(tmp_path),
        workflow_router_factory=lambda: actual_router,
        executor_workflow_factory=FakeManager,
        report_store_factory=FakeReportStore,
    )


def test_public_inventory_stays_nine_and_schema_reaches_functional_mvp(tmp_path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="commander")
    workflow_tool = next(tool for tool in server.tool_defs if tool.name == "run_mcp_workflow")

    assert len(COMMANDER_EXPOSED_TOOLS) == 9
    assert "manage_executor_workflow" not in COMMANDER_EXPOSED_TOOLS
    assert "functional_mvp" in workflow_tool.input_schema["properties"]["workflow"]["enum"]
    assert {"run_id", "model", "executor_session_mode"} <= set(
        workflow_tool.input_schema["properties"]
    )


def test_functional_mvp_run_composes_existing_lifecycle_and_returns_immediately(tmp_path) -> None:
    router = FakeRouter()
    result = _workflow(tmp_path, router=router).handle(
        {
            "phase": "run",
            "user_request": "Update runner/public.py and run its focused test.",
            "allowed_files": ["runner/public.py"],
            "acceptance_commands": ["pytest -q tests/test_public.py"],
        }
    )

    assert result["ok"] is True
    assert result["status"] == "started"
    assert result["run_id"] == RUN_ID
    assert result["terminal"] is False
    assert result["executor_run_status"] == "running"
    assert result["security_profile"] == FUNCTIONAL_MVP_SECURITY_PROFILE
    assert result["cryptographic_execution_proof"] is False
    assert [params["phase"] for _, params in router.calls] == [
        "preview",
        "apply",
        "run_preview",
        "run",
    ]
    assert all(workflow == "agent_dispatch" for workflow, _ in router.calls)
    assert router.calls[-1][1]["profile_id"] == FUNCTIONAL_MVP_POLLING_PROFILE
    assert "manage_executor_workflow" not in json.dumps(result)


def test_actual_run_mcp_workflow_surface_routes_functional_mvp(tmp_path, monkeypatch) -> None:
    router = FakeRouter()
    server = MCPPlanningBridgeServer(str(tmp_path))
    monkeypatch.setattr(server, "_create_mcp_workflow_router", lambda: router)
    monkeypatch.setattr("runner.mcp_functional_mvp.MCPExecutorWorkflowManager", FakeManager)

    result = server._tool_run_mcp_workflow(
        {
            "workflow": "functional_mvp",
            "phase": "run",
            "user_request": "Update runner/public.py and validate it.",
            "allowed_files": ["runner/public.py"],
            "acceptance_commands": ["pytest -q tests/test_public.py"],
        }
    )

    assert result["ok"] is True
    assert result["workflow"] == "functional_mvp"
    assert result["run_id"] == RUN_ID
    assert [params["phase"] for _, params in router.calls] == [
        "preview",
        "apply",
        "run_preview",
        "run",
    ]


def test_public_surface_smoke_start_status_read(tmp_path, monkeypatch) -> None:
    router = FakeRouter()
    server = MCPPlanningBridgeServer(str(tmp_path))
    monkeypatch.setattr(server, "_create_mcp_workflow_router", lambda: router)
    monkeypatch.setattr("runner.mcp_functional_mvp.MCPExecutorWorkflowManager", FakeManager)
    monkeypatch.setattr("runner.mcp_functional_mvp.ExecutorRunReportStore", FakeReportStore)

    started = server._tool_run_mcp_workflow(
        {
            "workflow": "functional_mvp",
            "phase": "run",
            "user_request": "Update runner/public.py and validate it.",
            "allowed_files": ["runner/public.py"],
            "acceptance_commands": ["pytest -q tests/test_public.py"],
        }
    )
    FakeManager.status_payload = {
        "run_id": RUN_ID,
        "terminal": False,
        "executor_run_status": "running",
    }
    running = server._tool_run_mcp_workflow(
        {"workflow": "functional_mvp", "phase": "status", "run_id": started["run_id"]}
    )
    FakeManager.status_payload = {
        "run_id": RUN_ID,
        "terminal": True,
        "executor_run_status": "completed",
        "report_id": "report-functional-123",
    }
    completed = server._tool_run_mcp_workflow(
        {"workflow": "functional_mvp", "phase": "read", "run_id": started["run_id"]}
    )

    assert started["status"] == "started"
    assert running["executor_run_status"] == "running"
    assert running["result_ready"] is False
    assert completed["executor_run_status"] == "completed"
    assert completed["result_ready"] is True
    assert completed["changed_files"] == ["runner/public.py"]
    assert completed["validation_status_summary"] == "passed"


def test_functional_mvp_status_uses_web_profile_and_normalizes_running(tmp_path) -> None:
    FakeManager.status_payload = {
        "run_id": RUN_ID,
        "terminal": False,
        "executor_run_status": "running",
        "claimed_at": "2026-09-01T01:02:03Z",
        "last_meaningful_progress": {"available": True, "stage": "provider"},
    }
    workflow = _workflow(tmp_path)
    result = workflow.handle({"phase": "status", "run_id": RUN_ID})

    assert result["run_id"] == RUN_ID
    assert result["terminal"] is False
    assert result["executor_run_status"] == "running"
    assert result["result_ready"] is False
    assert result["next_actions"][0]["arguments"] == {
        "workflow": "functional_mvp",
        "phase": "status",
        "run_id": RUN_ID,
    }


def test_functional_mvp_inspect_is_compact_and_reports_active_run(tmp_path) -> None:
    result = _workflow(tmp_path).handle({"phase": "inspect", "provider": "codex"})

    assert result["available"] is True
    assert result["provider"] == "codex"
    assert result["runner_managed"] is True
    assert result["executor_preflight_ready"] is True
    assert result["active_run_id_or_empty"] == RUN_ID
    assert result["functional_mvp_version"] == "functional_mvp.v1"


def test_functional_mvp_status_reports_failed_terminal_run(tmp_path) -> None:
    FakeManager.status_payload = {
        "run_id": RUN_ID,
        "terminal": True,
        "executor_run_status": "failed",
        "error_code": "EXECUTOR_FAILED",
        "finished_at": "2026-09-01T01:03:04Z",
    }
    result = _workflow(tmp_path).handle({"phase": "status", "run_id": RUN_ID})

    assert result["terminal"] is True
    assert result["executor_run_status"] == "failed"
    assert result["result_ready"] is True
    assert result["error_code"] == "EXECUTOR_FAILED"
    assert result["next_actions"][0]["arguments"]["phase"] == "read"


def test_functional_mvp_read_returns_safe_completed_result(tmp_path) -> None:
    FakeManager.status_payload = {
        "run_id": RUN_ID,
        "terminal": True,
        "executor_run_status": "completed",
        "claimed_at": "2026-09-01T01:02:03Z",
        "finished_at": "2026-09-01T01:03:04Z",
        "report_id": "report-functional-123",
        "model": "gpt-functional",
    }
    result = _workflow(tmp_path).handle({"phase": "read", "run_id": RUN_ID})

    assert result["ok"] is True
    assert result["terminal"] is True
    assert result["result_ready"] is True
    assert result["changed_files"] == ["runner/public.py"]
    assert result["validation_status_summary"] == "passed"
    assert result["validation_sample"] == ["pytest: PASS"]
    assert result["executor_report_preview"].startswith("Implemented")
    serialized = json.dumps(result)
    assert "/private/" not in serialized
    assert "manage_executor_workflow" not in serialized


def test_functional_mvp_read_while_running_returns_status_guidance(tmp_path) -> None:
    FakeManager.status_payload = {
        "run_id": RUN_ID,
        "terminal": False,
        "executor_run_status": "stalled",
    }
    result = _workflow(tmp_path).handle({"phase": "read", "run_id": RUN_ID})

    assert result["ok"] is True
    assert result["result_ready"] is False
    assert result["executor_run_status"] == "stalled"


def test_commander_projection_retains_functional_run_handle_without_hidden_tool(tmp_path) -> None:
    raw = {
        "ok": True,
        "workflow": "functional_mvp",
        "phase": "run",
        "status": "started",
        "run_id": RUN_ID,
        "terminal": False,
        "executor_run_status": "running",
        "result_ready": False,
        "next_poll_after_seconds": 3,
        "next_actions": [
            {
                "tool": "run_mcp_workflow",
                "arguments": {
                    "workflow": "functional_mvp",
                    "phase": "status",
                    "run_id": RUN_ID,
                },
                "reason": "Check executor progress.",
            }
        ],
    }
    projected = CommanderPublicProjector(str(tmp_path)).project_tool_result(
        {"ok": True, "tool": "run_mcp_workflow", "data": raw},
        params={"workflow": "functional_mvp", "phase": "run"},
    )

    serialized = json.dumps(projected)
    assert RUN_ID in serialized
    assert "manage_executor_workflow" not in serialized
    assert projected["data"]["outcome"] == "in_progress"


def test_commander_projection_retains_functional_result_fields(tmp_path) -> None:
    raw = {
        "ok": True,
        "workflow": "functional_mvp",
        "phase": "read",
        "status": "succeeded",
        "run_id": RUN_ID,
        "terminal": True,
        "executor_run_status": "completed",
        "result_ready": True,
        "changed_files": ["runner/public.py"],
        "validation_status_summary": "passed",
        "executor_summary": "status=completed; changed_files=1; validation=passed",
    }
    projected = CommanderPublicProjector(str(tmp_path)).project_tool_result(
        {"ok": True, "tool": "run_mcp_workflow", "data": raw},
        params={"workflow": "functional_mvp", "phase": "read", "run_id": RUN_ID},
    )

    facts = projected["data"]["facts"]
    assert facts["run_id"] == RUN_ID
    assert facts["terminal"] is True
    assert facts["executor_run_status"] == "completed"
    assert facts["result_ready"] is True
    assert facts["changed_files"] == ["runner/public.py"]
    assert facts["validation_status_summary"] == "passed"
    assert facts["executor_summary"].startswith("status=completed")


def test_development_profile_relaxes_only_the_fresh_start_authority_gate(tmp_path) -> None:
    service = ExecutorRunOnceService(str(tmp_path))

    assert service._fresh_authority_dispatch_gate(
        recommended_action="start_new",
        executor_session_mode="auto",
        executor_authority_id="",
        admission_sha256="",
    ) == "FRESH_EXECUTOR_AUTHORITY_REQUIRED"
    assert service._fresh_authority_dispatch_gate(
        recommended_action="start_new",
        executor_session_mode="auto",
        executor_authority_id="",
        admission_sha256="",
        security_profile=FUNCTIONAL_MVP_SECURITY_PROFILE,
    ) is None
    development_gate = service._fresh_authority_execution_gate(
        provider="codex",
        executor_session_mode="auto",
        executor_authority_id="",
        admission_sha256="",
        continuation_recommended_action="start_new",
        run_id=RUN_ID,
        preview_id="executor_preview_functional_123",
        current_head="a" * 40,
        work_target={},
        security_profile=FUNCTIONAL_MVP_SECURITY_PROFILE,
    )
    assert development_gate == {
        "ok": True,
        "security_profile": FUNCTIONAL_MVP_SECURITY_PROFILE,
        "cryptographic_execution_proof": False,
        "runtime_attestation": False,
    }


def test_agent_dispatch_run_now_uses_existing_async_run_once(tmp_path) -> None:
    manager_calls: list[tuple[str, dict[str, Any]]] = []

    class StartManager:
        def __init__(self, project_root: str) -> None:
            assert project_root == str(tmp_path)

        def handle(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
            manager_calls.append((action, dict(params)))
            return {
                "ok": True,
                "status": "started",
                "run_id": RUN_ID,
                "next_poll_after_seconds": 3,
            }

    orchestrator = WorkflowOrchestrator.__new__(WorkflowOrchestrator)
    orchestrator.project_root = str(tmp_path)
    orchestrator._executor_workflow_factory = StartManager
    orchestrator._agent_dispatch_precheck = lambda *args, **kwargs: {
        "ok": True,
        "provider": "codex",
        "steps": [],
    }
    orchestrator._validate_agent_dispatch_executor_preview_source = lambda *args: None

    result = orchestrator._agent_dispatch_run(
        {
            "preview_id": "executor_preview_functional_123",
            "provider": "codex",
            "profile_id": FUNCTIONAL_MVP_POLLING_PROFILE,
            "security_profile": FUNCTIONAL_MVP_SECURITY_PROFILE,
        }
    )

    assert result.ok is True
    assert result.status == "started"
    assert result.result is not None
    assert result.result["run_id"] == RUN_ID
    assert manager_calls == [
        (
            "run_once",
            {
                "preview_id": "executor_preview_functional_123",
                "provider": "codex",
                "execution_mode": "run",
                "profile_id": FUNCTIONAL_MVP_POLLING_PROFILE,
                "security_profile": FUNCTIONAL_MVP_SECURITY_PROFILE,
            },
        )
    ]
