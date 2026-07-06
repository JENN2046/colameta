from __future__ import annotations

import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from runner.mcp_git_remote import MCPGitRemoteManager


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _init_repo_with_origin(tmp_path: Path, *, branch: str = "main", upstream: bool = False) -> Path:
    origin = tmp_path / "origin.git"
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True, text=True)
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True, text=True)
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "checkout", "-B", branch)
    _git(repo, "remote", "add", "origin", str(origin))
    (repo / "README.md").write_text("one\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "initial")
    if upstream:
        _git(repo, "push", "-u", "origin", branch)
        (repo / "README.md").write_text("two\n", encoding="utf-8")
        _git(repo, "add", "README.md")
        _git(repo, "commit", "-m", "local change")
    return repo


def test_push_preview_rejects_protected_main_branch(tmp_path: Path) -> None:
    repo = _init_repo_with_origin(tmp_path, branch="main", upstream=True)

    result = MCPGitRemoteManager(str(repo)).push_preview(reason="test")

    assert result["ok"] is False
    assert result["error_code"] == "protected_branch"
    assert "protected_branch" in result["blockers"]


def test_push_preview_rejects_non_allowlisted_feature_branch(tmp_path: Path) -> None:
    repo = _init_repo_with_origin(tmp_path, branch="feature/example", upstream=False)

    result = MCPGitRemoteManager(str(repo)).push_preview(reason="test")

    assert result["ok"] is False
    assert result["error_code"] == "branch_not_allowed"
    assert "branch_not_allowed" in result["blockers"]


def test_push_preview_allows_codex_branch_policy_to_reach_preview(tmp_path: Path) -> None:
    repo = _init_repo_with_origin(tmp_path, branch="codex/example", upstream=False)

    result = MCPGitRemoteManager(str(repo)).push_preview(reason="test")

    assert result["ok"] is True
    assert result["push_mode"] == "set_upstream"
    assert result["remote_name"] == "origin"


def test_push_apply_rechecks_protected_branch_policy(tmp_path: Path) -> None:
    repo = _init_repo_with_origin(tmp_path, branch="main", upstream=True)
    manager = MCPGitRemoteManager(str(repo))
    state = manager._collect_push_state()
    preview_id = manager._generate_preview_id()

    manager._write_preview(
        preview_id,
        {
            "action": "push_preview",
            "project_root": str(repo),
            "preview_id": preview_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
            "push_mode": "upstream",
            "branch": state["branch"],
            "upstream": state["upstream"],
            "remote_name": state["remote_name"],
            "remote_url_redacted": state["remote_url_redacted"],
            "head": state["head"],
            "ahead": state["ahead"],
            "behind": state["behind"],
            "blocking_git_status_short_hash": state["blocking_git_status_short_hash"],
        },
    )

    result = manager.push_apply(preview_id)

    assert result["ok"] is False
    assert result["error_code"] == "PROTECTED_BRANCH"
