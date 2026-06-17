import json
import os
import re
import secrets
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from runner._internal_utils import write_json_atomic
from runner.plan_loader import PlanLoader
from runner.plan_standards_linter import PlanStandardsLinter
from runner.source_review_bridge import SourceReviewBridge
from runner.state_store import StateStore
from runner.executor_registry import DEFAULT_EXECUTION_PROVIDER
from runner.runner_paths import (
    PRIMARY_PROJECT_RUNNER_DIRNAME,
    primary_project_runner_relpath,
    resolve_project_runner_dir,
)


class MCPRunnerPlanManager:
    _PREVIEW_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]+")
    _GITIGNORE_BLOCK_START = "# >>> ColaMeta local state >>>"
    _GITIGNORE_BLOCK_END = "# <<< ColaMeta local state <<<"
    _GITIGNORE_BLOCK_LINES = (
        _GITIGNORE_BLOCK_START,
        primary_project_runner_relpath("state.json"),
        primary_project_runner_relpath("runtime", "**"),
        primary_project_runner_relpath("logs", "**"),
        primary_project_runner_relpath("reports", "**"),
        primary_project_runner_relpath("audits", "**"),
        primary_project_runner_relpath("plan-patches", "**"),
        primary_project_runner_relpath("tmp", "**"),
        primary_project_runner_relpath("local", "**"),
        primary_project_runner_relpath("executor-session.json"),
        primary_project_runner_relpath("executor-sessions", "**"),
        primary_project_runner_relpath("settings.json"),
        primary_project_runner_relpath("runner-settings.json"),
        primary_project_runner_relpath("*.lock"),
        primary_project_runner_relpath("**", "*.lock"),
        _GITIGNORE_BLOCK_END,
    )
    _DANGEROUS_COMMAND_PATTERNS = (
        ("git reset", "dangerous_git_reset"),
        ("git clean", "dangerous_git_clean"),
        ("git checkout", "dangerous_git_checkout"),
        ("git switch", "dangerous_git_switch"),
        ("git rebase", "dangerous_git_rebase"),
        ("git merge", "dangerous_git_merge"),
        ("git branch -d", "dangerous_git_branch_delete"),
        ("git branch -D", "dangerous_git_branch_force_delete"),
        ("rm -rf", "dangerous_rm_rf"),
    )

    def __init__(self, project_root: str):
        self.project_root = os.path.abspath(os.path.expanduser(project_root))
        self.project_root_real = os.path.realpath(self.project_root)
        self.runner_dir = resolve_project_runner_dir(self.project_root)
        self.primary_runner_dir = self.runner_dir
        self.display_runner_dir = self._preferred_display_runner_dir()
        self.plan_path = os.path.join(self.runner_dir, "plan.json")
        self.state_path = os.path.join(self.runner_dir, "state.json")
        self.todolist_path = os.path.join(self.runner_dir, "todolist.json")
        self.decisions_path = os.path.join(self.runner_dir, "decisions.json")
        self.memory_path = os.path.join(self.runner_dir, "memory.md")
        self.prompts_dir = os.path.join(self.runner_dir, "prompts")
        self.runtime_dir = os.path.join(self.runner_dir, "runtime")
        self.logs_dir = os.path.join(self.runner_dir, "logs")
        self.reports_dir = os.path.join(self.runner_dir, "reports")
        self.plan_patches_dir = os.path.join(self.runner_dir, "plan-patches")
        self.audits_dir = os.path.join(self.runner_dir, "audits")
        self.plan_previews_dir = os.path.join(self.runtime_dir, "plan-previews")

        self.preview_ttl_seconds = 1800

        self.loader = PlanLoader()
        self.linter = PlanStandardsLinter()
        self.state_store = StateStore()
        self.source_review = SourceReviewBridge()

    def inspect(self) -> dict[str, Any]:
        path_info = self._runner_path_info()
        has_plan = os.path.isfile(self.plan_path)
        has_state = os.path.isfile(self.state_path)
        has_todolist = os.path.isfile(self.todolist_path)
        has_decisions = os.path.isfile(self.decisions_path)
        has_memory = os.path.isfile(self.memory_path)
        has_runtime_dir = os.path.isdir(self.runtime_dir)
        has_logs_dir = os.path.isdir(self.logs_dir)
        has_reports_dir = os.path.isdir(self.reports_dir)
        has_plan_patches_dir = os.path.isdir(self.plan_patches_dir)

        blockers: list[str] = []
        warnings: list[str] = []
        plan_summary: dict[str, Any] | None = None

        if has_plan:
            plan_data = self._read_json_file(self.plan_path)
            if not isinstance(plan_data, dict):
                blockers.append("plan_json_invalid")
            else:
                validation = self._validate_plan_data(plan_data)
                lint_result = validation.get("lint", {})
                blocking_issue_count = int(lint_result.get("blocking_issue_count", 0)) if isinstance(lint_result, dict) else 0
                warning_count = int(lint_result.get("warning_count", 0)) if isinstance(lint_result, dict) else 0
                versions = plan_data.get("versions") if isinstance(plan_data.get("versions"), list) else []
                enabled_count = 0
                for item in versions:
                    if isinstance(item, dict) and item.get("enabled", True) is not False:
                        enabled_count += 1
                path_mismatches = self._plan_path_mismatches(plan_data)
                plan_summary = {
                    "project_name": plan_data.get("project_name"),
                    "plan_version": plan_data.get("plan_version"),
                    "version_count": len(versions),
                    "enabled_version_count": enabled_count,
                    "loader_valid": bool(validation.get("loader_valid")),
                    "lint_status": lint_result.get("status") if isinstance(lint_result, dict) else None,
                    "lint_blocking_issue_count": blocking_issue_count,
                    "lint_warning_count": warning_count,
                    "path_mismatches": path_mismatches,
                }
                if path_mismatches:
                    warnings.append("plan_path_mismatch")
                if not validation.get("loader_valid"):
                    blockers.append("plan_loader_validation_failed")
                if blocking_issue_count > 0:
                    warnings.append("plan_lint_blocking_issues_present")

        git_status_summary: dict[str, Any] | None = None
        try:
            status = self.source_review.get_git_status(self.project_root)
            if isinstance(status, dict) and status.get("ok"):
                changed_files = status.get("changed_files", [])
                untracked_files = status.get("untracked_files", [])
                git_status_summary = {
                    "ok": True,
                    "branch": status.get("branch"),
                    "changed_file_count": len(changed_files) if isinstance(changed_files, list) else None,
                    "untracked_file_count": len(untracked_files) if isinstance(untracked_files, list) else None,
                }
            else:
                git_status_summary = status if isinstance(status, dict) else {"ok": False, "message": "git status unavailable"}
        except Exception as exc:
            git_status_summary = {"ok": False, "error_code": "GIT_STATUS_FAILED", "message": str(exc)}

        source_only = not has_plan
        return {
            "ok": True,
            "action": "inspect",
            "project_root": self.project_root,
            **path_info,
            "has_plan": has_plan,
            "has_state": has_state,
            "has_todolist": has_todolist,
            "has_decisions": has_decisions,
            "has_memory": has_memory,
            "has_runtime_dir": has_runtime_dir,
            "has_logs_dir": has_logs_dir,
            "has_reports_dir": has_reports_dir,
            "has_plan_patches_dir": has_plan_patches_dir,
            "source_only": source_only,
            "can_bootstrap": True,
            "can_import": True,
            "blockers": blockers,
            "warnings": warnings,
            "plan_summary": plan_summary,
            "git_status": git_status_summary,
        }

    def bootstrap_preview(
        self,
        *,
        project_name: str,
        goal: str | None = None,
        current_state_summary: str | None = None,
        first_version: str | None = None,
        first_version_name: str | None = None,
        first_version_prompt: str | None = None,
        allowed_files: list[str] | None = None,
        acceptance_commands: list[Any] | None = None,
        context_files: list[str] | None = None,
        manual_acceptance: list[str] | None = None,
    ) -> dict[str, Any]:
        blockers: list[str] = []
        warnings: list[str] = []

        if not project_name.strip():
            blockers.append("project_name_missing")
        if len(project_name.strip()) > 120:
            blockers.append("project_name_too_long")

        has_dev_prompt = bool(first_version_prompt and first_version_prompt.strip())

        if has_dev_prompt:
            if not goal or not goal.strip():
                blockers.append("goal_missing")
            if goal and len(goal.strip()) > 2000:
                blockers.append("goal_too_long")
            if current_state_summary and len(current_state_summary.strip()) > 4000:
                blockers.append("current_state_summary_too_long")

        normalized_version = first_version.strip() if (first_version and first_version.strip()) else "v1.0"
        normalized_version_name = first_version_name.strip() if (first_version_name and first_version_name.strip()) else "Adopt existing project into Runner"

        versions: list[dict[str, Any]] = []
        prompt_payloads: dict[str, str] = {}

        if has_dev_prompt:
            normalized_prompt = first_version_prompt.strip()

            normalized_allowed = self._normalize_and_validate_path_patterns(
                allowed_files or [],
                field_name="allowed_files",
                blockers=blockers,
            )
            if not normalized_allowed:
                blockers.append("allowed_files_empty")

            normalized_context = self._normalize_and_validate_path_patterns(
                context_files or [],
                field_name="context_files",
                blockers=blockers,
                allow_empty=True,
            )

            normalized_manual_acceptance = self._normalize_string_list(
                manual_acceptance or [],
                field_name="manual_acceptance",
                blockers=blockers,
                allow_empty=True,
            )

            normalized_acceptance = self._normalize_acceptance_commands(acceptance_commands or [], blockers=blockers)
            if not normalized_acceptance:
                blockers.append("acceptance_commands_empty")

            command_warnings, command_blockers = self._detect_command_risks(normalized_acceptance)
            warnings.extend(command_warnings)
            blockers.extend(command_blockers)

            out_of_scope = [
                "Do not change production infra in this onboarding version.",
                "Do not introduce unrelated refactors during onboarding.",
            ]

            prompt_file_name = self._prompt_file_name_for_version(normalized_version)
            prompt_file_abs = os.path.join(self.prompts_dir, prompt_file_name).replace(os.sep, "/")

            goal_text = goal.strip() if goal else ""
            state_text = current_state_summary.strip() if current_state_summary else "N/A"
            version_description = f"{goal_text}\\n\\nCurrent state: {state_text}"

            versions.append({
                "version": normalized_version,
                "name": normalized_version_name,
                "description": version_description,
                "prompt_file": prompt_file_abs,
                "enabled": True,
                "context_files": normalized_context,
                "allowed_files": normalized_allowed,
                "forbidden_files": [
                    ".env*",
                    "secrets/**",
                    primary_project_runner_relpath("runtime", "**"),
                ],
                "acceptance_commands": normalized_acceptance,
                "manual_acceptance": normalized_manual_acceptance,
                "out_of_scope": out_of_scope,
            })

            prompt_payloads[prompt_file_name] = normalized_prompt

        plan_data = {
            "project_name": project_name.strip(),
            "plan_version": "1.0.0",
            "project_root": self.project_root,
            "model_execution": {
                "mode": "manual",
                "model_command": None,
                "prompt_input_mode": "stdin",
                "timeout_seconds": 1800,
                "stream_output": True,
                "provider": DEFAULT_EXECUTION_PROVIDER,
            },
            "runner_policy": {
                "auto_continue_on_pass": False,
                "max_fix_attempts_per_version": 3,
                "require_clean_worktree": False,
                "stop_on_acceptance_failure": True,
                "stop_on_scope_violation": True,
            },
            "review_policy": {
                "enabled": False,
                "mode": "manual_gate",
                "after_versions": [],
            },
            "commit_policy": {
                "enabled": False,
                "mode": "manual_gate",
                "after_acceptance_pass": True,
                "require_clean_scope": True,
                "include_runner_runtime_files": False,
                "require_confirm": True,
                "require_commit_before_continue": False,
            },
            "default_acceptance_commands": [
                {
                    "command": "python3 -m compileall -q .",
                    "timeout_seconds": 600,
                    "continue_on_failure": False,
                }
            ],
            "logs_dir": self._display_logs_dir(),
            "runtime_dir": self._display_runtime_dir(),
            "rules_file": self._display_rules_file(),
            "state_file": self._display_state_path(),
            "versions": versions,
        }

        validation = self._validate_plan_data(plan_data)
        lint_result = validation.get("lint") if isinstance(validation.get("lint"), dict) else {}
        lint_blocking = int(lint_result.get("blocking_issue_count", 0)) if isinstance(lint_result, dict) else 0
        if lint_blocking > 0:
            blockers.append("plan_lint_blocking_issues")

        preview_id = secrets.token_urlsafe(24)
        preview_file = self._preview_file_path(preview_id)
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=self.preview_ttl_seconds)

        can_apply = len(blockers) == 0 and bool(validation.get("loader_valid"))
        preview_payload = {
            "preview_id": preview_id,
            "action": "bootstrap_preview",
            "project_root": self.project_root,
            "created_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
            "can_apply": can_apply,
            "blockers": sorted(set(blockers)),
            "warnings": sorted(set(warnings)),
            "plan_data": plan_data,
            "prompt_payloads": prompt_payloads,
            "validation": validation,
            "committed_at": None,
        }
        self._write_json(preview_file, preview_payload)

        return {
            "ok": True,
            "action": "bootstrap_preview",
            "preview_id": preview_id,
            "can_apply": can_apply,
            "plan_summary": self._plan_summary(plan_data),
            "validation": validation,
            "lint": lint_result,
            "warnings": sorted(set(warnings)),
            "blockers": sorted(set(blockers)),
            "expires_at": expires_at.isoformat(),
            "preview_file": os.path.relpath(preview_file, self.project_root).replace("\\", "/"),
        }

    def import_preview(self, plan_json: str) -> dict[str, Any]:
        try:
            data = json.loads(plan_json)
        except json.JSONDecodeError as exc:
            return {
                "ok": False,
                "action": "import_preview",
                "error_code": "PLAN_JSON_INVALID",
                "message": f"plan_json 不是合法 JSON：第 {exc.lineno} 行第 {exc.colno} 列，{exc.msg}",
            }

        if not isinstance(data, dict):
            return {
                "ok": False,
                "action": "import_preview",
                "error_code": "PLAN_NOT_OBJECT",
                "message": "plan_json 根节点必须是 JSON 对象。",
            }

        blockers: list[str] = []
        warnings: list[str] = []

        validation = self._validate_plan_data(data)
        lint_result = validation.get("lint") if isinstance(validation.get("lint"), dict) else {}
        lint_blocking = int(lint_result.get("blocking_issue_count", 0)) if isinstance(lint_result, dict) else 0
        if not validation.get("loader_valid"):
            blockers.append("plan_loader_validation_failed")
        if lint_blocking > 0:
            blockers.append("plan_lint_blocking_issues")

        prompt_warnings, prompt_blockers = self._inspect_prompt_paths(data)
        warnings.extend(prompt_warnings)
        blockers.extend(prompt_blockers)

        preview_id = secrets.token_urlsafe(24)
        preview_file = self._preview_file_path(preview_id)
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=self.preview_ttl_seconds)
        can_apply = len(blockers) == 0

        preview_payload = {
            "preview_id": preview_id,
            "action": "import_preview",
            "project_root": self.project_root,
            "created_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
            "can_apply": can_apply,
            "blockers": sorted(set(blockers)),
            "warnings": sorted(set(warnings)),
            "plan_data": data,
            "prompt_payloads": {},
            "validation": validation,
            "committed_at": None,
        }
        self._write_json(preview_file, preview_payload)

        return {
            "ok": True,
            "action": "import_preview",
            "preview_id": preview_id,
            "can_apply": can_apply,
            "plan_summary": self._plan_summary(data),
            "validation": validation,
            "lint": lint_result,
            "warnings": sorted(set(warnings)),
            "blockers": sorted(set(blockers)),
            "expires_at": expires_at.isoformat(),
            "preview_file": os.path.relpath(preview_file, self.project_root).replace("\\", "/"),
        }

    def apply(self, preview_id: str, allow_overwrite: bool = False) -> dict[str, Any]:
        path_info_before_apply = self._runner_path_info()
        normalized_preview_id = self._normalize_preview_id(preview_id)
        if normalized_preview_id is None:
            return {
                "ok": False,
                "action": "apply",
                "error_code": "INVALID_PREVIEW_ID",
                "message": "preview_id 格式无效。",
                "preview_id": self._truncate_preview_id_for_error(preview_id),
            }

        try:
            preview_file = self._preview_file_path(normalized_preview_id)
        except ValueError:
            return {
                "ok": False,
                "action": "apply",
                "error_code": "INVALID_PREVIEW_ID",
                "message": "preview_id 格式无效。",
                "preview_id": self._truncate_preview_id_for_error(preview_id),
            }

        if not os.path.isfile(preview_file):
            return {
                "ok": False,
                "action": "apply",
                "error_code": "PREVIEW_NOT_FOUND",
                "message": "preview_id 对应的预览不存在。",
                "preview_id": normalized_preview_id,
            }

        preview = self._read_json_file(preview_file)
        if not isinstance(preview, dict):
            return {
                "ok": False,
                "action": "apply",
                "error_code": "PREVIEW_INVALID",
                "message": "预览文件格式无效。",
                "preview_id": normalized_preview_id,
            }

        if preview.get("committed_at"):
            return {
                "ok": False,
                "action": "apply",
                "error_code": "PREVIEW_ALREADY_APPLIED",
                "message": "该 preview 已完成 apply。",
                "preview_id": normalized_preview_id,
            }

        expires_at = self._parse_time(preview.get("expires_at"))
        if expires_at is None or expires_at <= datetime.now(timezone.utc):
            return {
                "ok": False,
                "action": "apply",
                "error_code": "PREVIEW_EXPIRED",
                "message": "preview 已过期，请重新创建。",
                "preview_id": normalized_preview_id,
            }

        action = str(preview.get("action") or "")
        if action not in {"bootstrap_preview", "import_preview"}:
            return {
                "ok": False,
                "action": "apply",
                "error_code": "PREVIEW_ACTION_INVALID",
                "message": "preview action 无效，不能 apply。",
                "preview_id": normalized_preview_id,
            }

        if allow_overwrite:
            return {
                "ok": False,
                "action": "apply",
                "error_code": "OVERWRITE_NOT_SUPPORTED",
                "message": "当前版本不支持覆盖已有 plan.json，请先人工处理后重试。",
                "preview_id": normalized_preview_id,
            }

        if os.path.exists(self.plan_path):
            return {
                "ok": False,
                "action": "apply",
                "error_code": "PLAN_ALREADY_EXISTS",
                "message": f"目标项目已存在 {path_info_before_apply['plan_path']}。",
                "preview_id": normalized_preview_id,
            }

        can_apply = bool(preview.get("can_apply"))
        if not can_apply:
            return {
                "ok": False,
                "action": "apply",
                "error_code": "PREVIEW_NOT_APPLICABLE",
                "message": "该 preview 当前不可 apply，请先修复 blockers。",
                "preview_id": normalized_preview_id,
                "blockers": preview.get("blockers", []),
            }

        plan_data = preview.get("plan_data")
        if not isinstance(plan_data, dict):
            return {
                "ok": False,
                "action": "apply",
                "error_code": "PREVIEW_PLAN_INVALID",
                "message": "preview 中缺少有效 plan_data。",
                "preview_id": normalized_preview_id,
            }

        self._sync_plan_data_paths(plan_data)
        validation = self._validate_plan_data(plan_data)
        if not validation.get("loader_valid"):
            return {
                "ok": False,
                "action": "apply",
                "error_code": "PLAN_VALIDATION_FAILED",
                "message": "plan_data 校验失败，不能 apply。",
                "preview_id": normalized_preview_id,
                "validation": validation,
            }

        lint_result = validation.get("lint") if isinstance(validation.get("lint"), dict) else {}
        if isinstance(lint_result, dict) and int(lint_result.get("blocking_issue_count", 0)) > 0:
            return {
                "ok": False,
                "action": "apply",
                "error_code": "PLAN_LINT_BLOCKING_ISSUES",
                "message": "plan lint 存在阻断问题，不能 apply。",
                "preview_id": normalized_preview_id,
                "lint": lint_result,
            }

        prompt_payloads_raw = preview.get("prompt_payloads")
        prompt_payloads = prompt_payloads_raw if isinstance(prompt_payloads_raw, dict) else {}

        created_dirs_rel: list[str] = []
        controlled_dirs: list[tuple[str, str]] = [
            (self._storage_runner_rel_dir(), self.runner_dir),
            (self._storage_rel_path("prompts"), self.prompts_dir),
            (self._storage_rel_path("runtime"), self.runtime_dir),
            (self._storage_rel_path("audits"), self.audits_dir),
            (self._storage_rel_path("logs"), self.logs_dir),
            (self._storage_rel_path("reports"), self.reports_dir),
            (self._storage_rel_path("plan-patches"), self.plan_patches_dir),
            (self._storage_rel_path("runtime/plan-previews"), self.plan_previews_dir),
        ]
        for rel_path, abs_path in controlled_dirs:
            if not os.path.isdir(abs_path):
                os.makedirs(abs_path, exist_ok=True)
                created_dirs_rel.append(rel_path)

        write_json_atomic(self.plan_path, plan_data)

        parsed_plan = self._load_plan_from_data(plan_data)
        parsed_plan.project_root = self.project_root
        parsed_plan.runtime_dir = self._display_runtime_dir()
        parsed_plan.logs_dir = self._display_logs_dir()
        parsed_plan.state_file = self._display_state_path()

        state = self.state_store.initialize_state(parsed_plan)
        state_payload = self.state_store._serialize_state(state)
        write_json_atomic(self.state_path, state_payload)

        created_files = [self._storage_rel_path("plan.json"), self._storage_rel_path("state.json")]
        if not os.path.isfile(self.todolist_path):
            write_json_atomic(self.todolist_path, {"schema_version": 1, "items": []})
            created_files.append(self._storage_rel_path("todolist.json"))
        if not os.path.isfile(self.decisions_path):
            write_json_atomic(self.decisions_path, {"schema_version": 1, "decisions": []})
            created_files.append(self._storage_rel_path("decisions.json"))
        if not os.path.isfile(self.memory_path):
            self._write_text_atomic(self.memory_path, "")
            created_files.append(self._storage_rel_path("memory.md"))

        prompt_written: list[str] = []
        for prompt_file, prompt_content in prompt_payloads.items():
            if not isinstance(prompt_file, str) or not isinstance(prompt_content, str):
                continue
            normalized_prompt_file = self._normalize_prompt_file_name(prompt_file)
            if normalized_prompt_file is None:
                continue
            target = self._safe_join(self.prompts_dir, normalized_prompt_file)
            self._write_text_atomic(target, prompt_content.rstrip() + "\n")
            prompt_written.append(self._storage_rel_path(f"prompts/{normalized_prompt_file}"))

        if prompt_written:
            created_files.extend(prompt_written)

        gitignore_result = self._ensure_runner_gitignore_block()
        if gitignore_result.get("created"):
            created_files.append(".gitignore")

        path_info = self._runner_path_info()
        preview["committed_at"] = datetime.now(timezone.utc).isoformat()
        preview["applied_plan_path"] = path_info["plan_path"]
        preview["applied_state_path"] = path_info["state_path"]
        self._write_json(preview_file, preview)

        return {
            "ok": True,
            "action": "apply",
            "preview_id": normalized_preview_id,
            **path_info,
            "created_files": created_files,
            "created_dirs": created_dirs_rel,
            "gitignore": gitignore_result,
            "plan_summary": self._plan_summary(plan_data),
            "next_action_hint": "Restart or refresh Web Console to use the Runner-managed project.",
        }

    def _plan_summary(self, plan_data: dict[str, Any]) -> dict[str, Any]:
        versions = plan_data.get("versions") if isinstance(plan_data.get("versions"), list) else []
        enabled_count = 0
        version_ids: list[str] = []
        for item in versions:
            if not isinstance(item, dict):
                continue
            if item.get("enabled", True) is not False:
                enabled_count += 1
            ver = item.get("version")
            if isinstance(ver, str) and ver.strip():
                version_ids.append(ver.strip())
        return {
            "project_name": plan_data.get("project_name"),
            "plan_version": plan_data.get("plan_version"),
            "version_count": len(versions),
            "enabled_version_count": enabled_count,
            "versions": version_ids,
        }

    def _validate_plan_data(self, plan_data: dict[str, Any]) -> dict[str, Any]:
        lint = self.linter.lint_plan_data(plan_data, project_root=self.project_root)
        loader_valid = False
        loader_error: str | None = None
        try:
            parsed_plan = self._load_plan_from_data(plan_data)
            self.loader.validate_plan(parsed_plan)
            loader_valid = True
        except Exception as exc:
            loader_error = str(exc)

        return {
            "ok": True,
            "loader_valid": loader_valid,
            "loader_error": loader_error,
            "lint": lint,
        }

    def _load_plan_from_data(self, plan_data: dict[str, Any]):
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as f:
            tmp_path = f.name
            json.dump(plan_data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        try:
            return self.loader.load_plan(tmp_path)
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    def _normalize_and_validate_path_patterns(
        self,
        values: list[str],
        *,
        field_name: str,
        blockers: list[str],
        allow_empty: bool = False,
    ) -> list[str]:
        if values is None:
            return [] if allow_empty else []
        if not isinstance(values, list):
            blockers.append(f"{field_name}_not_list")
            return []

        normalized: list[str] = []
        for idx, value in enumerate(values):
            if not isinstance(value, str) or not value.strip():
                blockers.append(f"{field_name}_item_invalid_{idx}")
                continue
            item = value.strip().replace("\\", "/")
            if self._is_unsafe_path_pattern(item):
                blockers.append(f"{field_name}_item_unsafe_{idx}")
                continue
            normalized.append(item)

        if not normalized and not allow_empty:
            blockers.append(f"{field_name}_empty")
        return normalized

    def _normalize_string_list(
        self,
        values: list[str],
        *,
        field_name: str,
        blockers: list[str],
        allow_empty: bool,
    ) -> list[str]:
        if values is None:
            return []
        if not isinstance(values, list):
            blockers.append(f"{field_name}_not_list")
            return []
        result: list[str] = []
        for idx, value in enumerate(values):
            if not isinstance(value, str) or not value.strip():
                blockers.append(f"{field_name}_item_invalid_{idx}")
                continue
            result.append(value.strip())
        if not result and not allow_empty:
            blockers.append(f"{field_name}_empty")
        return result

    def _normalize_acceptance_commands(self, commands: list[Any], *, blockers: list[str]) -> list[dict[str, Any]]:
        if not isinstance(commands, list):
            blockers.append("acceptance_commands_not_list")
            return []

        normalized: list[dict[str, Any]] = []
        for idx, item in enumerate(commands):
            if isinstance(item, str):
                command = item.strip()
                if not command:
                    blockers.append(f"acceptance_command_empty_{idx}")
                    continue
                normalized.append(
                    {
                        "command": command,
                        "timeout_seconds": 600,
                        "continue_on_failure": False,
                    }
                )
                continue

            if not isinstance(item, dict):
                blockers.append(f"acceptance_command_invalid_type_{idx}")
                continue

            command = item.get("command")
            if not isinstance(command, str) or not command.strip():
                blockers.append(f"acceptance_command_missing_command_{idx}")
                continue

            timeout_seconds = item.get("timeout_seconds", 600)
            if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int) or timeout_seconds <= 0:
                blockers.append(f"acceptance_command_invalid_timeout_{idx}")
                continue

            continue_on_failure = item.get("continue_on_failure", False)
            if not isinstance(continue_on_failure, bool):
                blockers.append(f"acceptance_command_invalid_continue_on_failure_{idx}")
                continue

            normalized.append(
                {
                    "command": command.strip(),
                    "timeout_seconds": timeout_seconds,
                    "continue_on_failure": continue_on_failure,
                }
            )

        return normalized

    def _detect_command_risks(self, commands: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
        warnings: list[str] = []
        blockers: list[str] = []

        for idx, item in enumerate(commands, start=1):
            command = str(item.get("command") or "").strip()
            lower = command.lower()

            for token, code in self._DANGEROUS_COMMAND_PATTERNS:
                if token.lower() in lower:
                    blockers.append(f"{code}_at_{idx}")

            if "curl" in lower and "| sh" in lower:
                blockers.append(f"dangerous_curl_pipe_shell_at_{idx}")

            if "&&" in command or ";" in command:
                warnings.append(f"acceptance_command_multi_step_at_{idx}")

            if "<<" in command:
                blockers.append(f"acceptance_command_here_doc_at_{idx}")

        return warnings, blockers

    def _inspect_prompt_paths(self, plan_data: dict[str, Any]) -> tuple[list[str], list[str]]:
        warnings: list[str] = []
        blockers: list[str] = []
        versions = plan_data.get("versions")
        if not isinstance(versions, list):
            return warnings, blockers
        prompts_root = os.path.realpath(self.prompts_dir)
        for idx, item in enumerate(versions, start=1):
            if not isinstance(item, dict):
                continue
            prompt_file = item.get("prompt_file")
            if not isinstance(prompt_file, str) or not prompt_file.strip():
                continue
            prompt_path = prompt_file.strip()
            abs_path = os.path.realpath(os.path.abspath(prompt_path))
            if not (abs_path == prompts_root or abs_path.startswith(prompts_root + os.sep)):
                blockers.append(f"prompt_file_outside_runner_prompts_at_{idx}")
                continue
            if not os.path.exists(abs_path):
                warnings.append(f"prompt_file_missing_on_disk_at_{idx}")
        return warnings, blockers

    def _is_unsafe_path_pattern(self, value: str) -> bool:
        if not value:
            return True
        if value.startswith("/"):
            return True
        if re.match(r"^[A-Za-z]:[/\\]", value):
            return True
        if "\\" in value:
            return True
        parts = [part for part in value.split("/") if part]
        if any(part == ".." for part in parts):
            return True
        lower = value.lower()
        blocked_prefixes = (
            ".git",
            primary_project_runner_relpath("runtime"),
            primary_project_runner_relpath("logs"),
            "secrets",
            ".env",
        )
        return any(lower == prefix or lower.startswith(prefix + "/") for prefix in blocked_prefixes)

    def _prompt_file_name_for_version(self, version: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9._-]", "-", version.strip())
        cleaned = cleaned.strip("-") or "v1.0"
        return f"{cleaned}.md"

    def _normalize_prompt_file_name(self, name: str) -> str | None:
        normalized = name.replace("\\", "/").strip()
        if not normalized:
            return None
        path = PurePosixPath(normalized)
        if path.is_absolute() or ".." in path.parts:
            return None
        if len(path.parts) != 1:
            return None
        filename = path.name
        if filename in {".", ".."}:
            return None
        return filename

    def _normalize_preview_id(self, preview_id: str) -> str | None:
        value = preview_id.strip()
        if not value:
            return None
        if len(value) > 128:
            return None
        if self._PREVIEW_ID_PATTERN.fullmatch(value) is None:
            return None
        return value

    def _truncate_preview_id_for_error(self, preview_id: Any) -> str:
        value = str(preview_id) if preview_id is not None else ""
        return value[:128]

    def _is_under_root(self, root: str, path: str) -> bool:
        root_real = os.path.realpath(root)
        path_real = os.path.realpath(path)
        return path_real == root_real or path_real.startswith(root_real + os.sep)

    def _safe_join(self, root: str, rel_path: str) -> str:
        root_real = os.path.realpath(root)
        path = os.path.realpath(os.path.join(root_real, rel_path))
        if not self._is_under_root(root_real, path):
            raise ValueError("unsafe path")
        return path

    def _preview_file_path(self, preview_id: str) -> str:
        normalized = self._normalize_preview_id(preview_id)
        if normalized is None:
            raise ValueError("invalid preview id")
        preview_root = os.path.realpath(self.plan_previews_dir)
        preview_file = os.path.realpath(os.path.join(preview_root, f"{normalized}.json"))
        if not self._is_under_root(preview_root, preview_file):
            raise ValueError("preview path escapes plan-previews")
        return preview_file

    def _read_json_file(self, path: str) -> dict[str, Any] | None:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return None
        return data if isinstance(data, dict) else None

    def _write_json(self, path: str, payload: dict[str, Any]) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write("\n")

    def _write_text_atomic(self, path: str, content: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp_path = f"{path}.tmp-{secrets.token_urlsafe(8)}"
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, path)

    def _parse_time(self, value: Any) -> datetime | None:
        if not isinstance(value, str) or not value:
            return None
        try:
            parsed = datetime.fromisoformat(value)
        except Exception:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed

    def _sync_plan_data_paths(self, plan_data: dict[str, Any]) -> None:
        plan_data["project_root"] = self.project_root
        plan_data["logs_dir"] = self._display_logs_dir()
        plan_data["runtime_dir"] = self._display_runtime_dir()
        plan_data["state_file"] = self._display_state_path()
        plan_data["rules_file"] = self._display_rules_file()

    def _plan_path_mismatches(self, plan_data: dict[str, Any]) -> list[str]:
        expected = {
            "project_root": self.project_root,
            "logs_dir": self._display_logs_dir(),
            "runtime_dir": self._display_runtime_dir(),
            "state_file": self._display_state_path(),
        }
        mismatches: list[str] = []
        for key, value in expected.items():
            if plan_data.get(key) != value:
                mismatches.append(key)
        rules_file = plan_data.get("rules_file")
        if isinstance(rules_file, str) and os.path.isabs(rules_file) and rules_file != self._display_rules_file():
            mismatches.append("rules_file")
        return mismatches

    def _preferred_display_runner_dir(self) -> str:
        return self.primary_runner_dir

    def _storage_runner_rel_dir(self) -> str:
        return os.path.basename(self.runner_dir)

    def _display_runner_rel_dir(self) -> str:
        return os.path.basename(self._preferred_display_runner_dir())

    def _storage_rel_path(self, suffix: str) -> str:
        return self._join_rel_path(self._storage_runner_rel_dir(), suffix)

    def _display_rel_path(self, suffix: str) -> str:
        return self._join_rel_path(self._display_runner_rel_dir(), suffix)

    def _display_state_path(self) -> str:
        return os.path.join(self._preferred_display_runner_dir(), "state.json")

    def _display_runtime_dir(self) -> str:
        return os.path.join(self._preferred_display_runner_dir(), "runtime")

    def _display_logs_dir(self) -> str:
        return os.path.join(self._preferred_display_runner_dir(), "logs")

    def _display_rules_file(self) -> str:
        return os.path.join(self._preferred_display_runner_dir(), "rules.md")

    def _runner_path_info(self) -> dict[str, Any]:
        active_runner_dir = self._display_runner_rel_dir()
        return {
            "path_mode": "primary",
            "runner_dir": active_runner_dir,
            "plan_path": self._display_rel_path("plan.json"),
            "state_path": self._display_rel_path("state.json"),
            "todolist_path": self._display_rel_path("todolist.json"),
            "primary_runner_dir": PRIMARY_PROJECT_RUNNER_DIRNAME,
            "primary_plan_path": self._join_rel_path(PRIMARY_PROJECT_RUNNER_DIRNAME, "plan.json"),
            "primary_state_path": self._join_rel_path(PRIMARY_PROJECT_RUNNER_DIRNAME, "state.json"),
            "primary_todolist_path": self._join_rel_path(PRIMARY_PROJECT_RUNNER_DIRNAME, "todolist.json"),
        }

    def _join_rel_path(self, base: str, suffix: str) -> str:
        normalized_suffix = suffix.strip().replace("\\", "/").strip("/")
        if not normalized_suffix:
            return base
        return f"{base}/{normalized_suffix}"

    def _ensure_runner_gitignore_block(self) -> dict[str, Any]:
        path = os.path.join(self.project_root, ".gitignore")
        before_exists = os.path.exists(path)
        content = ""
        if before_exists:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        block = "\n".join(self._GITIGNORE_BLOCK_LINES) + "\n"
        if self._GITIGNORE_BLOCK_START in content:
            missing_lines = [line for line in self._GITIGNORE_BLOCK_LINES if line not in content]
            if not missing_lines:
                return {
                    "updated": False,
                    "created": False,
                    "path": ".gitignore",
                    "reason": "block_exists",

                }
            insert_at = content.find(self._GITIGNORE_BLOCK_END)
            if insert_at == -1:
                return {
                    "updated": False,
                    "created": False,
                    "path": ".gitignore",
                    "reason": "malformed_block",

                }
            prefix = content[:insert_at]
            suffix = content[insert_at:]
            if prefix and not prefix.endswith("\n"):
                prefix += "\n"
            with open(path, "w", encoding="utf-8") as f:
                f.write(prefix + "\n".join(missing_lines) + "\n" + suffix)
            return {
                "updated": True,
                "created": False,
                "path": ".gitignore",
                "reason": "block_updated",
                "added_lines": missing_lines,
            }

        prefix = ""
        if content:
            prefix = "" if content.endswith("\n") else "\n"
            if not content.endswith("\n\n"):
                prefix += "\n"
        with open(path, "w", encoding="utf-8") as f:
            f.write(content + prefix + block)
        return {
            "updated": True,
            "created": not before_exists,
            "path": ".gitignore",
            "reason": "block_added",
        }


def ensure_minimal_runner_managed_project(project_root: str) -> dict[str, Any]:
    resolved_root = os.path.abspath(os.path.expanduser(project_root))
    runner_dir = resolve_project_runner_dir(resolved_root)
    plan_path = os.path.join(runner_dir, "plan.json")

    result_base = {
        "runner_dir": PRIMARY_PROJECT_RUNNER_DIRNAME,
        "plan_path": f"{PRIMARY_PROJECT_RUNNER_DIRNAME}/plan.json",
        "state_path": f"{PRIMARY_PROJECT_RUNNER_DIRNAME}/state.json",
        "todolist_path": f"{PRIMARY_PROJECT_RUNNER_DIRNAME}/todolist.json",
        "decisions_path": f"{PRIMARY_PROJECT_RUNNER_DIRNAME}/decisions.json",
        "memory_path": f"{PRIMARY_PROJECT_RUNNER_DIRNAME}/memory.md",
    }

    if not os.path.isdir(resolved_root):
        return {
            "ok": False,
            "created": False,
            "error_code": "PROJECT_DIR_MISSING",
            "message": f"项目目录不存在：{resolved_root}",
            **result_base,
        }

    if os.path.isfile(plan_path):
        return {
            "ok": True,
            "created": False,
            "path_mode": "primary",
            "primary_runner_dir": PRIMARY_PROJECT_RUNNER_DIRNAME,
            **result_base,
        }

    manager = MCPRunnerPlanManager(resolved_root)
    project_name = os.path.basename(os.path.normpath(resolved_root)).strip() or "Runner Project"
    try:
        preview = manager.bootstrap_preview(project_name=project_name)
        if not preview.get("ok") or preview.get("can_apply") is not True:
            return {
                "ok": False,
                "created": False,
                "error_code": "BOOTSTRAP_PREVIEW_BLOCKED",
                "message": "自动创建最小 Runner 结构失败：bootstrap preview 不可应用。",
                "blockers": preview.get("blockers", []),
                "warnings": preview.get("warnings", []),
                **result_base,
            }

        preview_id = preview.get("preview_id")
        if not isinstance(preview_id, str) or not preview_id.strip():
            return {
                "ok": False,
                "created": False,
                "error_code": "BOOTSTRAP_PREVIEW_INVALID",
                "message": "自动创建最小 Runner 结构失败：缺少 preview_id。",
                **result_base,
            }

        applied = manager.apply(preview_id)
        if not applied.get("ok"):
            return {
                "ok": False,
                "created": False,
                "error_code": str(applied.get("error_code") or "BOOTSTRAP_APPLY_FAILED"),
                "message": str(applied.get("message") or "自动创建最小 Runner 结构失败。"),
                "blockers": applied.get("blockers", []),
                **result_base,
            }
    except Exception as exc:
        return {
            "ok": False,
            "created": False,
            "error_code": "MINIMAL_ONBOARDING_FAILED",
            "message": f"自动创建最小 Runner 结构失败：{exc}",
            **result_base,
        }

    return {
        "ok": True,
        "created": True,
        "created_files": list(applied.get("created_files", [])),
        "created_dirs": list(applied.get("created_dirs", [])),
        "path_mode": "primary",
        "runner_dir": str(applied.get("runner_dir") or result_base["runner_dir"]),
        "plan_path": str(applied.get("plan_path") or result_base["plan_path"]),
        "state_path": str(applied.get("state_path") or result_base["state_path"]),
        "todolist_path": str(applied.get("todolist_path") or result_base["todolist_path"]),
        "primary_plan_path": f"{PRIMARY_PROJECT_RUNNER_DIRNAME}/plan.json",
        "primary_state_path": f"{PRIMARY_PROJECT_RUNNER_DIRNAME}/state.json",
        "primary_todolist_path": f"{PRIMARY_PROJECT_RUNNER_DIRNAME}/todolist.json",
        "primary_decisions_path": f"{PRIMARY_PROJECT_RUNNER_DIRNAME}/decisions.json",
        "primary_memory_path": f"{PRIMARY_PROJECT_RUNNER_DIRNAME}/memory.md",
        "primary_runner_dir": PRIMARY_PROJECT_RUNNER_DIRNAME,
    }
