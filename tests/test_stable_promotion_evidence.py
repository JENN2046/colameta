from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import runner.stable_promotion_evidence as stable_promotion_evidence
import runner.stable_promotion_readiness as stable_promotion_readiness
from runner.stable_promotion_evidence import (
    MCPStablePromotionEvidenceManager,
    build_candidate_artifact_manifest,
    get_stable_promotion_evidence_status,
    get_stable_promotion_preview_status,
)
from runner.stable_promotion_readiness import (
    REQUIRED_VISIBLE_TOOLS,
    REQUIRED_WORKFLOWS,
    get_stable_promotion_readiness,
)
from runner.mcp_server import MCPPlanningBridgeServer
from runner.project_registry import ProjectRegistry
from runner.workflow_engine import infer_risk_level, should_record_tool


def _run(*args: str, cwd: Path | None = None) -> str:
    completed = subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=False, timeout=15)
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.strip()


def _repo(tmp_path: Path) -> tuple[Path, str]:
    origin = tmp_path / "origin.git"
    repo = tmp_path / "repo"
    _run("git", "init", "--bare", str(origin))
    _run("git", "init", str(repo))
    _run("git", "config", "user.email", "test@example.invalid", cwd=repo)
    _run("git", "config", "user.name", "ColaMeta Test", cwd=repo)
    (repo / ".gitignore").write_text(".colameta/runtime/\n", encoding="utf-8")
    (repo / "README.md").write_text("committed content\n", encoding="utf-8")
    _run("git", "add", ".gitignore", "README.md", cwd=repo)
    _run("git", "commit", "-m", "initial", cwd=repo)
    _run("git", "branch", "-M", "main", cwd=repo)
    _run("git", "remote", "add", "origin", str(origin), cwd=repo)
    _run("git", "push", "-u", "origin", "main", cwd=repo)
    return repo, _run("git", "rev-parse", "HEAD", cwd=repo)


def _runtime(repo: Path, head: str) -> dict[str, object]:
    return {
        "project_checkout_head": head,
        "project_checkout": {"branch": "main"},
        "loaded_runtime": {"source_root": str(repo)},
        "loaded_runtime_head": head,
        "runtime_loaded_code_stale": False,
        "reload_needed_for_verification": False,
        "reload_awareness_reason": "loaded_code_verified_current",
    }


def _rollback_rehearsal(head: str) -> dict[str, object]:
    return {
        "status": "ready",
        "reason_codes": ["ROLLBACK_REHEARSAL_READY"],
        "evidence_source": "local_read_only_status",
        "backup_file": "/tmp/stable-before-test.tar.gz",
        "backup_sha256": "a" * 64,
        "backup_member_count": 1,
        "target_head": head,
        "rehearsal_executed_restore": False,
    }


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def test_manifest_is_bound_to_exact_commit_not_dirty_worktree(tmp_path: Path) -> None:
    repo, head = _repo(tmp_path)
    committed = build_candidate_artifact_manifest(str(repo), head, include_entries=True)
    (repo / "README.md").write_text("uncommitted content\n", encoding="utf-8")
    dirty = build_candidate_artifact_manifest(str(repo), head, include_entries=True)

    assert committed["available"] is True
    assert committed["manifest_version"] == 2
    assert committed["manifest_kind"] == "git_commit_tracked_sha256_manifest"
    assert committed["source_kind"] == "git_object_database"
    assert committed["worktree_content_used"] is False
    assert dirty["manifest_sha256"] == committed["manifest_sha256"]
    assert dirty["files"] == committed["files"]
    readme = next(item for item in dirty["files"] if item["path"] == "README.md")
    assert readme["path_encoding"] == "utf-8"
    assert readme["sha256"] != hashlib.sha256(b"uncommitted content\n").hexdigest()


def test_manifest_losslessly_encodes_non_utf8_git_paths(tmp_path: Path) -> None:
    repo, _ = _repo(tmp_path)
    raw_path = os.fsencode(repo) + b"/non-utf8-\xff.txt"
    descriptor = os.open(raw_path, os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        os.write(descriptor, b"binary path content\n")
    finally:
        os.close(descriptor)
    _run("git", "add", "--all", cwd=repo)
    _run("git", "commit", "-m", "non utf8 path", cwd=repo)
    head = _run("git", "rev-parse", "HEAD", cwd=repo)

    manifest = build_candidate_artifact_manifest(str(repo), head, include_entries=True)
    encoded = [item for item in manifest["files"] if item["path_encoding"] == "base64"]
    assert len(encoded) == 1
    assert base64.b64decode(encoded[0]["path"]) == b"non-utf8-\xff.txt"


def test_preview_apply_persists_and_verifies_current_manifest(tmp_path: Path) -> None:
    repo, head = _repo(tmp_path)
    manager = MCPStablePromotionEvidenceManager(str(repo))

    preview = manager.handle("preview", {"candidate_head": head})
    assert preview["ok"] is True
    assert preview["can_apply"] is True
    assert preview["blockers"] == []
    assert preview["manifest"]["file_entries_omitted_from_response"] is True
    assert preview["worktree_isolation"]["status"] == "clean"

    applied = manager.handle("apply", {"preview_id": preview["preview_id"]})
    assert applied["ok"] is True
    assert applied["status"] == "recorded"
    assert applied["evidence_status"]["status"] == "verified_current"
    assert applied["authority_boundary"]["does_not_replace_stable_service"] is True
    assert not Path(repo / applied["receipt_path"]).is_relative_to(repo / ".git")

    replay = manager.handle("apply", {"preview_id": preview["preview_id"]})
    assert replay["ok"] is False
    assert replay["error_code"] == "PREVIEW_NOT_FOUND"

    status = get_stable_promotion_evidence_status(str(repo), candidate_head=head)
    assert status["verified"] is True
    assert status["current"] is True
    assert status["manifest"]["manifest_sha256"] == preview["manifest"]["manifest_sha256"]

    stable_dir = tmp_path / "stable"
    stable_dir.mkdir()
    readiness = get_stable_promotion_readiness(
        str(repo),
        visible_tool_names=list(REQUIRED_VISIBLE_TOOLS),
        supported_workflows=list(REQUIRED_WORKFLOWS),
        runtime_status=_runtime(repo, head),
        stable_runtime_dir=str(stable_dir),
        rollback_rehearsal_evidence=_rollback_rehearsal(head),
    )
    assert readiness["promotion_artifact_evidence"]["status"] == "verified_current"
    assert "PROMOTION_ARTIFACT_MANIFEST_NOT_PERSISTED" not in {
        item["code"] for item in readiness["external_required_before_stable_replacement"]
    }
    assert readiness["recommended_next_steps"][0]["step"] == "request_commander_authorization"


def test_active_preview_status_recovers_exact_apply_action(tmp_path: Path) -> None:
    repo, head = _repo(tmp_path)
    manager = MCPStablePromotionEvidenceManager(str(repo))

    missing = get_stable_promotion_preview_status(str(repo), candidate_head=head)
    assert missing["status"] == "missing"
    assert missing["can_apply"] is False

    preview = manager.handle("preview", {"candidate_head": head})
    active = get_stable_promotion_preview_status(str(repo), candidate_head=head)
    assert active["status"] == "ready_to_apply"
    assert active["read_only"] is True
    assert active["side_effects"] is False
    assert active["preview_id"] == preview["preview_id"]
    assert active["safe_next_action"] == {
        "tool": "manage_stable_promotion_evidence",
        "arguments": {"action": "apply", "preview_id": preview["preview_id"]},
        "required_scope": "mcp:commit",
    }

    applied = manager.handle("apply", active["safe_next_action"]["arguments"])
    assert applied["status"] == "recorded"
    assert get_stable_promotion_preview_status(str(repo), candidate_head=head)["status"] == "missing"


def test_readiness_advances_existing_preview_to_commit_scoped_apply(tmp_path: Path) -> None:
    repo, head = _repo(tmp_path)
    preview = MCPStablePromotionEvidenceManager(str(repo)).handle("preview", {"candidate_head": head})
    stable_dir = tmp_path / "stable"
    stable_dir.mkdir()

    readiness = get_stable_promotion_readiness(
        str(repo),
        visible_tool_names=list(REQUIRED_VISIBLE_TOOLS),
        supported_workflows=list(REQUIRED_WORKFLOWS),
        runtime_status=_runtime(repo, head),
        stable_runtime_dir=str(stable_dir),
        rollback_rehearsal_evidence=_rollback_rehearsal(head),
    )

    assert readiness["promotion_artifact_preview"]["status"] == "ready_to_apply"
    assert readiness["recommended_next_steps"][0]["arguments"] == {
        "action": "apply",
        "preview_id": preview["preview_id"],
    }
    assert readiness["recommended_next_steps"][0]["required_scope"] == "mcp:commit"


def test_verified_receipt_becomes_stale_when_origin_main_advances(tmp_path: Path) -> None:
    repo, head = _repo(tmp_path)
    manager = MCPStablePromotionEvidenceManager(str(repo))
    preview = manager.handle("preview", {"candidate_head": head})
    applied = manager.handle("apply", {"preview_id": preview["preview_id"]})
    assert applied["evidence_status"]["status"] == "verified_current"

    (repo / "NEXT.md").write_text("next\n", encoding="utf-8")
    _run("git", "add", "NEXT.md", cwd=repo)
    _run("git", "commit", "-m", "advance origin", cwd=repo)
    _run("git", "push", "origin", "main", cwd=repo)
    _run("git", "reset", "--hard", head, cwd=repo)

    status = get_stable_promotion_evidence_status(str(repo), candidate_head=head)

    assert status["verified"] is True
    assert status["status"] == "verified_stale"
    assert status["current"] is False
    assert status["freshness"] == {
        "current": False,
        "head_matches": True,
        "origin_main_available": True,
        "origin_main_matches": False,
    }
    stable_dir = tmp_path / "stable"
    stable_dir.mkdir()
    readiness = get_stable_promotion_readiness(
        str(repo),
        visible_tool_names=list(REQUIRED_VISIBLE_TOOLS),
        supported_workflows=list(REQUIRED_WORKFLOWS),
        runtime_status=_runtime(repo, head),
        stable_runtime_dir=str(stable_dir),
        rollback_rehearsal_evidence=_rollback_rehearsal(head),
    )
    assert readiness["promotion_artifact_evidence"]["status"] == "verified_stale"
    assert "PROMOTION_ARTIFACT_MANIFEST_NOT_PERSISTED" in {
        item["code"] for item in readiness["external_required_before_stable_replacement"]
    }


def test_preview_apply_excludes_dirty_worktree_but_fails_closed_when_head_changes(tmp_path: Path) -> None:
    repo, head = _repo(tmp_path)
    manager = MCPStablePromotionEvidenceManager(str(repo))

    (repo / "README.md").write_text("dirty\n", encoding="utf-8")
    dirty_preview = manager.handle("preview", {"candidate_head": head})
    assert dirty_preview["can_apply"] is True
    assert dirty_preview["blockers"] == []
    assert dirty_preview["worktree_isolation"] == {
        "status": "changes_excluded_from_exact_commit_evidence",
        "worktree_clean": False,
        "dirty_entry_count": 1,
        "candidate_source": "git_object_database",
        "worktree_content_used": False,
        "worktree_changes_block_artifact_receipt": False,
        "worktree_changes_still_block_promotion_review": True,
    }
    dirty_apply = manager.handle("apply", {"preview_id": dirty_preview["preview_id"]})
    assert dirty_apply["ok"] is True
    assert dirty_apply["status"] == "recorded"
    assert dirty_apply["worktree_isolation"]["worktree_clean"] is False
    assert dirty_apply["evidence_status"]["verified"] is True

    _run("git", "restore", "README.md", cwd=repo)
    receipt_path = repo / dirty_apply["receipt_path"]
    receipt_path.unlink()
    preview = manager.handle("preview", {"candidate_head": head})
    (repo / "NEXT.md").write_text("next\n", encoding="utf-8")
    _run("git", "add", "NEXT.md", cwd=repo)
    _run("git", "commit", "-m", "next", cwd=repo)
    changed = manager.handle("apply", {"preview_id": preview["preview_id"]})
    assert changed["ok"] is False
    assert changed["error_code"] == "PRECONDITION_CHANGED"
    assert "CANDIDATE_NOT_CURRENT_HEAD" in {item["code"] for item in changed["blockers"]}
    old_status = manager.handle("status", {"candidate_head": head})
    assert old_status["status"] == "missing"
    assert old_status["current"] is False
    assert old_status["active_preview"]["status"] == "stale"
    assert old_status["active_preview"]["can_apply"] is False

    invalid_ref = manager.handle("preview", {"candidate_head": "--help"})
    assert invalid_ref["ok"] is False
    assert invalid_ref["error_code"] == "CANDIDATE_COMMIT_UNAVAILABLE"


def test_worktree_change_after_preview_does_not_change_exact_commit_receipt(tmp_path: Path) -> None:
    repo, head = _repo(tmp_path)
    manager = MCPStablePromotionEvidenceManager(str(repo))
    preview = manager.handle("preview", {"candidate_head": head})
    (repo / "README.md").write_text("changed after preview\n", encoding="utf-8")

    applied = manager.handle("apply", {"preview_id": preview["preview_id"]})

    assert applied["ok"] is True
    assert applied["status"] == "recorded"
    assert applied["worktree_isolation"]["worktree_clean"] is False
    _run("git", "restore", "README.md", cwd=repo)
    status = manager.handle("status", {"candidate_head": head})
    assert status["verified"] is True
    assert status["worktree_isolation"]["worktree_content_used"] is False
    assert status["worktree_isolation"]["worktree_clean"] is True
    assert status["recorded_worktree_isolation"]["worktree_clean"] is False
    assert status["manifest"]["manifest_sha256"] == preview["manifest"]["manifest_sha256"]


def test_tampered_preview_and_receipt_are_rejected(tmp_path: Path) -> None:
    repo, head = _repo(tmp_path)
    manager = MCPStablePromotionEvidenceManager(str(repo))
    preview = manager.handle("preview", {"candidate_head": head})
    preview_path = repo / ".colameta" / "runtime" / "stable-promotion-evidence-previews" / f"{preview['preview_id']}.json"
    artifact = json.loads(preview_path.read_text(encoding="utf-8"))
    artifact["candidate_head"] = "0" * 40
    preview_path.write_text(json.dumps(artifact), encoding="utf-8")
    assert get_stable_promotion_preview_status(str(repo), candidate_head=head)["status"] == "missing"
    rejected = manager.handle("apply", {"preview_id": preview["preview_id"]})
    assert rejected["ok"] is False
    assert rejected["error_code"] == "PREVIEW_DIGEST_MISMATCH"

    preview = manager.handle("preview", {"candidate_head": head})
    preview_path = repo / ".colameta" / "runtime" / "stable-promotion-evidence-previews" / f"{preview['preview_id']}.json"
    artifact = json.loads(preview_path.read_text(encoding="utf-8"))
    artifact["worktree_isolation"]["worktree_clean"] = False
    artifact["preview_digest"] = _canonical_sha256(
        {key: value for key, value in artifact.items() if key != "preview_digest"}
    )
    preview_path.write_text(json.dumps(artifact), encoding="utf-8")
    assert get_stable_promotion_preview_status(str(repo), candidate_head=head)["status"] == "missing"
    rejected = manager.handle("apply", {"preview_id": preview["preview_id"]})
    assert rejected["ok"] is False
    assert rejected["error_code"] == "PREVIEW_WORKTREE_ISOLATION_MISMATCH"

    preview = manager.handle("preview", {"candidate_head": head})
    applied = manager.handle("apply", {"preview_id": preview["preview_id"]})
    receipt_path = repo / applied["receipt_path"]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["artifact_manifest"]["files"][0]["sha256"] = "0" * 64
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    status = get_stable_promotion_evidence_status(str(repo), candidate_head=head)
    assert status["ok"] is False
    assert status["error_code"] == "RECEIPT_DIGEST_MISMATCH"
    retry_preview = manager.handle("preview", {"candidate_head": head})
    conflict = manager.handle("apply", {"preview_id": retry_preview["preview_id"]})
    assert conflict["ok"] is False
    assert conflict["error_code"] == "RECEIPT_CONFLICT_INVALID"


def test_receipt_manifest_metadata_must_match_recomputed_manifest(tmp_path: Path) -> None:
    repo, head = _repo(tmp_path)
    manager = MCPStablePromotionEvidenceManager(str(repo))
    preview = manager.handle("preview", {"candidate_head": head})
    applied = manager.handle("apply", {"preview_id": preview["preview_id"]})
    receipt_path = repo / applied["receipt_path"]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["artifact_manifest"]["total_size_bytes"] += 1
    receipt["receipt_digest"] = _canonical_sha256(
        {key: value for key, value in receipt.items() if key != "receipt_digest"}
    )
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    status = get_stable_promotion_evidence_status(str(repo), candidate_head=head)

    assert status["ok"] is False
    assert status["error_code"] == "RECEIPT_MANIFEST_MISMATCH"


def test_receipt_worktree_isolation_must_match_recorded_git_snapshot(tmp_path: Path) -> None:
    repo, head = _repo(tmp_path)
    manager = MCPStablePromotionEvidenceManager(str(repo))
    preview = manager.handle("preview", {"candidate_head": head})
    applied = manager.handle("apply", {"preview_id": preview["preview_id"]})
    receipt_path = repo / applied["receipt_path"]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["worktree_isolation"]["worktree_clean"] = False
    receipt["receipt_digest"] = _canonical_sha256(
        {key: value for key, value in receipt.items() if key != "receipt_digest"}
    )
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    status = get_stable_promotion_evidence_status(str(repo), candidate_head=head)

    assert status["ok"] is False
    assert status["error_code"] == "RECEIPT_WORKTREE_ISOLATION_MISMATCH"


def test_runtime_storage_symlink_escape_fails_closed(tmp_path: Path) -> None:
    repo, head = _repo(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (repo / ".colameta").mkdir()
    (repo / ".colameta" / "runtime").symlink_to(outside, target_is_directory=True)
    manager = MCPStablePromotionEvidenceManager(str(repo))

    preview = manager.handle("preview", {"candidate_head": head})
    status = manager.handle("status", {"candidate_head": head})

    assert preview["ok"] is False
    assert preview["error_code"] == "RUNTIME_STORAGE_UNSAFE"
    assert status["ok"] is False
    assert status["error_code"] == "RUNTIME_STORAGE_UNSAFE"
    assert list(outside.iterdir()) == []


def test_concurrent_apply_publishes_one_receipt_without_overwrite(tmp_path: Path) -> None:
    repo, head = _repo(tmp_path)
    manager = MCPStablePromotionEvidenceManager(str(repo))
    previews = [manager.handle("preview", {"candidate_head": head}) for _ in range(2)]

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda preview: manager.handle("apply", {"preview_id": preview["preview_id"]}),
                previews,
            )
        )

    assert all(result["ok"] is True for result in results)
    assert {result["status"] for result in results} == {"recorded", "already_recorded"}
    receipts = list((repo / ".colameta" / "runtime" / "stable-promotion-evidence").glob("*.json"))
    assert len(receipts) == 1
    status = get_stable_promotion_evidence_status(str(repo), candidate_head=head)
    assert status["verified"] is True


def test_apply_rechecks_receipt_created_between_status_and_file_check(tmp_path: Path, monkeypatch) -> None:
    repo, head = _repo(tmp_path)
    manager = MCPStablePromotionEvidenceManager(str(repo))
    winner_preview = manager.handle("preview", {"candidate_head": head})
    observer_preview = manager.handle("preview", {"candidate_head": head})
    receipt_path = str(repo / ".colameta" / "runtime" / "stable-promotion-evidence" / f"{head}.json")
    original_isfile = os.path.isfile
    state = {"candidate_checks": 0, "inject_winner": True}

    def racing_isfile(path: object) -> bool:
        if state["inject_winner"] and str(path) == receipt_path:
            state["candidate_checks"] += 1
            if state["candidate_checks"] == 1:
                return False
            state["inject_winner"] = False
            winner = manager.handle("apply", {"preview_id": winner_preview["preview_id"]})
            assert winner["status"] == "recorded"
            return True
        return original_isfile(path)

    monkeypatch.setattr(stable_promotion_evidence.os.path, "isfile", racing_isfile)
    observed = manager.handle("apply", {"preview_id": observer_preview["preview_id"]})

    assert observed["ok"] is True
    assert observed["status"] == "already_recorded"
    assert observed["evidence_status"]["verified"] is True


def test_mcp_tool_is_visible_and_action_scoped(tmp_path: Path) -> None:
    repo, head = _repo(tmp_path)
    server = MCPPlanningBridgeServer(str(repo))
    tool_defs = {tool.name: tool for tool in server.tool_defs}

    assert "manage_stable_promotion_evidence" in server._visible_tool_names()
    assert tool_defs["manage_stable_promotion_evidence"].annotations["readOnlyHint"] is False
    assert server.get_required_scope_for_tool(
        "manage_stable_promotion_evidence", {"action": "status"}
    ) == "mcp:read"
    assert server.get_required_scope_for_tool(
        "manage_stable_promotion_evidence", {"action": "preview"}
    ) == "mcp:preview"
    assert server.get_required_scope_for_tool(
        "manage_stable_promotion_evidence", {"action": "apply", "preview_id": "preview_1234"}
    ) == "mcp:commit"
    assert server.get_required_scope_for_tool(
        "manage_stable_promotion_evidence", {"action": "unknown"}
    ) == "mcp:unknown"

    status = server.call_tool_for_agent(
        "manage_stable_promotion_evidence", {"action": "status", "candidate_head": head}
    )
    assert status["ok"] is True
    assert status["data"]["status"] == "missing"
    preview = server.call_tool_for_agent(
        "manage_stable_promotion_evidence", {"action": "preview", "candidate_head": head}
    )
    assert preview["ok"] is True
    assert preview["data"]["can_apply"] is True
    assert isinstance(preview["data"]["workflow_id"], str)
    applied = server.call_tool_for_agent(
        "manage_stable_promotion_evidence",
        {"action": "apply", "preview_id": preview["data"]["preview_id"]},
    )
    assert applied["ok"] is True
    assert applied["data"]["workflow_id"] == preview["data"]["workflow_id"]


def test_workflow_audit_classifies_all_stable_evidence_actions() -> None:
    expected_risks = {
        "inspect": "info",
        "status": "info",
        "preview": "preview",
        "apply": "commit",
        "discard": "preview",
    }

    for action, risk in expected_risks.items():
        assert should_record_tool("manage_stable_promotion_evidence", action) is True
        assert infer_risk_level("manage_stable_promotion_evidence", action) == risk
    assert should_record_tool("manage_stable_promotion_evidence", "unknown") is False


def test_service_routed_preview_preserves_project_name_for_apply(tmp_path: Path) -> None:
    repo, head = _repo(tmp_path)
    registry = ProjectRegistry(
        registry_path=str(tmp_path / "registry.json"),
        user_settings_path=str(tmp_path / "settings.json"),
    )
    registered = registry.register_project(
        str(repo),
        project_name="demo-project",
        project_mode="managed",
    )
    assert registered["ok"] is True
    server = MCPPlanningBridgeServer(str(repo), service_mode=True)
    server.project_registry = registry

    status = server.call_tool_for_agent(
        "manage_stable_promotion_evidence",
        {"action": "status", "candidate_head": head, "project_name": "demo-project"},
    )

    assert status["ok"] is True
    preview_arguments = status["data"]["safe_next_action"]["arguments"]
    assert preview_arguments["project_name"] == "demo-project"
    preview = server.call_tool_for_agent("manage_stable_promotion_evidence", preview_arguments)
    assert preview["ok"] is True
    next_arguments = preview["data"]["next_action"]["arguments"]
    assert next_arguments["project_name"] == "demo-project"
    applied = server.call_tool_for_agent("manage_stable_promotion_evidence", next_arguments)
    assert applied["ok"] is True
    assert applied["data"]["status"] == "recorded"


def test_service_routed_readiness_preserves_project_name_in_recommended_preview(tmp_path: Path, monkeypatch) -> None:
    repo, head = _repo(tmp_path)
    registry = ProjectRegistry(
        registry_path=str(tmp_path / "registry.json"),
        user_settings_path=str(tmp_path / "settings.json"),
    )
    registered = registry.register_project(
        str(repo),
        project_name="demo-project",
        project_mode="managed",
    )
    assert registered["ok"] is True
    server = MCPPlanningBridgeServer(str(repo), service_mode=True)
    server.project_registry = registry
    monkeypatch.setattr(stable_promotion_readiness, "get_runtime_version_status", lambda _root: _runtime(repo, head))

    readiness = server.call_tool_for_agent(
        "get_stable_promotion_readiness",
        {"project_name": "demo-project"},
    )

    assert readiness["ok"] is True
    recommended = readiness["data"]["recommended_next_steps"][0]
    assert recommended["tool"] == "manage_stable_promotion_evidence"
    assert recommended["arguments"]["project_name"] == "demo-project"
    preview = server.call_tool_for_agent(recommended["tool"], recommended["arguments"])
    assert preview["ok"] is True
    assert preview["data"]["can_apply"] is True
