from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from runner.mcp_managed_runtime_closeout import (
    CANONICAL_EXTERNAL_RUNTIME_HEALTH_URL,
    CANONICAL_STABLE_HEALTH_URL,
    COLAMETA_STABLE_LOCAL_TARGET,
    MCPManagedRuntimeCloseoutManager,
    _listener_matches_service,
    _normalize_git_object_identity,
    _parse_systemctl_show_exact,
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
        self.external_service_pid = 5678
        self.external_listener_pid = 5678
        self.external_service_active = True
        self.external_service_running = True
        self.external_listener_rows: list[str] | None = None
        self.systemctl_show_stdout: str | None = None
        self.systemctl_show_external_stdout: str | None = None
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str], cwd: str) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(args))
        if args[:2] == ["systemctl", "show"]:
            external = args[2] == "colameta-mcp-remote.service"
            override = (
                self.systemctl_show_external_stdout
                if external
                else self.systemctl_show_stdout
            )
            if override is not None:
                return subprocess.CompletedProcess(args, 0, override, "")
            service_active = (
                self.external_service_active if external else self.service_active
            )
            service_pid = self.external_service_pid if external else self.service_pid
            service_running = self.external_service_running if external else service_active
            return subprocess.CompletedProcess(
                args,
                0,
                (
                    f"ActiveState={'active' if service_active else 'inactive'}\n"
                    f"SubState={'running' if service_running else 'dead'}\n"
                    f"MainPID={service_pid}\n"
                ),
                "",
            )
        if args[:3] == ["ss", "-H", "-ltnp"]:
            external = args[-1] == ":8767"
            port = 8767 if external else 8766
            listener_pid = self.external_listener_pid if external else self.listener_pid
            if external and self.external_listener_rows is not None:
                stdout = "".join(f"{row}\n" for row in self.external_listener_rows)
            else:
                stdout = (
                    f'LISTEN 0 128 127.0.0.1:{port} 0.0.0.0:* '
                    f'users:(("python",pid={listener_pid},fd=9))\n'
                )
            return subprocess.CompletedProcess(
                args,
                0,
                stdout,
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
    auth_mode: str | None = None,
    service: str | None = "colameta-mcp",
) -> dict[str, object]:
    result: dict[str, object] = {
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
    if auth_mode is not None:
        result["auth_mode"] = auth_mode
    if service is not None:
        result["service"] = service
    return result


def _manager(
    project: Path,
    stable: Path,
    head: str,
    *,
    health: dict[str, object],
    external_health: dict[str, object] | None = None,
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
        external_health_reader=lambda: external_health
        if external_health is not None
        else _health(head, auth_mode="external-oauth"),
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
            assert args[:2] == ["systemctl", "show"]
            assert args[2] in {
                "colameta-stable.service",
                "colameta-mcp-remote.service",
            }
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
    assert handoff["target"] == COLAMETA_STABLE_LOCAL_TARGET
    assert handoff["required_targets"] == [COLAMETA_STABLE_LOCAL_TARGET]
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
    assert closeout["external_runtime"]["exact_loaded_code_verified"] is True
    _assert_read_only_commands(commands)


def test_stable_exact_external_runtime_behind_requires_external_promotion(
    tmp_path: Path,
) -> None:
    project, stable, head, old_head = _repository_pair(tmp_path)
    _run(["git", "fetch", str(project), "main"], stable)
    _run(["git", "checkout", "--detach", head], stable)
    manager, commands = _manager(
        project,
        stable,
        head,
        health=_health(head),
        external_health=_health(old_head, auth_mode="external-oauth"),
    )

    result = manager.status(runtime_target=COLAMETA_STABLE_LOCAL_TARGET)

    assert _state(result) == "READY_FOR_EXTERNAL_RUNTIME_PROMOTION"
    closeout = result["result"]["runtime_closeout"]  # type: ignore[index]
    assert "delivery" not in closeout
    assert closeout["external_runtime"]["runtime_project_checkout_head"] == old_head
    handoff = closeout["external_runtime_promotion"]
    assert handoff["target"] == "colameta_external_web_gpt_mcp"
    assert handoff["required_targets"] == ["colameta_external_web_gpt_mcp"]
    assert handoff["authority"]["colaMeta_can_apply"] is False
    _assert_read_only_commands(commands)


def test_external_runtime_listener_must_belong_to_remote_service(tmp_path: Path) -> None:
    project, stable, head, old_head = _repository_pair(tmp_path)
    manager, commands = _manager(project, stable, head, health=_health(old_head))
    commands.external_listener_pid = 9999

    result = manager.status(runtime_target=COLAMETA_STABLE_LOCAL_TARGET)

    assert result["blockers"] == ["EXTERNAL_RUNTIME_UNHEALTHY"]
    _assert_read_only_commands(commands)


def test_both_stable_and_external_runtime_behind_require_both_targets(
    tmp_path: Path,
) -> None:
    project, stable, head, old_head = _repository_pair(tmp_path)
    manager, commands = _manager(
        project,
        stable,
        head,
        health=_health(old_head),
        external_health=_health(old_head, auth_mode="external-oauth"),
    )

    result = manager.status(runtime_target=COLAMETA_STABLE_LOCAL_TARGET)

    handoff = result["result"]["runtime_closeout"]["external_runtime_promotion"]  # type: ignore[index]
    assert handoff["target"] == "multiple_runtime_targets"
    assert handoff["required_targets"] == [
        COLAMETA_STABLE_LOCAL_TARGET,
        "colameta_external_web_gpt_mcp",
    ]
    _assert_read_only_commands(commands)


def test_external_runtime_rejects_cross_row_listener_pid_splice(tmp_path: Path) -> None:
    project, stable, head, old_head = _repository_pair(tmp_path)
    manager, commands = _manager(project, stable, head, health=_health(old_head))
    commands.external_listener_rows = [
        'LISTEN 0 128 10.0.0.1:8767 0.0.0.0:* users:(("python",pid=5678,fd=9))',
        'LISTEN 0 128 127.0.0.1:8767 0.0.0.0:* users:(("other",pid=9999,fd=10))',
    ]

    result = manager.status(runtime_target=COLAMETA_STABLE_LOCAL_TARGET)

    assert result["blockers"] == ["EXTERNAL_RUNTIME_UNHEALTHY"]
    _assert_read_only_commands(commands)


def test_external_runtime_rejects_multiple_listener_rows(tmp_path: Path) -> None:
    project, stable, head, old_head = _repository_pair(tmp_path)
    manager, commands = _manager(project, stable, head, health=_health(old_head))
    exact_row = (
        'LISTEN 0 128 127.0.0.1:8767 0.0.0.0:* '
        'users:(("python",pid=5678,fd=9))'
    )
    commands.external_listener_rows = [exact_row, exact_row]

    result = manager.status(runtime_target=COLAMETA_STABLE_LOCAL_TARGET)

    assert result["blockers"] == ["EXTERNAL_RUNTIME_UNHEALTHY"]
    _assert_read_only_commands(commands)


def test_external_runtime_rejects_multiple_owners_on_one_listener(tmp_path: Path) -> None:
    project, stable, head, old_head = _repository_pair(tmp_path)
    manager, commands = _manager(project, stable, head, health=_health(old_head))
    commands.external_listener_rows = [
        'LISTEN 0 128 127.0.0.1:8767 0.0.0.0:* '
        'users:(("python",pid=5678,fd=9),("other",pid=9999,fd=10))'
    ]

    result = manager.status(runtime_target=COLAMETA_STABLE_LOCAL_TARGET)

    assert result["blockers"] == ["EXTERNAL_RUNTIME_UNHEALTHY"]
    _assert_read_only_commands(commands)


@pytest.mark.parametrize("address", ("0.0.0.0", "::", "::1"))
def test_external_runtime_rejects_wildcard_listener(
    tmp_path: Path,
    address: str,
) -> None:
    project, stable, head, old_head = _repository_pair(tmp_path)
    manager, commands = _manager(project, stable, head, health=_health(old_head))
    local = f"[{address}]:8767" if ":" in address else f"{address}:8767"
    commands.external_listener_rows = [
        f'LISTEN 0 128 {local} 0.0.0.0:* users:(("python",pid=5678,fd=9))'
    ]

    result = manager.status(runtime_target=COLAMETA_STABLE_LOCAL_TARGET)

    assert result["blockers"] == ["EXTERNAL_RUNTIME_UNHEALTHY"]
    _assert_read_only_commands(commands)


@pytest.mark.parametrize(
    "row",
    (
        "LISTEN 0 128 127.0.0.1:8767 0.0.0.0:*",
        "unparseable listener evidence",
    ),
)
def test_external_runtime_rejects_missing_or_unparseable_process_metadata(
    tmp_path: Path,
    row: str,
) -> None:
    project, stable, head, old_head = _repository_pair(tmp_path)
    manager, commands = _manager(project, stable, head, health=_health(old_head))
    commands.external_listener_rows = [row]

    result = manager.status(runtime_target=COLAMETA_STABLE_LOCAL_TARGET)

    assert result["blockers"] == ["EXTERNAL_RUNTIME_UNHEALTHY"]
    _assert_read_only_commands(commands)


@pytest.mark.parametrize(
    ("metadata", "expected"),
    (
        ("this-is-not-ss-owner-metadata pid=5678", False),
        ('users:(("python",pid=5678,fd=9),("other",pid=9999))', False),
        ('users:(("python",pid=5678),("other",pid=5678,fd=10))', False),
        ('users:(("python",pid=5678,pid=5678,fd=9))', False),
        ('users:(("python",pid=5678))', False),
        ('users:(("python",pid=5678,fd=9,fd=10))', False),
        ('users:(("python",pid=5678,fd=9,uid=1000))', False),
        ('users:(("python",pid=5678,fd=9)) trailing', False),
        ('users:(("python",pid=5678,fd=9),("other",pid=9999,fd=10))', False),
        ('users:(("python",pid=5678,fd=9),("other",pid=5678,fd=10))', False),
        ('users:(("pid=5678",fd=9))', False),
        ('users:(("python",pid=0,fd=9))', False),
        ('users:(("python",pid=05678,fd=9))', False),
        ('users:(("python",pid=99999999999,fd=9))', False),
        ('users:(("python",pid=5678,fd=9))', True),
    ),
    ids=(
        "arbitrary-prefix-plus-pid",
        "valid-owner-plus-partial-second-owner",
        "malformed-first-owner-plus-valid-second-owner",
        "duplicate-pid",
        "missing-fd",
        "duplicate-fd",
        "unknown-owner-field",
        "trailing-garbage",
        "multiple-complete-owners",
        "two-owners-same-main-pid",
        "pid-substring-in-process-name",
        "zero-pid",
        "leading-zero-pid",
        "overlong-pid",
        "exact-single-owner-main-pid",
    ),
)
def test_external_listener_owner_metadata_requires_complete_grammar(
    metadata: str,
    expected: bool,
) -> None:
    row = f"LISTEN 0 128 127.0.0.1:8767 0.0.0.0:* {metadata}"

    assert _listener_matches_service(
        row,
        expected_address="127.0.0.1",
        expected_port=8767,
        main_pid=5678,
    ) is expected


@pytest.mark.parametrize(
    "metadata",
    (
        "this-is-not-ss-owner-metadata pid=5678",
        'users:(("python",pid=5678,fd=9),("other",pid=5678))',
    ),
    ids=("reviewer-arbitrary-pid-substring", "reviewer-partial-second-owner"),
)
def test_external_runtime_rejects_reviewer_malformed_owner_reproductions(
    tmp_path: Path,
    metadata: str,
) -> None:
    project, stable, head, _ = _repository_pair(tmp_path)
    _run(["git", "fetch", str(project), "main"], stable)
    _run(["git", "checkout", "--detach", head], stable)
    manager, commands = _manager(project, stable, head, health=_health(head))
    commands.external_listener_rows = [
        f"LISTEN 0 128 127.0.0.1:8767 0.0.0.0:* {metadata}"
    ]

    result = manager.status(runtime_target=COLAMETA_STABLE_LOCAL_TARGET)

    assert result["blockers"] == ["EXTERNAL_RUNTIME_UNHEALTHY"]
    closeout = result["result"]["runtime_closeout"]  # type: ignore[index]
    assert "delivery" not in closeout
    _assert_read_only_commands(commands)


def test_external_runtime_accepts_single_exact_loopback_listener_owned_by_main_pid(
    tmp_path: Path,
) -> None:
    project, stable, head, old_head = _repository_pair(tmp_path)
    manager, commands = _manager(project, stable, head, health=_health(old_head))

    result = manager.status(runtime_target=COLAMETA_STABLE_LOCAL_TARGET)

    closeout = result["result"]["runtime_closeout"]  # type: ignore[index]
    assert result["blockers"] == []
    assert closeout["external_runtime"]["exact_loaded_code_verified"] is True
    _assert_read_only_commands(commands)


def test_external_runtime_rejects_unresolved_main_pid(tmp_path: Path) -> None:
    project, stable, head, old_head = _repository_pair(tmp_path)
    manager, commands = _manager(project, stable, head, health=_health(old_head))
    commands.external_service_pid = 0

    result = manager.status(runtime_target=COLAMETA_STABLE_LOCAL_TARGET)

    assert result["blockers"] == ["EXTERNAL_RUNTIME_UNHEALTHY"]
    _assert_read_only_commands(commands)


def _assert_external_service_identity_rejected(
    tmp_path: Path,
    *,
    service: str | None,
) -> None:
    project, stable, head, old_head = _repository_pair(tmp_path)
    external_health = _health(
        head,
        auth_mode="external-oauth",
        service=service,
    )
    manager, commands = _manager(
        project,
        stable,
        head,
        health=_health(old_head),
        external_health=external_health,
    )

    result = manager.status(runtime_target=COLAMETA_STABLE_LOCAL_TARGET)

    assert result["blockers"] == [
        "EXTERNAL_RUNTIME_APPLICATION_IDENTITY_MISMATCH"
    ]
    _assert_read_only_commands(commands)


def test_external_runtime_rejects_missing_service_identity(tmp_path: Path) -> None:
    _assert_external_service_identity_rejected(tmp_path, service=None)


@pytest.mark.parametrize("service", ("", "other-application"))
def test_external_runtime_rejects_wrong_service_identity(
    tmp_path: Path,
    service: str,
) -> None:
    _assert_external_service_identity_rejected(tmp_path, service=service)


def test_external_runtime_accepts_service_colameta_mcp(tmp_path: Path) -> None:
    project, stable, head, old_head = _repository_pair(tmp_path)
    manager, commands = _manager(project, stable, head, health=_health(old_head))

    result = manager.status(runtime_target=COLAMETA_STABLE_LOCAL_TARGET)

    external = result["result"]["runtime_closeout"]["external_runtime"]  # type: ignore[index]
    assert external["application_service"] == "colameta-mcp"
    assert external["application_identity_matches"] is True
    _assert_read_only_commands(commands)


def test_external_runtime_rejects_stale_loaded_code(tmp_path: Path) -> None:
    project, stable, head, old_head = _repository_pair(tmp_path)
    external_health = _health(head, auth_mode="external-oauth")
    external_health["runtime_loaded_code_stale"] = True
    manager, commands = _manager(
        project,
        stable,
        head,
        health=_health(old_head),
        external_health=external_health,
    )

    result = manager.status(runtime_target=COLAMETA_STABLE_LOCAL_TARGET)

    assert result["blockers"] == ["EXTERNAL_RUNTIME_FRESHNESS_INCONSISTENT"]
    _assert_read_only_commands(commands)


@pytest.mark.parametrize(
    "value",
    (
        "not-a-commit",
        "",
        "   ",
        "g" * 40,
        "a" * 39,
        "a" * 65,
        "a" * 40 + "-suffix",
    ),
    ids=(
        "not-a-commit",
        "empty",
        "whitespace-only",
        "non-hex",
        "truncated",
        "oversized",
        "valid-prefix-plus-suffix",
    ),
)
def test_git_object_identity_rejects_present_malformed_values(value: str) -> None:
    assert _normalize_git_object_identity(value) is None


@pytest.mark.parametrize("length", (40, 64))
def test_git_object_identity_accepts_and_normalizes_full_hash(length: int) -> None:
    value = "A" * length

    assert _normalize_git_object_identity(value) == "a" * length


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("runtime_project_checkout_head", "not-a-commit"),
        ("loaded_runtime_head", "a" * 40 + "-suffix"),
    ),
)
def test_external_runtime_rejects_malformed_health_git_identity(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    project, stable, head, old_head = _repository_pair(tmp_path)
    external_health = _health(head, auth_mode="external-oauth")
    external_health[field] = value
    manager, commands = _manager(
        project,
        stable,
        head,
        health=_health(old_head),
        external_health=external_health,
    )

    result = manager.status(runtime_target=COLAMETA_STABLE_LOCAL_TARGET)

    assert result["blockers"] == ["EXTERNAL_RUNTIME_PROVENANCE_INCONSISTENT"]
    closeout = result["result"]["runtime_closeout"]  # type: ignore[index]
    assert closeout["external_runtime"]["exact_loaded_code_verified"] is False
    assert "delivery" not in closeout
    _assert_read_only_commands(commands)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("runtime_project_checkout_head", "not-a-commit"),
        ("loaded_runtime_head", "a" * 39),
    ),
)
def test_stable_runtime_rejects_malformed_health_git_identity(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    project, stable, head, old_head = _repository_pair(tmp_path)
    health = _health(old_head)
    health[field] = value
    manager, commands = _manager(project, stable, head, health=health)

    result = manager.status(runtime_target=COLAMETA_STABLE_LOCAL_TARGET)

    assert result["blockers"] == ["RUNTIME_PROVENANCE_INCONSISTENT"]
    closeout = result["result"]["runtime_closeout"]  # type: ignore[index]
    assert closeout["runtime_target"]["exact_loaded_code_verified"] is False
    _assert_read_only_commands(commands)


def test_external_runtime_rejects_wrong_auth_mode(tmp_path: Path) -> None:
    project, stable, head, old_head = _repository_pair(tmp_path)
    manager, commands = _manager(
        project,
        stable,
        head,
        health=_health(old_head),
        external_health=_health(head, auth_mode="none"),
    )

    result = manager.status(runtime_target=COLAMETA_STABLE_LOCAL_TARGET)

    assert result["blockers"] == ["EXTERNAL_RUNTIME_UNHEALTHY"]
    _assert_read_only_commands(commands)


@pytest.mark.parametrize("failure", ("inactive", "not_running"))
def test_external_runtime_rejects_inactive_or_not_running_service(
    tmp_path: Path,
    failure: str,
) -> None:
    project, stable, head, old_head = _repository_pair(tmp_path)
    manager, commands = _manager(project, stable, head, health=_health(old_head))
    if failure == "inactive":
        commands.external_service_active = False
    else:
        commands.external_service_running = False

    result = manager.status(runtime_target=COLAMETA_STABLE_LOCAL_TARGET)

    assert result["blockers"] == ["EXTERNAL_RUNTIME_UNHEALTHY"]
    _assert_read_only_commands(commands)


def test_external_health_reader_uses_exact_zero_redirect_contract() -> None:
    class _HealthResponse:
        status = 200

        def __enter__(self) -> "_HealthResponse":
            return self

        def __exit__(self, *_: object) -> bool:
            return False

        def geturl(self) -> str:
            return CANONICAL_EXTERNAL_RUNTIME_HEALTH_URL

        def read(self, _: int) -> bytes:
            return b"{}"

    with patch(
        "runner.mcp_managed_runtime_closeout.open_http_url",
        return_value=_HealthResponse(),
    ) as opener:
        assert MCPManagedRuntimeCloseoutManager._read_external_health() == {}

    request = opener.call_args.args[0]
    kwargs = opener.call_args.kwargs
    assert request.full_url == CANONICAL_EXTERNAL_RUNTIME_HEALTH_URL
    assert request.get_method() == "GET"
    assert kwargs["timeout"] == 2
    assert kwargs["allowed_schemes"] == ("http",)
    assert kwargs["redirect_policy"].allow_redirects is False
    assert kwargs["redirect_policy"].allow_cross_host is False
    assert kwargs["redirect_policy"].reject_https_downgrade is True
    assert kwargs["allow_environment_proxy"] is False


def test_external_health_reader_rejects_noncanonical_final_url() -> None:
    class _RedirectedHealthResponse:
        status = 200

        def __enter__(self) -> "_RedirectedHealthResponse":
            return self

        def __exit__(self, *_: object) -> bool:
            return False

        def geturl(self) -> str:
            return "http://127.0.0.1:9999/forged-health"

        def read(self, _: int) -> bytes:
            raise AssertionError("redirected response body must not be read")

    with patch(
        "runner.mcp_managed_runtime_closeout.open_http_url",
        return_value=_RedirectedHealthResponse(),
    ):
        with pytest.raises(RuntimeError, match="endpoint identity"):
            MCPManagedRuntimeCloseoutManager._read_external_health()


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


# ---------------------------------------------------------------------------
# R3: strict `systemctl show` full-consumption grammar
# ---------------------------------------------------------------------------

_VALID_SHOW = "ActiveState=active\nSubState=running\nMainPID=5678\n"


@pytest.mark.parametrize(
    "stdout",
    (
        # SC1: duplicate state field must fail closed (no last-write-wins).
        "ActiveState=active\nActiveState=inactive\nSubState=running\nMainPID=5678\n",
        # SC2: duplicate numeric field must fail closed.
        "ActiveState=active\nSubState=running\nMainPID=5678\nMainPID=5678\n",
        # SC3: unknown property must fail closed.
        "ActiveState=active\nSubState=running\nMainPID=5678\nUnknownProperty=value\n",
        # SC4: malformed suffix line after all valid lines must fail closed.
        "ActiveState=active\nSubState=running\nMainPID=5678\ngarbage\n",
        "ActiveState=active\nSubState=running\nMainPID=5678\n=value\n",
        # SC5: line without '=' must fail closed.
        "ActiveState=active\nSubState=running\nMainPID=5678\nline_without_equals\n",
        # SC6: empty key line must fail closed.
        "ActiveState=active\nSubState=running\nMainPID=5678\n=value\n",
        # Missing expected key.
        "ActiveState=active\nSubState=running\n",
        # Extra blank line (real empty record, not the terminal newline).
        "ActiveState=active\nSubState=running\nMainPID=5678\n\n",
        # Empty stdout.
        "",
        # Leading/trailing whitespace around keys.
        " ActiveState=active\nSubState=running\nMainPID=5678\n",
        "ActiveState=active\nSubState=running\nMainPID=5678 \n",
        # Non-ASCII or control state value.
        "ActiveState=ａctive\nSubState=running\nMainPID=5678\n",
        "ActiveState=active\nSubState=run\x00ning\nMainPID=5678\n",
        "ActiveState=active\nSubState= running\nMainPID=5678\n",
        # MainPID grammar violations.
        "ActiveState=active\nSubState=running\nMainPID=05678\n",
        "ActiveState=active\nSubState=running\nMainPID=５６７８\n",
        "ActiveState=active\nSubState=running\nMainPID=⁵⁶⁷⁸\n",
        "ActiveState=active\nSubState=running\nMainPID=5678x\n",
        "ActiveState=active\nSubState=running\nMainPID=+5678\n",
        "ActiveState=active\nSubState=running\nMainPID=-1\n",
        "ActiveState=active\nSubState=running\nMainPID=\n",
        "ActiveState=active\nSubState=running\nMainPID=1_23\n",
        "ActiveState=active\nSubState=running\nMainPID=1.0\n",
        "ActiveState=active\nSubState=running\nMainPID= 5678\n",
        "ActiveState=active\nSubState=running\nMainPID=5678 \n",
    ),
)
def test_systemctl_show_parser_rejects_incomplete_or_malformed_evidence(
    stdout: str,
) -> None:
    assert _parse_systemctl_show_exact(stdout) is None


def test_systemctl_show_parser_accepts_exact_complete_evidence() -> None:
    assert _parse_systemctl_show_exact(_VALID_SHOW) == {
        "ActiveState": "active",
        "SubState": "running",
        "MainPID": "5678",
    }
    # A single terminal newline is the text terminator, not an empty record.
    assert _parse_systemctl_show_exact(_VALID_SHOW[:-1]) == {
        "ActiveState": "active",
        "SubState": "running",
        "MainPID": "5678",
    }


def test_systemctl_show_parser_main_pid_zero_is_syntactically_valid() -> None:
    # SN9: MainPID=0 parses (valid ASCII decimal) but must fail service
    # active admission because the listener authority requires PID > 0.
    assert _parse_systemctl_show_exact(
        "ActiveState=active\nSubState=running\nMainPID=0\n"
    ) == {"ActiveState": "active", "SubState": "running", "MainPID": "0"}


def test_systemctl_show_parser_unknown_state_is_parsed_but_not_active() -> None:
    parsed = _parse_systemctl_show_exact(
        "ActiveState=degraded\nSubState=starting\nMainPID=5678\n"
    )
    assert parsed is not None
    assert parsed["ActiveState"] == "degraded"


def test_systemctl_show_parser_rejects_non_string_stdout() -> None:
    assert _parse_systemctl_show_exact(b"ActiveState=active\n") is None


def test_systemctl_show_parser_rejects_undeclared_grammar_properties() -> None:
    assert (
        _parse_systemctl_show_exact(
            "ActiveState=active\nSubState=running\nMainPID=5678\n",
            expected_properties=frozenset({"ActiveState", "SubState", "MainPID", "Nope"}),
        )
        is None
    )
    assert (
        _parse_systemctl_show_exact(
            "ActiveState=active\nSubState=running\nMainPID=5678\n",
            expected_properties=frozenset(),
        )
        is None
    )


def test_systemctl_show_parser_superscript_pid_never_raises() -> None:
    # SN4: superscript digits must be rejected without raising ValueError.
    parsed = _parse_systemctl_show_exact(
        "ActiveState=active\nSubState=running\nMainPID=⁵⁶⁷⁸\n"
    )
    assert parsed is None


def test_external_runtime_rejects_duplicate_systemctl_evidence(tmp_path: Path) -> None:
    project, stable, head, old_head = _repository_pair(tmp_path)
    manager, commands = _manager(project, stable, head, health=_health(old_head))
    commands.systemctl_show_external_stdout = (
        "ActiveState=active\nActiveState=inactive\nSubState=running\nMainPID=5678\n"
    )

    result = manager.status(runtime_target=COLAMETA_STABLE_LOCAL_TARGET)

    assert result["blockers"] == ["EXTERNAL_RUNTIME_UNHEALTHY"]
    closeout = result["result"]["runtime_closeout"]  # type: ignore[index]
    assert closeout["external_runtime"]["pid"] is None
    assert closeout["external_runtime"]["exact_loaded_code_verified"] is False
    _assert_read_only_commands(commands)


def test_external_runtime_rejects_unknown_systemctl_property(tmp_path: Path) -> None:
    project, stable, head, old_head = _repository_pair(tmp_path)
    manager, commands = _manager(project, stable, head, health=_health(old_head))
    commands.systemctl_show_external_stdout = (
        "ActiveState=active\nSubState=running\nMainPID=5678\nUnknownProperty=value\n"
    )

    result = manager.status(runtime_target=COLAMETA_STABLE_LOCAL_TARGET)

    assert result["blockers"] == ["EXTERNAL_RUNTIME_UNHEALTHY"]
    _assert_read_only_commands(commands)


def test_external_runtime_rejects_unicode_systemctl_pid_without_exception(
    tmp_path: Path,
) -> None:
    project, stable, head, old_head = _repository_pair(tmp_path)
    manager, commands = _manager(project, stable, head, health=_health(old_head))
    commands.systemctl_show_external_stdout = (
        "ActiveState=active\nSubState=running\nMainPID=５６７８\n"
    )

    result = manager.status(runtime_target=COLAMETA_STABLE_LOCAL_TARGET)

    assert result["blockers"] == ["EXTERNAL_RUNTIME_UNHEALTHY"]
    closeout = result["result"]["runtime_closeout"]  # type: ignore[index]
    assert closeout["external_runtime"]["pid"] is None
    assert closeout["external_runtime"]["service_state"] == "unhealthy_or_unavailable"
    _assert_read_only_commands(commands)


def test_external_runtime_main_pid_zero_is_not_active_admission(tmp_path: Path) -> None:
    project, stable, head, old_head = _repository_pair(tmp_path)
    manager, commands = _manager(project, stable, head, health=_health(old_head))
    commands.systemctl_show_external_stdout = (
        "ActiveState=active\nSubState=running\nMainPID=0\n"
    )

    result = manager.status(runtime_target=COLAMETA_STABLE_LOCAL_TARGET)

    assert result["blockers"] == ["EXTERNAL_RUNTIME_UNHEALTHY"]
    closeout = result["result"]["runtime_closeout"]  # type: ignore[index]
    assert closeout["external_runtime"]["pid"] is None
    _assert_read_only_commands(commands)


def test_stable_runtime_rejects_malformed_systemctl_evidence(tmp_path: Path) -> None:
    project, stable, head, old_head = _repository_pair(tmp_path)
    manager, commands = _manager(project, stable, head, health=_health(old_head))
    commands.systemctl_show_stdout = (
        "ActiveState=active\nSubState=running\nMainPID=1234\ntrailing junk\n"
    )

    result = manager.status(runtime_target=COLAMETA_STABLE_LOCAL_TARGET)

    assert result["blockers"] == ["RUNTIME_TARGET_UNHEALTHY"]
    _assert_read_only_commands(commands)


def test_bounded_service_truth_exposes_evidence_completeness(tmp_path: Path) -> None:
    project, stable, head, old_head = _repository_pair(tmp_path)
    manager, commands = _manager(project, stable, head, health=_health(old_head))

    complete = manager._bounded_service_truth("colameta-mcp-remote.service", 8767)
    assert complete["systemctl_evidence_complete"] is True

    commands.systemctl_show_external_stdout = (
        "ActiveState=active\nSubState=running\nMainPID=5678\nMainPID=5678\n"
    )
    malformed = manager._bounded_service_truth("colameta-mcp-remote.service", 8767)
    assert malformed["systemctl_evidence_complete"] is False
    assert malformed["active"] is False
    assert malformed["main_pid"] is None
    assert malformed["listener_owned"] is False


# ---------------------------------------------------------------------------
# R3: canonical loopback probes must use direct transport (no ambient proxy)
# ---------------------------------------------------------------------------


def test_stable_health_reader_uses_direct_loopback_keeping_redirect_semantics() -> None:
    class _HealthResponse:
        status = 200

        def __enter__(self) -> "_HealthResponse":
            return self

        def __exit__(self, *_: object) -> bool:
            return False

        def geturl(self) -> str:
            return CANONICAL_STABLE_HEALTH_URL

        def read(self, _: int) -> bytes:
            return b"{}"

    with patch(
        "runner.mcp_managed_runtime_closeout.open_http_url",
        return_value=_HealthResponse(),
    ) as opener:
        assert MCPManagedRuntimeCloseoutManager._read_health() == {}

    request = opener.call_args.args[0]
    kwargs = opener.call_args.kwargs
    assert request.full_url == CANONICAL_STABLE_HEALTH_URL
    assert kwargs["timeout"] == 5
    # Stable redirect semantics are unchanged by R3 (proxy behavior is the
    # only transport change authorised for the stable probe).
    assert kwargs["redirect_policy"].allow_redirects is True
    assert kwargs["redirect_policy"].allow_cross_host is False
    assert kwargs["allow_environment_proxy"] is False
