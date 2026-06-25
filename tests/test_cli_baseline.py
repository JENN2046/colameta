from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "runner_cli.py"


def isolated_env(tmp_path: Path) -> dict[str, str]:
    home = tmp_path / "home"
    xdg_config = tmp_path / "xdg-config"
    home.mkdir(exist_ok=True)
    xdg_config.mkdir(exist_ok=True)
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(xdg_config),
            "PYTHONNOUSERSITE": "1",
        }
    )
    return env


def run_cli(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=ROOT,
        env=isolated_env(tmp_path),
        input="",
        text=True,
        capture_output=True,
        check=False,
    )


class CliBaselineTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="colameta-cli-test-")
        self.tmp_path = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_help_prints_usage(self) -> None:
        result = run_cli(self.tmp_path, "help")

        assert result.returncode == 0
        assert "colameta help" in result.stdout
        assert "colameta add <project_path>" in result.stdout
        assert result.stderr == ""

    def test_list_uses_isolated_user_config(self) -> None:
        result = run_cli(self.tmp_path, "list")

        assert result.returncode == 0
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        assert payload["projects"] == []
        assert payload["project_count"] == 0
        assert payload["registry_path"].startswith(str(self.tmp_path / "xdg-config" / "colameta"))

    def test_invalid_add_arguments_return_diagnostic_error(self) -> None:
        result = run_cli(self.tmp_path, "add")

        assert result.returncode != 0
        assert "add 参数不足" in result.stderr
        assert "colameta add <project_path>" in result.stderr
        assert result.stdout == ""

    def test_add_source_only_registers_without_project_mutation(self) -> None:
        project = self.tmp_path / "source-project"
        project.mkdir()

        add_result = run_cli(self.tmp_path, "add", "demo", str(project), "source-only")
        assert add_result.returncode == 0
        assert "Project registered" in add_result.stderr
        assert "Mode: source-only" in add_result.stderr
        assert not (project / ".colameta").exists()

        list_result = run_cli(self.tmp_path, "list")
        payload = json.loads(list_result.stdout)
        assert payload["project_count"] == 1
        record = payload["projects"][0]
        assert record["project_name"] == "demo"
        assert record["project_root"] == str(project.resolve())
        assert record["project_mode"] == "source-only"

    def test_add_managed_bootstraps_minimal_runner_project(self) -> None:
        project = self.tmp_path / "managed-project"
        project.mkdir()

        add_result = run_cli(self.tmp_path, "add", str(project), "managed")
        assert add_result.returncode == 0
        assert "Project registered" in add_result.stderr
        assert "Mode: managed" in add_result.stderr

        runner_dir = project / ".colameta"
        expected_files = {
            runner_dir / "plan.json",
            runner_dir / "state.json",
            runner_dir / "todolist.json",
            runner_dir / "decisions.json",
            runner_dir / "memory.md",
        }
        for path in expected_files:
            assert path.is_file()

        gitignore_text = (project / ".gitignore").read_text(encoding="utf-8")
        assert "# >>> ColaMeta local state >>>" in gitignore_text
        assert ".colameta/state.json" in gitignore_text

        plan = json.loads((runner_dir / "plan.json").read_text(encoding="utf-8"))
        assert plan["project_name"] == "managed-project"

        list_result = run_cli(self.tmp_path, "list")
        payload = json.loads(list_result.stdout)
        assert payload["project_count"] == 1
        assert payload["projects"][0]["project_mode"] == "managed"
