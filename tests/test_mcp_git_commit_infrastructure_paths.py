from __future__ import annotations

import subprocess
from pathlib import Path

from runner.mcp_git_commit import MCPGitCommitManager


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )


def test_commit_readiness_accepts_tracked_and_untracked_systemd_files(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    target = project / "systemd/system/app.target"
    target.parent.mkdir(parents=True)
    target.write_text("[Unit]\nDescription=Initial\n", encoding="utf-8")
    _git(project, "init", "-q")
    _git(project, "config", "user.name", "ColaMeta Test")
    _git(project, "config", "user.email", "colameta@example.invalid")
    _git(project, "add", "systemd/system/app.target")
    _git(project, "commit", "-q", "-m", "initial")

    target.write_text("[Unit]\nDescription=Updated\n", encoding="utf-8")
    service = project / "systemd/system/app.service"
    service.write_text("[Service]\nExecStart=/bin/true\n", encoding="utf-8")
    logrotate = project / "systemd/logrotate/app"
    logrotate.parent.mkdir(parents=True)
    logrotate.write_text("/tmp/app.log { missingok }\n", encoding="utf-8")

    selected = [
        "systemd/logrotate/app",
        "systemd/system/app.service",
        "systemd/system/app.target",
    ]
    readiness = MCPGitCommitManager(str(project)).readiness(
        include_files=selected,
        include_diff_summary=False,
    )

    assert readiness["ok"] is True
    assert readiness["files_to_commit"] == selected
    assert readiness["file_selection"]["selected_files"] == selected
