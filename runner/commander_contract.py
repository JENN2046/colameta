"""Pure public-response contract for the nine-tool Commander surface.

This module classifies and shapes already-produced tool results.  It performs
no project I/O, dispatches no workflow, grants no authority, and does not alter
the underlying result.  The normal Commander projector remains responsible for
transport-specific packaging and its existing path-redaction boundary.
"""

from __future__ import annotations

import base64
import binascii
from bisect import bisect_right
import copy
from datetime import datetime
import json
import math
import re
import unicodedata
from typing import Any, Iterable

from runner.project_context_binding import (
    BASE_CONTEXT_BINDING_FIELDS,
    OPERATION_CONTEXT_BINDING_FIELDS,
)


COMMANDER_RESPONSE_SCHEMA_VERSION = "commander_response.v1"
COMMANDER_OUTCOMES = frozenset(
    {
        "completed",
        "in_progress",
        "confirmation_required",
        "blocked",
        "failed",
    }
)
COMMANDER_RESPONSE_JOURNEY_STAGES = frozenset(
    {
        "connect",
        "observe",
        "plan",
        "execute",
        "review",
        "validate",
        "close",
        "recover",
    }
)
COMMANDER_RESPONSE_FIELDS = (
    "schema_version",
    "outcome",
    "summary",
    "journey_stage",
    "context_binding",
    "facts",
    "evidence",
    "next_action",
    "confirmation",
    "error",
)

COMMANDER_SUMMARY_MAX_CHARS = 600
COMMANDER_TEXT_MAX_CHARS = 2_000
COMMANDER_REASON_MAX_CHARS = 600
COMMANDER_LIST_MAX_ITEMS = 100
COMMANDER_OBJECT_MAX_FIELDS = 160
COMMANDER_PUBLIC_MAX_DEPTH = 12
COMMANDER_ARTIFACT_PAGE_MAX_CHARS = 100_000

COMMANDER_PUBLIC_ERROR_CODES = frozenset(
    {
        "PROJECT_REQUIRED",
        "PROJECT_NOT_REGISTERED",
        "PROJECT_MODE_UNSUPPORTED",
        "PROJECT_CONTEXT_MISMATCH",
        "STALE_CONTEXT",
        "STALE_PREVIEW",
        "PREVIEW_REQUIRED",
        "PREVIEW_EXPIRED",
        "CONFIRMATION_REQUIRED",
        "WORKTREE_DIRTY",
        "SCOPE_VIOLATION",
        "VALIDATION_FAILED",
        "VALIDATION_UNAVAILABLE",
        "EXECUTOR_UNAVAILABLE",
        "EXECUTOR_RUNNING",
        "MANUAL_REVIEW_REQUIRED",
        "EVIDENCE_UNAVAILABLE",
        "ARTIFACT_NOT_FOUND",
        "ARTIFACT_EXPIRED",
        "RESOURCE_URI_INVALID",
        "TOOL_NOT_AVAILABLE",
        "WORKFLOW_NOT_SUPPORTED",
        "PUBLIC_PROJECTION_FAILED",
        "INTERNAL_RESULT_INVALID",
        "INTERNAL_ERROR",
    }
)

_FAILED_PUBLIC_ERROR_CODES = frozenset(
    {
        "PUBLIC_PROJECTION_FAILED",
        "INTERNAL_RESULT_INVALID",
        "INTERNAL_ERROR",
    }
)
_IN_PROGRESS_PUBLIC_ERROR_CODES = frozenset({"EXECUTOR_RUNNING"})
_CONFIRMATION_PUBLIC_ERROR_CODES = frozenset({"CONFIRMATION_REQUIRED"})
_BLOCKED_PUBLIC_ERROR_CODES = COMMANDER_PUBLIC_ERROR_CODES - (
    _FAILED_PUBLIC_ERROR_CODES
    | _IN_PROGRESS_PUBLIC_ERROR_CODES
    | _CONFIRMATION_PUBLIC_ERROR_CODES
)

_INTERNAL_ERROR_CODE_MAP = {
    "PROJECT_NAME_REQUIRED": "PROJECT_REQUIRED",
    "INVALID_PROJECT_NAME": "PROJECT_REQUIRED",
    "PROJECT_NOT_REGISTERED": "PROJECT_NOT_REGISTERED",
    "PROJECT_NAME_ROUTING_NOT_SUPPORTED": "PROJECT_MODE_UNSUPPORTED",
    "PROJECT_MODE_UNSUPPORTED": "PROJECT_MODE_UNSUPPORTED",
    "PROJECT_UNAVAILABLE": "PROJECT_NOT_REGISTERED",
    "PROJECT_ROOT_UNAVAILABLE": "PROJECT_NOT_REGISTERED",
    "PROJECT_NAME_CONFLICT": "PROJECT_CONTEXT_MISMATCH",
    "PROJECT_ROOT_CONFLICT": "PROJECT_CONTEXT_MISMATCH",
    "PROJECT_ROOT_OVERRIDE_NOT_ALLOWED": "PROJECT_CONTEXT_MISMATCH",
    "OPERATOR_PROJECT_MISMATCH": "PROJECT_CONTEXT_MISMATCH",
    "PROJECT_MISMATCH": "PROJECT_CONTEXT_MISMATCH",
    "PROJECT_ROOT_MISMATCH": "PROJECT_CONTEXT_MISMATCH",
    "PREVIEW_PROJECT_MISMATCH": "PROJECT_CONTEXT_MISMATCH",
    "CONTEXT_BINDING_MISMATCH": "PROJECT_CONTEXT_MISMATCH",
    "REQUEST_CONTEXT_BINDING_MISMATCH": "PROJECT_CONTEXT_MISMATCH",
    "CONTEXT_BINDING_UNAVAILABLE": "STALE_CONTEXT",
    "REVIEW_MANIFEST_CONTEXT_UNAVAILABLE": "STALE_CONTEXT",
    "REVIEW_MANIFEST_SUBJECT_HASH_MISMATCH": "STALE_CONTEXT",
    "PREVIEW_STALE": "STALE_PREVIEW",
    "PREVIEW_INVALID": "STALE_PREVIEW",
    "PREVIEW_KIND_MISMATCH": "STALE_PREVIEW",
    "PREVIEW_ACTION_INVALID": "STALE_PREVIEW",
    "PREVIEW_NOT_APPLICABLE": "STALE_PREVIEW",
    "PREVIEW_STATUS_CHANGED": "STALE_PREVIEW",
    "PREVIEW_HEAD_CHANGED": "STALE_PREVIEW",
    "HEAD_CHANGED": "STALE_PREVIEW",
    "BRANCH_CHANGED": "STALE_PREVIEW",
    "REMOTE_CHANGED": "STALE_PREVIEW",
    "UPSTREAM_CHANGED": "STALE_PREVIEW",
    "UPSTREAM_BRANCH_CHANGED": "STALE_PREVIEW",
    "UPSTREAM_HEAD_CHANGED": "STALE_PREVIEW",
    "AHEAD_COUNT_CHANGED": "STALE_PREVIEW",
    "BEHIND_COUNT_CHANGED": "STALE_PREVIEW",
    "FILES_CHANGED": "STALE_PREVIEW",
    "FILES_NO_LONGER_ALLOWED": "STALE_PREVIEW",
    "DIFF_HASH_CHANGED": "STALE_PREVIEW",
    "CONTENT_MISMATCH": "STALE_PREVIEW",
    "BASE_CHANGED": "STALE_PREVIEW",
    "MESSAGE_MISMATCH": "STALE_PREVIEW",
    "INITIAL_COMMIT_STATE_CHANGED": "STALE_PREVIEW",
    "OPERATOR_PREVIEW_CHANGED": "STALE_PREVIEW",
    "OPERATOR_PREVIEW_ALREADY_CONSUMED": "STALE_PREVIEW",
    "INVALID_PREVIEW_ID": "PREVIEW_REQUIRED",
    "PREVIEW_NOT_FOUND": "PREVIEW_REQUIRED",
    "MANIFEST_VALIDATION_PREVIEW_REQUIRED": "PREVIEW_REQUIRED",
    "OPERATOR_PREVIEW_NOT_FOUND": "PREVIEW_REQUIRED",
    "PATCH_NOT_FOUND": "PREVIEW_REQUIRED",
    "OPERATOR_PREVIEW_EXPIRED": "PREVIEW_EXPIRED",
    "PREVIEW_EXPIRED": "PREVIEW_EXPIRED",
    "CONFIRMATION_REQUIRED": "CONFIRMATION_REQUIRED",
    "GIT_WORKTREE_DIRTY": "WORKTREE_DIRTY",
    "WORKTREE_DIRTY": "WORKTREE_DIRTY",
    "WORKING_TREE_DIRTY": "WORKTREE_DIRTY",
    "WORKTREE_NOT_CLEAN": "WORKTREE_DIRTY",
    "COMMIT_BLOCKED": "WORKTREE_DIRTY",
    "NO_FILES_TO_COMMIT": "WORKTREE_DIRTY",
    "INSUFFICIENT_SCOPE": "SCOPE_VIOLATION",
    "REMOTE_POLICY_DENIED": "SCOPE_VIOLATION",
    "REMOTE_MCP_COMMIT_DENIED": "SCOPE_VIOLATION",
    "REMOTE_MCP_PLAN_DENIED": "SCOPE_VIOLATION",
    "OPERATOR_PRINCIPAL_DENIED": "SCOPE_VIOLATION",
    "WORK_ITEM_PRIVATE_PRINCIPAL_REQUIRED": "SCOPE_VIOLATION",
    "TOOL_POLICY_DENIED": "SCOPE_VIOLATION",
    "REMOTE_NOT_ALLOWED": "SCOPE_VIOLATION",
    "FILE_NOT_ALLOWED": "SCOPE_VIOLATION",
    "PATH_NOT_ALLOWED": "SCOPE_VIOLATION",
    "FILE_NOT_COMMITTABLE": "SCOPE_VIOLATION",
    "TARGET_FILE_DENIED": "SCOPE_VIOLATION",
    "TARGET_FILE_NOT_ALLOWED": "SCOPE_VIOLATION",
    "INVALID_FILE_SELECTION": "SCOPE_VIOLATION",
    "INVALID_SCOPE": "SCOPE_VIOLATION",
    "SCOPE_VIOLATION": "SCOPE_VIOLATION",
    "VALIDATION_FAILED": "VALIDATION_FAILED",
    "VALIDATION_RUN_FAILED": "VALIDATION_FAILED",
    "VALIDATION_RUN_TIMEOUT": "VALIDATION_FAILED",
    "RUN_RESULT_DIGEST_MISMATCH": "VALIDATION_FAILED",
    "RUN_RESULT_INVALID": "VALIDATION_FAILED",
    "VALIDATION_UNAVAILABLE": "VALIDATION_UNAVAILABLE",
    "NO_VALIDATION_COMMANDS": "VALIDATION_UNAVAILABLE",
    "NO_MANIFEST_VALIDATION_COMMANDS": "VALIDATION_UNAVAILABLE",
    "NO_MANIFEST_ACCEPTANCE_COMMANDS": "VALIDATION_UNAVAILABLE",
    "RUN_NOT_FOUND": "VALIDATION_UNAVAILABLE",
    "INVALID_RUN_ID": "VALIDATION_UNAVAILABLE",
    "PREVIEW_BLOCKED": "VALIDATION_UNAVAILABLE",
    "EXECUTOR_UNAVAILABLE": "EXECUTOR_UNAVAILABLE",
    "EXECUTOR_RUNNING": "EXECUTOR_RUNNING",
    "RUNNER_STATUS_RUNNING": "EXECUTOR_RUNNING",
    "OPERATION_RUNNING": "EXECUTOR_RUNNING",
    "JOB_ALREADY_RUNNING": "EXECUTOR_RUNNING",
    "MANUAL_REVIEW_REQUIRED": "MANUAL_REVIEW_REQUIRED",
    "MCP_RESULT_ARTIFACT_UNAVAILABLE": "PUBLIC_PROJECTION_FAILED",
    "ACTION_RESULT_ARTIFACT_UNAVAILABLE": "PUBLIC_PROJECTION_FAILED",
    "EVIDENCE_UNAVAILABLE": "EVIDENCE_UNAVAILABLE",
    "NOT_FOUND": "ARTIFACT_NOT_FOUND",
    "RESULT_ARTIFACT_ID_REQUIRED": "RESOURCE_URI_INVALID",
    "INVALID_RESULT_ARTIFACT_ID": "RESOURCE_URI_INVALID",
    "INVALID_RESULT_ARTIFACT_PAGE": "RESOURCE_URI_INVALID",
    "RESULT_ARTIFACT_NOT_FOUND_OR_EXPIRED": "ARTIFACT_EXPIRED",
    "REVIEW_MANIFEST_ID_REQUIRED": "RESOURCE_URI_INVALID",
    "INVALID_REVIEW_MANIFEST_PAGE": "RESOURCE_URI_INVALID",
    "REVIEW_MANIFEST_PAGE_NOT_FOUND": "ARTIFACT_NOT_FOUND",
    "REVIEW_MANIFEST_SUBJECT_NOT_FOUND": "ARTIFACT_NOT_FOUND",
    "REVIEW_MANIFEST_NOT_FOUND_OR_EXPIRED": "ARTIFACT_EXPIRED",
    "ARTIFACT_EXPIRED": "ARTIFACT_EXPIRED",
    "INVALID_RESOURCE_URI": "RESOURCE_URI_INVALID",
    "RESOURCE_NOT_FOUND": "ARTIFACT_NOT_FOUND",
    "TOOL_NOT_EXPOSED": "TOOL_NOT_AVAILABLE",
    "TOOL_NOT_FOUND": "TOOL_NOT_AVAILABLE",
    "INVALID_TOOL": "TOOL_NOT_AVAILABLE",
    "INVALID_WORKFLOW_ACTION": "WORKFLOW_NOT_SUPPORTED",
    "INVALID_WORKFLOW": "WORKFLOW_NOT_SUPPORTED",
    "INVALID_ACTION": "WORKFLOW_NOT_SUPPORTED",
    "INVALID_RESULT_ARTIFACT_PHASE": "WORKFLOW_NOT_SUPPORTED",
    "INVALID_REVIEW_MANIFEST_PHASE": "WORKFLOW_NOT_SUPPORTED",
    "INVALID_PHASE": "WORKFLOW_NOT_SUPPORTED",
    "UNKNOWN_ACTION": "WORKFLOW_NOT_SUPPORTED",
    "UNSUPPORTED_ACTION": "WORKFLOW_NOT_SUPPORTED",
    "STAGE_7_9_PHASE_NOT_SUPPORTED": "WORKFLOW_NOT_SUPPORTED",
    "STAGE_7_9_CONTEXT_REQUIRED": "STALE_CONTEXT",
    "STAGE_7_9_CONTEXT_UNAVAILABLE": "STALE_CONTEXT",
    "STAGE_7_9_CONTEXT_MISMATCH": "PROJECT_CONTEXT_MISMATCH",
    "STAGE_7_9_TASKBOOK_BINDING_MISMATCH": "STALE_CONTEXT",
    "STAGE_7_9_DRIFT_PACK_BINDING_MISMATCH": "STALE_CONTEXT",
    "STAGE_7_9_INPUTS_REQUIRED": "EVIDENCE_UNAVAILABLE",
    "STAGE_7_9_STAGE_7_FAILED_CLOSED": "VALIDATION_FAILED",
    "STAGE_7_9_STAGE_8_FAILED_CLOSED": "VALIDATION_FAILED",
    "STAGE_7_9_STAGE_9_FAILED_CLOSED": "VALIDATION_FAILED",
    "STAGE_7_9_AUTHORITY_BOUNDARY_VIOLATION": "SCOPE_VIOLATION",
    "CURRENT_FACTS_PHASE_NOT_SUPPORTED": "WORKFLOW_NOT_SUPPORTED",
    "CURRENT_FACTS_PREVIEW_ID_REQUIRED": "PREVIEW_REQUIRED",
    "CURRENT_FACTS_PREVIEW_NOT_FOUND_OR_EXPIRED": "PREVIEW_EXPIRED",
    "CURRENT_FACTS_PREVIEW_STALE": "STALE_PREVIEW",
    "CURRENT_FACTS_RESULT_ARTIFACT_UNAVAILABLE": "EVIDENCE_UNAVAILABLE",
    "CURRENT_FACTS_UNAVAILABLE": "EVIDENCE_UNAVAILABLE",
    "MCP_RESULT_SHAPING_FAILED": "PUBLIC_PROJECTION_FAILED",
    "ACTION_RESPONSE_PACKAGING_FAILED": "PUBLIC_PROJECTION_FAILED",
    "TOOL_EXEC_ERROR": "INTERNAL_ERROR",
    "OPERATOR_REQUEST_FAILED": "INTERNAL_ERROR",
    "OPERATOR_STEP_ERROR": "INTERNAL_ERROR",
    "BRIDGE_ERROR": "INTERNAL_ERROR",
    "SOURCE_REVIEW_ERROR": "INTERNAL_ERROR",
    "INTERNAL_ERROR": "INTERNAL_ERROR",
}

_BLOCKER_KEYS = (
    "blockers",
    "commit_blockers",
    "validation_blockers",
    "hard_blockers",
)
_ACTION_CONTAINER_KEYS = frozenset(
    {
        "next_action",
        "next_actions",
        "recommended_next_action",
        "recommended_next_actions",
        "recommended_next_read",
        "recommended_next_reads",
        "copyable_apply_call",
        "copyable_tool_call",
        "recovery",
        "alternatives",
        "copy_paste_next_request",
    }
)
_FACT_EXCLUDED_KEYS = frozenset(
    {
        "ok",
        "message",
        "details",
        "error",
        "error_code",
        "requires_confirmation",
        "confirmation_required",
        "confirmation",
        "preview_id",
        "gate_preview_id",
        "batch_preview_id",
        "result_artifact",
        "evidence",
        "context_binding",
        "artifact_id",
        "resource_uri",
        "manifest_resource_uri",
        "page_uri_template",
        "page_count",
        "content_sha256",
        "manifest_sha256",
        "review_manifest_id",
        "run_id",
        "validation_run_id",
        "executor_run_id",
        "expires_at",
        *_ACTION_CONTAINER_KEYS,
    }
)
_FORBIDDEN_PUBLIC_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "authorization_code",
        "authorization_header",
        "audit_id",
        "client_secret",
        "cookie",
        "cookies",
        "delegated_tool",
        "evidence_path",
        "evidence_paths",
        "evidence_refs",
        "event_id",
        "id_token",
        "loaded_source_root",
        "log",
        "log_path",
        "logs",
        "operator_confirmation_ref",
        "oauth_access_token",
        "oauth_authorization_code",
        "oauth_code",
        "oauth_token",
        "oauth_refresh_token",
        "passphrase",
        "password",
        "passwd",
        "pid",
        "ppid",
        "private_key",
        "project_id",
        "project_identity",
        "project_root",
        "raw_log",
        "raw_logs",
        "record_id",
        "registry_path",
        "report_id",
        "request_id",
        "refresh_token",
        "runtime_dir",
        "runtime_project_root",
        "session_id",
        "session_ref",
        "settings_path",
        "source_root",
        "stable_runtime_dir",
        "stderr",
        "stdout",
        "secret",
        "trace_id",
        "token",
        "workflow_id",
        "workflow_record_warning",
        "workspace_root",
    }
)
_FACT_INTERNAL_ID_KEYS = frozenset(
    {
        "executor_run_id",
        "run_id",
        "validation_run_id",
    }
)
_ALLOWED_PUBLIC_OPAQUE_ID_KEYS = frozenset(
    {
        "artifact_id",
        "batch_preview_id",
        "gate_preview_id",
        "preview_id",
        "review_manifest_id",
    }
)
_SENSITIVE_PUBLIC_KEY_RE = re.compile(
    r"(?i)(?:^|_)(?:"
    r"access_?key(?:_?id)?"
    r"|access_?token"
    r"|api_?key"
    r"|auth(?:orization)?"
    r"|authorization_code"
    r"|client_?secret"
    r"|cookie"
    r"|credentials?"
    r"|id_?token"
    r"|oauth(?:_[a-z0-9]+)*(?:_code|_token)"
    r"|pass(?:_?phrase|word|wd)"
    r"|private_?key"
    r"|refresh_?token"
    r"|secret_?access_?key"
    r"|secret"
    r"|token"
    r")(?:$|_)"
)
_INTERNAL_ID_PUBLIC_KEY_RE = re.compile(
    r"(?i)^(?:"
    r"audit"
    r"|event"
    r"|executor_run"
    r"|project"
    r"|record"
    r"|report"
    r"|request"
    r"|run"
    r"|session"
    r"|trace"
    r"|validation_run"
    r"|workflow"
    r")_id$"
)

_RUNNING_STATUS_VALUES = frozenset(
    {
        "executing",
        "in_progress",
        "polling",
        "running",
        "started",
    }
)
_BLOCKED_STATUS_VALUES = frozenset(
    {
        "blocked",
        "needs_fix",
        "scope_violation",
        "stale",
    }
)
_CONFIRMATION_STATUS_VALUES = frozenset(
    {
        "awaiting_confirmation",
        "confirmation_required",
        "requires_confirmation",
    }
)
_FAILED_STATUS_VALUES = frozenset(
    {
        "error",
        "failed",
        "failure",
    }
)
_STATUS_KEYS = (
    "status",
    "state",
    "run_status",
    "validation_status",
    "executor_status",
    "workflow_status",
)

_MUTATING_GIT_ACTIONS = frozenset(
    {
        "commit_apply",
        "pull_apply",
        "push_apply",
        "restore_file_apply",
        "revert_apply",
    }
)
_CONFIRMATION_WORKFLOW_PHASES = frozenset(
    {
        "apply",
        "apply_all",
        "commit",
        "execute",
        "plan_apply",
        "run",
    }
)
_POLL_GIT_ACTIONS = frozenset({"status", "push_status", "pull_status"})

_OPAQUE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
_PREVIEW_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,128}$")
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_GIT_HEAD_RE = re.compile(r"^[0-9a-fA-F]{40,128}$")
_RESULT_ARTIFACT_URI_RE = re.compile(
    r"^colameta://result-artifact/(?P<artifact_id>[A-Za-z0-9_-]{16,128})$"
)
_RESULT_ARTIFACT_PAGE_TEMPLATE_RE = re.compile(
    r"^colameta://result-artifact/(?P<artifact_id>[A-Za-z0-9_-]{16,128})/pages/\{page\}$"
)
_REVIEW_MANIFEST_URI_RE = re.compile(
    r"^colameta://review-manifest/(?P<manifest_id>[A-Za-z0-9_-]{16,128})"
    r"(?:/subjects/[1-9][0-9]*)?$"
)
_COMMANDER_PUBLIC_OPAQUE_RESOURCE_URI_PATTERN = (
    r"colameta://(?:"
    r"result-artifact/[A-Za-z0-9_-]{16,128}(?:/pages/(?:[1-9][0-9]*|\{page\}))?"
    r"|review-manifest/[A-Za-z0-9_-]{16,128}"
    r"(?:/subjects/[1-9][0-9]*(?:/pages/(?:[1-9][0-9]*|\{page\}))?)?"
    r")"
)
COMMANDER_PUBLIC_OPAQUE_RESOURCE_URI_RE = re.compile(
    rf"^{_COMMANDER_PUBLIC_OPAQUE_RESOURCE_URI_PATTERN}$"
)
_PUBLIC_OPAQUE_RESOURCE_URI_CANDIDATE_RE = re.compile(
    _COMMANDER_PUBLIC_OPAQUE_RESOURCE_URI_PATTERN
)
_PUBLIC_COLAMETA_URI_TOKEN_RE = re.compile(
    r"colameta://[^\s\"'`<>]+",
    re.IGNORECASE,
)
_PUBLIC_COLAMETA_URI_SCHEME_RE = re.compile(
    r"colameta://",
    re.IGNORECASE,
)
_PUBLIC_RESOURCE_URI_PLACEHOLDER = "<resource-uri>"
_PUBLIC_RESOURCE_URI_ASCII_OPENING_DELIMITERS = frozenset("([{<")
_PUBLIC_RESOURCE_URI_ASCII_CLOSING_DELIMITERS = frozenset(")]}")
_PUBLIC_RESOURCE_URI_UNICODE_SENTENCE_DELIMITERS = frozenset(
    "。，、；：！？…．｡"
)
# Unicode 17.0 ``Emoji`` property ranges from
# https://www.unicode.org/Public/17.0.0/ucd/emoji/emoji-data.txt, compacted only
# across adjacent entries. ASCII keycap bases are intentionally excluded and
# recognized solely as complete keycap sequences.
_PUBLIC_RESOURCE_URI_EMOJI_BASE_RANGES = (
    (0x00A9, 0x00A9),
    (0x00AE, 0x00AE),
    (0x203C, 0x203C),
    (0x2049, 0x2049),
    (0x2122, 0x2122),
    (0x2139, 0x2139),
    (0x2194, 0x2199),
    (0x21A9, 0x21AA),
    (0x231A, 0x231B),
    (0x2328, 0x2328),
    (0x23CF, 0x23CF),
    (0x23E9, 0x23F3),
    (0x23F8, 0x23FA),
    (0x24C2, 0x24C2),
    (0x25AA, 0x25AB),
    (0x25B6, 0x25B6),
    (0x25C0, 0x25C0),
    (0x25FB, 0x25FE),
    (0x2600, 0x2604),
    (0x260E, 0x260E),
    (0x2611, 0x2611),
    (0x2614, 0x2615),
    (0x2618, 0x2618),
    (0x261D, 0x261D),
    (0x2620, 0x2620),
    (0x2622, 0x2623),
    (0x2626, 0x2626),
    (0x262A, 0x262A),
    (0x262E, 0x262F),
    (0x2638, 0x263A),
    (0x2640, 0x2640),
    (0x2642, 0x2642),
    (0x2648, 0x2653),
    (0x265F, 0x2660),
    (0x2663, 0x2663),
    (0x2665, 0x2666),
    (0x2668, 0x2668),
    (0x267B, 0x267B),
    (0x267E, 0x267F),
    (0x2692, 0x2697),
    (0x2699, 0x2699),
    (0x269B, 0x269C),
    (0x26A0, 0x26A1),
    (0x26A7, 0x26A7),
    (0x26AA, 0x26AB),
    (0x26B0, 0x26B1),
    (0x26BD, 0x26BE),
    (0x26C4, 0x26C5),
    (0x26C8, 0x26C8),
    (0x26CE, 0x26CF),
    (0x26D1, 0x26D1),
    (0x26D3, 0x26D4),
    (0x26E9, 0x26EA),
    (0x26F0, 0x26F5),
    (0x26F7, 0x26FA),
    (0x26FD, 0x26FD),
    (0x2702, 0x2702),
    (0x2705, 0x2705),
    (0x2708, 0x270D),
    (0x270F, 0x270F),
    (0x2712, 0x2712),
    (0x2714, 0x2714),
    (0x2716, 0x2716),
    (0x271D, 0x271D),
    (0x2721, 0x2721),
    (0x2728, 0x2728),
    (0x2733, 0x2734),
    (0x2744, 0x2744),
    (0x2747, 0x2747),
    (0x274C, 0x274C),
    (0x274E, 0x274E),
    (0x2753, 0x2755),
    (0x2757, 0x2757),
    (0x2763, 0x2764),
    (0x2795, 0x2797),
    (0x27A1, 0x27A1),
    (0x27B0, 0x27B0),
    (0x27BF, 0x27BF),
    (0x2934, 0x2935),
    (0x2B05, 0x2B07),
    (0x2B1B, 0x2B1C),
    (0x2B50, 0x2B50),
    (0x2B55, 0x2B55),
    (0x3030, 0x3030),
    (0x303D, 0x303D),
    (0x3297, 0x3297),
    (0x3299, 0x3299),
    (0x1F004, 0x1F004),
    (0x1F0CF, 0x1F0CF),
    (0x1F170, 0x1F171),
    (0x1F17E, 0x1F17F),
    (0x1F18E, 0x1F18E),
    (0x1F191, 0x1F19A),
    (0x1F1E6, 0x1F1FF),
    (0x1F201, 0x1F202),
    (0x1F21A, 0x1F21A),
    (0x1F22F, 0x1F22F),
    (0x1F232, 0x1F23A),
    (0x1F250, 0x1F251),
    (0x1F300, 0x1F321),
    (0x1F324, 0x1F393),
    (0x1F396, 0x1F397),
    (0x1F399, 0x1F39B),
    (0x1F39E, 0x1F3F0),
    (0x1F3F3, 0x1F3F5),
    (0x1F3F7, 0x1F4FD),
    (0x1F4FF, 0x1F53D),
    (0x1F549, 0x1F54E),
    (0x1F550, 0x1F567),
    (0x1F56F, 0x1F570),
    (0x1F573, 0x1F57A),
    (0x1F587, 0x1F587),
    (0x1F58A, 0x1F58D),
    (0x1F590, 0x1F590),
    (0x1F595, 0x1F596),
    (0x1F5A4, 0x1F5A5),
    (0x1F5A8, 0x1F5A8),
    (0x1F5B1, 0x1F5B2),
    (0x1F5BC, 0x1F5BC),
    (0x1F5C2, 0x1F5C4),
    (0x1F5D1, 0x1F5D3),
    (0x1F5DC, 0x1F5DE),
    (0x1F5E1, 0x1F5E1),
    (0x1F5E3, 0x1F5E3),
    (0x1F5E8, 0x1F5E8),
    (0x1F5EF, 0x1F5EF),
    (0x1F5F3, 0x1F5F3),
    (0x1F5FA, 0x1F64F),
    (0x1F680, 0x1F6C5),
    (0x1F6CB, 0x1F6D2),
    (0x1F6D5, 0x1F6D8),
    (0x1F6DC, 0x1F6E5),
    (0x1F6E9, 0x1F6E9),
    (0x1F6EB, 0x1F6EC),
    (0x1F6F0, 0x1F6F0),
    (0x1F6F3, 0x1F6FC),
    (0x1F7E0, 0x1F7EB),
    (0x1F7F0, 0x1F7F0),
    (0x1F90C, 0x1F93A),
    (0x1F93C, 0x1F945),
    (0x1F947, 0x1F9FF),
    (0x1FA70, 0x1FA7C),
    (0x1FA80, 0x1FA8A),
    (0x1FA8E, 0x1FAC6),
    (0x1FAC8, 0x1FAC8),
    (0x1FACD, 0x1FADC),
    (0x1FADF, 0x1FAEA),
    (0x1FAEF, 0x1FAF8),
)
_PUBLIC_RESOURCE_URI_EMOJI_BASE_STARTS = tuple(
    start for start, _ in _PUBLIC_RESOURCE_URI_EMOJI_BASE_RANGES
)
_PUBLIC_JSON_SHORT_ESCAPE_CHARACTERS = {
    '"': '"',
    "\\": "\\",
    "/": "/",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
}
_PUBLIC_POSIX_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9:/\\])/(?!/)[^\s,;\]\[(){}<>\"']+"
)
_PUBLIC_FILE_URI_RE = re.compile(
    r"(?<![A-Za-z0-9])file:(?://(?:localhost)?/|/)[^\s,;\]\[(){}<>\"']+",
    re.IGNORECASE,
)
_PUBLIC_UNC_PATH_RE = re.compile(
    r"(?:(?<![A-Za-z0-9\\])\\\\|(?<![A-Za-z0-9:/\\])/{2,})"
    r"[^\\/\s,;\]\[(){}<>\"']+[\\/][^\s,;\]\[(){}<>\"']+"
)
_PUBLIC_WINDOWS_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:[A-Za-z]:[\\/])[^\s,;\]\[(){}<>\"']*",
    re.IGNORECASE,
)
_SUMMARY_SENTENCE_END_RE = re.compile(r"[。！？!?]+|\.+(?=\s|$)")
_INTERNAL_TOOL_REFERENCE_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:"
    r"manage_files"
    r"|manage_executor_workflow"
    r"|manage_executor_config"
    r"|manage_workflow_run"
    r"|inspect_executor_activity"
    r"|manage_p1_release_evidence"
    r"|get_agent_consumer_contract"
    r"|get_agent_operator_flow_packet"
    r"|get_git_status"
    r"|manage_git_remote"
    r"|manage_plan_version"
    r"|resources/read"
    r")(?![A-Za-z0-9_])"
)
_TOOL_LIKE_IDENTIFIER_RE = re.compile(
    r"(?<![A-Za-z0-9_])"
    r"(?P<name>[a-z][a-z0-9]*(?:_[a-z0-9]+)+)"
    r"(?![A-Za-z0-9_])"
)
_SENSITIVE_HEADER_ASSIGNMENT_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9_])[\"']?(?:"
    r"(?:proxy[_-])?authorization"
    r"|(?:set[_-])?cookie"
    r")[\"']?\s*[:=]"
)
_SENSITIVE_ASSIGNMENT_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9_])[\"']?(?:"
    r"authorization"
    r"|authorization_code"
    r"|api_key"
    r"|client_secret"
    r"|cookie"
    r"|access_token"
    r"|id_token"
    r"|oauth_authorization_code"
    r"|refresh_token"
    r"|oauth_token"
    r"|passphrase"
    r"|password"
    r"|private_key"
    r"|secret"
    r"|token"
    r")[\"']?\s*[:=]\s*(?:(?:bearer|basic)\s+)?(?:"
    r"\"(?:\\.|[^\"\\])*\""
    r"|'(?:\\.|[^'\\])*'"
    r"|\"(?:\\.|[^\"\\])*$"
    r"|'(?:\\.|[^'\\])*$"
    r"|[^\s,;]+"
    r")"
)
_SENSITIVE_CLI_OPTION_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9_-])--"
    r"(?P<key>[A-Za-z][A-Za-z0-9_.-]{0,127})"
    r"[ \t]+(?!-)[^\s,;]+"
)
_ASSIGNMENT_KEY_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9_])"
    r"(?:"
    r"(?P<key_quote>[\"'])"
    r"(?P<quoted_key>[_.-]{0,8}[A-Za-z][A-Za-z0-9_. /-]{0,127})"
    r"(?P=key_quote)"
    r"|(?P<bare_key>[_.-]{0,8}[A-Za-z][A-Za-z0-9_.-]{0,127})"
    r")\s*[:=]"
)
_BEARER_TOKEN_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9_])bearer\s+"
    r"(?!resource_metadata\s*=)"
    r"(?:colameta://[^\s,;]*|[A-Za-z0-9._~+/=-]{8,})"
)
_BASIC_AUTHORIZATION_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9_])basic\s+"
    r"(?P<token>[A-Za-z0-9+/]{2,}={0,2})"
    r"(?![A-Za-z0-9+/=])"
)
_PRIVATE_KEY_BLOCK_RE = re.compile(
    r"(?i)-----BEGIN[ \t]+"
    r"(?:[A-Z0-9]+[ \t]+)*PRIVATE[ \t]+KEY"
    r"(?:[ \t]+BLOCK)?-----"
)
_PUTTY_PRIVATE_KEY_FILE_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9_-])"
    r"putty-user-key-file-[1-9][0-9]*[ \t]*:"
)
_STANDALONE_JWT_RE = re.compile(
    r"(?<![A-Za-z0-9_-])"
    r"(?P<header>[A-Za-z0-9_-]{8,1024})\."
    r"(?P<payload>[A-Za-z0-9_-]{8,16384})\."
    r"(?P<signature>[A-Za-z0-9_-]{8,8192})"
    r"(?![A-Za-z0-9_-])"
)
_CREDENTIAL_URI_USERINFO_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9+.-])"
    r"(?:[A-Za-z][A-Za-z0-9+.-]*:)?//"
    r"[^/?#@\s:]*:[^/?#@\s]+@"
    r"(?=[^/?#\s]+)"
)

_OMIT = object()


class CommanderContractError(ValueError):
    """A bounded public-contract validation failure."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message


def derive_commander_outcome(
    tool_name: str,
    result: dict[str, Any],
) -> str:
    """Derive one of the five public outcomes using the frozen precedence."""

    if not _raw_result_shape_valid(tool_name, result):
        return "failed"

    containers = _result_containers(result)
    public_error_code = commander_public_error_code_for_result(result)
    if public_error_code in _FAILED_PUBLIC_ERROR_CODES:
        return "failed"

    statuses = _direct_status_values(containers)
    if _has_blockers(containers) or public_error_code in _BLOCKED_PUBLIC_ERROR_CODES:
        return "blocked"
    if statuses & _BLOCKED_STATUS_VALUES:
        return "blocked"
    if tool_name == "get_apps_connector_smoke_packet" and _connector_smoke_blocked(
        result
    ):
        return "blocked"
    if "failed" in statuses and tool_name == "manage_validation_run":
        return "blocked"

    ok = _result_ok(containers)
    if ok is False and public_error_code not in (
        _CONFIRMATION_PUBLIC_ERROR_CODES | _IN_PROGRESS_PUBLIC_ERROR_CODES
    ):
        return "failed"

    confirmation_was_consumed = _confirmed_operation_completed(containers)
    if (
        not confirmation_was_consumed
        and (
            public_error_code in _CONFIRMATION_PUBLIC_ERROR_CODES
            or statuses & _CONFIRMATION_STATUS_VALUES
            or _requires_confirmation(containers)
            or _has_confirmation_ready_preview(containers)
        )
    ):
        return "confirmation_required"

    if (
        public_error_code in _IN_PROGRESS_PUBLIC_ERROR_CODES
        or statuses & _RUNNING_STATUS_VALUES
        or _has_running_flag(containers)
    ):
        return "in_progress"

    if statuses & _FAILED_STATUS_VALUES:
        return "failed"

    if ok is not True:
        return "failed"
    if _packaged_evidence_missing(containers):
        return "failed"
    return "completed"


def build_commander_response(
    *,
    tool_name: str,
    raw_result: dict[str, Any],
    params: dict[str, Any] | None = None,
    exact_evidence_prevalidated: bool = False,
) -> dict[str, Any]:
    """Build one validated ``commander_response.v1`` data object.

    Policy lookup is intentionally lazy so this pure contract module remains
    independent of the public projector's import graph.  The exact-evidence
    override is reserved for typed pages whose complete hash-bound content was
    already verified before slicing.
    """

    safe_params = params if isinstance(params, dict) else {}
    if not _raw_result_shape_valid(tool_name, raw_result):
        return _safe_failed_response(
            tool_name=tool_name,
            params=safe_params,
            error_code="INTERNAL_RESULT_INVALID",
            message="内部结果格式无效，无法安全建立 Commander 公共响应。",
        )

    try:
        from runner.commander_workflow_policy import (
            journey_stage_for,
            select_commander_next_action,
        )

        outcome = derive_commander_outcome(tool_name, raw_result)
        journey_stage = journey_stage_for(tool_name, safe_params, raw_result)
        selected_action = select_commander_next_action(
            tool_name=tool_name,
            params=safe_params,
            raw_result=raw_result,
            outcome=outcome,
        )
        next_action = _normalize_action(selected_action)
        context_binding = _extract_context_binding(raw_result)
        if _result_requires_context_binding(
            tool_name=tool_name,
            params=safe_params,
            outcome=outcome,
        ) and context_binding is None:
            raise CommanderContractError(
                "INTERNAL_RESULT_INVALID",
                "Project-bound Commander response is missing context_binding.",
            )
        evidence = _normalize_evidence(raw_result)
        confirmation = (
            _normalize_confirmation(
                tool_name=tool_name,
                raw_result=raw_result,
                params=safe_params,
                context_binding=context_binding,
                next_action=next_action,
            )
            if outcome == "confirmation_required"
            else None
        )
        error = (
            _normalize_error(
                tool_name=tool_name,
                outcome=outcome,
                raw_result=raw_result,
                next_action=next_action,
            )
            if outcome in {"blocked", "failed"}
            else None
        )
        response = {
            "schema_version": COMMANDER_RESPONSE_SCHEMA_VERSION,
            "outcome": outcome,
            "summary": _summary_for(tool_name, raw_result, outcome),
            "journey_stage": journey_stage,
            "context_binding": context_binding,
            "facts": _extract_facts(
                tool_name,
                raw_result,
                params=safe_params,
                exact_evidence_prevalidated=exact_evidence_prevalidated,
            ),
            "evidence": evidence,
            "next_action": next_action,
            "confirmation": confirmation,
            "error": error,
        }
        if outcome == "confirmation_required" and next_action is None:
            raise CommanderContractError(
                "INTERNAL_RESULT_INVALID",
                "confirmation_required 缺少可验证的公开确认动作。",
            )
        validate_commander_response(
            response,
            exact_evidence_prevalidated=exact_evidence_prevalidated,
        )
        return response
    except CommanderContractError as exc:
        return _safe_failed_response(
            tool_name=tool_name,
            params=safe_params,
            error_code=(
                exc.error_code
                if exc.error_code in _FAILED_PUBLIC_ERROR_CODES
                else "INTERNAL_RESULT_INVALID"
            ),
            message="内部结果无法满足 Commander 公共契约，已安全停止投影。",
        )
    except Exception:
        return _safe_failed_response(
            tool_name=tool_name,
            params=safe_params,
            error_code="PUBLIC_PROJECTION_FAILED",
            message="Commander 公共响应构建失败，内部诊断未公开。",
        )


def validate_commander_response(
    response: dict[str, Any],
    *,
    exact_evidence_prevalidated: bool = False,
) -> None:
    """Fail closed unless ``response`` is an exact public contract object.

    ``exact_evidence_prevalidated`` is valid only after the complete
    hash-bound Artifact payload or Manifest subject passed public safety
    projection before its requested page was sliced.
    """

    if not isinstance(response, dict):
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "Commander response must be an object.",
        )
    if set(response) != set(COMMANDER_RESPONSE_FIELDS):
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "Commander response fields do not match commander_response.v1.",
        )
    if response.get("schema_version") != COMMANDER_RESPONSE_SCHEMA_VERSION:
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "Unknown Commander response schema_version.",
        )

    outcome = response.get("outcome")
    if outcome not in COMMANDER_OUTCOMES:
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "Unknown Commander outcome.",
        )
    summary = response.get("summary")
    if (
        not isinstance(summary, str)
        or not summary.strip()
        or len(summary) > COMMANDER_SUMMARY_MAX_CHARS
        or _summary_sentence_count(summary) > 3
        or _contains_unsafe_public_text(summary)
    ):
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "Commander summary is missing, oversized, or unsafe.",
        )
    if response.get("journey_stage") not in COMMANDER_RESPONSE_JOURNEY_STAGES:
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "Unknown Commander journey_stage.",
        )

    _validate_context_binding(response.get("context_binding"))
    facts = response.get("facts")
    if not isinstance(facts, dict):
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "Commander facts must be an object.",
        )
    _validate_public_value(
        facts,
        depth=0,
        facts=True,
        exact_evidence_prevalidated=exact_evidence_prevalidated,
    )
    evidence = response.get("evidence")
    _validate_evidence(evidence)
    _validate_artifact_page_binding(
        facts,
        evidence,
        exact_evidence_prevalidated=exact_evidence_prevalidated,
    )
    _validate_review_manifest_page_binding(
        facts,
        evidence,
        exact_evidence_prevalidated=exact_evidence_prevalidated,
    )
    _validate_action(response.get("next_action"))

    confirmation = response.get("confirmation")
    error = response.get("error")
    if outcome == "confirmation_required":
        _validate_confirmation(confirmation)
        if response.get("context_binding") is None:
            raise CommanderContractError(
                "INTERNAL_RESULT_INVALID",
                "confirmation_required must expose the bound project context.",
            )
        if error is not None:
            raise CommanderContractError(
                "INTERNAL_RESULT_INVALID",
                "confirmation_required cannot also expose error.",
            )
        if response.get("next_action") is None or not _is_confirmation_action(
            response["next_action"]
        ):
            raise CommanderContractError(
                "INTERNAL_RESULT_INVALID",
                "confirmation_required must expose the matching public confirmation action.",
            )
        _validate_confirmation_relationship(response)
    elif confirmation is not None:
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "confirmation is only allowed for confirmation_required.",
        )

    if outcome in {"blocked", "failed"}:
        _validate_error(error)
        error_code = error["code"]
        if outcome == "blocked" and error_code not in _BLOCKED_PUBLIC_ERROR_CODES:
            raise CommanderContractError(
                "INTERNAL_RESULT_INVALID",
                "blocked must expose a blocker-class public error code.",
            )
        if outcome == "failed" and error_code not in _FAILED_PUBLIC_ERROR_CODES:
            raise CommanderContractError(
                "INTERNAL_RESULT_INVALID",
                "failed must expose a failure-class public error code.",
            )
        if response.get("next_action") is not None and _is_mutating_action(
            response["next_action"]
        ):
            raise CommanderContractError(
                "INTERNAL_RESULT_INVALID",
                "blocked or failed responses cannot recommend a mutation.",
            )
        if error.get("recovery") != response.get("next_action"):
            raise CommanderContractError(
                "INTERNAL_RESULT_INVALID",
                "error.recovery must match the single public next_action.",
            )
    elif error is not None:
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "error is only allowed for blocked or failed.",
        )

    if outcome == "in_progress":
        next_action = response.get("next_action")
        if next_action is None or not _is_poll_action(next_action):
            raise CommanderContractError(
                "INTERNAL_RESULT_INVALID",
                "in_progress must expose one public polling action.",
            )


def commander_response_schema() -> dict[str, Any]:
    """Return a JSON-Schema-compatible description for future tool catalogs."""

    nullable_string = {"type": ["string", "null"]}
    runner_plan_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "mode": {"type": "string", "enum": ["managed", "source-only"]},
            "plan_sha256": {
                "type": ["string", "null"],
                "pattern": "^[0-9a-fA-F]{64}$",
            },
        },
        "required": ["mode", "plan_sha256"],
    }
    context_properties = {
        "project_name": {
            "type": "string",
            "minLength": 1,
            "maxLength": 128,
        },
        "branch": {
            **copy.deepcopy(nullable_string),
            "minLength": 1,
            "maxLength": 255,
        },
        "head": {
            "type": ["string", "null"],
            "minLength": 40,
            "maxLength": 128,
            "pattern": "^[0-9a-fA-F]{40,128}$",
        },
        "runner_plan": runner_plan_schema,
        "current_version": {
            **copy.deepcopy(nullable_string),
            "minLength": 1,
            "maxLength": 128,
        },
    }
    base_context_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": copy.deepcopy(context_properties),
        "required": list(BASE_CONTEXT_BINDING_FIELDS),
    }
    operation_context_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            **copy.deepcopy(context_properties),
            "review_unit": {
                "type": "string",
                "minLength": 1,
                "maxLength": 160,
            },
            "workflow_intent": {
                "type": "string",
                "minLength": 1,
                "maxLength": 160,
            },
        },
        "required": list(OPERATION_CONTEXT_BINDING_FIELDS),
    }
    context_schema = {
        "anyOf": [
            {"type": "null"},
            base_context_schema,
            operation_context_schema,
        ]
    }
    action_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "tool": {
                "type": "string",
                "enum": sorted(_commander_tools()),
            },
            "arguments": {
                "type": "object",
                "additionalProperties": True,
            },
            "reason": {
                "type": "string",
                "minLength": 1,
                "maxLength": COMMANDER_REASON_MAX_CHARS,
            },
        },
        "required": ["tool", "arguments", "reason"],
    }
    result_artifact_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "kind": {"const": "result_artifact"},
            "artifact_id": {"type": "string", "pattern": _OPAQUE_ID_RE.pattern},
            "resource_uri": {
                "type": "string",
                "pattern": (
                    "^colameta://result-artifact/"
                    "[A-Za-z0-9_-]{16,128}$"
                ),
            },
            "page_uri_template": {
                "type": "string",
                "pattern": (
                    "^colameta://result-artifact/"
                    "[A-Za-z0-9_-]{16,128}/pages/\\{page\\}$"
                ),
            },
            "page_count": {"type": "integer", "minimum": 1},
            "content_sha256": {"type": "string", "pattern": _SHA256_RE.pattern},
            "expires_at": {"type": "string", "format": "date-time"},
        },
        "required": [
            "kind",
            "artifact_id",
            "resource_uri",
            "page_uri_template",
            "page_count",
            "content_sha256",
            "expires_at",
        ],
    }
    review_manifest_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "kind": {"const": "review_manifest"},
            "review_manifest_id": {
                "type": "string",
                "pattern": _OPAQUE_ID_RE.pattern,
            },
            "resource_uri": {
                "type": "string",
                "pattern": (
                    "^colameta://review-manifest/[A-Za-z0-9_-]{16,128}"
                    "(?:/subjects/[1-9][0-9]*)?$"
                ),
            },
            "manifest_sha256": {"type": "string", "pattern": _SHA256_RE.pattern},
            "expires_at": {"type": "string", "format": "date-time"},
        },
        "required": [
            "kind",
            "review_manifest_id",
            "resource_uri",
            "manifest_sha256",
            "expires_at",
        ],
    }
    confirmation_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "decision": {
                "type": "string",
                "minLength": 1,
                "maxLength": COMMANDER_SUMMARY_MAX_CHARS,
            },
            "impact": {
                "type": "array",
                "minItems": 1,
                "maxItems": COMMANDER_LIST_MAX_ITEMS,
                "items": {"type": "string", "minLength": 1},
            },
            "risks": {
                "type": "array",
                "maxItems": COMMANDER_LIST_MAX_ITEMS,
                "items": {"type": "string", "minLength": 1},
            },
            "preview_id": {"type": "string", "pattern": _PREVIEW_ID_RE.pattern},
            "expires_at": {"type": "string", "format": "date-time"},
            "context_binding": copy.deepcopy(context_schema),
        },
        "required": ["decision", "impact", "preview_id", "context_binding"],
    }
    error_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "code": {
                "type": "string",
                "enum": sorted(COMMANDER_PUBLIC_ERROR_CODES),
            },
            "message": {
                "type": "string",
                "minLength": 1,
                "maxLength": COMMANDER_SUMMARY_MAX_CHARS,
            },
            "recoverable": {"type": "boolean"},
            "recovery": {
                "anyOf": [
                    {"type": "null"},
                    copy.deepcopy(action_schema),
                ]
            },
        },
        "required": ["code", "message", "recoverable"],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "schema_version": {
                "type": "string",
                "const": COMMANDER_RESPONSE_SCHEMA_VERSION,
            },
            "outcome": {
                "type": "string",
                "enum": sorted(COMMANDER_OUTCOMES),
            },
            "summary": {
                "type": "string",
                "minLength": 1,
                "maxLength": COMMANDER_SUMMARY_MAX_CHARS,
            },
            "journey_stage": {
                "type": "string",
                "enum": sorted(COMMANDER_RESPONSE_JOURNEY_STAGES),
            },
            "context_binding": context_schema,
            "facts": {
                "type": "object",
                "additionalProperties": True,
            },
            "evidence": {
                "anyOf": [
                    {"type": "null"},
                    result_artifact_schema,
                    review_manifest_schema,
                ]
            },
            "next_action": {
                "anyOf": [
                    {"type": "null"},
                    action_schema,
                ]
            },
            "confirmation": {
                "anyOf": [
                    {"type": "null"},
                    confirmation_schema,
                ]
            },
            "error": {
                "anyOf": [
                    {"type": "null"},
                    error_schema,
                ]
            },
        },
        "required": list(COMMANDER_RESPONSE_FIELDS),
        "allOf": [
            {
                "if": {
                    "properties": {
                        "outcome": {"const": "confirmation_required"},
                    },
                    "required": ["outcome"],
                },
                "then": {
                    "properties": {
                        "confirmation": copy.deepcopy(confirmation_schema),
                        "error": {"type": "null"},
                        "next_action": copy.deepcopy(action_schema),
                    }
                },
            },
            {
                "if": {
                    "properties": {
                        "outcome": {"enum": ["blocked", "failed"]},
                    },
                    "required": ["outcome"],
                },
                "then": {
                    "properties": {
                        "confirmation": {"type": "null"},
                        "error": copy.deepcopy(error_schema),
                    }
                },
            },
            {
                "if": {
                    "properties": {
                        "outcome": {"const": "completed"},
                    },
                    "required": ["outcome"],
                },
                "then": {
                    "properties": {
                        "confirmation": {"type": "null"},
                        "error": {"type": "null"},
                    }
                },
            },
            {
                "if": {
                    "properties": {
                        "outcome": {"const": "in_progress"},
                    },
                    "required": ["outcome"],
                },
                "then": {
                    "properties": {
                        "confirmation": {"type": "null"},
                        "error": {"type": "null"},
                        "next_action": copy.deepcopy(action_schema),
                    }
                },
            },
        ],
    }


def _raw_result_shape_valid(tool_name: Any, result: Any) -> bool:
    if not isinstance(tool_name, str) or not tool_name.strip():
        return False
    try:
        if tool_name not in _commander_tools():
            return False
    except Exception:
        return False
    if not isinstance(result, dict):
        return False
    if "tool" in result:
        result_tool = result.get("tool")
        if not isinstance(result_tool, str) or result_tool != tool_name:
            return False
    if "data" in result and not isinstance(result.get("data"), dict):
        return False
    containers = _result_containers(result)
    return _result_ok(containers) is not None


def _result_containers(result: dict[str, Any]) -> list[dict[str, Any]]:
    containers = [result]
    data = result.get("data")
    if isinstance(data, dict):
        containers.append(data)
    return containers


def _result_ok(containers: Iterable[dict[str, Any]]) -> bool | None:
    observed = False
    for container in containers:
        value = container.get("ok")
        if isinstance(value, bool):
            observed = True
            if value is False:
                return False
    return True if observed else None


def _first_string(
    containers: Iterable[dict[str, Any]],
    keys: tuple[str, ...],
) -> str | None:
    for container in containers:
        for key in keys:
            value = container.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _first_nested_string(
    value: Any,
    keys: tuple[str, ...],
    *,
    depth: int = 0,
) -> str | None:
    if depth > COMMANDER_PUBLIC_MAX_DEPTH:
        return None
    if isinstance(value, dict):
        for key in keys:
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        for nested in value.values():
            candidate = _first_nested_string(nested, keys, depth=depth + 1)
            if candidate is not None:
                return candidate
    elif isinstance(value, list):
        for nested in value[:COMMANDER_LIST_MAX_ITEMS]:
            candidate = _first_nested_string(nested, keys, depth=depth + 1)
            if candidate is not None:
                return candidate
    return None


def commander_public_error_code(value: Any) -> str | None:
    """Map one internal or public error code to the stable Commander code."""

    if not isinstance(value, str) or not value.strip():
        return None
    normalized = re.sub(r"[^A-Z0-9_]+", "_", value.strip().upper()).strip("_")
    if normalized in COMMANDER_PUBLIC_ERROR_CODES:
        return normalized
    return _INTERNAL_ERROR_CODE_MAP.get(normalized, "INTERNAL_ERROR")


def commander_public_error_code_for_result(
    result: dict[str, Any],
) -> str | None:
    """Select and map the primary error code using the public contract order."""

    return commander_public_error_code(_raw_error_code(result))


def _raw_error_code(result: dict[str, Any]) -> str | None:
    direct_containers = [result]
    data = result.get("data")
    if isinstance(data, dict):
        direct_containers.append(data)
    direct_code = _first_string(direct_containers, ("error_code",))
    if direct_code is not None:
        return direct_code
    for container in direct_containers:
        error = container.get("error")
        if isinstance(error, dict):
            nested_code = _first_string([error], ("error_code", "code"))
            if nested_code is not None:
                return nested_code
    for container in direct_containers:
        for key in ("result", "unified_status"):
            nested = container.get(key)
            if not isinstance(nested, dict):
                continue
            nested_code = _first_nested_string(nested, ("error_code",))
            if nested_code is not None:
                return nested_code
    return None


def _raw_error_message(result: dict[str, Any]) -> str | None:
    direct_containers = [result]
    data = result.get("data")
    if isinstance(data, dict):
        direct_containers.append(data)
    for container in direct_containers:
        error = container.get("error")
        if isinstance(error, dict):
            nested_message = _first_string([error], ("message",))
            if nested_message is not None:
                return nested_message
    return _first_string(direct_containers, ("message",))


def _has_blockers(containers: Iterable[dict[str, Any]]) -> bool:
    for container in containers:
        for key in _BLOCKER_KEYS:
            value = container.get(key)
            if isinstance(value, list) and value:
                return True
            if isinstance(value, str) and value.strip():
                return True
    return False


def _blocker_values(containers: Iterable[dict[str, Any]]) -> list[str]:
    values: list[str] = []
    for container in containers:
        for key in _BLOCKER_KEYS:
            value = container.get(key)
            if isinstance(value, str) and value.strip():
                values.append(value.strip())
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, str) and item.strip():
                        values.append(item.strip())
                    elif isinstance(item, dict):
                        code = item.get("code") or item.get("error_code")
                        if isinstance(code, str) and code.strip():
                            values.append(code.strip())
    return values


def _direct_status_values(containers: Iterable[dict[str, Any]]) -> set[str]:
    values: set[str] = set()
    for container in containers:
        for key in _STATUS_KEYS:
            value = container.get(key)
            if isinstance(value, str) and value.strip():
                values.add(value.strip().lower())
    return values


def _connector_smoke_blocked(result: dict[str, Any]) -> bool:
    data = result.get("data")
    if not isinstance(data, dict):
        data = result
    closeout = data.get("apps_connector_closeout")
    if isinstance(closeout, dict):
        status = _normalized_string(closeout.get("status"))
        if status and status != "ready":
            return True
    health = data.get("connector_runtime_health")
    if isinstance(health, dict):
        status = _normalized_string(health.get("overall_status"))
        if status and status != "healthy":
            return True
    return False


def _requires_confirmation(containers: Iterable[dict[str, Any]]) -> bool:
    for container in containers:
        if container.get("requires_confirmation") is True:
            return True
        if container.get("confirmation_required") is True:
            return True
        confirmation = container.get("confirmation")
        if isinstance(confirmation, dict) and confirmation.get("required") is True:
            return True
    return False


def _has_running_flag(containers: Iterable[dict[str, Any]]) -> bool:
    for container in containers:
        if any(
            container.get(key) is True
            for key in ("is_running", "operation_running", "running")
        ):
            return True
    return False


def _has_confirmation_ready_preview(containers: list[dict[str, Any]]) -> bool:
    has_preview = any(
        isinstance(container.get(key), str) and bool(container.get(key).strip())
        for container in containers
        for key in ("preview_id", "gate_preview_id", "batch_preview_id")
    )
    if not has_preview:
        return False
    for container in containers:
        for key in _ACTION_CONTAINER_KEYS:
            if _contains_mutating_action_candidate(container.get(key)):
                return True
    return False


def _confirmed_operation_completed(containers: Iterable[dict[str, Any]]) -> bool:
    terminal_statuses = {"completed", "passed", "succeeded", "success"}
    mutating_actions = {
        "apply",
        "apply_all",
        "commit",
        "execute",
        "plan_apply",
        "run",
    }
    for container in containers:
        status = _normalized_string(container.get("status"))
        result = container.get("result")
        verification = container.get("context_binding_verification")
        if (
            status in terminal_statuses
            and isinstance(result, dict)
            and result.get("ok") is True
            and _normalized_string(result.get("action")) in mutating_actions
            and isinstance(verification, dict)
            and _normalized_string(verification.get("status")) == "matched"
        ):
            return True
    return False


def _contains_mutating_action_candidate(value: Any) -> bool:
    if isinstance(value, dict):
        tool = value.get("tool")
        arguments = value.get("arguments")
        if not isinstance(arguments, dict):
            arguments = value.get("params")
        action = {
            "tool": tool,
            "arguments": arguments if isinstance(arguments, dict) else {},
            "reason": "candidate",
        }
        if isinstance(tool, str) and _is_mutating_action(action):
            return True
        return any(_contains_mutating_action_candidate(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_mutating_action_candidate(item) for item in value)
    return False


def _packaged_evidence_missing(containers: Iterable[dict[str, Any]]) -> bool:
    for container in containers:
        if container.get("packaged") is True:
            artifact_id = container.get("artifact_id")
            resource_uri = container.get("resource_uri")
            descriptor = container.get("result_artifact")
            if isinstance(descriptor, dict):
                if artifact_id is None:
                    artifact_id = descriptor.get("artifact_id")
                if resource_uri is None:
                    resource_uri = descriptor.get("resource_uri")
            return not (
                isinstance(artifact_id, str)
                and isinstance(resource_uri, str)
                and _RESULT_ARTIFACT_URI_RE.fullmatch(resource_uri)
            )
    return False


def _summary_for(
    tool_name: str,
    raw_result: dict[str, Any],
    outcome: str,
) -> str:
    defaults = {
        "completed": f"{tool_name} 当前调用已完成。",
        "in_progress": f"{tool_name} 已启动，当前仍在运行。",
        "confirmation_required": f"{tool_name} 已准备确认对象，等待 Jenn 决定。",
        "blocked": f"{tool_name} 当前调用被前置条件阻断。",
        "failed": f"{tool_name} 当前调用失败，内部诊断未公开。",
    }
    # A failed internal result is not a trusted public-message source.  Stable
    # public error details are emitted separately by ``_normalize_error``.
    if outcome == "failed":
        return defaults[outcome]
    containers = _result_containers(raw_result)
    candidates: list[Any] = []
    for container in containers:
        candidates.extend(
            (
                container.get("message"),
                container.get("summary"),
                container.get("display_summary"),
            )
        )
        if outcome == "blocked":
            error = container.get("error")
            if isinstance(error, dict):
                candidates.append(error.get("message"))
    for candidate in candidates:
        if isinstance(candidate, dict):
            for key in ("one_line", "message", "summary", "text"):
                nested = candidate.get(key)
                if isinstance(nested, str) and nested.strip():
                    return _public_summary(nested)
        elif isinstance(candidate, str) and candidate.strip():
            return _public_summary(candidate)
    return defaults[outcome]


def _extract_context_binding(raw_result: dict[str, Any]) -> dict[str, Any] | None:
    containers = _result_containers(raw_result)
    for container in containers:
        value = container.get("context_binding")
        if isinstance(value, dict):
            return _normalize_context_binding(value)
        stage_context = container.get("stage_7_9_context")
        if isinstance(stage_context, dict):
            return _normalize_context_binding(stage_context)
        confirmation = container.get("confirmation")
        if isinstance(confirmation, dict) and isinstance(
            confirmation.get("context_binding"),
            dict,
        ):
            return _normalize_context_binding(confirmation["context_binding"])
    for container in containers:
        for key in ("canonical_state", "canonical_project_state"):
            canonical = container.get(key)
            if isinstance(canonical, dict) and isinstance(
                canonical.get("context_binding"),
                dict,
            ):
                return _normalize_context_binding(canonical["context_binding"])
    return None


def _result_requires_context_binding(
    *,
    tool_name: str,
    params: dict[str, Any],
    outcome: str,
) -> bool:
    if outcome in {"blocked", "failed"}:
        return False
    if outcome == "confirmation_required":
        return True
    if tool_name in {
        "analyze_project_state",
        "review_manifest",
        "manage_validation_run",
        "manage_git",
    }:
        return True
    if tool_name == "run_mcp_workflow":
        workflow = _normalized_string(params.get("workflow"))
        return workflow not in {"result_artifact"}
    return False


def _normalize_context_binding(value: dict[str, Any]) -> dict[str, Any]:
    _validate_context_binding(value)
    return copy.deepcopy(value)


def _validate_context_binding(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "context_binding must be an object or null.",
        )
    fields = set(value)
    base_fields = set(BASE_CONTEXT_BINDING_FIELDS)
    operation_fields = set(OPERATION_CONTEXT_BINDING_FIELDS)
    if fields != base_fields and fields != operation_fields:
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "context_binding fields do not match the existing binding contract.",
        )
    operation = fields == operation_fields
    project_name = value.get("project_name")
    if (
        not isinstance(project_name, str)
        or not project_name.strip()
        or len(project_name.strip()) > 128
        or any(ord(char) < 32 for char in project_name)
    ):
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "context_binding.project_name is required.",
        )
    for key in ("branch", "head"):
        item = value.get(key)
        if operation and (not isinstance(item, str) or not item.strip()):
            raise CommanderContractError(
                "INTERNAL_RESULT_INVALID",
                f"context_binding.{key} is required for an operation binding.",
            )
        if item is not None and not isinstance(item, str):
            raise CommanderContractError(
                "INTERNAL_RESULT_INVALID",
                f"context_binding.{key} must be a string or null.",
            )
        if isinstance(item, str) and (
            not item.strip()
            or len(item.strip()) > (255 if key == "branch" else 128)
            or any(ord(char) < 32 for char in item)
        ):
            raise CommanderContractError(
                "INTERNAL_RESULT_INVALID",
                f"context_binding.{key} must be non-empty and bounded.",
            )
    head = value.get("head")
    if isinstance(head, str) and head and not _GIT_HEAD_RE.fullmatch(head):
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "context_binding.head must be a full Git SHA.",
        )
    runner_plan = value.get("runner_plan")
    if not isinstance(runner_plan, dict) or set(runner_plan) != {
        "mode",
        "plan_sha256",
    }:
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "context_binding.runner_plan has an invalid shape.",
        )
    mode = runner_plan.get("mode")
    plan_sha256 = runner_plan.get("plan_sha256")
    if mode not in {"managed", "source-only"}:
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "context_binding.runner_plan.mode is invalid.",
        )
    if plan_sha256 is None:
        if mode != "source-only":
            raise CommanderContractError(
                "INTERNAL_RESULT_INVALID",
                "Managed context_binding requires plan_sha256.",
            )
    elif not isinstance(plan_sha256, str) or not _SHA256_RE.fullmatch(plan_sha256):
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "context_binding.runner_plan.plan_sha256 is invalid.",
        )
    current_version = value.get("current_version")
    if current_version is not None and (
        not isinstance(current_version, str)
        or not current_version.strip()
        or len(current_version.strip()) > 128
        or any(ord(char) < 32 for char in current_version)
    ):
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "context_binding.current_version must be a string or null.",
        )
    if operation:
        for key in ("review_unit", "workflow_intent"):
            item = value.get(key)
            if (
                not isinstance(item, str)
                or not item.strip()
                or len(item.strip()) > 160
                or any(ord(char) < 32 for char in item)
            ):
                raise CommanderContractError(
                    "INTERNAL_RESULT_INVALID",
                    f"context_binding.{key} is required.",
                )
    _validate_public_value(value, depth=0, facts=False)


def _extract_facts(
    tool_name: str,
    raw_result: dict[str, Any],
    *,
    params: dict[str, Any] | None = None,
    exact_evidence_prevalidated: bool = False,
) -> dict[str, Any]:
    safe_params = params if isinstance(params, dict) else {}
    payload = raw_result.get("data")
    if not isinstance(payload, dict):
        payload = raw_result
    payload_workflow = _normalized_string(payload.get("workflow"))
    payload_phase = _normalized_string(payload.get("phase"))
    is_result_artifact_read = tool_name == "read_result_artifact" or (
        tool_name == "run_mcp_workflow"
        and payload_workflow == "result_artifact"
        and payload_phase == "read"
    )
    artifact_page: dict[str, Any] | None = None
    if is_result_artifact_read and isinstance(
        payload.get("artifact_page"),
        dict,
    ):
        requested_artifact_id = safe_params.get("artifact_id")
        if isinstance(requested_artifact_id, str):
            requested_artifact_id = requested_artifact_id.strip()
        if (
            exact_evidence_prevalidated
            and payload["artifact_page"].get("artifact_id")
            != requested_artifact_id
        ):
            raise CommanderContractError(
                "INTERNAL_RESULT_INVALID",
                "Prevalidated artifact page does not match the requested handle.",
            )
        artifact_page = _normalize_artifact_page_fact(
            payload["artifact_page"],
            exact_evidence_prevalidated=exact_evidence_prevalidated,
        )
    is_review_manifest_read = tool_name == "review_manifest" or (
        tool_name == "run_mcp_workflow"
        and payload_workflow == "review_manifest"
        and payload_phase == "read"
    )
    subject_page: dict[str, Any] | None = None
    if is_review_manifest_read and isinstance(
        payload.get("subject_page"),
        dict,
    ):
        if exact_evidence_prevalidated:
            requested_page = safe_params.get("review_manifest_page", 1)
            requested_manifest_id = safe_params.get("review_manifest_id")
            if isinstance(requested_manifest_id, str):
                requested_manifest_id = requested_manifest_id.strip()
            raw_page = payload["subject_page"]
            if (
                raw_page.get("review_manifest_id")
                != requested_manifest_id
                or raw_page.get("subject_index")
                != safe_params.get("review_manifest_subject_index")
                or raw_page.get("page") != requested_page
            ):
                raise CommanderContractError(
                    "INTERNAL_RESULT_INVALID",
                    "Prevalidated manifest page does not match the requested subject.",
                )
        subject_page = _normalize_review_manifest_page_fact(
            payload["subject_page"],
            exact_evidence_prevalidated=exact_evidence_prevalidated,
        )
    facts_source: dict[str, Any] = {}
    source_summary = payload.get("summary")
    for key, value in payload.items():
        normalized_key = str(key)
        if normalized_key == "artifact_page" and artifact_page is not None:
            continue
        if normalized_key == "subject_page" and subject_page is not None:
            continue
        if normalized_key in _FACT_EXCLUDED_KEYS:
            continue
        facts_source[normalized_key] = value
    if isinstance(source_summary, dict):
        facts_source["source_summary"] = source_summary
    public = _public_value(
        facts_source,
        depth=0,
        strip_actions=True,
        facts=True,
    )
    facts = public if isinstance(public, dict) else {}
    if artifact_page is not None:
        facts["artifact_page"] = artifact_page
    if subject_page is not None:
        facts["subject_page"] = subject_page
    return facts


def _normalize_artifact_page_fact(
    value: dict[str, Any],
    *,
    exact_evidence_prevalidated: bool = False,
) -> dict[str, Any]:
    required = {
        "artifact_id",
        "tool",
        "page",
        "page_count",
        "page_char_start",
        "page_char_end",
        "content_sha256",
        "expires_at",
        "content",
    }
    if set(value) != required:
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "Result artifact page has an invalid shape.",
        )
    artifact_id = value.get("artifact_id")
    tool = value.get("tool")
    page = value.get("page")
    page_count = value.get("page_count")
    page_char_start = value.get("page_char_start")
    page_char_end = value.get("page_char_end")
    content_sha256 = value.get("content_sha256")
    expires_at = value.get("expires_at")
    content = value.get("content")
    if (
        not isinstance(artifact_id, str)
        or not _OPAQUE_ID_RE.fullmatch(artifact_id)
        or not isinstance(tool, str)
        or not tool.strip()
        or len(tool) > 128
        or tool not in _commander_tools()
        or isinstance(page, bool)
        or not isinstance(page, int)
        or isinstance(page_count, bool)
        or not isinstance(page_count, int)
        or page < 1
        or page_count < 1
        or page > page_count
        or isinstance(page_char_start, bool)
        or not isinstance(page_char_start, int)
        or isinstance(page_char_end, bool)
        or not isinstance(page_char_end, int)
        or page_char_start < 0
        or page_char_end < page_char_start
        or not isinstance(content_sha256, str)
        or not _SHA256_RE.fullmatch(content_sha256)
        or not isinstance(expires_at, str)
        or not _valid_expiry(expires_at)
        or not isinstance(content, str)
        or len(content) > COMMANDER_ARTIFACT_PAGE_MAX_CHARS
        or (
            not exact_evidence_prevalidated
            and _contains_unsafe_public_text(content)
        )
        or page_char_end - page_char_start != len(content)
    ):
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "Result artifact page fields are invalid.",
        )
    return {
        "artifact_id": artifact_id,
        "tool": tool,
        "page": page,
        "page_count": page_count,
        "page_char_start": page_char_start,
        "page_char_end": page_char_end,
        "content_sha256": content_sha256.lower(),
        "expires_at": expires_at,
        # Artifact pages are already bounded by the artifact store and must
        # remain byte-for-byte compatible with their published digest.
        "content": content,
    }


def _validate_artifact_page_binding(
    facts: dict[str, Any],
    evidence: Any,
    *,
    exact_evidence_prevalidated: bool = False,
) -> None:
    artifact_page = facts.get("artifact_page")
    if artifact_page is None:
        return
    if not isinstance(artifact_page, dict):
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "facts.artifact_page must be an object.",
        )
    normalized = _normalize_artifact_page_fact(
        artifact_page,
        exact_evidence_prevalidated=exact_evidence_prevalidated,
    )
    if normalized != artifact_page:
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "facts.artifact_page is not in canonical form.",
        )
    if (
        not isinstance(evidence, dict)
        or evidence.get("kind") != "result_artifact"
        or evidence.get("artifact_id") != artifact_page["artifact_id"]
        or evidence.get("page_count") != artifact_page["page_count"]
        or evidence.get("content_sha256") != artifact_page["content_sha256"]
        or evidence.get("expires_at") != artifact_page["expires_at"]
    ):
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "Artifact page facts do not match the opaque evidence descriptor.",
        )


def _normalize_review_manifest_page_fact(
    value: dict[str, Any],
    *,
    exact_evidence_prevalidated: bool = False,
) -> dict[str, Any]:
    required = {
        "review_manifest_id",
        "review_unit",
        "subject_index",
        "path",
        "sha256",
        "page",
        "page_count",
        "page_char_start",
        "page_char_end",
        "expires_at",
        "content",
    }
    if set(value) != required:
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "Review manifest subject page has an invalid shape.",
        )
    manifest_id = value.get("review_manifest_id")
    review_unit = value.get("review_unit")
    subject_index = value.get("subject_index")
    path = value.get("path")
    sha256 = value.get("sha256")
    page = value.get("page")
    page_count = value.get("page_count")
    page_char_start = value.get("page_char_start")
    page_char_end = value.get("page_char_end")
    expires_at = value.get("expires_at")
    content = value.get("content")
    if (
        not isinstance(manifest_id, str)
        or not _OPAQUE_ID_RE.fullmatch(manifest_id)
        or not isinstance(review_unit, str)
        or not review_unit.strip()
        or len(review_unit) > 160
        or isinstance(subject_index, bool)
        or not isinstance(subject_index, int)
        or subject_index < 1
        or not isinstance(path, str)
        or not path.strip()
        or len(path) > 1_000
        or path.startswith(("/", "\\"))
        or _PUBLIC_WINDOWS_PATH_RE.search(path)
        or any(part == ".." for part in path.replace("\\", "/").split("/"))
        or not isinstance(sha256, str)
        or not _SHA256_RE.fullmatch(sha256)
        or isinstance(page, bool)
        or not isinstance(page, int)
        or isinstance(page_count, bool)
        or not isinstance(page_count, int)
        or page < 1
        or page_count < 1
        or page > page_count
        or isinstance(page_char_start, bool)
        or not isinstance(page_char_start, int)
        or isinstance(page_char_end, bool)
        or not isinstance(page_char_end, int)
        or page_char_start < 0
        or page_char_end < page_char_start
        or not isinstance(expires_at, str)
        or not _valid_expiry(expires_at)
        or not isinstance(content, str)
        or len(content) > COMMANDER_ARTIFACT_PAGE_MAX_CHARS
        or (
            not exact_evidence_prevalidated
            and _contains_unsafe_public_text(content)
        )
        or page_char_end - page_char_start != len(content)
    ):
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "Review manifest subject page fields are invalid.",
        )
    return {
        "review_manifest_id": manifest_id,
        "review_unit": review_unit,
        "subject_index": subject_index,
        "path": path,
        "sha256": sha256.lower(),
        "page": page,
        "page_count": page_count,
        "page_char_start": page_char_start,
        "page_char_end": page_char_end,
        "expires_at": expires_at,
        # Review Manifest paging is hash-bound; preserve the exact page text.
        "content": content,
    }


def _validate_review_manifest_page_binding(
    facts: dict[str, Any],
    evidence: Any,
    *,
    exact_evidence_prevalidated: bool = False,
) -> None:
    subject_page = facts.get("subject_page")
    if subject_page is None:
        return
    if not isinstance(subject_page, dict):
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "facts.subject_page must be an object.",
        )
    normalized = _normalize_review_manifest_page_fact(
        subject_page,
        exact_evidence_prevalidated=exact_evidence_prevalidated,
    )
    if normalized != subject_page:
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "facts.subject_page is not in canonical form.",
        )
    if (
        not isinstance(evidence, dict)
        or evidence.get("kind") != "review_manifest"
        or evidence.get("review_manifest_id") != subject_page["review_manifest_id"]
        or evidence.get("expires_at") != subject_page["expires_at"]
    ):
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "Review manifest page facts do not match the opaque evidence descriptor.",
        )


def _normalize_evidence(raw_result: dict[str, Any]) -> dict[str, Any] | None:
    containers = _result_containers(raw_result)
    candidates: list[dict[str, Any]] = []
    for container in containers:
        existing = container.get("evidence")
        if isinstance(existing, dict):
            candidates.append(existing)
        descriptor = container.get("result_artifact")
        if isinstance(descriptor, dict):
            candidates.append(descriptor)
        candidates.append(container)

    evidence_error: CommanderContractError | None = None
    for candidate in candidates:
        kind = candidate.get("kind")
        try:
            if kind == "review_manifest" or "review_manifest_id" in candidate:
                review = _normalize_review_manifest_evidence(candidate)
                if review is not None:
                    return review
            if kind == "result_artifact" or "artifact_id" in candidate:
                artifact = _normalize_result_artifact_evidence(candidate)
                if artifact is not None:
                    return artifact
        except CommanderContractError as exc:
            # A transport wrapper may carry an incomplete handle while its
            # nested descriptor carries the complete evidence contract.
            evidence_error = exc

    if any(container.get("packaged") is True for container in containers):
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "Packaged result is missing its opaque result artifact contract.",
        )
    if evidence_error is not None:
        raise evidence_error
    return None


def _normalize_result_artifact_evidence(
    candidate: dict[str, Any],
) -> dict[str, Any] | None:
    artifact_id = candidate.get("artifact_id")
    resource_uri = candidate.get("resource_uri")
    page_uri_template = candidate.get("page_uri_template")
    artifact_page = candidate.get("artifact_page")
    if not isinstance(artifact_page, dict):
        artifact_page = {}
    page_count = candidate.get("page_count", artifact_page.get("page_count"))
    content_sha256 = candidate.get("content_sha256")
    expires_at = candidate.get("expires_at")
    if isinstance(artifact_id, str) and _OPAQUE_ID_RE.fullmatch(artifact_id):
        if resource_uri is None:
            resource_uri = f"colameta://result-artifact/{artifact_id}"
        if page_uri_template is None:
            page_uri_template = (
                f"colameta://result-artifact/{artifact_id}/pages/{{page}}"
            )
    values = (
        artifact_id,
        resource_uri,
        page_uri_template,
        page_count,
        content_sha256,
        expires_at,
    )
    if not any(value is not None for value in values):
        return None
    if (
        not isinstance(artifact_id, str)
        or not _OPAQUE_ID_RE.fullmatch(artifact_id)
        or not isinstance(resource_uri, str)
        or not isinstance(page_uri_template, str)
        or isinstance(page_count, bool)
        or not isinstance(page_count, int)
        or page_count < 1
        or not isinstance(content_sha256, str)
        or not _SHA256_RE.fullmatch(content_sha256)
        or not isinstance(expires_at, str)
        or not _valid_expiry(expires_at)
    ):
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "Result artifact evidence has an invalid shape.",
        )
    uri_match = _RESULT_ARTIFACT_URI_RE.fullmatch(resource_uri)
    template_match = _RESULT_ARTIFACT_PAGE_TEMPLATE_RE.fullmatch(page_uri_template)
    if (
        uri_match is None
        or template_match is None
        or uri_match.group("artifact_id") != artifact_id
        or template_match.group("artifact_id") != artifact_id
    ):
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "Result artifact URI binding is invalid.",
        )
    return {
        "kind": "result_artifact",
        "artifact_id": artifact_id,
        "resource_uri": resource_uri,
        "page_uri_template": page_uri_template,
        "page_count": page_count,
        "content_sha256": content_sha256.lower(),
        "expires_at": expires_at,
    }


def _normalize_review_manifest_evidence(
    candidate: dict[str, Any],
) -> dict[str, Any] | None:
    manifest_id = candidate.get("review_manifest_id")
    resource_uri = candidate.get("resource_uri")
    if not isinstance(resource_uri, str):
        resource_uri = candidate.get("manifest_resource_uri")
    if (
        resource_uri is None
        and isinstance(manifest_id, str)
        and _OPAQUE_ID_RE.fullmatch(manifest_id)
    ):
        resource_uri = f"colameta://review-manifest/{manifest_id}"
    manifest_sha256 = candidate.get("manifest_sha256")
    expires_at = candidate.get("expires_at")
    values = (manifest_id, resource_uri, manifest_sha256, expires_at)
    if not any(value is not None for value in values):
        return None
    if (
        not isinstance(manifest_id, str)
        or not _OPAQUE_ID_RE.fullmatch(manifest_id)
        or not isinstance(resource_uri, str)
        or not isinstance(manifest_sha256, str)
        or not _SHA256_RE.fullmatch(manifest_sha256)
        or not isinstance(expires_at, str)
        or not _valid_expiry(expires_at)
    ):
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "Review manifest evidence has an invalid shape.",
        )
    uri_match = _REVIEW_MANIFEST_URI_RE.fullmatch(resource_uri)
    if uri_match is None or uri_match.group("manifest_id") != manifest_id:
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "Review manifest URI binding is invalid.",
        )
    return {
        "kind": "review_manifest",
        "review_manifest_id": manifest_id,
        "resource_uri": resource_uri,
        "manifest_sha256": manifest_sha256.lower(),
        "expires_at": expires_at,
    }


def _valid_expiry(value: str) -> bool:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _normalize_confirmation(
    *,
    tool_name: str,
    raw_result: dict[str, Any],
    params: dict[str, Any],
    context_binding: dict[str, Any] | None,
    next_action: dict[str, Any] | None,
) -> dict[str, Any]:
    if context_binding is None or next_action is None:
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "confirmation_required must bind one public action to one project context.",
        )
    containers = _result_containers(raw_result)
    source: dict[str, Any] = {}
    for container in containers:
        confirmation = container.get("confirmation")
        if isinstance(confirmation, dict):
            source = confirmation
            break
    preview_id = _first_string(
        [source, *containers],
        ("preview_id", "gate_preview_id", "batch_preview_id"),
    )
    if preview_id is None:
        preview_id = _first_nested_string(
            [source, *containers],
            ("preview_id", "gate_preview_id", "batch_preview_id"),
        )
    if preview_id is None or not _PREVIEW_ID_RE.fullmatch(preview_id):
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "confirmation_required must include an opaque preview_id.",
        )
    action_arguments = next_action.get("arguments")
    action_preview_id = _confirmation_action_preview_id(action_arguments)
    if action_preview_id != preview_id:
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "confirmation preview_id does not match the selected apply action.",
        )
    action_context = (
        action_arguments.get("context_binding")
        if isinstance(action_arguments, dict)
        else None
    )
    if (
        _confirmation_action_requires_context_binding(next_action)
        and action_context != context_binding
    ):
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "confirmation action context does not match the response context.",
        )
    if action_context is not None and action_context != context_binding:
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "confirmation action exposes a mismatched project context.",
        )
    decision = _first_string(
        [source],
        ("decision", "prompt", "confirmation_prompt"),
    )
    if decision is None:
        decision = _default_confirmation_decision(tool_name, params)
    impact = _bounded_string_list(source.get("impact"))
    if not impact:
        impact = _default_confirmation_impact(tool_name, params)
    risks = _bounded_string_list(source.get("risks"))
    expires_at = source.get("expires_at")
    if not isinstance(expires_at, str):
        expires_at = _first_string(containers, ("expires_at",))
    if expires_at is not None and not _valid_expiry(expires_at):
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "confirmation expires_at is invalid.",
        )
    confirmation_context = source.get("context_binding")
    if isinstance(confirmation_context, dict):
        confirmation_context = _normalize_context_binding(confirmation_context)
    else:
        confirmation_context = copy.deepcopy(context_binding)
    if confirmation_context != context_binding:
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "confirmation context does not match the response context.",
        )
    result: dict[str, Any] = {
        "decision": _public_text(decision, max_chars=COMMANDER_SUMMARY_MAX_CHARS),
        "impact": impact,
        "preview_id": preview_id,
    }
    if risks:
        result["risks"] = risks
    if expires_at is not None:
        result["expires_at"] = expires_at
    result["context_binding"] = confirmation_context
    return result


def _default_confirmation_decision(
    tool_name: str,
    params: dict[str, Any],
) -> str:
    if tool_name == "manage_git":
        action = _normalized_string(params.get("action"))
        decisions = {
            "commit_preview": "是否创建当前预览绑定的本地 Git commit",
            "commit_apply": "是否创建当前预览绑定的本地 Git commit",
            "push_preview": "是否推送当前预览绑定的 Git 分支",
            "push_apply": "是否推送当前预览绑定的 Git 分支",
            "pull_preview": "是否执行当前预览绑定的 Git pull",
            "pull_apply": "是否执行当前预览绑定的 Git pull",
            "restore_file_preview": "是否恢复当前预览绑定的文件",
            "restore_file_apply": "是否恢复当前预览绑定的文件",
            "revert_preview": "是否创建当前预览绑定的 revert",
            "revert_apply": "是否创建当前预览绑定的 revert",
        }
        return decisions.get(action, "是否执行当前预览绑定的 Git 操作")
    if tool_name == "manage_validation_run":
        return "是否运行当前预览固定的验证命令"
    return "是否继续当前预览绑定的受控工作流"


def _default_confirmation_impact(
    tool_name: str,
    params: dict[str, Any],
) -> list[str]:
    if tool_name == "manage_git":
        action = _normalized_string(params.get("action"))
        if action.startswith("push_"):
            return ["将执行受控 Git push。", "不会替换稳定服务或发布软件包。"]
        if action.startswith("pull_"):
            return ["将执行受控 Git pull。", "执行前会重新验证项目上下文。"]
        if action.startswith(("restore_file_", "revert_")):
            return ["将修改当前 Git 工作区或历史。", "不会执行 Git push。"]
        return ["将创建一个本地 Git commit。", "不会执行 Git push。"]
    if tool_name == "manage_validation_run":
        return ["将运行当前预览固定的验证命令。", "不会创建 commit 或执行 push。"]
    return ["将执行与当前预览绑定的受控操作。"]


def _normalize_error(
    *,
    tool_name: str,
    outcome: str,
    raw_result: dict[str, Any],
    next_action: dict[str, Any] | None,
) -> dict[str, Any]:
    containers = _result_containers(raw_result)
    public_code = commander_public_error_code_for_result(raw_result)
    if public_code is None:
        public_code = _infer_blocker_error_code(_blocker_values(containers))
    if (
        outcome == "blocked"
        and tool_name == "manage_validation_run"
        and "failed" in _direct_status_values(containers)
        and public_code == "MANUAL_REVIEW_REQUIRED"
    ):
        public_code = "VALIDATION_FAILED"
    if outcome == "failed" and public_code not in _FAILED_PUBLIC_ERROR_CODES:
        public_code = "INTERNAL_ERROR"
    if outcome == "blocked" and public_code not in _BLOCKED_PUBLIC_ERROR_CODES:
        public_code = "MANUAL_REVIEW_REQUIRED"

    explicit_message = _raw_error_message(raw_result)
    if public_code in _FAILED_PUBLIC_ERROR_CODES:
        message = {
            "PUBLIC_PROJECTION_FAILED": "Commander 公共响应构建失败，内部诊断未公开。",
            "INTERNAL_RESULT_INVALID": "内部结果格式无效，无法安全建立公共响应。",
            "INTERNAL_ERROR": "工具执行失败，内部诊断未公开。",
        }[public_code]
    elif explicit_message is not None:
        message = _public_text(explicit_message, max_chars=COMMANDER_SUMMARY_MAX_CHARS)
    else:
        message = _default_public_error_message(public_code)

    explicit_recoverable: bool | None = None
    for container in containers:
        value = container.get("recoverable")
        if isinstance(value, bool):
            explicit_recoverable = value
            break
        error = container.get("error")
        if isinstance(error, dict) and isinstance(error.get("recoverable"), bool):
            explicit_recoverable = error["recoverable"]
            break
    recoverable = (
        explicit_recoverable
        if explicit_recoverable is not None
        else outcome == "blocked"
    )
    recovery = (
        copy.deepcopy(next_action)
        if next_action is not None and not _is_mutating_action(next_action)
        else None
    )
    result: dict[str, Any] = {
        "code": public_code,
        "message": message,
        "recoverable": recoverable,
    }
    if recovery is not None:
        result["recovery"] = recovery
    return result


def _infer_blocker_error_code(blockers: Iterable[str]) -> str:
    normalized = [item.strip().upper() for item in blockers]
    for value in normalized:
        if "WORKTREE" in value and "DIRTY" in value:
            return "WORKTREE_DIRTY"
        if "CONTEXT" in value and ("MISMATCH" in value or "STALE" in value):
            return "PROJECT_CONTEXT_MISMATCH"
        if "PREVIEW" in value and "EXPIRED" in value:
            return "PREVIEW_EXPIRED"
        if "PREVIEW" in value:
            return "PREVIEW_REQUIRED"
        if "SCOPE" in value:
            return "SCOPE_VIOLATION"
        if "VALIDATION" in value and "UNAVAILABLE" in value:
            return "VALIDATION_UNAVAILABLE"
        if "VALIDATION" in value:
            return "VALIDATION_FAILED"
        if "EXECUTOR" in value and "UNAVAILABLE" in value:
            return "EXECUTOR_UNAVAILABLE"
        if "EVIDENCE" in value:
            return "EVIDENCE_UNAVAILABLE"
    return "MANUAL_REVIEW_REQUIRED"


def _default_public_error_message(code: str) -> str:
    messages = {
        "PROJECT_REQUIRED": "必须先选择已登记项目。",
        "PROJECT_NOT_REGISTERED": "请求的项目未登记或当前不可用。",
        "PROJECT_MODE_UNSUPPORTED": "当前项目模式不支持该操作。",
        "PROJECT_CONTEXT_MISMATCH": "项目上下文已变化或不属于当前操作。",
        "STALE_CONTEXT": "当前上下文已过期，需要重新读取项目事实。",
        "STALE_PREVIEW": "当前预览已失效，需要重新生成。",
        "PREVIEW_REQUIRED": "该操作需要先生成有效预览。",
        "PREVIEW_EXPIRED": "当前预览已过期。",
        "WORKTREE_DIRTY": "当前工作区不满足操作前置条件。",
        "SCOPE_VIOLATION": "请求超出允许范围。",
        "VALIDATION_FAILED": "验证未通过，当前流程不能继续。",
        "VALIDATION_UNAVAILABLE": "当前无法运行所需验证。",
        "EXECUTOR_UNAVAILABLE": "当前执行器不可用。",
        "MANUAL_REVIEW_REQUIRED": "当前状态需要人工审查后才能继续。",
        "EVIDENCE_UNAVAILABLE": "当前无法建立所需证据。",
        "ARTIFACT_NOT_FOUND": "请求的结果证据不存在。",
        "ARTIFACT_EXPIRED": "请求的结果证据已过期。",
        "RESOURCE_URI_INVALID": "结果证据 URI 无效。",
        "TOOL_NOT_AVAILABLE": "请求的公共工具当前不可用。",
        "WORKFLOW_NOT_SUPPORTED": "请求的工作流不受支持。",
    }
    return messages.get(code, "当前调用被前置条件阻断。")


def _normalize_action(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    tool = value.get("tool")
    if not isinstance(tool, str) or tool not in _commander_tools():
        return None
    arguments = value.get("arguments")
    if not isinstance(arguments, dict):
        arguments = value.get("params")
    if not isinstance(arguments, dict):
        arguments = {}
    if _contains_noncommander_tool_reference(arguments):
        return None
    public_arguments = _public_value(
        arguments,
        depth=0,
        strip_actions=False,
        facts=False,
    )
    if not isinstance(public_arguments, dict):
        return None
    reason = value.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        reason = "继续当前受控流程。"
    return {
        "tool": tool,
        "arguments": public_arguments,
        "reason": _public_text(reason, max_chars=COMMANDER_REASON_MAX_CHARS),
    }


def _commander_tools() -> frozenset[str]:
    # The public inventory deliberately remains owned by mcp_commander_public.
    from runner.mcp_commander_public import COMMANDER_EXPOSED_TOOLS

    return frozenset(COMMANDER_EXPOSED_TOOLS)


def _contains_noncommander_tool_reference(value: Any) -> bool:
    if isinstance(value, dict):
        referenced_tool = value.get("tool")
        if (
            isinstance(referenced_tool, str)
            and referenced_tool
            and referenced_tool not in _commander_tools()
        ):
            return True
        return any(
            _contains_noncommander_tool_reference(nested)
            for nested in value.values()
        )
    if isinstance(value, list):
        return any(_contains_noncommander_tool_reference(item) for item in value)
    if isinstance(value, str):
        return bool(_INTERNAL_TOOL_REFERENCE_RE.search(value))
    return False


def _validate_action(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, dict) or set(value) != {
        "tool",
        "arguments",
        "reason",
    }:
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "next_action has an invalid shape.",
        )
    if value.get("tool") not in _commander_tools():
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "next_action references a non-Commander tool.",
        )
    arguments = value.get("arguments")
    if not isinstance(arguments, dict):
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "next_action.arguments must be an object.",
        )
    _validate_public_value(arguments, depth=0, facts=False)
    reason = value.get("reason")
    if (
        not isinstance(reason, str)
        or not reason.strip()
        or len(reason) > COMMANDER_REASON_MAX_CHARS
        or _contains_unsafe_public_text(reason)
    ):
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "next_action.reason is missing, oversized, or unsafe.",
        )


def _is_mutating_action(action: dict[str, Any]) -> bool:
    tool = action.get("tool")
    arguments = action.get("arguments")
    if not isinstance(arguments, dict):
        return False
    action_name = _normalized_string(arguments.get("action"))
    phase = _normalized_string(arguments.get("phase"))
    if tool == "manage_git":
        return action_name in _MUTATING_GIT_ACTIONS
    if tool == "manage_validation_run":
        return action_name == "run"
    if tool == "run_mcp_workflow":
        return phase in _CONFIRMATION_WORKFLOW_PHASES
    return False


def _is_confirmation_action(action: dict[str, Any]) -> bool:
    return _is_mutating_action(action)


def _confirmation_action_preview_id(arguments: Any) -> str | None:
    if not isinstance(arguments, dict):
        return None
    for key in ("preview_id", "gate_preview_id", "batch_preview_id"):
        value = arguments.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _confirmation_action_requires_context_binding(
    action: dict[str, Any],
) -> bool:
    if action.get("tool") != "run_mcp_workflow":
        return True
    arguments = action.get("arguments")
    if not isinstance(arguments, dict):
        return True
    workflow = _normalized_string(arguments.get("workflow"))
    return workflow not in {"gate_review_request", "operator_batch"}


def _is_poll_action(action: dict[str, Any]) -> bool:
    tool = action.get("tool")
    arguments = action.get("arguments")
    if not isinstance(arguments, dict):
        return False
    action_name = _normalized_string(arguments.get("action"))
    phase = _normalized_string(arguments.get("phase"))
    if tool in {"analyze_project_state", "get_apps_connector_smoke_packet"}:
        return True
    if tool == "manage_validation_run":
        return action_name == "status"
    if tool == "manage_git":
        return action_name in _POLL_GIT_ACTIONS
    if tool == "run_mcp_workflow":
        return phase == "status"
    if tool == "review_manifest":
        return phase == "status"
    return False


def _validate_confirmation(value: Any) -> None:
    if not isinstance(value, dict):
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "confirmation_required must include confirmation.",
        )
    required = {"decision", "impact", "preview_id", "context_binding"}
    allowed = required | {"risks", "expires_at"}
    if not required <= set(value) or not set(value) <= allowed:
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "confirmation has an invalid shape.",
        )
    decision = value.get("decision")
    if (
        not isinstance(decision, str)
        or not decision.strip()
        or len(decision) > COMMANDER_SUMMARY_MAX_CHARS
        or _contains_unsafe_public_text(decision)
    ):
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "confirmation.decision is invalid.",
        )
    impact = value.get("impact")
    if not isinstance(impact, list) or not impact:
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "confirmation.impact must be a non-empty list.",
        )
    _validate_string_list(impact, "confirmation.impact")
    preview_id = value.get("preview_id")
    if not isinstance(preview_id, str) or not _PREVIEW_ID_RE.fullmatch(preview_id):
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "confirmation.preview_id is invalid.",
        )
    risks = value.get("risks")
    if risks is not None:
        if not isinstance(risks, list):
            raise CommanderContractError(
                "INTERNAL_RESULT_INVALID",
                "confirmation.risks must be a list.",
            )
        _validate_string_list(risks, "confirmation.risks")
    expires_at = value.get("expires_at")
    if expires_at is not None and (
        not isinstance(expires_at, str) or not _valid_expiry(expires_at)
    ):
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "confirmation.expires_at is invalid.",
        )
    _validate_context_binding(value.get("context_binding"))


def _validate_confirmation_relationship(response: dict[str, Any]) -> None:
    confirmation = response.get("confirmation")
    next_action = response.get("next_action")
    context_binding = response.get("context_binding")
    if not isinstance(confirmation, dict) or not isinstance(next_action, dict):
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "confirmation_required must expose one bound confirmation action.",
        )
    arguments = next_action.get("arguments")
    if not isinstance(arguments, dict):
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "confirmation action arguments are missing.",
        )
    if confirmation.get("preview_id") != _confirmation_action_preview_id(
        arguments
    ):
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "confirmation.preview_id must match the next action preview handle.",
        )
    if confirmation.get("context_binding") != context_binding:
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "confirmation.context_binding must match response.context_binding.",
        )
    action_context = arguments.get("context_binding")
    if (
        _confirmation_action_requires_context_binding(next_action)
        and action_context != context_binding
    ):
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "next_action.context_binding must match response.context_binding.",
        )
    if action_context is not None and action_context != context_binding:
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "next_action cannot expose a mismatched context_binding.",
        )
    project_name = arguments.get("project_name")
    if (
        project_name is not None
        and isinstance(context_binding, dict)
        and project_name != context_binding.get("project_name")
    ):
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "next_action.project_name must match the bound project.",
        )


def _validate_error(value: Any) -> None:
    if not isinstance(value, dict):
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "blocked or failed must include error.",
        )
    required = {"code", "message", "recoverable"}
    allowed = required | {"recovery"}
    if not required <= set(value) or not set(value) <= allowed:
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "error has an invalid shape.",
        )
    if value.get("code") not in COMMANDER_PUBLIC_ERROR_CODES:
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "error.code is not a stable Commander public code.",
        )
    message = value.get("message")
    if (
        not isinstance(message, str)
        or not message.strip()
        or len(message) > COMMANDER_SUMMARY_MAX_CHARS
        or _contains_unsafe_public_text(message)
    ):
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "error.message is missing, oversized, or unsafe.",
        )
    if not isinstance(value.get("recoverable"), bool):
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "error.recoverable must be boolean.",
        )
    recovery = value.get("recovery")
    if recovery is not None:
        _validate_action(recovery)
        if _is_mutating_action(recovery):
            raise CommanderContractError(
                "INTERNAL_RESULT_INVALID",
                "error.recovery cannot be a mutation.",
            )


def _validate_evidence(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "evidence must be an object or null.",
        )
    kind = value.get("kind")
    if kind == "result_artifact":
        normalized = _normalize_result_artifact_evidence(value)
    elif kind == "review_manifest":
        normalized = _normalize_review_manifest_evidence(value)
    else:
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "Unknown Commander evidence kind.",
        )
    if normalized != value:
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "evidence is not in canonical public form.",
        )


def _validate_string_list(value: list[Any], field: str) -> None:
    if len(value) > COMMANDER_LIST_MAX_ITEMS:
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            f"{field} exceeds the public item limit.",
        )
    for item in value:
        if (
            not isinstance(item, str)
            or not item.strip()
            or len(item) > COMMANDER_TEXT_MAX_CHARS
            or _contains_unsafe_public_text(item)
        ):
            raise CommanderContractError(
                "INTERNAL_RESULT_INVALID",
                f"{field} contains an invalid item.",
            )


def _bounded_string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value[:COMMANDER_LIST_MAX_ITEMS]:
        if isinstance(item, str) and item.strip():
            result.append(_public_text(item, max_chars=COMMANDER_TEXT_MAX_CHARS))
    return result


def _public_value(
    value: Any,
    *,
    depth: int,
    strip_actions: bool,
    facts: bool,
) -> Any:
    if depth > COMMANDER_PUBLIC_MAX_DEPTH:
        return _OMIT
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else _OMIT
    if isinstance(value, str):
        return _public_text(value, max_chars=COMMANDER_TEXT_MAX_CHARS)
    if isinstance(value, list):
        result: list[Any] = []
        for item in value[:COMMANDER_LIST_MAX_ITEMS]:
            public = _public_value(
                item,
                depth=depth + 1,
                strip_actions=strip_actions,
                facts=facts,
            )
            if public is not _OMIT:
                result.append(public)
        return result
    if isinstance(value, dict):
        referenced_tool = value.get("tool")
        if (
            isinstance(referenced_tool, str)
            and referenced_tool
            and referenced_tool not in _commander_tools()
        ):
            return _OMIT
        result_dict: dict[str, Any] = {}
        for index, (key, nested) in enumerate(value.items()):
            if index >= COMMANDER_OBJECT_MAX_FIELDS:
                break
            clean_key = str(key)
            normalized_key = clean_key.strip().lower()
            if commander_public_key_is_forbidden(
                clean_key,
                include_internal_ids=facts,
            ):
                continue
            if strip_actions and normalized_key in _ACTION_CONTAINER_KEYS:
                continue
            public = _public_value(
                nested,
                depth=depth + 1,
                strip_actions=strip_actions,
                facts=facts,
            )
            if public is not _OMIT:
                result_dict[clean_key] = public
        return result_dict
    return _OMIT


def _validate_public_value(
    value: Any,
    *,
    depth: int,
    facts: bool,
    exact_evidence_prevalidated: bool = False,
) -> None:
    if depth > COMMANDER_PUBLIC_MAX_DEPTH:
        raise CommanderContractError(
            "INTERNAL_RESULT_INVALID",
            "Public value exceeds the nesting limit.",
        )
    if value is None or isinstance(value, (bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CommanderContractError(
                "INTERNAL_RESULT_INVALID",
                "Public value contains a non-finite number.",
            )
        return
    if isinstance(value, str):
        if len(value) > COMMANDER_TEXT_MAX_CHARS or _contains_unsafe_public_text(value):
            raise CommanderContractError(
                "INTERNAL_RESULT_INVALID",
                "Public value contains oversized or private text.",
            )
        return
    if isinstance(value, list):
        if len(value) > COMMANDER_LIST_MAX_ITEMS:
            raise CommanderContractError(
                "INTERNAL_RESULT_INVALID",
                "Public list exceeds the item limit.",
            )
        for item in value:
            _validate_public_value(
                item,
                depth=depth + 1,
                facts=facts,
                exact_evidence_prevalidated=exact_evidence_prevalidated,
            )
        return
    if isinstance(value, dict):
        if len(value) > COMMANDER_OBJECT_MAX_FIELDS:
            raise CommanderContractError(
                "INTERNAL_RESULT_INVALID",
                "Public object exceeds the field limit.",
            )
        referenced_tool = value.get("tool")
        if (
            isinstance(referenced_tool, str)
            and referenced_tool
            and referenced_tool not in _commander_tools()
        ):
            raise CommanderContractError(
                "INTERNAL_RESULT_INVALID",
                "Public value references a non-Commander tool.",
            )
        for key, nested in value.items():
            clean_key = str(key)
            normalized_key = clean_key.strip().lower()
            if commander_public_key_is_forbidden(
                clean_key,
                include_internal_ids=facts,
            ):
                raise CommanderContractError(
                    "INTERNAL_RESULT_INVALID",
                    f"Public value contains forbidden field {normalized_key}.",
                )
            if facts and normalized_key in _ACTION_CONTAINER_KEYS:
                raise CommanderContractError(
                    "INTERNAL_RESULT_INVALID",
                    "facts cannot contain nested next-action containers.",
                )
            if facts and depth == 0 and normalized_key == "artifact_page":
                if not isinstance(nested, dict):
                    raise CommanderContractError(
                        "INTERNAL_RESULT_INVALID",
                        "facts.artifact_page must be an object.",
                    )
                if (
                    _normalize_artifact_page_fact(
                        nested,
                        exact_evidence_prevalidated=(
                            exact_evidence_prevalidated
                        ),
                    )
                    != nested
                ):
                    raise CommanderContractError(
                        "INTERNAL_RESULT_INVALID",
                        "facts.artifact_page is not in canonical form.",
                    )
                continue
            if facts and depth == 0 and normalized_key == "subject_page":
                if not isinstance(nested, dict):
                    raise CommanderContractError(
                        "INTERNAL_RESULT_INVALID",
                        "facts.subject_page must be an object.",
                    )
                if (
                    _normalize_review_manifest_page_fact(
                        nested,
                        exact_evidence_prevalidated=(
                            exact_evidence_prevalidated
                        ),
                    )
                    != nested
                ):
                    raise CommanderContractError(
                        "INTERNAL_RESULT_INVALID",
                        "facts.subject_page is not in canonical form.",
                    )
                continue
            _validate_public_value(
                nested,
                depth=depth + 1,
                facts=facts,
                exact_evidence_prevalidated=exact_evidence_prevalidated,
            )
        return
    raise CommanderContractError(
        "INTERNAL_RESULT_INVALID",
        "Public value contains a non-JSON type.",
    )


def _normalize_public_key_for_match(value: Any) -> str:
    key = str(value).strip()
    key = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", key)
    key = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", "_", key)
    return re.sub(
        r"[^a-z0-9]+",
        "_",
        key.lower(),
    ).strip("_")


def commander_public_key_is_forbidden(
    value: Any,
    *,
    include_internal_ids: bool = False,
) -> bool:
    """Return whether an object key is unsafe at the Commander boundary."""

    key = str(value)
    normalized = key.strip().lower()
    normalized_for_match = _normalize_public_key_for_match(key)
    if (
        not normalized
        or normalized_for_match in _FORBIDDEN_PUBLIC_KEYS
        or _SENSITIVE_PUBLIC_KEY_RE.search(normalized_for_match)
        or _contains_private_path(key)
    ):
        return True
    if (
        include_internal_ids
        and normalized_for_match not in _ALLOWED_PUBLIC_OPAQUE_ID_KEYS
        and (
            normalized_for_match in _FACT_INTERNAL_ID_KEYS
            or _INTERNAL_ID_PUBLIC_KEY_RE.fullmatch(
                normalized_for_match
            )
        )
    ):
        return True
    return False


def _redact_noncommander_tool_references(
    value: str,
    *,
    forbidden_tools: Iterable[str] | None = None,
) -> str:
    redacted = _INTERNAL_TOOL_REFERENCE_RE.sub("<internal-tool>", value)
    hidden_tools = (
        frozenset(forbidden_tools)
        if forbidden_tools is not None
        else frozenset()
    )

    def replace(match: re.Match[str]) -> str:
        name = match.group("name")
        if name in _commander_tools():
            return name
        if name in hidden_tools:
            return "<internal-tool>"
        return name

    return _TOOL_LIKE_IDENTIFIER_RE.sub(replace, redacted)


def commander_public_text(
    value: str,
    *,
    max_chars: int | None = None,
    preserve_whitespace: bool = True,
    forbidden_tools: Iterable[str] | None = None,
) -> str:
    """Redact unsafe public text, optionally preserving exact line structure."""

    normalized = str(value)
    if not preserve_whitespace:
        normalized = " ".join(normalized.split())
    redacted = _redact_public_text_preserving_resource_uris(
        normalized,
        forbidden_tools=forbidden_tools,
    )
    if max_chars is None:
        return redacted
    if len(redacted) <= max_chars:
        return redacted
    if max_chars <= 1:
        return redacted[:max_chars]
    return _truncate_public_text_preserving_resource_uris(
        redacted,
        max_chars=max_chars,
    )


def _public_text(value: str, *, max_chars: int) -> str:
    return commander_public_text(
        value,
        max_chars=max_chars,
        preserve_whitespace=False,
    )


def _public_summary(value: str) -> str:
    public = _public_text(value, max_chars=COMMANDER_SUMMARY_MAX_CHARS)
    endings = list(_SUMMARY_SENTENCE_END_RE.finditer(public))
    if len(endings) <= 3:
        return public
    return public[: endings[2].end()].strip()


def _summary_sentence_count(value: str) -> int:
    count = len(_SUMMARY_SENTENCE_END_RE.findall(value))
    return max(1, count)


def _redact_public_path_segment_once(value: str) -> str:
    redacted = _PUBLIC_FILE_URI_RE.sub("<local-path>", value)
    redacted = _PUBLIC_UNC_PATH_RE.sub("<local-path>", redacted)
    redacted = _PUBLIC_POSIX_PATH_RE.sub("<local-path>", redacted)
    return _PUBLIC_WINDOWS_PATH_RE.sub("<local-path>", redacted)


def _segment_contains_private_path(value: str) -> bool:
    return bool(
        _PUBLIC_FILE_URI_RE.search(value)
        or _PUBLIC_UNC_PATH_RE.search(value)
        or _PUBLIC_POSIX_PATH_RE.search(value)
        or _PUBLIC_WINDOWS_PATH_RE.search(value)
    )


def _scan_nested_json_escape(
    value: str,
    index: int,
) -> tuple[int, str | None]:
    if index >= len(value) or value[index] != "\\":
        return index, None
    cursor = index
    while cursor < len(value) and value[cursor] == "\\":
        cursor += 1
    if cursor >= len(value):
        return cursor, None
    token = value[cursor]
    if token == "u":
        digits = value[cursor + 1 : cursor + 5]
        if len(digits) == 4 and all(
            character in "0123456789abcdefABCDEF"
            for character in digits
        ):
            return cursor + 5, chr(int(digits, 16))
        return cursor, None
    decoded = _PUBLIC_JSON_SHORT_ESCAPE_CHARACTERS.get(token)
    if decoded is None:
        return cursor, None
    return cursor + 1, decoded


def _nested_json_escape_tokens(
    value: str,
) -> Iterable[tuple[int, int, str]]:
    cursor = 0
    while cursor < len(value):
        start = value.find("\\", cursor)
        if start < 0:
            return
        end, decoded = _scan_nested_json_escape(value, start)
        if decoded is not None:
            yield start, end, decoded
            cursor = end
            continue
        cursor = max(start + 1, end)


def _decode_json_escapes_with_stack(
    value: str,
    *,
    collapse_escaped_backslashes: bool,
) -> str:
    rebuilt: list[str] = []
    changed = False
    for character in value:
        rebuilt.append(character)
        while True:
            if (
                len(rebuilt) >= 6
                and rebuilt[-6] == "\\"
                and rebuilt[-5] == "u"
                and all(
                    digit in "0123456789abcdefABCDEF"
                    for digit in rebuilt[-4:]
                )
            ):
                decoded = chr(int("".join(rebuilt[-4:]), 16))
                del rebuilt[-6:]
                rebuilt.append(decoded)
                changed = True
                continue
            if (
                len(rebuilt) >= 2
                and rebuilt[-2] == "\\"
                and rebuilt[-1] in _PUBLIC_JSON_SHORT_ESCAPE_CHARACTERS
                and (
                    rebuilt[-1] != "\\"
                    or collapse_escaped_backslashes
                )
            ):
                decoded = _PUBLIC_JSON_SHORT_ESCAPE_CHARACTERS[rebuilt[-1]]
                del rebuilt[-2:]
                rebuilt.append(decoded)
                changed = True
                continue
            break
    return "".join(rebuilt) if changed else value


def _decode_escaped_backslash_layer(value: str) -> str:
    rebuilt: list[str] = []
    cursor = 0
    changed = False
    while cursor < len(value):
        if value[cursor : cursor + 2] == "\\\\":
            rebuilt.append("\\")
            cursor += 2
            changed = True
            continue
        rebuilt.append(value[cursor])
        cursor += 1
    return "".join(rebuilt) if changed else value


def _json_escape_decoded_candidates(value: str) -> Iterable[str]:
    # First decode escape-generated introducers while retaining backslash
    # pairs.  Then decode escaped-backslash pairs one serialization layer at a
    # time: four serialized leading backslashes must be observable as the UNC
    # pair before a later layer collapses it to one.  The final fixed point
    # catches other escape-generated absolute paths without recursive suffix
    # rescans.
    preserved_backslashes = _decode_json_escapes_with_stack(
        value,
        collapse_escaped_backslashes=False,
    )
    if preserved_backslashes != value:
        yield preserved_backslashes
    candidate = preserved_backslashes
    while True:
        decoded = _decode_escaped_backslash_layer(candidate)
        if decoded == candidate:
            break
        yield decoded
        candidate = decoded
    fixed_point = _decode_json_escapes_with_stack(
        value,
        collapse_escaped_backslashes=True,
    )
    if fixed_point not in {value, preserved_backslashes, candidate}:
        yield fixed_point


def _json_escape_is_path_boundary(decoded: str) -> bool:
    # Mirror the characters that block an absolute POSIX path at its left edge.
    return not (
        decoded.isascii()
        and (decoded.isalnum() or decoded in ":/\\")
    )


def _json_escaped_path_boundary_matches(
    value: str,
) -> Iterable[tuple[int, int]]:
    return (
        (start, end)
        for start, end, decoded in _nested_json_escape_tokens(value)
        if _json_escape_is_path_boundary(decoded)
    )


def _segment_or_json_boundary_contains_private_path(value: str) -> bool:
    cursor = 0
    for start, end in _json_escaped_path_boundary_matches(value):
        if _segment_contains_private_path(value[cursor:start]):
            return True
        cursor = end
    return _segment_contains_private_path(value[cursor:])


def _contains_private_path_segment(value: str) -> bool:
    if _segment_or_json_boundary_contains_private_path(value):
        return True
    return any(
        _segment_or_json_boundary_contains_private_path(candidate)
        for candidate in _json_escape_decoded_candidates(value)
    )


def _redact_public_path_segment_with_json_boundaries(value: str) -> str:
    rebuilt: list[str] = []
    cursor = 0
    for start, end in _json_escaped_path_boundary_matches(value):
        rebuilt.append(
            _redact_public_path_segment_once(
                value[cursor:start]
            )
        )
        rebuilt.append(value[start:end])
        cursor = end
    if rebuilt:
        rebuilt.append(_redact_public_path_segment_once(value[cursor:]))
        return "".join(rebuilt)
    return _redact_public_path_segment_once(value)


def _redact_public_path_segment(value: str) -> str:
    redacted = _redact_public_path_segment_with_json_boundaries(value)
    if any(
        _segment_or_json_boundary_contains_private_path(candidate)
        for candidate in _json_escape_decoded_candidates(redacted)
    ):
        return "<local-path>"
    return redacted


def _is_unicode_resource_uri_emoji_base(value: str) -> bool:
    if len(value) != 1:
        return False
    codepoint = ord(value)
    range_index = bisect_right(
        _PUBLIC_RESOURCE_URI_EMOJI_BASE_STARTS,
        codepoint,
    ) - 1
    return bool(
        range_index >= 0
        and codepoint
        <= _PUBLIC_RESOURCE_URI_EMOJI_BASE_RANGES[range_index][1]
    )


def _is_unicode_resource_uri_delimiter(value: str) -> bool:
    return (
        bool(value)
        and not value.isascii()
        and (
            value in _PUBLIC_RESOURCE_URI_UNICODE_SENTENCE_DELIMITERS
            or unicodedata.category(value) in {"Pd", "Pe", "Pf", "Pi", "Ps"}
            or _is_unicode_resource_uri_emoji_base(value)
        )
    )


def _is_unicode_resource_uri_prose(value: str) -> bool:
    return bool(
        value
        and not value.isascii()
        and unicodedata.category(value).startswith(("L", "N"))
    )


def _is_unicode_emoji_sequence_component(value: str) -> bool:
    if not value:
        return False
    codepoint = ord(value)
    return bool(
        value == "\u200d"
        or 0xFE00 <= codepoint <= 0xFE0F
        or 0xE0100 <= codepoint <= 0xE01EF
        or 0x1F3FB <= codepoint <= 0x1F3FF
        or 0xE0020 <= codepoint <= 0xE007F
    )


def _is_unicode_resource_uri_prose_mark(value: str) -> bool:
    return bool(
        value
        and not value.isascii()
        and value != "\u20e3"
        and not _is_unicode_emoji_sequence_component(value)
        and unicodedata.category(value).startswith("M")
    )


def _resource_character_with_start_ending_at(
    value: str,
    index: int,
) -> tuple[int, str] | None:
    decoded = _decoded_json_unicode_character_with_start_ending_at(
        value,
        index,
    )
    if decoded is None:
        decoded = _decoded_json_short_character_with_start_ending_at(
            value,
            index,
        )
    if decoded is not None:
        return decoded
    if index <= 0:
        return None
    return index - 1, value[index - 1]


def _resource_character_with_end_at(
    value: str,
    index: int,
) -> tuple[int, str] | None:
    decoded = _decoded_json_unicode_character_with_end_at(value, index)
    if decoded is not None:
        return decoded
    if index >= len(value):
        return None
    return index + 1, value[index]


def _complete_keycap_sequence_start_ending_at(
    value: str,
    index: int,
) -> int | None:
    current = _resource_character_with_start_ending_at(value, index)
    if current is None or current[1] != "\u20e3":
        return None
    cursor = current[0]
    current = _resource_character_with_start_ending_at(value, cursor)
    if current is not None and current[1] == "\ufe0f":
        cursor = current[0]
        current = _resource_character_with_start_ending_at(value, cursor)
    if current is None or current[1] not in "#*0123456789":
        return None
    return current[0]


def _complete_keycap_sequence_end_at(
    value: str,
    index: int,
) -> int | None:
    current = _resource_character_with_end_at(value, index)
    if current is None or current[1] not in "#*0123456789":
        return None
    cursor = current[0]
    current = _resource_character_with_end_at(value, cursor)
    if current is not None and current[1] == "\ufe0f":
        cursor = current[0]
        current = _resource_character_with_end_at(value, cursor)
    if current is None or current[1] != "\u20e3":
        return None
    return current[0]


def _is_resource_uri_whitespace(value: str) -> bool:
    return value.isspace() or value in {"\u200b", "\ufeff"}


def _is_resource_uri_left_boundary_character(value: str) -> bool:
    category = unicodedata.category(value)
    if (
        _is_resource_uri_whitespace(value)
        or value in "\"'`<>([{"
        or value in _PUBLIC_RESOURCE_URI_ASCII_CLOSING_DELIMITERS
        or category == "Cc"
    ):
        return True
    return bool(
        not value.isascii()
        and (
            category.startswith(("L", "N"))
            or value in _PUBLIC_RESOURCE_URI_UNICODE_SENTENCE_DELIMITERS
            or category in {"Pd", "Pe", "Pf", "Pi", "Ps"}
            or _is_unicode_resource_uri_emoji_base(value)
        )
    )


def _json_unicode_escape_ending_at(
    value: str,
    index: int,
) -> tuple[int, int] | None:
    token_start = index - 5
    if token_start < 1 or value[token_start] != "u":
        return None
    escape_start = token_start
    while escape_start > 0 and value[escape_start - 1] == "\\":
        escape_start -= 1
    if escape_start == token_start:
        return None
    end, decoded = _scan_nested_json_escape(value, escape_start)
    if end != index or decoded is None:
        return None
    return escape_start, ord(decoded)


def _decoded_json_short_character_with_start_ending_at(
    value: str,
    index: int,
) -> tuple[int, str] | None:
    if index <= 1:
        return None
    token = value[index - 1]
    if token not in _PUBLIC_JSON_SHORT_ESCAPE_CHARACTERS:
        return None
    escape_start = index - 1
    while escape_start > 0 and value[escape_start - 1] == "\\":
        escape_start -= 1
    if escape_start == index - 1:
        return None
    end, decoded = _scan_nested_json_escape(value, escape_start)
    if end != index or decoded is None:
        return None
    return escape_start, decoded


def _json_unicode_escape_at(
    value: str,
    index: int,
) -> tuple[int, int] | None:
    cursor = index
    while cursor < len(value) and value[cursor] == "\\":
        cursor += 1
    if cursor >= len(value) or value[cursor] != "u":
        return None
    end, decoded = _scan_nested_json_escape(value, index)
    if decoded is None:
        return None
    return end, ord(decoded)


def _decoded_json_unicode_character_with_start_ending_at(
    value: str,
    index: int,
) -> tuple[int, str] | None:
    current = _json_unicode_escape_ending_at(value, index)
    if current is None:
        return None
    start, codepoint = current
    if 0xDC00 <= codepoint <= 0xDFFF:
        previous = _json_unicode_escape_ending_at(value, start)
        if previous is not None:
            previous_start, high = previous
            if 0xD800 <= high <= 0xDBFF:
                combined = (
                    0x10000
                    + ((high - 0xD800) << 10)
                    + (codepoint - 0xDC00)
                )
                return previous_start, chr(combined)
    return start, chr(codepoint)


def _decoded_json_unicode_character_ending_at(
    value: str,
    index: int,
) -> str | None:
    decoded = _decoded_json_unicode_character_with_start_ending_at(
        value,
        index,
    )
    return decoded[1] if decoded is not None else None


def _decoded_json_unicode_character_with_end_at(
    value: str,
    index: int,
) -> tuple[int, str] | None:
    current = _json_unicode_escape_at(value, index)
    if current is None:
        return None
    end, codepoint = current
    if 0xD800 <= codepoint <= 0xDBFF:
        following = _json_unicode_escape_at(value, end)
        if following is not None:
            following_end, low = following
            if 0xDC00 <= low <= 0xDFFF:
                combined = (
                    0x10000
                    + ((codepoint - 0xD800) << 10)
                    + (low - 0xDC00)
                )
                return following_end, chr(combined)
    return end, chr(codepoint)


def _decoded_json_unicode_character_at(
    value: str,
    index: int,
) -> str | None:
    decoded = _decoded_json_unicode_character_with_end_at(value, index)
    return decoded[1] if decoded is not None else None


def _is_resource_uri_left_boundary(value: str, index: int) -> bool:
    if index <= 0:
        return True
    if _complete_keycap_sequence_start_ending_at(value, index) is not None:
        return True
    current = _resource_character_with_start_ending_at(value, index)
    if current is None:
        return True
    cursor, preceding = current
    if _is_resource_uri_left_boundary_character(preceding):
        return True
    if _is_unicode_resource_uri_prose_mark(preceding):
        while cursor > 0:
            current = _resource_character_with_start_ending_at(value, cursor)
            if current is None:
                return False
            cursor, preceding = current
            if _is_unicode_resource_uri_prose_mark(preceding):
                continue
            return bool(
                _is_unicode_resource_uri_prose(preceding)
                or (
                    preceding.isascii()
                    and preceding.isalpha()
                )
            )
        return False
    if (
        preceding == "\u200d"
        or not _is_unicode_emoji_sequence_component(preceding)
    ):
        return False
    while cursor > 0:
        current = _resource_character_with_start_ending_at(value, cursor)
        if current is None:
            return False
        cursor, preceding = current
        if _is_unicode_resource_uri_emoji_base(preceding):
            return True
        if (
            preceding == "\u200d"
            or not _is_unicode_emoji_sequence_component(preceding)
        ):
            return False
    return False


def _is_resource_uri_hard_delimiter(value: str) -> bool:
    return bool(
        _is_resource_uri_whitespace(value)
        or unicodedata.category(value) == "Cc"
        or value in "\"'`>"
        or value in _PUBLIC_RESOURCE_URI_ASCII_OPENING_DELIMITERS
    )


def _json_escaped_resource_delimiter(
    value: str,
    index: int,
) -> tuple[int, str] | None:
    unicode_escape = _decoded_json_unicode_character_with_end_at(
        value,
        index,
    )
    if unicode_escape is not None:
        end, decoded = unicode_escape
    else:
        end, decoded = _scan_nested_json_escape(value, index)
        if decoded is None:
            return None
    if (
        _is_resource_uri_hard_delimiter(decoded)
        or decoded in ".,;:!?)]}"
        or _is_unicode_resource_uri_delimiter(decoded)
        or _is_unicode_emoji_sequence_component(decoded)
    ):
        return end, decoded
    return None


def _is_json_escaped_resource_delimiter(value: str, index: int) -> bool:
    return _json_escaped_resource_delimiter(value, index) is not None


def _is_resource_uri_following_delimiter(value: str, index: int) -> bool:
    cursor = index
    ascii_before_unicode_delimiter = False
    saw_unicode_delimiter = False
    saw_emoji_base = False
    emoji_joiner_pending = False
    saw_hard_escaped_delimiter = False
    while cursor < len(value):
        keycap_end = _complete_keycap_sequence_end_at(value, cursor)
        if keycap_end is not None:
            if emoji_joiner_pending:
                break
            saw_unicode_delimiter = True
            saw_emoji_base = False
            cursor = keycap_end
            continue
        following = value[cursor]
        if following in ".,;:!?)]}":
            if not saw_unicode_delimiter:
                ascii_before_unicode_delimiter = True
            saw_emoji_base = False
            cursor += 1
            continue
        if _is_unicode_resource_uri_delimiter(following):
            is_emoji_base = _is_unicode_resource_uri_emoji_base(
                following
            )
            if (
                emoji_joiner_pending
                and not is_emoji_base
            ):
                break
            saw_unicode_delimiter = True
            saw_emoji_base = is_emoji_base
            if is_emoji_base:
                emoji_joiner_pending = False
            cursor += 1
            continue
        if (
            saw_emoji_base
            and _is_unicode_emoji_sequence_component(following)
        ):
            if emoji_joiner_pending:
                break
            emoji_joiner_pending = following == "\u200d"
            cursor += 1
            continue
        escaped_delimiter = _json_escaped_resource_delimiter(
            value,
            cursor,
        )
        if escaped_delimiter is not None:
            end, decoded = escaped_delimiter
            if _is_unicode_emoji_sequence_component(decoded):
                if not saw_emoji_base or emoji_joiner_pending:
                    break
                emoji_joiner_pending = decoded == "\u200d"
                cursor = end
                continue
            if _is_resource_uri_hard_delimiter(decoded):
                saw_hard_escaped_delimiter = True
                saw_emoji_base = False
            elif _is_unicode_resource_uri_delimiter(decoded):
                is_emoji_base = _is_unicode_resource_uri_emoji_base(
                    decoded
                )
                if (
                    emoji_joiner_pending
                    and not is_emoji_base
                ):
                    break
                saw_unicode_delimiter = True
                saw_emoji_base = is_emoji_base
                if is_emoji_base:
                    emoji_joiner_pending = False
            else:
                if not saw_unicode_delimiter:
                    ascii_before_unicode_delimiter = True
                saw_emoji_base = False
            cursor = end
            continue
        break
    if emoji_joiner_pending:
        return False
    if cursor >= len(value):
        return True
    following = value[cursor]
    decoded_following = _decoded_json_unicode_character_at(value, cursor)
    return bool(
        _is_resource_uri_whitespace(following)
        or following in "\"'`>"
        or saw_hard_escaped_delimiter
        or (
            saw_unicode_delimiter
            # A preceding ASCII punctuation run can still be an invalid URI
            # continuation (for example, ``??）query``).
            and not ascii_before_unicode_delimiter
            and (
                unicodedata.category(following).startswith(("L", "N"))
                or (
                    decoded_following is not None
                    and unicodedata.category(decoded_following).startswith(
                        ("L", "N")
                    )
                )
            )
        )
    )


def _is_resource_uri_boundary(value: str, index: int) -> bool:
    if index >= len(value):
        return True
    following = value[index]
    if _is_resource_uri_hard_delimiter(following):
        return True
    if _is_unicode_resource_uri_prose(following):
        return True
    decoded_following = _decoded_json_unicode_character_at(value, index)
    if (
        decoded_following is not None
        and _is_unicode_resource_uri_prose(decoded_following)
    ):
        return True
    if _complete_keycap_sequence_end_at(value, index) is not None:
        return _is_resource_uri_following_delimiter(value, index)
    if (
        following in ".,;:!?)]}"
        or _is_unicode_resource_uri_delimiter(following)
        or _is_json_escaped_resource_delimiter(value, index)
    ):
        return _is_resource_uri_following_delimiter(value, index)
    return False


def _public_resource_uri_spans(value: str) -> Iterable[re.Match[str]]:
    for match in _PUBLIC_OPAQUE_RESOURCE_URI_CANDIDATE_RE.finditer(value):
        if _is_resource_uri_left_boundary(
            value,
            match.start(),
        ) and _is_resource_uri_boundary(value, match.end()):
            yield match


def _truncate_public_text_preserving_resource_uris(
    value: str,
    *,
    max_chars: int,
) -> str:
    bounded = value
    cutoff = max_chars - 1
    while len(bounded) > max_chars:
        crossing = next(
            (
                match
                for match in _public_resource_uri_spans(bounded)
                if match.start() < cutoff < match.end()
            ),
            None,
        )
        if crossing is None:
            return f"{bounded[:cutoff]}…"
        bounded = (
            f"{bounded[: crossing.start()]}"
            f"{_PUBLIC_RESOURCE_URI_PLACEHOLDER}"
            f"{bounded[crossing.end() :]}"
        )
    return bounded


def _redact_public_non_resource_segment(
    value: str,
    *,
    forbidden_tools: Iterable[str] | None,
) -> str:
    redacted = _PUBLIC_COLAMETA_URI_TOKEN_RE.sub(
        _PUBLIC_RESOURCE_URI_PLACEHOLDER,
        value,
    )
    redacted = _redact_public_path_segment(redacted)
    if _decoded_candidate_contains_noncommander_tool_reference(
        redacted,
        forbidden_tools=forbidden_tools,
    ):
        return "<internal-tool>"
    redacted = _redact_noncommander_tool_references(
        redacted,
        forbidden_tools=forbidden_tools,
    )
    return _redact_sensitive_material(redacted)


def _decoded_candidate_contains_noncommander_tool_reference(
    value: str,
    *,
    forbidden_tools: Iterable[str] | None = None,
) -> bool:
    hidden_tools = (
        None
        if forbidden_tools is None
        else frozenset(forbidden_tools)
    )
    return bool(
        "\\" in value
        and any(
            _redact_noncommander_tool_references(
                candidate,
                forbidden_tools=hidden_tools,
            )
            != candidate
            for candidate in _json_escape_decoded_candidates(value)
        )
    )


def _matches_sensitive_material(value: str) -> bool:
    return bool(
        _SENSITIVE_HEADER_ASSIGNMENT_RE.search(value)
        or _SENSITIVE_ASSIGNMENT_RE.search(value)
        or _contains_forbidden_key_assignment(value)
        or _contains_sensitive_cli_option_credential(value)
        or _BEARER_TOKEN_RE.search(value)
        or _contains_basic_authorization_credential(value)
        or _PRIVATE_KEY_BLOCK_RE.search(value)
        or _PUTTY_PRIVATE_KEY_FILE_RE.search(value)
        or _contains_standalone_jwt(value)
        or _CREDENTIAL_URI_USERINFO_RE.search(value)
    )


def _decoded_candidate_contains_sensitive_material(value: str) -> bool:
    return bool(
        "\\" in value
        and any(
            _matches_sensitive_material(candidate)
            for candidate in _json_escape_decoded_candidates(value)
        )
    )


def _is_basic_authorization_credential(match: re.Match[str]) -> bool:
    token = match.group("token").rstrip("=")
    if not token:
        return False
    padded = token + ("=" * (-len(token) % 4))
    try:
        decoded = base64.b64decode(padded, validate=True)
    except (binascii.Error, ValueError):
        return False
    return b":" in decoded


def _contains_basic_authorization_credential(value: str) -> bool:
    return any(
        _is_basic_authorization_credential(match)
        for match in _BASIC_AUTHORIZATION_RE.finditer(value)
    )


def _base64url_json_object(value: str) -> dict[str, Any] | None:
    padded = value + ("=" * (-len(value) % 4))
    try:
        decoded = base64.b64decode(
            padded,
            altchars=b"-_",
            validate=True,
        )
        parsed = json.loads(decoded.decode("utf-8"))
    except (
        binascii.Error,
        RecursionError,
        UnicodeDecodeError,
        ValueError,
    ):
        return None
    return parsed if isinstance(parsed, dict) else None


def _is_standalone_jwt(match: re.Match[str]) -> bool:
    header = _base64url_json_object(match.group("header"))
    payload = _base64url_json_object(match.group("payload"))
    return bool(
        header is not None
        and payload is not None
        and isinstance(header.get("alg"), str)
        and header["alg"].strip()
    )


def _contains_standalone_jwt(value: str) -> bool:
    return any(
        _is_standalone_jwt(match)
        for match in _STANDALONE_JWT_RE.finditer(value)
    )


def _redact_basic_authorization_credentials(value: str) -> str:
    return _BASIC_AUTHORIZATION_RE.sub(
        lambda match: (
            "<sensitive>"
            if _is_basic_authorization_credential(match)
            else match.group(0)
        ),
        value,
    )


def _assignment_key(match: re.Match[str]) -> str:
    return str(match.group("quoted_key") or match.group("bare_key") or "")


def _contains_forbidden_key_assignment(value: str) -> bool:
    return any(
        commander_public_key_is_forbidden(_assignment_key(match))
        for match in _ASSIGNMENT_KEY_RE.finditer(value)
    )


def _contains_sensitive_cli_option_credential(value: str) -> bool:
    return any(
        commander_public_key_is_forbidden(match.group("key"))
        for match in _SENSITIVE_CLI_OPTION_RE.finditer(value)
    )


def _redact_sensitive_material(value: str) -> str:
    if (
        _SENSITIVE_HEADER_ASSIGNMENT_RE.search(value)
        or _SENSITIVE_ASSIGNMENT_RE.search(value)
        or _contains_forbidden_key_assignment(value)
        or _PRIVATE_KEY_BLOCK_RE.search(value)
        or _PUTTY_PRIVATE_KEY_FILE_RE.search(value)
        or _contains_standalone_jwt(value)
        or _CREDENTIAL_URI_USERINFO_RE.search(value)
        or _contains_sensitive_cli_option_credential(value)
    ):
        return "<sensitive>"
    redacted = value
    redacted = _BEARER_TOKEN_RE.sub("<sensitive>", redacted)
    redacted = _redact_basic_authorization_credentials(redacted)
    if _decoded_candidate_contains_sensitive_material(value):
        return "<sensitive>"
    return redacted


def _redact_public_text_preserving_resource_uris(
    value: str,
    *,
    forbidden_tools: Iterable[str] | None,
) -> str:
    value = _redact_sensitive_material(value)
    if _decoded_candidate_contains_disallowed_public_resource_uri(value):
        return _PUBLIC_RESOURCE_URI_PLACEHOLDER
    parts: list[str] = []
    cursor = 0
    for match in _public_resource_uri_spans(value):
        parts.append(
            _redact_public_non_resource_segment(
                value[cursor : match.start()],
                forbidden_tools=forbidden_tools,
            )
        )
        parts.append(match.group(0))
        cursor = match.end()
    parts.append(
        _redact_public_non_resource_segment(
            value[cursor:],
            forbidden_tools=forbidden_tools,
        )
    )
    return "".join(parts)


def _public_text_non_resource_segments(value: str) -> Iterable[str]:
    cursor = 0
    for match in _public_resource_uri_spans(value):
        yield value[cursor : match.start()]
        cursor = match.end()
    yield value[cursor:]


def _contains_private_path(value: str) -> bool:
    return any(
        _contains_private_path_segment(segment)
        for segment in _public_text_non_resource_segments(value)
    )


def _contains_disallowed_public_resource_uri(value: str) -> bool:
    return any(
        _PUBLIC_COLAMETA_URI_TOKEN_RE.search(segment)
        for segment in _public_text_non_resource_segments(value)
    )


def _mask_literal_resource_uri_tokens_for_decoded_scan(value: str) -> str:
    parts: list[str] = []
    cursor = 0
    search_cursor = 0
    while True:
        match = _PUBLIC_COLAMETA_URI_SCHEME_RE.search(
            value,
            search_cursor,
        )
        if match is None:
            break
        parts.append(value[cursor : match.start()])
        parts.append("<literal-resource-uri>")
        token_cursor = match.end()
        while (
            token_cursor < len(value)
            and not _is_resource_uri_whitespace(value[token_cursor])
            and value[token_cursor] not in "\"'`<>"
        ):
            if value[token_cursor] == "\\":
                _end, decoded = _scan_nested_json_escape(
                    value,
                    token_cursor,
                )
                if decoded is not None:
                    break
            token_cursor += 1
        cursor = token_cursor
        search_cursor = cursor
    if not parts:
        return value
    parts.append(value[cursor:])
    return "".join(parts)


def _decoded_candidate_contains_disallowed_public_resource_uri(
    value: str,
) -> bool:
    # Literal tokens are checked against exact URI spans in the original text.
    # Retain every token suffix beginning at its first JSON escape so a decoded
    # delimiter followed by another encoded URI cannot hide inside the greedy
    # literal-token match.
    encoded_only = _mask_literal_resource_uri_tokens_for_decoded_scan(value)
    return bool(
        "\\" in encoded_only
        and any(
            _contains_disallowed_public_resource_uri(candidate)
            for candidate in _json_escape_decoded_candidates(encoded_only)
        )
    )


def _contains_unsafe_public_text(value: str) -> bool:
    return bool(
        _matches_sensitive_material(value)
        or _decoded_candidate_contains_sensitive_material(value)
        or _contains_private_path(value)
        or _contains_disallowed_public_resource_uri(value)
        or _decoded_candidate_contains_disallowed_public_resource_uri(value)
    ) or any(
        _redact_noncommander_tool_references(segment) != segment
        or _decoded_candidate_contains_noncommander_tool_reference(segment)
        for segment in _public_text_non_resource_segments(value)
    )


def _normalized_string(value: Any) -> str:
    return value.strip().lower() if isinstance(value, str) else ""


def _safe_failed_response(
    *,
    tool_name: str,
    params: dict[str, Any],
    error_code: str,
    message: str,
) -> dict[str, Any]:
    try:
        from runner.commander_workflow_policy import journey_stage_for

        journey_stage = journey_stage_for(tool_name, params, {})
    except Exception:
        journey_stage = "recover"
    safe_code = (
        error_code
        if error_code in _FAILED_PUBLIC_ERROR_CODES
        else "INTERNAL_RESULT_INVALID"
    )
    return {
        "schema_version": COMMANDER_RESPONSE_SCHEMA_VERSION,
        "outcome": "failed",
        "summary": _public_text(message, max_chars=COMMANDER_SUMMARY_MAX_CHARS),
        "journey_stage": (
            journey_stage
            if journey_stage in COMMANDER_RESPONSE_JOURNEY_STAGES
            else "recover"
        ),
        "context_binding": None,
        "facts": {},
        "evidence": None,
        "next_action": None,
        "confirmation": None,
        "error": {
            "code": safe_code,
            "message": _public_text(message, max_chars=COMMANDER_SUMMARY_MAX_CHARS),
            "recoverable": False,
        },
    }
