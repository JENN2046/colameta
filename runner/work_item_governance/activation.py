from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import sqlite3
import stat
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path
from typing import Any, Callable

from runner.work_item_governance.canonical import canonical_json, canonical_sha256, sha256_file
from runner.work_item_governance.errors import CommitWorkItemRejection, WorkItemGovernanceError
from runner.work_item_governance.ids import new_stable_id
from runner.work_item_governance.preview import isoformat_utc, parse_timestamp, utc_now
from runner.work_item_governance.principal import PrincipalContext
from runner.work_item_governance.repository import SQLiteWorkItemLedger
from runner.work_item_governance.request_context import (
    AuthenticatedTokenRequestProof,
    AuthoritativeCanaryRequestContext,
    _mint_authoritative_request_context,
)
from runner.work_item_governance.schema_loader import (
    load_governance_contract,
    validate_governance_record,
)


R2_SPEC_FREEZE_MANIFEST_SHA256 = "9bc0209f10dfb9b6b3583db66af443957e598982383bf1c5e88e6029cb4b0404"
AUTHORITATIVE_CANARY_PROFILE = "authoritative_canary"
# These are public Ledger metadata keys, not embedded credentials.
AUTHORITATIVE_TOKEN_FILE_SHA256_META_KEY = (  # nosec B105
    "authoritative_canary_token_file_sha256"
)
AUTHORITATIVE_TOKEN_EVIDENCE_DIGEST_META_KEY = (  # nosec B105
    "authoritative_canary_token_evidence_digest"
)
_AUTHORITATIVE_TOKEN_PATTERN = re.compile(r"mvr_([A-Za-z0-9_-]{43})")
ALLOWED_WRITE_COMMANDS = (
    "apply_work_item_create",
    "add_task_version",
    "create_execution_attempt",
    "complete_execution_attempt",
    "register_artifact_reference",
    "record_review_decision",
    "apply_work_item_transition",
)
DENIED_WRITE_COMMANDS = (
    "apply_legacy_work_item_import",
    "bind_historical_execution_attempt",
    "apply_blocker",
    "clear_blocker",
    "create_delivery_receipt",
    "retry_delivery",
    "acknowledge_delivery",
    "record_outbox_delivery_result",
    "recover_outbox_event",
)
AUTHORITATIVE_CANARY_TOOLS = (
    "get_work_item_governance_status",
    "get_work_item",
    "list_work_items",
    "get_work_item_timeline",
    "get_execution_attempt_dispatch_authority",
    "preview_work_item_create",
    "preview_work_item_transition",
    *ALLOWED_WRITE_COMMANDS,
)
DEFAULT_QUOTAS = {
    "maximum_new_work_items": 1,
    "maximum_task_versions": 2,
    "maximum_runtime_attempts": 2,
    "maximum_artifacts": 4,
    "maximum_decisions": 4,
    "maximum_applied_gate_events": 8,
    "maximum_rejected_gate_events": 8,
    "maximum_gate_events_total": 16,
    "maximum_lease_events": 40,
}
EMPTY_USAGE = {
    "new_work_items": 0,
    "task_versions": 0,
    "runtime_attempts": 0,
    "artifacts": 0,
    "decisions": 0,
    "applied_gate_events": 0,
    "rejected_gate_events": 0,
    "gate_events_total": 0,
    "lease_events": 1,
}
FACT_TO_QUOTA = {
    "new_work_items": "maximum_new_work_items",
    "task_versions": "maximum_task_versions",
    "runtime_attempts": "maximum_runtime_attempts",
    "artifacts": "maximum_artifacts",
    "decisions": "maximum_decisions",
    "applied_gate_events": "maximum_applied_gate_events",
    "rejected_gate_events": "maximum_rejected_gate_events",
    "gate_events_total": "maximum_gate_events_total",
}
HARD_REQUEST_BINDING_ERRORS = frozenset(
    {
        "ACTIVATION_PRINCIPAL_MISMATCH",
        "REQUEST_CONTEXT_BINDING_MISMATCH",
        "REQUEST_CONTEXT_PRINCIPAL_MISMATCH",
        "ACTIVATION_PROCESS_RESTARTED",
    }
)
DOMAIN_FACT_KEYS = (
    "work_items",
    "task_versions",
    "runtime_attempts",
    "attempt_events",
    "artifacts",
    "decisions",
    "applied_gate_events",
    "rejected_gate_events",
    "audit_events",
    "outbox_events",
    "acceptance_manifests",
)
ZERO_BUSINESS_TABLES = (
    "work_items",
    "task_versions",
    "execution_attempts",
    "artifact_refs",
    "decision_records",
    "gate_events",
    "acceptance_manifests",
    "delivery_receipts",
    "audit_events",
    "blocker_events",
    "outbox_events",
    "inbox_events",
)
BUSINESS_FACT_COUNT_QUERIES = {
    "work_items": "SELECT COUNT(*) FROM work_items",
    "task_versions": "SELECT COUNT(*) FROM task_versions",
    "execution_attempts": "SELECT COUNT(*) FROM execution_attempts",
    "artifact_refs": "SELECT COUNT(*) FROM artifact_refs",
    "decision_records": "SELECT COUNT(*) FROM decision_records",
    "gate_events": "SELECT COUNT(*) FROM gate_events",
    "acceptance_manifests": "SELECT COUNT(*) FROM acceptance_manifests",
    "delivery_receipts": "SELECT COUNT(*) FROM delivery_receipts",
    "audit_events": "SELECT COUNT(*) FROM audit_events",
    "blocker_events": "SELECT COUNT(*) FROM blocker_events",
    "outbox_events": "SELECT COUNT(*) FROM outbox_events",
    "inbox_events": "SELECT COUNT(*) FROM inbox_events",
}
SCOPED_FACT_TOTAL_QUERIES = {
    "work_items": ("SELECT COUNT(*) FROM work_items", "new_work_items"),
    "task_versions": ("SELECT COUNT(*) FROM task_versions", "task_versions"),
    "execution_attempts": (
        "SELECT COUNT(*) FROM execution_attempts WHERE attempt_kind='runtime'",
        "runtime_attempts",
    ),
    "artifact_refs": ("SELECT COUNT(*) FROM artifact_refs", "artifacts"),
    "decision_records": ("SELECT COUNT(*) FROM decision_records", "decisions"),
    "gate_events": ("SELECT COUNT(*) FROM gate_events", "gate_events_total"),
}
DERIVED_FACT_COUNT_QUERIES = {
    "audit_events": "SELECT COUNT(*) FROM audit_events",
    "outbox_events": "SELECT COUNT(*) FROM outbox_events",
}
DENIED_FACT_COUNT_QUERIES = {
    "external_associations": "SELECT COUNT(*) FROM external_associations",
    "delivery_receipts": "SELECT COUNT(*) FROM delivery_receipts",
    "blocker_events": "SELECT COUNT(*) FROM blocker_events",
    "inbox_events": "SELECT COUNT(*) FROM inbox_events",
}
FRESH_EXECUTION_FACT_COUNT_QUERIES = {
    "external_associations": "SELECT COUNT(*) FROM external_associations",
    "attempt_events": "SELECT COUNT(*) FROM attempt_events",
}


def canonical_path_digest(path: str | os.PathLike[str]) -> str:
    resolved = Path(path).expanduser().resolve()
    return canonical_sha256({"resolved_posix_path": resolved.as_posix()})


def validate_authoritative_bearer_token(token: str) -> str:
    """Validate the exact 256-bit base64url Canary token representation.

    The format check is not used as proof of CSPRNG provenance; that proof is
    supplied by the preflight evidence and exact auth-file binding.  It does
    reject malformed and obviously low-diversity stand-ins before startup.
    """

    match = _AUTHORITATIVE_TOKEN_PATTERN.fullmatch(token) if isinstance(token, str) else None
    if match is None:
        raise WorkItemGovernanceError(
            "ACTIVATION_TOKEN_CONFIGURATION_INVALID",
            "Authoritative Canary Token must use the exact mvr_ + 256-bit base64url format.",
        )
    body = match.group(1)
    try:
        decoded = base64.urlsafe_b64decode(body + "=")
    except (ValueError, binascii.Error) as exc:
        raise WorkItemGovernanceError(
            "ACTIVATION_TOKEN_CONFIGURATION_INVALID",
            "Authoritative Canary Token is not valid base64url.",
        ) from exc
    if len(decoded) != 32 or len(set(decoded)) < 16:
        raise WorkItemGovernanceError(
            "ACTIVATION_TOKEN_CONFIGURATION_INVALID",
            "Authoritative Canary Token does not satisfy the 256-bit material contract.",
        )
    return token


def read_authoritative_token_file(
    auth_file: str | os.PathLike[str],
) -> tuple[str, dict[str, Any]]:
    """Read one private auth file once and return its validated secret and public evidence."""

    path = Path(auth_file).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    path = Path(os.path.abspath(path))
    if path.is_symlink():
        raise WorkItemGovernanceError(
            "ACTIVATION_TOKEN_CONFIGURATION_INVALID",
            "Authoritative Canary auth.json must not be a symbolic link.",
        )
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise WorkItemGovernanceError(
            "ACTIVATION_TOKEN_CONFIGURATION_INVALID",
            "Authoritative Canary auth.json is not readable.",
        ) from exc
    try:
        file_stat = os.fstat(descriptor)
        if (
            not stat.S_ISREG(file_stat.st_mode)
            or stat.S_IMODE(file_stat.st_mode) != 0o600
            or file_stat.st_uid != os.getuid()
        ):
            raise WorkItemGovernanceError(
                "ACTIVATION_TOKEN_CONFIGURATION_INVALID",
                "Authoritative Canary auth.json must be an owned 0600 regular file.",
            )
        if stat.S_IMODE(path.parent.stat().st_mode) & 0o077:
            raise WorkItemGovernanceError(
                "ACTIVATION_TOKEN_CONFIGURATION_INVALID",
                "Authoritative Canary auth.json parent must be 0700 or stricter.",
            )
        chunks: list[bytes] = []
        bytes_read = 0
        while bytes_read <= 16_384:
            chunk = os.read(descriptor, min(4096, 16_385 - bytes_read))
            if not chunk:
                break
            chunks.append(chunk)
            bytes_read += len(chunk)
        raw = b"".join(chunks)
    finally:
        os.close(descriptor)
    if len(raw) > 16_384:
        raise WorkItemGovernanceError(
            "ACTIVATION_TOKEN_CONFIGURATION_INVALID",
            "Authoritative Canary auth.json exceeds the private control-plane size limit.",
        )
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorkItemGovernanceError(
            "ACTIVATION_TOKEN_CONFIGURATION_INVALID",
            "Authoritative Canary auth.json is invalid JSON.",
        ) from exc
    token = payload.get("auth_token") if isinstance(payload, dict) else None
    validate_authoritative_bearer_token(token)
    evidence = {
        "algorithm": "os_csprng_256_bits_minimum_base64url",
        "entropy_bits": 256,
        "token_sha256": hashlib.sha256(raw).hexdigest(),
        "auth_file_path_digest": canonical_path_digest(path),
    }
    return token, evidence


def require_authoritative_token_file_binding(
    ledger: SQLiteWorkItemLedger,
    auth_file: str | os.PathLike[str],
    *,
    expected_evidence_digest: str | None = None,
) -> str:
    """Require auth.json to match the exact bytes sealed into the fresh Ledger."""

    token, evidence = read_authoritative_token_file(auth_file)
    evidence_digest = canonical_sha256(evidence)
    with ledger.read_connection() as connection:
        rows = connection.execute(
            "SELECT key,value FROM ledger_meta WHERE key IN (?,?)",
            (
                AUTHORITATIVE_TOKEN_FILE_SHA256_META_KEY,
                AUTHORITATIVE_TOKEN_EVIDENCE_DIGEST_META_KEY,
            ),
        ).fetchall()
    binding = {str(row["key"]): str(row["value"]) for row in rows}
    if (
        binding.get(AUTHORITATIVE_TOKEN_FILE_SHA256_META_KEY) != evidence["token_sha256"]
        or binding.get(AUTHORITATIVE_TOKEN_EVIDENCE_DIGEST_META_KEY) != evidence_digest
        or (expected_evidence_digest is not None and expected_evidence_digest != evidence_digest)
    ):
        raise WorkItemGovernanceError(
            "ACTIVATION_TOKEN_BINDING_MISMATCH",
            "Authoritative Canary auth.json differs from the exact fresh-Ledger binding.",
        )
    return token


def _resource_sha256(filename: str) -> str:
    resource = resources.files("schemas").joinpath("work_item_governance", filename)
    return sha256_file(str(resource))


def _json(row: sqlite3.Row, field: str) -> dict[str, Any]:
    value = json.loads(str(row[field]))
    if not isinstance(value, dict):
        raise WorkItemGovernanceError(
            "ACTIVATION_LEASE_CORRUPT",
            "Activation Lease JSON field must be an object.",
            details={"field": field},
        )
    return value


def _strict_window(not_before: str, expires_at: str, maximum_seconds: int) -> tuple[datetime, datetime]:
    start = parse_timestamp(not_before, "not_before")
    end = parse_timestamp(expires_at, "expires_at")
    if start >= end or (end - start).total_seconds() > maximum_seconds:
        raise WorkItemGovernanceError(
            "ACTIVATION_WINDOW_INVALID",
            "Activation window must be ordered and no longer than the frozen maximum.",
        )
    return start, end


def process_identity_inputs(runtime_instance_nonce: str, *, pid: int | None = None) -> dict[str, Any]:
    process_id = os.getpid() if pid is None else int(pid)
    proc_root = Path("/proc") / str(process_id)
    try:
        stat_text = (proc_root / "stat").read_text(encoding="utf-8")
        remainder = stat_text[stat_text.rfind(")") + 2 :].split()
        process_start_ticks = int(remainder[19])
        boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip().lower()
        executable = (proc_root / "exe").resolve()
        executable_sha256 = sha256_file(executable)
    except (OSError, ValueError, IndexError) as exc:
        raise WorkItemGovernanceError(
            "PROCESS_IDENTITY_UNAVAILABLE",
            "The Linux process identity inputs could not be read.",
            details={"pid": process_id, "reason": str(exc)},
        ) from exc
    payload = {
        "pid": process_id,
        "process_start_ticks": process_start_ticks,
        "boot_id": boot_id,
        "executable_sha256": executable_sha256,
        "runtime_instance_nonce": runtime_instance_nonce,
    }
    return {
        **payload,
        "identity_algorithm": (
            "sha256(canonical_json({pid,process_start_ticks,boot_id,"
            "executable_sha256,runtime_instance_nonce}))"
        ),
        "expected_process_identity": canonical_sha256(payload),
    }


def listener_attestation_digest(
    *,
    claimed_process_identity: str,
    bind_address: str,
    port: int,
    process_listener_count: int,
    public_endpoint_created: bool = False,
    relay_enabled: bool = False,
    tunnel_enabled: bool = False,
    proxy_enabled: bool = False,
) -> str:
    return canonical_sha256(
        {
            "claimed_process_identity": claimed_process_identity,
            "bind_address": bind_address,
            "port": port,
            "process_listener_count": process_listener_count,
            "public_endpoint_created": public_endpoint_created,
            "relay_enabled": relay_enabled,
            "tunnel_enabled": tunnel_enabled,
            "proxy_enabled": proxy_enabled,
        }
    )


def request_context_binding_digest(
    *,
    lease_id: str,
    authorization_digest: str,
    claimed_process_identity: str,
    runtime_instance_nonce: str,
    listener_digest: str,
    principal_id: str,
    session_ref: str,
) -> str:
    return canonical_sha256(
        {
            "lease_id": lease_id,
            "authorization_digest": authorization_digest,
            "claimed_process_identity": claimed_process_identity,
            "runtime_instance_nonce": runtime_instance_nonce,
            "listener_attestation_digest": listener_digest,
            "principal_id": principal_id,
            "session_ref": session_ref,
        }
    )


def business_fact_counts(connection: sqlite3.Connection) -> dict[str, int]:
    return {
        table: int(connection.execute(BUSINESS_FACT_COUNT_QUERIES[table]).fetchone()[0])
        for table in ZERO_BUSINESS_TABLES
    }


def validate_runtime_policy_contracts() -> dict[str, Any]:
    allowlist = load_governance_contract("authoritative_canary_tool_allowlist.v1")
    matrix = load_governance_contract("work_item_write_command_matrix.v1")
    declared_tools = tuple(item["name"] for item in allowlist.get("tools", []))
    if declared_tools != AUTHORITATIVE_CANARY_TOOLS:
        raise WorkItemGovernanceError(
            "ACTIVATION_TOOL_ALLOWLIST_MISMATCH",
            "Runtime Authoritative Canary tools differ from the frozen contract.",
        )
    commands = matrix.get("commands")
    if not isinstance(commands, list):
        raise WorkItemGovernanceError(
            "ACTIVATION_COMMAND_MATRIX_INVALID",
            "Frozen Work Item command matrix is invalid.",
        )
    allowed = tuple(item["name"] for item in commands if item.get("allowed") is True)
    denied = tuple(item["name"] for item in commands if item.get("allowed") is False)
    if allowed != ALLOWED_WRITE_COMMANDS or denied != DENIED_WRITE_COMMANDS:
        raise WorkItemGovernanceError(
            "ACTIVATION_COMMAND_MATRIX_MISMATCH",
            "Runtime Work Item write classification differs from the frozen matrix.",
        )
    return {
        "tool_count": len(declared_tools),
        "allowed_write_count": len(allowed),
        "denied_write_count": len(denied),
        "tool_allowlist_digest": _resource_sha256("authoritative-canary-tool-allowlist.v1.json"),
        "command_matrix_digest": _resource_sha256("work-item-write-command-matrix.v1.json"),
    }


def validate_synthetic_fixture_semantics(fixture: dict[str, Any]) -> dict[str, Any]:
    """Validate the cross-field rules JSON Schema cannot express."""

    validate_governance_record("work_item_synthetic_fixture_contract.v1", fixture)
    errors: list[str] = []
    normalized_create = fixture["normalized_create"]
    if canonical_sha256(normalized_create["normalized_command"]) != normalized_create["normalized_command_digest"]:
        errors.append("normalized_create_digest")
    for item in fixture["task_versions"]:
        if canonical_sha256(item["normalized_payload"]) != item["normalized_payload_digest"]:
            errors.append(f"task_version_digest:{item['slot']}")
    for item in fixture["runtime_attempts"]:
        if canonical_sha256(item["objective_ref"]) != item["objective_ref_digest"]:
            errors.append(f"runtime_objective_digest:{item['slot']}")
    slots = fixture["command_slots"]
    generated: list[str] = []
    decision_actions: list[str] = []
    new_slots: list[dict[str, Any]] = []
    for index, slot in enumerate(slots, 1):
        command = slot["normalized_command"]
        if slot["sequence"] != index:
            errors.append(f"slot_sequence:{index}")
        if canonical_sha256(command) != slot["normalized_command_digest"]:
            errors.append(f"slot_command_digest:{index}")
        source_key = command.get("source_event_key") or command.get("idempotency_key")
        if not isinstance(source_key, str) or not source_key:
            errors.append(f"slot_idempotency_source:{index}")
        elif canonical_sha256(
            {"command_name": slot["command_name"], "source_event_key": source_key}
        ) != slot["idempotency_binding_digest"]:
            errors.append(f"slot_idempotency_digest:{index}")
        delta = slot["expected_fact_delta"]
        if slot["expected_outcome"] == "exact_idempotent_replay":
            if any(delta.values()) or slot["generated_binding_slots"]:
                errors.append(f"replay_creates_fact:{index}")
        else:
            generated.extend(slot["generated_binding_slots"])
            new_slots.append(slot)
        if slot["command_name"] == "record_review_decision" and slot["expected_outcome"] != "exact_idempotent_replay":
            decision_actions.append(command.get("action"))
    placeholders = fixture["generated_id_placeholders"]
    expected_generated = {
        placeholders["work_item"],
        *placeholders["attempts"],
        *placeholders["artifacts"],
        *placeholders["decisions"],
        *placeholders["gate_events"],
    }
    if len(generated) != len(set(generated)) or set(generated) != expected_generated:
        errors.append("generated_placeholder_coverage")
    if decision_actions != fixture["decision_actions"]:
        errors.append("decision_action_sequence")
    if set(slot["command_name"] for slot in slots) != set(fixture["required_command_names"]):
        errors.append("required_command_coverage")
    artifact_task_slots = {int(item["task_version_slot"]) for item in fixture["artifact_files"]}
    if artifact_task_slots != {1, 2}:
        errors.append("artifact_task_version_coverage")
    create_slots = [item for item in new_slots if item["command_name"] == "apply_work_item_create"]
    if len(create_slots) != 1 or create_slots[0]["normalized_command"] != normalized_create["normalized_command"]:
        errors.append("normalized_create_slot_binding")
    else:
        create = create_slots[0]["normalized_command"]
        origin = create.get("origin", {})
        if origin.get("kind") != fixture["origin"]["kind"] or origin.get("ref") != fixture["origin"]["ref"]:
            errors.append("origin_binding")
        if create.get("task") != fixture["task_versions"][0]["normalized_payload"]:
            errors.append("initial_task_binding")
    task_slots = [item for item in new_slots if item["command_name"] == "add_task_version"]
    if len(task_slots) != 1 or task_slots[0]["normalized_command"].get("task") != fixture["task_versions"][1][
        "normalized_payload"
    ]:
        errors.append("second_task_binding")
    attempt_slots = [item for item in new_slots if item["command_name"] == "create_execution_attempt"]
    if len(attempt_slots) != 2:
        errors.append("runtime_attempt_slot_count")
    else:
        for declaration, slot in zip(fixture["runtime_attempts"], attempt_slots, strict=True):
            command = slot["normalized_command"]
            if (
                command.get("objective_ref") != declaration["objective_ref"]
                or command.get("task_version") != declaration["task_version_slot"]
                or command.get("external_refs") != []
            ):
                errors.append(f"runtime_attempt_binding:{declaration['slot']}")
    transition_slots = [item for item in new_slots if item["command_name"] == "apply_work_item_transition"]
    if len(transition_slots) != len(fixture["required_lifecycle_transitions"]):
        errors.append("lifecycle_transition_slot_count")
    else:
        for declaration, slot in zip(
            fixture["required_lifecycle_transitions"],
            transition_slots,
            strict=True,
        ):
            command = slot["normalized_command"]
            if (
                command.get("task_version") != declaration["task_version_slot"]
                or command.get("target_state") != declaration["to_state"]
            ):
                errors.append(f"lifecycle_transition_binding:{declaration['sequence']}")
    artifact_commands: list[dict[str, Any]] = []
    for slot in new_slots:
        command = slot["normalized_command"]
        if slot["command_name"] == "register_artifact_reference":
            artifact_commands.append(command)
        elif slot["command_name"] == "complete_execution_attempt":
            artifacts = command.get("artifacts", [])
            if isinstance(artifacts, list):
                artifact_commands.extend(item for item in artifacts if isinstance(item, dict))
    declared_artifacts = fixture["artifact_files"]
    if len(artifact_commands) != len(declared_artifacts):
        errors.append("artifact_command_count")
    else:
        for declaration, command in zip(declared_artifacts, artifact_commands, strict=True):
            uri = str(command.get("uri", ""))
            if (
                command.get("kind") != declaration["kind"]
                or command.get("digest") != declaration["sha256"]
                or command.get("task_version") != declaration["task_version_slot"]
                or not uri.startswith("file://")
                or not uri.endswith(declaration["relative_path"])
            ):
                errors.append(f"artifact_binding:{declaration['slot']}")
    if errors:
        raise WorkItemGovernanceError(
            "SYNTHETIC_FIXTURE_SEMANTICS_INVALID",
            "Synthetic Fixture cross-field semantics are invalid.",
            details={"violations": errors},
        )
    return {
        "fixture_digest": canonical_sha256(fixture),
        "command_slot_count": len(slots),
        "generated_binding_count": len(generated),
        "semantic_checks": "passed",
    }


def verify_activation_lease_event_chain(
    ledger: SQLiteWorkItemLedger,
    lease_id: str,
) -> dict[str, Any]:
    with ledger.read_connection() as connection:
        lease = connection.execute(
            "SELECT * FROM activation_leases WHERE lease_id=?",
            (lease_id,),
        ).fetchone()
        rows = connection.execute(
            "SELECT * FROM activation_lease_events WHERE lease_id=? ORDER BY sequence",
            (lease_id,),
        ).fetchall()
    if lease is None or not rows:
        raise WorkItemGovernanceError(
            "ACTIVATION_LEASE_EVIDENCE_MISSING",
            "Activation Lease or Event evidence is missing.",
        )
    prior_digest: str | None = None
    prior_status: str | None = None
    prior_version = 0
    digests: list[str] = []
    for sequence, row in enumerate(rows, 1):
        event = json.loads(str(row["event_json"]))
        validate_governance_record("work_item_activation_lease_event.v1", event)
        unsigned = {key: value for key, value in event.items() if key != "event_digest"}
        if (
            event["sequence"] != sequence
            or row["sequence"] != sequence
            or event["previous_event_digest"] != prior_digest
            or event["event_digest"] != canonical_sha256(unsigned)
            or event["event_digest"] != row["event_digest"]
            or event["state_version_before"] != prior_version
            or (sequence > 1 and event["status_before"] != prior_status)
        ):
            raise WorkItemGovernanceError(
                "ACTIVATION_LEASE_EVENT_CHAIN_INVALID",
                "Activation Lease Event chain, digest, status, or state version is invalid.",
                details={"sequence": sequence},
            )
        prior_digest = str(event["event_digest"])
        prior_status = str(event["status_after"])
        prior_version = int(event["state_version_after"])
        digests.append(prior_digest)
    usage = _json(lease, "usage_json")
    if (
        int(usage["lease_events"]) != len(rows)
        or int(lease["state_version"]) != prior_version
        or str(lease["status"]) != prior_status
    ):
        raise WorkItemGovernanceError(
            "ACTIVATION_LEASE_EVENT_RECONCILIATION_FAILED",
            "Final Lease state does not match its append-only Event chain.",
        )
    return {
        "lease_id": lease_id,
        "event_count": len(rows),
        "event_root_sha256": canonical_sha256(digests),
        "final_status": prior_status,
        "final_state_version": prior_version,
        "chain_verified": True,
    }


def _activation_domain_fact_counts(connection: sqlite3.Connection) -> dict[str, int]:
    """Counts every fact type frozen by the synthetic Fixture contract."""

    return {
        "work_items": int(connection.execute("SELECT COUNT(*) FROM work_items").fetchone()[0]),
        "task_versions": int(connection.execute("SELECT COUNT(*) FROM task_versions").fetchone()[0]),
        "runtime_attempts": int(
            connection.execute(
                "SELECT COUNT(*) FROM execution_attempts WHERE attempt_kind='runtime'"
            ).fetchone()[0]
        ),
        "attempt_events": int(connection.execute("SELECT COUNT(*) FROM attempt_events").fetchone()[0]),
        "artifacts": int(connection.execute("SELECT COUNT(*) FROM artifact_refs").fetchone()[0]),
        "decisions": int(connection.execute("SELECT COUNT(*) FROM decision_records").fetchone()[0]),
        "applied_gate_events": int(
            connection.execute(
                "SELECT COUNT(*) FROM gate_events WHERE outcome='transition_applied'"
            ).fetchone()[0]
        ),
        "rejected_gate_events": int(
            connection.execute(
                "SELECT COUNT(*) FROM gate_events WHERE outcome='transition_rejected'"
            ).fetchone()[0]
        ),
        "audit_events": int(connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]),
        "outbox_events": int(connection.execute("SELECT COUNT(*) FROM outbox_events").fetchone()[0]),
        "acceptance_manifests": int(
            connection.execute("SELECT COUNT(*) FROM acceptance_manifests").fetchone()[0]
        ),
    }


def _lease_record(row: sqlite3.Row) -> dict[str, Any]:
    runtime = _json(row, "runtime_binding_json")
    runtime.update(
        {
            "claimed_process_identity": row["claimed_process_identity"],
            "listener_attested_at": row["listener_attested_at"],
            "listener_attestation_digest": row["listener_attestation_digest"],
            "authenticated_request_context_binding_digest": row["request_context_binding_digest"],
            "monotonic_claim_ns": row["monotonic_claim_ns"],
            "monotonic_deadline_ns": row["monotonic_deadline_ns"],
        }
    )
    scope = _json(row, "scope_json")
    scope["authorized_work_item_id"] = row["authorized_work_item_id"]
    return {
        "schema_version": row["schema_version"],
        "lease_id": row["lease_id"],
        "authorization_id": row["authorization_id"],
        "authorization_digest": row["authorization_digest"],
        "activation_envelope_digest": row["activation_envelope_digest"],
        "spec_manifest_digest": row["spec_manifest_digest"],
        "activation_envelope_schema_digest": _resource_sha256("activation-envelope.v1.schema.json"),
        "synthetic_fixture_schema_digest": _resource_sha256("synthetic-fixture-contract.v1.schema.json"),
        "preflight_receipt_schema_digest": _resource_sha256("preflight-receipt.v1.schema.json"),
        "lease_event_schema_digest": _resource_sha256("activation-lease-event.v1.schema.json"),
        "source_binding": _json(row, "source_binding_json"),
        "runtime_binding": runtime,
        "principal_binding": _json(row, "principal_binding_json"),
        "bootstrap": _json(row, "bootstrap_json"),
        "window": {
            "issued_at": row["created_at"],
            "not_before": row["not_before"],
            "expires_at": row["expires_at"],
            "maximum_runtime_seconds": row["maximum_runtime_seconds"],
        },
        "scope": scope,
        "fixture_bindings": _json(row, "fixture_bindings_json"),
        "quotas": _json(row, "quotas_json"),
        "usage": _json(row, "usage_json"),
        "policy": _json(row, "policy_json"),
        "maintenance": _json(row, "maintenance_json"),
        "failure_behavior": _json(row, "failure_behavior_json"),
        "status": row["status"],
        "state_version": row["state_version"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _append_lease_event(
    connection: sqlite3.Connection,
    *,
    row: sqlite3.Row,
    event_type: str,
    status_before: str | None,
    status_after: str,
    state_version_before: int,
    state_version_after: int,
    created_at: str,
    command_name: str | None = None,
    source_event_key_digest: str | None = None,
    domain_fact_delta_digest: str | None = None,
    principal_binding_digest: str | None = None,
    reason_code: str | None = None,
) -> dict[str, Any]:
    previous = connection.execute(
        "SELECT sequence,event_digest FROM activation_lease_events WHERE lease_id=? ORDER BY sequence DESC LIMIT 1",
        (row["lease_id"],),
    ).fetchone()
    sequence = 1 if previous is None else int(previous["sequence"]) + 1
    if sequence > DEFAULT_QUOTAS["maximum_lease_events"]:
        raise WorkItemGovernanceError(
            "ACTIVATION_LEASE_EVENT_LIMIT",
            "Activation Lease Event limit is exhausted.",
        )
    event = {
        "schema_version": "work_item_activation_lease_event.v1",
        "lease_event_id": new_stable_id("activation_lease_event"),
        "lease_id": str(row["lease_id"]),
        "sequence": sequence,
        "event_type": event_type,
        "status_before": status_before,
        "status_after": status_after,
        "state_version_before": state_version_before,
        "state_version_after": state_version_after,
        "claimed_process_identity": row["claimed_process_identity"],
        "listener_attestation_digest": row["listener_attestation_digest"],
        "authenticated_request_context_binding_digest": row["request_context_binding_digest"],
        "command_name": command_name,
        "source_event_key_digest": source_event_key_digest,
        "domain_fact_delta_digest": domain_fact_delta_digest,
        "principal_binding_digest": principal_binding_digest,
        "reason_code": reason_code,
        "previous_event_digest": None if previous is None else str(previous["event_digest"]),
        "event_digest_algorithm": "sha256(canonical_json(event_without_event_digest))",
        "created_at": created_at,
    }
    event["event_digest"] = canonical_sha256(event)
    validate_governance_record("work_item_activation_lease_event.v1", event)
    connection.execute(
        """
        INSERT INTO activation_lease_events(
          lease_event_id,schema_version,lease_id,sequence,event_type,status_before,status_after,
          state_version_before,state_version_after,claimed_process_identity,listener_attestation_digest,
          request_context_binding_digest,command_name,source_event_key_digest,domain_fact_delta_digest,
          principal_binding_digest,reason_code,previous_event_digest,event_digest,event_json,created_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            event["lease_event_id"], event["schema_version"], event["lease_id"], event["sequence"],
            event["event_type"], event["status_before"], event["status_after"],
            event["state_version_before"], event["state_version_after"],
            event["claimed_process_identity"], event["listener_attestation_digest"],
            event["authenticated_request_context_binding_digest"], event["command_name"],
            event["source_event_key_digest"], event["domain_fact_delta_digest"],
            event["principal_binding_digest"], event["reason_code"], event["previous_event_digest"],
            event["event_digest"], canonical_json(event), event["created_at"],
        ),
    )
    return event


@dataclass
class ActivationWriteSession:
    guard: AuthoritativeCanaryGuard
    connection: sqlite3.Connection
    row: sqlite3.Row
    command_name: str
    normalized_command: dict[str, Any]
    source_event_key_digest: str
    principal_binding_digest: str
    baseline_fact_counts: dict[str, int]
    fixture_slot: dict[str, Any] | None = None
    fact_delta: dict[str, int] | None = None
    domain_fact_delta: dict[str, int] | None = None

    def authorize_new(
        self,
        *,
        work_item_id: str | None,
        fact_delta: dict[str, int],
        domain_fact_delta: dict[str, int] | None = None,
    ) -> None:
        self.guard._authorize_new(
            self,
            work_item_id=work_item_id,
            fact_delta=fact_delta,
            domain_fact_delta=domain_fact_delta,
        )

    def commit_new(
        self,
        *,
        work_item_id: str,
        event_type: str = "command_committed",
        generated_ids: dict[str, list[str]] | None = None,
    ) -> None:
        self.guard._commit_new(
            self,
            work_item_id=work_item_id,
            event_type=event_type,
            generated_ids=generated_ids,
        )

    def authorize_replay(self, *, work_item_id: str) -> None:
        self.guard._authorize_replay(self, work_item_id=work_item_id)


class AuthoritativeCanaryGuard:
    def __init__(
        self,
        ledger: SQLiteWorkItemLedger,
        *,
        now: Callable[[], datetime] = utc_now,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
        process_identity_provider: Callable[[str], dict[str, Any]] = process_identity_inputs,
    ) -> None:
        self.ledger = ledger
        self.now = now
        self.monotonic_ns = monotonic_ns
        self.process_identity_provider = process_identity_provider

    def mint_request_context(
        self,
        *,
        proof: AuthenticatedTokenRequestProof | None,
        principal_context: PrincipalContext | None,
    ) -> AuthoritativeCanaryRequestContext:
        if proof is None or not proof.trusted:
            raise WorkItemGovernanceError(
                "AUTHENTICATED_REQUEST_CONTEXT_REQUIRED",
                "The Authoritative Canary requires a verified Bearer Token request.",
            )
        principal = self._trusted_principal(principal_context)
        with self.ledger.read_connection() as connection:
            row = self._active_row(connection)
            self._validate_time(row)
            self._validate_principal(row, principal)
            runtime = _json(row, "runtime_binding_json")
            self._validate_process_identity(row, runtime)
            expected = request_context_binding_digest(
                lease_id=str(row["lease_id"]),
                authorization_digest=str(row["authorization_digest"]),
                claimed_process_identity=str(row["claimed_process_identity"]),
                runtime_instance_nonce=str(runtime["runtime_instance_nonce"]),
                listener_digest=str(row["listener_attestation_digest"]),
                principal_id=principal.principal_id,
                session_ref=str(principal.session_ref),
            )
            if expected != row["request_context_binding_digest"]:
                raise WorkItemGovernanceError(
                    "REQUEST_CONTEXT_BINDING_MISMATCH",
                    "The active Lease request-context binding is invalid.",
                )
        return _mint_authoritative_request_context(
            proof=proof,
            lease_id=str(row["lease_id"]),
            authorization_digest=str(row["authorization_digest"]),
            claimed_process_identity=str(row["claimed_process_identity"]),
            runtime_instance_nonce=str(runtime["runtime_instance_nonce"]),
            listener_attestation_digest=str(row["listener_attestation_digest"]),
            principal_id=principal.principal_id,
            session_ref=str(principal.session_ref),
            binding_digest=expected,
        )

    def authorized_work_item_id(self) -> str | None:
        """Return the latest Lease binding for bounded read/closeout surfaces."""

        with self.ledger.read_connection() as connection:
            row = connection.execute(
                "SELECT * FROM activation_leases ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            if row is None:
                raise WorkItemGovernanceError(
                    "ACTIVATION_LEASE_REQUIRED",
                    "An Activation Lease is required for Canary reads.",
                )
            value = row["authorized_work_item_id"]
            return None if value is None else str(value)

    def dispatch_authority_active(self) -> bool:
        with self.ledger.read_connection() as connection:
            row = connection.execute(
                "SELECT * FROM activation_leases ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            if row is None or row["status"] != "active":
                return False
            try:
                self._validate_time(row)
                self._validate_process_identity(row, _json(row, "runtime_binding_json"))
            except WorkItemGovernanceError:
                return False
            return True

    def runtime_status(self) -> dict[str, Any]:
        with self.ledger.read_connection() as connection:
            row = connection.execute(
                "SELECT * FROM activation_leases ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return {"present": False, "status": None, "effective_active": False}
        effective_active = row["status"] == "active"
        if effective_active:
            try:
                self._validate_time(row)
                self._validate_process_identity(row, _json(row, "runtime_binding_json"))
            except WorkItemGovernanceError:
                effective_active = False
        return {
            "present": True,
            "lease_id": str(row["lease_id"]),
            "authorization_id": str(row["authorization_id"]),
            "status": str(row["status"]),
            "effective_active": effective_active,
            "state_version": int(row["state_version"]),
            "authorized_work_item_id": row["authorized_work_item_id"],
        }

    def assert_read_scope(self, work_item_id: str) -> None:
        bound = self.authorized_work_item_id()
        if bound is None or bound != work_item_id:
            raise WorkItemGovernanceError(
                "ACTIVATION_WORK_ITEM_SCOPE_VIOLATION",
                "The read does not target the Lease-bound Work Item.",
            )

    def authorize_preview(
        self,
        *,
        command_name: str,
        normalized_command: dict[str, Any],
        principal_context: PrincipalContext | None,
        request_context: AuthoritativeCanaryRequestContext | None,
    ) -> None:
        with self.ledger.read_connection() as connection:
            row = self._active_row(connection)
            principal = self._validate_request(row, principal_context, request_context)
            self._validate_fixture_slot(
                connection,
                row,
                command_name=command_name,
                normalized_command=normalized_command,
                source_event_key_digest=None,
                preview_only=True,
            )
            self._reconcile(connection, row)
            if principal.principal_id != request_context.principal_id:
                raise WorkItemGovernanceError("REQUEST_CONTEXT_PRINCIPAL_MISMATCH", "Preview Principal mismatch.")

    def begin_write(
        self,
        connection: sqlite3.Connection,
        *,
        command_name: str,
        normalized_command: dict[str, Any],
        source_event_key: str,
        principal_context: PrincipalContext | None,
        request_context: AuthoritativeCanaryRequestContext | None,
    ) -> ActivationWriteSession:
        row = self._active_row(connection)
        try:
            principal = self._validate_request(row, principal_context, request_context)
        except WorkItemGovernanceError as exc:
            if exc.code == "ACTIVATION_LEASE_EXPIRED":
                self._expire_and_raise(connection, row, command_name=command_name)
                raise AssertionError("unreachable")
            if exc.code == "ACTIVATION_MONOTONIC_DEADLINE_INVALID":
                self._freeze_and_raise(
                    connection,
                    row,
                    code=exc.code,
                    message=str(exc),
                    reason_code="monotonic_deadline_integrity",
                    command_name=command_name,
                )
                raise AssertionError("unreachable")
            if exc.code in HARD_REQUEST_BINDING_ERRORS:
                self._freeze_and_raise(
                    connection,
                    row,
                    code=exc.code,
                    message=str(exc),
                    reason_code="request_binding_integrity",
                    command_name=command_name,
                )
                raise AssertionError("unreachable")
            raise
        try:
            self._reconcile(connection, row)
        except WorkItemGovernanceError as exc:
            self._freeze_and_raise(
                connection,
                row,
                code=exc.code,
                message=str(exc),
                reason_code="fact_reconciliation",
                command_name=command_name,
            )
            raise AssertionError("unreachable")
        try:
            self._prevalidate_write_request(
                connection,
                row,
                command_name=command_name,
                normalized_command=normalized_command,
                source_event_key=source_event_key,
            )
        except WorkItemGovernanceError as exc:
            self._freeze_and_raise(
                connection,
                row,
                code=exc.code,
                message=str(exc),
                reason_code="fixture_prevalidation",
                command_name=command_name,
            )
            raise AssertionError("unreachable")
        connection.execute("SAVEPOINT activation_domain_write")
        return ActivationWriteSession(
            guard=self,
            connection=connection,
            row=row,
            command_name=command_name,
            normalized_command=normalized_command,
            source_event_key_digest=canonical_sha256(
                {"command_name": command_name, "source_event_key": source_event_key}
            ),
            principal_binding_digest=canonical_sha256(principal.to_record()),
            baseline_fact_counts=_activation_domain_fact_counts(connection),
        )

    def deny_command(
        self,
        connection: sqlite3.Connection,
        *,
        command_name: str,
        principal_context: PrincipalContext | None,
        request_context: AuthoritativeCanaryRequestContext | None,
    ) -> None:
        row = self._active_row(connection)
        try:
            self._validate_request(row, principal_context, request_context)
        except WorkItemGovernanceError as exc:
            if exc.code == "ACTIVATION_LEASE_EXPIRED":
                self._expire_and_raise(connection, row, command_name=command_name)
                raise AssertionError("unreachable")
            if exc.code == "ACTIVATION_MONOTONIC_DEADLINE_INVALID" or exc.code in HARD_REQUEST_BINDING_ERRORS:
                self._freeze_and_raise(
                    connection,
                    row,
                    code=exc.code,
                    message=str(exc),
                    reason_code="request_binding_integrity",
                    command_name=command_name,
                )
                raise AssertionError("unreachable")
            raise
        self._freeze_and_raise(
            connection,
            row,
            code="ACTIVATION_COMMAND_DENIED",
            message="This Work Item command is denied by the Authoritative Canary matrix.",
            reason_code="denied_command",
            command_name=command_name,
        )

    def _authorize_new(
        self,
        session: ActivationWriteSession,
        *,
        work_item_id: str | None,
        fact_delta: dict[str, int],
        domain_fact_delta: dict[str, int] | None,
    ) -> None:
        row = session.row
        connection = session.connection
        try:
            slot = self._validate_fixture_slot(
                connection,
                row,
                command_name=session.command_name,
                normalized_command=session.normalized_command,
                source_event_key_digest=session.source_event_key_digest,
                preview_only=False,
            )
        except WorkItemGovernanceError as exc:
            self._freeze_and_raise(
                connection,
                row,
                code=exc.code,
                message=str(exc),
                reason_code="fixture_mismatch",
                command_name=session.command_name,
            )
            raise AssertionError("unreachable")
        bound = row["authorized_work_item_id"]
        if session.command_name == "apply_work_item_create":
            if bound is not None:
                self._freeze_and_raise(
                    connection,
                    row,
                    code="ACTIVATION_WORK_ITEM_ALREADY_BOUND",
                    message="The Activation Lease already owns its single Work Item.",
                    reason_code="second_work_item_create",
                    command_name=session.command_name,
                )
        elif bound is None or work_item_id != bound:
            self._freeze_and_raise(
                connection,
                row,
                code="ACTIVATION_WORK_ITEM_SCOPE_VIOLATION",
                message="The command does not target the Lease-bound Work Item.",
                reason_code="work_item_scope",
                command_name=session.command_name,
            )
        usage = _json(row, "usage_json")
        quotas = _json(row, "quotas_json")
        if int(usage["lease_events"]) >= int(quotas["maximum_lease_events"]) - 2:
            self._freeze_and_raise(
                connection,
                row,
                code="ACTIVATION_LEASE_EVENT_LIMIT",
                message="Activation Lease reserves its final Event capacity for freeze and closeout.",
                reason_code="quota:lease_events",
                command_name=session.command_name,
            )
        normalized_delta: dict[str, int] = {}
        for key, value in fact_delta.items():
            if key not in FACT_TO_QUOTA or isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise WorkItemGovernanceError("ACTIVATION_FACT_DELTA_INVALID", "Activation fact delta is invalid.")
            normalized_delta[key] = value
            if int(usage[key]) + value > int(quotas[FACT_TO_QUOTA[key]]):
                self._freeze_and_raise(
                    connection,
                    row,
                    code="ACTIVATION_QUOTA_EXCEEDED",
                    message="The Authoritative Canary fact quota would be exceeded.",
                    reason_code=f"quota:{key}",
                    command_name=session.command_name,
                )
        expected_domain_delta = slot.get("expected_fact_delta")
        supplied_domain_delta = domain_fact_delta
        if supplied_domain_delta is None:
            supplied_domain_delta = {
                "work_items": int(fact_delta.get("new_work_items", 0)),
                "task_versions": int(fact_delta.get("task_versions", 0)),
                "runtime_attempts": int(fact_delta.get("runtime_attempts", 0)),
                "attempt_events": 0,
                "artifacts": int(fact_delta.get("artifacts", 0)),
                "decisions": int(fact_delta.get("decisions", 0)),
                "applied_gate_events": int(fact_delta.get("applied_gate_events", 0)),
                "rejected_gate_events": int(fact_delta.get("rejected_gate_events", 0)),
                "audit_events": 0,
                "outbox_events": 0,
                "acceptance_manifests": 0,
            }
        if (
            set(supplied_domain_delta) != set(DOMAIN_FACT_KEYS)
            or any(
                isinstance(value, bool) or not isinstance(value, int) or value < 0
                for value in supplied_domain_delta.values()
            )
            or supplied_domain_delta != expected_domain_delta
        ):
            self._freeze_and_raise(
                connection,
                row,
                code="ACTIVATION_DOMAIN_FACT_DELTA_MISMATCH",
                message="The command domain fact delta differs from the reviewed Fixture slot.",
                reason_code="domain_fact_delta",
                command_name=session.command_name,
            )
        session.fixture_slot = slot
        session.fact_delta = normalized_delta
        session.domain_fact_delta = dict(supplied_domain_delta)

    def _authorize_replay(
        self,
        session: ActivationWriteSession,
        *,
        work_item_id: str,
    ) -> None:
        row = session.row
        bound = row["authorized_work_item_id"]
        if bound is None or str(bound) != work_item_id:
            self._freeze_and_raise(
                session.connection,
                row,
                code="ACTIVATION_WORK_ITEM_SCOPE_VIOLATION",
                message="Idempotent replay does not target the Lease-bound Work Item.",
                reason_code="replay_work_item_scope",
                command_name=session.command_name,
            )
        fixture = _json(row, "fixture_json")
        normalized_digest = canonical_sha256(
            self._fixture_normalized_command(row, session.normalized_command)
        )
        slots = fixture.get("command_slots", [])
        consumed = int(
            session.connection.execute(
                """
                SELECT COUNT(*) FROM activation_lease_events
                WHERE lease_id=? AND event_type IN ('command_committed','domain_rejected')
                """,
                (row["lease_id"],),
            ).fetchone()[0]
        )
        progression_slots = [
            slot for slot in slots if slot.get("expected_outcome") != "exact_idempotent_replay"
        ]
        replay_slots = [
            slot for slot in slots if slot.get("expected_outcome") == "exact_idempotent_replay"
        ]
        matched = any(
            isinstance(slot, dict)
            and slot.get("command_name") == session.command_name
            and slot.get("normalized_command_digest") == normalized_digest
            and slot.get("idempotency_binding_digest") == session.source_event_key_digest
            and slot.get("exact_replay_allowed") is True
            for slot in [*progression_slots[:consumed], *replay_slots]
        )
        if not matched:
            self._freeze_and_raise(
                session.connection,
                row,
                code="ACTIVATION_REPLAY_NOT_AUTHORIZED",
                message="The request is not an exact replay of a consumed Fixture slot.",
                reason_code="replay_fixture_mismatch",
                command_name=session.command_name,
            )
        session.connection.execute("RELEASE SAVEPOINT activation_domain_write")

    def _commit_new(
        self,
        session: ActivationWriteSession,
        *,
        work_item_id: str,
        event_type: str,
        generated_ids: dict[str, list[str]] | None,
    ) -> None:
        try:
            self._commit_new_domain(
                session,
                work_item_id=work_item_id,
                event_type=event_type,
                generated_ids=generated_ids,
            )
        except CommitWorkItemRejection:
            raise
        except WorkItemGovernanceError as exc:
            session.connection.execute("ROLLBACK TO SAVEPOINT activation_domain_write")
            session.connection.execute("RELEASE SAVEPOINT activation_domain_write")
            row = self._active_row(session.connection)
            self._freeze_and_raise(
                session.connection,
                row,
                code=exc.code,
                message=str(exc),
                reason_code="internal_guard_error",
                command_name=session.command_name,
            )
            raise AssertionError("unreachable")
        session.connection.execute("RELEASE SAVEPOINT activation_domain_write")

    def _commit_new_domain(
        self,
        session: ActivationWriteSession,
        *,
        work_item_id: str,
        event_type: str,
        generated_ids: dict[str, list[str]] | None,
    ) -> None:
        if (
            session.fixture_slot is None
            or session.fact_delta is None
            or session.domain_fact_delta is None
        ):
            raise WorkItemGovernanceError(
                "ACTIVATION_WRITE_NOT_AUTHORIZED",
                "Activation write must be authorized before domain mutation.",
            )
        expected_outcome = session.fixture_slot.get("expected_outcome")
        if (
            (event_type == "domain_rejected" and expected_outcome != "transition_rejected")
            or (event_type == "command_committed" and expected_outcome != "new_fact")
        ):
            raise WorkItemGovernanceError(
                "ACTIVATION_COMMAND_OUTCOME_MISMATCH",
                "Domain command outcome differs from the reviewed Fixture slot.",
            )
        connection = session.connection
        row = connection.execute(
            "SELECT * FROM activation_leases WHERE lease_id=?",
            (session.row["lease_id"],),
        ).fetchone()
        if row is None or row["status"] != "active" or int(row["state_version"]) != int(session.row["state_version"]):
            raise WorkItemGovernanceError("ACTIVATION_LEASE_CAS_CONFLICT", "Activation Lease changed concurrently.")
        actual_counts = _activation_domain_fact_counts(connection)
        actual_delta = {
            key: int(actual_counts[key]) - int(session.baseline_fact_counts[key])
            for key in DOMAIN_FACT_KEYS
        }
        if actual_delta != session.domain_fact_delta:
            raise WorkItemGovernanceError(
                "ACTIVATION_DOMAIN_FACT_RECONCILIATION_FAILED",
                "Committed domain facts differ from the reviewed Fixture delta.",
                details={"expected": session.domain_fact_delta, "actual": actual_delta},
            )
        usage = _json(row, "usage_json")
        for key, value in session.fact_delta.items():
            usage[key] = int(usage[key]) + value
        usage["lease_events"] = int(usage["lease_events"]) + 1
        if usage["gate_events_total"] != usage["applied_gate_events"] + usage["rejected_gate_events"]:
            raise WorkItemGovernanceError("ACTIVATION_GATE_USAGE_INVALID", "Gate Event usage is inconsistent.")
        bound = row["authorized_work_item_id"]
        if session.command_name == "apply_work_item_create":
            bound = work_item_id
        fixture_bindings = _json(row, "fixture_bindings_json")
        supplied_bindings = generated_ids or {}
        expected_bindings = list(session.fixture_slot.get("generated_binding_slots", []))
        expected_by_field = {
            "attempt_ids": [item for item in expected_bindings if str(item).startswith("$attempt_")],
            "artifact_ids": [item for item in expected_bindings if str(item).startswith("$artifact_")],
            "decision_ids": [item for item in expected_bindings if str(item).startswith("$decision_")],
            "gate_event_ids": [item for item in expected_bindings if str(item).startswith("$gate_")],
        }
        expected_work_item = [item for item in expected_bindings if item == "$work_item"]
        if (session.command_name == "apply_work_item_create") != (expected_work_item == ["$work_item"]):
            raise WorkItemGovernanceError(
                "ACTIVATION_GENERATED_BINDING_MISMATCH",
                "Fixture Work Item placeholder does not match the create command.",
            )
        if set(supplied_bindings) - set(expected_by_field):
            raise WorkItemGovernanceError(
                "ACTIVATION_GENERATED_BINDING_MISMATCH",
                "Generated binding category is not recognized.",
            )
        prefixes = {
            "attempt_ids": "attempt_",
            "artifact_ids": "artifact_",
            "decision_ids": "decision_",
            "gate_event_ids": "gate_",
        }
        for field, placeholders in expected_by_field.items():
            values = supplied_bindings.get(field, [])
            if len(values) != len(placeholders) or any(
                not isinstance(value, str) or not value.startswith(prefixes[field])
                for value in values
            ):
                raise WorkItemGovernanceError(
                    "ACTIVATION_GENERATED_BINDING_MISMATCH",
                    "Generated IDs do not match the reviewed Fixture placeholders.",
                    details={"binding_field": field},
                )
            existing_values = list(fixture_bindings[field])
            for value in values:
                if value in existing_values:
                    raise WorkItemGovernanceError(
                        "ACTIVATION_GENERATED_BINDING_DUPLICATE",
                        "Generated Fixture ID was already bound.",
                    )
                existing_values.append(value)
            fixture_bindings[field] = existing_values
        next_version = int(row["state_version"]) + 1
        updated_at = isoformat_utc(self.now())
        cursor = connection.execute(
            """
            UPDATE activation_leases
            SET authorized_work_item_id=?,fixture_bindings_json=?,usage_json=?,state_version=?,updated_at=?
            WHERE lease_id=? AND state_version=? AND status='active'
            """,
            (
                bound, canonical_json(fixture_bindings), canonical_json(usage), next_version, updated_at,
                row["lease_id"], row["state_version"],
            ),
        )
        if cursor.rowcount != 1:
            raise WorkItemGovernanceError("ACTIVATION_LEASE_CAS_CONFLICT", "Activation Lease CAS failed.")
        event_row = connection.execute(
            "SELECT * FROM activation_leases WHERE lease_id=?",
            (row["lease_id"],),
        ).fetchone()
        _append_lease_event(
            connection,
            row=event_row,
            event_type=event_type,
            status_before="active",
            status_after="active",
            state_version_before=int(row["state_version"]),
            state_version_after=next_version,
            created_at=updated_at,
            command_name=session.command_name,
            source_event_key_digest=session.source_event_key_digest,
            domain_fact_delta_digest=canonical_sha256(session.domain_fact_delta),
            principal_binding_digest=session.principal_binding_digest,
            reason_code=None if event_type == "command_committed" else "domain_rejected",
        )
        self._reconcile(connection, event_row, expected_usage=usage)

    def _validate_fixture_slot(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        *,
        command_name: str,
        normalized_command: dict[str, Any],
        source_event_key_digest: str | None,
        preview_only: bool,
    ) -> dict[str, Any]:
        fixture = _json(row, "fixture_json")
        consumed = int(
            connection.execute(
                """
                SELECT COUNT(*) FROM activation_lease_events
                WHERE lease_id=? AND event_type IN ('command_committed','domain_rejected')
                """,
                (row["lease_id"],),
            ).fetchone()[0]
        )
        slots = fixture.get("command_slots")
        progression_slots = (
            [slot for slot in slots if slot.get("expected_outcome") != "exact_idempotent_replay"]
            if isinstance(slots, list)
            else []
        )
        if not progression_slots or consumed >= len(progression_slots):
            self._fixture_error("The reviewed Fixture has no remaining command slot.")
        slot = progression_slots[consumed]
        if not isinstance(slot, dict):
            self._fixture_error("Fixture command slot is invalid.")
        expected_name = str(slot.get("command_name"))
        if expected_name != command_name:
            self._fixture_error("Command does not match the next reviewed Fixture slot.")
        fixture_command = self._fixture_normalized_command(row, normalized_command)
        if slot.get("normalized_command_digest") != canonical_sha256(fixture_command):
            self._fixture_error("Normalized command digest does not match the Fixture.")
        if not preview_only and slot.get("idempotency_binding_digest") != source_event_key_digest:
            self._fixture_error("Command idempotency binding does not match the Fixture.")
        return slot

    def _prevalidate_write_request(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        *,
        command_name: str,
        normalized_command: dict[str, Any],
        source_event_key: str,
    ) -> None:
        fixture = _json(row, "fixture_json")
        slots = fixture.get("command_slots")
        if not isinstance(slots, list):
            self._fixture_error("Fixture command slots are invalid.")
        progression = [
            slot for slot in slots if slot.get("expected_outcome") != "exact_idempotent_replay"
        ]
        explicit_replays = [
            slot for slot in slots if slot.get("expected_outcome") == "exact_idempotent_replay"
        ]
        consumed = int(
            connection.execute(
                """
                SELECT COUNT(*) FROM activation_lease_events
                WHERE lease_id=? AND event_type IN ('command_committed','domain_rejected')
                """,
                (row["lease_id"],),
            ).fetchone()[0]
        )
        candidates = [*progression[:consumed], *explicit_replays]
        if consumed < len(progression):
            candidates.append(progression[consumed])
        command_digest = canonical_sha256(
            self._fixture_normalized_command(row, normalized_command)
        )
        source_digest = canonical_sha256(
            {"command_name": command_name, "source_event_key": source_event_key}
        )
        if not any(
            slot.get("command_name") == command_name
            and slot.get("normalized_command_digest") == command_digest
            and slot.get("idempotency_binding_digest") == source_digest
            for slot in candidates
        ):
            self._fixture_error("Write request is neither the next Fixture slot nor an exact reviewed replay.")

    @staticmethod
    def _fixture_normalized_command(
        row: sqlite3.Row,
        normalized_command: dict[str, Any],
    ) -> dict[str, Any]:
        replacements: dict[str, str] = {}
        if row["authorized_work_item_id"] is not None:
            replacements[str(row["authorized_work_item_id"])] = "$work_item"
        bindings = _json(row, "fixture_bindings_json")
        prefixes = {
            "attempt_ids": "attempt",
            "artifact_ids": "artifact",
            "decision_ids": "decision",
            "gate_event_ids": "gate",
        }
        for field, prefix in prefixes.items():
            for index, value in enumerate(bindings[field], 1):
                replacements[str(value)] = f"${prefix}_{index}"

        def replace(value: Any) -> Any:
            if isinstance(value, str):
                return replacements.get(value, value)
            if isinstance(value, list):
                return [replace(item) for item in value]
            if isinstance(value, dict):
                return {key: replace(item) for key, item in value.items()}
            return value

        result = replace(normalized_command)
        if not isinstance(result, dict):
            raise WorkItemGovernanceError(
                "ACTIVATION_NORMALIZED_COMMAND_INVALID",
                "Fixture-normalized command must remain an object.",
            )
        return result

    @staticmethod
    def _fixture_error(message: str) -> None:
        raise WorkItemGovernanceError("ACTIVATION_FIXTURE_MISMATCH", message)

    def _active_row(self, connection: sqlite3.Connection) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM activation_leases WHERE status='active' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        if row is None:
            raise WorkItemGovernanceError(
                "ACTIVE_ACTIVATION_LEASE_REQUIRED",
                "An exact Listener-attested active Activation Lease is required.",
            )
        return row

    @staticmethod
    def _trusted_principal(principal: PrincipalContext | None) -> PrincipalContext:
        if not isinstance(principal, PrincipalContext) or not principal.trusted or not principal.session_ref:
            raise WorkItemGovernanceError(
                "TRUSTED_PRINCIPAL_REQUIRED",
                "The Authoritative Canary requires a trusted session-bound Principal.",
            )
        return principal

    def _validate_principal(self, row: sqlite3.Row, principal: PrincipalContext) -> None:
        binding = _json(row, "principal_binding_json")
        if (
            principal.principal_id != binding.get("principal_id")
            or principal.principal_kind != binding.get("principal_kind")
            or principal.session_ref != binding.get("session_ref")
            or sorted(principal.granted_permissions) != list(binding.get("permissions", []))
        ):
            raise WorkItemGovernanceError(
                "ACTIVATION_PRINCIPAL_MISMATCH",
                "Principal, session, or permissions do not match the Activation Lease.",
            )

    def _validate_request(
        self,
        row: sqlite3.Row,
        principal_context: PrincipalContext | None,
        request_context: AuthoritativeCanaryRequestContext | None,
    ) -> PrincipalContext:
        self._validate_time(row)
        principal = self._trusted_principal(principal_context)
        self._validate_principal(row, principal)
        if not isinstance(request_context, AuthoritativeCanaryRequestContext) or not request_context.trusted:
            raise WorkItemGovernanceError(
                "AUTHENTICATED_REQUEST_CONTEXT_REQUIRED",
                "A sealed Token-authenticated request context is required.",
            )
        runtime = _json(row, "runtime_binding_json")
        self._validate_process_identity(row, runtime)
        expected = request_context_binding_digest(
            lease_id=str(row["lease_id"]),
            authorization_digest=str(row["authorization_digest"]),
            claimed_process_identity=str(row["claimed_process_identity"]),
            runtime_instance_nonce=str(runtime["runtime_instance_nonce"]),
            listener_digest=str(row["listener_attestation_digest"]),
            principal_id=principal.principal_id,
            session_ref=str(principal.session_ref),
        )
        if (
            request_context.lease_id != row["lease_id"]
            or request_context.authorization_digest != row["authorization_digest"]
            or request_context.binding_digest != expected
            or row["request_context_binding_digest"] != expected
        ):
            raise WorkItemGovernanceError(
                "REQUEST_CONTEXT_BINDING_MISMATCH",
                "Request context is stale or belongs to another Lease or authorization.",
            )
        return principal

    def _validate_process_identity(self, row: sqlite3.Row, runtime: dict[str, Any]) -> None:
        current = self.process_identity_provider(str(runtime["runtime_instance_nonce"]))
        if current["expected_process_identity"] != row["claimed_process_identity"]:
            raise WorkItemGovernanceError(
                "ACTIVATION_PROCESS_RESTARTED",
                "Current process does not own the claimed Activation Lease.",
            )

    def _validate_time(self, row: sqlite3.Row) -> None:
        start, end = _strict_window(
            str(row["not_before"]),
            str(row["expires_at"]),
            int(row["maximum_runtime_seconds"]),
        )
        now = self.now().astimezone(timezone.utc)
        if now < start:
            raise WorkItemGovernanceError("ACTIVATION_NOT_YET_VALID", "Activation Lease is not yet valid.")
        claim = row["monotonic_claim_ns"]
        deadline = row["monotonic_deadline_ns"]
        maximum_ns = int(row["maximum_runtime_seconds"]) * 1_000_000_000
        if (
            claim is None
            or deadline is None
            or int(claim) < 1
            or int(deadline) <= int(claim)
            or int(deadline) - int(claim) > maximum_ns
        ):
            raise WorkItemGovernanceError(
                "ACTIVATION_MONOTONIC_DEADLINE_INVALID",
                "Activation Lease monotonic timing is missing, inverted, or extended.",
            )
        if now >= end or self.monotonic_ns() >= int(deadline):
            raise WorkItemGovernanceError("ACTIVATION_LEASE_EXPIRED", "Activation Lease has expired.")

    def _reconcile(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        *,
        expected_usage: dict[str, Any] | None = None,
    ) -> None:
        usage = expected_usage or _json(row, "usage_json")
        bound = row["authorized_work_item_id"]
        if bound is None:
            actual = {
                "new_work_items": int(connection.execute("SELECT COUNT(*) FROM work_items").fetchone()[0]),
                "task_versions": int(connection.execute("SELECT COUNT(*) FROM task_versions").fetchone()[0]),
                "runtime_attempts": int(
                    connection.execute(
                        "SELECT COUNT(*) FROM execution_attempts WHERE attempt_kind='runtime'"
                    ).fetchone()[0]
                ),
                "artifacts": int(connection.execute("SELECT COUNT(*) FROM artifact_refs").fetchone()[0]),
                "decisions": int(connection.execute("SELECT COUNT(*) FROM decision_records").fetchone()[0]),
                "applied_gate_events": int(
                    connection.execute(
                        "SELECT COUNT(*) FROM gate_events WHERE outcome='transition_applied'"
                    ).fetchone()[0]
                ),
                "rejected_gate_events": int(
                    connection.execute(
                        "SELECT COUNT(*) FROM gate_events WHERE outcome='transition_rejected'"
                    ).fetchone()[0]
                ),
            }
        else:
            params = (bound,)
            actual = {
                "new_work_items": int(
                    connection.execute(
                        "SELECT COUNT(*) FROM work_items WHERE work_item_id=?", params
                    ).fetchone()[0]
                ),
                "task_versions": int(
                    connection.execute(
                        "SELECT COUNT(*) FROM task_versions WHERE work_item_id=?", params
                    ).fetchone()[0]
                ),
                "runtime_attempts": int(
                    connection.execute(
                        """
                        SELECT COUNT(*) FROM execution_attempts
                        WHERE work_item_id=? AND attempt_kind='runtime'
                        """,
                        params,
                    ).fetchone()[0]
                ),
                "artifacts": int(
                    connection.execute(
                        "SELECT COUNT(*) FROM artifact_refs WHERE work_item_id=?", params
                    ).fetchone()[0]
                ),
                "decisions": int(
                    connection.execute(
                        "SELECT COUNT(*) FROM decision_records WHERE work_item_id=?", params
                    ).fetchone()[0]
                ),
                "applied_gate_events": int(
                    connection.execute(
                        """
                        SELECT COUNT(*) FROM gate_events
                        WHERE work_item_id=? AND outcome='transition_applied'
                        """,
                        params,
                    ).fetchone()[0]
                ),
                "rejected_gate_events": int(
                    connection.execute(
                        """
                        SELECT COUNT(*) FROM gate_events
                        WHERE work_item_id=? AND outcome='transition_rejected'
                        """,
                        params,
                    ).fetchone()[0]
                ),
            }
        actual["gate_events_total"] = actual["applied_gate_events"] + actual["rejected_gate_events"]
        for key, value in actual.items():
            if int(usage[key]) != value:
                raise WorkItemGovernanceError(
                    "ACTIVATION_FACT_RECONCILIATION_FAILED",
                    "Domain fact counts do not match Activation Lease usage.",
                    details={"fact": key, "expected": int(usage[key]), "actual": value},
                )
        if bound is not None:
            for table, (query, usage_key) in SCOPED_FACT_TOTAL_QUERIES.items():
                total = int(connection.execute(query).fetchone()[0])
                if total != int(usage[usage_key]):
                    raise WorkItemGovernanceError(
                        "ACTIVATION_OUT_OF_SCOPE_FACT_PRESENT",
                        "A fact exists outside the single Lease-bound Work Item.",
                        details={"table": table},
                    )
        completed_attempts = int(
            connection.execute(
                """
                SELECT COUNT(*) FROM execution_attempts
                WHERE attempt_kind='runtime' AND completion_event_key IS NOT NULL
                """
            ).fetchone()[0]
        )
        expected_attempt_events = int(usage["runtime_attempts"]) + completed_attempts
        actual_attempt_events = int(connection.execute("SELECT COUNT(*) FROM attempt_events").fetchone()[0])
        if actual_attempt_events != expected_attempt_events:
            raise WorkItemGovernanceError(
                "ACTIVATION_ATTEMPT_EVENT_RECONCILIATION_FAILED",
                "Attempt Event facts do not match runtime Attempt state.",
            )
        for table, query in DERIVED_FACT_COUNT_QUERIES.items():
            if int(connection.execute(query).fetchone()[0]) != int(
                usage["gate_events_total"]
            ):
                raise WorkItemGovernanceError(
                    "ACTIVATION_DERIVED_FACT_RECONCILIATION_FAILED",
                    "Gate-derived facts do not match Gate Event usage.",
                    details={"table": table},
                )
        lease_events = int(
            connection.execute(
                "SELECT COUNT(*) FROM activation_lease_events WHERE lease_id=?",
                (row["lease_id"],),
            ).fetchone()[0]
        )
        if int(usage["lease_events"]) != lease_events:
            raise WorkItemGovernanceError(
                "ACTIVATION_EVENT_RECONCILIATION_FAILED",
                "Activation Lease Event count does not match usage.",
            )
        for table, query in DENIED_FACT_COUNT_QUERIES.items():
            if int(connection.execute(query).fetchone()[0]) != 0:
                raise WorkItemGovernanceError(
                    "ACTIVATION_DENIED_FACT_PRESENT",
                    "A denied fact exists in the Authoritative Canary Ledger.",
                    details={"table": table},
                )

    def _freeze_and_raise(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        *,
        code: str,
        message: str,
        reason_code: str,
        command_name: str | None,
    ) -> None:
        if row["status"] == "active":
            next_version = int(row["state_version"]) + 1
            usage = _json(row, "usage_json")
            if int(usage["lease_events"]) < DEFAULT_QUOTAS["maximum_lease_events"]:
                usage["lease_events"] = int(usage["lease_events"]) + 1
                now = isoformat_utc(self.now())
                connection.execute(
                    """
                    UPDATE activation_leases
                    SET status='write_frozen',state_version=?,usage_json=?,updated_at=?
                    WHERE lease_id=? AND state_version=? AND status='active'
                    """,
                    (next_version, canonical_json(usage), now, row["lease_id"], row["state_version"]),
                )
                frozen = connection.execute(
                    "SELECT * FROM activation_leases WHERE lease_id=?",
                    (row["lease_id"],),
                ).fetchone()
                _append_lease_event(
                    connection,
                    row=frozen,
                    event_type="lease_write_frozen",
                    status_before="active",
                    status_after="write_frozen",
                    state_version_before=int(row["state_version"]),
                    state_version_after=next_version,
                    created_at=now,
                    command_name=(command_name if command_name in ALLOWED_WRITE_COMMANDS else None),
                    reason_code=(
                        f"{reason_code}:{command_name}"
                        if command_name is not None and command_name not in ALLOWED_WRITE_COMMANDS
                        else reason_code
                    ),
                )
        raise CommitWorkItemRejection(
            WorkItemGovernanceError(code, message, details={"reason_code": reason_code})
        )

    def _expire_and_raise(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        *,
        command_name: str | None,
    ) -> None:
        next_version = int(row["state_version"]) + 1
        usage = _json(row, "usage_json")
        usage["lease_events"] = int(usage["lease_events"]) + 1
        now = isoformat_utc(self.now())
        connection.execute(
            """
            UPDATE activation_leases
            SET status='expired',state_version=?,usage_json=?,updated_at=?
            WHERE lease_id=? AND state_version=? AND status='active'
            """,
            (next_version, canonical_json(usage), now, row["lease_id"], row["state_version"]),
        )
        expired = connection.execute(
            "SELECT * FROM activation_leases WHERE lease_id=?",
            (row["lease_id"],),
        ).fetchone()
        _append_lease_event(
            connection,
            row=expired,
            event_type="lease_expired",
            status_before="active",
            status_after="expired",
            state_version_before=int(row["state_version"]),
            state_version_after=next_version,
            created_at=now,
            command_name=None,
            reason_code="hard_expiration",
        )
        raise CommitWorkItemRejection(
            WorkItemGovernanceError(
                "ACTIVATION_LEASE_EXPIRED",
                "Activation Lease has expired and authoritative writes are frozen.",
            )
        )


class ActivationLeaseControlPlane:
    """Local-only issuance and lifecycle operations; never exposed as MCP tools."""

    def __init__(
        self,
        ledger: SQLiteWorkItemLedger,
        *,
        canary_root: str | os.PathLike[str],
        now: Callable[[], datetime] = utc_now,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
        process_identity_provider: Callable[[str], dict[str, Any]] = process_identity_inputs,
    ) -> None:
        self.ledger = ledger
        self.canary_root = Path(canary_root).expanduser().resolve()
        self.now = now
        self.monotonic_ns = monotonic_ns
        self.process_identity_provider = process_identity_provider

    def issue_prepared_lease(
        self,
        *,
        activation_envelope: dict[str, Any],
        synthetic_fixture: dict[str, Any],
        preflight_receipt: dict[str, Any],
        envelope_path: str | os.PathLike[str],
    ) -> dict[str, Any]:
        validate_governance_record("work_item_activation_envelope.v1", activation_envelope)
        validate_synthetic_fixture_semantics(synthetic_fixture)
        validate_governance_record("work_item_authoritative_canary_preflight_receipt.v1", preflight_receipt)
        validate_runtime_policy_contracts()
        if activation_envelope["spec_manifest_digest"] != R2_SPEC_FREEZE_MANIFEST_SHA256:
            raise WorkItemGovernanceError("SPEC_MANIFEST_MISMATCH", "Activation Envelope binds another specification.")
        if canonical_sha256(synthetic_fixture) != activation_envelope["synthetic_fixture_contract_digest"]:
            raise WorkItemGovernanceError("FIXTURE_DIGEST_MISMATCH", "Synthetic Fixture digest mismatch.")
        if canonical_sha256(preflight_receipt) != activation_envelope["preflight_receipt_digest"]:
            raise WorkItemGovernanceError("PREFLIGHT_DIGEST_MISMATCH", "Preflight Receipt digest mismatch.")
        if activation_envelope["authorization_digest"] != preflight_receipt["authorization_digest"]:
            raise WorkItemGovernanceError("AUTHORIZATION_DIGEST_MISMATCH", "Authorization digest mismatch.")
        if activation_envelope["activation_lease_id"] != preflight_receipt["activation_lease_id"]:
            raise WorkItemGovernanceError("ACTIVATION_LEASE_ID_MISMATCH", "Activation Lease ID mismatch.")
        self._validate_preflight_contract_bindings(
            activation_envelope=activation_envelope,
            preflight_receipt=preflight_receipt,
        )
        issued = parse_timestamp(activation_envelope["window"]["issued_at"], "issued_at")
        not_before, _expires = _strict_window(
            activation_envelope["window"]["not_before"],
            activation_envelope["window"]["expires_at"],
            activation_envelope["window"]["maximum_runtime_seconds"],
        )
        if issued > not_before:
            raise WorkItemGovernanceError("ACTIVATION_WINDOW_INVALID", "issued_at must not follow not_before.")
        self._validate_preflight_paths(preflight_receipt)
        self._validate_fixture_paths(synthetic_fixture, preflight_receipt)
        self._validate_preflight_freshness(preflight_receipt)
        envelope_file = Path(envelope_path).expanduser().resolve()
        if canonical_path_digest(envelope_file) != activation_envelope["runtime_binding"]["activation_envelope_path_digest"]:
            raise WorkItemGovernanceError("ACTIVATION_ENVELOPE_PATH_MISMATCH", "Activation Envelope path mismatch.")
        self._atomic_write_envelope(envelope_file, activation_envelope)
        try:
            with self.ledger.write_transaction() as connection:
                self._assert_fresh_baseline(connection, preflight_receipt)
                lease = self._lease_from_contracts(
                    activation_envelope=activation_envelope,
                    synthetic_fixture=synthetic_fixture,
                    preflight_receipt=preflight_receipt,
                )
                validate_governance_record("work_item_activation_lease.v1", lease)
                self._insert_lease(connection, lease, synthetic_fixture)
                row = connection.execute(
                    "SELECT * FROM activation_leases WHERE lease_id=?",
                    (lease["lease_id"],),
                ).fetchone()
                _append_lease_event(
                    connection,
                    row=row,
                    event_type="lease_issued",
                    status_before=None,
                    status_after="prepared",
                    state_version_before=0,
                    state_version_after=0,
                    created_at=lease["created_at"],
                )
        except Exception:
            if envelope_file.exists():
                envelope_file.unlink()
            raise
        return {"lease": lease, "envelope_path": str(envelope_file), "prepared": True}

    def claim_prepared_lease(
        self,
        *,
        lease_id: str,
        envelope_path: str | os.PathLike[str],
        claimed_envelope_path: str | os.PathLike[str],
    ) -> dict[str, Any]:
        source = Path(envelope_path).expanduser().resolve()
        claimed = Path(claimed_envelope_path).expanduser().resolve()
        if not source.is_file() or claimed.exists():
            raise WorkItemGovernanceError("ACTIVATION_ENVELOPE_NOT_CLAIMABLE", "Activation Envelope is not claimable.")
        with self.ledger.read_connection() as connection:
            prepared = connection.execute(
                "SELECT * FROM activation_leases WHERE lease_id=?",
                (lease_id,),
            ).fetchone()
        if prepared is None or prepared["status"] != "prepared":
            raise WorkItemGovernanceError("PREPARED_ACTIVATION_LEASE_REQUIRED", "Prepared Lease is missing.")
        prepared_runtime = _json(prepared, "runtime_binding_json")
        if canonical_path_digest(claimed) != prepared_runtime["claimed_activation_envelope_path_digest"]:
            raise WorkItemGovernanceError("CLAIMED_ENVELOPE_PATH_MISMATCH", "Claimed Envelope path mismatch.")
        # Consume first. A malformed or stale single-use Envelope remains sealed
        # at the claimed path and the prepared Lease is revoked; it is never put
        # back into the reusable waiting location.
        self._claim_file_no_replace(source, claimed)
        try:
            envelope = json.loads(claimed.read_text(encoding="utf-8"))
            validate_governance_record("work_item_activation_envelope.v1", envelope)
            runtime_nonce = str(envelope["runtime_binding"]["runtime_instance_nonce"])
            identity = self.process_identity_provider(runtime_nonce)
            if identity["expected_process_identity"] != envelope["runtime_binding"]["expected_process_identity"]:
                raise WorkItemGovernanceError(
                    "PROCESS_IDENTITY_MISMATCH",
                    "Waiting process identity does not match Preflight.",
                )
            with self.ledger.write_transaction() as connection:
                row = connection.execute(
                    "SELECT * FROM activation_leases WHERE lease_id=?",
                    (lease_id,),
                ).fetchone()
                if row is None or row["status"] != "prepared":
                    raise WorkItemGovernanceError(
                        "PREPARED_ACTIVATION_LEASE_REQUIRED",
                        "Prepared Lease is missing.",
                    )
                if row["activation_envelope_digest"] != canonical_sha256(envelope):
                    raise WorkItemGovernanceError(
                        "ACTIVATION_ENVELOPE_DIGEST_MISMATCH",
                        "Claimed Envelope digest mismatch.",
                    )
                self._validate_prepared_freshness(row)
                self._assert_fresh_baseline(connection, None)
                claim_ns = self.monotonic_ns()
                deadline_ns = claim_ns + int(row["maximum_runtime_seconds"]) * 1_000_000_000
                runtime = _json(row, "runtime_binding_json")
                runtime["claimed_process_identity"] = identity["expected_process_identity"]
                runtime["monotonic_claim_ns"] = claim_ns
                runtime["monotonic_deadline_ns"] = deadline_ns
                usage = _json(row, "usage_json")
                usage["lease_events"] = 2
                now = isoformat_utc(self.now())
                cursor = connection.execute(
                    """
                    UPDATE activation_leases
                    SET claimed_process_identity=?,monotonic_claim_ns=?,monotonic_deadline_ns=?,
                        runtime_binding_json=?,usage_json=?,status='claimed',state_version=1,updated_at=?
                    WHERE lease_id=? AND status='prepared' AND state_version=0
                    """,
                    (
                        identity["expected_process_identity"], claim_ns, deadline_ns,
                        canonical_json(runtime), canonical_json(usage), now, lease_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise WorkItemGovernanceError(
                        "ACTIVATION_LEASE_CAS_CONFLICT",
                        "Prepared Lease claim CAS failed.",
                    )
                claimed_row = connection.execute(
                    "SELECT * FROM activation_leases WHERE lease_id=?",
                    (lease_id,),
                ).fetchone()
                _append_lease_event(
                    connection,
                    row=claimed_row,
                    event_type="process_claimed",
                    status_before="prepared",
                    status_after="claimed",
                    state_version_before=0,
                    state_version_after=1,
                    created_at=now,
                )
                lease = _lease_record(claimed_row)
                validate_governance_record("work_item_activation_lease.v1", lease)
        except Exception:
            try:
                self.revoke(lease_id=lease_id, reason="single_use_claim_validation_failed")
            except WorkItemGovernanceError:
                pass
            raise
        return {"lease": lease, "claimed_envelope_path": str(claimed), "claimed": True}

    def attest_listener(
        self,
        *,
        lease_id: str,
        bind_address: str,
        port: int,
        process_listener_count: int,
    ) -> dict[str, Any]:
        if bind_address != "127.0.0.1" or process_listener_count != 1:
            self.revoke(lease_id=lease_id, reason="listener_attestation_mismatch")
            raise WorkItemGovernanceError("LISTENER_ATTESTATION_FAILED", "Listener attestation failed closed.")
        with self.ledger.write_transaction() as connection:
            row = connection.execute(
                "SELECT * FROM activation_leases WHERE lease_id=?",
                (lease_id,),
            ).fetchone()
            if row is None or row["status"] != "claimed" or int(row["state_version"]) != 1:
                raise WorkItemGovernanceError("CLAIMED_ACTIVATION_LEASE_REQUIRED", "Claimed Lease is missing.")
            runtime = _json(row, "runtime_binding_json")
            if runtime.get("bind_address") != bind_address or int(runtime.get("port", -1)) != port:
                raise WorkItemGovernanceError("LISTENER_BINDING_MISMATCH", "Listener endpoint differs from Lease.")
            current_identity = self.process_identity_provider(str(runtime["runtime_instance_nonce"]))
            if current_identity["expected_process_identity"] != row["claimed_process_identity"]:
                raise WorkItemGovernanceError(
                    "PROCESS_IDENTITY_MISMATCH",
                    "Listener process differs from the process that claimed the Lease.",
                )
            principal = _json(row, "principal_binding_json")
            digest = listener_attestation_digest(
                claimed_process_identity=str(row["claimed_process_identity"]),
                bind_address=bind_address,
                port=port,
                process_listener_count=process_listener_count,
            )
            context_digest = request_context_binding_digest(
                lease_id=str(row["lease_id"]),
                authorization_digest=str(row["authorization_digest"]),
                claimed_process_identity=str(row["claimed_process_identity"]),
                runtime_instance_nonce=str(runtime["runtime_instance_nonce"]),
                listener_digest=digest,
                principal_id=str(principal["principal_id"]),
                session_ref=str(principal["session_ref"]),
            )
            now = isoformat_utc(self.now())
            runtime.update(
                {
                    "listener_attested_at": now,
                    "listener_attestation_digest": digest,
                    "authenticated_request_context_binding_digest": context_digest,
                }
            )
            usage = _json(row, "usage_json")
            usage["lease_events"] = 3
            connection.execute(
                """
                UPDATE activation_leases
                SET listener_attested_at=?,listener_attestation_digest=?,request_context_binding_digest=?,
                    runtime_binding_json=?,usage_json=?,status='active',state_version=2,updated_at=?
                WHERE lease_id=? AND status='claimed' AND state_version=1
                """,
                (now, digest, context_digest, canonical_json(runtime), canonical_json(usage), now, lease_id),
            )
            active = connection.execute(
                "SELECT * FROM activation_leases WHERE lease_id=?",
                (lease_id,),
            ).fetchone()
            _append_lease_event(
                connection,
                row=active,
                event_type="listener_attested",
                status_before="claimed",
                status_after="active",
                state_version_before=1,
                state_version_after=2,
                created_at=now,
            )
            lease = _lease_record(active)
            validate_governance_record("work_item_activation_lease.v1", lease)
        return {"lease": lease, "listener_attested": True}

    def freeze(self, *, lease_id: str, reason: str = "control_plane_closeout") -> dict[str, Any]:
        with self.ledger.write_transaction() as connection:
            row = connection.execute("SELECT * FROM activation_leases WHERE lease_id=?", (lease_id,)).fetchone()
            if row is None:
                raise WorkItemGovernanceError("ACTIVATION_LEASE_NOT_FOUND", "Activation Lease does not exist.")
            if row["status"] == "write_frozen":
                return {"lease": _lease_record(row), "idempotent": True}
            if row["status"] != "active":
                raise WorkItemGovernanceError("ACTIVE_ACTIVATION_LEASE_REQUIRED", "Only an active Lease can freeze.")
            next_version = int(row["state_version"]) + 1
            usage = _json(row, "usage_json")
            usage["lease_events"] += 1
            now = isoformat_utc(self.now())
            connection.execute(
                "UPDATE activation_leases SET status='write_frozen',state_version=?,usage_json=?,updated_at=? WHERE lease_id=?",
                (next_version, canonical_json(usage), now, lease_id),
            )
            frozen = connection.execute("SELECT * FROM activation_leases WHERE lease_id=?", (lease_id,)).fetchone()
            _append_lease_event(
                connection,
                row=frozen,
                event_type="lease_write_frozen",
                status_before="active",
                status_after="write_frozen",
                state_version_before=int(row["state_version"]),
                state_version_after=next_version,
                created_at=now,
                reason_code=reason,
            )
        return {"lease": _lease_record(frozen), "idempotent": False}

    def close(self, *, lease_id: str, reason: str = "closeout_complete") -> dict[str, Any]:
        with self.ledger.write_transaction() as connection:
            row = connection.execute("SELECT * FROM activation_leases WHERE lease_id=?", (lease_id,)).fetchone()
            if row is None:
                raise WorkItemGovernanceError("ACTIVATION_LEASE_NOT_FOUND", "Activation Lease does not exist.")
            if row["status"] == "closed":
                return {"lease": _lease_record(row), "idempotent": True}
            if row["status"] != "write_frozen":
                raise WorkItemGovernanceError("FROZEN_ACTIVATION_LEASE_REQUIRED", "Lease must be write-frozen first.")
            next_version = int(row["state_version"]) + 1
            usage = _json(row, "usage_json")
            usage["lease_events"] += 1
            now = isoformat_utc(self.now())
            connection.execute(
                "UPDATE activation_leases SET status='closed',state_version=?,usage_json=?,updated_at=? WHERE lease_id=?",
                (next_version, canonical_json(usage), now, lease_id),
            )
            closed = connection.execute("SELECT * FROM activation_leases WHERE lease_id=?", (lease_id,)).fetchone()
            _append_lease_event(
                connection,
                row=closed,
                event_type="lease_closed",
                status_before="write_frozen",
                status_after="closed",
                state_version_before=int(row["state_version"]),
                state_version_after=next_version,
                created_at=now,
                reason_code=reason,
            )
        return {"lease": _lease_record(closed), "idempotent": False}

    def revoke(self, *, lease_id: str, reason: str) -> dict[str, Any]:
        with self.ledger.write_transaction() as connection:
            row = connection.execute("SELECT * FROM activation_leases WHERE lease_id=?", (lease_id,)).fetchone()
            if row is None:
                raise WorkItemGovernanceError("ACTIVATION_LEASE_NOT_FOUND", "Activation Lease does not exist.")
            if row["status"] == "revoked":
                return {"lease": _lease_record(row), "idempotent": True}
            if row["status"] not in {"prepared", "claimed", "active"}:
                raise WorkItemGovernanceError("ACTIVATION_LEASE_TERMINAL", "Lease cannot be revoked from this state.")
            next_version = int(row["state_version"]) + 1
            usage = _json(row, "usage_json")
            usage["lease_events"] += 1
            now = isoformat_utc(self.now())
            before = str(row["status"])
            connection.execute(
                "UPDATE activation_leases SET status='revoked',state_version=?,usage_json=?,updated_at=? WHERE lease_id=?",
                (next_version, canonical_json(usage), now, lease_id),
            )
            revoked = connection.execute("SELECT * FROM activation_leases WHERE lease_id=?", (lease_id,)).fetchone()
            _append_lease_event(
                connection,
                row=revoked,
                event_type="lease_revoked",
                status_before=before,
                status_after="revoked",
                state_version_before=int(row["state_version"]),
                state_version_after=next_version,
                created_at=now,
                reason_code=reason,
            )
        return {"lease": _lease_record(revoked), "idempotent": False}

    def export_closeout_evidence(
        self,
        *,
        lease_id: str,
        destination: str | os.PathLike[str],
    ) -> dict[str, Any]:
        root = Path(destination).expanduser().resolve()
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        with self.ledger.read_connection() as connection:
            row = connection.execute("SELECT * FROM activation_leases WHERE lease_id=?", (lease_id,)).fetchone()
            if row is None:
                raise WorkItemGovernanceError("ACTIVATION_LEASE_NOT_FOUND", "Activation Lease does not exist.")
            events = [
                json.loads(str(item["event_json"]))
                for item in connection.execute(
                    "SELECT event_json FROM activation_lease_events WHERE lease_id=? ORDER BY sequence",
                    (lease_id,),
                ).fetchall()
            ]
            lease = _lease_record(row)
        snapshot_text = canonical_json(lease)
        events_text = canonical_json(events)
        snapshot_path = root / "activation-lease-snapshot.json"
        events_path = root / "activation-lease-events.json"
        self._write_private_file(snapshot_path, snapshot_text)
        self._write_private_file(events_path, events_text)
        event_digests = [str(event["event_digest"]) for event in events]
        chain = verify_activation_lease_event_chain(self.ledger, lease_id)
        return {
            "lease_snapshot_digest": canonical_sha256(lease),
            "lease_snapshot_export": str(snapshot_path),
            "lease_snapshot_export_sha256": sha256_file(snapshot_path),
            "lease_event_count": len(events),
            "lease_event_root_sha256": canonical_sha256(event_digests),
            "lease_event_export": str(events_path),
            "lease_event_export_sha256": sha256_file(events_path),
            "lease_event_chain_verified": chain["chain_verified"],
            "final_status": chain["final_status"],
            "final_state_version": chain["final_state_version"],
        }

    def _lease_from_contracts(
        self,
        *,
        activation_envelope: dict[str, Any],
        synthetic_fixture: dict[str, Any],
        preflight_receipt: dict[str, Any],
    ) -> dict[str, Any]:
        runtime = preflight_receipt["runtime_isolation"]
        process = preflight_receipt["process_identity_inputs"]
        source = activation_envelope["source_binding"]
        principal = activation_envelope["principal_binding"]
        fixture_digest = canonical_sha256(synthetic_fixture)
        issued_at = activation_envelope["window"]["issued_at"]
        updated_at = isoformat_utc(self.now())
        return {
            "schema_version": "work_item_activation_lease.v1",
            "lease_id": activation_envelope["activation_lease_id"],
            "authorization_id": activation_envelope["authorization_id"],
            "authorization_digest": activation_envelope["authorization_digest"],
            "activation_envelope_digest": canonical_sha256(activation_envelope),
            "spec_manifest_digest": activation_envelope["spec_manifest_digest"],
            "activation_envelope_schema_digest": _resource_sha256("activation-envelope.v1.schema.json"),
            "synthetic_fixture_schema_digest": _resource_sha256("synthetic-fixture-contract.v1.schema.json"),
            "preflight_receipt_schema_digest": _resource_sha256("preflight-receipt.v1.schema.json"),
            "lease_event_schema_digest": _resource_sha256("activation-lease-event.v1.schema.json"),
            "source_binding": source,
            "runtime_binding": {
                "instance_id": activation_envelope["runtime_binding"]["instance_id"],
                "runtime_instance_nonce": activation_envelope["runtime_binding"]["runtime_instance_nonce"],
                "expected_process_identity": process["expected_process_identity"],
                "claimed_process_identity": None,
                "listener_attested_at": None,
                "listener_attestation_digest": None,
                "authenticated_request_context_binding_digest": None,
                "monotonic_clock": "CLOCK_MONOTONIC",
                "monotonic_claim_ns": None,
                "monotonic_deadline_ns": None,
                "bind_address": activation_envelope["runtime_binding"]["bind_address"],
                "port": activation_envelope["runtime_binding"]["port"],
                "canary_root_digest": runtime["canary_root_path_digest"],
                "activation_envelope_path_digest": runtime["activation_envelope_path_digest"],
                "claimed_activation_envelope_path_digest": runtime["claimed_activation_envelope_path_digest"],
                "runtime_executable_path_digest": runtime["runtime_executable_path_digest"],
                "cwd_path_digest": runtime["cwd_path_digest"],
                "settings_path_digest": runtime["settings_path_digest"],
                "home_path_digest": runtime["home_path_digest"],
                "xdg_config_path_digest": runtime["xdg_config_path_digest"],
                "xdg_state_path_digest": runtime["xdg_state_path_digest"],
                "xdg_cache_path_digest": runtime["xdg_cache_path_digest"],
                "registry_path_digest": runtime["registry_path_digest"],
                "registry_project_count": runtime["registry_project_count"],
                "project_name": activation_envelope["runtime_binding"]["project_name"],
                "project_root_digest": runtime["project_root_digest"],
                "ledger_path_digest": runtime["ledger_path_digest"],
                "backup_path_digest": runtime["backup_path_digest"],
                "token_file_path_digest": preflight_receipt["authentication"]["token_file_path_digest"],
                "fixture_root_path_digest": runtime["fixture_root_path_digest"],
                "ledger_schema_version": preflight_receipt["fresh_ledger"]["schema_version"],
                "database_generation": preflight_receipt["fresh_ledger"]["database_generation"],
                "preflight_receipt_digest": canonical_sha256(preflight_receipt),
                "preflight_observed_at": preflight_receipt["observed_at"],
                "preflight_valid_until": preflight_receipt["valid_until"],
                "maximum_preflight_age_seconds": preflight_receipt["maximum_age_seconds"],
                "fresh_ledger_baseline_digest": preflight_receipt["fresh_ledger"]["baseline_digest"],
                "pre_activation_backup_receipt_digest": preflight_receipt["pre_activation_backup"]["receipt_digest"],
                "pre_activation_backup_sha256": preflight_receipt["pre_activation_backup"]["backup_sha256"],
                "tool_allowlist_digest": preflight_receipt["restricted_surface"]["tool_allowlist_digest"],
                "command_matrix_digest": preflight_receipt["restricted_surface"]["command_matrix_digest"],
                "global_registry_fallback": False,
                "public_endpoint_created": False,
                "relay_enabled": False,
                "tunnel_enabled": False,
                "proxy_enabled": False,
            },
            "principal_binding": {
                "principal_id": principal["principal_id"],
                "principal_kind": principal["principal_kind"],
                "session_ref": principal["session_ref"],
                "caller_auth_mode": "token",
                "principal_authenticated_by": "local_session",
                "permissions": principal["permissions"],
            },
            "bootstrap": {
                "mode": "one_shot_pre_listener_process_claim",
                "activation_envelope_source": "isolated_0600_file",
                "listener_before_claim": False,
                "claim_transaction": "BEGIN_IMMEDIATE",
                "process_identity_algorithm": process["identity_algorithm"],
                "envelope_claim_operation": "atomic_noreplace_move_to_process_identity_claim_path_then_fsync_parent",
                "unclaimed_envelope_after_claim": "must_be_absent",
                "claim_recovery": "deny_reuse_require_new_authorization",
                "request_dispatch_before_listener_attestation": False,
                "listener_attestation_event": "listener_attested",
                "claim_reusable_after_failure": False,
                "claim_reusable_after_process_exit": False,
            },
            "window": activation_envelope["window"],
            "scope": {
                "origin_kind": "manual",
                "allowed_origin_prefix": "synthetic://WIG-P3-AUTH-CANARY-A1-R2/",
                "authorized_work_item_id": None,
                "synthetic_fixture_contract_digest": fixture_digest,
                "authorized_create_command_digest": synthetic_fixture["normalized_create"]["normalized_command_digest"],
                "authorized_task_version_payload_digests": [
                    item["normalized_payload_digest"] for item in synthetic_fixture["task_versions"]
                ],
                "objective_ref_prefix": synthetic_fixture["objective_ref_prefix"],
                "fixture_root_digest": synthetic_fixture["fixture_root_path_digest"],
                "artifact_uri_scheme": synthetic_fixture["artifact_uri_scheme"],
                "allowed_artifact_kinds": synthetic_fixture["allowed_artifact_kinds"],
                "external_associations_allowed": False,
                "plan_version_refs_allowed": False,
                "real_git_commit_artifacts_allowed": False,
            },
            "fixture_bindings": {
                "attempt_ids": [],
                "artifact_ids": [],
                "decision_ids": [],
                "gate_event_ids": [],
            },
            "quotas": dict(DEFAULT_QUOTAS),
            "usage": dict(EMPTY_USAGE),
            "policy": {
                "allowed_write_commands": list(ALLOWED_WRITE_COMMANDS),
                "denied_write_commands": list(DENIED_WRITE_COMMANDS),
                "unknown_command": "deny",
                "authenticated_request_context_required": True,
                "request_context_mode": "sealed_token_verified_listener_attested_context",
                "request_context_binding_algorithm": (
                    "sha256(canonical_json({lease_id,authorization_digest,claimed_process_identity,"
                    "runtime_instance_nonce,listener_attestation_digest,principal_id,session_ref}))"
                ),
                "control_plane_domain_writes": "denied",
                "lease_event_idempotency": "new_domain_fact_at_most_one_event_exact_replay_zero_events",
                "fact_reconciliation": "actual_primary_and_denied_table_counts_must_match_lease_usage",
            },
            "maintenance": {
                "restore": "denied_during_activation_window",
                "migration": "pre_activation_exact_schema_only",
                "backup": "control_plane_only_outside_active_window",
                "export": "read_only_control_plane_after_write_freeze",
            },
            "failure_behavior": {
                "authentication_failure": "reject_without_lease_mutation",
                "ordinary_domain_rejection": "reject_or_record_domain_fact_without_lease_freeze",
                "hard_guard_violation": "reject_domain_mutation_and_write_freeze_lease",
                "expiration": "reject_preview_and_write_even_without_watchdog",
                "internal_guard_error": "reject_domain_mutation_and_write_freeze_lease",
                "reads_after_write_freeze": "allowed_for_closeout",
            },
            "status": "prepared",
            "state_version": 0,
            "created_at": issued_at,
            "updated_at": updated_at,
        }

    @staticmethod
    def _insert_lease(
        connection: sqlite3.Connection,
        lease: dict[str, Any],
        synthetic_fixture: dict[str, Any],
    ) -> None:
        connection.execute(
            """
            INSERT INTO activation_leases(
              lease_id,schema_version,authorization_id,authorization_digest,activation_envelope_digest,
              spec_manifest_digest,expected_process_identity,claimed_process_identity,listener_attested_at,
              listener_attestation_digest,request_context_binding_digest,monotonic_claim_ns,monotonic_deadline_ns,
              not_before,expires_at,maximum_runtime_seconds,authorized_work_item_id,source_binding_json,
              runtime_binding_json,principal_binding_json,bootstrap_json,scope_json,fixture_json,quotas_json,
              fixture_bindings_json,usage_json,policy_json,maintenance_json,failure_behavior_json,status,state_version,
              created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                lease["lease_id"], lease["schema_version"], lease["authorization_id"],
                lease["authorization_digest"], lease["activation_envelope_digest"],
                lease["spec_manifest_digest"], lease["runtime_binding"]["expected_process_identity"],
                None, None, None, None, None, None, lease["window"]["not_before"],
                lease["window"]["expires_at"], lease["window"]["maximum_runtime_seconds"], None,
                canonical_json(lease["source_binding"]), canonical_json(lease["runtime_binding"]),
                canonical_json(lease["principal_binding"]), canonical_json(lease["bootstrap"]),
                canonical_json(lease["scope"]), canonical_json(synthetic_fixture),
                canonical_json(lease["quotas"]), canonical_json(lease["fixture_bindings"]),
                canonical_json(lease["usage"]),
                canonical_json(lease["policy"]), canonical_json(lease["maintenance"]),
                canonical_json(lease["failure_behavior"]), lease["status"], lease["state_version"],
                lease["created_at"], lease["updated_at"],
            ),
        )

    def _assert_fresh_baseline(
        self,
        connection: sqlite3.Connection,
        preflight_receipt: dict[str, Any] | None,
    ) -> None:
        actual = business_fact_counts(connection)
        if any(actual.values()):
            raise WorkItemGovernanceError(
                "FRESH_LEDGER_REQUIRED",
                "The Authoritative Canary requires an empty business fact domain.",
                details={"counts": actual},
            )
        if preflight_receipt is not None and actual != preflight_receipt["fresh_ledger"]["business_fact_counts"]:
            raise WorkItemGovernanceError("FRESH_LEDGER_BASELINE_MISMATCH", "Fresh Ledger baseline changed.")
        for query in FRESH_EXECUTION_FACT_COUNT_QUERIES.values():
            if int(connection.execute(query).fetchone()[0]) != 0:
                raise WorkItemGovernanceError("FRESH_LEDGER_REQUIRED", "Fresh Ledger contains execution associations.")

    def _validate_prepared_freshness(self, row: sqlite3.Row) -> None:
        runtime = _json(row, "runtime_binding_json")
        valid_until = parse_timestamp(runtime["preflight_valid_until"], "preflight_valid_until")
        observed = parse_timestamp(runtime["preflight_observed_at"], "preflight_observed_at")
        now = self.now().astimezone(timezone.utc)
        if now > valid_until or (now - observed).total_seconds() > 120:
            raise WorkItemGovernanceError("PREFLIGHT_EXPIRED", "Fresh Preflight is older than 120 seconds.")

    def _validate_preflight_freshness(self, receipt: dict[str, Any]) -> None:
        observed = parse_timestamp(receipt["observed_at"], "observed_at")
        valid_until = parse_timestamp(receipt["valid_until"], "valid_until")
        now = self.now().astimezone(timezone.utc)
        if valid_until < observed or (valid_until - observed).total_seconds() > 120 or now > valid_until:
            raise WorkItemGovernanceError("PREFLIGHT_EXPIRED", "Fresh Preflight is invalid or stale.")

    def _validate_preflight_paths(self, receipt: dict[str, Any]) -> None:
        runtime = receipt["runtime_isolation"]
        if Path(runtime["canary_root_resolved_path"]).resolve() != self.canary_root:
            raise WorkItemGovernanceError("CANARY_ROOT_MISMATCH", "Preflight Canary root mismatch.")
        pairs = {
            "home_relative_path": "home_path_digest",
            "xdg_config_relative_path": "xdg_config_path_digest",
            "xdg_state_relative_path": "xdg_state_path_digest",
            "xdg_cache_relative_path": "xdg_cache_path_digest",
            "registry_relative_path": "registry_path_digest",
            "project_root_relative_path": "project_root_digest",
            "runtime_executable_relative_path": "runtime_executable_path_digest",
            "cwd_relative_path": "cwd_path_digest",
            "settings_relative_path": "settings_path_digest",
            "ledger_relative_path": "ledger_path_digest",
            "backup_relative_path": "backup_path_digest",
            "activation_envelope_relative_path": "activation_envelope_path_digest",
            "claimed_activation_envelope_relative_path": "claimed_activation_envelope_path_digest",
            "fixture_root_relative_path": "fixture_root_path_digest",
        }
        for relative_field, digest_field in pairs.items():
            target = (self.canary_root / runtime[relative_field]).resolve()
            try:
                target.relative_to(self.canary_root)
            except ValueError as exc:
                raise WorkItemGovernanceError("CANARY_PATH_ESCAPE", "Preflight path escapes Canary root.") from exc
            if canonical_path_digest(target) != runtime[digest_field]:
                raise WorkItemGovernanceError(
                    "CANARY_PATH_DIGEST_MISMATCH",
                    "Preflight path digest mismatch.",
                    details={"field": relative_field},
                )

    def _validate_preflight_contract_bindings(
        self,
        *,
        activation_envelope: dict[str, Any],
        preflight_receipt: dict[str, Any],
    ) -> None:
        policy = validate_runtime_policy_contracts()
        restricted = preflight_receipt["restricted_surface"]
        if (
            activation_envelope["source_binding"] != preflight_receipt["source_binding"]
            or activation_envelope["principal_binding"] != preflight_receipt["principal_binding"]
            or restricted["listed_tools_sha256"] != canonical_sha256(list(AUTHORITATIVE_CANARY_TOOLS))
            or restricted["tool_allowlist_digest"] != policy["tool_allowlist_digest"]
            or restricted["command_matrix_digest"] != policy["command_matrix_digest"]
            or activation_envelope["tool_allowlist_digest"] != policy["tool_allowlist_digest"]
            or activation_envelope["command_matrix_digest"] != policy["command_matrix_digest"]
        ):
            raise WorkItemGovernanceError(
                "PREFLIGHT_POLICY_BINDING_MISMATCH",
                "Preflight policy/source/Principal binding differs from the Activation Envelope.",
            )
        authentication = preflight_receipt["authentication"]
        token_file = (self.canary_root / authentication["token_file_relative_path"]).resolve()
        try:
            token_file.relative_to(self.canary_root)
        except ValueError as exc:
            raise WorkItemGovernanceError(
                "ACTIVATION_TOKEN_BINDING_MISMATCH",
                "Preflight Token file escapes the isolated Canary root.",
            ) from exc
        if canonical_path_digest(token_file) != authentication["token_file_path_digest"]:
            raise WorkItemGovernanceError(
                "ACTIVATION_TOKEN_BINDING_MISMATCH",
                "Preflight Token path differs from its exact digest binding.",
            )
        require_authoritative_token_file_binding(
            self.ledger,
            token_file,
            expected_evidence_digest=authentication["token_generation_evidence_digest"],
        )
        fresh = preflight_receipt["fresh_ledger"]
        baseline = {
            "business_fact_counts": fresh["business_fact_counts"],
            "external_associations": fresh["external_associations"],
            "attempt_events": fresh["attempt_events"],
            "prior_activation_leases_for_authorization": fresh[
                "prior_activation_leases_for_authorization"
            ],
        }
        if (
            canonical_sha256(baseline) != fresh["baseline_digest"]
            or activation_envelope["fresh_ledger_baseline_digest"] != fresh["baseline_digest"]
            or fresh["schema_version"] != self.ledger.schema_version()
            or fresh["database_generation"] != self.ledger.database_generation()
        ):
            raise WorkItemGovernanceError(
                "FRESH_LEDGER_BINDING_MISMATCH",
                "Fresh Ledger baseline or generation differs from Preflight.",
            )
        self.ledger.get_existing_signing_key()
        backup = preflight_receipt["pre_activation_backup"]
        backup_path = (
            self.canary_root / preflight_receipt["runtime_isolation"]["backup_relative_path"]
        ).resolve()
        backup_core = {key: value for key, value in backup.items() if key != "receipt_digest"}
        if (
            not backup_path.is_file()
            or sha256_file(backup_path) != backup["backup_sha256"]
            or canonical_sha256(backup_core) != backup["receipt_digest"]
            or activation_envelope["pre_activation_backup_receipt_digest"] != backup["receipt_digest"]
            or activation_envelope["pre_activation_backup_sha256"] != backup["backup_sha256"]
        ):
            raise WorkItemGovernanceError(
                "PRE_ACTIVATION_BACKUP_BINDING_MISMATCH",
                "Pre-activation Backup bytes or Receipt binding differs.",
            )

    def _validate_fixture_paths(
        self,
        fixture: dict[str, Any],
        preflight_receipt: dict[str, Any],
    ) -> None:
        runtime = preflight_receipt["runtime_isolation"]
        fixture_root = (self.canary_root / runtime["fixture_root_relative_path"]).resolve()
        try:
            fixture_root.relative_to(self.canary_root)
        except ValueError as exc:
            raise WorkItemGovernanceError(
                "FIXTURE_ROOT_PATH_ESCAPE",
                "Synthetic Fixture root escapes the Canary root.",
            ) from exc
        if canonical_path_digest(fixture_root) != fixture["fixture_root_path_digest"]:
            raise WorkItemGovernanceError(
                "FIXTURE_ROOT_DIGEST_MISMATCH",
                "Synthetic Fixture root digest differs from Preflight.",
            )
        reviewed: dict[tuple[str, str], Path] = {}
        for artifact in fixture["artifact_files"]:
            target = (fixture_root / artifact["relative_path"]).resolve()
            try:
                target.relative_to(fixture_root)
            except ValueError as exc:
                raise WorkItemGovernanceError(
                    "FIXTURE_ARTIFACT_PATH_ESCAPE",
                    "Synthetic Fixture Artifact escapes its reviewed root.",
                ) from exc
            if not target.is_file() or sha256_file(target) != artifact["sha256"]:
                raise WorkItemGovernanceError(
                    "FIXTURE_ARTIFACT_DIGEST_MISMATCH",
                    "Synthetic Fixture Artifact bytes differ from the reviewed declaration.",
                    details={"slot": artifact["slot"]},
                )
            reviewed[(artifact["kind"], artifact["sha256"])] = target
        for slot in fixture["command_slots"]:
            if slot["expected_outcome"] == "exact_idempotent_replay":
                continue
            command = slot["normalized_command"]
            artifacts: list[dict[str, Any]] = []
            if slot["command_name"] == "register_artifact_reference":
                artifacts = [command]
            elif slot["command_name"] == "complete_execution_attempt":
                artifacts = [item for item in command.get("artifacts", []) if isinstance(item, dict)]
            for artifact in artifacts:
                expected = reviewed.get((str(artifact.get("kind")), str(artifact.get("digest"))))
                uri = str(artifact.get("uri", ""))
                actual = Path(uri[len("file://") :]).expanduser().resolve() if uri.startswith("file://") else None
                if expected is None or actual != expected:
                    raise WorkItemGovernanceError(
                        "FIXTURE_ARTIFACT_URI_MISMATCH",
                        "Synthetic Artifact command URI is not the reviewed immutable Fixture file.",
                    )

    def _atomic_write_envelope(self, path: Path, value: dict[str, Any]) -> None:
        try:
            path.relative_to(self.canary_root)
        except ValueError as exc:
            raise WorkItemGovernanceError("ACTIVATION_ENVELOPE_PATH_ESCAPE", "Envelope escapes Canary root.") from exc
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if path.exists() or path.is_symlink():
            raise WorkItemGovernanceError("ACTIVATION_ENVELOPE_EXISTS", "Activation Envelope already exists.")
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags, 0o600)
        try:
            data = canonical_json(value).encode("utf-8")
            os.write(descriptor, data)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.chmod(path, 0o600)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    def _claim_file_no_replace(self, source: Path, destination: Path) -> None:
        try:
            source.relative_to(self.canary_root)
            destination.relative_to(self.canary_root)
        except ValueError as exc:
            raise WorkItemGovernanceError("ACTIVATION_ENVELOPE_PATH_ESCAPE", "Claim path escapes Canary root.") from exc
        try:
            os.link(source, destination, follow_symlinks=False)
        except FileExistsError as exc:
            raise WorkItemGovernanceError("ACTIVATION_ENVELOPE_ALREADY_CLAIMED", "Claim path exists.") from exc
        source.unlink()
        for parent in {source.parent, destination.parent}:
            directory = os.open(parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)

    @staticmethod
    def _write_private_file(path: Path, text: str) -> None:
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags, 0o600)
        try:
            os.write(descriptor, text.encode("utf-8"))
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.chmod(path, 0o600)
