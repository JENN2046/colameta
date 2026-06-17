from pathlib import PurePosixPath

from runner.file_policy_rules import (
    DENIED_PATH_PART_NAMES,
    EXACT_ALLOWED_ROOT_FILES,
    commit_allowed_patterns,
    commit_blocked_patterns,
    commit_excluded_patterns,
    denied_source_patterns,
    source_allowed_patterns,
)
from runner.path_glob import match as glob_match, normalize as glob_normalize


class RunnerPathPolicy:
    def allowed_source_roots(self) -> list[str]:
        return list(source_allowed_patterns())

    def denied_source_patterns(self) -> list[str]:
        return list(denied_source_patterns())

    def commit_blocked_patterns(self) -> list[str]:
        return list(commit_blocked_patterns())

    def commit_excluded_patterns(self) -> list[str]:
        return list(commit_excluded_patterns())

    def commit_allowed_patterns(self) -> list[str]:
        return list(commit_allowed_patterns())

    def match_pattern(self, path: str, pattern: str) -> bool:
        return glob_match(pattern, path)

    def is_denied_source_path(self, rel_path: str) -> bool:
        normalized = self._normalize_path(rel_path)
        if not normalized:
            return True
        parts = PurePosixPath(normalized).parts
        if any(part in DENIED_PATH_PART_NAMES for part in parts):
            return True
        return self._matches_any(normalized, denied_source_patterns())

    def is_allowed_source_path(self, rel_path: str) -> bool:
        normalized = self._normalize_path(rel_path)
        if not normalized:
            return False
        if self.is_denied_source_path(normalized):
            return False
        if normalized in EXACT_ALLOWED_ROOT_FILES:
            return True
        return self._matches_any(normalized, source_allowed_patterns())

    def is_commit_blocked_path(self, rel_path: str) -> bool:
        normalized = self._normalize_path(rel_path)
        if not normalized:
            return True
        return self._matches_any(normalized.lower(), [p.lower() for p in commit_blocked_patterns()])

    def is_commit_excluded_path(self, rel_path: str) -> bool:
        normalized = self._normalize_path(rel_path)
        if not normalized:
            return True
        return self._matches_any(normalized.lower(), [p.lower() for p in commit_excluded_patterns()])

    def is_commit_allowed_path(self, rel_path: str) -> bool:
        normalized = self._normalize_path(rel_path)
        if not normalized:
            return False
        if self.is_commit_blocked_path(normalized):
            return False
        if self.is_commit_excluded_path(normalized):
            return False
        return self._matches_any(normalized, commit_allowed_patterns())

    def is_untracked_expandable_path(self, rel_path: str) -> bool:
        return self.is_commit_allowed_path(rel_path)

    def _matches_any(self, path: str, patterns: list[str] | tuple[str, ...]) -> bool:
        return any(self.match_pattern(path, pattern) for pattern in patterns)

    def _normalize_path(self, path: str) -> str:
        return glob_normalize(path or "")
