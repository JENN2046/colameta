from __future__ import annotations

import hashlib
import json
import os
import secrets
import stat
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Any

from runner.mcp_git_remote import MCPGitRemoteManager
from runner.runner_paths import resolve_project_runner_path


class MCPGitBranchManager:
    """Preview-bound creation of one delivery-safe topic branch."""

    def __init__(self, project_root: str):
        self.project_root = os.path.abspath(os.path.expanduser(project_root))
        self.preview_dir = resolve_project_runner_path(
            self.project_root,
            "runtime",
            "git-branch-previews",
        )
        self.preview_ttl_seconds = 1800

    def topic_branch_preview(self, branch_name: str) -> dict[str, Any]:
        target_branch = branch_name.strip() if isinstance(branch_name, str) else ""
        state = self._repository_state(include_fingerprint=True)
        if state.get("ok") is not True:
            return state

        blocker = self._preview_blocker(state, target_branch)
        if blocker is not None:
            return self._error(
                action="topic_branch_preview",
                error_code=blocker,
                message=self._blocker_message(blocker),
                state=state,
                target_branch=target_branch,
            )

        preview_id = secrets.token_urlsafe(18)
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=self.preview_ttl_seconds)
        payload = {
            "schema_version": "git_topic_branch_preview.v1",
            "action": "topic_branch_preview",
            "preview_id": preview_id,
            "project_root": self.project_root,
            "project_identity": {
                "source_branch": state["branch"],
                "source_head": state["head"],
            },
            "source_branch": state["branch"],
            "source_head": state["head"],
            "target_branch": target_branch,
            "working_tree_fingerprint": state["working_tree_fingerprint"],
            "created_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
            "consumed": False,
        }
        preview_file = self._write_preview(preview_id, payload)
        return {
            "ok": True,
            "action": "topic_branch_preview",
            "preview_id": preview_id,
            "source_branch": state["branch"],
            "source_head": state["head"],
            "target_branch": target_branch,
            "working_tree_fingerprint": state["working_tree_fingerprint"],
            "working_tree_clean": state["working_tree_clean"],
            "working_tree_preserved_on_apply": True,
            "can_apply": True,
            "requires_confirmation": True,
            "created_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
            "preview_file": os.path.relpath(preview_file, self.project_root).replace(
                "\\", "/"
            ),
            "blockers": [],
            "warnings": [],
        }

    def topic_branch_apply(self, preview_id: str) -> dict[str, Any]:
        normalized_id = self._validate_preview_id(preview_id)
        if normalized_id is None:
            return self._error(
                action="topic_branch_apply",
                error_code="INVALID_PREVIEW_ID",
                message="preview_id is invalid.",
            )
        preview = self._read_preview(normalized_id)
        if preview is None:
            return self._error(
                action="topic_branch_apply",
                error_code="PREVIEW_NOT_FOUND",
                message="The topic-branch preview does not exist.",
                preview_id=normalized_id,
            )
        if preview.get("action") != "topic_branch_preview":
            return self._error(
                action="topic_branch_apply",
                error_code="PREVIEW_ACTION_INVALID",
                message="The preview cannot authorize topic-branch apply.",
                preview_id=normalized_id,
            )
        if os.path.abspath(str(preview.get("project_root") or "")) != self.project_root:
            return self._error(
                action="topic_branch_apply",
                error_code="PREVIEW_PROJECT_MISMATCH",
                message="The preview belongs to another project.",
                preview_id=normalized_id,
            )
        if preview.get("consumed") is True:
            return self._error(
                action="topic_branch_apply",
                error_code="PREVIEW_CONSUMED",
                message="The topic-branch preview has already been consumed.",
                preview_id=normalized_id,
            )
        expires_at = self._parse_time(preview.get("expires_at"))
        if expires_at is None or expires_at <= datetime.now(timezone.utc):
            return self._error(
                action="topic_branch_apply",
                error_code="PREVIEW_EXPIRED",
                message="The topic-branch preview has expired.",
                preview_id=normalized_id,
            )

        state = self._repository_state(include_fingerprint=True)
        if state.get("ok") is not True:
            return state
        target_branch = str(preview.get("target_branch") or "")
        mismatch = self._apply_mismatch(preview, state, target_branch)
        if mismatch is not None:
            return self._error(
                action="topic_branch_apply",
                error_code=mismatch,
                message=self._blocker_message(mismatch),
                state=state,
                preview_id=normalized_id,
                target_branch=target_branch,
            )

        source_branch = state["branch"]
        source_head = state["head"]
        fingerprint_before = state["working_tree_fingerprint"]
        switched = self._run_git(["switch", "-c", target_branch])
        if switched["code"] != 0:
            return self._error(
                action="topic_branch_apply",
                error_code="TOPIC_BRANCH_SWITCH_FAILED",
                message=self._git_message(switched, "Failed to create the topic branch."),
                state=state,
                preview_id=normalized_id,
                target_branch=target_branch,
            )

        after = self._repository_state(include_fingerprint=True)
        if (
            after.get("ok") is not True
            or after.get("branch") != target_branch
            or after.get("head") != source_head
            or after.get("working_tree_fingerprint") != fingerprint_before
        ):
            return self._error(
                action="topic_branch_apply",
                error_code="POST_APPLY_INVARIANT_FAILED",
                message="The branch changed but post-apply identity could not be verified.",
                state=after,
                preview_id=normalized_id,
                target_branch=target_branch,
                partial_mutation=True,
            )

        preview["consumed"] = True
        preview["consumed_at"] = datetime.now(timezone.utc).isoformat()
        self._write_preview(normalized_id, preview)
        return {
            "ok": True,
            "action": "topic_branch_apply",
            "status": "completed",
            "preview_id": normalized_id,
            "preview_consumed": True,
            "source_branch": source_branch,
            "current_branch": target_branch,
            "head_before": source_head,
            "head_after": after["head"],
            "working_tree_fingerprint_before": fingerprint_before,
            "working_tree_fingerprint_after": after["working_tree_fingerprint"],
            "working_tree_clean": after["working_tree_clean"],
            "working_tree_preserved": True,
            "commit_performed": False,
            "push_performed": False,
            "blockers": [],
            "warnings": [],
        }

    def _preview_blocker(
        self,
        state: dict[str, Any],
        target_branch: str,
    ) -> str | None:
        if state.get("branch") == "HEAD":
            return "DETACHED_HEAD"
        operation = state.get("operation_in_progress")
        if isinstance(operation, str) and operation:
            return "GIT_OPERATION_IN_PROGRESS"
        policy = MCPGitRemoteManager(self.project_root)
        if policy.delivery_branch_policy_blocker(state.get("branch")) is None:
            return "SOURCE_BRANCH_ALREADY_DELIVERY_SAFE"
        target_error = self._target_branch_blocker(target_branch, policy)
        if target_error is not None:
            return target_error
        if self._local_branch_exists(target_branch):
            return "TOPIC_BRANCH_ALREADY_EXISTS"
        return None

    def _apply_mismatch(
        self,
        preview: dict[str, Any],
        state: dict[str, Any],
        target_branch: str,
    ) -> str | None:
        if state.get("branch") == "HEAD":
            return "DETACHED_HEAD"
        operation = state.get("operation_in_progress")
        if isinstance(operation, str) and operation:
            return "GIT_OPERATION_IN_PROGRESS"
        if state.get("branch") != preview.get("source_branch"):
            return "SOURCE_BRANCH_DRIFT"
        if state.get("head") != preview.get("source_head"):
            return "SOURCE_HEAD_DRIFT"
        if state.get("working_tree_fingerprint") != preview.get(
            "working_tree_fingerprint"
        ):
            return "WORKING_TREE_DRIFT"
        policy = MCPGitRemoteManager(self.project_root)
        target_error = self._target_branch_blocker(target_branch, policy)
        if target_error is not None:
            return target_error
        if self._local_branch_exists(target_branch):
            return "TOPIC_BRANCH_ALREADY_EXISTS"
        return None

    def _target_branch_blocker(
        self,
        target_branch: str,
        policy: MCPGitRemoteManager,
    ) -> str | None:
        if not target_branch:
            return "INVALID_TOPIC_BRANCH"
        checked = self._run_git(["check-ref-format", "--branch", target_branch])
        if checked["code"] != 0:
            return "INVALID_TOPIC_BRANCH"
        if policy.delivery_branch_policy_blocker(target_branch) is not None:
            return "TOPIC_BRANCH_NOT_DELIVERY_SAFE"
        return None

    def _repository_state(self, *, include_fingerprint: bool) -> dict[str, Any]:
        inside = self._run_git(["rev-parse", "--is-inside-work-tree"])
        if inside["code"] != 0 or inside["stdout"].strip() != "true":
            return self._error(
                action="topic_branch_status",
                error_code="NOT_GIT_REPOSITORY",
                message="The project is not inside a Git worktree.",
            )
        branch_result = self._run_git(["symbolic-ref", "--quiet", "--short", "HEAD"])
        branch = branch_result["stdout"].strip() if branch_result["code"] == 0 else "HEAD"
        head_result = self._run_git(["rev-parse", "--verify", "HEAD"])
        if head_result["code"] != 0 or not head_result["stdout"].strip():
            return self._error(
                action="topic_branch_status",
                error_code="HEAD_MISSING",
                message="The current Git HEAD is unavailable.",
            )
        status = self._run_git_bytes(
            [
                "status",
                "--porcelain=v1",
                "-z",
                "--untracked-files=all",
                "--",
                ".",
                ":(exclude).colameta/runtime/git-branch-previews",
            ]
        )
        if status["code"] != 0:
            return self._error(
                action="topic_branch_status",
                error_code="GIT_STATUS_FAILED",
                message="Git working-tree status could not be read.",
            )
        result: dict[str, Any] = {
            "ok": True,
            "branch": branch,
            "head": head_result["stdout"].strip(),
            "working_tree_clean": not bool(status["stdout"]),
            "operation_in_progress": self._operation_in_progress(),
        }
        if include_fingerprint:
            fingerprint = self._working_tree_fingerprint(status["stdout"])
            if fingerprint is None:
                return self._error(
                    action="topic_branch_status",
                    error_code="WORKING_TREE_FINGERPRINT_FAILED",
                    message="The working-tree fingerprint could not be collected.",
                )
            result["working_tree_fingerprint"] = fingerprint
        return result

    def _working_tree_fingerprint(self, status_bytes: bytes) -> str | None:
        pathspec = ["--", ".", ":(exclude).colameta/runtime/git-branch-previews"]
        staged = self._run_git_bytes(
            ["diff", "--cached", "--binary", "--no-ext-diff", *pathspec]
        )
        unstaged = self._run_git_bytes(
            ["diff", "--binary", "--no-ext-diff", *pathspec]
        )
        untracked = self._run_git_bytes(
            ["ls-files", "--others", "--exclude-standard", "-z", *pathspec]
        )
        if any(item["code"] != 0 for item in (staged, unstaged, untracked)):
            return None
        untracked_signatures: list[dict[str, str]] = []
        for raw_path in sorted(item for item in untracked["stdout"].split(b"\0") if item):
            relative = raw_path.decode("utf-8", errors="surrogateescape")
            signature = self._untracked_signature(relative)
            if signature is None:
                return None
            untracked_signatures.append({"path": relative, "signature": signature})
        payload = {
            "status_sha256": hashlib.sha256(status_bytes).hexdigest(),
            "staged_diff_sha256": hashlib.sha256(staged["stdout"]).hexdigest(),
            "unstaged_diff_sha256": hashlib.sha256(unstaged["stdout"]).hexdigest(),
            "untracked": untracked_signatures,
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _untracked_signature(self, relative_path: str) -> str | None:
        candidate = os.path.abspath(os.path.join(self.project_root, relative_path))
        try:
            if os.path.commonpath([self.project_root, candidate]) != self.project_root:
                return None
            info = os.lstat(candidate)
            if stat.S_ISLNK(info.st_mode):
                target = os.readlink(candidate).encode("utf-8", errors="surrogateescape")
                return f"symlink:{hashlib.sha256(target).hexdigest()}"
            if stat.S_ISREG(info.st_mode):
                digest = hashlib.sha256()
                with open(candidate, "rb") as handle:
                    for chunk in iter(lambda: handle.read(65536), b""):
                        digest.update(chunk)
                return f"file:{info.st_mode & 0o777:o}:{digest.hexdigest()}"
            return f"special:{info.st_mode:o}:{info.st_size}"
        except (OSError, ValueError):
            return None

    def _operation_in_progress(self) -> str | None:
        markers = (
            ("merge", "MERGE_HEAD"),
            ("rebase", "rebase-merge"),
            ("rebase", "rebase-apply"),
            ("cherry_pick", "CHERRY_PICK_HEAD"),
            ("revert", "REVERT_HEAD"),
        )
        for label, marker in markers:
            path_result = self._run_git(["rev-parse", "--git-path", marker])
            if path_result["code"] != 0:
                continue
            path = path_result["stdout"].strip()
            if path and not os.path.isabs(path):
                path = os.path.join(self.project_root, path)
            if path and os.path.exists(path):
                return label
        return None

    def _local_branch_exists(self, branch_name: str) -> bool:
        result = self._run_git(
            ["show-ref", "--verify", "--quiet", f"refs/heads/{branch_name}"]
        )
        return result["code"] == 0

    def _write_preview(self, preview_id: str, payload: dict[str, Any]) -> str:
        os.makedirs(self.preview_dir, exist_ok=True)
        path = self._preview_path(preview_id)
        fd, temp_path = tempfile.mkstemp(
            prefix=".tmp-git-branch-",
            suffix=".json",
            dir=self.preview_dir,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            os.replace(temp_path, path)
        except Exception:
            try:
                os.remove(temp_path)
            except OSError:
                pass
            raise
        return path

    def _read_preview(self, preview_id: str) -> dict[str, Any] | None:
        try:
            with open(self._preview_path(preview_id), encoding="utf-8") as handle:
                value = json.load(handle)
        except (OSError, ValueError):
            return None
        return value if isinstance(value, dict) else None

    def _preview_path(self, preview_id: str) -> str:
        return os.path.join(self.preview_dir, f"{preview_id}.json")

    @staticmethod
    def _validate_preview_id(value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        if not normalized or any(
            character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
            for character in normalized
        ):
            return None
        return normalized

    @staticmethod
    def _parse_time(value: Any) -> datetime | None:
        if not isinstance(value, str) or not value.strip():
            return None
        raw = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)

    def _run_git(self, args: list[str]) -> dict[str, Any]:
        process = subprocess.run(
            ["git", "-C", self.project_root, *args],
            capture_output=True,
            text=True,
            check=False,
        )
        return {
            "code": process.returncode,
            "stdout": process.stdout,
            "stderr": process.stderr,
        }

    def _run_git_bytes(self, args: list[str]) -> dict[str, Any]:
        process = subprocess.run(
            ["git", "-C", self.project_root, *args],
            capture_output=True,
            text=False,
            check=False,
        )
        return {
            "code": process.returncode,
            "stdout": process.stdout,
            "stderr": process.stderr,
        }

    @staticmethod
    def _git_message(result: dict[str, Any], fallback: str) -> str:
        for key in ("stderr", "stdout"):
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:500]
        return fallback

    @staticmethod
    def _blocker_message(code: str) -> str:
        return {
            "DETACHED_HEAD": "Detached HEAD cannot enter topic-branch delivery.",
            "GIT_OPERATION_IN_PROGRESS": "A Git operation is already in progress.",
            "SOURCE_BRANCH_ALREADY_DELIVERY_SAFE": "The current branch is already delivery-safe.",
            "INVALID_TOPIC_BRANCH": "The requested topic branch name is invalid.",
            "TOPIC_BRANCH_NOT_DELIVERY_SAFE": "The requested branch is not allowed by delivery push policy.",
            "TOPIC_BRANCH_ALREADY_EXISTS": "The requested topic branch already exists locally.",
            "SOURCE_BRANCH_DRIFT": "The source branch changed after preview.",
            "SOURCE_HEAD_DRIFT": "HEAD changed after preview.",
            "WORKING_TREE_DRIFT": "The working tree changed after preview.",
        }.get(code, "Topic-branch admission is blocked.")

    @staticmethod
    def _error(
        *,
        action: str,
        error_code: str,
        message: str,
        state: dict[str, Any] | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "ok": False,
            "action": action,
            "status": "blocked",
            "error_code": error_code,
            "message": message,
            "blockers": [error_code],
            "warnings": [],
        }
        if isinstance(state, dict):
            for key in (
                "branch",
                "head",
                "working_tree_clean",
                "working_tree_fingerprint",
                "operation_in_progress",
            ):
                if key in state:
                    result[key] = state[key]
        result.update(extra)
        return result
