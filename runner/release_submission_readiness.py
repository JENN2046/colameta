from __future__ import annotations

import os
import json
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from runner.production_ops import DEFAULT_CONNECTOR_SMOKE_FRESH_HOURS, DEFAULT_PUBLIC_BASE_URL
from runner.product_readiness import build_product_readiness_packet


RELEASE_SUBMISSION_SOURCE = "release_submission_readiness"
RELEASE_SUBMISSION_VERSION = "release_submission_readiness.v1"
SUBMISSION_EVIDENCE_SCAFFOLD_SOURCE = "submission_evidence_scaffold"
SUBMISSION_EVIDENCE_SCAFFOLD_VERSION = "submission_evidence_scaffold.v1"
DEFAULT_SUBMISSION_MATERIALS_REL_PATH = "docs/chatgpt-app-submission-materials.json"
RELEASE_SUBMISSION_MATERIALS_MAX_BYTES = 65536
READY = "ready"
NEEDS_ATTENTION = "needs_attention"
BLOCKED = "blocked"

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
    placeholder_files: list[str] = []
    present_files: list[str] = []

    for evidence_key in required_keys:
        refs = _coerce_evidence_refs(evidence.get(evidence_key))
        if not refs:
            missing_keys.append(evidence_key)
            continue
        for ref in refs:
            normalized = _normalize_evidence_ref(project_root, ref)
            if normalized.get("ok") is not True:
                invalid_refs.append({"key": evidence_key, "ref": ref, "error_code": str(normalized.get("error_code"))})
                continue
            rel_path = str(normalized["rel_path"])
            if os.path.isfile(str(normalized["abs_path"])):
                if _is_placeholder_evidence_ref(rel_path):
                    placeholder_files.append(rel_path)
                else:
                    present_files.append(rel_path)
            else:
                missing_files.append(rel_path)

    if missing_keys or invalid_refs or missing_files or placeholder_files:
        return {
            "status": NEEDS_ATTENTION,
            "reason_codes": ["SUBMISSION_EVIDENCE_REFERENCES_INCOMPLETE"],
            "required_keys": required_keys,
            "missing_keys": sorted(set(missing_keys)),
            "invalid_refs": invalid_refs,
            "missing_files": sorted(set(missing_files)),
            "placeholder_files": sorted(set(placeholder_files)),
            "present_files": sorted(set(present_files)),
        }
    return {
        "status": READY,
        "reason_codes": ["SUBMISSION_EVIDENCE_REFERENCES_READY"],
        "required_keys": required_keys,
        "present_files": sorted(set(present_files)),
    }


def _coerce_evidence_refs(value: Any) -> list[str]:
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    if isinstance(value, list):
        refs = [item.strip() for item in value if isinstance(item, str) and item.strip()]
        return refs
    return []


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
