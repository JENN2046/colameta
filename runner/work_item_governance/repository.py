from __future__ import annotations

import os
import secrets
import sqlite3
import tempfile
import fcntl
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Sequence

from runner.work_item_governance.canonical import canonical_json, canonical_sha256
from runner.work_item_governance.contracts import (
    CURRENT_LEDGER_SCHEMA_VERSION,
    DEFAULT_BUSY_TIMEOUT_MS,
    LEDGER_RELATIVE_PATH,
)
from runner.work_item_governance.errors import CommitWorkItemRejection, WorkItemGovernanceError
from runner.work_item_governance.settings import load_work_item_governance_settings


class _ActivationControlWriteSession:
    """Exact, process-local authority for one Lease-control transaction.

    The session deliberately has no serializable or copyable representation.
    Repository authorization additionally requires object identity in a
    per-ledger issuance registry, so reconstructing an object with matching
    attributes never grants control-table write authority.
    """

    __slots__ = ("ledger", "connection", "controller", "_seal")

    def __init__(
        self,
        *,
        ledger: "SQLiteWorkItemLedger",
        connection: sqlite3.Connection,
        controller: Any,
        seal: bytes,
    ) -> None:
        self.ledger = ledger
        self.connection = connection
        self.controller = controller
        self._seal = seal

    def __copy__(self) -> "_ActivationControlWriteSession":
        raise TypeError("Activation control-write sessions cannot be copied.")

    def __deepcopy__(self, _memo: dict[int, Any]) -> "_ActivationControlWriteSession":
        raise TypeError("Activation control-write sessions cannot be copied.")

    def __reduce__(self) -> Any:
        raise TypeError("Activation control-write sessions cannot be serialized.")

    def __reduce_ex__(self, _protocol: int) -> Any:
        raise TypeError("Activation control-write sessions cannot be serialized.")


class _ActivationControllerBinding:
    """Non-serializable binding for one exact activation controller instance."""

    __slots__ = ("ledger", "controller", "_seal")

    def __init__(self, *, ledger: "SQLiteWorkItemLedger", controller: Any, seal: bytes) -> None:
        self.ledger = ledger
        self.controller = controller
        self._seal = seal

    def __copy__(self) -> "_ActivationControllerBinding":
        raise TypeError("Activation controller bindings cannot be copied.")

    def __deepcopy__(self, _memo: dict[int, Any]) -> "_ActivationControllerBinding":
        raise TypeError("Activation controller bindings cannot be copied.")

    def __reduce__(self) -> Any:
        raise TypeError("Activation controller bindings cannot be serialized.")

    def __reduce_ex__(self, _protocol: int) -> Any:
        raise TypeError("Activation controller bindings cannot be serialized.")


def _migration_v1() -> tuple[str, ...]:
    return (
        """
        CREATE TABLE ledger_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE work_items (
            work_item_id TEXT PRIMARY KEY,
            schema_version TEXT NOT NULL CHECK (schema_version = 'work_item.v1'),
            state TEXT NOT NULL CHECK (state IN ('proposed','ready','in_delivery','submitted','accepted','cancelled')),
            state_version INTEGER NOT NULL DEFAULT 0 CHECK (state_version >= 0),
            origin_kind TEXT NOT NULL CHECK (origin_kind IN ('quick_chat','project','workbench','slack','linear','manual','imported')),
            origin_ref TEXT,
            origin_snapshot_digest TEXT NOT NULL CHECK (length(origin_snapshot_digest) = 64),
            imported INTEGER NOT NULL CHECK (imported IN (0,1)),
            current_task_version INTEGER NOT NULL CHECK (current_task_version >= 1),
            attributes_json TEXT NOT NULL CHECK (json_valid(attributes_json)),
            content_digest TEXT NOT NULL CHECK (length(content_digest) = 64),
            creation_operation TEXT NOT NULL CHECK (creation_operation IN ('create','legacy_import')),
            creation_preview_id TEXT NOT NULL UNIQUE,
            creation_idempotency_key TEXT UNIQUE,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (origin_kind, origin_ref, origin_snapshot_digest)
        )
        """,
        """
        CREATE TABLE task_versions (
            work_item_id TEXT NOT NULL,
            task_version INTEGER NOT NULL CHECK (task_version >= 1),
            schema_version TEXT NOT NULL CHECK (schema_version = 'task_version.v1'),
            objective_ref TEXT,
            plan_version_refs_json TEXT NOT NULL CHECK (json_valid(plan_version_refs_json)),
            artifact_contract_json TEXT NOT NULL CHECK (json_valid(artifact_contract_json)),
            approval_requirements_json TEXT NOT NULL CHECK (json_valid(approval_requirements_json)),
            reporting_destination_json TEXT NOT NULL CHECK (json_valid(reporting_destination_json)),
            expected_receipt_contract_json TEXT NOT NULL CHECK (json_valid(expected_receipt_contract_json)),
            payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
            payload_digest TEXT NOT NULL CHECK (length(payload_digest) = 64),
            source_event_key TEXT UNIQUE,
            created_at TEXT NOT NULL,
            PRIMARY KEY (work_item_id, task_version),
            FOREIGN KEY (work_item_id) REFERENCES work_items(work_item_id) ON DELETE RESTRICT
        )
        """,
        """
        CREATE TABLE execution_attempts (
            attempt_id TEXT PRIMARY KEY,
            schema_version TEXT NOT NULL CHECK (schema_version = 'execution_attempt.v1'),
            work_item_id TEXT NOT NULL,
            task_version INTEGER NOT NULL CHECK (task_version >= 1),
            status TEXT NOT NULL CHECK (status IN ('claimed','running','completed','failed','cancelled')),
            objective_ref TEXT,
            metadata_json TEXT NOT NULL CHECK (json_valid(metadata_json)),
            source_event_key TEXT UNIQUE,
            completion_event_key TEXT UNIQUE,
            created_at TEXT NOT NULL,
            completed_at TEXT,
            UNIQUE (attempt_id, work_item_id, task_version),
            FOREIGN KEY (work_item_id, task_version)
              REFERENCES task_versions(work_item_id, task_version) ON DELETE RESTRICT
        )
        """,
        """
        CREATE TABLE artifact_refs (
            artifact_id TEXT PRIMARY KEY,
            schema_version TEXT NOT NULL CHECK (schema_version = 'artifact_reference.v1'),
            work_item_id TEXT NOT NULL,
            task_version INTEGER NOT NULL CHECK (task_version >= 1),
            attempt_id TEXT,
            kind TEXT NOT NULL CHECK (kind IN ('report','validation','git_commit','git_diff','file','test_report','evidence_receipt','other')),
            uri TEXT NOT NULL,
            immutable_ref TEXT NOT NULL,
            digest TEXT NOT NULL CHECK (length(digest) = 64),
            metadata_json TEXT NOT NULL CHECK (json_valid(metadata_json)),
            source_event_key TEXT UNIQUE,
            created_at TEXT NOT NULL,
            UNIQUE (work_item_id, kind, immutable_ref),
            FOREIGN KEY (work_item_id, task_version)
              REFERENCES task_versions(work_item_id, task_version) ON DELETE RESTRICT,
            FOREIGN KEY (attempt_id) REFERENCES execution_attempts(attempt_id) ON DELETE RESTRICT
        )
        """,
        "CREATE INDEX idx_work_items_state_updated ON work_items(state, updated_at DESC)",
        "CREATE INDEX idx_attempts_work_item ON execution_attempts(work_item_id, task_version, created_at)",
        "CREATE INDEX idx_artifacts_work_item ON artifact_refs(work_item_id, task_version, created_at)",
    )


def _migration_v2() -> tuple[str, ...]:
    return (
        """
        CREATE TABLE external_associations (
            association_kind TEXT NOT NULL,
            external_ref TEXT NOT NULL,
            work_item_id TEXT NOT NULL,
            task_version INTEGER,
            attempt_id TEXT,
            source_event_key TEXT UNIQUE,
            created_at TEXT NOT NULL,
            PRIMARY KEY (association_kind, external_ref),
            FOREIGN KEY (work_item_id) REFERENCES work_items(work_item_id) ON DELETE RESTRICT,
            FOREIGN KEY (attempt_id) REFERENCES execution_attempts(attempt_id) ON DELETE RESTRICT
        )
        """,
        """
        CREATE TABLE attempt_events (
            event_id TEXT PRIMARY KEY,
            attempt_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            source_event_key TEXT NOT NULL UNIQUE,
            payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
            created_at TEXT NOT NULL,
            FOREIGN KEY (attempt_id) REFERENCES execution_attempts(attempt_id) ON DELETE RESTRICT
        )
        """,
        "CREATE INDEX idx_attempt_events_attempt ON attempt_events(attempt_id, created_at)",
    )


def _migration_v3() -> tuple[str, ...]:
    append_only_trigger_tables = ("decision_records", "gate_events", "audit_events", "blocker_events", "inbox_events")
    statements: list[str] = [
        """
        CREATE TABLE decision_records (
            decision_id TEXT PRIMARY KEY,
            schema_version TEXT NOT NULL CHECK (schema_version = 'decision_record.v1'),
            work_item_id TEXT NOT NULL,
            task_version INTEGER NOT NULL CHECK (task_version >= 1),
            actor_json TEXT NOT NULL CHECK (json_valid(actor_json)),
            action TEXT NOT NULL CHECK (action IN ('approve','approve_submission','accept','cancel','reject','request_changes','submit')),
            evidence_artifact_ids_json TEXT NOT NULL CHECK (json_valid(evidence_artifact_ids_json)),
            authority_basis_json TEXT NOT NULL CHECK (json_valid(authority_basis_json)),
            reason TEXT NOT NULL,
            supersedes_decision_id TEXT,
            source_event_key TEXT UNIQUE,
            created_at TEXT NOT NULL,
            FOREIGN KEY (work_item_id, task_version)
              REFERENCES task_versions(work_item_id, task_version) ON DELETE RESTRICT,
            FOREIGN KEY (supersedes_decision_id) REFERENCES decision_records(decision_id) ON DELETE RESTRICT
        )
        """,
        """
        CREATE TABLE gate_events (
            gate_event_id TEXT PRIMARY KEY,
            schema_version TEXT NOT NULL CHECK (schema_version = 'gate_event.v1'),
            work_item_id TEXT NOT NULL,
            task_version INTEGER NOT NULL CHECK (task_version >= 1),
            from_state TEXT NOT NULL,
            target_state TEXT NOT NULL,
            expected_state_version INTEGER NOT NULL CHECK (expected_state_version >= 0),
            outcome TEXT NOT NULL CHECK (outcome IN ('transition_applied','transition_rejected')),
            reason_code TEXT NOT NULL,
            decision_ids_json TEXT NOT NULL CHECK (json_valid(decision_ids_json)),
            evidence_artifact_ids_json TEXT NOT NULL CHECK (json_valid(evidence_artifact_ids_json)),
            authority_basis_json TEXT NOT NULL CHECK (json_valid(authority_basis_json)),
            command_digest TEXT NOT NULL CHECK (length(command_digest) = 64),
            preview_id TEXT NOT NULL UNIQUE,
            idempotency_key TEXT UNIQUE,
            created_at TEXT NOT NULL,
            FOREIGN KEY (work_item_id, task_version)
              REFERENCES task_versions(work_item_id, task_version) ON DELETE RESTRICT
        )
        """,
        """
        CREATE TABLE delivery_receipts (
            delivery_receipt_id TEXT PRIMARY KEY,
            schema_version TEXT NOT NULL CHECK (schema_version = 'delivery_receipt.v1'),
            work_item_id TEXT NOT NULL,
            task_version INTEGER NOT NULL CHECK (task_version >= 1),
            destination TEXT NOT NULL,
            payload_digest TEXT NOT NULL CHECK (length(payload_digest) = 64),
            status TEXT NOT NULL CHECK (status IN ('pending','retry_scheduled','delivered','acknowledged','failed')),
            attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
            last_error TEXT,
            next_attempt_at TEXT,
            idempotency_key TEXT UNIQUE,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            acknowledged_at TEXT,
            FOREIGN KEY (work_item_id, task_version)
              REFERENCES task_versions(work_item_id, task_version) ON DELETE RESTRICT
        )
        """,
        """
        CREATE TABLE audit_events (
            audit_event_id TEXT PRIMARY KEY,
            work_item_id TEXT NOT NULL,
            task_version INTEGER,
            event_type TEXT NOT NULL,
            actor_json TEXT NOT NULL CHECK (json_valid(actor_json)),
            payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
            source_event_key TEXT UNIQUE,
            created_at TEXT NOT NULL,
            FOREIGN KEY (work_item_id) REFERENCES work_items(work_item_id) ON DELETE RESTRICT
        )
        """,
        """
        CREATE TABLE outbox_events (
            outbox_event_id TEXT PRIMARY KEY,
            work_item_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            dedupe_key TEXT NOT NULL UNIQUE,
            payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
            status TEXT NOT NULL CHECK (status IN ('pending','retry_scheduled','delivered','failed','manual_recovery')),
            attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
            next_attempt_at TEXT,
            last_error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (work_item_id) REFERENCES work_items(work_item_id) ON DELETE RESTRICT
        )
        """,
        """
        CREATE TABLE inbox_events (
            inbox_event_id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            source_event_key TEXT NOT NULL,
            payload_digest TEXT NOT NULL CHECK (length(payload_digest) = 64),
            received_at TEXT NOT NULL,
            UNIQUE (source, source_event_key)
        )
        """,
        """
        CREATE TABLE blocker_events (
            blocker_event_id TEXT PRIMARY KEY,
            blocker_id TEXT NOT NULL,
            work_item_id TEXT NOT NULL,
            task_version INTEGER NOT NULL CHECK (task_version >= 1),
            event_type TEXT NOT NULL CHECK (event_type IN ('blocker_applied','blocker_cleared')),
            reason TEXT NOT NULL,
            actor_json TEXT NOT NULL CHECK (json_valid(actor_json)),
            source_event_key TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            FOREIGN KEY (work_item_id, task_version)
              REFERENCES task_versions(work_item_id, task_version) ON DELETE RESTRICT
        )
        """,
        "CREATE INDEX idx_decisions_work_item ON decision_records(work_item_id, task_version, created_at)",
        "CREATE INDEX idx_gates_work_item ON gate_events(work_item_id, created_at)",
        "CREATE INDEX idx_delivery_work_item ON delivery_receipts(work_item_id, created_at)",
        "CREATE INDEX idx_audit_work_item ON audit_events(work_item_id, created_at)",
        "CREATE INDEX idx_outbox_status ON outbox_events(status, next_attempt_at)",
        "CREATE INDEX idx_blockers_work_item ON blocker_events(work_item_id, blocker_id, created_at)",
    ]
    for table in append_only_trigger_tables:
        statements.extend(
            (
                f"CREATE TRIGGER {table}_no_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT, 'append-only table'); END",
                f"CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT, 'append-only table'); END",
            )
        )
    return tuple(statements)


def _migration_v4() -> tuple[str, ...]:
    return (
        "ALTER TABLE execution_attempts ADD COLUMN attempt_kind TEXT NOT NULL DEFAULT 'runtime' "
        "CHECK (attempt_kind IN ('runtime','historical'))",
        "ALTER TABLE execution_attempts ADD COLUMN dispatch_authorized INTEGER NOT NULL DEFAULT 1 "
        "CHECK (dispatch_authorized IN (0,1))",
        "ALTER TABLE execution_attempts ADD COLUMN historical_reason TEXT",
        "ALTER TABLE execution_attempts ADD COLUMN imported INTEGER NOT NULL DEFAULT 0 CHECK (imported IN (0,1))",
        "ALTER TABLE decision_records ADD COLUMN principal_json TEXT NOT NULL DEFAULT '{}' "
        "CHECK (json_valid(principal_json))",
        "ALTER TABLE gate_events ADD COLUMN principal_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(principal_json))",
        "ALTER TABLE gate_events ADD COLUMN transition_result TEXT NOT NULL DEFAULT 'state_advanced' "
        "CHECK (transition_result IN ('state_advanced','returned_for_revision'))",
        """
        CREATE TABLE acceptance_manifests (
            acceptance_manifest_id TEXT PRIMARY KEY,
            schema_version TEXT NOT NULL CHECK (schema_version = 'acceptance_evidence_manifest.v1'),
            work_item_id TEXT NOT NULL UNIQUE,
            task_version INTEGER NOT NULL CHECK (task_version >= 1),
            gate_event_id TEXT NOT NULL UNIQUE,
            accepted_state_version INTEGER NOT NULL CHECK (accepted_state_version >= 1),
            artifact_ids_json TEXT NOT NULL CHECK (json_valid(artifact_ids_json)),
            artifact_manifest_json TEXT NOT NULL CHECK (json_valid(artifact_manifest_json)),
            artifact_manifest_digest TEXT NOT NULL CHECK (length(artifact_manifest_digest) = 64),
            decision_ids_json TEXT NOT NULL CHECK (json_valid(decision_ids_json)),
            principal_json TEXT NOT NULL CHECK (json_valid(principal_json)),
            created_at TEXT NOT NULL,
            FOREIGN KEY (work_item_id, task_version)
              REFERENCES task_versions(work_item_id, task_version) ON DELETE RESTRICT,
            FOREIGN KEY (gate_event_id) REFERENCES gate_events(gate_event_id) ON DELETE RESTRICT
        )
        """,
        "CREATE INDEX idx_acceptance_manifest_gate ON acceptance_manifests(gate_event_id)",
        "CREATE TRIGGER acceptance_manifests_no_update BEFORE UPDATE ON acceptance_manifests "
        "BEGIN SELECT RAISE(ABORT, 'append-only table'); END",
        "CREATE TRIGGER acceptance_manifests_no_delete BEFORE DELETE ON acceptance_manifests "
        "BEGIN SELECT RAISE(ABORT, 'append-only table'); END",
        "INSERT OR IGNORE INTO ledger_meta(key,value,updated_at) "
        "VALUES('database_generation','1',strftime('%Y-%m-%dT%H:%M:%fZ','now'))",
    )


def _migration_v5() -> tuple[str, ...]:
    return (
        """
        CREATE TABLE activation_leases (
            lease_id TEXT PRIMARY KEY,
            schema_version TEXT NOT NULL CHECK (schema_version = 'work_item_activation_lease.v1'),
            authorization_id TEXT NOT NULL UNIQUE,
            authorization_digest TEXT NOT NULL CHECK (length(authorization_digest) = 64),
            activation_envelope_digest TEXT NOT NULL CHECK (length(activation_envelope_digest) = 64),
            spec_manifest_digest TEXT NOT NULL CHECK (length(spec_manifest_digest) = 64),
            expected_process_identity TEXT NOT NULL CHECK (length(expected_process_identity) = 64),
            claimed_process_identity TEXT,
            listener_attested_at TEXT,
            listener_attestation_digest TEXT,
            request_context_binding_digest TEXT,
            monotonic_claim_ns INTEGER,
            monotonic_deadline_ns INTEGER,
            not_before TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            maximum_runtime_seconds INTEGER NOT NULL CHECK (maximum_runtime_seconds = 1800),
            authorized_work_item_id TEXT,
            source_binding_json TEXT NOT NULL CHECK (json_valid(source_binding_json)),
            runtime_binding_json TEXT NOT NULL CHECK (json_valid(runtime_binding_json)),
            principal_binding_json TEXT NOT NULL CHECK (json_valid(principal_binding_json)),
            bootstrap_json TEXT NOT NULL CHECK (json_valid(bootstrap_json)),
            scope_json TEXT NOT NULL CHECK (json_valid(scope_json)),
            fixture_json TEXT NOT NULL CHECK (json_valid(fixture_json)),
            fixture_bindings_json TEXT NOT NULL CHECK (json_valid(fixture_bindings_json)),
            quotas_json TEXT NOT NULL CHECK (json_valid(quotas_json)),
            usage_json TEXT NOT NULL CHECK (json_valid(usage_json)),
            policy_json TEXT NOT NULL CHECK (json_valid(policy_json)),
            maintenance_json TEXT NOT NULL CHECK (json_valid(maintenance_json)),
            failure_behavior_json TEXT NOT NULL CHECK (json_valid(failure_behavior_json)),
            status TEXT NOT NULL CHECK (
              status IN ('prepared','claimed','active','write_frozen','expired','closed','revoked')
            ),
            state_version INTEGER NOT NULL CHECK (state_version >= 0),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (authorized_work_item_id) REFERENCES work_items(work_item_id) ON DELETE RESTRICT,
            CHECK (claimed_process_identity IS NULL OR length(claimed_process_identity) = 64),
            CHECK (listener_attestation_digest IS NULL OR length(listener_attestation_digest) = 64),
            CHECK (request_context_binding_digest IS NULL OR length(request_context_binding_digest) = 64),
            CHECK (monotonic_claim_ns IS NULL OR monotonic_claim_ns >= 0),
            CHECK (monotonic_deadline_ns IS NULL OR monotonic_deadline_ns > 0)
        )
        """,
        """
        CREATE TABLE activation_lease_events (
            lease_event_id TEXT PRIMARY KEY,
            schema_version TEXT NOT NULL CHECK (schema_version = 'work_item_activation_lease_event.v1'),
            lease_id TEXT NOT NULL,
            sequence INTEGER NOT NULL CHECK (sequence BETWEEN 1 AND 40),
            event_type TEXT NOT NULL CHECK (
              event_type IN (
                'lease_issued','process_claimed','listener_attested','command_committed',
                'domain_rejected','lease_write_frozen','lease_expired','lease_closed','lease_revoked'
              )
            ),
            status_before TEXT,
            status_after TEXT NOT NULL,
            state_version_before INTEGER NOT NULL CHECK (state_version_before >= 0),
            state_version_after INTEGER NOT NULL CHECK (state_version_after >= 0),
            claimed_process_identity TEXT,
            listener_attestation_digest TEXT,
            request_context_binding_digest TEXT,
            command_name TEXT,
            source_event_key_digest TEXT,
            domain_fact_delta_digest TEXT,
            principal_binding_digest TEXT,
            reason_code TEXT,
            previous_event_digest TEXT,
            event_digest TEXT NOT NULL CHECK (length(event_digest) = 64),
            event_json TEXT NOT NULL CHECK (json_valid(event_json)),
            created_at TEXT NOT NULL,
            UNIQUE (lease_id, sequence),
            UNIQUE (lease_id, source_event_key_digest),
            FOREIGN KEY (lease_id) REFERENCES activation_leases(lease_id) ON DELETE RESTRICT,
            CHECK (claimed_process_identity IS NULL OR length(claimed_process_identity) = 64),
            CHECK (listener_attestation_digest IS NULL OR length(listener_attestation_digest) = 64),
            CHECK (request_context_binding_digest IS NULL OR length(request_context_binding_digest) = 64),
            CHECK (source_event_key_digest IS NULL OR length(source_event_key_digest) = 64),
            CHECK (domain_fact_delta_digest IS NULL OR length(domain_fact_delta_digest) = 64),
            CHECK (principal_binding_digest IS NULL OR length(principal_binding_digest) = 64),
            CHECK (previous_event_digest IS NULL OR length(previous_event_digest) = 64)
        )
        """,
        "CREATE UNIQUE INDEX idx_activation_single_live_lease "
        "ON activation_leases((1)) WHERE status IN ('claimed','active','write_frozen')",
        "CREATE INDEX idx_activation_lease_status ON activation_leases(status, updated_at)",
        "CREATE INDEX idx_activation_events_lease ON activation_lease_events(lease_id, sequence)",
        "CREATE TRIGGER activation_lease_events_no_update BEFORE UPDATE ON activation_lease_events "
        "BEGIN SELECT RAISE(ABORT, 'append-only table'); END",
        "CREATE TRIGGER activation_lease_events_no_delete BEFORE DELETE ON activation_lease_events "
        "BEGIN SELECT RAISE(ABORT, 'append-only table'); END",
    )


def _migration_v6() -> tuple[str, ...]:
    """Add the bounded single-project Pilot authority domain.

    The accepted v5 Canary tables remain byte-semantically untouched.  Pilot
    leases use separate tables because their four-hour window, 64-event chain,
    typed execution-slot binding, and v4 event contract cannot be represented
    truthfully by the v5 constraints.
    """

    return (
        """
        CREATE TABLE pilot_activation_leases (
            lease_id TEXT PRIMARY KEY,
            schema_version TEXT NOT NULL CHECK (
              schema_version='wig_p3_bounded_single_project_pilot_activation_lease.v4'
            ),
            authorization_id TEXT NOT NULL UNIQUE,
            authorization_digest TEXT NOT NULL CHECK (length(authorization_digest)=64),
            scope_envelope_digest TEXT NOT NULL CHECK (length(scope_envelope_digest)=64),
            spec_manifest_digest TEXT NOT NULL CHECK (length(spec_manifest_digest)=64),
            storage_schema_contract_digest TEXT NOT NULL CHECK (length(storage_schema_contract_digest)=64),
            fact_reconciliation_contract_digest TEXT NOT NULL CHECK (length(fact_reconciliation_contract_digest)=64),
            semantic_rules_digest TEXT NOT NULL CHECK (length(semantic_rules_digest)=64),
            tool_allowlist_digest TEXT NOT NULL CHECK (length(tool_allowlist_digest)=64),
            write_matrix_digest TEXT NOT NULL CHECK (length(write_matrix_digest)=64),
            execution_attempt_slot_schema_sha256 TEXT NOT NULL CHECK (length(execution_attempt_slot_schema_sha256)=64),
            execution_authorization_receipt_schema_sha256 TEXT NOT NULL CHECK (length(execution_authorization_receipt_schema_sha256)=64),
            authentication_conformance_receipt_schema_sha256 TEXT NOT NULL CHECK (length(authentication_conformance_receipt_schema_sha256)=64),
            expiry_conformance_receipt_schema_sha256 TEXT NOT NULL CHECK (length(expiry_conformance_receipt_schema_sha256)=64),
            authorized_work_item_id TEXT,
            source_binding_json TEXT NOT NULL CHECK (json_valid(source_binding_json)),
            runtime_binding_json TEXT NOT NULL CHECK (json_valid(runtime_binding_json)),
            principal_binding_json TEXT NOT NULL CHECK (json_valid(principal_binding_json)),
            scope_binding_json TEXT NOT NULL CHECK (json_valid(scope_binding_json)),
            issued_at TEXT NOT NULL,
            not_before TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            maximum_runtime_seconds INTEGER NOT NULL CHECK (maximum_runtime_seconds=14400),
            quotas_json TEXT NOT NULL CHECK (json_valid(quotas_json)),
            usage_json TEXT NOT NULL CHECK (json_valid(usage_json)),
            policy_json TEXT NOT NULL CHECK (json_valid(policy_json)),
            maintenance_json TEXT NOT NULL CHECK (json_valid(maintenance_json)),
            failure_behavior_json TEXT NOT NULL CHECK (json_valid(failure_behavior_json)),
            status TEXT NOT NULL CHECK (
              status IN ('prepared','claimed','active','write_frozen','expired','closed','revoked')
            ),
            state_version INTEGER NOT NULL CHECK (state_version>=1),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (authorized_work_item_id)
              REFERENCES work_items(work_item_id) ON DELETE RESTRICT
        )
        """,
        """
        CREATE TABLE pilot_activation_lease_events (
            lease_event_id TEXT PRIMARY KEY,
            schema_version TEXT NOT NULL CHECK (
              schema_version='wig_p3_bounded_single_project_pilot_activation_lease_event.v4'
            ),
            lease_id TEXT NOT NULL,
            sequence INTEGER NOT NULL CHECK (sequence BETWEEN 1 AND 64),
            event_type TEXT NOT NULL CHECK (
              event_type IN (
                'lease_issued','process_claimed','listener_attested','command_committed',
                'domain_rejected','lease_write_frozen','lease_expired','lease_closed','lease_revoked'
              )
            ),
            status_before TEXT,
            status_after TEXT NOT NULL,
            state_version_before INTEGER NOT NULL CHECK (state_version_before>=0),
            state_version_after INTEGER NOT NULL CHECK (state_version_after>=1),
            authorization_digest TEXT NOT NULL CHECK (length(authorization_digest)=64),
            authorized_work_item_id TEXT,
            process_identity_digest TEXT,
            listener_attestation_digest TEXT,
            command_name TEXT,
            source_event_key_digest TEXT,
            request_context_digest TEXT,
            principal_digest TEXT,
            fact_delta_json TEXT NOT NULL CHECK (json_valid(fact_delta_json)),
            rejection_code TEXT,
            previous_event_digest TEXT,
            event_digest TEXT NOT NULL CHECK (length(event_digest)=64),
            event_json TEXT NOT NULL CHECK (json_valid(event_json)),
            created_at TEXT NOT NULL,
            UNIQUE (lease_id,sequence),
            UNIQUE (lease_id,source_event_key_digest),
            FOREIGN KEY (lease_id)
              REFERENCES pilot_activation_leases(lease_id) ON DELETE RESTRICT
        )
        """,
        "CREATE UNIQUE INDEX idx_pilot_activation_single_live_lease "
        "ON pilot_activation_leases((1)) WHERE status IN ('claimed','active','write_frozen')",
        "CREATE INDEX idx_pilot_activation_lease_status "
        "ON pilot_activation_leases(status,updated_at)",
        "CREATE INDEX idx_pilot_activation_events_lease "
        "ON pilot_activation_lease_events(lease_id,sequence)",
        "CREATE TRIGGER pilot_activation_lease_events_no_update "
        "BEFORE UPDATE ON pilot_activation_lease_events "
        "BEGIN SELECT RAISE(ABORT,'append-only table'); END",
        "CREATE TRIGGER pilot_activation_lease_events_no_delete "
        "BEFORE DELETE ON pilot_activation_lease_events "
        "BEGIN SELECT RAISE(ABORT,'append-only table'); END",
    )


def _migration_v7() -> tuple[str, ...]:
    """Add durable, append-only Pilot authorization issuance and claim facts."""

    return (
        """
        CREATE TABLE pilot_authorization_facts (
            authorization_digest TEXT PRIMARY KEY CHECK (length(authorization_digest)=64),
            schema_version TEXT NOT NULL CHECK (
              schema_version='wig_p3_pilot_persisted_authority.v2'
            ),
            tombstone_digest TEXT NOT NULL CHECK (length(tombstone_digest)=64),
            tombstone_path_digest TEXT NOT NULL CHECK (length(tombstone_path_digest)=64),
            payload_digest TEXT NOT NULL CHECK (length(payload_digest)=64),
            issued_record_json TEXT NOT NULL CHECK (json_valid(issued_record_json)),
            issued_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE pilot_authorization_claims (
            authorization_digest TEXT PRIMARY KEY,
            schema_version TEXT NOT NULL CHECK (
              schema_version='wig_p3_pilot_authorization_claim.v1'
            ),
            claim_digest TEXT NOT NULL UNIQUE CHECK (length(claim_digest)=64),
            claimed_at TEXT NOT NULL,
            FOREIGN KEY (authorization_digest)
              REFERENCES pilot_authorization_facts(authorization_digest) ON DELETE RESTRICT
        )
        """,
        "CREATE TRIGGER pilot_authorization_facts_no_update "
        "BEFORE UPDATE ON pilot_authorization_facts "
        "BEGIN SELECT RAISE(ABORT,'append-only table'); END",
        "CREATE TRIGGER pilot_authorization_facts_no_delete "
        "BEFORE DELETE ON pilot_authorization_facts "
        "BEGIN SELECT RAISE(ABORT,'append-only table'); END",
        "CREATE TRIGGER pilot_authorization_claims_no_update "
        "BEFORE UPDATE ON pilot_authorization_claims "
        "BEGIN SELECT RAISE(ABORT,'append-only table'); END",
        "CREATE TRIGGER pilot_authorization_claims_no_delete "
        "BEFORE DELETE ON pilot_authorization_claims "
        "BEGIN SELECT RAISE(ABORT,'append-only table'); END",
    )


MIGRATIONS: dict[int, tuple[str, ...]] = {
    1: _migration_v1(),
    2: _migration_v2(),
    3: _migration_v3(),
    4: _migration_v4(),
    5: _migration_v5(),
    6: _migration_v6(),
    7: _migration_v7(),
}


class SQLiteWorkItemLedger:
    """Project-local durable SQLite repository.

    Connections are short lived.  Every write caller receives an explicit
    `BEGIN IMMEDIATE` transaction; the repository never exposes a connection to
    side-context modules.
    """

    def __init__(
        self,
        project_root: str | os.PathLike[str],
        *,
        busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
        migrations: dict[int, Sequence[str]] | None = None,
        target_schema_version: int = 5,
    ) -> None:
        self.project_root = Path(project_root).expanduser().resolve()
        self.path = self.project_root.joinpath(*LEDGER_RELATIVE_PATH.split("/"))
        self.maintenance_lock_path = self.path.parent / "work-items.restore.lock"
        self.busy_timeout_ms = max(1, int(busy_timeout_ms))
        self._migrations = dict(migrations or MIGRATIONS)
        if target_schema_version not in {5, 6, 7}:
            raise ValueError("target_schema_version must be 5, 6 or 7")
        self.target_schema_version = target_schema_version
        self._activation_transaction_states: dict[int, dict[str, Any]] = {}
        self.__write_connection_authority = object()
        self.__control_write_session_seal = secrets.token_bytes(32)
        self.__controller_binding_seal = secrets.token_bytes(32)
        self.__issued_control_write_sessions: dict[
            int, _ActivationControlWriteSession
        ] = {}
        self.__issued_controller_bindings: dict[int, _ActivationControllerBinding] = {}

    def _ensure_storage_path(self) -> None:
        if not self.project_root.is_dir():
            raise WorkItemGovernanceError(
                "PROJECT_ROOT_INVALID",
                "Project root must be an existing directory.",
                details={"project_root": str(self.project_root)},
            )
        runner_dir = self.project_root / ".colameta"
        if runner_dir.is_symlink():
            raise WorkItemGovernanceError(
                "LEDGER_PATH_UNSAFE",
                "The .colameta directory must not be a symbolic link.",
            )
        runner_dir.mkdir(mode=0o700, exist_ok=True)
        ledger_dir = runner_dir / "ledger"
        if ledger_dir.is_symlink():
            raise WorkItemGovernanceError("LEDGER_PATH_UNSAFE", "Ledger directory must not be a symbolic link.")
        ledger_dir.mkdir(mode=0o700, exist_ok=True)
        resolved_parent = ledger_dir.resolve()
        try:
            resolved_parent.relative_to(self.project_root)
        except ValueError as exc:
            raise WorkItemGovernanceError(
                "LEDGER_PATH_OUTSIDE_PROJECT",
                "Ledger path must remain under the project root.",
            ) from exc
        if self.path.is_symlink():
            raise WorkItemGovernanceError(
                "LEDGER_PATH_UNSAFE",
                "Ledger database must not be a symbolic link.",
            )
        os.chmod(ledger_dir, 0o700)

    def _assert_existing_storage_path(self) -> None:
        """Validate the Ledger path without creating or chmodding anything."""

        if not self.project_root.is_dir():
            raise WorkItemGovernanceError(
                "PROJECT_ROOT_INVALID",
                "Project root must be an existing directory.",
                details={"project_root": str(self.project_root)},
            )
        runner_dir = self.project_root / ".colameta"
        if runner_dir.is_symlink():
            raise WorkItemGovernanceError(
                "LEDGER_PATH_UNSAFE",
                "The .colameta directory must not be a symbolic link.",
            )
        ledger_dir = runner_dir / "ledger"
        if ledger_dir.is_symlink():
            raise WorkItemGovernanceError("LEDGER_PATH_UNSAFE", "Ledger directory must not be a symbolic link.")
        if not ledger_dir.is_dir():
            raise WorkItemGovernanceError(
                "LEDGER_FILE_MISSING",
                "Ledger database file does not exist.",
                details={"path": str(self.path)},
            )
        try:
            ledger_dir.resolve().relative_to(self.project_root)
        except ValueError as exc:
            raise WorkItemGovernanceError(
                "LEDGER_PATH_OUTSIDE_PROJECT",
                "Ledger path must remain under the project root.",
            ) from exc
        if self.path.is_symlink():
            raise WorkItemGovernanceError(
                "LEDGER_PATH_UNSAFE",
                "Ledger database must not be a symbolic link.",
            )

    @contextmanager
    def _maintenance_lock(
        self,
        *,
        exclusive: bool,
        blocking: bool = True,
        create: bool = True,
    ) -> Iterator[None]:
        if create:
            self._ensure_storage_path()
        else:
            self._assert_existing_storage_path()
        if self.maintenance_lock_path.is_symlink():
            raise WorkItemGovernanceError(
                "LEDGER_PATH_UNSAFE",
                "Ledger maintenance lock must not be a symbolic link.",
            )
        flags = os.O_CREAT | os.O_RDWR if create else os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(self.maintenance_lock_path, flags, 0o600)
        except FileNotFoundError as exc:
            raise WorkItemGovernanceError(
                "LEDGER_MAINTENANCE_LOCK_MISSING",
                "Ledger reads require the maintenance lock provisioned by explicit bootstrap.",
                details={"path": str(self.maintenance_lock_path)},
            ) from exc
        if create:
            os.chmod(self.maintenance_lock_path, 0o600)
        operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        if not blocking:
            operation |= fcntl.LOCK_NB
        try:
            try:
                fcntl.flock(descriptor, operation)
            except BlockingIOError as exc:
                raise WorkItemGovernanceError(
                    "LEDGER_RESTORE_ACTIVE_CONNECTIONS",
                    "Restore requires all Ledger readers, writers, and outbox dispatchers to drain.",
                    details={"lock_path": str(self.maintenance_lock_path)},
                ) from exc
            yield
        finally:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)

    @contextmanager
    def frozen_storage_boundary(self) -> Iterator[None]:
        """Freeze an existing Ledger for raw-byte snapshotting without opening SQLite.

        The existing maintenance lock is opened read-only and held exclusively.
        Repository-owned readers and writers therefore drain before the caller
        measures or copies bytes, while this boundary itself creates and chmods
        nothing under the protected Ledger root.
        """

        self._assert_existing_storage_path()
        if not self.path.is_file():
            raise WorkItemGovernanceError(
                "LEDGER_FILE_MISSING",
                "Ledger database file does not exist.",
                details={"path": str(self.path)},
            )
        with self._maintenance_lock(exclusive=True, blocking=False, create=False):
            yield

    def _connect(
        self,
        path: Path | None = None,
        *,
        readonly: bool = True,
        _write_authority: object | None = None,
    ) -> sqlite3.Connection:
        if not readonly and _write_authority is not self.__write_connection_authority:
            raise WorkItemGovernanceError(
                "LEDGER_WRITABLE_CONNECTION_DENIED",
                "Writable Ledger connections are available only inside repository-owned transactions.",
            )
        target = path or self.path
        if readonly:
            connection = sqlite3.connect(
                f"file:{target}?mode=ro",
                uri=True,
                timeout=self.busy_timeout_ms / 1000,
                isolation_level=None,
            )
        else:
            connection = sqlite3.connect(
                str(target),
                timeout=self.busy_timeout_ms / 1000,
                isolation_level=None,
            )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
        if not readonly:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
        return connection

    def initialize(self) -> None:
        with self._maintenance_lock(exclusive=False):
            self._initialize_unlocked()

    def _initialize_unlocked(self) -> None:
        self._ensure_storage_path()
        connection = self._connect(
            readonly=False,
            _write_authority=self.__write_connection_authority,
        )
        try:
            current = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if current > CURRENT_LEDGER_SCHEMA_VERSION:
                raise WorkItemGovernanceError(
                    "LEDGER_SCHEMA_TOO_NEW",
                    "Ledger schema is newer than this ColaMeta build.",
                    details={"current": current, "supported": CURRENT_LEDGER_SCHEMA_VERSION},
                )
            if current < 6 and self.target_schema_version >= 6:
                raise WorkItemGovernanceError(
                    "PILOT_EXPLICIT_MIGRATION_REQUIRED",
                    "Any schema transition into v6 requires the explicit atomic Pilot migration wrapper.",
                    details={"current": current, "target": self.target_schema_version},
                )
            if current == 6 and self.target_schema_version >= 7:
                raise WorkItemGovernanceError(
                    "PILOT_AUTHORITY_EXPLICIT_MIGRATION_REQUIRED",
                    "Schema v6 to v7 requires the explicit atomic authorization-fact migration wrapper.",
                    details={"current": current, "target": self.target_schema_version},
                )
            while current < self.target_schema_version:
                target = current + 1
                statements = self._migrations.get(target)
                if not statements:
                    raise WorkItemGovernanceError(
                        "LEDGER_MIGRATION_MISSING",
                        "Required forward Ledger migration is missing.",
                        details={"from_version": current, "target_version": target},
                    )
                connection.execute("BEGIN IMMEDIATE")
                try:
                    locked_current = int(connection.execute("PRAGMA user_version").fetchone()[0])
                    if locked_current != current:
                        connection.rollback()
                        current = locked_current
                        continue
                    for statement in statements:
                        connection.execute(statement)
                    connection.execute(f"PRAGMA user_version={target}")
                    if target == 1:
                        connection.execute(
                            "INSERT INTO ledger_meta(key,value,updated_at) VALUES('schema_version',?,strftime('%Y-%m-%dT%H:%M:%fZ','now'))",
                            (str(target),),
                        )
                    else:
                        connection.execute(
                            "UPDATE ledger_meta SET value=?, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE key='schema_version'",
                            (str(target),),
                        )
                    connection.commit()
                    current = target
                except Exception as exc:
                    connection.rollback()
                    if isinstance(exc, WorkItemGovernanceError):
                        raise
                    raise WorkItemGovernanceError(
                        "LEDGER_MIGRATION_FAILED",
                        "Ledger migration failed and was rolled back.",
                        details={"target_version": target, "reason": str(exc)},
                    ) from exc
        finally:
            connection.close()
        os.chmod(self.path, 0o600)

    @contextmanager
    def write_transaction(
        self,
    ) -> Iterator[sqlite3.Connection]:
        with self._maintenance_lock(exclusive=False):
            self._initialize_unlocked()
            connection = self._connect(
                readonly=False,
                _write_authority=self.__write_connection_authority,
            )
            connection.execute("BEGIN IMMEDIATE")
            legacy_lease = connection.execute(
                "SELECT lease_id,status FROM activation_leases ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            schema_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            pilot_lease = (
                connection.execute(
                    "SELECT lease_id,status FROM pilot_activation_leases ORDER BY created_at DESC LIMIT 1"
                ).fetchone()
                if schema_version >= 6
                else None
            )
            canary_marked = load_work_item_governance_settings(
                self.project_root
            ).authoritative_canary
            activation_managed = (
                canary_marked
                or schema_version >= 6
                or legacy_lease is not None
                or pilot_lease is not None
            )
            restricted = activation_managed
            transaction_state: dict[str, Any] | None = None
            if restricted:
                # Fresh Preflight provisions public binding metadata before its
                # first Lease is prepared.  Once a Lease exists, ledger_meta is
                # immutable through the default repository transaction.
                allowed_default_tables: set[str] = set()
                if legacy_lease is None and pilot_lease is None:
                    allowed_default_tables.add("ledger_meta")
                transaction_state = {
                    "connection": connection,
                    "domain_write_authorized": False,
                    "allowed_default_tables": frozenset(allowed_default_tables),
                    "control_write_authorized": False,
                    "authorized_control_tables": frozenset(),
                    "authorized_session": None,
                    "finalized_session": None,
                    "authorized_control_session": None,
                    "finalized_control_session": None,
                }
                self._activation_transaction_states[id(connection)] = transaction_state
                authorizer = self._activation_repository_authorizer(transaction_state)
                transaction_state["authorizer"] = authorizer
                connection.set_authorizer(authorizer)
            try:
                yield connection
                if transaction_state is not None:
                    self._assert_managed_transaction_finalized(transaction_state)
                connection.commit()
            except CommitWorkItemRejection as exc:
                if transaction_state is not None:
                    try:
                        self._assert_managed_transaction_finalized(transaction_state)
                    except Exception:
                        connection.rollback()
                        raise
                connection.commit()
                raise exc.error from exc
            except sqlite3.DatabaseError as exc:
                connection.rollback()
                if restricted and "not authorized" in str(exc).lower():
                    raise WorkItemGovernanceError(
                        "ACTIVATION_REPOSITORY_WRITE_DENIED",
                        "An activation-managed Ledger rejects raw repository domain or maintenance writes.",
                    ) from exc
                raise
            except Exception:
                connection.rollback()
                raise
            finally:
                if transaction_state is not None:
                    control_session = transaction_state.get("authorized_control_session")
                    if (
                        control_session is not None
                        and self.__issued_control_write_sessions.get(id(control_session))
                        is control_session
                    ):
                        self.__issued_control_write_sessions.pop(id(control_session), None)
                self._activation_transaction_states.pop(id(connection), None)
                connection.close()
                if self.path.exists():
                    os.chmod(self.path, 0o600)

    @staticmethod
    def _activation_repository_authorizer(
        transaction_state: dict[str, Any],
    ) -> Any:
        data_write_actions = {
            sqlite3.SQLITE_INSERT,
            sqlite3.SQLITE_UPDATE,
            sqlite3.SQLITE_DELETE,
        }
        structural_write_actions = {
            sqlite3.SQLITE_ALTER_TABLE,
            sqlite3.SQLITE_ANALYZE,
            sqlite3.SQLITE_ATTACH,
            sqlite3.SQLITE_CREATE_INDEX,
            sqlite3.SQLITE_CREATE_TABLE,
            sqlite3.SQLITE_CREATE_TEMP_INDEX,
            sqlite3.SQLITE_CREATE_TEMP_TABLE,
            sqlite3.SQLITE_CREATE_TEMP_TRIGGER,
            sqlite3.SQLITE_CREATE_TEMP_VIEW,
            sqlite3.SQLITE_CREATE_TRIGGER,
            sqlite3.SQLITE_CREATE_VIEW,
            sqlite3.SQLITE_DETACH,
            sqlite3.SQLITE_DROP_INDEX,
            sqlite3.SQLITE_DROP_TABLE,
            sqlite3.SQLITE_DROP_TEMP_INDEX,
            sqlite3.SQLITE_DROP_TEMP_TABLE,
            sqlite3.SQLITE_DROP_TEMP_TRIGGER,
            sqlite3.SQLITE_DROP_TEMP_VIEW,
            sqlite3.SQLITE_DROP_TRIGGER,
            sqlite3.SQLITE_DROP_VIEW,
            sqlite3.SQLITE_PRAGMA,
            sqlite3.SQLITE_REINDEX,
        }

        def authorize(
            action: int,
            argument_one: str | None,
            _argument_two: str | None,
            _database: str | None,
            _trigger: str | None,
        ) -> int:
            if action in data_write_actions:
                if transaction_state["domain_write_authorized"]:
                    return sqlite3.SQLITE_OK
                if (
                    transaction_state["control_write_authorized"]
                    and argument_one in transaction_state["authorized_control_tables"]
                ):
                    return sqlite3.SQLITE_OK
                return (
                    sqlite3.SQLITE_OK
                    if argument_one in transaction_state["allowed_default_tables"]
                    else sqlite3.SQLITE_DENY
                )
            if action in structural_write_actions:
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        return authorize

    @staticmethod
    def _refresh_managed_authorizer(
        connection: sqlite3.Connection,
        transaction_state: dict[str, Any],
    ) -> None:
        """Invalidate SQLite's prepared-statement authorization cache.

        SQLite invokes an authorizer while compiling a statement, not on every
        execution of a cached statement.  Every capability transition therefore
        reinstalls the callback so a statement compiled while unlocked cannot
        be replayed after relock.
        """

        connection.set_authorizer(None)
        connection.set_authorizer(transaction_state["authorizer"])

    @staticmethod
    def _assert_managed_transaction_finalized(transaction_state: dict[str, Any]) -> None:
        domain_session = transaction_state.get("authorized_session")
        if (
            transaction_state.get("domain_write_authorized") is True
            or (
                domain_session is not None
                and transaction_state.get("finalized_session") is not domain_session
            )
        ):
            raise WorkItemGovernanceError(
                "ACTIVATION_REPOSITORY_WRITE_NOT_FINALIZED",
                "Repository domain-write authority must be finalized before commit.",
            )
        control_session = transaction_state.get("authorized_control_session")
        if (
            transaction_state.get("control_write_authorized") is True
            or (
                control_session is not None
                and transaction_state.get("finalized_control_session")
                is not control_session
            )
        ):
            raise WorkItemGovernanceError(
                "ACTIVATION_CONTROL_WRITE_NOT_FINALIZED",
                "Repository control-write authority must be finalized before commit.",
            )

    def _bind_activation_controller(self, controller: Any) -> _ActivationControllerBinding:
        """Bind one exact controller; the capability is retained by that controller only."""

        from runner.work_item_governance.activation import (
            ActivationLeaseControlPlane,
            AuthoritativeCanaryGuard,
        )
        from runner.work_item_governance.pilot import (
            PilotActivationControlPlane,
            PilotActivationGuard,
        )
        from runner.work_item_governance.pilot_authorization import (
            _PilotAuthorizationPersistenceController,
            _is_issued_pilot_authorization_persistence_controller,
        )

        if (
            type(controller) not in {
                ActivationLeaseControlPlane,
                AuthoritativeCanaryGuard,
                PilotActivationControlPlane,
                PilotActivationGuard,
                _PilotAuthorizationPersistenceController,
            }
            or getattr(controller, "ledger", None) is not self
            or (
                type(controller) is _PilotAuthorizationPersistenceController
                and not _is_issued_pilot_authorization_persistence_controller(controller)
            )
            or id(controller) in self.__issued_controller_bindings
        ):
            raise WorkItemGovernanceError(
                "ACTIVATION_CONTROLLER_BINDING_INVALID",
                "Activation controller binding requires one unbound exact controller instance.",
            )
        binding = _ActivationControllerBinding(
            ledger=self,
            controller=controller,
            seal=self.__controller_binding_seal,
        )
        self.__issued_controller_bindings[id(controller)] = binding
        return binding

    def _release_activation_controller(self, controller: Any, binding: Any) -> None:
        if not self._is_issued_controller_binding(controller, binding):
            raise WorkItemGovernanceError(
                "ACTIVATION_CONTROLLER_BINDING_INVALID",
                "Only the exact issued controller binding can be released.",
            )
        self.__issued_controller_bindings.pop(id(controller), None)

    def _is_issued_controller_binding(
        self,
        controller: Any,
        binding: Any,
    ) -> bool:
        return bool(
            type(binding) is _ActivationControllerBinding
            and binding.ledger is self
            and binding.controller is controller
            and isinstance(binding._seal, bytes)
            and secrets.compare_digest(binding._seal, self.__controller_binding_seal)
            and self.__issued_controller_bindings.get(id(controller)) is binding
        )

    def authorize_activation_control_write(
        self,
        connection: sqlite3.Connection,
        *,
        controller: Any,
        controller_binding: Any,
    ) -> _ActivationControlWriteSession:
        """Mint authority for one exact Lease-control transaction.

        Only the two activation-domain controllers may request this authority.
        The returned session is bound to the exact Repository, connection, and
        controller object and must be finalized before the transaction commits.
        """

        # Local import avoids the repository/activation module import cycle.
        from runner.work_item_governance.activation import (
            ActivationLeaseControlPlane,
            AuthoritativeCanaryGuard,
        )
        from runner.work_item_governance.pilot import (
            PilotActivationControlPlane,
            PilotActivationGuard,
        )
        from runner.work_item_governance.pilot_authorization import (
            _PilotAuthorizationPersistenceController,
            _is_issued_pilot_authorization_persistence_controller,
            _pilot_authorization_persistence_controller_table,
        )

        state = self._activation_transaction_states.get(id(connection))
        trusted_controller = type(controller) in {
            ActivationLeaseControlPlane,
            AuthoritativeCanaryGuard,
            PilotActivationControlPlane,
            PilotActivationGuard,
            _PilotAuthorizationPersistenceController,
        }
        if (
            state is None
            or state.get("connection") is not connection
            or not trusted_controller
            or getattr(controller, "ledger", None) is not self
            or (
                type(controller) is _PilotAuthorizationPersistenceController
                and not _is_issued_pilot_authorization_persistence_controller(controller)
            )
            or not self._is_issued_controller_binding(controller, controller_binding)
            or state.get("domain_write_authorized") is True
            or (
                state.get("authorized_session") is not None
                and state.get("finalized_session") is not state.get("authorized_session")
            )
            or state.get("control_write_authorized") is True
            or (
                state.get("authorized_control_session") is not None
                and state.get("finalized_control_session")
                is not state.get("authorized_control_session")
            )
        ):
            raise WorkItemGovernanceError(
                "ACTIVATION_CONTROL_CAPABILITY_INVALID",
                "Lease-control writes require the exact activation controller and managed transaction.",
            )
        previous_control_session = state.get("authorized_control_session")
        if (
            previous_control_session is not None
            and state.get("finalized_control_session") is previous_control_session
        ):
            self.__issued_control_write_sessions.pop(
                id(previous_control_session),
                None,
            )
        session = _ActivationControlWriteSession(
            ledger=self,
            connection=connection,
            controller=controller,
            seal=self.__control_write_session_seal,
        )
        self.__issued_control_write_sessions[id(session)] = session
        state["control_write_authorized"] = True
        pilot_controller = type(controller) in {
            PilotActivationControlPlane,
            PilotActivationGuard,
        }
        if type(controller) is _PilotAuthorizationPersistenceController:
            authorized_table = _pilot_authorization_persistence_controller_table(controller)
            if authorized_table is None:
                raise WorkItemGovernanceError(
                    "ACTIVATION_CONTROL_CAPABILITY_INVALID",
                    "Pilot authorization persistence controller is not issued or is already consumed.",
                )
            authorized_tables = {authorized_table}
        elif pilot_controller:
            authorized_tables = {
                "pilot_activation_leases",
                "pilot_activation_lease_events",
            }
        else:
            authorized_tables = {"activation_leases", "activation_lease_events"}
        state["authorized_control_tables"] = frozenset(authorized_tables)
        state["authorized_control_session"] = session
        self._refresh_managed_authorizer(connection, state)
        return session

    def _is_issued_control_write_session(
        self,
        session: _ActivationControlWriteSession,
    ) -> bool:
        return bool(
            type(session) is _ActivationControlWriteSession
            and session.ledger is self
            and isinstance(session._seal, bytes)
            and secrets.compare_digest(
                session._seal,
                self.__control_write_session_seal,
            )
            and self.__issued_control_write_sessions.get(id(session)) is session
        )

    def finalize_activation_control_write(
        self,
        connection: sqlite3.Connection,
        *,
        session: Any,
    ) -> None:
        """Relock control tables after an exact controller-owned operation."""

        state = self._activation_transaction_states.get(id(connection))
        if (
            state is None
            or state.get("connection") is not connection
            or state.get("control_write_authorized") is not True
            or state.get("authorized_control_session") is not session
            or not self._is_issued_control_write_session(session)
            or session.connection is not connection
            or getattr(session.controller, "ledger", None) is not self
        ):
            raise WorkItemGovernanceError(
                "ACTIVATION_CONTROL_CAPABILITY_INVALID",
                "Lease-control relock requires the exact issued transaction session.",
            )
        state["control_write_authorized"] = False
        state["authorized_control_tables"] = frozenset()
        state["finalized_control_session"] = session
        self._refresh_managed_authorizer(connection, state)

    def activation_control_write_finalized(
        self,
        connection: sqlite3.Connection,
        *,
        session: Any,
    ) -> bool:
        state = self._activation_transaction_states.get(id(connection))
        return bool(
            state is not None
            and state.get("connection") is connection
            and state.get("authorized_control_session") is session
            and state.get("finalized_control_session") is session
            and state.get("control_write_authorized") is False
            and self._is_issued_control_write_session(session)
        )

    def authorize_activation_domain_write(
        self,
        connection: sqlite3.Connection,
        *,
        session: Any,
    ) -> None:
        """Unlock one managed transaction only after the Guard sealed it.

        The default repository transaction never accepts a caller-provided
        boolean or reusable capability.  Its authorizer closure is changed only
        for the exact connection and trusted ``ActivationWriteSession`` minted
        by the Guard after Lease/request validation.
        """

        # Local import avoids the repository/activation module import cycle.
        from runner.work_item_governance.activation import ActivationWriteSession

        state = self._activation_transaction_states.get(id(connection))
        if (
            state is None
            or state.get("connection") is not connection
            or state.get("authorized_session") is not None
            or not isinstance(session, ActivationWriteSession)
            or session.connection is not connection
            or session.guard.ledger is not self
            or not session.trusted_repository_write_session
        ):
            raise WorkItemGovernanceError(
                "ACTIVATION_REPOSITORY_CAPABILITY_INVALID",
                "Repository domain writes require the exact Guard-sealed transaction session.",
            )
        table = (
            "pilot_activation_leases"
            if session.guard.__class__.__name__ == "PilotActivationGuard"
            else "activation_leases"
        )
        query = (
            "SELECT lease_id,status FROM pilot_activation_leases WHERE lease_id=?"
            if table == "pilot_activation_leases"
            else "SELECT lease_id,status FROM activation_leases WHERE lease_id=?"
        )
        row = connection.execute(
            query,
            (session.row["lease_id"],),
        ).fetchone()
        if row is None or row["status"] != "active":
            raise WorkItemGovernanceError(
                "ACTIVE_ACTIVATION_LEASE_REQUIRED",
                "Repository domain writes require the active Guard-bound Lease.",
            )
        state["domain_write_authorized"] = True
        state["authorized_session"] = session
        self._refresh_managed_authorizer(connection, state)

    def finalize_activation_domain_write(
        self,
        connection: sqlite3.Connection,
        *,
        session: Any,
    ) -> None:
        """Immediately relock the exact managed transaction after Guard finalization."""

        from runner.work_item_governance.activation import ActivationWriteSession

        state = self._activation_transaction_states.get(id(connection))
        if (
            state is None
            or state.get("connection") is not connection
            or state.get("authorized_session") is not session
            or state.get("domain_write_authorized") is not True
            or not isinstance(session, ActivationWriteSession)
            or session.connection is not connection
            or session.guard.ledger is not self
            or not session.guard._is_issued_write_session(session)
        ):
            raise WorkItemGovernanceError(
                "ACTIVATION_REPOSITORY_CAPABILITY_INVALID",
                "Repository relock requires the exact Guard-issued transaction session.",
            )
        state["domain_write_authorized"] = False
        state["finalized_session"] = session
        self._refresh_managed_authorizer(connection, state)

    def activation_domain_write_finalized(
        self,
        connection: sqlite3.Connection,
        *,
        session: Any,
    ) -> bool:
        state = self._activation_transaction_states.get(id(connection))
        return bool(
            state is not None
            and state.get("connection") is connection
            and state.get("authorized_session") is session
            and state.get("finalized_session") is session
            and state.get("domain_write_authorized") is False
        )

    @contextmanager
    def read_connection(self) -> Iterator[sqlite3.Connection]:
        if not self.path.is_file():
            raise WorkItemGovernanceError(
                "LEDGER_FILE_MISSING",
                "Ledger database file does not exist.",
                details={"path": str(self.path)},
            )
        self._assert_existing_storage_path()
        with self._connect(readonly=True) as preflight:
            self._assert_readable_schema_version(
                int(preflight.execute("PRAGMA user_version").fetchone()[0])
            )
        with self._maintenance_lock(exclusive=False, create=False):
            connection = self._connect(readonly=True)
            try:
                self._assert_readable_schema_version(
                    int(connection.execute("PRAGMA user_version").fetchone()[0])
                )
                yield connection
            finally:
                connection.close()

    def _assert_readable_schema_version(self, current: int) -> None:
        if current > CURRENT_LEDGER_SCHEMA_VERSION:
            raise WorkItemGovernanceError(
                "LEDGER_SCHEMA_TOO_NEW",
                "Ledger schema is newer than this ColaMeta build.",
                details={"current": current, "supported": CURRENT_LEDGER_SCHEMA_VERSION},
            )
        if current < self.target_schema_version:
            raise WorkItemGovernanceError(
                "LEDGER_SCHEMA_MIGRATION_REQUIRED",
                "Ledger reads refuse implicit schema migration; run an explicit bootstrap or migration command.",
                details={"current": current, "required": self.target_schema_version},
            )

    def schema_version(self) -> int:
        with self.read_connection() as connection:
            return int(connection.execute("PRAGMA user_version").fetchone()[0])

    @staticmethod
    def _legacy_activation_history_digest(connection: sqlite3.Connection) -> dict[str, Any]:
        tables: list[dict[str, str]] = []
        table_queries = {
            "activation_leases": {
                "columns": "PRAGMA table_info(activation_leases)",
                "rows": "SELECT * FROM activation_leases ORDER BY lease_id",
            },
            "activation_lease_events": {
                "columns": "PRAGMA table_info(activation_lease_events)",
                "rows": "SELECT * FROM activation_lease_events ORDER BY lease_event_id",
            },
        }
        for table in ("activation_leases", "activation_lease_events"):
            schema_row = connection.execute(
                "SELECT sql FROM sqlite_schema WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            if schema_row is None:
                raise WorkItemGovernanceError(
                    "PILOT_LEGACY_SCHEMA_MISSING",
                    "Schema v6 migration requires both exact legacy activation tables.",
                    details={"table": table},
                )
            table_info = connection.execute(table_queries[table]["columns"]).fetchall()
            columns = [str(row[1]) for row in table_info]
            primary_key = [
                str(row[1])
                for row in sorted(
                    table_info,
                    key=lambda row: int(row[5]) if int(row[5]) > 0 else 1_000_000,
                )
                if int(row[5]) > 0
            ]
            rows = [
                {column: row[index] for index, column in enumerate(columns)}
                for row in connection.execute(table_queries[table]["rows"]).fetchall()
            ]
            value = {
                "name": table,
                "sqlite_schema_sql": str(schema_row[0]),
                "rows": rows,
            }
            tables.append({"name": table, "sha256": canonical_sha256(value)})
        return {"tables": tables, "aggregate_sha256": canonical_sha256(tables)}

    def migrate_to_v6(self) -> dict[str, Any]:
        """Perform the frozen v5→v6 migration under one exclusive maintenance boundary."""

        with self._maintenance_lock(exclusive=True, blocking=False):
            self._ensure_storage_path()
            if not self.path.exists():
                raise WorkItemGovernanceError(
                    "PILOT_MIGRATION_SOURCE_MISSING",
                    "Pilot migration requires an existing Schema v5 Ledger.",
                )
            connection = self._connect(
                readonly=False,
                _write_authority=self.__write_connection_authority,
            )
            try:
                connection.execute("BEGIN IMMEDIATE")
                before_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                if before_version != 5:
                    raise WorkItemGovernanceError(
                        "PILOT_MIGRATION_SOURCE_VERSION_INVALID",
                        "Pilot migration requires exact Schema v5 input.",
                        details={"actual": before_version},
                    )
                integrity_before = [str(row[0]) for row in connection.execute("PRAGMA integrity_check")]
                foreign_keys_before = [tuple(row) for row in connection.execute("PRAGMA foreign_key_check")]
                if integrity_before != ["ok"] or foreign_keys_before:
                    raise WorkItemGovernanceError(
                        "PILOT_MIGRATION_SOURCE_INTEGRITY_FAILED",
                        "Pilot migration source failed integrity or foreign-key checks.",
                    )
                live_legacy = connection.execute(
                    """
                    SELECT lease_id,status FROM activation_leases
                    WHERE status IN ('prepared','claimed','active','write_frozen')
                    LIMIT 1
                    """
                ).fetchone()
                if live_legacy is not None:
                    raise WorkItemGovernanceError(
                        "PILOT_MIGRATION_LEGACY_LEASE_NONTERMINAL",
                        "Schema v6 migration requires all legacy Activation Leases to be terminal.",
                        details={
                            "lease_id": str(live_legacy["lease_id"]),
                            "status": str(live_legacy["status"]),
                        },
                    )
                before = self._legacy_activation_history_digest(connection)
                for statement in self._migrations[6]:
                    connection.execute(statement)
                connection.execute("PRAGMA user_version=6")
                connection.execute(
                    "UPDATE ledger_meta SET value='6', updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
                    "WHERE key='schema_version'"
                )
                after_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                after = self._legacy_activation_history_digest(connection)
                pilot_counts = {
                    "pilot_activation_leases": int(
                        connection.execute("SELECT COUNT(*) FROM pilot_activation_leases").fetchone()[0]
                    ),
                    "pilot_activation_lease_events": int(
                        connection.execute("SELECT COUNT(*) FROM pilot_activation_lease_events").fetchone()[0]
                    ),
                }
                integrity_after = [str(row[0]) for row in connection.execute("PRAGMA integrity_check")]
                foreign_keys_after = [tuple(row) for row in connection.execute("PRAGMA foreign_key_check")]
                if (
                    after_version != 6
                    or before["aggregate_sha256"] != after["aggregate_sha256"]
                    or any(pilot_counts.values())
                    or integrity_after != ["ok"]
                    or foreign_keys_after
                ):
                    raise WorkItemGovernanceError(
                        "PILOT_MIGRATION_POSTCONDITION_FAILED",
                        "Schema v6 migration failed its frozen postconditions.",
                    )
                receipt = {
                "schema_version": "wig_p3_pilot_storage_migration_receipt.v1",
                "from_schema_version": before_version,
                "to_schema_version": after_version,
                "transaction_mode": "BEGIN_IMMEDIATE",
                "maintenance_lock": "exclusive",
                "legacy_before": before,
                "legacy_after": after,
                "legacy_table_digests_unchanged": True,
                "pilot_fact_counts": pilot_counts,
                "integrity_check": integrity_after,
                "foreign_key_violations": foreign_keys_after,
                }
                connection.commit()
            except Exception as exc:
                connection.rollback()
                if isinstance(exc, WorkItemGovernanceError):
                    raise
                raise WorkItemGovernanceError(
                    "LEDGER_MIGRATION_FAILED",
                    "Ledger migration failed and was rolled back.",
                    details={"target_version": 6, "reason": str(exc)},
                ) from exc
            finally:
                connection.close()
            os.chmod(self.path, 0o600)
            return receipt

    def migrate_to_v7(self) -> dict[str, Any]:
        """Atomically add append-only Pilot authorization facts to exact Schema v6."""

        with self._maintenance_lock(exclusive=True, blocking=False):
            self._ensure_storage_path()
            if not self.path.exists():
                raise WorkItemGovernanceError(
                    "PILOT_AUTHORITY_MIGRATION_SOURCE_MISSING",
                    "Authorization-fact migration requires an existing Schema v6 Ledger.",
                )
            connection = self._connect(readonly=False, _write_authority=self.__write_connection_authority)
            try:
                connection.execute("BEGIN IMMEDIATE")
                before_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                if before_version != 6:
                    raise WorkItemGovernanceError(
                        "PILOT_AUTHORITY_MIGRATION_SOURCE_VERSION_INVALID",
                        "Authorization-fact migration requires exact Schema v6 input.",
                        details={"actual": before_version},
                    )
                schema_meta_rows = connection.execute(
                    "SELECT value FROM ledger_meta WHERE key='schema_version'"
                ).fetchall()
                if len(schema_meta_rows) != 1 or str(schema_meta_rows[0]["value"]) != "6":
                    raise WorkItemGovernanceError(
                        "PILOT_AUTHORITY_MIGRATION_SOURCE_VERSION_INVALID",
                        "Schema v7 migration requires one exact Schema v6 Ledger metadata row.",
                    )
                live_pilot = connection.execute(
                    "SELECT lease_id,status FROM pilot_activation_leases LIMIT 1"
                ).fetchone()
                if live_pilot is not None:
                    raise WorkItemGovernanceError(
                        "PILOT_AUTHORITY_MIGRATION_REQUIRES_FRESH_LEDGER",
                        "Schema v7 migration must precede every Pilot Lease.",
                    )
                integrity_before = [str(row[0]) for row in connection.execute("PRAGMA integrity_check")]
                foreign_keys_before = [tuple(row) for row in connection.execute("PRAGMA foreign_key_check")]
                if integrity_before != ["ok"] or foreign_keys_before:
                    raise WorkItemGovernanceError(
                        "PILOT_AUTHORITY_MIGRATION_SOURCE_INTEGRITY_FAILED",
                        "Schema v7 migration source failed integrity or foreign-key checks.",
                    )
                for statement in self._migrations[7]:
                    connection.execute(statement)
                connection.execute("PRAGMA user_version=7")
                metadata_update = connection.execute(
                    "UPDATE ledger_meta SET value='7', updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
                    "WHERE key='schema_version'"
                )
                counts = {
                    "pilot_authorization_facts": int(
                        connection.execute("SELECT COUNT(*) FROM pilot_authorization_facts").fetchone()[0]
                    ),
                    "pilot_authorization_claims": int(
                        connection.execute("SELECT COUNT(*) FROM pilot_authorization_claims").fetchone()[0]
                    ),
                }
                integrity_after = [str(row[0]) for row in connection.execute("PRAGMA integrity_check")]
                foreign_keys_after = [tuple(row) for row in connection.execute("PRAGMA foreign_key_check")]
                schema_meta_after = connection.execute(
                    "SELECT value FROM ledger_meta WHERE key='schema_version'"
                ).fetchall()
                if (
                    int(connection.execute("PRAGMA user_version").fetchone()[0]) != 7
                    or metadata_update.rowcount != 1
                    or len(schema_meta_after) != 1
                    or str(schema_meta_after[0]["value"]) != "7"
                    or any(counts.values())
                    or integrity_after != ["ok"]
                    or foreign_keys_after
                ):
                    raise WorkItemGovernanceError(
                        "PILOT_AUTHORITY_MIGRATION_POSTCONDITION_FAILED",
                        "Schema v7 authorization-fact migration failed its postconditions.",
                    )
                receipt = {
                    "schema_version": "wig_p3_pilot_authority_storage_migration_receipt.v1",
                    "from_schema_version": before_version,
                    "to_schema_version": 7,
                    "transaction_mode": "BEGIN_IMMEDIATE",
                    "maintenance_lock": "exclusive",
                    "authorization_fact_counts": counts,
                    "integrity_check": integrity_after,
                    "foreign_key_violations": foreign_keys_after,
                }
                connection.commit()
            except Exception as exc:
                connection.rollback()
                if isinstance(exc, WorkItemGovernanceError):
                    raise
                raise WorkItemGovernanceError(
                    "LEDGER_MIGRATION_FAILED",
                    "Schema v7 authorization-fact migration failed and was rolled back.",
                    details={"target_version": 7, "reason": str(exc)},
                ) from exc
            finally:
                connection.close()
            os.chmod(self.path, 0o600)
            return receipt

    def assert_exact_schema_without_migration(self, *, expected_version: int | None = None) -> int:
        """Verify a preflighted Ledger without running a startup migration."""

        if not self.path.is_file():
            raise WorkItemGovernanceError(
                "ACTIVATION_LEDGER_MISSING",
                "Authoritative Canary requires its preflighted Ledger.",
            )
        expected = self.target_schema_version if expected_version is None else expected_version
        self._assert_existing_storage_path()
        with self._connect(readonly=True) as preflight:
            version = int(preflight.execute("PRAGMA user_version").fetchone()[0])
        if version != expected:
            raise WorkItemGovernanceError(
                "ACTIVATION_LEDGER_SCHEMA_MISMATCH",
                "Authoritative Canary refuses startup migration or schema drift.",
                details={"expected": expected, "actual": version},
            )
        with self._maintenance_lock(exclusive=False, create=False):
            with self._connect(readonly=True) as connection:
                version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if version != expected:
            raise WorkItemGovernanceError(
                "ACTIVATION_LEDGER_SCHEMA_MISMATCH",
                "Authoritative Canary refuses startup migration or schema drift.",
                details={"expected": expected, "actual": version},
            )
        return version

    def database_generation(self) -> int:
        with self.read_connection() as connection:
            row = connection.execute(
                "SELECT value FROM ledger_meta WHERE key='database_generation'"
            ).fetchone()
        if row is None:
            raise WorkItemGovernanceError(
                "LEDGER_GENERATION_MISSING",
                "Ledger database generation is missing.",
            )
        try:
            return int(row["value"])
        except (TypeError, ValueError) as exc:
            raise WorkItemGovernanceError(
                "LEDGER_GENERATION_INVALID",
                "Ledger database generation is invalid.",
            ) from exc

    def get_or_create_signing_key(self) -> bytes:
        with self.write_transaction() as connection:
            self._assert_not_activation_managed(connection, operation="signing_key")
            row = connection.execute("SELECT value FROM ledger_meta WHERE key='preview_signing_key'").fetchone()
            if row is None:
                value = secrets.token_hex(32)
                connection.execute(
                    "INSERT INTO ledger_meta(key,value,updated_at) VALUES('preview_signing_key',?,strftime('%Y-%m-%dT%H:%M:%fZ','now'))",
                    (value,),
                )
            else:
                value = str(row["value"])
        try:
            key = bytes.fromhex(value)
        except ValueError as exc:
            raise WorkItemGovernanceError("LEDGER_SIGNING_KEY_INVALID", "Ledger preview signing key is invalid.") from exc
        if len(key) != 32:
            raise WorkItemGovernanceError("LEDGER_SIGNING_KEY_INVALID", "Ledger preview signing key has an invalid size.")
        return key

    def get_existing_signing_key(self) -> bytes:
        with self.read_connection() as connection:
            row = connection.execute("SELECT value FROM ledger_meta WHERE key='preview_signing_key'").fetchone()
        if row is None:
            raise WorkItemGovernanceError(
                "LEDGER_SIGNING_KEY_MISSING",
                "The Authoritative Canary requires a preprovisioned Preview signing key.",
            )
        try:
            key = bytes.fromhex(str(row["value"]))
        except ValueError as exc:
            raise WorkItemGovernanceError(
                "LEDGER_SIGNING_KEY_INVALID",
                "Ledger preview signing key is invalid.",
            ) from exc
        if len(key) != 32:
            raise WorkItemGovernanceError(
                "LEDGER_SIGNING_KEY_INVALID",
                "Ledger preview signing key has an invalid size.",
            )
        return key

    def integrity_check(self, path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
        target = Path(path).expanduser().resolve() if path is not None else self.path
        if path is None:
            if not self.path.is_file():
                raise WorkItemGovernanceError(
                    "LEDGER_FILE_MISSING",
                    "Ledger database file does not exist.",
                    details={"path": str(self.path)},
                )
            with self._maintenance_lock(exclusive=False, create=False):
                return self._integrity_check_unlocked(target)
        return self._integrity_check_unlocked(target)

    def _integrity_check_unlocked(self, target: Path) -> dict[str, Any]:
        if not target.is_file():
            raise WorkItemGovernanceError(
                "LEDGER_FILE_MISSING",
                "Ledger database file does not exist.",
                details={"path": str(target)},
            )
        try:
            with self._connect(target, readonly=True) as connection:
                rows = [str(row[0]) for row in connection.execute("PRAGMA integrity_check").fetchall()]
                version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                foreign_key_violations = [tuple(row) for row in connection.execute("PRAGMA foreign_key_check").fetchall()]
        except sqlite3.DatabaseError as exc:
            raise WorkItemGovernanceError(
                "LEDGER_INTEGRITY_CHECK_FAILED",
                "Ledger database could not be opened for integrity checking.",
                details={"path": str(target), "reason": str(exc)},
            ) from exc
        ok = rows == ["ok"] and not foreign_key_violations and version <= CURRENT_LEDGER_SCHEMA_VERSION
        return {
            "ok": ok,
            "path": str(target),
            "integrity_check": rows,
            "foreign_key_violations": foreign_key_violations,
            "schema_version": version,
            "supported_schema_version": CURRENT_LEDGER_SCHEMA_VERSION,
        }

    def backup_to(
        self,
        destination: str | os.PathLike[str],
        *,
        reject_activation_managed: bool = True,
    ) -> dict[str, Any]:
        # Retain the keyword for source compatibility, but never let callers
        # disable the activation-managed boundary.
        _ = reject_activation_managed
        with self._maintenance_lock(exclusive=True):
            self._initialize_unlocked()
            destination_path = Path(destination).expanduser().resolve()
            if destination_path == self.path.resolve():
                raise WorkItemGovernanceError("BACKUP_TARGET_INVALID", "Backup target must differ from the active Ledger.")
            destination_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            source = self._connect(readonly=True)
            target = sqlite3.connect(str(destination_path), isolation_level=None)
            try:
                self._assert_not_activation_managed(source, operation="backup")
                generation_row = source.execute(
                    "SELECT value FROM ledger_meta WHERE key='database_generation'"
                ).fetchone()
                generation = int(generation_row["value"]) if generation_row is not None else 0
                source.backup(target)
            except sqlite3.DatabaseError as exc:
                raise WorkItemGovernanceError(
                    "LEDGER_BACKUP_FAILED",
                    "SQLite Backup API failed.",
                    details={"reason": str(exc)},
                ) from exc
            finally:
                target.close()
                source.close()
            os.chmod(destination_path, 0o600)
            result = self._integrity_check_unlocked(destination_path)
            if not result["ok"]:
                raise WorkItemGovernanceError(
                    "LEDGER_BACKUP_INVALID",
                    "Backup failed integrity verification.",
                    details=result,
                )
            return {
                "backup_api": "sqlite3.Connection.backup",
                "database_generation": generation,
                **result,
            }

    def restore_from_backup(
        self,
        source: str | os.PathLike[str],
        *,
        expected_database_generation: int,
        reject_activation_managed: bool = True,
    ) -> dict[str, Any]:
        _ = reject_activation_managed
        if (
            isinstance(expected_database_generation, bool)
            or not isinstance(expected_database_generation, int)
            or expected_database_generation < 1
        ):
            raise WorkItemGovernanceError(
                "LEDGER_RESTORE_GENERATION_REQUIRED",
                "Restore requires the expected positive database generation.",
            )
        source_path = Path(source).expanduser().resolve()
        source_check = self.integrity_check(source_path)
        if not source_check["ok"] or source_check["schema_version"] != self.target_schema_version:
            raise WorkItemGovernanceError(
                "LEDGER_RESTORE_SOURCE_INVALID",
                "Restore source failed integrity or exact schema verification.",
                details=source_check,
            )
        with self._maintenance_lock(exclusive=True, blocking=False):
            self._initialize_unlocked()
            with self._connect(readonly=True) as current_connection:
                self._assert_not_activation_managed(current_connection, operation="restore")
                generation_row = current_connection.execute(
                    "SELECT value FROM ledger_meta WHERE key='database_generation'"
                ).fetchone()
                current_generation = int(generation_row["value"]) if generation_row is not None else 0
            if current_generation != expected_database_generation:
                raise WorkItemGovernanceError(
                    "LEDGER_RESTORE_GENERATION_MISMATCH",
                    "Active Ledger generation changed after restore authorization.",
                    details={
                        "expected_database_generation": expected_database_generation,
                        "actual_database_generation": current_generation,
                    },
                )
            descriptor, temp_name = tempfile.mkstemp(
                prefix="work-items-restore-",
                suffix=".sqlite3",
                dir=self.path.parent,
            )
            os.close(descriptor)
            temp_path = Path(temp_name)
            try:
                source_connection = self._connect(source_path, readonly=True)
                target_connection = sqlite3.connect(str(temp_path), isolation_level=None)
                try:
                    self._assert_not_activation_managed(
                        source_connection,
                        operation="restore_source",
                    )
                    source_connection.backup(target_connection)
                finally:
                    target_connection.close()
                    source_connection.close()
                restored_generation = current_generation + 1
                with sqlite3.connect(str(temp_path), isolation_level=None) as staged_connection:
                    staged_connection.execute("BEGIN IMMEDIATE")
                    staged_connection.execute(
                        """
                        INSERT INTO ledger_meta(key,value,updated_at)
                        VALUES('database_generation',?,strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                        ON CONFLICT(key) DO UPDATE SET
                          value=excluded.value,
                          updated_at=excluded.updated_at
                        """,
                        (str(restored_generation),),
                    )
                    staged_connection.commit()
                    staged_connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    staged_connection.execute("PRAGMA journal_mode=DELETE")
                staged_check = self._integrity_check_unlocked(temp_path)
                if not staged_check["ok"]:
                    raise WorkItemGovernanceError(
                        "LEDGER_RESTORE_STAGED_COPY_INVALID",
                        "Staged restore copy failed integrity verification.",
                        details=staged_check,
                    )
                for suffix in ("-wal", "-shm"):
                    sidecar = Path(f"{self.path}{suffix}")
                    if sidecar.exists():
                        sidecar.unlink()
                os.replace(temp_path, self.path)
                os.chmod(self.path, 0o600)
                final_check = self._integrity_check_unlocked(self.path)
                if not final_check["ok"]:
                    raise WorkItemGovernanceError(
                        "LEDGER_RESTORE_FINAL_INVALID",
                        "Restored Ledger failed final integrity verification.",
                        details=final_check,
                    )
                return {
                    "backup_api": "sqlite3.Connection.backup",
                    "maintenance_lock": str(self.maintenance_lock_path),
                    "active_writer_count": 0,
                    "outbox_dispatch_paused": True,
                    "previous_database_generation": current_generation,
                    "database_generation": restored_generation,
                    "source": source_check,
                    "staged_copy": staged_check,
                    "restored": final_check,
                }
            finally:
                if temp_path.exists():
                    temp_path.unlink()
                for suffix in ("-wal", "-shm"):
                    temp_sidecar = Path(f"{temp_path}{suffix}")
                    if temp_sidecar.exists():
                        temp_sidecar.unlink()

    def export_audit_package(
        self,
        *,
        reject_activation_managed: bool = True,
    ) -> dict[str, Any]:
        """Return a structured export; secrets and source/report bodies are absent."""

        _ = reject_activation_managed

        export_queries = {
            "work_items": "SELECT * FROM work_items",
            "task_versions": "SELECT * FROM task_versions",
            "execution_attempts": "SELECT * FROM execution_attempts",
            "artifact_refs": "SELECT * FROM artifact_refs",
            "decision_records": "SELECT * FROM decision_records",
            "gate_events": "SELECT * FROM gate_events",
            "delivery_receipts": "SELECT * FROM delivery_receipts",
            "audit_events": "SELECT * FROM audit_events",
            "outbox_events": "SELECT * FROM outbox_events",
            "inbox_events": "SELECT * FROM inbox_events",
            "blocker_events": "SELECT * FROM blocker_events",
            "acceptance_manifests": "SELECT * FROM acceptance_manifests",
        }
        records: dict[str, list[dict[str, Any]]] = {}
        with self._maintenance_lock(exclusive=True):
            self._initialize_unlocked()
            with self._connect(readonly=True) as connection:
                self._assert_not_activation_managed(connection, operation="export")
                for table, query in export_queries.items():
                    rows = connection.execute(query).fetchall()
                    records[table] = [dict(row) for row in rows]
                ledger_schema_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        manifest = {
            "schema_version": "work_item_audit_export.v1",
            "ledger_schema_version": ledger_schema_version,
            "record_counts": {table: len(rows) for table, rows in records.items()},
            "records_digest": canonical_sha256(records),
            "contains_preview_signing_key": False,
            "contains_artifact_bodies": False,
        }
        return {"manifest": manifest, "records": records, "export_digest": canonical_sha256(manifest)}

    @staticmethod
    def _assert_not_activation_managed(
        connection: sqlite3.Connection,
        *,
        operation: str,
    ) -> None:
        pilot_schema_present = connection.execute(
            "SELECT 1 FROM sqlite_schema WHERE type='table' AND name='pilot_activation_leases'"
        ).fetchone() is not None
        query = """
            SELECT lease_id,status FROM activation_leases
            WHERE status IN ('prepared','claimed','active','write_frozen')
        """
        if pilot_schema_present:
            query += """
                UNION ALL
                SELECT lease_id,status FROM pilot_activation_leases
                WHERE status IN ('prepared','claimed','active','write_frozen')
            """
        lease = connection.execute(query + " LIMIT 1").fetchone()
        if lease is not None:
            raise WorkItemGovernanceError(
                "ACTIVATION_COMPOSITION_DOWNGRADE_DENIED",
                "An activation-managed Ledger cannot be accessed by an unguarded repository operation.",
                details={
                    "operation": operation,
                    "lease_id": str(lease["lease_id"]),
                    "lease_status": str(lease["status"]),
                },
            )

    @staticmethod
    def json_text(value: Any) -> str:
        return canonical_json(value)
