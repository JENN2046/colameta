from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path

import pytest

import runner.acceptance_command_policy as policy
from runner.acceptance_command_policy import (
    AcceptanceCommandPolicyError,
    acceptance_command_to_execution_plan,
    acceptance_command_rejection_code,
    acceptance_command_to_argv,
    acceptance_command_to_execution_argv,
    trusted_acceptance_environment,
    verify_acceptance_execution_plan,
)
from runner.acceptance_runner import AcceptanceRunner
from schemas.plan import AcceptanceCommand, BuildVersion


@pytest.mark.parametrize(
    "command",
    [
        "git diff --check",
        "git status --porcelain=v1 --untracked-files=all",
        "python3 --version",
    ],
)
def test_shell_free_acceptance_commands_are_allowed(command: str) -> None:
    assert acceptance_command_to_argv(command)
    assert acceptance_command_rejection_code(command) is None


@pytest.mark.parametrize(
    ("command", "code"),
    [
        ('test -z "$(git status --porcelain=v1)"', "ACCEPTANCE_COMMAND_SHELL_OPERATOR"),
        ("git diff --check && git status", "ACCEPTANCE_COMMAND_SHELL_OPERATOR"),
        ("git status | python3 -m json.tool", "ACCEPTANCE_COMMAND_SHELL_OPERATOR"),
        ("git status > result.txt", "ACCEPTANCE_COMMAND_SHELL_OPERATOR"),
        ("bash -lc 'git status'", "ACCEPTANCE_COMMAND_EXECUTABLE_NOT_ALLOWED"),
    ],
)
def test_unsafe_acceptance_commands_are_rejected(command: str, code: str) -> None:
    with pytest.raises(AcceptanceCommandPolicyError) as error:
        acceptance_command_to_argv(command)
    assert error.value.code == code
    assert acceptance_command_rejection_code(command) == code


@pytest.mark.parametrize(
    "executable",
    [
        "/tmp/python",
        "project-controlled/python",
        "./pytest",
    ],
)
def test_executable_paths_other_than_exact_runtime_are_rejected(executable: str) -> None:
    with pytest.raises(AcceptanceCommandPolicyError) as error:
        acceptance_command_to_argv(f"{executable} --version")
    assert error.value.code == "ACCEPTANCE_COMMAND_EXECUTABLE_PATH_NOT_TRUSTED"


def test_symlink_to_runtime_at_another_path_is_rejected(tmp_path: Path) -> None:
    alias = tmp_path / "python"
    alias.symlink_to(sys.executable)

    with pytest.raises(AcceptanceCommandPolicyError) as error:
        acceptance_command_to_argv(f"{alias} --version")

    assert error.value.code == "ACCEPTANCE_COMMAND_EXECUTABLE_PATH_NOT_TRUSTED"


def test_bare_python_is_bound_to_canonical_runtime_interpreter(tmp_path: Path) -> None:
    argv = acceptance_command_to_execution_argv(
        "python3 --version",
        project_root=str(tmp_path),
    )

    assert argv == [
        policy._runtime_interpreter_identity(str(tmp_path)).path,
        "-I",
        "-P",
        "-s",
        "-E",
        "--version",
    ]


def test_trusted_environment_is_a_fixed_minimal_allowlist() -> None:
    env = trusted_acceptance_environment(
        {
            "PATH": "/tmp/untrusted-bin",
            "PYTHONHOME": "/tmp/untrusted-home",
            "PYTHONPATH": "/tmp/untrusted-modules",
            "NODE_OPTIONS": "--require=/tmp/inject.js",
            "PYTEST_ADDOPTS": "-p malicious_plugin",
            "RUFF_CACHE_DIR": "/tmp/ruff-inject",
            "COLAMETA_TEST_VALUE": "must-not-cross-boundary",
        }
    )

    assert "/tmp/untrusted-bin" not in env["PATH"]
    for key in (
        "PYTHONHOME",
        "PYTHONPATH",
        "NODE_OPTIONS",
        "PYTEST_ADDOPTS",
        "RUFF_CACHE_DIR",
        "COLAMETA_TEST_VALUE",
    ):
        assert key not in env
    assert env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"
    assert env["PYTHONSAFEPATH"] == "1"


def test_runtime_interpreter_inside_project_is_blocked_with_stable_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    runtime = project / ".venv" / "bin" / "python"
    runtime.parent.mkdir(parents=True)
    runtime.write_text("not executed\n", encoding="utf-8")
    runtime.chmod(0o700)
    monkeypatch.setattr(policy.sys, "executable", str(runtime))
    monkeypatch.setattr(policy.sys, "_base_executable", str(runtime))

    with pytest.raises(AcceptanceCommandPolicyError) as error:
        acceptance_command_to_execution_plan(
            "python3 --version",
            project_root=str(project),
        )

    assert error.value.code == "ACCEPTANCE_RUNTIME_INTERPRETER_IN_PROJECT"


def test_runtime_interpreter_under_tmp_is_blocked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = tmp_path / "external" / "python"
    runtime.parent.mkdir()
    runtime.write_text("not executed\n", encoding="utf-8")
    runtime.chmod(0o700)
    monkeypatch.setattr(policy.sys, "executable", str(runtime))
    monkeypatch.setattr(policy.sys, "_base_executable", str(runtime))

    with pytest.raises(AcceptanceCommandPolicyError) as error:
        acceptance_command_to_execution_plan(
            "python3 --version",
            project_root="/home/jenn/src/colameta-dev",
        )

    assert error.value.code == "ACCEPTANCE_EXECUTABLE_IN_TEMP_ROOT"


def test_user_owned_external_runtime_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = tmp_path / "external-python"
    runtime.write_text("not executed\n", encoding="utf-8")
    runtime.chmod(0o700)
    monkeypatch.setattr(policy, "_DISALLOWED_TEMP_ROOTS", ())
    monkeypatch.setattr(policy, "_path_components", lambda path: [path])
    monkeypatch.setattr(policy.sys, "executable", str(runtime))
    monkeypatch.setattr(policy.sys, "_base_executable", str(runtime))

    with pytest.raises(AcceptanceCommandPolicyError) as error:
        acceptance_command_to_execution_plan(
            "python3 --version",
            project_root="/home/jenn/src/colameta-dev",
        )

    assert error.value.code == "ACCEPTANCE_COMMAND_EXECUTABLE_OWNER_NOT_TRUSTED"


def test_third_party_python_launcher_fails_closed_before_resolution() -> None:
    with pytest.raises(AcceptanceCommandPolicyError) as error:
        acceptance_command_to_execution_plan(
            "pytest --version",
            project_root="/home/jenn/src/colameta-dev",
        )

    assert error.value.code == "ACCEPTANCE_COMMAND_TOOLCHAIN_UNPROVEN"


@pytest.mark.parametrize(
    "command",
    [
        "python3 -c pass",
        "python3 -",
        "python3",
        "python3 -I -m compileall -q runner",
        "python3 -q -m compileall runner",
        "python3 -m compileall -q runner",
        "python3 -m compileall -j 4 runner",
        "python3 -m compileall --invalidation-mode checked-hash runner",
        "python3 /tmp/external.py",
        "python3 scripts/other.py",
        "python3 scripts/check_clean_worktree.py",
        "python3 scripts/check_clean_worktree.py --verbose",
    ],
)
def test_python_requires_an_exact_approved_grammar(command: str) -> None:
    with pytest.raises(AcceptanceCommandPolicyError) as error:
        acceptance_command_to_argv(command)

    assert error.value.code in {
        "ACCEPTANCE_COMMAND_ARGUMENTS_NOT_ALLOWED",
        "ACCEPTANCE_COMMAND_PYTHON_GRAMMAR_NOT_ALLOWED",
        "ACCEPTANCE_COMMAND_PYTHON_MODULE_NOT_ALLOWED",
    }


@pytest.mark.parametrize(
    "command",
    [
        "node --eval console.log(1)",
        "node safe.js",
        "npm test",
        "npx pytest",
        "pnpm test",
        "yarn test",
        "make test",
        "go test ./...",
        "cargo test",
        "tox -q",
        "nox -s tests",
        "ruff check .",
        "pyright",
        "uv run pytest",
    ],
)
def test_secondary_resolving_launchers_fail_closed(command: str) -> None:
    with pytest.raises(AcceptanceCommandPolicyError) as error:
        acceptance_command_to_argv(command)

    assert error.value.code == "ACCEPTANCE_COMMAND_TOOLCHAIN_UNPROVEN"


@pytest.mark.parametrize(
    "command",
    [
        "git -c alias.run=!sh run",
        "git diff --ext-diff --check",
        "git diff --check -- runner",
        "git status --porcelain=v2",
        "git push",
    ],
)
def test_git_requires_an_exact_read_only_grammar(command: str) -> None:
    with pytest.raises(AcceptanceCommandPolicyError) as error:
        acceptance_command_to_argv(command)

    assert error.value.code == "ACCEPTANCE_COMMAND_GIT_GRAMMAR_NOT_ALLOWED"


def test_compileall_is_rejected_before_resolution_closure(tmp_path: Path) -> None:
    with pytest.raises(AcceptanceCommandPolicyError) as error:
        acceptance_command_to_execution_plan(
            "python3 -m compileall -q runner tests",
            project_root=str(tmp_path),
        )

    assert error.value.code == "ACCEPTANCE_COMMAND_PYTHON_MODULE_NOT_ALLOWED"


def test_git_diff_plan_disables_secondary_diff_resolution(tmp_path: Path) -> None:
    plan = acceptance_command_to_execution_plan(
        "git diff --check",
        project_root=str(tmp_path),
    )

    assert plan.argv[1:] == (
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.hooksPath=/dev/null",
        "diff",
        "--no-ext-diff",
        "--no-textconv",
        "--check",
    )


def test_clean_worktree_helper_is_removed_from_executable_grammar(
    tmp_path: Path,
) -> None:
    script = tmp_path / "scripts" / "check_clean_worktree.py"
    script.parent.mkdir()
    script.write_text("raise SystemExit(0)\n", encoding="utf-8")

    with pytest.raises(AcceptanceCommandPolicyError) as error:
        acceptance_command_to_execution_plan(
            "python3 scripts/check_clean_worktree.py",
            project_root=str(tmp_path),
        )

    assert error.value.code == "ACCEPTANCE_COMMAND_PYTHON_GRAMMAR_NOT_ALLOWED"


def test_removed_helper_support_replacement_remains_rejected(
    tmp_path: Path,
) -> None:
    script = tmp_path / "scripts" / "check_clean_worktree.py"
    script.parent.mkdir()
    script.write_text("raise SystemExit(0)\n", encoding="utf-8")
    replacement = tmp_path / "replacement.py"
    replacement.write_text("import subprocess\nsubprocess.run(['git'])\n", encoding="utf-8")
    replacement.replace(script)

    with pytest.raises(AcceptanceCommandPolicyError) as error:
        acceptance_command_to_execution_plan(
            "python3 scripts/check_clean_worktree.py",
            project_root=str(tmp_path),
        )

    assert error.value.code == "ACCEPTANCE_COMMAND_PYTHON_GRAMMAR_NOT_ALLOWED"


@pytest.mark.parametrize(
    "command",
    [
        "python3 --version",
        "git --version",
        "git diff --check",
        "git status --porcelain=v1 --untracked-files=all",
    ],
)
def test_approved_plans_expose_no_path_reopened_support_items(
    tmp_path: Path,
    command: str,
) -> None:
    plan = acceptance_command_to_execution_plan(command, project_root=str(tmp_path))

    assert set(plan.__dataclass_fields__) == {"argv", "project_root", "executable"}
    assert plan.argv[0] == plan.executable.path


def test_trusted_tool_symlink_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alias = tmp_path / "git"
    alias.symlink_to("/usr/bin/git")
    monkeypatch.setattr(policy, "_DISALLOWED_TEMP_ROOTS", ())
    monkeypatch.setattr(policy, "_path_components", lambda path: [path])

    with pytest.raises(AcceptanceCommandPolicyError) as error:
        policy._trusted_path_identity(
            str(alias),
            project_root="/home/jenn/src/colameta-dev",
            kind="executable",
            executable=True,
        )

    assert error.value.code == "ACCEPTANCE_COMMAND_EXECUTABLE_SYMLINK"


def test_trusted_tool_untrusted_mode_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "git"
    executable.write_text("not executed\n", encoding="utf-8")
    executable.chmod(0o777)
    monkeypatch.setattr(policy, "_DISALLOWED_TEMP_ROOTS", ())
    monkeypatch.setattr(policy, "_path_components", lambda path: [path])

    with pytest.raises(AcceptanceCommandPolicyError) as error:
        policy._trusted_path_identity(
            str(executable),
            project_root="/home/jenn/src/colameta-dev",
            kind="executable",
            executable=True,
        )

    assert error.value.code == "ACCEPTANCE_COMMAND_EXECUTABLE_MODE_NOT_TRUSTED"


def test_executable_identity_swap_is_detected_before_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = acceptance_command_to_execution_plan(
        "git --version",
        project_root=str(tmp_path),
    )
    real_lstat = policy.os.lstat

    def swapped_lstat(path: str):
        current = real_lstat(path)
        if os.path.abspath(path) != plan.executable.path:
            return current
        values = list(current)
        values[1] = current.st_ino + 1
        return os.stat_result(values)

    monkeypatch.setattr(policy.os, "lstat", swapped_lstat)

    with pytest.raises(AcceptanceCommandPolicyError) as error:
        verify_acceptance_execution_plan(plan)

    assert error.value.code == "ACCEPTANCE_COMMAND_EXECUTABLE_IDENTITY_CHANGED"


def _version(command: str) -> BuildVersion:
    return BuildVersion(
        version="v-next",
        name="Acceptance command policy",
        description="test",
        prompt_file="prompt.md",
        enabled=True,
        acceptance_commands=[AcceptanceCommand(command=command)],
    )


def test_run_acceptance_uses_runtime_python_not_project_venv(tmp_path: Path) -> None:
    project = tmp_path / "project"
    venv_bin = project / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    fake_python = venv_bin / "python"
    fake_python.write_text("#!/bin/sh\nexit 97\n", encoding="utf-8")
    fake_python.chmod(0o755)

    result = AcceptanceRunner().run_acceptance(
        "run-acceptance-policy",
        _version("python3 --version"),
        str(project),
    )

    assert result.status == "PASSED"
    assert result.commands[0].exit_code == 0
    trusted_runtime = policy._runtime_interpreter_identity(str(project)).path
    assert shlex.split(result.commands[0].executed_command or "")[0] == trusted_runtime
    assert result.commands[0].resolved_python == trusted_runtime
    assert result.commands[0].venv_bin_path is None


def test_run_acceptance_blocks_runtime_from_target_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    runtime = project / ".venv" / "bin" / "python"
    runtime.parent.mkdir(parents=True)
    runtime.write_text("not executed\n", encoding="utf-8")
    runtime.chmod(0o700)
    monkeypatch.setattr(policy.sys, "executable", str(runtime))
    monkeypatch.setattr(policy.sys, "_base_executable", str(runtime))

    result = AcceptanceRunner().run_acceptance(
        "run-project-runtime-block",
        _version("python3 --version"),
        str(project),
    )

    assert result.status == "FAILED"
    assert result.commands[0].exit_code == -2
    assert "ACCEPTANCE_RUNTIME_INTERPRETER_IN_PROJECT" in result.commands[0].stderr


def test_run_acceptance_rejects_untrusted_path_without_echoing_it(
    tmp_path: Path,
) -> None:
    private_command = "/tmp/private-project-python --version"

    result = AcceptanceRunner().run_acceptance(
        "run-acceptance-rejected",
        _version(private_command),
        str(tmp_path),
    )

    assert result.status == "FAILED"
    assert result.commands[0].exit_code == -2
    assert private_command not in result.commands[0].stderr
    assert "Executable paths are not trusted" in result.commands[0].stderr
