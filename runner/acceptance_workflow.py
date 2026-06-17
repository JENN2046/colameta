import os
from typing import Any

from runner.workspace import ProjectWorkspace
from runner.plan_loader import PlanLoader
from runner.state_machine import RunnerStateMachine
from runner.state_mutation_gateway import StateMutationGateway
from runner.state_store import StateStore


class AcceptanceRerunService:
    def __init__(self, project_root: str):
        self.project_root = project_root

    def rerun_acceptance(self) -> dict[str, Any]:
        workspace = ProjectWorkspace.from_project_path(self.project_root)
        workspace.ensure_directories()
        loader = PlanLoader()
        plan = loader.load_plan(workspace.plan_file)
        plan.project_root = workspace.workspace_root
        plan.logs_dir = workspace.logs_dir
        plan.runtime_dir = workspace.runtime_dir
        plan.state_file = workspace.state_file
        if not os.path.isabs(plan.rules_file):
            plan.rules_file = workspace.rules_file
        loader.validate_plan(plan)
        store = StateStore()
        state = store.load_state(workspace.state_file)
        machine = RunnerStateMachine(plan, state)

        current_index = state.current_version_index
        if not isinstance(current_index, int) or not (0 <= current_index < len(plan.versions)):
            return {
                "ok": False,
                "action": "rerun_acceptance",
                "error_code": "NO_CURRENT_VERSION",
                "message": "当前没有可验收版本。",
                "version": state.current_version,
                "current_version": state.current_version,
            }

        current_plan_version = plan.versions[current_index]
        if not current_plan_version.acceptance_commands:
            return {
                "ok": False,
                "action": "rerun_acceptance",
                "error_code": "NO_ACCEPTANCE_COMMANDS",
                "message": "当前版本没有 acceptance_commands。",
                "version": state.current_version,
                "current_version": state.current_version,
            }

        baseline_updated_at = state.updated_at
        try:
            result = machine.run_acceptance_only()
        except Exception as e:
            return {
                "ok": False,
                "action": "rerun_acceptance",
                "error_code": "ACCEPTANCE_FAILED",
                "message": str(e),
                "version": state.current_version,
                "current_version": state.current_version,
            }

        StateMutationGateway().save(state, workspace.state_file, expected_updated_at=baseline_updated_at)

        failed_indexes: list[int] = []
        cmd_results: list[dict[str, Any]] = []
        if result.acceptance_run:
            for idx, item in enumerate(result.acceptance_run.commands, start=1):
                cmd_results.append(
                    {
                        "index": idx,
                        "status": item.status,
                        "exit_code": item.exit_code,
                        "original_command": item.original_command or item.command,
                        "executed_command": item.executed_command or item.command,
                        "cwd": item.cwd,
                    }
                )
                if item.status != "PASSED":
                    failed_indexes.append(idx)

        return {
            "ok": True,
            "action": "rerun_acceptance",
            "message": "重跑验收完成。",
            "run_status": result.status,
            "runner_status": state.status,
            "audit_file": result.audit_file,
            "scope_status": result.scope_check.status if result.scope_check else "NOT_CHECKED",
            "failed_command_indexes": failed_indexes,
            "command_results": cmd_results,
            "version": state.current_version,
            "current_version": state.current_version,
        }
