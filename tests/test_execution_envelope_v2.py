from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from runner.execution_envelope import (
    CURRENT_ENVELOPE_SCHEMA_VERSION,
    ENVELOPE_CHECK_FAILED_CLOSED,
    ENVELOPE_CHECK_PASSED,
    validate_execution_envelope,
)
from runner.executor_confirmation import run_once_preview_artifact
from runner.executor_events import ExecutorEventStore
from runner.executor_run_claims import ExecutorRunClaimStore
from runner.executor_run_reports import ExecutorRunReportStore
from runner.executor_session import ExecutorSessionStore
from runner.plan_loader import PlanLoader
from runner.work_item_governance.ids import new_stable_id
from runner.work_item_governance.references import resolve_execution_attempt_binding
from runner.work_item_governance.schema_loader import validate_governance_record


def envelope_v2(*, bound: bool = True) -> dict:
    binding = {
        "work_item_id": new_stable_id("work_item"),
        "task_version": 1,
        "attempt_id": new_stable_id("attempt"),
        "objective_ref": "objective://task/1",
    }
    if not bound:
        binding = {
            "work_item_id": None,
            "task_version": None,
            "attempt_id": None,
            "objective_ref": None,
        }
    return {
        "envelope_id": "envelope-v2",
        "envelope_schema_version": CURRENT_ENVELOPE_SCHEMA_VERSION,
        "version_taskbook_ref": {"path": "docs/taskbook-v2.md", "raw_snapshot_sha256": "a" * 64},
        "master_taskbook_ref": {"path": "PROJECT_MASTER_TASKBOOK.md", "raw_snapshot_sha256": "b" * 64},
        "stage_taskbook_ref": {"path": "docs/stage.md", "raw_snapshot_sha256": "c" * 64},
        "authority_mode": "local_execution",
        "local_execution_authorization_ref": {"id": "auth"},
        "imported_receipt_authorization_ref": {},
        "allowed_files": ["runner/**"],
        "forbidden_files": [".env"],
        "allowed_commands": ["pytest"],
        "validation_commands": ["pytest"],
        "timeout_limits": {"seconds": 60},
        "network_policy": {"allowed": False},
        "secrets_policy": {"mode": "deny"},
        "destructive_operation_policy": {"mode": "deny"},
        "retry_policy": {"max": 0},
        "stop_conditions": ["tests complete"],
        **binding,
        "artifact_contract": {"required": ["test_report"]},
        "approval_requirements": {"review": True},
        "reporting_destination": {"kind": "ledger_reference"},
        "expected_receipt_contract": {"schema": "execution_evidence_receipt.v1"},
    }


def test_v2_accepts_caller_supplied_taskbook_hashes_and_bound_attempt() -> None:
    envelope = envelope_v2()
    result = validate_execution_envelope(envelope)
    assert result["envelope_check_result"] == ENVELOPE_CHECK_PASSED
    assert result["work_item_id"] == envelope["work_item_id"]
    assert result["attempt_id"] == envelope["attempt_id"]
    assert result["writes_delivery_state"] is False
    validate_governance_record("execution_envelope.v2", envelope)


def test_v2_allows_explicit_unbound_compatibility_path() -> None:
    result = validate_execution_envelope(envelope_v2(bound=False))
    assert result["envelope_check_result"] == ENVELOPE_CHECK_PASSED
    assert result["work_item_id"] is None
    assert result["work_item_binding_is_optional_for_legacy_execution"] is True


def test_v2_partial_binding_and_unsafe_taskbook_ref_fail_closed() -> None:
    envelope = envelope_v2()
    envelope["attempt_id"] = None
    envelope["master_taskbook_ref"]["path"] = "../outside.md"
    result = validate_execution_envelope(envelope)
    assert result["envelope_check_result"] == ENVELOPE_CHECK_FAILED_CLOSED
    assert "attempt_id" in result["rejected_fields"]
    assert "master_taskbook_ref" in result["rejected_fields"]


def test_v2_exact_caller_expected_binding_detects_mismatch() -> None:
    envelope = envelope_v2()
    expected = copy.deepcopy(envelope["version_taskbook_ref"])
    expected["raw_snapshot_sha256"] = "f" * 64
    result = validate_execution_envelope(envelope, expected_version_taskbook_ref=expected)
    assert result["envelope_check_result"] == ENVELOPE_CHECK_FAILED_CLOSED
    assert "reference_mismatch" in {item["conflict_type"] for item in result["known_conflicts"]}


def test_claim_event_and_session_preserve_optional_attempt_binding(tmp_path: Path) -> None:
    binding = {
        "work_item_id": new_stable_id("work_item"),
        "task_version": 1,
        "attempt_id": new_stable_id("attempt"),
        "artifact_refs": [],
    }
    claims = ExecutorRunClaimStore(
        str(tmp_path),
        ".colameta/runtime/previews",
        "claims",
        heartbeat_interval_seconds=5,
        heartbeat_stale_multiplier=3,
        heartbeat_stale_min_seconds=15,
    )
    claim = claims.acquire_claim(
        preview_id="preview-1",
        artifact={"artifact_kind": "run_once", **binding},
        provider="codex",
        execution_mode="run",
    )["claim"]
    assert {key: claim[key] for key in binding} == binding
    assert claims.refresh_heartbeat(preview_id="preview-1", run_id=claim["run_id"])
    assert claims.read_claim("preview-1")["attempt_id"] == binding["attempt_id"]

    events = ExecutorEventStore(str(tmp_path))
    events.append("run-1", "heartbeat", {}, event_context={"run_id": "run-1", **binding})
    assert events.read("run-1")[-1]["attempt_id"] == binding["attempt_id"]

    sessions = ExecutorSessionStore(str(tmp_path))
    session = sessions.record_execution(
        provider="codex",
        version="v1",
        execution_mode="run",
        attempt=1,
        **binding,
    )
    assert session["record"]["work_item_id"] == binding["work_item_id"]
    assert session["record"]["attempt_id"] == binding["attempt_id"]


def test_plan_can_carry_optional_task_and_attempt_binding(tmp_path: Path) -> None:
    binding = {
        "work_item_id": new_stable_id("work_item"),
        "task_version": 2,
        "attempt_id": new_stable_id("attempt"),
    }
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(
        json.dumps({
            "project_name": "demo",
            "plan_version": "plan-v2",
            "project_root": str(tmp_path),
            **binding,
            "versions": [{
                "version": "v1",
                "name": "Bound version",
                "prompt_file": "prompt.md",
                "enabled": True,
            }],
        }),
        encoding="utf-8",
    )
    loader = PlanLoader()
    plan = loader.load_plan(str(plan_file))
    loader.validate_plan(plan)

    assert plan.work_item_id == binding["work_item_id"]
    assert resolve_execution_attempt_binding(plan, plan.versions[0]) == {**binding, "artifact_refs": []}


def test_partial_plan_binding_fails_closed() -> None:
    loader = PlanLoader()
    plan = loader._parse_plan({
        "project_name": "demo",
        "versions": [{
            "version": "v1",
            "name": "Invalid binding",
            "prompt_file": "prompt.md",
            "attempt_id": new_stable_id("attempt"),
        }],
    })

    with pytest.raises(ValueError, match="Work Item binding invalid"):
        loader.validate_plan(plan)


def test_preview_and_report_propagate_complete_attempt_binding(tmp_path: Path) -> None:
    binding = {
        "work_item_id": new_stable_id("work_item"),
        "task_version": 3,
        "attempt_id": new_stable_id("attempt"),
        "artifact_refs": [],
    }
    artifact = run_once_preview_artifact(
        preview_id="preview-bound",
        project_root=str(tmp_path),
        preflight_result={"current_version": "v1", **binding},
        provider="codex",
        execution_mode="run",
        created_at="2026-01-01T00:00:00+00:00",
        expires_at="2026-01-01T01:00:00+00:00",
    )
    assert {key: artifact[key] for key in binding} == binding

    report_result = ExecutorRunReportStore(str(tmp_path)).record_report(
        version="v1",
        provider="codex",
        execution_mode="run",
        status="completed",
        **binding,
    )
    report = json.loads(Path(report_result["json_file"]).read_text(encoding="utf-8"))
    assert {key: report[key] for key in binding} == binding
