from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import runner.release_submission_readiness as release_submission_readiness
from runner.mcp_submission_evidence_revision import MCPSubmissionEvidenceRevisionManager
from runner.release_submission_readiness import (
    DEFAULT_SUBMISSION_MATERIALS_REL_PATH,
    init_submission_evidence_scaffold,
)
from runner.workflow_engine import infer_risk_level, record_tool_call, should_record_tool
from runner.workflow_records import WorkflowRecordStore


DRAFT_LOGO = """# Logo Evidence

## asset_path
docs/assets/app-logo.png

## dimensions
1024x1024

## review_notes
Draft evidence only; a human reviewer still needs to confirm the final asset.
"""

FINAL_LOGO = """# Logo Evidence

## asset_path
docs/assets/app-logo.png

## dimensions
1024x1024 RGBA PNG

## review_notes
The release operator compared the exported asset with the submission preview on 2026-07-11.
"""

FINAL_LOGO_VARIANT = """# Logo Variant Evidence

## asset_path
docs/assets/app-logo-dark.png

## dimensions
1024x1024 RGBA PNG

## review_notes
The release operator reviewed the final dark-mode asset in the local Web Console.
"""


def _project(tmp_path: Path, *, ready: bool = False) -> tuple[Path, Path]:
    init_submission_evidence_scaffold(str(tmp_path))
    evidence_path = tmp_path / "docs/submission/logo.md"
    evidence_path.write_text(DRAFT_LOGO, encoding="utf-8")
    manifest_path = tmp_path / DEFAULT_SUBMISSION_MATERIALS_REL_PATH
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["evidence"]["logo"] = "docs/submission/logo.md"
    manifest["logo_ready"] = ready
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return evidence_path, manifest_path


def _preview(manager: MCPSubmissionEvidenceRevisionManager, content: str = FINAL_LOGO) -> dict:
    return manager.handle(
        "preview",
        {
            "key": "logo",
            "ref": "docs/submission/logo.md",
            "content": content,
        },
    )


def test_preview_and_apply_revise_bound_evidence_without_returning_content(tmp_path: Path) -> None:
    evidence_path, manifest_path = _project(tmp_path, ready=True)
    manager = MCPSubmissionEvidenceRevisionManager(str(tmp_path))

    preview = _preview(manager)

    assert preview["ok"] is True
    assert preview["status"] == "preview_ready"
    assert preview["content_included"] is False
    assert preview["prior_reason_codes"] == ["DRAFT_CONTENT", "HUMAN_REVIEW_PENDING"]
    assert preview["current_sha256"] != preview["proposed_sha256"]
    assert len(preview["manifest_sha256"]) == 64
    assert FINAL_LOGO.strip() not in json.dumps(preview)
    assert evidence_path.read_text(encoding="utf-8") == DRAFT_LOGO
    artifact_path = next((tmp_path / ".colameta/runtime/submission-evidence-revision-previews").glob("*.json"))
    artifact_text = artifact_path.read_text(encoding="utf-8")
    assert FINAL_LOGO.strip() not in artifact_text
    assert "proposed_content" not in artifact_text

    applied = manager.handle("apply", {"preview_id": preview["preview_id"], "content": FINAL_LOGO})

    assert applied["ok"] is True
    assert applied["status"] == "applied"
    assert applied["content_included"] is False
    assert applied["manifest_sha256_before"] == preview["manifest_sha256"]
    assert len(applied["manifest_sha256_after"]) == 64
    assert FINAL_LOGO.strip() not in json.dumps(applied)
    assert evidence_path.read_text(encoding="utf-8") == FINAL_LOGO
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["logo_ready"] is False
    assert "preview-bound local transaction" in manifest["notes"]
    assert manager.handle("apply", {"preview_id": preview["preview_id"]})["error_code"] == "PREVIEW_NOT_FOUND"


def test_editor_context_exposes_only_manifest_bound_unfinished_content_for_local_web(tmp_path: Path) -> None:
    _project(tmp_path)
    manager = MCPSubmissionEvidenceRevisionManager(str(tmp_path))

    context = manager.editor_context({"key": "logo", "ref": "docs/submission/logo.md"})

    assert context["ok"] is True
    assert context["action"] == "editor_context"
    assert context["current_content"] == DRAFT_LOGO
    assert context["content_included"] is True
    assert context["local_web_only"] is True
    assert context["reason_codes"] == ["DRAFT_CONTENT", "HUMAN_REVIEW_PENDING"]
    assert context["required_sections"] == ["asset_path", "dimensions", "review_notes"]
    assert len(context["current_sha256"]) == 64

    missing = manager.editor_context({"key": "logo", "ref": "docs/submission/not-bound.md"})
    assert missing["ok"] is False
    assert missing["content_included"] is False


def test_ready_review_binds_every_manifest_ref_before_marking_one_key_ready(tmp_path: Path) -> None:
    _, manifest_path = _project(tmp_path)
    first_path = tmp_path / "docs/submission/logo.md"
    second_path = tmp_path / "docs/submission/logo-dark.md"
    first_path.write_text(FINAL_LOGO, encoding="utf-8")
    second_path.write_text(FINAL_LOGO_VARIANT, encoding="utf-8")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["evidence"]["logo"] = ["docs/submission/logo.md", "docs/submission/logo-dark.md"]
    manifest["notes"] = "Keep this operator-authored submission note unchanged."
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manager = MCPSubmissionEvidenceRevisionManager(str(tmp_path))

    first = manager.ready_review_context({"key": "logo", "ref": "docs/submission/logo.md"})
    second = manager.ready_review_context({"key": "logo", "ref": "docs/submission/logo-dark.md"})

    assert first["ok"] is True
    assert first["current_content"] == FINAL_LOGO
    assert first["key_refs"] == ["docs/submission/logo.md", "docs/submission/logo-dark.md"]
    assert first["local_web_only"] is True
    incomplete = manager.ready_preview({
        "key": "logo",
        "reviewed_refs": [{"ref": first["ref"], "current_sha256": first["current_sha256"]}],
    })
    assert incomplete["ok"] is False
    assert incomplete["error_code"] == "SUBMISSION_EVIDENCE_READY_REVIEW_INCOMPLETE"
    assert incomplete["missing_or_changed_refs"] == ["docs/submission/logo-dark.md"]

    preview = manager.ready_preview({
        "key": "logo",
        "reviewed_refs": [
            {"ref": first["ref"], "current_sha256": first["current_sha256"]},
            {"ref": second["ref"], "current_sha256": second["current_sha256"]},
        ],
    })
    assert preview["ok"] is True
    assert preview["reviewed_ref_count"] == 2
    assert preview["content_included"] is False
    assert FINAL_LOGO.strip() not in json.dumps(preview)
    artifact_path = next((tmp_path / ".colameta/runtime/submission-evidence-revision-previews").glob("evidence_ready_*.json"))
    artifact_text = artifact_path.read_text(encoding="utf-8")
    assert FINAL_LOGO.strip() not in artifact_text
    assert FINAL_LOGO_VARIANT.strip() not in artifact_text
    missing_key = manager.ready_apply({"preview_id": preview["preview_id"]})
    assert missing_key["ok"] is False
    assert missing_key["error_code"] == "SUBMISSION_EVIDENCE_READY_PREVIEW_KEY_MISMATCH"
    mismatched_key = manager.ready_apply({"preview_id": preview["preview_id"], "key": "screenshots"})
    assert mismatched_key["ok"] is False
    assert mismatched_key["error_code"] == "SUBMISSION_EVIDENCE_READY_PREVIEW_KEY_MISMATCH"

    second_path.write_text(FINAL_LOGO_VARIANT + "changed\n", encoding="utf-8")
    changed = manager.ready_apply({"preview_id": preview["preview_id"], "key": "logo"})
    assert changed["ok"] is False
    assert changed["error_code"] == "SUBMISSION_EVIDENCE_REVIEWED_CONTENT_CHANGED"
    assert changed["changed_refs"] == ["docs/submission/logo-dark.md"]
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["logo_ready"] is False

    second_path.write_text(FINAL_LOGO_VARIANT, encoding="utf-8")
    original_validate = release_submission_readiness._validate_ready_evidence_refs
    validate_calls = 0

    def mutate_during_final_write(*args, **kwargs):
        nonlocal validate_calls
        validate_calls += 1
        if validate_calls == 2:
            second_path.write_text(FINAL_LOGO_VARIANT + "changed during ready write\n", encoding="utf-8")
        return original_validate(*args, **kwargs)

    with patch(
        "runner.release_submission_readiness._validate_ready_evidence_refs",
        side_effect=mutate_during_final_write,
    ):
        raced = manager.ready_apply({"preview_id": preview["preview_id"], "key": "logo"})

    assert raced["ok"] is False
    assert raced["error_code"] == "SUBMISSION_EVIDENCE_REVIEWED_CONTENT_CHANGED_DURING_WRITE"
    assert raced["rollback_receipt"]["status"] == "committed"
    rolled_back_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert rolled_back_manifest["logo_ready"] is False
    assert rolled_back_manifest["notes"] == "Keep this operator-authored submission note unchanged."

    second_path.write_text(FINAL_LOGO_VARIANT, encoding="utf-8")
    applied = manager.ready_apply({"preview_id": preview["preview_id"], "key": "logo"})
    assert applied["ok"] is True
    assert applied["status"] == "ready_marked"
    assert applied["ready_fields_marked"] == ["logo_ready"]
    assert applied["content_included"] is False
    updated_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert updated_manifest["logo_ready"] is True
    assert updated_manifest["notes"] == "Keep this operator-authored submission note unchanged."
    assert applied["notes_updated"] is False
    assert applied["manifest_notes_preserved"] is True
    assert applied["expected_digests_enforced"] is True


def test_ready_review_workflow_risk_levels_match_preview_and_write_authority() -> None:
    assert should_record_tool("mark_submission_evidence_ready_fields", "preview") is True
    assert should_record_tool("mark_submission_evidence_ready_fields", "apply") is True
    assert infer_risk_level("mark_submission_evidence_ready_fields", "preview") == "preview"
    assert infer_risk_level("mark_submission_evidence_ready_fields", "apply") == "write"


def test_preview_rejects_replacement_that_is_still_unfinished_without_artifact(tmp_path: Path) -> None:
    _project(tmp_path)
    manager = MCPSubmissionEvidenceRevisionManager(str(tmp_path))

    result = _preview(manager, DRAFT_LOGO)

    assert result["ok"] is False
    assert result["error_code"] == "SUBMISSION_EVIDENCE_CONTENT_REVIEW_REQUIRED"
    assert result["reason_codes"] == ["DRAFT_CONTENT", "HUMAN_REVIEW_PENDING"]
    assert result["content_included"] is False
    preview_dir = tmp_path / ".colameta/runtime/submission-evidence-revision-previews"
    assert not list(preview_dir.glob("*.json"))


def test_preview_requires_all_evidence_template_sections(tmp_path: Path) -> None:
    _project(tmp_path)
    manager = MCPSubmissionEvidenceRevisionManager(str(tmp_path))

    result = _preview(manager, "# Logo Evidence\n\n## asset_path\nlogo.png\n")

    assert result["ok"] is False
    assert result["error_code"] == "SUBMISSION_EVIDENCE_REQUIRED_SECTIONS_MISSING"
    assert result["missing_sections"] == ["dimensions", "review_notes"]


def test_preview_rejects_ref_not_bound_to_selected_key(tmp_path: Path) -> None:
    _project(tmp_path)
    other = tmp_path / "docs/submission/other.md"
    other.write_text(DRAFT_LOGO, encoding="utf-8")
    manager = MCPSubmissionEvidenceRevisionManager(str(tmp_path))

    result = manager.handle(
        "preview",
        {"key": "logo", "ref": "docs/submission/other.md", "content": FINAL_LOGO},
    )

    assert result["ok"] is False
    assert result["error_code"] == "SUBMISSION_EVIDENCE_REF_NOT_BOUND_TO_KEY"
    assert other.read_text(encoding="utf-8") == DRAFT_LOGO


def test_preview_rejects_ref_shared_across_evidence_keys(tmp_path: Path) -> None:
    evidence_path, manifest_path = _project(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["evidence"]["screenshots"] = ["docs/submission/logo.md"]
    manifest["screenshots_ready"] = True
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest_before = manifest_path.read_text(encoding="utf-8")
    manager = MCPSubmissionEvidenceRevisionManager(str(tmp_path))

    result = _preview(manager)

    assert result["ok"] is False
    assert result["error_code"] == "SUBMISSION_EVIDENCE_REF_SHARED_ACROSS_KEYS"
    assert result["bound_keys"] == ["logo", "screenshots"]
    assert evidence_path.read_text(encoding="utf-8") == DRAFT_LOGO
    assert manifest_path.read_text(encoding="utf-8") == manifest_before


def test_apply_blocks_when_evidence_changes_after_preview(tmp_path: Path) -> None:
    evidence_path, manifest_path = _project(tmp_path)
    manager = MCPSubmissionEvidenceRevisionManager(str(tmp_path))
    preview = _preview(manager)
    changed = DRAFT_LOGO.replace("1024x1024", "512x512")
    evidence_path.write_text(changed, encoding="utf-8")
    manifest_before = manifest_path.read_text(encoding="utf-8")

    result = manager.handle("apply", {"preview_id": preview["preview_id"], "content": FINAL_LOGO})

    assert result["ok"] is False
    assert result["error_code"] == "SUBMISSION_EVIDENCE_BASE_CHANGED"
    assert evidence_path.read_text(encoding="utf-8") == changed
    assert manifest_path.read_text(encoding="utf-8") == manifest_before


def test_apply_requires_exact_content_bound_by_preview_digest(tmp_path: Path) -> None:
    evidence_path, manifest_path = _project(tmp_path)
    manager = MCPSubmissionEvidenceRevisionManager(str(tmp_path))
    preview = _preview(manager)
    different_final = FINAL_LOGO.replace("2026-07-11", "2026-07-12")
    manifest_before = manifest_path.read_text(encoding="utf-8")

    result = manager.handle(
        "apply",
        {"preview_id": preview["preview_id"], "content": different_final},
    )

    assert result["ok"] is False
    assert result["error_code"] == "SUBMISSION_EVIDENCE_PROPOSED_CONTENT_MISMATCH"
    assert result["received_sha256"] != result["proposed_sha256"]
    assert result["content_included"] is False
    assert evidence_path.read_text(encoding="utf-8") == DRAFT_LOGO
    assert manifest_path.read_text(encoding="utf-8") == manifest_before


def test_apply_blocks_when_manifest_changes_after_preview(tmp_path: Path) -> None:
    evidence_path, manifest_path = _project(tmp_path)
    manager = MCPSubmissionEvidenceRevisionManager(str(tmp_path))
    preview = _preview(manager)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["notes"] = "concurrent operator update"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    result = manager.handle("apply", {"preview_id": preview["preview_id"], "content": FINAL_LOGO})

    assert result["ok"] is False
    assert result["error_code"] == "SUBMISSION_EVIDENCE_MANIFEST_CHANGED"
    assert evidence_path.read_text(encoding="utf-8") == DRAFT_LOGO
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["notes"] == "concurrent operator update"


def test_preview_rejects_symlinked_evidence_before_read(tmp_path: Path) -> None:
    _, manifest_path = _project(tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_text(DRAFT_LOGO, encoding="utf-8")
    evidence_path = tmp_path / "docs/submission/logo.md"
    evidence_path.unlink()
    evidence_path.symlink_to(outside)
    manager = MCPSubmissionEvidenceRevisionManager(str(tmp_path))

    result = _preview(manager)

    assert result["ok"] is False
    assert result["error_code"] == "SUBMISSION_EVIDENCE_SYMLINK_NOT_ALLOWED"
    assert outside.read_text(encoding="utf-8") == DRAFT_LOGO
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["logo_ready"] is False


def test_preview_rejects_symlinked_manifest_before_read(tmp_path: Path) -> None:
    evidence_path, manifest_path = _project(tmp_path)
    outside_manifest = tmp_path / "outside-manifest.json"
    outside_manifest.write_bytes(manifest_path.read_bytes())
    manifest_path.unlink()
    manifest_path.symlink_to(outside_manifest)
    manager = MCPSubmissionEvidenceRevisionManager(str(tmp_path))

    result = _preview(manager)

    assert result["ok"] is False
    assert result["error_code"] == "SUBMISSION_EVIDENCE_MANIFEST_SYMLINK_NOT_ALLOWED"
    assert result["content_included"] is False
    assert evidence_path.read_text(encoding="utf-8") == DRAFT_LOGO


def test_status_and_discard_never_include_proposed_content(tmp_path: Path) -> None:
    _project(tmp_path)
    manager = MCPSubmissionEvidenceRevisionManager(str(tmp_path))
    preview = _preview(manager)

    status = manager.handle("status", {"preview_id": preview["preview_id"]})
    discarded = manager.handle("discard", {"preview_id": preview["preview_id"]})

    assert status["status"] == "preview_ready"
    assert status["content_included"] is False
    assert FINAL_LOGO.strip() not in json.dumps(status)
    assert discarded["status"] == "discarded"
    assert FINAL_LOGO.strip() not in json.dumps(discarded)
    assert manager.handle("status", {"preview_id": preview["preview_id"]})["error_code"] == "PREVIEW_NOT_FOUND"


def test_workflow_record_hashes_revision_content_instead_of_storing_it(tmp_path: Path) -> None:
    secret_content = FINAL_LOGO + "\nprivate operator note 8f921ca7\n"
    result = {
        "ok": True,
        "action": "preview",
        "status": "preview_ready",
        "preview_id": "evidence_revision_record_test",
        "content_included": False,
        "current_sha256": "a" * 64,
        "manifest_sha256": "b" * 64,
        "proposed_sha256": "c" * 64,
    }

    recorded = record_tool_call(
        str(tmp_path),
        "manage_submission_evidence_revision",
        "preview",
        {
            "action": "preview",
            "key": "logo",
            "ref": "docs/submission/logo.md",
            "content": secret_content,
        },
        result,
    )

    packet = WorkflowRecordStore(str(tmp_path)).get_run(recorded["workflow_id"])
    run = packet["run"]
    serialized = json.dumps(run)
    assert "private operator note 8f921ca7" not in serialized
    content_summary = run["inputs_summary"]["content"]
    assert content_summary["present"] is True
    assert content_summary["length"] == len(secret_content)
    assert len(content_summary["sha256"]) == 64
    assert run["outputs_summary"]["current_sha256"] == "a" * 64
    assert run["outputs_summary"]["manifest_sha256"] == "b" * 64
    assert run["outputs_summary"]["proposed_sha256"] == "c" * 64
