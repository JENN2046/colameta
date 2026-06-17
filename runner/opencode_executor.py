import os
from dataclasses import dataclass
from typing import Any, Callable, Literal

from adapters.opencode_types import OpenCodeCliError, OpenCodeRunResult
from adapters.opencode_server_adapter import OpenCodeServerAdapter, OpenCodeServerError
from runner.executor_session import ExecutorSessionStore
from runner.prompt_builder import PromptBuilder
from runner.execution_profile import (
    load_runner_settings_for_project,
    resolve_version_execution_model,
)
from runner.workspace import ProjectWorkspace
from schemas.plan import BuildRunnerPlan
from schemas.state import BuildRunnerState




@dataclass
class OpenCodeExecutionResult:
    prompt: str
    prompt_file: str
    opencode_run: OpenCodeRunResult
    result_summary: "OpenCodeExecutorResultSummary"


@dataclass
class OpenCodeExecutorResultSummary:
    provider: Literal["opencode"]
    execution_mode: Literal["normal", "fix"]
    log_path: str
    summary: str | None
    summary_path: str | None
    full_report_text: str | None = None
    process_status: str = "completed"
    attempted_resume: bool = False
    used_resume: bool = False
    fallback_to_new_session: bool = False
    resume_failed_reason: str | None = None
    command_shape: str | None = None
    token_usage: dict[str, Any] | None = None


class OpenCodeExecutor:
    def __init__(
        self,
        workspace: ProjectWorkspace,
        adapter: OpenCodeServerAdapter | None = None,
        model_override: str | None = None,
    ):
        self.workspace = workspace
        self.model = None
        self.model_override = model_override.strip() if isinstance(model_override, str) and model_override.strip() else None
        self.adapter = adapter
        self.prompt_builder = PromptBuilder()
        self._settings = load_runner_settings_for_project(workspace.workspace_root)

    def _resolve_adapter(self, plan: BuildRunnerPlan, version, model: str | None) -> OpenCodeServerAdapter:
        if self.adapter is not None:
            return self.adapter
        return OpenCodeServerAdapter(model=model)

    def run_current_version(
        self,
        plan: BuildRunnerPlan,
        state: BuildRunnerState,
        progress: Callable[[str, str | None], None] | None = None,
        executor_session_mode: str = "auto",
        run_id: str = "",
        event_context: dict[str, Any] | None = None,
    ) -> OpenCodeExecutionResult:
        if state.current_version is None:
            raise ValueError("当前没有版本，无法运行执行器。")
        current_version = plan.versions[state.current_version_index]
        prompt = self.prompt_builder.build_version_prompt(plan, current_version)
        prompt_file = os.path.join(plan.runtime_dir, "current-prompt.md")
        if progress:
            progress("prompt_generated", prompt_file)
            progress("opencode_started", None)
        summary_file = os.path.join(plan.runtime_dir, "opencode-last-message.md")
        model = self.model_override or resolve_version_execution_model(
            plan=plan, version=current_version, provider="opencode",
            settings=self._settings,
        )
        adapter = self._resolve_adapter(plan, current_version, model)

        opencode_run = self._execute_opencode_with_auto_resume(
            adapter=adapter,
            plan=plan,
            version=current_version.version,
            attempt=state.attempt,
            prompt=prompt,
            prompt_file=prompt_file,
            summary_file=summary_file,
            execution_mode="normal",
            progress=progress,
            executor_session_mode=executor_session_mode,
            run_id=run_id,
            event_context=event_context,
        )

        if progress:
            progress("log_written", opencode_run.log_path)

        state.last_generated_prompt_file = prompt_file
        state.last_prompt_file = prompt_file
        state.last_log_file = opencode_run.log_path

        opencode_token_usage = opencode_run.token_usage if isinstance(opencode_run.token_usage, dict) else None
        result_summary = OpenCodeExecutorResultSummary(
            provider="opencode",
            execution_mode="normal",
            process_status="completed",
            log_path=opencode_run.log_path,
            summary=opencode_run.summary,
            summary_path=opencode_run.summary_path,
            full_report_text=getattr(opencode_run, "full_report_text", None),
            attempted_resume=opencode_run.attempted_resume,
            used_resume=opencode_run.used_resume,
            fallback_to_new_session=opencode_run.fallback_to_new_session,
            resume_failed_reason=opencode_run.resume_failed_reason,
            command_shape=opencode_run.command_shape,
            token_usage=opencode_token_usage,
        )
        self._record_execution_session(
            plan=plan,
            version=current_version.version,
            execution_mode="normal",
            attempt=state.attempt,
            log_path=result_summary.log_path,
            summary_path=result_summary.summary_path,
            opencode_run=opencode_run,
        )
        session_rec_warning = getattr(opencode_run, "record_execution_session_warning", None)
        if session_rec_warning:
            setattr(result_summary, "record_execution_session_warning", session_rec_warning)
        return OpenCodeExecutionResult(
            prompt=prompt,
            prompt_file=prompt_file,
            opencode_run=opencode_run,
            result_summary=result_summary,
        )

    def run_current_fix(
        self,
        plan: BuildRunnerPlan,
        state: BuildRunnerState,
        progress: Callable[[str, str | None], None] | None = None,
        executor_session_mode: str = "auto",
        run_id: str = "",
        event_context: dict[str, Any] | None = None,
    ) -> OpenCodeExecutionResult:
        if state.current_version is None:
            raise ValueError("当前没有版本，无法运行执行器。")
        current_version = plan.versions[state.current_version_index]
        fix_prompt_file = os.path.join(plan.runtime_dir, "current-fix-prompt.md")
        if not os.path.exists(fix_prompt_file):
            raise FileNotFoundError("当前修复提示词不存在，请先按 F 生成修复提示词。")

        with open(fix_prompt_file, "r", encoding="utf-8") as f:
            prompt = f.read()

        if progress:
            progress("fix_prompt_loaded", fix_prompt_file)
            progress("opencode_started", None)
        summary_file = os.path.join(plan.runtime_dir, "opencode-fix-last-message.md")
        model = self.model_override or resolve_version_execution_model(
            plan=plan, version=current_version, provider="opencode",
            settings=self._settings,
        )
        adapter = self._resolve_adapter(plan, current_version, model)

        opencode_run = self._execute_opencode_with_auto_resume(
            adapter=adapter,
            plan=plan,
            version=current_version.version,
            attempt=state.attempt,
            prompt=prompt,
            prompt_file=fix_prompt_file,
            summary_file=summary_file,
            execution_mode="fix",
            progress=progress,
            executor_session_mode=executor_session_mode,
            run_id=run_id,
            event_context=event_context,
        )

        if progress:
            progress("log_written", opencode_run.log_path)

        state.last_log_file = opencode_run.log_path
        state.last_prompt_file = fix_prompt_file
        state.last_generated_prompt_file = fix_prompt_file

        opencode_token_usage = opencode_run.token_usage if isinstance(opencode_run.token_usage, dict) else None
        result_summary = OpenCodeExecutorResultSummary(
            provider="opencode",
            execution_mode="fix",
            process_status="completed",
            log_path=opencode_run.log_path,
            summary=opencode_run.summary,
            summary_path=opencode_run.summary_path,
            full_report_text=getattr(opencode_run, "full_report_text", None),
            attempted_resume=opencode_run.attempted_resume,
            used_resume=opencode_run.used_resume,
            fallback_to_new_session=opencode_run.fallback_to_new_session,
            resume_failed_reason=opencode_run.resume_failed_reason,
            command_shape=opencode_run.command_shape,
            token_usage=opencode_token_usage,
        )
        self._record_execution_session(
            plan=plan,
            version=current_version.version,
            execution_mode="fix",
            attempt=state.attempt,
            log_path=result_summary.log_path,
            summary_path=result_summary.summary_path,
            opencode_run=opencode_run,
        )
        session_rec_warning = getattr(opencode_run, "record_execution_session_warning", None)
        if session_rec_warning:
            setattr(result_summary, "record_execution_session_warning", session_rec_warning)
        return OpenCodeExecutionResult(
            prompt=prompt,
            prompt_file=fix_prompt_file,
            opencode_run=opencode_run,
            result_summary=result_summary,
        )

    def _execute_opencode_with_auto_resume(
        self,
        *,
        adapter: OpenCodeServerAdapter,
        plan: BuildRunnerPlan,
        version: str,
        attempt: int,
        prompt: str,
        prompt_file: str,
        summary_file: str,
        execution_mode: Literal["normal", "fix"],
        progress: Callable[[str, str | None], None] | None = None,
        executor_session_mode: str = "auto",
        run_id: str = "",
        event_context: dict[str, Any] | None = None,
    ) -> OpenCodeRunResult:
        resume_session_id = None
        if executor_session_mode != "start_new":
            candidate = self._get_opencode_auto_resume_candidate(plan.project_root)
            resume_session_id = candidate.get("resume_session_id") if candidate.get("enabled") else None
        if not resume_session_id:
            return adapter.execute_prompt(
                project_root=plan.project_root,
                logs_dir=plan.logs_dir,
                version=version,
                attempt=attempt,
                prompt=prompt,
                prompt_file=prompt_file,
                summary_file=summary_file,
                execution_mode=execution_mode,
                run_id=run_id,
                event_context=event_context,
            )

        if progress:
            progress("opencode_resume_started", None)
        try:
            return adapter.execute_prompt(
                project_root=plan.project_root,
                logs_dir=plan.logs_dir,
                version=version,
                attempt=attempt,
                prompt=prompt,
                prompt_file=prompt_file,
                summary_file=summary_file,
                execution_mode=execution_mode,
                resume_session_id=resume_session_id,
                run_id=run_id,
                event_context=event_context,
            )
        except OpenCodeCliError as resume_error:
            resume_failed_reason = self._sanitize_opencode_error(resume_error)
            message = (
                "OpenCode resume 执行失败，已停止，不再 fallback 新会话。"
                f" resume_failed_reason={resume_failed_reason}"
            )
            raise OpenCodeCliError(message, log_path=getattr(resume_error, "log_path", None)) from resume_error

    def _get_opencode_auto_resume_candidate(self, project_root: str) -> dict[str, Any]:
        store = ExecutorSessionStore(project_root)
        status = store.get_status()
        decision = store.get_continuation_decision(requested_provider="opencode")
        invocation = store.get_resume_invocation_preview(requested_provider="opencode")
        record = status.get("record") if isinstance(status, dict) else None
        if not isinstance(record, dict):
            record = {}

        resume_session_id = self._select_opencode_resume_session_value(record)
        blockers: list[str] = []
        if not resume_session_id:
            blockers.append("opencode_resume_session_value_missing")
        if not decision.get("continuation_available"):
            blockers.append("continuation_unavailable")
        if decision.get("decision") != "resume_auto_eligible":
            blockers.append("decision_not_resume_candidate")
        if decision.get("hard_blockers"):
            blockers.extend(str(item) for item in decision.get("hard_blockers") or [])
        if invocation.get("hard_blockers"):
            blockers.extend(str(item) for item in invocation.get("hard_blockers") or [])
        if invocation.get("resume_invocation_supported") is not True:
            blockers.append("resume_invocation_unsupported")
        if invocation.get("resume_invocation_verified") is not True:
            blockers.append("resume_invocation_unverified")
        if invocation.get("resume_invocation_kind") != "opencode_run_session":
            blockers.append("resume_invocation_kind_mismatch")

        return {
            "enabled": not blockers,
            "resume_session_id": resume_session_id,
            "blockers": blockers,
            "decision": decision,
            "invocation": invocation,
            "status": status,
        }

    def _select_opencode_resume_session_value(self, record: dict[str, Any]) -> str | None:
        session_id = record.get("session_id")
        if isinstance(session_id, str) and session_id.strip():
            return session_id.strip()
        conversation_id = record.get("conversation_id")
        if isinstance(conversation_id, str) and conversation_id.strip():
            return conversation_id.strip()
        return None

    def _sanitize_opencode_error(self, error: OpenCodeCliError) -> str:
        message = str(error).strip() or error.__class__.__name__
        log_path = getattr(error, "log_path", None)
        if log_path and log_path not in message:
            message = f"{message}; log_path={log_path}"
        return message[:800]

    def _record_execution_session(
        self,
        *,
        plan: BuildRunnerPlan,
        version: str,
        execution_mode: str,
        attempt: int,
        log_path: str | None,
        summary_path: str | None,
        opencode_run: OpenCodeRunResult,
    ) -> None:
        try:
            conversation_id = opencode_run.conversation_id
            session_id = opencode_run.session_id
            session_file = opencode_run.session_file
            has_resume_hint = bool(conversation_id or session_id or session_file)
            if opencode_run.used_resume:
                source = "opencode_run_resume"
                resume_enabled = True
            elif opencode_run.fallback_to_new_session:
                source = "opencode_run_resume_fallback_new_session"
                resume_enabled = False
            else:
                source = "opencode_run_resume_hint" if has_resume_hint else "opencode_run_stateless"
                resume_enabled = False
            ExecutorSessionStore(plan.project_root).record_execution(
                provider="opencode",
                version=version,
                execution_mode=execution_mode,
                attempt=attempt,
                session_id=session_id,
                session_file=session_file,
                conversation_id=conversation_id,
                resume_supported=has_resume_hint,
                resume_enabled=resume_enabled,
                log_path=log_path,
                summary_path=summary_path,
                source=source,
            )
        except Exception as rec_exc:
            rec_msg = f"record_execution_session_failed:{rec_exc.__class__.__name__}:{str(rec_exc)[:300]}"
            setattr(opencode_run, "record_execution_session_warning", rec_msg)
