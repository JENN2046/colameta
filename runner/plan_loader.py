import json
import os
from typing import Any, Dict
from schemas.plan import (
    BuildRunnerPlan,
    ModelExecutionConfig,
    RunnerPolicy,
    ReviewPolicy,
    CommitPolicy,
    AcceptanceCommand,
    BuildVersion,
    VersionExecutionProfile,
)
from runner.executor_registry import is_supported_execution_provider
from runner.runner_paths import primary_project_runner_relpath

class PlanLoader:
    def load_plan(self, path: str) -> BuildRunnerPlan:
        try:
            if not os.path.exists(path):
                raise FileNotFoundError(f"找不到计划文件: {path}")

            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            return self._parse_plan(data)
        except Exception as e:
            raise RuntimeError(f"加载计划文件失败: {str(e)}")

    def _parse_plan(self, data: Dict[str, Any]) -> BuildRunnerPlan:
        # Parse model execution
        me_data = data.get("model_execution", {})
        model_execution = ModelExecutionConfig(
            mode=me_data.get("mode", "manual"),
            model_command=me_data.get("model_command"),
            prompt_input_mode=me_data.get("prompt_input_mode", "stdin"),
            timeout_seconds=me_data.get("timeout_seconds", 1800),
            stream_output=me_data.get("stream_output", True),
            provider=me_data.get("provider"),
            model=me_data.get("model"),
            model_name=me_data.get("model_name"),
            pi_model=me_data.get("pi_model"),
            codex_model=me_data.get("codex_model"),
            opencode_model=me_data.get("opencode_model"),
        )

        # Parse runner policy
        rp_data = data.get("runner_policy", {})
        runner_policy = RunnerPolicy(
            auto_continue_on_pass=rp_data.get("auto_continue_on_pass", False),
            max_fix_attempts_per_version=rp_data.get("max_fix_attempts_per_version", 3),
            require_clean_worktree=rp_data.get("require_clean_worktree", True),
            stop_on_acceptance_failure=rp_data.get("stop_on_acceptance_failure", True),
            stop_on_scope_violation=rp_data.get("stop_on_scope_violation", True)
        )

        review_policy = self._parse_review_policy(data.get("review_policy"))
        commit_policy = self._parse_commit_policy(data.get("commit_policy"))

        # Parse default acceptance commands
        default_commands = []
        for cmd_data in data.get("default_acceptance_commands", []):
            default_commands.append(AcceptanceCommand(
                command=cmd_data.get("command"),
                cwd=cmd_data.get("cwd"),
                timeout_seconds=cmd_data.get("timeout_seconds", 600),
                continue_on_failure=cmd_data.get("continue_on_failure", False)
            ))

        # Parse versions
        versions = []
        for v_data in data.get("versions", []):
            acc_commands = []
            for cmd_data in v_data.get("acceptance_commands", []):
                acc_commands.append(AcceptanceCommand(
                    command=cmd_data.get("command"),
                    cwd=cmd_data.get("cwd"),
                    timeout_seconds=cmd_data.get("timeout_seconds", 600),
                    continue_on_failure=cmd_data.get("continue_on_failure", False)
                ))
            
            execution = self._parse_version_execution(v_data.get("execution"))

            versions.append(BuildVersion(
                version=v_data.get("version", ""),
                name=v_data.get("name", ""),
                description=v_data.get("description"),
                prompt_file=v_data.get("prompt_file", ""),
                enabled=v_data.get("enabled", True),
                context_files=v_data.get("context_files", []),
                allowed_files=v_data.get("allowed_files", []),
                forbidden_files=v_data.get("forbidden_files", []),
                acceptance_commands=acc_commands,
                manual_acceptance=v_data.get("manual_acceptance", []),
                out_of_scope=v_data.get("out_of_scope", []),
                execution=execution,
                allow_no_changes=v_data.get("allow_no_changes", False),
                required_changed_files=v_data.get("required_changed_files", []),
            ))

        return BuildRunnerPlan(
            project_name=data.get("project_name", "unknown"),
            plan_version=data.get("plan_version", "0.0.0"),
            project_root=data.get("project_root", "."),
            model_execution=model_execution,
            runner_policy=runner_policy,
            versions=versions,
            review_policy=review_policy,
            commit_policy=commit_policy,
            default_acceptance_commands=default_commands,
            logs_dir=data.get("logs_dir", primary_project_runner_relpath("logs")),
            runtime_dir=data.get("runtime_dir", primary_project_runner_relpath("runtime")),
            rules_file=data.get("rules_file", primary_project_runner_relpath("rules.md")),
            state_file=data.get("state_file", primary_project_runner_relpath("state.json"))
        )

    def _parse_review_policy(self, value: Any) -> ReviewPolicy:
        if not isinstance(value, dict):
            return ReviewPolicy()

        enabled = value.get("enabled")
        enabled_bool = enabled if isinstance(enabled, bool) else False

        mode = value.get("mode")
        if enabled_bool:
            mode_value = mode if isinstance(mode, str) and mode.strip() else "manual_gate"
        else:
            mode_value = mode if isinstance(mode, str) and mode.strip() else "manual_gate"

        after_versions = value.get("after_versions")
        if isinstance(after_versions, list):
            versions = [item for item in after_versions if isinstance(item, str)]
        else:
            versions = []

        return ReviewPolicy(
            enabled=enabled_bool,
            mode=mode_value,
            after_versions=versions,
        )

    def _parse_commit_policy(self, value: Any) -> CommitPolicy:
        if not isinstance(value, dict):
            return CommitPolicy()

        enabled = value.get("enabled")
        enabled_bool = enabled if isinstance(enabled, bool) else False

        mode = value.get("mode")
        mode_value = mode if isinstance(mode, str) and mode.strip() else "manual_gate"

        return CommitPolicy(
            enabled=enabled_bool,
            mode=mode_value,
            after_acceptance_pass=bool(value.get("after_acceptance_pass", True)),
            require_clean_scope=bool(value.get("require_clean_scope", True)),
            include_runner_runtime_files=bool(value.get("include_runner_runtime_files", False)),
            require_confirm=bool(value.get("require_confirm", True)),
            require_commit_before_continue=bool(value.get("require_commit_before_continue", False)),
        )

    def _parse_version_execution(self, value: Any) -> VersionExecutionProfile | None:
        if not isinstance(value, dict):
            return None

        def _str(v: Any) -> str | None:
            return v.strip() if isinstance(v, str) and v.strip() else None

        provider_raw = _str(value.get("provider"))
        if provider_raw is not None and not is_supported_execution_provider(provider_raw):
            provider_raw = None

        return VersionExecutionProfile(
            provider=provider_raw,
            model=_str(value.get("model")),
            model_name=_str(value.get("model_name")),
            pi_model=_str(value.get("pi_model")),
            codex_model=_str(value.get("codex_model")),
            opencode_model=_str(value.get("opencode_model")),
            lane=_str(value.get("lane")),
            capability_level=_str(value.get("capability_level")),
            notes=_str(value.get("notes")),
        )

    def validate_plan(self, plan: BuildRunnerPlan) -> None:
        if not plan.versions:
            return
        if not [version for version in plan.versions if version.enabled]:
            raise ValueError("计划文件中没有启用任何版本")
