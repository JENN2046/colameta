"""Public-compatible start/status/result facade for the existing executor."""

from __future__ import annotations

import os
from typing import Any, Callable

from runner.executor_run_reports import ExecutorRunReportStore
from runner.functional_mvp_contract import (
    FUNCTIONAL_MVP_POLLING_PROFILE,
    FUNCTIONAL_MVP_SECURITY_PROFILE,
    FUNCTIONAL_MVP_VERSION,
    FUNCTIONAL_MVP_WORKFLOW,
)
from runner.mcp_executor_workflow import MCPExecutorWorkflowManager


FUNCTIONAL_MVP_PHASES = frozenset({"inspect", "run", "status", "read"})
_PUBLIC_EXECUTOR_STATUSES = frozenset(
    {"queued", "running", "stalled", "completed", "failed", "orphaned", "cancelled", "unknown"}
)


class FunctionalMVPWorkflowError(ValueError):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message


class MCPFunctionalMVPWorkflow:
    """Compose the existing agent-dispatch and executor state machines."""

    def __init__(
        self,
        project_root: str,
        *,
        workflow_router_factory: Callable[[], Any],
        executor_workflow_factory: Callable[[str], MCPExecutorWorkflowManager] | None = None,
        report_store_factory: Callable[[str], ExecutorRunReportStore] | None = None,
    ) -> None:
        self.project_root = os.path.abspath(os.path.expanduser(project_root))
        self._workflow_router_factory = workflow_router_factory
        self._executor_workflow_factory = executor_workflow_factory or MCPExecutorWorkflowManager
        self._report_store_factory = report_store_factory or ExecutorRunReportStore

    def handle(self, params: dict[str, Any]) -> dict[str, Any]:
        phase = self._string(params.get("phase"), default="inspect", lower=True)
        if phase not in FUNCTIONAL_MVP_PHASES:
            raise FunctionalMVPWorkflowError(
                "FUNCTIONAL_MVP_PHASE_NOT_SUPPORTED",
                f"functional_mvp 不支持 phase={phase}；支持 inspect、run、status、read。",
            )
        if phase == "inspect":
            return self._inspect(params)
        if phase == "run":
            return self._run(params)
        if phase == "status":
            return self._status(params)
        return self._read(params)

    def _manager(self) -> MCPExecutorWorkflowManager:
        return self._executor_workflow_factory(self.project_root)

    def _inspect(self, params: dict[str, Any]) -> dict[str, Any]:
        provider = self._provider(params)
        manager = self._manager()
        preflight = manager.handle("preflight", {"provider": provider, "execution_mode": "run"})
        active_run_id = manager.latest_active_run_id()
        available = bool(preflight.get("ok"))
        preflight_ready = bool(preflight.get("ok")) and not bool(preflight.get("preflight_blocked"))
        runner_status = self._string(preflight.get("runner_status"), lower=True)
        runner_managed = runner_status not in {"", "source_only", "source-only"}
        return {
            "ok": True,
            "workflow": FUNCTIONAL_MVP_WORKFLOW,
            "phase": "inspect",
            "status": "succeeded",
            "available": available,
            "provider": provider,
            "runner_managed": runner_managed,
            "executor_preflight_ready": preflight_ready,
            "active_run_id_or_empty": active_run_id,
            "functional_mvp_version": FUNCTIONAL_MVP_VERSION,
            **self._security_boundary(),
            "message": (
                "Functional MVP executor is ready."
                if preflight_ready
                else "Functional MVP executor preflight is blocked."
            ),
        }

    def _run(self, params: dict[str, Any]) -> dict[str, Any]:
        user_request = self._string(params.get("user_request"))
        if not user_request:
            raise FunctionalMVPWorkflowError(
                "USER_REQUEST_REQUIRED",
                "functional_mvp/run 需要非空 user_request。",
            )
        provider = self._provider(params)
        router = self._workflow_router_factory()
        forwarded = {
            key: params[key]
            for key in (
                "allowed_files",
                "forbidden_files",
                "acceptance_commands",
                "context_files",
                "name",
                "description",
                "model",
                "executor_session_mode",
            )
            if params.get(key) is not None
        }
        common = {
            "provider": provider,
            "security_profile": FUNCTIONAL_MVP_SECURITY_PROFILE,
            **forwarded,
        }
        preview = router.handle(
            "agent_dispatch",
            {**common, "phase": "preview", "user_request": user_request},
        )
        plan_preview_id = self._preview_id(preview)
        if not plan_preview_id:
            return self._lifecycle_failure("preview", preview)

        applied = router.handle(
            "agent_dispatch",
            {**common, "phase": "apply", "preview_id": plan_preview_id},
        )
        if not applied.get("ok"):
            return self._lifecycle_failure("apply", applied)
        version = self._first_string(applied, ("version", "inserted_version", "updated_version"))

        run_preview_params: dict[str, Any] = {**common, "phase": "run_preview"}
        if version:
            run_preview_params["version"] = version
        executor_preview = router.handle("agent_dispatch", run_preview_params)
        executor_preview_id = self._preview_id(executor_preview)
        if not executor_preview_id:
            return self._lifecycle_failure("run_preview", executor_preview)

        started = router.handle(
            "agent_dispatch",
            {
                **common,
                "phase": "run",
                "preview_id": executor_preview_id,
                "profile_id": FUNCTIONAL_MVP_POLLING_PROFILE,
            },
        )
        run_id = self._first_string(started, ("run_id",))
        if not started.get("ok") or not run_id:
            return self._lifecycle_failure("run", started)
        next_poll = self._first_int(started, ("next_poll_after_seconds",), default=3)
        return {
            "ok": True,
            "workflow": FUNCTIONAL_MVP_WORKFLOW,
            "phase": "run",
            "status": "started",
            "run_id": run_id,
            "terminal": False,
            "executor_run_status": "running",
            "next_poll_after_seconds": next_poll,
            **self._security_boundary(),
            "message": "Executor started in the background. Use functional_mvp/status with this run_id.",
            "next_actions": [self._next_action("status", run_id)],
        }

    def _status(self, params: dict[str, Any]) -> dict[str, Any]:
        run_id = self._required_run_id(params)
        raw = self._manager().handle(
            "status",
            {
                "run_id": run_id,
                "profile_id": FUNCTIONAL_MVP_POLLING_PROFILE,
                "poll_attempt": params.get("poll_attempt", 1),
            },
        )
        return self._public_status(raw, run_id=run_id, phase="status")

    def _read(self, params: dict[str, Any]) -> dict[str, Any]:
        run_id = self._required_run_id(params)
        manager = self._manager()
        raw_status = manager.handle(
            "status",
            {"run_id": run_id, "profile_id": FUNCTIONAL_MVP_POLLING_PROFILE},
        )
        status = self._public_status(raw_status, run_id=run_id, phase="read")
        if not status["terminal"]:
            status["result_ready"] = False
            return status

        report_id = self._string(raw_status.get("report_id")) or self._string(
            raw_status.get("possible_report_id")
        )
        if not report_id:
            status["result_ready"] = True
            status["ok"] = status["executor_run_status"] == "completed"
            return status
        report_result = self._report_store_factory(self.project_root).get_report(
            report_id=report_id,
            latest=False,
            include_markdown=True,
            max_markdown_chars=12000,
        )
        if not report_result.get("ok"):
            return {
                **status,
                "ok": False,
                "result_ready": False,
                "error_code": "FUNCTIONAL_MVP_RESULT_UNAVAILABLE",
                "message": "The terminal executor report is not currently readable.",
            }
        report = report_result.get("report")
        report = report if isinstance(report, dict) else {}
        summary = report.get("summary")
        summary = summary if isinstance(summary, dict) else {}
        changed_files = self._safe_relative_paths(
            summary.get("changed_files") or report.get("changed_files") or []
        )
        validation_sample = self._safe_string_list(summary.get("validation_sample"), limit=20)
        risks = self._safe_string_list(summary.get("risk_and_followups"), limit=30)
        report_preview = self._string(report_result.get("report_markdown"))[:12000]
        completed = status["executor_run_status"] == "completed"
        return {
            **status,
            "ok": completed,
            "result_ready": True,
            "provider": self._string(report.get("provider")),
            "model": self._string(raw_status.get("model")),
            "changed_files": changed_files,
            "validation_status_summary": self._string(
                summary.get("validation_status_summary"), default="unknown"
            ),
            "validation_sample": validation_sample,
            "validation_failed_command_count": self._first_int(
                summary, ("validation_failed_command_count",), default=0
            ),
            "risk_and_followups": risks,
            "executor_summary": self._executor_summary(status, changed_files, summary),
            "executor_report_preview": report_preview,
            "token_usage": report.get("token_usage") if isinstance(report.get("token_usage"), dict) else {},
            "message": self._string(status.get("message")) or (
                "Executor completed; the final result is ready."
                if completed
                else "Executor finished without a successful result."
            ),
        }

    def _public_status(self, raw: dict[str, Any], *, run_id: str, phase: str) -> dict[str, Any]:
        executor_status = self._string(raw.get("executor_run_status"), default="unknown", lower=True)
        if executor_status not in _PUBLIC_EXECUTOR_STATUSES:
            executor_status = "unknown"
        terminal = bool(raw.get("terminal"))
        if executor_status == "unknown":
            terminal = False
        next_phase = "read" if terminal else "status"
        result = {
            "ok": bool(raw.get("ok", True)),
            "workflow": FUNCTIONAL_MVP_WORKFLOW,
            "phase": phase,
            "status": "succeeded",
            "run_id": run_id,
            "terminal": terminal,
            "executor_run_status": executor_status,
            "started_at": self._first_string(raw, ("worker_started_at", "thread_started_at", "claimed_at")),
            "finished_at": self._string(raw.get("finished_at")),
            "last_meaningful_progress": raw.get("last_meaningful_progress", {}),
            "next_poll_after_seconds": self._first_int(raw, ("next_poll_after_seconds",), default=3),
            "result_ready": terminal,
            "message": self._string(raw.get("message")) or self._status_message(executor_status),
            "next_actions": [self._next_action(next_phase, run_id)],
        }
        error_code = self._string(raw.get("error_code"))
        if error_code:
            result["error_code"] = error_code
        return result

    @staticmethod
    def _security_boundary() -> dict[str, Any]:
        return {
            "security_profile": FUNCTIONAL_MVP_SECURITY_PROFILE,
            "cryptographic_execution_proof": False,
            "runtime_attestation": False,
            "automatic_delivery": False,
        }

    @staticmethod
    def _next_action(phase: str, run_id: str) -> dict[str, Any]:
        return {
            "tool": "run_mcp_workflow",
            "arguments": {
                "workflow": FUNCTIONAL_MVP_WORKFLOW,
                "phase": phase,
                "run_id": run_id,
            },
            "reason": "Read the executor result." if phase == "read" else "Check executor progress.",
        }

    def _lifecycle_failure(self, stage: str, result: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": False,
            "workflow": FUNCTIONAL_MVP_WORKFLOW,
            "phase": "run",
            "status": "blocked",
            "terminal": True,
            "executor_run_status": "failed",
            "result_ready": False,
            "error_code": self._first_string(result, ("error_code",)) or "FUNCTIONAL_MVP_LIFECYCLE_BLOCKED",
            "message": self._first_string(result, ("message",)) or f"Existing agent_dispatch {stage} was blocked.",
            "failed_lifecycle_stage": stage,
            **self._security_boundary(),
        }

    def _required_run_id(self, params: dict[str, Any]) -> str:
        run_id = self._string(params.get("run_id"))
        if not run_id:
            raise FunctionalMVPWorkflowError("RUN_ID_REQUIRED", "functional_mvp/status|read 需要 run_id。")
        return run_id

    def _provider(self, params: dict[str, Any]) -> str:
        provider = self._string(params.get("provider"), default="codex", lower=True)
        if provider not in {"codex", "pi", "opencode"}:
            raise FunctionalMVPWorkflowError("INVALID_PROVIDER", f"不支持 provider={provider}。")
        return provider

    @staticmethod
    def _preview_id(result: dict[str, Any]) -> str:
        ids = result.get("preview_ids")
        if isinstance(ids, list):
            for value in ids:
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return MCPFunctionalMVPWorkflow._first_string(result, ("preview_id",))

    @staticmethod
    def _first_string(value: Any, keys: tuple[str, ...]) -> str:
        if isinstance(value, dict):
            for key in keys:
                candidate = value.get(key)
                if isinstance(candidate, str) and candidate.strip():
                    return candidate.strip()
            for nested in value.values():
                candidate = MCPFunctionalMVPWorkflow._first_string(nested, keys)
                if candidate:
                    return candidate
        elif isinstance(value, list):
            for nested in value:
                candidate = MCPFunctionalMVPWorkflow._first_string(nested, keys)
                if candidate:
                    return candidate
        return ""

    @staticmethod
    def _first_int(value: Any, keys: tuple[str, ...], *, default: int) -> int:
        if isinstance(value, dict):
            for key in keys:
                candidate = value.get(key)
                if isinstance(candidate, int) and not isinstance(candidate, bool):
                    return candidate
            for nested in value.values():
                candidate = MCPFunctionalMVPWorkflow._first_int(nested, keys, default=-1)
                if candidate >= 0:
                    return candidate
        elif isinstance(value, list):
            for nested in value:
                candidate = MCPFunctionalMVPWorkflow._first_int(nested, keys, default=-1)
                if candidate >= 0:
                    return candidate
        return default

    @staticmethod
    def _string(value: Any, *, default: str = "", lower: bool = False) -> str:
        text = value.strip() if isinstance(value, str) else default
        return text.lower() if lower else text

    @staticmethod
    def _safe_relative_paths(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        safe: list[str] = []
        for item in value:
            if not isinstance(item, str):
                continue
            path = item.strip().replace("\\", "/")
            if not path or os.path.isabs(path) or path == ".." or path.startswith("../") or "/../" in path:
                continue
            if path not in safe:
                safe.append(path)
        return safe[:200]

    @staticmethod
    def _safe_string_list(value: Any, *, limit: int) -> list[str]:
        if not isinstance(value, list):
            return []
        return [item.strip()[:1000] for item in value if isinstance(item, str) and item.strip()][:limit]

    @staticmethod
    def _status_message(executor_status: str) -> str:
        return {
            "running": "Executor is still running.",
            "stalled": "Executor is running but meaningful progress appears stale.",
            "completed": "Executor completed; the result is ready.",
            "failed": "Executor failed; read the terminal result for details.",
            "orphaned": "Executor run was orphaned after its worker disappeared.",
            "cancelled": "Executor run was cancelled.",
        }.get(executor_status, "Executor run status is unknown.")

    @staticmethod
    def _executor_summary(
        status: dict[str, Any],
        changed_files: list[str],
        summary: dict[str, Any],
    ) -> str:
        validation = str(summary.get("validation_status_summary") or "unknown")
        return (
            f"status={status['executor_run_status']}; "
            f"changed_files={len(changed_files)}; validation={validation}"
        )
