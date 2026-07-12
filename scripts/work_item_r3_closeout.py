from __future__ import annotations

if "_R3_TRUSTED_BOOTSTRAP_CAPABILITY" not in globals():
    _R3_TRUSTED_BOOTSTRAP_CAPABILITY = None

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess  # nosec B404
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runner.work_item_governance.activation import AUTHORITATIVE_CANARY_TOOLS
from runner.work_item_governance.canonical import canonical_json, canonical_sha256, sha256_file
from runner.work_item_governance.closeout import (
    REQUIRED_VERIFICATION_NAMES,
    _FINAL_REVIEW_BUNDLE_FILES,
    _LEASE_CHECK_EVIDENCE_BINDINGS,
    _SPEC_BINDING_PATHS,
    _load_strict_json,
    _verify_sanitized_evidence_bundle,
    verify_r2_closeout_receipt,
)
from runner.work_item_governance.preview import parse_timestamp
from runner.work_item_governance.source_binding import (
    _authority_sanitized_environment,
    _inspect_git_checkout,
    _trusted_git_for_checkout,
    verify_runtime_source_artifacts,
)
from runner.work_item_governance.toolchain_binding import measure_closeout_toolchain


COMMAND_EVIDENCE_SCHEMA = "work_item_closeout_command_evidence.v2"

_COMMAND_ENVIRONMENT_REMOVALS = (
    "PYTEST_ADDOPTS",
    "PYTEST_PLUGINS",
    "PYTHONPATH",
    "PYTHONSTARTUP",
    "PYTHONINSPECT",
    "COVERAGE_PROCESS_START",
)
_COMMAND_ENVIRONMENT_FORCED = {
    "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
    "PYTHONHASHSEED": "0",
    "PYTHONDONTWRITEBYTECODE": "1",
}
_COMMAND_ENVIRONMENT_PREFIX_REMOVALS = (
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
)
_PROTECTED_ASSET_SCHEMA_ORDER = (
    "AGENTS.md",
    "AGENTS - 副本.amd",
    "AGENTS - 副本.md:Zone.Identifier",
    "AGENTS.md:Zone.Identifier",
)
_PROTECTED_ASSET_PATHS = frozenset(_PROTECTED_ASSET_SCHEMA_ORDER)

_RUNTIME_EVIDENCE_JSON_FILES = (
    "evidence/preflight-receipt.json",
    "evidence/claimed-activation-envelope.json",
    "evidence/synthetic-fixture.json",
    "evidence/ephemeral-ledger-closeout.json",
    "evidence/lease/activation-lease-snapshot.json",
    "evidence/lease/activation-lease-events.json",
    "evidence/lease/runtime-source-attestation.json",
    "evidence/runtime-observations.json",
)
_RUNTIME_COMMAND_EVIDENCE_REF = (
    "evidence/commands/runtime-isolation-smoke-command.json"
)
_EXPECTED_RUNTIME_SAFETY = {
    "existing_canary_restarted": False,
    "a1_snapshot_refreshed": False,
    "authoritative_activation_performed": False,
    "isolated_conformance_harness_used": True,
    "deployed_canary_activation_performed": False,
    "existing_service_modified": False,
    "stable_runtime_modified": False,
    "real_work_item_used": False,
    "push_performed": False,
    "stable_promotion_performed": False,
}


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    target = path.expanduser().resolve()
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(canonical_json(payload))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, target)
        os.chmod(target, 0o600)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def _source_snapshot(cwd: Path, *, environment: dict[str, str]) -> dict[str, Any]:
    errors: list[str] = []
    requested_root = cwd.expanduser().resolve()
    repository_root = requested_root
    try:
        git = _trusted_git_for_checkout(requested_root, environment=environment)
    except Exception as exc:  # fail closed while retaining a completed-process record
        errors.append(f"trusted_git_checkout:{type(exc).__name__}")
        return {
            "repository_root": repository_root.as_posix(),
            "requested_checkout_root": requested_root.as_posix(),
            "commit": None,
            "tree": None,
            "candidate_clean": False,
            "tracked_changes": [],
            "staged_changes": [],
            "untracked_changes": [],
            "allowed_protected_asset_changes": [],
            "assume_unchanged_paths": [],
            "skip_worktree_paths": [],
            "ignored_execution_overlays": [],
            "untracked_execution_overlays": [],
            "object_mismatches": [],
            "git_object_manifest_digest": None,
            "git_object_format": None,
            "git_executable": None,
            "inspection_errors": errors,
        }

    def _revision(revision: str) -> str | None:
        try:
            return git.run(repository_root, "rev-parse", "--verify", revision).strip()
        except Exception as exc:
            errors.append(f"git_revision:{revision}:{type(exc).__name__}")
            return None

    try:
        tracked = sorted(
            path for path in git.run(repository_root, "diff", "--name-only", "-z").split("\0") if path
        )
        staged = sorted(
            path
            for path in git.run(repository_root, "diff", "--cached", "--name-only", "-z").split("\0")
            if path
        )
        untracked = sorted(
            path
            for path in git.run(
                repository_root,
                "ls-files",
                "--others",
                "--exclude-standard",
                "-z",
            ).split("\0")
            if path
        )
        exact_state = _inspect_git_checkout(
            repository_root,
            git=git,
            pathspecs=(),
            excluded_paths=_PROTECTED_ASSET_PATHS,
        )
    except Exception as exc:
        errors.append(f"git_inventory:{type(exc).__name__}")
        tracked, staged, untracked = [], [], []
        exact_state = {
            "object_format": None,
            "manifest_digest": None,
            "object_mismatches": [],
            "assume_unchanged_paths": [],
            "skip_worktree_paths": [],
            "ignored_execution_overlays": [],
            "untracked_execution_overlays": [],
        }
    changed_paths = set(tracked) | set(staged) | set(untracked)
    protected_changes = sorted(changed_paths & _PROTECTED_ASSET_PATHS)
    candidate_tracked = sorted(set(tracked) - _PROTECTED_ASSET_PATHS)
    candidate_staged = sorted(set(staged) - _PROTECTED_ASSET_PATHS)
    candidate_untracked = sorted(set(untracked) - _PROTECTED_ASSET_PATHS)
    exact_violations = any(
        exact_state[key]
        for key in (
            "object_mismatches",
            "assume_unchanged_paths",
            "skip_worktree_paths",
            "ignored_execution_overlays",
            "untracked_execution_overlays",
        )
    )
    return {
        "repository_root": repository_root.as_posix(),
        "requested_checkout_root": requested_root.as_posix(),
        "commit": _revision("HEAD"),
        "tree": _revision("HEAD^{tree}"),
        "candidate_clean": not errors
        and not candidate_tracked
        and not candidate_staged
        and not candidate_untracked
        and not exact_violations,
        "tracked_changes": candidate_tracked,
        "staged_changes": candidate_staged,
        "untracked_changes": candidate_untracked,
        "allowed_protected_asset_changes": protected_changes,
        "assume_unchanged_paths": exact_state["assume_unchanged_paths"],
        "skip_worktree_paths": exact_state["skip_worktree_paths"],
        "ignored_execution_overlays": exact_state["ignored_execution_overlays"],
        "untracked_execution_overlays": exact_state[
            "untracked_execution_overlays"
        ],
        "object_mismatches": exact_state["object_mismatches"],
        "git_object_manifest_digest": exact_state["manifest_digest"],
        "git_object_format": exact_state["object_format"],
        "git_executable": git.public_binding(),
        "inspection_errors": errors,
    }


def _command_environment(cwd: Path) -> tuple[dict[str, str], dict[str, Any]]:
    environment = dict(os.environ)
    removed_keys = {key: key in environment for key in _COMMAND_ENVIRONMENT_REMOVALS}
    for key in _COMMAND_ENVIRONMENT_REMOVALS:
        environment.pop(key, None)
    prefix_removed = tuple(
        sorted(
            key
            for key in environment
            if key.startswith(_COMMAND_ENVIRONMENT_PREFIX_REMOVALS)
        )
    )
    for key in prefix_removed:
        environment.pop(key, None)
    environment, authority_removed = _authority_sanitized_environment(environment)
    environment.update(_COMMAND_ENVIRONMENT_FORCED)
    environment.update(
        {
            "PATH": f"{(cwd / '.venv' / 'bin').resolve().as_posix()}:{os.defpath}",
            "PIP_CONFIG_FILE": os.devnull,
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        }
    )
    policy = {
        "removed_keys": removed_keys,
        "forced_values": dict(_COMMAND_ENVIRONMENT_FORCED),
        "authority_removed_keys": sorted(set(prefix_removed) | set(authority_removed)),
        "authority_prefixes": list(_COMMAND_ENVIRONMENT_PREFIX_REMOVALS),
        "executable_path": environment["PATH"],
        "pip_config_file": environment["PIP_CONFIG_FILE"],
        "git_authority_environment_scrubbed": True,
        "loader_authority_environment_scrubbed": True,
    }
    return environment, policy


def _resolve_executable(command: str, *, environment: dict[str, str], cwd: Path) -> Path | None:
    if os.sep in command or (os.altsep is not None and os.altsep in command):
        candidate = Path(command)
        if not candidate.is_absolute():
            candidate = cwd / candidate
        launcher = candidate.absolute()
        return launcher if launcher.is_file() else None
    located = shutil.which(command, path=environment.get("PATH"))
    return Path(located).absolute() if located is not None else None


def _process_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def run_command(
    *,
    name: str,
    output: Path,
    command: list[str],
    startup_attestation: dict[str, Any],
) -> int:
    if not command:
        raise ValueError("command argv is required")
    if (
        not isinstance(startup_attestation, dict)
        or startup_attestation.get("schema_version")
        != "work_item_r3_preimport_attestation.v1"
        or startup_attestation.get("accepted") is not True
    ):
        raise ValueError("A trusted R3 pre-import attestation is required.")
    cwd = Path.cwd().resolve()
    environment, environment_policy = _command_environment(cwd)
    trusted_launcher_child = (
        len(command) >= 6
        and Path(command[0]).absolute() == Path("/usr/bin/python3.12")
        and command[1:5]
        == ["-I", "-S", "-B", "-"]
        and command[5] == "."
    )
    process_environment = dict(environment)
    trusted_launcher_removed_keys: list[str] = []
    if trusted_launcher_child:
        trusted_launcher_removed_keys = sorted(
            key
            for key in process_environment
            if key.startswith(("GIT_", "LD_", "DYLD_", "PYTHON"))
        )
        for key in trusted_launcher_removed_keys:
            process_environment.pop(key, None)
    environment_policy["trusted_launcher_child"] = trusted_launcher_child
    environment_policy["trusted_launcher_removed_keys"] = trusted_launcher_removed_keys
    trusted_launcher_stdin: dict[str, Any] | None = None
    trusted_launcher_source: str | None = None
    trusted_launcher_error: str | None = None
    if trusted_launcher_child:
        try:
            git = _trusted_git_for_checkout(cwd, environment=environment)
            launcher_relative = "scripts/work_item_r3_trusted_launcher.py"
            trusted_launcher_source = git.run(
                cwd,
                "show",
                f"HEAD:{launcher_relative}",
            )
            trusted_launcher_stdin = {
                "execution_source": "trusted_git_blob_stdin",
                "relative_path": launcher_relative,
                "commit": git.run(cwd, "rev-parse", "HEAD").strip(),
                "tree": git.run(cwd, "rev-parse", "HEAD^{tree}").strip(),
                "blob_oid": git.run(
                    cwd,
                    "rev-parse",
                    f"HEAD:{launcher_relative}",
                ).strip(),
                "sha256": hashlib.sha256(
                    trusted_launcher_source.encode("utf-8")
                ).hexdigest(),
            }
        except Exception as exc:
            trusted_launcher_error = getattr(exc, "code", type(exc).__name__)
    source_before = _source_snapshot(cwd, environment=environment)
    try:
        toolchain_before: dict[str, Any] = measure_closeout_toolchain(cwd)
        toolchain_error_before: str | None = None
    except Exception as exc:  # fail closed while retaining the provenance record
        toolchain_before = {}
        toolchain_error_before = getattr(exc, "code", type(exc).__name__)
    executable_launcher = _resolve_executable(command[0], environment=environment, cwd=cwd)
    resolved_executable = (
        executable_launcher.resolve() if executable_launcher is not None else None
    )
    launcher_sha256 = (
        sha256_file(executable_launcher) if executable_launcher is not None else None
    )
    launcher_symlink_target = (
        os.readlink(executable_launcher)
        if executable_launcher is not None and executable_launcher.is_symlink()
        else None
    )
    resolved_executable_sha256 = (
        sha256_file(resolved_executable) if resolved_executable is not None else None
    )
    started_at = _timestamp()
    started_monotonic_ns = time.monotonic_ns()
    if trusted_launcher_error is not None:
        process_exit_code = 126
        stdout = ""
        stderr = f"Trusted launcher Git blob verification failed: {trusted_launcher_error}"
    elif toolchain_error_before is not None:
        process_exit_code = 126
        stdout = ""
        stderr = f"Toolchain verification failed: {toolchain_error_before}"
    elif executable_launcher is None or resolved_executable is None:
        process_exit_code = 127
        stdout = ""
        stderr = f"Executable not found: {command[0]}"
    else:
        try:
            completed = subprocess.run(  # nosec B603
                [executable_launcher.as_posix(), *command[1:]],
                cwd=cwd,
                check=False,
                capture_output=True,
                text=True,
                env=process_environment,
                input=trusted_launcher_source,
                timeout=900,
            )
            process_exit_code = completed.returncode
            stdout = completed.stdout
            stderr = completed.stderr
        except subprocess.TimeoutExpired as error:
            process_exit_code = 124
            stdout = _process_text(error.stdout)
            stderr = _process_text(error.stderr) + "Command timed out after 900 seconds"
    ended_observed_at = _timestamp()
    ended_monotonic_ns = time.monotonic_ns()
    wall_clock_rollback_clamped = parse_timestamp(
        ended_observed_at,
        "command.ended_observed_at",
    ) < parse_timestamp(started_at, "command.started_at")
    ended_at = started_at if wall_clock_rollback_clamped else ended_observed_at
    monotonic_duration_ns = max(0, ended_monotonic_ns - started_monotonic_ns)
    source_after = _source_snapshot(cwd, environment=environment)
    try:
        toolchain_after: dict[str, Any] = measure_closeout_toolchain(cwd)
        toolchain_error_after: str | None = None
    except Exception as exc:  # fail closed while retaining the provenance record
        toolchain_after = {}
        toolchain_error_after = getattr(exc, "code", type(exc).__name__)
    launcher_sha256_after = (
        sha256_file(executable_launcher)
        if executable_launcher is not None and executable_launcher.is_file()
        else None
    )
    launcher_symlink_target_after = (
        os.readlink(executable_launcher)
        if executable_launcher is not None and executable_launcher.is_symlink()
        else None
    )
    resolved_executable_sha256_after = (
        sha256_file(resolved_executable)
        if resolved_executable is not None and resolved_executable.is_file()
        else None
    )
    source_binding_match = (
        source_before["commit"] is not None
        and source_before["commit"] == source_after["commit"]
        and source_before["tree"] is not None
        and source_before["tree"] == source_after["tree"]
    )
    executable_unchanged = (
        launcher_sha256 is not None
        and launcher_sha256 == launcher_sha256_after
        and launcher_symlink_target == launcher_symlink_target_after
        and resolved_executable_sha256 is not None
        and resolved_executable_sha256 == resolved_executable_sha256_after
    )
    toolchain_unchanged = (
        toolchain_error_before is None
        and toolchain_error_after is None
        and toolchain_before == toolchain_after
    )
    provenance_valid = (
        source_before["candidate_clean"] is True
        and source_after["candidate_clean"] is True
        and source_binding_match
        and executable_unchanged
        and toolchain_unchanged
    )
    passed = process_exit_code == 0 and provenance_valid
    evidence_exit_code = process_exit_code if process_exit_code != 0 else (0 if passed else 1)
    evidence = {
        "schema_version": COMMAND_EVIDENCE_SCHEMA,
        "name": name,
        "argv": command,
        "cwd": cwd.as_posix(),
        "started_at": started_at,
        "ended_at": ended_at,
        "monotonic_duration_ns": monotonic_duration_ns,
        "wall_clock_rollback_clamped": wall_clock_rollback_clamped,
        "exit_code": evidence_exit_code,
        "process_exit_code": process_exit_code,
        "passed": passed,
        "stdout": stdout,
        "stderr": stderr,
        "source_before": source_before,
        "source_after": source_after,
        "source_binding_match": source_binding_match,
        "executable": {
            "requested": command[0],
            "launcher_path": (
                executable_launcher.as_posix()
                if executable_launcher is not None
                else None
            ),
            "launcher_sha256": launcher_sha256,
            "launcher_sha256_after": launcher_sha256_after,
            "launcher_symlink_target": launcher_symlink_target,
            "launcher_symlink_target_after": launcher_symlink_target_after,
            "resolved_path": (
                resolved_executable.as_posix() if resolved_executable is not None else None
            ),
            "resolved_sha256": resolved_executable_sha256,
            "resolved_sha256_after": resolved_executable_sha256_after,
            "unchanged": executable_unchanged,
        },
        "toolchain": {
            "before": toolchain_before,
            "after": toolchain_after,
            "error_before": toolchain_error_before,
            "error_after": toolchain_error_after,
            "unchanged": toolchain_unchanged,
        },
        "environment_policy": environment_policy,
        "preimport_attestation": startup_attestation,
        "trusted_launcher_stdin": trusted_launcher_stdin,
    }
    _write_json(output, evidence)
    return evidence_exit_code


def protected_assets_check(expected: list[str]) -> int:
    records: list[dict[str, Any]] = []
    passed = True
    for item in expected:
        path_text, separator, expected_sha256 = item.rpartition("=")
        path = Path(path_text)
        valid = bool(separator and path.is_file() and sha256_file(path) == expected_sha256)
        passed = passed and valid
        records.append(
            {
                "path": path_text,
                "expected_sha256": expected_sha256,
                "actual_sha256": sha256_file(path) if path.is_file() else None,
                "match": valid,
            }
        )
    print(canonical_json({"pass": passed, "assets": records}))
    return 0 if passed else 1


def bundle_access_check(*, bundle_root: Path, required: list[str]) -> int:
    root = bundle_root.expanduser().resolve()
    records: list[dict[str, Any]] = []
    passed = True
    for relative_text in required:
        target = (root / relative_text).resolve()
        try:
            target.relative_to(root)
            within_root = True
        except ValueError:
            within_root = False
        valid = within_root and target.is_file() and target.stat().st_size > 0
        passed = passed and valid
        records.append(
            {
                "path": relative_text,
                "readable": valid,
                "sha256": sha256_file(target) if valid else None,
            }
        )
    sanitization_findings: list[str] = []
    _verify_sanitized_evidence_bundle(
        root,
        sanitization_findings,
        allowed_relative_paths=required,
    )
    passed = passed and not sanitization_findings
    print(
        canonical_json(
            {
                "pass": passed,
                "files": records,
                "sanitization_findings": sanitization_findings,
            }
        )
    )
    return 0 if passed else 1


def wheel_inventory(*, checkout: Path, wheel: Path, output: Path) -> int:
    measured = verify_runtime_source_artifacts(
        checkout_root=checkout,
        wheel_artifact=wheel,
    )
    payload = {
        "schema_version": "work_item_runtime_wheel_inventory.v1",
        "source_binding": measured.source_binding,
        "file_manifest_digest": measured.file_manifest_digest,
        "wheel_sha256": sha256_file(wheel),
        "wheel_size_bytes": wheel.stat().st_size,
        "verified": True,
    }
    _write_json(output, payload)
    return 0


def assemble_runtime_evidence(
    *,
    runtime_root: Path,
    bundle_root: Path,
    runtime_command_evidence: Path,
) -> int:
    """Copy only reviewed runtime outputs and derive the sanitized evidence records.

    The pytest runtime tree deliberately contains the private Ledger, Backup, Token
    directory and exact source checkout.  This command never copies that tree.  It
    accepts only the explicit JSON/marker allowlist below, validates their cross-
    bindings, and writes canonical JSON into the review bundle.
    """

    source_root = runtime_root.expanduser().resolve()
    target_root = bundle_root.expanduser().resolve()
    command_path = runtime_command_evidence.expanduser().resolve()
    expected_command_path = (target_root / _RUNTIME_COMMAND_EVIDENCE_REF).resolve()
    if command_path != expected_command_path:
        raise ValueError("Runtime command evidence must use the frozen bundle path.")
    if not source_root.is_dir() or not command_path.is_file() or command_path.is_symlink():
        raise ValueError("Runtime root or completed-process evidence is unavailable.")

    retained: dict[str, Any] = {}
    for relative in _RUNTIME_EVIDENCE_JSON_FILES:
        source = (source_root / relative).resolve()
        try:
            source.relative_to(source_root)
        except ValueError as exc:
            raise ValueError(f"Runtime evidence escapes its root: {relative}") from exc
        if not source.is_file() or source.is_symlink():
            raise ValueError(f"Runtime evidence is unavailable or a symlink: {relative}")
        retained[relative] = _load_strict_json(source)

    marker_source = (source_root / "evidence/revoked-token-rejected.ok").resolve()
    try:
        marker_source.relative_to(source_root)
    except ValueError as exc:
        raise ValueError("The revoked-Token marker escapes the runtime root.") from exc
    if (
        not marker_source.is_file()
        or marker_source.is_symlink()
        or marker_source.read_text(encoding="utf-8") != "true"
    ):
        raise ValueError("The revoked-Token rejection marker is missing or invalid.")

    preflight = retained["evidence/preflight-receipt.json"]
    snapshot = retained["evidence/lease/activation-lease-snapshot.json"]
    source_attestation = retained["evidence/lease/runtime-source-attestation.json"]
    observations = retained["evidence/runtime-observations.json"]
    command = _load_strict_json(command_path)
    expected_observation_keys = {
        "schema_version",
        "pass",
        "bind_address",
        "port",
        "process_pid",
        "listener",
        "authentication",
        "tool_names",
        "restricted_surface",
        "lifecycle",
        "safety",
        "existing_d1_canary_modified",
        "existing_service_modified",
        "authoritative_activation_outside_ephemeral_test",
        "secret_material_included",
    }
    if not isinstance(observations, dict) or set(observations) != expected_observation_keys:
        raise ValueError("Runtime observations do not match the frozen evidence shape.")
    expected_authentication = {
        "no_token_http_status": 401,
        "wrong_token_http_status": 401,
        "correct_token_http_status": 200,
        "revoked_token_http_status": 401,
        "replacement_token_http_status": 200,
        "token_file_present_after": False,
    }
    expected_restricted_surface = {
        "definition_dispatch_exact_match": True,
        "hidden_jsonrpc_call_rejected": True,
        "direct_alias_rejected": True,
        "actions_disabled": True,
        "agent_dispatch_enforced": True,
    }
    expected_lifecycle = {
        "accepted_state_observed": True,
        "guard_failure_observed": True,
        "lease_final_status": "closed",
        "shadow_recovery_verified": True,
    }
    intended_port = preflight.get("runtime_isolation", {}).get("intended_port")
    listener = observations.get("listener")
    if (
        observations.get("schema_version") != "work_item_r3_runtime_observations.v1"
        or observations.get("pass") is not True
        or observations.get("bind_address") != "127.0.0.1"
        or observations.get("port") != intended_port
        or isinstance(observations.get("process_pid"), bool)
        or not isinstance(observations.get("process_pid"), int)
        or observations["process_pid"] <= 0
        or observations.get("authentication") != expected_authentication
        or observations.get("tool_names") != list(AUTHORITATIVE_CANARY_TOOLS)
        or observations.get("restricted_surface") != expected_restricted_surface
        or observations.get("lifecycle") != expected_lifecycle
        or observations.get("safety") != _EXPECTED_RUNTIME_SAFETY
        or observations.get("existing_d1_canary_modified") is not False
        or observations.get("existing_service_modified") is not False
        or observations.get("authoritative_activation_outside_ephemeral_test") is not False
        or observations.get("secret_material_included") is not False
        or not isinstance(listener, dict)
        or listener
        != {
            "inventory": [["127.0.0.1", intended_port]],
            "process_listener_count": 1,
            "public_endpoint_created": False,
            "relay_enabled": False,
            "tunnel_enabled": False,
            "proxy_enabled": False,
        }
    ):
        raise ValueError("Runtime observations did not pass the frozen conformance checks.")

    source_binding = preflight.get("source_binding")
    snapshot_runtime = snapshot.get("runtime_binding")
    if (
        not isinstance(source_binding, dict)
        or snapshot.get("source_binding") != source_binding
        or source_attestation.get("verified") is not True
        or source_attestation.get("source_binding") != source_binding
        or snapshot.get("status") != "closed"
        or not isinstance(snapshot_runtime, dict)
        or preflight.get("runtime_isolation", {}).get("canary_root_resolved_path")
        != source_root.as_posix()
    ):
        raise ValueError("Runtime Preflight, Lease and source evidence are not cross-bound.")
    if (
        command.get("schema_version") != COMMAND_EVIDENCE_SCHEMA
        or command.get("name") != "runtime_isolation_smoke"
        or command.get("passed") is not True
        or command.get("exit_code") != 0
    ):
        raise ValueError("Runtime completed-process evidence is absent or failed.")
    for snapshot_name in ("source_before", "source_after"):
        measured = command.get(snapshot_name)
        if (
            not isinstance(measured, dict)
            or measured.get("candidate_clean") is not True
            or measured.get("commit") != source_binding.get("implementation_commit")
            or measured.get("tree") != source_binding.get("implementation_tree")
        ):
            raise ValueError("Runtime command provenance differs from the exact source binding.")

    backup = preflight.get("pre_activation_backup")
    if not isinstance(backup, dict):
        raise ValueError("Pre-activation Backup receipt is unavailable.")
    backup_receipt = {
        "schema_version": "work_item_r3_pre_activation_backup_receipt.v1",
        "api": backup.get("api"),
        "backup_sha256": backup.get("backup_sha256"),
        "database_generation": backup.get("database_generation"),
        "ledger_schema_version": backup.get("schema_version"),
        "integrity_check": backup.get("integrity_check"),
        "foreign_key_violations": backup.get("foreign_key_violations"),
        "mode": backup.get("mode"),
        "backup_bytes_in_sanitized_bundle": False,
    }
    backup_core = {
        "api": backup_receipt["api"],
        "backup_sha256": backup_receipt["backup_sha256"],
        "database_generation": backup_receipt["database_generation"],
        "schema_version": backup_receipt["ledger_schema_version"],
        "integrity_check": backup_receipt["integrity_check"],
        "foreign_key_violations": backup_receipt["foreign_key_violations"],
        "mode": backup_receipt["mode"],
    }
    if canonical_sha256(backup_core) != backup.get("receipt_digest"):
        raise ValueError("Pre-activation Backup receipt digest does not recompute.")

    runtime_evidence = {
        "schema_version": "work_item_r3_runtime_isolation_evidence.v1",
        "source": source_binding,
        "pass": True,
        "bind_address": observations["bind_address"],
        "port": observations["port"],
        "listed_tools": len(observations["tool_names"]),
        "tool_names": observations["tool_names"],
        "command_evidence_ref": _RUNTIME_COMMAND_EVIDENCE_REF,
        "command_evidence_sha256": sha256_file(command_path),
        "observations_ref": "evidence/runtime-observations.json",
        "observations_sha256": canonical_sha256(observations),
        "authentication": {
            key: observations["authentication"][key]
            for key in (
                "no_token_http_status",
                "wrong_token_http_status",
                "correct_token_http_status",
                "revoked_token_http_status",
                "token_file_present_after",
            )
        },
        "source_attestation": source_attestation,
        "lease": {
            "lease_id": snapshot["lease_id"],
            "claimed_process_identity": snapshot_runtime["claimed_process_identity"],
            "listener_attestation_digest": snapshot_runtime["listener_attestation_digest"],
            "authenticated_request_context_binding_digest": snapshot_runtime[
                "authenticated_request_context_binding_digest"
            ],
            "final_status": snapshot["status"],
            "final_state_version": snapshot["state_version"],
        },
        "listener": listener,
        "restricted_surface": observations["restricted_surface"],
        "lifecycle": observations["lifecycle"],
        "safety": observations["safety"],
        "existing_d1_canary_modified": observations["existing_d1_canary_modified"],
        "existing_service_modified": observations["existing_service_modified"],
        "authoritative_activation_outside_ephemeral_test": observations[
            "authoritative_activation_outside_ephemeral_test"
        ],
    }

    for relative, payload in retained.items():
        _write_json(target_root / relative, payload)
    marker_target = target_root / "evidence/runtime/revoked-token-rejected.ok"
    marker_target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    marker_target.write_text("true", encoding="utf-8")
    os.chmod(marker_target, 0o600)
    _write_json(
        target_root / "evidence/pre-activation-backup-receipt.json",
        backup_receipt,
    )
    _write_json(target_root / "evidence/runtime-isolation-evidence.json", runtime_evidence)
    sanitization_findings: list[str] = []
    assembled_relative_paths = (
        *_RUNTIME_EVIDENCE_JSON_FILES,
        _RUNTIME_COMMAND_EVIDENCE_REF,
        "evidence/runtime/revoked-token-rejected.ok",
        "evidence/pre-activation-backup-receipt.json",
        "evidence/runtime-isolation-evidence.json",
    )
    _verify_sanitized_evidence_bundle(
        target_root,
        sanitization_findings,
        allowed_relative_paths=assembled_relative_paths,
    )
    if sanitization_findings:
        raise ValueError(f"Assembled runtime evidence is not sanitized: {sanitization_findings}")
    print(
        canonical_json(
            {
                "pass": True,
                "runtime_observations_sha256": canonical_sha256(observations),
                "runtime_evidence_sha256": canonical_sha256(runtime_evidence),
                "retained_runtime_json_files": list(_RUNTIME_EVIDENCE_JSON_FILES),
                "private_runtime_tree_copied": False,
            }
        )
    )
    return 0


def bundle_manifest(*, bundle_root: Path, output: Path) -> int:
    root = bundle_root.expanduser().resolve()
    target = output.expanduser().resolve()
    if target != (root / "BUNDLE_MANIFEST.json").resolve():
        raise ValueError("Bundle Manifest must use the frozen final path.")
    sanitization_findings: list[str] = []
    expected_before_manifest = tuple(
        path for path in _FINAL_REVIEW_BUNDLE_FILES if path != "BUNDLE_MANIFEST.json"
    )
    _verify_sanitized_evidence_bundle(
        root,
        sanitization_findings,
        allowed_relative_paths=expected_before_manifest,
        exact_paths=True,
    )
    if sanitization_findings:
        raise ValueError(f"Review bundle is not sanitized: {sanitization_findings}")
    files: list[dict[str, Any]] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.resolve() == target:
            continue
        relative = path.relative_to(root).as_posix()
        files.append(
            {
                "path": relative,
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    payload = {
        "schema_version": "work_item_r3_closeout_bundle_manifest.v1",
        "generated_at": _timestamp(),
        "files": files,
        "file_count": len(files),
        "file_list_root_sha256": canonical_sha256(files),
    }
    _write_json(target, payload)
    return 0


def verify_receipt(*, receipt: Path, bundle_root: Path, project_root: Path) -> int:
    payload = _load_strict_json(receipt)
    result = verify_r2_closeout_receipt(
        payload,
        evidence_root=bundle_root,
        project_root=project_root,
    )
    print(canonical_json({"pass": bool(1), "verification": result}))
    return 0


def build_receipt(*, bundle_root: Path, project_root: Path, output: Path) -> int:
    """Derive the retained Closeout Receipt from strict retained evidence."""

    root = bundle_root.expanduser().resolve()
    project = project_root.expanduser().resolve()
    if output.expanduser().resolve() != (root / "R3_CLOSEOUT_RECEIPT.json").resolve():
        raise ValueError("Closeout Receipt must use the frozen final path.")

    def load(relative: str) -> Any:
        return _load_strict_json(root / relative)

    preflight = load("evidence/preflight-receipt.json")
    snapshot = load("evidence/lease/activation-lease-snapshot.json")
    events = load("evidence/lease/activation-lease-events.json")
    runtime = load("evidence/runtime-isolation-evidence.json")
    backup = load("evidence/pre-activation-backup-receipt.json")
    inventory = load("evidence/wheel-source-inventory.json")
    command_paths = {
        "schema_contract_validation": "evidence/commands/schema-contract-validation.json",
        "focused_negative_tests": "evidence/commands/focused-negative-tests.json",
        "concurrency_tests": "evidence/commands/concurrency-tests.json",
        "full_pytest": "evidence/commands/full-pytest.json",
        "ruff": "evidence/commands/ruff.json",
        "architecture_checks": "evidence/commands/architecture-checks.json",
        "bandit_changed_scope": "evidence/commands/bandit-changed-scope.json",
        "pip_audit": "evidence/commands/pip-audit.json",
        "wheel_source_inventory": "evidence/commands/wheel-source-inventory-command.json",
        "runtime_isolation_smoke": "evidence/commands/runtime-isolation-smoke-command.json",
        "protected_assets_hash_check": "evidence/commands/protected-assets-hash-check.json",
        "review_bundle_accessibility": "evidence/commands/review-bundle-accessibility.json",
    }
    evidence_paths = {
        **command_paths,
        "wheel_source_inventory": "evidence/wheel-source-inventory.json",
        "runtime_isolation_smoke": "evidence/runtime-isolation-evidence.json",
    }
    commands = {name: load(path) for name, path in command_paths.items()}
    if tuple(commands) != REQUIRED_VERIFICATION_NAMES or not all(
        command.get("schema_version") == COMMAND_EVIDENCE_SCHEMA
        and command.get("passed") is True
        and command.get("exit_code") == 0
        for command in commands.values()
    ):
        raise ValueError("The exact command evidence set is incomplete or failed.")

    verification: list[dict[str, Any]] = []
    for name in REQUIRED_VERIFICATION_NAMES:
        command = commands[name]
        result: dict[str, Any] = {"completed_process_record_bound": True}
        if name == "full_pytest":
            passed = [
                int(value)
                for value in re.findall(
                    r"(?:^|\s)(\d+) passed",
                    f"{command['stdout']}\n{command['stderr']}",
                    re.IGNORECASE,
                )
            ]
            if not passed:
                raise ValueError("Full pytest evidence has no passed-test summary.")
            result = {"pytest_passed": max(passed)}
        elif name == "bandit_changed_scope":
            bandit = json.loads(command["stdout"])
            result = {
                "high_severity": bandit["metrics"]["_totals"]["SEVERITY.HIGH"],
                "retained_findings": len(bandit["results"]),
            }
        elif name == "wheel_source_inventory":
            wheel = root / "evidence/candidate/colameta-0.1.2-py3-none-any.whl"
            result = {
                "wheel_sha256": sha256_file(wheel),
                "wheel_artifact_ref": (
                    "evidence/candidate/colameta-0.1.2-py3-none-any.whl"
                ),
                "wheel_artifact_size_bytes": wheel.stat().st_size,
                "file_manifest_digest": inventory["file_manifest_digest"],
            }
        elif name == "runtime_isolation_smoke":
            result = {
                "loopback_only": runtime["bind_address"] == "127.0.0.1",
                "token_negative_tests": sum(
                    runtime["authentication"].get(key) == expected
                    for key, expected in (
                        ("no_token_http_status", 401),
                        ("wrong_token_http_status", 401),
                        ("revoked_token_http_status", 401),
                    )
                ),
                "listed_tools": runtime["listed_tools"],
                "lease_final_status": snapshot["status"],
            }
        evidence_ref = evidence_paths[name]
        verification.append(
            {
                "name": name,
                "command": shlex.join(command["argv"]),
                "started_at": command["started_at"],
                "ended_at": command["ended_at"],
                "exit_code": command["exit_code"],
                "passed": command["passed"],
                "result": result,
                "evidence_ref": evidence_ref,
                "evidence_sha256": sha256_file(root / evidence_ref),
            }
        )

    principal = snapshot["principal_binding"]
    runtime_binding = snapshot["runtime_binding"]
    preflight_runtime = preflight["runtime_isolation"]
    preflight_fresh = preflight["fresh_ledger"]
    preflight_backup = preflight["pre_activation_backup"]
    claim_event = next(
        event for event in events if event["event_type"] == "process_claimed"
    )
    preflight_age = (
        parse_timestamp(claim_event["created_at"], "claim.created_at")
        - parse_timestamp(preflight["observed_at"], "preflight.observed_at")
    ).total_seconds()
    event_root = canonical_sha256([event["event_digest"] for event in events])
    snapshot_path = root / "evidence/lease/activation-lease-snapshot.json"
    events_path = root / "evidence/lease/activation-lease-events.json"
    runtime_path = root / "evidence/runtime-isolation-evidence.json"
    spec_binding = {
        field: sha256_file(project / relative_path)
        for field, relative_path in _SPEC_BINDING_PATHS.items()
    }
    spec_binding.update(
        {
            "json_schema_dialect": "https://json-schema.org/draft/2020-12/schema",
            "format_assertions_enabled": True,
            "date_time_checker": "explicit_strict_rfc3339_registered",
        }
    )
    evidence_gate = bool(
        all(item["passed"] is True for item in verification)
        and runtime.get("pass") is True
        and snapshot.get("status") == "closed"
        and events
    )
    lease_checks = {
        key: evidence_gate
        and all(target in commands[slot]["argv"] for slot, target in bindings)
        for key, bindings in _LEASE_CHECK_EVIDENCE_BINDINGS.items()
    }
    started = min(
        parse_timestamp(item["started_at"], item["name"])
        for item in verification
    )
    ended = max(
        parse_timestamp(item["ended_at"], item["name"])
        for item in verification
    )
    runtime_auth = runtime["authentication"]
    all_paths = preflight_runtime["all_paths_under_canary_root"] is True
    receipt = {
        "schema_version": "wig_p3_canary_a1_r2_closeout_receipt.v1",
        "receipt_purpose": "isolated_implementation_conformance_not_deployed_canary_activation",
        "stage_id": "WIG-P3-CANARY-A1-R2",
        "generated_at": _timestamp(),
        "verification_window": {
            "started_at": started.isoformat().replace("+00:00", "Z"),
            "ended_at": ended.isoformat().replace("+00:00", "Z"),
            "timezone": "UTC",
        },
        "source_binding": {**snapshot["source_binding"], "tracked_source_clean": True},
        "spec_binding": spec_binding,
        "authentication": {
            "auth_mode": preflight["authentication"]["auth_mode"],
            "token_source": preflight["authentication"]["token_source"],
            "token_generation_algorithm": preflight["authentication"][
                "token_generation_algorithm"
            ],
            "token_entropy_bits": preflight["authentication"]["token_entropy_bits"],
            "token_generation_evidence_digest": preflight["authentication"][
                "token_generation_evidence_digest"
            ],
            "auth_file_mode": preflight["authentication"]["token_file_mode"],
            "auth_parent_directories_mode": preflight["authentication"]["token_parent_mode"],
            "no_token_rejected": runtime_auth["no_token_http_status"] == 401,
            "wrong_token_rejected": runtime_auth["wrong_token_http_status"] == 401,
            "weak_token_configuration_rejected": preflight["authentication"][
                "weak_token_configuration_rejected"
            ],
            "correct_token_accepted": runtime_auth["correct_token_http_status"] == 200,
            "token_absent_from_public_surfaces": preflight["authentication"][
                "token_absent_from_public_surfaces"
            ],
            "one_time_token_revoked_after_test": runtime_auth["token_file_present_after"]
            is False,
            "revoked_token_rejected": runtime_auth["revoked_token_http_status"] == 401,
        },
        "runtime_isolation": {
            **{
                field: all_paths
                for field in (
                    "home_under_canary_root",
                    "xdg_config_under_canary_root",
                    "xdg_state_under_canary_root",
                    "xdg_cache_under_canary_root",
                    "registry_under_canary_root",
                    "runtime_executable_under_canary_root",
                    "cwd_under_canary_root",
                    "project_root_under_canary_root",
                    "settings_under_canary_root",
                    "ledger_under_canary_root",
                    "backup_under_canary_root",
                    "token_file_under_canary_root",
                    "fixture_root_under_canary_root",
                    "activation_envelope_under_canary_root",
                    "claimed_activation_envelope_under_canary_root",
                )
            },
            "global_registry_not_selected": not preflight_runtime["global_registry_selected"],
            "global_registry_not_open": not preflight_runtime["global_registry_open"],
            "registry_project_count": preflight_runtime["registry_project_count"],
            "bind_address": runtime_binding["bind_address"],
            "port": runtime_binding["port"],
            "preclaim_listener_count": preflight_runtime["preclaim_listener_count"],
            "postclaim_listener_count": runtime["listener"]["process_listener_count"],
            "listener_attestation_digest": runtime_binding["listener_attestation_digest"],
            "authenticated_request_context_binding_digest": runtime_binding[
                "authenticated_request_context_binding_digest"
            ],
            "request_dispatch_before_listener_attestation": snapshot["bootstrap"][
                "request_dispatch_before_listener_attestation"
            ],
            "public_endpoint_created": runtime["listener"]["public_endpoint_created"],
            "relay_enabled": runtime["listener"]["relay_enabled"],
            "tunnel_enabled": runtime["listener"]["tunnel_enabled"],
            "proxy_enabled": runtime["listener"]["proxy_enabled"],
            "background_side_effect_workers_started": preflight_runtime[
                "background_side_effect_workers_started"
            ],
        },
        "restricted_surface": {
            "profile": preflight["restricted_surface"]["profile"],
            "listed_tool_count": len(runtime["tool_names"]),
            "listed_tools_sha256": canonical_sha256(runtime["tool_names"]),
            **runtime["restricted_surface"],
        },
        "fresh_ledger": {
            "schema_version": preflight_fresh["schema_version"],
            "database_generation": preflight_fresh["database_generation"],
            "business_fact_counts_before": preflight_fresh["business_fact_counts"],
            "external_associations_before": preflight_fresh["external_associations"],
            "attempt_events_before": preflight_fresh["attempt_events"],
            "prior_activation_leases_for_authorization": preflight_fresh[
                "prior_activation_leases_for_authorization"
            ],
            "fresh_ledger_baseline_digest": preflight_fresh["baseline_digest"],
            "preflight_receipt_digest": canonical_sha256(preflight),
            "preflight_observed_at": preflight["observed_at"],
            "preflight_valid_until": preflight["valid_until"],
            "preflight_age_seconds_at_claim": preflight_age,
            "preview_signing_key_preprovisioned": preflight_fresh[
                "preview_signing_key_preprovisioned"
            ],
            "backup_receipt_digest": preflight_backup["receipt_digest"],
            "backup_sha256": backup["backup_sha256"],
            "integrity_check": preflight_fresh["integrity_check"],
            "foreign_key_violations": preflight_fresh["foreign_key_violations"],
        },
        "activation_lease": {
            "lease_id": snapshot["lease_id"],
            "authorization_id": snapshot["authorization_id"],
            "authorization_digest": snapshot["authorization_digest"],
            "activation_envelope_digest": snapshot["activation_envelope_digest"],
            "synthetic_fixture_contract_digest": snapshot["scope"][
                "synthetic_fixture_contract_digest"
            ],
            "claimed_envelope_path_digest": runtime_binding[
                "claimed_activation_envelope_path_digest"
            ],
            "expected_process_identity": runtime_binding["expected_process_identity"],
            "claimed_process_identity": runtime_binding["claimed_process_identity"],
            "listener_attestation_digest": runtime_binding["listener_attestation_digest"],
            "authenticated_request_context_binding_digest": runtime_binding[
                "authenticated_request_context_binding_digest"
            ],
            "principal_id": principal["principal_id"],
            "principal_kind": principal["principal_kind"],
            "session_ref": principal["session_ref"],
            "principal_binding_digest": canonical_sha256(principal),
            "evidence_export_root_path_digest": canonical_sha256(
                {"resolved_posix_path": root.as_posix()}
            ),
            "lease_snapshot_digest": canonical_sha256(snapshot),
            "lease_snapshot_export_relative_path": (
                "evidence/lease/activation-lease-snapshot.json"
            ),
            "lease_snapshot_export_sha256": sha256_file(snapshot_path),
            "lease_event_schema_digest": snapshot["lease_event_schema_digest"],
            "lease_event_count": len(events),
            "lease_event_root_sha256": event_root,
            "lease_event_root_algorithm": (
                "sha256(canonical_json(event_digest_array_ordered_by_contiguous_sequence))"
            ),
            "lease_event_export_relative_path": (
                "evidence/lease/activation-lease-events.json"
            ),
            "lease_event_export_sha256": sha256_file(events_path),
            "final_status": snapshot["status"],
            "final_state_version": snapshot["state_version"],
            **lease_checks,
        },
        "verification": verification,
        "gaps": [
            {
                "id": "external_non_occurrence_audit_log_not_available",
                "severity": "low",
                "summary": (
                    "No external provider audit log was consulted for Push or Stable Promotion; "
                    "the claim is bounded to local Git state and the isolated harness."
                ),
                "evidence_ref": "evidence/runtime-isolation-evidence.json",
                "evidence_sha256": sha256_file(runtime_path),
            }
        ],
        "blockers": [],
        "protected_user_assets": {
            "unchanged": True,
            "staged": False,
            "committed": False,
            "assets": [
                {"path": path, "sha256": sha256_file(project / path)}
                for path in _PROTECTED_ASSET_SCHEMA_ORDER
            ],
        },
        "safety": runtime["safety"],
        "result": "PASS_WITH_GAPS",
    }
    _write_json(output, receipt)
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="action", required=True)
    run = commands.add_parser("run-command")
    run.add_argument("--name", required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("command", nargs=argparse.REMAINDER)
    protected = commands.add_parser("protected-assets-check")
    protected.add_argument("--expected", action="append", default=[])
    access = commands.add_parser("bundle-access-check")
    access.add_argument("--bundle-root", type=Path, required=True)
    access.add_argument("--required", action="append", default=[])
    inventory = commands.add_parser("wheel-inventory")
    inventory.add_argument("--checkout", type=Path, required=True)
    inventory.add_argument("--wheel", type=Path, required=True)
    inventory.add_argument("--output", type=Path, required=True)
    assemble = commands.add_parser("assemble-runtime-evidence")
    assemble.add_argument("--runtime-root", type=Path, required=True)
    assemble.add_argument("--bundle-root", type=Path, required=True)
    assemble.add_argument("--runtime-command-evidence", type=Path, required=True)
    manifest = commands.add_parser("bundle-manifest")
    manifest.add_argument("--bundle-root", type=Path, required=True)
    manifest.add_argument("--output", type=Path, required=True)
    build = commands.add_parser("build-receipt")
    build.add_argument("--bundle-root", type=Path, required=True)
    build.add_argument("--project-root", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    verify = commands.add_parser("verify-receipt")
    verify.add_argument("--receipt", type=Path, required=True)
    verify.add_argument("--bundle-root", type=Path, required=True)
    verify.add_argument("--project-root", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    capability = _R3_TRUSTED_BOOTSTRAP_CAPABILITY
    if capability is None or not callable(getattr(capability, "consume", None)):
        raise RuntimeError(
            "R3 Closeout CLI requires scripts/work_item_r3_trusted_launcher.py."
        )
    startup_attestation = capability.consume()
    arguments = _parser().parse_args(argv)
    if arguments.action == "run-command":
        command = list(arguments.command)
        if command[:1] == ["--"]:
            command = command[1:]
        return run_command(
            name=arguments.name,
            output=arguments.output,
            command=command,
            startup_attestation=startup_attestation,
        )
    if arguments.action == "protected-assets-check":
        return protected_assets_check(arguments.expected)
    if arguments.action == "bundle-access-check":
        return bundle_access_check(bundle_root=arguments.bundle_root, required=arguments.required)
    if arguments.action == "wheel-inventory":
        return wheel_inventory(
            checkout=arguments.checkout,
            wheel=arguments.wheel,
            output=arguments.output,
        )
    if arguments.action == "assemble-runtime-evidence":
        return assemble_runtime_evidence(
            runtime_root=arguments.runtime_root,
            bundle_root=arguments.bundle_root,
            runtime_command_evidence=arguments.runtime_command_evidence,
        )
    if arguments.action == "bundle-manifest":
        return bundle_manifest(bundle_root=arguments.bundle_root, output=arguments.output)
    if arguments.action == "build-receipt":
        return build_receipt(
            bundle_root=arguments.bundle_root,
            project_root=arguments.project_root,
            output=arguments.output,
        )
    if arguments.action == "verify-receipt":
        return verify_receipt(
            receipt=arguments.receipt,
            bundle_root=arguments.bundle_root,
            project_root=arguments.project_root,
        )
    raise AssertionError("unreachable")


if __name__ == "__main__":
    sys.exit(main())
