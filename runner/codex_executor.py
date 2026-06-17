import os
from dataclasses import dataclass, replace as dataclass_replace
from typing import Any, Callable, Literal

from adapters.codex_cli_adapter import CodexCliAdapter, CodexCliError, CodexRunResult
from runner.execution_profile import load_runner_settings_for_project, resolve_version_execution_model
from runner.executor_session import ExecutorSessionStore
from runner.prompt_builder import PromptBuilder
from runner.workspace import ProjectWorkspace
from schemas.plan import BuildRunnerPlan
from schemas.state import BuildRunnerState


@dataclass
class CodexExecutionResult:
    prompt: str
    prompt_file: str
    codex_run: CodexRunResult
    result_summary: "CodexExecutorResultSummary"


@dataclass
class CodexExecutorResultSummary:
    provider: Literal["codex"]
    execution_mode: Literal["normal", "fix"]
    status: Literal["completed", "failed"]
    log_path: str
    summary: str | None
    summary_path: str | None
    attempted_resume: bool = False
    used_resume: bool = False
    fallback_to_new_session: bool = False
    resume_failed_reason: str | None = None
    command_shape: str | None = None
    token_usage: dict[str, Any] | None = None


class CodexExecutor:
    def __init__(self, workspace: ProjectWorkspace, adapter: CodexCliAdapter | None = None, model_override: str | None = None):
        self.workspace = workspace
        self.adapter = adapter
        self.model_override = model_override.strip() if isinstance(model_override, str) and model_override.strip() else None
        self.prompt_builder = PromptBuilder()
        self._settings = load_runner_settings_for_project(workspace.workspace_root)

    def run_current_version(
        self,
        plan: BuildRunnerPlan,
        state: BuildRunnerState,
        progress: Callable[[str, str | None], None] | None = None,
        executor_session_mode: str = "auto",
        run_id: str = "",
        event_context: dict[str, Any] | None = None,
    ) -> CodexExecutionResult:
        if state.current_version is None:
            raise ValueError("当前没有版本，无法运行执行器。")
        current_version = plan.versions[state.current_version_index]
        self.model = self.model_override or resolve_version_execution_model(
            plan=plan, version=current_version, provider="codex",
            settings=self._settings,
        )
        prompt = self.prompt_builder.build_version_prompt(plan, current_version)
        prompt_file = os.path.join(plan.runtime_dir, "current-prompt.md")
        if progress:
            progress("prompt_generated", prompt_file)
            progress("codex_started", None)
        summary_file = os.path.join(plan.runtime_dir, "codex-last-message.md")

        codex_run = self._execute_codex_with_auto_resume(
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
            progress("log_written", codex_run.log_path)

        state.last_generated_prompt_file = prompt_file
        state.last_prompt_file = prompt_file
        state.last_log_file = codex_run.log_path

        codex_token_usage = codex_run.token_usage if isinstance(codex_run.token_usage, dict) else None
        result_summary = CodexExecutorResultSummary(
            provider="codex",
            execution_mode="normal",
            status="completed",
            log_path=codex_run.log_path,
            summary=codex_run.summary,
            summary_path=codex_run.summary_path,
            attempted_resume=codex_run.attempted_resume,
            used_resume=codex_run.used_resume,
            fallback_to_new_session=codex_run.fallback_to_new_session,
            resume_failed_reason=codex_run.resume_failed_reason,
            command_shape=codex_run.command_shape,
            token_usage=codex_token_usage,
        )
        self._record_execution_session(
            plan=plan,
            version=current_version.version,
            execution_mode="normal",
            attempt=state.attempt,
            log_path=result_summary.log_path,
            summary_path=result_summary.summary_path,
            codex_run=codex_run,
        )
        session_rec_warning = getattr(codex_run, "record_execution_session_warning", None)
        if session_rec_warning:
            setattr(result_summary, "record_execution_session_warning", session_rec_warning)
        fallback_note_warning = getattr(codex_run, "fallback_note_warning", None)
        if fallback_note_warning:
            setattr(result_summary, "fallback_note_warning", fallback_note_warning)
        return CodexExecutionResult(
            prompt=prompt,
            prompt_file=prompt_file,
            codex_run=codex_run,
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
    ) -> CodexExecutionResult:
        if state.current_version is None:
            raise ValueError("当前没有版本，无法运行执行器。")
        current_version = plan.versions[state.current_version_index]
        self.model = self.model_override or resolve_version_execution_model(
            plan=plan, version=current_version, provider="codex",
            settings=self._settings,
        )
        fix_prompt_file = os.path.join(plan.runtime_dir, "current-fix-prompt.md")
        if not os.path.exists(fix_prompt_file):
            raise FileNotFoundError("当前修复提示词不存在，请先按 F 生成修复提示词。")

        with open(fix_prompt_file, "r", encoding="utf-8") as f:
            prompt = f.read()

        if progress:
            progress("fix_prompt_loaded", fix_prompt_file)
            progress("codex_started", None)
        summary_file = os.path.join(plan.runtime_dir, "codex-fix-last-message.md")

        codex_run = self._execute_codex_with_auto_resume(
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
            progress("log_written", codex_run.log_path)

        state.last_log_file = codex_run.log_path
        state.last_prompt_file = fix_prompt_file
        state.last_generated_prompt_file = fix_prompt_file

        codex_token_usage = codex_run.token_usage if isinstance(codex_run.token_usage, dict) else None
        result_summary = CodexExecutorResultSummary(
            provider="codex",
            execution_mode="fix",
            status="completed",
            log_path=codex_run.log_path,
            summary=codex_run.summary,
            summary_path=codex_run.summary_path,
            attempted_resume=codex_run.attempted_resume,
            used_resume=codex_run.used_resume,
            fallback_to_new_session=codex_run.fallback_to_new_session,
            resume_failed_reason=codex_run.resume_failed_reason,
            command_shape=codex_run.command_shape,
            token_usage=codex_token_usage,
        )
        self._record_execution_session(
            plan=plan,
            version=current_version.version,
            execution_mode="fix",
            attempt=state.attempt,
            log_path=result_summary.log_path,
            summary_path=result_summary.summary_path,
            codex_run=codex_run,
        )
        session_rec_warning = getattr(codex_run, "record_execution_session_warning", None)
        if session_rec_warning:
            setattr(result_summary, "record_execution_session_warning", session_rec_warning)
        fallback_note_warning = getattr(codex_run, "fallback_note_warning", None)
        if fallback_note_warning:
            setattr(result_summary, "fallback_note_warning", fallback_note_warning)
        return CodexExecutionResult(
            prompt=prompt,
            prompt_file=fix_prompt_file,
            codex_run=codex_run,
            result_summary=result_summary,
        )

    def _execute_codex_with_auto_resume(
        self,
        *,
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
    ) -> CodexRunResult:
        adapter = self.adapter or CodexCliAdapter(model=getattr(self, "model", None))
        conversation_id = None
        if executor_session_mode != "start_new":
            candidate = self._get_codex_auto_resume_candidate(plan.project_root)
            conversation_id = candidate.get("conversation_id") if candidate.get("enabled") else None
        if not conversation_id:
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
            progress("codex_resume_started", None)
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
                resume_conversation_id=conversation_id,
                run_id=run_id,
                event_context=event_context,
            )
        except CodexCliError as resume_error:
            resume_failed_reason = self._sanitize_codex_error(resume_error)
            if progress:
                progress("codex_resume_fallback_started", None)
            try:
                fallback_run = adapter.execute_prompt(
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
            except CodexCliError as fallback_error:
                fallback_reason = self._sanitize_codex_error(fallback_error)
                resume_log_path = getattr(resume_error, "log_path", None)
                message = (
                    "Codex resume 执行失败，并且 fallback 新会话执行也失败。"
                    f" resume_failed_reason={resume_failed_reason};"
                    f" resume_log_path={resume_log_path or '无'};"
                    f" fallback_failed_reason={fallback_reason}"
                )
                raise CodexCliError(message, log_path=fallback_error.log_path) from fallback_error

            fallback_run = dataclass_replace(
                fallback_run,
                attempted_resume=True,
                used_resume=False,
                resume_conversation_id_present=False,
                fallback_to_new_session=True,
                resume_failed_reason=resume_failed_reason,
                command_shape="codex_exec_new_after_resume_fallback",
            )
            fallback_note_warning = self._append_fallback_note(fallback_run.log_path, resume_failed_reason)
            if fallback_note_warning:
                setattr(fallback_run, "fallback_note_warning", fallback_note_warning)
            return fallback_run

    def _get_codex_auto_resume_candidate(self, project_root: str) -> dict[str, Any]:
        store = ExecutorSessionStore(project_root)
        status = store.get_status()
        decision = store.get_continuation_decision(requested_provider="codex")
        invocation = store.get_resume_invocation_preview(requested_provider="codex")
        record = status.get("record") if isinstance(status, dict) else None
        if not isinstance(record, dict):
            record = {}

        conversation_id = record.get("conversation_id")
        blockers: list[str] = []
        if not isinstance(conversation_id, str) or not conversation_id.strip():
            blockers.append("conversation_id_missing")
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
        if invocation.get("resume_invocation_kind") != "codex_exec_resume_session":
            blockers.append("resume_invocation_kind_mismatch")

        return {
            "enabled": not blockers,
            "conversation_id": conversation_id.strip() if isinstance(conversation_id, str) else None,
            "blockers": blockers,
            "decision": decision,
            "invocation": invocation,
            "status": status,
        }

    def _sanitize_codex_error(self, error: CodexCliError) -> str:
        message = str(error).strip() or error.__class__.__name__
        log_path = getattr(error, "log_path", None)
        if log_path and log_path not in message:
            message = f"{message}; log_path={log_path}"
        return message[:800]

    def _append_fallback_note(self, log_path: str | None, resume_failed_reason: str) -> str | None:
        if not log_path:
            return None
        try:
            with open(log_path, "a", encoding="utf-8") as handle:
                handle.write("\n## resume fallback\n")
                handle.write("attempted_resume: true\n")
                handle.write("used_resume: false\n")
                handle.write("fallback_to_new_session: true\n")
                handle.write(f"resume_failed_reason: {resume_failed_reason}\n")
            return None
        except Exception as e:
            return f"fallback_note_write_failed:{e.__class__.__name__}:{str(e)[:200]}"

    def _record_execution_session(
        self,
        *,
        plan: BuildRunnerPlan,
        version: str,
        execution_mode: str,
        attempt: int,
        log_path: str | None,
        summary_path: str | None,
        codex_run: CodexRunResult,
    ) -> None:
        try:
            conversation_id = codex_run.conversation_id
            has_resume_hint = bool(conversation_id)
            if codex_run.used_resume:
                source = "codex_exec_resume"
                resume_enabled = True
            elif codex_run.fallback_to_new_session:
                source = "codex_exec_resume_fallback_new_session"
                resume_enabled = False
            else:
                source = "codex_exec_resume_hint" if has_resume_hint else "codex_exec_stateless"
                resume_enabled = False
            ExecutorSessionStore(plan.project_root).record_execution(
                provider="codex",
                version=version,
                execution_mode=execution_mode,
                attempt=attempt,
                session_id=None,
                session_file=None,
                conversation_id=conversation_id,
                resume_supported=has_resume_hint,
                resume_enabled=resume_enabled,
                log_path=log_path,
                summary_path=summary_path,
                source=source,
            )
        except Exception as rec_exc:
            rec_msg = f"record_execution_session_failed:{rec_exc.__class__.__name__}:{str(rec_exc)[:300]}"
            setattr(codex_run, "record_execution_session_warning", rec_msg)
