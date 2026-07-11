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


MIGRATIONS: dict[int, tuple[str, ...]] = {
    1: _migration_v1(),
    2: _migration_v2(),
    3: _migration_v3(),
    4: _migration_v4(),
    5: _migration_v5(),
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
    ) -> None:
        self.project_root = Path(project_root).expanduser().resolve()
        self.path = self.project_root.joinpath(*LEDGER_RELATIVE_PATH.split("/"))
        self.maintenance_lock_path = self.path.parent / "work-items.restore.lock"
        self.busy_timeout_ms = max(1, int(busy_timeout_ms))
        self._migrations = dict(migrations or MIGRATIONS)

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

    @contextmanager
    def _maintenance_lock(
        self,
        *,
        exclusive: bool,
        blocking: bool = True,
    ) -> Iterator[None]:
        self._ensure_storage_path()
        if self.maintenance_lock_path.is_symlink():
            raise WorkItemGovernanceError(
                "LEDGER_PATH_UNSAFE",
                "Ledger maintenance lock must not be a symbolic link.",
            )
        flags = os.O_CREAT | os.O_RDWR
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(self.maintenance_lock_path, flags, 0o600)
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

    def _connect(self, path: Path | None = None, *, readonly: bool = False) -> sqlite3.Connection:
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
        connection = self._connect()
        try:
            current = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if current > CURRENT_LEDGER_SCHEMA_VERSION:
                raise WorkItemGovernanceError(
                    "LEDGER_SCHEMA_TOO_NEW",
                    "Ledger schema is newer than this ColaMeta build.",
                    details={"current": current, "supported": CURRENT_LEDGER_SCHEMA_VERSION},
                )
            while current < CURRENT_LEDGER_SCHEMA_VERSION:
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
    def write_transaction(self) -> Iterator[sqlite3.Connection]:
        with self._maintenance_lock(exclusive=False):
            self._initialize_unlocked()
            connection = self._connect()
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
                connection.commit()
            except CommitWorkItemRejection as exc:
                connection.commit()
                raise exc.error from exc
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()
                if self.path.exists():
                    os.chmod(self.path, 0o600)

    @contextmanager
    def read_connection(self) -> Iterator[sqlite3.Connection]:
        with self._maintenance_lock(exclusive=False):
            self._initialize_unlocked()
            connection = self._connect(readonly=True)
            try:
                yield connection
            finally:
                connection.close()

    def schema_version(self) -> int:
        with self.read_connection() as connection:
            return int(connection.execute("PRAGMA user_version").fetchone()[0])

    def assert_exact_schema_without_migration(self) -> int:
        """Verify a preflighted Ledger without running a startup migration."""

        with self._maintenance_lock(exclusive=False):
            if not self.path.is_file():
                raise WorkItemGovernanceError(
                    "ACTIVATION_LEDGER_MISSING",
                    "Authoritative Canary requires its preflighted Ledger.",
                )
            with self._connect(readonly=True) as connection:
                version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if version != CURRENT_LEDGER_SCHEMA_VERSION:
            raise WorkItemGovernanceError(
                "ACTIVATION_LEDGER_SCHEMA_MISMATCH",
                "Authoritative Canary refuses startup migration or schema drift.",
                details={"expected": CURRENT_LEDGER_SCHEMA_VERSION, "actual": version},
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
            with self._maintenance_lock(exclusive=False):
                self._initialize_unlocked()
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

    def backup_to(self, destination: str | os.PathLike[str]) -> dict[str, Any]:
        with self._maintenance_lock(exclusive=False):
            self._initialize_unlocked()
            destination_path = Path(destination).expanduser().resolve()
            if destination_path == self.path.resolve():
                raise WorkItemGovernanceError("BACKUP_TARGET_INVALID", "Backup target must differ from the active Ledger.")
            destination_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            source = self._connect(readonly=True)
            target = sqlite3.connect(str(destination_path), isolation_level=None)
            try:
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
    ) -> dict[str, Any]:
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
        if not source_check["ok"] or source_check["schema_version"] != CURRENT_LEDGER_SCHEMA_VERSION:
            raise WorkItemGovernanceError(
                "LEDGER_RESTORE_SOURCE_INVALID",
                "Restore source failed integrity or exact schema verification.",
                details=source_check,
            )
        with self._maintenance_lock(exclusive=True, blocking=False):
            self._initialize_unlocked()
            with self._connect(readonly=True) as current_connection:
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

    def export_audit_package(self) -> dict[str, Any]:
        """Return a structured export; secrets and source/report bodies are absent."""

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
        with self.read_connection() as connection:
            for table, query in export_queries.items():
                rows = connection.execute(query).fetchall()
                records[table] = [dict(row) for row in rows]
        manifest = {
            "schema_version": "work_item_audit_export.v1",
            "ledger_schema_version": self.schema_version(),
            "record_counts": {table: len(rows) for table, rows in records.items()},
            "records_digest": canonical_sha256(records),
            "contains_preview_signing_key": False,
            "contains_artifact_bodies": False,
        }
        return {"manifest": manifest, "records": records, "export_digest": canonical_sha256(manifest)}

    @staticmethod
    def json_text(value: Any) -> str:
        return canonical_json(value)
