from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from runner.mcp_github_delivery import MCPGitHubDeliveryManager
from runner.mcp_server import MCPPlanningBridgeServer
from runner.operator_artifact_binding import canonical_artifact_digest


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=True,
    )


class FakeCommands:
    def __init__(self, project: Path, head: str):
        self.project = project
        self.remote_head = head
        self.default_branch = "main"
        self.authorized = True
        self.pull_requests: list[dict[str, object]] = []
        self.create_calls = 0
        self.verify_create = True
        self.create_return_code = 0
        self.base_head = head
        self.workflow_runs: list[dict[str, object]] = [
            {
                "id": 700,
                "workflow_id": 70,
                "name": "CI",
                "event": "pull_request",
                "head_sha": head,
                "run_attempt": 1,
                "status": "completed",
                "conclusion": "success",
            }
        ]
        self.jobs: list[dict[str, object]] = [
            {
                "id": 701,
                "name": "tests",
                "status": "completed",
                "conclusion": "success",
            }
        ]
        self.check_runs: list[dict[str, object]] = []
        self.commit_statuses: list[dict[str, object]] = []
        self.commit_status_pages: list[list[dict[str, object]]] | None = None
        self.review_threads_pages: list[list[dict[str, object]]] = [[]]
        self.review_pages: list[list[dict[str, object]]] = [[]]
        self.review_decision = ""
        self.mergeable = "MERGEABLE"
        self.compare_status = "ahead"
        self.pr_view_override: dict[str, object] | None = None
        self.ready_calls = 0
        self.merge_calls = 0
    def __call__(
        self, args: list[str], cwd: str
    ) -> subprocess.CompletedProcess[str]:
        if args[:2] == ["git", "ls-remote"]:
            branch_ref = args[-1]
            return self._completed(
                args, 0, f"{self.remote_head}\t{branch_ref}\n"
            )
        if args[:2] == ["gh", "--version"]:
            return self._completed(args, 0, "gh version 2.45.0\n")
        if args[:3] == ["gh", "auth", "status"]:
            return self._completed(args, 0 if self.authorized else 1)
        if args[:3] == ["gh", "repo", "view"]:
            return self._completed(
                args,
                0,
                json.dumps({"defaultBranchRef": {"name": self.default_branch}}),
            )
        if args[:3] == ["gh", "pr", "list"]:
            return self._completed(args, 0, json.dumps(self.pull_requests))
        if args[:3] == ["gh", "pr", "view"]:
            number = int(args[3])
            pull_request = next(
                (item for item in self.pull_requests if item.get("number") == number),
                None,
            )
            if pull_request is None:
                return self._completed(args, 1)
            projected = {
                **pull_request,
                **(self.pr_view_override or {}),
                "mergeable": self.mergeable,
                "mergeStateStatus": "CLEAN",
                "reviewDecision": self.review_decision,
            }
            return self._completed(args, 0, json.dumps(projected))
        if args[:3] == ["gh", "pr", "ready"]:
            self.ready_calls += 1
            number = int(args[3])
            for item in self.pull_requests:
                if item.get("number") == number:
                    item["isDraft"] = False
            return self._completed(args, 0)
        if args[:3] == ["gh", "pr", "merge"]:
            self.merge_calls += 1
            expected = args[args.index("--match-head-commit") + 1]
            if expected != self.remote_head:
                return self._completed(args, 1)
            number = int(args[3])
            for item in self.pull_requests:
                if item.get("number") == number:
                    item["state"] = "MERGED"
                    item["mergedAt"] = datetime.now(timezone.utc).isoformat()
                    item["mergeCommit"] = {"oid": "f" * 40}
            self.base_head = "f" * 40
            return self._completed(args, 0)
        if args[:3] == ["gh", "pr", "create"]:
            self.create_calls += 1
            branch = args[args.index("--head") + 1]
            base = args[args.index("--base") + 1]
            created = [
                {
                    "number": 91,
                    "url": "https://github.com/OWNER/repo/pull/91",
                    "state": "OPEN",
                    "isDraft": True,
                    "baseRefName": base,
                    "headRefName": branch,
                    "headRefOid": self.remote_head,
                    "headRepository": {"name": "repo"},
                    "headRepositoryOwner": {"login": "OWNER"},
                }
            ]
            if self.verify_create:
                self.pull_requests = created
            return self._completed(
                args,
                self.create_return_code,
                created[0]["url"] + "\n" if self.create_return_code == 0 else "",
            )
        if args[:2] == ["gh", "api"] and len(args) >= 3:
            endpoint = args[2]
            if endpoint == "graphql":
                query = next(
                    (value.removeprefix("query=") for value in args if value.startswith("query=")),
                    "",
                )
                cursor_value = next(
                    (value.removeprefix("cursor=") for value in args if value.startswith("cursor=")),
                    None,
                )
                page_index = int(cursor_value or "0")
                pages = (
                    self.review_threads_pages
                    if "ReviewThreads" in query
                    else self.review_pages
                )
                nodes = pages[page_index] if page_index < len(pages) else []
                has_next = page_index + 1 < len(pages)
                connection = "reviewThreads" if "ReviewThreads" in query else "reviews"
                return self._completed(
                    args,
                    0,
                    json.dumps(
                        {
                            "data": {
                                "repository": {
                                    "pullRequest": {
                                        connection: {
                                            "nodes": nodes,
                                            "pageInfo": {
                                                "hasNextPage": has_next,
                                                "endCursor": str(page_index + 1) if has_next else None,
                                            },
                                        }
                                    }
                                }
                            }
                        }
                    ),
                )
            if "/git/ref/heads/" in endpoint:
                return self._completed(
                    args, 0, json.dumps({"object": {"sha": self.base_head}})
                )
            if "/compare/" in endpoint:
                return self._completed(args, 0, self.compare_status + "\n")
            if "/actions/runs/" in endpoint and "/jobs?" in endpoint:
                return self._completed(args, 0, json.dumps({"jobs": self.jobs}))
            if "/actions/runs?" in endpoint or "/actions/workflows/ci.yml/runs?" in endpoint:
                return self._completed(
                    args, 0, json.dumps({"workflow_runs": self.workflow_runs})
                )
            if endpoint.endswith("/check-runs") or "/check-runs?" in endpoint:
                return self._completed(
                    args, 0, json.dumps({"check_runs": self.check_runs})
                )
            if endpoint.endswith("/status") or "/status?" in endpoint:
                page_match = re.search(r"[?&]page=(\d+)", endpoint)
                page = int(page_match.group(1)) if page_match else 1
                statuses = (
                    self.commit_status_pages[page - 1]
                    if self.commit_status_pages is not None
                    and page <= len(self.commit_status_pages)
                    else []
                    if self.commit_status_pages is not None
                    else self.commit_statuses
                )
                return self._completed(
                    args, 0, json.dumps({"statuses": statuses})
                )
        return subprocess.run(
            args,
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
        )

    @staticmethod
    def _completed(
        args: list[str], code: int, stdout: str = "", stderr: str = ""
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, code, stdout, stderr)


@pytest.fixture
def synchronized_project(tmp_path: Path) -> tuple[Path, FakeCommands]:
    project = tmp_path / "project"
    bare = tmp_path / "remote.git"
    project.mkdir()
    _run(["git", "init", "--initial-branch=main"], project)
    _run(["git", "config", "user.email", "test@example.com"], project)
    _run(["git", "config", "user.name", "Test User"], project)
    (project / "README.md").write_text("hello\n", encoding="utf-8")
    (project / ".gitignore").write_text(".colameta/runtime/\n", encoding="utf-8")
    _run(["git", "add", "README.md", ".gitignore"], project)
    _run(["git", "commit", "-m", "feat: delivery candidate"], project)
    _run(["git", "switch", "-c", "codex/delivery-test"], project)
    _run(["git", "init", "--bare", str(bare)], project)
    _run(["git", "remote", "add", "origin", str(bare)], project)
    _run(["git", "push", "-u", "origin", "codex/delivery-test"], project)
    _run(
        ["git", "remote", "set-url", "origin", "git@github.com:OWNER/repo.git"],
        project,
    )
    head = _run(["git", "rev-parse", "HEAD"], project).stdout.strip()
    return project, FakeCommands(project, head)


def _manager(project: Path, commands: FakeCommands) -> MCPGitHubDeliveryManager:
    return MCPGitHubDeliveryManager(
        str(project),
        command_runner=commands,
        gh_resolver=lambda name: "/usr/bin/gh" if name == "gh" else None,
    )


def _exact_pr(commands: FakeCommands) -> dict[str, object]:
    return {
        "number": 90,
        "url": "https://github.com/OWNER/repo/pull/90",
        "state": "OPEN",
        "isDraft": True,
        "baseRefName": "main",
        "headRefName": "codex/delivery-test",
        "headRefOid": commands.remote_head,
        "headRepository": {"name": "repo"},
        "headRepositoryOwner": {"login": "OWNER"},
    }


def _foreign_pr(commands: FakeCommands, *, draft: bool = True) -> dict[str, object]:
    pull_request = _exact_pr(commands)
    pull_request["number"] = 89
    pull_request["url"] = "https://github.com/OWNER/repo/pull/89"
    pull_request["isDraft"] = draft
    pull_request["headRepositoryOwner"] = {"login": "FORK"}
    return pull_request


def test_exact_push_ci_observer_binds_event_branch_and_head(
    synchronized_project: tuple[Path, FakeCommands],
) -> None:
    project, commands = synchronized_project
    commands.workflow_runs = [
        {
            "id": 801,
            "workflow_id": 80,
            "name": "CI",
            "event": "push",
            "head_branch": "main",
            "head_sha": commands.remote_head,
            "path": ".github/workflows/ci.yml",
            "run_attempt": 1,
            "status": "completed",
            "conclusion": "success",
        },
        {
            "id": 802,
            "workflow_id": 81,
            "name": "stale branch",
            "event": "push",
            "head_branch": "other",
            "head_sha": commands.remote_head,
            "path": ".github/workflows/other.yml",
            "run_attempt": 1,
            "status": "completed",
            "conclusion": "failure",
        },
    ]
    manager = _manager(project, commands)

    result = manager.observe_exact_ci(
        repository="OWNER/repo",
        head_sha=commands.remote_head,
        event="push",
        branch="main",
        workflow_path=".github/workflows/ci.yml",
    )

    assert result["state"] == "PASS"
    assert [item["run_id"] for item in result["workflow_runs"]] == [801]


def test_exact_push_ci_observer_rejects_unrelated_workflow(
    synchronized_project: tuple[Path, FakeCommands],
) -> None:
    project, commands = synchronized_project
    commands.workflow_runs = [
        {
            "id": 803,
            "workflow_id": 81,
            "name": "Unrelated docs ping",
            "event": "push",
            "head_branch": "main",
            "head_sha": commands.remote_head,
            "path": ".github/workflows/docs.yml",
            "run_attempt": 1,
            "status": "completed",
            "conclusion": "success",
        }
    ]
    manager = _manager(project, commands)

    result = manager.observe_exact_ci(
        repository="OWNER/repo",
        head_sha=commands.remote_head,
        event="push",
        branch="main",
        workflow_path=".github/workflows/ci.yml",
    )

    assert result["state"] == "WAITING"
    assert result["workflow_runs"] == []


def test_pr_status_preview_apply_creates_one_exact_draft(
    synchronized_project: tuple[Path, FakeCommands],
) -> None:
    project, commands = synchronized_project
    manager = _manager(project, commands)

    status = manager.pr_status(project_name="sample")
    assert status["ok"] is True
    assert status["state"] == "PR_ACTION_REQUIRED"
    assert status["next_actions"][0]["params"]["phase"] == "pr_preview"

    preview = manager.pr_preview(project_name="sample")
    branch_before = _run(["git", "branch", "--show-current"], project).stdout.strip()
    head_before = _run(["git", "rev-parse", "HEAD"], project).stdout.strip()
    result = manager.pr_apply(
        project_name="sample",
        preview_id=preview["preview_id"],
        preview_digest=preview["preview_digest"],
    )

    assert result["ok"] is True
    assert result["state"] == "PR_PRESENT"
    assert result["pull_request"]["draft"] is True
    assert result["pull_request"]["head_sha"] == head_before
    assert commands.create_calls == 1
    assert _run(["git", "branch", "--show-current"], project).stdout.strip() == branch_before
    assert _run(["git", "rev-parse", "HEAD"], project).stdout.strip() == head_before
    assert _run(["git", "status", "--porcelain"], project).stdout == ""

    replay = manager.pr_apply(
        project_name="sample",
        preview_id=preview["preview_id"],
        preview_digest=preview["preview_digest"],
    )
    assert replay["error_code"] == "PREVIEW_DIGEST_MISMATCH"
    assert commands.create_calls == 1


def test_exact_existing_pr_is_idempotent(
    synchronized_project: tuple[Path, FakeCommands],
) -> None:
    project, commands = synchronized_project
    commands.pull_requests = [_exact_pr(commands)]
    result = _manager(project, commands).pr_status(project_name="sample")
    assert result["ok"] is True
    assert result["state"] == "PR_PRESENT"
    assert result["pull_request"]["number"] == 90
    assert commands.create_calls == 0


def test_exact_same_repository_non_draft_is_outside_authority(
    synchronized_project: tuple[Path, FakeCommands],
) -> None:
    project, commands = synchronized_project
    pull_request = _exact_pr(commands)
    pull_request["isDraft"] = False
    commands.pull_requests = [pull_request]
    result = _manager(project, commands).pr_status(project_name="sample")
    assert result["error_code"] == "GITHUB_PR_STATE_OUTSIDE_AUTHORITY"
    assert commands.create_calls == 0


def test_fork_draft_with_same_branch_and_sha_does_not_satisfy_origin_pr(
    synchronized_project: tuple[Path, FakeCommands],
) -> None:
    project, commands = synchronized_project
    commands.pull_requests = [_foreign_pr(commands)]
    result = _manager(project, commands).pr_status(project_name="sample")
    assert result["ok"] is True
    assert result["state"] == "PR_ACTION_REQUIRED"
    assert result["pull_request"] == {"present": False}
    assert result["warnings"] == ["foreign_head_pr_ignored"]
    preview = _manager(project, commands).pr_preview(project_name="sample")
    assert preview["ok"] is True
    assert preview["state"] == "PR_PREVIEW_READY"
    assert preview["head_repository"] == "OWNER/repo"


def test_missing_head_repository_identity_cannot_satisfy_origin_pr(
    synchronized_project: tuple[Path, FakeCommands],
) -> None:
    project, commands = synchronized_project
    pull_request = _exact_pr(commands)
    pull_request.pop("headRepository")
    pull_request.pop("headRepositoryOwner")
    commands.pull_requests = [pull_request]
    result = _manager(project, commands).pr_status(project_name="sample")
    assert result["ok"] is True
    assert result["state"] == "PR_ACTION_REQUIRED"
    assert result["warnings"] == ["foreign_head_pr_ignored"]


def test_origin_draft_wins_over_fork_draft(
    synchronized_project: tuple[Path, FakeCommands],
) -> None:
    project, commands = synchronized_project
    commands.pull_requests = [_foreign_pr(commands), _exact_pr(commands)]
    result = _manager(project, commands).pr_status(project_name="sample")
    assert result["ok"] is True
    assert result["state"] == "PR_PRESENT"
    assert result["pull_request"]["head_repository"] == "OWNER/repo"
    assert result["warnings"] == ["foreign_head_pr_ignored"]


def test_origin_non_draft_blocks_even_when_fork_draft_exists(
    synchronized_project: tuple[Path, FakeCommands],
) -> None:
    project, commands = synchronized_project
    origin = _exact_pr(commands)
    origin["isDraft"] = False
    commands.pull_requests = [_foreign_pr(commands), origin]
    result = _manager(project, commands).pr_status(project_name="sample")
    assert result["error_code"] == "GITHUB_PR_STATE_OUTSIDE_AUTHORITY"
    assert commands.create_calls == 0


def test_multiple_authoritative_matches_are_ambiguous(
    synchronized_project: tuple[Path, FakeCommands],
) -> None:
    project, commands = synchronized_project
    second = _exact_pr(commands)
    second["number"] = 92
    second["url"] = "https://github.com/OWNER/repo/pull/92"
    commands.pull_requests = [_exact_pr(commands), second]
    result = _manager(project, commands).pr_status(project_name="sample")
    assert result["error_code"] == "GITHUB_PR_CONTEXT_AMBIGUOUS"


def test_authoritative_draft_and_non_draft_mix_is_ambiguous(
    synchronized_project: tuple[Path, FakeCommands],
) -> None:
    project, commands = synchronized_project
    non_draft = _exact_pr(commands)
    non_draft["number"] = 93
    non_draft["url"] = "https://github.com/OWNER/repo/pull/93"
    non_draft["isDraft"] = False
    commands.pull_requests = [_exact_pr(commands), non_draft]
    result = _manager(project, commands).pr_status(project_name="sample")
    assert result["error_code"] == "GITHUB_PR_CONTEXT_AMBIGUOUS"


def test_conflicting_pr_fails_closed(
    synchronized_project: tuple[Path, FakeCommands],
) -> None:
    project, commands = synchronized_project
    conflict = _exact_pr(commands)
    conflict["baseRefName"] = "release"
    commands.pull_requests = [conflict]
    result = _manager(project, commands).pr_status(project_name="sample")
    assert result["error_code"] == "GITHUB_PR_CONTEXT_AMBIGUOUS"


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("repository", "OTHER/repo"),
        ("head_repository", "OTHER/repo"),
        ("base_branch", "release"),
        ("head_branch", "codex/other"),
        ("head_sha", "0" * 40),
        ("title", "substituted"),
        ("body", "substituted"),
        ("expires_at", "2999-01-01T00:00:00+00:00"),
        ("consumed", True),
    ],
)
def test_preview_authorization_tamper_is_rejected_before_create(
    synchronized_project: tuple[Path, FakeCommands],
    field: str,
    replacement: object,
) -> None:
    project, commands = synchronized_project
    manager = _manager(project, commands)
    preview = manager.pr_preview(project_name="sample")
    path = Path(manager.preview_dir) / f"{preview['preview_id']}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload[field] = replacement
    path.write_text(json.dumps(payload), encoding="utf-8")
    result = manager.pr_apply(
        project_name="sample",
        preview_id=preview["preview_id"],
        preview_digest=preview["preview_digest"],
    )
    assert result["error_code"] == "PREVIEW_DIGEST_MISMATCH"
    assert commands.create_calls == 0


def test_symlink_and_oversized_previews_are_rejected(
    synchronized_project: tuple[Path, FakeCommands], tmp_path: Path
) -> None:
    project, commands = synchronized_project
    manager = _manager(project, commands)
    preview = manager.pr_preview(project_name="sample")
    path = Path(manager.preview_dir) / f"{preview['preview_id']}.json"
    other = tmp_path / "other.json"
    other.write_text("{}", encoding="utf-8")
    path.unlink()
    path.symlink_to(other)
    unsafe = manager.pr_apply(
        project_name="sample",
        preview_id=preview["preview_id"],
        preview_digest=preview["preview_digest"],
    )
    assert unsafe["error_code"] == "PREVIEW_UNSAFE"

    preview = manager.pr_preview(project_name="sample")
    path = Path(manager.preview_dir) / f"{preview['preview_id']}.json"
    path.write_bytes(b"x" * (manager._MAX_PREVIEW_BYTES + 1))
    oversized = manager.pr_apply(
        project_name="sample",
        preview_id=preview["preview_id"],
        preview_digest=preview["preview_digest"],
    )
    assert oversized["error_code"] == "PREVIEW_INVALID"
    assert commands.create_calls == 0


def test_authority_and_remote_head_fail_closed(
    synchronized_project: tuple[Path, FakeCommands],
) -> None:
    project, commands = synchronized_project
    commands.authorized = False
    denied = _manager(project, commands).pr_status(project_name="sample")
    assert denied["error_code"] == "GITHUB_AUTHORITY_UNAVAILABLE"

    commands.authorized = True
    commands.remote_head = "f" * 40
    mismatch = _manager(project, commands).pr_status(project_name="sample")
    assert mismatch["error_code"] == "GITHUB_REMOTE_HEAD_MISMATCH"


def test_missing_github_cli_fails_closed(
    synchronized_project: tuple[Path, FakeCommands],
) -> None:
    project, commands = synchronized_project
    result = MCPGitHubDeliveryManager(
        str(project),
        command_runner=commands,
        gh_resolver=lambda name: None,
    ).pr_status(project_name="sample")
    assert result["error_code"] == "GITHUB_AUTHORITY_UNAVAILABLE"


@pytest.mark.parametrize(
    "origin",
    [
        "https://user:secret@github.com/OWNER/repo.git",
        "git@gitlab.com:OWNER/repo.git",
        "https://github.com/OWNER/repo/extra.git",
    ],
)
def test_untrusted_origin_is_rejected(
    synchronized_project: tuple[Path, FakeCommands], origin: str
) -> None:
    project, commands = synchronized_project
    _run(["git", "remote", "set-url", "origin", origin], project)
    result = _manager(project, commands).pr_status(project_name="sample")
    assert result["error_code"] == "GITHUB_ORIGIN_INVALID"


def test_dirty_worktree_is_blocked(
    synchronized_project: tuple[Path, FakeCommands],
) -> None:
    project, commands = synchronized_project
    (project / "README.md").write_text("changed\n", encoding="utf-8")
    result = _manager(project, commands).pr_status(project_name="sample")
    assert result["error_code"] in {
        "WORKTREE_DIRTY",
        "WORKTREE_NOT_CLEAN",
        "working_tree_dirty",
    }


def test_protected_and_non_delivery_branches_are_blocked(
    synchronized_project: tuple[Path, FakeCommands],
) -> None:
    project, commands = synchronized_project
    _run(["git", "switch", "main"], project)
    protected = _manager(project, commands).pr_status(project_name="sample")
    assert protected["error_code"] == "GITHUB_HEAD_BRANCH_BLOCKED"

    _run(["git", "switch", "-c", "feature/not-allowed"], project)
    denied = _manager(project, commands).pr_status(project_name="sample")
    assert denied["error_code"] == "GITHUB_HEAD_BRANCH_BLOCKED"


def test_missing_upstream_and_ahead_branch_are_blocked(
    synchronized_project: tuple[Path, FakeCommands],
) -> None:
    project, commands = synchronized_project
    _run(["git", "branch", "--unset-upstream"], project)
    missing = _manager(project, commands).pr_status(project_name="sample")
    assert missing["error_code"] in {
        "GITHUB_UPSTREAM_MISMATCH",
        "upstream_missing",
        "first_push_remote_check_failed",
    }

    _run(
        ["git", "branch", "--set-upstream-to", "origin/codex/delivery-test"],
        project,
    )
    (project / "second.txt").write_text("second\n", encoding="utf-8")
    _run(["git", "add", "second.txt"], project)
    _run(["git", "commit", "-m", "feat: second"], project)
    commands.remote_head = _run(["git", "rev-parse", "HEAD"], project).stdout.strip()
    ahead = _manager(project, commands).pr_status(project_name="sample")
    assert ahead["error_code"] in {"GITHUB_BRANCH_AHEAD", "unpushed_commits"}


def test_non_origin_upstream_and_behind_branch_are_blocked(
    synchronized_project: tuple[Path, FakeCommands], tmp_path: Path
) -> None:
    project, commands = synchronized_project
    other = tmp_path / "other.git"
    _run(["git", "init", "--bare", str(other)], project)
    _run(["git", "remote", "add", "other", str(other)], project)
    _run(["git", "push", "-u", "other", "codex/delivery-test"], project)
    non_origin = _manager(project, commands).pr_status(project_name="sample")
    assert non_origin["error_code"] in {
        "GITHUB_UPSTREAM_MISMATCH",
        "remote_not_allowed",
    }

    _run(
        ["git", "branch", "--set-upstream-to", "origin/codex/delivery-test"],
        project,
    )
    old_head = _run(["git", "rev-parse", "HEAD"], project).stdout.strip()
    (project / "remote.txt").write_text("remote\n", encoding="utf-8")
    _run(["git", "add", "remote.txt"], project)
    _run(["git", "commit", "-m", "feat: remote"], project)
    remote_head = _run(["git", "rev-parse", "HEAD"], project).stdout.strip()
    _run(["git", "update-ref", "refs/remotes/origin/codex/delivery-test", remote_head], project)
    _run(["git", "reset", "--hard", old_head], project)
    commands.remote_head = remote_head
    behind = _manager(project, commands).pr_status(project_name="sample")
    assert behind["error_code"] in {
        "GITHUB_BRANCH_BEHIND",
        "remote_ahead",
        "branch_behind_upstream",
    }


def test_missing_or_malformed_preview_digest_fails_before_create(
    synchronized_project: tuple[Path, FakeCommands],
) -> None:
    project, commands = synchronized_project
    manager = _manager(project, commands)
    preview = manager.pr_preview(project_name="sample")
    missing = manager.pr_apply(
        project_name="sample",
        preview_id=preview["preview_id"],
        preview_digest="",
    )
    invalid = manager.pr_apply(
        project_name="sample",
        preview_id=preview["preview_id"],
        preview_digest="not-a-digest",
    )
    assert missing["error_code"] == "PREVIEW_DIGEST_REQUIRED"
    assert invalid["error_code"] == "PREVIEW_DIGEST_INVALID"
    assert commands.create_calls == 0


def test_expired_preview_fails_before_create(
    synchronized_project: tuple[Path, FakeCommands],
) -> None:
    project, commands = synchronized_project
    manager = _manager(project, commands)
    preview = manager.pr_preview(project_name="sample")
    path = Path(manager.preview_dir) / f"{preview['preview_id']}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["expires_at"] = (
        datetime.now(timezone.utc) - timedelta(seconds=1)
    ).isoformat()
    manager._write_preview(preview["preview_id"], payload)
    expired_digest = canonical_artifact_digest(payload)
    result = manager.pr_apply(
        project_name="sample",
        preview_id=preview["preview_id"],
        preview_digest=expired_digest,
    )
    assert result["error_code"] == "PREVIEW_EXPIRED"
    assert commands.create_calls == 0


def test_pr_created_during_preview_window_is_already_satisfied(
    synchronized_project: tuple[Path, FakeCommands],
) -> None:
    project, commands = synchronized_project
    manager = _manager(project, commands)
    preview = manager.pr_preview(project_name="sample")
    commands.pull_requests = [_exact_pr(commands)]
    result = manager.pr_apply(
        project_name="sample",
        preview_id=preview["preview_id"],
        preview_digest=preview["preview_digest"],
    )
    assert result["ok"] is True
    assert result["already_satisfied"] is True
    assert commands.create_calls == 0


def test_origin_non_draft_created_after_preview_blocks_apply(
    synchronized_project: tuple[Path, FakeCommands],
) -> None:
    project, commands = synchronized_project
    manager = _manager(project, commands)
    preview = manager.pr_preview(project_name="sample")
    origin = _exact_pr(commands)
    origin["isDraft"] = False
    commands.pull_requests = [origin]
    result = manager.pr_apply(
        project_name="sample",
        preview_id=preview["preview_id"],
        preview_digest=preview["preview_digest"],
    )
    assert result["error_code"] == "GITHUB_PR_STATE_OUTSIDE_AUTHORITY"
    assert commands.create_calls == 0


def test_fork_pr_created_after_preview_does_not_satisfy_apply(
    synchronized_project: tuple[Path, FakeCommands],
) -> None:
    project, commands = synchronized_project
    manager = _manager(project, commands)
    preview = manager.pr_preview(project_name="sample")
    commands.pull_requests = [_foreign_pr(commands)]
    result = manager.pr_apply(
        project_name="sample",
        preview_id=preview["preview_id"],
        preview_digest=preview["preview_digest"],
    )
    assert result["ok"] is True
    assert result["created"] is True
    assert result["already_satisfied"] is False
    assert result["pull_request"]["head_repository"] == "OWNER/repo"
    assert commands.create_calls == 1


def test_create_race_provider_error_rechecks_exact_desired_state(
    synchronized_project: tuple[Path, FakeCommands],
) -> None:
    project, commands = synchronized_project
    commands.create_return_code = 1
    manager = _manager(project, commands)
    preview = manager.pr_preview(project_name="sample")
    result = manager.pr_apply(
        project_name="sample",
        preview_id=preview["preview_id"],
        preview_digest=preview["preview_digest"],
    )
    assert result["ok"] is True
    assert result["already_satisfied"] is True
    assert result["created"] is False
    assert commands.create_calls == 1


def test_post_create_verification_failure_reports_partial_mutation(
    synchronized_project: tuple[Path, FakeCommands],
) -> None:
    project, commands = synchronized_project
    commands.verify_create = False
    manager = _manager(project, commands)
    preview = manager.pr_preview(project_name="sample")
    result = manager.pr_apply(
        project_name="sample",
        preview_id=preview["preview_id"],
        preview_digest=preview["preview_digest"],
    )
    assert result["error_code"] == "GITHUB_PR_POST_CREATE_UNVERIFIED"
    assert result["partial_mutation"] is True
    assert commands.create_calls == 1


def test_provider_url_with_query_is_not_exposed(
    synchronized_project: tuple[Path, FakeCommands],
) -> None:
    project, commands = synchronized_project
    pull_request = _exact_pr(commands)
    pull_request["url"] = "https://github.com/OWNER/repo/pull/90?credential=redacted"
    commands.pull_requests = [pull_request]
    result = _manager(project, commands).pr_status(project_name="sample")
    assert result["error_code"] == "GITHUB_PR_STATUS_INVALID"
    assert "credential" not in json.dumps(result)


def test_secret_like_commit_subject_is_not_used_as_pr_title(
    synchronized_project: tuple[Path, FakeCommands],
) -> None:
    project, commands = synchronized_project
    (project / "secret-subject.txt").write_text("safe contents\n", encoding="utf-8")
    _run(["git", "add", "secret-subject.txt"], project)
    synthetic = "ghp_" + ("A" * 36)
    _run(["git", "commit", "-m", f"token {synthetic}"], project)
    new_head = _run(["git", "rev-parse", "HEAD"], project).stdout.strip()
    _run(["git", "update-ref", "refs/remotes/origin/codex/delivery-test", new_head], project)
    commands.remote_head = new_head
    preview = _manager(project, commands).pr_preview(project_name="sample")
    assert preview["title"] == "Deliver reviewed project changes"
    assert synthetic not in json.dumps(preview)


def test_synchronized_push_status_gets_one_github_delivery_continuation() -> None:
    result = {
        "ok": True,
        "branch": "codex/delivery-test",
        "head": "a" * 40,
        "remote_name": "origin",
        "upstream": "origin/codex/delivery-test",
        "ahead": 0,
        "behind": 0,
        "blocking_working_tree_clean": True,
        "blockers": ["nothing_to_push"],
    }
    MCPPlanningBridgeServer._add_github_delivery_continuation(
        result,
        action="push_status",
        project_name="sample",
    )
    assert result["next_actions"] == [
        {
            "tool": "run_mcp_workflow",
            "params": {
                "workflow": "github_delivery",
                "phase": "pr_status",
                "project_name": "sample",
            },
            "reason": "Inspect exact-head GitHub pull-request admission.",
            "requires_confirmation": False,
        }
    ]


def test_unsynchronized_push_status_has_no_github_continuation() -> None:
    result = {
        "ok": True,
        "branch": "codex/delivery-test",
        "remote_name": "origin",
        "upstream": "origin/codex/delivery-test",
        "ahead": 1,
        "behind": 0,
        "blocking_working_tree_clean": True,
        "blockers": [],
    }
    MCPPlanningBridgeServer._add_github_delivery_continuation(
        result,
        action="push_status",
        project_name="sample",
    )
    assert "next_actions" not in result


def _merge_manager(
    synchronized_project: tuple[Path, FakeCommands],
) -> tuple[MCPGitHubDeliveryManager, FakeCommands]:
    project, commands = synchronized_project
    commands.pull_requests = [_exact_pr(commands)]
    return _manager(project, commands), commands


def test_pr_present_continues_to_merge_status(
    synchronized_project: tuple[Path, FakeCommands],
) -> None:
    manager, _commands = _merge_manager(synchronized_project)
    result = manager.pr_status(project_name="sample")
    assert result["state"] == "PR_PRESENT"
    assert result["next_actions"][0]["params"]["phase"] == "merge_status"


def test_merge_status_ready_binds_exact_pr_base_ci_and_review(
    synchronized_project: tuple[Path, FakeCommands],
) -> None:
    manager, commands = _merge_manager(synchronized_project)
    result = manager.merge_status(project_name="sample")
    assert result["state"] == "READY_FOR_EXTERNAL_MERGE"
    assert result["draft"] is True
    assert result["base_head_sha"] == commands.base_head
    assert result["head_sha"] == commands.remote_head
    assert result["ci"]["state"] == "PASS"
    assert result["review"]["state"] == "PASS"
    assert result["next_actions"] == []
    assert result["merge_authority"] == {
        "mode": "external",
        "atomic_provider_guard_available": False,
        "observation_is_point_in_time": True,
    }
    assert result["merge_handoff"]["observed_base_sha"] == commands.base_head
    assert result["merge_handoff"]["head_sha"] == commands.remote_head
    assert "fresh_recheck_required_before_external_merge" in result["warnings"]
    assert commands.ready_calls == 0
    assert commands.merge_calls == 0


def test_merge_status_rejects_non_draft_and_foreign_entry(
    synchronized_project: tuple[Path, FakeCommands],
) -> None:
    manager, commands = _merge_manager(synchronized_project)
    commands.pull_requests[0]["isDraft"] = False
    non_draft = manager.merge_status(project_name="sample")
    assert non_draft["blockers"] == ["GITHUB_PR_STATE_OUTSIDE_AUTHORITY"]
    commands.pull_requests = [_foreign_pr(commands)]
    foreign = manager.merge_status(project_name="sample")
    assert foreign["blockers"] == ["GITHUB_PR_NOT_FOUND"]
    assert foreign["warnings"] == ["foreign_head_pr_ignored"]


def test_merge_status_blocks_wrong_pr_identity_and_stale_base(
    synchronized_project: tuple[Path, FakeCommands],
) -> None:
    manager, commands = _merge_manager(synchronized_project)
    commands.pull_requests[0]["baseRefName"] = "production"
    wrong_base = manager.merge_status(project_name="sample")
    assert wrong_base["blockers"] == ["GITHUB_PR_CONTEXT_AMBIGUOUS"]
    commands.pull_requests[0]["baseRefName"] = "main"
    commands.compare_status = "diverged"
    stale = manager.merge_status(project_name="sample")
    assert stale["blockers"] == ["GITHUB_HEAD_NOT_UP_TO_DATE"]


def test_merge_status_blocks_non_mergeable_pr_without_provider_mutation(
    synchronized_project: tuple[Path, FakeCommands],
) -> None:
    manager, commands = _merge_manager(synchronized_project)
    commands.mergeable = "CONFLICTING"
    result = manager.merge_status(project_name="sample")
    assert result["blockers"] == ["GITHUB_PR_NOT_MERGEABLE"]
    assert commands.ready_calls == 0
    assert commands.merge_calls == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("baseRefName", "production"),
        ("headRefName", "codex/foreign"),
        ("headRefOid", "a" * 40),
        ("isDraft", False),
    ],
)
def test_merge_status_fails_closed_when_pr_details_drift_after_list(
    synchronized_project: tuple[Path, FakeCommands],
    field: str,
    value: object,
) -> None:
    manager, commands = _merge_manager(synchronized_project)
    commands.pr_view_override = {field: value}
    result = manager.merge_status(project_name="sample")
    assert result["blockers"] == ["GITHUB_PR_CONTEXT_AMBIGUOUS"]
    assert commands.ready_calls == 0
    assert commands.merge_calls == 0


@pytest.mark.parametrize(
    ("status", "conclusion", "expected", "blocker"),
    [
        ("in_progress", None, "WAITING_FOR_EXTERNAL_GATE", None),
        ("completed", "failure", "BLOCKED", "GITHUB_CI_FAILED"),
    ],
)
def test_merge_status_normalizes_exact_head_ci(
    synchronized_project: tuple[Path, FakeCommands],
    status: str,
    conclusion: str | None,
    expected: str,
    blocker: str | None,
) -> None:
    manager, commands = _merge_manager(synchronized_project)
    commands.workflow_runs[0]["status"] = status
    commands.workflow_runs[0]["conclusion"] = conclusion
    result = manager.merge_status(project_name="sample")
    assert result["state"] == expected
    if blocker:
        assert result["blockers"] == [blocker]


def test_no_exact_head_run_waits_and_latest_rerun_supersedes_failure(
    synchronized_project: tuple[Path, FakeCommands],
) -> None:
    manager, commands = _merge_manager(synchronized_project)
    commands.workflow_runs = []
    assert manager.merge_status(project_name="sample")["state"] == "WAITING_FOR_EXTERNAL_GATE"
    commands.workflow_runs = [
        {
            "id": 700,
            "workflow_id": 70,
            "name": "CI",
            "event": "pull_request",
            "head_sha": commands.remote_head,
            "run_attempt": 1,
            "status": "completed",
            "conclusion": "failure",
        },
        {
            "id": 702,
            "workflow_id": 70,
            "name": "CI",
            "event": "pull_request",
            "head_sha": commands.remote_head,
            "run_attempt": 2,
            "status": "completed",
            "conclusion": "success",
        },
    ]
    rerun = manager.merge_status(project_name="sample")
    assert rerun["state"] == "READY_FOR_EXTERNAL_MERGE"
    assert rerun["ci"]["workflow_runs"][0]["run_id"] == 702


@pytest.mark.parametrize(
    ("classic_state", "expected"),
    [("pending", "WAITING_FOR_EXTERNAL_GATE"), ("failure", "BLOCKED")],
)
def test_classic_commit_status_participates_in_gate(
    synchronized_project: tuple[Path, FakeCommands],
    classic_state: str,
    expected: str,
) -> None:
    manager, commands = _merge_manager(synchronized_project)
    commands.commit_statuses = [{"context": "external", "state": classic_state}]
    assert manager.merge_status(project_name="sample")["state"] == expected


def test_provider_envelope_inconsistency_requires_adjudication(
    synchronized_project: tuple[Path, FakeCommands],
) -> None:
    manager, commands = _merge_manager(synchronized_project)
    commands.jobs = [
        {
            "id": 701,
            "name": "Quality gates",
            "status": "in_progress",
            "conclusion": None,
            "steps": [
                {
                    "name": "Complete job",
                    "status": "completed",
                    "conclusion": "success",
                }
            ],
        }
    ]
    result = manager.merge_status(project_name="sample")
    assert result["blockers"] == ["GITHUB_PROVIDER_STATE_INCONSISTENCY"]


def test_review_pagination_and_effective_review_state(
    synchronized_project: tuple[Path, FakeCommands],
) -> None:
    manager, commands = _merge_manager(synchronized_project)
    commands.review_threads_pages = [
        [{"id": "T1", "isResolved": True}],
        [{"id": "T2", "isResolved": False}],
    ]
    blocked = manager.merge_status(project_name="sample")
    assert blocked["blockers"] == ["GITHUB_REVIEW_THREAD_UNRESOLVED"]
    commands.review_threads_pages = [[]]
    commands.review_pages = [
        [
            {
                "id": "R1",
                "state": "CHANGES_REQUESTED",
                "submittedAt": "2026-08-11T00:00:00Z",
                "author": {"login": "reviewer"},
            },
            {
                "id": "R2",
                "state": "APPROVED",
                "submittedAt": "2026-08-11T01:00:00Z",
                "author": {"login": "reviewer"},
            },
        ]
    ]
    assert manager.merge_status(project_name="sample")["state"] == "READY_FOR_EXTERNAL_MERGE"


@pytest.mark.parametrize(
    ("decision", "expected", "blocker"),
    [
        ("REVIEW_REQUIRED", "WAITING_FOR_EXTERNAL_GATE", None),
        ("CHANGES_REQUESTED", "BLOCKED", "GITHUB_REVIEW_CHANGES_REQUESTED"),
    ],
)
def test_review_decision_is_authoritative(
    synchronized_project: tuple[Path, FakeCommands],
    decision: str,
    expected: str,
    blocker: str | None,
) -> None:
    manager, commands = _merge_manager(synchronized_project)
    commands.review_decision = decision
    result = manager.merge_status(project_name="sample")
    assert result["state"] == expected
    if blocker:
        assert result["blockers"] == [blocker]


def test_merge_mutation_surface_is_absent(
    synchronized_project: tuple[Path, FakeCommands],
) -> None:
    manager, commands = _merge_manager(synchronized_project)
    assert not hasattr(manager, "merge_preview")
    assert not hasattr(manager, "merge_apply")
    assert manager.merge_status(project_name="sample")["state"] == (
        "READY_FOR_EXTERNAL_MERGE"
    )
    assert commands.ready_calls == 0
    assert commands.merge_calls == 0


def test_old_head_success_cannot_satisfy_exact_head_pending_or_failure(
    synchronized_project: tuple[Path, FakeCommands],
) -> None:
    manager, commands = _merge_manager(synchronized_project)
    old_success = {
        "id": 699,
        "workflow_id": 70,
        "name": "CI",
        "event": "pull_request",
        "head_sha": "a" * 40,
        "run_attempt": 1,
        "status": "completed",
        "conclusion": "success",
    }
    commands.workflow_runs = [old_success, {**commands.workflow_runs[0], "status": "in_progress", "conclusion": None}]
    assert manager.merge_status(project_name="sample")["state"] == "WAITING_FOR_EXTERNAL_GATE"
    commands.workflow_runs[1]["status"] = "completed"
    commands.workflow_runs[1]["conclusion"] = "failure"
    assert manager.merge_status(project_name="sample")["blockers"] == ["GITHUB_CI_FAILED"]


def test_latest_check_run_supersedes_old_failed_check(
    synchronized_project: tuple[Path, FakeCommands],
) -> None:
    manager, commands = _merge_manager(synchronized_project)
    commands.check_runs = [
        {
            "id": 1,
            "name": "external",
            "status": "completed",
            "conclusion": "failure",
            "app": {"slug": "checks"},
        },
        {
            "id": 2,
            "name": "external",
            "status": "completed",
            "conclusion": "success",
            "app": {"slug": "checks"},
        },
    ]
    result = manager.merge_status(project_name="sample")
    assert result["state"] == "READY_FOR_EXTERNAL_MERGE"
    assert [item["check_id"] for item in result["ci"]["checks"] if "check_id" in item] == [2]


def test_review_pagination_incomplete_fails_closed(
    synchronized_project: tuple[Path, FakeCommands],
) -> None:
    manager, commands = _merge_manager(synchronized_project)
    commands.review_threads_pages = [
        [{"id": f"T{index}", "isResolved": True}] for index in range(11)
    ]
    result = manager.merge_status(project_name="sample")
    assert result["blockers"] == ["GITHUB_REVIEW_DATA_INCOMPLETE"]


def test_closed_or_merged_pr_is_outside_observation_authority(
    synchronized_project: tuple[Path, FakeCommands],
) -> None:
    manager, commands = _merge_manager(synchronized_project)
    commands.pull_requests[0]["state"] = "CLOSED"
    closed = manager.merge_status(project_name="sample")
    assert closed["blockers"] == ["GITHUB_PR_STATE_OUTSIDE_AUTHORITY"]
    commands.pull_requests[0]["mergedAt"] = "2026-08-11T00:00:00Z"
    commands.pull_requests[0]["mergeCommit"] = {"oid": "f" * 40}
    merged = manager.merge_status(project_name="sample")
    assert merged["blockers"] == ["GITHUB_PR_STATE_OUTSIDE_AUTHORITY"]


def test_ready_state_is_read_only_for_all_observed_gate_outcomes(
    synchronized_project: tuple[Path, FakeCommands],
) -> None:
    manager, commands = _merge_manager(synchronized_project)
    assert manager.merge_status(project_name="sample")["state"] == (
        "READY_FOR_EXTERNAL_MERGE"
    )
    commands.workflow_runs[0]["status"] = "in_progress"
    commands.workflow_runs[0]["conclusion"] = None
    assert manager.merge_status(project_name="sample")["state"] == (
        "WAITING_FOR_EXTERNAL_GATE"
    )
    commands.workflow_runs[0]["status"] = "completed"
    commands.workflow_runs[0]["conclusion"] = "failure"
    assert manager.merge_status(project_name="sample")["state"] == "BLOCKED"
    assert commands.ready_calls == 0
    assert commands.merge_calls == 0
