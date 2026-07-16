from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from runner.work_item_governance.errors import WorkItemGovernanceError
from runner.work_item_governance.repository import SQLiteWorkItemLedger
from runner.work_item_governance.schema_loader import validate_governance_record
from runner.work_item_governance.service import WorkItemApplicationService


def origin(ref: str = "manual-1") -> dict[str, str]:
    return {
        "kind": "manual",
        "ref": ref,
        "snapshot_digest": hashlib.sha256(ref.encode()).hexdigest(),
    }


def create(service: WorkItemApplicationService, ref: str = "manual-1") -> dict:
    preview = service.preview_work_item_create(
        {
            "origin": origin(ref),
            "title": "Bounded task",
            "task": {"objective_ref": "objective://one", "plan_version_refs": [f"plan:{ref}:v1"]},
            "idempotency_key": f"create:{ref}",
        }
    )
    assert preview["creates_work_item"] is False
    return service.apply_work_item_create(preview["preview"])["work_item"]


def test_default_off_does_not_create_ledger(tmp_path: Path) -> None:
    service = WorkItemApplicationService(tmp_path)
    assert service.status()["enabled"] is False
    with pytest.raises(WorkItemGovernanceError) as raised:
        service.list_work_items()
    assert raised.value.code == "WORK_ITEM_GOVERNANCE_DISABLED"
    assert not service.ledger.path.exists()


def test_explicit_create_is_idempotent_and_has_secure_sqlite_settings(tmp_path: Path) -> None:
    service = WorkItemApplicationService(tmp_path, enabled=True)
    preview = service.preview_work_item_create(
        {"origin": origin(), "objective": "Do it", "idempotency_key": "create:1"}
    )["preview"]
    first = service.apply_work_item_create(preview)
    second = service.apply_work_item_create(preview)
    assert first["created"] is True
    assert second["created"] is False
    assert second["idempotent_replay"] is True
    assert second["work_item"]["state"] == "proposed"
    assert second["work_item"]["gate_events"] == []
    assert stat.S_IMODE(service.ledger.path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(service.ledger.path.stat().st_mode) == 0o600
    with sqlite3.connect(service.ledger.path) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        connection.execute("PRAGMA foreign_keys=ON")
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 5


def test_preview_is_ttl_bound_project_bound_and_content_bound(tmp_path: Path) -> None:
    clock = [datetime(2026, 7, 11, tzinfo=timezone.utc)]
    service = WorkItemApplicationService(tmp_path / "one", enabled=True, now=lambda: clock[0])
    (tmp_path / "one").mkdir()
    preview = service.preview_work_item_create({"origin": origin()}, ttl_seconds=2)["preview"]
    tampered = json.loads(json.dumps(preview))
    tampered["command"]["attributes"]["title"] = "tampered"
    with pytest.raises(WorkItemGovernanceError) as raised:
        service.apply_work_item_create(tampered)
    assert raised.value.code in {"PREVIEW_SIGNATURE_INVALID", "PREVIEW_CONTENT_MISMATCH"}

    other_root = tmp_path / "two"
    other_root.mkdir()
    other = WorkItemApplicationService(other_root, enabled=True, now=lambda: clock[0])
    with pytest.raises(WorkItemGovernanceError) as raised:
        other.apply_work_item_create(preview)
    assert raised.value.code in {"PREVIEW_PROJECT_MISMATCH", "PREVIEW_SIGNATURE_INVALID"}

    clock[0] += timedelta(seconds=3)
    with pytest.raises(WorkItemGovernanceError) as raised:
        service.apply_work_item_create(preview)
    assert raised.value.code == "PREVIEW_EXPIRED"


def test_source_deletion_does_not_affect_query(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("source", encoding="utf-8")
    service = WorkItemApplicationService(tmp_path, enabled=True)
    item = create(service, str(source.name))
    source.unlink()
    assert service.get_work_item(item["work_item_id"])["origin"]["ref"] == source.name


def test_explicit_legacy_import_preserves_only_explicit_refs_and_marks_imported(tmp_path: Path) -> None:
    service = WorkItemApplicationService(tmp_path, enabled=True)
    legacy = {"plan": "v1", "run": "run-1", "unrelated": {"value": 3}}
    preview_result = service.preview_legacy_work_item_import(
        {
            "legacy_record": legacy,
            "legacy_refs": [{"kind": "plan", "ref": "v1"}],
            "idempotency_key": "legacy:1",
        }
    )
    assert preview_result["history_relationships_inferred"] is False
    applied = service.apply_legacy_work_item_import(preview_result["preview"])
    item = applied["work_item"]
    assert item["imported"] is True
    assert item["origin"]["kind"] == "imported"
    assert item["attributes"]["legacy_refs"] == [{"kind": "plan", "ref": "v1"}]
    exported = service.export_audit_package()
    assert "unrelated" not in json.dumps(exported)
    assert exported["manifest"]["contains_preview_signing_key"] is False


def test_multiple_task_versions_attempts_and_idempotent_completion(tmp_path: Path) -> None:
    service = WorkItemApplicationService(tmp_path, enabled=True)
    item = create(service)
    wi = item["work_item_id"]
    first = service.create_execution_attempt(
        {"work_item_id": wi, "task_version": 1, "source_event_key": "claim:1"}
    )["attempt"]
    service.add_task_version(
        {
            "work_item_id": wi,
            "task_version": 2,
            "task": {"plan_version_refs": ["plan:v2"]},
            "source_event_key": "task:v2",
        }
    )
    second = service.create_execution_attempt(
        {"work_item_id": wi, "task_version": 2, "source_event_key": "claim:2"}
    )["attempt"]
    assert first["attempt_id"] != second["attempt_id"]
    completion = {
        "attempt_id": first["attempt_id"],
        "status": "failed",
        "source_event_key": "complete:1",
        "artifacts": [
            {
                "work_item_id": wi,
                "task_version": 1,
                "attempt_id": first["attempt_id"],
                "kind": "report",
                "uri": "https://e.invalid/report/1",
                "immutable_ref": "report:1",
                "digest": "a" * 64,
                "source_event_key": "artifact:1",
            }
        ],
    }
    assert service.complete_execution_attempt(completion)["idempotent_replay"] is False
    assert service.complete_execution_attempt(completion)["idempotent_replay"] is True
    current = service.get_work_item(wi)
    assert [task["task_version"] for task in current["task_versions"]] == [1, 2]
    assert len(current["execution_attempts"]) == 2
    assert len(current["artifact_refs"]) == 1
    validate_governance_record("work_item.v1", current)
    for task in current["task_versions"]:
        validate_governance_record("task_version.v1", task)
    for attempt in current["execution_attempts"]:
        validate_governance_record("execution_attempt.v1", attempt)
    validate_governance_record("artifact_reference.v1", current["artifact_refs"][0])


def test_artifact_digest_mismatch_fails_without_registration(tmp_path: Path) -> None:
    service = WorkItemApplicationService(tmp_path, enabled=True)
    item = create(service)
    path = tmp_path / "report.txt"
    path.write_text("actual", encoding="utf-8")
    with pytest.raises(WorkItemGovernanceError) as raised:
        service.register_artifact_reference(
            {
                "work_item_id": item["work_item_id"],
                "task_version": 1,
                "kind": "report",
                "uri": "report.txt",
                "immutable_ref": "report:mismatch",
                "digest": "0" * 64,
                "source_event_key": "artifact:mismatch",
            }
        )
    assert raised.value.code == "ARTIFACT_DIGEST_MISMATCH"
    assert service.get_work_item(item["work_item_id"])["artifact_refs"] == []


def test_missing_relative_artifact_fails_without_registration(tmp_path: Path) -> None:
    service = WorkItemApplicationService(tmp_path, enabled=True)
    item = create(service)

    with pytest.raises(WorkItemGovernanceError) as raised:
        service.register_artifact_reference(
            {
                "work_item_id": item["work_item_id"],
                "task_version": 1,
                "kind": "report",
                "uri": "missing/report.txt",
                "immutable_ref": "report:missing",
                "digest": "0" * 64,
                "source_event_key": "artifact:missing",
            }
        )

    assert raised.value.code == "ARTIFACT_FILE_MISSING"
    assert service.get_work_item(item["work_item_id"])["artifact_refs"] == []


def test_missing_relative_completion_artifact_fails_without_completion(tmp_path: Path) -> None:
    service = WorkItemApplicationService(tmp_path, enabled=True)
    item = create(service)
    attempt = service.create_execution_attempt(
        {
            "work_item_id": item["work_item_id"],
            "task_version": 1,
            "source_event_key": "claim:missing-artifact",
        }
    )["attempt"]

    with pytest.raises(WorkItemGovernanceError) as raised:
        service.complete_execution_attempt(
            {
                "attempt_id": attempt["attempt_id"],
                "status": "completed",
                "source_event_key": "complete:missing-artifact",
                "artifacts": [
                    {
                        "work_item_id": item["work_item_id"],
                        "task_version": 1,
                        "attempt_id": attempt["attempt_id"],
                        "kind": "report",
                        "uri": "missing/completion-report.txt",
                        "immutable_ref": "report:completion-missing",
                        "digest": "0" * 64,
                        "source_event_key": "artifact:completion-missing",
                    }
                ],
            }
        )

    assert raised.value.code == "ARTIFACT_FILE_MISSING"
    current = service.get_work_item(item["work_item_id"])
    assert current["execution_attempts"][0]["status"] == "claimed"
    assert current["artifact_refs"] == []


def test_completion_idempotency_key_rejects_changed_content(tmp_path: Path) -> None:
    service = WorkItemApplicationService(tmp_path, enabled=True)
    item = create(service)
    attempt = service.create_execution_attempt(
        {"work_item_id": item["work_item_id"], "task_version": 1, "source_event_key": "claim:conflict"}
    )["attempt"]
    command = {
        "attempt_id": attempt["attempt_id"],
        "status": "completed",
        "metadata": {"result": "one"},
        "source_event_key": "completion:conflict",
    }
    service.complete_execution_attempt(command)
    changed = {**command, "metadata": {"result": "different"}}
    with pytest.raises(WorkItemGovernanceError) as raised:
        service.complete_execution_attempt(changed)
    assert raised.value.code == "IDEMPOTENCY_CONFLICT"


def test_concurrent_duplicate_apply_creates_one_work_item(tmp_path: Path) -> None:
    service = WorkItemApplicationService(tmp_path, enabled=True)
    preview = service.preview_work_item_create(
        {"origin": origin(), "idempotency_key": "concurrent:create"}
    )["preview"]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _index: service.apply_work_item_create(preview), range(16)))
    assert sum(result["created"] is True for result in results) == 1
    assert service.list_work_items()["count"] == 1


def test_migration_failure_rolls_back_and_backup_restore_uses_backup_api(tmp_path: Path) -> None:
    broken_root = tmp_path / "broken"
    broken_root.mkdir()
    ledger = SQLiteWorkItemLedger(
        broken_root,
        migrations={1: ("CREATE TABLE ledger_meta(key TEXT PRIMARY KEY)", "THIS IS NOT SQL")},
    )
    with pytest.raises(WorkItemGovernanceError) as raised:
        ledger.initialize()
    assert raised.value.code == "LEDGER_MIGRATION_FAILED"
    with sqlite3.connect(ledger.path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 0
        assert connection.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='ledger_meta'"
        ).fetchone()[0] == 0

    project = tmp_path / "project"
    project.mkdir()
    service = WorkItemApplicationService(project, enabled=True)
    item = create(service)
    backup = tmp_path / "backup.sqlite3"
    receipt = service.backup_ledger(backup)
    assert receipt["backup_api"] == "sqlite3.Connection.backup"
    assert receipt["integrity_check"] == ["ok"]
    service.add_task_version(
        {
            "work_item_id": item["work_item_id"],
            "task_version": 2,
            "task": {},
            "source_event_key": "task:after-backup",
        }
    )
    generation = service.status()["database_generation"]
    restored = service.restore_ledger(
        backup,
        expected_database_generation=generation,
    )
    assert restored["staged_copy"]["integrity_check"] == ["ok"]
    assert restored["database_generation"] == generation + 1
    assert service.get_work_item(item["work_item_id"])["current_task_version"] == 1


def test_corrupt_database_and_symlinked_ledger_directory_fail_closed(tmp_path: Path) -> None:
    corrupt = tmp_path / "corrupt.sqlite3"
    corrupt.write_bytes(b"not a sqlite database")
    ledger = SQLiteWorkItemLedger(tmp_path)
    with pytest.raises(WorkItemGovernanceError) as raised:
        ledger.integrity_check(corrupt)
    assert raised.value.code == "LEDGER_INTEGRITY_CHECK_FAILED"

    project = tmp_path / "symlink-project"
    outside = tmp_path / "outside"
    project.mkdir()
    outside.mkdir()
    (project / ".colameta").mkdir()
    (project / ".colameta" / "ledger").symlink_to(outside, target_is_directory=True)
    unsafe = SQLiteWorkItemLedger(project)
    with pytest.raises(WorkItemGovernanceError) as raised:
        unsafe.initialize()
    assert raised.value.code == "LEDGER_PATH_UNSAFE"

    root_symlink_project = tmp_path / "root-symlink-project"
    root_symlink_project.mkdir()
    root_outside = tmp_path / "root-outside"
    root_outside.mkdir()
    (root_symlink_project / ".colameta").symlink_to(root_outside, target_is_directory=True)
    with pytest.raises(WorkItemGovernanceError) as raised:
        SQLiteWorkItemLedger(root_symlink_project).initialize()
    assert raised.value.code == "LEDGER_PATH_UNSAFE"
    assert not (root_outside / "ledger").exists()

    file_symlink_project = tmp_path / "file-symlink-project"
    ledger_dir = file_symlink_project / ".colameta" / "ledger"
    ledger_dir.mkdir(parents=True)
    outside_database = tmp_path / "outside.sqlite3"
    outside_database.touch()
    (ledger_dir / "work-items.sqlite3").symlink_to(outside_database)
    with pytest.raises(WorkItemGovernanceError) as raised:
        SQLiteWorkItemLedger(file_symlink_project).initialize()
    assert raised.value.code == "LEDGER_PATH_UNSAFE"

    future_project = tmp_path / "future-project"
    future_path = future_project / ".colameta" / "ledger" / "work-items.sqlite3"
    future_path.parent.mkdir(parents=True)
    with sqlite3.connect(future_path) as connection:
        connection.execute("PRAGMA user_version=99")
    with pytest.raises(WorkItemGovernanceError) as raised:
        SQLiteWorkItemLedger(future_project).initialize()
    assert raised.value.code == "LEDGER_SCHEMA_TOO_NEW"


def test_restore_rejects_active_writer(tmp_path: Path) -> None:
    service = WorkItemApplicationService(tmp_path, enabled=True)
    create(service, "restore-lock")
    backup = tmp_path / "restore-lock-backup.sqlite3"
    service.backup_ledger(backup)
    generation = service.status()["database_generation"]
    entered = threading.Event()
    release = threading.Event()

    def hold_writer() -> None:
        with service.ledger.write_transaction():
            entered.set()
            assert release.wait(timeout=10)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(hold_writer)
        assert entered.wait(timeout=10)
        try:
            with pytest.raises(WorkItemGovernanceError) as raised:
                service.restore_ledger(
                    backup,
                    expected_database_generation=generation,
                )
            assert raised.value.code == "LEDGER_RESTORE_ACTIVE_CONNECTIONS"
        finally:
            release.set()
        future.result(timeout=10)

    with pytest.raises(WorkItemGovernanceError) as raised:
        service.restore_ledger(
            backup,
            expected_database_generation=generation + 99,
        )
    assert raised.value.code == "LEDGER_RESTORE_GENERATION_MISMATCH"


def test_sensitive_and_oversized_ledger_payloads_are_rejected(tmp_path: Path) -> None:
    service = WorkItemApplicationService(tmp_path, enabled=True)
    with pytest.raises(WorkItemGovernanceError) as raised:
        service.preview_work_item_create(
            {
                "origin": origin(),
                "attributes": {"access_token": "must-not-enter-ledger"},
            }
        )
    assert raised.value.code == "SENSITIVE_FIELD_REJECTED"
    with pytest.raises(WorkItemGovernanceError) as raised:
        service.preview_work_item_create(
            {
                "origin": origin("large"),
                "attributes": {"description": "x" * 70_000},
            }
        )
    assert raised.value.code == "TEXT_TOO_LARGE"
    with pytest.raises(WorkItemGovernanceError) as raised:
        service.preview_work_item_create(
            {
                "origin": origin("task-secret"),
                "task": {"payload": {"api_key": "must-not-enter-ledger"}},
            }
        )
    assert raised.value.code == "SENSITIVE_FIELD_REJECTED"
    with pytest.raises(WorkItemGovernanceError) as raised:
        service.preview_work_item_create(
            {
                "origin": origin("too-many-properties"),
                "attributes": {f"field_{index}": index for index in range(129)},
            }
        )
    assert raised.value.code == "METADATA_TOO_LARGE"


def test_attempt_claim_replay_remains_idempotent_after_completion(tmp_path: Path) -> None:
    service = WorkItemApplicationService(tmp_path, enabled=True)
    item = create(service)
    claim = {
        "work_item_id": item["work_item_id"],
        "task_version": 1,
        "status": "running",
        "metadata": {"claim": "initial"},
        "source_event_key": "claim:replay-after-completion",
    }
    attempt = service.create_execution_attempt(claim)["attempt"]
    service.complete_execution_attempt(
        {
            "attempt_id": attempt["attempt_id"],
            "status": "completed",
            "metadata": {"completion": "final"},
            "source_event_key": "completion:replay-after-completion",
        }
    )

    replay = service.create_execution_attempt(claim)
    assert replay["idempotent_replay"] is True
    assert replay["attempt"]["attempt_id"] == attempt["attempt_id"]
    event_types = {
        event["event_type"]
        for event in service.get_work_item_timeline(item["work_item_id"])["events"]
    }
    assert {"attempt_claim", "attempt_completion"}.issubset(event_types)


def test_stale_task_version_rejects_new_runtime_attempt(tmp_path: Path) -> None:
    service = WorkItemApplicationService(tmp_path, enabled=True)
    item = create(service)
    service.add_task_version(
        {
            "work_item_id": item["work_item_id"],
            "task_version": 2,
            "task": {"objective_ref": "objective://current-v2"},
            "source_event_key": "task:current-v2",
        }
    )
    with pytest.raises(WorkItemGovernanceError) as raised:
        service.create_execution_attempt(
            {
                "work_item_id": item["work_item_id"],
                "task_version": 1,
                "source_event_key": "attempt:stale-v1",
            }
        )
    assert raised.value.code == "TASK_VERSION_STALE"


def test_historical_attempt_has_no_dispatch_authority(tmp_path: Path) -> None:
    service = WorkItemApplicationService(tmp_path, enabled=True)
    item = create(service)
    historical = service.bind_historical_execution_attempt(
        {
            "work_item_id": item["work_item_id"],
            "task_version": 1,
            "status": "completed",
            "historical_reason": "Explicit legacy run import",
            "imported": True,
            "source_event_key": "historical:attempt:1",
            "external_refs": [{"kind": "legacy_run", "ref": "run-legacy-1"}],
        }
    )["attempt"]
    assert historical["attempt_kind"] == "historical"
    assert historical["dispatch_authorized"] is False
    authority = service.get_execution_attempt_dispatch_authority(
        attempt_id=historical["attempt_id"],
        work_item_id=item["work_item_id"],
        task_version=1,
    )
    assert authority["dispatch_authorized"] is False
    assert "ATTEMPT_DISPATCH_NOT_AUTHORIZED" in authority["reason_codes"]
    with pytest.raises(WorkItemGovernanceError) as raised:
        service.complete_execution_attempt(
            {
                "attempt_id": historical["attempt_id"],
                "status": "completed",
                "source_event_key": "historical:completion:forbidden",
            }
        )
    assert raised.value.code == "HISTORICAL_ATTEMPT_NOT_COMPLETABLE"


def test_artifact_registration_rejects_metadata_change_on_same_event_key(tmp_path: Path) -> None:
    service = WorkItemApplicationService(tmp_path, enabled=True)
    item = create(service)
    command = {
        "work_item_id": item["work_item_id"],
        "task_version": 1,
        "kind": "report",
        "uri": "https://e.invalid/report/idempotency",
        "immutable_ref": "report:idempotency",
        "digest": "a" * 64,
        "metadata": {"revision": 1},
        "source_event_key": "artifact:idempotency",
    }
    service.register_artifact_reference(command)
    with pytest.raises(WorkItemGovernanceError) as raised:
        service.register_artifact_reference({**command, "metadata": {"revision": 2}})
    assert raised.value.code == "IDEMPOTENCY_CONFLICT"
