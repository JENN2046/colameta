import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runner.mcp_runner_plan import MCPRunnerPlanManager
from runner.planning_bridge import PlanningBridge, PlanningBridgeError
from runner.plan_standards_linter import PlanStandardsLinter
from runner.source_review_bridge import SourceReviewBridge
from runner.runner_paths import (
    project_runner_dirnames,
    resolve_project_runner_plan_path,
)


SAFE_ALLOWED_FILES = [
    "README.md",
    "AGENTS.md",
    "docs/*.md",
    "runner/**/*.py",
    "scripts/*.py",
    "adapters/**/*.py",
    "schemas/**/*.py",
    "bin/colameta",
]

BROAD_PATTERNS = {"**/*", "*", ".", "/", "../*"}
FORBIDDEN_PATTERNS = {
    *(f"{dirname}/**" for dirname in project_runner_dirnames()),
    ".git/**", ".env*", "venv/**", ".venv/**",
    "node_modules/**", "dist/**", "build/**",
    "*.pem", "*.key", "*.db", "*.sqlite",
}

SAFE_ACCEPTANCE_COMMANDS = [
    {
        "command": "python3 -m compileall -q runner scripts adapters schemas",
        "timeout_seconds": 600,
        "continue_on_failure": False,
    },
]

DANGEROUS_COMMAND_PATTERNS = re.compile(
    r"(rm\s+-rf|git\s+reset|git\s+clean|git\s+checkout|"
    r"git\s+switch|git\s+merge|git\s+rebase|git\s+push|"
    r"git\s+add\s+\.|curl\s+\|?\s*sh|sudo|chmod\s+-R\s+777|"
    r"pip\s+install\s+(?!.*--user)|npm\s+install)",
    re.IGNORECASE,
)


class MCPPlanWorkflowManager:
    def __init__(self, project_root: str, source_review: SourceReviewBridge):
        self.project_root = os.path.abspath(os.path.expanduser(project_root))
        self.source_review = source_review
        self._runner_plan_manager: MCPRunnerPlanManager | None = None
        self._bridge: PlanningBridge | None = None

    @property
    def runner_plan_manager(self) -> MCPRunnerPlanManager:
        if self._runner_plan_manager is None:
            self._runner_plan_manager = MCPRunnerPlanManager(self.project_root)
        return self._runner_plan_manager

    @property
    def bridge(self) -> PlanningBridge:
        if self._bridge is None:
            self._bridge = PlanningBridge()
        return self._bridge

    def handle(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        if action == "source_onboarding_preview":
            return self._source_onboarding_preview(params)
        if action == "plan_repair_preview":
            return self._plan_repair_preview(params)
        if action == "plan_extend_preview":
            return self._plan_extend_preview(params)
        return {
            "ok": False,
            "error_code": "UNKNOWN_ACTION",
            "message": f"未知 action：{action}",
        }

    # ----------------------------------------------------------------
    # source_onboarding_preview
    # ----------------------------------------------------------------
    def _source_onboarding_preview(self, params: dict[str, Any]) -> dict[str, Any]:
        plan_path = resolve_project_runner_plan_path(self.project_root)
        if os.path.isfile(plan_path):
            return {
                "ok": False,
                "error_code": "PLAN_ALREADY_EXISTS",
                "action": "source_onboarding_preview",
                "message": "当前项目已有 plan.json，请使用 plan_repair_preview 或 plan_extend_preview。",
                "recommended_actions": ["plan_repair_preview", "plan_extend_preview"],
            }

        dry_run = bool(params.get("dry_run", False))
        max_files = self._bounded_int(params.get("max_files"), 300, 1, 500)

        repo_overview = self._get_repo_overview(max_files)
        project_identity = self._get_project_identity()

        if not isinstance(repo_overview, dict) or not repo_overview.get("ok"):
            return {
                "ok": False,
                "error_code": "REPO_OVERVIEW_FAILED",
                "action": "source_onboarding_preview",
                "message": "无法读取项目仓库概况。",
            }
        if not isinstance(project_identity, dict) or not project_identity.get("project_root"):
            return {
                "ok": False,
                "error_code": "PROJECT_IDENTITY_FAILED",
                "action": "source_onboarding_preview",
                "message": "无法读取项目身份标识。",
            }

        repo_profile = self._build_repo_profile(repo_overview, project_identity)
        assumptions = self._build_assumptions(repo_profile)
        confidence = self._compute_confidence(repo_profile)
        blockers: list[str] = []
        warnings: list[str] = []
        direct_reconcile_preview = self.bridge.get_unreconciled_direct_versions_preview(self.project_root, scan_limit=20)
        direct_candidates: list[dict[str, Any]] = []
        if isinstance(direct_reconcile_preview, dict) and direct_reconcile_preview.get("ok"):
            raw_candidates = direct_reconcile_preview.get("candidates")
            if isinstance(raw_candidates, list):
                direct_candidates = [item for item in raw_candidates if isinstance(item, dict)]
        direct_count = len(direct_candidates)
        if direct_count > 0:
            warnings.append(f"Git 历史发现 {direct_count} 个 direct version 候选。source_onboarding 仅提示，不自动导入。")

        project_name = params.get("project_name")
        if not isinstance(project_name, str) or not project_name.strip():
            project_name = self._infer_project_name(project_identity)
        else:
            project_name = project_name.strip()

        # Onboarding-only mode: create managed workspace, no development version
        if dry_run:
            return {
                "ok": True,
                "action": "source_onboarding_preview",
                "workflow_action": "source_onboarding_preview",
                "dry_run": True,
                "repo_profile": repo_profile,
                "generated_spec_summary": {
                    "project_name": project_name,
                    "mode": "onboarding_only",
                    "description": "将创建 .colameta 基础结构，不创建真实开发版本。",
                },
                "confidence": confidence,
                "assumptions": assumptions + [
                    "Onboarding only: no development version will be created.",
                    "After apply, use manage_plan_version insert_from_prompt_file_preview to add the first development version.",
                ],
                "manual_review_required": True,
                "can_apply": False,
                "blockers": blockers,
                "warnings": warnings,
                "recommended_next_action": "review_dry_run_and_proceed_or_apply",
                "unreconciled_direct_version_count": direct_count,
                "unreconciled_direct_versions": direct_candidates[:5],
                "reconcile_git_history_hint": (
                    {"tool": "run_mcp_workflow", "action": "manual_git_history_review_required", "params": {"workflow": "project_status", "phase": "inspect"}}
                    if direct_count > 0 else None
                ),
            }

        try:
            result = self.runner_plan_manager.bootstrap_preview(
                project_name=project_name,
            )
        except Exception as e:
            return {
                "ok": False,
                "action": "source_onboarding_preview",
                "error_code": "BOOTSTRAP_PREVIEW_FAILED",
                "message": f"bootstrap_preview 调用失败：{e}",
            }

        if not isinstance(result, dict):
            return {
                "ok": False,
                "action": "source_onboarding_preview",
                "error_code": "BOOTSTRAP_PREVIEW_INVALID",
                "message": "bootstrap_preview 返回格式无效。",
            }

        can_apply = bool(result.get("ok") and result.get("can_apply") and len(blockers) == 0)
        result_blockers = list(result.get("blockers", []))
        result_blockers.extend(blockers)

        plan_summary = result.get("plan_summary")
        preview_id = result.get("preview_id")

        result.update({
            "action": "source_onboarding_preview",
            "underlying_action": "bootstrap_preview",
            "workflow_action": "source_onboarding_preview",
            "repo_profile": repo_profile,
            "generated_spec_summary": {
                "project_name": project_name,
                "mode": "onboarding_only",
                "description": "将创建 .colameta 基础结构，不创建真实开发版本。",
            },
            "confidence": confidence,
            "assumptions": assumptions + [
                "Onboarding only: no development version created.",
                "After apply, use manage_plan_version insert_from_prompt_file_preview to add the first development version.",
            ],
            "manual_review_required": True,
            "can_apply": can_apply,
            "blockers": result_blockers,
            "warnings": list(result.get("warnings", [])),
            "recommended_next_action": "manage_runner_plan.apply" if can_apply else "review_blockers",
            "preview_id": preview_id,
            "plan_summary": plan_summary,
            "unreconciled_direct_version_count": direct_count,
            "unreconciled_direct_versions": direct_candidates[:5],
            "reconcile_git_history_hint": (
                {"tool": "run_mcp_workflow", "action": "manual_git_history_review_required", "params": {"workflow": "project_status", "phase": "inspect"}}
                if direct_count > 0 else None
            ),
        })
        return result

    # ----------------------------------------------------------------
    # plan_repair_preview
    # ----------------------------------------------------------------
    def _plan_repair_preview(self, params: dict[str, Any]) -> dict[str, Any]:
        plan_path = resolve_project_runner_plan_path(self.project_root)
        if not os.path.isfile(plan_path):
            return {
                "ok": False,
                "error_code": "PLAN_REQUIRED",
                "action": "plan_repair_preview",
                "message": "source-only 项目请先使用 source_onboarding_preview 创建 plan。",
                "recommended_actions": ["source_onboarding_preview"],
            }

        dry_run = bool(params.get("dry_run", False))

        try:
            lint_result = PlanStandardsLinter().lint_project(self.project_root)
        except Exception as e:
            return {
                "ok": False,
                "action": "plan_repair_preview",
                "error_code": "LINT_FAILED",
                "message": f"lint 失败：{e}",
            }

        if not isinstance(lint_result, dict) or not lint_result.get("ok"):
            return {
                "ok": True,
                "action": "plan_repair_preview",
                "can_preview": False,
                "message": "无法读取 plan lint 状态。请先检查 plan.json。",
                "suggested_next_action": "fix_plan_manually",
                "workflow_action": "plan_repair_preview",
                "dry_run": dry_run,
                "repair_candidates": [],
                "confidence": 0.0,
                "assumptions": [],
                "manual_review_required": True,
                "blockers": ["lint_unavailable"],
                "warnings": [],
            }

        target_version = params.get("version")
        if isinstance(target_version, str):
            target_version = target_version.strip()
        else:
            target_version = None

        repair_kinds_raw = params.get("repair_kinds")
        allowed_kinds = {"acceptance_command_shape", "invalid_provider", "missing_optional_safety_fields", "prompt_file_safety"}
        repair_kinds: set[str] | None = None
        if isinstance(repair_kinds_raw, list) and repair_kinds_raw:
            kinds = set()
            for item in repair_kinds_raw:
                if isinstance(item, str) and item.strip() in allowed_kinds:
                    kinds.add(item.strip())
            if kinds:
                repair_kinds = kinds

        issues = lint_result.get("issues", [])
        repair_candidates: list[dict[str, Any]] = []
        blockers: list[str] = []
        warnings: list[str] = []

        for issue in issues:
            if not isinstance(issue, dict):
                continue
            if target_version:
                ver = issue.get("version")
                if ver is not None and str(ver) != target_version:
                    continue

            error_code = issue.get("error_code", "")
            field = issue.get("field", "")
            blocking = bool(issue.get("blocking", False))
            repair: dict[str, Any] = {
                "issue": error_code, "field": field,
                "blocking": blocking, "message": issue.get("message", ""),
            }

            if error_code == "LEGACY_STRING_ACCEPTANCE_COMMAND" and (not repair_kinds or "acceptance_command_shape" in repair_kinds):
                repair["repair_action"] = "normalize_to_object"
                repair["repair_suggestion"] = "将字符串命令转为 object 格式"
                repair_candidates.append(repair)
            elif error_code == "MISSING_TIMEOUT_SECONDS" and (not repair_kinds or "acceptance_command_shape" in repair_kinds):
                repair["repair_action"] = "add_default_timeout"
                repair["repair_suggestion"] = "添加 timeout_seconds: 600"
                repair_candidates.append(repair)
            elif error_code == "MISSING_CONTINUE_ON_FAILURE" and (not repair_kinds or "acceptance_command_shape" in repair_kinds):
                repair["repair_action"] = "add_default_continue_on_failure"
                repair["repair_suggestion"] = "添加 continue_on_failure: false"
                repair_candidates.append(repair)
            elif error_code in ("INVALID_EXECUTION_PROVIDER", "INVALID_MODEL_EXECUTION_PROVIDER") and (not repair_kinds or "invalid_provider" in repair_kinds):
                repair["repair_action"] = "blocker_user_must_choose"
                repair["repair_suggestion"] = "需要用户从 pi、codex、opencode 中选择合法 provider。"
                repair_candidates.append(repair)
            elif error_code in ("MISSING_OUT_OF_SCOPE", "MISSING_VERSION_DESCRIPTION") and (not repair_kinds or "missing_optional_safety_fields" in repair_kinds):
                repair["repair_action"] = "optional_recommendation"
                repair_candidates.append(repair)
            elif error_code == "PROMPT_FILE_PATH_UNSAFE" and (not repair_kinds or "prompt_file_safety" in repair_kinds):
                repair["repair_action"] = "blocker_manual_fix_required"
                repair_candidates.append(repair)
                if blocking:
                    blockers.append(f"prompt_file 路径不安全：{issue.get('message', '')}")
            else:
                continue

            if blocking and repair.get("repair_action") not in ("blocker_user_must_choose", "blocker_manual_fix_required"):
                blockers.append(f"{error_code}: {issue.get('message', '')}")

        confidence = self._compute_repair_confidence(repair_candidates)
        has_blocker_repairs = any(
            r.get("repair_action") in ("blocker_user_must_choose", "blocker_manual_fix_required")
            for r in repair_candidates
        )
        has_actionable = any(
            r.get("repair_action") in ("normalize_to_object", "add_default_timeout", "add_default_continue_on_failure", "optional_recommendation")
            for r in repair_candidates
        )

        if not repair_candidates:
            return {
                "ok": True,
                "action": "plan_repair_preview",
                "workflow_action": "plan_repair_preview",
                "dry_run": dry_run,
                "can_preview": False,
                "lint_summary": {"total_issues": len(issues), "repairable_count": 0},
                "repair_candidates": [],
                "confidence": 0.0,
                "assumptions": self._build_assumptions({}),
                "manual_review_required": True,
                "blockers": blockers,
                "warnings": warnings,
                "message": "未检测到可自动修复的问题。",
                "suggested_next_action": "no_repair_needed",
            }

        can_preview = has_actionable and not (has_blocker_repairs and not has_actionable)
        suggested_next_action = "review_repair_candidates"
        if has_blocker_repairs and not has_actionable:
            can_preview = False
            suggested_next_action = "manual_fix_required"

        if dry_run or not can_preview:
            return {
                "ok": True,
                "action": "plan_repair_preview",
                "workflow_action": "plan_repair_preview",
                "dry_run": dry_run,
                "can_preview": can_preview,
                "lint_summary": {"total_issues": len(issues), "repairable_count": len(repair_candidates)},
                "repair_candidates": repair_candidates,
                "confidence": confidence,
                "assumptions": self._build_assumptions({}),
                "manual_review_required": True,
                "blockers": blockers,
                "warnings": warnings,
                "message": "" if can_preview else "存在需要人工修复的阻断问题。",
                "suggested_next_action": suggested_next_action,
            }

        preview_result = self._generate_repair_preview(repair_candidates, issues, lint_result)
        if not preview_result.get("ok"):
            return {
                "ok": False,
                "action": "plan_repair_preview",
                "workflow_action": "plan_repair_preview",
                "dry_run": dry_run,
                "can_preview": False,
                "error_code": "REPAIR_PREVIEW_FAILED",
                "message": preview_result.get("message", "生成修复 preview 失败。"),
                "lint_summary": {"total_issues": len(issues), "repairable_count": len(repair_candidates)},
                "repair_candidates": repair_candidates,
                "confidence": confidence,
                "assumptions": self._build_assumptions({}),
                "manual_review_required": True,
                "blockers": blockers,
                "warnings": warnings,
                "suggested_next_action": "manual_fix_required",
            }

        return {
            "ok": True,
            "action": "plan_repair_preview",
            "underlying_action": "repair_preview",
            "workflow_action": "plan_repair_preview",
            "dry_run": dry_run,
            "can_preview": can_preview,
            "preview_id": preview_result.get("preview_id"),
            "patch_preview_ids": preview_result.get("patch_preview_ids", []),
            "lint_summary": {"total_issues": len(issues), "repairable_count": len(repair_candidates)},
            "repair_candidates": repair_candidates,
            "confidence": confidence,
            "assumptions": self._build_assumptions({}),
            "manual_review_required": True,
            "blockers": blockers,
            "warnings": warnings,
            "message": "修复 preview 已生成，请审查后通过 Web Console apply。",
            "suggested_next_action": "review_repair_patches",
        }

    # ----------------------------------------------------------------
    # plan_extend_preview
    # ----------------------------------------------------------------
    def _plan_extend_preview(self, params: dict[str, Any]) -> dict[str, Any]:
        plan_path = resolve_project_runner_plan_path(self.project_root)
        if not os.path.isfile(plan_path):
            return {
                "ok": False,
                "error_code": "PLAN_REQUIRED",
                "action": "plan_extend_preview",
                "message": "source-only 项目请先使用 source_onboarding_preview 创建 plan。",
                "recommended_actions": ["source_onboarding_preview"],
            }

        dry_run = bool(params.get("dry_run", False))

        repo_profile = {}
        try:
            overview = self.source_review.get_repo_overview(self.project_root)
            if isinstance(overview, dict) and overview.get("ok"):
                identity = self._get_project_identity()
                repo_profile = self._build_repo_profile(overview, identity)
        except Exception:
            pass

        version = params.get("version")
        if not isinstance(version, str) or not version.strip():
            version = self._infer_next_version()

        insert_after = params.get("insert_after")
        if not isinstance(insert_after, str) or not insert_after.strip():
            insert_after = None

        if insert_after is None:
            try:
                with open(plan_path, "r", encoding="utf-8") as f:
                    plan_data = json.load(f)
            except Exception:
                return {
                    "ok": False,
                    "error_code": "INSERT_AFTER_UNRESOLVED",
                    "action": "plan_extend_preview",
                    "message": "无法读取 plan.json 获取 insert_after，请显式提供。",
                }
            plan_versions = plan_data.get("versions", [])
            if plan_versions:
                last_version = plan_versions[-1].get("version", "").strip()
                if last_version:
                    insert_after = last_version
                else:
                    return {
                        "ok": False,
                        "error_code": "INSERT_AFTER_UNRESOLVED",
                        "action": "plan_extend_preview",
                        "message": "plan.versions 最后一个版本缺少 version 字段，请显式提供 insert_after。",
                    }
            else:
                insert_after = "__first__"

        name = params.get("name")
        if not isinstance(name, str) or not name.strip():
            name = f"v{version.replace('v', '')}" if version else "Next Version"

        description = params.get("description")
        if not isinstance(description, str) or not description.strip():
            description = f"Automated version {version} via plan_extend_preview."

        explicit_allowed_files = self._normalize_optional_string_list(params.get("allowed_files"))
        explicit_acceptance_commands = self._normalize_optional_acceptance_commands(params.get("acceptance_commands"))
        explicit_context_files = self._normalize_optional_string_list(params.get("context_files"))
        explicit_manual_acceptance = self._normalize_optional_string_list(params.get("manual_acceptance"))
        explicit_out_of_scope = self._normalize_optional_string_list(params.get("out_of_scope"))
        explicit_forbidden_files = self._normalize_optional_string_list(params.get("forbidden_files"))

        allowed_files = explicit_allowed_files if explicit_allowed_files else self._infer_allowed_files(repo_profile)
        acceptance_commands = explicit_acceptance_commands if explicit_acceptance_commands else self._infer_acceptance_commands(repo_profile)
        context_files = explicit_context_files if explicit_context_files else self._infer_context_files(repo_profile)

        command_blockers = self._validate_acceptance_commands(acceptance_commands)
        file_blockers = self._validate_allowed_files(allowed_files)

        prompt_text = params.get("prompt")
        if not isinstance(prompt_text, str) or not prompt_text.strip():
            prompt_text = (
                f"Version {version}: {name}.\\n\\n"
                f"Description: {description}\\n\\n"
                f"Review current project state and implement changes.\\n"
                f"Do not perform unsafe git operations (reset/clean/push/merge/rebase/add .).\\n"
                f"Do not modify runtime/logs/plan files.\\n"
                f"Keep changes minimal and focused on this version scope."
            )

        generated_spec = {
            "version": version,
            "name": name,
            "description": description,
            "insert_after": insert_after,
            "allowed_files": allowed_files,
            "acceptance_commands": acceptance_commands,
            "context_files": context_files,
        }
        if explicit_manual_acceptance is not None:
            generated_spec["manual_acceptance"] = explicit_manual_acceptance
        if explicit_out_of_scope is not None:
            generated_spec["out_of_scope"] = explicit_out_of_scope
        if explicit_forbidden_files is not None:
            generated_spec["forbidden_files"] = explicit_forbidden_files

        assumptions = [
            f"Generated version {version} as next version after current plan state.",
            "Prompt is conservative, no unsafe operations included.",
            "allowed_files derived from repo profile.",
            "acceptance_commands are safe object-format commands.",
            "Manual review is required before any apply.",
        ]
        if not params.get("insert_after"):
            assumptions.append(f"insert_after was not specified; auto-resolved to {insert_after}.")

        if dry_run:
            return {
                "ok": True,
                "action": "plan_extend_preview",
                "workflow_action": "plan_extend_preview",
                "dry_run": True,
                "generated_version_spec_summary": generated_spec,
                "confidence": 0.7,
                "assumptions": assumptions,
                "manual_review_required": True,
                "can_preview": True,
                "blockers": command_blockers + file_blockers,
                "warnings": [],
                "recommended_next_action": "review_dry_run_and_proceed",
            }

        spec: dict[str, Any] = {
            "insert_after": insert_after,
            "version": version,
            "name": name,
            "description": description,
            "prompt": prompt_text,
            "allowed_files": allowed_files,
            "acceptance_commands": acceptance_commands,
        }
        if context_files:
            spec["context_files"] = context_files
        if explicit_manual_acceptance is not None:
            spec["manual_acceptance"] = explicit_manual_acceptance
        if explicit_out_of_scope is not None:
            spec["out_of_scope"] = explicit_out_of_scope
        if explicit_forbidden_files is not None:
            spec["forbidden_files"] = explicit_forbidden_files

        try:
            result = self.bridge.preview_insert_version(self.project_root, spec)
        except PlanningBridgeError as e:
            return {
                "ok": False,
                "action": "plan_extend_preview",
                "error_code": "INSERT_PREVIEW_FAILED",
                "message": str(e),
            }
        except Exception as e:
            return {
                "ok": False,
                "action": "plan_extend_preview",
                "error_code": "INSERT_PREVIEW_FAILED",
                "message": f"preview_insert_version 调用失败：{e}",
            }

        if not isinstance(result, dict) or not result.get("ok"):
            return {
                "ok": False,
                "action": "plan_extend_preview",
                "error_code": "INSERT_PREVIEW_FAILED",
                "message": result.get("message", "preview_insert_version 失败。"),
            }

        result.update({
            "workflow_action": "plan_extend_preview",
            "generated_version_spec_summary": generated_spec,
            "confidence": 0.7,
            "assumptions": assumptions,
            "manual_review_required": True,
            "recommended_next_action": "review_patch_and_apply",
        })
        return result

    # ----------------------------------------------------------------
    # Repo analysis helpers
    # ----------------------------------------------------------------
    def _get_repo_overview(self, max_files: int = 300) -> dict[str, Any]:
        return self.source_review.get_repo_overview(self.project_root, {"max_files": max_files})

    def _get_project_identity(self) -> dict[str, Any]:
        from runner.project_identity import build_project_identity
        return build_project_identity(self.project_root)

    def _build_repo_profile(self, overview: dict[str, Any], identity: dict[str, Any]) -> dict[str, Any]:
        file_tree = overview.get("file_tree", [])
        language_map: dict[str, float] = {}
        has_python = any(f.endswith(".py") for f in file_tree)
        has_js = any(f.endswith(".js") or f.endswith(".ts") or f.endswith(".tsx") or f.endswith(".jsx") for f in file_tree)
        has_package_json = any("package.json" in f for f in file_tree)
        has_requirements = any("requirements.txt" in f for f in file_tree)
        has_pyproject = any("pyproject.toml" in f for f in file_tree)
        has_setup_cfg = any("setup.cfg" in f for f in file_tree)
        has_makefile = any("Makefile" in f for f in file_tree)

        if has_python or has_pyproject or has_requirements or has_setup_cfg:
            language_map["python"] = 0.9
        if has_js or has_package_json:
            language_map["javascript"] = 0.7

        runner_py = [f for f in file_tree if f.startswith("runner/") and f.endswith(".py")]
        scripts_py = [f for f in file_tree if f.startswith("scripts/") and f.endswith(".py")]
        adapters_py = [f for f in file_tree if f.startswith("adapters/") and f.endswith(".py")]
        schemas_py = [f for f in file_tree if f.startswith("schemas/") and f.endswith(".py")]

        languages = sorted(language_map.keys(), key=lambda k: -language_map[k])
        entrypoints = []
        for e in ("bin/colameta", "scripts/runner_cli.py", "runner/web_console.py", "runner/mcp_server.py", "main.py", "app.py", "index.py"):
            if e in file_tree:
                if e not in entrypoints:
                    entrypoints.append(e)
        if not entrypoints:
            entrypoints = [f for f in file_tree[:20] if f.endswith(".py") and not f.startswith("tests/") and not f.startswith(".")][:3]

        docs = []
        for d in ("README.md", "AGENTS.md", "docs/RUNNER_USAGE.md", "docs/MCP_PLANNING_BRIDGE.md", "docs/RUNNER_PLAN_AND_PROMPTS.md"):
            if d in file_tree:
                docs.append(d)
        if not docs:
            md_files = [f for f in file_tree if f.endswith(".md")][:5]
            docs.extend(md_files)

        project_basename = identity.get("project_basename", os.path.basename(self.project_root))
        git_branch = identity.get("git_branch")

        return {
            "languages": languages,
            "has_python": has_python,
            "has_pyproject": has_pyproject,
            "has_requirements": has_requirements,
            "has_setup_cfg": has_setup_cfg,
            "has_makefile": has_makefile,
            "has_package_json": has_package_json,
            "file_tree": file_tree,
            "runner_py_count": len(runner_py),
            "scripts_py_count": len(scripts_py),
            "adapters_py_count": len(adapters_py),
            "schemas_py_count": len(schemas_py),
            "entrypoints": entrypoints,
            "docs": docs,
            "project_basename": project_basename,
            "git_branch": git_branch,
            "total_files": len(file_tree),
        }

    def _infer_project_name(self, identity: dict[str, Any]) -> str:
        basename = identity.get("project_basename") or os.path.basename(self.project_root)
        return basename.replace("_", " ").replace("-", " ").title()

    def _infer_goal(self, profile: dict[str, Any]) -> str:
        languages = profile.get("languages", [])
        entrypoints = profile.get("entrypoints", [])
        parts = ["Adopt existing project into ColaMeta"]
        if languages:
            parts.append(f"detected languages: {', '.join(languages)}")
        if entrypoints:
            parts.append(f"entrypoints: {', '.join(entrypoints[:3])}")
        parts.append("generate plan.json and prompts")
        parts.append("confirm existing project structure")
        return ". ".join(parts)

    def _infer_allowed_files(self, profile: dict[str, Any]) -> list[str]:
        allowed: list[str] = list(SAFE_ALLOWED_FILES)
        tree = profile.get("file_tree", [])
        extra = []
        for f in tree:
            if f.endswith(".gitignore") and f not in allowed and f not in extra:
                extra.append(f)
            if f.endswith("pyproject.toml") and f not in allowed and f not in extra:
                extra.append(f)
            if f.endswith("setup.cfg") and f not in allowed and f not in extra:
                extra.append(f)
            if f.endswith("requirements.txt") and f not in allowed and f not in extra:
                extra.append(f)
            if f.endswith("Makefile") and f not in allowed and f not in extra:
                extra.append(f)
            if f.startswith("tests/") and f.endswith(".py") and f not in allowed and f not in extra:
                extra.append(f)
        allowed.extend(extra[:10])
        return allowed

    def _infer_acceptance_commands(self, profile: dict[str, Any]) -> list[dict[str, Any]]:
        cmds = list(SAFE_ACCEPTANCE_COMMANDS)
        if profile.get("has_pyproject") or profile.get("has_requirements"):
            cmds.append({
                "command": "python3 -c 'import sys; print(f\"Python {sys.version}\")'",
                "timeout_seconds": 60,
                "continue_on_failure": False,
            })
        return cmds

    def _infer_context_files(self, profile: dict[str, Any]) -> list[str]:
        docs = profile.get("docs", [])
        if not docs:
            return ["README.md", "AGENTS.md"]
        return docs[:5]

    def _infer_manual_acceptance(self) -> list[str]:
        return [
            "Review generated plan.json before apply",
            "Confirm source-only onboarding assumptions",
            "Confirm Web Console and MCP remain reachable after apply",
        ]

    def _build_first_version_prompt(self, project_name: str, goal: str, profile: dict[str, Any]) -> str:
        entrypoints = profile.get("entrypoints", [])
        docs = profile.get("docs", [])
        languages = profile.get("languages", [])

        lines = [
            f"# Onboard {project_name} into ColaMeta",
            "",
            f"Goal: {goal}",
            "",
            "## Requirements",
            "",
            "1. Review the current project structure and confirm the generated plan.json is correct.",
            "2. Do NOT perform large refactors or architecture changes.",
            "3. Do NOT modify .colameta/runtime, .colameta/logs, or .colameta/plan-patches.",
            "4. Do NOT use git reset, git clean, git push, git merge, git rebase, or git add .",
            "5. Keep changes minimal and focused on confirming the ColaMeta onboarding.",
            "6. Verify that the project compiles and existing tests pass.",
            "7. Do NOT introduce dangerous acceptance commands or broad allowed_files.",
            "",
            "## Detected Project Profile",
            "",
            f"- Languages: {', '.join(languages) if languages else 'detected'}",
            f"- Entrypoints: {', '.join(entrypoints[:5]) if entrypoints else 'none detected'}",
            f"- Docs: {', '.join(docs[:5]) if docs else 'none detected'}",
            "",
            "## Allowed Files",
            "",
            "Only modify files within the allowed_files list from the plan. Do not change runtime/logs/config files.",
        ]
        return "\n".join(lines)

    def _build_assumptions(self, profile: dict[str, Any]) -> list[str]:
        assumptions = [
            "Project is source-only (no existing .colameta/plan.json).",
        ]
        languages = profile.get("languages", [])
        if languages:
            assumptions.append(f"Primary language(s): {', '.join(languages)}.")
        entrypoints = profile.get("entrypoints", [])
        if entrypoints:
            assumptions.append(f"Detected entrypoints: {', '.join(entrypoints[:3])}.")
        docs = profile.get("docs", [])
        if docs:
            assumptions.append(f"Found documentation files: {', '.join(docs[:3])}.")
        else:
            assumptions.append("No documentation files detected; goal may be generic.")
        git_branch = profile.get("git_branch")
        if git_branch:
            assumptions.append(f"Current git branch: {git_branch}.")
        return assumptions

    def _compute_confidence(self, profile: dict[str, Any]) -> float:
        score = 0.5
        if profile.get("has_python") or profile.get("has_pyproject"):
            score += 0.15
        if profile.get("runner_py_count", 0) > 0:
            score += 0.1
        if profile.get("scripts_py_count", 0) > 0:
            score += 0.05
        if profile.get("docs"):
            score += 0.05
        if profile.get("entrypoints"):
            score += 0.05
        return min(score, 0.85)

    def _compute_repair_confidence(self, candidates: list[dict[str, Any]]) -> float:
        if not candidates:
            return 0.0
        deterministic = sum(
            1 for c in candidates
            if c.get("repair_action") in ("normalize_to_object", "add_default_timeout", "add_default_continue_on_failure")
        )
        total = len(candidates)
        base = deterministic / total if total > 0 else 0.0
        return min(0.5 + base * 0.4, 0.9)

    def _infer_next_version(self) -> str:
        plan_path = resolve_project_runner_plan_path(self.project_root)
        if not os.path.isfile(plan_path):
            return "v1.0"
        try:
            from runner.plan_loader import PlanLoader
            loader = PlanLoader()
            plan = loader.load_plan(plan_path)
            if isinstance(plan, dict):
                versions = plan.get("versions", [])
                if versions:
                    last = versions[-1]
                    v_str = last.get("version", "v1.0")
                    return self._bump_version(v_str)
        except Exception:
            pass
        return "v1.0"

    def _bump_version(self, v: str) -> str:
        m = re.fullmatch(r"v?(\d+)(?:\.(\d+))?", v)
        if m:
            major = int(m.group(1))
            minor = int(m.group(2)) if m.group(2) else 0
            new_minor = minor + 1 if m.group(2) else 1
            return f"v{major}.{new_minor}"
        return "v1.0"

    def _validate_allowed_files(self, allowed_files: list[str]) -> list[str]:
        blockers: list[str] = []
        for f in allowed_files:
            if f in BROAD_PATTERNS:
                blockers.append(f"broad allowed_file pattern: {f}")
            if f in FORBIDDEN_PATTERNS:
                blockers.append(f"forbidden allowed_file pattern: {f}")
        return blockers

    def _validate_acceptance_commands(self, commands: list[Any]) -> list[str]:
        blockers: list[str] = []
        for i, cmd in enumerate(commands):
            if not isinstance(cmd, dict):
                blockers.append(f"acceptance_commands[{i}] is not an object")
                continue
            command_str = cmd.get("command", "")
            if DANGEROUS_COMMAND_PATTERNS.search(command_str):
                blockers.append(f"dangerous command at [{i}]: {command_str[:80]}")
            if not isinstance(cmd.get("timeout_seconds"), int):
                blockers.append(f"acceptance_commands[{i}] missing int timeout_seconds")
            if not isinstance(cmd.get("continue_on_failure"), bool):
                blockers.append(f"acceptance_commands[{i}] missing bool continue_on_failure")
        return blockers

    def _normalize_optional_string_list(self, value: Any) -> list[str] | None:
        if value is None:
            return None
        if not isinstance(value, list):
            return None
        out: list[str] = []
        for item in value:
            if isinstance(item, str):
                text = item.strip()
                if text and text not in out:
                    out.append(text)
        return out

    def _normalize_optional_acceptance_commands(self, value: Any) -> list[Any] | None:
        if value is None:
            return None
        if not isinstance(value, list):
            return None
        normalized: list[Any] = []
        for item in value:
            if isinstance(item, str):
                command_text = item.strip()
                if command_text:
                    normalized.append({
                        "command": command_text,
                        "timeout_seconds": 600,
                        "continue_on_failure": False,
                    })
                else:
                    normalized.append(item)
                continue
            if isinstance(item, dict):
                command_obj = dict(item)
                command_raw = command_obj.get("command")
                if isinstance(command_raw, str):
                    command_obj["command"] = command_raw.strip()
                normalized.append(command_obj)
                continue
            normalized.append(item)
        return normalized

    def _generate_repair_preview(self, repair_candidates: list[dict[str, Any]], issues: list[dict[str, Any]], lint_result: dict[str, Any]) -> dict[str, Any]:
        plan_path = resolve_project_runner_plan_path(self.project_root)
        if not os.path.isfile(plan_path):
            return {"ok": False, "message": "plan.json 不存在。"}

        try:
            import json
            with open(plan_path, "r") as f:
                plan = json.load(f)
        except Exception as e:
            return {"ok": False, "message": f"读取 plan.json 失败：{e}"}

        if not isinstance(plan, dict):
            return {"ok": False, "message": "plan.json 格式无效。"}

        versions = plan.get("versions", [])
        if not isinstance(versions, list):
            return {"ok": False, "message": "plan.json 缺少 versions 列表。"}

        version_fixes: dict[str, dict[str, Any]] = {}
        for issue in issues:
            if not isinstance(issue, dict):
                continue
            error_code = issue.get("error_code", "")
            ver = issue.get("version")
            if ver is None:
                continue
            ver_str = str(ver)
            field = issue.get("field", "")

            deterministic_kinds = {"LEGACY_STRING_ACCEPTANCE_COMMAND", "MISSING_TIMEOUT_SECONDS", "MISSING_CONTINUE_ON_FAILURE"}
            if error_code not in deterministic_kinds:
                continue
            if not field or "acceptance_command" not in field:
                continue

            try:
                parts = field.split(".")
                if len(parts) < 3:
                    continue
                cmd_idx = int(parts[1])
            except (ValueError, IndexError):
                continue

            if ver_str not in version_fixes:
                version_fixes[ver_str] = {"version": ver_str, "acceptance_commands": None}

            current_fixes = version_fixes[ver_str]
            current_cmds = current_fixes.get("acceptance_commands")

            if current_cmds is None:
                original_ver = None
                for v in versions:
                    if isinstance(v, dict) and str(v.get("version", "")) == ver_str:
                        original_ver = v
                        break
                if original_ver is None:
                    continue
                raw_cmds = original_ver.get("acceptance_commands", [])
                current_cmds = list(raw_cmds)
                current_fixes["acceptance_commands"] = current_cmds

            if cmd_idx < 0 or cmd_idx >= len(current_cmds):
                continue

            cmd_entry = current_cmds[cmd_idx]
            if not isinstance(cmd_entry, dict):
                cmd_str = str(cmd_entry) if not isinstance(cmd_entry, dict) else ""
                cmd_entry = {"command": cmd_str}
                current_cmds[cmd_idx] = cmd_entry

            if error_code == "LEGACY_STRING_ACCEPTANCE_COMMAND":
                cmd_entry["timeout_seconds"] = 600
                cmd_entry["continue_on_failure"] = False
            elif error_code == "MISSING_TIMEOUT_SECONDS":
                cmd_entry["timeout_seconds"] = 600
            elif error_code == "MISSING_CONTINUE_ON_FAILURE":
                cmd_entry["continue_on_failure"] = False

        if not version_fixes:
            return {"ok": False, "message": "未找到可确定性修复的版本。"}

        patch_preview_ids: list[str] = []
        for ver_str, fix_spec in version_fixes.items():
            if fix_spec.get("acceptance_commands") is None:
                continue
            try:
                update_spec: dict[str, Any] = {
                    "version": ver_str,
                    "acceptance_commands": fix_spec["acceptance_commands"],
                }
                result = self.bridge.preview_update_version(self.project_root, update_spec)
                if isinstance(result, dict) and result.get("ok"):
                    pid = result.get("patch_id") or result.get("preview_id")
                    if isinstance(pid, str) and pid.strip():
                        if pid.strip() not in patch_preview_ids:
                            patch_preview_ids.append(pid.strip())
            except Exception:
                pass

        if not patch_preview_ids:
            return {"ok": False, "message": "无法生成修复 preview patch。"}

        return {
            "ok": True,
            "preview_id": patch_preview_ids[0],
            "patch_preview_ids": patch_preview_ids,
            "message": f"已生成 {len(patch_preview_ids)} 个修复 preview patch。",
        }

    def _bounded_int(self, value: Any, default: int, minimum: int, maximum: int) -> int:
        if isinstance(value, bool):
            return default
        try:
            parsed = int(value)
        except Exception:
            return default
        return max(minimum, min(parsed, maximum))
