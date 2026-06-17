from dataclasses import dataclass

from runner.state_mutation_gateway import StateMutationGateway
from runner.state_store import StateStore
from schemas.state import BuildRunnerState, BuildVersionRuntimeState


MANUAL_VALIDATION_APPLY_NOTE = "manual_validation_apply: 手动/等价验收通过，版本状态已刷新。"


@dataclass(frozen=True)
class ManualValidationPassMutation:
    version: str
    runner_status_to: str
    version_status_to: str
    validation_run_id: str
    commands: list[str]
    current_head: str
    reason: str
    recorded_at: str
    note: str = MANUAL_VALIDATION_APPLY_NOTE


@dataclass(frozen=True)
class ManualValidationPassResult:
    state_file: str
    runner_status: str
    version_status: str
    recorded_at: str


@dataclass(frozen=True)
class ScopeMismatchResolutionMutation:
    runner_status_to: str
    version_status_to: str
    note: str
    resolution_metadata: dict[str, object]
    recorded_at: str


@dataclass(frozen=True)
class ScopeMismatchResolutionResult:
    state_file: str
    runner_status: str
    version_status: str
    note: str
    resolution_metadata: dict[str, object]
    recorded_at: str


@dataclass(frozen=True)
class RecheckReportStateRefreshMutation:
    runner_status_to: str
    version_status_to: str
    recorded_at: str


@dataclass(frozen=True)
class RecheckReportStateRefreshResult:
    state_file: str
    runner_status: str
    version_status: str
    completed_at: str | None
    recorded_at: str


@dataclass(frozen=True)
class ExecutorRunLifecycleStatePersistMutation:
    lifecycle_point: str


@dataclass(frozen=True)
class ExecutorRunLifecycleStatePersistResult:
    state_file: str
    lifecycle_point: str
    runner_status: str
    current_version: str | None
    current_version_index: int


class RunnerStateMutationService:
    def __init__(self, state_store: StateStore | None = None, gateway: StateMutationGateway | None = None):
        if gateway is not None:
            self._gateway = gateway
        else:
            self._state_store = state_store or StateStore()
            self._gateway = StateMutationGateway(self._state_store)

    def apply_manual_validation_pass(
        self,
        *,
        state: BuildRunnerState,
        target_runtime: BuildVersionRuntimeState,
        state_file: str,
        mutation: ManualValidationPassMutation,
    ) -> ManualValidationPassResult:
        expected_updated_at = state.updated_at
        state.status = mutation.runner_status_to
        target_runtime.status = mutation.version_status_to
        target_runtime.completed_at = target_runtime.completed_at or mutation.recorded_at
        target_runtime.commit_hash = mutation.current_head or target_runtime.commit_hash
        target_runtime.note = mutation.note
        existing_meta = target_runtime.metadata if isinstance(target_runtime.metadata, dict) else {}
        existing_meta["manual_validation_passed"] = {
            "validation_run_id": mutation.validation_run_id,
            "commands": list(mutation.commands),
            "current_head": mutation.current_head,
            "reason": mutation.reason,
            "recorded_at": mutation.recorded_at,
        }
        target_runtime.metadata = existing_meta
        state.updated_at = mutation.recorded_at
        self._gateway.save(state, state_file, expected_updated_at=expected_updated_at)
        return ManualValidationPassResult(
            state_file=state_file,
            runner_status=state.status,
            version_status=target_runtime.status,
            recorded_at=mutation.recorded_at,
        )

    def apply_scope_mismatch_resolution(
        self,
        *,
        state: BuildRunnerState,
        target_runtime: BuildVersionRuntimeState,
        state_file: str,
        mutation: ScopeMismatchResolutionMutation,
    ) -> ScopeMismatchResolutionResult:
        expected_updated_at = state.updated_at
        target_runtime.status = mutation.version_status_to
        target_runtime.note = mutation.note
        existing_meta = target_runtime.metadata if isinstance(target_runtime.metadata, dict) else {}
        existing_meta["scope_mismatch_resolution"] = dict(mutation.resolution_metadata)
        target_runtime.metadata = existing_meta
        state.status = mutation.runner_status_to
        state.updated_at = mutation.recorded_at
        self._gateway.save(state, state_file, expected_updated_at=expected_updated_at)
        return ScopeMismatchResolutionResult(
            state_file=state_file,
            runner_status=state.status,
            version_status=target_runtime.status,
            note=target_runtime.note or "",
            resolution_metadata=dict(existing_meta["scope_mismatch_resolution"]),
            recorded_at=mutation.recorded_at,
        )

    def apply_recheck_report_state_refresh(
        self,
        *,
        state: BuildRunnerState,
        target_runtime: BuildVersionRuntimeState,
        state_file: str,
        mutation: RecheckReportStateRefreshMutation,
    ) -> RecheckReportStateRefreshResult:
        expected_updated_at = state.updated_at
        state.status = mutation.runner_status_to
        target_runtime.status = mutation.version_status_to
        if not getattr(target_runtime, "completed_at", None):
            target_runtime.completed_at = mutation.recorded_at
        state.updated_at = mutation.recorded_at
        self._gateway.save(state, state_file, expected_updated_at=expected_updated_at)
        return RecheckReportStateRefreshResult(
            state_file=state_file,
            runner_status=state.status,
            version_status=target_runtime.status,
            completed_at=target_runtime.completed_at,
            recorded_at=mutation.recorded_at,
        )

    def persist_executor_run_post_provider_state(
        self,
        *,
        state: BuildRunnerState,
        state_file: str,
        mutation: ExecutorRunLifecycleStatePersistMutation,
        baseline_updated_at: str | None = None,
    ) -> ExecutorRunLifecycleStatePersistResult:
        kwargs = {}
        if baseline_updated_at is not None:
            kwargs["expected_updated_at"] = baseline_updated_at
        self._gateway.save(state, state_file, **kwargs)
        return ExecutorRunLifecycleStatePersistResult(
            state_file=state_file,
            lifecycle_point=mutation.lifecycle_point,
            runner_status=state.status,
            current_version=state.current_version,
            current_version_index=state.current_version_index,
        )

    def persist_executor_run_post_acceptance_state(
        self,
        *,
        state: BuildRunnerState,
        state_file: str,
        mutation: ExecutorRunLifecycleStatePersistMutation,
        baseline_updated_at: str | None = None,
    ) -> ExecutorRunLifecycleStatePersistResult:
        kwargs = {}
        if baseline_updated_at is not None:
            kwargs["expected_updated_at"] = baseline_updated_at
        self._gateway.save(state, state_file, **kwargs)
        return ExecutorRunLifecycleStatePersistResult(
            state_file=state_file,
            lifecycle_point=mutation.lifecycle_point,
            runner_status=state.status,
            current_version=state.current_version,
            current_version_index=state.current_version_index,
        )
