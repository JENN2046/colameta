from __future__ import annotations

import shlex
import sys

from adapters.shell_adapter import ShellAdapter


def test_shell_adapter_runs_allowed_argv_command() -> None:
    command = f"{shlex.quote(sys.executable)} -c \"print('ok')\""

    result = ShellAdapter().run(command)

    assert result.exit_code == 0
    assert result.stdout.strip() == "ok"
    assert result.stderr == ""


def test_shell_adapter_rejects_shell_operator_without_side_effect(tmp_path) -> None:
    marker = tmp_path / "marker"
    command = f"{shlex.quote(sys.executable)} -c \"print('ok')\" ; touch {shlex.quote(str(marker))}"

    result = ShellAdapter().run(command)

    assert result.exit_code == -2
    assert "Shell operators are not allowed" in result.stderr
    assert not marker.exists()


def test_shell_adapter_rejects_non_allowlisted_executable() -> None:
    result = ShellAdapter().run("bash -lc 'echo no'")

    assert result.exit_code == -2
    assert "Executable is not allowed" in result.stderr
