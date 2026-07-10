from __future__ import annotations

import json
from pathlib import Path

from runner.mcp_submission_evidence_revision import MCPSubmissionEvidenceRevisionManager
from runner.release_submission_readiness import (
    DEFAULT_SUBMISSION_MATERIALS_REL_PATH,
    init_submission_evidence_scaffold,
)
from runner.workflow_engine import record_tool_call
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
    assert FINAL_LOGO.strip() not in json.dumps(applied)
    assert evidence_path.read_text(encoding="utf-8") == FINAL_LOGO
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["logo_ready"] is False
    assert "preview-bound local transaction" in manifest["notes"]
    assert manager.handle("apply", {"preview_id": preview["preview_id"]})["error_code"] == "PREVIEW_NOT_FOUND"


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
