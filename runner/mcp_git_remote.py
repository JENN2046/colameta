import hashlib
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from runner.runner_data_layout import classify_runner_path
from runner.runner_paths import (
    is_project_runner_subpath,
    project_runner_dirnames,
    resolve_project_runner_path,
)

class MCPGitRemoteManager:
    _PREVIEW_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]+")
    _REMOTE_URL_CREDENTIALS_PATTERN = re.compile(r"(?i)^(?P<scheme>[a-z][a-z0-9+.-]*://)(?P<userinfo>[^/@\s]+@)(?P<rest>.+)$")
    _REMOTE_URL_AUTH_PATTERN = re.compile(r"(?i)^(?P<scheme>[a-z][a-z0-9+.-]*://)(?P<userinfo>[^/@\s]+:[^/@\s]*@)(?P<rest>.+)$")

    def __init__(self, project_root: str):
        self.project_root = os.path.abspath(os.path.expanduser(project_root))
        self.preview_dir = resolve_project_runner_path(self.project_root, "runtime", "git-remote-previews")
        self.preview_ttl_seconds = 1800

    def push_status(self) -> dict[str, Any]:
        state = self._collect_push_state()
        if not state.get("ok"):
            return state

        blockers = self._build_status_blockers(state)
        can_preview = len(blockers) == 0
        can_push = can_preview

        result = {
            "ok": True,
            "action": "push_status",
            "project_root": self.project_root,
            "branch": state.get("branch"),
            "head": state.get("head"),
            "head_short": state.get("head_short"),
            "working_tree_clean": state.get("working_tree_clean"),
            "status_short": state.get("status_short", []),
            "status_short_hash": state.get("status_short_hash"),
            "blocking_working_tree_clean": state.get("blocking_working_tree_clean"),
            "blocking_tree_clean": state.get("blocking_working_tree_clean"),
            "blocking_git_status_short": state.get("blocking_git_status_short", []),
            "blocking_git_status_short_hash": state.get("blocking_git_status_short_hash"),
            "blocking_git_changed_files": state.get("blocking_git_changed_files", []),
            "ignored_runner_local_files": state.get("ignored_runner_local_files", []),
            "ignored_runner_runtime_files": state.get("ignored_runner_runtime_files", []),
            "ignored_runner_archive_files": state.get("ignored_runner_archive_files", []),
            "upstream": state.get("upstream"),
            "remote_name": state.get("remote_name"),
            "remote_url_redacted": state.get("remote_url_redacted"),
            "ahead": state.get("ahead"),
            "behind": state.get("behind"),
            "first_push_available": state.get("first_push_available", False),
            "first_push_remote": state.get("first_push_remote"),
            "first_push_target": state.get("first_push_target"),
            "remote_missing": state.get("remote_missing", False),
            "can_preview": can_preview,
            "can_push": can_push,
            "blockers": blockers,
            "warnings": state.get("warnings", []),
        }
        if state.get("commits") is not None:
            result["commits"] = state.get("commits")
        return result

    def push_preview(self, reason: str | None = None) -> dict[str, Any]:
        state = self._collect_push_state()
        if not state.get("ok"):
            return state

        blockers = self._build_status_blockers(state)
        if blockers:
            return self._push_not_ready(
                action="push_preview",
                blockers=blockers,
                state=state,
                error_code=blockers[0],
                message=self._blocker_message(blockers[0]),
            )

        if not state.get("upstream"):
            return self._build_first_push_preview(state, reason)

        commits = self._commits_to_push(state["upstream"])
        if commits is None:
            return self._push_error(
                action="push_preview",
                error_code="COMMITS_READ_FAILED",
                message="读取待推送提交失败。",
                state=state,
            )

        preview_id = self._generate_preview_id()
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=self.preview_ttl_seconds)
        preview_payload = {
            "action": "push_preview",
            "project_root": self.project_root,
            "preview_id": preview_id,
            "created_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
            "reason": reason.strip() if isinstance(reason, str) and reason.strip() else "",
            "push_mode": "upstream",
            "branch": state["branch"],
            "upstream": state["upstream"],
            "remote_name": state["remote_name"],
            "remote_url_redacted": state["remote_url_redacted"],
            "head": state["head"],
            "head_short": state["head_short"],
            "ahead": state["ahead"],
            "behind": state["behind"],
            "status_short": state.get("status_short", []),
            "status_short_hash": state.get("status_short_hash"),
            "blocking_git_status_short": state.get("blocking_git_status_short", []),
            "blocking_git_status_short_hash": state.get("blocking_git_status_short_hash"),
            "blocking_git_changed_files": state.get("blocking_git_changed_files", []),
            "ignored_runner_local_files": state.get("ignored_runner_local_files", []),
            "ignored_runner_runtime_files": state.get("ignored_runner_runtime_files", []),
            "ignored_runner_archive_files": state.get("ignored_runner_archive_files", []),
            "commits": commits,
            "can_apply": True,
            "blockers": [],
            "warnings": state.get("warnings", []),
        }
        preview_file = self._write_preview(preview_id, preview_payload)
        return {
            "ok": True,
            "action": "push_preview",
            "preview_id": preview_id,
            "project_root": self.project_root,
            "branch": state["branch"],
            "upstream": state["upstream"],
            "remote_name": state["remote_name"],
            "remote_url_redacted": state["remote_url_redacted"],
            "push_mode": "upstream",
            "head": state["head"],
            "head_short": state["head_short"],
            "ahead": state["ahead"],
            "behind": state["behind"],
            "status_short": state.get("status_short", []),
            "status_short_hash": state.get("status_short_hash"),
            "blocking_git_status_short": state.get("blocking_git_status_short", []),
            "blocking_git_status_short_hash": state.get("blocking_git_status_short_hash"),
            "blocking_git_changed_files": state.get("blocking_git_changed_files", []),
            "ignored_runner_local_files": state.get("ignored_runner_local_files", []),
            "ignored_runner_runtime_files": state.get("ignored_runner_runtime_files", []),
            "ignored_runner_archive_files": state.get("ignored_runner_archive_files", []),
            "commits": commits,
            "can_apply": True,
            "blockers": [],
            "warnings": state.get("warnings", []),
            "preview_file": os.path.relpath(preview_file, self.project_root).replace("\\", "/"),
            "expires_at": expires_at.isoformat(),
        }

    def push_apply(self, preview_id: str) -> dict[str, Any]:
        normalized_preview_id = self._validate_preview_id(preview_id)
        if normalized_preview_id is None:
            return self._push_error(
                action="push_apply",
                error_code="INVALID_PREVIEW_ID",
                message="preview_id 格式无效。",
            )

        preview = self._read_preview(normalized_preview_id)
        if preview is None:
            return self._push_error(
                action="push_apply",
                error_code="PREVIEW_NOT_FOUND",
                message="preview_id 对应的预览不存在。",
                preview_id=normalized_preview_id,
            )
        if not isinstance(preview, dict):
            return self._push_error(
                action="push_apply",
                error_code="PREVIEW_INVALID",
                message="预览文件格式无效。",
                preview_id=normalized_preview_id,
            )

        expires_at = self._parse_time(preview.get("expires_at"))
        if expires_at is None or expires_at <= datetime.now(timezone.utc):
            return self._push_error(
                action="push_apply",
                error_code="PREVIEW_EXPIRED",
                message="preview 已过期，请重新创建。",
                preview_id=normalized_preview_id,
            )

        if str(preview.get("action") or "") != "push_preview":
            return self._push_error(
                action="push_apply",
                error_code="PREVIEW_ACTION_INVALID",
                message="preview action 无效，不能 apply。",
                preview_id=normalized_preview_id,
            )

        preview_root = self._normalize_path(str(preview.get("project_root") or ""))
        if preview_root != self.project_root:
            return self._push_error(
                action="push_apply",
                error_code="PREVIEW_PROJECT_MISMATCH",
                message="preview 不属于当前项目。",
                preview_id=normalized_preview_id,
            )

        state = self._collect_push_state()
        if not state.get("ok"):
            return state

        if str(preview.get("push_mode") or "upstream") == "set_upstream":
            validation_error = self._validate_first_push_apply_state(preview, state)
            if validation_error is not None:
                return validation_error
            return self._apply_first_push(normalized_preview_id, preview, state)

        validation_error = self._validate_apply_state(preview, state)
        if validation_error is not None:
            return validation_error

        remote_name = str(preview.get("remote_name") or "")
        upstream_branch = self._parse_upstream_branch(str(preview.get("upstream") or ""))
        head_before = str(preview.get("head") or "")
        ahead_before = int(preview.get("ahead") or 0)
        behind_before = int(preview.get("behind") or 0)

        push_result = self._git(["push", remote_name, f"HEAD:{upstream_branch}"])
        if push_result["code"] != 0:
            return {
                "ok": False,
                "action": "push_apply",
                "error_code": "REMOTE_PUSH_FAILED",
                "message": "git push 执行失败。",
                "preview_id": normalized_preview_id,
                "branch": state.get("branch"),
                "upstream": state.get("upstream"),
                "head_before": head_before,
                "ahead_before": ahead_before,
                "behind_before": behind_before,
                "push_output_summary": self._shorten(self._redact_secret_text(self._merge_git_output(push_result)), 240),
            }

        status_after = self.push_status()
        head_after = status_after.get("head") if isinstance(status_after, dict) else None
        push_output_summary = self._shorten(self._redact_secret_text(self._merge_git_output(push_result)), 240)
        if not isinstance(status_after, dict):
            status_after = {
                "ok": False,
                "error_code": "PUSH_STATUS_AFTER_FAILED",
                "message": "读取推送后的状态失败。",
            }
        ahead_after = status_after.get("ahead") if isinstance(status_after, dict) else None
        behind_after = status_after.get("behind") if isinstance(status_after, dict) else None
        synced = bool(status_after.get("ok") and ahead_after == 0 and behind_after == 0) if isinstance(status_after, dict) else False

        return {
            "ok": True,
            "action": "push_apply",
            "pushed": True,
            "preview_id": normalized_preview_id,
            "branch": state.get("branch"),
            "upstream": state.get("upstream"),
            "head_before": head_before,
            "head_after": head_after,
            "ahead_before": ahead_before,
            "behind_before": behind_before,
            "ahead_after": ahead_after,
            "behind_after": behind_after,
            "synced": synced,
            "status_after": status_after,
            "push_output_summary": push_output_summary,
            "remote_name": remote_name,
            "remote_url_redacted": preview.get("remote_url_redacted"),
        }

    def _build_first_push_preview(self, state: dict[str, Any], reason: str | None = None) -> dict[str, Any]:
        commits = self._recent_head_commits()
        if commits is None:
            return self._push_error(
                action="push_preview",
                error_code="COMMITS_READ_FAILED",
                message="读取本地提交摘要失败。",
                state=state,
            )

        branch = str(state.get("branch") or "")
        remote_name = "origin"
        target_upstream = f"{remote_name}/{branch}"
        preview_id = self._generate_preview_id()
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=self.preview_ttl_seconds)
        preview_payload = {
            "action": "push_preview",
            "project_root": self.project_root,
            "preview_id": preview_id,
            "created_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
            "reason": reason.strip() if isinstance(reason, str) and reason.strip() else "",
            "push_mode": "set_upstream",
            "branch": branch,
            "upstream": None,
            "target_upstream": target_upstream,
            "remote_name": remote_name,
            "remote_url_redacted": state.get("remote_url_redacted"),
            "head": state.get("head"),
            "head_short": state.get("head_short"),
            "ahead": state.get("ahead"),
            "behind": state.get("behind"),
            "status_short": state.get("status_short", []),
            "status_short_hash": state.get("status_short_hash"),
            "blocking_git_status_short": state.get("blocking_git_status_short", []),
            "blocking_git_status_short_hash": state.get("blocking_git_status_short_hash"),
            "blocking_git_changed_files": state.get("blocking_git_changed_files", []),
            "ignored_runner_local_files": state.get("ignored_runner_local_files", []),
            "ignored_runner_runtime_files": state.get("ignored_runner_runtime_files", []),
            "ignored_runner_archive_files": state.get("ignored_runner_archive_files", []),
            "commits": commits,
            "command_summary": f"git push -u {remote_name} {branch}",
            "can_apply": True,
            "blockers": [],
            "warnings": state.get("warnings", []),
        }
        preview_file = self._write_preview(preview_id, preview_payload)
        return {
            "ok": True,
            "action": "push_preview",
            "preview_id": preview_id,
            "project_root": self.project_root,
            "push_mode": "set_upstream",
            "branch": branch,
            "upstream": None,
            "target_upstream": target_upstream,
            "remote_name": remote_name,
            "remote_url_redacted": state.get("remote_url_redacted"),
            "head": state.get("head"),
            "head_short": state.get("head_short"),
            "ahead": state.get("ahead"),
            "behind": state.get("behind"),
            "status_short": state.get("status_short", []),
            "status_short_hash": state.get("status_short_hash"),
            "blocking_git_status_short": state.get("blocking_git_status_short", []),
            "blocking_git_status_short_hash": state.get("blocking_git_status_short_hash"),
            "blocking_git_changed_files": state.get("blocking_git_changed_files", []),
            "ignored_runner_local_files": state.get("ignored_runner_local_files", []),
            "ignored_runner_runtime_files": state.get("ignored_runner_runtime_files", []),
            "ignored_runner_archive_files": state.get("ignored_runner_archive_files", []),
            "commits": commits,
            "command_summary": f"git push -u {remote_name} {branch}",
            "can_apply": True,
            "blockers": [],
            "warnings": state.get("warnings", []),
            "preview_file": os.path.relpath(preview_file, self.project_root).replace("\\", "/"),
            "expires_at": expires_at.isoformat(),
        }

    def _apply_first_push(self, preview_id: str, preview: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
        remote_name = str(preview.get("remote_name") or "")
        branch = str(preview.get("branch") or "")
        if remote_name != "origin" or not self._is_safe_git_arg(remote_name) or not self._is_safe_git_arg(branch):
            return self._push_error(
                action="push_apply",
                error_code="FIRST_PUSH_TARGET_INVALID",
                message="首次 push 目标无效。",
                preview_id=preview_id,
                preview=preview,
                state=state,
            )

        head_before = str(preview.get("head") or "")
        push_result = self._git(["push", "-u", remote_name, branch])
        push_output_summary = self._shorten(self._redact_secret_text(self._merge_git_output(push_result)), 240)
        if push_result["code"] != 0:
            return {
                "ok": False,
                "action": "push_apply",
                "error_code": "REMOTE_PUSH_FAILED",
                "message": "git push -u 执行失败。",
                "preview_id": preview_id,
                "push_mode": "set_upstream",
                "branch": state.get("branch"),
                "upstream": state.get("upstream"),
                "target_upstream": preview.get("target_upstream"),
                "head_before": head_before,
                "push_output_summary": push_output_summary,
            }

        status_after = self.push_status()
        head_after = status_after.get("head") if isinstance(status_after, dict) else None
        ahead_after = status_after.get("ahead") if isinstance(status_after, dict) else None
        behind_after = status_after.get("behind") if isinstance(status_after, dict) else None
        synced = bool(status_after.get("ok") and ahead_after == 0 and behind_after == 0) if isinstance(status_after, dict) else False
        return {
            "ok": True,
            "action": "push_apply",
            "pushed": True,
            "preview_id": preview_id,
            "push_mode": "set_upstream",
            "branch": branch,
            "upstream": preview.get("target_upstream"),
            "target_upstream": preview.get("target_upstream"),
            "head_before": head_before,
            "head_after": head_after,
            "ahead_before": preview.get("ahead"),
            "behind_before": preview.get("behind"),
            "ahead_after": ahead_after,
            "behind_after": behind_after,
            "synced": synced,
            "status_after": status_after,
            "push_output_summary": push_output_summary,
            "remote_name": remote_name,
            "remote_url_redacted": preview.get("remote_url_redacted"),
            "command_summary": f"git push -u {remote_name} {branch}",
        }

    def fetch_preview(self, reason: str | None = None) -> dict[str, Any]:
        state = self._collect_remote_state(action="fetch_preview", include_dirty_warning=True)
        if not state.get("ok"):
            return state

        blockers = self._build_fetch_blockers(state)
        can_apply = len(blockers) == 0

        preview_id = self._generate_preview_id()
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=self.preview_ttl_seconds)
        preview_payload = {
            "action": "fetch_preview",
            "project_root": self.project_root,
            "preview_id": preview_id,
            "created_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
            "reason": reason.strip() if isinstance(reason, str) and reason.strip() else "",
            "branch": state.get("branch"),
            "upstream": state.get("upstream"),
            "remote_name": state.get("remote_name"),
            "upstream_branch": state.get("upstream_branch"),
            "remote_url_redacted": state.get("remote_url_redacted"),
            "head": state.get("head"),
            "head_short": state.get("head_short"),
            "status_short": state.get("status_short", []),
            "status_short_hash": state.get("status_short_hash"),
            "warnings": state.get("warnings", []),
            "blockers": blockers,
            "can_apply": can_apply,
        }
        preview_file = self._write_preview(preview_id, preview_payload)
        return {
            "ok": True,
            "action": "fetch_preview",
            "preview_id": preview_id,
            "project_root": self.project_root,
            "can_apply": can_apply,
            "branch": state.get("branch"),
            "upstream": state.get("upstream"),
            "remote_name": state.get("remote_name"),
            "upstream_branch": state.get("upstream_branch"),
            "remote_url_redacted": state.get("remote_url_redacted"),
            "head": state.get("head"),
            "head_short": state.get("head_short"),
            "status_short": state.get("status_short", []),
            "status_short_hash": state.get("status_short_hash"),
            "warnings": state.get("warnings", []),
            "blockers": blockers,
            "preview_file": os.path.relpath(preview_file, self.project_root).replace("\\", "/"),
            "expires_at": expires_at.isoformat(),
        }

    def fetch_apply(self, preview_id: str) -> dict[str, Any]:
        preview, error = self._read_apply_preview(
            action="fetch_apply",
            expected_preview_action="fetch_preview",
            preview_id=preview_id,
        )
        if error is not None:
            return error
        if preview is None:
            return self._push_error(
                action="fetch_apply",
                error_code="PREVIEW_INVALID",
                message="预览文件格式无效。",
            )

        if preview.get("can_apply") is not True or preview.get("blockers"):
            return self._push_error(
                action="fetch_apply",
                error_code="PREVIEW_NOT_APPLICABLE",
                message="preview 当前不可 apply，请重新创建。",
                preview_id=preview.get("preview_id"),
                preview=preview,
            )

        state = self._collect_remote_state(action="fetch_apply", include_dirty_warning=True)
        if not state.get("ok"):
            return state

        validation_error = self._validate_fetch_apply_state(preview, state)
        if validation_error is not None:
            return validation_error

        remote_name = str(preview.get("remote_name") or "")
        upstream_branch = str(preview.get("upstream_branch") or "")
        head_before = str(preview.get("head") or "")

        fetch_result = self._git(["fetch", remote_name, upstream_branch])
        fetch_output_summary = self._shorten(self._redact_secret_text(self._merge_git_output(fetch_result)), 240)
        if fetch_result["code"] != 0:
            return {
                "ok": False,
                "action": "fetch_apply",
                "error_code": "REMOTE_FETCH_FAILED",
                "message": "git fetch 执行失败。",
                "preview_id": preview.get("preview_id"),
                "branch": state.get("branch"),
                "upstream": state.get("upstream"),
                "remote_name": remote_name,
                "upstream_branch": upstream_branch,
                "head_before": head_before,
                "fetch_output_summary": fetch_output_summary,
            }

        status_after = self.pull_status()
        head_after = status_after.get("head") if isinstance(status_after, dict) else None
        ahead_after = status_after.get("ahead") if isinstance(status_after, dict) else None
        behind_after = status_after.get("behind") if isinstance(status_after, dict) else None

        return {
            "ok": True,
            "action": "fetch_apply",
            "fetched": True,
            "preview_id": preview.get("preview_id"),
            "branch": state.get("branch"),
            "upstream": state.get("upstream"),
            "remote_name": remote_name,
            "upstream_branch": upstream_branch,
            "head_before": head_before,
            "head_after": head_after,
            "ahead_after": ahead_after,
            "behind_after": behind_after,
            "status_after": status_after,
            "fetch_output_summary": fetch_output_summary,
        }

    def pull_status(self) -> dict[str, Any]:
        state = self._collect_remote_state(action="pull_status")
        if not state.get("ok"):
            return state

        blockers = self._build_pull_blockers(state)
        can_preview = len(blockers) == 0
        can_pull = can_preview
        warnings = self._with_tracking_ref_warning(state.get("warnings", []))

        return {
            "ok": True,
            "action": "pull_status",
            "project_root": self.project_root,
            "branch": state.get("branch"),
            "head": state.get("head"),
            "head_short": state.get("head_short"),
            "working_tree_clean": state.get("working_tree_clean"),
            "status_short": state.get("status_short", []),
            "status_short_hash": state.get("status_short_hash"),
            "upstream": state.get("upstream"),
            "remote_name": state.get("remote_name"),
            "remote_url_redacted": state.get("remote_url_redacted"),
            "ahead": state.get("ahead"),
            "behind": state.get("behind"),
            "can_preview": can_preview,
            "can_pull": can_pull,
            "blockers": blockers,
            "warnings": warnings,
        }

    def pull_preview(self, reason: str | None = None) -> dict[str, Any]:
        state = self._collect_remote_state(action="pull_preview")
        if not state.get("ok"):
            return state

        blockers = self._build_pull_blockers(state)
        warnings = self._with_tracking_ref_warning(state.get("warnings", []))
        if blockers:
            result = self._push_not_ready(
                action="pull_preview",
                blockers=blockers,
                state=state,
                error_code=blockers[0],
                message=self._blocker_message(blockers[0]),
            )
            result["can_apply"] = False
            result["warnings"] = warnings
            return result

        upstream_head = self._current_upstream_head()
        if upstream_head is None:
            return self._push_error(
                action="pull_preview",
                error_code="UPSTREAM_HEAD_MISSING",
                message="读取 upstream HEAD 失败。",
                state=state,
            )

        commits = self._commits_to_pull(str(state.get("upstream") or ""))
        if commits is None:
            return self._push_error(
                action="pull_preview",
                error_code="COMMITS_READ_FAILED",
                message="读取待拉取提交失败。",
                state=state,
            )

        preview_id = self._generate_preview_id()
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=self.preview_ttl_seconds)
        preview_payload = {
            "action": "pull_preview",
            "project_root": self.project_root,
            "preview_id": preview_id,
            "created_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
            "reason": reason.strip() if isinstance(reason, str) and reason.strip() else "",
            "branch": state.get("branch"),
            "upstream": state.get("upstream"),
            "remote_name": state.get("remote_name"),
            "upstream_branch": state.get("upstream_branch"),
            "remote_url_redacted": state.get("remote_url_redacted"),
            "head": state.get("head"),
            "head_short": state.get("head_short"),
            "upstream_head": upstream_head,
            "upstream_head_short": upstream_head[:7],
            "ahead": state.get("ahead"),
            "behind": state.get("behind"),
            "status_short": state.get("status_short", []),
            "status_short_hash": state.get("status_short_hash"),
            "commits": commits,
            "can_apply": True,
            "blockers": [],
            "warnings": warnings,
        }
        preview_file = self._write_preview(preview_id, preview_payload)
        return {
            "ok": True,
            "action": "pull_preview",
            "preview_id": preview_id,
            "project_root": self.project_root,
            "can_apply": True,
            "branch": state.get("branch"),
            "upstream": state.get("upstream"),
            "head": state.get("head"),
            "head_short": state.get("head_short"),
            "upstream_head": upstream_head,
            "upstream_head_short": upstream_head[:7],
            "ahead": state.get("ahead"),
            "behind": state.get("behind"),
            "commits": commits,
            "warnings": warnings,
            "blockers": [],
            "preview_file": os.path.relpath(preview_file, self.project_root).replace("\\", "/"),
            "expires_at": expires_at.isoformat(),
        }

    def pull_apply(self, preview_id: str) -> dict[str, Any]:
        preview, error = self._read_apply_preview(
            action="pull_apply",
            expected_preview_action="pull_preview",
            preview_id=preview_id,
        )
        if error is not None:
            return error
        if preview is None:
            return self._push_error(
                action="pull_apply",
                error_code="PREVIEW_INVALID",
                message="预览文件格式无效。",
            )

        if preview.get("can_apply") is not True or preview.get("blockers"):
            return self._push_error(
                action="pull_apply",
                error_code="PREVIEW_NOT_APPLICABLE",
                message="preview 当前不可 apply，请重新创建。",
                preview_id=preview.get("preview_id"),
                preview=preview,
            )

        state = self._collect_remote_state(action="pull_apply")
        if not state.get("ok"):
            return state

        validation_error = self._validate_pull_apply_state(preview, state)
        if validation_error is not None:
            return validation_error

        head_before = str(preview.get("head") or "")
        upstream_head = str(preview.get("upstream_head") or "")
        ahead_before = int(preview.get("ahead") or 0)
        behind_before = int(preview.get("behind") or 0)

        merge_result = self._git(["merge", "--ff-only", "@{u}"])
        merge_output_summary = self._shorten(self._redact_secret_text(self._merge_git_output(merge_result)), 240)
        if merge_result["code"] != 0:
            return {
                "ok": False,
                "action": "pull_apply",
                "error_code": "FAST_FORWARD_MERGE_FAILED",
                "message": "git merge --ff-only 执行失败。",
                "preview_id": preview.get("preview_id"),
                "branch": state.get("branch"),
                "upstream": state.get("upstream"),
                "head_before": head_before,
                "upstream_head": upstream_head,
                "ahead_before": ahead_before,
                "behind_before": behind_before,
                "merge_output_summary": merge_output_summary,
            }

        status_after = self.pull_status()
        head_after = status_after.get("head") if isinstance(status_after, dict) else None
        return {
            "ok": True,
            "action": "pull_apply",
            "pulled": True,
            "preview_id": preview.get("preview_id"),
            "branch": state.get("branch"),
            "upstream": state.get("upstream"),
            "head_before": head_before,
            "head_after": head_after,
            "upstream_head": upstream_head,
            "ahead_before": ahead_before,
            "behind_before": behind_before,
            "status_after": status_after,
            "merge_output_summary": merge_output_summary,
        }

    def _collect_push_state(self) -> dict[str, Any]:
        return self._collect_remote_state(action="push_status", include_push_commits=True)

    def _collect_remote_state(
        self,
        *,
        action: str,
        include_dirty_warning: bool = False,
        include_push_commits: bool = False,
    ) -> dict[str, Any]:
        repo_check = self._git(["rev-parse", "--is-inside-work-tree"])
        if repo_check["code"] != 0:
            return self._push_error(
                action=action,
                error_code="NOT_GIT_REPOSITORY",
                message=self._git_error_message(repo_check, "当前目录不是 Git 仓库。"),
            )

        branch_res = self._git(["rev-parse", "--abbrev-ref", "HEAD"])
        if branch_res["code"] != 0:
            return self._push_error(
                action=action,
                error_code="BRANCH_READ_FAILED",
                message=self._git_error_message(branch_res, "读取当前分支失败。"),
            )
        branch = str(branch_res["stdout"] or "").strip()
        if not branch:
            return self._push_error(
                action=action,
                error_code="BRANCH_READ_FAILED",
                message="无法读取当前分支。",
            )
        detached_head = branch == "HEAD"

        head_res = self._git(["rev-parse", "HEAD"])
        head = None
        head_short = None
        if head_res["code"] == 0:
            candidate = str(head_res["stdout"] or "").strip()
            if candidate:
                head = candidate
                head_short = candidate[:7]

        status_short, status_res = self._git_status_short()
        if status_res["code"] != 0:
            return self._push_error(
                action=action,
                error_code="GIT_STATUS_FAILED",
                message=self._git_error_message(status_res, "读取 git status 失败。"),
            )
        status_short_hash = self._hash_lines(status_short)
        working_tree_clean = len(status_short) == 0
        dirty_context = self._classify_git_changed_files(status_short)
        blocking_git_status_short = dirty_context["blocking_status_short"]
        blocking_git_status_short_hash = self._hash_lines(blocking_git_status_short)
        blocking_working_tree_clean = len(blocking_git_status_short) == 0

        upstream_res = self._git(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"])
        upstream = None
        remote_name = None
        upstream_branch = None
        remote_url_redacted = None
        ahead = None
        behind = None
        commits: list[dict[str, str]] | None = None
        first_push_remote = None
        first_push_target = None
        first_push_available = False
        first_push_remote_branch_exists = None
        first_push_remote_check_failed = False
        remote_missing = False

        if upstream_res["code"] == 0:
            upstream_candidate = str(upstream_res["stdout"] or "").strip()
            if upstream_candidate:
                upstream = upstream_candidate
                remote_name = self._parse_remote_name(upstream_candidate)
                upstream_branch = self._parse_upstream_branch(upstream_candidate)
                if remote_name:
                    remote_url = self._remote_url(remote_name)
                    remote_url_redacted = self._redact_remote_url(remote_url)
                if head is not None:
                    ahead_behind_res = self._git(["rev-list", "--left-right", "--count", "HEAD...@{u}"])
                    if ahead_behind_res["code"] != 0:
                        return self._push_error(
                            action=action,
                            error_code="AHEAD_BEHIND_FAILED",
                            message=self._git_error_message(ahead_behind_res, "读取 ahead/behind 失败。"),
                        )
                    parsed = self._parse_counts(ahead_behind_res["stdout"])
                    if parsed is None:
                        return self._push_error(
                            action=action,
                            error_code="AHEAD_BEHIND_FAILED",
                            message="读取 ahead/behind 失败。",
                        )
                    ahead, behind = parsed
                    if include_push_commits:
                        commits = self._commits_to_push(upstream)
                        if commits is None:
                            return self._push_error(
                                action=action,
                                error_code="COMMITS_READ_FAILED",
                                message="读取待推送提交失败。",
                            )
        else:
            origin_url = self._remote_url("origin")
            if origin_url:
                remote_name = "origin"
                remote_url_redacted = self._redact_remote_url(origin_url)
                first_push_remote = "origin"
                first_push_target = f"origin/{branch}" if branch and branch != "HEAD" else None
                if head is not None and branch and branch != "HEAD" and self._is_safe_git_arg(branch):
                    remote_branch_exists = self._remote_branch_exists("origin", branch)
                    if remote_branch_exists is None:
                        first_push_remote_check_failed = True
                    else:
                        first_push_remote_branch_exists = remote_branch_exists
                        first_push_available = (
                            remote_branch_exists is False
                            and blocking_working_tree_clean
                        )
            else:
                remote_missing = True

        warnings: list[str] = []
        if detached_head:
            warnings.append("branch_detached")
        if head is None:
            warnings.append("head_missing")
        if upstream is None:
            warnings.append("upstream_missing")
        if include_dirty_warning and not working_tree_clean:
            warnings.append("working_tree_dirty")
        if dirty_context["ignored_runner_local_files"]:
            warnings.append("ignored_runner_local_files")
        if dirty_context["ignored_runner_runtime_files"]:
            warnings.append("ignored_runner_runtime_files")
        if dirty_context["ignored_runner_archive_files"]:
            warnings.append("ignored_runner_archive_files")

        return {
            "ok": True,
            "action": action,
            "project_root": self.project_root,
            "branch": branch,
            "head": head,
            "head_short": head_short,
            "working_tree_clean": working_tree_clean,
            "status_short": status_short,
            "status_short_hash": status_short_hash,
            "blocking_working_tree_clean": blocking_working_tree_clean,
            "blocking_tree_clean": blocking_working_tree_clean,
            "blocking_git_status_short": blocking_git_status_short,
            "blocking_git_status_short_hash": blocking_git_status_short_hash,
            "blocking_git_changed_files": dirty_context["blocking_files"],
            "runner_memory_files": dirty_context["runner_memory_files"],
            "ignored_runner_local_files": dirty_context["ignored_runner_local_files"],
            "ignored_runner_runtime_files": dirty_context["ignored_runner_runtime_files"],
            "ignored_runner_archive_files": dirty_context["ignored_runner_archive_files"],
            "upstream": upstream,
            "remote_name": remote_name,
            "upstream_branch": upstream_branch,
            "remote_url_redacted": remote_url_redacted,
            "ahead": ahead,
            "behind": behind,
            "commits": commits,
            "first_push_available": first_push_available,
            "first_push_remote": first_push_remote,
            "first_push_target": first_push_target,
            "first_push_remote_branch_exists": first_push_remote_branch_exists,
            "first_push_remote_check_failed": first_push_remote_check_failed,
            "remote_missing": remote_missing,
            "warnings": warnings,
        }

    def _build_status_blockers(self, state: dict[str, Any]) -> list[str]:
        blockers: list[str] = []
        if state.get("branch") == "HEAD":
            blockers.append("branch_detached")
        if not state.get("head"):
            blockers.append("head_missing")
        if state.get("blocking_working_tree_clean") is not True:
            blockers.append("working_tree_dirty")
        if not state.get("upstream"):
            if state.get("remote_missing"):
                blockers.append("remote_missing")
                blockers.append("upstream_missing")
            elif not state.get("remote_url_redacted"):
                blockers.append("remote_url_missing")
            elif not self._is_safe_git_arg(state.get("branch")):
                blockers.append("branch_invalid")
            elif state.get("first_push_remote_check_failed"):
                blockers.append("first_push_remote_check_failed")
            elif state.get("first_push_remote_branch_exists"):
                blockers.append("first_push_remote_branch_exists")
            elif state.get("first_push_available") is not True:
                blockers.append("upstream_missing")
        if state.get("upstream") and not state.get("remote_url_redacted"):
            blockers.append("remote_url_missing")
        behind = state.get("behind")
        if isinstance(behind, int) and behind > 0:
            blockers.append("branch_behind_upstream")
        ahead = state.get("ahead")
        if isinstance(ahead, int) and ahead == 0:
            blockers.append("nothing_to_push")
        return blockers

    def _build_fetch_blockers(self, state: dict[str, Any]) -> list[str]:
        blockers: list[str] = []
        if state.get("branch") == "HEAD":
            blockers.append("branch_detached")
        if not state.get("head"):
            blockers.append("head_missing")
        if not state.get("upstream"):
            blockers.append("upstream_missing")
        if state.get("upstream") and (
            not self._is_safe_git_arg(state.get("remote_name")) or not self._is_safe_git_arg(state.get("upstream_branch"))
        ):
            blockers.append("upstream_invalid")
        if state.get("upstream") and not state.get("remote_url_redacted"):
            blockers.append("remote_url_missing")
        return blockers

    def _build_pull_blockers(self, state: dict[str, Any]) -> list[str]:
        blockers: list[str] = []
        if state.get("branch") == "HEAD":
            blockers.append("branch_detached")
        if not state.get("head"):
            blockers.append("head_missing")
        if state.get("working_tree_clean") is not True:
            blockers.append("working_tree_dirty")
        if not state.get("upstream"):
            blockers.append("upstream_missing")
        if state.get("upstream") and (
            not self._is_safe_git_arg(state.get("remote_name")) or not self._is_safe_git_arg(state.get("upstream_branch"))
        ):
            blockers.append("upstream_invalid")
        if state.get("upstream") and not state.get("remote_url_redacted"):
            blockers.append("remote_url_missing")

        ahead = state.get("ahead")
        behind = state.get("behind")
        if isinstance(ahead, int) and isinstance(behind, int):
            if ahead > 0 and behind > 0:
                blockers.append("diverged_from_upstream")
            elif ahead > 0 and behind == 0:
                blockers.append("local_ahead")
            elif behind == 0:
                blockers.append("nothing_to_pull")
            elif behind > 0 and ahead == 0 and not self._is_head_ancestor_of_upstream():
                blockers.append("non_fast_forward")
        return blockers

    def _validate_first_push_apply_state(self, preview: dict[str, Any], state: dict[str, Any]) -> dict[str, Any] | None:
        if state.get("branch") != preview.get("branch"):
            return self._push_error(
                action="push_apply",
                error_code="BRANCH_CHANGED",
                message="当前分支已变化，请重新预览。",
                preview_id=preview.get("preview_id"),
                preview=preview,
                state=state,
            )
        if state.get("head") != preview.get("head"):
            return self._push_error(
                action="push_apply",
                error_code="PREVIEW_HEAD_CHANGED",
                message="当前 HEAD 已变化，请重新预览。",
                preview_id=preview.get("preview_id"),
                preview=preview,
                state=state,
            )
        if state.get("upstream") is not None:
            return self._push_error(
                action="push_apply",
                error_code="UPSTREAM_CHANGED",
                message="当前 upstream 已变化，请重新预览。",
                preview_id=preview.get("preview_id"),
                preview=preview,
                state=state,
            )
        if state.get("remote_name") != preview.get("remote_name") or state.get("remote_url_redacted") != preview.get("remote_url_redacted"):
            return self._push_error(
                action="push_apply",
                error_code="REMOTE_CHANGED",
                message="当前 origin remote 已变化，请重新预览。",
                preview_id=preview.get("preview_id"),
                preview=preview,
                state=state,
            )
        if state.get("blocking_git_status_short_hash") != preview.get("blocking_git_status_short_hash"):
            return self._push_error(
                action="push_apply",
                error_code="PREVIEW_STATUS_CHANGED",
                message="阻断性 Git 状态已变化，请重新预览。",
                preview_id=preview.get("preview_id"),
                preview=preview,
                state=state,
            )
        if state.get("blocking_working_tree_clean") is not True:
            return self._push_error(
                action="push_apply",
                error_code="WORKING_TREE_DIRTY",
                message="工作区存在阻断性改动，请重新预览。",
                preview_id=preview.get("preview_id"),
                preview=preview,
                state=state,
            )
        branch = str(preview.get("branch") or "")
        remote_name = str(preview.get("remote_name") or "")
        if remote_name != "origin" or not self._is_safe_git_arg(remote_name) or not self._is_safe_git_arg(branch):
            return self._push_error(
                action="push_apply",
                error_code="FIRST_PUSH_TARGET_INVALID",
                message="首次 push 目标无效。",
                preview_id=preview.get("preview_id"),
                preview=preview,
                state=state,
            )
        remote_branch_exists = self._remote_branch_exists(remote_name, branch)
        if remote_branch_exists is None:
            return self._push_error(
                action="push_apply",
                error_code="FIRST_PUSH_REMOTE_CHECK_FAILED",
                message="检查远端同名分支失败，请重新预览。",
                preview_id=preview.get("preview_id"),
                preview=preview,
                state=state,
            )
        if remote_branch_exists:
            return self._push_error(
                action="push_apply",
                error_code="FIRST_PUSH_REMOTE_BRANCH_EXISTS",
                message="远端同名分支已存在，当前工具不会自动关联以避免错误覆盖。",
                preview_id=preview.get("preview_id"),
                preview=preview,
                state=state,
            )
        return None

    def _validate_apply_state(self, preview: dict[str, Any], state: dict[str, Any]) -> dict[str, Any] | None:
        current_branch = state.get("branch")
        current_head = state.get("head")
        current_upstream = state.get("upstream")
        current_ahead = state.get("ahead")
        current_behind = state.get("behind")

        preview_branch = preview.get("branch")
        preview_head = preview.get("head")
        preview_upstream = preview.get("upstream")
        preview_ahead = preview.get("ahead")
        preview_behind = preview.get("behind")

        if current_branch != preview_branch:
            return self._push_error(
                action="push_apply",
                error_code="BRANCH_CHANGED",
                message="当前分支已变化，请重新预览。",
                preview_id=preview.get("preview_id"),
                preview=preview,
                state=state,
            )
        if current_head != preview_head:
            return self._push_error(
                action="push_apply",
                error_code="HEAD_CHANGED",
                message="当前 HEAD 已变化，请重新预览。",
                preview_id=preview.get("preview_id"),
                preview=preview,
                state=state,
            )
        if current_upstream != preview_upstream:
            return self._push_error(
                action="push_apply",
                error_code="UPSTREAM_CHANGED",
                message="当前 upstream 已变化，请重新预览。",
                preview_id=preview.get("preview_id"),
                preview=preview,
                state=state,
            )
        if state.get("blocking_working_tree_clean") is not True:
            return self._push_error(
                action="push_apply",
                error_code="WORKING_TREE_DIRTY",
                message="工作区已变脏，请重新预览。",
                preview_id=preview.get("preview_id"),
                preview=preview,
                state=state,
            )
        if current_behind != 0:
            return self._push_error(
                action="push_apply",
                error_code="BRANCH_BEHIND_UPSTREAM",
                message="当前分支已落后于 upstream，请重新预览。",
                preview_id=preview.get("preview_id"),
                preview=preview,
                state=state,
            )
        if current_ahead != preview_ahead or not isinstance(current_ahead, int) or current_ahead <= 0:
            return self._push_error(
                action="push_apply",
                error_code="AHEAD_COUNT_CHANGED",
                message="待推送提交数量已变化，请重新预览。",
                preview_id=preview.get("preview_id"),
                preview=preview,
                state=state,
            )
        if preview_behind != 0:
            return self._push_error(
                action="push_apply",
                error_code="BRANCH_BEHIND_UPSTREAM",
                message="preview 记录的 upstream 状态无效。",
                preview_id=preview.get("preview_id"),
                preview=preview,
                state=state,
            )
        return None

    def _validate_fetch_apply_state(self, preview: dict[str, Any], state: dict[str, Any]) -> dict[str, Any] | None:
        if state.get("branch") != preview.get("branch"):
            return self._push_error(
                action="fetch_apply",
                error_code="BRANCH_CHANGED",
                message="当前分支已变化，请重新预览。",
                preview_id=preview.get("preview_id"),
                preview=preview,
                state=state,
            )
        if state.get("head") != preview.get("head"):
            return self._push_error(
                action="fetch_apply",
                error_code="HEAD_CHANGED",
                message="当前 HEAD 已变化，请重新预览。",
                preview_id=preview.get("preview_id"),
                preview=preview,
                state=state,
            )
        if state.get("upstream") != preview.get("upstream"):
            return self._push_error(
                action="fetch_apply",
                error_code="UPSTREAM_CHANGED",
                message="当前 upstream 已变化，请重新预览。",
                preview_id=preview.get("preview_id"),
                preview=preview,
                state=state,
            )
        if state.get("remote_name") != preview.get("remote_name"):
            return self._push_error(
                action="fetch_apply",
                error_code="REMOTE_CHANGED",
                message="当前 remote 已变化，请重新预览。",
                preview_id=preview.get("preview_id"),
                preview=preview,
                state=state,
            )
        if state.get("upstream_branch") != preview.get("upstream_branch"):
            return self._push_error(
                action="fetch_apply",
                error_code="UPSTREAM_BRANCH_CHANGED",
                message="当前 upstream branch 已变化，请重新预览。",
                preview_id=preview.get("preview_id"),
                preview=preview,
                state=state,
            )
        if not self._is_safe_git_arg(state.get("remote_name")) or not self._is_safe_git_arg(state.get("upstream_branch")):
            return self._push_error(
                action="fetch_apply",
                error_code="UPSTREAM_INVALID",
                message="当前 upstream 不能作为受控 fetch 目标。",
                preview_id=preview.get("preview_id"),
                preview=preview,
                state=state,
            )
        return None

    def _validate_pull_apply_state(self, preview: dict[str, Any], state: dict[str, Any]) -> dict[str, Any] | None:
        if state.get("branch") != preview.get("branch"):
            return self._push_error(
                action="pull_apply",
                error_code="BRANCH_CHANGED",
                message="当前分支已变化，请重新预览。",
                preview_id=preview.get("preview_id"),
                preview=preview,
                state=state,
            )
        if state.get("head") != preview.get("head"):
            return self._push_error(
                action="pull_apply",
                error_code="HEAD_CHANGED",
                message="当前 HEAD 已变化，请重新预览。",
                preview_id=preview.get("preview_id"),
                preview=preview,
                state=state,
            )
        if state.get("upstream") != preview.get("upstream"):
            return self._push_error(
                action="pull_apply",
                error_code="UPSTREAM_CHANGED",
                message="当前 upstream 已变化，请重新预览。",
                preview_id=preview.get("preview_id"),
                preview=preview,
                state=state,
            )

        current_upstream_head = self._current_upstream_head()
        if current_upstream_head != preview.get("upstream_head"):
            return self._push_error(
                action="pull_apply",
                error_code="UPSTREAM_HEAD_CHANGED",
                message="当前 upstream HEAD 已变化，请重新预览。",
                preview_id=preview.get("preview_id"),
                preview=preview,
                state=state,
            )
        if state.get("working_tree_clean") is not True:
            return self._push_error(
                action="pull_apply",
                error_code="WORKING_TREE_DIRTY",
                message="工作区不干净，请重新预览。",
                preview_id=preview.get("preview_id"),
                preview=preview,
                state=state,
            )

        current_ahead = state.get("ahead")
        current_behind = state.get("behind")
        preview_behind = preview.get("behind")
        if current_ahead != 0:
            return self._push_error(
                action="pull_apply",
                error_code="AHEAD_COUNT_CHANGED",
                message="当前分支已产生本地提交，请重新预览。",
                preview_id=preview.get("preview_id"),
                preview=preview,
                state=state,
            )
        if current_behind != preview_behind or not isinstance(current_behind, int) or current_behind <= 0:
            return self._push_error(
                action="pull_apply",
                error_code="BEHIND_COUNT_CHANGED",
                message="待拉取提交数量已变化，请重新预览。",
                preview_id=preview.get("preview_id"),
                preview=preview,
                state=state,
            )
        if not self._is_head_ancestor_of_upstream():
            return self._push_error(
                action="pull_apply",
                error_code="NON_FAST_FORWARD",
                message="当前分支无法 fast-forward 到 upstream。",
                preview_id=preview.get("preview_id"),
                preview=preview,
                state=state,
            )
        return None

    def _git_status_short(self) -> tuple[list[str], dict[str, Any]]:
        status_res = self._git(["status", "--short", "--untracked-files=all"])
        if status_res["code"] != 0:
            return [], status_res
        status_lines = [line for line in str(status_res["stdout"] or "").splitlines() if line.strip()]
        filtered = [line for line in status_lines if not self._is_internal_runner_status_line(line)]
        return filtered, status_res

    def _classify_git_changed_files(self, status_short: list[str]) -> dict[str, Any]:
        changed_files = self._get_git_changed_files_from_status(status_short)
        runner_memory_files = [path for path in changed_files if self._is_runner_project_tracked_file(path)]
        ignored_runner_local_files = [path for path in changed_files if self._is_runner_local_private_file(path)]
        ignored_runner_runtime_files = [path for path in changed_files if self._is_runner_runtime_file(path)]
        ignored_runner_archive_files = [path for path in changed_files if self._is_runner_archive_file(path)]
        ignored_files = set(ignored_runner_local_files + ignored_runner_runtime_files + ignored_runner_archive_files)
        blocking_files = sorted(path for path in changed_files if path not in ignored_files)
        blocking_status_short = [
            line for line in status_short
            if any(path in blocking_files for path in self._status_line_paths(line))
        ]
        return {
            "changed_files": changed_files,
            "blocking_files": blocking_files,
            "blocking_status_short": blocking_status_short,
            "runner_memory_files": runner_memory_files,
            "ignored_runner_local_files": ignored_runner_local_files,
            "ignored_runner_runtime_files": ignored_runner_runtime_files,
            "ignored_runner_archive_files": ignored_runner_archive_files,
        }

    def _get_git_changed_files_from_status(self, status_short: list[str]) -> list[str]:
        files: list[str] = []
        for line in status_short:
            files.extend(self._status_line_paths(line))
        return sorted(set(path for path in files if path))

    def _status_line_paths(self, line: str) -> list[str]:
        raw_path = str(line[3:] if len(line) > 3 else "").strip()
        if not raw_path:
            return []
        if " -> " in raw_path:
            return [self._normalize_status_path(part) for part in raw_path.split(" -> ", 1) if self._normalize_status_path(part)]
        normalized = self._normalize_status_path(raw_path)
        return [normalized] if normalized else []

    def _normalize_status_path(self, path: str) -> str:
        normalized = str(path or "").strip().strip('"').replace("\\", "/")
        while normalized.startswith("./"):
            normalized = normalized[2:]
        return normalized.rstrip("/")

    def _is_runner_project_tracked_file(self, path: str) -> bool:
        category = classify_runner_path(path).get("category")
        return category == "project_tracked"

    def _is_runner_local_private_file(self, path: str) -> bool:
        normalized = self._normalize_status_path(path)
        category = classify_runner_path(normalized).get("category")
        return (
            category == "project_local"
            or is_project_runner_subpath(normalized, ("executor-sessions",))
        )

    def _is_runner_runtime_file(self, path: str) -> bool:
        category = classify_runner_path(path).get("category")
        return category == "runtime_ephemeral"

    def _is_runner_archive_file(self, path: str) -> bool:
        category = classify_runner_path(path).get("category")
        return category == "archive_private_or_exportable"

    def _is_internal_runner_status_line(self, line: str) -> bool:
        raw_path = str(line[3:] if len(line) > 3 else "").strip()
        if not raw_path:
            return False
        if " -> " in raw_path:
            left, right = [part.strip() for part in raw_path.split(" -> ", 1)]
            return self._is_internal_git_remote_preview_path(left) or self._is_internal_git_remote_preview_path(right)
        if self._is_mvp_runner_folded_status_path(raw_path):
            return self._folded_status_tree_has_only_git_remote_previews(raw_path)
        return self._is_internal_git_remote_preview_path(raw_path)

    def _is_mvp_runner_folded_status_path(self, rel_path: str) -> bool:
        normalized = str(rel_path or "").replace("\\", "/").strip()
        return any(
            normalized in {dirname, f"{dirname}/", f"{dirname}/runtime", f"{dirname}/runtime/"}
            for dirname in project_runner_dirnames()
        )

    def _is_internal_git_remote_preview_path(self, rel_path: str) -> bool:
        normalized = str(rel_path or "").replace("\\", "/").strip()
        if not normalized:
            return False
        return is_project_runner_subpath(normalized, ("runtime/git-remote-previews",))

    def _folded_status_tree_has_only_git_remote_previews(self, rel_path: str) -> bool:
        normalized = str(rel_path or "").replace("\\", "/").strip().rstrip("/")
        target_dir = os.path.join(self.project_root, normalized)
        if not os.path.isdir(target_dir):
            return False
        for current_dir, _dir_names, file_names in os.walk(target_dir):
            for file_name in file_names:
                full_path = os.path.join(current_dir, file_name)
                try:
                    rel_path = os.path.relpath(full_path, self.project_root).replace("\\", "/")
                except ValueError:
                    return False
                if not self._is_internal_git_remote_preview_path(rel_path):
                    return False
        return True

    def _commits_to_push(self, upstream: str) -> list[dict[str, str]] | None:
        commits_res = self._git(["log", "--format=%h%x09%s", "--max-count=20", f"{upstream}..HEAD"])
        if commits_res["code"] != 0:
            return None
        commits: list[dict[str, str]] = []
        for line in str(commits_res["stdout"] or "").splitlines():
            if not line.strip():
                continue
            short_hash, _, subject = line.partition("\t")
            if not short_hash or not subject:
                continue
            commits.append(
                {
                    "short_hash": short_hash.strip(),
                    "subject": subject.strip(),
                }
            )
        return commits

    def _recent_head_commits(self) -> list[dict[str, str]] | None:
        commits_res = self._git(["log", "--format=%h%x09%s", "--max-count=5", "HEAD"])
        if commits_res["code"] != 0:
            return None
        commits: list[dict[str, str]] = []
        for line in str(commits_res["stdout"] or "").splitlines():
            if not line.strip():
                continue
            short_hash, _, subject = line.partition("\t")
            if not short_hash or not subject:
                continue
            commits.append(
                {
                    "short_hash": short_hash.strip(),
                    "subject": subject.strip(),
                }
            )
        return commits

    def _commits_to_pull(self, upstream: str) -> list[dict[str, str]] | None:
        if not upstream:
            return None
        commits_res = self._git(["log", "--format=%h%x09%s", "--max-count=20", "HEAD..@{u}"])
        if commits_res["code"] != 0:
            return None
        commits: list[dict[str, str]] = []
        for line in str(commits_res["stdout"] or "").splitlines():
            if not line.strip():
                continue
            short_hash, _, subject = line.partition("\t")
            if not short_hash or not subject:
                continue
            commits.append(
                {
                    "short_hash": short_hash.strip(),
                    "subject": subject.strip(),
                }
            )
        return commits

    def _current_upstream_head(self) -> str | None:
        upstream_head_res = self._git(["rev-parse", "@{u}"])
        if upstream_head_res["code"] != 0:
            return None
        upstream_head = str(upstream_head_res["stdout"] or "").strip()
        return upstream_head or None

    def _is_head_ancestor_of_upstream(self) -> bool:
        return self._git(["merge-base", "--is-ancestor", "HEAD", "@{u}"])["code"] == 0

    def _remote_branch_exists(self, remote_name: str, branch: str) -> bool | None:
        if not self._is_safe_git_arg(remote_name) or not self._is_safe_git_arg(branch):
            return None
        result = self._git(["ls-remote", "--heads", remote_name, branch])
        if result["code"] != 0:
            return None
        return bool(str(result.get("stdout") or "").strip())

    def _with_tracking_ref_warning(self, warnings: Any) -> list[str]:
        result = [item for item in warnings if isinstance(item, str)] if isinstance(warnings, list) else []
        if "tracking_ref_may_be_stale" not in result:
            result.append("tracking_ref_may_be_stale")
        return result

    def _is_safe_git_arg(self, value: Any) -> bool:
        if not isinstance(value, str):
            return False
        raw = value.strip()
        if not raw or raw.startswith("-"):
            return False
        if any(ch.isspace() for ch in raw):
            return False
        if raw in {".", ".."} or raw.startswith("/") or raw.endswith("/") or "//" in raw:
            return False
        if ".." in raw or "@{" in raw or "\\" in raw:
            return False
        if any(ch in raw for ch in ("~", "^", ":", "?", "*", "[")):
            return False
        return re.fullmatch(r"[A-Za-z0-9._/-]+", raw) is not None

    def _git(self, args: list[str]) -> dict[str, Any]:
        try:
            proc = subprocess.run(
                ["git", *args],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            return {
                "code": proc.returncode,
                "stdout": proc.stdout or "",
                "stderr": proc.stderr or "",
                "args": ["git", *args],
            }
        except Exception as exc:
            return {
                "code": 1,
                "stdout": "",
                "stderr": str(exc),
                "args": ["git", *args],
            }

    def _git_error_message(self, result: dict[str, Any], fallback: str) -> str:
        stderr = self._shorten(self._redact_secret_text(str(result.get("stderr") or "")), 240)
        stdout = self._shorten(self._redact_secret_text(str(result.get("stdout") or "")), 240)
        parts = [part for part in (stderr, stdout) if part]
        if parts:
            return f"{fallback} {'; '.join(parts)}"
        return fallback

    def _remote_url(self, remote_name: str) -> str | None:
        remote_res = self._git(["config", "--get", f"remote.{remote_name}.url"])
        if remote_res["code"] != 0:
            return None
        remote_url = str(remote_res["stdout"] or "").strip()
        return remote_url or None

    def _redact_remote_url(self, remote_url: str | None) -> str | None:
        if not remote_url:
            return None
        parsed = urlsplit(remote_url)
        if parsed.scheme and parsed.netloc:
            netloc = parsed.netloc
            if "@" in netloc:
                host_part = netloc.split("@", 1)[1]
                return urlunsplit((parsed.scheme, f"***@{host_part}", parsed.path, parsed.query, parsed.fragment))
        match = self._REMOTE_URL_AUTH_PATTERN.match(remote_url) or self._REMOTE_URL_CREDENTIALS_PATTERN.match(remote_url)
        if match:
            return f"{match.group('scheme')}***@{match.group('rest')}"
        return remote_url

    def _parse_remote_name(self, upstream: str) -> str | None:
        if not upstream or "/" not in upstream:
            return None
        remote_name = upstream.split("/", 1)[0].strip()
        return remote_name or None

    def _parse_upstream_branch(self, upstream: str) -> str | None:
        if not upstream or "/" not in upstream:
            return None
        branch = upstream.split("/", 1)[1].strip()
        return branch or None

    def _parse_counts(self, raw: str | None) -> tuple[int, int] | None:
        if not isinstance(raw, str):
            return None
        parts = raw.strip().split()
        if len(parts) != 2:
            return None
        try:
            return int(parts[0]), int(parts[1])
        except ValueError:
            return None

    def _shorten(self, text: str, max_len: int = 300) -> str:
        if len(text) <= max_len:
            return text
        return text[:max_len] + "..."

    def _hash_lines(self, lines: list[str]) -> str:
        payload = "\n".join(lines)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _write_preview(self, preview_id: str, payload: dict[str, Any]) -> str:
        os.makedirs(self.preview_dir, exist_ok=True)
        path = self._preview_file_path(preview_id)
        fd, tmp_path = tempfile.mkstemp(prefix=".tmp-git-remote-", suffix=".json", dir=self.preview_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
                f.write("\n")
            os.replace(tmp_path, path)
        except Exception:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise
        return path

    def _read_apply_preview(
        self,
        *,
        action: str,
        expected_preview_action: str,
        preview_id: str,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        normalized_preview_id = self._validate_preview_id(preview_id)
        if normalized_preview_id is None:
            return None, self._push_error(
                action=action,
                error_code="INVALID_PREVIEW_ID",
                message="preview_id 格式无效。",
            )

        preview = self._read_preview(normalized_preview_id)
        if preview is None:
            return None, self._push_error(
                action=action,
                error_code="PREVIEW_NOT_FOUND",
                message="preview_id 对应的预览不存在。",
                preview_id=normalized_preview_id,
            )
        if not isinstance(preview, dict):
            return None, self._push_error(
                action=action,
                error_code="PREVIEW_INVALID",
                message="预览文件格式无效。",
                preview_id=normalized_preview_id,
            )

        expires_at = self._parse_time(preview.get("expires_at"))
        if expires_at is None or expires_at <= datetime.now(timezone.utc):
            return None, self._push_error(
                action=action,
                error_code="PREVIEW_EXPIRED",
                message="preview 已过期，请重新创建。",
                preview_id=normalized_preview_id,
            )

        if str(preview.get("action") or "") != expected_preview_action:
            return None, self._push_error(
                action=action,
                error_code="PREVIEW_ACTION_INVALID",
                message="preview action 无效，不能 apply。",
                preview_id=normalized_preview_id,
            )

        preview_root = self._normalize_path(str(preview.get("project_root") or ""))
        if preview_root != self.project_root:
            return None, self._push_error(
                action=action,
                error_code="PREVIEW_PROJECT_MISMATCH",
                message="preview 不属于当前项目。",
                preview_id=normalized_preview_id,
            )
        return preview, None

    def _read_preview(self, preview_id: str) -> dict[str, Any] | None:
        path = self._preview_file_path(preview_id)
        if not os.path.isfile(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return None
        return data if isinstance(data, dict) else None

    def _preview_file_path(self, preview_id: str) -> str:
        if not self._validate_preview_id(preview_id):
            raise ValueError("invalid preview_id")
        return os.path.join(self.preview_dir, f"{preview_id}.json")

    def _validate_preview_id(self, preview_id: Any) -> str | None:
        if not isinstance(preview_id, str):
            return None
        normalized = preview_id.strip()
        if not normalized:
            return None
        if not self._PREVIEW_ID_PATTERN.fullmatch(normalized):
            return None
        return normalized

    def _normalize_path(self, value: str) -> str:
        return os.path.abspath(os.path.expanduser(value)).replace("\\", "/")

    def _parse_time(self, value: Any) -> datetime | None:
        if not isinstance(value, str) or not value.strip():
            return None
        raw = value.strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(raw)
        except Exception:
            return None

    def _redact_secret_text(self, text: Any) -> str:
        if not isinstance(text, str):
            return ""
        redacted = text
        redacted = re.sub(r"(?i)(authorization\s*:\s*)(\S+)", r"\1***", redacted)
        redacted = re.sub(r"(?i)(password\s*[:=]\s*)(\S+)", r"\1***", redacted)
        redacted = re.sub(r"(?i)(token\s*[:=]\s*)(\S+)", r"\1***", redacted)
        redacted = re.sub(r"(?i)(https?://)([^/\s:@]+):([^@\s]+)@", r"\1***@", redacted)
        redacted = re.sub(r"(?i)(https?://)([^/\s:@]+)@([^/\s]+)", r"\1***@\3", redacted)
        redacted = re.sub(r"(?i)(ssh://)([^/\s@]+)@", r"\1***@", redacted)
        return redacted

    def _merge_git_output(self, result: dict[str, Any]) -> str:
        stdout = str(result.get("stdout") or "").strip()
        stderr = str(result.get("stderr") or "").strip()
        parts = [part for part in (stdout, stderr) if part]
        return "\n".join(parts)

    def _push_error(
        self,
        *,
        action: str,
        error_code: str,
        message: str,
        preview_id: str | None = None,
        preview: dict[str, Any] | None = None,
        state: dict[str, Any] | None = None,
        blockers: list[str] | None = None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "ok": False,
            "action": action,
            "error_code": error_code,
            "message": message,
        }
        if preview_id is not None:
            result["preview_id"] = preview_id
        if preview is not None:
            result["preview"] = {
                "preview_id": preview.get("preview_id"),
                "branch": preview.get("branch"),
                "upstream": preview.get("upstream"),
                "head": preview.get("head"),
                "ahead": preview.get("ahead"),
                "behind": preview.get("behind"),
            }
        if state is not None:
            result["state"] = {
                "branch": state.get("branch"),
                "upstream": state.get("upstream"),
                "head": state.get("head"),
                "ahead": state.get("ahead"),
                "behind": state.get("behind"),
                "working_tree_clean": state.get("working_tree_clean"),
                "blocking_working_tree_clean": state.get("blocking_working_tree_clean"),
                "blocking_git_status_short": state.get("blocking_git_status_short", []),
                "blocking_git_status_short_hash": state.get("blocking_git_status_short_hash"),
                "blocking_git_changed_files": state.get("blocking_git_changed_files", []),
                "ignored_runner_local_files": state.get("ignored_runner_local_files", []),
                "ignored_runner_runtime_files": state.get("ignored_runner_runtime_files", []),
                "ignored_runner_archive_files": state.get("ignored_runner_archive_files", []),
            }
        if blockers:
            result["blockers"] = blockers
        return result

    def _push_not_ready(
        self,
        *,
        action: str,
        blockers: list[str],
        state: dict[str, Any],
        error_code: str,
        message: str,
    ) -> dict[str, Any]:
        return {
            "ok": False,
            "action": action,
            "error_code": error_code,
            "message": message,
            "blockers": blockers,
            "branch": state.get("branch"),
            "head": state.get("head"),
            "head_short": state.get("head_short"),
            "working_tree_clean": state.get("working_tree_clean"),
            "status_short": state.get("status_short", []),
            "status_short_hash": state.get("status_short_hash"),
            "blocking_working_tree_clean": state.get("blocking_working_tree_clean"),
            "blocking_tree_clean": state.get("blocking_working_tree_clean"),
            "blocking_git_status_short": state.get("blocking_git_status_short", []),
            "blocking_git_status_short_hash": state.get("blocking_git_status_short_hash"),
            "blocking_git_changed_files": state.get("blocking_git_changed_files", []),
            "ignored_runner_local_files": state.get("ignored_runner_local_files", []),
            "ignored_runner_runtime_files": state.get("ignored_runner_runtime_files", []),
            "ignored_runner_archive_files": state.get("ignored_runner_archive_files", []),
            "upstream": state.get("upstream"),
            "remote_name": state.get("remote_name"),
            "remote_url_redacted": state.get("remote_url_redacted"),
            "ahead": state.get("ahead"),
            "behind": state.get("behind"),
            "first_push_available": state.get("first_push_available", False),
            "first_push_remote": state.get("first_push_remote"),
            "first_push_target": state.get("first_push_target"),
            "warnings": state.get("warnings", []),
        }

    def _blocker_message(self, blocker: str) -> str:
        messages = {
            "branch_detached": "当前 HEAD 处于 detached 状态。",
            "head_missing": "当前 HEAD 不存在。",
            "working_tree_dirty": "工作区不干净。",
            "upstream_missing": "当前分支没有 upstream。",
            "remote_missing": "当前分支没有 upstream，且未发现 origin remote。",
            "branch_invalid": "当前分支名不能作为受控 Git 参数。",
            "first_push_remote_check_failed": "检查远端同名分支失败。",
            "first_push_remote_branch_exists": "远端同名分支已存在，当前工具不会自动关联以避免错误覆盖。",
            "upstream_invalid": "当前 upstream 不能作为受控 remote 目标。",
            "remote_url_missing": "upstream 的 remote URL 无法读取。",
            "branch_behind_upstream": "当前分支落后于 upstream。",
            "nothing_to_push": "没有可推送的提交。",
            "diverged_from_upstream": "当前分支与 upstream 已分叉。",
            "local_ahead": "当前分支包含本地未推送提交。",
            "nothing_to_pull": "没有可拉取的提交。",
            "non_fast_forward": "当前分支无法 fast-forward 到 upstream。",
        }
        return messages.get(blocker, blocker)

    def _generate_preview_id(self) -> str:
        import secrets
        return secrets.token_urlsafe(24)
