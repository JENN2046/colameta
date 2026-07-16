from __future__ import annotations

import json
from pathlib import Path

import pytest

from runner.work_item_governance.architecture import (
    LEASE_DENIED_WRITE_METHODS,
    check_work_item_architecture,
)
from runner.work_item_governance.errors import WorkItemGovernanceError
from runner.work_item_governance.ids import new_stable_id
from runner.work_item_governance.service import WorkItemApplicationService
from work_item_r2_helpers import (
    all_permissions_principal,
    install_active_lease,
    make_fixture,
)


def _legacy_command(service: WorkItemApplicationService) -> dict[str, object]:
    return service._normalize_legacy_import_command(
        {
            "legacy_record": {"plan": "legacy-plan-v1", "run": "legacy-run-v1"},
            "legacy_refs": [{"kind": "plan", "ref": "legacy-plan-v1"}],
            "idempotency_key": "r3:legacy-import",
        }
    )


def _private_preview() -> dict[str, object]:
    return {
        "preview_id": new_stable_id("preview"),
        "generated_ids": {"work_item_id": new_stable_id("work_item")},
    }


def _lease_and_domain_snapshot(service: WorkItemApplicationService) -> dict[str, object]:
    with service.ledger.read_connection() as connection:
        lease = connection.execute(
            "SELECT status,state_version,usage_json FROM activation_leases"
        ).fetchone()
        return {
            "lease": None
            if lease is None
            else {
                "status": str(lease["status"]),
                "state_version": int(lease["state_version"]),
                "usage": json.loads(str(lease["usage_json"])),
            },
            "lease_events": connection.execute(
                "SELECT COUNT(*) FROM activation_lease_events"
            ).fetchone()[0],
            "work_items": connection.execute("SELECT COUNT(*) FROM work_items").fetchone()[0],
            "task_versions": connection.execute("SELECT COUNT(*) FROM task_versions").fetchone()[0],
        }


def test_private_legacy_create_helper_fails_before_facts_or_quota(tmp_path: Path) -> None:
    principal = all_permissions_principal()
    fixture, _raw = make_fixture(tmp_path, principal)
    service = install_active_lease(tmp_path, fixture, principal)
    command = _legacy_command(service)
    before = _lease_and_domain_snapshot(service)

    with pytest.raises(WorkItemGovernanceError) as exc_info:
        service._apply_create(
            _private_preview(),
            command,
            creation_operation="legacy_import",
        )

    assert exc_info.value.code == "ACTIVATION_INTERNAL_WRITE_PATH_DENIED"
    assert _lease_and_domain_snapshot(service) == before


def test_imported_origin_cannot_be_relabelled_as_allowed_create(tmp_path: Path) -> None:
    principal = all_permissions_principal()
    fixture, _raw = make_fixture(tmp_path, principal)
    service = install_active_lease(tmp_path, fixture, principal)
    legacy = _legacy_command(service)
    smuggled = {
        key: legacy[key]
        for key in ("origin", "attributes", "task", "idempotency_key")
    }
    before = _lease_and_domain_snapshot(service)

    with pytest.raises(WorkItemGovernanceError) as exc_info:
        service._apply_create(
            _private_preview(),
            smuggled,
            creation_operation="create",
        )

    assert exc_info.value.code == "IMPORT_COMMAND_REQUIRED"
    assert _lease_and_domain_snapshot(service) == before


def test_public_legacy_preview_apply_remains_compatible_for_shadow_project(tmp_path: Path) -> None:
    service = WorkItemApplicationService(tmp_path, enabled=True)
    preview = service.preview_legacy_work_item_import(
        {
            "legacy_record": {"plan": "legacy-plan-v1"},
            "legacy_refs": [{"kind": "plan", "ref": "legacy-plan-v1"}],
            "idempotency_key": "r3:compatible-legacy-import",
        }
    )["preview"]

    result = service.apply_legacy_work_item_import(preview)

    assert result["created"] is True
    assert result["work_item"]["imported"] is True
    assert result["work_item"]["origin"]["kind"] == "imported"


def test_unknown_private_creation_operation_fails_before_write(tmp_path: Path) -> None:
    service = WorkItemApplicationService(tmp_path, enabled=True)

    with pytest.raises(WorkItemGovernanceError) as exc_info:
        service._apply_create({}, {}, creation_operation="future_import_alias")

    assert exc_info.value.code == "CREATE_OPERATION_UNSUPPORTED"
    assert not service.ledger.path.exists()


def test_architecture_keeps_legacy_import_denied_and_private_create_guarded() -> None:
    assert "apply_legacy_work_item_import" in LEASE_DENIED_WRITE_METHODS
    project_root = Path(__file__).resolve().parents[1]
    result = check_work_item_architecture(project_root)
    assert result["ok"] is True, result["violations"]


def test_architecture_rejects_private_create_without_legacy_boundary(tmp_path: Path) -> None:
    core = tmp_path / "runner" / "work_item_governance"
    core.mkdir(parents=True)
    (core / "service.py").write_text(
        """
class WorkItemApplicationService:
    def _apply_create(self, command):
        self._normalize_create_command(command, imported=False)
        self._normalize_legacy_import_command(command)
        with self._write_transaction() as connection:
            self._activation_begin(connection, command_name='apply_work_item_create')
""",
        encoding="utf-8",
    )

    result = check_work_item_architecture(tmp_path)

    assert {
        "rule": "activation_legacy_create_boundary_missing",
        "path": "runner/work_item_governance/service.py",
        "import": "_apply_create",
    } in result["violations"]
