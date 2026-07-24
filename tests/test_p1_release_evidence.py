from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess

from runner.mcp_commander_public import COMMANDER_EXPOSED_TOOLS
from runner.mcp_server import MCPPlanningBridgeServer
from runner.p1_release_evidence import (
    P1ReleaseEvidenceManager,
    get_p1_release_evidence_status,
)
from runner.p1_release_gate import build_p1_client_release_gate


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


def _observations(head: str, now: datetime) -> dict[str, object]:
    observed_at = (now - timedelta(minutes=2)).isoformat()
    expires_at = (now + timedelta(minutes=13)).isoformat()
    return {
        "full_local_validation": {
            "observed_at": observed_at,
            "candidate_head": head,
            "commands": {
                "pytest": "passed",
                "self_hosting_smoke": "passed",
                "compileall": "passed",
                "ruff": "passed",
                "git_diff_check": "passed",
            },
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
                "manifest_sha256": _sha256("review-manifest"),
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
        {"candidate_head": head, **_observations(head, now)},
    )

    assert preview["ok"] is True
    assert preview["status"] == "preview_ready"
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
    observations = _observations(head, now)
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
    preview = manager.handle("preview", {"candidate_head": head, **_observations(head, now)})
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
    assert local.get_required_scope_for_tool("manage_p1_release_evidence", {"action": "status"}) == "mcp:read"
    assert local.get_required_scope_for_tool("manage_p1_release_evidence", {"action": "preview"}) == "mcp:preview"
    assert local.get_required_scope_for_tool("manage_p1_release_evidence", {"action": "apply"}) == "mcp:commit"
