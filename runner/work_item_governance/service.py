from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

from runner.work_item_governance.canonical import canonical_json, canonical_sha256, sha256_file
from runner.work_item_governance.activation import AuthoritativeCanaryGuard, ActivationWriteSession
from runner.work_item_governance.pilot import PilotActivationGuard
from runner.work_item_governance.contracts import (
    ARTIFACT_KINDS,
    DECISION_ACTIONS,
    MAX_TEXT_LENGTH,
    MAX_URI_LENGTH,
    SCHEMA_VERSIONS,
    SHA256_PATTERN,
    TERMINAL_WORK_ITEM_STATES,
    TRANSITION_REQUIREMENTS,
    WORK_ITEM_STATES,
    can_transition,
)
from runner.work_item_governance.errors import WorkItemGovernanceError
from runner.work_item_governance.ids import new_stable_id
from runner.work_item_governance.preview import PreviewCodec, isoformat_utc, utc_now
from runner.work_item_governance.principal import (
    PrincipalContext,
    authorize_principal,
    permission_for_decision,
)
from runner.work_item_governance.request_context import AuthoritativeCanaryRequestContext
from runner.work_item_governance.repository import SQLiteWorkItemLedger
from runner.work_item_governance.settings import load_work_item_governance_settings
from runner.work_item_governance.validation import (
    normalize_actor,
    normalize_authority_basis,
    normalize_initial_task,
    normalize_origin,
    normalize_string_list,
    optional_text,
    require_metadata_object,
    require_non_negative_integer,
    require_object,
    require_positive_integer,
    require_sha256,
    require_stable_id,
    require_text,
)


_SENSITIVE_KEY_FRAGMENTS = (
    "access_token",
    "api_key",
    "authorization",
    "cookie",
    "credential",
    "password",
    "private_key",
    "prompt_body",
    "refresh_token",
    "report_body",
    "secret",
    "source_body",
    "source_code",
)


class WorkItemApplicationService:
    """The only application service authorized to mutate Work Item state."""

    def __init__(
        self,
        project_root: str | os.PathLike[str],
        *,
        enabled: bool | None = None,
        authoritative_transitions: bool | None = None,
        ledger: SQLiteWorkItemLedger | None = None,
        now: Callable[[], datetime] = utc_now,
        authoritative_canary: bool = False,
        bounded_single_project_pilot: bool = False,
        principal_context: PrincipalContext | None = None,
        request_context: AuthoritativeCanaryRequestContext | None = None,
    ) -> None:
        self.project_root = Path(project_root).expanduser().resolve()
        settings = load_work_item_governance_settings(self.project_root)
        self.enabled = settings.shadow_ledger_enabled if enabled is None else bool(enabled)
        if authoritative_transitions is None:
            self.gate_mode = settings.gate_mode
        else:
            self.gate_mode = "authoritative" if authoritative_transitions else "shadow"
        self.authoritative_transitions = self.gate_mode == "authoritative"
        self.authoritative_canary = bool(authoritative_canary)
        self.bounded_single_project_pilot = bool(bounded_single_project_pilot)
        if self.authoritative_canary and self.bounded_single_project_pilot:
            raise WorkItemGovernanceError(
                "ACTIVATION_COMPOSITION_CONFLICT",
                "Legacy Canary and bounded Pilot compositions are mutually exclusive.",
            )
        self.canary_project_marked = settings.authoritative_canary
        if (self.authoritative_canary or self.bounded_single_project_pilot) and not self.authoritative_transitions:
            raise WorkItemGovernanceError(
                "AUTHORITATIVE_CANARY_MODE_INVALID",
                "The Authoritative Canary composition requires authoritative Gate evaluation.",
            )
        self.ledger = ledger or SQLiteWorkItemLedger(
            self.project_root,
            target_schema_version=7 if self.bounded_single_project_pilot else 5,
        )
        if self.authoritative_canary or self.bounded_single_project_pilot:
            self.ledger.assert_exact_schema_without_migration(
                expected_version=7 if self.bounded_single_project_pilot else 5
            )
        self.now = now
        self.principal_context = principal_context
        self.request_context = request_context
        self.activation_guard = (
            PilotActivationGuard(self.ledger, now=now)
            if self.bounded_single_project_pilot
            else (AuthoritativeCanaryGuard(self.ledger, now=now) if self.authoritative_canary else None)
        )
        self._activation_authorized_transactions: dict[int, ActivationWriteSession] = {}
        self.previews = PreviewCodec(
            self.ledger,
            now=now,
            allow_signing_key_creation=not (
                self.authoritative_canary or self.bounded_single_project_pilot or self.canary_project_marked
            ),
        )

    def status(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema_version": "work_item_governance_status.v1",
            "enabled": self.enabled,
            "gate_mode": self.gate_mode,
            "ledger_relative_path": ".colameta/ledger/work-items.sqlite3",
            "data_classification": "project_local_durable",
            "automatic_creation": False,
            "automatic_history_backfill": False,
            "authoritative_canary": self.authoritative_canary,
            "bounded_single_project_pilot": self.bounded_single_project_pilot,
            "effective_authoritative_writes": (
                "lease_controlled"
                if self.authoritative_canary or self.bounded_single_project_pilot
                else (
                    "denied_composition"
                    if self.canary_project_marked
                    else self.authoritative_transitions
                )
            ),
        }
        if self.enabled and self.ledger.path.exists():
            result["ledger_schema_version"] = self.ledger.schema_version()
            result["database_generation"] = self.ledger.database_generation()
            result["integrity"] = self.ledger.integrity_check()
            if self.activation_guard is not None:
                result["activation_lease"] = self.activation_guard.runtime_status()
        return result

    def _activation_preview(self, command_name: str, normalized_command: dict[str, Any]) -> None:
        if self.activation_guard is None:
            return
        self.activation_guard.authorize_preview(
            command_name=command_name,
            normalized_command=normalized_command,
            principal_context=self.principal_context,
            request_context=self.request_context,
        )

    def _activation_begin(
        self,
        connection: sqlite3.Connection,
        *,
        command_name: str,
        normalized_command: dict[str, Any],
        source_event_key: str,
        principal_context: PrincipalContext | None = None,
    ) -> ActivationWriteSession | None:
        if self.activation_guard is None:
            return None
        session = self.activation_guard.begin_write(
            connection,
            command_name=command_name,
            normalized_command=normalized_command,
            source_event_key=source_event_key,
            principal_context=principal_context or self.principal_context,
            request_context=self.request_context,
        )
        self._activation_authorized_transactions[id(connection)] = session
        return session

    def _deny_activation_command(
        self,
        command_name: str,
        *,
        principal_context: PrincipalContext | None = None,
    ) -> None:
        if self.activation_guard is None:
            return
        with self._write_transaction() as connection:
            self.activation_guard.deny_command(
                connection,
                command_name=command_name,
                principal_context=principal_context or self.principal_context,
                request_context=self.request_context,
            )

    @contextmanager
    def _write_transaction(self) -> Iterator[sqlite3.Connection]:
        """Open an application write transaction without permitting composition downgrade.

        Once a Ledger has ever contained an Activation Lease, all application writes must
        continue through the Authoritative Canary guard.  The check deliberately runs
        after ``BEGIN IMMEDIATE`` so a service instance created before Lease issuance
        cannot race the control plane and write unaccounted facts.
        """

        with self.ledger.write_transaction() as connection:
            connection_id = id(connection)
            if self.activation_guard is None:
                if self.canary_project_marked:
                    raise WorkItemGovernanceError(
                        "ACTIVATION_COMPOSITION_DOWNGRADE_DENIED",
                        "A project marked for Authoritative Canary execution cannot be mutated by an unguarded application composition.",
                    )
                lease = self._latest_activation_lease(connection)
                if lease is not None:
                    raise WorkItemGovernanceError(
                        "ACTIVATION_COMPOSITION_DOWNGRADE_DENIED",
                        "A Ledger containing an Activation Lease cannot be mutated by an unguarded application composition.",
                        details={"lease_id": str(lease["lease_id"]), "lease_status": str(lease["status"])},
                    )
            try:
                yield connection
                if self.activation_guard is not None:
                    session = self._activation_authorized_transactions.get(connection_id)
                    if session is None:
                        raise WorkItemGovernanceError(
                            "ACTIVATION_WRITE_NOT_AUTHORIZED",
                            "Every Authoritative Canary application write must enter the transactional Activation Lease guard.",
                        )
                    if not self.ledger.activation_domain_write_finalized(
                        connection,
                        session=session,
                    ):
                        raise WorkItemGovernanceError(
                            "ACTIVATION_WRITE_NOT_FINALIZED",
                            "Every Authoritative Canary application write must finalize through the transactional Activation Lease guard.",
                        )
            finally:
                session = self._activation_authorized_transactions.pop(connection_id, None)
                if self.activation_guard is not None and session is not None:
                    self.activation_guard._discard_write_session(session)

    def _assert_unguarded_maintenance_allowed(self, operation: str) -> None:
        """Keep activation-managed Ledgers behind their dedicated control plane."""

        if self.activation_guard is not None:
            raise WorkItemGovernanceError(
                f"ACTIVATION_LEDGER_{operation.upper()}_DENIED",
                f"Ledger {operation} is denied while the Authoritative Canary composition is active.",
            )
        with self.ledger.read_connection() as connection:
            lease = self._latest_activation_lease(connection, live_only=True)
        if lease is not None:
            raise WorkItemGovernanceError(
                "ACTIVATION_COMPOSITION_DOWNGRADE_DENIED",
                "An activation-managed Ledger cannot be accessed through an unguarded maintenance command.",
                details={
                    "operation": operation,
                    "lease_id": str(lease["lease_id"]),
                    "lease_status": str(lease["status"]),
                },
            )

    def _assert_internal_activation_write_denied(self, operation: str) -> None:
        """Reject direct invocation of a legacy helper in a Canary composition.

        Public denied commands freeze the Lease through ``_deny_activation_command``.
        Private helpers must not be callable as an alternative write entry point.
        """

        if self.activation_guard is not None or self.canary_project_marked:
            raise WorkItemGovernanceError(
                "ACTIVATION_INTERNAL_WRITE_PATH_DENIED",
                "This internal Work Item write path is unavailable to an Authoritative Canary.",
                details={"operation": operation},
            )
        with self.ledger.read_connection() as connection:
            lease = self._latest_activation_lease(connection)
        if lease is not None:
            raise WorkItemGovernanceError(
                "ACTIVATION_COMPOSITION_DOWNGRADE_DENIED",
                "An activation-managed Ledger cannot be accessed through an unguarded internal write path.",
                details={
                    "operation": operation,
                    "lease_id": str(lease["lease_id"]),
                    "lease_status": str(lease["status"]),
                },
            )

    @staticmethod
    def _latest_activation_lease(
        connection: sqlite3.Connection,
        *,
        live_only: bool = False,
    ) -> sqlite3.Row | None:
        legacy_query = "SELECT lease_id,status FROM activation_leases"
        pilot_query = "SELECT lease_id,status FROM pilot_activation_leases"
        if live_only:
            live_filter = " WHERE status IN ('prepared','claimed','active','write_frozen')"
            legacy_query += live_filter
            pilot_query += live_filter
        queries = [legacy_query]
        if int(connection.execute("PRAGMA user_version").fetchone()[0]) >= 6:
            queries.append(pilot_query)
        return connection.execute(" UNION ALL ".join(queries) + " LIMIT 1").fetchone()

    @staticmethod
    def _activation_domain_delta(**overrides: int) -> dict[str, int]:
        delta = {
            "work_items": 0,
            "task_versions": 0,
            "runtime_attempts": 0,
            "attempt_events": 0,
            "artifacts": 0,
            "decisions": 0,
            "applied_gate_events": 0,
            "rejected_gate_events": 0,
            "audit_events": 0,
            "outbox_events": 0,
            "acceptance_manifests": 0,
        }
        unknown = set(overrides) - set(delta)
        if unknown:
            raise AssertionError(f"unknown activation domain facts: {sorted(unknown)}")
        delta.update(overrides)
        return delta

    @staticmethod
    def _activation_artifact_command(artifact: dict[str, Any]) -> dict[str, Any]:
        return {
            key: (None if key == "artifact_id" and not artifact["_artifact_id_supplied"] else value)
            for key, value in artifact.items()
            if not key.startswith("_")
        }

    def _require_enabled(self) -> None:
        if not self.enabled:
            raise WorkItemGovernanceError(
                "WORK_ITEM_GOVERNANCE_DISABLED",
                "Work Item Shadow Ledger is disabled for this project.",
                details={
                    "setting": "work_item_governance.shadow_ledger_enabled",
                    "default": False,
                },
            )

    def _require_gate_enabled(self) -> None:
        if self.gate_mode == "off":
            raise WorkItemGovernanceError(
                "WORK_ITEM_GATES_DISABLED",
                "Work Item Gate evaluation is disabled for this project.",
                details={"setting": "work_item_governance.gate_mode"},
            )

    # ------------------------------------------------------------------
    # Phase 1: explicit create/import preview -> apply
    # ------------------------------------------------------------------

    def preview_work_item_create(
        self,
        command: dict[str, Any],
        *,
        ttl_seconds: int = 300,
    ) -> dict[str, Any]:
        self._require_enabled()
        normalized = self._normalize_create_command(command, imported=False)
        self._activation_preview("apply_work_item_create", normalized)
        work_item_id = new_stable_id("work_item")
        preview = self.previews.issue(
            "work_item_create",
            normalized,
            ttl_seconds=ttl_seconds,
            generated_ids={"work_item_id": work_item_id},
        )
        return {
            "status": "preview_ready",
            "creates_work_item": False,
            "writes_delivery_state": False,
            "preview": preview,
            "proposed_work_item_id": work_item_id,
        }

    def apply_work_item_create(self, preview: dict[str, Any]) -> dict[str, Any]:
        self._require_enabled()
        verified = self.previews.verify(preview, expected_operation="work_item_create")
        command = self._normalize_create_command(verified["command"], imported=False)
        return self._apply_create(verified, command, creation_operation="create")

    def preview_legacy_work_item_import(
        self,
        command: dict[str, Any],
        *,
        ttl_seconds: int = 300,
    ) -> dict[str, Any]:
        self._require_enabled()
        self._deny_activation_command("apply_legacy_work_item_import")
        normalized = self._normalize_legacy_import_command(command)
        work_item_id = new_stable_id("work_item")
        preview = self.previews.issue(
            "legacy_work_item_import",
            normalized,
            ttl_seconds=ttl_seconds,
            generated_ids={"work_item_id": work_item_id},
        )
        return {
            "status": "preview_ready",
            "creates_work_item": False,
            "writes_delivery_state": False,
            "history_relationships_inferred": False,
            "preview": preview,
            "proposed_work_item_id": work_item_id,
        }

    def apply_legacy_work_item_import(self, preview: dict[str, Any]) -> dict[str, Any]:
        self._require_enabled()
        self._deny_activation_command("apply_legacy_work_item_import")
        verified = self.previews.verify(preview, expected_operation="legacy_work_item_import")
        command = self._normalize_legacy_import_command(verified["command"])
        return self._apply_create(verified, command, creation_operation="legacy_import")

    def _normalize_create_command(self, value: Any, *, imported: bool) -> dict[str, Any]:
        command = require_object(value, "command", non_empty=True)
        allowed = {"origin", "title", "objective", "attributes", "task", "idempotency_key"}
        unknown = sorted(set(command) - allowed)
        if unknown:
            raise WorkItemGovernanceError(
                "CREATE_FIELD_UNSUPPORTED",
                "Work Item create command contains unsupported fields.",
                details={"unsupported_fields": unknown},
            )
        origin = normalize_origin(command.get("origin"), imported=imported)
        attributes = require_metadata_object(command.get("attributes", {}), "attributes")
        self._reject_sensitive_fields(attributes, "attributes")
        if "title" in command:
            attributes["title"] = require_text(command.get("title"), "title", max_length=512)
        if "objective" in command:
            attributes["objective"] = require_text(command.get("objective"), "objective")
        attributes = require_metadata_object(attributes, "attributes")
        task = normalize_initial_task(command.get("task"), fallback_objective=attributes.get("objective"))
        self._reject_sensitive_fields(task, "task")
        idempotency_key = optional_text(command.get("idempotency_key"), "idempotency_key", max_length=1024)
        normalized = {
            "origin": origin,
            "attributes": attributes,
            "task": task,
            "idempotency_key": idempotency_key,
        }
        canonical_sha256(normalized)
        return normalized

    def _normalize_legacy_import_command(self, value: Any) -> dict[str, Any]:
        command = require_object(value, "command", non_empty=True)
        allowed = {"legacy_record", "legacy_refs", "origin", "attributes", "task", "idempotency_key"}
        unknown = sorted(set(command) - allowed)
        if unknown:
            raise WorkItemGovernanceError(
                "LEGACY_IMPORT_FIELD_UNSUPPORTED",
                "Legacy import command contains unsupported fields.",
                details={"unsupported_fields": unknown},
            )
        legacy_record = require_object(command.get("legacy_record"), "legacy_record", non_empty=True)
        self._reject_sensitive_fields(legacy_record, "legacy_record")
        snapshot_digest = canonical_sha256(legacy_record)
        origin_value = command.get("origin")
        if origin_value is None:
            origin_value = {"kind": "imported", "ref": None, "snapshot_digest": snapshot_digest}
        origin = normalize_origin(origin_value, imported=True)
        if origin["snapshot_digest"] != snapshot_digest:
            raise WorkItemGovernanceError(
                "IMPORT_SNAPSHOT_DIGEST_MISMATCH",
                "Imported origin digest does not match the explicit legacy record snapshot.",
                details={"expected": snapshot_digest, "actual": origin["snapshot_digest"]},
            )
        legacy_refs_value = command.get("legacy_refs", [])
        if not isinstance(legacy_refs_value, list) or len(legacy_refs_value) > 1024:
            raise WorkItemGovernanceError(
                "LEGACY_REFS_INVALID",
                "legacy_refs must be a bounded list of explicit references.",
            )
        legacy_refs: list[dict[str, str]] = []
        for index, item in enumerate(legacy_refs_value):
            ref = require_object(item, f"legacy_refs[{index}]", non_empty=True)
            if set(ref) != {"kind", "ref"}:
                raise WorkItemGovernanceError(
                    "LEGACY_REF_SHAPE_INVALID",
                    "Each legacy reference must contain only kind and ref.",
                    details={"index": index},
                )
            legacy_refs.append(
                {
                    "kind": require_text(ref.get("kind"), f"legacy_refs[{index}].kind", max_length=128),
                    "ref": require_text(ref.get("ref"), f"legacy_refs[{index}].ref", max_length=2048),
                }
            )
        attributes = require_metadata_object(command.get("attributes", {}), "attributes")
        self._reject_sensitive_fields(attributes, "attributes")
        attributes = {**attributes, "legacy_refs": legacy_refs, "imported_snapshot_digest": snapshot_digest}
        attributes = require_metadata_object(attributes, "attributes")
        task = normalize_initial_task(command.get("task"))
        self._reject_sensitive_fields(task, "task")
        normalized = {
            "origin": origin,
            "attributes": attributes,
            "task": task,
            "idempotency_key": optional_text(command.get("idempotency_key"), "idempotency_key", max_length=1024),
            "legacy_refs": legacy_refs,
            # The snapshot remains in the signed preview only. _apply_create does
            # not persist it; this field protects the exact import authorization.
            "legacy_record": legacy_record,
        }
        canonical_sha256(normalized)
        return normalized

    def _apply_create(
        self,
        preview: dict[str, Any],
        command: dict[str, Any],
        *,
        creation_operation: str,
    ) -> dict[str, Any]:
        # ``_apply_create`` is shared by the ordinary create and explicit
        # legacy-import public commands.  It must not let a direct Python
        # caller relabel an imported command as the lease-controlled
        # ``apply_work_item_create`` operation.  Resolve and validate the
        # operation before opening a write transaction so a rejected legacy
        # path cannot create domain facts or consume Activation Lease quota.
        if creation_operation == "create":
            activation_command_name = "apply_work_item_create"
            command = self._normalize_create_command(command, imported=False)
        elif creation_operation == "legacy_import":
            activation_command_name = "apply_legacy_work_item_import"
            self._assert_internal_activation_write_denied(activation_command_name)
            command = self._normalize_legacy_import_command(command)
        else:
            raise WorkItemGovernanceError(
                "CREATE_OPERATION_UNSUPPORTED",
                "Work Item creation operation is unsupported.",
                details={"creation_operation": creation_operation},
            )
        work_item_id = require_stable_id(preview.get("generated_ids", {}).get("work_item_id"), "work_item")
        preview_id = require_stable_id(preview.get("preview_id"), "preview")
        origin = command["origin"]
        attributes = command["attributes"]
        task = command["task"]
        idempotency_key = command.get("idempotency_key")
        content_digest = canonical_sha256(command)
        created_at = isoformat_utc(self.now())
        try:
            with self._write_transaction() as connection:
                activation = self._activation_begin(
                    connection,
                    command_name=activation_command_name,
                    normalized_command=command,
                    source_event_key=idempotency_key or preview_id,
                )
                existing = connection.execute(
                    "SELECT * FROM work_items WHERE creation_preview_id=?",
                    (preview_id,),
                ).fetchone()
                if existing is not None:
                    self._assert_existing_create_matches(existing, content_digest, creation_operation)
                    existing_id = str(existing["work_item_id"])
                    idempotent = True
                else:
                    existing = None
                    if idempotency_key is not None:
                        existing = connection.execute(
                            "SELECT * FROM work_items WHERE creation_idempotency_key=?",
                            (idempotency_key,),
                        ).fetchone()
                    if existing is not None:
                        self._assert_existing_create_matches(existing, content_digest, creation_operation)
                        existing_id = str(existing["work_item_id"])
                        idempotent = True
                    else:
                        origin_existing = connection.execute(
                            """
                            SELECT * FROM work_items
                            WHERE origin_kind=? AND origin_ref IS ? AND origin_snapshot_digest=?
                            """,
                            (origin["kind"], origin["ref"], origin["snapshot_digest"]),
                        ).fetchone()
                        if origin_existing is not None:
                            self._assert_existing_create_matches(origin_existing, content_digest, creation_operation)
                            existing_id = str(origin_existing["work_item_id"])
                            idempotent = True
                        else:
                            if activation is not None:
                                activation.authorize_new(
                                    work_item_id=None,
                                    fact_delta={"new_work_items": 1, "task_versions": 1},
                                    domain_fact_delta=self._activation_domain_delta(
                                        work_items=1,
                                        task_versions=1,
                                    ),
                                )
                            connection.execute(
                                """
                                INSERT INTO work_items(
                                  work_item_id,schema_version,state,state_version,origin_kind,origin_ref,
                                  origin_snapshot_digest,imported,current_task_version,attributes_json,
                                  content_digest,creation_operation,creation_preview_id,
                                  creation_idempotency_key,created_at,updated_at
                                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                                """,
                                (
                                    work_item_id,
                                    SCHEMA_VERSIONS["work_item"],
                                    "proposed",
                                    0,
                                    origin["kind"],
                                    origin["ref"],
                                    origin["snapshot_digest"],
                                    1 if creation_operation == "legacy_import" else 0,
                                    1,
                                    canonical_json(attributes),
                                    content_digest,
                                    creation_operation,
                                    preview_id,
                                    idempotency_key,
                                    created_at,
                                    created_at,
                                ),
                            )
                            self._insert_task_version(
                                connection,
                                work_item_id=work_item_id,
                                task_version=1,
                                task=task,
                                source_event_key=f"{preview_id}:task:1",
                                created_at=created_at,
                            )
                            if activation is not None:
                                activation.commit_new(work_item_id=work_item_id)
                            existing_id = work_item_id
                            idempotent = False
                if idempotent and activation is not None:
                    activation.authorize_replay(work_item_id=existing_id)
        except sqlite3.IntegrityError as exc:
            raise self._integrity_error(exc, operation=creation_operation) from exc
        result = self.get_work_item(existing_id)
        return {
            "status": "applied",
            "created": not idempotent,
            "idempotent_replay": idempotent,
            "writes_delivery_state": False,
            "work_item": result,
        }

    @staticmethod
    def _assert_existing_create_matches(row: sqlite3.Row, content_digest: str, creation_operation: str) -> None:
        if row["content_digest"] != content_digest or row["creation_operation"] != creation_operation:
            raise WorkItemGovernanceError(
                "IDEMPOTENCY_CONFLICT",
                "An existing Work Item uses this idempotency/origin key with different content.",
                details={"work_item_id": row["work_item_id"]},
            )

    # ------------------------------------------------------------------
    # Read models
    # ------------------------------------------------------------------

    def get_work_item(self, work_item_id: str) -> dict[str, Any]:
        self._require_enabled()
        require_stable_id(work_item_id, "work_item")
        if self.activation_guard is not None:
            self.activation_guard.assert_read_scope(work_item_id)
        with self.ledger.read_connection() as connection:
            row = connection.execute("SELECT * FROM work_items WHERE work_item_id=?", (work_item_id,)).fetchone()
            if row is None:
                raise WorkItemGovernanceError(
                    "WORK_ITEM_NOT_FOUND",
                    "Work Item does not exist.",
                    details={"work_item_id": work_item_id},
                )
            return self._materialize_work_item(connection, row)

    def list_work_items(
        self,
        *,
        state: str | None = None,
        limit: int = 50,
        after_created_at: str | None = None,
    ) -> dict[str, Any]:
        self._require_enabled()
        if state is not None and state not in WORK_ITEM_STATES:
            raise WorkItemGovernanceError("WORK_ITEM_STATE_INVALID", "Work Item state filter is invalid.")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
            raise WorkItemGovernanceError("LIST_LIMIT_INVALID", "List limit must be between 1 and 200.")
        if self.activation_guard is not None:
            bound = self.activation_guard.authorized_work_item_id()
            if bound is None:
                items: list[dict[str, Any]] = []
            else:
                with self.ledger.read_connection() as connection:
                    row = connection.execute(
                        "SELECT * FROM work_items WHERE work_item_id=?",
                        (bound,),
                    ).fetchone()
                    items = (
                        []
                        if row is None or (state is not None and row["state"] != state)
                        else [self._materialize_work_item(connection, row, include_children=False)]
                    )
            return {
                "schema_version": "work_item_list.v1",
                "items": items,
                "count": len(items),
                "next_cursor": None,
                "authoritative_for_delivery_state": True,
                "shadow_read_model": False,
            }
        params: list[Any] = []
        if state is not None:
            params.append(state)
        if after_created_at is not None:
            params.append(require_text(after_created_at, "after_created_at", max_length=64))
        queries = {
            (False, False): "SELECT * FROM work_items ORDER BY created_at DESC, work_item_id DESC LIMIT ?",
            (True, False): "SELECT * FROM work_items WHERE state=? ORDER BY created_at DESC, work_item_id DESC LIMIT ?",
            (False, True): "SELECT * FROM work_items WHERE created_at<? ORDER BY created_at DESC, work_item_id DESC LIMIT ?",
            (True, True): (
                "SELECT * FROM work_items WHERE state=? AND created_at<? "
                "ORDER BY created_at DESC, work_item_id DESC LIMIT ?"
            ),
        }
        query = queries[(state is not None, after_created_at is not None)]
        with self.ledger.read_connection() as connection:
            rows = connection.execute(
                query,
                (*params, limit),
            ).fetchall()
            items = [self._materialize_work_item(connection, row, include_children=False) for row in rows]
        return {
            "schema_version": "work_item_list.v1",
            "items": items,
            "count": len(items),
            "next_cursor": items[-1]["created_at"] if len(items) == limit else None,
            "authoritative_for_delivery_state": self.authoritative_transitions,
            "shadow_read_model": not self.authoritative_transitions,
        }

    def get_work_item_timeline(self, work_item_id: str) -> dict[str, Any]:
        self._require_enabled()
        require_stable_id(work_item_id, "work_item")
        if self.activation_guard is not None:
            self.activation_guard.assert_read_scope(work_item_id)
        with self.ledger.read_connection() as connection:
            exists = connection.execute(
                "SELECT 1 FROM work_items WHERE work_item_id=?", (work_item_id,)
            ).fetchone()
            if exists is None:
                raise WorkItemGovernanceError("WORK_ITEM_NOT_FOUND", "Work Item does not exist.")
            specs = (
                ("execution_attempt", "SELECT * FROM execution_attempts WHERE work_item_id=?", "created_at", "attempt_id"),
                ("artifact_reference", "SELECT * FROM artifact_refs WHERE work_item_id=?", "created_at", "artifact_id"),
                ("decision_record", "SELECT * FROM decision_records WHERE work_item_id=?", "created_at", "decision_id"),
                ("gate_event", "SELECT * FROM gate_events WHERE work_item_id=?", "created_at", "gate_event_id"),
                (
                    "delivery_receipt",
                    "SELECT * FROM delivery_receipts WHERE work_item_id=?",
                    "created_at",
                    "delivery_receipt_id",
                ),
                ("audit_event", "SELECT * FROM audit_events WHERE work_item_id=?", "created_at", "audit_event_id"),
                ("blocker_event", "SELECT * FROM blocker_events WHERE work_item_id=?", "created_at", "blocker_event_id"),
            )
            events: list[dict[str, Any]] = []
            for event_type, query, timestamp_field, id_field in specs:
                rows = connection.execute(
                    query,
                    (work_item_id,),
                ).fetchall()
                for row in rows:
                    events.append(
                        {
                            "event_type": event_type,
                            "event_id": row[id_field],
                            "occurred_at": row[timestamp_field],
                            "record": self._decode_row(dict(row)),
                        }
                    )
            attempt_event_rows = connection.execute(
                """
                SELECT event.*
                FROM attempt_events AS event
                JOIN execution_attempts AS attempt ON attempt.attempt_id=event.attempt_id
                WHERE attempt.work_item_id=?
                """,
                (work_item_id,),
            ).fetchall()
            for row in attempt_event_rows:
                events.append(
                    {
                        "event_type": f"attempt_{row['event_type']}",
                        "event_id": row["event_id"],
                        "occurred_at": row["created_at"],
                        "record": self._decode_row(dict(row)),
                    }
                )
        events.sort(key=lambda item: (str(item["occurred_at"]), str(item["event_id"])))
        return {
            "schema_version": "work_item_timeline.v1",
            "work_item_id": work_item_id,
            "events": events,
            "event_count": len(events),
        }

    def get_execution_attempt_dispatch_authority(
        self,
        *,
        attempt_id: str,
        work_item_id: str,
        task_version: int,
    ) -> dict[str, Any]:
        self._require_enabled()
        normalized_attempt_id = require_stable_id(attempt_id, "attempt")
        normalized_work_item_id = require_stable_id(work_item_id, "work_item")
        normalized_task_version = require_positive_integer(task_version, "task_version")
        if self.activation_guard is not None:
            self.activation_guard.assert_read_scope(normalized_work_item_id)
        with self.ledger.read_connection() as connection:
            attempt = connection.execute(
                "SELECT * FROM execution_attempts WHERE attempt_id=?",
                (normalized_attempt_id,),
            ).fetchone()
            if attempt is None:
                raise WorkItemGovernanceError("ATTEMPT_NOT_FOUND", "Execution Attempt does not exist.")
            work_item = self._work_item_row(connection, normalized_work_item_id)
        reasons: list[str] = []
        if attempt["work_item_id"] != normalized_work_item_id or int(attempt["task_version"]) != normalized_task_version:
            reasons.append("ATTEMPT_CONTEXT_MISMATCH")
        if attempt["attempt_kind"] != "runtime" or int(attempt["dispatch_authorized"]) != 1:
            reasons.append("ATTEMPT_DISPATCH_NOT_AUTHORIZED")
        if attempt["status"] not in {"claimed", "running"}:
            reasons.append("ATTEMPT_NOT_ACTIVE")
        if work_item["state"] in TERMINAL_WORK_ITEM_STATES:
            reasons.append("WORK_ITEM_TERMINAL")
        if work_item["state"] == "submitted":
            reasons.append("REVISION_GATE_REQUIRED")
        if int(work_item["current_task_version"]) != normalized_task_version:
            reasons.append("TASK_VERSION_STALE")
        if self.activation_guard is not None and not self.activation_guard.dispatch_authority_active():
            reasons.append("ACTIVATION_LEASE_INACTIVE")
        if isinstance(self.activation_guard, PilotActivationGuard) and not reasons:
            try:
                self.activation_guard.assert_attempt_dispatch_authority(
                    normalized_attempt_id,
                    normalized_work_item_id,
                    normalized_task_version,
                )
            except WorkItemGovernanceError as exc:
                reasons.append(exc.code)
        return {
            "schema_version": "execution_attempt_dispatch_authority.v1",
            "attempt_id": normalized_attempt_id,
            "work_item_id": normalized_work_item_id,
            "task_version": normalized_task_version,
            "dispatch_authorized": not reasons,
            "reason_codes": reasons,
            "creates_attempt": False,
            "writes_delivery_state": False,
        }

    # ------------------------------------------------------------------
    # Task Version and Execution/Evidence binding
    # ------------------------------------------------------------------

    def add_task_version(self, command: dict[str, Any]) -> dict[str, Any]:
        self._require_enabled()
        value = require_object(command, "command", non_empty=True)
        allowed = {"work_item_id", "task_version", "task", "source_event_key"}
        if set(value) - allowed:
            raise WorkItemGovernanceError("TASK_VERSION_FIELD_UNSUPPORTED", "Task Version command has unsupported fields.")
        work_item_id = require_stable_id(value.get("work_item_id"), "work_item")
        task_version = require_positive_integer(value.get("task_version"), "task_version")
        task = normalize_initial_task(value.get("task"))
        self._reject_sensitive_fields(task, "task")
        task_digest = canonical_sha256(task)
        source_event_key = require_text(value.get("source_event_key"), "source_event_key", max_length=1024)
        activation_command = {
            "work_item_id": work_item_id,
            "task_version": task_version,
            "task": task,
            "source_event_key": source_event_key,
        }
        created_at = isoformat_utc(self.now())
        try:
            with self._write_transaction() as connection:
                activation = self._activation_begin(
                    connection,
                    command_name="add_task_version",
                    normalized_command=activation_command,
                    source_event_key=source_event_key,
                )
                existing = connection.execute(
                    "SELECT * FROM task_versions WHERE source_event_key=?", (source_event_key,)
                ).fetchone()
                if existing is not None:
                    if (
                        existing["work_item_id"] != work_item_id
                        or existing["task_version"] != task_version
                        or existing["payload_digest"] != task_digest
                    ):
                        raise WorkItemGovernanceError("IDEMPOTENCY_CONFLICT", "Task Version event key is already in use.")
                    if activation is not None:
                        activation.authorize_replay(work_item_id=work_item_id)
                    idempotent = True
                else:
                    work_item = self._work_item_row(connection, work_item_id)
                    if work_item["state"] in TERMINAL_WORK_ITEM_STATES:
                        raise WorkItemGovernanceError("WORK_ITEM_TERMINAL", "Terminal Work Items cannot receive Task Versions.")
                    if work_item["state"] == "submitted":
                        raise WorkItemGovernanceError(
                            "REVISION_GATE_REQUIRED",
                            "A submitted Work Item must return to in_delivery through the revision Gate before a new Task Version.",
                        )
                    expected = int(work_item["current_task_version"]) + 1
                    if task_version != expected:
                        raise WorkItemGovernanceError(
                            "TASK_VERSION_SEQUENCE_INVALID",
                            "Task Version must be the next positive integer.",
                            details={"expected": expected, "actual": task_version},
                        )
                    if activation is not None:
                        activation.authorize_new(
                            work_item_id=work_item_id,
                            fact_delta={"task_versions": 1},
                            domain_fact_delta=self._activation_domain_delta(task_versions=1),
                        )
                    self._insert_task_version(
                        connection,
                        work_item_id=work_item_id,
                        task_version=task_version,
                        task=task,
                        source_event_key=source_event_key,
                        created_at=created_at,
                    )
                    connection.execute(
                        """
                        UPDATE work_items
                        SET current_task_version=?, state_version=state_version+1, updated_at=?
                        WHERE work_item_id=?
                        """,
                        (task_version, created_at, work_item_id),
                    )
                    if activation is not None:
                        activation.commit_new(work_item_id=work_item_id)
                    idempotent = False
        except sqlite3.IntegrityError as exc:
            raise self._integrity_error(exc, operation="add_task_version") from exc
        return {"task_version": self.get_work_item(work_item_id)["task_versions"][-1], "idempotent_replay": idempotent}

    def create_execution_attempt(self, command: dict[str, Any]) -> dict[str, Any]:
        self._require_enabled()
        value = require_object(command, "command", non_empty=True)
        allowed = {
            "work_item_id", "task_version", "attempt_id", "status", "objective_ref", "metadata",
            "source_event_key", "external_refs",
        }
        if set(value) - allowed:
            raise WorkItemGovernanceError("ATTEMPT_FIELD_UNSUPPORTED", "Attempt command has unsupported fields.")
        work_item_id = require_stable_id(value.get("work_item_id"), "work_item")
        task_version = require_positive_integer(value.get("task_version"), "task_version")
        attempt_id_value = value.get("attempt_id")
        attempt_id_supplied = attempt_id_value is not None
        attempt_id = new_stable_id("attempt") if attempt_id_value is None else require_stable_id(attempt_id_value, "attempt")
        status = value.get("status", "claimed")
        if status not in {"claimed", "running"}:
            raise WorkItemGovernanceError("ATTEMPT_INITIAL_STATUS_INVALID", "New Attempt status must be claimed or running.")
        metadata = require_metadata_object(value.get("metadata", {}), "metadata")
        self._reject_sensitive_fields(metadata, "metadata")
        objective_ref = optional_text(value.get("objective_ref"), "objective_ref", max_length=8192)
        source_event_key = require_text(value.get("source_event_key"), "source_event_key", max_length=1024)
        external_refs = self._normalize_external_refs(value.get("external_refs"))
        sorted_external_refs = sorted(external_refs, key=lambda item: (item["kind"], item["ref"]))
        claim_payload = {
            "work_item_id": work_item_id,
            "task_version": task_version,
            "attempt_id": attempt_id if attempt_id_supplied else None,
            "status": status,
            "objective_ref": objective_ref,
            "metadata": metadata,
            "external_refs": sorted_external_refs,
            "attempt_kind": "runtime",
            "dispatch_authorized": True,
        }
        activation_command = {**claim_payload, "source_event_key": source_event_key}
        created_at = isoformat_utc(self.now())
        try:
            with self._write_transaction() as connection:
                activation = self._activation_begin(
                    connection,
                    command_name="create_execution_attempt",
                    normalized_command=activation_command,
                    source_event_key=source_event_key,
                )
                existing = connection.execute(
                    "SELECT * FROM execution_attempts WHERE source_event_key=?", (source_event_key,)
                ).fetchone()
                if existing is not None:
                    claim_event = connection.execute(
                        "SELECT * FROM attempt_events WHERE source_event_key=? AND event_type='claim'",
                        (source_event_key,),
                    ).fetchone()
                    existing_external_refs = [
                        {"kind": str(row["association_kind"]), "ref": str(row["external_ref"])}
                        for row in connection.execute(
                            """
                            SELECT association_kind,external_ref FROM external_associations
                            WHERE attempt_id=? ORDER BY association_kind,external_ref
                            """,
                            (existing["attempt_id"],),
                        ).fetchall()
                    ]
                    immutable_mismatch = (
                        existing["work_item_id"] != work_item_id
                        or existing["task_version"] != task_version
                        or existing["attempt_kind"] != "runtime"
                        or int(existing["dispatch_authorized"]) != 1
                        or (attempt_id_supplied and existing["attempt_id"] != attempt_id)
                        or existing["objective_ref"] != objective_ref
                        or existing_external_refs != sorted_external_refs
                    )
                    event_mismatch = (
                        claim_event is not None
                        and json.loads(claim_event["payload_json"]) != claim_payload
                    )
                    legacy_mutable_mismatch = (
                        claim_event is None
                        and existing["completion_event_key"] is None
                        and (
                            existing["status"] != status
                            or json.loads(existing["metadata_json"]) != metadata
                        )
                    )
                    if immutable_mismatch or event_mismatch or legacy_mutable_mismatch:
                        raise WorkItemGovernanceError("IDEMPOTENCY_CONFLICT", "Attempt event key is already in use.")
                    attempt_id = str(existing["attempt_id"])
                    if activation is not None:
                        activation.authorize_replay(work_item_id=work_item_id)
                    idempotent = True
                else:
                    work_item = self._work_item_row(connection, work_item_id)
                    if work_item["state"] in TERMINAL_WORK_ITEM_STATES:
                        raise WorkItemGovernanceError(
                            "WORK_ITEM_TERMINAL",
                            "Terminal Work Items cannot start new runtime Attempts.",
                        )
                    if work_item["state"] == "submitted":
                        raise WorkItemGovernanceError(
                            "REVISION_GATE_REQUIRED",
                            "Submitted Work Items must return for revision before new runtime execution.",
                        )
                    if int(work_item["current_task_version"]) != task_version:
                        raise WorkItemGovernanceError(
                            "TASK_VERSION_STALE",
                            "New runtime Attempts must bind the current Task Version.",
                            details={
                                "current_task_version": int(work_item["current_task_version"]),
                                "requested_task_version": task_version,
                            },
                        )
                    self._assert_task_exists(connection, work_item_id, task_version)
                    if activation is not None:
                        activation.authorize_new(
                            work_item_id=work_item_id,
                            fact_delta={"runtime_attempts": 1},
                            domain_fact_delta=self._activation_domain_delta(
                                runtime_attempts=1,
                                attempt_events=1,
                            ),
                        )
                    connection.execute(
                        """
                        INSERT INTO execution_attempts(
                          attempt_id,schema_version,work_item_id,task_version,status,objective_ref,
                          metadata_json,source_event_key,created_at,attempt_kind,dispatch_authorized,
                          historical_reason,imported
                        ) VALUES(?,?,?,?,?,?,?,?,?,'runtime',1,NULL,0)
                        """,
                        (
                            attempt_id, SCHEMA_VERSIONS["execution_attempt"], work_item_id, task_version,
                            status, objective_ref, canonical_json(metadata), source_event_key, created_at,
                        ),
                    )
                    self._insert_external_refs(
                        connection,
                        external_refs,
                        work_item_id=work_item_id,
                        task_version=task_version,
                        attempt_id=attempt_id,
                        source_event_key=source_event_key,
                        created_at=created_at,
                    )
                    connection.execute(
                        """
                        INSERT INTO attempt_events(
                          event_id,attempt_id,event_type,source_event_key,payload_json,created_at
                        ) VALUES(?,?,'claim',?,?,?)
                        """,
                        (
                            new_stable_id("attempt_event"), attempt_id, source_event_key,
                            canonical_json(claim_payload), created_at,
                        ),
                    )
                    if activation is not None:
                        activation.commit_new(
                            work_item_id=work_item_id,
                            generated_ids={"attempt_ids": [attempt_id]},
                        )
                    idempotent = False
                row = connection.execute("SELECT * FROM execution_attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
        except sqlite3.IntegrityError as exc:
            raise self._integrity_error(exc, operation="create_execution_attempt") from exc
        return {"attempt": self._materialize_attempt(row), "idempotent_replay": idempotent}

    def register_artifact_reference(self, command: dict[str, Any]) -> dict[str, Any]:
        self._require_enabled()
        normalized = self._normalize_artifact_command(command)
        activation_command = self._activation_artifact_command(normalized)
        created_at = isoformat_utc(self.now())
        try:
            with self._write_transaction() as connection:
                activation = self._activation_begin(
                    connection,
                    command_name="register_artifact_reference",
                    normalized_command=activation_command,
                    source_event_key=normalized["source_event_key"],
                )
                existing = connection.execute(
                    "SELECT * FROM artifact_refs WHERE source_event_key=?",
                    (normalized["source_event_key"],),
                ).fetchone()
                if existing is None:
                    existing = connection.execute(
                        """
                        SELECT * FROM artifact_refs
                        WHERE work_item_id=? AND kind=? AND immutable_ref=?
                        """,
                        (
                            normalized["work_item_id"],
                            normalized["kind"],
                            normalized["immutable_ref"],
                        ),
                    ).fetchone()
                if existing is None and activation is not None:
                    activation.authorize_new(
                        work_item_id=normalized["work_item_id"],
                        fact_delta={"artifacts": 1},
                        domain_fact_delta=self._activation_domain_delta(artifacts=1),
                    )
                row, idempotent = self._insert_artifact(connection, normalized, created_at=created_at)
                if not idempotent and activation is not None:
                    activation.commit_new(
                        work_item_id=normalized["work_item_id"],
                        generated_ids={"artifact_ids": [str(row["artifact_id"])]},
                    )
                elif idempotent and activation is not None:
                    activation.authorize_replay(work_item_id=normalized["work_item_id"])
        except sqlite3.IntegrityError as exc:
            raise self._integrity_error(exc, operation="register_artifact_reference") from exc
        return {"artifact": self._materialize_artifact(row), "idempotent_replay": idempotent}

    def bind_historical_execution_attempt(self, command: dict[str, Any]) -> dict[str, Any]:
        self._require_enabled()
        self._deny_activation_command("bind_historical_execution_attempt")
        value = require_object(command, "command", non_empty=True)
        allowed = {
            "work_item_id", "task_version", "attempt_id", "status", "objective_ref", "metadata",
            "source_event_key", "external_refs", "historical_reason", "imported",
        }
        if set(value) - allowed:
            raise WorkItemGovernanceError(
                "HISTORICAL_ATTEMPT_FIELD_UNSUPPORTED",
                "Historical Attempt command has unsupported fields.",
            )
        if value.get("imported") is not True:
            raise WorkItemGovernanceError(
                "HISTORICAL_ATTEMPT_IMPORT_REQUIRED",
                "Historical Attempt binding must be explicitly marked imported=true.",
            )
        work_item_id = require_stable_id(value.get("work_item_id"), "work_item")
        task_version = require_positive_integer(value.get("task_version"), "task_version")
        supplied_attempt_id = value.get("attempt_id")
        attempt_id_supplied = supplied_attempt_id is not None
        attempt_id = (
            new_stable_id("attempt")
            if supplied_attempt_id is None
            else require_stable_id(supplied_attempt_id, "attempt")
        )
        status = value.get("status")
        if status not in {"completed", "failed", "cancelled"}:
            raise WorkItemGovernanceError(
                "HISTORICAL_ATTEMPT_STATUS_INVALID",
                "Historical Attempts must be imported in a terminal runtime status.",
            )
        objective_ref = optional_text(value.get("objective_ref"), "objective_ref", max_length=8192)
        metadata = require_metadata_object(value.get("metadata", {}), "metadata")
        self._reject_sensitive_fields(metadata, "metadata")
        historical_reason = str(require_text(value.get("historical_reason"), "historical_reason"))
        source_event_key = str(require_text(value.get("source_event_key"), "source_event_key", max_length=1024))
        external_refs = sorted(
            self._normalize_external_refs(value.get("external_refs")),
            key=lambda item: (item["kind"], item["ref"]),
        )
        payload = {
            "work_item_id": work_item_id,
            "task_version": task_version,
            "attempt_id": attempt_id if attempt_id_supplied else None,
            "status": status,
            "objective_ref": objective_ref,
            "metadata": metadata,
            "external_refs": external_refs,
            "historical_reason": historical_reason,
            "imported": True,
            "attempt_kind": "historical",
            "dispatch_authorized": False,
        }
        created_at = isoformat_utc(self.now())
        try:
            with self._write_transaction() as connection:
                existing = connection.execute(
                    "SELECT * FROM execution_attempts WHERE source_event_key=?",
                    (source_event_key,),
                ).fetchone()
                if existing is not None:
                    event = connection.execute(
                        "SELECT * FROM attempt_events WHERE source_event_key=? AND event_type='historical_binding'",
                        (source_event_key,),
                    ).fetchone()
                    if event is None or json.loads(event["payload_json"]) != payload:
                        raise WorkItemGovernanceError(
                            "IDEMPOTENCY_CONFLICT",
                            "Historical Attempt event key is already in use.",
                        )
                    attempt_id = str(existing["attempt_id"])
                    idempotent = True
                else:
                    self._assert_task_exists(connection, work_item_id, task_version)
                    connection.execute(
                        """
                        INSERT INTO execution_attempts(
                          attempt_id,schema_version,work_item_id,task_version,status,objective_ref,
                          metadata_json,source_event_key,created_at,completed_at,attempt_kind,
                          dispatch_authorized,historical_reason,imported
                        ) VALUES(?,?,?,?,?,?,?,?,?,?,'historical',0,?,1)
                        """,
                        (
                            attempt_id, SCHEMA_VERSIONS["execution_attempt"], work_item_id, task_version,
                            status, objective_ref, canonical_json(metadata), source_event_key,
                            created_at, created_at, historical_reason,
                        ),
                    )
                    self._insert_external_refs(
                        connection,
                        external_refs,
                        work_item_id=work_item_id,
                        task_version=task_version,
                        attempt_id=attempt_id,
                        source_event_key=source_event_key,
                        created_at=created_at,
                    )
                    connection.execute(
                        """
                        INSERT INTO attempt_events(
                          event_id,attempt_id,event_type,source_event_key,payload_json,created_at
                        ) VALUES(?,?,'historical_binding',?,?,?)
                        """,
                        (
                            new_stable_id("attempt_event"), attempt_id, source_event_key,
                            canonical_json(payload), created_at,
                        ),
                    )
                    idempotent = False
                row = connection.execute(
                    "SELECT * FROM execution_attempts WHERE attempt_id=?",
                    (attempt_id,),
                ).fetchone()
        except sqlite3.IntegrityError as exc:
            raise self._integrity_error(exc, operation="bind_historical_execution_attempt") from exc
        return {
            "attempt": self._materialize_attempt(row),
            "idempotent_replay": idempotent,
            "runtime_dispatch_authorized": False,
            "writes_delivery_state": False,
        }

    def complete_execution_attempt(self, command: dict[str, Any]) -> dict[str, Any]:
        self._require_enabled()
        value = require_object(command, "command", non_empty=True)
        allowed = {"attempt_id", "status", "source_event_key", "metadata", "artifacts"}
        if set(value) - allowed:
            raise WorkItemGovernanceError("ATTEMPT_COMPLETION_FIELD_UNSUPPORTED", "Completion has unsupported fields.")
        attempt_id = require_stable_id(value.get("attempt_id"), "attempt")
        status = value.get("status")
        if status not in {"completed", "failed", "cancelled"}:
            raise WorkItemGovernanceError("ATTEMPT_COMPLETION_STATUS_INVALID", "Completion status is invalid.")
        source_event_key = require_text(value.get("source_event_key"), "source_event_key", max_length=1024)
        metadata = require_metadata_object(value.get("metadata", {}), "metadata")
        self._reject_sensitive_fields(metadata, "metadata")
        artifact_values = value.get("artifacts", [])
        if not isinstance(artifact_values, list) or len(artifact_values) > 1024:
            raise WorkItemGovernanceError("ARTIFACT_LIST_INVALID", "Completion artifacts must be a bounded list.")
        normalized_artifacts = [self._normalize_artifact_command(item) for item in artifact_values]
        completion_payload = {
            "status": status,
            "metadata": metadata,
            "artifacts": [
                {
                    key: child
                    for key, child in artifact.items()
                    if key != "artifact_id" and not key.startswith("_")
                }
                for artifact in normalized_artifacts
            ],
        }
        activation_command = {
            "attempt_id": attempt_id,
            "status": status,
            "source_event_key": source_event_key,
            "metadata": metadata,
            "artifacts": [
                self._activation_artifact_command(artifact)
                for artifact in normalized_artifacts
            ],
        }
        completed_at = isoformat_utc(self.now())
        event_id = new_stable_id("attempt_event")
        try:
            with self._write_transaction() as connection:
                activation = self._activation_begin(
                    connection,
                    command_name="complete_execution_attempt",
                    normalized_command=activation_command,
                    source_event_key=source_event_key,
                )
                attempt = connection.execute(
                    "SELECT * FROM execution_attempts WHERE attempt_id=?", (attempt_id,)
                ).fetchone()
                if attempt is None:
                    raise WorkItemGovernanceError("ATTEMPT_NOT_FOUND", "Execution Attempt does not exist.")
                if attempt["attempt_kind"] != "runtime" or int(attempt["dispatch_authorized"]) != 1:
                    raise WorkItemGovernanceError(
                        "HISTORICAL_ATTEMPT_NOT_COMPLETABLE",
                        "Historical Attempts are immutable bindings and cannot receive runtime completion.",
                    )
                prior = connection.execute(
                    "SELECT * FROM attempt_events WHERE source_event_key=?", (source_event_key,)
                ).fetchone()
                if prior is not None:
                    if (
                        prior["attempt_id"] != attempt_id
                        or json.loads(prior["payload_json"]) != completion_payload
                    ):
                        raise WorkItemGovernanceError("IDEMPOTENCY_CONFLICT", "Completion event key is already in use.")
                    if activation is not None:
                        activation.authorize_replay(work_item_id=str(attempt["work_item_id"]))
                    idempotent = True
                else:
                    if attempt["completion_event_key"] is not None:
                        raise WorkItemGovernanceError(
                            "ATTEMPT_ALREADY_COMPLETED",
                            "Execution Attempt is immutable after its first completion event.",
                        )
                    for artifact in normalized_artifacts:
                        if artifact["attempt_id"] != attempt_id:
                            raise WorkItemGovernanceError(
                                "ARTIFACT_ATTEMPT_MISMATCH",
                                "Completion artifact must reference the completed Attempt.",
                            )
                        if artifact["work_item_id"] != attempt["work_item_id"] or artifact["task_version"] != attempt["task_version"]:
                            raise WorkItemGovernanceError(
                                "ARTIFACT_CONTEXT_MISMATCH",
                                "Completion artifact Work Item/Task Version does not match the Attempt.",
                            )
                    new_artifact_count = self._count_new_completion_artifacts(
                        connection,
                        normalized_artifacts,
                    )
                    if activation is not None:
                        activation.authorize_new(
                            work_item_id=str(attempt["work_item_id"]),
                            fact_delta={"artifacts": new_artifact_count},
                            domain_fact_delta=self._activation_domain_delta(
                                attempt_events=1,
                                artifacts=new_artifact_count,
                            ),
                        )
                    connection.execute(
                        """
                        UPDATE execution_attempts
                        SET status=?, completion_event_key=?, completed_at=?,
                            metadata_json=?
                        WHERE attempt_id=? AND completion_event_key IS NULL
                        """,
                        (status, source_event_key, completed_at, canonical_json(metadata), attempt_id),
                    )
                    connection.execute(
                        """
                        INSERT INTO attempt_events(event_id,attempt_id,event_type,source_event_key,payload_json,created_at)
                        VALUES(?,?,?,?,?,?)
                        """,
                        (
                            event_id,
                            attempt_id,
                            "completion",
                            source_event_key,
                            canonical_json(completion_payload),
                            completed_at,
                        ),
                    )
                    inserted_artifact_ids: list[str] = []
                    for artifact in normalized_artifacts:
                        artifact_row, artifact_replay = self._insert_artifact(
                            connection,
                            artifact,
                            created_at=completed_at,
                        )
                        if not artifact_replay:
                            inserted_artifact_ids.append(str(artifact_row["artifact_id"]))
                    if activation is not None:
                        activation.commit_new(
                            work_item_id=str(attempt["work_item_id"]),
                            generated_ids={"artifact_ids": inserted_artifact_ids},
                        )
                    idempotent = False
                row = connection.execute("SELECT * FROM execution_attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
                artifacts = connection.execute(
                    "SELECT * FROM artifact_refs WHERE attempt_id=? ORDER BY created_at, artifact_id", (attempt_id,)
                ).fetchall()
        except sqlite3.IntegrityError as exc:
            raise self._integrity_error(exc, operation="complete_execution_attempt") from exc
        return {
            "attempt": self._materialize_attempt(row),
            "artifacts": [self._materialize_artifact(item) for item in artifacts],
            "idempotent_replay": idempotent,
            "writes_delivery_state": False,
        }

    # ------------------------------------------------------------------
    # Phase 3: append-only Decisions
    # ------------------------------------------------------------------

    def record_review_decision(
        self,
        command: dict[str, Any],
        *,
        principal_context: PrincipalContext | None,
    ) -> dict[str, Any]:
        self._require_enabled()
        value = require_object(command, "command", non_empty=True)
        if set(value) & {"actor", "authority_basis", "principal_context"}:
            raise WorkItemGovernanceError(
                "CALLER_ASSERTED_AUTHORITY_FORBIDDEN",
                "Decision identity and authority must be derived from PrincipalContext.",
            )
        allowed = {
            "decision_id", "work_item_id", "task_version", "action", "evidence_artifact_ids",
            "reason", "supersedes_decision_id", "source_event_key",
        }
        if set(value) - allowed:
            raise WorkItemGovernanceError("DECISION_FIELD_UNSUPPORTED", "Decision contains unsupported fields.")
        decision_value = value.get("decision_id")
        decision_id_supplied = decision_value is not None
        decision_id = new_stable_id("decision") if decision_value is None else require_stable_id(decision_value, "decision")
        work_item_id = require_stable_id(value.get("work_item_id"), "work_item")
        task_version = require_positive_integer(value.get("task_version"), "task_version")
        action = value.get("action")
        if action not in DECISION_ACTIONS:
            raise WorkItemGovernanceError("DECISION_ACTION_INVALID", "Review Decision action is invalid.")
        principal, actor, authority_basis = authorize_principal(
            principal_context,
            permission_for_decision(str(action)),
        )
        artifact_ids = self._normalize_id_list(value.get("evidence_artifact_ids", []), "artifact", "evidence_artifact_ids")
        if action not in {"cancel", "reject", "request_changes"} and not artifact_ids:
            raise WorkItemGovernanceError(
                "DECISION_EVIDENCE_REQUIRED",
                "Approval/submission Decisions require Artifact evidence.",
            )
        reason = require_text(value.get("reason"), "reason")
        supersedes = value.get("supersedes_decision_id")
        if supersedes is not None:
            supersedes = require_stable_id(supersedes, "decision")
            if supersedes == decision_id:
                raise WorkItemGovernanceError("DECISION_SUPERSEDES_SELF", "Decision cannot supersede itself.")
        source_event_key = require_text(value.get("source_event_key"), "source_event_key", max_length=1024)
        activation_command = {
            "decision_id": decision_id if decision_id_supplied else None,
            "work_item_id": work_item_id,
            "task_version": task_version,
            "action": action,
            "evidence_artifact_ids": artifact_ids,
            "reason": reason,
            "supersedes_decision_id": supersedes,
            "source_event_key": source_event_key,
            "actor": actor,
            "authority_basis": authority_basis,
            "principal_context": principal,
        }
        created_at = isoformat_utc(self.now())
        try:
            with self._write_transaction() as connection:
                activation = self._activation_begin(
                    connection,
                    command_name="record_review_decision",
                    normalized_command=activation_command,
                    source_event_key=source_event_key,
                    principal_context=principal_context,
                )
                existing = connection.execute(
                    "SELECT * FROM decision_records WHERE source_event_key=?", (source_event_key,)
                ).fetchone()
                if existing is not None:
                    if (
                        existing["work_item_id"] != work_item_id
                        or existing["task_version"] != task_version
                        or (decision_id_supplied and existing["decision_id"] != decision_id)
                        or existing["action"] != action
                        or json.loads(existing["actor_json"]) != actor
                        or json.loads(existing["evidence_artifact_ids_json"]) != artifact_ids
                        or json.loads(existing["authority_basis_json"]) != authority_basis
                        or json.loads(existing["principal_json"]) != principal
                        or existing["reason"] != reason
                        or existing["supersedes_decision_id"] != supersedes
                    ):
                        raise WorkItemGovernanceError("IDEMPOTENCY_CONFLICT", "Decision event key is already in use.")
                    row = existing
                    if activation is not None:
                        activation.authorize_replay(work_item_id=work_item_id)
                    idempotent = True
                else:
                    work_item = self._work_item_row(connection, work_item_id)
                    if work_item["state"] in TERMINAL_WORK_ITEM_STATES:
                        raise WorkItemGovernanceError(
                            "WORK_ITEM_TERMINAL",
                            "Terminal Work Items cannot receive new Review Decisions.",
                        )
                    if int(work_item["current_task_version"]) != task_version:
                        raise WorkItemGovernanceError("TASK_VERSION_STALE", "Decision must bind the current Task Version.")
                    self._assert_artifacts(connection, artifact_ids, work_item_id, task_version)
                    if supersedes is not None:
                        prior = connection.execute(
                            "SELECT * FROM decision_records WHERE decision_id=?", (supersedes,)
                        ).fetchone()
                        if prior is None or prior["work_item_id"] != work_item_id or prior["task_version"] != task_version:
                            raise WorkItemGovernanceError(
                                "SUPERSEDED_DECISION_INVALID",
                                "Superseded Decision must exist in the same Work Item and Task Version.",
                            )
                    if activation is not None:
                        activation.authorize_new(
                            work_item_id=work_item_id,
                            fact_delta={"decisions": 1},
                            domain_fact_delta=self._activation_domain_delta(decisions=1),
                        )
                    connection.execute(
                        """
                        INSERT INTO decision_records(
                          decision_id,schema_version,work_item_id,task_version,actor_json,action,
                          evidence_artifact_ids_json,authority_basis_json,reason,supersedes_decision_id,
                          source_event_key,created_at,principal_json
                        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            decision_id, SCHEMA_VERSIONS["decision_record"], work_item_id, task_version,
                            canonical_json(actor), action, canonical_json(artifact_ids), canonical_json(authority_basis),
                            reason, supersedes, source_event_key, created_at, canonical_json(principal),
                        ),
                    )
                    row = connection.execute(
                        "SELECT * FROM decision_records WHERE decision_id=?", (decision_id,)
                    ).fetchone()
                    if activation is not None:
                        activation.commit_new(
                            work_item_id=work_item_id,
                            generated_ids={"decision_ids": [decision_id]},
                        )
                    idempotent = False
        except sqlite3.IntegrityError as exc:
            raise self._integrity_error(exc, operation="record_review_decision") from exc
        return {"decision": self._materialize_decision(row), "idempotent_replay": idempotent}

    # ------------------------------------------------------------------
    # Transactional Gate transitions
    # ------------------------------------------------------------------

    def preview_work_item_transition(
        self,
        command: dict[str, Any],
        *,
        principal_context: PrincipalContext | None,
        ttl_seconds: int = 300,
    ) -> dict[str, Any]:
        self._require_enabled()
        self._require_gate_enabled()
        normalized = self._normalize_transition_command(command)
        with self.ledger.read_connection() as connection:
            work_item = self._work_item_row(connection, normalized["work_item_id"])
            normalized = self._bind_transition_authority(
                normalized,
                principal_context,
                current_state=str(work_item["state"]),
            )
            evaluation = self._evaluate_transition(connection, work_item, normalized)
        self._activation_preview("apply_work_item_transition", normalized)
        gate_event_id = new_stable_id("gate_event")
        preview = self.previews.issue(
            "work_item_transition",
            normalized,
            ttl_seconds=ttl_seconds,
            generated_ids={"gate_event_id": gate_event_id},
        )
        return {
            "status": "preview_ready",
            "preview": preview,
            "proposed_gate_event_id": gate_event_id,
            "evaluation": evaluation,
            "state_changed": False,
            "gate_mode": self.gate_mode,
        }

    def apply_work_item_transition(
        self,
        preview: dict[str, Any],
        *,
        principal_context: PrincipalContext | None,
    ) -> dict[str, Any]:
        self._require_enabled()
        self._require_gate_enabled()
        verified = self.previews.verify(preview, expected_operation="work_item_transition")
        command = self._verify_signed_transition_authority(verified["command"], principal_context)
        if not self.authoritative_transitions:
            with self.ledger.read_connection() as connection:
                work_item = self._work_item_row(connection, command["work_item_id"])
                evaluation = self._evaluate_transition(connection, work_item, command)
            return {
                "status": "shadow_evaluated",
                "gate_mode": "shadow",
                "evaluation": evaluation,
                "state_changed": False,
                "gate_event_written": False,
            }

        gate_event_id = require_stable_id(
            verified.get("generated_ids", {}).get("gate_event_id"), "gate_event"
        )
        preview_id = require_stable_id(verified.get("preview_id"), "preview")
        created_at = isoformat_utc(self.now())
        command_digest = canonical_sha256(command)
        try:
            with self._write_transaction() as connection:
                activation = self._activation_begin(
                    connection,
                    command_name="apply_work_item_transition",
                    normalized_command=command,
                    source_event_key=command.get("idempotency_key") or preview_id,
                    principal_context=principal_context,
                )
                existing = connection.execute(
                    "SELECT * FROM gate_events WHERE preview_id=?", (preview_id,)
                ).fetchone()
                if existing is None and command.get("idempotency_key") is not None:
                    existing = connection.execute(
                        "SELECT * FROM gate_events WHERE idempotency_key=?", (command["idempotency_key"],)
                    ).fetchone()
                if existing is not None:
                    if existing["command_digest"] != command_digest:
                        raise WorkItemGovernanceError(
                            "IDEMPOTENCY_CONFLICT",
                            "Gate idempotency key is already bound to different content.",
                        )
                    gate_row = existing
                    if activation is not None:
                        activation.authorize_replay(work_item_id=command["work_item_id"])
                    idempotent = True
                else:
                    work_item = self._work_item_row(connection, command["work_item_id"])
                    evaluation = self._evaluate_transition(connection, work_item, command)
                    outcome = "transition_applied" if evaluation["eligible"] else "transition_rejected"
                    reason_code = str(evaluation["reason_code"])
                    requirements = TRANSITION_REQUIREMENTS.get(
                        (str(work_item["state"]), command["target_state"]),
                        {},
                    )
                    transition_result = str(requirements.get("transition_result", "state_advanced"))
                    if activation is not None:
                        if outcome == "transition_applied":
                            quota_delta = {
                                "applied_gate_events": 1,
                                "gate_events_total": 1,
                            }
                            domain_delta = self._activation_domain_delta(
                                applied_gate_events=1,
                                audit_events=1,
                                outbox_events=1,
                                acceptance_manifests=(1 if command["target_state"] == "accepted" else 0),
                            )
                        else:
                            quota_delta = {
                                "rejected_gate_events": 1,
                                "gate_events_total": 1,
                            }
                            domain_delta = self._activation_domain_delta(
                                rejected_gate_events=1,
                                audit_events=1,
                                outbox_events=1,
                            )
                        activation.authorize_new(
                            work_item_id=command["work_item_id"],
                            fact_delta=quota_delta,
                            domain_fact_delta=domain_delta,
                        )
                    if evaluation["eligible"]:
                        cursor = connection.execute(
                            """
                            UPDATE work_items
                            SET state=?, state_version=state_version+1, updated_at=?
                            WHERE work_item_id=? AND state=? AND state_version=? AND current_task_version=?
                            """,
                            (
                                command["target_state"],
                                created_at,
                                command["work_item_id"],
                                work_item["state"],
                                command["expected_state_version"],
                                command["task_version"],
                            ),
                        )
                        if cursor.rowcount != 1:
                            outcome = "transition_rejected"
                            reason_code = "CAS_CONFLICT"
                    connection.execute(
                        """
                        INSERT INTO gate_events(
                          gate_event_id,schema_version,work_item_id,task_version,from_state,target_state,
                          expected_state_version,outcome,reason_code,decision_ids_json,
                          evidence_artifact_ids_json,authority_basis_json,command_digest,preview_id,
                          idempotency_key,created_at,principal_json,transition_result
                        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            gate_event_id,
                            SCHEMA_VERSIONS["gate_event"],
                            command["work_item_id"],
                            command["task_version"],
                            work_item["state"],
                            command["target_state"],
                            command["expected_state_version"],
                            outcome,
                            reason_code,
                            canonical_json(command["decision_ids"]),
                            canonical_json(command["evidence_artifact_ids"]),
                            canonical_json(command["authority_basis"]),
                            command_digest,
                            preview_id,
                            command.get("idempotency_key"),
                            created_at,
                            canonical_json(command["principal_context"]),
                            transition_result,
                        ),
                    )
                    if outcome == "transition_applied" and command["target_state"] == "accepted":
                        self._insert_acceptance_manifest(
                            connection,
                            gate_event_id=gate_event_id,
                            work_item_id=command["work_item_id"],
                            task_version=command["task_version"],
                            accepted_state_version=command["expected_state_version"] + 1,
                            artifact_ids=command["evidence_artifact_ids"],
                            decision_ids=command["decision_ids"],
                            principal=command["principal_context"],
                            created_at=created_at,
                        )
                    self._insert_audit_event(
                        connection,
                        work_item_id=command["work_item_id"],
                        task_version=command["task_version"],
                        event_type=outcome,
                        actor=command["actor"],
                        payload={
                            "gate_event_id": gate_event_id,
                            "from_state": work_item["state"],
                            "target_state": command["target_state"],
                            "reason_code": reason_code,
                            "transition_result": transition_result,
                            "command_digest": command_digest,
                        },
                        source_event_key=f"gate:{gate_event_id}",
                        created_at=created_at,
                    )
                    self._insert_outbox_event(
                        connection,
                        work_item_id=command["work_item_id"],
                        event_type=outcome,
                        dedupe_key=f"gate:{gate_event_id}",
                        payload={
                            "gate_event_id": gate_event_id,
                            "work_item_id": command["work_item_id"],
                            "task_version": command["task_version"],
                            "from_state": work_item["state"],
                            "target_state": command["target_state"],
                            "reason_code": reason_code,
                            "transition_result": transition_result,
                        },
                        created_at=created_at,
                    )
                    gate_row = connection.execute(
                        "SELECT * FROM gate_events WHERE gate_event_id=?", (gate_event_id,)
                    ).fetchone()
                    if activation is not None:
                        activation.commit_new(
                            work_item_id=command["work_item_id"],
                            event_type=(
                                "command_committed"
                                if outcome == "transition_applied"
                                else "domain_rejected"
                            ),
                            generated_ids={"gate_event_ids": [gate_event_id]},
                        )
                    idempotent = False
        except sqlite3.IntegrityError as exc:
            raise self._integrity_error(exc, operation="apply_work_item_transition") from exc
        gate = self._materialize_gate(gate_row)
        return {
            "status": gate["outcome"],
            "gate_mode": "authoritative",
            "gate_event": gate,
            "state_changed": gate["outcome"] == "transition_applied",
            "idempotent_replay": idempotent,
            "work_item": self.get_work_item(command["work_item_id"]),
        }

    def _normalize_transition_command(self, value: Any) -> dict[str, Any]:
        command = require_object(value, "command", non_empty=True)
        if set(command) & {"actor", "authority_basis", "principal_context"}:
            raise WorkItemGovernanceError(
                "CALLER_ASSERTED_AUTHORITY_FORBIDDEN",
                "Gate identity and authority must be derived from PrincipalContext.",
            )
        allowed = {
            "work_item_id", "task_version", "target_state", "expected_state_version", "decision_ids",
            "evidence_artifact_ids", "idempotency_key",
        }
        unknown = sorted(set(command) - allowed)
        if unknown:
            raise WorkItemGovernanceError(
                "TRANSITION_FIELD_UNSUPPORTED",
                "Transition command contains unsupported fields.",
                details={"unsupported_fields": unknown},
            )
        target_state = command.get("target_state")
        if target_state not in WORK_ITEM_STATES:
            raise WorkItemGovernanceError("TARGET_STATE_INVALID", "Transition target state is invalid.")
        normalized = {
            "work_item_id": require_stable_id(command.get("work_item_id"), "work_item"),
            "task_version": require_positive_integer(command.get("task_version"), "task_version"),
            "target_state": target_state,
            "expected_state_version": require_non_negative_integer(
                command.get("expected_state_version"), "expected_state_version"
            ),
            "decision_ids": self._normalize_id_list(command.get("decision_ids", []), "decision", "decision_ids"),
            "evidence_artifact_ids": self._normalize_id_list(
                command.get("evidence_artifact_ids", []), "artifact", "evidence_artifact_ids"
            ),
            "idempotency_key": optional_text(command.get("idempotency_key"), "idempotency_key", max_length=1024),
        }
        canonical_sha256(normalized)
        return normalized

    def _bind_transition_authority(
        self,
        command: dict[str, Any],
        principal_context: PrincipalContext | None,
        *,
        current_state: str,
    ) -> dict[str, Any]:
        requirements = TRANSITION_REQUIREMENTS.get((current_state, command["target_state"]))
        permission = (
            str(requirements["authority"])
            if requirements is not None
            else self._fallback_transition_permission(current_state, command["target_state"])
        )
        principal, actor, authority_basis = authorize_principal(principal_context, permission)
        return {
            **command,
            "actor": actor,
            "authority_basis": authority_basis,
            "principal_context": principal,
        }

    def _verify_signed_transition_authority(
        self,
        value: Any,
        principal_context: PrincipalContext | None,
    ) -> dict[str, Any]:
        signed = require_object(value, "signed_transition", non_empty=True)
        public_fields = {
            "work_item_id", "task_version", "target_state", "expected_state_version", "decision_ids",
            "evidence_artifact_ids", "idempotency_key",
        }
        expected_fields = public_fields | {"actor", "authority_basis", "principal_context"}
        if set(signed) != expected_fields:
            raise WorkItemGovernanceError(
                "SIGNED_TRANSITION_SHAPE_INVALID",
                "Signed transition authority fields are missing or unexpected.",
            )
        normalized = self._normalize_transition_command(
            {field: signed[field] for field in public_fields}
        )
        authority = signed.get("authority_basis")
        if not isinstance(authority, dict) or not isinstance(authority.get("authority"), str):
            raise WorkItemGovernanceError(
                "SIGNED_TRANSITION_AUTHORITY_INVALID",
                "Signed transition authority is invalid.",
            )
        principal, actor, authority_basis = authorize_principal(
            principal_context,
            str(authority["authority"]),
        )
        verified = {
            **normalized,
            "actor": actor,
            "authority_basis": authority_basis,
            "principal_context": principal,
        }
        if verified != signed:
            raise WorkItemGovernanceError(
                "PREVIEW_PRINCIPAL_MISMATCH",
                "Apply Principal does not match the Principal bound to the signed preview.",
            )
        return verified

    @staticmethod
    def _fallback_transition_permission(current_state: str, target_state: str) -> str:
        if current_state == "submitted" and target_state == "in_delivery":
            return "work_item.return_for_revision"
        permissions = {
            "ready": "work_item.ready",
            "in_delivery": "work_item.start_delivery",
            "submitted": "work_item.submit",
            "accepted": "work_item.accept",
            "cancelled": "work_item.cancel",
        }
        return permissions.get(target_state, "work_item.approve")

    def _evaluate_transition(
        self,
        connection: sqlite3.Connection,
        work_item: sqlite3.Row,
        command: dict[str, Any],
    ) -> dict[str, Any]:
        current_state = str(work_item["state"])
        target_state = command["target_state"]
        if current_state in TERMINAL_WORK_ITEM_STATES:
            return self._transition_evaluation(False, "TERMINAL_STATE", current_state, target_state)
        if not can_transition(current_state, target_state):
            return self._transition_evaluation(False, "TRANSITION_NOT_ALLOWED", current_state, target_state)
        if int(work_item["state_version"]) != command["expected_state_version"]:
            return self._transition_evaluation(
                False,
                "STATE_VERSION_STALE",
                current_state,
                target_state,
                expected=command["expected_state_version"],
                actual=int(work_item["state_version"]),
            )
        if int(work_item["current_task_version"]) != command["task_version"]:
            return self._transition_evaluation(
                False,
                "TASK_VERSION_STALE",
                current_state,
                target_state,
                expected=command["task_version"],
                actual=int(work_item["current_task_version"]),
            )
        requirements = TRANSITION_REQUIREMENTS.get((current_state, target_state))
        if requirements is None:
            return self._transition_evaluation(False, "TRANSITION_POLICY_MISSING", current_state, target_state)
        try:
            normalize_authority_basis(
                command["authority_basis"], expected_authority=str(requirements["authority"])
            )
        except WorkItemGovernanceError as exc:
            return self._transition_evaluation(False, exc.code, current_state, target_state, **exc.details)
        if requirements["blockers_must_be_clear"]:
            blockers = self._active_blocker_rows(connection, command["work_item_id"])
            if blockers:
                return self._transition_evaluation(
                    False,
                    "ACTIVE_BLOCKERS",
                    current_state,
                    target_state,
                    blocker_ids=[str(row["blocker_id"]) for row in blockers],
                )
        try:
            self._assert_artifacts(
                connection,
                command["evidence_artifact_ids"],
                command["work_item_id"],
                command["task_version"],
            )
        except WorkItemGovernanceError as exc:
            return self._transition_evaluation(False, exc.code, current_state, target_state, **exc.details)
        if requirements["evidence_required"] and not command["evidence_artifact_ids"]:
            return self._transition_evaluation(False, "EVIDENCE_REQUIRED", current_state, target_state)
        if target_state == "accepted":
            active_attempts = connection.execute(
                """
                SELECT attempt_id FROM execution_attempts
                WHERE work_item_id=? AND task_version=? AND attempt_kind='runtime'
                  AND status IN ('claimed','running')
                ORDER BY attempt_id
                """,
                (command["work_item_id"], command["task_version"]),
            ).fetchall()
            if active_attempts:
                return self._transition_evaluation(
                    False,
                    "ACTIVE_EXECUTION_ATTEMPTS",
                    current_state,
                    target_state,
                    attempt_ids=[str(row["attempt_id"]) for row in active_attempts],
                )
        required_actions = requirements["decision_actions"]
        if required_actions:
            try:
                decisions = self._assert_decisions(
                    connection,
                    command["decision_ids"],
                    command["work_item_id"],
                    command["task_version"],
                )
            except WorkItemGovernanceError as exc:
                return self._transition_evaluation(False, exc.code, current_state, target_state, **exc.details)
            matching = [row for row in decisions if row["action"] in required_actions]
            if not matching:
                return self._transition_evaluation(
                    False,
                    "REQUIRED_DECISION_MISSING",
                    current_state,
                    target_state,
                    required_actions=sorted(required_actions),
                )
            evidence_set = set(command["evidence_artifact_ids"])
            if not any(set(json.loads(row["evidence_artifact_ids_json"])).issubset(evidence_set) for row in matching):
                return self._transition_evaluation(
                    False,
                    "DECISION_EVIDENCE_MISMATCH",
                    current_state,
                    target_state,
                )
        return self._transition_evaluation(True, "ELIGIBLE", current_state, target_state)

    @staticmethod
    def _transition_evaluation(
        eligible: bool,
        reason_code: str,
        current_state: str,
        target_state: str,
        **details: Any,
    ) -> dict[str, Any]:
        return {
            "eligible": eligible,
            "reason_code": reason_code,
            "current_state": current_state,
            "target_state": target_state,
            "details": details,
            "runner_status_considered": False,
            "connector_status_considered": False,
            "stable_promotion_considered": False,
            "product_submission_considered": False,
        }

    # ------------------------------------------------------------------
    # Independent blocker condition
    # ------------------------------------------------------------------

    def apply_blocker(self, command: dict[str, Any]) -> dict[str, Any]:
        self._deny_activation_command("apply_blocker")
        return self._record_blocker_event(command, event_type="blocker_applied")

    def clear_blocker(self, command: dict[str, Any]) -> dict[str, Any]:
        self._deny_activation_command("clear_blocker")
        return self._record_blocker_event(command, event_type="blocker_cleared")

    def _record_blocker_event(self, command: dict[str, Any], *, event_type: str) -> dict[str, Any]:
        self._assert_internal_activation_write_denied("record_blocker_event")
        self._require_enabled()
        value = require_object(command, "command", non_empty=True)
        allowed = {"blocker_id", "work_item_id", "task_version", "reason", "actor", "source_event_key"}
        if set(value) - allowed:
            raise WorkItemGovernanceError("BLOCKER_FIELD_UNSUPPORTED", "Blocker command has unsupported fields.")
        blocker_value = value.get("blocker_id")
        blocker_id_supplied = blocker_value is not None
        if event_type == "blocker_cleared" and blocker_value is None:
            raise WorkItemGovernanceError("BLOCKER_ID_REQUIRED", "Clearing a blocker requires blocker_id.")
        blocker_id = new_stable_id("blocker") if blocker_value is None else require_stable_id(blocker_value, "blocker")
        work_item_id = require_stable_id(value.get("work_item_id"), "work_item")
        task_version = require_positive_integer(value.get("task_version"), "task_version")
        reason = require_text(value.get("reason"), "reason")
        actor = normalize_actor(value.get("actor"))
        source_event_key = require_text(value.get("source_event_key"), "source_event_key", max_length=1024)
        created_at = isoformat_utc(self.now())
        event_id = new_stable_id("blocker_event")
        try:
            with self._write_transaction() as connection:
                existing = connection.execute(
                    "SELECT * FROM blocker_events WHERE source_event_key=?", (source_event_key,)
                ).fetchone()
                if existing is not None:
                    if not blocker_id_supplied:
                        blocker_id = str(existing["blocker_id"])
                    if (
                        existing["blocker_id"] != blocker_id
                        or existing["work_item_id"] != work_item_id
                        or int(existing["task_version"]) != task_version
                        or existing["event_type"] != event_type
                        or existing["reason"] != reason
                        or json.loads(existing["actor_json"]) != actor
                    ):
                        raise WorkItemGovernanceError("IDEMPOTENCY_CONFLICT", "Blocker event key is already in use.")
                    row = existing
                    idempotent = True
                else:
                    work_item = self._work_item_row(connection, work_item_id)
                    if int(work_item["current_task_version"]) != task_version:
                        raise WorkItemGovernanceError("TASK_VERSION_STALE", "Blocker must bind the current Task Version.")
                    active = {str(row["blocker_id"]): row for row in self._active_blocker_rows(connection, work_item_id)}
                    if event_type == "blocker_applied" and blocker_id in active:
                        raise WorkItemGovernanceError("BLOCKER_ALREADY_ACTIVE", "Blocker is already active.")
                    if event_type == "blocker_cleared" and blocker_id not in active:
                        raise WorkItemGovernanceError("BLOCKER_NOT_ACTIVE", "Only an active blocker can be cleared.")
                    connection.execute(
                        """
                        INSERT INTO blocker_events(
                          blocker_event_id,blocker_id,work_item_id,task_version,event_type,reason,
                          actor_json,source_event_key,created_at
                        ) VALUES(?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            event_id, blocker_id, work_item_id, task_version, event_type, reason,
                            canonical_json(actor), source_event_key, created_at,
                        ),
                    )
                    self._insert_audit_event(
                        connection,
                        work_item_id=work_item_id,
                        task_version=task_version,
                        event_type=event_type,
                        actor=actor,
                        payload={"blocker_id": blocker_id, "reason": reason},
                        source_event_key=f"audit:{source_event_key}",
                        created_at=created_at,
                    )
                    row = connection.execute(
                        "SELECT * FROM blocker_events WHERE blocker_event_id=?", (event_id,)
                    ).fetchone()
                    idempotent = False
        except sqlite3.IntegrityError as exc:
            raise self._integrity_error(exc, operation=event_type) from exc
        return {"blocker_event": self._decode_row(dict(row)), "idempotent_replay": idempotent}

    # ------------------------------------------------------------------
    # Delivery, Outbox and Inbox — never mutate Work Item state
    # ------------------------------------------------------------------

    def create_delivery_receipt(self, command: dict[str, Any]) -> dict[str, Any]:
        self._require_enabled()
        self._deny_activation_command("create_delivery_receipt")
        value = require_object(command, "command", non_empty=True)
        allowed = {"delivery_receipt_id", "work_item_id", "task_version", "destination", "payload_digest", "idempotency_key"}
        if set(value) - allowed:
            raise WorkItemGovernanceError("DELIVERY_FIELD_UNSUPPORTED", "Delivery command has unsupported fields.")
        receipt_value = value.get("delivery_receipt_id")
        receipt_id_supplied = receipt_value is not None
        receipt_id = (
            new_stable_id("delivery_receipt")
            if receipt_value is None
            else require_stable_id(receipt_value, "delivery_receipt")
        )
        work_item_id = require_stable_id(value.get("work_item_id"), "work_item")
        task_version = require_positive_integer(value.get("task_version"), "task_version")
        destination = require_text(value.get("destination"), "destination", max_length=MAX_URI_LENGTH)
        payload_digest = require_sha256(value.get("payload_digest"), "payload_digest")
        idempotency_key = require_text(value.get("idempotency_key"), "idempotency_key", max_length=1024)
        created_at = isoformat_utc(self.now())
        try:
            with self._write_transaction() as connection:
                existing = connection.execute(
                    "SELECT * FROM delivery_receipts WHERE idempotency_key=?", (idempotency_key,)
                ).fetchone()
                if existing is not None:
                    if (
                        existing["payload_digest"] != payload_digest
                        or (receipt_id_supplied and existing["delivery_receipt_id"] != receipt_id)
                        or existing["destination"] != destination
                        or existing["work_item_id"] != work_item_id
                        or int(existing["task_version"]) != task_version
                    ):
                        raise WorkItemGovernanceError("IDEMPOTENCY_CONFLICT", "Delivery idempotency key has different content.")
                    row = existing
                    idempotent = True
                else:
                    self._assert_task_exists(connection, work_item_id, task_version)
                    connection.execute(
                        """
                        INSERT INTO delivery_receipts(
                          delivery_receipt_id,schema_version,work_item_id,task_version,destination,
                          payload_digest,status,attempt_count,idempotency_key,created_at,updated_at
                        ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            receipt_id, SCHEMA_VERSIONS["delivery_receipt"], work_item_id, task_version,
                            destination, payload_digest, "pending", 0, idempotency_key, created_at, created_at,
                        ),
                    )
                    self._insert_outbox_event(
                        connection,
                        work_item_id=work_item_id,
                        event_type="delivery_pending",
                        dedupe_key=f"delivery:{receipt_id}:created",
                        payload={"delivery_receipt_id": receipt_id, "destination": destination, "payload_digest": payload_digest},
                        created_at=created_at,
                    )
                    row = connection.execute(
                        "SELECT * FROM delivery_receipts WHERE delivery_receipt_id=?", (receipt_id,)
                    ).fetchone()
                    idempotent = False
        except sqlite3.IntegrityError as exc:
            raise self._integrity_error(exc, operation="create_delivery_receipt") from exc
        return {"delivery_receipt": self._materialize_delivery(row), "idempotent_replay": idempotent}

    def retry_delivery(self, command: dict[str, Any]) -> dict[str, Any]:
        self._require_enabled()
        self._deny_activation_command("retry_delivery")
        value = require_object(command, "command", non_empty=True)
        allowed = {"delivery_receipt_id", "source_event_key", "error", "delivered"}
        if set(value) - allowed:
            raise WorkItemGovernanceError("DELIVERY_RETRY_FIELD_UNSUPPORTED", "Delivery retry has unsupported fields.")
        receipt_id = require_stable_id(value.get("delivery_receipt_id"), "delivery_receipt")
        source_event_key = require_text(value.get("source_event_key"), "source_event_key", max_length=1024)
        error = optional_text(value.get("error"), "error")
        delivered = value.get("delivered", error is None)
        if not isinstance(delivered, bool):
            raise WorkItemGovernanceError("DELIVERY_RESULT_INVALID", "delivered must be a boolean.")
        if delivered and error is not None:
            raise WorkItemGovernanceError("DELIVERY_RESULT_CONFLICT", "Delivered retry cannot also include an error.")
        now = self.now().astimezone(timezone.utc)
        updated_at = isoformat_utc(now)
        retry_payload = {"delivery_receipt_id": receipt_id, "delivered": delivered, "error": error}
        try:
            with self._write_transaction() as connection:
                receipt = connection.execute(
                    "SELECT * FROM delivery_receipts WHERE delivery_receipt_id=?", (receipt_id,)
                ).fetchone()
                if receipt is None:
                    raise WorkItemGovernanceError("DELIVERY_RECEIPT_NOT_FOUND", "Delivery Receipt does not exist.")
                existing = connection.execute(
                    "SELECT * FROM inbox_events WHERE source='delivery_retry' AND source_event_key=?",
                    (source_event_key,),
                ).fetchone()
                if existing is not None:
                    if existing["payload_digest"] != canonical_sha256(retry_payload):
                        raise WorkItemGovernanceError(
                            "IDEMPOTENCY_CONFLICT",
                            "Delivery retry event key is bound to different content.",
                        )
                    idempotent = True
                else:
                    if receipt["status"] == "acknowledged":
                        raise WorkItemGovernanceError("DELIVERY_ALREADY_ACKNOWLEDGED", "Acknowledged delivery cannot be retried.")
                    attempt_count = int(receipt["attempt_count"]) + 1
                    next_attempt = None
                    status = "delivered" if delivered else "retry_scheduled"
                    if not delivered:
                        delay_seconds = min(3600, 2 ** min(attempt_count, 12))
                        next_attempt = isoformat_utc(now + timedelta(seconds=delay_seconds))
                    connection.execute(
                        """
                        UPDATE delivery_receipts
                        SET status=?,attempt_count=?,last_error=?,next_attempt_at=?,updated_at=?
                        WHERE delivery_receipt_id=?
                        """,
                        (status, attempt_count, error, next_attempt, updated_at, receipt_id),
                    )
                    self._insert_inbox_event(
                        connection,
                        source="delivery_retry",
                        source_event_key=source_event_key,
                        payload=retry_payload,
                        received_at=updated_at,
                    )
                    self._insert_outbox_event(
                        connection,
                        work_item_id=str(receipt["work_item_id"]),
                        event_type="delivery_succeeded" if delivered else "delivery_retry_scheduled",
                        dedupe_key=f"delivery:{receipt_id}:retry:{source_event_key}",
                        payload={
                            "delivery_receipt_id": receipt_id,
                            "attempt_count": attempt_count,
                            "status": status,
                            "next_attempt_at": next_attempt,
                        },
                        created_at=updated_at,
                    )
                    idempotent = False
                row = connection.execute(
                    "SELECT * FROM delivery_receipts WHERE delivery_receipt_id=?", (receipt_id,)
                ).fetchone()
        except sqlite3.IntegrityError as exc:
            raise self._integrity_error(exc, operation="retry_delivery") from exc
        return {
            "delivery_receipt": self._materialize_delivery(row),
            "idempotent_replay": idempotent,
            "work_item_state_changed": False,
        }

    def acknowledge_delivery(self, command: dict[str, Any]) -> dict[str, Any]:
        self._require_enabled()
        self._deny_activation_command("acknowledge_delivery")
        value = require_object(command, "command", non_empty=True)
        allowed = {"delivery_receipt_id", "source", "source_event_key"}
        if set(value) - allowed:
            raise WorkItemGovernanceError("DELIVERY_ACK_FIELD_UNSUPPORTED", "Delivery acknowledgement has unsupported fields.")
        receipt_id = require_stable_id(value.get("delivery_receipt_id"), "delivery_receipt")
        source = require_text(value.get("source"), "source", max_length=256)
        source_event_key = require_text(value.get("source_event_key"), "source_event_key", max_length=1024)
        acknowledged_at = isoformat_utc(self.now())
        acknowledgement_payload = {"delivery_receipt_id": receipt_id}
        with self._write_transaction() as connection:
            receipt = connection.execute(
                "SELECT * FROM delivery_receipts WHERE delivery_receipt_id=?", (receipt_id,)
            ).fetchone()
            if receipt is None:
                raise WorkItemGovernanceError("DELIVERY_RECEIPT_NOT_FOUND", "Delivery Receipt does not exist.")
            existing = connection.execute(
                "SELECT * FROM inbox_events WHERE source=? AND source_event_key=?", (source, source_event_key)
            ).fetchone()
            if existing is None:
                if receipt["status"] not in {"delivered", "acknowledged"}:
                    raise WorkItemGovernanceError(
                        "DELIVERY_NOT_DELIVERED",
                        "Delivery must be delivered before it can be acknowledged.",
                    )
                self._insert_inbox_event(
                    connection,
                    source=source,
                    source_event_key=source_event_key,
                    payload=acknowledgement_payload,
                    received_at=acknowledged_at,
                )
                connection.execute(
                    """
                    UPDATE delivery_receipts
                    SET status='acknowledged',acknowledged_at=COALESCE(acknowledged_at,?),updated_at=?
                    WHERE delivery_receipt_id=?
                    """,
                    (acknowledged_at, acknowledged_at, receipt_id),
                )
                idempotent = False
            else:
                if existing["payload_digest"] != canonical_sha256(acknowledgement_payload):
                    raise WorkItemGovernanceError(
                        "IDEMPOTENCY_CONFLICT",
                        "Delivery acknowledgement key is bound to different content.",
                    )
                idempotent = True
            row = connection.execute(
                "SELECT * FROM delivery_receipts WHERE delivery_receipt_id=?", (receipt_id,)
            ).fetchone()
        return {
            "delivery_receipt": self._materialize_delivery(row),
            "idempotent_replay": idempotent,
            "work_item_state_changed": False,
        }

    def list_outbox_events(self, *, status: str | None = None, limit: int = 100) -> dict[str, Any]:
        self._require_enabled()
        valid_statuses = {"pending", "retry_scheduled", "delivered", "failed", "manual_recovery"}
        if status is not None and status not in valid_statuses:
            raise WorkItemGovernanceError("OUTBOX_STATUS_INVALID", "Outbox status filter is invalid.")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise WorkItemGovernanceError("LIST_LIMIT_INVALID", "Outbox limit must be between 1 and 500.")
        with self.ledger.read_connection() as connection:
            if status is None:
                rows = connection.execute(
                    "SELECT * FROM outbox_events ORDER BY created_at,outbox_event_id LIMIT ?",
                    (limit,),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM outbox_events WHERE status=? ORDER BY created_at,outbox_event_id LIMIT ?",
                    (status, limit),
                ).fetchall()
        return {
            "schema_version": "work_item_outbox_list.v1",
            "events": [self._decode_row(dict(row)) for row in rows],
            "count": len(rows),
        }

    def record_outbox_delivery_result(self, command: dict[str, Any]) -> dict[str, Any]:
        self._require_enabled()
        self._deny_activation_command("record_outbox_delivery_result")
        value = require_object(command, "command", non_empty=True)
        allowed = {"outbox_event_id", "source_event_key", "delivered", "error"}
        if set(value) - allowed:
            raise WorkItemGovernanceError("OUTBOX_RESULT_FIELD_UNSUPPORTED", "Outbox result has unsupported fields.")
        event_id = require_stable_id(value.get("outbox_event_id"), "outbox_event")
        source_event_key = require_text(value.get("source_event_key"), "source_event_key", max_length=1024)
        delivered = value.get("delivered")
        if not isinstance(delivered, bool):
            raise WorkItemGovernanceError("OUTBOX_RESULT_INVALID", "delivered must be a boolean.")
        error = optional_text(value.get("error"), "error")
        if delivered and error is not None:
            raise WorkItemGovernanceError("OUTBOX_RESULT_CONFLICT", "Delivered Outbox result cannot include an error.")
        now = self.now().astimezone(timezone.utc)
        updated_at = isoformat_utc(now)
        result_payload = {"outbox_event_id": event_id, "delivered": delivered, "error": error}
        with self._write_transaction() as connection:
            row = connection.execute(
                "SELECT * FROM outbox_events WHERE outbox_event_id=?", (event_id,)
            ).fetchone()
            if row is None:
                raise WorkItemGovernanceError("OUTBOX_EVENT_NOT_FOUND", "Outbox Event does not exist.")
            inbox = connection.execute(
                "SELECT * FROM inbox_events WHERE source='outbox_delivery' AND source_event_key=?",
                (source_event_key,),
            ).fetchone()
            if inbox is None:
                attempts = int(row["attempt_count"]) + 1
                next_attempt = None
                status = "delivered" if delivered else "retry_scheduled"
                if not delivered:
                    next_attempt = isoformat_utc(now + timedelta(seconds=min(3600, 2 ** min(attempts, 12))))
                connection.execute(
                    """
                    UPDATE outbox_events
                    SET status=?,attempt_count=?,next_attempt_at=?,last_error=?,updated_at=?
                    WHERE outbox_event_id=?
                    """,
                    (status, attempts, next_attempt, error, updated_at, event_id),
                )
                self._insert_inbox_event(
                    connection,
                    source="outbox_delivery",
                    source_event_key=source_event_key,
                    payload=result_payload,
                    received_at=updated_at,
                )
                idempotent = False
            else:
                if inbox["payload_digest"] != canonical_sha256(result_payload):
                    raise WorkItemGovernanceError(
                        "IDEMPOTENCY_CONFLICT",
                        "Outbox delivery result key is bound to different content.",
                    )
                idempotent = True
            current = connection.execute(
                "SELECT * FROM outbox_events WHERE outbox_event_id=?", (event_id,)
            ).fetchone()
        return {
            "outbox_event": self._decode_row(dict(current)),
            "idempotent_replay": idempotent,
            "work_item_state_changed": False,
        }

    def recover_outbox_event(self, command: dict[str, Any]) -> dict[str, Any]:
        self._require_enabled()
        self._deny_activation_command("recover_outbox_event")
        value = require_object(command, "command", non_empty=True)
        allowed = {"outbox_event_id", "source_event_key", "reason"}
        if set(value) - allowed:
            raise WorkItemGovernanceError("OUTBOX_RECOVERY_FIELD_UNSUPPORTED", "Outbox recovery has unsupported fields.")
        event_id = require_stable_id(value.get("outbox_event_id"), "outbox_event")
        source_event_key = require_text(value.get("source_event_key"), "source_event_key", max_length=1024)
        reason = require_text(value.get("reason"), "reason")
        recovery_payload = {"outbox_event_id": event_id, "reason": reason}
        updated_at = isoformat_utc(self.now())
        with self._write_transaction() as connection:
            row = connection.execute(
                "SELECT * FROM outbox_events WHERE outbox_event_id=?", (event_id,)
            ).fetchone()
            if row is None:
                raise WorkItemGovernanceError("OUTBOX_EVENT_NOT_FOUND", "Outbox Event does not exist.")
            inbox = connection.execute(
                "SELECT * FROM inbox_events WHERE source='outbox_manual_recovery' AND source_event_key=?",
                (source_event_key,),
            ).fetchone()
            if inbox is None:
                if row["status"] == "delivered":
                    raise WorkItemGovernanceError("OUTBOX_ALREADY_DELIVERED", "Delivered Outbox Event cannot be recovered.")
                connection.execute(
                    """
                    UPDATE outbox_events
                    SET status='pending',next_attempt_at=NULL,last_error=NULL,updated_at=?
                    WHERE outbox_event_id=?
                    """,
                    (updated_at, event_id),
                )
                self._insert_inbox_event(
                    connection,
                    source="outbox_manual_recovery",
                    source_event_key=source_event_key,
                    payload=recovery_payload,
                    received_at=updated_at,
                )
                idempotent = False
            else:
                if inbox["payload_digest"] != canonical_sha256(recovery_payload):
                    raise WorkItemGovernanceError(
                        "IDEMPOTENCY_CONFLICT",
                        "Outbox recovery event key is bound to different content.",
                    )
                idempotent = True
            current = connection.execute(
                "SELECT * FROM outbox_events WHERE outbox_event_id=?", (event_id,)
            ).fetchone()
        return {
            "outbox_event": self._decode_row(dict(current)),
            "idempotent_replay": idempotent,
            "work_item_state_changed": False,
        }

    # ------------------------------------------------------------------
    # Backup/export application commands
    # ------------------------------------------------------------------

    def backup_ledger(self, destination: str | os.PathLike[str]) -> dict[str, Any]:
        self._require_enabled()
        self._assert_unguarded_maintenance_allowed("backup")
        return self.ledger.backup_to(destination, reject_activation_managed=True)

    def restore_ledger(
        self,
        source: str | os.PathLike[str],
        *,
        expected_database_generation: int,
    ) -> dict[str, Any]:
        self._require_enabled()
        self._assert_unguarded_maintenance_allowed("restore")
        return self.ledger.restore_from_backup(
            source,
            expected_database_generation=expected_database_generation,
            reject_activation_managed=True,
        )

    def export_audit_package(self) -> dict[str, Any]:
        self._require_enabled()
        self._assert_unguarded_maintenance_allowed("export")
        return self.ledger.export_audit_package(reject_activation_managed=True)

    # ------------------------------------------------------------------
    # Internal repository mapping and invariants
    # ------------------------------------------------------------------

    def _insert_task_version(
        self,
        connection: sqlite3.Connection,
        *,
        work_item_id: str,
        task_version: int,
        task: dict[str, Any],
        source_event_key: str,
        created_at: str,
    ) -> None:
        payload_digest = canonical_sha256(task)
        connection.execute(
            """
            INSERT INTO task_versions(
              work_item_id,task_version,schema_version,objective_ref,plan_version_refs_json,
              artifact_contract_json,approval_requirements_json,reporting_destination_json,
              expected_receipt_contract_json,payload_json,payload_digest,source_event_key,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                work_item_id,
                task_version,
                SCHEMA_VERSIONS["task_version"],
                task["objective_ref"],
                canonical_json(task["plan_version_refs"]),
                canonical_json(task["artifact_contract"]),
                canonical_json(task["approval_requirements"]),
                canonical_json(task["reporting_destination"]),
                canonical_json(task["expected_receipt_contract"]),
                canonical_json(task["payload"]),
                payload_digest,
                source_event_key,
                created_at,
            ),
        )
        for index, plan_ref in enumerate(task["plan_version_refs"]):
            connection.execute(
                """
                INSERT INTO external_associations(
                  association_kind,external_ref,work_item_id,task_version,source_event_key,created_at
                ) VALUES('plan_version',?,?,?,?,?)
                """,
                (
                    plan_ref,
                    work_item_id,
                    task_version,
                    f"{source_event_key}:plan:{index}",
                    created_at,
                ),
            )

    def _insert_acceptance_manifest(
        self,
        connection: sqlite3.Connection,
        *,
        gate_event_id: str,
        work_item_id: str,
        task_version: int,
        accepted_state_version: int,
        artifact_ids: list[str],
        decision_ids: list[str],
        principal: dict[str, Any],
        created_at: str,
    ) -> str:
        artifact_rows = self._assert_artifacts(
            connection,
            artifact_ids,
            work_item_id,
            task_version,
        )
        artifact_manifest = sorted(
            (
                {
                    "artifact_id": str(row["artifact_id"]),
                    "kind": str(row["kind"]),
                    "uri": str(row["uri"]),
                    "immutable_ref": str(row["immutable_ref"]),
                    "digest": str(row["digest"]),
                }
                for row in artifact_rows
            ),
            key=lambda item: item["artifact_id"],
        )
        sorted_artifact_ids = [item["artifact_id"] for item in artifact_manifest]
        manifest_id = new_stable_id("acceptance_manifest")
        connection.execute(
            """
            INSERT INTO acceptance_manifests(
              acceptance_manifest_id,schema_version,work_item_id,task_version,gate_event_id,
              accepted_state_version,artifact_ids_json,artifact_manifest_json,
              artifact_manifest_digest,decision_ids_json,principal_json,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                manifest_id,
                SCHEMA_VERSIONS["acceptance_manifest"],
                work_item_id,
                task_version,
                gate_event_id,
                accepted_state_version,
                canonical_json(sorted_artifact_ids),
                canonical_json(artifact_manifest),
                canonical_sha256(artifact_manifest),
                canonical_json(sorted(decision_ids)),
                canonical_json(principal),
                created_at,
            ),
        )
        return manifest_id

    @staticmethod
    def _normalize_external_refs(value: Any) -> list[dict[str, str]]:
        if value is None:
            return []
        if not isinstance(value, list) or len(value) > 1024:
            raise WorkItemGovernanceError("EXTERNAL_REFS_INVALID", "external_refs must be a bounded list.")
        result: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for index, item in enumerate(value):
            ref = require_object(item, f"external_refs[{index}]", non_empty=True)
            if set(ref) != {"kind", "ref"}:
                raise WorkItemGovernanceError(
                    "EXTERNAL_REF_SHAPE_INVALID",
                    "External reference must contain only kind and ref.",
                )
            normalized = {
                "kind": str(require_text(ref.get("kind"), f"external_refs[{index}].kind", max_length=128)),
                "ref": str(require_text(ref.get("ref"), f"external_refs[{index}].ref", max_length=2048)),
            }
            key = (normalized["kind"], normalized["ref"])
            if key in seen:
                raise WorkItemGovernanceError("EXTERNAL_REF_DUPLICATE", "External references must be unique.")
            seen.add(key)
            result.append(normalized)
        return result

    @staticmethod
    def _insert_external_refs(
        connection: sqlite3.Connection,
        refs: Iterable[dict[str, str]],
        *,
        work_item_id: str,
        task_version: int,
        attempt_id: str,
        source_event_key: str,
        created_at: str,
    ) -> None:
        for index, ref in enumerate(refs):
            connection.execute(
                """
                INSERT INTO external_associations(
                  association_kind,external_ref,work_item_id,task_version,attempt_id,source_event_key,created_at
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (
                    ref["kind"], ref["ref"], work_item_id, task_version, attempt_id,
                    f"{source_event_key}:external:{index}", created_at,
                ),
            )

    def _normalize_artifact_command(self, value: Any) -> dict[str, Any]:
        command = require_object(value, "artifact", non_empty=True)
        allowed = {
            "artifact_id", "work_item_id", "task_version", "attempt_id", "kind", "uri",
            "immutable_ref", "digest", "observed_digest", "metadata", "source_event_key",
        }
        unknown = sorted(set(command) - allowed)
        if unknown:
            raise WorkItemGovernanceError(
                "ARTIFACT_FIELD_UNSUPPORTED",
                "Artifact Reference contains unsupported fields.",
                details={"unsupported_fields": unknown},
            )
        artifact_value = command.get("artifact_id")
        artifact_id_supplied = artifact_value is not None
        artifact_id = new_stable_id("artifact") if artifact_value is None else require_stable_id(artifact_value, "artifact")
        kind = command.get("kind")
        if kind not in ARTIFACT_KINDS:
            raise WorkItemGovernanceError("ARTIFACT_KIND_INVALID", "Artifact kind is invalid.")
        uri = require_text(command.get("uri"), "uri", max_length=MAX_URI_LENGTH)
        if any(ord(character) < 32 for character in str(uri)):
            raise WorkItemGovernanceError("ARTIFACT_URI_INVALID", "Artifact URI contains control characters.")
        digest = require_sha256(command.get("digest"), "digest")
        observed = command.get("observed_digest")
        if observed is not None:
            observed = require_sha256(observed, "observed_digest")
            if observed != digest:
                raise WorkItemGovernanceError(
                    "ARTIFACT_DIGEST_MISMATCH",
                    "Observed Artifact digest does not match the declared digest.",
                    details={"declared": digest, "observed": observed},
                )
        self._verify_local_artifact_digest(str(uri), digest)
        metadata = require_metadata_object(command.get("metadata", {}), "metadata")
        self._reject_sensitive_fields(metadata, "metadata")
        attempt = command.get("attempt_id")
        return {
            "artifact_id": artifact_id,
            "_artifact_id_supplied": artifact_id_supplied,
            "work_item_id": require_stable_id(command.get("work_item_id"), "work_item"),
            "task_version": require_positive_integer(command.get("task_version"), "task_version"),
            "attempt_id": None if attempt is None else require_stable_id(attempt, "attempt"),
            "kind": kind,
            "uri": str(uri),
            "immutable_ref": str(require_text(command.get("immutable_ref"), "immutable_ref", max_length=MAX_URI_LENGTH)),
            "digest": digest,
            "metadata": metadata,
            "source_event_key": str(require_text(command.get("source_event_key"), "source_event_key", max_length=1024)),
        }

    def _verify_local_artifact_digest(self, uri: str, digest: str) -> None:
        path: Path | None = None
        if uri.startswith("project://"):
            path = self.project_root / uri[len("project://") :].lstrip("/")
        elif uri.startswith("file://"):
            path = Path(uri[len("file://") :])
        elif "://" not in uri:
            path = self.project_root / uri
        if path is None:
            return
        resolved = path.expanduser().resolve()
        try:
            resolved.relative_to(self.project_root)
        except ValueError as exc:
            raise WorkItemGovernanceError(
                "ARTIFACT_PATH_OUTSIDE_PROJECT",
                "Local Artifact URI must remain within the project root.",
            ) from exc
        if not resolved.is_file():
            raise WorkItemGovernanceError(
                "ARTIFACT_FILE_MISSING",
                "Local Artifact URI does not identify a file.",
                details={"uri": uri},
            )
        observed = sha256_file(resolved)
        if observed != digest:
            raise WorkItemGovernanceError(
                "ARTIFACT_DIGEST_MISMATCH",
                "Local Artifact content does not match the declared digest.",
                details={"declared": digest, "observed": observed},
            )

    def _insert_artifact(
        self,
        connection: sqlite3.Connection,
        artifact: dict[str, Any],
        *,
        created_at: str,
    ) -> tuple[sqlite3.Row, bool]:
        existing = self._find_existing_artifact(connection, artifact)
        if existing is not None:
            self._assert_existing_artifact_matches(existing, artifact)
            return existing, True
        work_item = self._work_item_row(connection, artifact["work_item_id"])
        if work_item["state"] in TERMINAL_WORK_ITEM_STATES:
            raise WorkItemGovernanceError(
                "TERMINAL_ARTIFACT_SET_FROZEN",
                "Terminal Work Items cannot receive new Acceptance Artifact References.",
            )
        self._assert_task_exists(connection, artifact["work_item_id"], artifact["task_version"])
        if artifact["attempt_id"] is not None:
            attempt = connection.execute(
                "SELECT * FROM execution_attempts WHERE attempt_id=?", (artifact["attempt_id"],)
            ).fetchone()
            if (
                attempt is None
                or attempt["work_item_id"] != artifact["work_item_id"]
                or int(attempt["task_version"]) != artifact["task_version"]
            ):
                raise WorkItemGovernanceError(
                    "ARTIFACT_ATTEMPT_MISMATCH",
                    "Artifact Attempt must belong to the same Work Item and Task Version.",
                )
        connection.execute(
            """
            INSERT INTO artifact_refs(
              artifact_id,schema_version,work_item_id,task_version,attempt_id,kind,uri,
              immutable_ref,digest,metadata_json,source_event_key,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                artifact["artifact_id"], SCHEMA_VERSIONS["artifact_reference"], artifact["work_item_id"],
                artifact["task_version"], artifact["attempt_id"], artifact["kind"], artifact["uri"],
                artifact["immutable_ref"], artifact["digest"], canonical_json(artifact["metadata"]),
                artifact["source_event_key"], created_at,
            ),
        )
        row = connection.execute(
            "SELECT * FROM artifact_refs WHERE artifact_id=?", (artifact["artifact_id"],)
        ).fetchone()
        return row, False

    @staticmethod
    def _find_existing_artifact(
        connection: sqlite3.Connection,
        artifact: dict[str, Any],
    ) -> sqlite3.Row | None:
        existing = connection.execute(
            "SELECT * FROM artifact_refs WHERE source_event_key=?", (artifact["source_event_key"],)
        ).fetchone()
        if existing is not None:
            return existing
        return connection.execute(
            """
            SELECT * FROM artifact_refs
            WHERE work_item_id=? AND kind=? AND immutable_ref=?
            """,
            (artifact["work_item_id"], artifact["kind"], artifact["immutable_ref"]),
        ).fetchone()

    def _count_new_completion_artifacts(
        self,
        connection: sqlite3.Connection,
        artifacts: list[dict[str, Any]],
    ) -> int:
        pending_by_source: dict[str, dict[str, Any]] = {}
        pending_by_reference: dict[tuple[str, str, str], dict[str, Any]] = {}
        count = 0
        for artifact in artifacts:
            existing = self._find_existing_artifact(connection, artifact)
            if existing is not None:
                self._assert_existing_artifact_matches(existing, artifact)
                continue
            reference_key = (
                str(artifact["work_item_id"]),
                str(artifact["kind"]),
                str(artifact["immutable_ref"]),
            )
            pending = pending_by_source.get(str(artifact["source_event_key"]))
            if pending is None:
                pending = pending_by_reference.get(reference_key)
            if pending is not None:
                self._assert_pending_artifact_matches(pending, artifact)
                continue
            pending_by_source[str(artifact["source_event_key"])] = artifact
            pending_by_reference[reference_key] = artifact
            count += 1
        return count

    @staticmethod
    def _assert_pending_artifact_matches(
        existing: dict[str, Any],
        artifact: dict[str, Any],
    ) -> None:
        content_fields = (
            "work_item_id",
            "task_version",
            "attempt_id",
            "kind",
            "uri",
            "immutable_ref",
            "digest",
            "metadata",
        )
        explicit_id_mismatch = (
            artifact.get("_artifact_id_supplied") is True
            and existing["artifact_id"] != artifact["artifact_id"]
        )
        if explicit_id_mismatch or any(
            existing[field] != artifact[field] for field in content_fields
        ):
            raise WorkItemGovernanceError(
                "IDEMPOTENCY_CONFLICT",
                "Artifact registration key/reference is bound to different content.",
                details={"artifact_id": existing["artifact_id"]},
            )

    @staticmethod
    def _assert_existing_artifact_matches(row: sqlite3.Row, artifact: dict[str, Any]) -> None:
        expected = (
            artifact["work_item_id"], artifact["task_version"], artifact["attempt_id"], artifact["kind"],
            artifact["uri"], artifact["immutable_ref"], artifact["digest"],
        )
        actual = (
            row["work_item_id"], row["task_version"], row["attempt_id"], row["kind"], row["uri"],
            row["immutable_ref"], row["digest"],
        )
        explicit_id_mismatch = (
            artifact.get("_artifact_id_supplied") is True
            and row["artifact_id"] != artifact["artifact_id"]
        )
        metadata_mismatch = json.loads(row["metadata_json"]) != artifact["metadata"]
        if actual != expected or explicit_id_mismatch or metadata_mismatch:
            raise WorkItemGovernanceError(
                "IDEMPOTENCY_CONFLICT",
                "Artifact registration key/reference is bound to different content.",
                details={"artifact_id": row["artifact_id"]},
            )

    @staticmethod
    def _normalize_id_list(value: Any, kind: str, field: str) -> list[str]:
        if not isinstance(value, list) or len(value) > 1024:
            raise WorkItemGovernanceError("ID_LIST_INVALID", f"{field} must be a bounded list.")
        result = [require_stable_id(item, kind, field) for item in value]
        if len(set(result)) != len(result):
            raise WorkItemGovernanceError("ID_LIST_DUPLICATE", f"{field} must not contain duplicates.")
        return result

    @staticmethod
    def _work_item_row(connection: sqlite3.Connection, work_item_id: str) -> sqlite3.Row:
        row = connection.execute("SELECT * FROM work_items WHERE work_item_id=?", (work_item_id,)).fetchone()
        if row is None:
            raise WorkItemGovernanceError(
                "WORK_ITEM_NOT_FOUND",
                "Work Item does not exist.",
                details={"work_item_id": work_item_id},
            )
        return row

    @staticmethod
    def _assert_task_exists(connection: sqlite3.Connection, work_item_id: str, task_version: int) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM task_versions WHERE work_item_id=? AND task_version=?",
            (work_item_id, task_version),
        ).fetchone()
        if row is None:
            raise WorkItemGovernanceError(
                "TASK_VERSION_NOT_FOUND",
                "Task Version does not exist for the Work Item.",
                details={"work_item_id": work_item_id, "task_version": task_version},
            )
        return row

    @staticmethod
    def _assert_artifacts(
        connection: sqlite3.Connection,
        artifact_ids: list[str],
        work_item_id: str,
        task_version: int,
    ) -> list[sqlite3.Row]:
        rows: list[sqlite3.Row] = []
        for artifact_id in artifact_ids:
            row = connection.execute(
                "SELECT * FROM artifact_refs WHERE artifact_id=?", (artifact_id,)
            ).fetchone()
            if row is None:
                raise WorkItemGovernanceError(
                    "ARTIFACT_NOT_FOUND",
                    "Transition/Decision Artifact does not exist.",
                    details={"artifact_id": artifact_id},
                )
            if row["work_item_id"] != work_item_id or int(row["task_version"]) != task_version:
                raise WorkItemGovernanceError(
                    "ARTIFACT_CONTEXT_MISMATCH",
                    "Artifact belongs to a different Work Item or Task Version.",
                    details={"artifact_id": artifact_id},
                )
            rows.append(row)
        return rows

    @staticmethod
    def _assert_decisions(
        connection: sqlite3.Connection,
        decision_ids: list[str],
        work_item_id: str,
        task_version: int,
    ) -> list[sqlite3.Row]:
        rows: list[sqlite3.Row] = []
        for decision_id in decision_ids:
            row = connection.execute(
                "SELECT * FROM decision_records WHERE decision_id=?", (decision_id,)
            ).fetchone()
            if row is None:
                raise WorkItemGovernanceError(
                    "DECISION_NOT_FOUND",
                    "Transition Decision does not exist.",
                    details={"decision_id": decision_id},
                )
            principal = json.loads(row["principal_json"])
            authority = json.loads(row["authority_basis_json"])
            expected_permission = permission_for_decision(str(row["action"]))
            if (
                not isinstance(principal, dict)
                or principal.get("principal_id") != authority.get("principal_id")
                or authority.get("authority") != expected_permission
                or authority.get("policy") != "work_item_principal_policy.v1"
            ):
                raise WorkItemGovernanceError(
                    "DECISION_PRINCIPAL_UNTRUSTED",
                    "Decision lacks a trusted Principal and policy binding.",
                    details={"decision_id": decision_id},
                )
            if row["work_item_id"] != work_item_id or int(row["task_version"]) != task_version:
                raise WorkItemGovernanceError(
                    "DECISION_CONTEXT_MISMATCH",
                    "Decision belongs to a different Work Item or Task Version.",
                    details={"decision_id": decision_id},
                )
            superseding = connection.execute(
                "SELECT decision_id FROM decision_records WHERE supersedes_decision_id=?", (decision_id,)
            ).fetchone()
            if superseding is not None:
                raise WorkItemGovernanceError(
                    "DECISION_SUPERSEDED",
                    "Superseded Decision cannot authorize a transition.",
                    details={"decision_id": decision_id, "superseded_by": superseding["decision_id"]},
                )
            rows.append(row)
        return rows

    @staticmethod
    def _active_blocker_rows(connection: sqlite3.Connection, work_item_id: str) -> list[sqlite3.Row]:
        return connection.execute(
            """
            SELECT current.*
            FROM blocker_events AS current
            JOIN (
              SELECT blocker_id, MAX(rowid) AS latest_rowid
              FROM blocker_events
              WHERE work_item_id=?
              GROUP BY blocker_id
            ) AS latest ON current.rowid=latest.latest_rowid
            WHERE current.event_type='blocker_applied'
            ORDER BY current.created_at,current.blocker_id
            """,
            (work_item_id,),
        ).fetchall()

    @staticmethod
    def _insert_audit_event(
        connection: sqlite3.Connection,
        *,
        work_item_id: str,
        task_version: int | None,
        event_type: str,
        actor: dict[str, Any],
        payload: dict[str, Any],
        source_event_key: str,
        created_at: str,
    ) -> str:
        event_id = new_stable_id("audit_event")
        connection.execute(
            """
            INSERT INTO audit_events(
              audit_event_id,work_item_id,task_version,event_type,actor_json,payload_json,
              source_event_key,created_at
            ) VALUES(?,?,?,?,?,?,?,?)
            """,
            (
                event_id, work_item_id, task_version, event_type, canonical_json(actor),
                canonical_json(payload), source_event_key, created_at,
            ),
        )
        return event_id

    @staticmethod
    def _insert_outbox_event(
        connection: sqlite3.Connection,
        *,
        work_item_id: str,
        event_type: str,
        dedupe_key: str,
        payload: dict[str, Any],
        created_at: str,
    ) -> str:
        event_id = new_stable_id("outbox_event")
        connection.execute(
            """
            INSERT INTO outbox_events(
              outbox_event_id,work_item_id,event_type,dedupe_key,payload_json,status,
              attempt_count,created_at,updated_at
            ) VALUES(?,?,?,?,?,'pending',0,?,?)
            """,
            (
                event_id, work_item_id, event_type, dedupe_key, canonical_json(payload), created_at, created_at,
            ),
        )
        return event_id

    @staticmethod
    def _insert_inbox_event(
        connection: sqlite3.Connection,
        *,
        source: str,
        source_event_key: str,
        payload: dict[str, Any],
        received_at: str,
    ) -> str:
        event_id = new_stable_id("inbox_event")
        connection.execute(
            """
            INSERT INTO inbox_events(inbox_event_id,source,source_event_key,payload_digest,received_at)
            VALUES(?,?,?,?,?)
            """,
            (event_id, source, source_event_key, canonical_sha256(payload), received_at),
        )
        return event_id

    def _materialize_work_item(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        *,
        include_children: bool = True,
    ) -> dict[str, Any]:
        work_item_id = str(row["work_item_id"])
        blockers = self._active_blocker_rows(connection, work_item_id)
        item: dict[str, Any] = {
            "schema_version": row["schema_version"],
            "work_item_id": work_item_id,
            "state": row["state"],
            "state_version": int(row["state_version"]),
            "origin": {
                "kind": row["origin_kind"],
                "ref": row["origin_ref"],
                "snapshot_digest": row["origin_snapshot_digest"],
            },
            "imported": bool(row["imported"]),
            "current_task_version": int(row["current_task_version"]),
            "attributes": json.loads(row["attributes_json"]),
            "blocked": bool(blockers),
            "active_blocker_ids": [str(blocker["blocker_id"]) for blocker in blockers],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "delivery_state_authority": (
                "work_item_application_service" if self.authoritative_transitions else "shadow_only"
            ),
            "gate_mode": self.gate_mode,
            "runner_status_is_authority": False,
            "connector_status_is_authority": False,
            "stable_promotion_is_authority": False,
            "product_submission_is_authority": False,
        }
        if not include_children:
            return item
        task_rows = connection.execute(
            "SELECT * FROM task_versions WHERE work_item_id=? ORDER BY task_version", (work_item_id,)
        ).fetchall()
        attempt_rows = connection.execute(
            "SELECT * FROM execution_attempts WHERE work_item_id=? ORDER BY created_at,attempt_id", (work_item_id,)
        ).fetchall()
        artifact_rows = connection.execute(
            "SELECT * FROM artifact_refs WHERE work_item_id=? ORDER BY created_at,artifact_id", (work_item_id,)
        ).fetchall()
        decision_rows = connection.execute(
            "SELECT * FROM decision_records WHERE work_item_id=? ORDER BY created_at,decision_id", (work_item_id,)
        ).fetchall()
        gate_rows = connection.execute(
            "SELECT * FROM gate_events WHERE work_item_id=? ORDER BY created_at,gate_event_id", (work_item_id,)
        ).fetchall()
        delivery_rows = connection.execute(
            "SELECT * FROM delivery_receipts WHERE work_item_id=? ORDER BY created_at,delivery_receipt_id",
            (work_item_id,),
        ).fetchall()
        acceptance_row = connection.execute(
            "SELECT * FROM acceptance_manifests WHERE work_item_id=?",
            (work_item_id,),
        ).fetchone()
        item.update(
            {
                "task_versions": [self._materialize_task_version(value) for value in task_rows],
                "execution_attempts": [self._materialize_attempt(value) for value in attempt_rows],
                "artifact_refs": [self._materialize_artifact(value) for value in artifact_rows],
                "decision_records": [self._materialize_decision(value) for value in decision_rows],
                "gate_events": [self._materialize_gate(value) for value in gate_rows],
                "delivery_receipts": [self._materialize_delivery(value) for value in delivery_rows],
                "accepted_evidence_manifest": (
                    self._materialize_acceptance_manifest(acceptance_row)
                    if acceptance_row is not None
                    else None
                ),
            }
        )
        return item

    @staticmethod
    def _materialize_task_version(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "schema_version": row["schema_version"],
            "work_item_id": row["work_item_id"],
            "task_version": int(row["task_version"]),
            "objective_ref": row["objective_ref"],
            "plan_version_refs": json.loads(row["plan_version_refs_json"]),
            "artifact_contract": json.loads(row["artifact_contract_json"]),
            "approval_requirements": json.loads(row["approval_requirements_json"]),
            "reporting_destination": json.loads(row["reporting_destination_json"]),
            "expected_receipt_contract": json.loads(row["expected_receipt_contract_json"]),
            "payload": json.loads(row["payload_json"]),
            "payload_digest": row["payload_digest"],
            "created_at": row["created_at"],
        }

    @staticmethod
    def _materialize_attempt(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "schema_version": row["schema_version"],
            "attempt_id": row["attempt_id"],
            "work_item_id": row["work_item_id"],
            "task_version": int(row["task_version"]),
            "status": row["status"],
            "objective_ref": row["objective_ref"],
            "metadata": json.loads(row["metadata_json"]),
            "attempt_kind": row["attempt_kind"],
            "dispatch_authorized": bool(row["dispatch_authorized"]),
            "historical_reason": row["historical_reason"],
            "imported": bool(row["imported"]),
            "source_event_key": row["source_event_key"],
            "completion_event_key": row["completion_event_key"],
            "created_at": row["created_at"],
            "completed_at": row["completed_at"],
        }

    @staticmethod
    def _materialize_artifact(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "schema_version": row["schema_version"],
            "artifact_id": row["artifact_id"],
            "work_item_id": row["work_item_id"],
            "task_version": int(row["task_version"]),
            "attempt_id": row["attempt_id"],
            "kind": row["kind"],
            "uri": row["uri"],
            "immutable_ref": row["immutable_ref"],
            "digest": row["digest"],
            "metadata": json.loads(row["metadata_json"]),
            "source_event_key": row["source_event_key"],
            "created_at": row["created_at"],
        }

    @staticmethod
    def _materialize_decision(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "schema_version": row["schema_version"],
            "decision_id": row["decision_id"],
            "work_item_id": row["work_item_id"],
            "task_version": int(row["task_version"]),
            "actor": json.loads(row["actor_json"]),
            "action": row["action"],
            "evidence_artifact_ids": json.loads(row["evidence_artifact_ids_json"]),
            "authority_basis": json.loads(row["authority_basis_json"]),
            "principal_context": json.loads(row["principal_json"]),
            "reason": row["reason"],
            "supersedes_decision_id": row["supersedes_decision_id"],
            "source_event_key": row["source_event_key"],
            "created_at": row["created_at"],
        }

    @staticmethod
    def _materialize_gate(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "schema_version": row["schema_version"],
            "gate_event_id": row["gate_event_id"],
            "work_item_id": row["work_item_id"],
            "task_version": int(row["task_version"]),
            "from_state": row["from_state"],
            "target_state": row["target_state"],
            "expected_state_version": int(row["expected_state_version"]),
            "outcome": row["outcome"],
            "reason_code": row["reason_code"],
            "decision_ids": json.loads(row["decision_ids_json"]),
            "evidence_artifact_ids": json.loads(row["evidence_artifact_ids_json"]),
            "authority_basis": json.loads(row["authority_basis_json"]),
            "principal_context": json.loads(row["principal_json"]),
            "transition_result": row["transition_result"],
            "command_digest": row["command_digest"],
            "created_at": row["created_at"],
        }

    @staticmethod
    def _materialize_delivery(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "schema_version": row["schema_version"],
            "delivery_receipt_id": row["delivery_receipt_id"],
            "work_item_id": row["work_item_id"],
            "task_version": int(row["task_version"]),
            "destination": row["destination"],
            "payload_digest": row["payload_digest"],
            "status": row["status"],
            "attempt_count": int(row["attempt_count"]),
            "last_error": row["last_error"],
            "next_attempt_at": row["next_attempt_at"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "acknowledged_at": row["acknowledged_at"],
        }

    @staticmethod
    def _materialize_acceptance_manifest(row: sqlite3.Row) -> dict[str, Any]:
        artifact_ids = json.loads(row["artifact_ids_json"])
        artifact_manifest = json.loads(row["artifact_manifest_json"])
        stored_digest = str(row["artifact_manifest_digest"])
        computed_digest = canonical_sha256(artifact_manifest)
        manifest_ids = [
            entry.get("artifact_id")
            for entry in artifact_manifest
            if isinstance(entry, dict)
        ] if isinstance(artifact_manifest, list) else []
        if (
            computed_digest != stored_digest
            or not isinstance(artifact_ids, list)
            or sorted(artifact_ids) != manifest_ids
        ):
            raise WorkItemGovernanceError(
                "ACCEPTANCE_MANIFEST_INTEGRITY_FAILED",
                "Acceptance evidence manifest no longer matches its frozen digest and identifiers.",
                details={
                    "acceptance_manifest_id": row["acceptance_manifest_id"],
                    "stored_digest": stored_digest,
                    "computed_digest": computed_digest,
                },
            )
        return {
            "schema_version": row["schema_version"],
            "acceptance_manifest_id": row["acceptance_manifest_id"],
            "work_item_id": row["work_item_id"],
            "task_version": int(row["task_version"]),
            "gate_event_id": row["gate_event_id"],
            "accepted_state_version": int(row["accepted_state_version"]),
            "artifact_ids": artifact_ids,
            "artifact_manifest": artifact_manifest,
            "artifact_manifest_digest": stored_digest,
            "decision_ids": json.loads(row["decision_ids_json"]),
            "principal_context": json.loads(row["principal_json"]),
            "created_at": row["created_at"],
        }

    @staticmethod
    def _decode_row(value: dict[str, Any]) -> dict[str, Any]:
        decoded: dict[str, Any] = {}
        for key, child in value.items():
            if key.endswith("_json") and isinstance(child, str):
                decoded[key[:-5]] = json.loads(child)
            else:
                decoded[key] = child
        return decoded

    @classmethod
    def _reject_sensitive_fields(cls, value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                normalized = str(key).lower()
                if any(fragment in normalized for fragment in _SENSITIVE_KEY_FRAGMENTS):
                    raise WorkItemGovernanceError(
                        "SENSITIVE_FIELD_REJECTED",
                        "Ledger payload contains a prohibited sensitive/body field.",
                        details={"path": f"{path}.{key}"},
                    )
                cls._reject_sensitive_fields(child, f"{path}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                cls._reject_sensitive_fields(child, f"{path}[{index}]")
        elif isinstance(value, str) and len(value) > MAX_TEXT_LENGTH:
            raise WorkItemGovernanceError(
                "TEXT_TOO_LARGE",
                "Ledger text value exceeds the allowed length.",
                details={"path": path, "max_length": MAX_TEXT_LENGTH},
            )

    @staticmethod
    def _integrity_error(exc: sqlite3.IntegrityError, *, operation: str) -> WorkItemGovernanceError:
        message = str(exc)
        code = "LEDGER_CONSTRAINT_VIOLATION"
        if "UNIQUE constraint failed" in message:
            code = "IDEMPOTENCY_OR_ASSOCIATION_CONFLICT"
        elif "FOREIGN KEY constraint failed" in message:
            code = "LEDGER_REFERENCE_INVALID"
        return WorkItemGovernanceError(
            code,
            "Ledger rejected the operation to preserve integrity.",
            details={"operation": operation, "constraint": message},
        )
