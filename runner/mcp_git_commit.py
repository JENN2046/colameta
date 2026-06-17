import hashlib
import json
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from runner._internal_utils import run_git as _run_git_base
from runner.current_version import load_current_version
from runner.core_confirmation import confirmation_git_commit_preview_guard
from runner.executor_run_reports import ExecutorRunReportStore
from runner.git_history_reconcile import GitHistoryReconcileScanner
from runner.path_policy import RunnerPathPolicy
from runner.plan_allowed_files import is_allowed_by_current_plan, current_plan_allowed_patterns
from runner.path_glob import match_any
from runner.runner_status import create_status_from_manager_output
from runner.runner_data_layout import classify_runner_path
from runner.runner_paths import (
    PRIMARY_PROJECT_RUNNER_DIRNAME,
    project_runner_dirnames,
    resolve_project_runner_path,
)
from runner.workflow_records import WorkflowRecordStore


def _best_effort_commit_state_update(
    project_root: str,
    commit_hash: str,
    commit_message: str,
    committed_files: list[str],
    version: str | None = None,
) -> dict:
    try:
        from runner.commit_state_workflow import CommitStateUpdateService
        csu = CommitStateUpdateService(project_root)
        return csu.record_commit_metadata(
            commit_hash=commit_hash,
            commit_message=commit_message,
            committed_files=committed_files,
            version=version,
        )
    except Exception:
        return {"ok": False, "skipped": True, "reason": "update_failed"}


class MCPGitCommitManager:
    _PREVIEW_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]+")

    def __init__(self, project_root: str):
        self.project_root = os.path.abspath(os.path.expanduser(project_root))
        self.project_root_real = os.path.realpath(self.project_root)
        self.preview_dir = resolve_project_runner_path(self.project_root, "runtime", "commit-previews")
        self.preview_ttl_seconds = 1800
        self.path_policy = RunnerPathPolicy()
        self.excluded_patterns = self.path_policy.commit_excluded_patterns()
        self.blocked_patterns = self.path_policy.commit_blocked_patterns()
        self._untracked_allowed_patterns = self.path_policy.commit_allowed_patterns()

    def _read_current_head_state(self) -> dict[str, Any]:
        head_res = self._run_git(["rev-parse", "HEAD"])
        if head_res["code"] == 0:
            current_head = str(head_res["stdout"] or "").strip()
            if current_head:
                return {
                    "ok": True,
                    "current_head": current_head,
                    "has_head": True,
                    "initial_commit": False,
                }

        if self._has_empty_git_history() or self._is_initial_commit_head_failure(head_res):
            return {
                "ok": True,
                "current_head": None,
                "has_head": False,
                "initial_commit": True,
                "warning": "initial_commit",
            }

        return {
            "ok": False,
            "error_code": "HEAD_READ_FAILED",
            "message": self._git_error_message(head_res, "读取当前 HEAD 失败。"),
        }

    def _has_empty_git_history(self) -> bool:
        worktree_res = self._run_git(["rev-parse", "--is-inside-work-tree"])
        if worktree_res["code"] != 0:
            return False
        if str(worktree_res.get("stdout") or "").strip().lower() != "true":
            return False

        count_res = self._run_git(["rev-list", "--count", "--all"])
        if count_res["code"] != 0:
            return False
        try:
            return int(str(count_res.get("stdout") or "").strip()) == 0
        except ValueError:
            return False

    def _is_initial_commit_head_failure(self, result: dict[str, Any]) -> bool:
        if not isinstance(result, dict):
            return False
        if int(result.get("code", 0) or 0) == 0:
            return False

        message_parts = [str(result.get("stderr") or "").strip(), str(result.get("stdout") or "").strip()]
        message = "\n".join(part for part in message_parts if part).lower()
        if not message:
            return False

        keywords = (
            "ambiguous argument 'head'",
            'ambiguous argument "head"',
            "unknown revision or path not in the working tree",
            "needed a single revision",
        )
        return any(keyword in message for keyword in keywords)

    def _load_recent_patch_evidence_from_workflows(
        self,
        version: str,
        files_to_commit: list[str],
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "post_executor_patch_detected": False,
            "manual_acceptance_present": False,
            "patch_evidence": [],
            "manual_acceptance_sources": [],
            "notes": [],
        }
        try:
            store = WorkflowRecordStore(self.project_root)
            list_ret = store.list_runs(limit=100)
        except Exception as exc:
            result["notes"].append(f"workflow store list failed: {exc}")
            return result
        if not isinstance(list_ret, dict) or not list_ret.get("ok"):
            result["notes"].append("workflow store list unavailable")
            return result
        wf_ids = [r.get("workflow_id") for r in list_ret.get("runs", []) if isinstance(r, dict)]
        for wf_id in wf_ids:
            if not isinstance(wf_id, str) or not wf_id:
                continue
            try:
                get_ret = store.get_run(wf_id)
            except Exception:
                continue
            if not isinstance(get_ret, dict) or not get_ret.get("ok"):
                continue
            run = get_ret.get("run", {})
            if not isinstance(run, dict):
                continue
            self._scan_workflow_record_for_evidence(run, version, files_to_commit, result)
        return result

    def _scan_workflow_record_for_evidence(
        self,
        run: dict[str, Any],
        version: str,
        files_to_commit: list[str],
        result: dict[str, Any],
    ) -> None:
        scan_targets: list[dict[str, Any]] = []
        run_os = run.get("outputs_summary")
        if isinstance(run_os, dict):
            scan_targets.append(run_os)
        steps = run.get("steps", [])
        if isinstance(steps, list):
            for step in steps:
                step_os = step.get("outputs_summary") if isinstance(step, dict) else None
                if isinstance(step_os, dict):
                    scan_targets.append(step_os)
        for os_dict in scan_targets:
            patch_ev = os_dict.get("post_executor_patch_evidence")
            if isinstance(patch_ev, dict):
                self._match_patch_evidence(patch_ev, version, files_to_commit, result)
            ma_ev = os_dict.get("manual_acceptance_evidence")
            if isinstance(ma_ev, dict):
                self._match_manual_acceptance(ma_ev, version, patch_ev, result)

    def _match_patch_evidence(
        self,
        patch_ev: dict[str, Any],
        version: str,
        files_to_commit: list[str],
        result: dict[str, Any],
    ) -> None:
        ev_version = str(patch_ev.get("version") or "")
        if ev_version != version:
            return
        source = str(patch_ev.get("evidence_source") or "")
        if source != "controlled_patch_apply":
            return
        tool = str(patch_ev.get("tool") or "")
        if tool not in ("manage_project_patch", "manage_project_docs"):
            return
        ev_files = patch_ev.get("files_changed", [])
        if not isinstance(ev_files, list):
            return
        common = list(set(f.replace("\\", "/") for f in ev_files if isinstance(f, str)) & set(files_to_commit))
        if not common:
            return
        entry = {
            "tool": tool,
            "preview_id": str(patch_ev.get("preview_id") or ""),
            "files_changed": sorted(common),
            "operation": str(patch_ev.get("operation") or ""),
            "applied_at": str(patch_ev.get("applied_at") or ""),
        }
        ids = [e.get("preview_id") for e in result["patch_evidence"]]
        if entry["preview_id"] not in ids:
            result["patch_evidence"].append(entry)
        result["post_executor_patch_detected"] = True

    def _match_manual_acceptance(
        self,
        ma_ev: dict[str, Any],
        version: str,
        patch_ev: dict[str, Any] | None,
        result: dict[str, Any],
    ) -> None:
        ev_version = str(ma_ev.get("version") or "")
        patch_version = str(patch_ev.get("version") or "") if isinstance(patch_ev, dict) else ""
        if ev_version != version and patch_version != version:
            return
        if ma_ev.get("present") is not True:
            return
        source = str(ma_ev.get("source") or "")
        if not source:
            return
        if source not in result["manual_acceptance_sources"]:
            result["manual_acceptance_sources"].append(source)
        result["manual_acceptance_present"] = True

    def _check_evidence_mismatch(self, files_to_commit: list[str]) -> dict[str, Any]:
        result: dict[str, Any] = {
            "detected": False,
            "completion_evidence_mode": None,
            "post_executor_patch_detected": False,
            "manual_acceptance_present": False,
            "warning": None,
            "notes": [],
        }
        version = load_current_version(self.project_root)
        if not version:
            result["notes"].append("current_version unavailable")
            return result
        try:
            report_store = ExecutorRunReportStore(self.project_root)
            report_ret = report_store.get_report(latest=True, version=version, include_markdown=False)
        except Exception:
            report_ret = {}
        if not isinstance(report_ret, dict) or not report_ret.get("ok"):
            result["notes"].append("no executor run report found for this version")
            return result
        report = report_ret.get("report", {})
        if not isinstance(report, dict):
            return result
        evidence_raw = report.get("completion_evidence")
        evidence = evidence_raw if isinstance(evidence_raw, dict) else {}
        mode = str(evidence.get("mode", "") or "")
        result["completion_evidence_mode"] = mode if mode else None
        if mode != "validation_only_no_diff":
            return result
        allowed_patterns = current_plan_allowed_patterns(self.project_root)
        allowed_changes = [f for f in files_to_commit if allowed_patterns and match_any(f, allowed_patterns)]
        if not allowed_changes:
            result["notes"].append("no allowed_files changes in commit set")
            return result
        result["detected"] = True
        wf_evidence = self._load_recent_patch_evidence_from_workflows(version, files_to_commit)
        if not wf_evidence.get("post_executor_patch_detected"):
            result["warning"] = "当前版本 executor report 为 PASSED，但未产生目标文件 diff；本次提交包含 allowed_files 变更，但未找到对应受控 patch evidence。请确认变更来源。"
            result["notes"].append("validation_only_no_diff but no matching patch evidence found in workflow records")
            return result
        result["post_executor_patch_detected"] = True
        result["patch_evidence_details"] = wf_evidence.get("patch_evidence", [])
        if not wf_evidence.get("manual_acceptance_present"):
            result["warning"] = "当前版本 executor report 为 PASSED，但未产生目标文件 diff；最终变更来自受控 patch。请确认人工验收记录。"
            result["notes"].append("validation_only_no_diff with post-executor patch changes pending commit")
            return result
        result["manual_acceptance_present"] = True
        result["manual_acceptance_sources"] = wf_evidence.get("manual_acceptance_sources", [])
        result["warning"] = None
        result["notes"].append(
            "当前版本由 validation-only executor report + post-executor patch + manual acceptance 完成。"
        )
        return result

    def readiness(
        self,
        include_diff_summary: bool = True,
        max_diff_chars: int = 40000,
        include_files: list[str] | None = None,
        exclude_files: list[str] | None = None,
    ) -> dict[str, Any]:
        repo_check = self._run_git(["rev-parse", "--is-inside-work-tree"])
        if repo_check["code"] != 0:
            return {
                "ok": False,
                "action": "readiness",
                "error_code": "NOT_GIT_REPOSITORY",
                "message": self._git_error_message(repo_check, "当前目录不是 Git 仓库。"),
            }

        head_state = self._read_current_head_state()
        if head_state.get("ok") is not True:
            return {
                "ok": False,
                "action": "readiness",
                "error_code": str(head_state.get("error_code") or "HEAD_READ_FAILED"),
                "message": str(head_state.get("message") or "读取当前 HEAD 失败。"),
            }
        current_head = head_state.get("current_head")
        has_head = bool(head_state.get("has_head"))
        initial_commit = bool(head_state.get("initial_commit"))

        status_res = self._run_git(["status", "--short"])
        if status_res["code"] != 0:
            return {
                "ok": False,
                "action": "readiness",
                "error_code": "GIT_STATUS_FAILED",
                "message": self._git_error_message(status_res, "读取 git status 失败。"),
            }

        status_lines = [line for line in status_res["stdout"].splitlines() if line.strip()]
        changed_files: list[str] = []
        untracked_files: list[str] = []
        files_to_commit: list[str] = []
        excluded_files: list[str] = []
        blocked_files: list[str] = []
        unsupported_status_entries: list[str] = []
        commit_warnings: list[str] = []

        for line in status_lines:
            parsed = self._parse_status_line(line)
            if parsed is None:
                unsupported_status_entries.append(line)
                continue
            if parsed["status"] == "!!":
                continue
            if parsed["unsupported"]:
                unsupported_status_entries.append(line)
                continue

            rel_path = parsed["path"]
            is_untracked = parsed["status"].startswith("??")

            if is_untracked:
                abs_candidate = os.path.join(self.project_root, rel_path)
                if os.path.isdir(abs_candidate):
                    expanded = self._expand_untracked_directory(rel_path)
                    if expanded:
                        for expanded_path in expanded:
                            untracked_files.append(expanded_path)
                            if expanded_path not in files_to_commit:
                                files_to_commit.append(expanded_path)
                    else:
                        excluded_files.append(rel_path)
                    continue

            if is_untracked:
                untracked_files.append(rel_path)
            else:
                changed_files.append(rel_path)

            is_tracked_deletion = self._is_tracked_deletion(parsed["status"])
            classify = self._classify_path(rel_path)
            if classify["blocked"]:
                blocked_files.append(rel_path)
                continue
            if classify["excluded"] and not is_tracked_deletion:
                excluded_files.append(rel_path)
                continue
            if not classify["safe"]:
                blocked_files.append(rel_path)
                continue

            if rel_path not in files_to_commit:
                files_to_commit.append(rel_path)

        diff_check = self._run_git(["diff", "--check"])
        commit_blockers: list[str] = []
        if blocked_files:
            commit_blockers.append("blocked_files_present")
        if unsupported_status_entries:
            commit_blockers.append("unsupported_status_entries_present")
        if diff_check["code"] != 0:
            commit_blockers.append("git_diff_check_failed")
        if not files_to_commit:
            commit_blockers.append("no_files_to_commit")

        if blocked_files:
            commit_warnings.append("contains_blocked_files")
        if excluded_files:
            commit_warnings.append("contains_excluded_files")
        if unsupported_status_entries:
            commit_warnings.append("contains_unsupported_status_entries")
        if initial_commit:
            commit_warnings.append("initial_commit")

        working_tree_clean = len(status_lines) == 0
        can_preview = bool(files_to_commit)
        can_commit = len(commit_blockers) == 0

        available_files_to_commit = sorted(files_to_commit)
        normalized_include_files, include_error = self._normalize_file_selection_list(
            include_files,
            action="readiness",
            field_name="include_files",
        )
        if include_error is not None:
            return include_error
        normalized_exclude_files, exclude_error = self._normalize_file_selection_list(
            exclude_files,
            action="readiness",
            field_name="exclude_files",
        )
        if exclude_error is not None:
            return exclude_error
        selected_files_to_commit, selection_meta, selection_error = self._select_files_for_commit(
            available_files_to_commit=available_files_to_commit,
            blocked_files=blocked_files,
            excluded_files=excluded_files,
            unsupported_status_entries=unsupported_status_entries,
            include_files=normalized_include_files,
            exclude_files=normalized_exclude_files,
            action="readiness",
        )
        if selection_error is not None:
            return selection_error
        selected_status_short = self._build_selected_status_short(
            status_lines=status_lines,
            selected_files=selected_files_to_commit,
            untracked_files=untracked_files,
        )
        file_signatures = self._build_file_signatures(selected_files_to_commit)
        diff_hash = self._build_diff_hash(
            current_head=current_head,
            status_short=selected_status_short,
            files_to_commit=selected_files_to_commit,
            file_signatures=file_signatures,
        )

        diff_summary, diff_truncated = self._build_diff_summary(
            include_diff_summary=include_diff_summary,
            max_diff_chars=max_diff_chars,
            selected_files=selected_files_to_commit,
            untracked_files=untracked_files,
            initial_commit=initial_commit,
        )

        recommended_next_action = "fix_blockers"
        if can_commit:
            recommended_next_action = "preview"
        elif working_tree_clean:
            recommended_next_action = "nothing_to_commit"

        evidence_mismatch = self._check_evidence_mismatch(selected_files_to_commit)
        if evidence_mismatch.get("detected") and evidence_mismatch.get("warning"):
            warning_text = evidence_mismatch["warning"]
            if warning_text not in commit_warnings and not evidence_mismatch.get("manual_acceptance_present"):
                commit_warnings.append(warning_text)

        result: dict[str, Any] = {
            "ok": True,
            "action": "readiness",
            "project_root": self.project_root,
            "current_head": current_head,
            "has_head": has_head,
            "initial_commit": initial_commit,
            "status_short": status_lines,
            "selected_status_short": selected_status_short,
            "changed_files": sorted(changed_files),
            "untracked_files": sorted(untracked_files),
            "files_to_commit": sorted(selected_files_to_commit),
            "available_files_to_commit": available_files_to_commit,
            "file_selection": selection_meta or {},
            "excluded_files": sorted(excluded_files),
            "blocked_files": sorted(blocked_files),
            "unsupported_status_entries": unsupported_status_entries,
            "working_tree_clean": working_tree_clean,
            "can_preview": can_preview,
            "can_commit": can_commit,
            "can_commit_without_preview": False,
            "commit_blockers": commit_blockers,
            "commit_warnings": commit_warnings,
            "evidence_mismatch_warning": evidence_mismatch,
            "diff_hash": diff_hash,
            "diff_summary": diff_summary,
            "diff_truncated": diff_truncated,
            "recommended_next_action": recommended_next_action,
            "unified_status": create_status_from_manager_output(
                {
                    "working_tree_clean": working_tree_clean,
                    "can_preview": can_preview,
                    "commit_blockers": commit_blockers,
                    "commit_warnings": commit_warnings,
                },
                source="git_commit",
                action="readiness",
            ).to_dict(),
        }
        if diff_check["code"] != 0:
            result["diff_check_message"] = self._git_error_message(diff_check, "git diff --check 失败。")
        return result

    def _suggest_messages(
        self,
        files_to_commit: list[str],
        diff_hash: str,
        diff_summary: str,
        scope_hint: str | None,
        style: str,
    ) -> dict[str, Any]:
        suggestions: list[dict[str, Any]] = []
        file_set = set(files_to_commit)
        scope_hints: list[str] = []
        if scope_hint:
            scope_hints.append(scope_hint)

        mcp_docs_files = {"runner/mcp_project_docs.py"}
        mcp_git_history_files = {"runner/mcp_git_history.py"}
        mcp_git_commit_files = {"runner/mcp_git_commit.py"}
        workflow_engine_files = {"runner/workflow_engine.py", "runner/workflow_records.py"}
        mcp_workflow_router_files = {"runner/mcp_workflow_router.py"}

        has_git_commit = bool(file_set & mcp_git_commit_files)
        has_git_history = bool(file_set & mcp_git_history_files)

        has_workflow_router = bool(file_set & mcp_workflow_router_files)
        if has_workflow_router:
            suggestions.append({
                "message": "add MCP workflow router",
                "confidence": "high",
                "reason": "files include MCP workflow router",
                "scope_hints": ["workflow_router"],
                "risks": [],
            })
            suggestions.append({
                "message": "consolidate MCP workflow UX",
                "confidence": "high",
                "reason": "files include MCP workflow router and server wiring",
                "scope_hints": ["workflow_ux"],
                "risks": [],
            })

        if has_git_commit and has_git_history:
            suggestions.append({
                "message": "enhance MCP git revert and commit workflow",
                "confidence": "high",
                "reason": "files include both git commit and git history managers",
                "scope_hints": ["git_workflow"],
                "risks": [],
            })

        if has_git_commit:
            suggestions.append({
                "message": "enhance MCP git commit workflow",
                "confidence": "high",
                "reason": "files include MCP git commit manager",
                "scope_hints": ["git_commit"],
                "risks": [],
            })

        if has_git_history:
            suggestions.append({
                "message": "add controlled MCP git history manager",
                "confidence": "high",
                "reason": "files include MCP git history manager",
                "scope_hints": ["git_history"],
                "risks": [],
            })

        if file_set & workflow_engine_files:
            suggestions.append({
                "message": "enhance MCP workflow records",
                "confidence": "medium",
                "reason": "files include workflow engine or records",
                "scope_hints": ["workflow_records"],
                "risks": [],
            })

        if file_set & mcp_docs_files:
            suggestions.append({
                "message": "add MCP docs workflow",
                "confidence": "high",
                "reason": "files include MCP project docs manager",
                "scope_hints": ["docs_workflow"],
                "risks": [],
            })

        only_docs = all(
            f.endswith(".md") or f.startswith("docs/")
            for f in files_to_commit
        )
        if only_docs and files_to_commit:
            suggestions.append({
                "message": "update MCP workflow documentation",
                "confidence": "medium",
                "reason": "only documentation files changed",
                "scope_hints": ["documentation"],
                "risks": [],
            })

        mcp_manager_count = 0
        for f in file_set:
            if any(f.startswith(p) for p in ("runner/mcp_",)):
                mcp_manager_count += 1
        if mcp_manager_count >= 2 and not suggestions:
            suggestions.append({
                "message": "enhance MCP workflow automation",
                "confidence": "medium",
                "reason": f"changes span {mcp_manager_count} MCP managers",
                "scope_hints": ["mcp_automation"],
                "risks": [],
            })

        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        for s in suggestions:
            if s["message"] not in seen:
                seen.add(s["message"])
                unique.append(s)

        if not unique:
            unique.append({
                "message": "update project files",
                "confidence": "low",
                "reason": "generic file changes",
                "scope_hints": [],
                "risks": [],
            })

        if scope_hints:
            for s in unique:
                for h in scope_hints:
                    if h not in s["scope_hints"]:
                        s["scope_hints"].append(h)

        version_prefix = ""
        if scope_hint:
            version_prefix = f"{scope_hint} "
        elif style == "runner_version" and scope_hints:
            pass

        recommended_message = unique[0]["message"]
        if version_prefix:
            recommended_message = f"{version_prefix}{recommended_message}"

        return {
            "suggestions": unique,
            "recommended_message": recommended_message,
            "scope_hints": scope_hints,
        }

    def suggest_commit_message(
        self,
        include_diff_summary: bool = True,
        max_diff_chars: int = 40000,
        style: str = "runner_version",
        scope_hint: str | None = None,
        include_files: list[str] | None = None,
        exclude_files: list[str] | None = None,
    ) -> dict[str, Any]:
        readiness = self.readiness(
            include_diff_summary=include_diff_summary,
            max_diff_chars=max_diff_chars,
            include_files=include_files,
            exclude_files=exclude_files,
        )
        if readiness.get("ok") is not True:
            return {
                "ok": False,
                "action": "suggest_commit_message",
                "error_code": str(readiness.get("error_code") or "READINESS_FAILED"),
                "message": str(readiness.get("message") or "无法读取 readiness。"),
            }

        working_tree_clean = bool(readiness.get("working_tree_clean", False))
        files_to_commit: list[str] = readiness.get("files_to_commit", [])
        diff_hash: str = readiness.get("diff_hash", "")
        diff_summary: str = readiness.get("diff_summary", "")
        commit_blockers: list[str] = readiness.get("commit_blockers", [])
        commit_warnings: list[str] = readiness.get("commit_warnings", [])
        can_preview = bool(readiness.get("can_preview", False))

        if working_tree_clean:
            return {
                "ok": True,
                "action": "suggest_commit_message",
                "working_tree_clean": True,
                "has_head": bool(readiness.get("has_head", True)),
                "initial_commit": bool(readiness.get("initial_commit", False)),
                "suggestions": [],
                "recommended_message": "",
                "can_preview": False,
                "files_to_commit": [],
                "diff_hash": "",
                "commit_blockers": [],
                "commit_warnings": [],
                "message": "没有可提交改动。",
            }

        msg_result = self._suggest_messages(files_to_commit, diff_hash, diff_summary, scope_hint, style)

        return {
            "ok": True,
            "action": "suggest_commit_message",
            "working_tree_clean": False,
            "has_head": bool(readiness.get("has_head", True)),
            "initial_commit": bool(readiness.get("initial_commit", False)),
            "files_to_commit": files_to_commit,
            "available_files_to_commit": readiness.get("available_files_to_commit", files_to_commit),
            "file_selection": readiness.get("file_selection", {}),
            "diff_hash": diff_hash,
            "commit_blockers": commit_blockers,
            "commit_warnings": commit_warnings,
            "suggestions": msg_result["suggestions"],
            "recommended_message": msg_result["recommended_message"],
            "scope_hints": msg_result["scope_hints"],
            "can_preview": can_preview,
        }

    def commit_workflow_preview(
        self,
        message: str | None = None,
        include_diff_summary: bool = True,
        max_diff_chars: int = 40000,
        style: str = "runner_version",
        scope_hint: str | None = None,
        include_files: list[str] | None = None,
        exclude_files: list[str] | None = None,
    ) -> dict[str, Any]:
        suggest_result = self.suggest_commit_message(
            include_diff_summary=include_diff_summary,
            max_diff_chars=max_diff_chars,
            style=style,
            scope_hint=scope_hint,
            include_files=include_files,
            exclude_files=exclude_files,
        )
        if suggest_result.get("ok") is not True:
            return {
                "ok": False,
                "action": "commit_workflow_preview",
                "error_code": str(suggest_result.get("error_code") or "SUGGEST_FAILED"),
                "message": str(suggest_result.get("message") or "无法生成 commit message 建议。"),
            }

        if not suggest_result.get("can_preview", False):
            return {
                "ok": False,
                "action": "commit_workflow_preview",
                "error_code": "NO_FILES_TO_COMMIT",
                "message": "没有可提交改动。",
                "working_tree_clean": bool(suggest_result.get("working_tree_clean", False)),
            }

        final_message = message
        if not final_message:
            final_message = suggest_result.get("recommended_message", "").strip()
        if not final_message:
            return {
                "ok": False,
                "action": "commit_workflow_preview",
                "error_code": "COMMIT_MESSAGE_REQUIRED",
                "message": "commit message 为空。请提供 message 参数。",
            }

        preview_result = self.preview(
            message=final_message,
            include_diff_summary=include_diff_summary,
            max_diff_chars=max_diff_chars,
            include_files=include_files,
            exclude_files=exclude_files,
        )
        if preview_result.get("ok") is not True:
            return {
                "ok": False,
                "action": "commit_workflow_preview",
                "error_code": str(preview_result.get("error_code") or "PREVIEW_FAILED"),
                "message": str(preview_result.get("message") or "创建 commit preview 失败。"),
            }

        return {
            "ok": True,
            "action": "commit_workflow_preview",
            "preview_id": preview_result.get("preview_id"),
            "message": final_message,
            "suggested_message": suggest_result.get("recommended_message", ""),
            "suggestions": suggest_result.get("suggestions", []),
            "current_head": preview_result.get("current_head"),
            "files_to_commit": preview_result.get("files_to_commit", []),
            "available_files_to_commit": preview_result.get("available_files_to_commit", []),
            "file_selection": preview_result.get("file_selection", {}),
            "has_head": preview_result.get("has_head"),
            "initial_commit": preview_result.get("initial_commit"),
            "diff_hash": preview_result.get("diff_hash"),
            "diff_summary": preview_result.get("diff_summary"),
            "diff_truncated": preview_result.get("diff_truncated"),
            "risk_warnings": suggest_result.get("commit_warnings", []),
            "scope_hints": suggest_result.get("scope_hints", []),
            "commit_blockers": suggest_result.get("commit_blockers", []),
            "evidence_mismatch_warning": preview_result.get("evidence_mismatch_warning", {}),
            "can_commit": preview_result.get("can_commit", False),
            "can_preview": preview_result.get("can_preview", False),
            "recommended_next_action": "manage_git_commit.commit",
        }

    def preview(
        self,
        message: str,
        include_diff_summary: bool = True,
        max_diff_chars: int = 40000,
        include_files: list[str] | None = None,
        exclude_files: list[str] | None = None,
    ) -> dict[str, Any]:
        readiness = self.readiness(
            include_diff_summary=include_diff_summary,
            max_diff_chars=max_diff_chars,
            include_files=include_files,
            exclude_files=exclude_files,
        )
        if readiness.get("ok") is not True:
            return {
                "ok": False,
                "action": "preview",
                "error_code": str(readiness.get("error_code") or "READINESS_FAILED"),
                "message": str(readiness.get("message") or "无法读取 readiness。"),
            }

        if not readiness.get("can_preview", False):
            return {
                "ok": False,
                "action": "preview",
                "error_code": "NO_FILES_TO_COMMIT",
                "message": "没有可预览的可提交文件。",
                "current_head": readiness.get("current_head"),
                "has_head": readiness.get("has_head"),
                "initial_commit": readiness.get("initial_commit"),
            }

        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=self.preview_ttl_seconds)
        preview_id = secrets.token_urlsafe(24)
        preview_record = {
            "preview_id": preview_id,
            "project_root": self.project_root,
            "message": message,
            "current_head": readiness.get("current_head"),
            "has_head": readiness.get("has_head"),
            "initial_commit": readiness.get("initial_commit"),
            "status_short": readiness.get("status_short", []),
            "selected_status_short": readiness.get("selected_status_short", []),
            "files_to_commit": readiness.get("files_to_commit", []),
            "available_files_to_commit": readiness.get("available_files_to_commit", readiness.get("files_to_commit", [])),
            "file_selection": readiness.get("file_selection", {}),
            "excluded_files": readiness.get("excluded_files", []),
            "blocked_files": readiness.get("blocked_files", []),
            "unsupported_status_entries": readiness.get("unsupported_status_entries", []),
            "commit_blockers": readiness.get("commit_blockers", []),
            "commit_warnings": readiness.get("commit_warnings", []),
            "evidence_mismatch_warning": readiness.get("evidence_mismatch_warning", {}),
            "can_commit": len(readiness.get("commit_blockers", [])) == 0,
            "diff_hash": readiness.get("diff_hash"),
            "diff_summary": readiness.get("diff_summary", ""),
            "diff_truncated": bool(readiness.get("diff_truncated")),
            "created_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
            "committed_at": None,
            "commit_hash": None,
        }
        preview_file = self._preview_file_path(preview_id)
        self._write_json(preview_file, preview_record)

        return {
            "ok": True,
            "action": "preview",
            "preview_id": preview_id,
            "project_root": self.project_root,
            "message": message,
            "current_head": preview_record["current_head"],
            "has_head": preview_record["has_head"],
            "initial_commit": preview_record["initial_commit"],
            "status_short": preview_record["status_short"],
            "selected_status_short": preview_record.get("selected_status_short", []),
            "files_to_commit": preview_record["files_to_commit"],
            "available_files_to_commit": preview_record.get("available_files_to_commit", preview_record["files_to_commit"]),
            "file_selection": preview_record.get("file_selection", {}),
            "excluded_files": preview_record["excluded_files"],
            "blocked_files": preview_record["blocked_files"],
            "commit_blockers": preview_record["commit_blockers"],
            "commit_warnings": preview_record["commit_warnings"],
            "evidence_mismatch_warning": preview_record.get("evidence_mismatch_warning", {}),
            "can_commit": preview_record["can_commit"],
            "can_preview": readiness.get("can_preview", False),
            "diff_hash": preview_record["diff_hash"],
            "diff_summary": preview_record["diff_summary"],
            "diff_truncated": preview_record["diff_truncated"],
            "expires_at": preview_record["expires_at"],
            "preview_file": os.path.relpath(preview_file, self.project_root).replace("\\", "/"),
        }

    def commit(self, preview_id: str, message: str | None = None) -> dict[str, Any]:
        normalized_preview_id = self._normalize_preview_id(preview_id)
        if normalized_preview_id is None:
            return {
                "ok": False,
                "action": "commit",
                "error_code": "INVALID_PREVIEW_ID",
                "message": "preview_id 格式无效。",
                "preview_id": self._truncate_preview_id_for_error(preview_id),
            }
        try:
            preview_file = self._preview_file_path(normalized_preview_id)
        except ValueError:
            return {
                "ok": False,
                "action": "commit",
                "error_code": "INVALID_PREVIEW_ID",
                "message": "preview_id 格式无效。",
                "preview_id": self._truncate_preview_id_for_error(preview_id),
            }
        if not os.path.isfile(preview_file):
            return {
                "ok": False,
                "action": "commit",
                "error_code": "PREVIEW_NOT_FOUND",
                "message": "preview_id 对应的预览不存在。",
                "preview_id": normalized_preview_id,
            }

        preview = self._read_json(preview_file)
        if not isinstance(preview, dict):
            return {
                "ok": False,
                "action": "commit",
                "error_code": "PREVIEW_INVALID",
                "message": "预览文件格式无效。",
                "preview_id": normalized_preview_id,
            }

        preview_guard = confirmation_git_commit_preview_guard(preview, now=datetime.now(timezone.utc))
        if preview_guard.get("ok") is not True:
            error_result = {
                "ok": False,
                "action": "commit",
                "error_code": str(preview_guard.get("error_code") or "PREVIEW_INVALID"),
                "message": str(preview_guard.get("message") or "预览文件格式无效。"),
                "preview_id": normalized_preview_id,
            }
            commit_hash = preview_guard.get("commit_hash")
            if commit_hash is not None:
                error_result["commit_hash"] = commit_hash
            return error_result

        preview_message = str(preview.get("message") or "")
        if message is not None and message != preview_message:
            return {
                "ok": False,
                "action": "commit",
                "error_code": "MESSAGE_MISMATCH",
                "message": "commit message 与 preview message 不一致。",
                "preview_id": normalized_preview_id,
            }
        commit_message = preview_message
        if not commit_message:
            return {
                "ok": False,
                "action": "commit",
                "error_code": "COMMIT_MESSAGE_MISSING",
                "message": "preview 中缺少 commit message。",
                "preview_id": normalized_preview_id,
            }

        full_readiness = self.readiness(include_diff_summary=False, max_diff_chars=1)
        if full_readiness.get("ok") is not True:
            return {
                "ok": False,
                "action": "commit",
                "error_code": str(full_readiness.get("error_code") or "READINESS_FAILED"),
                "message": str(full_readiness.get("message") or "无法读取 readiness。"),
                "preview_id": normalized_preview_id,
            }

        current_head_before = full_readiness.get("current_head")
        preview_head = preview.get("current_head")
        preview_initial_commit = bool(preview.get("initial_commit"))
        full_initial_commit = bool(full_readiness.get("initial_commit"))

        if preview_initial_commit:
            if not full_initial_commit or current_head_before is not None:
                return {
                    "ok": False,
                    "action": "commit",
                    "error_code": "INITIAL_COMMIT_STATE_CHANGED",
                    "message": "初始提交状态已变化，请重新 preview。",
                    "preview_id": normalized_preview_id,
                    "current_head": current_head_before,
                    "preview_head": preview_head,
                    "preview_initial_commit": preview_initial_commit,
                    "current_initial_commit": full_initial_commit,
                }
        elif current_head_before != preview_head:
            return {
                "ok": False,
                "action": "commit",
                "error_code": "HEAD_CHANGED",
                "message": "HEAD 已变化，请重新 preview。",
                "preview_id": normalized_preview_id,
                "current_head": current_head_before,
                "preview_head": preview.get("current_head"),
            }

        preview_files = sorted([str(item) for item in preview.get("files_to_commit", []) if isinstance(item, str)])
        selected_readiness = self.readiness(
            include_diff_summary=False,
            max_diff_chars=1,
            include_files=preview_files,
        )
        if selected_readiness.get("ok") is not True:
            selection_error_code = str(selected_readiness.get("error_code") or "READINESS_FAILED")
            if selection_error_code in {"FILE_NOT_COMMITTABLE", "NO_FILES_TO_COMMIT"}:
                return {
                    "ok": False,
                    "action": "commit",
                    "error_code": "FILES_CHANGED",
                    "message": "可提交文件集合已变化，请重新 preview。",
                    "preview_id": normalized_preview_id,
                    "preview_files": preview_files,
                }
            return {
                "ok": False,
                "action": "commit",
                "error_code": selection_error_code,
                "message": str(selected_readiness.get("message") or "无法读取已选择文件的 readiness。"),
                "preview_id": normalized_preview_id,
            }

        current_diff_hash = str(selected_readiness.get("diff_hash") or "")
        preview_diff_hash = str(preview.get("diff_hash") or "")
        if current_diff_hash != preview_diff_hash:
            return {
                "ok": False,
                "action": "commit",
                "error_code": "DIFF_HASH_CHANGED",
                "message": "工作区变更已变化，请重新 preview。",
                "preview_id": normalized_preview_id,
            }

        current_files = sorted([str(item) for item in selected_readiness.get("files_to_commit", []) if isinstance(item, str)])
        if current_files != preview_files:
            return {
                "ok": False,
                "action": "commit",
                "error_code": "FILES_CHANGED",
                "message": "可提交文件集合已变化，请重新 preview。",
                "preview_id": normalized_preview_id,
                "current_files": current_files,
                "preview_files": preview_files,
            }

        commit_blockers = [str(item) for item in full_readiness.get("commit_blockers", [])]
        commit_blockers = [item for item in commit_blockers if item != "no_files_to_commit"]
        if commit_blockers:
            return {
                "ok": False,
                "action": "commit",
                "error_code": "COMMIT_BLOCKED",
                "message": "当前存在提交阻断，请先处理后再提交。",
                "preview_id": normalized_preview_id,
                "commit_blockers": commit_blockers,
            }

        if not current_files:
            return {
                "ok": False,
                "action": "commit",
                "error_code": "NO_FILES_TO_COMMIT",
                "message": "没有可提交文件。",
                "preview_id": normalized_preview_id,
            }

        diff_check = self._run_git(["diff", "--check"])
        if diff_check["code"] != 0:
            return {
                "ok": False,
                "action": "commit",
                "error_code": "DIFF_CHECK_FAILED",
                "message": self._git_error_message(diff_check, "git diff --check 失败。"),
                "preview_id": normalized_preview_id,
            }

        add_result = self._run_git(["add", "--", *current_files])
        if add_result["code"] != 0:
            return {
                "ok": False,
                "action": "commit",
                "error_code": "GIT_ADD_FAILED",
                "message": self._git_error_message(add_result, "git add 失败。"),
                "preview_id": normalized_preview_id,
            }

        commit_result = self._run_git(["commit", "-m", commit_message])
        if commit_result["code"] != 0:
            return {
                "ok": False,
                "action": "commit",
                "error_code": "GIT_COMMIT_FAILED",
                "message": self._git_error_message(commit_result, "git commit 失败。"),
                "preview_id": normalized_preview_id,
            }

        head_after_result = self._run_git(["log", "-1", "--pretty=%H"])
        if head_after_result["code"] != 0:
            return {
                "ok": False,
                "action": "commit",
                "error_code": "COMMIT_HASH_READ_FAILED",
                "message": self._git_error_message(head_after_result, "读取 commit hash 失败。"),
                "preview_id": normalized_preview_id,
            }
        current_head_after = head_after_result["stdout"].strip()

        status_after_result = self._run_git(["status", "--short"])
        git_status_after = status_after_result["stdout"].splitlines() if status_after_result["code"] == 0 else []
        status_after_clean = [
            line for line in git_status_after
            if line.strip() and not self._is_ignorable_runner_status_line(line)
        ]

        verify_clean = len(status_after_clean) == 0
        verify_status_short_raw: list[str] = list(status_after_clean)
        verify_status_short: list[str] = [line.strip() for line in verify_status_short_raw]
        verify_blockers: list[str] = []
        remaining_uncommitted_files = self._extract_paths_from_status_lines(verify_status_short_raw)

        preview["committed_at"] = datetime.now(timezone.utc).isoformat()
        preview["commit_hash"] = current_head_after
        self._write_json(preview_file, preview)

        preview_version = preview.get("version")
        if not isinstance(preview_version, str) or not preview_version.strip():
            preview_version = None
        warnings: list[str] = []
        direct_version_reconcile: dict[str, Any] | None = None
        if preview_version:
            state_update = _best_effort_commit_state_update(
                self.project_root,
                current_head_after,
                commit_message,
                current_files,
                version=preview_version,
            )
        else:
            reconcile_inspect = GitHistoryReconcileScanner(self.project_root).inspect_commit_message(
                current_head_after,
                commit_message,
            )
            if reconcile_inspect.get("has_version_marker") and reconcile_inspect.get("has_unreconciled_candidate"):
                selected = reconcile_inspect.get("selected_candidate")
                selected_version = None
                if isinstance(selected, dict):
                    selected_version = selected.get("version")
                state_update = {
                    "ok": True,
                    "skipped": True,
                    "reason": "unreconciled_direct_version_candidate",
                    "matched_version_source": "none",
                    "version": None,
                }
                warnings.append("本次 commit message 命中未纳入 Runner lineage 的版本号，已保留为 direct Git candidate。")
                if reconcile_inspect.get("ambiguous"):
                    warnings.append("commit message 含多个版本号，候选需要人工确认。")
                direct_version_reconcile = {
                    "has_unreconciled_candidate": True,
                    "detected_versions": reconcile_inspect.get("detected_versions", []),
                    "ambiguous": bool(reconcile_inspect.get("ambiguous")),
                    "selected_candidate": selected,
                    "recommended_next_action": {
                        "tool": "run_mcp_workflow",
                        "action": "manual_git_history_review_required",
                        "params": {"workflow": "project_status", "phase": "inspect"},
                    },
                }
                if selected_version:
                    direct_version_reconcile["selected_version"] = selected_version
            else:
                state_update = _best_effort_commit_state_update(
                    self.project_root,
                    current_head_after,
                    commit_message,
                    current_files,
                    version=None,
                )

        result = {
            "ok": True,
            "action": "commit",
            "preview_id": normalized_preview_id,
            "commit_hash": current_head_after,
            "commit_hash_short": current_head_after[:8],
            "message": commit_message,
            "committed_files": current_files,
            "commit_state_update": state_update,
            "git_status_after": git_status_after,
            "current_head_before": current_head_before,
            "current_head_after": current_head_after,
            "initial_commit": preview_initial_commit,
            "verify_clean": verify_clean,
            "verify_status_short": verify_status_short,
            "verify_blockers": verify_blockers,
            "verify_summary": {
                "remaining_status_short": verify_status_short,
                "remaining_uncommitted_files": remaining_uncommitted_files,
                "one_line": "工作区已清理，提交完成。" if verify_clean else "提交后工作区仍有未跟踪或未提交的文件。",
            },
            "remaining_status_short": verify_status_short,
            "remaining_uncommitted_files": remaining_uncommitted_files,
        }
        if warnings:
            result["warnings"] = warnings
        if direct_version_reconcile is not None:
            result["direct_version_reconcile"] = direct_version_reconcile
            result["recommended_next_action"] = direct_version_reconcile.get("recommended_next_action")
        return result

    def _parse_status_line(self, line: str) -> dict[str, Any] | None:
        if len(line) < 3:
            return None
        status = line[:2]
        raw_path = line[3:].strip() if len(line) > 3 else ""
        if not raw_path:
            return None

        if status == "??":
            rel_path = self._normalize_rel_path(raw_path)
            return {
                "status": status,
                "path": rel_path,
                "unsupported": rel_path is None,
            }

        if status == "!!":
            rel_path = self._normalize_rel_path(raw_path)
            return {
                "status": status,
                "path": rel_path,
                "unsupported": False,
            }

        if "->" in raw_path:
            return {
                "status": status,
                "path": raw_path,
                "unsupported": True,
            }

        if any(ch in status for ch in ("U", "T")):
            return {
                "status": status,
                "path": raw_path,
                "unsupported": True,
            }

        rel_path = self._normalize_rel_path(raw_path)
        return {
            "status": status,
            "path": rel_path,
            "unsupported": rel_path is None,
        }

    def _classify_path(self, rel_path: str) -> dict[str, bool]:
        norm = rel_path.replace("\\", "/")
        if self.path_policy.is_commit_blocked_path(norm):
            return {"safe": False, "excluded": False, "blocked": True}
        if self.path_policy.is_commit_excluded_path(norm):
            return {"safe": True, "excluded": True, "blocked": False}

        if not self._is_path_within_project(norm):
            return {"safe": False, "excluded": False, "blocked": True}

        abs_path = os.path.join(self.project_root, norm)
        if os.path.exists(abs_path):
            real_path = os.path.realpath(abs_path)
            if not self._is_under_root(real_path):
                return {"safe": False, "excluded": False, "blocked": True}
            if os.path.isdir(abs_path):
                return {"safe": True, "excluded": True, "blocked": False}

        if not self.path_policy.is_commit_allowed_path(norm):
            if is_allowed_by_current_plan(
                self.project_root,
                norm,
                deny_predicate=self._is_commit_denied_path,
            ):
                return {"safe": True, "excluded": False, "blocked": False}
            return {"safe": True, "excluded": True, "blocked": False}

        return {"safe": True, "excluded": False, "blocked": False}

    def _is_tracked_deletion(self, status: str) -> bool:
        return "D" in status and not status.startswith("??") and not status.startswith("!!")

    def _is_commit_denied_path(self, rel_path: str) -> bool:
        norm = rel_path.replace("\\", "/")
        return (
            self.path_policy.is_commit_blocked_path(norm)
            or self.path_policy.is_commit_excluded_path(norm)
        )

    def _expand_untracked_directory(self, dir_path: str) -> list[str]:
        norm_dir = dir_path.replace("\\", "/")
        abs_dir = os.path.join(self.project_root, norm_dir)
        if not os.path.isdir(abs_dir):
            return []

        expanded: list[str] = []
        for current_dir, dir_names, file_names in os.walk(abs_dir):
            safe_dirs: list[str] = []
            for d in sorted(dir_names):
                if d.startswith(".") and d not in project_runner_dirnames():
                    continue
                full_dir = os.path.join(current_dir, d)
                try:
                    rel_dir = os.path.relpath(full_dir, self.project_root).replace("\\", "/")
                except ValueError:
                    continue
                probe_path = f"{rel_dir}/__probe__"
                if self.path_policy.is_commit_blocked_path(probe_path):
                    continue
                if self.path_policy.is_commit_excluded_path(probe_path):
                    continue
                safe_dirs.append(d)
            dir_names[:] = safe_dirs

            for file_name in sorted(file_names):
                full_path = os.path.join(current_dir, file_name)
                try:
                    rel_path = os.path.relpath(full_path, self.project_root)
                except ValueError:
                    continue
                norm_path = rel_path.replace("\\", "/")
                classify = self._classify_path(norm_path)
                if classify["blocked"] or classify["excluded"] or not classify["safe"]:
                    continue

                if norm_path not in expanded:
                    expanded.append(norm_path)

        return expanded

    def _matches_any(self, path: str, patterns: list[str]) -> bool:
        return any(self._match_pattern(path, pattern) for pattern in patterns)

    def _match_pattern(self, path: str, pattern: str) -> bool:
        return self.path_policy.match_pattern(path, pattern)

    def _normalize_rel_path(self, path: str) -> str | None:
        candidate = path.strip().replace("\\", "/")
        if not candidate:
            return None
        if os.path.isabs(candidate):
            return None
        norm = os.path.normpath(candidate).replace("\\", "/")
        if norm in (".", ""):
            return None
        if norm.startswith("../") or norm == "..":
            return None
        parts = Path(norm).parts
        if any(part == ".." for part in parts):
            return None
        return norm

    def _is_path_within_project(self, rel_path: str) -> bool:
        abs_path = os.path.realpath(os.path.join(self.project_root, rel_path))
        return self._is_under_root(abs_path)

    def _is_under_root(self, abs_path: str) -> bool:
        root = self.project_root_real
        return abs_path == root or abs_path.startswith(root + os.sep)

    def _build_file_signatures(self, files_to_commit: list[str]) -> dict[str, str]:
        signatures: dict[str, str] = {}
        for rel_path in sorted(files_to_commit):
            abs_path = os.path.join(self.project_root, rel_path)
            if not os.path.exists(abs_path):
                signatures[rel_path] = "missing"
                continue
            if not os.path.isfile(abs_path):
                signatures[rel_path] = "invalid"
                continue
            sha = hashlib.sha256()
            with open(abs_path, "rb") as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    sha.update(chunk)
            signatures[rel_path] = f"file:{sha.hexdigest()}"
        return signatures

    def _build_diff_hash(
        self,
        *,
        current_head: str | None,
        status_short: list[str],
        files_to_commit: list[str],
        file_signatures: dict[str, str],
    ) -> str:
        payload = {
            "head": current_head,
            "status_short": status_short,
            "files_to_commit": sorted(files_to_commit),
            "file_signatures": file_signatures,
        }
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _build_diff_summary(
        self,
        *,
        include_diff_summary: bool,
        max_diff_chars: int,
        selected_files: list[str],
        untracked_files: list[str],
        initial_commit: bool = False,
    ) -> tuple[str, bool]:
        if not include_diff_summary:
            return "", False

        selected_sorted = sorted(selected_files)
        if initial_commit:
            lines = [f"Initial commit will add {len(selected_sorted)} files"]
            if selected_sorted:
                lines.append("")
                lines.extend(f"- {path}" for path in selected_sorted)
            diff_text = "\n".join(lines) + "\n"
        else:
            selected_set = set(selected_files)
            tracked_selected_files = [path for path in selected_sorted if path not in set(untracked_files)]
            if tracked_selected_files:
                diff_res = self._run_git(["diff", "--", *tracked_selected_files])
            else:
                diff_res = {"code": 0, "stdout": "", "stderr": ""}
            diff_text = diff_res["stdout"] if diff_res["code"] == 0 else ""
            selected_untracked_files = [path for path in sorted(untracked_files) if path in selected_set]
            if selected_untracked_files:
                suffix = "\n\n# Untracked files\n" + "\n".join(selected_untracked_files) + "\n"
                diff_text = diff_text + suffix
        if len(diff_text) > max_diff_chars:
            return diff_text[:max_diff_chars], True
        return diff_text, False

    def _normalize_file_selection_list(
        self,
        values: Any,
        *,
        action: str,
        field_name: str,
    ) -> tuple[list[str] | None, dict[str, Any] | None]:
        if values is None:
            return None, None
        if not isinstance(values, list):
            return None, {
                "ok": False,
                "action": action,
                "error_code": "INVALID_FILE_SELECTION",
                "message": f"{field_name} 必须是字符串数组。",
            }
        normalized: list[str] = []
        seen: set[str] = set()
        for item in values:
            if not isinstance(item, str):
                return None, {
                    "ok": False,
                    "action": action,
                    "error_code": "INVALID_FILE_SELECTION",
                    "message": f"{field_name} 必须是字符串数组。",
                }
            rel_path = self._normalize_rel_path(item)
            if rel_path is None:
                return None, {
                    "ok": False,
                    "action": action,
                    "error_code": "INVALID_FILE_SELECTION",
                    "message": f"{field_name} 包含非法路径。",
                    "invalid_files": [str(item)],
                }
            if rel_path in seen:
                return None, {
                    "ok": False,
                    "action": action,
                    "error_code": "INVALID_FILE_SELECTION",
                    "message": f"{field_name} 包含重复路径。",
                    "invalid_files": [rel_path],
                }
            seen.add(rel_path)
            normalized.append(rel_path)
        return normalized, None

    def _select_files_for_commit(
        self,
        *,
        available_files_to_commit: list[str],
        blocked_files: list[str],
        excluded_files: list[str],
        unsupported_status_entries: list[str],
        include_files: list[str] | None,
        exclude_files: list[str] | None,
        action: str,
    ) -> tuple[list[str], dict[str, Any] | None, dict[str, Any] | None]:
        available_sorted = sorted(available_files_to_commit)
        available_set = set(available_sorted)
        if include_files is None:
            selected = list(available_sorted)
        else:
            invalid_includes = [path for path in include_files if path not in available_set]
            if invalid_includes:
                return [], None, {
                    "ok": False,
                    "action": action,
                    "error_code": "FILE_NOT_COMMITTABLE",
                    "message": "Selected file is not in readiness.files_to_commit.",
                    "invalid_files": sorted(invalid_includes),
                }
            selected = [path for path in include_files if path in available_set]
        if exclude_files is not None:
            ignored_exclude_files = sorted(path for path in exclude_files if path not in available_set)
            exclude_set = set(exclude_files) & available_set
            selected = [path for path in selected if path not in exclude_set]
        else:
            ignored_exclude_files = []

        blocked_set = set(blocked_files)
        excluded_set = set(excluded_files)
        invalid_selected = [path for path in selected if path in blocked_set or path in excluded_set]
        if invalid_selected:
            invalid_files = sorted(set(invalid_selected))
            return [], None, {
                "ok": False,
                "action": action,
                "error_code": "FILE_NOT_COMMITTABLE",
                "message": "Selected file is not in readiness.files_to_commit.",
                "invalid_files": invalid_files,
            }
        selected_sorted = sorted(selected)
        if not selected_sorted:
            if include_files is None and exclude_files is None:
                selection_meta = {
                    "include_files": [],
                    "exclude_files": [],
                    "ignored_exclude_files": [],
                    "selected_files": [],
                    "available_files": available_sorted,
                }
                return [], selection_meta, None
            return [], None, {
                "ok": False,
                "action": action,
                "error_code": "NO_FILES_TO_COMMIT",
                "message": "没有可提交文件。",
            }
        selection_meta = {
            "include_files": include_files or [],
            "exclude_files": exclude_files or [],
            "ignored_exclude_files": ignored_exclude_files,
            "selected_files": selected_sorted,
            "available_files": available_sorted,
        }
        return selected_sorted, selection_meta, None

    def _build_selected_status_short(
        self,
        *,
        status_lines: list[str],
        selected_files: list[str],
        untracked_files: list[str],
    ) -> list[str]:
        selected_set = set(selected_files)
        selected_untracked_set = set(untracked_files) & selected_set
        selected_status_lines: list[str] = []
        matched_paths: set[str] = set()
        for line in status_lines:
            parsed = self._parse_status_line(line)
            if parsed is None:
                continue
            rel_path = parsed.get("path")
            if not isinstance(rel_path, str):
                continue
            if rel_path in selected_set:
                selected_status_lines.append(line.strip())
                matched_paths.add(rel_path)
        for rel_path in sorted(selected_untracked_set - matched_paths):
            selected_status_lines.append(f"?? {rel_path}")
        return selected_status_lines

    def _extract_paths_from_status_lines(self, status_lines: list[str]) -> list[str]:
        paths: list[str] = []
        seen: set[str] = set()
        for line in status_lines:
            parsed = self._parse_status_line(line)
            if parsed is None:
                continue
            rel_path = parsed.get("path")
            if not isinstance(rel_path, str):
                continue
            if rel_path in seen:
                continue
            seen.add(rel_path)
            paths.append(rel_path)
        return sorted(paths)

    def _is_ignorable_runner_status_line(self, line: str) -> bool:
        parsed = self._parse_status_line(line)
        rel_path = parsed.get("path") if isinstance(parsed, dict) else None
        if not isinstance(rel_path, str):
            return False
        normalized = rel_path.replace("\\", "/").rstrip("/")
        category = classify_runner_path(normalized).get("category")
        if category in {"project_local", "runtime_ephemeral", "archive_private_or_exportable"}:
            return True
        if normalized not in project_runner_dirnames():
            return False
        root = os.path.join(self.project_root, normalized)
        if not os.path.isdir(root):
            return False
        for current_root, _dirs, files in os.walk(root):
            for filename in files:
                child = os.path.relpath(os.path.join(current_root, filename), self.project_root)
                child_category = classify_runner_path(child).get("category")
                if child_category not in {
                    "project_local",
                    "runtime_ephemeral",
                    "archive_private_or_exportable",
                }:
                    return False
        return True

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

    def _is_under_preview_dir(self, path: str) -> bool:
        preview_dir_real = os.path.realpath(self.preview_dir)
        return path == preview_dir_real or path.startswith(preview_dir_real + os.sep)

    def _preview_file_path(self, preview_id: str) -> str:
        normalized = self._normalize_preview_id(preview_id)
        if normalized is None:
            raise ValueError("invalid preview id")
        preview_dir_real = os.path.realpath(self.preview_dir)
        preview_file = os.path.realpath(os.path.join(preview_dir_real, f"{normalized}.json"))
        if not self._is_under_preview_dir(preview_file):
            raise ValueError("preview path escapes preview directory")
        return preview_file

    def _read_json(self, path: str) -> dict[str, Any] | None:
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

    def _run_git(self, args: list[str]) -> dict[str, Any]:
        rc, stdout, stderr = _run_git_base(args, self.project_root, timeout=60)
        return {"code": rc, "stdout": stdout, "stderr": stderr}

    def _git_error_message(self, result: dict[str, Any], fallback: str) -> str:
        stderr = str(result.get("stderr") or "").strip()
        stdout = str(result.get("stdout") or "").strip()
        message = stderr or stdout
        if not message:
            return fallback
        return message[:400]
