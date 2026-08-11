from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from runner.mcp_managed_runtime_closeout import (
    COLAMETA_STABLE_LOCAL_TARGET,
    MCPManagedRuntimeCloseoutManager,
)


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)


def _repository_pair(tmp_path: Path) -> tuple[Path, Path, str, str]:
    project = tmp_path / "project"
    project.mkdir()
    _run(["git", "init", "-b", "main"], project)
    _run(["git", "config", "user.name", "Test"], project)
    _run(["git", "config", "user.email", "test@example.invalid"], project)
    _run(["git", "remote", "add", "origin", "git@github.com:JENN2046/colameta.git"], project)
    (project / "value.txt").write_text("old\n", encoding="utf-8")
    _run(["git", "add", "value.txt"], project)
    _run(["git", "commit", "-m", "old"], project)
    old_head = _run(["git", "rev-parse", "HEAD"], project).stdout.strip()
    stable = tmp_path / "stable"
    _run(["git", "clone", str(project), str(stable)], tmp_path)
    _run(["git", "remote", "set-url", "origin", "git@github.com:JENN2046/colameta.git"], stable)
    (project / "value.txt").write_text("new\n", encoding="utf-8")
    _run(["git", "add", "value.txt"], project)
    _run(["git", "commit", "-m", "new"], project)
    head = _run(["git", "rev-parse", "HEAD"], project).stdout.strip()
    return project, stable, head, old_head


class _CIManager:
    def __init__(self, state: str = "PASS", **_: object):
        self.state = state

    def observe_exact_ci(self, **kwargs: object) -> dict[str, object]:
        return {
            "state": self.state,
            "head_sha": kwargs["head_sha"],
            "workflow_runs": [{"workflow": "CI", "status": "completed", "conclusion": "success"}],
            "checks": [],
            "commit_statuses": [],
        }


class _Commands:
    def __init__(self, remote_head: str):
        self.remote_head = remote_head
        self.service_pid = 1234
        self.listener_pid = 1234
        self.service_active = True
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str], cwd: str) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(args))
        if args[:2] == ["systemctl", "show"]:
            return subprocess.CompletedProcess(
                args,
                0,
                (
                    f"ActiveState={'active' if self.service_active else 'inactive'}\n"
                    f"SubState={'running' if self.service_active else 'dead'}\n"
                    f"MainPID={self.service_pid}\n"
                ),
                "",
            )
        if args[:3] == ["ss", "-H", "-ltnp"]:
            return subprocess.CompletedProcess(
                args,
                0,
                f'LISTEN 0 128 127.0.0.1:8766 0.0.0.0:* users:(("python",pid={self.listener_pid},fd=9))\n',
                "",
            )
        if args[:2] == ["git", "ls-remote"]:
            return subprocess.CompletedProcess(
                args,
                0,
                f"{self.remote_head}\trefs/heads/main\n",
                "",
            )
        return subprocess.run(args, cwd=cwd, check=False, capture_output=True, text=True)


def _health(
    stable_head: str,
    *,
    loaded_head: str | None = None,
    package_matches: bool = True,
    healthy: bool = True,
) -> dict[str, object]:
    return {
        "ok": healthy,
        "serving_pid": 1234 if healthy else None,
        "loaded_runtime_head": loaded_head,
        "runtime_project_checkout_head": stable_head,
        "installed_package_matches_project_checkout": package_matches,
        "installed_package_project_source_clean": True,
        "installed_package_verification_status": "match" if package_matches else "mismatch",
        "runtime_loaded_code_stale": False,
        "reload_needed_for_verification": False,
        "reload_awareness_reason": "installed_package_matches_project_checkout",
    }


def _manager(
    project: Path,
    stable: Path,
    head: str,
    *,
    health: dict[str, object],
    ci_state: str = "PASS",
    project_mode: str = "managed",
) -> tuple[MCPManagedRuntimeCloseoutManager, _Commands]:
    commands = _Commands(head)
    manager = MCPManagedRuntimeCloseoutManager(
        str(project),
        project_name="colameta-self-dev",
        project_mode=project_mode,
        command_runner=commands,
        health_reader=lambda: health,
        stable_checkout=str(stable),
        github_manager_factory=lambda *args, **kwargs: _CIManager(ci_state),
    )
    return manager, commands


def _state(result: dict[str, object]) -> str:
    return str(result["result"]["runtime_closeout"]["state"])  # type: ignore[index]


def _assert_read_only_commands(commands: _Commands) -> None:
    forbidden = {"checkout", "switch", "reset", "clean", "pull", "fetch", "push", "commit"}
    for args in commands.calls:
        assert args[0] != "sudo"
        assert args[0] not in {"sudo", "pip", "python"}
        if args[0] == "systemctl":
            assert args[:3] == ["systemctl", "show", "colameta-stable.service"]
        if args[0] == "git":
            assert not forbidden.intersection(args[1:])


def test_stable_behind_returns_external_boundary_without_self_termination(tmp_path: Path) -> None:
    project, stable, head, old_head = _repository_pair(tmp_path)
    manager, commands = _manager(project, stable, head, health=_health(old_head))

    result = manager.status(runtime_target=COLAMETA_STABLE_LOCAL_TARGET)

    assert result["ok"] is True
    assert _state(result) == "READY_FOR_EXTERNAL_RUNTIME_PROMOTION"
    handoff = result["result"]["runtime_closeout"]["external_runtime_promotion"]  # type: ignore[index]
    assert handoff["mode"] == "external"
    assert handoff["authority"]["colaMeta_can_apply"] is False
    assert handoff["stable_before"]["checkout_head"] == old_head
    assert result["next_actions"] == []
    _assert_read_only_commands(commands)


def test_stable_exact_returns_delivery_complete_with_equivalent_provenance(tmp_path: Path) -> None:
    project, stable, head, _ = _repository_pair(tmp_path)
    _run(["git", "fetch", str(project), "main"], stable)
    _run(["git", "checkout", "--detach", head], stable)
    manager, commands = _manager(project, stable, head, health=_health(head))

    result = manager.status(runtime_target=COLAMETA_STABLE_LOCAL_TARGET)

    assert _state(result) == "RUNTIME_ALREADY_CURRENT"
    closeout = result["result"]["runtime_closeout"]  # type: ignore[index]
    assert closeout["delivery"]["state"] == "DELIVERY_COMPLETE"
    assert closeout["runtime_target"]["exact_loaded_code_verified"] is True
    _assert_read_only_commands(commands)


@pytest.mark.parametrize(
    ("target", "mode", "expected"),
    [
        ("unknown", "managed", "RUNTIME_TARGET_UNSUPPORTED"),
        (COLAMETA_STABLE_LOCAL_TARGET, "source-only", "RUNTIME_TARGET_PROJECT_MISMATCH"),
    ],
)
def test_target_boundary_blocks_without_mutation(
    tmp_path: Path, target: str, mode: str, expected: str
) -> None:
    project, stable, head, old_head = _repository_pair(tmp_path)
    manager, commands = _manager(
        project,
        stable,
        head,
        health=_health(old_head),
        project_mode=mode,
    )
    result = manager.status(runtime_target=target)
    assert _state(result) == "RUNTIME_CLOSEOUT_BLOCKED"
    assert result["blockers"] == [expected]
    _assert_read_only_commands(commands)


@pytest.mark.parametrize(
    ("setup", "expected"),
    [
        ("topic", "RUNTIME_DELIVERY_BRANCH_INVALID"),
        ("dirty", "RUNTIME_DELIVERY_WORKTREE_DIRTY"),
        ("remote_drift", "RUNTIME_DELIVERY_HEAD_DRIFT"),
        ("wrong_origin", "RUNTIME_TARGET_PROJECT_MISMATCH"),
    ],
)
def test_delivery_truth_fails_closed(
    tmp_path: Path, setup: str, expected: str
) -> None:
    project, stable, head, old_head = _repository_pair(tmp_path)
    manager, commands = _manager(project, stable, head, health=_health(old_head))
    if setup == "topic":
        _run(["git", "switch", "-c", "codex/topic"], project)
    elif setup == "dirty":
        (project / "value.txt").write_text("dirty\n", encoding="utf-8")
    elif setup == "remote_drift":
        commands.remote_head = old_head
    else:
        _run(["git", "remote", "set-url", "origin", "git@github.com:OTHER/repo.git"], project)
    result = manager.status(runtime_target=COLAMETA_STABLE_LOCAL_TARGET)
    assert result["blockers"] == [expected]
    _assert_read_only_commands(commands)


@pytest.mark.parametrize(
    ("ci_state", "expected"),
    [
        ("WAITING", "RUNTIME_EXACT_HEAD_CI_PENDING"),
        ("BLOCKED", "RUNTIME_EXACT_HEAD_CI_FAILED"),
        ("INCONSISTENT", "GITHUB_PROVIDER_STATE_INCONSISTENCY"),
        ("INCOMPLETE", "RUNTIME_EXACT_HEAD_CI_UNVERIFIED"),
    ],
)
def test_exact_main_ci_must_pass(
    tmp_path: Path, ci_state: str, expected: str
) -> None:
    project, stable, head, old_head = _repository_pair(tmp_path)
    manager, commands = _manager(
        project,
        stable,
        head,
        health=_health(old_head),
        ci_state=ci_state,
    )
    result = manager.status(runtime_target=COLAMETA_STABLE_LOCAL_TARGET)
    assert result["blockers"] == [expected]
    _assert_read_only_commands(commands)


@pytest.mark.parametrize(
    ("health_change", "expected"),
    [
        ({"loaded_runtime_head": "f" * 40}, "RUNTIME_PROVENANCE_INCONSISTENT"),
        ({"installed_package_matches_project_checkout": False}, "RUNTIME_PACKAGE_PROVENANCE_MISMATCH"),
        ({"ok": False, "serving_pid": None}, "RUNTIME_TARGET_UNHEALTHY"),
        ({"runtime_loaded_code_stale": True}, "RUNTIME_FRESHNESS_INCONSISTENT"),
    ],
)
def test_runtime_inconsistency_blocks(
    tmp_path: Path, health_change: dict[str, object], expected: str
) -> None:
    project, stable, head, old_head = _repository_pair(tmp_path)
    health = _health(old_head)
    health.update(health_change)
    manager, commands = _manager(project, stable, head, health=health)
    result = manager.status(runtime_target=COLAMETA_STABLE_LOCAL_TARGET)
    assert result["blockers"] == [expected]
    _assert_read_only_commands(commands)


def test_wrong_stable_repository_blocks(tmp_path: Path) -> None:
    project, stable, head, old_head = _repository_pair(tmp_path)
    _run(["git", "remote", "set-url", "origin", "git@github.com:OTHER/repo.git"], stable)
    manager, commands = _manager(project, stable, head, health=_health(old_head))
    result = manager.status(runtime_target=COLAMETA_STABLE_LOCAL_TARGET)
    assert result["blockers"] == ["RUNTIME_TARGET_IDENTITY_UNAVAILABLE"]
    _assert_read_only_commands(commands)


def test_canonical_stable_local_origin_is_bound_to_project(tmp_path: Path) -> None:
    project, stable, head, old_head = _repository_pair(tmp_path)
    _run(["git", "remote", "set-url", "origin", str(project)], stable)
    manager, commands = _manager(project, stable, head, health=_health(old_head))

    result = manager.status(runtime_target=COLAMETA_STABLE_LOCAL_TARGET)

    assert _state(result) == "READY_FOR_EXTERNAL_RUNTIME_PROMOTION"
    _assert_read_only_commands(commands)


def test_foreign_loopback_listener_cannot_impersonate_stable_service(tmp_path: Path) -> None:
    project, stable, head, old_head = _repository_pair(tmp_path)
    manager, commands = _manager(project, stable, head, health=_health(old_head))
    commands.listener_pid = 9999

    result = manager.status(runtime_target=COLAMETA_STABLE_LOCAL_TARGET)

    assert result["blockers"] == ["RUNTIME_TARGET_UNHEALTHY"]
    _assert_read_only_commands(commands)
