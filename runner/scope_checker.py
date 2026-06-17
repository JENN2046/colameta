import os

from adapters.git_adapter import GitAdapter
from runner.path_glob import match_any, normalize as normalize_path
from runner.runner_paths import is_project_runner_path
from schemas.plan import BuildVersion
from schemas.result import ScopeCheckResult


class ScopeChecker:
    def __init__(self):
        self.git_adapter = GitAdapter()

    def check_scope(self, version: BuildVersion, project_root: str) -> ScopeCheckResult:
        allowed_files = [normalize_path(pattern) for pattern in version.allowed_files]
        forbidden_files = [normalize_path(pattern) for pattern in version.forbidden_files]
        skip_message = "未检测到 Git 仓库，已跳过文件越界检查。"

        if not self.git_adapter.is_git_repository(project_root):
            return ScopeCheckResult(
                status="NOT_CHECKED",
                allowed_files=allowed_files,
                forbidden_files=forbidden_files,
                git_diff_name_only_output=skip_message,
                git_diff_stat_output=skip_message,
            )

        name_only = self.git_adapter.diff_name_only(project_root)
        diff_stat = self.git_adapter.diff_stat(project_root)
        if name_only.exit_code != 0 or diff_stat.exit_code != 0:
            message = "未检测到 Git 仓库，已跳过文件越界检查。"
            return ScopeCheckResult(
                status="NOT_CHECKED",
                allowed_files=allowed_files,
                forbidden_files=forbidden_files,
                git_diff_name_only_output=name_only.stderr.strip() or message,
                git_diff_stat_output=diff_stat.stderr.strip() or message,
            )

        raw_changed_files = [
            self._normalize_path(line)
            for line in name_only.stdout.splitlines()
            if line.strip()
        ]
        ignored_runtime_files, scope_checked_files = self._split_runtime_files(raw_changed_files)
        changed_outside_allowed_files = [
            path for path in scope_checked_files
            if not self._matches_any(path, allowed_files)
        ]
        changed_forbidden_files = [
            path for path in scope_checked_files
            if self._matches_any(path, forbidden_files)
        ]
        status = "FAILED" if changed_outside_allowed_files or changed_forbidden_files else "PASSED"

        return ScopeCheckResult(
            status=status,
            allowed_files=allowed_files,
            forbidden_files=forbidden_files,
            raw_changed_files=raw_changed_files,
            ignored_runtime_files=ignored_runtime_files,
            scope_checked_files=scope_checked_files,
            outside_allowed_files=changed_outside_allowed_files,
            forbidden_changed_files=changed_forbidden_files,
            changed_files=raw_changed_files,
            changed_outside_allowed_files=changed_outside_allowed_files,
            changed_forbidden_files=changed_forbidden_files,
            git_diff_name_only_output=name_only.stdout,
            git_diff_stat_output=diff_stat.stdout,
        )

    def get_diff_stat(self, project_root: str) -> str:
        warning = "未检测到 Git 仓库，已跳过文件越界检查。"
        if not self.git_adapter.is_git_repository(project_root):
            return warning

        result = self.git_adapter.diff_stat(project_root)
        if result.exit_code != 0:
            return warning

        output = result.stdout.strip()
        if not output:
            return "当前没有 Git Diff。"
        return output

    def _normalize_path(self, path: str) -> str:
        return normalize_path(path)

    def _matches_any(self, path: str, patterns: list[str]) -> bool:
        return match_any(path, patterns)

    def _is_runner_runtime_file(self, path: str) -> bool:
        normalized = self._normalize_path(path)
        return is_project_runner_path(normalized)

    def _split_runtime_files(self, paths: list[str]) -> tuple[list[str], list[str]]:
        ignored_runtime_files: list[str] = []
        scope_checked_files: list[str] = []
        for path in paths:
            if self._is_runner_runtime_file(path):
                ignored_runtime_files.append(path)
            else:
                scope_checked_files.append(path)
        return ignored_runtime_files, scope_checked_files
