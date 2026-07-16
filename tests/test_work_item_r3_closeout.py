from __future__ import annotations

import hashlib
import io
import json
import os
import stat
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path

import pytest

import runner.work_item_governance.closeout as closeout
from runner.work_item_governance.canonical import canonical_sha256, sha256_file


def test_closeout_loads_critical_runtime_modules_before_source_attestation() -> None:
    assert "runner.work_item_governance.activation" in sys.modules
    assert "runner.work_item_governance.bootstrap" in sys.modules
    assert "runner.work_item_governance.source_binding" in sys.modules


def _git_binding(project_root: Path) -> tuple[str, str]:
    output = subprocess.run(
        ["git", "rev-parse", "HEAD", "HEAD^{tree}"],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    return output[0], output[1]


def _command_provenance(
    project_root: Path,
    argv: list[str],
) -> tuple[dict[str, object], dict[str, object]]:
    commit, tree = _git_binding(project_root)
    protected = [
        "AGENTS - 副本.amd",
        "AGENTS - 副本.md:Zone.Identifier",
        "AGENTS.md",
        "AGENTS.md:Zone.Identifier",
    ]
    state = {
        "repository_root": project_root.as_posix(),
        "requested_checkout_root": project_root.as_posix(),
        "commit": commit,
        "tree": tree,
        "candidate_clean": True,
        "tracked_changes": [],
        "staged_changes": [],
        "untracked_changes": [],
        "allowed_protected_asset_changes": protected,
        "assume_unchanged_paths": [],
        "skip_worktree_paths": [],
        "ignored_execution_overlays": [],
        "untracked_execution_overlays": [],
        "object_mismatches": [],
        "git_object_manifest_digest": "a" * 64,
        "git_object_format": "sha1",
        "git_executable": {
            "resolved_path": "/usr/bin/git",
            "sha256": "b" * 64,
            "owner_uid": 0,
            "mode": "0755",
            "root_owned": True,
            "group_or_other_writable": False,
        },
        "inspection_errors": [],
    }
    executable = Path(argv[0]).resolve()
    digest = hashlib.sha256(executable.read_bytes()).hexdigest()
    launcher = Path(argv[0]).absolute()
    launcher_target = os.readlink(launcher) if launcher.is_symlink() else None
    toolchain = {
        "environment_root_sha256": "c" * 64,
        "fixed_files": [
            {
                "path": "bin/python",
                "sha256": digest,
                "symlink_target": launcher_target,
            }
        ],
        "wrappers": [],
    }
    bootstrap_launcher = project_root / "scripts" / "work_item_r3_trusted_launcher.py"
    system_python = Path("/usr/bin/python3.12")
    python_resolved = system_python.resolve()
    python_metadata = python_resolved.stat()
    preimport_git = closeout._trusted_git_for_checkout(project_root)
    preimport_source_state = closeout._inspect_git_checkout(
        project_root,
        git=preimport_git,
        pathspecs=(),
        excluded_paths=frozenset(
            {
                "AGENTS.md",
                "AGENTS - 副本.amd",
                "AGENTS - 副本.md:Zone.Identifier",
                "AGENTS.md:Zone.Identifier",
            }
        ),
    )
    try:
        launcher_blob_oid = preimport_git.run(
            project_root,
            "rev-parse",
            "HEAD:scripts/work_item_r3_trusted_launcher.py",
        ).strip()
    except Exception:
        launcher_blob_oid = "0" * 40
    attestation: dict[str, object] = {
        "schema_version": "work_item_r3_preimport_attestation.v1",
        "accepted": True,
        "project_root": project_root.as_posix(),
        "launcher_execution_source": "trusted_git_blob_stdin",
        "launcher_relative_path": "scripts/work_item_r3_trusted_launcher.py",
        "launcher_blob_oid": launcher_blob_oid,
        "launcher_sha256": sha256_file(bootstrap_launcher),
        "python_executable": {
            "requested_path": system_python.as_posix(),
            "resolved_path": python_resolved.as_posix(),
            "proc_self_exe": python_resolved.as_posix(),
            "sha256": sha256_file(python_resolved),
            "owner_uid": 0,
            "mode": f"{stat.S_IMODE(python_metadata.st_mode):04o}",
            "root_owned": True,
            "group_or_other_writable": False,
        },
        "python_flags": {
            "isolated": True,
            "no_site": True,
            "dont_write_bytecode": True,
            "safe_path": True,
        },
        "startup_authority_environment": [],
        "source": {
            "commit": commit,
            "tree": tree,
            "git_object_format": preimport_source_state["object_format"],
            "tracked_path_count": preimport_source_state["tracked_path_count"],
            "tracked_manifest_sha256": preimport_source_state["manifest_digest"],
            "git_executable_sha256": sha256_file(Path("/usr/bin/git")),
            "launcher_blob_oid": launcher_blob_oid,
            "launcher_blob_sha256": sha256_file(bootstrap_launcher),
        },
        "environment": {
            "entry_count": closeout._PREIMPORT_ENVIRONMENT_ENTRY_COUNT,
            "environment_tree_sha256": closeout._PREIMPORT_ENVIRONMENT_TREE_SHA256,
        },
    }
    attestation["attestation_sha256"] = canonical_sha256(attestation)
    payload = {
        "schema_version": "work_item_closeout_command_evidence.v2",
        "process_exit_code": 0,
        "monotonic_duration_ns": 1_000_000_000,
        "wall_clock_rollback_clamped": False,
        "source_before": state,
        "source_after": state,
        "source_binding_match": True,
        "executable": {
            "requested": argv[0],
            "launcher_path": launcher.as_posix(),
            "launcher_sha256": digest,
            "launcher_sha256_after": digest,
            "launcher_symlink_target": launcher_target,
            "launcher_symlink_target_after": launcher_target,
            "resolved_path": executable.as_posix(),
            "resolved_sha256": digest,
            "resolved_sha256_after": digest,
            "unchanged": True,
        },
        "toolchain": {
            "before": toolchain,
            "after": toolchain,
            "error_before": None,
            "error_after": None,
            "unchanged": True,
        },
        "environment_policy": {
            "removed_keys": {
                key: False
                for key in (
                    "PYTEST_ADDOPTS",
                    "PYTEST_PLUGINS",
                    "PYTHONPATH",
                    "PYTHONSTARTUP",
                    "PYTHONINSPECT",
                    "COVERAGE_PROCESS_START",
                )
            },
            "forced_values": {
                "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
                "PYTHONHASHSEED": "0",
                "PYTHONDONTWRITEBYTECODE": "1",
            },
            "authority_removed_keys": [],
            "authority_prefixes": [
                "BANDIT_",
                "COVERAGE_",
                "COV_CORE_",
                "DISTUTILS_",
                "DYLD_",
                "GIT_",
                "LD_",
                "PIP_",
                "PYTEST_",
                "PYTHON",
                "RUFF_",
                "SETUPTOOLS_",
            ],
            "executable_path": (
                f"{(project_root / '.venv' / 'bin').resolve().as_posix()}:/bin:/usr/bin"
            ),
            "pip_config_file": "/dev/null",
            "git_authority_environment_scrubbed": True,
            "loader_authority_environment_scrubbed": True,
            "trusted_launcher_child": False,
            "trusted_launcher_removed_keys": [],
        },
        "preimport_attestation": attestation,
    }
    receipt = {
        "source_binding": {
            "implementation_commit": commit,
            "implementation_tree": tree,
        },
        "protected_user_assets": {
            "assets": [{"path": path} for path in protected]
        },
    }
    return payload, receipt


def _receipt(project_root: Path, wheel_sha256: str) -> dict[str, object]:
    commit, tree = _git_binding(project_root)
    source = {
        "core_baseline_commit": "5" * 40,
        "implementation_commit": commit,
        "implementation_tree": tree,
        "wheel_sha256": wheel_sha256,
    }
    return {
        "source_binding": source,
        "runtime_isolation": {"bind_address": "127.0.0.1", "port": 48713},
        "restricted_surface": {"listed_tool_count": 14},
        "activation_lease": {
            "lease_snapshot_export_relative_path": "evidence/activation-lease-snapshot.json"
        },
        "verification": [
            {
                "name": "wheel_source_inventory",
                "evidence_ref": "evidence/wheel-source-inventory.json",
                "result": {
                    "wheel_sha256": wheel_sha256,
                    "wheel_artifact_ref": "evidence/candidate.whl",
                    "wheel_artifact_size_bytes": 11,
                },
            },
            {
                "name": "runtime_isolation_smoke",
                "evidence_ref": "evidence/runtime.json",
                "started_at": "2026-07-12T00:00:00Z",
                "ended_at": "2026-07-12T00:01:00Z",
            },
        ],
    }


@dataclass
class _MeasuredSource:
    source_binding: dict[str, str]
    file_manifest_digest: str = "a" * 64


def _write_runtime_evidence(root: Path, receipt: dict[str, object]) -> None:
    evidence = root / "evidence"
    commands = evidence / "commands"
    commands.mkdir()
    source = receipt["source_binding"]
    attestation = {
        "schema_version": "work_item_runtime_source_attestation.v1",
        "source_binding": source,
        "file_manifest_digest": "a" * 64,
        "artifact_evidence_digest": "b" * 64,
        "checkout_path_digest": "c" * 64,
        "wheel_path_digest": "d" * 64,
        "verified": True,
    }
    lease = {
        "lease_id": "lease_01900000-0000-7000-8000-000000000000",
        "claimed_process_identity": "e" * 64,
        "listener_attestation_digest": "f" * 64,
        "authenticated_request_context_binding_digest": "1" * 64,
        "final_status": "closed",
        "final_state_version": 4,
    }
    runtime_item = receipt["verification"][1]
    command_path = commands / "runtime-isolation-smoke-command.json"
    command_path.write_text(
        json.dumps(
            {
                "schema_version": "work_item_closeout_command_evidence.v1",
                "name": "runtime_isolation_smoke",
                "argv": [
                    "python3",
                    "-m",
                    "pytest",
                    "-q",
                    (
                        "tests/test_work_item_authoritative_canary.py::"
                        "test_loopback_conformance_requires_token_and_exposes_exact_surface"
                    ),
                ],
                "cwd": Path(__file__).resolve().parents[1].as_posix(),
                "started_at": runtime_item["started_at"],
                "ended_at": runtime_item["ended_at"],
                "exit_code": 0,
                "passed": True,
                "stdout": "1 passed in 1.00s",
                "stderr": "",
            }
        ),
        encoding="utf-8",
    )
    (evidence / "runtime.json").write_text(
        json.dumps(
            {
                "pass": True,
                "bind_address": "127.0.0.1",
                "port": 48713,
                "listed_tools": 14,
                "tool_names": list(closeout.AUTHORITATIVE_CANARY_TOOLS),
                "source": source,
                "source_attestation": attestation,
                "authentication": {
                    "no_token_http_status": 401,
                    "wrong_token_http_status": 401,
                    "correct_token_http_status": 200,
                    "revoked_token_http_status": 401,
                    "token_file_present_after": False,
                },
                "command_evidence_ref": (
                    "evidence/commands/runtime-isolation-smoke-command.json"
                ),
                "command_evidence_sha256": hashlib.sha256(
                    command_path.read_bytes()
                ).hexdigest(),
                "lease": lease,
            }
        ),
        encoding="utf-8",
    )
    (evidence / "activation-lease-snapshot.json").write_text(
        json.dumps(
            {
                "lease_id": lease["lease_id"],
                "created_at": "2026-07-12T00:00:01Z",
                "updated_at": "2026-07-12T00:00:59Z",
                "status": "closed",
                "state_version": 4,
                "runtime_binding": {
                    "claimed_process_identity": lease["claimed_process_identity"],
                    "listener_attestation_digest": lease["listener_attestation_digest"],
                    "authenticated_request_context_binding_digest": lease[
                        "authenticated_request_context_binding_digest"
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    (evidence / "runtime-source-attestation.json").write_text(
        json.dumps(attestation),
        encoding="utf-8",
    )


def test_closeout_rejects_wheel_inventory_that_disagrees_with_retained_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    wheel = evidence / "candidate.whl"
    wheel.write_bytes(b"wheel-bytes")
    wheel_sha256 = hashlib.sha256(wheel.read_bytes()).hexdigest()
    receipt = _receipt(Path(__file__).resolve().parents[1], wheel_sha256)
    monkeypatch.setattr(
        closeout,
        "verify_runtime_source_artifacts",
        lambda **_kwargs: _MeasuredSource(receipt["source_binding"]),
    )
    (evidence / "wheel-source-inventory.json").write_text(
        json.dumps(
            {
                "wheel_sha256": "0" * 64,
                "source_binding": receipt["source_binding"],
                "file_manifest_digest": "a" * 64,
            }
        ),
        encoding="utf-8",
    )
    _write_runtime_evidence(tmp_path, receipt)

    violations: list[str] = []
    closeout._verify_exact_source_and_runtime_evidence(
        receipt,  # type: ignore[arg-type]
        tmp_path,
        Path(__file__).resolve().parents[1],
        violations,
    )

    assert violations == ["wheel_inventory_source_binding"]


def test_closeout_requires_retained_wheel_and_causal_runtime_lease_time(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    wheel_sha256 = "1" * 64
    receipt = _receipt(Path(__file__).resolve().parents[1], wheel_sha256)
    (evidence / "wheel-source-inventory.json").write_text(
        json.dumps({"wheel_sha256": wheel_sha256}),
        encoding="utf-8",
    )
    _write_runtime_evidence(tmp_path, receipt)
    snapshot = json.loads((evidence / "activation-lease-snapshot.json").read_text())
    snapshot["created_at"] = "2026-07-11T23:59:59Z"
    snapshot["updated_at"] = "2026-07-12T00:01:01Z"
    (evidence / "activation-lease-snapshot.json").write_text(
        json.dumps(snapshot),
        encoding="utf-8",
    )

    violations: list[str] = []
    closeout._verify_exact_source_and_runtime_evidence(
        receipt,  # type: ignore[arg-type]
        tmp_path,
        Path(__file__).resolve().parents[1],
        violations,
    )

    assert "evidence_missing:wheel_artifact" in violations
    assert "runtime_lease_time_causality" in violations


def test_closeout_rejects_non_wheel_artifact_even_when_hashes_agree(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    wheel = evidence / "candidate.whl"
    wheel.write_bytes(b"not-a-wheel")
    wheel_sha256 = hashlib.sha256(wheel.read_bytes()).hexdigest()
    receipt = _receipt(Path(__file__).resolve().parents[1], wheel_sha256)
    receipt["verification"][0]["result"]["wheel_artifact_size_bytes"] = wheel.stat().st_size  # type: ignore[index]
    (evidence / "wheel-source-inventory.json").write_text(
        json.dumps(
            {
                "wheel_sha256": wheel_sha256,
                "source_binding": receipt["source_binding"],
                "file_manifest_digest": "a" * 64,
            }
        ),
        encoding="utf-8",
    )
    _write_runtime_evidence(tmp_path, receipt)

    violations: list[str] = []
    closeout._verify_exact_source_and_runtime_evidence(
        receipt,  # type: ignore[arg-type]
        tmp_path,
        Path(__file__).resolve().parents[1],
        violations,
    )

    assert "wheel_git_runtime_source_attestation" in violations


def test_closeout_rejects_true_command_masquerading_as_full_pytest(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[1]
    argv = [str(Path("/usr/bin/true").resolve())]
    provenance, receipt = _command_provenance(project_root, argv)
    evidence = tmp_path / "full-pytest.json"
    evidence.write_text(
        json.dumps(
                {
                    **provenance,
                "name": "full_pytest",
                    "argv": argv,
                    "cwd": project_root.as_posix(),
                "started_at": "2026-07-12T00:00:00Z",
                "ended_at": "2026-07-12T00:00:01Z",
                "exit_code": 0,
                "passed": True,
                "stdout": "1132 passed",
                "stderr": "",
            }
        ),
        encoding="utf-8",
    )
    receipt_item = {
        "name": "full_pytest",
        "command": argv[0],
        "started_at": "2026-07-12T00:00:00Z",
        "ended_at": "2026-07-12T00:00:01Z",
        "exit_code": 0,
        "passed": True,
    }

    violations: list[str] = []
    closeout._verify_command_evidence(
        receipt_item,
        evidence,
        receipt=receipt,
        project_root=project_root,
        expected_git_binding=provenance["source_before"]["git_executable"],
        expected_git_state={"manifest_digest": "a" * 64, "object_format": "sha1"},
        expected_toolchain={"environment_root_sha256": "c" * 64},
        violations=violations,
    )

    assert "command_contract:full_pytest" in violations


def test_closeout_accepts_bound_pytest_completed_process_record(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[1]
    exact = closeout._inspect_git_checkout(
        project_root,
        git=closeout._trusted_git_for_checkout(project_root),
        pathspecs=(),
        excluded_paths=frozenset(
            {
                "AGENTS.md",
                "AGENTS - 副本.amd",
                "AGENTS - 副本.md:Zone.Identifier",
                "AGENTS.md:Zone.Identifier",
            }
        ),
    )
    if exact["object_mismatches"]:
        pytest.skip("positive exact-attestation assertion requires the committed candidate")
    argv = [str(project_root / ".venv/bin/python"), "-m", "pytest", "-q"]
    provenance, receipt = _command_provenance(project_root, argv)
    evidence = tmp_path / "full-pytest.json"
    payload = {
        **provenance,
        "name": "full_pytest",
        "argv": argv,
        "cwd": project_root.as_posix(),
        "started_at": "2026-07-12T00:00:00Z",
        "ended_at": "2026-07-12T00:00:01Z",
        "exit_code": 0,
        "passed": True,
        "stdout": "1280 passed in 180.00s",
        "stderr": "",
    }
    evidence.write_text(json.dumps(payload), encoding="utf-8")
    receipt_item = {
        "name": "full_pytest",
        "command": " ".join(argv),
        "started_at": payload["started_at"],
        "ended_at": payload["ended_at"],
        "exit_code": 0,
        "passed": True,
    }

    violations: list[str] = []
    closeout._verify_command_evidence(
        receipt_item,
        evidence,
        receipt=receipt,
        project_root=project_root,
        expected_git_binding=provenance["source_before"]["git_executable"],
        expected_git_state={"manifest_digest": "a" * 64, "object_format": "sha1"},
        expected_toolchain=provenance["toolchain"]["before"],
        violations=violations,
    )

    assert violations == []


def test_closeout_requires_real_commands_for_special_evidence_slots() -> None:
    bundle = "docs/WIG-P3-CANARY-A1-R2-IMPLEMENTATION-R3-review/evidence"
    assert closeout._command_matches_slot(
        "wheel_source_inventory",
        [
            "/usr/bin/python3.12",
            "-I",
            "-S",
            "-B",
            "-",
            ".",
            "wheel-inventory",
            "--checkout",
            ".",
            "--wheel",
            f"{bundle}/candidate/colameta-0.1.2-py3-none-any.whl",
            "--output",
            f"{bundle}/wheel-source-inventory.json",
        ],
    )


def test_ruff_evidence_rejects_no_files_warning() -> None:
    assert not closeout._command_output_matches_slot(
        "ruff",
        stdout="All checks passed!\n",
        stderr="warning: No Python files found under the given path(s)\n",
    )


def test_lease_event_principal_digest_uses_principal_context_projection() -> None:
    snapshot = {
        "caller_auth_mode": "token",
        "permissions": ["work_item.accept"],
        "principal_authenticated_by": "local_session",
        "principal_id": "operator",
        "principal_kind": "human",
        "session_ref": "session",
    }
    expected = canonical_sha256(
        {
            "principal_id": "operator",
            "principal_kind": "human",
            "authenticated_by": "local_session",
            "granted_permissions": ["work_item.accept"],
            "session_ref": "session",
        }
    )
    assert closeout._event_principal_binding_digest(snapshot) == expected
    assert expected != canonical_sha256(snapshot)


def test_every_lease_semantic_claim_is_bound_to_an_exact_pytest_target() -> None:
    bundle = "docs/WIG-P3-CANARY-A1-R2-IMPLEMENTATION-R3-review/evidence"
    focused = closeout._EXPECTED_PYTEST_ARGUMENTS["focused_negative_tests"]
    runtime = [
        "-q",
        closeout._RUNTIME_CONFORMANCE_TEST,
        "--basetemp=docs/WIG-P3-CANARY-A1-R2-IMPLEMENTATION-R3-review/"
        "evidence/runtime/pytest-runtime-exact",
    ]
    for bindings in closeout._LEASE_CHECK_EVIDENCE_BINDINGS.values():
        for slot, target in bindings:
            assert target in (focused if slot == "focused_negative_tests" else runtime)

    first = closeout._REQUIRED_FOCUSED_LEASE_TESTS[0]
    reduced = [item for item in focused if item != first]
    assert not closeout._command_matches_slot(
        "focused_negative_tests",
        [sys.executable, "-m", "pytest", *reduced],
    )
    assert closeout._command_matches_slot(
        "runtime_isolation_smoke",
        [
            "python3",
            "-m",
            "pytest",
            "-q",
            (
                "tests/test_work_item_authoritative_canary.py::"
                "test_loopback_conformance_requires_token_and_exposes_exact_surface"
            ),
            f"--basetemp={bundle}/runtime/pytest-runtime-exact",
        ],
    )
    assert not closeout._command_matches_slot("wheel_source_inventory", ["true"])
    assert not closeout._command_matches_slot("runtime_isolation_smoke", ["pytest", "-q"])


def test_runtime_command_rejects_basetemp_path_escape() -> None:
    assert not closeout._command_matches_slot(
        "runtime_isolation_smoke",
        [
            str(Path(sys.executable).resolve()),
            "-m",
            "pytest",
            "-q",
            "tests/test_work_item_authoritative_canary.py::"
            "test_loopback_conformance_requires_token_and_exposes_exact_surface",
            "--basetemp=docs/WIG-P3-CANARY-A1-R2-IMPLEMENTATION-R3-review/"
            "evidence/runtime/pytest-runtime-exact/../../outside",
        ],
    )


def test_sanitized_bundle_decodes_json_and_scans_wheel_members(tmp_path: Path) -> None:
    escaped = tmp_path / "escaped.json"
    escaped.write_text(
        r'{"\u0061uth_token":"\u006d\u0076\u0072\u005f'
        + (r"\u0041" * 43)
        + r'"}',
        encoding="utf-8",
    )
    wheel = tmp_path / "candidate.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("package/data.txt", "mvr_" + ("A" * 43))

    violations: list[str] = []
    closeout._verify_sanitized_evidence_bundle(tmp_path, violations)

    assert any("decoded_token_secret" in item for item in violations)
    assert any("candidate.whl!package/data.txt" in item for item in violations)


def test_sanitized_candidate_wheel_allows_source_auth_token_literals(
    tmp_path: Path,
) -> None:
    wheel = tmp_path / "candidate.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(
            "package/module.py",
            'EXAMPLE = {"auth_token": "documented-field-not-a-secret"}\n',
        )

    violations: list[str] = []
    closeout._verify_sanitized_evidence_bundle(tmp_path, violations)

    assert violations == []


@pytest.mark.parametrize(
    ("name", "payload"),
    [
        ("renamed-sqlite.txt", b"SQLite format 3\x00" + (b"x" * 100)),
        ("renamed-wal.txt", bytes.fromhex("377f0682") + (b"x" * 100)),
        ("renamed-journal.txt", b"\xd9\xd5\x05\xf9 \xa1c\xd7" + (b"x" * 100)),
        ("renamed-zip.txt", b"PK\x03\x04" + (b"x" * 100)),
        ("prefixed-zip.md", b"review text\nPK\x03\x04" + (b"x" * 100)),
        ("renamed-gzip.txt", b"\x1f\x8b" + (b"x" * 100)),
        ("renamed-bzip.txt", b"BZh" + (b"x" * 100)),
        ("renamed-xz.txt", b"\xfd7zXZ\x00" + (b"x" * 100)),
        ("renamed-7z.txt", b"7z\xbc\xaf'\x1c" + (b"x" * 100)),
        ("renamed-rar.txt", b"Rar!\x1a\x07" + (b"x" * 100)),
        ("renamed-ar.txt", b"!<arch>\n" + (b"x" * 100)),
        ("renamed-tar.txt", (b"x" * 257) + b"ustar\x00" + (b"x" * 100)),
    ],
)
def test_sanitized_bundle_rejects_renamed_database_and_archives(
    tmp_path: Path,
    name: str,
    payload: bytes,
) -> None:
    (tmp_path / name).write_bytes(payload)

    violations: list[str] = []
    closeout._verify_sanitized_evidence_bundle(tmp_path, violations)

    assert any(item.startswith("sanitized_bundle_forbidden_content:") for item in violations)


def test_sanitized_bundle_caps_non_wheel_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(closeout, "_MAX_SANITIZED_NON_ARCHIVE_BYTES", 3)
    (tmp_path / "oversized.txt").write_bytes(b"four")

    violations: list[str] = []
    closeout._verify_sanitized_evidence_bundle(tmp_path, violations)

    assert violations == ["sanitized_bundle_non_archive_too_large:oversized.txt"]


def test_sanitized_bundle_rejects_prefixed_valid_zip_with_compressed_secret(
    tmp_path: Path,
) -> None:
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("auth.json", '{"auth_token":"mvr_' + ("a" * 43) + '"}')
    (tmp_path / "REVIEW.md").write_bytes(b"review preface\n" + archive_bytes.getvalue())

    violations: list[str] = []
    closeout._verify_sanitized_evidence_bundle(tmp_path, violations)

    assert any("sanitized_bundle_forbidden_content:REVIEW.md:archive" in item for item in violations)


def test_exact_sanitized_bundle_rejects_unmanifested_special_entry(
    tmp_path: Path,
) -> None:
    (tmp_path / "safe.json").write_text('{"safe":true}', encoding="utf-8")
    os.mkfifo(tmp_path / "private-ledger-stream")

    violations: list[str] = []
    closeout._verify_sanitized_evidence_bundle(
        tmp_path,
        violations,
        allowed_relative_paths=("safe.json",),
        exact_paths=True,
    )

    assert "sanitized_bundle_special_entry:private-ledger-stream" in violations
    assert "sanitized_bundle_path_set" in violations


def test_sanitized_bundle_can_scan_explicit_assembly_subset(tmp_path: Path) -> None:
    (tmp_path / "retained.json").write_text('{"safe":true}', encoding="utf-8")
    private = tmp_path / "private-runtime"
    private.mkdir()
    (private / "ledger.data").write_bytes(b"SQLite format 3\x00" + (b"x" * 100))

    violations: list[str] = []
    closeout._verify_sanitized_evidence_bundle(
        tmp_path,
        violations,
        allowed_relative_paths=("retained.json",),
    )

    assert violations == []


def test_bundle_manifest_rejects_unknown_file_even_when_manifest_attests_it(
    tmp_path: Path,
) -> None:
    for relative in closeout._FINAL_REVIEW_BUNDLE_FILES:
        if relative == "BUNDLE_MANIFEST.json":
            continue
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"retained")

    def write_manifest() -> None:
        files = []
        for path in sorted(item for item in tmp_path.rglob("*") if item.is_file()):
            if path.name == "BUNDLE_MANIFEST.json":
                continue
            files.append(
                {
                    "path": path.relative_to(tmp_path).as_posix(),
                    "size_bytes": path.stat().st_size,
                    "sha256": closeout.sha256_file(path),
                }
            )
        (tmp_path / "BUNDLE_MANIFEST.json").write_text(
            json.dumps(
                {
                    "schema_version": "work_item_r3_closeout_bundle_manifest.v1",
                    "files": files,
                    "file_count": len(files),
                    "file_list_root_sha256": closeout.canonical_sha256(files),
                }
            ),
            encoding="utf-8",
        )

    write_manifest()
    violations: list[str] = []
    closeout._verify_bundle_manifest(tmp_path, violations)
    assert violations == []

    (tmp_path / "unreviewed.txt").write_text("retained", encoding="utf-8")
    write_manifest()
    violations = []
    closeout._verify_bundle_manifest(tmp_path, violations)
    assert "bundle_manifest_path_set" in violations


def _runtime_observation_projection_fixture(
    root: Path,
) -> tuple[dict[str, object], dict[str, object], dict[str, object], dict[str, object]]:
    evidence = root / "evidence"
    marker = evidence / "runtime/revoked-token-rejected.ok"
    marker.parent.mkdir(parents=True)
    marker.write_bytes(b"true")
    process_identity = "a" * 64
    observations: dict[str, object] = {
        "schema_version": "work_item_r3_runtime_observations.v1",
        "pass": True,
        "bind_address": "127.0.0.1",
        "port": 48713,
        "process_pid": 43123,
        "listener": {
            "inventory": [["127.0.0.1", 48713]],
            "process_listener_count": 1,
            **closeout._EXPECTED_RUNTIME_LISTENER_FLAGS,
        },
        "authentication": dict(closeout._EXPECTED_RUNTIME_AUTHENTICATION),
        "tool_names": list(closeout.AUTHORITATIVE_CANARY_TOOLS),
        "restricted_surface": dict(closeout._EXPECTED_RUNTIME_RESTRICTED_SURFACE),
        "lifecycle": dict(closeout._EXPECTED_RUNTIME_LIFECYCLE),
        "safety": dict(closeout._EXPECTED_RUNTIME_SAFETY),
        "existing_d1_canary_modified": False,
        "existing_service_modified": False,
        "authoritative_activation_outside_ephemeral_test": False,
        "secret_material_included": False,
    }
    observations_path = evidence / "runtime-observations.json"
    observations_path.write_text(json.dumps(observations), encoding="utf-8")
    runtime = {
        "observations_ref": "evidence/runtime-observations.json",
        "observations_sha256": closeout.sha256_file(observations_path),
        "bind_address": observations["bind_address"],
        "port": observations["port"],
        "tool_names": observations["tool_names"],
        "listener": observations["listener"],
        "restricted_surface": observations["restricted_surface"],
        "safety": observations["safety"],
        "existing_d1_canary_modified": False,
        "existing_service_modified": False,
        "authoritative_activation_outside_ephemeral_test": False,
        "authentication": {
            key: closeout._EXPECTED_RUNTIME_AUTHENTICATION[key]
            for key in (
                "no_token_http_status",
                "wrong_token_http_status",
                "correct_token_http_status",
                "revoked_token_http_status",
                "token_file_present_after",
            )
        },
    }
    preflight = {
        "runtime_isolation": {"intended_port": 48713},
        "process_identity_inputs": {
            "pid": 43123,
            "expected_process_identity": process_identity,
        },
    }
    snapshot = {
        "runtime_binding": {"claimed_process_identity": process_identity},
    }
    return observations, runtime, preflight, snapshot


def _verify_runtime_projection_fixture(
    root: Path,
    runtime: dict[str, object],
    preflight: dict[str, object],
    snapshot: dict[str, object],
) -> list[str]:
    violations: list[str] = []
    closeout._verify_runtime_observations_projection(
        runtime,
        root,
        preflight=preflight,
        snapshot=snapshot,
        violations=violations,
    )
    return violations


def test_runtime_observations_require_exact_shape_auth_listener_and_process(
    tmp_path: Path,
) -> None:
    observations, runtime, preflight, snapshot = _runtime_observation_projection_fixture(
        tmp_path
    )
    assert _verify_runtime_projection_fixture(tmp_path, runtime, preflight, snapshot) == []

    observations["unexpected"] = False
    observations_path = tmp_path / "evidence/runtime-observations.json"
    observations_path.write_text(json.dumps(observations), encoding="utf-8")
    runtime["observations_sha256"] = closeout.sha256_file(observations_path)
    violations = _verify_runtime_projection_fixture(tmp_path, runtime, preflight, snapshot)
    assert "runtime_observations_binding" in violations

    observations.pop("unexpected")
    authentication = observations["authentication"]
    assert isinstance(authentication, dict)
    authentication["replacement_token_http_status"] = 401
    observations_path.write_text(json.dumps(observations), encoding="utf-8")
    runtime["observations_sha256"] = closeout.sha256_file(observations_path)
    violations = _verify_runtime_projection_fixture(tmp_path, runtime, preflight, snapshot)
    assert "runtime_observations_binding" in violations

    authentication["replacement_token_http_status"] = 200
    observations["process_pid"] = 43124
    observations_path.write_text(json.dumps(observations), encoding="utf-8")
    runtime["observations_sha256"] = closeout.sha256_file(observations_path)
    violations = _verify_runtime_projection_fixture(tmp_path, runtime, preflight, snapshot)
    assert "runtime_observations_process_listener_binding" in violations

    observations["process_pid"] = 43123
    listener = observations["listener"]
    assert isinstance(listener, dict)
    listener["inventory"] = [["0.0.0.0", 48713]]
    runtime["listener"] = listener
    observations_path.write_text(json.dumps(observations), encoding="utf-8")
    runtime["observations_sha256"] = closeout.sha256_file(observations_path)
    violations = _verify_runtime_projection_fixture(tmp_path, runtime, preflight, snapshot)
    assert "runtime_observations_process_listener_binding" in violations


def test_runtime_observations_require_exact_revoked_token_marker(tmp_path: Path) -> None:
    _observations, runtime, preflight, snapshot = _runtime_observation_projection_fixture(
        tmp_path
    )
    (tmp_path / "evidence/runtime/revoked-token-rejected.ok").write_bytes(b"true\n")

    violations = _verify_runtime_projection_fixture(tmp_path, runtime, preflight, snapshot)

    assert "runtime_revoked_token_marker_content" in violations


def test_closeout_rejects_reduced_verification_commands_and_ignored_audits() -> None:
    assert not closeout._command_matches_slot(
        "full_pytest",
        ["python3", "-m", "pytest", "-q", "tests/test_work_item_r3_closeout.py"],
    )
    assert not closeout._command_matches_slot(
        "concurrency_tests",
        ["python3", "-m", "pytest", "-q", "tests/test_work_item_r3_closeout.py"],
    )
    assert not closeout._command_matches_slot(
        "pip_audit",
        ["python3", "-m", "pip_audit", "--ignore-vuln", "CVE-2099-0001"],
    )
    assert not closeout._command_matches_slot(
        "ruff",
        ["python3", "-m", "ruff", "check", "runner/work_item_governance/closeout.py"],
    )


def test_closeout_binds_token_generation_digest_to_retained_preflight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    authentication = {
        "auth_mode": "token",
        "token_source": "isolated_xdg_config_auth_json_0600",
        "token_generation_algorithm": "os_csprng_secrets_token_urlsafe_32",
        "token_entropy_bits": 256,
        "token_generation_evidence_digest": "a" * 64,
        "token_file_mode": "0600",
        "token_parent_mode": "0700",
        "weak_token_configuration_rejected": True,
        "token_absent_from_public_surfaces": True,
    }
    preflight = {"authentication": authentication}
    (evidence / "preflight-receipt.json").write_text(
        json.dumps(preflight),
        encoding="utf-8",
    )
    receipt_authentication = {
        "auth_mode": authentication["auth_mode"],
        "token_source": authentication["token_source"],
        "token_generation_algorithm": authentication["token_generation_algorithm"],
        "token_entropy_bits": authentication["token_entropy_bits"],
        "token_generation_evidence_digest": authentication[
            "token_generation_evidence_digest"
        ],
        "auth_file_mode": authentication["token_file_mode"],
        "auth_parent_directories_mode": authentication["token_parent_mode"],
        "weak_token_configuration_rejected": True,
        "token_absent_from_public_surfaces": True,
    }
    receipt = {
        "authentication": receipt_authentication,
        "fresh_ledger": {"preflight_receipt_digest": closeout.canonical_sha256(preflight)},
    }
    monkeypatch.setattr(closeout, "validate_governance_record", lambda *_args: None)

    violations: list[str] = []
    closeout._verify_authentication_preflight_evidence(receipt, tmp_path, violations)
    assert violations == []

    receipt_authentication["token_generation_evidence_digest"] = "b" * 64
    closeout._verify_authentication_preflight_evidence(receipt, tmp_path, violations)
    assert "preflight_authentication_binding" in violations


def test_closeout_binds_runtime_contracts_to_authorized_freeze_manifest() -> None:
    project_root = Path(__file__).resolve().parents[1]
    spec_binding = {
        field: closeout.sha256_file(project_root / relative_path)
        for field, relative_path in closeout._SPEC_BINDING_PATHS.items()
    }
    receipt = {"spec_binding": spec_binding}

    violations: list[str] = []
    closeout._verify_spec_binding(receipt, project_root, violations)
    assert violations == []

    spec_binding["write_path_inventory_sha256"] = "0" * 64
    closeout._verify_spec_binding(receipt, project_root, violations)
    assert "spec_digest_mismatch:write_path_inventory_sha256" in violations
    assert "spec_freeze_binding:write_path_inventory_sha256" in violations


def test_bandit_evidence_retains_baseline_findings_but_blocks_high_severity() -> None:
    payload = {
        "errors": [],
        "metrics": {"_totals": {"SEVERITY.HIGH": 0, "SEVERITY.MEDIUM": 14}},
        "results": [{"issue_severity": "MEDIUM"}],
    }
    assert closeout._command_output_matches_slot(
        "bandit_changed_scope",
        stdout=json.dumps(payload),
        stderr="",
    )
    payload["metrics"]["_totals"]["SEVERITY.HIGH"] = 1
    assert not closeout._command_output_matches_slot(
        "bandit_changed_scope",
        stdout=json.dumps(payload),
        stderr="",
    )
    duplicate_metrics = (
        '{"errors":[],"metrics":{"_totals":{"SEVERITY.HIGH":1}},'
        '"metrics":{"_totals":{"SEVERITY.HIGH":0}},"results":[]}'
    )
    assert not closeout._command_output_matches_slot(
        "bandit_changed_scope",
        stdout=duplicate_metrics,
        stderr="",
    )
    assert not closeout._command_output_matches_slot(
        "review_bundle_accessibility",
        stdout='{"pass":false,"pass":true}',
        stderr="",
    )
