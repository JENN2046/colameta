from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import pytest

import runner.toolchain_environment as toolchain_environment
from runner.mcp_validation_run import (
    MCPValidationRunManager,
)
from runner.toolchain_environment import (
    build_validation_subprocess_environment,
    create_validation_venv,
    materialize_trusted_source_venv,
    rewrite_command_for_validation_environment,
    venv_bin_dir,
    venv_python,
)


def _git(project: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(project), *args],
        capture_output=True,
        text=True,
        check=True,
        shell=False,
    )
    return result.stdout.strip()


def _git_project(tmp_path: Path) -> Path:
    project = tmp_path / "validation-project"
    project.mkdir()
    (project / "README.md").write_text("validation fixture\n", encoding="utf-8")
    _git(project, "init", "-q")
    _git(project, "config", "user.name", "Validation Fixture")
    _git(project, "config", "user.email", "validation@example.invalid")
    _git(project, "add", "README.md")
    _git(project, "commit", "-qm", "initial")
    return project


def _terminal_status(manager: MCPValidationRunManager, run_id: str) -> dict:
    for _ in range(10000):
        status = manager.status({"run_id": run_id})
        if status.get("status") in {"passed", "failed"}:
            return status
        time.sleep(0.01)
    pytest.fail("validation run did not reach a terminal status")


def _candidate_with_current_pyproject(tmp_path: Path) -> Path:
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    shutil.copy2(Path("pyproject.toml"), candidate / "pyproject.toml")
    return candidate


def test_validation_environment_removes_parent_python_contamination(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    serving = tmp_path / "serving"
    serving.mkdir()
    validation_venv = tmp_path / "validation-venv"
    (validation_venv / "bin").mkdir(parents=True)
    parent = {
        "PATH": os.pathsep.join(
            [str(serving / ".venv" / "bin"), os.defpath]
        ),
        "PYTHONPATH": str(serving),
        "PYTHONHOME": str(serving),
        "VIRTUAL_ENV": str(serving / ".venv"),
        "CONDA_PREFIX": str(serving / "conda"),
        "PIP_PREFIX": str(serving),
        "PIP_TARGET": str(serving / "target"),
        "PIP_USER": "1",
        "PYTHONUSERBASE": str(serving / "user"),
        "PYTHONSTARTUP": str(serving / "startup.py"),
        "PIP_CONFIG_FILE": str(serving / "pip.conf"),
        "PIP_INDEX_URL": "https://malicious.invalid/simple",
        "PIP_EXTRA_INDEX_URL": "https://malicious.invalid/extra",
        "PIP_TRUSTED_HOST": "malicious.invalid",
        "PIP_CONSTRAINT": str(serving / "constraints.txt"),
        "PIP_REQUIREMENT": str(serving / "requirements.txt"),
        "PIP_NO_INDEX": "0",
        "LANG": "C.UTF-8",
    }

    environment = build_validation_subprocess_environment(
        candidate_root=candidate,
        validation_venv=validation_venv,
        parent_environment=parent,
        temp_root=tmp_path / "runtime",
        forbidden_roots=(serving,),
    )

    assert environment["PATH"].split(os.pathsep)[0] == str(
        validation_venv / "bin"
    )
    assert str(serving / ".venv" / "bin") not in environment["PATH"]
    assert environment["VIRTUAL_ENV"] == str(validation_venv.resolve())
    assert environment["HOME"].startswith(str((tmp_path / "runtime").resolve()))
    assert environment["PWD"] == str(candidate.resolve())
    for key in (
        "PYTHONPATH",
        "PYTHONHOME",
        "CONDA_PREFIX",
        "PIP_PREFIX",
        "PIP_TARGET",
        "PIP_USER",
        "PYTHONUSERBASE",
        "PYTHONSTARTUP",
        "PIP_CONFIG_FILE",
        "PIP_INDEX_URL",
        "PIP_EXTRA_INDEX_URL",
        "PIP_TRUSTED_HOST",
        "PIP_CONSTRAINT",
        "PIP_REQUIREMENT",
        "PIP_NO_INDEX",
    ):
        assert key not in environment


def test_validation_environment_does_not_retain_sensitive_parent_values(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    synthetic_secret = "synthetic-validation-secret-value"
    environment = build_validation_subprocess_environment(
        candidate_root=candidate,
        parent_environment={
            "PATH": os.defpath,
            "COLAMETA_SYNTHETIC_TOKEN": synthetic_secret,
            "PIP_CONFIG_FILE": synthetic_secret,
            "PYTHONPATH": synthetic_secret,
        },
        temp_root=tmp_path / "runtime",
    )

    assert "COLAMETA_SYNTHETIC_TOKEN" not in environment
    assert synthetic_secret not in environment.values()


def test_validation_environment_uses_platform_specific_venv_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    venv_dir = tmp_path / "validation-venv"
    monkeypatch.setattr(toolchain_environment.os, "name", "nt")
    assert venv_bin_dir(venv_dir) == venv_dir / "Scripts"
    assert venv_python(venv_dir) == venv_dir / "Scripts" / "python.exe"


def test_validation_venv_creation_uses_one_cross_platform_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    class FakeBuilder:
        def __init__(self, **kwargs: object) -> None:
            calls.append(kwargs)

        def create(self, path: Path) -> None:
            path.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(toolchain_environment.venv, "EnvBuilder", FakeBuilder)
    monkeypatch.setattr(toolchain_environment.os, "name", "nt")
    create_validation_venv(tmp_path / "windows-first")
    create_validation_venv(tmp_path / "windows-rebuild")
    assert [call["symlinks"] for call in calls] == [False, False]
    assert venv_bin_dir(tmp_path / "windows-first").name == "Scripts"
    assert venv_python(tmp_path / "windows-first").name == "python.exe"

    monkeypatch.setattr(toolchain_environment.os, "name", "posix")
    create_validation_venv(tmp_path / "posix")
    assert calls[-1]["symlinks"] is True


def test_candidate_pip_asset_is_hash_and_metadata_bound(
    tmp_path: Path,
) -> None:
    assert toolchain_environment.resolve_candidate_pip_asset({"PATH": os.defpath}) is None
    assert toolchain_environment._CANDIDATE_PIP_WHEEL_FILENAME == "pip-26.2-py3-none-any.whl"
    assert toolchain_environment._CANDIDATE_PIP_WHEEL_SHA256 == (
        "931c303696af6fa3417112103b1cad26890e5a07eccb5b99783700e33f2b8aad"
    )
    wrong = tmp_path / toolchain_environment._CANDIDATE_PIP_WHEEL_FILENAME
    wrong.write_bytes(b"not a wheel")
    with pytest.raises(
        toolchain_environment.ValidationEnvironmentError,
        match="CANDIDATE_PIP_26_2_ASSET_UNAVAILABLE|digest mismatch",
    ):
        toolchain_environment.resolve_candidate_pip_asset(
            {toolchain_environment._CANDIDATE_PIP_WHEEL_ENV: str(wrong)}
        )


def test_frozen_wheel_directory_rejects_an_extra_matching_distribution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from packaging.tags import sys_tags

    asset_dir = tmp_path / "wheel-assets"
    asset_dir.mkdir()
    bound = asset_dir / "cryptography-50.0.0-cp311-abi3-manylinux_2_34_x86_64.whl"
    extra = asset_dir / "cryptography-50.0.0-1-cp311-abi3-manylinux_2_34_x86_64.whl"
    bound.write_bytes(b"bound")
    extra.write_bytes(b"extra")
    monkeypatch.setattr(
        toolchain_environment,
        "verify_bound_wheel_asset",
        lambda *_args, **_kwargs: {
            "filename": bound.name,
            "sha256": "a" * 64,
            "source_verified": True,
        },
    )
    monkeypatch.setattr(
        toolchain_environment,
        "_wheel_primary_metadata",
        lambda _path: (
            "cryptography",
            "50.0.0",
            set(sys_tags()),
            {"Name": "cryptography", "Version": "50.0.0"},
        ),
    )

    with pytest.raises(
        toolchain_environment.ValidationEnvironmentError,
        match="candidate set is ambiguous",
    ):
        toolchain_environment._verify_bound_wheel_directory(
            bound,
            expected_filename=bound.name,
            expected_sha256="a" * 64,
            expected_distribution="cryptography",
            expected_version="50.0.0",
        )


def test_frozen_bound_wheel_digest_is_checked_before_installation(
    tmp_path: Path,
) -> None:
    asset_dir = tmp_path / "wheel-assets"
    asset_dir.mkdir()
    bound = asset_dir / "cryptography-50.0.0-cp311-abi3-manylinux_2_34_x86_64.whl"
    bound.write_bytes(b"bound")

    with pytest.raises(
        toolchain_environment.ValidationEnvironmentError,
        match="digest mismatch",
    ):
        toolchain_environment._verify_bound_wheel_directory(
            bound,
            expected_filename=bound.name,
            expected_sha256="b" * 64,
            expected_distribution="cryptography",
            expected_version="50.0.0",
        )


def test_frozen_materialization_uses_find_links_requirement_not_absolute_wheel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_venv = tmp_path / "source-venv"
    source_venv.mkdir()
    (source_venv / "pyvenv.cfg").write_text("home = local\n", encoding="utf-8")
    asset_dir = tmp_path / "wheel-assets"
    asset_dir.mkdir()
    bound = asset_dir / "cryptography-50.0.0-cp311-abi3-manylinux_2_34_x86_64.whl"
    bound.write_bytes(b"bound")
    commands: list[list[str]] = []

    monkeypatch.setattr(
        toolchain_environment,
        "_verify_bound_wheel_directory",
        lambda *_args, **_kwargs: (
            asset_dir,
            {
                "filename": bound.name,
                "sha256": "a" * 64,
                "source_verified": True,
                "distribution": "cryptography",
                "version": "50.0.0",
            },
        ),
    )
    monkeypatch.setattr(
        toolchain_environment,
        "venv_python",
        lambda venv: venv / "bin" / "python",
    )
    monkeypatch.setattr(
        toolchain_environment,
        "_run_toolchain_command",
        lambda command, **_kwargs: commands.append(list(command)),
    )
    monkeypatch.setattr(
        toolchain_environment.subprocess,
        "check_output",
        lambda *_args, **_kwargs: "50.0.0\n",
    )

    toolchain_environment.materialize_frozen_toolchain_environment(
        source_venv=source_venv,
        work_root=tmp_path / "work",
        frozen_asset=bound,
        frozen_asset_filename=bound.name,
        frozen_asset_sha256="a" * 64,
        frozen_asset_distribution="cryptography",
        frozen_asset_version="50.0.0",
    )

    assert len(commands) == 1
    command = commands[0]
    assert command[0].endswith("/bin/python")
    assert command[1:4] == ["-m", "pip", "install"]
    assert command[command.index("--find-links") + 1] == str(asset_dir)
    assert "--only-binary" in command
    assert command[command.index("--only-binary") + 1] == ":all:"
    assert command[-1] == "cryptography==50.0.0"
    assert str(bound) not in command


def test_candidate_validation_uses_online_tools_without_validation_closure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    shutil.copy2(Path("pyproject.toml"), candidate / "pyproject.toml")
    commands: list[list[str]] = []
    environments: list[dict[str, str]] = []
    download_environments: list[dict[str, str]] = []

    class FakeBuilder:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def create(self, path: Path) -> None:
            path.mkdir(parents=True, exist_ok=True)
            python = toolchain_environment.venv_python(path)
            python.parent.mkdir(parents=True, exist_ok=True)
            python.write_text("validation-python\n", encoding="utf-8")

    monkeypatch.setattr(toolchain_environment.venv, "EnvBuilder", FakeBuilder)
    monkeypatch.setattr(
        toolchain_environment,
        "_run_toolchain_command",
        lambda command, **kwargs: (
            commands.append(list(command)),
            environments.append(dict(kwargs["environment"])),
        ),
    )
    pip_wheel = tmp_path / "pip-26.2-py3-none-any.whl"
    pip_wheel.write_bytes(b"bound pip wheel fixture")

    def fake_download_candidate_pip_asset(**kwargs: object) -> dict[str, object]:
        python = Path(str(kwargs["python_executable"]))
        environment = dict(kwargs["environment"])  # type: ignore[arg-type]
        download_environments.append(environment)
        return {
            "path": pip_wheel,
            "filename": "pip-26.2-py3-none-any.whl",
            "sha256": toolchain_environment._CANDIDATE_PIP_WHEEL_SHA256,
            "asset_verified": True,
            "installed_offline": False,
            "network_used": True,
            "runtime_dependency": False,
            "_pip_command": [
                str(python),
                "-m",
                "pip",
                "download",
                "--index-url",
                toolchain_environment._OFFICIAL_PYPI_INDEX_URL,
                "pip==26.2",
            ],
        }

    monkeypatch.setattr(
        toolchain_environment,
        "download_candidate_pip_asset",
        fake_download_candidate_pip_asset,
    )
    versions = iter(("24.0", "26.2"))
    monkeypatch.setattr(
        toolchain_environment,
        "_read_distribution_version",
        lambda *_args, **_kwargs: next(versions),
    )
    monkeypatch.setattr(
        toolchain_environment,
        "_verify_candidate_install",
        lambda **_kwargs: {
            "candidate_module_provenance_verified": True,
            "validation_environment_verified": True,
        },
    )
    monkeypatch.setattr(
        toolchain_environment,
        "_project_metadata",
        lambda _candidate: (None, []),
    )

    environment = toolchain_environment.prepare_validation_environment(
        candidate_root=candidate,
        work_root=tmp_path / "work",
        parent_environment={
            "PATH": os.defpath,
            toolchain_environment._VALIDATION_ASSET_DIR_ENV: str(
                tmp_path / "removed-external-closure"
            ),
            "PIP_INDEX_URL": "https://malicious.invalid/simple",
            "PIP_EXTRA_INDEX_URL": "https://malicious.invalid/extra",
            "PIP_TRUSTED_HOST": "malicious.invalid",
            "PIP_CONSTRAINT": str(tmp_path / "constraints.txt"),
            "PIP_REQUIREMENT": str(tmp_path / "requirements.txt"),
        },
        needs_python=True,
    )

    bootstrap = environment.summary["candidate_bootstrap"]
    assert bootstrap == {
        "initial_pip_version": "24.0",
        "selected_pip_version": "26.2",
        "wheel_filename": "pip-26.2-py3-none-any.whl",
        "wheel_sha256": (
            "931c303696af6fa3417112103b1cad26890e5a07eccb5b99783700e33f2b8aad"
        ),
        "asset_verified": True,
        "installed_offline": False,
        "asset_source": "official_pypi",
        "network_used": True,
        "runtime_dependency": False,
    }
    assert "validation_asset_closure" not in environment.summary
    assert len(commands) == 2
    assert all(command[0] == str(environment.python_executable) for command in commands)
    assert all(
        command[command.index("--index-url") + 1]
        == toolchain_environment._OFFICIAL_PYPI_INDEX_URL
        for command in commands
    )
    assert "--no-index" in commands[0]
    assert all("--find-links" not in command for command in commands)
    assert all("--require-hashes" not in command for command in commands)
    assert all(
        value.get("PIP_CONFIG_FILE") == os.devnull
        and value.get("PIP_INDEX_URL") == toolchain_environment._OFFICIAL_PYPI_INDEX_URL
        and "PIP_EXTRA_INDEX_URL" not in value
        and "PIP_TRUSTED_HOST" not in value
        and "PIP_CONSTRAINT" not in value
        and "PIP_REQUIREMENT" not in value
        and "PIP_FIND_LINKS" not in value
        and "PIP_NO_INDEX" not in value
        for value in [*environments, *download_environments]
    )
    authority = environment.summary["candidate_pip_authority"]
    assert authority["sole_pip_executable"] == str(environment.python_executable)
    assert authority["post_upgrade_parent_pip_invocation_count"] == 0
    assert authority["all_commands_candidate_python"] is True
    assert authority["all_online_index_urls_official"] is True
    assert authority["extra_index_present"] is False
    assert authority["trusted_host_present"] is False
    assert authority["build_isolation_disabled"] is False
    assert authority["network_used"] is True


def test_candidate_wheel_build_uses_candidate_pip_without_build_isolation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = _candidate_with_current_pyproject(tmp_path)
    commands: list[list[str]] = []

    class FakeBuilder:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def create(self, path: Path) -> None:
            path.mkdir(parents=True, exist_ok=True)
            python = toolchain_environment.venv_python(path)
            python.parent.mkdir(parents=True, exist_ok=True)
            python.write_text("validation-python\n", encoding="utf-8")

    monkeypatch.setattr(toolchain_environment.venv, "EnvBuilder", FakeBuilder)
    monkeypatch.setattr(
        toolchain_environment,
        "_run_toolchain_command",
        lambda command, **kwargs: (
            commands.append(list(command)),
            (
                Path(command[command.index("--wheel-dir") + 1])
                / "colameta-0.1.2-py3-none-any.whl"
            ).write_bytes(b"candidate-wheel")
            if kwargs["label"] == "candidate wheel build"
            else None,
        ),
    )
    pip_wheel = tmp_path / "pip-26.2-py3-none-any.whl"
    pip_wheel.write_bytes(b"bound pip wheel fixture")
    monkeypatch.setattr(
        toolchain_environment,
        "download_candidate_pip_asset",
        lambda **kwargs: {
            "path": pip_wheel,
            "filename": "pip-26.2-py3-none-any.whl",
            "sha256": toolchain_environment._CANDIDATE_PIP_WHEEL_SHA256,
            "asset_verified": True,
            "installed_offline": False,
            "network_used": True,
            "runtime_dependency": False,
            "_pip_command": [
                str(kwargs["python_executable"]),
                "-m",
                "pip",
                "download",
                "--index-url",
                toolchain_environment._OFFICIAL_PYPI_INDEX_URL,
            ],
        },
    )
    versions = iter(("24.0", "26.2"))
    monkeypatch.setattr(
        toolchain_environment,
        "_read_distribution_version",
        lambda *_args, **_kwargs: next(versions),
    )
    monkeypatch.setattr(
        toolchain_environment,
        "_verify_candidate_install",
        lambda **_kwargs: {
            "candidate_module_provenance_verified": True,
            "validation_environment_verified": True,
        },
    )
    monkeypatch.setattr(toolchain_environment, "_clean_candidate_build_overlays", lambda **_kwargs: None)
    def fake_wheel_primary_metadata(path: Path):
        del path
        return ("colameta", "0.1.2", set(), object())

    monkeypatch.setattr(
        toolchain_environment,
        "_wheel_primary_metadata",
        fake_wheel_primary_metadata,
    )

    environment = toolchain_environment.prepare_validation_environment(
        candidate_root=candidate,
        work_root=tmp_path / "work",
        parent_environment={
            "PATH": os.defpath,
        },
        needs_python=True,
    )

    assert len(commands) == 4
    assert all(command[0] == str(environment.python_executable) for command in commands)
    assert all(
        command[command.index("--index-url") + 1]
        == toolchain_environment._OFFICIAL_PYPI_INDEX_URL
        for command in commands
    )
    build = next(command for command in commands if "wheel" in command)
    assert "--no-build-isolation" in build
    assert "--no-index" in commands[0]
    assert all("--find-links" not in command for command in commands)
    assert environment.summary["candidate_pip_authority"]["post_upgrade_parent_pip_invocation_count"] == 0
    assert environment.summary["candidate_pip_authority"]["build_isolation_disabled"] is True
    assert environment.summary["candidate_pip_authority"]["network_used"] is True
    assert "validation_asset_closure" not in environment.summary


def test_candidate_build_cleanup_preserves_validation_venv(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    venv_marker = candidate / ".venv" / "bin" / "python"
    venv_marker.parent.mkdir(parents=True)
    venv_marker.write_text("validation python\n", encoding="utf-8")
    (candidate / "build").mkdir()
    (candidate / "build" / "artifact.txt").write_text("build\n", encoding="utf-8")
    (candidate / "dist").mkdir()
    (candidate / "dist" / "artifact.whl").write_text("wheel\n", encoding="utf-8")
    (candidate / "colameta.egg-info").mkdir()
    (candidate / "colameta.egg-info" / "PKG-INFO").write_text(
        "metadata\n",
        encoding="utf-8",
    )

    toolchain_environment._clean_candidate_build_overlays(
        candidate_root=candidate,
        environment={},
    )

    assert venv_marker.is_file()
    assert not (candidate / "build").exists()
    assert not (candidate / "dist").exists()
    assert not (candidate / "colameta.egg-info").exists()


def test_candidate_and_host_checkouts_are_distinct_and_mutually_invisible(
    tmp_path: Path,
) -> None:
    project = _git_project(tmp_path)
    manager = MCPValidationRunManager(str(project))
    head = _git(project, "rev-parse", "HEAD")
    for order in (("candidate", "host"), ("host", "candidate")):
        candidate = manager._prepare_isolated_checkout(head, f"s4-{order[0]}-candidate")
        host = manager._prepare_isolated_checkout(head, f"s4-{order[1]}-host")
        try:
            assert candidate["root"] != host["root"]
            checkouts = {"candidate": Path(candidate["root"]), "host": Path(host["root"])}
            for lane in order:
                other = "host" if lane == "candidate" else "candidate"
                side_effect = checkouts[lane] / f"{lane}-only.txt"
                side_effect.write_text(f"{lane} lane\n", encoding="utf-8")
                assert not (checkouts[other] / side_effect.name).exists()
        finally:
            assert manager._cleanup_isolated_checkout(candidate) is True
            assert manager._cleanup_isolated_checkout(host) is True


def test_python_command_rewrite_keeps_declared_argv_shape(tmp_path: Path) -> None:
    command = [".venv/bin/python", "-m", "pytest", "tests/test_one.py", "-q"]
    rewritten = rewrite_command_for_validation_environment(
        command,
        tmp_path / "validation-venv",
    )
    assert command[1:] == rewritten[1:]
    assert rewritten[0].endswith(os.path.join("validation-venv", "bin", "python"))


def test_manifest_validation_does_not_allow_deselect_extensions(
    tmp_path: Path,
) -> None:
    manager = MCPValidationRunManager(str(tmp_path))
    allowed = [
        ".venv/bin/python",
        "-m",
        "pytest",
        "-q",
    ]
    assert manager._is_supported_manifest_command(allowed) is True
    assert manager._is_supported_manifest_command(
        [*allowed, "--deselect=tests/test_other.py::test_skip"]
    ) is False


def test_host_frozen_test_classification_uses_complementary_marker_expressions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = MCPValidationRunManager(str(_git_project(tmp_path)))
    monkeypatch.setattr(manager, "_detect_project_types", lambda: ["python"])
    preview = manager.preview({"scope": "full"})
    assert preview["ok"] is True
    selection = preview["validation_selection"]
    assert selection["classification_mechanism"] == "pytest_marker_partition"
    assert selection["marker"] == "host_frozen_toolchain"
    assert selection["candidate_expression"] == "not host_frozen_toolchain"
    assert selection["host_expression"] == "host_frozen_toolchain"
    assert selection["fixed_node_list_used"] is False
    assert selection["classification_exhaustive"] == {
        "value": True,
        "basis": "complementary_marker_expressions",
    }
    assert all(
        "--ignore=tests/test_work_item_r3_closeout_runner.py" not in command
        for command in preview["command_summary"]
    )


def test_preview_separates_target_selection_from_full_candidate_delta(
    tmp_path: Path,
) -> None:
    project = _git_project(tmp_path)
    source = project / "runner" / "source_dependency.py"
    selected = project / "tests" / "test_selected.py"
    source.parent.mkdir()
    selected.parent.mkdir()
    source.write_text('VALUE = "head"\n', encoding="utf-8")
    selected.write_text(
        "from runner.source_dependency import VALUE\n\n"
        "def test_selected():\n    assert VALUE == 'head'\n",
        encoding="utf-8",
    )
    _git(project, "add", "runner/source_dependency.py", "tests/test_selected.py")
    _git(project, "commit", "-qm", "add candidate fixture")
    source.write_text('VALUE = "repaired"\n', encoding="utf-8")
    selected.write_text(
        "from runner.source_dependency import VALUE\n\n"
        "def test_selected():\n    assert VALUE == 'repaired'\n",
        encoding="utf-8",
    )

    manager = MCPValidationRunManager(str(project))
    preview = manager.preview(
        {"scope": "target_files", "target_files": ["tests/test_selected.py"]}
    )
    assert preview["ok"] is True
    assert preview["validation_selection"]["target_files"] == [
        "tests/test_selected.py"
    ]
    assert preview["candidate_identity"]["source_binding_count"] == 2
    assert {
        item["path"]
        for item in manager._read_preview(preview["preview_id"])["candidate_source_bindings"]
    } == {"runner/source_dependency.py", "tests/test_selected.py"}
    assert all(
        "runner/source_dependency.py" not in command
        for command in preview["command_summary"]
    )


def test_full_candidate_delta_includes_untracked_source_and_deletions(
    tmp_path: Path,
) -> None:
    project = _git_project(tmp_path)
    untracked = project / "runner" / "untracked_candidate.py"
    untracked.parent.mkdir()
    untracked.write_text("VALUE = 1\n", encoding="utf-8")
    deleted = project / "runner" / "deleted_candidate.py"
    deleted.write_text("VALUE = 2\n", encoding="utf-8")
    _git(project, "add", "runner/deleted_candidate.py")
    _git(project, "commit", "-qm", "add deletion fixture")
    deleted.unlink()

    manager = MCPValidationRunManager(str(project))
    preview = manager.preview({"scope": "full"})
    assert preview["ok"] is True
    bindings = manager._read_preview(preview["preview_id"])["candidate_source_bindings"]
    by_path = {item["path"]: item for item in bindings}
    assert by_path["runner/untracked_candidate.py"]["present"] is True
    assert by_path["runner/deleted_candidate.py"]["present"] is False
    assert preview["candidate_identity"]["source_binding_count"] == 2
    assert all("--deselect=" not in command for command in preview["command_summary"])


def test_current_version_binds_full_delta_while_selection_stays_policy_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _git_project(tmp_path)
    changed = project / "runner" / "current_version_change.py"
    changed.parent.mkdir()
    changed.write_text("VALUE = 1\n", encoding="utf-8")
    manager = MCPValidationRunManager(str(project))
    monkeypatch.setattr(
        manager,
        "_current_acceptance_commands",
        lambda: ([{
            "argv": ["python3", "-m", "pytest", "tests", "-q"],
            "timeout_seconds": 60,
            "continue_on_failure": False,
        }], []),
    )
    preview = manager.preview({"scope": "current_version"})
    assert preview["ok"] is True
    assert preview["validation_selection"]["scope"] == "current_version"
    assert preview["validation_selection"]["target_files"] == []
    assert preview["candidate_identity"]["source_binding_count"] == 1
    assert manager._read_preview(preview["preview_id"])["candidate_source_bindings"][0][
        "path"
    ] == "runner/current_version_change.py"


def test_full_candidate_overlay_executes_modified_dependency_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _git_project(tmp_path)
    module = project / "runner" / "candidate_marker.py"
    package_init = project / "runner" / "__init__.py"
    test_file = project / "tests" / "test_candidate_marker.py"
    module.parent.mkdir()
    test_file.parent.mkdir()
    package_init.write_text("\n", encoding="utf-8")
    module.write_text('VALUE = "head"\n', encoding="utf-8")
    test_file.write_text(
        "from runner.candidate_marker import VALUE\n\n"
        "def test_marker():\n    assert VALUE == 'head'\n",
        encoding="utf-8",
    )
    _git(
        project,
        "add",
        "runner/__init__.py",
        "runner/candidate_marker.py",
        "tests/test_candidate_marker.py",
    )
    _git(project, "commit", "-qm", "add marker")
    module.write_text('VALUE = "repaired"\n', encoding="utf-8")
    test_file.write_text(
        "from runner.candidate_marker import VALUE\n\n"
        "def test_marker():\n    assert VALUE == 'repaired'\n",
        encoding="utf-8",
    )
    wrong_checkout = tmp_path / "wrong-checkout"
    wrong_checkout.mkdir()
    (wrong_checkout / "runner").mkdir()
    (wrong_checkout / "runner" / "candidate_marker.py").write_text(
        'VALUE = "wrong-parent-import"\n', encoding="utf-8"
    )
    monkeypatch.setenv("PYTHONPATH", str(wrong_checkout))

    manager = MCPValidationRunManager(str(project))
    bindings, paths, error = manager._build_full_worktree_candidate_bindings()
    assert error is None
    assert paths == ["runner/candidate_marker.py", "tests/test_candidate_marker.py"]
    isolated = manager._prepare_isolated_checkout(
        _git(project, "rev-parse", "HEAD"), "validation_run_full_overlay"
    )
    try:
        manager._apply_candidate_source_overlays(
            isolated, bindings, binding_kind="full_allowed_worktree_delta"
        )
        checkout = Path(isolated["root"])
        environment = build_validation_subprocess_environment(
            candidate_root=checkout,
            parent_environment=dict(os.environ),
            temp_root=tmp_path / "runtime",
            forbidden_roots=(project,),
        )
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                "from runner.candidate_marker import VALUE; assert VALUE == 'repaired'",
            ],
            cwd=checkout,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
            shell=False,
        )
        assert completed.returncode == 0, completed.stderr
    finally:
        manager._remove_isolated_execution_overlays(isolated)
        assert manager._cleanup_isolated_checkout(isolated) is True


def test_candidate_delta_preview_rejects_new_unbound_worktree_change(
    tmp_path: Path,
) -> None:
    project = _git_project(tmp_path)
    manager = MCPValidationRunManager(str(project))
    preview = manager.preview(
        {"scope": "target_files", "target_files": ["README.md"]}
    )
    new_source = project / "runner" / "unbound.py"
    new_source.parent.mkdir()
    new_source.write_text("VALUE = 1\n", encoding="utf-8")
    blocked = manager.run({"preview_id": preview["preview_id"]})
    assert blocked["ok"] is False
    assert blocked["error_code"] == "VALIDATION_CANDIDATE_DELTA_INCOMPLETE"


def test_bound_materialization_fails_closed_or_keeps_original_bytes_on_race(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _git_project(tmp_path)
    manager = MCPValidationRunManager(str(project))
    source = tmp_path / "source.py"
    destination = tmp_path / "destination.py"
    original = b"VALUE = 'expected'\n"
    source.write_bytes(original)
    expected = hashlib.sha256(original).hexdigest()

    def raced(_path: Path) -> bytes:
        source.write_bytes(b"VALUE = 'unbound'\n")
        return original

    monkeypatch.setattr(manager, "_read_bound_source_bytes", raced)
    manager._materialize_bound_file(
        source=source,
        destination=destination,
        expected_sha256=expected,
    )
    assert destination.read_bytes() == original
    assert source.read_bytes() != original


def test_bound_materialization_rejects_destination_digest_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _git_project(tmp_path)
    manager = MCPValidationRunManager(str(project))
    source = tmp_path / "source.py"
    destination = tmp_path / "destination.py"
    source.write_bytes(b"VALUE = 1\n")
    expected = hashlib.sha256(source.read_bytes()).hexdigest()
    original_hash = manager._sha256_file

    def corrupted_hash(path: Path) -> str:
        if path == destination:
            return "0" * 64
        return original_hash(path)

    monkeypatch.setattr(manager, "_sha256_file", corrupted_hash)
    with pytest.raises(RuntimeError, match="destination digest"):
        manager._materialize_bound_file(
            source=source,
            destination=destination,
            expected_sha256=expected,
        )


def test_deleted_binding_removes_head_file_from_candidate_checkout(
    tmp_path: Path,
) -> None:
    project = _git_project(tmp_path)
    (project / "README.md").unlink()
    manager = MCPValidationRunManager(str(project))
    bindings, error = manager._build_candidate_source_bindings(["README.md"])
    assert error is None
    assert bindings == [{"path": "README.md", "present": False, "sha256": None}]
    isolated = manager._prepare_isolated_checkout(
        _git(project, "rev-parse", "HEAD"), "validation_run_deleted_overlay"
    )
    try:
        manager._apply_candidate_source_overlays(isolated, bindings)
        assert not (Path(isolated["root"]) / "README.md").exists()
    finally:
        manager._remove_isolated_execution_overlays(isolated)
        assert manager._cleanup_isolated_checkout(isolated) is True


def test_full_validation_preview_contains_no_deselect_argument(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _git_project(tmp_path)
    manager = MCPValidationRunManager(str(project))
    monkeypatch.setattr(manager, "_current_acceptance_commands", lambda: ([], []))
    monkeypatch.setattr(
        manager,
        "_full_validation_strategies",
        lambda: [{
            "strategy": "python_full",
            "argv": ["python3", "-m", "pytest", "tests", "-q"],
        }],
    )
    preview = manager.preview({"scope": "full"})
    assert preview["ok"] is True
    assert all("--deselect=" not in command for command in preview["command_summary"])


def test_full_preview_binds_candidate_and_host_frozen_lanes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _git_project(tmp_path)
    manager = MCPValidationRunManager(str(project))
    monkeypatch.setattr(manager, "_current_acceptance_commands", lambda: ([], []))
    monkeypatch.setattr(
        manager,
        "_full_validation_strategies",
        lambda: [
            {
                "strategy": "python_candidate_full",
                "lane": "candidate",
                "argv": [
                    "python3",
                    "-m",
                    "pytest",
                    "tests",
                    "-q",
                    "-m",
                    "not host_frozen_toolchain",
                    "-rs",
                ],
            },
            {
                "strategy": "python_host_frozen",
                "lane": "host_frozen",
                "argv": [
                    "python3",
                    "-m",
                    "pytest",
                    "tests/test_work_item_r3_closeout_runner.py",
                    "-q",
                    "-m",
                    "host_frozen_toolchain",
                    "-rs",
                ],
            },
        ],
    )
    preview = manager.preview({"scope": "full"})
    assert preview["ok"] is True
    assert preview["validation_lanes"] == ["candidate", "host_frozen", "candidate"]
    assert preview["validation_selection"]["classification_mechanism"] == (
        "pytest_marker_partition"
    )
    assert preview["validation_selection"]["fixed_node_list_used"] is False
    assert all(
        "--ignore=tests/test_work_item_r3_closeout_runner.py" not in command
        for command in preview["command_summary"]
    )
    assert all("--deselect=" not in command for command in preview["command_summary"])


def test_targeted_frozen_file_uses_both_marker_partitions(
    tmp_path: Path,
) -> None:
    project = _git_project(tmp_path)
    manager = MCPValidationRunManager(str(project))
    preview = manager.preview(
        {
            "scope": "target_files",
            "target_files": ["tests/test_work_item_r3_closeout_runner.py"],
        }
    )
    assert preview["ok"] is True
    assert preview["validation_lanes"] == ["candidate", "host_frozen", "candidate"]
    assert "-m not host_frozen_toolchain -rs" in preview["command_summary"][0]
    assert "-m host_frozen_toolchain -rs" in preview["command_summary"][1]
    assert all(
        "--ignore=tests/test_work_item_r3_closeout_runner.py" not in command
        for command in preview["command_summary"]
    )


def test_changed_frozen_authority_triggers_both_marker_partitions(
    tmp_path: Path,
) -> None:
    manager = MCPValidationRunManager(str(_git_project(tmp_path)))
    commands, _specs, _strategy, _warnings, _groups, lanes = manager._select_commands(
        "changed_files",
        ["runner/work_item_governance/toolchain_binding.py"],
    )
    assert lanes == ["candidate", "host_frozen", "candidate"]
    assert "-m not host_frozen_toolchain -rs" in manager._display_command(commands[0])
    assert "-m host_frozen_toolchain -rs" in manager._display_command(commands[1])


def test_marker_is_registered_without_unknown_marker_warning(pytestconfig) -> None:
    assert any(
        marker.startswith("host_frozen_toolchain:")
        for marker in pytestconfig.getini("markers")
    )


def test_lane_skip_policy_fails_closed_without_fake_unexecuted_count() -> None:
    evidence, aggregate = MCPValidationRunManager._validation_lane_evidence(
        command_specs=[
            {
                "argv": ["python", "-m", "pytest", "tests", "-q"],
                "timeout_seconds": 10,
                "continue_on_failure": True,
            },
            {
                "argv": [
                    "python",
                    "-m",
                    "pytest",
                    "tests/test_work_item_r3_closeout_runner.py",
                    "-q",
                ],
                "timeout_seconds": 10,
                "continue_on_failure": True,
            },
        ],
        command_results=[
            {
                "index": 0,
                "lane": "candidate",
                "ok": True,
                "selected_test_count": 10,
                "skipped_count": 1,
                "allowed_skip_count": 0,
                "unexpected_skip_count": 1,
                "required_skipped_count": 0,
            },
            {
                "index": 1,
                "lane": "host_frozen",
                "ok": True,
                "selected_test_count": 3,
                "skipped_count": 1,
                "allowed_skip_count": 0,
                "unexpected_skip_count": 0,
                "required_skipped_count": 1,
            },
        ],
        lane_assignments=["candidate", "host_frozen"],
        candidate_delta_sha256="a" * 64,
        candidate_module_provenance=True,
        host_preflight={
            "module_provenance": True,
            "frozen_toolchain_record_sha256": "b" * 64,
            "environment_root_binding_sha256": "c" * 64,
            "record_owned_preimport_bytecode_count": 0,
            "error_code": None,
        },
    )
    assert evidence["candidate"]["status"] == "failed"
    assert evidence["candidate"]["unexpected_skip_count"] == 1
    assert evidence["host_frozen"]["status"] == "failed"
    assert evidence["host_frozen"]["required_skipped_count"] == 1
    assert aggregate["status"] == "failed"
    assert "unexecuted_test_count" not in aggregate


def test_dual_lane_aggregate_requires_both_lanes() -> None:
    evidence, aggregate = MCPValidationRunManager._validation_lane_evidence(
        command_specs=[
            {"argv": ["candidate"], "timeout_seconds": 10, "continue_on_failure": True},
            {"argv": ["host"], "timeout_seconds": 10, "continue_on_failure": True},
        ],
        command_results=[
            {"index": 0, "lane": "candidate", "ok": True},
            {"index": 1, "lane": "host_frozen", "ok": False},
        ],
        lane_assignments=["candidate", "host_frozen"],
        candidate_delta_sha256="a" * 64,
        candidate_module_provenance=True,
        host_preflight={
            "module_provenance": True,
            "frozen_toolchain_record_sha256": "b" * 64,
            "environment_root_binding_sha256": "c" * 64,
            "record_owned_preimport_bytecode_count": 0,
            "error_code": None,
        },
    )
    assert evidence["candidate"]["status"] == "passed"
    assert evidence["host_frozen"]["status"] == "failed"
    assert aggregate["status"] == "failed"
    assert aggregate["both_lanes_required"] is True


def test_dual_lane_aggregate_marks_missing_host_lane_incomplete() -> None:
    _evidence, aggregate = MCPValidationRunManager._validation_lane_evidence(
        command_specs=[
            {"argv": ["candidate"], "timeout_seconds": 10, "continue_on_failure": True},
            {"argv": ["host"], "timeout_seconds": 10, "continue_on_failure": True},
        ],
        command_results=[{"index": 0, "lane": "candidate", "ok": True}],
        lane_assignments=["candidate", "host_frozen"],
        candidate_delta_sha256="a" * 64,
        candidate_module_provenance=True,
        host_preflight=None,
    )
    assert aggregate["status"] == "incomplete"
    assert aggregate["classification_exhaustive"] is True
    assert aggregate["classification_basis"] == "complementary_marker_expressions"
    assert "unexecuted_test_count" not in aggregate


def test_host_frozen_preflight_requires_a_verified_host_environment(
    tmp_path: Path,
) -> None:
    project = _git_project(tmp_path)
    frozen_root = project / ".venv"
    frozen_root.mkdir()
    (frozen_root / "site-packages").mkdir()
    (frozen_root / "site-packages" / "unknown.cpython-312.pyc").write_bytes(b"fixture")

    manager = MCPValidationRunManager(str(project))
    evidence = manager._host_frozen_preflight(
        candidate_root=project,
        work_root=tmp_path / "host-runtime",
    )
    assert evidence["error_code"] == "FROZEN_TOOLCHAIN_AUTHORITY_UNAVAILABLE"
    assert evidence["total_host_venv_bytecode_count"] == 0
    assert (frozen_root / "site-packages" / "unknown.cpython-312.pyc").is_file()


def test_trusted_source_venv_materialization_is_local_and_bytecode_free(
    tmp_path: Path,
) -> None:
    project = _git_project(tmp_path)
    source_venv = tmp_path / "source-venv"
    (source_venv / "bin").mkdir(parents=True)
    (source_venv / "pyvenv.cfg").write_text("home = local\n", encoding="utf-8")
    (source_venv / "bin" / "python").write_text("launcher\n", encoding="utf-8")
    pyc = source_venv / "lib" / "python3.12" / "site-packages" / "x.pyc"
    pyc.parent.mkdir(parents=True)
    pyc.write_bytes(b"source-bytecode")

    summary = materialize_trusted_source_venv(
        source_venv=source_venv,
        source_checkout=project,
    )

    assert summary["local_assets_only"] is True
    assert summary["network_used"] is False
    assert summary["source_bytecode_count"] == 1
    assert summary["materialized_bytecode_count"] == 0
    assert not (project / ".venv" / "lib" / "python3.12" / "site-packages" / "x.pyc").exists()
    assert pyc.read_bytes() == b"source-bytecode"


def test_target_files_validation_uses_clean_candidate_checkout(
    tmp_path: Path,
) -> None:
    project = _git_project(tmp_path)
    manager = MCPValidationRunManager(str(project))
    preview = manager.preview(
        {"scope": "target_files", "target_files": ["README.md"]}
    )
    assert preview["ok"] is True
    started = manager.run({"preview_id": preview["preview_id"]})
    assert started["ok"] is True
    final = _terminal_status(manager, started["run_id"])

    assert final["status"] == "passed"
    checkout = final["output_summary"]["checkout_provenance"]
    assert checkout["candidate_head"] == _git(project, "rev-parse", "HEAD")
    assert checkout["isolated_from_project_worktree"] is True
    assert checkout["source_binding_match"] is True
    environment = final["output_summary"]["validation_environment"]
    assert environment["candidate_code_authority"] is True
    assert environment["parent_pythonpath_removed"] is True
    assert environment["shell_false"] is True


def test_target_files_overlay_loads_current_candidate_bytes_without_parent_import_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _git_project(tmp_path)
    marker = project / "marker.py"
    test_file = project / "tests" / "test_candidate_marker.py"
    test_file.parent.mkdir()
    marker.write_text('VALUE = "head"\n', encoding="utf-8")
    test_file.write_text(
        "from marker import VALUE\n\n\ndef test_candidate_marker():\n"
        '    assert VALUE == "head"\n',
        encoding="utf-8",
    )
    _git(project, "add", "marker.py", "tests/test_candidate_marker.py")
    _git(project, "commit", "-qm", "add marker fixture")

    marker.write_text('VALUE = "overlay"\n', encoding="utf-8")
    test_file.write_text(
        "from marker import VALUE\n\n\ndef test_candidate_marker():\n"
        '    assert VALUE == "overlay"\n',
        encoding="utf-8",
    )
    wrong_checkout = tmp_path / "wrong-checkout"
    wrong_checkout.mkdir()
    (wrong_checkout / "marker.py").write_text(
        'VALUE = "wrong-parent-import"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("PYTHONPATH", str(wrong_checkout))

    manager = MCPValidationRunManager(str(project))
    bindings, error = manager._build_candidate_source_bindings(
        ["marker.py", "tests/test_candidate_marker.py"]
    )
    assert error is None
    isolated = manager._prepare_isolated_checkout(
        _git(project, "rev-parse", "HEAD"),
        "validation_run_overlay",
    )
    try:
        overlay = manager._apply_candidate_source_overlays(
            isolated,
            bindings,
            binding_kind="target_files",
        )
        checkout = Path(isolated["root"])
        assert (checkout / "marker.py").read_text(encoding="utf-8") == (
            'VALUE = "overlay"\n'
        )
        environment = build_validation_subprocess_environment(
            candidate_root=checkout,
            parent_environment=dict(os.environ),
            temp_root=tmp_path / "runtime",
            forbidden_roots=(project,),
        )
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                "from marker import VALUE; assert VALUE == 'overlay'",
            ],
            cwd=checkout,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
            shell=False,
        )
        assert completed.returncode == 0
        assert overlay["binding_kind"] == "target_files"
        assert overlay["source_hashes_verified"] is True
        assert overlay["cleanup_complete"] is False
    finally:
        manager._remove_isolated_execution_overlays(isolated)
        assert manager._cleanup_isolated_checkout(isolated) is True

    assert isolated["source_overlay_summary"]["cleanup_complete"] is True
    assert marker.read_text(encoding="utf-8") == 'VALUE = "overlay"\n'


def test_target_files_preview_rejects_candidate_head_drift(tmp_path: Path) -> None:
    project = _git_project(tmp_path)
    manager = MCPValidationRunManager(str(project))
    preview = manager.preview(
        {"scope": "target_files", "target_files": ["README.md"]}
    )
    (project / "README.md").write_text("changed after preview\n", encoding="utf-8")
    _git(project, "add", "README.md")
    _git(project, "commit", "-qm", "drift")

    blocked = manager.run({"preview_id": preview["preview_id"]})
    assert blocked["ok"] is False
    assert blocked["error_code"] == "VALIDATION_CANDIDATE_HEAD_MISMATCH"


def test_target_files_run_rejects_bound_source_drift(tmp_path: Path) -> None:
    project = _git_project(tmp_path)
    manager = MCPValidationRunManager(str(project))
    preview = manager.preview(
        {"scope": "target_files", "target_files": ["README.md"]}
    )
    (project / "README.md").write_text("changed after preview\n", encoding="utf-8")

    blocked = manager.run({"preview_id": preview["preview_id"]})
    assert blocked["ok"] is False
    assert blocked["error_code"] == "VALIDATION_CANDIDATE_DELTA_INCOMPLETE"


def test_target_files_preview_rejects_symlink_escape(tmp_path: Path) -> None:
    project = _git_project(tmp_path)
    outside = tmp_path / "outside.py"
    outside.write_text("VALUE = 1\n", encoding="utf-8")
    (project / "escaped.py").symlink_to(outside)
    manager = MCPValidationRunManager(str(project))

    preview = manager.preview(
        {"scope": "target_files", "target_files": ["escaped.py"]}
    )
    assert preview["ok"] is False
    assert preview["error_code"] == "CANDIDATE_SOURCE_BINDING_INVALID"


def test_validation_result_writes_never_replace_an_older_run(tmp_path: Path) -> None:
    project = _git_project(tmp_path)
    manager = MCPValidationRunManager(str(project))
    base = {
        "schema_version": "colameta.validation_run_result.v1",
        "preview_id": "preview_keep_1",
        "action": "run",
        "status": "passed",
        "passed": True,
        "scope": "target_files",
        "target_files": ["README.md"],
        "strategy": "quick_static",
        "validation_groups": [],
        "command_summary": [],
        "command_count": 0,
        "command_results": [],
        "failed_command_indexes": [],
        "failed_command_index": None,
        "output_summary": {"redacted": True, "total_output_chars": 0, "truncated": False},
        "started_at": "2026-08-03T00:00:00+00:00",
        "completed_at": "2026-08-03T00:00:01+00:00",
        "duration_seconds": 1.0,
        "manifest_validation": None,
    }
    first = {**base, "run_id": "validation_run_keep_first"}
    second = {**base, "run_id": "validation_run_keep_second", "preview_id": "preview_keep_2"}
    manager._write_terminal_run_result(first["run_id"], first)
    first_path = Path(manager._run_result_path(first["run_id"]))
    original = first_path.read_bytes()
    manager._write_terminal_run_result(second["run_id"], second)

    assert first_path.read_bytes() == original
    assert Path(manager._run_result_path(second["run_id"])).is_file()
    assert json.loads(first_path.read_text(encoding="utf-8"))["run_id"] == first["run_id"]
