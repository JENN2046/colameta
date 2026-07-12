from __future__ import annotations

import json
import sqlite3
from copy import copy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from runner.work_item_governance.architecture import check_work_item_architecture
from runner.work_item_governance.activation import (
    ActivationLeaseControlPlane,
    AuthoritativeCanaryGuard,
)
from runner.work_item_governance.errors import WorkItemGovernanceError
from runner.work_item_governance.repository import SQLiteWorkItemLedger
from runner.work_item_governance.service import WorkItemApplicationService
from work_item_r2_helpers import (
    all_permissions_principal,
    install_active_lease,
    make_fixture,
)


def _create(service: WorkItemApplicationService, *, key: str = "r3:create") -> str:
    preview = service.preview_work_item_create(
        {
            "origin": {
                "kind": "manual",
                "ref": f"synthetic://WIG-P3-R3/{key}",
                "snapshot_digest": "1" * 64,
            },
            "objective": "R3 write-boundary fixture",
            "task": {"objective_ref": f"synthetic://WIG-P3-R3/objective/{key}"},
            "idempotency_key": key,
        }
    )["preview"]
    return str(service.apply_work_item_create(preview)["work_item"]["work_item_id"])


def _mark_authoritative_canary(project: Path) -> None:
    settings = project / ".colameta" / "settings.json"
    settings.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    settings.write_text(
        json.dumps(
            {
                "work_item_governance": {
                    "shadow_ledger_enabled": True,
                    "gate_mode": "authoritative",
                    "authoritative_canary": True,
                }
            }
        ),
        encoding="utf-8",
    )


def test_canary_marker_prevents_authoritative_composition_downgrade(tmp_path: Path) -> None:
    ledger = SQLiteWorkItemLedger(tmp_path)
    ledger.initialize()
    ledger.get_or_create_signing_key()
    _mark_authoritative_canary(tmp_path)
    service = WorkItemApplicationService(
        tmp_path,
        enabled=True,
        authoritative_transitions=True,
        authoritative_canary=False,
    )
    preview = service.preview_work_item_create(
        {
            "origin": {
                "kind": "manual",
                "ref": "synthetic://WIG-P3-R3/direct-authoritative",
                "snapshot_digest": "3" * 64,
            },
            "objective": "must not persist",
            "idempotency_key": "r3:direct-authoritative",
        }
    )["preview"]
    with pytest.raises(WorkItemGovernanceError) as exc_info:
        service.apply_work_item_create(preview)
    assert exc_info.value.code == "ACTIVATION_COMPOSITION_DOWNGRADE_DENIED"
    with ledger.read_connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM work_items").fetchone()[0] == 0


def test_canary_marker_rejects_unguarded_shadow_domain_write(tmp_path: Path) -> None:
    ledger = SQLiteWorkItemLedger(tmp_path)
    ledger.initialize()
    ledger.get_or_create_signing_key()
    _mark_authoritative_canary(tmp_path)
    service = WorkItemApplicationService(
        tmp_path,
        enabled=True,
        authoritative_transitions=False,
    )
    preview = service.preview_work_item_create(
        {
            "origin": {
                "kind": "manual",
                "ref": "synthetic://WIG-P3-R3/downgrade",
                "snapshot_digest": "2" * 64,
            },
            "objective": "must not persist",
            "idempotency_key": "r3:downgrade",
        }
    )["preview"]

    with pytest.raises(WorkItemGovernanceError) as exc_info:
        service.apply_work_item_create(preview)

    assert exc_info.value.code == "ACTIVATION_COMPOSITION_DOWNGRADE_DENIED"
    with ledger.read_connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM work_items").fetchone()[0] == 0


def test_canary_marked_repository_raw_domain_write_is_default_deny(tmp_path: Path) -> None:
    ledger = SQLiteWorkItemLedger(tmp_path)
    ledger.initialize()
    ledger.get_or_create_signing_key()
    _mark_authoritative_canary(tmp_path)

    with pytest.raises(WorkItemGovernanceError) as exc_info:
        with ledger.write_transaction() as connection:
            connection.execute("DELETE FROM work_items")

    assert exc_info.value.code == "ACTIVATION_REPOSITORY_WRITE_DENIED"
    assert not hasattr(ledger, "_activation_domain_write_capability")


def test_fake_repository_session_cannot_unlock_domain_writes(tmp_path: Path) -> None:
    ledger = SQLiteWorkItemLedger(tmp_path)
    ledger.initialize()
    ledger.get_or_create_signing_key()
    _mark_authoritative_canary(tmp_path)

    with ledger.write_transaction() as connection:
        with pytest.raises(WorkItemGovernanceError) as exc_info:
            ledger.authorize_activation_domain_write(
                connection,
                session=SimpleNamespace(connection=connection),
            )
        assert exc_info.value.code == "ACTIVATION_REPOSITORY_CAPABILITY_INVALID"
        with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
            connection.execute("DELETE FROM work_items")


def test_copied_forged_or_other_guard_session_cannot_unlock(tmp_path: Path) -> None:
    import runner.work_item_governance.activation as activation_module

    principal = all_permissions_principal()
    fixture, _raw = make_fixture(tmp_path, principal)
    service = install_active_lease(tmp_path, fixture, principal)
    normalized = fixture["command_slots"][0]["normalized_command"]
    assert not hasattr(activation_module, "_ACTIVATION_WRITE_SESSION_TRUST_SEAL")

    with pytest.raises(WorkItemGovernanceError) as unfinished:
        with service._write_transaction() as connection:
            issued = service._activation_begin(
                connection,
                command_name="apply_work_item_create",
                normalized_command=normalized,
                source_event_key="r2:create",
            )
            assert issued is not None
            copied = copy(issued)
            other_guard = AuthoritativeCanaryGuard(service.ledger)
            other_guard_copy = replace(issued, guard=other_guard)
            manual = replace(issued, _trust_seal=b"forged")
            for forged in (copied, other_guard_copy, manual):
                with pytest.raises(WorkItemGovernanceError) as exc_info:
                    service.ledger.authorize_activation_domain_write(
                        connection,
                        session=forged,
                    )
                assert exc_info.value.code == "ACTIVATION_REPOSITORY_CAPABILITY_INVALID"
    assert unfinished.value.code == "ACTIVATION_WRITE_NOT_FINALIZED"


def test_finalize_immediately_relocks_repository_domain_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    principal = all_permissions_principal()
    fixture, raw = make_fixture(tmp_path, principal)
    service = install_active_lease(tmp_path, fixture, principal)
    original = service.ledger.finalize_activation_domain_write
    observed = {"relocked": False}

    def finalize_and_probe(connection: sqlite3.Connection, *, session: object) -> None:
        original(connection, session=session)
        with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
            connection.execute("DELETE FROM work_items")
        observed["relocked"] = True

    monkeypatch.setattr(
        service.ledger,
        "finalize_activation_domain_write",
        finalize_and_probe,
    )
    preview = service.preview_work_item_create(raw["create"])["preview"]

    created = service.apply_work_item_create(preview)

    assert created["created"] is True
    assert observed["relocked"] is True


def test_internal_blocker_helper_cannot_bypass_canary_guard(tmp_path: Path) -> None:
    ledger = SQLiteWorkItemLedger(tmp_path)
    ledger.initialize()
    ledger.get_or_create_signing_key()
    _mark_authoritative_canary(tmp_path)
    service = WorkItemApplicationService(
        tmp_path,
        enabled=True,
        authoritative_transitions=True,
        authoritative_canary=True,
    )

    with pytest.raises(WorkItemGovernanceError) as exc_info:
        service._record_blocker_event({}, event_type="blocker_applied")

    assert exc_info.value.code == "ACTIVATION_INTERNAL_WRITE_PATH_DENIED"
    with ledger.read_connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM blocker_events").fetchone()[0] == 0


def test_canary_transaction_without_guard_session_rolls_back(tmp_path: Path) -> None:
    ledger = SQLiteWorkItemLedger(tmp_path)
    ledger.initialize()
    ledger.get_or_create_signing_key()
    _mark_authoritative_canary(tmp_path)
    service = WorkItemApplicationService(
        tmp_path,
        enabled=True,
        authoritative_transitions=True,
        authoritative_canary=True,
    )
    with ledger.read_connection() as connection:
        before = connection.execute(
            "SELECT value FROM ledger_meta WHERE key='schema_version'"
        ).fetchone()[0]

    with pytest.raises(WorkItemGovernanceError) as exc_info:
        with service._write_transaction() as connection:
            connection.execute(
                "UPDATE ledger_meta SET value='999' WHERE key='schema_version'"
            )

    assert exc_info.value.code == "ACTIVATION_WRITE_NOT_AUTHORIZED"
    with ledger.read_connection() as connection:
        after = connection.execute(
            "SELECT value FROM ledger_meta WHERE key='schema_version'"
        ).fetchone()[0]
    assert after == before


def test_active_lease_domain_write_before_guard_begin_is_rejected(tmp_path: Path) -> None:
    principal = all_permissions_principal()
    fixture, _raw = make_fixture(tmp_path, principal)
    service = install_active_lease(tmp_path, fixture, principal)

    with pytest.raises(WorkItemGovernanceError) as exc_info:
        with service._write_transaction() as connection:
            connection.execute("DELETE FROM work_items")

    assert exc_info.value.code == "ACTIVATION_REPOSITORY_WRITE_DENIED"
    with service.ledger.read_connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM work_items").fetchone()[0] == 0
        assert connection.execute("SELECT status FROM activation_leases").fetchone()[0] == "active"


def test_guard_begin_without_guard_finalize_rolls_back(tmp_path: Path) -> None:
    principal = all_permissions_principal()
    fixture, _raw = make_fixture(tmp_path, principal)
    service = install_active_lease(tmp_path, fixture, principal)
    normalized = fixture["command_slots"][0]["normalized_command"]

    with pytest.raises(WorkItemGovernanceError) as exc_info:
        with service._write_transaction() as connection:
            issued = service._activation_begin(
                connection,
                command_name="apply_work_item_create",
                normalized_command=normalized,
                source_event_key="r2:create",
            )
            assert issued is not None
            # A caller-mutated dataclass flag is not Repository finalization.
            issued._finalized = True

    assert exc_info.value.code == "ACTIVATION_WRITE_NOT_FINALIZED"
    with service.ledger.read_connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM work_items").fetchone()[0] == 0
        assert connection.execute("SELECT status FROM activation_leases").fetchone()[0] == "active"


def test_legacy_maintenance_flag_cannot_bypass_active_lease(tmp_path: Path) -> None:
    principal = all_permissions_principal()
    fixture, _raw = make_fixture(tmp_path, principal)
    service = install_active_lease(tmp_path, fixture, principal)

    for operation in (
        lambda: service.ledger.backup_to(
            tmp_path / "forbidden.sqlite3",
            reject_activation_managed=False,
        ),
        lambda: service.ledger.export_audit_package(
            reject_activation_managed=False,
        ),
    ):
        with pytest.raises(WorkItemGovernanceError) as exc_info:
            operation()
        assert exc_info.value.code == "ACTIVATION_COMPOSITION_DOWNGRADE_DENIED"


@pytest.mark.parametrize("lease_status", ("prepared", "claimed", "active", "write_frozen"))
def test_every_live_lease_status_blocks_backup_and_export(
    tmp_path: Path,
    lease_status: str,
) -> None:
    principal = all_permissions_principal()
    fixture, _raw = make_fixture(tmp_path, principal)
    service = install_active_lease(tmp_path, fixture, principal)
    with service.ledger.write_transaction() as connection:
        connection.execute("UPDATE activation_leases SET status=?", (lease_status,))

    for operation in (
        lambda: service.ledger.backup_to(tmp_path / f"{lease_status}.sqlite3"),
        service.ledger.export_audit_package,
    ):
        with pytest.raises(WorkItemGovernanceError) as exc_info:
            operation()
        assert exc_info.value.code == "ACTIVATION_COMPOSITION_DOWNGRADE_DENIED"


def test_terminal_lease_allows_control_plane_backup_export_and_restore(
    tmp_path: Path,
) -> None:
    principal = all_permissions_principal()
    fixture, _raw = make_fixture(tmp_path, principal)
    service = install_active_lease(tmp_path, fixture, principal)
    with service.ledger.read_connection() as connection:
        lease_id = str(connection.execute("SELECT lease_id FROM activation_leases").fetchone()[0])
    control = ActivationLeaseControlPlane(service.ledger, canary_root=tmp_path)
    control.freeze(lease_id=lease_id, reason="r3-maintenance-test")
    control.close(lease_id=lease_id, reason="r3-maintenance-test")
    maintenance = WorkItemApplicationService(
        tmp_path,
        enabled=True,
        authoritative_transitions=False,
    )

    backup_path = tmp_path / "terminal-lease.sqlite3"
    backup = maintenance.backup_ledger(backup_path)
    exported = maintenance.export_audit_package()
    generation = maintenance.ledger.database_generation()
    restored = maintenance.restore_ledger(
        backup_path,
        expected_database_generation=generation,
    )

    assert backup["ok"] is True
    assert exported["manifest"]["record_counts"]["work_items"] == 0
    assert restored["database_generation"] == generation + 1


@pytest.mark.parametrize("terminal_status", ("revoked", "expired"))
def test_other_terminal_lease_statuses_allow_control_plane_maintenance(
    tmp_path: Path,
    terminal_status: str,
) -> None:
    principal = all_permissions_principal()
    fixture, _raw = make_fixture(tmp_path, principal)
    service = install_active_lease(tmp_path, fixture, principal)
    with service.ledger.write_transaction() as connection:
        connection.execute("UPDATE activation_leases SET status=?", (terminal_status,))
    maintenance = WorkItemApplicationService(
        tmp_path,
        enabled=True,
        authoritative_transitions=False,
    )

    backup = maintenance.backup_ledger(tmp_path / f"{terminal_status}.sqlite3")
    exported = maintenance.export_audit_package()

    assert backup["ok"] is True
    assert exported["manifest"]["record_counts"]["work_items"] == 0


def test_ordinary_shadow_project_remains_compatible(tmp_path: Path) -> None:
    service = WorkItemApplicationService(tmp_path, enabled=True)
    work_item_id = _create(service)

    assert service.get_work_item(work_item_id)["state"] == "proposed"


def test_architecture_classifies_every_application_write_transaction() -> None:
    project_root = Path(__file__).resolve().parents[1]
    result = check_work_item_architecture(project_root)

    assert result["ok"] is True, result["violations"]
    assert not {
        item["rule"]
        for item in result["violations"]
    } & {
        "application_write_transaction_unclassified",
        "application_write_bypasses_composition_guard",
    }


def test_architecture_rejects_future_unclassified_application_writer(
    tmp_path: Path,
) -> None:
    core = tmp_path / "runner" / "work_item_governance"
    core.mkdir(parents=True)
    (core / "service.py").write_text(
        """
class WorkItemApplicationService:
    def future_hidden_write(self):
        with self._write_transaction() as connection:
            connection.execute('DELETE FROM work_items')
""",
        encoding="utf-8",
    )

    result = check_work_item_architecture(tmp_path)

    assert {
        "rule": "application_write_transaction_unclassified",
        "path": "runner/work_item_governance/service.py",
        "import": "future_hidden_write",
    } in result["violations"]


def test_architecture_rejects_future_repository_unlock_caller(tmp_path: Path) -> None:
    core = tmp_path / "runner" / "work_item_governance"
    core.mkdir(parents=True)
    (core / "activation.py").write_text(
        """
class AuthoritativeCanaryGuard:
    def begin_write(self):
        self.ledger.authorize_activation_domain_write(self.connection, session=self.session)
""",
        encoding="utf-8",
    )
    (tmp_path / "runner" / "future_writer.py").write_text(
        """
def bypass(ledger, connection, session):
    ledger.authorize_activation_domain_write(connection, session=session)
""",
        encoding="utf-8",
    )

    result = check_work_item_architecture(tmp_path)

    assert {
        "rule": "activation_repository_unlock_bypass",
        "path": "runner/future_writer.py",
        "import": "authorize_activation_domain_write",
    } in result["violations"]
