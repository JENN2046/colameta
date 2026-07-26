from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess

from runner.mcp_commander_public import COMMANDER_EXPOSED_TOOLS
from runner.mcp_server import MCPPlanningBridgeServer
from runner.mcp_validation_run import (
    MCPValidationRunManager,
    VALIDATION_RUN_RESULT_SCHEMA_VERSION,
    canonical_validation_result_sha256,
)
from runner.p1_release_evidence import (
    P1_RELEASE_EVIDENCE_LEGACY_PREVIEW_SCHEMA_VERSION,
    P1_RELEASE_EVIDENCE_LEGACY_RECEIPT_SCHEMA_VERSION,
    P1_RELEASE_EVIDENCE_PREVIEW_SCHEMA_VERSION,
    P1_RELEASE_EVIDENCE_RECEIPT_SCHEMA_VERSION,
    P1ReleaseEvidenceManager,
    get_p1_release_evidence_status,
)
from runner.p1_release_gate import build_p1_client_release_gate
from runner.review_manifest_validation import (
    REVIEW_MANIFEST_VALIDATION_SOURCE_SCHEMA_VERSION,
    build_review_manifest_validation_contract,
    canonical_manifest_validation_sha256,
)


def _git_fixture(tmp_path: Path) -> tuple[Path, str]:
    project = tmp_path / "p1-release-evidence"
    project.mkdir()
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    subprocess.run(["git", "-C", str(project), "config", "user.email", "p1@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(project), "config", "user.name", "P1 Evidence Test"], check=True)
    (project / ".gitignore").write_text(".colameta/runtime/\n", encoding="utf-8")
    (project / "README.md").write_text("P1 release evidence fixture.\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(project), "add", "."], check=True)
    subprocess.run(["git", "-C", str(project), "commit", "-qm", "fixture"], check=True)
    head = subprocess.run(
        ["git", "-C", str(project), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return project, head


def _sha256(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _validation_result(
    project: Path,
    head: str,
    now: datetime,
    *,
    status: str = "passed",
) -> tuple[dict[str, str], Path, dict[str, object]]:
    observed_at = (now - timedelta(minutes=2)).isoformat()
    command_specs = [
        {
            "argv": [".venv/bin/python", "-m", "pytest", "-q"],
            "timeout_seconds": 900,
            "continue_on_failure": False,
        },
        {
            "argv": [".venv/bin/python", "scripts/self_hosting_smoke.py"],
            "timeout_seconds": 900,
            "continue_on_failure": False,
        },
        {
            "argv": [
                ".venv/bin/python",
                "-m",
                "compileall",
                "-q",
                "adapters",
                "runner",
                "schemas",
                "scripts",
                "tests",
            ],
            "timeout_seconds": 600,
            "continue_on_failure": False,
        },
        {
            "argv": [
                ".venv/bin/python",
                "-m",
                "ruff",
                "check",
                "adapters",
                "runner",
                "schemas",
                "scripts",
                "tests",
            ],
            "timeout_seconds": 600,
            "continue_on_failure": False,
        },
        {
            "argv": ["git", "diff", "--check"],
            "timeout_seconds": 600,
            "continue_on_failure": False,
        },
    ]
    manifest_sha256 = _sha256("review-manifest")
    source = {
        "schema_version": REVIEW_MANIFEST_VALIDATION_SOURCE_SCHEMA_VERSION,
        "review_manifest_id": "review_manifest_fixture_123",
        "manifest_sha256": manifest_sha256,
        "review_unit": "p1-validation-fixture",
        "workflow_intent": "independent_review",
        "review_context_binding": {
            "project_name": "p1-release-evidence",
            "branch": "fixture",
            "head": head,
            "runner_plan": {"mode": "source-only", "plan_sha256": None},
            "current_version": None,
            "review_unit": "p1-validation-fixture",
            "workflow_intent": "independent_review",
        },
        "subjects": [
            {
                "path": "README.md",
                "sha256": hashlib.sha256(
                    (project / "README.md").read_bytes()
                ).hexdigest(),
            }
        ],
        "acceptance_commands": [],
    }
    contract = build_review_manifest_validation_contract(source, command_specs)
    run_id = "validation_run_p1_fixture_123"
    failed = status == "failed"
    command_results = [
        {
            "index": index,
            "ok": not failed,
            "returncode": 1 if failed else 0,
            "error_code": None,
            "timeout_seconds": spec["timeout_seconds"],
            "continue_on_failure": spec["continue_on_failure"],
            "command": " ".join(spec["argv"]),
            "stdout": "",
            "stderr": "",
            "stdout_truncated": False,
            "stderr_truncated": False,
        }
        for index, spec in enumerate(command_specs)
    ]
    result: dict[str, object] = {
        "schema_version": VALIDATION_RUN_RESULT_SCHEMA_VERSION,
        "run_id": run_id,
        "preview_id": "preview_fixture_123",
        "action": "run",
        "status": status,
        "passed": not failed,
        "scope": "manifest_bound",
        "target_files": ["README.md"],
        "strategy": "manifest_acceptance",
        "validation_groups": [],
        "command_summary": [" ".join(spec["argv"]) for spec in command_specs],
        "command_count": len(command_specs),
        "command_results": command_results,
        "failed_command_indexes": list(range(len(command_specs))) if failed else [],
        "failed_command_index": 0 if failed else None,
        "output_summary": {
            "total_output_chars": 0,
            "redacted": True,
            "truncated": False,
        },
        "started_at": (now - timedelta(minutes=3)).isoformat(),
        "completed_at": observed_at,
        "duration_seconds": 60.0,
        "manifest_validation": contract,
    }
    result["validation_result_sha256"] = canonical_validation_result_sha256(
        result
    )
    path = (
        project
        / ".colameta"
        / "runtime"
        / "validation-runs"
        / f"{run_id}.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result), encoding="utf-8")
    return (
        {
            "run_id": run_id,
            "validation_result_sha256": str(
                result["validation_result_sha256"]
            ),
            "contract_sha256": contract["contract_sha256"],
            "manifest_sha256": manifest_sha256,
        },
        path,
        result,
    )


def _observations(
    project: Path,
    head: str,
    now: datetime,
) -> dict[str, object]:
    validation_reference, _path, _result = _validation_result(project, head, now)
    observed_at = (now - timedelta(minutes=2)).isoformat()
    expires_at = (now + timedelta(minutes=13)).isoformat()
    return {
        "full_local_validation": {
            "validation_run": validation_reference,
        },
        "runtime_provenance": {
            "observed_at": observed_at,
            "candidate_head": head,
            "loaded_runtime_head": head,
            "runtime_project_checkout_head": head,
            "runtime_loaded_code_stale": False,
            "reload_needed_for_verification": False,
            "installed_package_matches_project_checkout": True,
        },
        "connector_oauth": {
            "observed_at": observed_at,
            "candidate_head": head,
            "connector_reachable": True,
            "oauth_authorized": True,
            "visible_tool_inventory": list(COMMANDER_EXPOSED_TOOLS),
        },
        "current_facts": {
            "observed_at": observed_at,
            "candidate_head": head,
            "artifact_id": "currentfacts_artifact_12345",
            "content_sha256": _sha256("current-facts-content"),
            "expires_at": expires_at,
            "canonical_state_sha256": _sha256("canonical-state"),
            "canonical_state_semantic_sha256": _sha256("canonical-semantic"),
            "snapshot_json_sha256": _sha256("snapshot-json"),
            "freshness_current_observation": True,
            "unresolved_critical_blocker_count": 0,
        },
        "live_chatgpt_development_acceptance": {
            "observed_at": observed_at,
            "candidate_head": head,
            "visible_tool_inventory": list(COMMANDER_EXPOSED_TOOLS),
            "context_binding_mismatch_error_code": "CONTEXT_BINDING_MISMATCH",
            "review_manifest": {
                "manifest_sha256": validation_reference["manifest_sha256"],
                "expires_at": expires_at,
                "subject_count": 2,
                "page_count": 4,
                "all_subject_pages_read": True,
                "page_ranges_contiguous": True,
                "expiry_continuity": True,
                "verify_context_binding": "matched",
                "verify_subject_hashes": "matched",
            },
            "result_artifact": {
                "artifact_id": "resultartifact_1234567890",
                "content_sha256": _sha256("result-artifact"),
                "expires_at": expires_at,
                "page_count": 8,
                "all_pages_read": True,
                "page_ranges_contiguous": True,
                "expiry_continuity": True,
                "typed_read_tool": "read_result_artifact",
            },
            "resources_read_used": False,
            "all_calls_read_only": True,
        },
    }


def test_p1_receipt_clears_evidence_checks_but_never_stable_authorization(tmp_path: Path) -> None:
    project, head = _git_fixture(tmp_path)
    now = datetime(2026, 7, 24, 5, 0, tzinfo=timezone.utc)
    manager = P1ReleaseEvidenceManager(str(project), now_fn=lambda: now)

    preview = manager.handle(
        "preview",
        {"candidate_head": head, **_observations(project, head, now)},
    )

    assert preview["ok"] is True
    assert preview["status"] == "preview_ready"
    assert preview["schema_version"] == P1_RELEASE_EVIDENCE_PREVIEW_SCHEMA_VERSION
    assert preview["authority_boundary"]["does_not_replace_stable"] is True
    assert preview["confirmation"]["confirm_release_evidence"] is True

    missing_confirmation = manager.handle("apply", {"preview_id": preview["preview_id"]})
    assert missing_confirmation["ok"] is False
    assert missing_confirmation["error_code"] == "P1_RELEASE_EVIDENCE_CONFIRMATION_REQUIRED"

    applied = manager.handle(
        "apply",
        {"preview_id": preview["preview_id"], "confirm_release_evidence": True},
    )

    assert applied["ok"] is True
    assert applied["status"] == "recorded"
    assert applied["schema_version"] == P1_RELEASE_EVIDENCE_RECEIPT_SCHEMA_VERSION
    evidence = get_p1_release_evidence_status(str(project), candidate_head=head, now=now)
    assert evidence["status"] == "verified_current"
    assert evidence["receipt_integrity_verified"] is True
    assert evidence["operator_attested_external_observations"] is True
    assert evidence["evidence_complete"] is True
    assert {item["status"] for item in evidence["checks"].values()} == {"passed"}

    gate = build_p1_client_release_gate(str(project), candidate_head=head, now=now)
    assert gate["status"] == "blocked"
    assert gate["ready"] is False
    assert gate["candidate_release_status"] == "evidence_ready_pending_stable_authorization"
    assert gate["blocker_codes"] == ["EXPLICIT_STABLE_REPLACEMENT_AUTHORIZATION_REQUIRED"]
    assert [check["status"] for check in gate["checks"][:-1]] == ["passed"] * 5
    assert gate["checks"][-1]["check_id"] == "stable_replacement_authorization"
    assert gate["checks"][-1]["status"] == "blocked"


def test_p1_preview_rejects_noncanonical_commander_inventory(tmp_path: Path) -> None:
    project, head = _git_fixture(tmp_path)
    now = datetime(2026, 7, 24, 5, 0, tzinfo=timezone.utc)
    observations = _observations(project, head, now)
    connector = observations["connector_oauth"]
    assert isinstance(connector, dict)
    connector["visible_tool_inventory"] = list(reversed(COMMANDER_EXPOSED_TOOLS))

    result = P1ReleaseEvidenceManager(str(project), now_fn=lambda: now).handle(
        "preview",
        {"candidate_head": head, **observations},
    )

    assert result["ok"] is False
    assert result["error_code"] == "P1_COMMANDER_TOOL_INVENTORY_MISMATCH"


def test_p1_receipt_becomes_stale_and_tampering_fails_closed(tmp_path: Path) -> None:
    project, head = _git_fixture(tmp_path)
    now = datetime(2026, 7, 24, 5, 0, tzinfo=timezone.utc)
    manager = P1ReleaseEvidenceManager(str(project), now_fn=lambda: now)
    preview = manager.handle(
        "preview",
        {"candidate_head": head, **_observations(project, head, now)},
    )
    applied = manager.handle(
        "apply",
        {"preview_id": preview["preview_id"], "confirm_release_evidence": True},
    )
    assert applied["ok"] is True

    stale = get_p1_release_evidence_status(
        str(project),
        candidate_head=head,
        now=now + timedelta(hours=25),
    )
    assert stale["status"] == "verified_stale"
    assert stale["evidence_complete"] is False
    assert {item["status"] for item in stale["checks"].values()} == {"stale"}
    stale_gate = build_p1_client_release_gate(
        str(project),
        candidate_head=head,
        now=now + timedelta(hours=25),
    )
    assert {check["status"] for check in stale_gate["checks"][:-1]} == {"stale"}

    receipt_path = project / applied["receipt_path"]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["observations"]["connector_oauth"]["oauth_authorized"] = False
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    tampered = get_p1_release_evidence_status(str(project), candidate_head=head, now=now)
    assert tampered["ok"] is False
    assert tampered["error_code"] == "RECEIPT_DIGEST_MISMATCH"


def test_p1_evidence_manager_is_local_advanced_only_with_typed_scope_map(tmp_path: Path) -> None:
    project, _ = _git_fixture(tmp_path)
    local = MCPPlanningBridgeServer(str(project), exposure_profile="normal")
    commander = MCPPlanningBridgeServer(str(project), exposure_profile="commander")
    tool_defs = {tool.name: tool for tool in local.tool_defs}

    assert "manage_p1_release_evidence" in local._visible_tool_names()
    assert "manage_p1_release_evidence" not in commander._visible_tool_names()
    assert "manage_p1_release_evidence" in tool_defs
    assert tool_defs["manage_p1_release_evidence"].annotations["readOnlyHint"] is False
    schema = tool_defs["manage_p1_release_evidence"].input_schema
    assert schema["properties"]["action"]["enum"] == ["inspect", "status", "preview", "apply", "discard"]
    validation_schema = schema["properties"]["full_local_validation"]
    assert set(validation_schema["properties"]) == {"validation_run"}
    reference_schema = validation_schema["properties"]["validation_run"]
    assert set(reference_schema["properties"]) == {
        "run_id",
        "validation_result_sha256",
        "contract_sha256",
        "manifest_sha256",
    }
    assert "commands" not in repr(validation_schema)
    assert "result_path" not in repr(validation_schema)
    assert local.get_required_scope_for_tool("manage_p1_release_evidence", {"action": "status"}) == "mcp:read"
    assert local.get_required_scope_for_tool("manage_p1_release_evidence", {"action": "preview"}) == "mcp:preview"
    assert local.get_required_scope_for_tool("manage_p1_release_evidence", {"action": "apply"}) == "mcp:commit"


def test_p1_result_reference_failures_are_distinct_and_fail_closed(
    tmp_path: Path,
) -> None:
    project, head = _git_fixture(tmp_path)
    now = datetime(2026, 7, 24, 5, 0, tzinfo=timezone.utc)
    manager = P1ReleaseEvidenceManager(str(project), now_fn=lambda: now)

    observations = _observations(project, head, now)
    reference = observations["full_local_validation"]["validation_run"]
    reference["run_id"] = "validation_run_missing_123"
    missing = manager.handle(
        "preview",
        {"candidate_head": head, **observations},
    )
    assert missing["error_code"] == "P1_VALIDATION_RESULT_NOT_FOUND"

    for field, code in (
        ("validation_result_sha256", "P1_VALIDATION_RESULT_DIGEST_MISMATCH"),
        ("contract_sha256", "P1_VALIDATION_CONTRACT_DIGEST_MISMATCH"),
        ("manifest_sha256", "P1_VALIDATION_MANIFEST_DIGEST_MISMATCH"),
    ):
        observations = _observations(project, head, now)
        observations["full_local_validation"]["validation_run"][field] = "0" * 64
        mismatch = manager.handle(
            "preview",
            {"candidate_head": head, **observations},
        )
        assert mismatch["error_code"] == code

    observations = _observations(project, head, now)
    _reference, path, result = _validation_result(
        project,
        head,
        now,
        status="failed",
    )
    observations["full_local_validation"]["validation_run"] = _reference
    failed = manager.handle(
        "preview",
        {"candidate_head": head, **observations},
    )
    assert failed["error_code"] == "P1_VALIDATION_RESULT_NOT_PASSED"
    assert path.exists()
    assert result["validation_result_sha256"]


def test_p1_rejects_running_and_legacy_terminal_results_without_backfill(
    tmp_path: Path,
) -> None:
    project, head = _git_fixture(tmp_path)
    now = datetime(2026, 7, 24, 5, 0, tzinfo=timezone.utc)
    manager = P1ReleaseEvidenceManager(str(project), now_fn=lambda: now)

    observations = _observations(project, head, now)
    _reference, path, terminal = _validation_result(project, head, now)
    running = {
        key: value
        for key, value in terminal.items()
        if key != "validation_result_sha256"
    }
    running.update(
        {
            "status": "running",
            "passed": None,
            "command_results": [],
            "failed_command_indexes": [],
            "failed_command_index": None,
            "completed_at": None,
            "duration_seconds": None,
        }
    )
    path.write_text(json.dumps(running), encoding="utf-8")
    non_terminal = manager.handle(
        "preview",
        {"candidate_head": head, **observations},
    )
    assert (
        non_terminal["error_code"]
        == "P1_VALIDATION_RESULT_NOT_TERMINAL"
    )

    legacy = {
        key: value
        for key, value in terminal.items()
        if key not in {"schema_version", "validation_result_sha256"}
    }
    path.write_text(json.dumps(legacy), encoding="utf-8")
    unverified = manager.handle(
        "preview",
        {"candidate_head": head, **observations},
    )
    assert (
        unverified["error_code"]
        == "P1_LEGACY_VALIDATION_PROVENANCE_MISSING"
    )
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert "validation_result_sha256" not in persisted


def test_p1_contract_candidate_and_command_coverage_errors_are_distinct(
    tmp_path: Path,
) -> None:
    project, head = _git_fixture(tmp_path)
    now = datetime(2026, 7, 24, 5, 0, tzinfo=timezone.utc)
    manager = P1ReleaseEvidenceManager(str(project), now_fn=lambda: now)

    observations = _observations(project, head, now)
    reference, path, result = _validation_result(project, head, now)
    contract = result["manifest_validation"]
    assert isinstance(contract, dict)
    contract["command_specs_sha256"] = "0" * 64
    result["validation_result_sha256"] = canonical_validation_result_sha256(
        result
    )
    path.write_text(json.dumps(result), encoding="utf-8")
    reference["validation_result_sha256"] = str(
        result["validation_result_sha256"]
    )
    observations["full_local_validation"]["validation_run"] = reference
    specs_mismatch = manager.handle(
        "preview",
        {"candidate_head": head, **observations},
    )
    assert (
        specs_mismatch["error_code"]
        == "P1_VALIDATION_COMMAND_SPECS_DIGEST_MISMATCH"
    )

    observations = _observations(project, head, now)
    reference, path, result = _validation_result(project, head, now)
    contract = result["manifest_validation"]
    assert isinstance(contract, dict)
    contract["contract_sha256"] = "0" * 64
    result["validation_result_sha256"] = canonical_validation_result_sha256(
        result
    )
    path.write_text(json.dumps(result), encoding="utf-8")
    reference["validation_result_sha256"] = str(
        result["validation_result_sha256"]
    )
    observations["full_local_validation"]["validation_run"] = reference
    contract_mismatch = manager.handle(
        "preview",
        {"candidate_head": head, **observations},
    )
    assert (
        contract_mismatch["error_code"]
        == "P1_VALIDATION_CONTRACT_DIGEST_MISMATCH"
    )

    observations = _observations(project, head, now)
    reference, path, result = _validation_result(project, head, now)
    contract = result["manifest_validation"]
    assert isinstance(contract, dict)
    contract["review_context_binding"]["head"] = "0" * 40
    unsigned = {
        key: value
        for key, value in contract.items()
        if key != "contract_sha256"
    }
    contract["contract_sha256"] = canonical_manifest_validation_sha256(
        unsigned
    )
    result["validation_result_sha256"] = canonical_validation_result_sha256(
        result
    )
    path.write_text(json.dumps(result), encoding="utf-8")
    reference["validation_result_sha256"] = str(
        result["validation_result_sha256"]
    )
    reference["contract_sha256"] = contract["contract_sha256"]
    observations["full_local_validation"]["validation_run"] = reference
    candidate_mismatch = manager.handle(
        "preview",
        {"candidate_head": head, **observations},
    )
    assert (
        candidate_mismatch["error_code"]
        == "P1_VALIDATION_CANDIDATE_MISMATCH"
    )

    observations = _observations(project, head, now)
    reference, path, result = _validation_result(project, head, now)
    contract = result["manifest_validation"]
    assert isinstance(contract, dict)
    contract["command_specs"].pop()
    contract["command_specs_sha256"] = canonical_manifest_validation_sha256(
        contract["command_specs"]
    )
    unsigned = {
        key: value
        for key, value in contract.items()
        if key != "contract_sha256"
    }
    contract["contract_sha256"] = canonical_manifest_validation_sha256(
        unsigned
    )
    result["command_results"].pop()
    result["command_summary"].pop()
    result["command_count"] -= 1
    result["validation_result_sha256"] = canonical_validation_result_sha256(
        result
    )
    path.write_text(json.dumps(result), encoding="utf-8")
    reference.update(
        {
            "validation_result_sha256": str(
                result["validation_result_sha256"]
            ),
            "contract_sha256": contract["contract_sha256"],
        }
    )
    observations["full_local_validation"]["validation_run"] = reference
    incomplete = manager.handle(
        "preview",
        {"candidate_head": head, **observations},
    )
    assert (
        incomplete["error_code"]
        == "P1_VALIDATION_COMMAND_COVERAGE_INCOMPLETE"
    )


def test_p1_rejects_nonexact_python_executable_with_rebound_digests(
    tmp_path: Path,
) -> None:
    project, head = _git_fixture(tmp_path)
    now = datetime(2026, 7, 24, 5, 0, tzinfo=timezone.utc)
    manager = P1ReleaseEvidenceManager(str(project), now_fn=lambda: now)

    for executable in ("python3", "python-malware", "tools/python"):
        observations = _observations(project, head, now)
        reference, path, result = _validation_result(project, head, now)
        contract = result["manifest_validation"]
        assert isinstance(contract, dict)
        command_specs = contract["command_specs"]
        assert isinstance(command_specs, list)
        first_spec = command_specs[0]
        assert isinstance(first_spec, dict)
        argv = first_spec["argv"]
        assert isinstance(argv, list)
        argv[0] = executable
        contract["command_specs_sha256"] = (
            canonical_manifest_validation_sha256(command_specs)
        )
        unsigned_contract = {
            key: value
            for key, value in contract.items()
            if key != "contract_sha256"
        }
        contract["contract_sha256"] = (
            canonical_manifest_validation_sha256(unsigned_contract)
        )
        rebound_command = " ".join(argv)
        command_results = result["command_results"]
        command_summary = result["command_summary"]
        assert isinstance(command_results, list)
        assert isinstance(command_summary, list)
        command_results[0]["command"] = rebound_command
        command_summary[0] = rebound_command
        result["validation_result_sha256"] = (
            canonical_validation_result_sha256(result)
        )
        path.write_text(json.dumps(result), encoding="utf-8")
        reference.update(
            {
                "validation_result_sha256": str(
                    result["validation_result_sha256"]
                ),
                "contract_sha256": str(contract["contract_sha256"]),
            }
        )
        observations["full_local_validation"]["validation_run"] = reference

        rejected = manager.handle(
            "preview",
            {"candidate_head": head, **observations},
        )

        assert (
            rejected["error_code"]
            == "P1_VALIDATION_COMMAND_COVERAGE_INCOMPLETE"
        )


def test_p1_reverifies_one_run_id_source_across_preview_apply_and_status(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project, head = _git_fixture(tmp_path)
    now = datetime(2026, 7, 24, 5, 0, tzinfo=timezone.utc)
    phases: list[str] = []
    original = MCPValidationRunManager.verify_p1_result

    def recording_verifier(self, *args, **kwargs):
        phases.append(kwargs["phase"])
        return original(self, *args, **kwargs)

    monkeypatch.setattr(
        MCPValidationRunManager,
        "verify_p1_result",
        recording_verifier,
    )
    manager = P1ReleaseEvidenceManager(str(project), now_fn=lambda: now)
    preview = manager.handle(
        "preview",
        {"candidate_head": head, **_observations(project, head, now)},
    )
    applied = manager.handle(
        "apply",
        {
            "preview_id": preview["preview_id"],
            "confirm_release_evidence": True,
        },
    )
    status = manager.handle("status", {"candidate_head": head})
    assert applied["ok"] is True
    assert status["status"] == "verified_current"
    assert phases.count("preview") == 1
    assert phases.count("apply") == 1
    assert phases.count("status") >= 2


def test_p1_rejects_legacy_preview_and_keeps_legacy_receipt_historical(
    tmp_path: Path,
) -> None:
    project, head = _git_fixture(tmp_path)
    now = datetime(2026, 7, 24, 5, 0, tzinfo=timezone.utc)
    manager = P1ReleaseEvidenceManager(str(project), now_fn=lambda: now)
    preview_id = "p1e_legacy_preview_123"
    legacy_preview = {
        "schema_version": P1_RELEASE_EVIDENCE_LEGACY_PREVIEW_SCHEMA_VERSION,
        "artifact_kind": "p1_release_evidence_preview",
        "preview_id": preview_id,
        "project_root": str(project.resolve()),
        "candidate_head": head,
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=5)).isoformat(),
        "observations": {},
        "authority_boundary": {},
    }
    legacy_preview["preview_digest"] = _sha256("irrelevant")
    preview_path = (
        project
        / ".colameta"
        / "runtime"
        / "p1-release-evidence-previews"
        / f"{preview_id}.json"
    )
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    preview_path.write_text(json.dumps(legacy_preview), encoding="utf-8")
    rejected = manager.handle(
        "apply",
        {"preview_id": preview_id, "confirm_release_evidence": True},
    )
    assert rejected["error_code"] == "P1_LEGACY_PREVIEW_NOT_APPLICABLE"

    preview = manager.handle(
        "preview",
        {"candidate_head": head, **_observations(project, head, now)},
    )
    applied = manager.handle(
        "apply",
        {
            "preview_id": preview["preview_id"],
            "confirm_release_evidence": True,
        },
    )
    receipt_path = project / applied["receipt_path"]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["schema_version"] = P1_RELEASE_EVIDENCE_LEGACY_RECEIPT_SCHEMA_VERSION
    validation = receipt["observations"]["full_local_validation"]
    receipt["observations"]["full_local_validation"] = {
        "observed_at": validation["observed_at"],
        "candidate_head": validation["candidate_head"],
        "commands": {
            "pytest": "passed",
            "self_hosting_smoke": "passed",
            "compileall": "passed",
            "ruff": "passed",
            "git_diff_check": "passed",
        },
    }
    unsigned = {
        key: value
        for key, value in receipt.items()
        if key != "receipt_digest"
    }
    receipt["receipt_digest"] = hashlib.sha256(
        json.dumps(
            unsigned,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    before = receipt_path.read_bytes()
    historical = get_p1_release_evidence_status(
        str(project),
        candidate_head=head,
        now=now,
    )
    assert historical["status"] == "verified_stale"
    assert historical["evidence_complete"] is False
    assert (
        historical["error_code"]
        == "P1_LEGACY_VALIDATION_PROVENANCE_MISSING"
    )
    assert receipt_path.read_bytes() == before


def test_p1_result_rewrite_and_deletion_after_binding_keep_gate_blocked(
    tmp_path: Path,
) -> None:
    project, head = _git_fixture(tmp_path)
    now = datetime(2026, 7, 24, 5, 0, tzinfo=timezone.utc)
    manager = P1ReleaseEvidenceManager(str(project), now_fn=lambda: now)
    observations = _observations(project, head, now)
    reference = observations["full_local_validation"]["validation_run"]
    run_path = (
        project
        / ".colameta"
        / "runtime"
        / "validation-runs"
        / f"{reference['run_id']}.json"
    )
    preview = manager.handle(
        "preview",
        {"candidate_head": head, **observations},
    )
    rewritten = json.loads(run_path.read_text(encoding="utf-8"))
    rewritten["output_summary"]["total_output_chars"] = 1
    rewritten["validation_result_sha256"] = canonical_validation_result_sha256(
        rewritten
    )
    run_path.write_text(json.dumps(rewritten), encoding="utf-8")
    changed = manager.handle(
        "apply",
        {
            "preview_id": preview["preview_id"],
            "confirm_release_evidence": True,
        },
    )
    assert (
        changed["error_code"]
        == "P1_VALIDATION_RESULT_CHANGED_AFTER_PREVIEW"
    )

    observations = _observations(project, head, now)
    reference = observations["full_local_validation"]["validation_run"]
    run_path = run_path.with_name(f"{reference['run_id']}.json")
    preview = manager.handle(
        "preview",
        {"candidate_head": head, **observations},
    )
    applied = manager.handle(
        "apply",
        {
            "preview_id": preview["preview_id"],
            "confirm_release_evidence": True,
        },
    )
    assert applied["ok"] is True
    retained = json.loads(run_path.read_text(encoding="utf-8"))
    rewritten = dict(retained)
    rewritten["output_summary"] = dict(retained["output_summary"])
    rewritten["output_summary"]["total_output_chars"] = 2
    rewritten["validation_result_sha256"] = canonical_validation_result_sha256(
        rewritten
    )
    run_path.write_text(json.dumps(rewritten), encoding="utf-8")
    modified = get_p1_release_evidence_status(
        str(project),
        candidate_head=head,
        now=now,
    )
    assert modified["status"] == "verified_stale"
    assert modified["evidence_complete"] is False
    assert (
        modified["error_code"]
        == "P1_VALIDATION_RESULT_DIGEST_MISMATCH"
    )
    run_path.unlink()
    missing = get_p1_release_evidence_status(
        str(project),
        candidate_head=head,
        now=now,
    )
    assert missing["status"] == "verified_stale"
    assert missing["evidence_complete"] is False
    assert missing["error_code"] == "P1_VALIDATION_RESULT_NOT_FOUND"
    gate = build_p1_client_release_gate(
        str(project),
        candidate_head=head,
        now=now,
    )
    assert gate["status"] == "blocked"
    assert gate["ready"] is False


def test_p1_head_drift_is_verified_stale_and_never_superseded(
    tmp_path: Path,
) -> None:
    project, head = _git_fixture(tmp_path)
    now = datetime(2026, 7, 24, 5, 0, tzinfo=timezone.utc)
    manager = P1ReleaseEvidenceManager(str(project), now_fn=lambda: now)
    preview = manager.handle(
        "preview",
        {"candidate_head": head, **_observations(project, head, now)},
    )
    applied = manager.handle(
        "apply",
        {
            "preview_id": preview["preview_id"],
            "confirm_release_evidence": True,
        },
    )
    assert applied["ok"] is True
    (project / "drift.txt").write_text("later head\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(project), "add", "drift.txt"], check=True)
    subprocess.run(
        ["git", "-C", str(project), "commit", "-qm", "head drift"],
        check=True,
    )
    stale = get_p1_release_evidence_status(
        str(project),
        candidate_head=head,
        now=now,
    )
    assert stale["status"] == "verified_stale"
    assert stale["evidence_complete"] is False
    assert "superseded" not in repr(stale)


def test_p1_taskbooks_state_the_canonical_integrity_binding_boundary() -> None:
    repository_root = Path(__file__).resolve().parents[1]
    documents = [
        (
            repository_root
            / "docs"
            / "taskbooks"
            / "P1_E_RELEASE_EVIDENCE_GATE.md"
        ),
        (
            repository_root
            / "docs"
            / "taskbooks"
            / "P1_E_RELEASE_EVIDENCE_GATE.zh-CN.md"
        ),
    ]
    required_phrases = (
        "canonical integrity binding",
        "digital signature",
        "remote attestation",
        "executor or operator identity",
        "privileged local writer",
        "server_verified_validation_run",
        "HMAC",
        "new trust authority",
    )
    for path in documents:
        content = path.read_text(encoding="utf-8")
        for phrase in required_phrases:
            assert phrase in content
