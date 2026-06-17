import os
import uuid
import datetime
from schemas.plan import BuildRunnerPlan, BuildVersion
from schemas.state import BuildRunnerState
from schemas.result import AcceptanceRunResult, AcceptanceCommandResult, ScopeCheckResult
from schemas.audit import BuildAuditReport

class AuditBuilder:
    def build_audit(
        self,
        plan: BuildRunnerPlan,
        version: BuildVersion,
        state: BuildRunnerState,
        acceptance: AcceptanceRunResult,
        scope_check: ScopeCheckResult,
        current_prompt: str,
    ) -> BuildAuditReport:
        failed_commands = [cmd for cmd in acceptance.commands if cmd.status == "FAILED"]
        
        status = "UNKNOWN_FAILED"
        if acceptance.status == "FAILED":
            status = "ACCEPTANCE_FAILED"
        elif scope_check.status == "FAILED":
            status = "SCOPE_VIOLATION"
        
        current_prompt_file = os.path.join(plan.runtime_dir, "current-prompt.md")
        
        audit = BuildAuditReport(
            audit_id=str(uuid.uuid4()),
            project_name=plan.project_name,
            version=version.version,
            version_name=version.name,
            status=status,
            attempt=state.attempt,
            max_attempts=state.max_fix_attempts_per_version,
            failed_commands=failed_commands,
            scope_check=scope_check,
            changed_files=scope_check.changed_files,
            current_prompt=current_prompt,
            current_prompt_file=current_prompt_file,
            copyable_audit_markdown="",
            created_at=datetime.datetime.now(datetime.timezone.utc).astimezone().isoformat()
        )
        
        audit.copyable_audit_markdown = self.render_markdown(audit, acceptance)
        return audit

    def render_markdown(self, audit: BuildAuditReport, acceptance: AcceptanceRunResult) -> str:
        lines = []
        lines.append("# Build Runner Audit")
        lines.append("## 项目")
        lines.append(audit.project_name)
        lines.append("## 当前版本")
        lines.append(f"{audit.version} - {audit.version_name}")
        lines.append("## 状态")
        lines.append(audit.status)
        lines.append("## 尝试次数")
        lines.append(f"{audit.attempt} / {audit.max_attempts}")

        lines.append("## 失败命令详情")
        if not audit.failed_commands:
            lines.append("无")
        else:
            for cmd in audit.failed_commands:
                failed_index = self._find_command_index(acceptance.commands, cmd)
                lines.append(f"[#{failed_index}]")
                lines.append(f"原始命令: {cmd.original_command or cmd.command}")
                lines.append(f"实际执行命令: {cmd.executed_command or cmd.command}")
                lines.append(f"Resolved Python: {cmd.resolved_python or '未解析'}")
                lines.append(f"CWD: {cmd.cwd or '未提供'}")
                lines.append(f"退出码: {cmd.exit_code}")
                if cmd.rewrite_warning:
                    lines.append(f"Rewrite Warning: {cmd.rewrite_warning}")
                lines.append("")

        lines.append("## 验收命令执行明细")
        if not acceptance.commands:
            lines.append("无")
        else:
            for index, cmd in enumerate(acceptance.commands, start=1):
                lines.append(f"### [#{index}]")
                lines.append(f"状态: {cmd.status}")
                lines.append(f"原始命令: {cmd.original_command or cmd.command}")
                lines.append(f"实际执行命令: {cmd.executed_command or cmd.command}")
                lines.append(f"Resolved Python: {cmd.resolved_python or '未解析'}")
                lines.append(f"CWD: {cmd.cwd or '未提供'}")
                lines.append(f"退出码: {cmd.exit_code}")
                if cmd.rewrite_warning:
                    lines.append(f"Rewrite Warning: {cmd.rewrite_warning}")
                lines.append("")
        
        lines.append("## 失败命令")
        if not audit.failed_commands:
            lines.append("无")
        else:
            for cmd in audit.failed_commands:
                lines.append(f"### {cmd.command}")
                lines.append(f"Exit Code: {cmd.exit_code}")
                if cmd.stdout:
                    lines.append("STDOUT:")
                    lines.append("```text")
                    lines.append(cmd.stdout)
                    lines.append("```")
                if cmd.stderr:
                    lines.append("STDERR:")
                    lines.append("```text")
                    lines.append(cmd.stderr)
                    lines.append("```")
                    
        lines.append("## 变更文件")
        lines.append("```text")
        lines.append("\n".join(audit.changed_files) if audit.changed_files else "无")
        lines.append("```")
        
        lines.append("## 文件越界检查")
        lines.append("### Scope Check Status")
        lines.append("```text")
        lines.append(audit.scope_check.status)
        lines.append("```")
        
        lines.append("### 允许文件")
        lines.append("```text")
        lines.append("\n".join(audit.scope_check.allowed_files) if audit.scope_check.allowed_files else "无")
        lines.append("```")

        lines.append("### 禁止文件")
        lines.append("```text")
        lines.append("\n".join(audit.scope_check.forbidden_files) if audit.scope_check.forbidden_files else "无")
        lines.append("```")

        lines.append("### Git Diff Name Only")
        lines.append("```text")
        if audit.scope_check.raw_changed_files:
            lines.append("\n".join(audit.scope_check.raw_changed_files))
        else:
            lines.append(audit.scope_check.git_diff_name_only_output if audit.scope_check.git_diff_name_only_output else "无")
        lines.append("```")

        lines.append("### 已忽略 Runner 运行态文件")
        lines.append("```text")
        lines.append("\n".join(audit.scope_check.ignored_runtime_files) if audit.scope_check.ignored_runtime_files else "无")
        lines.append("```")

        lines.append("### 实际参与 Scope Check 的文件")
        lines.append("```text")
        lines.append("\n".join(audit.scope_check.scope_checked_files) if audit.scope_check.scope_checked_files else "无")
        lines.append("```")
        
        lines.append("### 越界文件")
        lines.append("```text")
        lines.append("\n".join(audit.scope_check.outside_allowed_files) if audit.scope_check.outside_allowed_files else "无")
        lines.append("```")
        
        lines.append("### 禁止文件变更")
        lines.append("```text")
        lines.append("\n".join(audit.scope_check.forbidden_changed_files) if audit.scope_check.forbidden_changed_files else "无")
        lines.append("```")
        
        lines.append("## Git Diff Summary")
        lines.append("```text")
        lines.append(audit.scope_check.git_diff_stat_output if audit.scope_check.git_diff_stat_output else "无")
        lines.append("```")
        
        lines.append("## 当前版本提示词")
        lines.append("```text")
        lines.append(audit.current_prompt)
        lines.append("```")
        
        lines.append("## 请求")
        lines.append("请给我一个只修复当前版本的修复提示词。")
        lines.append("要求：")
        lines.append("- 只修复当前版本。")
        lines.append("- 不进入下一版本。")
        lines.append("- 不扩展 scope。")
        lines.append("- 不修改 allowed_files 之外的文件。")
        lines.append("- 不改变公共接口，除非修复当前错误必须。")
        lines.append("- 修复后必须能通过验收命令。")
        
        return "\n".join(lines)

    def _find_command_index(self, commands: list[AcceptanceCommandResult], target: AcceptanceCommandResult) -> int:
        for index, cmd in enumerate(commands, start=1):
            if cmd is target:
                return index
        for index, cmd in enumerate(commands, start=1):
            if cmd.command == target.command and cmd.started_at == target.started_at:
                return index
        return 0
