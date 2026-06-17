import os
from dataclasses import dataclass
from typing import Any, Callable, Literal

from adapters.pi_rpc_adapter import PiRpcAdapter, PiRpcRunResult
from runner.execution_profile import load_runner_settings_for_project, resolve_version_execution_model
from runner.executor_session import ExecutorSessionStore
from runner.prompt_builder import PromptBuilder
from runner.workspace import ProjectWorkspace
from schemas.plan import BuildRunnerPlan
from schemas.state import BuildRunnerState


@dataclass
class PiExecutionResult:
    prompt: str
    prompt_file: str
    pi_run: PiRpcRunResult
    result_summary: "PiExecutorResultSummary"


@dataclass
class PiExecutorResultSummary:
    provider: Literal["pi"]
    execution_mode: Literal["normal", "fix"]
    status: Literal["completed", "failed"]
    log_path: str
    summary: str | None
    summary_path: str | None
    token_usage: dict[str, Any] | None = None


class PiExecutor:
    def __init__(self, workspace: ProjectWorkspace, adapter: PiRpcAdapter | None = None, model_override: str | None = None):
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
    ) -> PiExecutionResult:
        if state.current_version is None:
            raise ValueError("当前没有版本，无法运行执行器。")
        current_version = plan.versions[state.current_version_index]
        self.model = self.model_override or resolve_version_execution_model(
            plan=plan, version=current_version, provider="pi",
            settings=self._settings,
        )
        prompt = self.prompt_builder.build_version_prompt(plan, current_version)
        prompt_file = os.path.join(plan.runtime_dir, "current-prompt.md")
        if progress:
            progress("prompt_generated", prompt_file)
            progress("pi_started", None)
        adapter = self.adapter or PiRpcAdapter(model=getattr(self, "model", None))
        pi_run = adapter.execute_prompt(
            project_root=plan.project_root,
            logs_dir=plan.logs_dir,
            runner_dir=self.workspace.runner_dir,
            version=current_version.version,
            attempt=state.attempt,
            prompt=prompt,
            prompt_file=prompt_file,
            execution_mode="normal",
            run_id=run_id,
            event_context=event_context,
        )
        if progress:
            progress("log_written", pi_run.log_path)
        state.last_generated_prompt_file = prompt_file
        state.last_prompt_file = prompt_file
        state.last_log_file = pi_run.log_path
        result_summary = PiExecutorResultSummary(
            provider="pi",
            execution_mode="normal",
            status="completed",
            log_path=pi_run.log_path,
            summary=pi_run.summary,
            summary_path=pi_run.summary_path,
        )
        self._record_execution_session(
            plan=plan,
            version=current_version.version,
            execution_mode="normal",
            attempt=state.attempt,
            log_path=result_summary.log_path,
            summary_path=result_summary.summary_path,
            session_id=pi_run.session_id,
            session_file=pi_run.session_file,
            source="pi_rpc",
            resume_supported=True,
        )
        return PiExecutionResult(
            prompt=prompt,
            prompt_file=prompt_file,
            pi_run=pi_run,
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
    ) -> PiExecutionResult:
        if state.current_version is None:
            raise ValueError("当前没有版本，无法运行执行器。")
        current_version = plan.versions[state.current_version_index]
        self.model = self.model_override or resolve_version_execution_model(
            plan=plan, version=current_version, provider="pi",
            settings=self._settings,
        )
        fix_prompt_file = os.path.join(plan.runtime_dir, "current-fix-prompt.md")
        if not os.path.exists(fix_prompt_file):
            raise FileNotFoundError("当前修复提示词不存在，请先按 F 生成修复提示词。")
        with open(fix_prompt_file, "r", encoding="utf-8") as f:
            prompt = f.read()
        if progress:
            progress("fix_prompt_loaded", fix_prompt_file)
            progress("pi_started", None)
        adapter = self.adapter or PiRpcAdapter(model=getattr(self, "model", None))
        pi_run = adapter.execute_prompt(
            project_root=plan.project_root,
            logs_dir=plan.logs_dir,
            runner_dir=self.workspace.runner_dir,
            version=current_version.version,
            attempt=state.attempt,
            prompt=prompt,
            prompt_file=fix_prompt_file,
            execution_mode="fix",
            run_id=run_id,
            event_context=event_context,
        )
        if progress:
            progress("log_written", pi_run.log_path)
        state.last_log_file = pi_run.log_path
        result_summary = PiExecutorResultSummary(
            provider="pi",
            execution_mode="fix",
            status="completed",
            log_path=pi_run.log_path,
            summary=pi_run.summary,
            summary_path=pi_run.summary_path,
        )
        self._record_execution_session(
            plan=plan,
            version=current_version.version,
            execution_mode="fix",
            attempt=state.attempt,
            log_path=result_summary.log_path,
            summary_path=result_summary.summary_path,
            session_id=pi_run.session_id,
            session_file=pi_run.session_file,
            source="pi_rpc",
            resume_supported=True,
        )
        return PiExecutionResult(
            prompt=prompt,
            prompt_file=fix_prompt_file,
            pi_run=pi_run,
            result_summary=result_summary,
        )

    def _record_execution_session(
        self,
        *,
        plan: BuildRunnerPlan,
        version: str,
        execution_mode: str,
        attempt: int,
        log_path: str | None,
        summary_path: str | None,
        session_id: str | None,
        session_file: str | None,
        source: str,
        resume_supported: bool,
    ) -> None:
        try:
            ExecutorSessionStore(plan.project_root).record_execution(
                provider="pi",
                version=version,
                execution_mode=execution_mode,
                attempt=attempt,
                session_id=session_id,
                session_file=session_file,
                conversation_id=None,
                resume_supported=resume_supported,
                resume_enabled=False,
                log_path=log_path,
                summary_path=summary_path,
                source=source,
            )
        except Exception:
            pass
