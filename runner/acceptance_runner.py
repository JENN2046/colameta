import datetime
import shlex

from adapters.shell_adapter import ShellAdapter
from runner.acceptance_command_policy import (
    AcceptanceCommandPolicyError,
    acceptance_command_to_execution_argv,
    canonical_acceptance_project_root,
)
from schemas.plan import BuildVersion
from schemas.result import AcceptanceCommandResult, AcceptanceRunResult


class AcceptanceRunner:
    def __init__(self):
        self.shell_adapter = ShellAdapter()

    def _execution_metadata(
        self,
        command: str,
        project_root: str,
    ) -> tuple[str, str | None]:
        try:
            argv = acceptance_command_to_execution_argv(
                command,
                project_root=project_root,
            )
        except AcceptanceCommandPolicyError:
            return command, None
        resolved_python = argv[0] if len(argv) > 1 and argv[1] == "-I" else None
        return shlex.join(argv), resolved_python

    def run_acceptance(
        self,
        run_id: str,
        version: BuildVersion,
        project_root: str,
    ) -> AcceptanceRunResult:
        run_started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

        command_results: list[AcceptanceCommandResult] = []
        overall_status = "PASSED"
        cmd_cwd = canonical_acceptance_project_root(project_root)
        for acc_cmd in version.acceptance_commands:
            original_command = acc_cmd.command
            executed_command, resolved_python = self._execution_metadata(
                original_command,
                cmd_cwd,
            )

            shell_result = self.shell_adapter.run(
                command=original_command,
                cwd=cmd_cwd,
                timeout_seconds=acc_cmd.timeout_seconds,
                project_root=cmd_cwd,
            )

            cmd_status = "PASSED" if shell_result.exit_code == 0 else "FAILED"

            acc_cmd_result = AcceptanceCommandResult(
                command=original_command,
                status=cmd_status,
                exit_code=shell_result.exit_code,
                stdout=shell_result.stdout,
                stderr=shell_result.stderr,
                started_at=shell_result.started_at,
                completed_at=shell_result.completed_at,
                duration_ms=shell_result.duration_ms,
                cwd=cmd_cwd,
                original_command=original_command,
                executed_command=executed_command,
                resolved_python=resolved_python,
                venv_bin_path=None,
                rewrite_warning=None,
            )

            command_results.append(acc_cmd_result)

            if cmd_status == "FAILED":
                if not acc_cmd.continue_on_failure:
                    overall_status = "FAILED"
                    break
                overall_status = "FAILED"

        # Also run default acceptance commands if there are no version specific ones?
        # The schema says default_acceptance_commands exists but docs usually say run version.acceptance_commands
        # Let's just follow version.acceptance_commands as specified in the schema

        if not version.acceptance_commands:
            # If no commands, default to passed?
            overall_status = "PASSED"

        run_completed_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

        return AcceptanceRunResult(
            run_id=run_id,
            version=version.version,
            # The outer state machine owns the durable attempt counter.
            attempt=1,
            status=overall_status,
            commands=command_results,
            started_at=run_started_at,
            completed_at=run_completed_at,
        )
