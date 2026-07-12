from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

import runner.work_item_governance.closeout as closeout


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
    evidence = tmp_path / "full-pytest.json"
    evidence.write_text(
        json.dumps(
            {
                "schema_version": "work_item_closeout_command_evidence.v1",
                "name": "full_pytest",
                "argv": ["true"],
                "cwd": tmp_path.as_posix(),
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
        "command": "true",
        "started_at": "2026-07-12T00:00:00Z",
        "ended_at": "2026-07-12T00:00:01Z",
        "exit_code": 0,
        "passed": True,
    }

    violations: list[str] = []
    closeout._verify_command_evidence(
        receipt_item,
        evidence,
        project_root=tmp_path,
        violations=violations,
    )

    assert violations == ["command_contract:full_pytest"]


def test_closeout_accepts_bound_pytest_completed_process_record(tmp_path: Path) -> None:
    argv = ["python3", "-m", "pytest", "-q"]
    evidence = tmp_path / "full-pytest.json"
    payload = {
        "schema_version": "work_item_closeout_command_evidence.v1",
        "name": "full_pytest",
        "argv": argv,
        "cwd": tmp_path.as_posix(),
        "started_at": "2026-07-12T00:00:00Z",
        "ended_at": "2026-07-12T00:00:01Z",
        "exit_code": 0,
        "passed": True,
        "stdout": "1132 passed in 88.37s",
        "stderr": "",
    }
    evidence.write_text(json.dumps(payload), encoding="utf-8")
    receipt_item = {
        "name": "full_pytest",
        "command": "python3 -m pytest -q",
        "started_at": payload["started_at"],
        "ended_at": payload["ended_at"],
        "exit_code": 0,
        "passed": True,
    }

    violations: list[str] = []
    closeout._verify_command_evidence(
        receipt_item,
        evidence,
        project_root=tmp_path,
        violations=violations,
    )

    assert violations == []


def test_closeout_requires_real_commands_for_special_evidence_slots() -> None:
    assert closeout._command_matches_slot(
        "wheel_source_inventory",
        [
            "python3",
            "-m",
            "scripts.work_item_r3_closeout",
            "wheel-inventory",
            "--checkout",
            ".",
        ],
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
        ],
    )
    assert not closeout._command_matches_slot("wheel_source_inventory", ["true"])
    assert not closeout._command_matches_slot("runtime_isolation_smoke", ["pytest", "-q"])


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
