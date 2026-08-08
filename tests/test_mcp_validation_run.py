from __future__ import annotations

import hashlib
import json
import os
import builtins
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig
import time
import types

import pytest

import runner.mcp_validation_run as validation_run
import runner.toolchain_environment as toolchain_environment
import runner.work_item_governance.toolchain_binding as toolchain_binding
from runner.mcp_validation_run import (
    AmbiguousHostFrozenMarkerError,
    GroupedPytestMarkerSelectorError,
    MCPValidationRunManager,
    MultiplePytestMarkerSelectorsError,
)
from runner.toolchain_environment import (
    ValidationEnvironment,
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


def _venv_purelib(venv: Path) -> Path:
    if os.name == "nt":
        return venv / "Lib" / "site-packages"
    return Path(
        sysconfig.get_path(
            "purelib",
            vars={"base": str(venv), "platbase": str(venv)},
        )
    )


def _fake_environment_identity() -> dict[str, object]:
    package_set, package_set_sha256 = (
        toolchain_environment.canonical_installed_distribution_set(
            [{"canonical_name": "fixture", "version": "1.0"}]
        )
    )
    environment_identity, environment_identity_sha256 = (
        toolchain_environment.canonical_environment_identity(
            executable_sha256="1" * 64,
            python_implementation="CPython",
            python_version="3.12.3",
            python_cache_tag="cpython-312",
            package_set_sha256=package_set_sha256,
        )
    )
    return {
        **environment_identity,
        "package_set": package_set,
        "distribution_count": 1,
        "environment_identity_sha256": environment_identity_sha256,
    }


def test_validation_tool_install_timeout_remains_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def timeout(command, **kwargs):
        assert kwargs["timeout"] == 1200
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(toolchain_environment.subprocess, "run", timeout)

    with pytest.raises(
        toolchain_environment.ValidationEnvironmentError,
        match="validation toolchain candidate validation tool installation failed",
    ):
        toolchain_environment._run_toolchain_command(
            ["candidate-validation-tools"],
            cwd=tmp_path,
            environment={},
            timeout_seconds=1200,
            label="candidate validation tool installation",
        )


def _trusted_launcher_artifact_for_bindings(
    tmp_path: Path,
    bindings: list[dict[str, object]],
) -> tuple[MCPValidationRunManager, dict[str, object], Path]:
    project = _git_project(tmp_path)
    launcher = project / "scripts" / "work_item_r3_trusted_launcher.py"
    launcher.parent.mkdir(parents=True)
    launcher.write_bytes(
        Path("scripts/work_item_r3_trusted_launcher.py").read_bytes()
    )
    manager = MCPValidationRunManager(str(project))
    identity = manager._candidate_identity(
        "a" * 40,
        bindings,
        binding_scope="full_allowed_worktree_delta",
    )
    artifact = {
        "candidate_identity": identity,
        "candidate_source_bindings": list(bindings),
        "validation_selection": {
            "command_specs_sha256": "b" * 64,
        },
    }
    host_preflight = {
        "toolchain_project_root": str(tmp_path / "toolchain-project"),
        "environment_root": str(tmp_path / "toolchain-project" / ".venv"),
        "environment_root_sha256": "c" * 64,
        "frozen_toolchain_record_sha256": "d" * 64,
        "cryptography_version": "50.0.0",
        "frozen_asset_path": str(tmp_path / "assets" / "cryptography.whl"),
        "frozen_asset_filename": "cryptography-50.0.0-cp39-abi3-manylinux_2_34_x86_64.whl",
        "frozen_asset_size": 4762400,
        "frozen_asset_sha256": "e" * 64,
    }
    return manager, {"artifact": artifact, "host_preflight": host_preflight}, project


def test_trusted_launcher_receipt_accepts_explicit_empty_candidate_delta(
    tmp_path: Path,
) -> None:
    manager, payload, project = _trusted_launcher_artifact_for_bindings(tmp_path, [])
    _path, receipt = manager._write_trusted_launcher_binding_receipt(
        artifact=payload["artifact"],
        preview_id="preview-empty-delta",
        candidate_root=project,
        run_parent=tmp_path / "run",
        host_preflight=payload["host_preflight"],
    )
    candidate = receipt["candidate"]
    assert candidate["source_binding_count"] == 0
    assert candidate["source_bindings"] == []
    assert candidate["source_binding_sha256"] == (
        validation_run.canonical_manifest_validation_sha256([])
    )
    assert candidate["worktree_delta_sha256"] == candidate["source_binding_sha256"]


@pytest.mark.parametrize(
    "identity_update",
    [
        {"source_binding_sha256": None},
        {"worktree_delta_sha256": None},
        {"source_binding_sha256": "e" * 64},
    ],
)
def test_trusted_launcher_receipt_rejects_missing_null_or_mismatched_empty_delta(
    tmp_path: Path,
    identity_update: dict[str, object],
) -> None:
    manager, payload, project = _trusted_launcher_artifact_for_bindings(tmp_path, [])
    payload["artifact"]["candidate_identity"].update(identity_update)
    with pytest.raises(
        validation_run.ValidationEnvironmentError,
        match="trusted launcher candidate digest binding mismatch",
    ):
        manager._write_trusted_launcher_binding_receipt(
            artifact=payload["artifact"],
            preview_id="preview-invalid-empty-delta",
            candidate_root=project,
            run_parent=tmp_path / "run",
            host_preflight=payload["host_preflight"],
        )


def test_trusted_launcher_receipt_rejects_missing_empty_delta_binding(
    tmp_path: Path,
) -> None:
    manager, payload, project = _trusted_launcher_artifact_for_bindings(tmp_path, [])
    del payload["artifact"]["candidate_identity"]["worktree_delta_sha256"]
    with pytest.raises(
        validation_run.ValidationEnvironmentError,
        match="trusted launcher candidate digest binding mismatch",
    ):
        manager._write_trusted_launcher_binding_receipt(
            artifact=payload["artifact"],
            preview_id="preview-missing-empty-delta",
            candidate_root=project,
            run_parent=tmp_path / "run",
            host_preflight=payload["host_preflight"],
        )


@pytest.mark.parametrize("invalid_bindings", ["missing", None, [{"path": "broken"}]])
def test_trusted_launcher_receipt_rejects_missing_or_malformed_delta_evidence(
    tmp_path: Path,
    invalid_bindings: object,
) -> None:
    manager, payload, project = _trusted_launcher_artifact_for_bindings(tmp_path, [])
    if invalid_bindings == "missing":
        del payload["artifact"]["candidate_source_bindings"]
    else:
        payload["artifact"]["candidate_source_bindings"] = invalid_bindings
    with pytest.raises(
        validation_run.ValidationEnvironmentError,
        match="trusted launcher candidate source bindings are unavailable",
    ):
        manager._write_trusted_launcher_binding_receipt(
            artifact=payload["artifact"],
            preview_id="preview-malformed-empty-delta",
            candidate_root=project,
            run_parent=tmp_path / "run",
            host_preflight=payload["host_preflight"],
        )


def test_frozen_cryptography_record_is_compatible_with_python_310_and_current_host() -> None:
    from packaging.tags import cpython_tags, sys_tags
    from packaging.utils import parse_wheel_filename

    asset = toolchain_binding.load_verified_frozen_toolchain_record()["required_assets"][
        "cryptography"
    ]
    _name, _version, _build, compatible_tags = parse_wheel_filename(asset["filename"])
    compatible_tags = set(compatible_tags)
    python310_tags = set(
        cpython_tags(
            python_version=(3, 10),
            abis=("cp310",),
            platforms=("manylinux_2_34_x86_64",),
        )
    )
    cp311_tags = set(
        parse_wheel_filename(
            "cryptography-50.0.0-cp311-abi3-manylinux_2_34_x86_64.whl"
        )[3]
    )
    assert compatible_tags & python310_tags
    assert compatible_tags & set(sys_tags())
    assert not cp311_tags & python310_tags
    assert asset["filename"].startswith("cryptography-50.0.0-cp39-abi3-")
    assert asset["size"] == 4762400
    assert asset["sha256"] == (
        "37fdb0d0111f1e2ff07139dfb79f1b49531f8e213c46f1163dd7642979b58c47"
    )


def test_frozen_asset_size_mismatch_is_rejected_before_hash_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asset = toolchain_binding.load_verified_frozen_toolchain_record()["required_assets"][
        "cryptography"
    ]
    wrong = tmp_path / asset["filename"]
    wrong.write_bytes(b"wrong-size")
    monkeypatch.setenv("COLAMETA_FROZEN_CRYPTOGRAPHY_WHEEL", str(wrong))
    manager = MCPValidationRunManager(str(_git_project(tmp_path)))
    resolved = manager._resolve_frozen_toolchain_asset()
    assert resolved == {
        "ok": False,
        "error_code": "FROZEN_TOOLCHAIN_LOCAL_ASSETS_UNAVAILABLE",
    }


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


def test_project_metadata_uses_tomli_only_when_stdlib_tomllib_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    (candidate / "pyproject.toml").write_bytes(
        b'[project]\nname = "fixture"\n[project.scripts]\nfixture = "fixture:main"\n'
    )
    fake_tomli = types.ModuleType("tomli")
    fake_tomli.load = lambda handle: {
        "project": {
            "name": "fixture",
            "scripts": {"fixture": "fixture:main"},
        }
    }
    real_import = builtins.__import__

    def import_without_tomllib(name, *args, **kwargs):
        if name == "tomllib":
            raise ModuleNotFoundError("tomllib unavailable in Python 3.10")
        if name == "tomli":
            return fake_tomli
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_tomllib)
    assert toolchain_environment._project_metadata(candidate) == (
        "fixture",
        ["fixture"],
    )


def test_runtime_dependencies_are_direct_and_python_version_bound() -> None:
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib

    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    dependencies = project["project"]["dependencies"]
    assert "tomli>=2.0.1; python_version < \"3.11\"" in dependencies
    assert "packaging>=24,<27" in dependencies


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
    timeouts: list[tuple[str, int]] = []
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
            timeouts.append((kwargs["label"], kwargs["timeout_seconds"])),
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
    monkeypatch.setattr(
        toolchain_environment,
        "_probe_installed_environment_identity",
        lambda **_kwargs: _fake_environment_identity(),
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
    assert timeouts == [
        ("candidate pip bootstrap upgrade", 300),
        ("candidate validation tool installation", 1200),
    ]
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
    timeouts: list[tuple[str, int]] = []

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
            timeouts.append((kwargs["label"], kwargs["timeout_seconds"])),
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
    monkeypatch.setattr(
        toolchain_environment,
        "_probe_installed_environment_identity",
        lambda **_kwargs: _fake_environment_identity(),
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
    assert timeouts == [
        ("candidate pip bootstrap upgrade", 300),
        ("candidate validation tool installation", 1200),
        ("candidate wheel build", 300),
        ("candidate wheel installation", 300),
    ]
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


@pytest.mark.parametrize(
    ("command", "is_pytest", "marker", "expected_lane"),
    [
        (
            ["python", "-m", "pytest", "x.py", "-m", "host_frozen_toolchain"],
            True,
            "host_frozen_toolchain",
            "host_frozen",
        ),
        (
            [
                "python",
                "-m",
                "pytest",
                "x.py",
                "-m",
                "not host_frozen_toolchain",
            ],
            True,
            "not host_frozen_toolchain",
            "candidate",
        ),
        (
            ["python", "-m", "pytest", "x.py", "-m=host_frozen_toolchain"],
            True,
            "host_frozen_toolchain",
            "host_frozen",
        ),
        (
            ["python", "-m", "pytest", "x.py", "-mhost_frozen_toolchain"],
            True,
            "host_frozen_toolchain",
            "host_frozen",
        ),
        (
            [
                "python",
                "-m",
                "pytest",
                "x.py",
                "-m=not host_frozen_toolchain",
            ],
            True,
            "not host_frozen_toolchain",
            "candidate",
        ),
        (
            [
                "python",
                "-m",
                "pytest",
                "x.py",
                "-mnot host_frozen_toolchain",
            ],
            True,
            "not host_frozen_toolchain",
            "candidate",
        ),
        (["python", "-m", "pytest", "x.py"], True, None, "candidate"),
        (
            ["pytest", "x.py", "-m", "host_frozen_toolchain"],
            True,
            "host_frozen_toolchain",
            "host_frozen",
        ),
        (
            ["pytest", "x.py", "-m=host_frozen_toolchain"],
            True,
            "host_frozen_toolchain",
            "host_frozen",
        ),
        (
            ["pytest", "x.py", "-mhost_frozen_toolchain"],
            True,
            "host_frozen_toolchain",
            "host_frozen",
        ),
        (
            ["pytest", "x.py", "-m=not host_frozen_toolchain"],
            True,
            "not host_frozen_toolchain",
            "candidate",
        ),
        (
            ["pytest", "x.py", "-mnot host_frozen_toolchain"],
            True,
            "not host_frozen_toolchain",
            "candidate",
        ),
        (
            ["python", "-m", "unrelated_module", "-m", "host_frozen_toolchain"],
            False,
            None,
            "candidate",
        ),
        (
            ["python", "-m", "unrelated_module", "-m=host_frozen_toolchain"],
            False,
            None,
            "candidate",
        ),
        (["python", "-m", "pytest", "x.py", "-m="], True, None, "candidate"),
        (["python", "-m", "pytest", "x.py", "-m"], True, None, "candidate"),
    ],
)
def test_pytest_marker_parser_distinguishes_python_module_flag(
    command: list[str],
    is_pytest: bool,
    marker: str | None,
    expected_lane: str,
) -> None:
    actual_is_pytest, actual_marker = (
        MCPValidationRunManager._extract_pytest_marker_expression(command)
    )
    assert (actual_is_pytest, actual_marker) == (is_pytest, marker)
    assert MCPValidationRunManager._command_lane(command) == expected_lane


@pytest.mark.parametrize(
    "marker_expression",
    [
        "host_frozen_toolchain or smoke",
        "host_frozen_toolchain and smoke",
        "smoke or host_frozen_toolchain",
        "smoke and host_frozen_toolchain",
        "not (host_frozen_toolchain)",
        "not host_frozen_toolchain or smoke",
        "host_frozen_toolchain or not smoke",
    ],
)
def test_compound_host_frozen_marker_is_rejected(
    marker_expression: str,
) -> None:
    command = ["python", "-m", "pytest", "x.py", f"-m={marker_expression}"]
    with pytest.raises(
        AmbiguousHostFrozenMarkerError,
        match="mixed or unsupported authority semantics",
    ) as raised:
        MCPValidationRunManager._command_lane(command)
    assert raised.value.code == "AMBIGUOUS_HOST_FROZEN_MARKER_EXPRESSION"


def test_compact_compound_host_frozen_marker_is_rejected() -> None:
    command = [
        "python",
        "-m",
        "pytest",
        "x.py",
        "-mhost_frozen_toolchain or smoke",
    ]
    with pytest.raises(
        AmbiguousHostFrozenMarkerError,
        match="mixed or unsupported authority semantics",
    ):
        MCPValidationRunManager._command_lane(command)


@pytest.mark.parametrize(
    "command",
    [
        ["python", "-m", "pytest", "x.py", "-qmhost_frozen_toolchain"],
        ["python", "-m", "pytest", "x.py", "-qvmhost_frozen_toolchain"],
        ["pytest", "x.py", "-vmsmoke"],
    ],
)
def test_grouped_pytest_marker_selector_is_rejected(
    command: list[str],
) -> None:
    with pytest.raises(
        GroupedPytestMarkerSelectorError,
        match="grouped pytest marker selectors",
    ) as raised:
        MCPValidationRunManager._command_lane(command)
    assert raised.value.code == "GROUPED_PYTEST_MARKER_SELECTOR_UNSUPPORTED"


@pytest.mark.parametrize(
    "command",
    [
        ["python", "-m", "pytest", "x.py", "-qv"],
        ["pytest", "x.py", "-vv"],
    ],
)
def test_grouped_pytest_options_without_marker_stay_candidate(
    command: list[str],
) -> None:
    assert MCPValidationRunManager._command_lane(command) == "candidate"


def test_grouped_marker_after_double_dash_is_positional() -> None:
    command = ["pytest", "--", "-qmhost_frozen_toolchain"]
    is_pytest, selections = MCPValidationRunManager._extract_pytest_marker_selections(
        command
    )
    assert is_pytest is True
    assert selections == []
    assert MCPValidationRunManager._command_lane(command) == "candidate"


def test_preview_rejects_grouped_marker_before_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = MCPValidationRunManager(str(_git_project(tmp_path)))
    monkeypatch.setattr(
        manager,
        "_current_acceptance_commands",
        lambda: ([{
            "argv": [
                "python",
                "-m",
                "pytest",
                "tests",
                "-q",
                "-qmhost_frozen_toolchain",
            ],
            "timeout_seconds": 60,
            "continue_on_failure": False,
        }], []),
    )

    result = manager.preview({"scope": "current_version"})

    assert result["ok"] is False
    assert result["error_code"] == "GROUPED_PYTEST_MARKER_SELECTOR_UNSUPPORTED"
    assert result["command_executed"] is False
    assert result["candidate_lane_fallback"] is False
    assert result["host_frozen_lane_execution"] is False
    assert "preview_id" not in result


@pytest.mark.parametrize(
    "marker_expression",
    [
        "smoke",
        "smoke or unit",
        "host_frozen_toolchain_extra",
        "not_host_frozen_toolchain",
        "my_host_frozen_toolchain",
        "host_frozen_toolchain2",
    ],
)
def test_non_protected_marker_expression_stays_candidate(
    marker_expression: str,
) -> None:
    command = ["pytest", "x.py", f"-m={marker_expression}"]
    assert MCPValidationRunManager._command_lane(command) == "candidate"


def test_pytest_metrics_are_parsed_before_retention_truncation() -> None:
    command = ["python", "-m", "pytest", "x.py", "-q"]
    raw_stdout = (
        "noise\n" * (validation_run.MAX_STDOUT_CHARS // 2)
        + "2 passed, 1 skipped in 0.01s\n"
    )
    metrics = MCPValidationRunManager._pytest_command_metrics(
        command,
        raw_stdout,
        "",
    )
    retained_stdout, truncated = validation_run._truncate(
        raw_stdout,
        validation_run.MAX_STDOUT_CHARS,
    )

    assert truncated is True
    assert "2 passed, 1 skipped" not in retained_stdout
    assert metrics["metrics_valid"] is True
    assert metrics["selected_test_count"] == 3
    assert metrics["skipped_count"] == 1


def test_host_frozen_metrics_missing_summary_are_invalid() -> None:
    command = ["python", "-m", "pytest", "x.py", "-q"]
    metrics = MCPValidationRunManager._pytest_command_metrics(
        command,
        "output without a pytest terminal summary",
        "",
    )
    assert metrics["metrics_valid"] is False


def test_preview_rejects_compound_host_frozen_marker_before_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = MCPValidationRunManager(str(_git_project(tmp_path)))
    monkeypatch.setattr(
        manager,
        "_current_acceptance_commands",
        lambda: ([{
            "argv": [
                "python",
                "-m",
                "pytest",
                "tests",
                "-q",
                "-m=host_frozen_toolchain or smoke",
            ],
            "timeout_seconds": 60,
            "continue_on_failure": False,
        }], []),
    )

    result = manager.preview({"scope": "current_version"})

    assert result["ok"] is False
    assert result["error_code"] == "AMBIGUOUS_HOST_FROZEN_MARKER_EXPRESSION"
    assert result["command_executed"] is False
    assert result["candidate_lane_fallback"] is False
    assert result["host_frozen_lane_execution"] is False
    assert "preview_id" not in result
    assert not (tmp_path / "validation-project" / ".colameta").exists()


@pytest.mark.parametrize(
    "command",
    [
        [
            "python",
            "-m",
            "pytest",
            "x.py",
            "-m",
            "smoke",
            "-m",
            "host_frozen_toolchain",
        ],
        [
            "python",
            "-m",
            "pytest",
            "x.py",
            "-m",
            "host_frozen_toolchain",
            "-m",
            "smoke",
        ],
        [
            "python",
            "-m",
            "pytest",
            "x.py",
            "-m",
            "smoke",
            "-m",
            "unit",
        ],
        [
            "python",
            "-m",
            "pytest",
            "x.py",
            "-m=smoke",
            "-m=host_frozen_toolchain",
        ],
    ],
)
def test_repeated_pytest_marker_selectors_are_rejected(
    command: list[str],
) -> None:
    with pytest.raises(
        MultiplePytestMarkerSelectorsError,
        match="multiple marker selectors",
    ):
        MCPValidationRunManager._command_lane(command)


def test_repeated_compact_pytest_marker_selectors_are_rejected() -> None:
    command = [
        "python",
        "-m",
        "pytest",
        "x.py",
        "-msmoke",
        "-mhost_frozen_toolchain",
    ]
    with pytest.raises(
        MultiplePytestMarkerSelectorsError,
        match="multiple marker selectors",
    ):
        MCPValidationRunManager._command_lane(command)


def test_unsafe_acceptance_command_is_not_silently_filtered(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _git_project(tmp_path)
    manager = MCPValidationRunManager(str(project))
    acceptance = types.SimpleNamespace(
        version="v1.18",
        acceptance_commands=[
            types.SimpleNamespace(
                command="python -m pytest tests -q",
                timeout_seconds=60,
                continue_on_failure=False,
            ),
            types.SimpleNamespace(
                command=(
                    "python -m pytest tests -q -m "
                    "'host_frozen_toolchain or smoke'"
                ),
                timeout_seconds=60,
                continue_on_failure=False,
            ),
        ],
    )
    monkeypatch.setattr(
        validation_run,
        "load_current_version",
        lambda _project_root: "v1.18",
    )
    monkeypatch.setattr(
        validation_run.PlanLoader,
        "load_plan",
        lambda _loader, _plan_file: types.SimpleNamespace(versions=[acceptance]),
    )

    result = manager.preview({"scope": "current_version"})

    assert result["ok"] is False
    assert result["error_code"] == "AMBIGUOUS_HOST_FROZEN_MARKER_EXPRESSION"
    assert result["command_executed"] is False
    assert result["candidate_lane_fallback"] is False
    assert "preview_id" not in result


def test_preview_rejects_repeated_marker_selector_before_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = MCPValidationRunManager(str(_git_project(tmp_path)))
    monkeypatch.setattr(
        manager,
        "_current_acceptance_commands",
        lambda: ([{
            "argv": [
                "python",
                "-m",
                "pytest",
                "tests",
                "-q",
                "-m",
                "smoke",
                "-m",
                "host_frozen_toolchain",
            ],
            "timeout_seconds": 60,
            "continue_on_failure": False,
        }], []),
    )

    result = manager.preview({"scope": "current_version"})

    assert result["ok"] is False
    assert result["error_code"] == "MULTIPLE_PYTEST_MARKER_SELECTORS_UNSUPPORTED"
    assert result["command_executed"] is False
    assert result["candidate_lane_fallback"] is False
    assert result["host_frozen_lane_execution"] is False
    assert "preview_id" not in result


def test_full_preserves_declared_host_frozen_acceptance_lane(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = MCPValidationRunManager(str(_git_project(tmp_path)))
    acceptance = [
        {
            "argv": ["python", "-m", "pytest", "tests", "-q"],
            "timeout_seconds": 600,
            "continue_on_failure": False,
        },
        {
            "argv": ["python", "-m", "compileall", "runner"],
            "timeout_seconds": 600,
            "continue_on_failure": False,
        },
        {
            "argv": ["git", "diff", "--check"],
            "timeout_seconds": 600,
            "continue_on_failure": False,
        },
        {
            "argv": [
                "python",
                "-m",
                "pytest",
                "tests/test_work_item_r3_closeout_runner.py",
                "-q",
                "-m",
                "host_frozen_toolchain",
                "-rs",
            ],
            "timeout_seconds": 1200,
            "continue_on_failure": False,
        },
    ]
    monkeypatch.setattr(
        manager,
        "_current_acceptance_commands",
        lambda: (acceptance, []),
    )
    monkeypatch.setattr(
        manager,
        "_full_validation_strategies",
        lambda: [
            {
                "strategy": "python_candidate_full",
                "lane": "candidate",
                "argv": ["python", "-m", "pytest", "tests", "-q"],
            }
        ],
    )

    commands, specs, _strategy, _warnings, groups, lanes = manager._select_commands(
        "full", []
    )

    assert len(acceptance) == 4
    assert len(commands) == len(specs) == 5
    assert lanes[:4] == ["candidate", "candidate", "candidate", "host_frozen"]
    assert groups[0]["strategy"] == "plan_acceptance"


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


def _patch_git_diff_only_preview(
    manager: MCPValidationRunManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command = ["git", "diff", "--check"]
    spec = {
        "argv": command,
        "timeout_seconds": 30,
        "continue_on_failure": False,
    }
    monkeypatch.setattr(
        manager,
        "_select_commands",
        lambda _scope, _target_files: (
            [command],
            [spec],
            "git_diff_check",
            [],
            [{"strategy": "git_diff_check", "lane": "candidate", "files": [], "command_count": 1}],
            ["candidate"],
        ),
    )


def test_non_manifest_diff_check_rejects_overlay_whitespace_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _git_project(tmp_path)
    source = project / "candidate.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")
    _git(project, "add", "candidate.py")
    _git(project, "commit", "-qm", "add candidate")
    source.write_text("VALUE = 1  \n", encoding="utf-8")

    manager = MCPValidationRunManager(str(project))
    _patch_git_diff_only_preview(manager, monkeypatch)
    preview = manager.preview({"scope": "target_files", "target_files": ["candidate.py"]})
    assert preview["ok"] is True
    artifact = manager._read_preview(preview["preview_id"])
    assert artifact is not None
    assert "manifest_validation" not in artifact
    started = manager.run({"preview_id": preview["preview_id"]})
    final = _terminal_status(manager, started["run_id"])

    assert final["status"] == "failed"
    command_result = final["command_results"][0]
    assert command_result["ok"] is False
    assert "trailing whitespace" in (
        command_result["stdout"] + command_result["stderr"]
    )
    assert final["output_summary"]["checkout_provenance"]["source_binding_match"] is True


def test_non_manifest_diff_check_uses_overlay_to_fix_head_whitespace_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _git_project(tmp_path)
    source = project / "candidate.py"
    source.write_text("VALUE = 1  \n", encoding="utf-8")
    _git(project, "add", "candidate.py")
    _git(project, "commit", "-qm", "add whitespace fixture")
    source.write_text("VALUE = 1\n", encoding="utf-8")

    manager = MCPValidationRunManager(str(project))
    _patch_git_diff_only_preview(manager, monkeypatch)
    preview = manager.preview({"scope": "target_files", "target_files": ["candidate.py"]})
    assert preview["ok"] is True
    assert "manifest_validation" not in (manager._read_preview(preview["preview_id"]) or {})
    started = manager.run({"preview_id": preview["preview_id"]})
    final = _terminal_status(manager, started["run_id"])

    assert final["status"] == "passed"
    assert final["command_results"][0]["ok"] is True
    assert final["output_summary"]["checkout_provenance"]["source_binding_match"] is True


def test_manifest_bound_diff_check_keeps_commit_bound_command_contract(
    tmp_path: Path,
) -> None:
    manager = MCPValidationRunManager(str(_git_project(tmp_path)))
    candidate_head = "a" * 40
    assert manager._manifest_execution_command(
        ["git", "diff", "--check"], candidate_head
    ) == [
        "git",
        "diff-tree",
        "--check",
        "--root",
        "-r",
        "-m",
        "--no-commit-id",
        "--no-ext-diff",
        "--no-textconv",
        candidate_head,
    ]


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
    # Merely changing the toolchain binding source does not implicitly opt a
    # generic validation scope into ColaMeta's private Host-Frozen lane.
    assert lanes == ["candidate"]
    assert all("test_work_item_r3_closeout_runner.py" not in command for command in commands)


def test_generic_python_full_selection_does_not_inject_colameta_host_tests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _git_project(tmp_path)
    (project / "pyproject.toml").write_text(
        "[project]\nname='demo'\nversion='0.1.0'\n",
        encoding="utf-8",
    )
    tests_dir = project / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_demo.py").write_text(
        "def test_demo():\n    assert True\n",
        encoding="utf-8",
    )
    manager = MCPValidationRunManager(str(project))
    monkeypatch.setattr(manager, "_current_acceptance_commands", lambda: ([], []))

    commands, _specs, _strategy, _warnings, _groups, lanes = manager._select_commands(
        "full", []
    )

    assert lanes == ["candidate"]
    assert all(
        "test_work_item_r3_closeout_runner.py" not in command
        for command in commands
    )
    assert all("host_frozen_toolchain" not in command for command in commands)


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
    pyc = _venv_purelib(source_venv) / "x.pyc"
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
    assert not (_venv_purelib(project / ".venv") / "x.pyc").exists()
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


def _minimal_validation_environment(
    tmp_path: Path,
    candidate: Path,
) -> ValidationEnvironment:
    del tmp_path
    venv_dir = candidate / ".venv"
    bin_dir = venv_dir / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "python").symlink_to(Path(sys.executable).resolve())
    environment = dict(os.environ)
    environment["PATH"] = os.pathsep.join([str(bin_dir), os.defpath])
    environment["VIRTUAL_ENV"] = str(venv_dir)
    environment.pop("PYTHONPYCACHEPREFIX", None)
    package_set, package_set_sha256 = (
        toolchain_environment.canonical_installed_distribution_set(
            [{"canonical_name": "fixture", "version": "1.0"}]
        )
    )
    executable_sha256 = hashlib.sha256(
        Path(sys.executable).read_bytes()
    ).hexdigest()
    identity, environment_identity_sha256 = (
        toolchain_environment.canonical_environment_identity(
            executable_sha256=executable_sha256,
            python_implementation="CPython",
            python_version=(
                f"{sys.version_info.major}.{sys.version_info.minor}."
                f"{sys.version_info.micro}"
            ),
            python_cache_tag=sys.implementation.cache_tag,
            package_set_sha256=package_set_sha256,
        )
    )
    return ValidationEnvironment(
        candidate_root=candidate,
        cwd=candidate,
        env=environment,
        venv_dir=venv_dir,
        python_executable=bin_dir / "python",
        summary={
            "candidate_module_provenance_verified": True,
            "python_implementation": identity["python_implementation"],
            "python_version": identity["python_version"],
            "python_cache_tag": identity["python_cache_tag"],
            "package_set": package_set,
            "package_set_sha256": package_set_sha256,
            "distribution_count": len(package_set["distributions"]),
            "executable_sha256": executable_sha256,
            "environment_identity": identity,
            "environment_identity_sha256": environment_identity_sha256,
        },
    )


def test_candidate_compileall_uses_unique_external_pycache_without_leakage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _git_project(tmp_path)
    module = project / "fixture_module.py"
    module.write_text("VALUE = 1\n", encoding="utf-8")
    (project / ".gitignore").write_text(".venv\n", encoding="utf-8")
    _git(project, "add", "fixture_module.py", ".gitignore")
    _git(project, "commit", "-qm", "add compile fixture")
    manager = MCPValidationRunManager(str(project))
    environment = _minimal_validation_environment(tmp_path, project)
    evidence_root = (
        project
        / ".colameta"
        / "runtime"
        / "validation-run-artifacts"
        / "validation_run_compileall_regression"
    )
    command_artifacts_root = evidence_root / "command-artifacts"
    external_venv_bytecode = (
        _venv_purelib(environment.venv_dir) / "external.pyc"
    )
    external_venv_bytecode.parent.mkdir(parents=True)
    external_venv_bytecode.write_bytes(b"external validation bytecode")
    observed: list[tuple[list[str], dict[str, str]]] = []
    original_run = validation_run.subprocess.run

    def recording_run(command, *args, **kwargs):
        observed.append((list(command), dict(kwargs.get("env") or {})))
        return original_run(command, *args, **kwargs)

    monkeypatch.setattr(validation_run.subprocess, "run", recording_run)
    token = validation_run._VALIDATION_ENVIRONMENT_CONTEXT.set(environment)
    try:
        first = manager._run_candidate_command(
            [".venv/bin/python", "-m", "compileall", "fixture_module.py"],
            timeout_seconds=30,
            cwd=str(project),
            command_index=3,
            command_artifacts_root=command_artifacts_root,
        )
        second = manager._run_candidate_command(
            [".venv/bin/python", "-m", "compileall", "fixture_module.py"],
            timeout_seconds=30,
            cwd=str(project),
            command_index=4,
            command_artifacts_root=command_artifacts_root,
        )
        following = manager._run_candidate_command(
            [
                ".venv/bin/python",
                "-c",
                "import os; print(os.environ.get('PYTHONPYCACHEPREFIX'))",
            ],
            timeout_seconds=30,
            cwd=str(project),
            command_index=5,
            command_artifacts_root=command_artifacts_root,
        )
    finally:
        validation_run._VALIDATION_ENVIRONMENT_CONTEXT.reset(token)

    assert first["returncode"] == second["returncode"] == 0
    first_artifact = first["compileall_artifact"]
    second_artifact = second["compileall_artifact"]
    assert first_artifact["scratch_root_class"] == (
        "repository_external_ephemeral"
    )
    assert second_artifact["scratch_root_class"] == (
        "repository_external_ephemeral"
    )
    assert first_artifact["pycache_root_sanitized"] == (
        "external-command-scratch/pycache"
    )
    assert second_artifact["pycache_root_sanitized"] == (
        "external-command-scratch/pycache"
    )
    assert first_artifact["pyc_count"] > 0
    assert second_artifact["pyc_count"] > 0
    assert first_artifact["candidate_contamination_count"] == 0
    assert second_artifact["candidate_contamination_count"] == 0
    assert first_artifact["cleanup_complete"] is True
    assert second_artifact["cleanup_complete"] is True
    assert manager._candidate_bytecode_contamination_count(project) == 0
    assert external_venv_bytecode.is_file()
    assert _git(project, "status", "--porcelain=v1", "--untracked-files=all") == ""
    assert observed[0][0][1:3] == ["-m", "compileall"]
    assert observed[1][0][1:3] == ["-m", "compileall"]
    first_pycache = Path(observed[0][1]["PYTHONPYCACHEPREFIX"])
    second_pycache = Path(observed[1][1]["PYTHONPYCACHEPREFIX"])
    protected_roots = (
        project,
        environment.venv_dir,
        evidence_root,
        command_artifacts_root,
    )
    assert first_pycache != second_pycache
    assert all(
        not manager._paths_overlap(first_pycache, root)
        and not manager._paths_overlap(second_pycache, root)
        for root in protected_roots
    )
    assert not first_pycache.parent.exists()
    assert not second_pycache.parent.exists()
    assert following["returncode"] == 0
    assert following["stdout"].strip() == "None"
    assert "PYTHONPYCACHEPREFIX" not in observed[2][1]


def test_candidate_compileall_rejects_every_protected_scratch_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    development_parent = tmp_path / "development"
    candidate_parent = tmp_path / "candidate"
    development_parent.mkdir()
    candidate_parent.mkdir()
    development = _git_project(development_parent)
    candidate = _git_project(candidate_parent)
    module = candidate / "fixture_module.py"
    module.write_text("VALUE = 1\n", encoding="utf-8")
    manager = MCPValidationRunManager(str(development))
    environment = _minimal_validation_environment(tmp_path, candidate)
    evidence_root = (
        development
        / ".colameta"
        / "runtime"
        / "validation-run-artifacts"
        / "validation_run_protected_roots"
    )
    command_artifacts_root = evidence_root / "command-artifacts"
    protected_roots = (
        development,
        candidate,
        environment.venv_dir,
        evidence_root,
        command_artifacts_root,
    )
    token = validation_run._VALIDATION_ENVIRONMENT_CONTEXT.set(environment)
    try:
        for command_index, protected_root in enumerate(protected_roots, 20):
            def forced_mkdtemp(prefix: str, root=protected_root) -> str:
                root.mkdir(parents=True, exist_ok=True)
                forced = root / f"{prefix}forced"
                forced.mkdir(mode=0o700)
                return str(forced)

            monkeypatch.setattr(
                validation_run.tempfile,
                "mkdtemp",
                forced_mkdtemp,
            )
            result = manager._run_candidate_command(
                [
                    ".venv/bin/python",
                    "-m",
                    "compileall",
                    "fixture_module.py",
                ],
                timeout_seconds=30,
                cwd=str(candidate),
                command_index=command_index,
                command_artifacts_root=command_artifacts_root,
            )
            assert result == {
                "returncode": 125,
                "stdout": "",
                "stderr": "VALIDATION_COMMAND_ARTIFACT_INVALID",
                "error_code": "VALIDATION_COMMAND_ARTIFACT_INVALID",
            }
    finally:
        validation_run._VALIDATION_ENVIRONMENT_CONTEXT.reset(token)


def test_candidate_compileall_rejects_symlink_scratch_escape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _git_project(tmp_path)
    manager = MCPValidationRunManager(str(project))
    environment = _minimal_validation_environment(tmp_path, project)
    external_parent = tmp_path / "external-scratch-authority"
    external_parent.mkdir()

    def symlink_mkdtemp(prefix: str) -> str:
        escaped = external_parent / f"{prefix}escape"
        escaped.symlink_to(project, target_is_directory=True)
        return str(escaped)

    monkeypatch.setattr(
        validation_run.tempfile,
        "mkdtemp",
        symlink_mkdtemp,
    )
    token = validation_run._VALIDATION_ENVIRONMENT_CONTEXT.set(environment)
    try:
        result = manager._run_candidate_command(
            [".venv/bin/python", "-m", "compileall", "README.md"],
            timeout_seconds=30,
            cwd=str(project),
            command_index=30,
            command_artifacts_root=(
                project
                / ".colameta/runtime/validation-run-artifacts/run/command-artifacts"
            ),
        )
    finally:
        validation_run._VALIDATION_ENVIRONMENT_CONTEXT.reset(token)

    assert result["returncode"] == 125
    assert result["error_code"] == "VALIDATION_COMMAND_ARTIFACT_INVALID"
    assert project.is_dir()
    assert not any(external_parent.iterdir())


def test_candidate_compileall_rejects_scratch_containing_protected_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command_index = 31
    evidence_name = "validation_run_reverse_overlap"
    prefix = (
        f"colameta-validation-compileall-{evidence_name}-"
        f"{command_index}-"
    )
    forced_scratch = tmp_path / f"{prefix}ancestor"
    development_parent = forced_scratch / "development"
    candidate_parent = tmp_path / "candidate"
    development_parent.mkdir(parents=True)
    candidate_parent.mkdir()
    development = _git_project(development_parent)
    candidate = _git_project(candidate_parent)
    environment = _minimal_validation_environment(tmp_path, candidate)
    manager = MCPValidationRunManager(str(development))
    evidence_root = (
        development
        / ".colameta"
        / "runtime"
        / "validation-run-artifacts"
        / evidence_name
    )
    monkeypatch.setattr(
        validation_run.tempfile,
        "mkdtemp",
        lambda prefix: str(forced_scratch),
    )
    monkeypatch.setattr(
        manager,
        "_cleanup_compileall_scratch_root",
        lambda *_args, **_kwargs: False,
    )
    token = validation_run._VALIDATION_ENVIRONMENT_CONTEXT.set(environment)
    try:
        result = manager._run_candidate_command(
            [".venv/bin/python", "-m", "compileall", "README.md"],
            timeout_seconds=30,
            cwd=str(candidate),
            command_index=command_index,
            command_artifacts_root=evidence_root / "command-artifacts",
        )
    finally:
        validation_run._VALIDATION_ENVIRONMENT_CONTEXT.reset(token)

    assert result["returncode"] == 125
    assert result["error_code"] == "VALIDATION_COMMAND_ARTIFACT_INVALID"
    assert development.is_dir()


def test_full_compileall_under_real_evidence_root_seals_verified_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _git_project(tmp_path)
    module = project / "fixture_module.py"
    module.write_text("VALUE = 1\n", encoding="utf-8")
    (project / ".gitignore").write_text(
        ".venv\n__pycache__/\n*.pyc\n",
        encoding="utf-8",
    )
    _git(project, "add", "fixture_module.py", ".gitignore")
    _git(project, "commit", "-qm", "add compileall fixture")
    module.write_text("VALUE = 2\n", encoding="utf-8")
    manager = MCPValidationRunManager(str(project))
    command = [
        ".venv/bin/python",
        "-m",
        "compileall",
        "fixture_module.py",
    ]
    spec = {
        "argv": command,
        "timeout_seconds": 30,
        "continue_on_failure": False,
    }
    monkeypatch.setattr(
        manager,
        "_select_commands",
        lambda _scope, _target_files: (
            [command],
            [spec],
            "compileall",
            [],
            [
                {
                    "strategy": "compileall",
                    "lane": "candidate",
                    "files": ["fixture_module.py"],
                    "command_count": 1,
                }
            ],
            ["candidate"],
        ),
    )
    monkeypatch.setattr(
        validation_run,
        "prepare_validation_environment",
        lambda *, candidate_root, **_kwargs: _minimal_validation_environment(
            tmp_path,
            Path(candidate_root),
        ),
    )
    monkeypatch.setattr(
        manager,
        "_resolve_frozen_toolchain_asset",
        lambda: {
            "ok": True,
            "path": tmp_path / "unused-frozen-asset.whl",
            "filename": "unused-frozen-asset.whl",
            "sha256": "1" * 64,
            "distribution": "cryptography",
            "version": "50.0.0",
        },
    )

    preview = manager.preview({"scope": "full"})
    started = manager.run({"preview_id": preview["preview_id"]})
    final = _terminal_status(manager, started["run_id"])

    assert final["status"] == "passed"
    assert final["integrity_classification"] == "verified"
    assert final["external_evidence"] == {
        "evidence_contract_version": 2,
        "manifest_verified": True,
        "projection_receipt_verified": True,
        "source_snapshot_verified": True,
        "terminal_result_verified": True,
        "command_artifacts_verified": True,
    }
    command_result = final["command_results"][0]
    assert command_result["returncode"] == 0
    assert command_result["compileall_artifact"]["pyc_count"] > 0
    assert command_result["compileall_artifact"][
        "scratch_root_class"
    ] == "repository_external_ephemeral"
    assert command_result["compileall_artifact"]["cleanup_complete"] is True
    assert manager._candidate_bytecode_contamination_count(project) == 0
    evidence_root = manager._run_evidence_root(started["run_id"])
    manifest = json.loads(
        (evidence_root / "external-evidence-manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["command_artifact_count"] == 1
    assert manifest["command_artifacts"][0]["file_sha256"]
    assert not any(
        path.is_dir() and path.name == "pycache"
        for path in evidence_root.rglob("*")
    )


def test_candidate_compileall_fails_closed_without_cleaning_seeded_bytecode(
    tmp_path: Path,
) -> None:
    project = _git_project(tmp_path)
    module = project / "fixture_module.py"
    module.write_text("VALUE = 1\n", encoding="utf-8")
    (project / ".gitignore").write_text(
        ".venv\n__pycache__/\n*.pyc\n",
        encoding="utf-8",
    )
    _git(project, "add", "fixture_module.py", ".gitignore")
    _git(project, "commit", "-qm", "add contamination fixture")
    seeded = project / "__pycache__" / "seeded.cpython-312.pyc"
    seeded.parent.mkdir()
    seeded.write_bytes(b"manually seeded candidate bytecode")
    manager = MCPValidationRunManager(str(project))
    environment = _minimal_validation_environment(tmp_path, project)
    token = validation_run._VALIDATION_ENVIRONMENT_CONTEXT.set(environment)
    try:
        result = manager._run_candidate_command(
            [".venv/bin/python", "-m", "compileall", "fixture_module.py"],
            timeout_seconds=30,
            cwd=str(project),
            command_index=9,
            command_artifacts_root=tmp_path / "command-artifacts",
        )
    finally:
        validation_run._VALIDATION_ENVIRONMENT_CONTEXT.reset(token)

    assert result["returncode"] == 125
    assert result["error_code"] == "COMPILEALL_BYTECODE_ISOLATION_FAILED"
    assert result["compileall_artifact"]["candidate_contamination_count"] > 0
    assert result["compileall_artifact"]["cleanup_complete"] is True
    assert seeded.read_bytes() == b"manually seeded candidate bytecode"


@pytest.mark.parametrize(
    "command",
    [
        [".venv/bin/python", "some_script_named_compileall.py"],
        [".venv/bin/python", "-c", "print('compileall')"],
        ["echo", "-m", "compileall"],
    ],
)
def test_compileall_artifact_privilege_requires_exact_module_invocation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: list[str],
) -> None:
    project = _git_project(tmp_path)
    manager = MCPValidationRunManager(str(project))
    environment = _minimal_validation_environment(tmp_path, project)
    observed_environment: dict[str, str] = {}

    def fake_run(_command, **kwargs):
        observed_environment.update(kwargs["env"])
        return subprocess.CompletedProcess(_command, 0, stdout="", stderr="")

    monkeypatch.setattr(validation_run.subprocess, "run", fake_run)
    token = validation_run._VALIDATION_ENVIRONMENT_CONTEXT.set(environment)
    try:
        result = manager._run_candidate_command(
            command,
            timeout_seconds=30,
            cwd=str(project),
            command_index=7,
            command_artifacts_root=tmp_path / "command-artifacts",
        )
    finally:
        validation_run._VALIDATION_ENVIRONMENT_CONTEXT.reset(token)

    assert result["returncode"] == 0
    assert "compileall_artifact" not in result
    assert "PYTHONPYCACHEPREFIX" not in observed_environment
    assert not (tmp_path / "command-artifacts").exists()


def test_worker_exception_writes_digest_verified_failure_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _git_project(tmp_path)
    manager = MCPValidationRunManager(str(project))
    preview = manager.preview(
        {"scope": "target_files", "target_files": ["README.md"]}
    )
    artifact = manager._read_preview(preview["preview_id"])
    assert artifact is not None
    command_specs = artifact["command_specs"]
    commands = artifact["commands"]
    started_at = validation_run._utc_now()
    run_id = "validation_run_worker_failure"

    def fail_worker(*_args, **_kwargs):
        raise RuntimeError("bounded worker failure")

    monkeypatch.setattr(manager, "_execute_run_worker", fail_worker)
    manager._prepare_run_evidence(
        run_id,
        preview["preview_id"],
        artifact,
    )
    manager._execute_run_worker_safe(
        run_id,
        preview["preview_id"],
        artifact,
        command_specs,
        commands,
        started_at,
    )

    status = manager.status({"run_id": run_id})
    assert status["ok"] is True
    assert status["status"] == "failed"
    assert status["passed"] is False
    assert status["integrity_classification"] == "verified"
    assert status["command_results"][0]["error_code"] == (
        "VALIDATION_RUN_FAILED"
    )
    evidence_root = manager._run_evidence_root(run_id)
    manifest = json.loads(
        (evidence_root / "external-evidence-manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["command_artifact_count"] == 1
    assert len(manifest["command_artifacts"]) == 1
    assert manifest["command_artifacts"][0]["file_sha256"]
    persisted, read_error = manager._read_verified_run_result(run_id)
    assert read_error is None
    assert persisted is not None
    assert persisted["validation_result_sha256"] == (
        validation_run.canonical_validation_result_sha256(persisted)
    )


def test_full_preview_binds_exact_candidate_overlay_and_snapshot(
    tmp_path: Path,
) -> None:
    project = _git_project(tmp_path)
    pyproject = project / "pyproject.toml"
    pyproject.write_text("[project]\nname = 'fixture'\n", encoding="utf-8")
    manager = MCPValidationRunManager(str(project))

    preview = manager.preview({"scope": "full"})
    assert preview["ok"] is True
    artifact = manager._read_preview(preview["preview_id"])
    assert artifact is not None
    assert artifact["candidate_delta_mode"] == "exact_worktree_overlay"
    assert artifact["candidate_identity"]["source_binding_count"] == 1
    assert artifact["candidate_identity"]["pyproject_sha256"] == (
        hashlib.sha256(pyproject.read_bytes()).hexdigest()
    )
    assert artifact["candidate_snapshot"]["snapshot_sha256"]
    snapshot_root = Path(manager._previews_root) / preview["preview_id"]
    assert (snapshot_root / "candidate-source-snapshot" / "snapshot.json").is_file()
    assert (
        (snapshot_root / "candidate-source-snapshot").stat().st_mode & 0o777
    ) == 0o700


def test_full_execution_uses_candidate_root_and_retains_projection_failure_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _git_project(tmp_path)
    changed = project / "candidate.py"
    changed.write_text("VALUE = 1\n", encoding="utf-8")
    manager = MCPValidationRunManager(str(project))
    _patch_git_diff_only_preview(manager, monkeypatch)
    observed_cwds: list[str] = []

    def failed_command(*_args, **kwargs):
        observed_cwds.append(str(kwargs["cwd"]))
        return {
            "returncode": 1,
            "stdout": "",
            "stderr": "candidate projection failure fixture",
            "error_code": "VALIDATION_COMMAND_FAILED",
        }

    monkeypatch.setattr(manager, "_run_command", failed_command)
    preview = manager.preview({"scope": "full"})
    started = manager.run({"preview_id": preview["preview_id"]})
    final = _terminal_status(manager, started["run_id"])

    assert final["status"] == "failed"
    assert observed_cwds
    assert all(Path(cwd).resolve() != project.resolve() for cwd in observed_cwds)
    projection = final["candidate_projection"]
    assert projection["candidate"]["root_class"] == "isolated_detached_worktree"
    assert projection["execution"]["cwd_class"] == "exact_candidate_root"
    assert projection["artifacts"]["retention_verified"] is True
    evidence_root = manager._run_evidence_root(started["run_id"])
    assert (evidence_root / "candidate-projection-receipt.json").is_file()
    assert (evidence_root / "candidate-source-snapshot").is_dir()
    assert (evidence_root / "command-artifacts").is_dir()
    assert (evidence_root / "terminal-result.json").is_file()


def test_projection_fields_are_digest_bound_and_status_is_fail_closed(
    tmp_path: Path,
) -> None:
    project = _git_project(tmp_path)
    manager = MCPValidationRunManager(str(project))
    preview = manager.preview(
        {"scope": "target_files", "target_files": ["README.md"]}
    )
    started = manager.run({"preview_id": preview["preview_id"]})
    final = _terminal_status(manager, started["run_id"])
    assert final["candidate_projection"]["source_snapshot"]["snapshot_sha256"]

    path = Path(manager._run_result_path(started["run_id"]))
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["candidate_projection"]["candidate"]["file_map_sha256"] = "0" * 64
    path.write_text(json.dumps(payload), encoding="utf-8")

    rejected = manager.status({"run_id": started["run_id"]})
    assert rejected["ok"] is False
    assert rejected["error_code"] == "RUN_RESULT_INVALID"


def _sealed_external_evidence_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[MCPValidationRunManager, str, Path, dict]:
    project = _git_project(tmp_path)
    changed = project / "candidate.py"
    changed.write_text("VALUE = 1\n", encoding="utf-8")
    manager = MCPValidationRunManager(str(project))
    _patch_git_diff_only_preview(manager, monkeypatch)
    preview = manager.preview({"scope": "full"})
    started = manager.run({"preview_id": preview["preview_id"]})
    final = _terminal_status(manager, started["run_id"])
    assert final["integrity_classification"] == "verified"
    assert final["external_evidence"] == {
        "evidence_contract_version": 2,
        "manifest_verified": True,
        "projection_receipt_verified": True,
        "source_snapshot_verified": True,
        "terminal_result_verified": True,
        "command_artifacts_verified": True,
    }
    return (
        manager,
        started["run_id"],
        manager._run_evidence_root(started["run_id"]),
        final,
    )


def _assert_external_tamper_rejected(
    manager: MCPValidationRunManager,
    run_id: str,
) -> None:
    rejected = manager.status({"run_id": run_id})
    assert rejected["ok"] is False
    assert rejected["error_code"] == "RUN_RESULT_INVALID"


def test_status_rejects_external_projection_receipt_tamper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, run_id, evidence_root, _final = _sealed_external_evidence_run(
        tmp_path, monkeypatch
    )
    receipt = evidence_root / "candidate-projection-receipt.json"
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    payload["preview"]["HEAD"] = "0" * 40
    receipt.write_text(json.dumps(payload), encoding="utf-8")
    _assert_external_tamper_rejected(manager, run_id)


def test_status_rejects_external_projection_receipt_deletion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, run_id, evidence_root, _final = _sealed_external_evidence_run(
        tmp_path, monkeypatch
    )
    (evidence_root / "candidate-projection-receipt.json").unlink()
    _assert_external_tamper_rejected(manager, run_id)


def test_status_rejects_external_command_artifact_tamper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, run_id, evidence_root, _final = _sealed_external_evidence_run(
        tmp_path, monkeypatch
    )
    artifact = evidence_root / "command-artifacts" / "0000.json"
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    payload["returncode"] = 99
    artifact.write_text(json.dumps(payload), encoding="utf-8")
    _assert_external_tamper_rejected(manager, run_id)


def test_status_rejects_external_command_artifact_deletion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, run_id, evidence_root, _final = _sealed_external_evidence_run(
        tmp_path, monkeypatch
    )
    (evidence_root / "command-artifacts" / "0000.json").unlink()
    _assert_external_tamper_rejected(manager, run_id)


def test_status_rejects_source_snapshot_file_tamper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, run_id, evidence_root, _final = _sealed_external_evidence_run(
        tmp_path, monkeypatch
    )
    snapshot_file = next(
        (evidence_root / "candidate-source-snapshot" / "files").iterdir()
    )
    snapshot_file.write_bytes(b"tampered source snapshot")
    _assert_external_tamper_rejected(manager, run_id)


def test_status_rejects_source_snapshot_file_deletion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, run_id, evidence_root, _final = _sealed_external_evidence_run(
        tmp_path, monkeypatch
    )
    snapshot_file = next(
        (evidence_root / "candidate-source-snapshot" / "files").iterdir()
    )
    snapshot_file.unlink()
    _assert_external_tamper_rejected(manager, run_id)


def test_source_snapshot_verifier_rejects_identity_mode_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, run_id, evidence_root, _final = _sealed_external_evidence_run(
        tmp_path, monkeypatch
    )
    terminal = json.loads(
        Path(manager._run_result_path(run_id)).read_text(encoding="utf-8")
    )
    evidence_manifest = json.loads(
        (evidence_root / "external-evidence-manifest.json").read_text(
            encoding="utf-8"
        )
    )
    snapshot_path = evidence_root / "candidate-source-snapshot" / "snapshot.json"
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    snapshot["bindings"][0]["mode"] ^= 0o100
    snapshot["snapshot_sha256"] = (
        validation_run.canonical_manifest_validation_sha256(
            {key: value for key, value in snapshot.items() if key != "snapshot_sha256"}
        )
    )
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    source_binding = dict(evidence_manifest["source_snapshot"])
    source_binding["manifest_sha256"] = hashlib.sha256(
        snapshot_path.read_bytes()
    ).hexdigest()

    assert manager._verify_external_source_snapshot(
        evidence_root=evidence_root,
        source_binding=source_binding,
        candidate_identity=terminal["candidate_identity"],
    ) is False


def test_status_rejects_external_evidence_manifest_tamper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, run_id, evidence_root, _final = _sealed_external_evidence_run(
        tmp_path, monkeypatch
    )
    manifest_path = evidence_root / "external-evidence-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["command_artifact_count"] += 1
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    _assert_external_tamper_rejected(manager, run_id)


def test_status_rejects_external_terminal_result_tamper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, run_id, evidence_root, _final = _sealed_external_evidence_run(
        tmp_path, monkeypatch
    )
    terminal_path = evidence_root / "terminal-result.json"
    terminal = json.loads(terminal_path.read_text(encoding="utf-8"))
    terminal["passed"] = not terminal["passed"]
    terminal_path.write_text(json.dumps(terminal), encoding="utf-8")
    _assert_external_tamper_rejected(manager, run_id)


def test_status_rejects_governed_manifest_path_escape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, run_id, _evidence_root, _final = _sealed_external_evidence_run(
        tmp_path, monkeypatch
    )
    path = Path(manager._run_result_path(run_id))
    terminal = json.loads(path.read_text(encoding="utf-8"))
    terminal["external_evidence_binding"][
        "evidence_manifest_relative_path"
    ] = "../external-evidence-manifest.json"
    terminal["validation_result_sha256"] = (
        validation_run.canonical_validation_result_sha256(terminal)
    )
    manager._write_restricted_json(path, terminal)
    _assert_external_tamper_rejected(manager, run_id)


def test_status_rejects_governed_manifest_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, run_id, evidence_root, _final = _sealed_external_evidence_run(
        tmp_path, monkeypatch
    )
    manifest = evidence_root / "external-evidence-manifest.json"
    retained = evidence_root / "retained-manifest.json"
    manifest.rename(retained)
    manifest.symlink_to(retained.name)
    _assert_external_tamper_rejected(manager, run_id)


def test_external_manifest_hashes_every_command_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _manager, _run_id, evidence_root, final = _sealed_external_evidence_run(
        tmp_path, monkeypatch
    )
    manifest = json.loads(
        (evidence_root / "external-evidence-manifest.json").read_text(
            encoding="utf-8"
        )
    )
    commands = manifest["command_artifacts"]
    assert manifest["command_artifact_count"] == len(commands) == 1
    assert final["candidate_projection"]["artifacts"][
        "command_artifact_count"
    ] == 1
    assert all(entry["file_sha256"] for entry in commands)
    assert all(entry["command_artifact_sha256"] for entry in commands)
    receipt = json.loads(
        (evidence_root / "candidate-projection-receipt.json").read_text(
            encoding="utf-8"
        )
    )
    assert receipt["commands"] == commands
    internal_terminal = Path(
        _manager._run_result_path(_run_id)
    )
    external_terminal = evidence_root / "terminal-result.json"
    assert internal_terminal.read_bytes() == external_terminal.read_bytes()
    manifest_core = _manager._external_evidence_manifest_core(manifest)
    assert manifest["evidence_manifest_core_sha256"] == (
        validation_run.canonical_manifest_validation_sha256(manifest_core)
    )
    terminal = json.loads(internal_terminal.read_text(encoding="utf-8"))
    assert terminal["external_evidence_binding"][
        "evidence_manifest_core_sha256"
    ] == manifest["evidence_manifest_core_sha256"]
    unsigned_manifest = {
        key: value
        for key, value in manifest.items()
        if key != "manifest_receipt_sha256"
    }
    assert manifest["manifest_receipt_sha256"] == (
        validation_run.canonical_manifest_validation_sha256(unsigned_manifest)
    )


def test_status_rejects_missing_materialized_environment_identity_field(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, run_id, _evidence_root, _final = _sealed_external_evidence_run(
        tmp_path, monkeypatch
    )
    path = Path(manager._run_result_path(run_id))
    terminal = json.loads(path.read_text(encoding="utf-8"))
    projection = terminal["candidate_projection"]
    projection["execution_environment"] = {
        "state": "materialized",
        "python_implementation": "CPython",
        "python_version": "3.12.3",
        "python_cache_tag": "cpython-312",
        "executable_sha256": "1" * 64,
    }
    projection["projection_payload_sha256"] = (
        validation_run.canonical_manifest_validation_sha256(
            {
                key: value
                for key, value in projection.items()
                if key != "projection_payload_sha256"
            }
        )
    )
    terminal["validation_result_sha256"] = (
        validation_run.canonical_validation_result_sha256(terminal)
    )
    manager._write_restricted_json(path, terminal)
    assert manager._candidate_projection_is_valid(terminal) is False
    _assert_external_tamper_rejected(manager, run_id)


def test_environment_identity_changes_with_python_and_package_versions() -> None:
    package_set, package_sha256 = (
        toolchain_environment.canonical_installed_distribution_set(
            [
                {"canonical_name": "package-b", "version": "2.0"},
                {"canonical_name": "package-a", "version": "1.0"},
            ]
        )
    )
    reordered_set, reordered_sha256 = (
        toolchain_environment.canonical_installed_distribution_set(
            [
                {"canonical_name": "package-a", "version": "1.0"},
                {"canonical_name": "package-b", "version": "2.0"},
            ]
        )
    )
    assert package_set == reordered_set
    assert package_sha256 == reordered_sha256
    _, python_312_identity = toolchain_environment.canonical_environment_identity(
        executable_sha256="1" * 64,
        python_implementation="CPython",
        python_version="3.12.9",
        python_cache_tag="cpython-312",
        package_set_sha256=package_sha256,
    )
    _, python_313_identity = toolchain_environment.canonical_environment_identity(
        executable_sha256="1" * 64,
        python_implementation="CPython",
        python_version="3.13.2",
        python_cache_tag="cpython-313",
        package_set_sha256=package_sha256,
    )
    assert python_312_identity != python_313_identity

    _changed_set, changed_package_sha256 = (
        toolchain_environment.canonical_installed_distribution_set(
            [{"canonical_name": "package-a", "version": "1.1"}]
        )
    )
    _, changed_package_identity = toolchain_environment.canonical_environment_identity(
        executable_sha256="1" * 64,
        python_implementation="CPython",
        python_version="3.12.9",
        python_cache_tag="cpython-312",
        package_set_sha256=changed_package_sha256,
    )
    assert changed_package_sha256 != package_sha256
    assert changed_package_identity != python_312_identity


def test_distribution_name_normalization_uses_packaging_authority() -> None:
    package_set, package_sha256 = (
        toolchain_environment.canonical_installed_distribution_set(
            [
                {"canonical_name": "PyYAML", "version": "6.0.3"},
                {"canonical_name": "pyyaml", "version": "6.0.3"},
                {"canonical_name": "py_yaml", "version": "1.0"},
            ]
        )
    )
    assert package_set["distributions"] == [
        {"name": "py-yaml", "version": "1.0"},
        {"name": "pyyaml", "version": "6.0.3"},
    ]
    assert package_sha256
    with pytest.raises(
        toolchain_environment.ValidationEnvironmentError,
        match="conflicting distribution versions",
    ):
        toolchain_environment.canonical_installed_distribution_set(
            [
                {"canonical_name": "PyYAML", "version": "6.0.2"},
                {"canonical_name": "pyyaml", "version": "6.0.3"},
            ]
        )


def test_target_venv_probe_binds_python_and_package_set(tmp_path: Path) -> None:
    candidate = Path.cwd().resolve()
    validation_venv = Path(sys.prefix).resolve()
    environment = toolchain_environment.build_validation_subprocess_environment(
        candidate_root=candidate,
        validation_venv=validation_venv,
        parent_environment=os.environ,
        temp_root=tmp_path,
    )
    identity = toolchain_environment._probe_installed_environment_identity(
        python_executable=Path(sys.executable),
        validation_venv=validation_venv,
        candidate_root=candidate,
        environment=environment,
    )
    assert identity["python_implementation"]
    assert identity["python_version"]
    assert identity["python_cache_tag"]
    assert identity["package_set_sha256"]
    assert identity["distribution_count"] > 0
    assert identity["environment_identity_sha256"]


@pytest.mark.parametrize(
    ("error_code", "stderr"),
    [
        ("VALIDATION_COMMAND_FAILED", "bounded command failure"),
        (
            "COMMAND_PREIMPORT_ATTESTATION_FAILED",
            "command_preimport_attestation:full_pytest",
        ),
    ],
)
def test_command_failures_write_digest_verified_terminal_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error_code: str,
    stderr: str,
) -> None:
    project = _git_project(tmp_path)
    manager = MCPValidationRunManager(str(project))

    def failed_command(*_args, **_kwargs):
        return {
            "returncode": 1,
            "stdout": "",
            "stderr": stderr,
            "error_code": error_code,
        }

    monkeypatch.setattr(manager, "_run_command", failed_command)
    preview = manager.preview(
        {"scope": "target_files", "target_files": ["README.md"]}
    )
    started = manager.run({"preview_id": preview["preview_id"]})
    final = _terminal_status(manager, started["run_id"])

    assert final["ok"] is True
    assert final["status"] == "failed"
    assert final["passed"] is False
    assert final["integrity_classification"] == "verified"
    assert final["command_results"][0]["error_code"] == error_code
    assert stderr in final["command_results"][0]["stderr"]


def test_terminal_result_tampering_remains_fail_closed(tmp_path: Path) -> None:
    project = _git_project(tmp_path)
    manager = MCPValidationRunManager(str(project))
    preview = manager.preview(
        {"scope": "target_files", "target_files": ["README.md"]}
    )
    started = manager.run({"preview_id": preview["preview_id"]})
    final = _terminal_status(manager, started["run_id"])
    assert final["ok"] is True
    path = Path(manager._run_result_path(started["run_id"]))
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["passed"] = not payload["passed"]
    path.write_text(json.dumps(payload), encoding="utf-8")

    rejected = manager.status({"run_id": started["run_id"]})
    assert rejected["ok"] is False
    assert rejected["error_code"] == "RUN_RESULT_INVALID"
