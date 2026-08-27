from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.check_clean_worktree import main


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    assert _git(repo, "init", "-q").returncode == 0
    assert _git(repo, "config", "user.email", "tests@example.invalid").returncode == 0
    assert _git(repo, "config", "user.name", "ColaMeta Tests").returncode == 0
    (repo / "tracked.txt").write_text("clean\n", encoding="utf-8")
    assert _git(repo, "add", "tracked.txt").returncode == 0
    assert _git(repo, "commit", "-qm", "initial").returncode == 0
    return repo


def _status(repo: Path) -> str:
    result = _git(repo, "status", "--porcelain=v1", "--untracked-files=all")
    assert result.returncode == 0
    return result.stdout


def test_clean_worktree_returns_zero_without_mutation(tmp_path: Path, monkeypatch) -> None:
    repo = _repo(tmp_path)
    before = _status(repo)
    monkeypatch.chdir(repo)
    assert main() == 0
    assert _status(repo) == before == ""


@pytest.mark.parametrize("dirty_kind", ["tracked", "staged", "untracked"])
def test_dirty_worktree_returns_one_without_mutation(
    tmp_path: Path, monkeypatch, dirty_kind: str
) -> None:
    repo = _repo(tmp_path)
    if dirty_kind == "tracked":
        (repo / "tracked.txt").write_text("dirty\n", encoding="utf-8")
    elif dirty_kind == "staged":
        (repo / "tracked.txt").write_text("staged\n", encoding="utf-8")
        assert _git(repo, "add", "tracked.txt").returncode == 0
    else:
        (repo / "untracked.txt").write_text("untracked\n", encoding="utf-8")
    before = _status(repo)
    monkeypatch.chdir(repo)
    assert main() == 1
    assert _status(repo) == before


def test_non_git_directory_returns_two(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main() == 2
