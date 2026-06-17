from dataclasses import dataclass
from typing import Optional

from runner._internal_utils import run_git as _run_git_base


@dataclass
class GitCommandResult:
    exit_code: int
    stdout: str
    stderr: str


class GitAdapter:
    def _run_git(self, args: list[str], cwd: str) -> GitCommandResult:
        rc, stdout, stderr = _run_git_base(args, cwd)
        return GitCommandResult(exit_code=rc, stdout=stdout, stderr=stderr)

    def is_git_repository(self, project_root: str) -> bool:
        result = self._run_git(["rev-parse", "--is-inside-work-tree"], cwd=project_root)
        return result.exit_code == 0 and result.stdout.strip() == "true"

    def diff_name_only(self, project_root: str) -> GitCommandResult:
        return self._run_git(["diff", "--name-only"], cwd=project_root)

    def diff_stat(self, project_root: str) -> GitCommandResult:
        return self._run_git(["diff", "--stat"], cwd=project_root)
