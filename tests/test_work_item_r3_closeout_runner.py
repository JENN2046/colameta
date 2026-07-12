from __future__ import annotations

import json
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

import runner.work_item_governance.toolchain_binding as toolchain_binding
import scripts.work_item_r3_closeout as closeout_script
import scripts.work_item_r3_trusted_launcher as trusted_launcher
from runner.work_item_governance.canonical import canonical_sha256, sha256_file
from runner.work_item_governance.errors import WorkItemGovernanceError
from runner.work_item_governance.toolchain_binding import measure_closeout_toolchain
from scripts.work_item_r3_closeout import (
    bundle_access_check,
    bundle_manifest,
    protected_assets_check,
    run_command as _run_command,
    verify_receipt,
)


_TEST_TOOLCHAIN = {
    "schema_version": "work_item_r3_closeout_toolchain.test",
    "environment_root_sha256": "a" * 64,
}


def _test_startup_attestation(project_root: Path) -> dict[str, object]:
    record: dict[str, object] = {
        "schema_version": "work_item_r3_preimport_attestation.v1",
        "accepted": True,
        "project_root": project_root.resolve().as_posix(),
        "launcher_relative_path": "scripts/work_item_r3_trusted_launcher.py",
        "launcher_sha256": "a" * 64,
        "python_executable": {"sha256": "b" * 64},
        "python_flags": {
            "isolated": True,
            "no_site": True,
            "dont_write_bytecode": True,
            "safe_path": True,
        },
        "startup_authority_environment": [],
        "source": {"commit": "c" * 40, "tree": "d" * 40},
        "environment": {"environment_tree_sha256": "e" * 64},
    }
    record["attestation_sha256"] = canonical_sha256(record)
    return record


def run_command(*, name: str, output: Path, command: list[str]) -> int:
    return _run_command(
        name=name,
        output=output,
        command=command,
        startup_attestation=_test_startup_attestation(Path.cwd()),
    )


@pytest.fixture(autouse=True)
def _stub_exact_project_toolchain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        closeout_script,
        "measure_closeout_toolchain",
        lambda _project_root: dict(_TEST_TOOLCHAIN),
    )


def _initialize_clean_repository(root: Path) -> Path:
    repository = root / "repository"
    repository.mkdir()
    subprocess.run(["git", "init", "-q", repository], check=True)
    subprocess.run(
        ["git", "-C", repository, "config", "user.email", "r3-runner@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", repository, "config", "user.name", "R3 Runner"],
        check=True,
    )
    (repository / "tracked.txt").write_text("tracked\n", encoding="utf-8")
    subprocess.run(["git", "-C", repository, "add", "tracked.txt"], check=True)
    subprocess.run(["git", "-C", repository, "commit", "-q", "-m", "fixture"], check=True)
    return repository


def test_run_command_retains_exact_completed_process_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _initialize_clean_repository(tmp_path)
    monkeypatch.chdir(repository)
    output = tmp_path / "command.json"

    result = run_command(
        name="full_pytest",
        output=output,
        command=[sys.executable, "-c", "print('1 passed')"],
    )

    evidence = json.loads(output.read_text(encoding="utf-8"))
    assert result == 0
    assert evidence["schema_version"] == "work_item_closeout_command_evidence.v2"
    assert evidence["preimport_attestation"]["accepted"] is True
    assert evidence["argv"] == [sys.executable, "-c", "print('1 passed')"]
    assert evidence["exit_code"] == 0
    assert evidence["process_exit_code"] == 0
    assert evidence["passed"] is True
    assert evidence["stdout"] == "1 passed\n"
    expected_commit = subprocess.run(
        ["git", "-C", repository, "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    expected_tree = subprocess.run(
        ["git", "-C", repository, "rev-parse", "HEAD^{tree}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    for source in (evidence["source_before"], evidence["source_after"]):
        assert source["commit"] == expected_commit
        assert source["tree"] == expected_tree
        assert source["requested_checkout_root"] == repository.resolve().as_posix()
        assert source["candidate_clean"] is True
        assert source["tracked_changes"] == []
        assert source["staged_changes"] == []
        assert source["untracked_changes"] == []
        assert source["assume_unchanged_paths"] == []
        assert source["skip_worktree_paths"] == []
        assert source["ignored_execution_overlays"] == []
        assert source["untracked_execution_overlays"] == []
        assert source["object_mismatches"] == []
        assert source["git_object_format"] == "sha1"
        assert len(source["git_object_manifest_digest"]) == 64
        assert source["git_executable"]["resolved_path"] == "/usr/bin/git"
        assert source["git_executable"]["sha256"] == sha256_file(Path("/usr/bin/git"))
        assert source["git_executable"]["root_owned"] is True
        assert source["git_executable"]["group_or_other_writable"] is False
    executable = Path(sys.executable).resolve()
    assert evidence["executable"] == {
        "requested": sys.executable,
        "launcher_path": Path(sys.executable).absolute().as_posix(),
        "launcher_sha256": sha256_file(Path(sys.executable)),
        "launcher_sha256_after": sha256_file(Path(sys.executable)),
        "launcher_symlink_target": os.readlink(sys.executable),
        "launcher_symlink_target_after": os.readlink(sys.executable),
        "resolved_path": executable.as_posix(),
        "resolved_sha256": sha256_file(executable),
        "resolved_sha256_after": sha256_file(executable),
        "unchanged": True,
    }
    assert evidence["toolchain"] == {
        "before": _TEST_TOOLCHAIN,
        "after": _TEST_TOOLCHAIN,
        "error_before": None,
        "error_after": None,
        "unchanged": True,
    }


def test_run_command_clamps_wall_clock_rollback_with_monotonic_duration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _initialize_clean_repository(tmp_path)
    monkeypatch.chdir(repository)
    timestamps = iter(("2026-07-12T00:00:01Z", "2026-07-12T00:00:00Z"))
    monotonic = iter((100, 350))
    monkeypatch.setattr(closeout_script, "_timestamp", lambda: next(timestamps))
    monkeypatch.setattr(closeout_script.time, "monotonic_ns", lambda: next(monotonic))
    output = tmp_path / "clock-rollback.json"

    assert run_command(
        name="clock_rollback",
        output=output,
        command=[sys.executable, "-c", "print('complete')"],
    ) == 0

    evidence = json.loads(output.read_text(encoding="utf-8"))
    assert evidence["started_at"] == "2026-07-12T00:00:01Z"
    assert evidence["ended_at"] == evidence["started_at"]
    assert evidence["monotonic_duration_ns"] == 250
    assert evidence["wall_clock_rollback_clamped"] is True


def test_run_command_sanitizes_python_and_pytest_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _initialize_clean_repository(tmp_path)
    monkeypatch.chdir(repository)
    removed = (
        "PYTEST_ADDOPTS",
        "PYTEST_PLUGINS",
        "PYTHONPATH",
        "PYTHONSTARTUP",
        "PYTHONINSPECT",
        "COVERAGE_PROCESS_START",
    )
    for key in removed:
        monkeypatch.setenv(key, "secret-or-injected-value")
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "malicious")
    monkeypatch.setenv("PYTHONHASHSEED", "random")
    authority_environment = (
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_CONFIG_GLOBAL",
        "LD_PRELOAD",
        "LD_LIBRARY_PATH",
        "DYLD_INSERT_LIBRARIES",
        "PYTHONHOME",
        "PYTHONUSERBASE",
    )
    for key in authority_environment:
        monkeypatch.setenv(key, "secret-or-injected-authority")
    output = tmp_path / "environment-command.json"
    script = (
        "import json,os; "
        f"print(json.dumps({{key: os.environ.get(key) for key in {removed!r}}} | "
        f"{{key: os.environ.get(key) for key in {authority_environment!r}}} | "
        "{'PYTEST_DISABLE_PLUGIN_AUTOLOAD': os.environ.get('PYTEST_DISABLE_PLUGIN_AUTOLOAD'), "
        "'PYTHONHASHSEED': os.environ.get('PYTHONHASHSEED')}))"
    )

    assert run_command(
        name="environment_check",
        output=output,
        command=[sys.executable, "-c", script],
    ) == 0

    evidence = json.loads(output.read_text(encoding="utf-8"))
    observed = json.loads(evidence["stdout"])
    assert all(observed[key] is None for key in removed)
    assert all(
        observed[key] is None
        for key in authority_environment
        if key != "GIT_CONFIG_GLOBAL"
    )
    assert observed["GIT_CONFIG_GLOBAL"] == "/dev/null"
    assert observed["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"
    assert observed["PYTHONHASHSEED"] == "0"
    policy = evidence["environment_policy"]
    assert policy["removed_keys"] == {key: True for key in removed}
    assert policy["forced_values"] == {
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "PYTHONHASHSEED": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    assert set(policy["authority_removed_keys"]) >= set(authority_environment)
    assert policy["git_authority_environment_scrubbed"] is True
    assert policy["loader_authority_environment_scrubbed"] is True
    assert "secret-or-injected-value" not in output.read_text(encoding="utf-8")
    assert "secret-or-injected-authority" not in output.read_text(encoding="utf-8")


def test_run_command_executes_lexical_virtualenv_python_launcher(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _initialize_clean_repository(tmp_path)
    monkeypatch.chdir(repository)
    output = tmp_path / "venv-launcher.json"

    assert run_command(
        name="venv_launcher",
        output=output,
        command=[
            sys.executable,
            "-c",
            "import json,pytest,sys; print(json.dumps({'prefix':sys.prefix,'pytest':pytest.__version__}))",
        ],
    ) == 0

    evidence = json.loads(output.read_text(encoding="utf-8"))
    observed = json.loads(evidence["stdout"])
    assert Path(observed["prefix"]).resolve() == Path(sys.prefix).resolve()
    assert observed["pytest"] == pytest.__version__
    assert evidence["executable"]["launcher_path"] == Path(sys.executable).as_posix()


def test_run_command_ignores_hostile_git_dir_and_work_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _initialize_clean_repository(tmp_path)
    attacker_root = tmp_path / "attacker"
    attacker_root.mkdir()
    attacker = _initialize_clean_repository(attacker_root)
    monkeypatch.chdir(repository)
    monkeypatch.setenv("GIT_DIR", str(attacker / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(attacker))
    output = tmp_path / "hostile-git-command.json"

    assert run_command(
        name="hostile_git_environment",
        output=output,
        command=[sys.executable, "-c", "print('trusted checkout')"],
    ) == 0

    evidence = json.loads(output.read_text(encoding="utf-8"))
    expected_commit = subprocess.run(
        ["git", "-C", repository, "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert evidence["source_before"]["repository_root"] == repository.as_posix()
    assert evidence["source_before"]["commit"] == expected_commit
    assert "GIT_DIR" in evidence["environment_policy"]["authority_removed_keys"]
    assert "GIT_WORK_TREE" in evidence["environment_policy"]["authority_removed_keys"]
    assert attacker.as_posix() not in output.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("flag", "field"),
    (
        ("--assume-unchanged", "assume_unchanged_paths"),
        ("--skip-worktree", "skip_worktree_paths"),
    ),
)
def test_run_command_rejects_suppressed_index_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    flag: str,
    field: str,
) -> None:
    repository = _initialize_clean_repository(tmp_path)
    subprocess.run(
        ["git", "-C", repository, "update-index", flag, "tracked.txt"],
        check=True,
    )
    monkeypatch.chdir(repository)
    output = tmp_path / f"{field}.json"

    assert run_command(
        name="suppressed_index_path",
        output=output,
        command=[sys.executable, "-c", "print('process passed')"],
    ) != 0

    evidence = json.loads(output.read_text(encoding="utf-8"))
    assert evidence["process_exit_code"] == 0
    assert evidence["passed"] is False
    assert evidence["source_before"]["candidate_clean"] is False
    assert evidence["source_before"][field] == ["tracked.txt"]


def test_run_command_rejects_ignored_conftest_overlay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _initialize_clean_repository(tmp_path)
    (repository / ".gitignore").write_text("/conftest.py\n", encoding="utf-8")
    subprocess.run(["git", "-C", repository, "add", ".gitignore"], check=True)
    subprocess.run(
        ["git", "-C", repository, "commit", "-qm", "ignore overlay"],
        check=True,
    )
    (repository / "conftest.py").write_text("pytest_plugins = []\n", encoding="utf-8")
    monkeypatch.chdir(repository)
    output = tmp_path / "ignored-conftest.json"

    assert run_command(
        name="ignored_conftest",
        output=output,
        command=[sys.executable, "-c", "print('process passed')"],
    ) != 0

    evidence = json.loads(output.read_text(encoding="utf-8"))
    assert evidence["process_exit_code"] == 0
    assert evidence["source_before"]["candidate_clean"] is False
    assert evidence["source_before"]["ignored_execution_overlays"] == ["conftest.py"]


def test_run_command_requires_requested_checkout_to_be_repository_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _initialize_clean_repository(tmp_path)
    nested = repository / "nested"
    nested.mkdir()
    monkeypatch.chdir(nested)
    output = tmp_path / "nested-checkout.json"

    assert run_command(
        name="nested_checkout",
        output=output,
        command=[sys.executable, "-c", "print('process passed')"],
    ) != 0

    evidence = json.loads(output.read_text(encoding="utf-8"))
    assert evidence["process_exit_code"] == 0
    assert evidence["passed"] is False
    assert evidence["source_before"]["candidate_clean"] is False
    assert evidence["source_before"]["inspection_errors"] == [
        "trusted_git_checkout:WorkItemGovernanceError"
    ]


def test_run_command_fails_evidence_when_candidate_is_dirty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _initialize_clean_repository(tmp_path)
    monkeypatch.chdir(repository)
    (repository / "tracked.txt").write_text("dirty\n", encoding="utf-8")
    output = tmp_path / "dirty-command.json"

    result = run_command(
        name="dirty_candidate",
        output=output,
        command=[sys.executable, "-c", "print('process passed')"],
    )

    evidence = json.loads(output.read_text(encoding="utf-8"))
    assert result != 0
    assert evidence["process_exit_code"] == 0
    assert evidence["exit_code"] != 0
    assert evidence["passed"] is False
    assert evidence["source_before"]["candidate_clean"] is False
    assert evidence["source_before"]["tracked_changes"] == ["tracked.txt"]


def test_run_command_allows_only_the_exact_protected_asset_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _initialize_clean_repository(tmp_path)
    monkeypatch.chdir(repository)
    (repository / "AGENTS.md").write_text("protected user change\n", encoding="utf-8")
    output = tmp_path / "protected-command.json"

    assert run_command(
        name="protected_asset_candidate",
        output=output,
        command=[sys.executable, "-c", "print('process passed')"],
    ) == 0

    evidence = json.loads(output.read_text(encoding="utf-8"))
    assert evidence["source_before"]["candidate_clean"] is True
    assert evidence["source_before"]["untracked_changes"] == []
    assert evidence["source_before"]["allowed_protected_asset_changes"] == ["AGENTS.md"]


def test_run_command_fails_evidence_when_source_changes_during_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _initialize_clean_repository(tmp_path)
    monkeypatch.chdir(repository)
    output = tmp_path / "source-change-command.json"
    script = (
        "from pathlib import Path; import subprocess; "
        "Path('tracked.txt').write_text('changed\\n'); "
        "subprocess.run(['git','add','tracked.txt'],check=True); "
        "subprocess.run(['git','commit','-q','-m','changed'],check=True)"
    )

    result = run_command(
        name="source_change",
        output=output,
        command=[sys.executable, "-c", script],
    )

    evidence = json.loads(output.read_text(encoding="utf-8"))
    assert result != 0
    assert evidence["process_exit_code"] == 0
    assert evidence["passed"] is False
    assert evidence["source_binding_match"] is False
    assert evidence["source_before"]["commit"] != evidence["source_after"]["commit"]
    assert evidence["source_before"]["tree"] != evidence["source_after"]["tree"]


def test_protected_asset_and_bundle_access_checks_fail_closed(
    tmp_path: Path,
    capsys,
) -> None:
    asset = tmp_path / "asset.txt"
    asset.write_text("protected", encoding="utf-8")
    assert protected_assets_check([f"{asset}={sha256_file(asset)}"]) == 0
    assert json.loads(capsys.readouterr().out)["pass"] is True

    assert bundle_access_check(bundle_root=tmp_path, required=["asset.txt", "missing.txt"]) == 1
    assert json.loads(capsys.readouterr().out)["pass"] is False

    secret = tmp_path / "auth.json"
    secret.write_text('{"auth_token":"mvr_' + "a" * 43 + '"}', encoding="utf-8")
    assert bundle_access_check(bundle_root=tmp_path, required=["asset.txt"]) == 0
    assert json.loads(capsys.readouterr().out)["pass"] is True
    assert bundle_access_check(
        bundle_root=tmp_path,
        required=["asset.txt", "auth.json"],
    ) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["pass"] is False
    assert result["sanitization_findings"]


def test_protected_asset_receipt_order_matches_frozen_schema() -> None:
    schema = json.loads(
        Path("schemas/work_item_governance/r2-closeout-receipt.v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    prefix_items = schema["properties"]["protected_user_assets"]["properties"][
        "assets"
    ]["prefixItems"]
    assert tuple(
        item["allOf"][1]["properties"]["path"]["const"] for item in prefix_items
    ) == closeout_script._PROTECTED_ASSET_SCHEMA_ORDER


def test_bundle_manifest_excludes_itself_and_binds_file_list(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "one.txt").write_text("one", encoding="utf-8")
    manifest_path = tmp_path / "BUNDLE_MANIFEST.json"
    monkeypatch.setattr(
        closeout_script,
        "_FINAL_REVIEW_BUNDLE_FILES",
        ("one.txt", "BUNDLE_MANIFEST.json"),
    )

    assert bundle_manifest(bundle_root=tmp_path, output=manifest_path) == 0

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["file_count"] == 1
    assert manifest["files"][0]["path"] == "one.txt"


def test_frozen_toolchain_record_and_environment_root_are_verified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = Path(__file__).resolve().parents[1]
    measured = measure_closeout_toolchain(project)
    assert measured["record_hashes_verified"] is True
    assert measured["unowned_import_files"] == []

    original = toolchain_binding.sha256_file

    def tampered(path: str | Path) -> str:
        target = Path(path)
        if target.name == "ruff" and ".venv/bin" in target.as_posix():
            return "0" * 64
        return original(path)

    monkeypatch.setattr(toolchain_binding, "sha256_file", tampered)
    with pytest.raises(WorkItemGovernanceError) as rejected:
        measure_closeout_toolchain(project)
    assert rejected.value.code in {
        "CLOSEOUT_TOOLCHAIN_RECORD_MISMATCH",
        "CLOSEOUT_TOOLCHAIN_ROOT_MISMATCH",
    }


def test_toolchain_inventory_rejects_symlink_special_and_sourceless_overlays(
    tmp_path: Path,
) -> None:
    site_packages = tmp_path / "site-packages"
    site_packages.mkdir()
    owned = site_packages / "owned.py"
    owned.write_text("VALUE = 1\n", encoding="utf-8")
    (site_packages / "alias.py").symlink_to(owned)
    (site_packages / "late_overlay.pyc").write_bytes(b"sourceless")
    os.mkfifo(site_packages / "loader.pipe")
    cache = site_packages / "__pycache__"
    cache.mkdir()
    (cache / "owned.cpython-312.pyc").write_bytes(b"cache")

    assert toolchain_binding._unowned_site_package_entries(
        site_packages,
        {owned.absolute()},
    ) == [
        "__pycache__/owned.cpython-312.pyc",
        "alias.py",
        "late_overlay.pyc",
        "loader.pipe",
    ]


def test_toolchain_bin_inventory_rejects_import_shadow_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    venv = tmp_path / "venv"
    bin_root = venv / "bin"
    bin_root.mkdir(parents=True)
    (bin_root / "bandit").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (bin_root / "python").symlink_to(Path(sys.executable).resolve())
    monkeypatch.setattr(
        toolchain_binding,
        "_EXPECTED_BIN_ENTRIES",
        ("bandit", "python"),
    )
    assert len(toolchain_binding._measure_bin_inventory(venv)) == 2

    (bin_root / "_pytest").mkdir()
    with pytest.raises(WorkItemGovernanceError) as rejected:
        toolchain_binding._measure_bin_inventory(venv)
    assert rejected.value.code == "CLOSEOUT_TOOLCHAIN_BIN_INVENTORY_MISMATCH"


def test_toolchain_rejects_record_owned_preimport_bytecode() -> None:
    project = Path(__file__).resolve().parents[1]
    source = project / ".venv/lib/python3.12/site-packages/_distutils_hack/__init__.py"
    cache = Path(importlib.util.cache_from_source(source.as_posix()))
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(b"pre-import bytecode")
    try:
        with pytest.raises(WorkItemGovernanceError) as rejected:
            measure_closeout_toolchain(project)
        assert rejected.value.code in {
            "CLOSEOUT_TOOLCHAIN_PREIMPORT_BYTECODE",
            "CLOSEOUT_TOOLCHAIN_UNOWNED_IMPORT_FILE",
        }
    finally:
        cache.unlink(missing_ok=True)
        try:
            cache.parent.rmdir()
        except OSError:
            pass


def test_run_command_executes_nested_trusted_launcher_with_scrubbed_startup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = Path(__file__).resolve().parents[1]
    try:
        trusted_launcher._measure_source_tree(project)
    except RuntimeError:
        pytest.skip("nested launcher positive assertion requires the committed candidate")
    monkeypatch.chdir(project)
    output = tmp_path / "nested-launcher.json"

    assert run_command(
        name="nested_launcher",
        output=output,
        command=[
            "/usr/bin/python3.12",
            "-I",
            "-S",
            "-B",
            "-",
            ".",
            "protected-assets-check",
        ],
    ) == 0

    evidence = json.loads(output.read_text(encoding="utf-8"))
    assert json.loads(evidence["stdout"])["pass"] is True
    assert evidence["environment_policy"]["trusted_launcher_child"] is True
    assert evidence["environment_policy"]["trusted_launcher_removed_keys"] == [
        "GIT_CONFIG_GLOBAL",
        "GIT_CONFIG_NOSYSTEM",
        "GIT_NO_REPLACE_OBJECTS",
        "GIT_OPTIONAL_LOCKS",
        "GIT_TERMINAL_PROMPT",
        "PYTHONDONTWRITEBYTECODE",
        "PYTHONHASHSEED",
    ]


@pytest.mark.parametrize(
    "payload",
    (
        '{"result":"PASS","result":"BLOCKED"}',
        '{"result":NaN}',
    ),
)
def test_receipt_runner_rejects_duplicate_keys_and_nonfinite_values(
    tmp_path: Path,
    payload: str,
) -> None:
    receipt = tmp_path / "receipt.json"
    receipt.write_text(payload, encoding="utf-8")

    with pytest.raises(ValueError):
        verify_receipt(
            receipt=receipt,
            bundle_root=tmp_path,
            project_root=tmp_path,
        )
