from __future__ import annotations

import json
import importlib.util
import os
import subprocess
import sys
import sysconfig
from pathlib import Path

import pytest

import runner.work_item_governance.closeout as governance_closeout
import runner.work_item_governance.toolchain_binding as toolchain_binding
import scripts.work_item_r3_closeout as closeout_script
import scripts.work_item_r3_trusted_launcher as trusted_launcher
from runner.work_item_governance.canonical import canonical_sha256, sha256_file
from runner.work_item_governance.errors import WorkItemGovernanceError
from scripts.work_item_r3_closeout import (
    bundle_access_check,
    bundle_manifest,
    protected_assets_check,
    run_command as _run_command,
    verify_receipt,
)
from runner.toolchain_environment import (
    materialize_frozen_toolchain_environment,
    venv_python,
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


def _frozen_toolchain_project() -> Path:
    configured = os.environ.get("COLAMETA_FROZEN_TOOLCHAIN_PROJECT_ROOT")
    return (
        Path(configured).expanduser().resolve()
        if configured
        else Path(__file__).resolve().parents[1]
    )


def _frozen_source_project() -> Path:
    configured = os.environ.get("COLAMETA_FROZEN_SOURCE_ROOT") or os.environ.get(
        "COLAMETA_FROZEN_TRUSTED_SOURCE_ROOT"
    )
    return (
        Path(configured).expanduser().resolve()
        if configured
        else Path(__file__).resolve().parents[1]
    )


def _materialize_test_frozen_toolchain(tmp_path: Path) -> tuple[Path, Path]:
    source_project = _frozen_toolchain_project()
    asset_path = os.environ.get("COLAMETA_FROZEN_CRYPTOGRAPHY_WHEEL")
    assets = toolchain_binding.load_verified_frozen_toolchain_record()["required_assets"]
    asset = assets["cryptography"]
    if not asset_path:
        raise AssertionError("the bound cryptography wheel asset is required")
    materialized_project, materialized_venv, _summary = (
        materialize_frozen_toolchain_environment(
            source_venv=source_project / ".venv",
            work_root=tmp_path / "frozen-toolchain",
            frozen_asset=Path(asset_path),
            frozen_asset_filename=asset["filename"],
            frozen_asset_sha256=asset["sha256"],
            frozen_asset_distribution=asset["distribution"],
            frozen_asset_version=asset["version"],
        )
    )
    return materialized_project, materialized_venv


def _measure_in_frozen_venv(
    project: Path,
    venv: Path,
    *,
    tamper_wrapper: bool = False,
) -> dict[str, object]:
    probe = r'''
import json
import sys
from pathlib import Path
import runner.work_item_governance.toolchain_binding as binding

if sys.argv[2] == "tamper":
    original = binding.sha256_file
    def tampered(path):
        target = Path(path)
        if target.name == "ruff" and ".venv/bin" in target.as_posix():
            return "0" * 64
        return original(path)
    binding.sha256_file = tampered
try:
    measured = binding.measure_closeout_toolchain(sys.argv[1])
except Exception as exc:
    print(json.dumps({"ok": False, "error_code": getattr(exc, "code", type(exc).__name__)}))
else:
    print(json.dumps({
        "ok": True,
        "record_hashes_verified": measured.get("record_hashes_verified"),
        "unowned_import_files": measured.get("unowned_import_files"),
        "environment_root_sha256": measured.get("environment_root_sha256"),
    }, sort_keys=True))
'''
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"}
    }
    environment.update(
        {
            "PATH": f"{venv / 'bin'}:{os.defpath}",
            "VIRTUAL_ENV": str(venv),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
        }
    )
    completed = subprocess.run(
        [str(venv_python(venv)), "-c", probe, str(project), "tamper" if tamper_wrapper else "clean"],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
        shell=False,
    )
    return json.loads(completed.stdout)


@pytest.fixture(autouse=True)
def _stub_exact_project_toolchain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        closeout_script,
        "measure_closeout_toolchain",
        lambda _project_root: dict(_TEST_TOOLCHAIN),
    )


def _initialize_clean_repository(
    root: Path,
    *,
    tracked_content: str = "tracked\n",
) -> Path:
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
    (repository / "tracked.txt").write_text(tracked_content, encoding="utf-8")
    subprocess.run(["git", "-C", repository, "add", "tracked.txt"], check=True)
    subprocess.run(["git", "-C", repository, "commit", "-q", "-m", "fixture"], check=True)
    return repository


def _initialize_governed_candidate(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path]:
    """Build a small HEAD-plus-delta checkout and its governed receipt."""

    repository = root / "candidate"
    repository.mkdir()
    for directory in ("runner", "adapters", "schemas", "scripts", "tests"):
        package = repository / directory
        package.mkdir()
        (package / ".keep").write_text("fixture\n", encoding="utf-8")
    launcher = repository / "scripts" / "work_item_r3_trusted_launcher.py"
    launcher.write_bytes(
        (Path(__file__).resolve().parents[1] / "scripts" / launcher.name).read_bytes()
    )
    tracked = repository / "runner" / "dependency.py"
    tracked.write_text("MARKER = 'head'\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", repository], check=True)
    subprocess.run(
        ["git", "-C", repository, "config", "user.email", "r3-runner@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", repository, "config", "user.name", "R3 Runner"],
        check=True,
    )
    subprocess.run(["git", "-C", repository, "add", "."], check=True)
    subprocess.run(["git", "-C", repository, "commit", "-q", "-m", "fixture"], check=True)

    tracked.write_text("MARKER = 'delta'\n", encoding="utf-8")
    overlay = repository / "scripts" / "candidate_overlay.py"
    overlay.write_text("MARKER = 'overlay'\n", encoding="utf-8")
    head = subprocess.run(
        ["git", "-C", repository, "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    bindings = [
        {
            "path": "runner/dependency.py",
            "present": True,
            "sha256": sha256_file(tracked),
        },
        {
            "path": "scripts/candidate_overlay.py",
            "present": True,
            "sha256": sha256_file(overlay),
        },
    ]
    toolchain_project = root / "frozen-toolchain-project"
    toolchain_environment = toolchain_project / ".venv"
    toolchain_environment.mkdir(parents=True)
    (toolchain_environment / "pyvenv.cfg").write_text(
        "home = /usr/bin\nversion = 3.12.3\n", encoding="utf-8"
    )
    receipt = {
        "schema_version": "colameta.trusted_launcher_binding.v1",
        "candidate": {
            "head": head,
            "root": repository.resolve().as_posix(),
            "worktree_delta_sha256": canonical_sha256(bindings),
            "source_binding_sha256": canonical_sha256(bindings),
            "source_binding_count": len(bindings),
            "source_binding_scope": "full_allowed_worktree_delta",
            "source_bindings": bindings,
        },
        "toolchain": {
            "project_root": toolchain_project.resolve().as_posix(),
            "environment_root": toolchain_environment.resolve().as_posix(),
            "environment_root_sha256": "a" * 64,
            "frozen_record_sha256": "b" * 64,
            "cryptography_version": "50.0.0",
        },
        "launcher": {
            "path": "scripts/work_item_r3_trusted_launcher.py",
            "sha256": sha256_file(launcher),
        },
        "validation": {
            "preview_id": "fixture1234",
            "command_specs_sha256": "c" * 64,
            "lane": "host_frozen",
        },
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    receipt_path = repository.parent / "trusted-launcher-binding.json"
    receipt_path.write_text(json.dumps(receipt, sort_keys=True), encoding="utf-8")
    monkeypatch.setenv(
        "COLAMETA_TRUSTED_LAUNCHER_BINDING_FILE",
        receipt_path.as_posix(),
    )
    return repository, receipt_path


def test_governed_receipt_accepts_exact_head_plus_candidate_delta(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, _receipt_path = _initialize_governed_candidate(tmp_path, monkeypatch)

    receipt = trusted_launcher._load_binding_receipt(repository)
    assert receipt is not None
    measured = trusted_launcher._measure_source_tree(
        repository,
        binding_receipt=receipt,
    )
    assert measured["candidate_binding"]["exact_match"] is True
    assert measured["candidate_binding"]["source_binding_count"] == 2


def test_governed_receipt_rejects_extra_candidate_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, _receipt_path = _initialize_governed_candidate(tmp_path, monkeypatch)
    (repository / "schemas" / "unbound.py").write_text(
        "MARKER = 'unbound'\n", encoding="utf-8"
    )

    with pytest.raises(RuntimeError, match="unbound source overlay"):
        trusted_launcher._measure_source_tree(repository)


def test_governed_receipt_rejects_bound_file_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, _receipt_path = _initialize_governed_candidate(tmp_path, monkeypatch)
    (repository / "runner" / "dependency.py").write_text(
        "MARKER = 'raced'\n", encoding="utf-8"
    )

    with pytest.raises(RuntimeError, match="source differs"):
        trusted_launcher._measure_source_tree(repository)


def test_governed_receipt_rejects_tampering_and_receipt_path_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, receipt_path = _initialize_governed_candidate(tmp_path, monkeypatch)
    tampered = json.loads(receipt_path.read_text(encoding="utf-8"))
    tampered["candidate"]["head"] = "0" * 40
    receipt_path.write_text(json.dumps(tampered, sort_keys=True), encoding="utf-8")
    with pytest.raises(RuntimeError, match="digest mismatch"):
        trusted_launcher._load_binding_receipt(repository)

    link = receipt_path.with_name("receipt-link.json")
    link.symlink_to(receipt_path)
    monkeypatch.setenv("COLAMETA_TRUSTED_LAUNCHER_BINDING_FILE", link.as_posix())
    with pytest.raises(RuntimeError, match="path is unsafe"):
        trusted_launcher._load_binding_receipt(repository)


def test_host_nested_launcher_rejects_missing_governed_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _initialize_clean_repository(tmp_path)
    monkeypatch.chdir(repository)
    monkeypatch.setenv("COLAMETA_VALIDATION_LANE", "host_frozen")
    monkeypatch.delenv("COLAMETA_TRUSTED_LAUNCHER_BINDING_FILE", raising=False)
    output = tmp_path / "missing-binding.json"

    result = run_command(
        name="missing_binding",
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
    )

    assert result == 126
    evidence = json.loads(output.read_text(encoding="utf-8"))
    assert evidence["passed"] is False
    assert evidence["trusted_launcher_stdin"] is None


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
    expected_commit = subprocess.run(
        ["git", "-C", repository, "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    attacker_root = tmp_path / "attacker"
    attacker_root.mkdir()
    attacker = _initialize_clean_repository(
        attacker_root,
        tracked_content="attacker\n",
    )
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


def test_only_exact_obsolete_zone_metadata_paths_may_be_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    expected = governance_closeout.OPTIONAL_ABSENT_PROTECTED_ASSET_SHA256
    monkeypatch.chdir(tmp_path)

    for path, digest in expected.items():
        assert protected_assets_check([f"{path}={digest}"]) == 0
        result = json.loads(capsys.readouterr().out)
        assert result["assets"] == [
            {
                "path": path,
                "expected_sha256": digest,
                "present": False,
                "absence_allowed": True,
                "actual_sha256": None,
                "match": True,
            }
        ]

    arbitrary = "other:Zone.Identifier"
    assert protected_assets_check([f"{arbitrary}={'a' * 64}"]) == 1
    assert json.loads(capsys.readouterr().out)["assets"][0]["absence_allowed"] is False

    exact_name_at_wrong_root = tmp_path / next(iter(expected))
    assert protected_assets_check(
        [f"{exact_name_at_wrong_root}={expected[exact_name_at_wrong_root.name]}"]
    ) == 1
    assert json.loads(capsys.readouterr().out)["assets"][0]["absence_allowed"] is False

    exact_path = next(iter(expected))
    Path(exact_path).write_text("wrong bytes", encoding="utf-8")
    assert protected_assets_check([f"{exact_path}={expected[exact_path]}"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["assets"][0]["present"] is True
    assert result["assets"][0]["match"] is False


def test_receipt_verifier_accepts_only_exact_absent_zone_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _CleanGit:
        def run(self, _root: Path, *_arguments: str) -> str:
            return ""

    monkeypatch.setattr(
        governance_closeout,
        "_trusted_git_for_checkout",
        lambda _root: _CleanGit(),
    )
    expected = governance_closeout.OPTIONAL_ABSENT_PROTECTED_ASSET_SHA256
    receipt = {
        "protected_user_assets": {
            "assets": [
                {"path": path, "sha256": digest}
                for path, digest in expected.items()
            ],
            "staged": False,
            "committed": False,
        }
    }

    violations: list[str] = []
    governance_closeout._verify_protected_assets(receipt, tmp_path, violations)
    assert violations == []

    receipt["protected_user_assets"]["assets"][0]["sha256"] = "a" * 64
    governance_closeout._verify_protected_assets(receipt, tmp_path, violations := [])
    assert violations == [
        "protected_asset_digest:AGENTS - 副本.md:Zone.Identifier"
    ]

    receipt["protected_user_assets"]["assets"] = [
        {"path": "other:Zone.Identifier", "sha256": "a" * 64}
    ]
    governance_closeout._verify_protected_assets(receipt, tmp_path, violations := [])
    assert violations == ["protected_asset_missing:other:Zone.Identifier"]


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


@pytest.mark.host_frozen_toolchain
def test_frozen_toolchain_record_and_environment_root_are_verified(
    tmp_path: Path,
) -> None:
    project, venv = _materialize_test_frozen_toolchain(tmp_path)
    measured = _measure_in_frozen_venv(project, venv)
    assert measured["ok"] is True
    assert measured["record_hashes_verified"] is True
    assert measured["unowned_import_files"] == []

    tampered = _measure_in_frozen_venv(project, venv, tamper_wrapper=True)
    assert tampered["ok"] is False
    assert tampered["error_code"] in {
        "CLOSEOUT_TOOLCHAIN_RECORD_MISMATCH",
        "CLOSEOUT_TOOLCHAIN_ROOT_MISMATCH",
    }


def test_rebased_frozen_authority_does_not_accept_historical_root() -> None:
    historical_root = (
        "0f80e9f3d3bb3cc4b7aed88acdddf7f87c2fc17e3954c7d2966795fb0dc2515d"
    )
    record = toolchain_binding.load_verified_frozen_toolchain_record()
    assert record["environment_root_sha256"] == (
        "1eb3b914080827525b75bb230b0f2cb41a692995892ba39a71085f70bd141c29"
    )
    assert record["environment_root_sha256"] != historical_root


def test_frozen_record_load_is_independent_from_active_bytecode_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = toolchain_binding.load_verified_frozen_toolchain_record()
    venv = tmp_path / "venv"
    site_packages = venv / "lib" / "python3.12" / "site-packages"
    unknown = site_packages / "unknown" / "__pycache__" / "module.cpython-312.pyc"
    unknown.parent.mkdir(parents=True)
    unknown.write_bytes(b"unknown")
    monkeypatch.setattr(
        toolchain_binding,
        "_toolchain_context",
        lambda project_root: (Path(project_root), venv, site_packages),
    )
    monkeypatch.setattr(
        toolchain_binding,
        "_measure_closeout_toolchain",
        lambda _project_root, allow_preimport_bytecode=False: {
            "environment_root_sha256": record["environment_root_sha256"],
            "record_hashes_verified": True,
        },
    )
    inspection = toolchain_binding.inspect_frozen_toolchain_environment(
        tmp_path,
    )
    inventory = inspection["bytecode_inventory"]
    assert record["record_sha256"]
    assert inspection["status"] == "drifted"
    assert inspection["record_hashes_verified"] is True
    assert inspection["bytecode_policy_satisfied"] is False
    assert inventory["total_count"] == 1
    assert inventory["unknown_owner_count"] == 1
    assert inspection["blocking_reasons"]


def test_unknown_bytecode_owner_is_not_silently_allowed(tmp_path: Path) -> None:
    site_packages = tmp_path / "lib" / "python3.12" / "site-packages"
    site_packages.mkdir(parents=True)
    unknown = site_packages / "unknown" / "__pycache__" / "module.cpython-312.pyc"
    unknown.parent.mkdir(parents=True)
    unknown.write_bytes(b"unknown")

    inventory = toolchain_binding._bytecode_inventory(
        venv=tmp_path,
        site_packages=site_packages,
        distributions=[],
    )
    assert inventory["total_count"] == 1
    assert inventory["record_listed_count"] == 0
    assert inventory["unknown_owner_count"] == 1
    assert inventory["bytecode_policy_satisfied"] is False


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


@pytest.mark.host_frozen_toolchain
def test_toolchain_rejects_record_owned_preimport_bytecode(tmp_path: Path) -> None:
    project, venv = _materialize_test_frozen_toolchain(tmp_path)
    purelib = Path(sysconfig.get_paths()["purelib"])
    relative_purelib = purelib.relative_to(Path(sys.prefix))
    source = project / ".venv" / relative_purelib / "_distutils_hack" / "__init__.py"
    cache = Path(importlib.util.cache_from_source(source.as_posix()))
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(b"pre-import bytecode")
    try:
        rejected = _measure_in_frozen_venv(project, venv)
        assert rejected["ok"] is False
        assert rejected["error_code"] in {
            "CLOSEOUT_TOOLCHAIN_PREIMPORT_BYTECODE",
            "CLOSEOUT_TOOLCHAIN_UNOWNED_IMPORT_FILE",
        }
    finally:
        cache.unlink(missing_ok=True)
        try:
            cache.parent.rmdir()
        except OSError:
            pass


@pytest.mark.host_frozen_toolchain
def test_run_command_executes_nested_trusted_launcher_with_scrubbed_startup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _frozen_source_project()
    binding_receipt = trusted_launcher._load_binding_receipt(project)
    if binding_receipt is not None:
        trusted_launcher._measure_source_tree(
            project,
            binding_receipt=binding_receipt,
        )
        launcher_python = Path(
            binding_receipt["toolchain"]["environment_root"]
        ) / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    else:
        try:
            trusted_launcher._measure_source_tree(project)
        except RuntimeError:
            pytest.skip("nested launcher positive assertion requires the committed candidate")
        launcher_python = Path("/usr/bin/python3.12")
    monkeypatch.chdir(project)
    output = tmp_path / "nested-launcher.json"

    assert run_command(
        name="nested_launcher",
        output=output,
        command=[
            launcher_python.as_posix(),
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
