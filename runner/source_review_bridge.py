import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from runner._internal_utils import run_git as _run_git
from runner.plan_allowed_files import (
    current_plan_allowed_patterns,
    is_allowed_by_current_plan,
    normalize_plan_allowed_pattern,
)
from runner.path_policy import RunnerPathPolicy
from runner.runner_paths import resolve_project_runner_dir


class SourceReviewError(RuntimeError):
    pass


@dataclass
class SourceReviewPaths:
    project_root: str
    runner_dir: str
    plan_file: str
    state_file: str
    logs_dir: str
    prompts_dir: str
    review_state_file: str
    patch_dir: str


class SourceReviewBridge:
    def __init__(self) -> None:
        self.path_policy = RunnerPathPolicy()

    def _paths(self, project_path: str) -> SourceReviewPaths:
        project_root = os.path.abspath(os.path.expanduser(project_path))
        runner_dir = resolve_project_runner_dir(project_root)
        return SourceReviewPaths(
            project_root=project_root,
            runner_dir=runner_dir,
            plan_file=os.path.join(runner_dir, "plan.json"),
            state_file=os.path.join(runner_dir, "state.json"),
            logs_dir=os.path.join(runner_dir, "logs"),
            prompts_dir=os.path.join(runner_dir, "prompts"),
            review_state_file=os.path.join(runner_dir, "review-state.json"),
            patch_dir=os.path.join(runner_dir, "plan-patches"),
        )

    def get_repo_overview(self, project_path: str, spec: dict[str, Any] | None = None) -> dict[str, Any]:
        paths = self._paths(project_path)
        params = spec or {}
        max_depth = self._bounded_int(params.get("max_depth", 3), default=3, minimum=1, maximum=8)
        max_files = self._bounded_int(params.get("max_files", 300), default=300, minimum=1, maximum=1000)
        git_status = self._run_git(["status", "--short"], cwd=paths.project_root)
        git_log = self._run_git(["log", "--pretty=format:%h%x09%s", "-n", "8"], cwd=paths.project_root)
        recent_commits: list[dict[str, str]] = []
        if git_log["code"] == 0:
            for line in git_log["stdout"].splitlines():
                if "\t" in line:
                    commit_hash, subject = line.split("\t", 1)
                    recent_commits.append({"hash": commit_hash, "subject": subject})

        tree = self._build_repo_file_tree(paths.project_root, max_depth=max_depth, max_files=max_files)
        return {
            "ok": True,
            "project_root": paths.project_root,
            "git_status_short": git_status["stdout"].splitlines() if git_status["code"] == 0 else [],
            "recent_commits": recent_commits,
            "file_tree": tree["files"],
            "file_tree_truncated": tree["truncated"],
            "allowed_source_roots": self._allowed_source_roots(),
            "denied_paths": self._denied_source_patterns(),
        }

    def get_git_status(self, project_path: str) -> dict[str, Any]:
        paths = self._paths(project_path)
        status = self._run_git(["status", "--short"], cwd=paths.project_root)
        if status["code"] != 0:
            raise SourceReviewError(self._git_error_message(status))
        branch = self._run_git(["branch", "--show-current"], cwd=paths.project_root)
        status_lines = [line for line in status["stdout"].splitlines() if line.strip()]
        changed_files: list[str] = []
        untracked_files: list[str] = []
        for line in status_lines:
            path_text = line[3:].strip() if len(line) > 3 else line.strip()
            if " -> " in path_text:
                path_text = path_text.split(" -> ", 1)[1].strip()
            if line.startswith("??"):
                untracked_files.append(path_text)
            else:
                changed_files.append(path_text)
        return {
            "ok": True,
            "status_short": status_lines,
            "changed_files": changed_files,
            "untracked_files": untracked_files,
            "branch": branch["stdout"].strip() if branch["code"] == 0 else None,
        }

    def get_git_diff(self, project_path: str, spec: dict[str, Any] | None = None) -> dict[str, Any]:
        paths = self._paths(project_path)
        params = spec or {}
        file_value = params.get("file")
        mode_raw = params.get("mode")
        include_files_raw = params.get("include_files")
        offset_raw = params.get("offset")
        max_chars = self._bounded_int(params.get("max_chars", 60000), default=60000, minimum=1, maximum=120000)
        cached = bool(params.get("cached", False))
        recommended_page_size = 60000

        if mode_raw is None:
            mode = "file" if file_value is not None else "diff"
            explicit_mode = False
        else:
            if not isinstance(mode_raw, str) or not mode_raw.strip():
                return {"ok": False, "error_code": "INVALID_MODE", "message": "mode 必须是字符串。"}
            mode = mode_raw.strip().lower()
            if mode not in {"diff", "summary", "file", "files", "page"}:
                return {"ok": False, "error_code": "INVALID_MODE", "message": "mode 仅支持 diff、summary、file、files、page。"}
            explicit_mode = True

        offset, offset_error = self._validate_offset(offset_raw)
        if offset_error is not None and mode in {"file", "page"}:
            return offset_error
        if mode == "page" and offset is None:
            offset = 0

        diff_files, untracked_all, status_map, list_error = self._collect_diff_file_lists(
            paths.project_root, cached=cached,
        )
        if list_error is not None:
            return list_error
        assert diff_files is not None
        assert untracked_all is not None
        assert status_map is not None

        if mode == "summary":
            files: list[dict[str, Any]] = []
            skipped_files: list[dict[str, Any]] = []
            total_diff_chars = 0
            total_additions = 0
            total_deletions = 0
            candidate_files = list(diff_files)
            if not cached:
                candidate_files.extend(untracked_all)
            seen: set[str] = set()
            for rel_path in candidate_files:
                if rel_path in seen:
                    continue
                seen.add(rel_path)
                status = status_map.get(rel_path, "??" if rel_path in untracked_all else "M")
                if not self._is_review_allowed_path(paths.project_root, rel_path):
                    skipped_reason = "FILE_NOT_ALLOWED"
                    skipped_files.append(
                        {
                            "file": rel_path,
                            "status": status,
                            "allowed": False,
                            "skipped_reason": skipped_reason,
                        }
                    )
                    files.append(
                        {
                            "file": rel_path,
                            "status": status,
                            "allowed": False,
                            "skipped_reason": skipped_reason,
                            "diff_chars": 0,
                            "additions": 0,
                            "deletions": 0,
                            "binary": False,
                            "untracked": rel_path in untracked_all,
                            "cached": cached,
                            "has_more": False,
                            "recommended_page_size": recommended_page_size,
                        }
                    )
                    continue

                additions, deletions, binary = self._get_file_numstat(paths.project_root, rel_path, cached=cached)
                untracked = rel_path in untracked_all
                diff_chars = 0
                if binary:
                    diff_chars = 0
                elif untracked:
                    synthetic_patch, _ = self._build_untracked_patch(paths.project_root, rel_path, 10_000_000)
                    diff_chars = len(synthetic_patch)
                    if additions == 0 and diff_chars > 0:
                        additions = synthetic_patch.count("\n") - 5 if synthetic_patch.count("\n") > 5 else 0
                else:
                    diff_args = ["diff", "--", rel_path]
                    if cached:
                        diff_args = ["diff", "--cached", "--", rel_path]
                    result = self._run_git(diff_args, cwd=paths.project_root)
                    if result["code"] != 0:
                        return {"ok": False, "error_code": "GIT_DIFF_FAILED", "message": self._git_error_message(result)}
                    diff_chars = len(result["stdout"])

                total_diff_chars += diff_chars
                total_additions += additions
                total_deletions += deletions
                files.append(
                    {
                        "file": rel_path,
                        "status": status,
                        "allowed": True,
                        "skipped_reason": None,
                        "diff_chars": diff_chars,
                        "additions": additions,
                        "deletions": deletions,
                        "binary": binary,
                        "untracked": untracked,
                        "cached": cached,
                        "has_more": diff_chars > recommended_page_size,
                        "recommended_page_size": recommended_page_size,
                    }
                )

            recommended_next_reads = [
                {
                    "mode": "page",
                    "file": item["file"],
                    "offset": 0,
                    "max_chars": recommended_page_size,
                }
                for item in files
                if item.get("allowed") and not item.get("binary") and int(item.get("diff_chars", 0)) > 0
            ]
            result = {
                "ok": True,
                "mode": "summary",
                "cached": cached,
                "file_count": len(files),
                "allowed_file_count": len([f for f in files if f.get("allowed")]),
                "skipped_file_count": len(skipped_files),
                "total_diff_chars": total_diff_chars,
                "total_additions": total_additions,
                "total_deletions": total_deletions,
                "truncated": False,
                "files": files,
                "skipped_files": skipped_files,
                "recommended_next_reads": recommended_next_reads,
            }
            return result

        if mode in {"file", "page"}:
            if not isinstance(file_value, str) or not file_value.strip():
                return {"ok": False, "error_code": "INVALID_FILE", "message": "file 必须是非空字符串。"}
            rel_path = self._normalize_repo_relative_path(file_value)
            if rel_path is None:
                return {"ok": False, "error_code": "FILE_NOT_ALLOWED", "message": "file 必须是项目内相对路径，且不能包含 ..。"}
            if not self._is_review_allowed_path(paths.project_root, rel_path):
                return {"ok": False, "error_code": "FILE_NOT_ALLOWED", "message": "file 不在允许读取的源码白名单内。"}
            try:
                abs_path = self._resolve_project_relative_path(paths.project_root, rel_path)
            except SourceReviewError as e:
                return {"ok": False, "error_code": "FILE_NOT_ALLOWED", "message": str(e)}
            file_exists = abs_path.exists()
            if not file_exists and rel_path not in diff_files:
                return {"ok": False, "error_code": "FILE_NOT_FOUND", "message": f"文件不存在：{rel_path}"}

            diff_args = ["diff", "--", rel_path]
            if cached:
                diff_args = ["diff", "--cached", "--", rel_path]
            result = self._run_git(diff_args, cwd=paths.project_root)
            if result["code"] != 0:
                return {"ok": False, "error_code": "GIT_DIFF_FAILED", "message": self._git_error_message(result)}
            full_diff_text = result["stdout"]

            if not full_diff_text.strip() and not cached:
                untracked_check = self._run_git(
                    ["ls-files", "--others", "--exclude-standard", "--", rel_path],
                    cwd=paths.project_root,
                )
                if untracked_check["code"] == 0 and untracked_check["stdout"].strip():
                    synthetic, _ = self._build_untracked_patch(paths.project_root, rel_path, 10_000_000)
                    if synthetic:
                        full_diff_text = synthetic

            active_offset = offset or 0
            diff_chars = len(full_diff_text)
            if active_offset >= diff_chars:
                payload = {
                    "ok": True,
                    "diff": "",
                    "truncated": False,
                    "file": rel_path,
                    "cached": cached,
                    "offset": active_offset,
                    "max_chars": max_chars,
                    "diff_chars": diff_chars,
                    "returned_chars": 0,
                    "has_more": False,
                    "next_offset": None,
                }
            else:
                sliced = full_diff_text[active_offset : active_offset + max_chars]
                returned_chars = len(sliced)
                next_offset = active_offset + returned_chars
                has_more = next_offset < diff_chars
                payload = {
                    "ok": True,
                    "diff": sliced,
                    "truncated": has_more,
                    "file": rel_path,
                    "cached": cached,
                    "offset": active_offset,
                    "max_chars": max_chars,
                    "diff_chars": diff_chars,
                    "returned_chars": returned_chars,
                    "has_more": has_more,
                    "next_offset": next_offset if has_more else None,
                }
            if explicit_mode:
                payload["mode"] = mode
            return payload

        include_files: list[str] | None = None
        if mode == "files":
            normalized_files, files_error = self._normalize_include_files(include_files_raw)
            if files_error is not None:
                return files_error
            include_files = normalized_files
            assert include_files is not None

        target_files = list(diff_files)
        if mode == "files" and include_files is not None:
            target_files = include_files

        allowed_files: list[str] = []
        skipped_files: list[str] = []
        for rel_path in target_files:
            if not self._is_review_allowed_path(paths.project_root, rel_path):
                if mode == "files":
                    return {
                        "ok": False,
                        "error_code": "FILE_NOT_ALLOWED",
                        "message": f"文件不在允许读取范围内：{rel_path}",
                    }
                skipped_files.append(rel_path)
                continue
            allowed_files.append(rel_path)

        diff_parts: list[str] = []
        truncated = False
        remaining = max_chars
        next_read: dict[str, Any] | None = None
        included_untracked: list[str] = []
        included_files: list[str] = []
        has_more_files = False

        for rel_path in allowed_files:
            if remaining <= 0:
                truncated = True
                has_more_files = True
                if next_read is None:
                    next_read = {"mode": "page", "file": rel_path, "offset": 0, "max_chars": recommended_page_size}
                break
            diff_args = ["diff", "--", rel_path]
            if cached:
                diff_args = ["diff", "--cached", "--", rel_path]
            result = self._run_git(diff_args, cwd=paths.project_root)
            if result["code"] != 0:
                return {"ok": False, "error_code": "GIT_DIFF_FAILED", "message": self._git_error_message(result)}
            chunk = result["stdout"]
            if not chunk and not cached and rel_path in untracked_all:
                synthetic_patch, _ = self._build_untracked_patch(paths.project_root, rel_path, 10_000_000)
                chunk = synthetic_patch
                if chunk:
                    included_untracked.append(rel_path)
            if not chunk:
                continue
            included_files.append(rel_path)
            if len(chunk) > remaining:
                diff_parts.append(chunk[:remaining])
                truncated = True
                has_more_files = True
                if next_read is None:
                    next_read = {"mode": "page", "file": rel_path, "offset": remaining, "max_chars": recommended_page_size}
                break
            diff_parts.append(chunk)
            remaining -= len(chunk)

        if mode == "diff" and not cached:
            for rel_path in untracked_all:
                if rel_path in target_files:
                    continue
                if not self._is_review_allowed_path(paths.project_root, rel_path):
                    if rel_path not in skipped_files:
                        skipped_files.append(rel_path)
                    continue
                if remaining <= 0:
                    truncated = True
                    break
                patch, patch_truncated = self._build_untracked_patch(paths.project_root, rel_path, remaining)
                if not patch:
                    continue
                if patch_truncated:
                    truncated = True
                if len(patch) > remaining:
                    diff_parts.append(patch[:remaining])
                    truncated = True
                    included_untracked.append(rel_path)
                    remaining = 0
                    break
                diff_parts.append(patch)
                included_untracked.append(rel_path)
                remaining -= len(patch)

        payload = {
            "ok": True,
            "diff": "".join(diff_parts),
            "truncated": truncated,
            "file": None,
            "cached": cached,
            "allowed_file_count": len(allowed_files),
            "skipped_file_count": len(skipped_files),
            "skipped_files": skipped_files,
            "included_untracked_files": included_untracked,
            "untracked_file_count": len(included_untracked),
        }
        if explicit_mode:
            payload["mode"] = mode
        if mode == "files":
            payload["included_files"] = included_files
            payload["has_more_files"] = has_more_files
            payload["next_read"] = next_read
        return payload

    def _validate_offset(self, value: Any) -> tuple[int | None, dict[str, Any] | None]:
        if value is None:
            return None, None
        if isinstance(value, bool):
            return None, {"ok": False, "error_code": "INVALID_OFFSET", "message": "offset 必须是大于等于 0 的整数。"}
        try:
            parsed = int(value)
        except Exception:
            return None, {"ok": False, "error_code": "INVALID_OFFSET", "message": "offset 必须是大于等于 0 的整数。"}
        if parsed < 0:
            return None, {"ok": False, "error_code": "INVALID_OFFSET", "message": "offset 必须是大于等于 0 的整数。"}
        return parsed, None

    def _normalize_include_files(self, include_files_raw: Any) -> tuple[list[str] | None, dict[str, Any] | None]:
        if not isinstance(include_files_raw, list) or len(include_files_raw) == 0:
            return None, {"ok": False, "error_code": "INVALID_FILES", "message": "include_files 必须是非空数组。"}
        normalized: list[str] = []
        seen: set[str] = set()
        for item in include_files_raw:
            if not isinstance(item, str) or not item.strip():
                return None, {"ok": False, "error_code": "INVALID_FILES", "message": "include_files 元素必须是非空字符串。"}
            rel_path = self._normalize_repo_relative_path(item)
            if rel_path is None:
                return None, {"ok": False, "error_code": "INVALID_FILES", "message": "include_files 仅支持项目内相对路径。"}
            if rel_path in seen:
                continue
            normalized.append(rel_path)
            seen.add(rel_path)
        if len(normalized) == 0:
            return None, {"ok": False, "error_code": "INVALID_FILES", "message": "include_files 不能为空。"}
        return normalized, None

    def _collect_diff_file_lists(
        self,
        project_root: str,
        *,
        cached: bool,
    ) -> tuple[list[str] | None, list[str] | None, dict[str, str] | None, dict[str, Any] | None]:
        list_args = ["diff", "--name-only"]
        if cached:
            list_args = ["diff", "--cached", "--name-only"]
        list_result = self._run_git(list_args, cwd=project_root)
        if list_result["code"] != 0:
            return None, None, None, {"ok": False, "error_code": "GIT_DIFF_FAILED", "message": self._git_error_message(list_result)}
        diff_files = [line.strip() for line in list_result["stdout"].splitlines() if line.strip()]

        untracked_all: list[str] = []
        if not cached:
            untracked_result = self._run_git(
                ["ls-files", "--others", "--exclude-standard"],
                cwd=project_root,
            )
            if untracked_result["code"] == 0:
                untracked_all = [line.strip() for line in untracked_result["stdout"].splitlines() if line.strip()]

        status_result = self._run_git(["status", "--short"], cwd=project_root)
        status_map: dict[str, str] = {}
        if status_result["code"] == 0:
            for line in status_result["stdout"].splitlines():
                if not line.strip():
                    continue
                status_code = line[:2].strip()
                rel_path = line[3:].strip() if len(line) > 3 else line.strip()
                if " -> " in rel_path:
                    rel_path = rel_path.split(" -> ", 1)[1].strip()
                if rel_path:
                    status_map[rel_path] = status_code or "M"
        return diff_files, untracked_all, status_map, None

    def _get_file_numstat(self, project_root: str, rel_path: str, *, cached: bool) -> tuple[int, int, bool]:
        args = ["diff", "--numstat", "--", rel_path]
        if cached:
            args = ["diff", "--cached", "--numstat", "--", rel_path]
        result = self._run_git(args, cwd=project_root)
        if result["code"] != 0:
            return 0, 0, False
        line = ""
        for raw in result["stdout"].splitlines():
            text = raw.strip()
            if text:
                line = text
                break
        if not line:
            return 0, 0, False
        parts = line.split("\t")
        if len(parts) < 3:
            return 0, 0, False
        add_raw, del_raw = parts[0], parts[1]
        binary = add_raw == "-" or del_raw == "-"
        additions = 0 if binary else int(add_raw) if add_raw.isdigit() else 0
        deletions = 0 if binary else int(del_raw) if del_raw.isdigit() else 0
        return additions, deletions, binary

    def _build_untracked_patch(self, project_root: str, rel_path: str, max_chars: int) -> tuple[str, bool]:
        abs_path = Path(project_root) / rel_path
        if not abs_path.exists() or not abs_path.is_file():
            return "", False
        read_result = self._read_text_file_limited(abs_path)
        if not read_result.get("ok"):
            return "", False
        content = str(read_result["content"])
        lines = content.splitlines()
        header = f"diff --git a/{rel_path} b/{rel_path}\nnew file mode 100644\n--- /dev/null\n+++ b/{rel_path}\n"
        hunk = f"@@ -0,0 +1,{len(lines)} @@\n"
        if len(header) + len(hunk) > max_chars:
            return header + hunk, True
        body_parts: list[str] = []
        body_remaining = max_chars - len(header) - len(hunk)
        truncated = bool(read_result.get("truncated"))
        for line in lines:
            plus_line = f"+{line}\n"
            if len(plus_line) > body_remaining:
                truncated = True
                break
            body_parts.append(plus_line)
            body_remaining -= len(plus_line)
        return header + hunk + "".join(body_parts), truncated

    def get_git_log(self, project_path: str, spec: dict[str, Any] | None = None) -> dict[str, Any]:
        paths = self._paths(project_path)
        params = spec or {}
        limit = self._bounded_int(params.get("limit", 12), default=12, minimum=1, maximum=50)
        result = self._run_git(["log", "--pretty=format:%h%x09%s", "-n", str(limit)], cwd=paths.project_root)
        if result["code"] != 0:
            message = self._git_error_message(result)
            if "no commits yet" in message.lower() or "does not have any commits yet" in message.lower():
                return {
                    "ok": True,
                    "limit": limit,
                    "commits": [],
                    "initial_commit": True,
                }
            raise SourceReviewError(message)
        commits: list[dict[str, str]] = []
        for line in result["stdout"].splitlines():
            if "\t" in line:
                commit_hash, subject = line.split("\t", 1)
            else:
                parts = line.split(" ", 1)
                commit_hash = parts[0]
                subject = parts[1] if len(parts) > 1 else ""
            commits.append({"hash": commit_hash, "subject": subject})
        return {
            "ok": True,
            "limit": limit,
            "commits": commits,
        }

    def get_source_file(self, project_path: str, spec: dict[str, Any]) -> dict[str, Any]:
        paths = self._paths(project_path)
        file_value = spec.get("file")
        if not isinstance(file_value, str) or not file_value.strip():
            return self._source_error("INVALID_FILE", "file 必须是非空字符串。")
        rel_path = self._normalize_repo_relative_path(file_value)
        if rel_path is None:
            return self._source_error("FILE_NOT_ALLOWED", "file 必须是项目内相对路径，且不能包含 ..。")
        if not self._is_review_allowed_path(paths.project_root, rel_path):
            return self._source_error("FILE_NOT_ALLOWED", "file 不在允许读取的源码白名单内。")

        try:
            abs_path = self._resolve_project_relative_path(paths.project_root, rel_path)
        except SourceReviewError as e:
            return self._source_error("FILE_NOT_ALLOWED", str(e))
        if not abs_path.exists() or not abs_path.is_file():
            return self._source_error("FILE_NOT_FOUND", f"文件不存在：{rel_path}")

        max_chars = self._bounded_int(spec.get("max_chars", 30000), default=30000, minimum=1, maximum=100000)
        start_line = self._optional_positive_int(spec.get("start_line"))
        end_line = self._optional_positive_int(spec.get("end_line"))
        read_result = self._read_text_file_limited(abs_path)
        if not read_result.get("ok"):
            return read_result
        text = str(read_result["content"])
        lines = text.splitlines()
        line_count = len(lines)
        if line_count == 0:
            if (start_line is not None and start_line != 1) or (end_line is not None and end_line != 1):
                return self._source_error("INVALID_LINE_RANGE", "空文件没有可读取的行范围。")
            return {
                "ok": True,
                "file": rel_path,
                "line_count": 0,
                "start_line": 0,
                "end_line": 0,
                "content": "",
                "truncated": bool(read_result.get("truncated")),
                "empty_file": True,
            }

        start = start_line or 1
        end = end_line or line_count
        if start > end:
            return self._source_error("INVALID_LINE_RANGE", "start_line 必须小于或等于 end_line。")
        start = max(1, min(start, line_count))
        end = max(start, min(end, line_count))
        selected = "\n".join(lines[start - 1:end])
        truncated = bool(read_result.get("truncated"))
        if len(selected) > max_chars:
            selected = selected[:max_chars]
            truncated = True
        return {
            "ok": True,
            "file": rel_path,
            "line_count": line_count,
            "start_line": start,
            "end_line": end,
            "content": selected,
            "truncated": truncated,
            "empty_file": False,
        }

    def search_source(self, project_path: str, spec: dict[str, Any]) -> dict[str, Any]:
        paths = self._paths(project_path)
        query = spec.get("query")
        if not isinstance(query, str) or not query.strip():
            return self._source_error("INVALID_QUERY", "query 必须是非空字符串。")
        query = query.strip()
        if len(query) > 120:
            return self._source_error("INVALID_QUERY", "query 最长 120 个字符。")
        max_results = self._bounded_int(spec.get("max_results", 30), default=30, minimum=1, maximum=100)
        results: list[dict[str, Any]] = []
        query_lower = query.lower()
        truncated = False
        for rel_path, abs_path in self._iter_allowed_source_files(paths.project_root):
            read_result = self._read_text_file_limited(abs_path)
            if not read_result.get("ok"):
                continue
            for line_no, line in enumerate(str(read_result["content"]).splitlines(), start=1):
                if query_lower not in line.lower():
                    continue
                text = line.strip()
                if len(text) > 240:
                    text = text[:240] + "..."
                results.append({"file": rel_path, "line": line_no, "text": text})
                if len(results) >= max_results:
                    truncated = True
                    return {
                        "ok": True,
                        "query": query,
                        "results": results,
                        "truncated": truncated,
                    }
        return {
            "ok": True,
            "query": query,
            "results": results,
            "truncated": truncated,
        }

    def _allowed_source_roots(self) -> list[str]:
        return self.path_policy.allowed_source_roots()

    def _denied_source_patterns(self) -> list[str]:
        return self.path_policy.denied_source_patterns()

    def _is_denied_source_path(self, rel_path: str) -> bool:
        return self.path_policy.is_denied_source_path(rel_path)

    def _is_allowed_source_path(self, rel_path: str) -> bool:
        return self.path_policy.is_allowed_source_path(rel_path)

    def _is_review_allowed_path(self, project_root: str, rel_path: str) -> bool:
        normalized = self._normalize_repo_relative_path(rel_path)
        if normalized is None:
            return False
        if self._is_denied_source_path(normalized):
            return False
        if self._is_allowed_source_path(normalized):
            return True
        return self._is_allowed_by_current_plan(project_root, normalized)

    def _is_allowed_by_current_plan(self, project_root: str, rel_path: str) -> bool:
        return is_allowed_by_current_plan(
            project_root,
            rel_path,
            deny_predicate=self._is_denied_source_path,
        )

    def _current_plan_allowed_patterns(self, project_root: str) -> list[str]:
        return current_plan_allowed_patterns(project_root)

    def _normalize_plan_allowed_pattern(self, value: Any) -> str | None:
        return normalize_plan_allowed_pattern(value)

    def is_allowed_project_file(self, project_path: str, rel_path: str) -> tuple[bool, str]:
        try:
            self.validate_project_file_for_patch(project_path, rel_path)
            return True, ""
        except SourceReviewError as e:
            return False, str(e)

    def validate_project_file_for_patch(self, project_path: str, rel_path: str) -> None:
        paths = self._paths(project_path)
        normalized = self._normalize_repo_relative_path(rel_path)
        if normalized is None:
            raise SourceReviewError("路径必须是项目内相对路径，不能包含 .. 或为绝对路径。")
        if self._is_denied_source_path(normalized):
            raise SourceReviewError("文件路径不在允许修改的范围内（被 deny list 阻止）。")
        if not self._is_allowed_source_path(normalized):
            if not self._is_allowed_by_current_plan(project_path, normalized):
                raise SourceReviewError("文件路径不在允许修改的源码白名单内。")
        self._resolve_project_relative_path(paths.project_root, normalized)

    def _normalize_repo_relative_path(self, raw_path: str) -> str | None:
        value = raw_path.strip().replace("\\", "/")
        if value.startswith("./"):
            value = value[2:]
        pure = PurePosixPath(value)
        if pure.is_absolute():
            return None
        if any(part in ("", ".", "..") for part in pure.parts):
            return None
        return str(pure)

    def _resolve_project_relative_path(self, project_root: str, rel_path: str) -> Path:
        root = Path(project_root).resolve()
        candidate = (root / rel_path).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise SourceReviewError("路径解析后越过项目根目录。") from exc
        return candidate

    def _iter_allowed_source_files(self, project_root: str):
        root = Path(project_root).resolve()
        for current_dir, dir_names, file_names in os.walk(root):
            current_path = Path(current_dir)
            safe_dirs: list[str] = []
            for dir_name in sorted(dir_names):
                rel_dir = self._normalize_path(str((current_path / dir_name).resolve().relative_to(root)))
                if self._is_denied_source_path(rel_dir) or self._is_denied_source_path(rel_dir + "/x"):
                    continue
                safe_dirs.append(dir_name)
            dir_names[:] = safe_dirs
            for file_name in sorted(file_names):
                abs_path = (current_path / file_name).resolve()
                try:
                    rel_path = self._normalize_path(str(abs_path.relative_to(root)))
                except ValueError:
                    continue
                if self._is_denied_source_path(rel_path) or not self._is_allowed_source_path(rel_path):
                    continue
                yield rel_path, abs_path

    def _read_text_file_limited(self, path: Path, max_bytes: int = 2_000_000) -> dict[str, Any]:
        try:
            size = path.stat().st_size
            if size > max_bytes:
                return self._source_error("FILE_TOO_LARGE", "文件过大，已拒绝读取。")
            with path.open("rb") as handle:
                head = handle.read(4096)
            if b"\0" in head:
                return self._source_error("FILE_NOT_TEXT", "文件不是文本文件。")
            content = path.read_text(encoding="utf-8")
            return {"ok": True, "content": content, "truncated": False}
        except UnicodeDecodeError:
            return self._source_error("FILE_NOT_TEXT", "文件不是 UTF-8 文本文件。")
        except Exception as e:
            return self._source_error("FILE_READ_ERROR", f"读取文件失败：{e}")

    def _source_error(self, error_code: str, message: str) -> dict[str, Any]:
        return {
            "ok": False,
            "error_code": error_code,
            "message": message,
        }

    def _normalize_path(self, path: str) -> str:
        normalized = path.strip().replace("\\", "/").replace(os.sep, "/")
        if normalized.startswith("./"):
            return normalized[2:]
        return normalized

    def _bounded_int(self, value: Any, default: int, minimum: int, maximum: int) -> int:
        if isinstance(value, bool):
            return default
        try:
            parsed = int(value)
        except Exception:
            return default
        return max(minimum, min(parsed, maximum))

    def _optional_positive_int(self, value: Any) -> int | None:
        if value is None or isinstance(value, bool):
            return None
        try:
            parsed = int(value)
        except Exception:
            return None
        return parsed if parsed > 0 else None

    def _build_repo_file_tree(self, project_root: str, max_depth: int, max_files: int) -> dict[str, Any]:
        root = Path(project_root).resolve()
        files: list[str] = []
        truncated = False
        for current_dir, dir_names, file_names in os.walk(root):
            current_path = Path(current_dir)
            try:
                rel_dir = self._normalize_path(str(current_path.resolve().relative_to(root)))
            except ValueError:
                continue
            depth = 0 if rel_dir == "." else len(PurePosixPath(rel_dir).parts)
            safe_dirs: list[str] = []
            for dir_name in sorted(dir_names):
                dir_abs = (current_path / dir_name).resolve()
                try:
                    dir_rel = self._normalize_path(str(dir_abs.relative_to(root)))
                except ValueError:
                    continue
                if self._is_denied_source_path(dir_rel) or self._is_denied_source_path(dir_rel + "/x"):
                    continue
                if depth < max_depth:
                    safe_dirs.append(dir_name)
            dir_names[:] = safe_dirs
            for file_name in sorted(file_names):
                file_abs = (current_path / file_name).resolve()
                try:
                    rel_path = self._normalize_path(str(file_abs.relative_to(root)))
                except ValueError:
                    continue
                if self._is_denied_source_path(rel_path):
                    continue
                files.append(rel_path)
                if len(files) >= max_files:
                    truncated = True
                    return {"files": files, "truncated": truncated}
        return {"files": files, "truncated": truncated}

    def _git_error_message(self, result: dict[str, Any]) -> str:
        stderr = str(result.get("stderr") or "").strip()
        if "Not a git repository" in stderr:
            return "当前项目不是 Git 仓库。"
        return stderr[:500] if stderr else "Git 只读命令执行失败。"

    def _run_git(self, args: list[str], cwd: str) -> dict[str, Any]:
        rc, stdout, stderr = _run_git(args, cwd)
        return {"code": rc, "stdout": stdout, "stderr": stderr}
