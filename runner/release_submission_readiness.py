from __future__ import annotations

import os
import json
import hashlib
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from runner.production_ops import DEFAULT_CONNECTOR_SMOKE_FRESH_HOURS, DEFAULT_PUBLIC_BASE_URL
from runner.product_readiness import build_product_readiness_packet
from runner.file_transaction import FileTransaction, FileTransactionError


RELEASE_SUBMISSION_SOURCE = "release_submission_readiness"
RELEASE_SUBMISSION_VERSION = "release_submission_readiness.v1"
SUBMISSION_EVIDENCE_SCAFFOLD_SOURCE = "submission_evidence_scaffold"
SUBMISSION_EVIDENCE_SCAFFOLD_VERSION = "submission_evidence_scaffold.v1"
SUBMISSION_EVIDENCE_FILL_SOURCE = "submission_evidence_fill"
SUBMISSION_EVIDENCE_FILL_VERSION = "submission_evidence_fill.v1"
SUBMISSION_EVIDENCE_MARK_READY_SOURCE = "submission_evidence_mark_ready"
SUBMISSION_EVIDENCE_MARK_READY_VERSION = "submission_evidence_mark_ready.v1"
SUBMISSION_EVIDENCE_REVIEW_CONFIRMATION = "human_reviewed"
SUBMISSION_EVIDENCE_CONTENT_REVIEW_REQUIRED = "SUBMISSION_EVIDENCE_CONTENT_REVIEW_REQUIRED"
DEFAULT_SUBMISSION_MATERIALS_REL_PATH = "docs/chatgpt-app-submission-materials.json"
RELEASE_SUBMISSION_MATERIALS_MAX_BYTES = 65536
SUBMISSION_EVIDENCE_CONTENT_MAX_BYTES = 32768
SUBMISSION_EVIDENCE_CONTENT_ROOT = "docs/submission/"
READY = "ready"
NEEDS_ATTENTION = "needs_attention"
BLOCKED = "blocked"

SUBMISSION_EVIDENCE_UNFINISHED_CONTENT_MARKERS = {
    "DRAFT_CONTENT": (
        "draft evidence only",
        "draft visual evidence",
        "this draft does not claim complete",
        "this evidence draft is generated",
        "this draft is built",
    ),
    "FINAL_ASSET_MISSING": (
        "it is not a final",
        "no final chatgpt app",
        "must be provided separately",
    ),
    "HUMAN_REVIEW_PENDING": (
        "a human reviewer still needs to",
        "still need a human",
        "human privacy review is still required",
        "human security/privacy review is still required",
        "human reviewer must confirm final",
    ),
    "CONFIRMATION_PENDING": (
        "not yet confirmed",
        "must remain false until",
        "keep this field unready until",
        "must be confirmed from the dashboard before",
        "must still be confirmed by the human submitter",
    ),
    "REQUIRED_PERMISSION_UNPROVEN": (
        "does not prove that the current operator session has",
    ),
    "REQUIRED_COVERAGE_MISSING": (
        "they do not cover mobile ui screenshots",
    ),
}

SUBMISSION_MATERIAL_TEXT_FIELDS = {
    "app_name",
    "app_description",
    "company_url",
    "privacy_policy_url",
}
SUBMISSION_MATERIAL_BOOL_FIELDS = {
    "logo_ready",
    "screenshots_ready",
    "test_prompts_ready",
    "test_responses_ready",
    "localization_ready",
    "mcp_tool_info_ready",
    "app_management_permissions_confirmed",
    "security_review_ready",
    "metadata_snapshot_reviewed",
    "submission_confirmations_ready",
}
SUBMISSION_MATERIAL_METADATA_FIELDS = {
    "schema_version",
    "evidence",
    "notes",
}
SUBMISSION_MATERIAL_FIELDS = (
    SUBMISSION_MATERIAL_TEXT_FIELDS | SUBMISSION_MATERIAL_BOOL_FIELDS | SUBMISSION_MATERIAL_METADATA_FIELDS
)
SUBMISSION_EVIDENCE_REQUIREMENTS = {
    "logo_ready": "logo",
    "screenshots_ready": "screenshots",
    "test_prompts_ready": "test_prompts",
    "test_responses_ready": "test_responses",
    "localization_ready": "localization",
    "mcp_tool_info_ready": "mcp_tool_info",
    "app_management_permissions_confirmed": "app_management_permissions",
    "security_review_ready": "security_review",
    "metadata_snapshot_reviewed": "metadata_snapshot",
    "submission_confirmations_ready": "submission_confirmations",
}
SUBMISSION_EVIDENCE_READY_FIELD_BY_KEY = {evidence_key: ready_field for ready_field, evidence_key in SUBMISSION_EVIDENCE_REQUIREMENTS.items()}
SUBMISSION_EVIDENCE_DEFAULT_OUTPUT_REFS = {
    "logo": "docs/submission/logo.md",
    "screenshots": "docs/submission/screenshot-1.md",
    "test_prompts": "docs/submission/test-prompts.md",
    "test_responses": "docs/submission/test-responses.md",
    "localization": "docs/submission/localization.md",
    "mcp_tool_info": "docs/submission/mcp-tool-info.md",
    "app_management_permissions": "docs/submission/app-management-permissions.md",
    "security_review": "docs/submission/security-review.md",
    "metadata_snapshot": "docs/submission/metadata-snapshot.md",
    "submission_confirmations": "docs/submission/submission-confirmations.md",
}
SUBMISSION_EVIDENCE_ENTRY_TEMPLATE_DETAILS = {
    "logo": {
        "title": "Logo Evidence",
        "purpose": "Record the final app logo asset path, dimensions, and review notes.",
        "required_sections": ["asset_path", "dimensions", "review_notes"],
    },
    "screenshots": {
        "title": "Screenshot Evidence",
        "purpose": "Record final ChatGPT App screenshots, viewport/device context, and captions.",
        "required_sections": ["asset_paths", "viewport_or_device", "captions", "review_notes"],
    },
    "test_prompts": {
        "title": "Test Prompts Evidence",
        "purpose": "List review prompts that exercise the app's main workflows and failure paths.",
        "required_sections": ["prompt_id", "prompt_text", "workflow_covered", "expected_tool_calls"],
    },
    "test_responses": {
        "title": "Test Responses Evidence",
        "purpose": "Record observed tool behavior and response evidence for each test prompt.",
        "required_sections": ["prompt_id", "observed_result", "evidence_link_or_notes", "review_status"],
    },
    "localization": {
        "title": "Localization Evidence",
        "purpose": "Document supported locales and localized metadata or screenshot coverage.",
        "required_sections": ["supported_locales", "localized_assets", "known_gaps"],
    },
    "mcp_tool_info": {
        "title": "MCP Tool Information Evidence",
        "purpose": "Document exposed tools, descriptions, scopes, and safety boundaries.",
        "required_sections": ["tool_inventory", "scope_map", "side_effects", "safety_boundaries"],
    },
    "app_management_permissions": {
        "title": "App Management Permissions Evidence",
        "purpose": "Record who owns Dashboard submission and app management permissions.",
        "required_sections": ["owner", "dashboard_access", "approval_notes"],
    },
    "security_review": {
        "title": "Security And Privacy Review Evidence",
        "purpose": "Record least privilege, consent, redaction, and monitoring review evidence.",
        "required_sections": ["least_privilege", "consent", "redaction", "monitoring"],
    },
    "metadata_snapshot": {
        "title": "Metadata Snapshot Evidence",
        "purpose": "Record the app name, description, URLs, screenshots, and tool metadata reviewed for submission.",
        "required_sections": ["app_metadata", "urls", "assets", "reviewer"],
    },
    "submission_confirmations": {
        "title": "Submission Confirmations Evidence",
        "purpose": "Record final human confirmations required before Dashboard submission.",
        "required_sections": ["human_reviewer", "confirmed_items", "submission_boundary"],
    },
}
SUBMISSION_EVIDENCE_SCAFFOLD_REFS = {
    "logo": "docs/submission/logo.todo.md",
    "screenshots": ["docs/submission/screenshot-1.todo.md"],
    "test_prompts": "docs/submission/test-prompts.todo.md",
    "test_responses": "docs/submission/test-responses.todo.md",
    "localization": "docs/submission/localization.todo.md",
    "mcp_tool_info": "docs/submission/mcp-tool-info.todo.md",
    "app_management_permissions": "docs/submission/app-management-permissions.todo.md",
    "security_review": "docs/submission/security-review.todo.md",
    "metadata_snapshot": "docs/submission/metadata-snapshot.todo.md",
    "submission_confirmations": "docs/submission/submission-confirmations.todo.md",
}

DOC_REFS = [
    {
        "id": "submit_app",
        "url": "https://developers.openai.com/apps-sdk/deploy/submission",
        "why": "Submission requires public MCP details, required form fields, screenshots, prompts/responses, and review flow.",
    },
    {
        "id": "submission_guidelines",
        "url": "https://developers.openai.com/apps-sdk/app-submission-guidelines",
        "why": "Apps must be complete, reliable, well-described, and thoroughly tested before submission.",
    },
    {
        "id": "testing",
        "url": "https://developers.openai.com/apps-sdk/deploy/testing",
        "why": "Tool handlers, ChatGPT developer mode, and mobile layouts should be tested before rollout.",
    },
    {
        "id": "security_privacy",
        "url": "https://developers.openai.com/apps-sdk/guides/security-privacy",
        "why": "Launch readiness should cover least privilege, explicit consent, redaction, confirmation, and operational monitoring.",
    },
]


def build_release_submission_readiness(
    project_root: str,
    *,
    project_name: str | None = None,
    public_base_url: str = DEFAULT_PUBLIC_BASE_URL,
    no_network: bool = False,
    app_name: str | None = None,
    app_description: str | None = None,
    company_url: str | None = None,
    privacy_policy_url: str | None = None,
    logo_ready: bool = False,
    screenshots_ready: bool = False,
    test_prompts_ready: bool = False,
    test_responses_ready: bool = False,
    localization_ready: bool = False,
    mcp_tool_info_ready: bool = False,
    app_management_permissions_confirmed: bool = False,
    security_review_ready: bool = False,
    metadata_snapshot_reviewed: bool = False,
    submission_confirmations_ready: bool = False,
    submission_materials: Mapping[str, Any] | None = None,
    auto_load_submission_materials: bool = True,
    readiness_packet: dict[str, Any] | None = None,
    now: datetime | None = None,
    readiness_builder: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    readiness = readiness_packet if isinstance(readiness_packet, dict) else None
    if readiness is None:
        builder = readiness_builder or build_product_readiness_packet
        readiness = builder(
            project_root,
            public_base_url=public_base_url,
            no_network=no_network,
            connector_smoke_fresh_hours=DEFAULT_CONNECTOR_SMOKE_FRESH_HOURS,
            now=now,
        )
    manifest_source: dict[str, Any] | None = None
    manifest_error: dict[str, Any] | None = None
    if submission_materials is None and auto_load_submission_materials:
        default_materials_path = default_submission_materials_path(project_root)
        if os.path.isfile(default_materials_path):
            loaded_materials, load_error = load_submission_materials_file(default_materials_path)
            if loaded_materials is not None:
                submission_materials = loaded_materials
                manifest_source = {
                    "source": "default_manifest_file",
                    "path": DEFAULT_SUBMISSION_MATERIALS_REL_PATH,
                }
            else:
                manifest_error = {
                    "source": "default_manifest_file",
                    "path": DEFAULT_SUBMISSION_MATERIALS_REL_PATH,
                    **(load_error or {"error_code": "SUBMISSION_MATERIALS_READ_FAILED"}),
                }
    materials = _merge_submission_materials(
        submission_materials,
        app_name=app_name,
        app_description=app_description,
        company_url=company_url,
        privacy_policy_url=privacy_policy_url,
        logo_ready=logo_ready,
        screenshots_ready=screenshots_ready,
        test_prompts_ready=test_prompts_ready,
        test_responses_ready=test_responses_ready,
        localization_ready=localization_ready,
        mcp_tool_info_ready=mcp_tool_info_ready,
        app_management_permissions_confirmed=app_management_permissions_confirmed,
        security_review_ready=security_review_ready,
        metadata_snapshot_reviewed=metadata_snapshot_reviewed,
        submission_confirmations_ready=submission_confirmations_ready,
        manifest_source=manifest_source,
        manifest_error=manifest_error,
    )
    materials_manifest = materials["manifest"]
    evidence_references = _evidence_references_check(project_root, materials, materials_manifest)
    evidence_progress = _submission_evidence_progress(project_root, materials, materials_manifest)
    checks = _checks(
        readiness=readiness,
        app_name=materials["app_name"],
        app_description=materials["app_description"],
        company_url=materials["company_url"],
        privacy_policy_url=materials["privacy_policy_url"],
        logo_ready=materials["logo_ready"],
        screenshots_ready=materials["screenshots_ready"],
        test_prompts_ready=materials["test_prompts_ready"],
        test_responses_ready=materials["test_responses_ready"],
        localization_ready=materials["localization_ready"],
        mcp_tool_info_ready=materials["mcp_tool_info_ready"],
        app_management_permissions_confirmed=materials["app_management_permissions_confirmed"],
        security_review_ready=materials["security_review_ready"],
        metadata_snapshot_reviewed=materials["metadata_snapshot_reviewed"],
        submission_confirmations_ready=materials["submission_confirmations_ready"],
        submission_materials=materials_manifest,
        evidence_references=evidence_references,
    )
    blocker_codes, needs_attention_codes = _reason_codes(checks)
    status = BLOCKED if blocker_codes else NEEDS_ATTENTION if needs_attention_codes else READY
    evidence_entry_templates = _submission_evidence_entry_templates_for(
        evidence_references.get("incomplete_keys") if isinstance(evidence_references, dict) else []
    )
    return {
        "ok": True,
        "source": RELEASE_SUBMISSION_SOURCE,
        "schema_version": RELEASE_SUBMISSION_VERSION,
        "read_only": True,
        "side_effects": False,
        "project_root": os.path.abspath(os.path.expanduser(project_root)),
        "project_name": project_name,
        "public_base_url": readiness.get("public_base_url") or public_base_url,
        "connector_url": readiness.get("connector_url"),
        "observed_at": _iso_now(now),
        "status": status,
        "ready": status == READY,
        "summary": _summary_for(status),
        "checks": checks,
        "blocker_codes": blocker_codes,
        "needs_attention_codes": needs_attention_codes,
        "submission_materials": materials_manifest,
        "submission_evidence_entry_templates": evidence_entry_templates,
        "submission_evidence_progress": evidence_progress,
        "required_submission_materials": [
            "app_name",
            "logo",
            "description",
            "company_url",
            "privacy_policy_url",
            "mcp_server_details",
            "tool_information",
            "screenshots",
            "test_prompts_and_responses",
            "localization_information",
            "submission_confirmations",
        ],
        "doc_refs": DOC_REFS,
        "safe_next_action": _safe_next_action(status, blocker_codes, needs_attention_codes),
        "authority_boundary": _authority_boundary(),
        "not_authorized_actions": [
            "create_openai_app_draft",
            "submit_app_for_review",
            "publish_app",
            "call_openai_dashboard_or_api",
            "read_tokens_or_cookies",
            "read_provider_config",
            "release_or_deploy",
        ],
    }


def init_submission_evidence_scaffold(
    project_root: str,
    *,
    app_name: str = "ColaMeta",
    app_description: str = "Project console for local AI engineering workflows.",
    company_url: str = "https://example.com",
    privacy_policy_url: str = "https://example.com/privacy",
    now: datetime | None = None,
) -> dict[str, Any]:
    root = os.path.abspath(os.path.expanduser(project_root))
    manifest_rel_path = DEFAULT_SUBMISSION_MATERIALS_REL_PATH
    manifest_path = os.path.join(root, manifest_rel_path)
    created_files: list[str] = []
    existing_files: list[str] = []

    for rel_path, content in _submission_evidence_placeholder_files().items():
        abs_path = os.path.join(root, rel_path)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        if os.path.exists(abs_path):
            existing_files.append(rel_path)
            continue
        with open(abs_path, "w", encoding="utf-8") as handle:
            handle.write(content)
        created_files.append(rel_path)

    os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
    if os.path.exists(manifest_path):
        existing_files.append(manifest_rel_path)
        manifest_created = False
    else:
        with open(manifest_path, "w", encoding="utf-8") as handle:
            json.dump(
                _submission_materials_scaffold_manifest(
                    app_name=app_name,
                    app_description=app_description,
                    company_url=company_url,
                    privacy_policy_url=privacy_policy_url,
                ),
                handle,
                ensure_ascii=False,
                indent=2,
            )
            handle.write("\n")
        created_files.append(manifest_rel_path)
        manifest_created = True

    return {
        "ok": True,
        "source": SUBMISSION_EVIDENCE_SCAFFOLD_SOURCE,
        "schema_version": SUBMISSION_EVIDENCE_SCAFFOLD_VERSION,
        "project_root": root,
        "observed_at": _iso_now(now),
        "manifest_path": manifest_rel_path,
        "manifest_created": manifest_created,
        "created_files": sorted(created_files),
        "existing_files": sorted(existing_files),
        "ready_fields_default": False,
        "placeholder_suffix": ".todo.md",
        "next_step": {
            "tool": "release-readiness",
            "arguments": {"project_path": root, "json": True},
            "why": "Fill real evidence, replace .todo.md refs, then mark the corresponding manifest fields true.",
        },
    }


def _submission_evidence_keys_from_entries(entries: Any) -> list[str]:
    if not isinstance(entries, list):
        return []
    keys: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        key = entry.get("key")
        normalized = key.strip() if isinstance(key, str) else ""
        if normalized not in SUBMISSION_EVIDENCE_READY_FIELD_BY_KEY or normalized in seen:
            continue
        seen.add(normalized)
        keys.append(normalized)
    return keys


def _submission_evidence_safe_recovery_actions(*, selected_keys: Any = None) -> list[dict[str, Any]]:
    keys = [
        key
        for key in (selected_keys if isinstance(selected_keys, list) else [])
        if isinstance(key, str) and key in SUBMISSION_EVIDENCE_READY_FIELD_BY_KEY
    ]
    preview_arguments: dict[str, Any] = {}
    if keys:
        preview_arguments["selected_keys"] = sorted(set(keys))
    boundary = {
        "read_only": True,
        "side_effects": False,
        "does_not_write_files": True,
        "does_not_mark_ready_fields": True,
    }
    return [
        {
            "tool": "get_release_submission_readiness",
            "arguments": {},
            "required_scope": "mcp:read",
            "side_effects": False,
            "authority_boundary": boundary,
            "why": "Refresh current submission evidence status before trying another commit-scoped evidence action.",
        },
        {
            "tool": "get_submission_evidence_fill_preview",
            "arguments": preview_arguments,
            "required_scope": "mcp:read",
            "side_effects": False,
            "authority_boundary": boundary,
            "why": "Regenerate the bounded fill or mark-ready payload instead of editing a failed commit call by hand.",
        },
    ]


def fill_submission_evidence_files(
    project_root: str,
    *,
    entries: list[dict[str, Any]],
    mark_ready: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    root = os.path.abspath(os.path.expanduser(project_root))
    manifest_rel_path = DEFAULT_SUBMISSION_MATERIALS_REL_PATH
    manifest_path = os.path.join(root, manifest_rel_path)
    manifest, load_error = load_submission_materials_file(manifest_path)
    if manifest is None:
        return {
            "ok": False,
            "source": SUBMISSION_EVIDENCE_FILL_SOURCE,
            "schema_version": SUBMISSION_EVIDENCE_FILL_VERSION,
            "project_root": root,
            "observed_at": _iso_now(now),
            "error_code": str((load_error or {}).get("error_code") or "SUBMISSION_MATERIALS_FILE_NOT_FOUND"),
            "message": "Submission materials manifest must exist and be valid before evidence files can be filled.",
            "details": {"manifest_path": manifest_rel_path, **(load_error or {})},
            "safe_recovery_actions": _submission_evidence_safe_recovery_actions(),
        }

    evidence_raw = manifest.get("evidence")
    evidence = dict(evidence_raw) if isinstance(evidence_raw, dict) else {}
    planned, validation_errors = _plan_submission_evidence_file_writes(root, entries)
    if mark_ready and not validation_errors:
        for item in planned:
            reason_codes = _submission_evidence_unfinished_content_reason_codes(str(item.get("content") or ""))
            if reason_codes:
                validation_errors.append(
                    {
                        "key": item.get("key"),
                        "ref": item.get("rel_path"),
                        "error_code": SUBMISSION_EVIDENCE_CONTENT_REVIEW_REQUIRED,
                        "reason_codes": reason_codes,
                    }
                )
        if not validation_errors:
            planned_refs_by_key: dict[str, set[str]] = {}
            for item in planned:
                planned_refs_by_key.setdefault(str(item["key"]), set()).add(str(item["rel_path"]))
            for evidence_key, planned_refs in planned_refs_by_key.items():
                retained_refs = [
                    ref
                    for ref in _coerce_evidence_refs(evidence.get(evidence_key))
                    if not _is_placeholder_evidence_ref(ref) and ref not in planned_refs
                ]
                if retained_refs:
                    ref_errors, _ = _validate_ready_evidence_refs(root, evidence_key, retained_refs)
                    validation_errors.extend(ref_errors)
    if validation_errors:
        return {
            "ok": False,
            "source": SUBMISSION_EVIDENCE_FILL_SOURCE,
            "schema_version": SUBMISSION_EVIDENCE_FILL_VERSION,
            "project_root": root,
            "observed_at": _iso_now(now),
            "error_code": "SUBMISSION_EVIDENCE_INPUT_INVALID",
            "message": (
                "Submission evidence input is invalid or explicitly unfinished; no files were written or marked ready."
            ),
            "validation_errors": validation_errors,
            "safe_recovery_actions": _submission_evidence_safe_recovery_actions(
                selected_keys=_submission_evidence_keys_from_entries(entries),
            ),
        }

    created_files: list[str] = []
    existing_files: list[str] = []
    grouped_refs: dict[str, list[str]] = {}
    for item in planned:
        rel_path = item["rel_path"]
        abs_path = item["abs_path"]
        if os.path.isfile(abs_path):
            existing_files.append(rel_path)
        else:
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            with open(abs_path, "w", encoding="utf-8") as handle:
                handle.write(item["content"])
                if not item["content"].endswith("\n"):
                    handle.write("\n")
            created_files.append(rel_path)
        grouped_refs.setdefault(item["key"], []).append(rel_path)

    ready_fields_marked: list[str] = []
    updated_evidence_keys: list[str] = []
    for evidence_key, refs in sorted(grouped_refs.items()):
        existing_real_refs = [
            ref
            for ref in _coerce_evidence_refs(evidence.get(evidence_key))
            if not _is_placeholder_evidence_ref(ref)
        ]
        merged_refs = _dedupe_preserve_order(existing_real_refs + refs)
        evidence[evidence_key] = merged_refs if evidence_key == "screenshots" or len(merged_refs) > 1 else merged_refs[0]
        updated_evidence_keys.append(evidence_key)
        ready_field = SUBMISSION_EVIDENCE_READY_FIELD_BY_KEY[evidence_key]
        if mark_ready:
            manifest[ready_field] = True
            ready_fields_marked.append(ready_field)

    manifest["evidence"] = evidence
    manifest["notes"] = (
        "Submission evidence files were filled locally. Keep each ready field false until the referenced evidence "
        "has been reviewed by a human operator."
        if not mark_ready
        else "Submission evidence files were filled locally and requested ready fields were marked true."
    )
    os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    changed_files = sorted(set(created_files + [manifest_rel_path]))
    return {
        "ok": True,
        "source": SUBMISSION_EVIDENCE_FILL_SOURCE,
        "schema_version": SUBMISSION_EVIDENCE_FILL_VERSION,
        "project_root": root,
        "observed_at": _iso_now(now),
        "manifest_path": manifest_rel_path,
        "created_files": sorted(created_files),
        "existing_files": sorted(existing_files),
        "changed_files": changed_files,
        "updated_evidence_keys": sorted(updated_evidence_keys),
        "ready_fields_marked": sorted(ready_fields_marked),
        "mark_ready": bool(mark_ready),
        "next_step": {
            "tool": "get_release_submission_readiness",
            "arguments": {"project_path": root},
            "why": "Review submission readiness; only mark remaining ready fields true after human evidence review.",
        },
    }


def mark_submission_evidence_ready_fields(
    project_root: str,
    *,
    keys: list[str],
    review_confirmation: str,
    now: datetime | None = None,
    update_notes: bool = True,
    expected_manifest_sha256: str | None = None,
    expected_ref_sha256_by_key: Mapping[str, Mapping[str, str]] | None = None,
) -> dict[str, Any]:
    root = os.path.abspath(os.path.expanduser(project_root))
    manifest_rel_path = DEFAULT_SUBMISSION_MATERIALS_REL_PATH
    manifest_path = os.path.join(root, manifest_rel_path)
    manifest_preimage_text: str | None = None
    if expected_manifest_sha256:
        try:
            with open(manifest_path, "rb") as handle:
                manifest_preimage_bytes = handle.read(RELEASE_SUBMISSION_MATERIALS_MAX_BYTES + 1)
            if len(manifest_preimage_bytes) > RELEASE_SUBMISSION_MATERIALS_MAX_BYTES:
                raise ValueError("submission materials manifest exceeds the size limit")
            manifest_preimage_text = manifest_preimage_bytes.decode("utf-8")
            manifest = json.loads(manifest_preimage_text)
            load_error = None if isinstance(manifest, dict) else {"error_code": "SUBMISSION_MATERIALS_SCHEMA_INVALID"}
            if not isinstance(manifest, dict):
                manifest = None
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            manifest = None
            load_error = {"error_code": "SUBMISSION_MATERIALS_READ_FAILED", "error_type": exc.__class__.__name__}
        if manifest is not None and hashlib.sha256(manifest_preimage_bytes).hexdigest() != expected_manifest_sha256:
            return {
                "ok": False,
                "source": SUBMISSION_EVIDENCE_MARK_READY_SOURCE,
                "schema_version": SUBMISSION_EVIDENCE_MARK_READY_VERSION,
                "project_root": root,
                "observed_at": _iso_now(now),
                "error_code": "SUBMISSION_EVIDENCE_MANIFEST_CHANGED",
                "message": "Submission materials changed after ready review; no ready fields were changed.",
                "safe_recovery_actions": _submission_evidence_safe_recovery_actions(selected_keys=keys),
            }
    else:
        manifest, load_error = load_submission_materials_file(manifest_path)
    if manifest is None:
        return {
            "ok": False,
            "source": SUBMISSION_EVIDENCE_MARK_READY_SOURCE,
            "schema_version": SUBMISSION_EVIDENCE_MARK_READY_VERSION,
            "project_root": root,
            "observed_at": _iso_now(now),
            "error_code": str((load_error or {}).get("error_code") or "SUBMISSION_MATERIALS_FILE_NOT_FOUND"),
            "message": "Submission materials manifest must exist and be valid before evidence can be marked ready.",
            "details": {"manifest_path": manifest_rel_path, **(load_error or {})},
            "safe_recovery_actions": _submission_evidence_safe_recovery_actions(),
        }
    if review_confirmation != SUBMISSION_EVIDENCE_REVIEW_CONFIRMATION:
        return {
            "ok": False,
            "source": SUBMISSION_EVIDENCE_MARK_READY_SOURCE,
            "schema_version": SUBMISSION_EVIDENCE_MARK_READY_VERSION,
            "project_root": root,
            "observed_at": _iso_now(now),
            "error_code": "SUBMISSION_EVIDENCE_REVIEW_CONFIRMATION_REQUIRED",
            "message": f"Set review_confirmation to {SUBMISSION_EVIDENCE_REVIEW_CONFIRMATION!r} after human review.",
            "safe_recovery_actions": _submission_evidence_safe_recovery_actions(selected_keys=keys),
        }
    normalized_keys, validation_errors = _validate_submission_evidence_ready_keys(keys)
    if validation_errors:
        return {
            "ok": False,
            "source": SUBMISSION_EVIDENCE_MARK_READY_SOURCE,
            "schema_version": SUBMISSION_EVIDENCE_MARK_READY_VERSION,
            "project_root": root,
            "observed_at": _iso_now(now),
            "error_code": "SUBMISSION_EVIDENCE_READY_KEYS_INVALID",
            "message": "Submission evidence ready keys are invalid; no ready fields were changed.",
            "validation_errors": validation_errors,
            "safe_recovery_actions": _submission_evidence_safe_recovery_actions(selected_keys=keys),
        }

    evidence = manifest.get("evidence")
    if not isinstance(evidence, Mapping):
        evidence = {}
    proof_errors: list[dict[str, Any]] = []
    ready_fields_marked: list[str] = []
    already_ready_fields: list[str] = []
    reviewed_refs_by_key: list[dict[str, Any]] = []
    for key in normalized_keys:
        refs = _coerce_evidence_refs(evidence.get(key))
        expected_ref_digests = None
        if isinstance(expected_ref_sha256_by_key, Mapping):
            candidate_digests = expected_ref_sha256_by_key.get(key)
            if not isinstance(candidate_digests, Mapping):
                proof_errors.append(
                    {
                        "key": key,
                        "error_code": "SUBMISSION_EVIDENCE_REVIEWED_DIGESTS_REQUIRED",
                    }
                )
                continue
            expected_ref_digests = candidate_digests
        ref_errors, reviewed_refs = _validate_ready_evidence_refs(
            root,
            key,
            refs,
            expected_sha256_by_ref=expected_ref_digests,
        )
        proof_errors.extend(ref_errors)
        if ref_errors:
            continue
        reviewed_refs_by_key.append({"key": key, "refs": reviewed_refs})
        ready_field = SUBMISSION_EVIDENCE_READY_FIELD_BY_KEY[key]
        if manifest.get(ready_field) is True:
            already_ready_fields.append(ready_field)
        else:
            manifest[ready_field] = True
            ready_fields_marked.append(ready_field)

    if proof_errors:
        return {
            "ok": False,
            "source": SUBMISSION_EVIDENCE_MARK_READY_SOURCE,
            "schema_version": SUBMISSION_EVIDENCE_MARK_READY_VERSION,
            "project_root": root,
            "observed_at": _iso_now(now),
            "error_code": "SUBMISSION_EVIDENCE_READY_PROOF_INVALID",
            "message": (
                "Every selected evidence key must reference present non-placeholder files whose content does not "
                "explicitly declare draft, pending review, missing final assets, unconfirmed permissions, or coverage gaps."
            ),
            "validation_errors": proof_errors,
            "safe_recovery_actions": _submission_evidence_safe_recovery_actions(selected_keys=normalized_keys),
        }

    if update_notes:
        manifest["notes"] = (
            "Submission evidence ready fields were marked after human review. "
            "Re-run release readiness before Dashboard submission."
        )
    manifest_text = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    transaction = FileTransaction(root, label="mark_submission_evidence_ready_fields")
    transaction.write_text(manifest_rel_path, manifest_text)
    try:
        transaction_receipt = transaction.commit()
    except FileTransactionError as exc:
        return {
            "ok": False,
            "source": SUBMISSION_EVIDENCE_MARK_READY_SOURCE,
            "schema_version": SUBMISSION_EVIDENCE_MARK_READY_VERSION,
            "project_root": root,
            "observed_at": _iso_now(now),
            "error_code": "SUBMISSION_EVIDENCE_READY_TRANSACTION_FAILED",
            "message": str(exc),
            "transaction_receipt": exc.receipt,
            "safe_recovery_actions": _submission_evidence_safe_recovery_actions(selected_keys=normalized_keys),
        }

    if expected_ref_sha256_by_key:
        post_write_errors: list[dict[str, Any]] = []
        for key in normalized_keys:
            expected_ref_digests = expected_ref_sha256_by_key.get(key)
            refs = _coerce_evidence_refs(evidence.get(key))
            ref_errors, _ = _validate_ready_evidence_refs(
                root,
                key,
                refs,
                expected_sha256_by_ref=expected_ref_digests if isinstance(expected_ref_digests, Mapping) else None,
            )
            post_write_errors.extend(ref_errors)
        if post_write_errors:
            rollback_receipt: dict[str, Any] | None = None
            if manifest_preimage_text is not None:
                rollback = FileTransaction(root, label="mark_submission_evidence_ready_fields.rollback")
                rollback.write_text(manifest_rel_path, manifest_preimage_text)
                try:
                    rollback_receipt = rollback.commit()
                except FileTransactionError as exc:
                    rollback_receipt = exc.receipt
            return {
                "ok": False,
                "source": SUBMISSION_EVIDENCE_MARK_READY_SOURCE,
                "schema_version": SUBMISSION_EVIDENCE_MARK_READY_VERSION,
                "project_root": root,
                "observed_at": _iso_now(now),
                "error_code": "SUBMISSION_EVIDENCE_REVIEWED_CONTENT_CHANGED_DURING_WRITE",
                "message": "Reviewed evidence changed during the ready write; the manifest write was rolled back.",
                "validation_errors": post_write_errors,
                "ready_fields_marked": [],
                "transaction_receipt": transaction_receipt,
                "rollback_receipt": rollback_receipt,
                "safe_recovery_actions": _submission_evidence_safe_recovery_actions(selected_keys=normalized_keys),
            }

    return {
        "ok": True,
        "source": SUBMISSION_EVIDENCE_MARK_READY_SOURCE,
        "schema_version": SUBMISSION_EVIDENCE_MARK_READY_VERSION,
        "project_root": root,
        "observed_at": _iso_now(now),
        "manifest_path": manifest_rel_path,
        "changed_files": [manifest_rel_path] if ready_fields_marked else [],
        "selected_keys": normalized_keys,
        "ready_fields_marked": sorted(ready_fields_marked),
        "already_ready_fields": sorted(already_ready_fields),
        "review_confirmation": review_confirmation,
        "notes_updated": update_notes,
        "expected_digests_enforced": bool(expected_manifest_sha256 or expected_ref_sha256_by_key),
        "reviewed_refs_by_key": reviewed_refs_by_key,
        "next_step": {
            "tool": "get_release_submission_readiness",
            "arguments": {"project_path": root},
            "why": "Confirm submission readiness after marking reviewed evidence fields ready.",
        },
        "transaction_receipt": transaction_receipt,
    }


def _checks(
    *,
    readiness: dict[str, Any],
    app_name: str | None,
    app_description: str | None,
    company_url: str | None,
    privacy_policy_url: str | None,
    logo_ready: bool,
    screenshots_ready: bool,
    test_prompts_ready: bool,
    test_responses_ready: bool,
    localization_ready: bool,
    mcp_tool_info_ready: bool,
    app_management_permissions_confirmed: bool,
    security_review_ready: bool,
    metadata_snapshot_reviewed: bool,
    submission_confirmations_ready: bool,
    submission_materials: dict[str, Any],
    evidence_references: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    ops_check = readiness.get("ops_check") if isinstance(readiness.get("ops_check"), dict) else {}
    return {
        "product_readiness": _status_check(
            READY if readiness.get("ready") is True else BLOCKED,
            "PRODUCT_READINESS_READY" if readiness.get("ready") is True else "PRODUCT_READINESS_NOT_READY",
            evidence={"status": readiness.get("status"), "primary_blocker": readiness.get("primary_blocker")},
        ),
        "public_mcp_endpoint": _status_check(
            READY if ops_check.get("ops_check_ready") is True else BLOCKED,
            "PUBLIC_MCP_ENDPOINT_READY"
            if ops_check.get("ops_check_ready") is True
            else "PUBLIC_MCP_ENDPOINT_NOT_READY",
        ),
        "apps_connector_smoke": _status_check(
            READY if ops_check.get("connector_smoke_ready") is True else NEEDS_ATTENTION,
            "APPS_CONNECTOR_SMOKE_READY"
            if ops_check.get("connector_smoke_ready") is True
            else "APPS_CONNECTOR_SMOKE_MISSING",
        ),
        "submission_form_assets": _materials_check(
            {
                "app_name": _has_text(app_name),
                "app_description": _has_text(app_description),
                "company_url": _is_https_url(company_url),
                "privacy_policy_url": _is_https_url(privacy_policy_url),
                "logo_ready": bool(logo_ready),
                "screenshots_ready": bool(screenshots_ready),
                "localization_ready": bool(localization_ready),
            }
        ),
        "mcp_tool_information": _status_check(
            READY if mcp_tool_info_ready else NEEDS_ATTENTION,
            "MCP_TOOL_INFORMATION_READY" if mcp_tool_info_ready else "MCP_TOOL_INFORMATION_MISSING",
        ),
        "testing_evidence": _materials_check(
            {
                "test_prompts_ready": bool(test_prompts_ready),
                "test_responses_ready": bool(test_responses_ready),
            }
        ),
        "security_privacy": _status_check(
            READY if security_review_ready and _is_https_url(privacy_policy_url) else NEEDS_ATTENTION,
            "SECURITY_PRIVACY_READY" if security_review_ready and _is_https_url(privacy_policy_url) else "SECURITY_PRIVACY_INCOMPLETE",
        ),
        "app_management_permissions": _status_check(
            READY if app_management_permissions_confirmed else NEEDS_ATTENTION,
            "APP_MANAGEMENT_PERMISSIONS_CONFIRMED"
            if app_management_permissions_confirmed
            else "APP_MANAGEMENT_PERMISSIONS_UNCONFIRMED",
        ),
        "metadata_snapshot": _status_check(
            READY if metadata_snapshot_reviewed else NEEDS_ATTENTION,
            "METADATA_SNAPSHOT_REVIEWED" if metadata_snapshot_reviewed else "METADATA_SNAPSHOT_NOT_REVIEWED",
        ),
        "submission_confirmations": _status_check(
            READY if submission_confirmations_ready else NEEDS_ATTENTION,
            "SUBMISSION_CONFIRMATIONS_READY" if submission_confirmations_ready else "SUBMISSION_CONFIRMATIONS_MISSING",
        ),
        "submission_materials_manifest": _manifest_check(submission_materials),
        "submission_evidence_references": evidence_references,
    }


def _materials_check(materials: dict[str, bool]) -> dict[str, Any]:
    missing = [name for name, present in materials.items() if not present]
    return {
        "status": READY if not missing else NEEDS_ATTENTION,
        "reason_codes": ["MATERIALS_READY"] if not missing else ["SUBMISSION_MATERIALS_MISSING"],
        "missing": missing,
        "present": [name for name, present in materials.items() if present],
    }


def _status_check(status: str, reason_code: str, *, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"status": status, "reason_codes": [reason_code]}
    if evidence is not None:
        payload["evidence"] = evidence
    return payload


def _manifest_check(submission_materials: dict[str, Any]) -> dict[str, Any]:
    error = submission_materials.get("error")
    if isinstance(error, dict):
        return {
            "status": NEEDS_ATTENTION,
            "reason_codes": ["SUBMISSION_MATERIALS_MANIFEST_INVALID"],
            "error": error,
        }
    ignored = submission_materials.get("ignored_manifest_fields")
    if isinstance(ignored, list) and ignored:
        return {
            "status": NEEDS_ATTENTION,
            "reason_codes": ["SUBMISSION_MATERIALS_MANIFEST_HAS_UNKNOWN_FIELDS"],
            "ignored_fields": ignored,
        }
    if submission_materials.get("source") == "parameters_only":
        return _status_check(
            READY,
            "SUBMISSION_MATERIALS_FROM_PARAMETERS",
            evidence={"source": "parameters_only"},
        )
    return _status_check(
        READY,
        "SUBMISSION_MATERIALS_MANIFEST_ACCEPTED",
        evidence={
            "schema_version": submission_materials.get("schema_version"),
            "manifest_fields": submission_materials.get("manifest_fields"),
        },
    )


def _merge_submission_materials(
    submission_materials: Mapping[str, Any] | None,
    *,
    app_name: str | None,
    app_description: str | None,
    company_url: str | None,
    privacy_policy_url: str | None,
    logo_ready: bool,
    screenshots_ready: bool,
    test_prompts_ready: bool,
    test_responses_ready: bool,
    localization_ready: bool,
    mcp_tool_info_ready: bool,
    app_management_permissions_confirmed: bool,
    security_review_ready: bool,
    metadata_snapshot_reviewed: bool,
    submission_confirmations_ready: bool,
    manifest_source: dict[str, Any] | None = None,
    manifest_error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    manifest = submission_materials if isinstance(submission_materials, Mapping) else {}
    parameter_values = {
        "app_name": app_name,
        "app_description": app_description,
        "company_url": company_url,
        "privacy_policy_url": privacy_policy_url,
        "logo_ready": logo_ready,
        "screenshots_ready": screenshots_ready,
        "test_prompts_ready": test_prompts_ready,
        "test_responses_ready": test_responses_ready,
        "localization_ready": localization_ready,
        "mcp_tool_info_ready": mcp_tool_info_ready,
        "app_management_permissions_confirmed": app_management_permissions_confirmed,
        "security_review_ready": security_review_ready,
        "metadata_snapshot_reviewed": metadata_snapshot_reviewed,
        "submission_confirmations_ready": submission_confirmations_ready,
    }
    effective: dict[str, Any] = {}
    parameter_fields: list[str] = []

    for field in sorted(SUBMISSION_MATERIAL_TEXT_FIELDS):
        parameter_value = parameter_values[field]
        if _has_text(parameter_value if isinstance(parameter_value, str) else None):
            effective[field] = parameter_value
            parameter_fields.append(field)
        else:
            effective[field] = _text_from_manifest(manifest, field)

    for field in sorted(SUBMISSION_MATERIAL_BOOL_FIELDS):
        parameter_value = bool(parameter_values[field])
        if parameter_value:
            effective[field] = True
            parameter_fields.append(field)
        else:
            effective[field] = _bool_from_manifest(manifest, field)

    manifest_fields = sorted(str(key) for key in manifest if str(key) in SUBMISSION_MATERIAL_FIELDS)
    ignored_manifest_fields = sorted(str(key) for key in manifest if str(key) not in SUBMISSION_MATERIAL_FIELDS)
    effective_fields = sorted(
        field
        for field in sorted(SUBMISSION_MATERIAL_TEXT_FIELDS | SUBMISSION_MATERIAL_BOOL_FIELDS)
        if _material_field_present(field, effective.get(field))
    )
    source_base = str((manifest_source or {}).get("source") or "manifest")
    source = (
        f"{source_base}_and_parameters"
        if manifest and parameter_fields
        else source_base
        if manifest
        else "parameters_only"
    )
    manifest_summary = {
        "source": source,
        "schema_version": _text_from_manifest(manifest, "schema_version"),
        "manifest_fields": manifest_fields,
        "parameter_fields": sorted(parameter_fields),
        "effective_fields": effective_fields,
        "ignored_manifest_fields": ignored_manifest_fields,
    }
    if manifest_source:
        manifest_summary["source_detail"] = dict(manifest_source)
    if manifest_error:
        manifest_summary["error"] = dict(manifest_error)
    evidence = manifest.get("evidence")
    if isinstance(evidence, Mapping):
        manifest_summary["evidence_keys"] = sorted(str(key) for key in evidence)
        effective["_evidence"] = evidence
    else:
        manifest_summary["evidence_keys"] = []
        effective["_evidence"] = {}
    effective["manifest"] = manifest_summary
    return effective


def _evidence_references_check(project_root: str, materials: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    if isinstance(manifest.get("error"), dict):
        return _status_check(READY, "SUBMISSION_EVIDENCE_SKIPPED_MANIFEST_INVALID")
    if manifest.get("source") == "parameters_only":
        return _status_check(READY, "SUBMISSION_EVIDENCE_FROM_OPERATOR_PARAMETERS")

    evidence = materials.get("_evidence")
    if not isinstance(evidence, Mapping):
        evidence = {}
    required_keys = [
        evidence_key for ready_field, evidence_key in sorted(SUBMISSION_EVIDENCE_REQUIREMENTS.items()) if materials.get(ready_field) is True
    ]
    missing_keys: list[str] = []
    invalid_refs: list[dict[str, str]] = []
    missing_files: list[str] = []
    missing_files_by_key: list[dict[str, str]] = []
    placeholder_files: list[str] = []
    placeholder_files_by_key: list[dict[str, str]] = []
    content_review_files: list[str] = []
    content_review_files_by_key: list[dict[str, Any]] = []
    present_files: list[str] = []

    for evidence_key in required_keys:
        refs = _coerce_evidence_refs(evidence.get(evidence_key))
        if not refs:
            missing_keys.append(evidence_key)
            continue
        for ref in refs:
            state = _submission_evidence_ref_state(project_root, ref)
            rel_path = str(state.get("ref") or ref)
            state_status = str(state.get("status") or "invalid")
            if state_status == "invalid":
                invalid_refs.append(
                    {
                        "key": evidence_key,
                        "ref": ref,
                        "error_code": str(state.get("error_code") or "EVIDENCE_REF_INVALID"),
                    }
                )
            elif state_status == "missing":
                missing_files.append(rel_path)
                missing_files_by_key.append({"key": evidence_key, "ref": rel_path})
            elif state_status == "placeholder":
                placeholder_files.append(rel_path)
                placeholder_files_by_key.append({"key": evidence_key, "ref": rel_path})
            elif state_status == "review_required":
                content_review_files.append(rel_path)
                content_review_files_by_key.append(
                    {
                        "key": evidence_key,
                        "ref": rel_path,
                        "reason_codes": list(state.get("reason_codes") or []),
                    }
                )
            else:
                present_files.append(rel_path)

    structural_incomplete = bool(missing_keys or invalid_refs or missing_files or placeholder_files)
    if structural_incomplete or content_review_files:
        incomplete_keys = _dedupe_preserve_order(
            sorted(set(missing_keys))
            + [item["key"] for item in invalid_refs]
            + [item["key"] for item in missing_files_by_key]
            + [item["key"] for item in placeholder_files_by_key]
            + [item["key"] for item in content_review_files_by_key]
        )
        reason_codes: list[str] = []
        if structural_incomplete:
            reason_codes.append("SUBMISSION_EVIDENCE_REFERENCES_INCOMPLETE")
        if content_review_files:
            reason_codes.append(SUBMISSION_EVIDENCE_CONTENT_REVIEW_REQUIRED)
        return {
            "status": NEEDS_ATTENTION,
            "reason_codes": reason_codes,
            "required_keys": required_keys,
            "incomplete_keys": incomplete_keys,
            "missing_keys": sorted(set(missing_keys)),
            "invalid_refs": invalid_refs,
            "missing_files": sorted(set(missing_files)),
            "missing_files_by_key": missing_files_by_key,
            "placeholder_files": sorted(set(placeholder_files)),
            "placeholder_files_by_key": placeholder_files_by_key,
            "content_review_files": sorted(set(content_review_files)),
            "content_review_files_by_key": content_review_files_by_key,
            "present_files": sorted(set(present_files)),
            "fill_entry_templates": _submission_evidence_entry_templates_for(incomplete_keys),
        }
    return {
        "status": READY,
        "reason_codes": ["SUBMISSION_EVIDENCE_REFERENCES_READY"],
        "required_keys": required_keys,
        "incomplete_keys": [],
        "content_review_files": [],
        "content_review_files_by_key": [],
        "present_files": sorted(set(present_files)),
        "fill_entry_templates": [],
    }


def _submission_evidence_progress(project_root: str, materials: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    evidence = materials.get("_evidence")
    if not isinstance(evidence, Mapping):
        evidence = {}
    rows: list[dict[str, Any]] = []
    counts = {
        "ready": 0,
        "needs_attention": 0,
        "filled_not_marked_ready": 0,
        "review_required": 0,
        "placeholder": 0,
        "not_started": 0,
    }
    for evidence_key in SUBMISSION_EVIDENCE_DEFAULT_OUTPUT_REFS:
        ready_field = SUBMISSION_EVIDENCE_READY_FIELD_BY_KEY[evidence_key]
        refs = _coerce_evidence_refs(evidence.get(evidence_key))
        file_states = [_submission_evidence_ref_state(project_root, ref) for ref in refs]
        ready_field_value = materials.get(ready_field) is True
        status = _submission_evidence_progress_status(ready_field_value, refs, file_states)
        counts[status] = counts.get(status, 0) + 1
        template = _submission_evidence_entry_templates_for([evidence_key])[0]
        rows.append(
            {
                "key": evidence_key,
                "ready_field": ready_field,
                "ready": ready_field_value,
                "status": status,
                "refs": refs,
                "file_states": file_states,
                "default_path": SUBMISSION_EVIDENCE_DEFAULT_OUTPUT_REFS[evidence_key],
                "template": template,
                "next_action": _submission_evidence_row_next_action(status, template),
            }
        )
    total = len(rows)
    complete = counts["ready"]
    return {
        "source": "submission_evidence_progress",
        "schema_version": "submission_evidence_progress.v1",
        "status": "ready" if complete == total else "needs_attention",
        "complete_count": complete,
        "total_count": total,
        "counts": counts,
        "rows": rows,
        "manifest_source": manifest.get("source") if isinstance(manifest, dict) else "unknown",
        "manifest_available": manifest.get("source") not in {"parameters_only", None} if isinstance(manifest, dict) else False,
        "read_only": True,
        "side_effects": False,
    }


def _submission_evidence_ref_state(
    project_root: str,
    ref: str,
    *,
    include_sha256: bool = False,
) -> dict[str, Any]:
    normalized = _normalize_evidence_ref(project_root, ref)
    if normalized.get("ok") is not True:
        return {
            "ref": ref,
            "status": "invalid",
            "error_code": str(normalized.get("error_code") or "EVIDENCE_REF_INVALID"),
        }
    rel_path = str(normalized["rel_path"])
    if not os.path.isfile(str(normalized["abs_path"])):
        return {"ref": rel_path, "status": "missing"}
    if _is_placeholder_evidence_ref(rel_path):
        return {"ref": rel_path, "status": "placeholder"}
    current_sha256 = ""
    if rel_path.lower().endswith((".md", ".markdown")):
        path_error = _submission_evidence_markdown_path_error(
            project_root,
            rel_path,
            str(normalized["abs_path"]),
        )
        if path_error:
            return {
                "ref": rel_path,
                "status": "invalid",
                "error_code": path_error,
                "allowed_root": SUBMISSION_EVIDENCE_CONTENT_ROOT,
            }
        try:
            with open(str(normalized["abs_path"]), "rb") as handle:
                content_bytes = handle.read(SUBMISSION_EVIDENCE_CONTENT_MAX_BYTES + 1)
        except OSError as exc:
            return {
                "ref": rel_path,
                "status": "invalid",
                "error_code": "SUBMISSION_EVIDENCE_FILE_UNREADABLE",
                "error_type": exc.__class__.__name__,
            }
        if len(content_bytes) > SUBMISSION_EVIDENCE_CONTENT_MAX_BYTES:
            return {
                "ref": rel_path,
                "status": "invalid",
                "error_code": "SUBMISSION_EVIDENCE_CONTENT_TOO_LARGE",
                "max_bytes": SUBMISSION_EVIDENCE_CONTENT_MAX_BYTES,
                "actual_bytes_at_least": len(content_bytes),
            }
        try:
            content = content_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            return {
                "ref": rel_path,
                "status": "invalid",
                "error_code": "SUBMISSION_EVIDENCE_FILE_UNREADABLE",
                "error_type": exc.__class__.__name__,
            }
        current_sha256 = hashlib.sha256(content_bytes).hexdigest()
        reason_codes = _submission_evidence_unfinished_content_reason_codes(content)
        if reason_codes:
            return {
                "ref": rel_path,
                "status": "review_required",
                "reason_codes": reason_codes,
                **({"current_sha256": current_sha256} if include_sha256 else {}),
            }
    result = {"ref": rel_path, "status": "present"}
    if include_sha256 and current_sha256:
        result["current_sha256"] = current_sha256
    return result


def _submission_evidence_markdown_path_error(project_root: str, rel_path: str, abs_path: str) -> str | None:
    if not rel_path.startswith(SUBMISSION_EVIDENCE_CONTENT_ROOT):
        return "SUBMISSION_EVIDENCE_CONTENT_PATH_NOT_ALLOWED"
    expected_real_path = os.path.abspath(os.path.join(os.path.realpath(project_root), rel_path))
    if os.path.realpath(abs_path) != expected_real_path:
        return "SUBMISSION_EVIDENCE_SYMLINK_NOT_ALLOWED"
    return None


def _submission_evidence_unfinished_content_reason_codes(content: str) -> list[str]:
    normalized = " ".join(content.casefold().split())
    return [
        reason_code
        for reason_code, markers in SUBMISSION_EVIDENCE_UNFINISHED_CONTENT_MARKERS.items()
        if any(marker in normalized for marker in markers)
    ]


def _submission_evidence_progress_status(ready: bool, refs: list[str], file_states: list[dict[str, Any]]) -> str:
    if not refs:
        return "needs_attention" if ready else "not_started"
    state_values = {str(item.get("status") or "unknown") for item in file_states}
    has_problem = bool(state_values & {"invalid", "missing", "placeholder", "review_required"})
    has_present = "present" in state_values
    if "review_required" in state_values:
        return "review_required"
    if ready:
        return "needs_attention" if has_problem or not has_present else "ready"
    if has_present and not has_problem:
        return "filled_not_marked_ready"
    if "placeholder" in state_values:
        return "placeholder"
    return "not_started"


def _submission_evidence_row_next_action(status: str, template: dict[str, Any]) -> dict[str, Any]:
    if status == "ready":
        return {"action": "none", "why": "Evidence is present and the manifest ready field is true."}
    if status == "filled_not_marked_ready":
        return {
            "action": "review_and_mark_ready",
            "tool": "mark_submission_evidence_ready_fields",
            "mark_ready": True,
            "why": "Evidence file exists, but the manifest ready field remains false.",
        }
    if status == "review_required":
        return {
            "action": "preview_evidence_content_revision",
            "tool": "manage_submission_evidence_revision",
            "phase": "preview",
            "mark_ready": False,
            "why": (
                "The referenced file explicitly declares draft, missing-final-asset, pending-review, "
                "unconfirmed-permission, or uncovered-test state; preview a controlled revision before marking ready."
            ),
        }
    return {
        "action": "fill_submission_evidence",
        "tool": "fill_submission_evidence_files",
        "entry_shape": template.get("copyable_entry_shape"),
        "why": "Provide operator-confirmed evidence text before marking the ready field true.",
    }


def _coerce_evidence_refs(value: Any) -> list[str]:
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    if isinstance(value, list):
        refs = [item.strip() for item in value if isinstance(item, str) and item.strip()]
        return refs
    return []


def _validate_submission_evidence_ready_keys(keys: list[str]) -> tuple[list[str], list[dict[str, Any]]]:
    if not isinstance(keys, list) or not keys:
        return [], [{"index": None, "error_code": "SUBMISSION_EVIDENCE_KEYS_REQUIRED"}]
    normalized: list[str] = []
    errors: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(keys):
        key = item.strip() if isinstance(item, str) else ""
        if key not in SUBMISSION_EVIDENCE_READY_FIELD_BY_KEY:
            errors.append(
                {
                    "index": index,
                    "key": key,
                    "error_code": "SUBMISSION_EVIDENCE_KEY_INVALID",
                    "accepted_keys": sorted(SUBMISSION_EVIDENCE_READY_FIELD_BY_KEY),
                }
            )
            continue
        if key in seen:
            errors.append({"index": index, "key": key, "error_code": "SUBMISSION_EVIDENCE_KEY_DUPLICATE"})
            continue
        seen.add(key)
        normalized.append(key)
    return normalized, errors


def _validate_ready_evidence_refs(
    root: str,
    key: str,
    refs: list[str],
    *,
    expected_sha256_by_ref: Mapping[str, str] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    if not refs:
        return [{"key": key, "error_code": "SUBMISSION_EVIDENCE_REFS_REQUIRED"}], []
    errors: list[dict[str, Any]] = []
    reviewed_refs: list[str] = []
    for ref in refs:
        state = _submission_evidence_ref_state(
            root,
            ref,
            include_sha256=expected_sha256_by_ref is not None,
        )
        rel_path = str(state.get("ref") or ref)
        state_status = str(state.get("status") or "invalid")
        if state_status == "invalid":
            errors.append(
                {
                    "key": key,
                    "ref": ref,
                    "error_code": str(state.get("error_code") or "EVIDENCE_REF_INVALID"),
                }
            )
            continue
        if state_status == "placeholder":
            errors.append({"key": key, "ref": rel_path, "error_code": "SUBMISSION_EVIDENCE_PLACEHOLDER_REF"})
            continue
        if state_status == "missing":
            errors.append({"key": key, "ref": rel_path, "error_code": "SUBMISSION_EVIDENCE_FILE_MISSING"})
            continue
        if state_status == "review_required":
            errors.append(
                {
                    "key": key,
                    "ref": rel_path,
                    "error_code": SUBMISSION_EVIDENCE_CONTENT_REVIEW_REQUIRED,
                    "reason_codes": list(state.get("reason_codes") or []),
                }
            )
            continue
        if expected_sha256_by_ref is not None:
            expected_sha256 = str(expected_sha256_by_ref.get(rel_path) or "")
            current_sha256 = str(state.get("current_sha256") or "")
            if not expected_sha256 or current_sha256 != expected_sha256:
                errors.append(
                    {
                        "key": key,
                        "ref": rel_path,
                        "error_code": "SUBMISSION_EVIDENCE_REVIEWED_DIGEST_MISMATCH",
                        "expected_sha256": expected_sha256,
                        "current_sha256": current_sha256,
                    }
                )
                continue
        reviewed_refs.append(rel_path)
    return errors, reviewed_refs


def _plan_submission_evidence_file_writes(root: str, entries: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not isinstance(entries, list) or not entries:
        return [], [{"index": None, "error_code": "SUBMISSION_EVIDENCE_ENTRIES_REQUIRED"}]
    planned: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    seen_rel_paths: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append({"index": index, "error_code": "SUBMISSION_EVIDENCE_ENTRY_INVALID"})
            continue
        evidence_key_raw = entry.get("key")
        evidence_key = evidence_key_raw.strip() if isinstance(evidence_key_raw, str) else ""
        if evidence_key not in SUBMISSION_EVIDENCE_READY_FIELD_BY_KEY:
            errors.append(
                {
                    "index": index,
                    "error_code": "SUBMISSION_EVIDENCE_KEY_INVALID",
                    "key": evidence_key,
                    "accepted_keys": sorted(SUBMISSION_EVIDENCE_READY_FIELD_BY_KEY),
                }
            )
            continue
        content = entry.get("content")
        if not isinstance(content, str) or not content.strip():
            errors.append({"index": index, "key": evidence_key, "error_code": "SUBMISSION_EVIDENCE_CONTENT_REQUIRED"})
            continue
        content_bytes = len(content.encode("utf-8"))
        if content_bytes > SUBMISSION_EVIDENCE_CONTENT_MAX_BYTES:
            errors.append(
                {
                    "index": index,
                    "key": evidence_key,
                    "error_code": "SUBMISSION_EVIDENCE_CONTENT_TOO_LARGE",
                    "max_bytes": SUBMISSION_EVIDENCE_CONTENT_MAX_BYTES,
                    "actual_bytes": content_bytes,
                }
            )
            continue
        ref_raw = entry.get("filename")
        ref = ref_raw.strip() if isinstance(ref_raw, str) and ref_raw.strip() else SUBMISSION_EVIDENCE_DEFAULT_OUTPUT_REFS[evidence_key]
        normalized = _normalize_submission_evidence_output_ref(root, ref)
        if normalized.get("ok") is not True:
            errors.append({"index": index, "key": evidence_key, "ref": ref, "error_code": str(normalized.get("error_code"))})
            continue
        rel_path = str(normalized["rel_path"])
        abs_path = str(normalized["abs_path"])
        if rel_path in seen_rel_paths:
            errors.append({"index": index, "key": evidence_key, "ref": rel_path, "error_code": "SUBMISSION_EVIDENCE_DUPLICATE_FILE"})
            continue
        seen_rel_paths.add(rel_path)
        if os.path.isfile(abs_path):
            try:
                with open(abs_path, encoding="utf-8") as handle:
                    existing_content = handle.read()
            except (OSError, UnicodeDecodeError) as exc:
                errors.append(
                    {
                        "index": index,
                        "key": evidence_key,
                        "ref": rel_path,
                        "error_code": "SUBMISSION_EVIDENCE_EXISTING_FILE_UNREADABLE",
                        "error_type": exc.__class__.__name__,
                    }
                )
                continue
            if existing_content.rstrip("\n") != content.rstrip("\n"):
                errors.append(
                    {
                        "index": index,
                        "key": evidence_key,
                        "ref": rel_path,
                        "error_code": "SUBMISSION_EVIDENCE_FILE_EXISTS",
                    }
                )
                continue
        planned.append({"key": evidence_key, "rel_path": rel_path, "abs_path": abs_path, "content": content})
    return planned, errors


def _normalize_submission_evidence_output_ref(project_root: str, ref: str) -> dict[str, Any]:
    if ref.startswith(("http://", "https://")):
        return {"ok": False, "error_code": "EXTERNAL_EVIDENCE_URL_NOT_ACCEPTED"}
    candidate = ref if "/" in ref or "\\" in ref else f"docs/submission/{ref}"
    normalized = _normalize_evidence_ref(project_root, candidate)
    if normalized.get("ok") is not True:
        return normalized
    rel_path = str(normalized["rel_path"])
    if not rel_path.startswith("docs/submission/"):
        return {"ok": False, "error_code": "SUBMISSION_EVIDENCE_PATH_OUTSIDE_SUBMISSION_DIR"}
    if _is_placeholder_evidence_ref(rel_path):
        return {"ok": False, "error_code": "SUBMISSION_EVIDENCE_TODO_TARGET_NOT_ACCEPTED"}
    if not rel_path.endswith(".md"):
        return {"ok": False, "error_code": "SUBMISSION_EVIDENCE_MARKDOWN_REQUIRED"}
    path_error = _submission_evidence_markdown_path_error(project_root, rel_path, str(normalized["abs_path"]))
    if path_error:
        return {"ok": False, "error_code": path_error}
    return normalized


def _submission_evidence_entry_templates_for(keys: Any) -> list[dict[str, Any]]:
    if not isinstance(keys, list):
        return []
    templates: list[dict[str, Any]] = []
    for key in keys:
        if not isinstance(key, str) or key not in SUBMISSION_EVIDENCE_READY_FIELD_BY_KEY:
            continue
        detail = SUBMISSION_EVIDENCE_ENTRY_TEMPLATE_DETAILS.get(key, {})
        default_ref = SUBMISSION_EVIDENCE_DEFAULT_OUTPUT_REFS[key]
        templates.append(
            {
                "key": key,
                "ready_field": SUBMISSION_EVIDENCE_READY_FIELD_BY_KEY[key],
                "title": str(detail.get("title") or key),
                "default_filename": os.path.basename(default_ref),
                "default_path": default_ref,
                "purpose": str(detail.get("purpose") or ""),
                "required_sections": list(detail.get("required_sections") or []),
                "content_prompt": _submission_evidence_content_prompt(key, detail),
                "mark_ready_default": False,
                "copyable_entry_shape": {
                    "key": key,
                    "filename": os.path.basename(default_ref),
                    "content": "<operator-confirmed evidence text>",
                },
            }
        )
    return templates


def _submission_evidence_content_prompt(key: str, detail: Mapping[str, Any]) -> str:
    sections = [str(section) for section in detail.get("required_sections", []) if isinstance(section, str)]
    section_text = ", ".join(sections) if sections else "evidence notes"
    purpose = str(detail.get("purpose") or f"Record evidence for {key}.")
    return f"{purpose} Include these sections: {section_text}. Do not mark ready until a human reviewer confirms the content."


def _normalize_evidence_ref(project_root: str, ref: str) -> dict[str, Any]:
    if ref.startswith(("http://", "https://")):
        return {"ok": False, "error_code": "EXTERNAL_EVIDENCE_URL_NOT_ACCEPTED"}
    if os.path.isabs(ref):
        return {"ok": False, "error_code": "ABSOLUTE_EVIDENCE_PATH_NOT_ACCEPTED"}
    normalized_rel = os.path.normpath(ref)
    if normalized_rel == "." or normalized_rel.startswith("..") or os.path.isabs(normalized_rel):
        return {"ok": False, "error_code": "EVIDENCE_PATH_OUTSIDE_PROJECT"}
    root = os.path.abspath(os.path.expanduser(project_root))
    abs_path = os.path.abspath(os.path.join(root, normalized_rel))
    try:
        common = os.path.commonpath([root, abs_path])
    except ValueError:
        return {"ok": False, "error_code": "EVIDENCE_PATH_OUTSIDE_PROJECT"}
    if common != root:
        return {"ok": False, "error_code": "EVIDENCE_PATH_OUTSIDE_PROJECT"}
    return {"ok": True, "rel_path": normalized_rel, "abs_path": abs_path}


def _is_placeholder_evidence_ref(rel_path: str) -> bool:
    return rel_path.endswith(".todo.md")


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _submission_materials_scaffold_manifest(
    *,
    app_name: str,
    app_description: str,
    company_url: str,
    privacy_policy_url: str,
) -> dict[str, Any]:
    return {
        "schema_version": "chatgpt_app_submission_materials.v1",
        "app_name": app_name,
        "app_description": app_description,
        "company_url": company_url,
        "privacy_policy_url": privacy_policy_url,
        "logo_ready": False,
        "screenshots_ready": False,
        "test_prompts_ready": False,
        "test_responses_ready": False,
        "localization_ready": False,
        "mcp_tool_info_ready": False,
        "app_management_permissions_confirmed": False,
        "security_review_ready": False,
        "metadata_snapshot_reviewed": False,
        "submission_confirmations_ready": False,
        "evidence": dict(SUBMISSION_EVIDENCE_SCAFFOLD_REFS),
        "notes": "Replace .todo.md placeholder refs with real evidence files before marking readiness fields true.",
    }


def _submission_evidence_placeholder_files() -> dict[str, str]:
    return {
        "docs/submission/logo.todo.md": "# Logo Evidence TODO\n\nAdd the final app logo asset path and review notes here.\n",
        "docs/submission/screenshot-1.todo.md": "# Screenshot Evidence TODO\n\nAdd final ChatGPT App screenshots and captions here.\n",
        "docs/submission/test-prompts.todo.md": "# Test Prompts TODO\n\nList review prompts that exercise the app's main workflows.\n",
        "docs/submission/test-responses.todo.md": "# Test Responses TODO\n\nRecord expected tool behavior and response evidence for each test prompt.\n",
        "docs/submission/localization.todo.md": "# Localization TODO\n\nDocument supported locales and localized metadata/screenshots.\n",
        "docs/submission/mcp-tool-info.todo.md": "# MCP Tool Information TODO\n\nDocument exposed tools, descriptions, scopes, and safety boundaries.\n",
        "docs/submission/app-management-permissions.todo.md": "# App Management Permissions TODO\n\nRecord who owns Dashboard submission and app management permissions.\n",
        "docs/submission/security-review.todo.md": "# Security And Privacy Review TODO\n\nRecord least privilege, consent, redaction, and monitoring review evidence.\n",
        "docs/submission/metadata-snapshot.todo.md": "# Metadata Snapshot TODO\n\nRecord the app name, description, URLs, screenshots, and tool metadata reviewed for submission.\n",
        "docs/submission/submission-confirmations.todo.md": "# Submission Confirmations TODO\n\nRecord the final human confirmations required before Dashboard submission.\n",
    }


def default_submission_materials_path(project_root: str) -> str:
    return os.path.join(os.path.abspath(os.path.expanduser(project_root)), DEFAULT_SUBMISSION_MATERIALS_REL_PATH)


def load_submission_materials_file(path: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    resolved = os.path.abspath(os.path.expanduser(path))
    if not os.path.isfile(resolved):
        return None, {"error_code": "SUBMISSION_MATERIALS_FILE_NOT_FOUND"}
    try:
        size = os.path.getsize(resolved)
    except OSError as exc:
        return None, {"error_code": "SUBMISSION_MATERIALS_STAT_FAILED", "error_type": exc.__class__.__name__}
    if size > RELEASE_SUBMISSION_MATERIALS_MAX_BYTES:
        return None, {
            "error_code": "SUBMISSION_MATERIALS_FILE_TOO_LARGE",
            "max_bytes": RELEASE_SUBMISSION_MATERIALS_MAX_BYTES,
        }
    try:
        with open(resolved, encoding="utf-8") as handle:
            payload = json.load(handle)
    except json.JSONDecodeError as exc:
        return None, {
            "error_code": "SUBMISSION_MATERIALS_JSON_INVALID",
            "line": exc.lineno,
            "column": exc.colno,
        }
    except (OSError, UnicodeDecodeError) as exc:
        return None, {"error_code": "SUBMISSION_MATERIALS_READ_FAILED", "error_type": exc.__class__.__name__}
    if not isinstance(payload, dict):
        return None, {"error_code": "SUBMISSION_MATERIALS_SCHEMA_INVALID"}
    return payload, None


def _text_from_manifest(manifest: Mapping[str, Any], field: str) -> str | None:
    value = manifest.get(field)
    if isinstance(value, str) and value.strip():
        return value
    return None


def _bool_from_manifest(manifest: Mapping[str, Any], field: str) -> bool:
    return manifest.get(field) is True


def _material_field_present(field: str, value: Any) -> bool:
    if field in SUBMISSION_MATERIAL_TEXT_FIELDS:
        return _has_text(value if isinstance(value, str) else None)
    return value is True


def _reason_codes(checks: dict[str, dict[str, Any]]) -> tuple[list[str], list[str]]:
    blockers: list[str] = []
    needs_attention: list[str] = []
    for check in checks.values():
        codes = [str(code) for code in check.get("reason_codes", []) if isinstance(code, str)]
        if check.get("status") == BLOCKED:
            blockers.extend(codes)
        elif check.get("status") == NEEDS_ATTENTION:
            needs_attention.extend(codes)
    return sorted(set(blockers)), sorted(set(needs_attention))


def _safe_next_action(status: str, blocker_codes: list[str], needs_attention_codes: list[str]) -> dict[str, Any]:
    if status == READY:
        return {
            "action": "open_openai_dashboard_submission_form",
            "why": "Local readiness evidence is complete. Human operator still submits manually in the OpenAI dashboard.",
        }
    if blocker_codes:
        return {
            "action": "fix_product_readiness_before_submission",
            "tool": "get_product_readiness_status",
            "arguments": {},
            "why": "Submission should not start while product readiness or public MCP endpoint is blocked.",
        }
    return {
        "action": "complete_submission_materials",
        "missing_reason_codes": needs_attention_codes,
        "why": "Submission materials, testing evidence, permissions, or confirmations are incomplete.",
    }


def _summary_for(status: str) -> str:
    if status == READY:
        return "Release/App submission readiness evidence is complete; submit manually from the OpenAI dashboard."
    if status == BLOCKED:
        return "Release/App submission is blocked by product readiness or public endpoint evidence."
    return "Release/App submission needs operator-supplied materials, testing, permission, or confirmation evidence."


def _authority_boundary() -> dict[str, bool]:
    return {
        "read_only": True,
        "side_effects": False,
        "does_not_create_openai_app_draft": True,
        "does_not_submit_app_for_review": True,
        "does_not_publish_app": True,
        "does_not_call_openai_dashboard_or_api": True,
        "does_not_read_tokens_or_cookies": True,
        "does_not_read_provider_config": True,
        "does_not_release_or_deploy": True,
    }


def _has_text(value: str | None) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_https_url(value: str | None) -> bool:
    return isinstance(value, str) and value.strip().lower().startswith("https://")


def _iso_now(now: datetime | None) -> str:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
