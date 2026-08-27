from __future__ import annotations

import os
import shlex
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from adapters.shell_adapter import ShellAdapter
from runner.acceptance_command_policy import (
    TRUSTED_ACCEPTANCE_PATH,
    AcceptanceExecutionPlan,
    TrustedPathIdentity,
)


def test_shell_adapter_runs_allowed_argv_command(tmp_path: Path) -> None:
    command = "python3 --version"

    result = ShellAdapter().run(command, project_root=str(tmp_path))

    assert result.exit_code == 0
    assert result.stdout.startswith("Python ")
    assert result.stderr == ""


def test_shell_adapter_rejects_shell_operator_without_side_effect(tmp_path) -> None:
    marker = tmp_path / "marker"
    command = f"{shlex.quote(sys.executable)} --version ; touch {shlex.quote(str(marker))}"

    result = ShellAdapter().run(command, project_root=str(tmp_path))

    assert result.exit_code == -2
    assert "Shell operators are not allowed" in result.stderr
    assert not marker.exists()


def test_shell_adapter_rejects_non_allowlisted_executable(tmp_path: Path) -> None:
    result = ShellAdapter().run("bash -lc 'echo no'", project_root=str(tmp_path))

    assert result.exit_code == -2
    assert "Executable is not allowed" in result.stderr


def test_shell_adapter_rejects_python_evaluation(tmp_path: Path) -> None:
    command = "python3 -c \"print('must-not-run')\""

    result = ShellAdapter().run(command, project_root=str(tmp_path))

    assert result.exit_code == -2
    assert "ACCEPTANCE_COMMAND_PYTHON_GRAMMAR_NOT_ALLOWED" in result.stderr
    assert "must-not-run" not in result.stdout


def test_shell_adapter_rejects_untrusted_absolute_python_path(tmp_path) -> None:
    alias = tmp_path / "python"
    alias.symlink_to(sys.executable)

    result = ShellAdapter().run(
        f"{shlex.quote(str(alias))} --version",
        project_root=str(tmp_path),
    )

    assert result.exit_code == -2
    assert "Executable paths are not trusted" in result.stderr


def test_shell_adapter_does_not_resolve_bare_executable_from_caller_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    malicious_bin = tmp_path / "bin"
    malicious_bin.mkdir()
    malicious_git = malicious_bin / "git"
    malicious_git.write_text("not executed\n", encoding="utf-8")
    malicious_git.chmod(0o755)
    captured: dict[str, object] = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["env"] = kwargs["env"]
        return SimpleNamespace(returncode=0, stdout="git version safe\n", stderr="")

    monkeypatch.setattr("adapters.shell_adapter.subprocess.run", fake_run)

    result = ShellAdapter().run(
        "git --version",
        env={"PATH": str(malicious_bin)},
        project_root=str(tmp_path),
    )

    assert result.exit_code == 0
    captured_argv = captured["argv"]
    captured_env = captured["env"]
    assert isinstance(captured_argv, list)
    assert isinstance(captured_env, dict)
    assert captured_argv[0] != str(malicious_git)
    assert str(captured_argv[0]).startswith("/")
    assert captured_argv[1:5] == [
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.hooksPath=/dev/null",
    ]
    assert captured_env["PATH"] == TRUSTED_ACCEPTANCE_PATH
    assert captured_env["GIT_CONFIG_NOSYSTEM"] == "1"
    assert captured_env["GIT_OPTIONAL_LOCKS"] == "0"


def test_shell_adapter_isolates_pytest_launcher_from_project_module_shadow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "pytest.py").write_text(
        "raise RuntimeError('must not be imported as launcher')\n",
        encoding="utf-8",
    )
    captured: dict[str, object] = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["env"] = kwargs["env"]
        return SimpleNamespace(returncode=0, stdout="pytest safe\n", stderr="")

    monkeypatch.setattr("adapters.shell_adapter.subprocess.run", fake_run)

    result = ShellAdapter().run(
        "pytest --version",
        project_root=str(tmp_path),
        env={
            "NODE_OPTIONS": "--require=/tmp/inject.js",
            "PYTHONPATH": str(tmp_path),
            "PYTEST_ADDOPTS": "-p malicious_plugin",
        },
    )

    assert result.exit_code == -2
    assert "ACCEPTANCE_COMMAND_TOOLCHAIN_UNPROVEN" in result.stderr
    assert captured == {}


def test_isolated_pytest_entry_runs_without_importing_project_shadow(
    tmp_path: Path,
) -> None:
    (tmp_path / "pytest.py").write_text(
        "raise RuntimeError('project shadow imported')\n",
        encoding="utf-8",
    )

    result = ShellAdapter().run(
        "pytest --version",
        project_root=str(tmp_path),
    )

    assert result.exit_code == -2
    assert "ACCEPTANCE_COMMAND_TOOLCHAIN_UNPROVEN" in result.stderr
    assert "project shadow imported" not in result.stderr


def test_shell_adapter_executes_pinned_fd_after_path_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    launcher = tmp_path / "launcher"
    swapped_launcher = tmp_path / "launcher.verified"
    shutil.copy2("/usr/bin/true", launcher)
    launcher_stat = launcher.stat()
    identity = TrustedPathIdentity(
        path=str(launcher),
        device=launcher_stat.st_dev,
        inode=launcher_stat.st_ino,
        owner=launcher_stat.st_uid,
        group=launcher_stat.st_gid,
        mode=launcher_stat.st_mode,
        size=launcher_stat.st_size,
        modified_ns=launcher_stat.st_mtime_ns,
        kind="executable",
    )
    plan = AcceptanceExecutionPlan(
        argv=(str(launcher),),
        project_root=str(tmp_path),
        executable=identity,
    )
    real_run = __import__("subprocess").run

    monkeypatch.setattr(
        "adapters.shell_adapter.acceptance_command_to_execution_plan",
        lambda command, project_root: plan,
    )
    monkeypatch.setattr(
        "adapters.shell_adapter.verify_acceptance_execution_plan",
        lambda execution_plan: None,
    )

    def swap_then_run(argv, **kwargs):
        launcher.rename(swapped_launcher)
        shutil.copy2("/usr/bin/false", launcher)
        pinned_fd = kwargs["pass_fds"][0]
        assert os.fstat(pinned_fd).st_ino == swapped_launcher.stat().st_ino
        assert os.fstat(pinned_fd).st_ino != launcher.stat().st_ino
        return real_run(argv, **kwargs)

    monkeypatch.setattr("adapters.shell_adapter.subprocess.run", swap_then_run)

    result = ShellAdapter().run("git --version", project_root=str(tmp_path))

    assert result.exit_code == 0


def test_shell_adapter_rejects_removed_helper_after_support_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    script = scripts_dir / "check_clean_worktree.py"
    replacement = tmp_path / "replacement.py"
    script.write_text("raise SystemExit(0)\n", encoding="utf-8")
    replacement.write_text("import subprocess\nsubprocess.run(['git'])\n", encoding="utf-8")
    replacement.replace(script)
    subprocess_called = False

    def fake_run(*args, **kwargs):
        nonlocal subprocess_called
        subprocess_called = True
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("adapters.shell_adapter.subprocess.run", fake_run)

    result = ShellAdapter().run(
        "python3 scripts/check_clean_worktree.py",
        project_root=str(tmp_path),
    )

    assert result.exit_code == -2
    assert "ACCEPTANCE_COMMAND_PYTHON_GRAMMAR_NOT_ALLOWED" in result.stderr
    assert subprocess_called is False


def test_shell_adapter_rejects_compileall_before_subprocess(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subprocess_called = False

    def fake_run(*args, **kwargs):
        nonlocal subprocess_called
        subprocess_called = True
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("adapters.shell_adapter.subprocess.run", fake_run)

    result = ShellAdapter().run(
        "python3 -m compileall -q runner",
        project_root=str(tmp_path),
    )

    assert result.exit_code == -2
    assert "ACCEPTANCE_COMMAND_PYTHON_MODULE_NOT_ALLOWED" in result.stderr
    assert subprocess_called is False


def test_shell_adapter_rechecks_identity_before_subprocess(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subprocess_called = False

    def reject_changed_identity(plan) -> None:
        raise RuntimeError("identity check marker")

    def fake_run(*args, **kwargs):
        nonlocal subprocess_called
        subprocess_called = True
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(
        "adapters.shell_adapter.verify_acceptance_execution_plan",
        reject_changed_identity,
    )
    monkeypatch.setattr("adapters.shell_adapter.subprocess.run", fake_run)

    result = ShellAdapter().run("git --version", project_root=str(tmp_path))

    assert result.exit_code == -2
    assert "identity check marker" in result.stderr
    assert subprocess_called is False
