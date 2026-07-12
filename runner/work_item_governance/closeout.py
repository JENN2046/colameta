from __future__ import annotations

import hashlib
import json
import shlex
import subprocess  # nosec B404
from datetime import timezone
from http import HTTPStatus
from pathlib import Path
from typing import Any

from runner.work_item_governance import bootstrap as _runtime_bootstrap
from runner.work_item_governance.activation import (
    AUTHORITATIVE_CANARY_TOOLS,
    validate_synthetic_fixture_semantics,
)
from runner.work_item_governance.canonical import canonical_sha256, sha256_file
from runner.work_item_governance.contracts import MAX_JSON_BYTES
from runner.work_item_governance.errors import WorkItemGovernanceError
from runner.work_item_governance.preview import parse_timestamp
from runner.work_item_governance.schema_loader import validate_governance_record
from runner.work_item_governance.source_binding import verify_runtime_source_artifacts


REQUIRED_VERIFICATION_NAMES = (
    "schema_contract_validation",
    "focused_negative_tests",
    "concurrency_tests",
    "full_pytest",
    "ruff",
    "architecture_checks",
    "bandit_changed_scope",
    "pip_audit",
    "wheel_source_inventory",
    "runtime_isolation_smoke",
    "protected_assets_hash_check",
    "review_bundle_accessibility",
)

_SPECIAL_COMMAND_EVIDENCE = {
    "wheel_source_inventory": "evidence/commands/wheel-source-inventory-command.json",
    "runtime_isolation_smoke": "evidence/commands/runtime-isolation-smoke-command.json",
}

_SPEC_BINDING_PATHS = {
    "freeze_manifest_sha256": "docs/work-item-governance/r2-spec/FREEZE_MANIFEST.json",
    "tool_allowlist_sha256": (
        "schemas/work_item_governance/authoritative-canary-tool-allowlist.v1.json"
    ),
    "command_matrix_sha256": (
        "schemas/work_item_governance/work-item-write-command-matrix.v1.json"
    ),
    "write_path_inventory_sha256": (
        "docs/work-item-governance/r2-spec/write-path-inventory.v1.json"
    ),
    "activation_envelope_schema_sha256": (
        "schemas/work_item_governance/activation-envelope.v1.schema.json"
    ),
    "synthetic_fixture_schema_sha256": (
        "schemas/work_item_governance/synthetic-fixture-contract.v1.schema.json"
    ),
    "preflight_receipt_schema_sha256": (
        "schemas/work_item_governance/preflight-receipt.v1.schema.json"
    ),
    "lease_schema_sha256": "schemas/work_item_governance/activation-lease.v1.schema.json",
    "lease_event_schema_sha256": (
        "schemas/work_item_governance/activation-lease-event.v1.schema.json"
    ),
    "closeout_receipt_schema_sha256": (
        "schemas/work_item_governance/r2-closeout-receipt.v1.schema.json"
    ),
    "negative_test_matrix_sha256": (
        "docs/work-item-governance/r2-spec/negative-test-matrix.v1.json"
    ),
}

# The closeout verifier attests the exact bootstrap and activation modules that
# make up the authoritative runtime.  Importing bootstrap here is intentional:
# an offline inventory/receipt process must measure the same critical module set
# as the live composition root instead of depending on unrelated import order.
assert _runtime_bootstrap is not None


def verify_r2_closeout_receipt(
    receipt: dict[str, Any],
    *,
    evidence_root: str | Path,
    project_root: str | Path,
) -> dict[str, Any]:
    """Fail closed on semantic PASS claims that JSON Schema alone cannot prove."""

    validate_governance_record("wig_p3_canary_a1_r2_closeout_receipt.v1", receipt)
    resolved_evidence_root = Path(evidence_root).expanduser().resolve()
    resolved_project_root = Path(project_root).expanduser().resolve()
    violations: list[str] = []
    verification = receipt["verification"]
    if tuple(item["name"] for item in verification) != REQUIRED_VERIFICATION_NAMES:
        violations.append("verification_order_or_coverage")
    for item in verification:
        started = parse_timestamp(item["started_at"], f"{item['name']}.started_at")
        ended = parse_timestamp(item["ended_at"], f"{item['name']}.ended_at")
        if started > ended:
            violations.append(f"verification_time_order:{item['name']}")
        if item["exit_code"] != 0 or item["passed"] is not True:
            violations.append(f"verification_failed:{item['name']}")
        target = (resolved_evidence_root / item["evidence_ref"]).resolve()
        try:
            target.relative_to(resolved_evidence_root)
        except ValueError:
            violations.append(f"evidence_path_escape:{item['name']}")
        if not target.is_file():
            violations.append(f"evidence_missing:{item['name']}")
        elif sha256_file(target) != item["evidence_sha256"]:
            violations.append(f"evidence_digest_mismatch:{item['name']}")
        elif item["name"] not in _SPECIAL_COMMAND_EVIDENCE:
            _verify_command_evidence(
                item,
                target,
                project_root=resolved_project_root,
                violations=violations,
            )
        else:
            command_path = _evidence_path(
                resolved_evidence_root,
                _SPECIAL_COMMAND_EVIDENCE[item["name"]],
                f"{item['name']}_command",
                violations,
            )
            if command_path is not None:
                _verify_command_evidence(
                    item,
                    command_path,
                    project_root=resolved_project_root,
                    violations=violations,
                )
    window = receipt["verification_window"]
    started = parse_timestamp(window["started_at"], "verification_window.started_at")
    ended = parse_timestamp(window["ended_at"], "verification_window.ended_at")
    generated = parse_timestamp(receipt["generated_at"], "generated_at")
    if started > ended or ended > generated.astimezone(timezone.utc):
        violations.append("closeout_time_order")
    for item in verification:
        item_started = parse_timestamp(item["started_at"], f"{item['name']}.started_at")
        item_ended = parse_timestamp(item["ended_at"], f"{item['name']}.ended_at")
        if item_started < started or item_ended > ended:
            violations.append(f"verification_outside_window:{item['name']}")
    if receipt["activation_lease"]["final_status"] not in {
        "write_frozen",
        "expired",
        "closed",
        "revoked",
    }:
        violations.append("lease_not_inactive")
    result = receipt["result"]
    if result == "PASS" and (receipt["gaps"] or receipt["blockers"]):
        violations.append("pass_with_findings")
    if result == "PASS_WITH_GAPS" and receipt["blockers"]:
        violations.append("gaps_result_has_blockers")
    _verify_spec_binding(receipt, resolved_project_root, violations)
    _verify_authentication_preflight_evidence(receipt, resolved_evidence_root, violations)
    _verify_fresh_ledger_and_runtime_evidence(
        receipt,
        resolved_evidence_root,
        violations,
    )
    _verify_activation_contract_exports(receipt, resolved_evidence_root, violations)
    _verify_exported_lease_evidence(receipt, resolved_evidence_root, violations)
    _verify_exact_source_and_runtime_evidence(
        receipt,
        resolved_evidence_root,
        resolved_project_root,
        violations,
    )
    _verify_protected_assets(receipt, resolved_project_root, violations)
    if violations:
        raise WorkItemGovernanceError(
            "R2_CLOSEOUT_SEMANTICS_INVALID",
            "R2 Closeout Receipt cannot support its claimed result.",
            details={"violations": sorted(set(violations))},
        )
    return {
        "schema_valid": True,
        "semantic_valid": True,
        "result": result,
        "verification_count": len(verification),
    }


def _verify_exact_source_and_runtime_evidence(
    receipt: dict[str, Any],
    evidence_root: Path,
    project_root: Path,
    violations: list[str],
) -> None:
    verification = {item["name"]: item for item in receipt["verification"]}
    wheel_item = verification.get("wheel_source_inventory")
    runtime_item = verification.get("runtime_isolation_smoke")
    if not isinstance(wheel_item, dict) or not isinstance(runtime_item, dict):
        return

    wheel_result = wheel_item.get("result")
    measured_source = None
    if not isinstance(wheel_result, dict):
        violations.append("wheel_inventory_result_shape")
    else:
        inventory_path = _evidence_path(
            evidence_root,
            str(wheel_item["evidence_ref"]),
            "wheel_inventory",
            violations,
        )
        inventory: Any = None
        if inventory_path is not None:
            try:
                inventory = _load_strict_json(inventory_path)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
                violations.append("wheel_inventory_parse")
        expected_wheel_sha256 = receipt["source_binding"]["wheel_sha256"]
        if (
            not isinstance(inventory, dict)
            or inventory.get("wheel_sha256") != expected_wheel_sha256
            or wheel_result.get("wheel_sha256") != expected_wheel_sha256
        ):
            violations.append("wheel_inventory_source_binding")
        artifact_ref = wheel_result.get("wheel_artifact_ref")
        if not isinstance(artifact_ref, str) or not artifact_ref:
            violations.append("wheel_artifact_reference_missing")
        else:
            wheel_path = _evidence_path(
                evidence_root,
                artifact_ref,
                "wheel_artifact",
                violations,
            )
            if wheel_path is not None:
                if sha256_file(wheel_path) != expected_wheel_sha256:
                    violations.append("wheel_artifact_digest")
                expected_size = wheel_result.get("wheel_artifact_size_bytes")
                if (
                    isinstance(expected_size, bool)
                    or not isinstance(expected_size, int)
                    or expected_size != wheel_path.stat().st_size
                ):
                    violations.append("wheel_artifact_size")
                try:
                    measured_source = verify_runtime_source_artifacts(
                        checkout_root=project_root,
                        wheel_artifact=wheel_path,
                        expected_source_binding={
                            "core_baseline_commit": receipt["source_binding"]["core_baseline_commit"],
                            "implementation_commit": receipt["source_binding"]["implementation_commit"],
                            "implementation_tree": receipt["source_binding"]["implementation_tree"],
                            "wheel_sha256": receipt["source_binding"]["wheel_sha256"],
                        },
                    )
                except WorkItemGovernanceError:
                    violations.append("wheel_git_runtime_source_attestation")
                else:
                    if (
                        not isinstance(inventory, dict)
                        or inventory.get("source_binding") != measured_source.source_binding
                        or inventory.get("file_manifest_digest")
                        != measured_source.file_manifest_digest
                    ):
                        violations.append("wheel_inventory_manifest_binding")

    runtime_path = _evidence_path(
        evidence_root,
        str(runtime_item["evidence_ref"]),
        "runtime_isolation",
        violations,
    )
    runtime_evidence: Any = None
    if runtime_path is not None:
        try:
            runtime_evidence = _load_strict_json(runtime_path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            violations.append("runtime_evidence_parse")
    if not isinstance(runtime_evidence, dict):
        violations.append("runtime_evidence_shape")
    else:
        expected_source = {
            "core_baseline_commit": receipt["source_binding"]["core_baseline_commit"],
            "implementation_commit": receipt["source_binding"]["implementation_commit"],
            "implementation_tree": receipt["source_binding"]["implementation_tree"],
            "wheel_sha256": receipt["source_binding"]["wheel_sha256"],
        }
        if runtime_evidence.get("source") != expected_source:
            violations.append("runtime_evidence_source_binding")
        if (
            runtime_evidence.get("pass") is not True
            or runtime_evidence.get("bind_address") != receipt["runtime_isolation"]["bind_address"]
            or runtime_evidence.get("port") != receipt["runtime_isolation"]["port"]
            or runtime_evidence.get("listed_tools") != receipt["restricted_surface"]["listed_tool_count"]
        ):
            violations.append("runtime_evidence_binding")
        if runtime_evidence.get("tool_names") != list(AUTHORITATIVE_CANARY_TOOLS):
            violations.append("runtime_tool_inventory")
        command_evidence_ref = _SPECIAL_COMMAND_EVIDENCE["runtime_isolation_smoke"]
        command_evidence_path = _evidence_path(
            evidence_root,
            command_evidence_ref,
            "runtime_command_evidence",
            violations,
        )
        if (
            command_evidence_path is None
            or runtime_evidence.get("command_evidence_ref") != command_evidence_ref
            or runtime_evidence.get("command_evidence_sha256")
            != sha256_file(command_evidence_path)
        ):
            violations.append("runtime_command_evidence_binding")
        authentication = runtime_evidence.get("authentication")
        expected_authentication = dict(
            (
                ("no_token_http_status", int(HTTPStatus.UNAUTHORIZED)),
                ("wrong_token_http_status", int(HTTPStatus.UNAUTHORIZED)),
                ("correct_token_http_status", int(HTTPStatus.OK)),
                ("revoked_token_http_status", int(HTTPStatus.UNAUTHORIZED)),
                ("token_file_present_after", bool(0)),
            )
        )
        if not isinstance(authentication, dict) or authentication != expected_authentication:
            violations.append("runtime_authentication_evidence")
        source_attestation = runtime_evidence.get("source_attestation")
        if (
            measured_source is None
            or not isinstance(source_attestation, dict)
            or source_attestation.get("verified") is not True
            or source_attestation.get("source_binding") != measured_source.source_binding
            or source_attestation.get("file_manifest_digest")
            != measured_source.file_manifest_digest
        ):
            violations.append("runtime_source_attestation")

    snapshot_path = _evidence_path(
        evidence_root,
        receipt["activation_lease"]["lease_snapshot_export_relative_path"],
        "runtime_lease_snapshot",
        violations,
    )
    if snapshot_path is not None:
        try:
            snapshot = _load_strict_json(snapshot_path)
            runtime_started = parse_timestamp(runtime_item["started_at"], "runtime.started_at")
            runtime_ended = parse_timestamp(runtime_item["ended_at"], "runtime.ended_at")
            lease_created = parse_timestamp(snapshot["created_at"], "lease.created_at")
            lease_updated = parse_timestamp(snapshot["updated_at"], "lease.updated_at")
            if lease_created < runtime_started or lease_updated > runtime_ended:
                violations.append("runtime_lease_time_causality")
            runtime_binding = snapshot["runtime_binding"]
            runtime_lease = runtime_evidence.get("lease") if isinstance(runtime_evidence, dict) else None
            if not isinstance(runtime_lease, dict) or runtime_lease != {
                "lease_id": snapshot["lease_id"],
                "claimed_process_identity": runtime_binding["claimed_process_identity"],
                "listener_attestation_digest": runtime_binding["listener_attestation_digest"],
                "authenticated_request_context_binding_digest": runtime_binding[
                    "authenticated_request_context_binding_digest"
                ],
                "final_status": snapshot["status"],
                "final_state_version": snapshot["state_version"],
            }:
                violations.append("runtime_lease_binding")
            source_export = snapshot_path.parent / "runtime-source-attestation.json"
            if not source_export.is_file():
                violations.append("runtime_source_attestation_export_missing")
            else:
                exported_source = _load_strict_json(source_export)
                if (
                    measured_source is None
                    or exported_source.get("verified") is not True
                    or exported_source.get("source_binding") != measured_source.source_binding
                    or exported_source.get("file_manifest_digest")
                    != measured_source.file_manifest_digest
                    or not isinstance(runtime_evidence, dict)
                    or runtime_evidence.get("source_attestation") != exported_source
                ):
                    violations.append("runtime_source_attestation_export_binding")
        except (KeyError, OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError, WorkItemGovernanceError):
            violations.append("runtime_lease_time_parse")


def _verify_command_evidence(
    receipt_item: dict[str, Any],
    evidence_path: Path,
    *,
    project_root: Path,
    violations: list[str],
) -> None:
    """Bind a verification slot to the retained completed-process record.

    This does not pretend that a local JSON file is an external attestation.  It
    does prevent a PASS receipt from pointing at arbitrary prose or replacing a
    real command with ``true`` while claiming pytest, Ruff or Bandit ran.
    """

    name = str(receipt_item["name"])
    try:
        evidence = _load_strict_json(evidence_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        violations.append(f"command_evidence_parse:{name}")
        return
    if not isinstance(evidence, dict):
        violations.append(f"command_evidence_shape:{name}")
        return
    argv = evidence.get("argv")
    if (
        evidence.get("schema_version") != "work_item_closeout_command_evidence.v1"
        or evidence.get("name") != name
        or not isinstance(argv, list)
        or not argv
        or any(not isinstance(value, str) or not value for value in argv)
        or evidence.get("cwd") != project_root.as_posix()
        or evidence.get("started_at") != receipt_item["started_at"]
        or evidence.get("ended_at") != receipt_item["ended_at"]
        or evidence.get("exit_code") != receipt_item["exit_code"]
        or evidence.get("passed") != receipt_item["passed"]
        or shlex.join(argv) != receipt_item["command"]
        or not isinstance(evidence.get("stdout"), str)
        or not isinstance(evidence.get("stderr"), str)
    ):
        violations.append(f"command_evidence_binding:{name}")
        return
    if len(evidence["stdout"].encode("utf-8")) + len(evidence["stderr"].encode("utf-8")) > MAX_JSON_BYTES:
        violations.append(f"command_evidence_too_large:{name}")
    if not _command_matches_slot(name, argv):
        violations.append(f"command_contract:{name}")
    if not _command_output_matches_slot(
        name,
        stdout=evidence["stdout"],
        stderr=evidence["stderr"],
    ):
        violations.append(f"command_output_contract:{name}")


def _command_matches_slot(name: str, argv: list[str]) -> bool:
    executable = Path(argv[0]).name
    modules = tuple(argv[1:3])
    arguments = argv[1:]
    is_python = executable.startswith("python")
    is_pytest = executable == "pytest" or (is_python and modules == ("-m", "pytest"))
    if name in {
        "schema_contract_validation",
        "focused_negative_tests",
        "concurrency_tests",
        "full_pytest",
        "architecture_checks",
    }:
        return is_pytest and "--collect-only" not in arguments
    if name == "ruff":
        return (executable == "ruff" and arguments[:1] == ["check"]) or (
            is_python and modules == ("-m", "ruff") and arguments[2:3] == ["check"]
        )
    if name == "bandit_changed_scope":
        return (
            executable == "bandit" or (is_python and modules == ("-m", "bandit"))
        ) and all(
            required in arguments for required in ("-f", "json", "--exit-zero")
        ) and any(
            value.endswith(".py") or value in {"runner", "scripts", "adapters"} for value in arguments
        )
    if name == "pip_audit":
        return executable == "pip-audit" or (is_python and modules == ("-m", "pip_audit"))
    if name == "wheel_source_inventory":
        return (
            is_python
            and modules == ("-m", "scripts.work_item_r3_closeout")
            and arguments[2:3] == ["wheel-inventory"]
        )
    if name == "runtime_isolation_smoke":
        return is_pytest and any(
            value
            == (
                "tests/test_work_item_authoritative_canary.py::"
                "test_loopback_conformance_requires_token_and_exposes_exact_surface"
            )
            for value in arguments
        )
    if name in {"protected_assets_hash_check", "review_bundle_accessibility"}:
        return is_python and (
            modules == ("-m", "scripts.work_item_r3_closeout")
            or any(value.endswith(".py") for value in arguments)
        )
    return False


def _command_output_matches_slot(name: str, *, stdout: str, stderr: str) -> bool:
    combined = f"{stdout}\n{stderr}".lower()
    if name in {
        "schema_contract_validation",
        "focused_negative_tests",
        "concurrency_tests",
        "full_pytest",
        "architecture_checks",
    }:
        return " passed" in combined and not any(
            marker in combined for marker in (" failed", " error", " errors")
        )
    if name == "ruff":
        return not combined.strip() or "all checks passed" in combined
    if name == "bandit_changed_scope":
        try:
            payload = json.loads(stdout)
            totals = payload["metrics"]["_totals"]
        except (KeyError, TypeError, json.JSONDecodeError):
            return False
        return (
            payload.get("errors") == []
            and isinstance(payload.get("results"), list)
            and totals.get("SEVERITY.HIGH") == 0
        )
    if name == "pip_audit":
        return "vulnerability" in combined or "no known vulnerabilities" in combined
    if name == "wheel_source_inventory":
        return not combined.strip()
    if name == "runtime_isolation_smoke":
        return " passed" in combined and not any(
            marker in combined for marker in (" failed", " error", " errors")
        )
    if name in {"protected_assets_hash_check", "review_bundle_accessibility"}:
        try:
            payload = json.loads(stdout)
        except (json.JSONDecodeError, TypeError):
            return False
        return isinstance(payload, dict) and payload.get("pass") is True
    return False


def _verify_authentication_preflight_evidence(
    receipt: dict[str, Any],
    evidence_root: Path,
    violations: list[str],
) -> None:
    preflight_path = _evidence_path(
        evidence_root,
        "evidence/preflight-receipt.json",
        "preflight_receipt",
        violations,
    )
    if preflight_path is None:
        return
    try:
        preflight = _load_strict_json(preflight_path)
        validate_governance_record(
            "work_item_authoritative_canary_preflight_receipt.v1",
            preflight,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError, WorkItemGovernanceError):
        violations.append("preflight_receipt_parse_or_schema")
        return
    if canonical_sha256(preflight) != receipt["fresh_ledger"]["preflight_receipt_digest"]:
        violations.append("preflight_receipt_digest")
    authentication = preflight.get("authentication")
    closeout_authentication = receipt["authentication"]
    if not isinstance(authentication, dict) or {
        "auth_mode": authentication.get("auth_mode"),
        "token_source": authentication.get("token_source"),
        "token_generation_algorithm": authentication.get("token_generation_algorithm"),
        "token_entropy_bits": authentication.get("token_entropy_bits"),
        "token_generation_evidence_digest": authentication.get(
            "token_generation_evidence_digest"
        ),
        "auth_file_mode": authentication.get("token_file_mode"),
        "auth_parent_directories_mode": authentication.get("token_parent_mode"),
        "weak_token_configuration_rejected": authentication.get(
            "weak_token_configuration_rejected"
        ),
        "token_absent_from_public_surfaces": authentication.get(
            "token_absent_from_public_surfaces"
        ),
    } != {
        key: closeout_authentication[key]
        for key in (
            "auth_mode",
            "token_source",
            "token_generation_algorithm",
            "token_entropy_bits",
            "token_generation_evidence_digest",
            "auth_file_mode",
            "auth_parent_directories_mode",
            "weak_token_configuration_rejected",
            "token_absent_from_public_surfaces",
        )
    }:
        violations.append("preflight_authentication_binding")


def _verify_spec_binding(
    receipt: dict[str, Any],
    project_root: Path,
    violations: list[str],
) -> None:
    manifest_path = project_root / _SPEC_BINDING_PATHS["freeze_manifest_sha256"]
    try:
        manifest = _load_strict_json(manifest_path)
        package_binding = manifest["package_binding"]
        frozen_files = package_binding["files"]
        frozen_by_name = {Path(item["path"]).name: item for item in frozen_files}
    except (KeyError, OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        violations.append("spec_freeze_manifest_parse")
        return
    if (
        package_binding.get("file_count_excluding_manifest") != len(frozen_files)
        or package_binding.get("total_bytes_excluding_manifest")
        != sum(item["bytes"] for item in frozen_files)
        or package_binding.get("file_list_root_algorithm")
        != (
            "sha256(concatenated UTF-8 '<sha256>  <relative_path>\\n' lines "
            "sorted bytewise by relative_path)"
        )
        or package_binding.get("file_list_root_sha256")
        != hashlib.sha256(
            "".join(
                f"{item['sha256']}  {item['path']}\n"
                for item in sorted(frozen_files, key=lambda value: value["path"].encode("utf-8"))
            ).encode("utf-8")
        ).hexdigest()
        or package_binding.get("manifest_self_digest_included") is not False
    ):
        violations.append("spec_freeze_manifest_package_binding")
    for field, relative_path in _SPEC_BINDING_PATHS.items():
        target = (project_root / relative_path).resolve()
        try:
            target.relative_to(project_root)
        except ValueError:
            violations.append(f"spec_path_escape:{field}")
            continue
        if not target.is_file():
            violations.append(f"spec_file_missing:{field}")
            continue
        measured_sha256 = sha256_file(target)
        if receipt["spec_binding"][field] != measured_sha256:
            violations.append(f"spec_digest_mismatch:{field}")
        if field == "freeze_manifest_sha256":
            continue
        frozen = frozen_by_name.get(target.name)
        if (
            not isinstance(frozen, dict)
            or frozen.get("sha256") != measured_sha256
            or frozen.get("bytes") != target.stat().st_size
            or receipt["spec_binding"][field] != frozen.get("sha256")
        ):
            violations.append(f"spec_freeze_binding:{field}")


def _verify_fresh_ledger_and_runtime_evidence(
    receipt: dict[str, Any],
    evidence_root: Path,
    violations: list[str],
) -> None:
    preflight_path = _evidence_path(
        evidence_root,
        "evidence/preflight-receipt.json",
        "fresh_ledger_preflight",
        violations,
    )
    backup_path = _evidence_path(
        evidence_root,
        "evidence/pre-activation-backup-receipt.json",
        "fresh_ledger_backup",
        violations,
    )
    runtime_path = _evidence_path(
        evidence_root,
        "evidence/runtime-isolation-evidence.json",
        "fresh_ledger_runtime",
        violations,
    )
    snapshot_path = _evidence_path(
        evidence_root,
        receipt["activation_lease"]["lease_snapshot_export_relative_path"],
        "fresh_ledger_lease_snapshot",
        violations,
    )
    events_path = _evidence_path(
        evidence_root,
        receipt["activation_lease"]["lease_event_export_relative_path"],
        "fresh_ledger_lease_events",
        violations,
    )
    ledger_closeout_path = _evidence_path(
        evidence_root,
        "evidence/ephemeral-ledger-closeout.json",
        "fresh_ledger_closeout",
        violations,
    )
    if None in {
        preflight_path,
        backup_path,
        runtime_path,
        snapshot_path,
        events_path,
        ledger_closeout_path,
    }:
        return
    try:
        preflight = _load_strict_json(preflight_path)
        backup = _load_strict_json(backup_path)
        runtime = _load_strict_json(runtime_path)
        snapshot = _load_strict_json(snapshot_path)
        events = _load_strict_json(events_path)
        ledger_closeout = _load_strict_json(ledger_closeout_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        violations.append("fresh_ledger_evidence_parse")
        return
    fresh = receipt["fresh_ledger"]
    preflight_fresh = preflight.get("fresh_ledger")
    preflight_backup = preflight.get("pre_activation_backup")
    if not isinstance(preflight_fresh, dict) or not isinstance(preflight_backup, dict):
        violations.append("fresh_ledger_evidence_shape")
        return
    expected_fresh = {
        "schema_version": preflight_fresh.get("schema_version"),
        "database_generation": preflight_fresh.get("database_generation"),
        "business_fact_counts_before": preflight_fresh.get("business_fact_counts"),
        "external_associations_before": preflight_fresh.get("external_associations"),
        "attempt_events_before": preflight_fresh.get("attempt_events"),
        "prior_activation_leases_for_authorization": preflight_fresh.get(
            "prior_activation_leases_for_authorization"
        ),
        "fresh_ledger_baseline_digest": preflight_fresh.get("baseline_digest"),
        "preflight_receipt_digest": canonical_sha256(preflight),
        "preflight_observed_at": preflight.get("observed_at"),
        "preflight_valid_until": preflight.get("valid_until"),
        "preview_signing_key_preprovisioned": preflight_fresh.get(
            "preview_signing_key_preprovisioned"
        ),
        "backup_receipt_digest": preflight_backup.get("receipt_digest"),
        "backup_sha256": preflight_backup.get("backup_sha256"),
        "integrity_check": preflight_fresh.get("integrity_check"),
        "foreign_key_violations": preflight_fresh.get("foreign_key_violations"),
    }
    for field, expected in expected_fresh.items():
        if fresh.get(field) != expected:
            violations.append(f"fresh_ledger_binding:{field}")
    try:
        observed = parse_timestamp(preflight["observed_at"], "preflight.observed_at")
        claim_event = next(
            event
            for event in events
            if isinstance(event, dict) and event.get("event_type") == "process_claimed"
        )
        claimed = parse_timestamp(claim_event["created_at"], "process_claimed.created_at")
        measured_age = max(0.0, (claimed - observed).total_seconds())
        if abs(float(fresh["preflight_age_seconds_at_claim"]) - measured_age) > 0.001:
            violations.append("fresh_ledger_binding:preflight_age_seconds_at_claim")
    except (KeyError, StopIteration, TypeError, ValueError, WorkItemGovernanceError):
        violations.append("fresh_ledger_preflight_age")
    backup_core = {
        "api": backup.get("api"),
        "backup_sha256": backup.get("backup_sha256"),
        "database_generation": backup.get("database_generation"),
        "schema_version": backup.get("ledger_schema_version"),
        "integrity_check": (
            backup.get("integrity_check", [None])[0]
            if isinstance(backup.get("integrity_check"), list)
            else backup.get("integrity_check")
        ),
        "foreign_key_violations": backup.get("foreign_key_violations"),
        "mode": backup.get("mode"),
    }
    if canonical_sha256(backup_core) != fresh.get("backup_receipt_digest"):
        violations.append("fresh_ledger_backup_receipt_digest")
    if (
        backup.get("backup_bytes_in_sanitized_bundle") is not False
        or backup.get("backup_sha256") != fresh.get("backup_sha256")
        or backup.get("database_generation") != fresh.get("database_generation")
        or backup.get("ledger_schema_version") != fresh.get("schema_version")
        or backup.get("foreign_key_violations") != fresh.get("foreign_key_violations")
    ):
        violations.append("fresh_ledger_backup_binding")
    if (
        ledger_closeout.get("ledger_bytes_in_sanitized_bundle") is not False
        or ledger_closeout.get("integrity_check") != "ok"
        or ledger_closeout.get("foreign_key_violations") != []
        or any(ledger_closeout.get("business_fact_counts", {}).values())
        or ledger_closeout.get("activation_lease")
        != {
            "lease_id": snapshot.get("lease_id"),
            "status": snapshot.get("status"),
            "state_version": snapshot.get("state_version"),
            "usage": snapshot.get("usage"),
        }
    ):
        violations.append("fresh_ledger_closeout_binding")
    runtime_safety = runtime.get("safety")
    if not isinstance(runtime_safety, dict) or runtime_safety != receipt["safety"]:
        violations.append("runtime_safety_binding")
    if (
        runtime.get("existing_d1_canary_modified")
        != receipt["safety"]["existing_canary_restarted"]
        or runtime.get("existing_service_modified")
        != receipt["safety"]["existing_service_modified"]
        or runtime.get("authoritative_activation_outside_ephemeral_test")
        != receipt["safety"]["authoritative_activation_performed"]
    ):
        violations.append("runtime_safety_cross_binding")
    _verify_preflight_snapshot_binding(receipt, preflight, snapshot, violations)
    _verify_runtime_and_surface_receipt_bindings(receipt, preflight, runtime, snapshot, violations)


def _verify_preflight_snapshot_binding(
    receipt: dict[str, Any],
    preflight: dict[str, Any],
    snapshot: dict[str, Any],
    violations: list[str],
) -> None:
    runtime = snapshot.get("runtime_binding")
    snapshot_principal = snapshot.get("principal_binding")
    preflight_principal = preflight.get("principal_binding")
    preflight_runtime = preflight.get("runtime_isolation")
    if not all(
        isinstance(value, dict)
        for value in (runtime, snapshot_principal, preflight_principal, preflight_runtime)
    ):
        violations.append("preflight_snapshot_shape")
        return
    direct_bindings = {
        "authorization_id": (
            preflight.get("authorization_id"),
            snapshot.get("authorization_id"),
            receipt["activation_lease"]["authorization_id"],
        ),
        "authorization_digest": (
            preflight.get("authorization_digest"),
            snapshot.get("authorization_digest"),
            receipt["activation_lease"]["authorization_digest"],
        ),
        "lease_id": (
            preflight.get("activation_lease_id"),
            snapshot.get("lease_id"),
            receipt["activation_lease"]["lease_id"],
        ),
        "source_binding": (
            preflight.get("source_binding"),
            snapshot.get("source_binding"),
            {
                key: receipt["source_binding"][key]
                for key in (
                    "core_baseline_commit",
                    "implementation_commit",
                    "implementation_tree",
                    "wheel_sha256",
                )
            },
        ),
        "preflight_receipt_digest": (
            canonical_sha256(preflight),
            runtime.get("preflight_receipt_digest"),
            receipt["fresh_ledger"]["preflight_receipt_digest"],
        ),
        "backup_receipt_digest": (
            preflight.get("pre_activation_backup", {}).get("receipt_digest"),
            runtime.get("pre_activation_backup_receipt_digest"),
            receipt["fresh_ledger"]["backup_receipt_digest"],
        ),
        "backup_sha256": (
            preflight.get("pre_activation_backup", {}).get("backup_sha256"),
            runtime.get("pre_activation_backup_sha256"),
            receipt["fresh_ledger"]["backup_sha256"],
        ),
    }
    for field, values in direct_bindings.items():
        if values[0] != values[1] or values[1] != values[2]:
            violations.append(f"preflight_snapshot_binding:{field}")
    expected_principal = {
        "principal_id": preflight_principal.get("principal_id"),
        "principal_kind": preflight_principal.get("principal_kind"),
        "session_ref": preflight_principal.get("session_ref"),
        "caller_auth_mode": preflight.get("authentication", {}).get("auth_mode"),
        "principal_authenticated_by": preflight_principal.get("authenticated_by"),
        "permissions": preflight_principal.get("permissions"),
    }
    if snapshot_principal != expected_principal:
        violations.append("preflight_snapshot_binding:principal")
    path_bindings = {
        "canary_root_digest": "canary_root_path_digest",
        "home_path_digest": "home_path_digest",
        "xdg_config_path_digest": "xdg_config_path_digest",
        "xdg_state_path_digest": "xdg_state_path_digest",
        "xdg_cache_path_digest": "xdg_cache_path_digest",
        "registry_path_digest": "registry_path_digest",
        "project_root_digest": "project_root_digest",
        "runtime_executable_path_digest": "runtime_executable_path_digest",
        "cwd_path_digest": "cwd_path_digest",
        "settings_path_digest": "settings_path_digest",
        "ledger_path_digest": "ledger_path_digest",
        "backup_path_digest": "backup_path_digest",
        "activation_envelope_path_digest": "activation_envelope_path_digest",
        "claimed_activation_envelope_path_digest": (
            "claimed_activation_envelope_path_digest"
        ),
        "fixture_root_path_digest": "fixture_root_path_digest",
        "token_file_path_digest": "token_file_path_digest",
    }
    for runtime_field, preflight_field in path_bindings.items():
        source = (
            preflight.get("authentication", {})
            if preflight_field == "token_file_path_digest"
            else preflight_runtime
        )
        if runtime.get(runtime_field) != source.get(preflight_field):
            violations.append(f"preflight_snapshot_path_binding:{runtime_field}")
    scalar_bindings = {
        "database_generation": preflight.get("fresh_ledger", {}).get("database_generation"),
        "ledger_schema_version": preflight.get("fresh_ledger", {}).get("schema_version"),
        "fresh_ledger_baseline_digest": preflight.get("fresh_ledger", {}).get(
            "baseline_digest"
        ),
        "preflight_observed_at": preflight.get("observed_at"),
        "preflight_valid_until": preflight.get("valid_until"),
        "registry_project_count": preflight_runtime.get("registry_project_count"),
        "global_registry_fallback": False,
        "public_endpoint_created": preflight_runtime.get("public_endpoint_created"),
        "relay_enabled": preflight_runtime.get("relay_enabled"),
        "tunnel_enabled": preflight_runtime.get("tunnel_enabled"),
        "proxy_enabled": preflight_runtime.get("proxy_enabled"),
        "tool_allowlist_digest": preflight.get("restricted_surface", {}).get(
            "tool_allowlist_digest"
        ),
        "command_matrix_digest": preflight.get("restricted_surface", {}).get(
            "command_matrix_digest"
        ),
    }
    for field, expected in scalar_bindings.items():
        if runtime.get(field) != expected:
            violations.append(f"preflight_snapshot_binding:{field}")


def _verify_activation_contract_exports(
    receipt: dict[str, Any],
    evidence_root: Path,
    violations: list[str],
) -> None:
    envelope_path = _evidence_path(
        evidence_root,
        "evidence/claimed-activation-envelope.json",
        "claimed_activation_envelope",
        violations,
    )
    fixture_path = _evidence_path(
        evidence_root,
        "evidence/synthetic-fixture.json",
        "synthetic_fixture",
        violations,
    )
    if envelope_path is None or fixture_path is None:
        return
    try:
        envelope = _load_strict_json(envelope_path)
        fixture = _load_strict_json(fixture_path)
        validate_governance_record("work_item_activation_envelope.v1", envelope)
        validate_governance_record("work_item_synthetic_fixture_contract.v1", fixture)
        validate_synthetic_fixture_semantics(fixture)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError, WorkItemGovernanceError):
        violations.append("activation_contract_export_parse_or_semantics")
        return
    lease = receipt["activation_lease"]
    source = {
        key: receipt["source_binding"][key]
        for key in (
            "core_baseline_commit",
            "implementation_commit",
            "implementation_tree",
            "wheel_sha256",
        )
    }
    bindings = {
        "activation_envelope_digest": (
            canonical_sha256(envelope),
            lease["activation_envelope_digest"],
        ),
        "synthetic_fixture_contract_digest": (
            canonical_sha256(fixture),
            envelope.get("synthetic_fixture_contract_digest"),
            lease["synthetic_fixture_contract_digest"],
        ),
        "authorization_id": (
            envelope.get("authorization_id"),
            lease["authorization_id"],
        ),
        "authorization_digest": (
            envelope.get("authorization_digest"),
            lease["authorization_digest"],
        ),
        "lease_id": (
            envelope.get("activation_lease_id"),
            lease["lease_id"],
        ),
        "spec_manifest_digest": (
            envelope.get("spec_manifest_digest"),
            receipt["spec_binding"]["freeze_manifest_sha256"],
        ),
        "preflight_receipt_digest": (
            envelope.get("preflight_receipt_digest"),
            receipt["fresh_ledger"]["preflight_receipt_digest"],
        ),
        "source_binding": (envelope.get("source_binding"), source),
    }
    for field, values in bindings.items():
        if any(value != values[0] for value in values[1:]):
            violations.append(f"activation_contract_binding:{field}")


def _verify_runtime_and_surface_receipt_bindings(
    receipt: dict[str, Any],
    preflight: dict[str, Any],
    runtime: dict[str, Any],
    snapshot: dict[str, Any],
    violations: list[str],
) -> None:
    isolation = receipt["runtime_isolation"]
    preflight_runtime = preflight.get("runtime_isolation")
    runtime_listener = runtime.get("listener")
    snapshot_runtime = snapshot.get("runtime_binding")
    snapshot_bootstrap = snapshot.get("bootstrap")
    if not all(
        isinstance(value, dict)
        for value in (preflight_runtime, runtime_listener, snapshot_runtime, snapshot_bootstrap)
    ):
        violations.append("runtime_isolation_evidence_shape")
        return
    expected_isolation = {
        "home_under_canary_root": preflight_runtime.get("all_paths_under_canary_root"),
        "xdg_config_under_canary_root": preflight_runtime.get("all_paths_under_canary_root"),
        "xdg_state_under_canary_root": preflight_runtime.get("all_paths_under_canary_root"),
        "xdg_cache_under_canary_root": preflight_runtime.get("all_paths_under_canary_root"),
        "registry_under_canary_root": preflight_runtime.get("all_paths_under_canary_root"),
        "runtime_executable_under_canary_root": preflight_runtime.get(
            "all_paths_under_canary_root"
        ),
        "cwd_under_canary_root": preflight_runtime.get("all_paths_under_canary_root"),
        "project_root_under_canary_root": preflight_runtime.get("all_paths_under_canary_root"),
        "settings_under_canary_root": preflight_runtime.get("all_paths_under_canary_root"),
        "ledger_under_canary_root": preflight_runtime.get("all_paths_under_canary_root"),
        "backup_under_canary_root": preflight_runtime.get("all_paths_under_canary_root"),
        "token_file_under_canary_root": preflight_runtime.get("all_paths_under_canary_root"),
        "fixture_root_under_canary_root": preflight_runtime.get("all_paths_under_canary_root"),
        "activation_envelope_under_canary_root": preflight_runtime.get(
            "all_paths_under_canary_root"
        ),
        "claimed_activation_envelope_under_canary_root": preflight_runtime.get(
            "all_paths_under_canary_root"
        ),
        "global_registry_not_selected": not bool(
            preflight_runtime.get("global_registry_selected")
        ),
        "global_registry_not_open": not bool(preflight_runtime.get("global_registry_open")),
        "registry_project_count": preflight_runtime.get("registry_project_count"),
        "bind_address": preflight_runtime.get("intended_bind_address"),
        "port": preflight_runtime.get("intended_port"),
        "preclaim_listener_count": preflight_runtime.get("preclaim_listener_count"),
        "postclaim_listener_count": runtime_listener.get("process_listener_count"),
        "listener_attestation_digest": snapshot_runtime.get("listener_attestation_digest"),
        "authenticated_request_context_binding_digest": snapshot_runtime.get(
            "authenticated_request_context_binding_digest"
        ),
        "request_dispatch_before_listener_attestation": snapshot_bootstrap.get(
            "request_dispatch_before_listener_attestation"
        ),
        "public_endpoint_created": runtime_listener.get("public_endpoint_created"),
        "relay_enabled": runtime_listener.get("relay_enabled"),
        "tunnel_enabled": runtime_listener.get("tunnel_enabled"),
        "proxy_enabled": runtime_listener.get("proxy_enabled"),
        "background_side_effect_workers_started": preflight_runtime.get(
            "background_side_effect_workers_started"
        ),
    }
    for field, expected in expected_isolation.items():
        if isolation.get(field) != expected:
            violations.append(f"runtime_isolation_binding:{field}")
    tools = runtime.get("tool_names")
    surface_evidence = runtime.get("restricted_surface")
    surface = receipt["restricted_surface"]
    if not isinstance(tools, list) or not isinstance(surface_evidence, dict):
        violations.append("restricted_surface_evidence_shape")
        return
    expected_surface = {
        "profile": preflight.get("restricted_surface", {}).get("profile"),
        "listed_tool_count": len(tools),
        "listed_tools_sha256": canonical_sha256(tools),
        "definition_dispatch_exact_match": surface_evidence.get(
            "definition_dispatch_exact_match"
        ),
        "hidden_jsonrpc_call_rejected": surface_evidence.get(
            "hidden_jsonrpc_call_rejected"
        ),
        "direct_alias_rejected": surface_evidence.get("direct_alias_rejected"),
        "actions_disabled": surface_evidence.get("actions_disabled"),
        "agent_dispatch_enforced": surface_evidence.get("agent_dispatch_enforced"),
    }
    for field, expected in expected_surface.items():
        if surface.get(field) != expected:
            violations.append(f"restricted_surface_binding:{field}")


def _verify_exported_lease_evidence(
    receipt: dict[str, Any],
    evidence_root: Path,
    violations: list[str],
) -> None:
    root = evidence_root.expanduser().resolve()
    lease_receipt = receipt["activation_lease"]
    snapshot_path = _evidence_path(
        root,
        lease_receipt["lease_snapshot_export_relative_path"],
        "lease_snapshot",
        violations,
    )
    events_path = _evidence_path(
        root,
        lease_receipt["lease_event_export_relative_path"],
        "lease_events",
        violations,
    )
    if snapshot_path is None or events_path is None:
        return
    if sha256_file(snapshot_path) != lease_receipt["lease_snapshot_export_sha256"]:
        violations.append("lease_snapshot_export_digest")
    if sha256_file(events_path) != lease_receipt["lease_event_export_sha256"]:
        violations.append("lease_event_export_digest")
    try:
        snapshot = _load_strict_json(snapshot_path)
        events = _load_strict_json(events_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        violations.append(f"lease_evidence_parse:{type(exc).__name__}")
        return
    if not isinstance(snapshot, dict) or not isinstance(events, list):
        violations.append("lease_evidence_shape")
        return
    try:
        validate_governance_record("work_item_activation_lease.v1", snapshot)
    except WorkItemGovernanceError:
        violations.append("lease_snapshot_schema")
        return
    if canonical_sha256(snapshot) != lease_receipt["lease_snapshot_digest"]:
        violations.append("lease_snapshot_canonical_digest")
    expected_snapshot = {
        "lease_id": lease_receipt["lease_id"],
        "authorization_id": lease_receipt["authorization_id"],
        "authorization_digest": lease_receipt["authorization_digest"],
        "activation_envelope_digest": lease_receipt["activation_envelope_digest"],
        "status": lease_receipt["final_status"],
        "state_version": lease_receipt["final_state_version"],
        "spec_manifest_digest": receipt["spec_binding"]["freeze_manifest_sha256"],
        "lease_event_schema_digest": lease_receipt["lease_event_schema_digest"],
    }
    for field, expected in expected_snapshot.items():
        if snapshot.get(field) != expected:
            violations.append(f"lease_snapshot_binding:{field}")
    if snapshot.get("source_binding") != {
        "core_baseline_commit": receipt["source_binding"]["core_baseline_commit"],
        "implementation_commit": receipt["source_binding"]["implementation_commit"],
        "implementation_tree": receipt["source_binding"]["implementation_tree"],
        "wheel_sha256": receipt["source_binding"]["wheel_sha256"],
    }:
        violations.append("lease_snapshot_source_binding")
    runtime = snapshot.get("runtime_binding")
    scope = snapshot.get("scope")
    principal = snapshot.get("principal_binding")
    if not isinstance(runtime, dict) or not isinstance(scope, dict) or not isinstance(principal, dict):
        violations.append("lease_snapshot_nested_shape")
        return
    nested_bindings = {
        "claimed_envelope_path_digest": runtime.get("claimed_activation_envelope_path_digest"),
        "expected_process_identity": runtime.get("expected_process_identity"),
        "claimed_process_identity": runtime.get("claimed_process_identity"),
        "listener_attestation_digest": runtime.get("listener_attestation_digest"),
        "authenticated_request_context_binding_digest": runtime.get(
            "authenticated_request_context_binding_digest"
        ),
        "synthetic_fixture_contract_digest": scope.get("synthetic_fixture_contract_digest"),
        "principal_id": principal.get("principal_id"),
        "principal_kind": principal.get("principal_kind"),
        "session_ref": principal.get("session_ref"),
    }
    for field, actual in nested_bindings.items():
        if actual != lease_receipt[field]:
            violations.append(f"lease_snapshot_binding:{field}")
    if canonical_sha256(principal) != lease_receipt["principal_binding_digest"]:
        violations.append("principal_binding_digest")
    expected_root_digest = canonical_sha256({"resolved_posix_path": root.as_posix()})
    if lease_receipt["evidence_export_root_path_digest"] != expected_root_digest:
        violations.append("evidence_export_root_path_digest")
    if lease_receipt["lease_event_schema_digest"] != receipt["spec_binding"]["lease_event_schema_sha256"]:
        violations.append("lease_event_schema_digest")
    _verify_exported_event_chain(
        events=events,
        snapshot=snapshot,
        lease_receipt=lease_receipt,
        violations=violations,
    )


def _verify_exported_event_chain(
    *,
    events: list[Any],
    snapshot: dict[str, Any],
    lease_receipt: dict[str, Any],
    violations: list[str],
) -> None:
    if len(events) != lease_receipt["lease_event_count"] or not events:
        violations.append("lease_event_count")
        return
    prior_digest: str | None = None
    prior_status: str | None = None
    prior_version = 0
    prior_created_at = None
    digests: list[str] = []
    snapshot_created = parse_timestamp(snapshot["created_at"], "lease.created_at")
    snapshot_updated = parse_timestamp(snapshot["updated_at"], "lease.updated_at")
    for sequence, event in enumerate(events, 1):
        if not isinstance(event, dict):
            violations.append(f"lease_event_shape:{sequence}")
            continue
        try:
            validate_governance_record("work_item_activation_lease_event.v1", event)
        except WorkItemGovernanceError:
            violations.append(f"lease_event_schema:{sequence}")
            continue
        unsigned = {key: value for key, value in event.items() if key != "event_digest"}
        if event["event_digest"] != canonical_sha256(unsigned):
            violations.append(f"lease_event_digest:{sequence}")
        if event["sequence"] != sequence or event["previous_event_digest"] != prior_digest:
            violations.append(f"lease_event_chain:{sequence}")
        if event["state_version_before"] != prior_version:
            violations.append(f"lease_event_state_version:{sequence}")
        if sequence == 1:
            if event["state_version_after"] != 0:
                violations.append(f"lease_event_state_version_delta:{sequence}")
        elif event["state_version_after"] != event["state_version_before"] + 1:
            violations.append(f"lease_event_state_version_delta:{sequence}")
        if sequence > 1 and event["status_before"] != prior_status:
            violations.append(f"lease_event_status:{sequence}")
        if event["lease_id"] != lease_receipt["lease_id"]:
            violations.append(f"lease_event_lease_binding:{sequence}")
        prior_digest = str(event["event_digest"])
        prior_status = str(event["status_after"])
        prior_version = int(event["state_version_after"])
        try:
            created_at = parse_timestamp(event["created_at"], f"lease_event.created_at:{sequence}")
            if created_at < snapshot_created or created_at > snapshot_updated:
                violations.append(f"lease_event_time_bounds:{sequence}")
            if prior_created_at is not None and created_at < prior_created_at:
                violations.append(f"lease_event_time_order:{sequence}")
            prior_created_at = created_at
        except (KeyError, TypeError, ValueError, WorkItemGovernanceError):
            violations.append(f"lease_event_time_parse:{sequence}")
        digests.append(prior_digest)
    if canonical_sha256(digests) != lease_receipt["lease_event_root_sha256"]:
        violations.append("lease_event_root")
    if (
        prior_status != snapshot.get("status")
        or prior_version != snapshot.get("state_version")
        or prior_status != lease_receipt["final_status"]
        or prior_version != lease_receipt["final_state_version"]
        or snapshot.get("usage", {}).get("lease_events") != len(events)
    ):
        violations.append("lease_event_final_reconciliation")


def _verify_protected_assets(
    receipt: dict[str, Any],
    project_root: Path,
    violations: list[str],
) -> None:
    root = project_root.expanduser().resolve()
    asset_paths = [str(item["path"]) for item in receipt["protected_user_assets"]["assets"]]
    for item in receipt["protected_user_assets"]["assets"]:
        target = (root / item["path"]).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            violations.append(f"protected_asset_path_escape:{item['path']}")
            continue
        if not target.is_file():
            violations.append(f"protected_asset_missing:{item['path']}")
        elif sha256_file(target) != item["sha256"]:
            violations.append(f"protected_asset_digest:{item['path']}")
    staged = subprocess.run(  # nosec B603 B607
        ["git", "diff", "--cached", "--name-only", "--", *asset_paths],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    committed = subprocess.run(  # nosec B603 B607
        ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD^", "HEAD", "--", *asset_paths],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if staged.returncode != 0 or staged.stdout.strip() or receipt["protected_user_assets"]["staged"]:
        violations.append("protected_assets_staged")
    if (
        committed.returncode != 0
        or committed.stdout.strip()
        or receipt["protected_user_assets"]["committed"]
    ):
        violations.append("protected_assets_committed")


def _evidence_path(
    root: Path,
    relative: str,
    label: str,
    violations: list[str],
) -> Path | None:
    target = (root / relative).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        violations.append(f"evidence_path_escape:{label}")
        return None
    if not target.is_file():
        violations.append(f"evidence_missing:{label}")
        return None
    return target


def _load_strict_json(path: Path) -> Any:
    if path.stat().st_size > MAX_JSON_BYTES:
        raise ValueError("JSON evidence exceeds the canonical size limit")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f"duplicate JSON object key: {key}")
            value[key] = item
        return value

    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=reject_duplicates,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"non-finite JSON: {value}")),
    )


__all__ = ["REQUIRED_VERIFICATION_NAMES", "verify_r2_closeout_receipt"]
