import datetime
import uuid
from typing import Optional
from schemas.plan import BuildRunnerPlan
from schemas.state import BuildRunnerState
from schemas.result import VersionRunResult, ScopeCheckResult
from runner.acceptance_runner import AcceptanceRunner
from runner.audit_builder import AuditBuilder
from runner.prompt_builder import PromptBuilder
from runner.scope_checker import ScopeChecker
import os

class RunnerStateMachine:
    def __init__(self, plan: BuildRunnerPlan, state: BuildRunnerState):
        self.plan = plan
        self.state = state
        self.acceptance_runner = AcceptanceRunner()
        self.audit_builder = AuditBuilder()
        self.prompt_builder = PromptBuilder()
        self.scope_checker = ScopeChecker()

    def _now(self) -> str:
        return datetime.datetime.now(datetime.timezone.utc).astimezone().isoformat()

    def _current_version_state(self):
        if not self.state.current_version:
            raise ValueError("No current version")
        return self.state.versions[self.state.current_version_index]

    def _current_version_plan(self):
        if not self.state.current_version:
            raise ValueError("No current version")
        return self.plan.versions[self.state.current_version_index]

    def _build_acceptance_audit(self, current_v_plan, acc_result, scope_check: ScopeCheckResult) -> str:
        current_prompt_path = os.path.join(self.plan.runtime_dir, "current-prompt.md")
        current_prompt_content = ""
        if os.path.exists(current_prompt_path):
            with open(current_prompt_path, "r", encoding="utf-8") as f:
                current_prompt_content = f.read()

        audit_report = self.audit_builder.build_audit(
            plan=self.plan,
            version=current_v_plan,
            state=self.state,
            acceptance=acc_result,
            scope_check=scope_check,
            current_prompt=current_prompt_content
        )

        os.makedirs(self.plan.logs_dir, exist_ok=True)
        audit_file_path = os.path.join(self.plan.logs_dir, f"{current_v_plan.version}-audit.md")
        with open(audit_file_path, "w", encoding="utf-8") as f:
            f.write(audit_report.copyable_audit_markdown)

        self.state.last_audit_file = audit_file_path
        self._current_version_state().last_audit_file = audit_file_path
        return audit_file_path

    def _run_acceptance(self, is_fix: bool) -> VersionRunResult:
        if not self.state.current_version:
            raise ValueError("No current version")
            
        current_v_state = self._current_version_state()
        current_v_plan = self._current_version_plan()
        previous_status = self.state.status
        
        run_id = str(uuid.uuid4())
        
        if is_fix:
            self.state.status = "RUNNING_FIX_ACCEPTANCE"
            current_v_state.status = "FIX_ACCEPTANCE_RUNNING"
        else:
            self.state.status = "RUNNING_ACCEPTANCE"
            current_v_state.status = "ACCEPTANCE_RUNNING"
        
        acc_result = self.acceptance_runner.run_acceptance(
            run_id=run_id,
            version=current_v_plan,
            project_root=self.plan.project_root
        )
        
        acc_result.attempt = self.state.attempt
        
        audit_file_path = None
        scope_check = ScopeCheckResult(status="NOT_CHECKED")
        run_status = acc_result.status
        
        if acc_result.status == "PASSED":
            scope_check = self.scope_checker.check_scope(
                version=current_v_plan,
                project_root=self.plan.project_root,
            )
            if scope_check.status == "FAILED":
                audit_file_path = self._build_acceptance_audit(current_v_plan, acc_result, scope_check)
                self.state.status = "BLOCKED_BY_SCOPE_VIOLATION"
                current_v_state.status = "BLOCKED"
                run_status = "FAILED"
            else:
                self.state.status = "VERSION_PASSED"
                current_v_state.status = "PASSED"
                current_v_state.completed_at = self._now()
                self.state.last_audit_file = None
                current_v_state.last_audit_file = None
                self.state.last_error = None
        else:
            audit_file_path = self._build_acceptance_audit(current_v_plan, acc_result, scope_check)

            max_attempts_reached = (
                is_fix
                and self.state.attempt >= self.state.max_fix_attempts_per_version
            )
            keep_max_block = (
                previous_status == "BLOCKED_BY_MAX_FIX_ATTEMPTS"
                and self.state.attempt >= self.state.max_fix_attempts_per_version
            )

            if max_attempts_reached or keep_max_block:
                self.state.status = "BLOCKED_BY_MAX_FIX_ATTEMPTS"
                current_v_state.status = "BLOCKED"
            else:
                self.state.status = "BLOCKED_BY_ACCEPTANCE_FAILURE"
                current_v_state.status = "FAILED_BLOCKED"
            
        self.state.updated_at = self._now()
        current_v_state.last_run_id = run_id
        
        return VersionRunResult(
            run_id=run_id,
            version=current_v_plan.version,
            attempt=self.state.attempt,
            status=run_status,
            model_run=None,
            acceptance_run=acc_result,
            scope_check=scope_check,
            changed_files=scope_check.changed_files,
            audit_file=audit_file_path,
            log_file="",
            started_at=acc_result.started_at,
            completed_at=acc_result.completed_at
        )

    def run_acceptance_only(self) -> VersionRunResult:
        return self._run_acceptance(is_fix=False)
        
    def mark_model_done_and_run_acceptance(self) -> VersionRunResult:
        return self.run_acceptance_only()

    def mark_fix_model_done_and_run_acceptance(self) -> VersionRunResult:
        return self._run_acceptance(is_fix=True)

    def mark_blocked_by_no_changes(
        self,
        version_index: int,
        evidence: dict[str, object],
        *,
        recorded_at: str | None = None,
    ) -> BuildRunnerState:
        if version_index < 0 or version_index >= len(self.state.versions):
            raise ValueError("Invalid version index")

        current_v_state = self.state.versions[version_index]
        recorded_at = recorded_at or self._now()

        self.state.status = "BLOCKED_BY_MODEL_FAILURE"
        current_v_state.status = "FAILED_BLOCKED"
        current_v_state.attempt = self.state.attempt
        current_v_state.completed_at = None
        current_v_state.note = "executor_no_changes: acceptance passed but no allowed_files diff was produced."
        existing_meta = current_v_state.metadata if isinstance(current_v_state.metadata, dict) else {}
        existing_meta["executor_no_changes_blocked"] = {
            "mode": evidence.get("mode"),
            "provider": evidence.get("provider"),
            "version": evidence.get("version"),
            "executor_changed_files": list(evidence.get("executor_changed_files") or []),
            "validation_commands": list(evidence.get("validation_commands") or []),
            "recorded_at": recorded_at,
        }
        current_v_state.metadata = existing_meta
        self.state.updated_at = recorded_at
        return self.state

    def get_current_audit_file(self) -> str | None:
        current_v_state = None
        if 0 <= self.state.current_version_index < len(self.state.versions):
            current_v_state = self.state.versions[self.state.current_version_index]

        candidates = []
        if self.state.last_audit_file:
            candidates.append(self.state.last_audit_file)
        if current_v_state and current_v_state.last_audit_file:
            candidates.append(current_v_state.last_audit_file)
        if self.state.current_version:
            candidates.append(os.path.join(self.plan.logs_dir, f"{self.state.current_version}-audit.md"))

        for path in candidates:
            if path and os.path.exists(path):
                return path
        return None

    def paste_manual_fix_prompt(
        self,
        content: str,
        *,
        audit_file_override: str | None = None,
        audit_markdown_override: str | None = None,
        allow_max_attempt_recovery: bool = False,
    ) -> str:
        if self.state.status == "BLOCKED_BY_MAX_FIX_ATTEMPTS":
            max_attempts = int(self.state.max_fix_attempts_per_version or 0)
            attempts_exhausted = self.state.attempt >= max_attempts if max_attempts > 0 else True
            if attempts_exhausted or not allow_max_attempt_recovery:
                raise ValueError("当前版本已达到最大修复次数，流程已暂停。")

        audit_file = audit_file_override or self.get_current_audit_file()
        audit_markdown = str(audit_markdown_override or "")
        if not audit_file and not audit_markdown.strip():
            raise ValueError("当前没有审计包，不能生成修复提示词。")

        if not content.strip():
            raise ValueError("提供的修复提示词为空。")

        if not self.state.current_version:
            raise ValueError("No current version")

        current_v_state = self.state.versions[self.state.current_version_index]
        current_v_plan = self.plan.versions[self.state.current_version_index]

        # 修复提示词只作用于当前失败版本；优先复用已有审计文件，其次复用已解析的外部证据。
        if audit_markdown.strip():
            audit_md = audit_markdown
        else:
            with open(audit_file, "r", encoding="utf-8") as f:
                audit_md = f.read()

        self.state.attempt += 1
        current_v_state.attempt = self.state.attempt
        os.makedirs(self.plan.runtime_dir, exist_ok=True)
        manual_fix_path = os.path.join(self.plan.runtime_dir, f"manual-fix-{current_v_plan.version}-attempt-{self.state.attempt}.md")
        with open(manual_fix_path, "w", encoding="utf-8") as f:
            f.write(content)

        fix_prompt = self.prompt_builder.build_fix_prompt(
            plan=self.plan,
            version=current_v_plan,
            audit_markdown=audit_md,
            manual_fix_prompt=content
        )

        self.state.status = "FIX_PROMPT_READY"
        current_v_state.status = "FIX_PROMPT_READY"
        if audit_file:
            self.state.last_audit_file = audit_file
            current_v_state.last_audit_file = audit_file
        self.state.updated_at = datetime.datetime.now(datetime.timezone.utc).astimezone().isoformat()
        
        return fix_prompt

    def _ensure_state_versions_aligned(self) -> None:
        from schemas.state import BuildVersionRuntimeState

        state_by_version = {v.version: v for v in self.state.versions}
        synced: list[BuildVersionRuntimeState] = []
        for plan_v in self.plan.versions:
            runtime = state_by_version.pop(plan_v.version, None)
            if runtime is None:
                runtime = BuildVersionRuntimeState(
                    version=plan_v.version,
                    name=plan_v.name,
                    status="NOT_STARTED",
                    attempt=0,
                )
            else:
                runtime.name = plan_v.name
            synced.append(runtime)
        if synced != self.state.versions:
            self.state.versions = synced

    def reopen_completed_state_if_pending(self) -> bool:
        if self.state.status != "COMPLETED":
            return False
        current_index = self.state.current_version_index
        if not isinstance(current_index, int) or current_index < 0:
            return False
        runtimes = self.state.versions or []
        if current_index >= len(runtimes):
            return False
        current_runtime = runtimes[current_index]
        if current_runtime.status != "PASSED":
            return False
        for index in range(current_index + 1, len(self.plan.versions)):
            if self.plan.versions[index].enabled:
                self.state.status = "VERSION_PASSED"
                self.state.completed_at = None
                return True
        return False

    def normalize_passed_current_version_status(self) -> None:
        if not self.state.current_version:
            return
        current_index = self.state.current_version_index
        if not isinstance(current_index, int) or current_index < 0 or current_index >= len(self.state.versions):
            return
        current_runtime = self.state.versions[current_index]
        if current_runtime.status == "PASSED" and self.state.status in {
            "READY",
            "BLOCKED_BY_MAX_FIX_ATTEMPTS",
        }:
            self.state.status = "VERSION_PASSED"

    def continue_next_version(self) -> BuildRunnerState:
        self.normalize_passed_current_version_status()
        if self.state.status != "VERSION_PASSED":
            raise ValueError("当前版本尚未通过，不能进入下一版本。")

        self._ensure_state_versions_aligned()

        next_index = None
        for index in range(self.state.current_version_index + 1, len(self.plan.versions)):
            if not self.plan.versions[index].enabled:
                continue
            candidate_state = self.state.versions[index]
            if candidate_state.status == "PASSED":
                continue
            next_index = index
            break

        if next_index is None:
            self.state.status = "COMPLETED"
            self.state.completed_at = self._now()
            self.state.updated_at = self.state.completed_at
            return self.state

        next_plan = self.plan.versions[next_index]
        next_state = self.state.versions[next_index]

        self.state.current_version_index = next_index
        self.state.current_version = next_plan.version
        self.state.attempt = 1
        self.state.status = "READY"
        self.state.last_error = None
        self.state.last_log_file = None
        if not next_state.status:
            next_state.status = "NOT_STARTED"
        next_state.version = next_plan.version
        next_state.name = next_plan.name
        self.state.updated_at = self._now()
        return self.state

    def reset_current_attempt(self, reason: str = "") -> BuildRunnerState:
        current_v_state = self._current_version_state()
        self.state.attempt = 1
        current_v_state.attempt = 0

        if self.get_current_audit_file():
            self.state.status = "BLOCKED_BY_ACCEPTANCE_FAILURE"
            current_v_state.status = "FAILED_BLOCKED"
        else:
            self.state.status = "READY"
            current_v_state.status = "NOT_STARTED"

        self.state.updated_at = self._now()
        return self.state
