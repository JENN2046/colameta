import os
import re
from pathlib import Path
from typing import Any

from runner._internal_utils import run_git as _run_git_base
from runner.confirmation_store import ConfirmationStore
from runner.core_confirmation import (
    confirmation_apply_guard,
    confirmation_guard_reports_expired_before_mismatch,
)
from runner.diff_utils import diff_hash, synthetic_unified_diff, truncate_text
from runner.file_signature import sha256_text, signatures_equal, text_signature
from runner.git_history_reconcile import GitHistoryReconcileScanner
from runner.param_utils import bounded_int
from runner.runner_paths import resolve_project_runner_rel_dir
from runner.source_review_bridge import SourceReviewBridge, SourceReviewError
from runner.tool_result import apply_result, error_result, ok_result, preview_result


PREVIEW_TTL_SECONDS = 1800
PREVIEW_DIR_NAME = "git-history-previews"
GIT_PREVIEW_DIR_NAME = "project-patch-previews"
PREVIEW_RELATIVE_DIR = os.path.join("runtime", PREVIEW_DIR_NAME)

ALLOWED_GIT_CMDS = {"rev-parse", "log", "show", "diff", "cat-file", "ls-tree", "status", "revert"}


def _is_safe_preview_id(preview_id: str) -> bool:
    return bool(re.fullmatch(r"[a-zA-Z0-9_\-]{1,64}", preview_id))


class MCPGitHistoryManager:
    def __init__(self, project_root: str, source_review: SourceReviewBridge):
        self.project_root = os.path.abspath(os.path.expanduser(project_root))
        self.source_review = source_review
        preview_dir = os.path.join(resolve_project_runner_rel_dir(self.project_root), PREVIEW_RELATIVE_DIR)
        self._store = ConfirmationStore(self.project_root, preview_dir, PREVIEW_TTL_SECONDS)

    # ----------------------------------------------------------------
    # Public dispatch
    # ----------------------------------------------------------------
    def handle(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        if action == "log":
            return self._log(params)
        if action == "show":
            return self._show(params)
        if action == "diff_commits":
            return self._diff_commits(params)
        if action == "restore_file_preview":
            return self._restore_file_preview(params)
        if action == "restore_file_apply":
            return self._restore_file_apply(params)
        if action == "revert_preview":
            return self._revert_preview(params)
        if action == "revert_apply":
            return self._revert_apply(params)
        if action == "reconcile_git_history_preview":
            return self._reconcile_git_history_preview(params)
        return error_result("UNKNOWN_ACTION", f"未知 action：{action}")

    # ----------------------------------------------------------------
    # 1. log
    # ----------------------------------------------------------------
    def _log(self, params: dict[str, Any]) -> dict[str, Any]:
        limit = bounded_int(params.get("limit"), 12, 1, 50)
        result = self._run_git(
            ["log", f"--max-count={limit}",
             "--pretty=format:%H||%h||%s||%an||%ai||%ar"],
            self.project_root,
        )
        if result["code"] != 0:
            return error_result("GIT_LOG_FAILED", self._git_error(result))

        commits: list[dict[str, Any]] = []
        for line in result["stdout"].splitlines():
            parts = line.split("||", 5)
            if len(parts) < 6:
                continue
            commits.append({
                "hash": parts[0],
                "short_hash": parts[1],
                "subject": parts[2],
                "author_name": parts[3],
                "author_date": parts[4],
                "relative_date": parts[5],
            })

        return ok_result("log", limit=limit, commits=commits)

    # ----------------------------------------------------------------
    # 2. show
    # ----------------------------------------------------------------
    def _show(self, params: dict[str, Any]) -> dict[str, Any]:
        commit_ref = params.get("commit")
        if not isinstance(commit_ref, str) or not commit_ref.strip():
            return error_result("INVALID_COMMIT", "commit 必须是非空字符串。")
        commit_ref = commit_ref.strip()

        resolved = self._resolve_commit(commit_ref)
        if isinstance(resolved, dict):
            return resolved

        log_result = self._run_git(
            ["log", "-1", "--pretty=format:%H||%h||%s||%b||%an||%ae||%ai", resolved],
            self.project_root,
        )
        if log_result["code"] != 0:
            return error_result("GIT_SHOW_FAILED", self._git_error(log_result))

        parts = log_result["stdout"].split("||", 6)
        if len(parts) < 7:
            return error_result("PARSE_ERROR", "无法解析 commit 元数据。")

        max_chars = bounded_int(params.get("max_chars"), 40000, 1, 80000)

        name_status = self._run_git(
            ["show", "--name-status", "--format=", "-r", "-m", resolved],
            self.project_root,
        )
        raw_changed: list[str] = []
        if name_status["code"] == 0:
            for line in name_status["stdout"].splitlines():
                parts_line = line.split("\t", 1)
                if len(parts_line) == 2:
                    raw_changed.append(parts_line[1].strip())

        allowed_files: list[str] = []
        skipped_files: list[str] = []
        for f in raw_changed:
            is_allowed, _ = self._classify_project_file(f)
            if is_allowed:
                allowed_files.append(f)
            else:
                skipped_files.append(f)

        result: dict[str, Any] = {
            "ok": True,
            "action": "show",
            "hash": parts[0],
            "short_hash": parts[1],
            "subject": parts[2],
            "body": parts[3].strip() if parts[3].strip() else None,
            "author_name": parts[4],
            "author_email": parts[5],
            "author_date": parts[6],
            "changed_files": allowed_files,
            "skipped_files": skipped_files if skipped_files else None,
        }

        include_patch = params.get("include_patch", True)
        if include_patch:
            patch_result = self._run_git(["show", "--no-color", resolved], self.project_root)
            if patch_result["code"] == 0:
                patch_filtered, patch_skipped, patch_truncated = self._filter_patch_to_allowed_files(
                    patch_result["stdout"], max_chars,
                )
                result["patch"] = patch_filtered
                if patch_truncated:
                    result["patch_truncated"] = True
                if patch_skipped:
                    result["patch_skipped_files"] = patch_skipped

        return result

    # ----------------------------------------------------------------
    # 3. diff_commits
    # ----------------------------------------------------------------
    def _diff_commits(self, params: dict[str, Any]) -> dict[str, Any]:
        base = params.get("base")
        head = params.get("head")
        if not isinstance(base, str) or not base.strip():
            return error_result("INVALID_BASE", "base 必须是非空字符串。")
        if not isinstance(head, str) or not head.strip():
            return error_result("INVALID_HEAD", "head 必须是非空字符串。")
        base = base.strip()
        head = head.strip()

        resolved_base = self._resolve_commit(base)
        if isinstance(resolved_base, dict):
            return resolved_base
        resolved_head = self._resolve_commit(head)
        if isinstance(resolved_head, dict):
            return resolved_head

        max_chars = bounded_int(params.get("max_chars"), 40000, 1, 80000)
        file_filter = params.get("file")
        if file_filter is not None:
            if not isinstance(file_filter, str) or not file_filter.strip():
                return error_result("INVALID_FILE", "file 必须是非空字符串。")
            try:
                self.source_review.validate_project_file_for_patch(self.project_root, file_filter)
            except SourceReviewError as e:
                return error_result("FILE_NOT_ALLOWED", str(e))
            norm = self.source_review._normalize_repo_relative_path(file_filter)
            if norm is None:
                return error_result("FILE_NOT_ALLOWED", "路径必须是项目内相对路径。")
            file_filter = norm

        # Get changed files list
        if file_filter:
            name_args = ["diff", "--name-status", f"{resolved_base}..{resolved_head}", "--", file_filter]
            diff_args = ["diff", f"{resolved_base}..{resolved_head}", "--no-color", "--", file_filter]
        else:
            name_args = ["diff", "--name-status", f"{resolved_base}..{resolved_head}"]
            diff_args = ["diff", f"{resolved_base}..{resolved_head}", "--no-color"]

        name_result = self._run_git(name_args, self.project_root)
        changed: list[str] = []
        if name_result["code"] == 0:
            for line in name_result["stdout"].splitlines():
                parts_line = line.split("\t", 1)
                if len(parts_line) == 2:
                    changed.append(parts_line[1].strip())

        if file_filter:
            allowed_files = [file_filter]
            skipped_files: list[str] = []
        else:
            allowed_files = []
            skipped_files = []
            for f in changed:
                is_allowed, _ = self._classify_project_file(f)
                if is_allowed:
                    allowed_files.append(f)
                else:
                    skipped_files.append(f)
        if file_filter:
            diff_result = self._run_git(diff_args, self.project_root)
            diff_text = diff_result["stdout"] if diff_result["code"] == 0 else ""
            truncated = False
            if len(diff_text) > max_chars:
                diff_text = diff_text[:max_chars]
                truncated = True
        else:
            diff_parts: list[str] = []
            truncated = False
            remaining = max_chars
            for f in allowed_files:
                if remaining <= 0:
                    truncated = True
                    break
                file_diff_result = self._run_git(
                    ["diff", f"{resolved_base}..{resolved_head}", "--no-color", "--", f],
                    self.project_root,
                )
                if file_diff_result["code"] != 0:
                    continue
                chunk = file_diff_result["stdout"]
                if not chunk.strip():
                    continue
                if len(chunk) > remaining:
                    diff_parts.append(chunk[:remaining])
                    truncated = True
                    break
                diff_parts.append(chunk)
                remaining -= len(chunk)
            diff_text = "".join(diff_parts)

        return ok_result(
            "diff_commits",
            base=resolved_base,
            head=resolved_head,
            changed_files=allowed_files,
            skipped_files=skipped_files,
            diff=diff_text,
            truncated=truncated,
        )

    # ----------------------------------------------------------------
    # 4. restore_file_preview
    # ----------------------------------------------------------------
    def _restore_file_preview(self, params: dict[str, Any]) -> dict[str, Any]:
        commit_ref = params.get("commit")
        file_raw = params.get("file")
        reason = params.get("reason")

        if not isinstance(commit_ref, str) or not commit_ref.strip():
            return error_result("INVALID_COMMIT", "commit 必须是非空字符串。")
        if not isinstance(file_raw, str) or not file_raw.strip():
            return error_result("INVALID_FILE", "file 必须是非空字符串。")

        commit_ref = commit_ref.strip()
        resolved = self._resolve_commit(commit_ref)
        if isinstance(resolved, dict):
            return resolved

        try:
            self.source_review.validate_project_file_for_patch(self.project_root, file_raw)
        except SourceReviewError as e:
            return error_result("FILE_NOT_ALLOWED", str(e))

        rel_path = self.source_review._normalize_repo_relative_path(file_raw)
        if rel_path is None:
            return error_result("FILE_NOT_ALLOWED", "路径必须是项目内相对路径。")

        abs_path = Path(self.project_root) / rel_path
        if not abs_path.exists() or not abs_path.is_file():
            return error_result("FILE_NOT_FOUND", f"文件不存在：{rel_path}")
        try:
            current_content = abs_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return error_result("BINARY_OR_UNSUPPORTED_FILE", "当前文件不是 UTF-8 文本。")
        except Exception as e:
            return error_result("FILE_READ_ERROR", f"读取文件失败：{e}")

        restored_content = self._git_show_file(resolved, rel_path)
        if isinstance(restored_content, dict):
            return restored_content

        if current_content == restored_content:
            return error_result("NO_CHANGE", f"文件 {rel_path} 在 commit {resolved[:8]} 中的内容与当前工作区一致，无需恢复。")

        predicted_diff = synthetic_unified_diff(rel_path, current_content, restored_content)
        max_chars = 80000
        if len(predicted_diff) > max_chars:
            return error_result("DIFF_TOO_LARGE", "恢复产生的 diff 过大。")

        base_sig = text_signature(current_content)
        preview_id = self._store.create_id()
        created_at = self._store.now_iso()
        expires_at = self._store.expires_at()

        preview_data: dict[str, Any] = {
            "preview_id": preview_id,
            "created_at": created_at,
            "expires_at": expires_at,
            "project_root": self.project_root,
            "mode": "restore_file",
            "commit": commit_ref,
            "resolved_commit": resolved,
            "file": rel_path,
            "reason": reason if isinstance(reason, str) and reason.strip() else "",
            "base_signature": base_sig,
            "restored_content_hash": sha256_text(restored_content),
            "predicted_diff": predicted_diff,
            "predicted_diff_hash": diff_hash(predicted_diff),
        }
        self._write_preview(preview_id, preview_data)

        return preview_result(
            "restore_file_preview",
            preview_id,
            file=rel_path,
            commit=commit_ref,
            resolved_commit=resolved,
            diff_summary=truncate_text(predicted_diff, 2000),
            diff_hash=preview_data["predicted_diff_hash"],
            expires_at=expires_at,
            recommended_next_action="restore_file_apply",
        )

    # ----------------------------------------------------------------
    # 5. restore_file_apply
    # ----------------------------------------------------------------
    def _restore_file_apply(self, params: dict[str, Any]) -> dict[str, Any]:
        preview_id = params.get("preview_id")
        if not isinstance(preview_id, str) or not preview_id.strip():
            return error_result("INVALID_PREVIEW_ID", "需要非空 preview_id。")
        preview_id = preview_id.strip()
        if not _is_safe_preview_id(preview_id):
            return error_result("INVALID_PREVIEW_ID", "preview_id 包含不安全字符。")

        guard = confirmation_apply_guard(self._store, preview_id, project_root=self.project_root)
        if not guard["ok"]:
            ec = guard["error_code"]
            if ec == "PREVIEW_NOT_FOUND":
                return error_result("PREVIEW_NOT_FOUND", f"preview 不存在：{preview_id}")
            if ec == "PROJECT_MISMATCH":
                return {"ok": False, "error_code": "PROJECT_MISMATCH", "message": "preview 与当前项目不匹配。"}
            if ec == "PREVIEW_EXPIRED":
                return {"ok": False, "error_code": "PREVIEW_EXPIRED", "message": "preview 已过期。"}
        preview_data = guard["payload"]
        if preview_data.get("mode") != "restore_file":
            return error_result("INVALID_MODE", "preview 模式不是 restore_file。")

        file_path = preview_data.get("file", "")
        resolved_commit = preview_data.get("resolved_commit", "")

        abs_path = Path(self.project_root) / file_path
        if not abs_path.exists() or not abs_path.is_file():
            return error_result("FILE_NOT_FOUND", f"文件已不存在：{file_path}")

        try:
            current_content = abs_path.read_text(encoding="utf-8")
        except Exception:
            return error_result("FILE_READ_ERROR", f"无法读取文件：{file_path}")

        base_sig = preview_data.get("base_signature", {})
        current_sig = text_signature(current_content)
        if not signatures_equal(current_sig, base_sig):
            return error_result("BASE_CHANGED", f"文件已变化：{file_path}")

        restored_content = self._git_show_file(resolved_commit, file_path)
        if isinstance(restored_content, dict):
            return restored_content

        restored_hash = sha256_text(restored_content)
        stored_hash = preview_data.get("restored_content_hash", "")
        if restored_hash != stored_hash:
            return error_result("CONTENT_MISMATCH", "恢复内容 hash 不一致，preview 可能失效。")

        abs_path.write_text(restored_content, encoding="utf-8")

        diff_text = self._run_git_diff(file_path)
        resulting_diff_hash = diff_hash(diff_text)
        diff_summary = truncate_text(diff_text, 2000)

        return apply_result(
            "restore_file_apply",
            preview_id,
            changed_files=[file_path],
            diff_summary=diff_summary,
            diff_hash=resulting_diff_hash,
            recommended_next_action="manage_git_commit.readiness",
        )

    # ----------------------------------------------------------------
    # 6. revert_preview
    # ----------------------------------------------------------------
    def _revert_preview(self, params: dict[str, Any]) -> dict[str, Any]:
        commit_ref = params.get("commit")
        if not isinstance(commit_ref, str) or not commit_ref.strip():
            return error_result("INVALID_COMMIT", "commit 必须是非空字符串。")
        commit_ref = commit_ref.strip()

        resolved = self._resolve_commit(commit_ref)
        if isinstance(resolved, dict):
            return resolved

        max_chars = bounded_int(params.get("max_chars"), 40000, 1, 80000)

        # Check working tree is clean
        status_res = self._run_git(["status", "--short"], self.project_root)
        status_lines = [line for line in status_res["stdout"].splitlines() if line.strip()]
        if status_lines:
            return {
                "ok": False,
                "error_code": "WORKTREE_NOT_CLEAN",
                "message": "revert_preview 需要干净工作区。",
                "status_short": status_lines,
            }

        # Get current HEAD
        head_res = self._run_git(["rev-parse", "HEAD"], self.project_root)
        current_head = head_res["stdout"].strip() if head_res["code"] == 0 else ""

        # Get commit subject
        log_result = self._run_git(
            ["log", "-1", "--pretty=format:%s", resolved],
            self.project_root,
        )
        subject = log_result["stdout"].strip() if log_result["code"] == 0 else ""

        # Get changed files
        name_result = self._run_git(
            ["show", "--name-status", "--format=", "-r", "-m", resolved],
            self.project_root,
        )
        changed_files: list[str] = []
        if name_result["code"] == 0:
            changed_files = [
                line.split("\t", 1)[1].strip()
                for line in name_result["stdout"].splitlines()
                if "\t" in line
            ]

        allowed_files: list[str] = []
        skipped_files: list[str] = []
        blockers: list[str] = []

        for f in changed_files:
            is_allowed, reason = self.source_review.is_allowed_project_file(self.project_root, f)
            if is_allowed:
                allowed_files.append(f)
            else:
                skipped_files.append(f)
                blockers.append(f"文件 {f} 不在允许修改的白名单内或为 deny path（{reason}）。")

        # Get original patch for summary (only allowed files)
        patch_result = self._run_git(["show", "--no-color", resolved], self.project_root)
        raw_patch = patch_result["stdout"] if patch_result["code"] == 0 else ""
        patch_text, _, _ = self._filter_patch_to_allowed_files(raw_patch, max_chars)

        original_patch_hash = sha256_text(raw_patch)
        reason = params.get("reason")

        can_apply = len(blockers) == 0

        if can_apply:
            preview_id = self._store.create_id()
            created_at = self._store.now_iso()
            expires_at = self._store.expires_at()

            preview_data: dict[str, Any] = {
                "preview_id": preview_id,
                "created_at": created_at,
                "expires_at": expires_at,
                "project_root": self.project_root,
                "mode": "revert_commit",
                "commit": commit_ref,
                "resolved_commit": resolved,
                "subject": subject,
                "current_head": current_head,
                "status_short_snapshot": [],
                "changed_files": changed_files,
                "allowed_files": allowed_files,
                "skipped_files": skipped_files,
                "blockers": [],
                "original_patch_hash": original_patch_hash,
                "reason": reason if isinstance(reason, str) and reason.strip() else "",
            }
            self._write_preview(preview_id, preview_data)

            preview_result = {
                "ok": True,
                "action": "revert_preview",
                "preview_id": preview_id,
                "commit": commit_ref,
                "resolved_commit": resolved,
                "subject": subject,
                "changed_files": changed_files,
                "allowed_files": allowed_files,
                "skipped_files": skipped_files,
                "blockers": [],
                "warnings": [],
                "diff_summary": truncate_text(patch_text, 2000),
                "diff_hash": original_patch_hash,
                "can_apply": True,
                "manual_review_required": True,
                "recommended_next_action": "manage_git.revert_apply",
            }
        else:
            preview_result = {
                "ok": True,
                "action": "revert_preview",
                "commit": commit_ref,
                "resolved_commit": resolved,
                "subject": subject,
                "changed_files": changed_files,
                "allowed_files": allowed_files,
                "skipped_files": skipped_files,
                "blockers": blockers,
                "warnings": [],
                "diff_summary": truncate_text(patch_text, 2000),
                "can_apply": False,
                "manual_review_required": False,
                "recommended_next_action": "fix_blockers",
            }

        return preview_result

    # ----------------------------------------------------------------
    # 7. revert_apply
    # ----------------------------------------------------------------
    def _revert_apply(self, params: dict[str, Any]) -> dict[str, Any]:
        preview_id = params.get("preview_id")
        if not isinstance(preview_id, str) or not preview_id.strip():
            return error_result("INVALID_PREVIEW_ID", "revert_apply 需要非空 preview_id。")
        preview_id = preview_id.strip()
        if not _is_safe_preview_id(preview_id):
            return error_result("INVALID_PREVIEW_ID", "preview_id 包含不安全字符。")

        guard = confirmation_apply_guard(self._store, preview_id, project_root=self.project_root)
        if not guard["ok"]:
            ec = guard["error_code"]
            if ec == "PREVIEW_NOT_FOUND":
                return error_result("PREVIEW_NOT_FOUND", f"preview 不存在：{preview_id}")
            # Preserve original ordering: expiry before project mismatch.
            if confirmation_guard_reports_expired_before_mismatch(guard, self._store.is_expired):
                return {"ok": False, "error_code": "PREVIEW_EXPIRED", "message": "preview 已过期。"}
            if ec == "PROJECT_MISMATCH":
                return {"ok": False, "error_code": "PROJECT_MISMATCH", "message": "preview 与当前项目不匹配。"}
            if ec == "PREVIEW_EXPIRED":
                return {"ok": False, "error_code": "PREVIEW_EXPIRED", "message": "preview 已过期。"}
        preview_data = guard["payload"]
        if preview_data.get("mode") != "revert_commit":
            return error_result("INVALID_MODE", "preview 模式不是 revert_commit。")

        # Check HEAD unchanged
        head_res = self._run_git(["rev-parse", "HEAD"], self.project_root)
        current_head = head_res["stdout"].strip() if head_res["code"] == 0 else ""
        preview_head = preview_data.get("current_head", "")
        if current_head != preview_head:
            return {
                "ok": False,
                "error_code": "HEAD_CHANGED",
                "message": "HEAD 已变化，请重新创建 revert_preview。",
                "current_head": current_head,
                "preview_head": preview_head,
            }

        # Check working tree clean
        status_res = self._run_git(["status", "--short"], self.project_root)
        status_lines = [line for line in status_res["stdout"].splitlines() if line.strip()]
        if status_lines:
            return {
                "ok": False,
                "error_code": "WORKTREE_NOT_CLEAN",
                "message": "revert_apply 需要干净工作区。",
                "status_short": status_lines,
            }

        # Check blockers
        preview_blockers = preview_data.get("blockers", [])
        if preview_blockers:
            return {
                "ok": False,
                "error_code": "PREVIEW_HAS_BLOCKERS",
                "message": "preview 存在 blockers，无法 apply。",
                "blockers": preview_blockers,
            }

        # Verify files still allowed
        resolved_commit = preview_data.get("resolved_commit", "")
        allowed_files = preview_data.get("allowed_files", [])
        new_blockers: list[str] = []
        for f in allowed_files:
            is_allowed, reason = self.source_review.is_allowed_project_file(self.project_root, f)
            if not is_allowed:
                new_blockers.append(f"文件 {f} 已不在允许修改的白名单内（{reason}）。")
        if new_blockers:
            return {
                "ok": False,
                "error_code": "FILES_NO_LONGER_ALLOWED",
                "message": "部分文件已不在允许修改范围。",
                "blockers": new_blockers,
            }

        # Execute revert
        revert_result = self._run_git(
            ["revert", "--no-commit", resolved_commit],
            self.project_root,
        )
        if revert_result["code"] != 0:
            stderr = revert_result.get("stderr", "")
            status_after = self._run_git(["status", "--short"], self.project_root)
            status_after_lines = [line for line in status_after["stdout"].splitlines() if line.strip()]

            # Check for conflict/unmerged indicators
            has_unmerged = any(
                line.startswith("U") or line.startswith("AA") or line.startswith("UU") or "both modified" in line
                for line in status_after_lines
            )
            conflict_files: list[str] = []
            for line in status_after_lines:
                parts = line.split() if len(line) > 3 else []
                if len(parts) >= 2:
                # Some lines may have XY status in first two chars
                    path_part = line[3:].strip() if len(line) > 3 else ""
                    if path_part and "both modified" in line.lower():
                        conflict_files.append(path_part)
                    elif path_part and line[:1] == "U":
                        conflict_files.append(path_part)

            if has_unmerged:
                return {
                    "ok": False,
                    "action": "revert_apply",
                    "error_code": "REVERT_CONFLICT",
                    "message": "revert 产生冲突，需要人工处理。不使用 reset/clean 自动解决。",
                    "preview_id": preview_id,
                    "status_short": status_after_lines,
                    "conflict_files": conflict_files if conflict_files else None,
                    "blockers": ["revert_conflict"],
                }

            return {
                "ok": False,
                "action": "revert_apply",
                "error_code": "REVERT_FAILED",
                "message": f"git revert --no-commit 失败：{stderr[:500]}",
                "preview_id": preview_id,
                "status_short": status_after_lines,
            }

        # Success
        status_after = self._run_git(["status", "--short"], self.project_root)
        status_after_lines = [line for line in status_after["stdout"].splitlines() if line.strip()]

        changed_files_list: list[str] = []
        for line in status_after_lines:
            path_part = line[3:].strip() if len(line) > 3 else ""
            if path_part:
                changed_files_list.append(path_part)

        diff_result = self._run_git(["diff", "--no-color"], self.project_root)
        diff_text = diff_result["stdout"] if diff_result["code"] == 0 else ""
        resulting_diff_hash = diff_hash(diff_text)
        diff_summary = truncate_text(diff_text, 2000)

        subject = preview_data.get("subject", "")
        suggested_message = f"revert: {subject}" if subject else "revert: previous commit"

        return {
            "ok": True,
            "action": "revert_apply",
            "preview_id": preview_id,
            "changed_files": sorted(set(changed_files_list)),
            "status_short": status_after_lines,
            "diff_hash": resulting_diff_hash,
            "diff_summary": diff_summary,
            "recommended_next_action": "manage_git_commit.suggest_commit_message",
            "suggested_message": suggested_message,
            "manual_review_required": True,
        }

    # ----------------------------------------------------------------
    # 8. reconcile_git_history_preview
    # ----------------------------------------------------------------
    def _reconcile_git_history_preview(self, params: dict[str, Any]) -> dict[str, Any]:
        scan_limit = bounded_int(params.get("scan_limit"), 20, 1, 100)
        result = GitHistoryReconcileScanner(self.project_root).scan_unreconciled_candidates(scan_limit=scan_limit)
        if not isinstance(result, dict):
            return {
                "ok": False,
                "action": "reconcile_git_history_preview",
                "error_code": "RECONCILE_PREVIEW_INVALID",
                "message": "reconcile_git_history_preview 返回格式无效。",
            }
        if not result.get("ok"):
            result.setdefault("action", "reconcile_git_history_preview")
            return result
        result["action"] = "reconcile_git_history_preview"
        result.setdefault("preview_only", True)
        result.setdefault("recommended_next_action", {
            "tool": "run_mcp_workflow",
            "action": "manual_git_history_review_required",
            "params": {"workflow": "project_status", "phase": "inspect"},
        })
        return result

    # ----------------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------------
    def _resolve_commit(self, ref: str) -> str | dict:
        result = self._run_git(
            ["rev-parse", "--verify", f"{ref}^{{commit}}"],
            self.project_root,
        )
        if result["code"] != 0:
            return error_result("COMMIT_NOT_FOUND", f"commit 不存在：{ref}")
        return result["stdout"].strip()

    def _git_show_file(self, commit: str, file_path: str) -> str | dict:
        result = self._run_git(
            ["show", f"{commit}:{file_path}"],
            self.project_root,
        )
        if result["code"] != 0:
            stderr = (result.get("stderr") or "").strip()
            if "exists but not" in stderr.lower() or "does not exist" in stderr.lower():
                return {
                    "ok": False,
                    "error_code": "FILE_NOT_IN_COMMIT",
                    "message": f"文件 {file_path} 在 commit {commit[:8]} 中不存在。",
                }
            return {
                "ok": False,
                "error_code": "GIT_SHOW_FAILED",
                "message": f"git show {commit[:8]}:{file_path} 失败：{stderr[:500]}",
            }
        try:
            content = result["stdout"]
            # Check if binary
            if "\0" in content[:4096] if content else False:
                return {
                    "ok": False,
                    "error_code": "BINARY_OR_UNSUPPORTED_FILE",
                    "message": f"文件 {file_path} 在 commit 中为 binary。",
                }
            return content
        except Exception as e:
            return {"ok": False, "error_code": "READ_ERROR", "message": f"读取内容失败：{e}"}

    def _run_git(self, args: list[str], cwd: str) -> dict[str, Any]:
        cmd = args[0] if args else ""
        if cmd not in ALLOWED_GIT_CMDS:
            return {"code": 1, "stdout": "", "stderr": f"不允许的 git 子命令：{cmd}"}
        if cmd == "revert":
            if len(args) != 3 or args[1] != "--no-commit" or not re.fullmatch(r"[0-9a-f]{40}", args[2]):
                return {"code": 1, "stdout": "", "stderr": "revert 只允许 --no-commit 加完整 40 字符 commit hash。"}
        rc, stdout, stderr = _run_git_base(args, cwd)
        return {"code": rc, "stdout": stdout, "stderr": stderr}

    def _run_git_diff(self, file_path: str) -> str:
        result = self._run_git(["diff", "--no-color", "--", file_path], self.project_root)
        return result["stdout"] if result["code"] == 0 else ""

    def _compute_signature(self, content: str) -> dict[str, Any]:
        return text_signature(content)

    def _classify_project_file(self, rel_path: str) -> tuple[bool, str]:
        return self.source_review.is_allowed_project_file(self.project_root, rel_path)

    def _filter_patch_to_allowed_files(self, patch_text: str, max_chars: int) -> tuple[str, list[str], bool]:
        allowed_lines: list[str] = []
        skipped_files: list[str] = []
        current_file = ""
        for line in patch_text.splitlines(keepends=True):
            if line.startswith("diff --git "):
                parts_line = line.split()
                if len(parts_line) >= 4:
                    f = parts_line[3]
                    if f.startswith("b/"):
                        f = f[2:]
                    current_file = f
                    is_allowed, _ = self._classify_project_file(f)
                    if not is_allowed:
                        if f not in skipped_files:
                            skipped_files.append(f)
                        continue
                else:
                    current_file = ""
            elif line.startswith("--- a/") or line.startswith("+++ b/"):
                if current_file:
                    is_allowed_f, _ = self._classify_project_file(current_file)
                    if not is_allowed_f:
                        continue
                allowed_lines.append(line)
                continue
            elif current_file:
                is_allowed_f, _ = self._classify_project_file(current_file)
                if not is_allowed_f:
                    continue
            allowed_lines.append(line)

        result = "".join(allowed_lines)
        truncated = False
        if len(result) > max_chars:
            result = result[:max_chars]
            truncated = True
        return result, skipped_files, truncated

    def _git_error(self, result: dict[str, Any]) -> str:
        stderr = str(result.get("stderr") or "").strip()
        return stderr[:500] if stderr else "Git 命令执行失败。"

    def _write_preview(self, preview_id: str, data: dict[str, Any]) -> None:
        self._store.write(preview_id, data)

    def _read_preview(self, preview_id: str) -> dict[str, Any] | None:
        return self._store.read(preview_id)
