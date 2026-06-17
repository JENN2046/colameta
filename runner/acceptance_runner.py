import datetime
import os
import shlex
import shutil
from schemas.plan import BuildVersion
from schemas.result import AcceptanceRunResult, AcceptanceCommandResult
from adapters.shell_adapter import ShellAdapter

class AcceptanceRunner:
    def __init__(self):
        self.shell_adapter = ShellAdapter()

    def _resolve_python(self, project_root: str) -> str:
        venv_python = os.path.join(os.path.abspath(project_root), ".venv", "bin", "python")
        if os.path.isfile(venv_python):
            return venv_python
        return shutil.which("python3") or "python3"

    def _resolve_venv_bin(self, project_root: str) -> str | None:
        venv_bin = os.path.join(os.path.abspath(project_root), ".venv", "bin")
        if os.path.isdir(venv_bin):
            return venv_bin
        return None

    def _build_acceptance_env(self, venv_bin_path: str | None) -> dict[str, str] | None:
        if not venv_bin_path:
            return None
        env = os.environ.copy()
        original_path = env.get("PATH", "")
        env["PATH"] = f"{venv_bin_path}{os.pathsep}{original_path}" if original_path else venv_bin_path
        return env

    def _rewrite_command_for_python(self, command: str, resolved_python: str) -> tuple[str, str | None]:
        try:
            parts = shlex.split(command, posix=True)
        except ValueError as exc:
            warning = f"命令解析失败，保持原命令执行：{exc}"
            return command, warning

        if not parts:
            return command, None
        if parts[0] not in ("python", "python3"):
            return command, None

        parts[0] = resolved_python
        rewritten = " ".join(shlex.quote(token) for token in parts)
        return rewritten, None

    def run_acceptance(
        self,
        run_id: str,
        version: BuildVersion,
        project_root: str,
    ) -> AcceptanceRunResult:
        run_started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        
        command_results = []
        overall_status = "PASSED"
        resolved_python = self._resolve_python(project_root)
        venv_bin_path = self._resolve_venv_bin(project_root)
        command_env = self._build_acceptance_env(venv_bin_path)
        
        for acc_cmd in version.acceptance_commands:
            cmd_cwd = os.path.abspath(project_root)
            original_command = acc_cmd.command
            executed_command, rewrite_warning = self._rewrite_command_for_python(
                original_command,
                resolved_python,
            )
            
            shell_result = self.shell_adapter.run(
                command=executed_command,
                cwd=cmd_cwd,
                timeout_seconds=acc_cmd.timeout_seconds,
                env=command_env,
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
                venv_bin_path=venv_bin_path,
                rewrite_warning=rewrite_warning,
            )
            
            command_results.append(acc_cmd_result)
            
            if cmd_status == "FAILED":
                if not acc_cmd.continue_on_failure:
                    overall_status = "FAILED"
                    break
                else:
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
            attempt=1, # Just a placeholder since the interface doesn't ask for it, we will derive it from outside if needed
            status=overall_status,
            commands=command_results,
            started_at=run_started_at,
            completed_at=run_completed_at
        )
