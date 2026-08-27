"""Fresh ColaMeta executor authority admission primitive (R0).

This module creates a brand-new ColaMeta-owned executor authority record:

    canonical project facts
        -> fresh-admission safety facts
        -> create NEW ColaMeta executor authority
        -> persist authority (write-once, create-exclusive)
        -> NO provider process / NO prompt / NO project work

It is deliberately separate from the continuation plane
(``runner/executor_session.py``): it never resumes, reactivates, rewrites, or
inherits historical executor session state, and it never invokes a provider.
The only persistent state it creates lives under
``.colameta/runtime/executor-sessions/<executor_authority_id>/admission.json``.
"""

from __future__ import annotations

import errno
import ctypes
import hashlib
import json
import os
import re
import time
import stat
import uuid
from datetime import datetime, timezone
from typing import Any

from runner.mcp_github_delivery import MCPGitHubDeliveryManager
from runner.project_operation_lease import (
    PROJECT_OPERATION_BUSY,
    PROJECT_OPERATION_LEASE_UNAVAILABLE,
    ProjectOperationLease,
)
from runner.runner_paths import resolve_project_runner_path
from runner.work_item_governance.references import optional_work_item_reference_rejections

FRESH_EXECUTOR_AUTHORITY_SCHEMA_VERSION = "fresh_executor_authority_admission.v1"
FRESH_EXECUTOR_AUTHORITY_SOURCE = "fresh_executor_admission"
FRESH_EXECUTOR_AUTHORITY_STATE = "admitted"
FRESH_EXECUTOR_OPERATION_STATE = "idle"
ADMISSION_FILENAME = "admission.json"
STAGE_SHARD_RESERVATION_FILENAME = "stage-shard-admission-reservation.json"
EXECUTOR_SESSIONS_PARTS = ("runtime", "executor-sessions")

# Error codes.
FRESH_EXECUTOR_ADMISSION_HEAD_DRIFT = "FRESH_EXECUTOR_ADMISSION_HEAD_DRIFT"
FRESH_EXECUTOR_ADMISSION_PROJECT_BUSY = "FRESH_EXECUTOR_ADMISSION_PROJECT_BUSY"
FRESH_EXECUTOR_ADMISSION_LEASE_UNAVAILABLE = "FRESH_EXECUTOR_ADMISSION_LEASE_UNAVAILABLE"
FRESH_EXECUTOR_ADMISSION_PROJECT_ROOT_INVALID = "FRESH_EXECUTOR_ADMISSION_PROJECT_ROOT_INVALID"
FRESH_EXECUTOR_ADMISSION_HEAD_UNRESOLVED = "FRESH_EXECUTOR_ADMISSION_HEAD_UNRESOLVED"
FRESH_EXECUTOR_ADMISSION_REPOSITORY_UNRESOLVED = "FRESH_EXECUTOR_ADMISSION_REPOSITORY_UNRESOLVED"
FRESH_EXECUTOR_ADMISSION_HISTORICAL_SESSION_LIVE = "FRESH_EXECUTOR_ADMISSION_HISTORICAL_SESSION_LIVE"
FRESH_EXECUTOR_ADMISSION_AUTHORITY_EXISTS = "FRESH_EXECUTOR_ADMISSION_AUTHORITY_EXISTS"
FRESH_EXECUTOR_ADMISSION_INVALID_AUTHORITY_ID = "FRESH_EXECUTOR_ADMISSION_INVALID_AUTHORITY_ID"
FRESH_EXECUTOR_ADMISSION_WRITE_FAILED = "FRESH_EXECUTOR_ADMISSION_WRITE_FAILED"
FRESH_EXECUTOR_ADMISSION_INVALID_FACTS = "FRESH_EXECUTOR_ADMISSION_INVALID_FACTS"
# R0-repair error codes (three independent-review P1 findings).
FRESH_EXECUTOR_ADMISSION_WORKTREE_DIRTY = "FRESH_EXECUTOR_ADMISSION_WORKTREE_DIRTY"
FRESH_EXECUTOR_ADMISSION_WORKTREE_STATE_UNAVAILABLE = (
    "FRESH_EXECUTOR_ADMISSION_WORKTREE_STATE_UNAVAILABLE"
)
FRESH_EXECUTOR_ADMISSION_LIVE_OPERATION = "FRESH_EXECUTOR_ADMISSION_LIVE_OPERATION"
FRESH_EXECUTOR_ADMISSION_LIVENESS_UNAVAILABLE = (
    "FRESH_EXECUTOR_ADMISSION_LIVENESS_UNAVAILABLE"
)
FRESH_EXECUTOR_ADMISSION_STATE_ROOT_ESCAPE = "FRESH_EXECUTOR_ADMISSION_STATE_ROOT_ESCAPE"
STAGE_SHARD_RESERVATION_SCHEMA_VERSION = "stage_shard_fresh_authority_reservation.v1"
STAGE_SHARD_RESERVATION_SOURCE = "stage_parallel_shard_fresh_authority"
STAGE_SHARD_AUTHORITY_RESERVATION_CONFLICT = "STAGE_SHARD_AUTHORITY_RESERVATION_CONFLICT"
STAGE_SHARD_AUTHORITY_RESERVATION_MALFORMED = "STAGE_SHARD_AUTHORITY_RESERVATION_MALFORMED"
STAGE_SHARD_AUTHORITY_BINDING_MISMATCH = "STAGE_SHARD_AUTHORITY_BINDING_MISMATCH"
STAGE_SHARD_AUTHORITY_ALREADY_CONSUMED = "STAGE_SHARD_AUTHORITY_ALREADY_CONSUMED"
STAGE_SHARD_AUTHORITY_PUBLICATION_FAILED = "STAGE_SHARD_AUTHORITY_PUBLICATION_FAILED"

# --- Fresh-executor execution binding (R0) ---------------------------------
# The admission record is immutable; consumption is a separate create-exclusive
# ``execution-binding.json`` anchored to the open authority directory FD.
FRESH_EXECUTOR_BINDING_SCHEMA_VERSION = "fresh_executor_execution_binding.v2"
FRESH_EXECUTOR_BINDING_SOURCE = "fresh_executor_authority_execution_binding"
EXECUTION_BINDING_FILENAME = "execution-binding.json"
_MAX_AUTHORITY_RECORD_BYTES = 1024 * 1024
_ADMISSION_FIELDS = frozenset(
    {
        "schema_version", "executor_authority_id", "project_root",
        "repository", "git_branch", "admitted_head", "created_at",
        "admission_state", "operation_state", "provider",
        "provider_session_identity", "parent_authority_id",
        "continuation_from", "historical_session_inherited",
        "provider_invoked", "work_started", "source",
    }
)
_BINDING_FIELDS = frozenset(
    {
        "schema_version", "executor_authority_id", "admission_sha256",
        "project_root", "repository", "run_id", "preview_id", "admitted_head",
        "provider", "executor_session_mode", "work_item_id", "task_version",
        "attempt_id", "artifact_refs", "bound_at", "source",
        "event_stream",
    }
)
_STAGE_SHARD_RESERVATION_FIELDS = frozenset(
    {
        "schema_version", "source", "reserved_authority_id",
        "stage_shard_admission_key", "project_identity", "project_root",
        "repository", "stage_preview_sha256", "runner_plan_sha256",
        "stage_id", "parallel_group_id", "task_id", "work_item_id",
        "task_version", "attempt_id", "artifact_refs",
        "artifact_refs_sha256", "git_branch", "git_head", "provider",
        "created_at",
    }
)


def _validate_event_stream_contract(contract: Any) -> str | None:
    if not isinstance(contract, dict) or frozenset(contract) != {
        "identity", "size", "raw_sha256", "record_count"
    }:
        return "BINDING_EVENT_STREAM_FIELDS_INVALID"
    identity = contract.get("identity")
    if not isinstance(identity, dict) or frozenset(identity) != {"device", "inode"}:
        return "BINDING_EVENT_STREAM_IDENTITY_INVALID"
    for field in ("device", "inode"):
        value = identity.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            return "BINDING_EVENT_STREAM_IDENTITY_INVALID"
    for field in ("size", "record_count"):
        value = contract.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            return "BINDING_EVENT_STREAM_PREFIX_INVALID"
    raw_sha256 = contract.get("raw_sha256")
    if not isinstance(raw_sha256, str) or _SHA256_RE.fullmatch(raw_sha256) is None:
        return "BINDING_EVENT_STREAM_DIGEST_INVALID"
    return None

# R0 binding/execution gate error codes (all hard blocks).
FRESH_EXECUTOR_AUTHORITY_REQUIRED = "FRESH_EXECUTOR_AUTHORITY_REQUIRED"
FRESH_EXECUTOR_AUTHORITY_NOT_FOUND = "FRESH_EXECUTOR_AUTHORITY_NOT_FOUND"
FRESH_EXECUTOR_AUTHORITY_MALFORMED = "FRESH_EXECUTOR_AUTHORITY_MALFORMED"
FRESH_EXECUTOR_AUTHORITY_HASH_MISMATCH = "FRESH_EXECUTOR_AUTHORITY_HASH_MISMATCH"
FRESH_EXECUTOR_AUTHORITY_HEAD_MISMATCH = "FRESH_EXECUTOR_AUTHORITY_HEAD_MISMATCH"
FRESH_EXECUTOR_AUTHORITY_PROVIDER_MISMATCH = "FRESH_EXECUTOR_AUTHORITY_PROVIDER_MISMATCH"
FRESH_EXECUTOR_AUTHORITY_STATE_INVALID = "FRESH_EXECUTOR_AUTHORITY_STATE_INVALID"
FRESH_EXECUTOR_AUTHORITY_ALREADY_CONSUMED = "FRESH_EXECUTOR_AUTHORITY_ALREADY_CONSUMED"
FRESH_EXECUTOR_AUTHORITY_BINDING_CONFLICT = "FRESH_EXECUTOR_AUTHORITY_BINDING_CONFLICT"
FRESH_EXECUTOR_AUTHORITY_PREVIEW_MISMATCH = "FRESH_EXECUTOR_AUTHORITY_PREVIEW_MISMATCH"
FRESH_EXECUTOR_AUTHORITY_WORK_TARGET_REQUIRED = "FRESH_EXECUTOR_AUTHORITY_WORK_TARGET_REQUIRED"
FRESH_EXECUTOR_AUTHORITY_WORK_TARGET_MISMATCH = "WORK_TARGET_MISMATCH"
FRESH_EXECUTOR_AUTHORITY_SESSION_MODE_MISMATCH = "FRESH_EXECUTOR_AUTHORITY_SESSION_MODE_MISMATCH"
FRESH_EXECUTOR_AUTHORITY_BOUNDED_UNSUPPORTED_R0 = "FRESH_EXECUTOR_AUTHORITY_BOUNDED_UNSUPPORTED_R0"
FRESH_EXECUTOR_AUTHORITY_BINDING_WRITE_FAILED = "FRESH_EXECUTOR_AUTHORITY_BINDING_WRITE_FAILED"
FRESH_EXECUTOR_AUTHORITY_INVALID_CONTEXT = "FRESH_EXECUTOR_AUTHORITY_INVALID_CONTEXT"

# Authority ids are ColaMeta-generated UUID4 hex (32 lowercase hex chars).
_AUTHORITY_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_FULL_HEAD_RE = re.compile(r"^[0-9a-f]{40,64}$")
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_PREVIEW_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _durable_identity(metadata: os.stat_result) -> dict[str, int]:
    return {"device": int(metadata.st_dev), "inode": int(metadata.st_ino)}


def _durable_metadata(metadata: os.stat_result) -> dict[str, int]:
    return {
        "device": int(metadata.st_dev),
        "inode": int(metadata.st_ino),
        "mode": int(metadata.st_mode),
        "uid": int(metadata.st_uid),
        "gid": int(metadata.st_gid),
        "link_count": int(metadata.st_nlink),
        "size": int(metadata.st_size),
        "mtime_ns": int(metadata.st_mtime_ns),
        "ctime_ns": int(metadata.st_ctime_ns),
    }


def _content_sha256(record: dict[str, Any]) -> str:
    canonical = json.dumps(
        record,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _trusted_authority_directory(metadata: os.stat_result) -> bool:
    return bool(
        stat.S_ISDIR(metadata.st_mode)
        and metadata.st_uid == os.geteuid()
        and metadata.st_nlink >= 1
        and stat.S_IMODE(metadata.st_mode) & 0o022 == 0
    )


def _trusted_authority_ancestor(metadata: os.stat_result) -> bool:
    return bool(
        stat.S_ISDIR(metadata.st_mode)
        and metadata.st_uid == os.geteuid()
        and metadata.st_nlink >= 1
        and stat.S_IMODE(metadata.st_mode) & 0o002 == 0
    )


def _trusted_authority_file(metadata: os.stat_result) -> bool:
    return bool(
        stat.S_ISREG(metadata.st_mode)
        and metadata.st_uid == os.geteuid()
        and metadata.st_nlink == 1
        and stat.S_IMODE(metadata.st_mode) & 0o077 == 0
        and 0 <= metadata.st_size <= _MAX_AUTHORITY_RECORD_BYTES
    )


def _same_authority_file_snapshot(
    first: os.stat_result, second: os.stat_result
) -> bool:
    fields = (
        "st_dev", "st_ino", "st_mode", "st_uid", "st_nlink", "st_size",
        "st_mtime_ns", "st_ctime_ns",
    )
    return all(getattr(first, field) == getattr(second, field) for field in fields)

# Positive liveness schema (P1-b): admission may only proceed when the
# canonical activity evidence is explicitly interpretable.  Unknown schemas or
# unknown status values fail closed (LIVENESS_UNAVAILABLE); "no running
# evidence" is never treated as "definitely idle".
_LIVENESS_LIVE_STATUSES = frozenset({"running", "orphaned"})
# Statuses the canonical latest_run_status reader currently emits for a
# determinably idle executor (report / no-report outcomes).
_LIVENESS_IDLE_STATUSES = frozenset({"not_found", "completed", "failed", "failed_blocked"})
_LIVENESS_KNOWN_STATUSES = _LIVENESS_LIVE_STATUSES | _LIVENESS_IDLE_STATUSES
# Claim artifact statuses that determinably mean the claim is not live.
_LIVENESS_CLAIM_IDLE_STATUSES = frozenset({"completed", "failed", "failed_blocked"})
_LIVENESS_CLAIM_KNOWN_STATUSES = _LIVENESS_LIVE_STATUSES | _LIVENESS_CLAIM_IDLE_STATUSES

# Parent components of the authority state root that must never escape the
# canonical project state root through a symlink.
_RUNNER_DIRNAME = ".colameta"
_EXECUTOR_RUNTIME_PARTS = ("runtime", "executor-sessions")
_CLAIMS_REL_PARTS = (
    ".colameta",
    "runtime",
    "executor-workflow-previews",
    "claims",
)


def _run_git(project_root: str, *args: str) -> str:
    import subprocess

    completed = subprocess.run(
        ["git", *args],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _git_worktree_clean(project_root: str) -> tuple[bool | None, str | None]:
    """Return ``(clean, error)`` for the tracked + untracked working tree.

    ``clean`` is ``True``/``False`` when the state is determinable, otherwise
    ``None`` with a non-empty error.  This is read-only observation only: it
    never resets, restores, stashes, or cleans the working tree.
    """
    import subprocess

    try:
        completed = subprocess.run(
            ["git", "status", "--porcelain=v1", "--untracked-files=all"],
            cwd=project_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, str(exc)
    if completed.returncode != 0:
        detail = (completed.stderr or "").strip()
        return None, detail or f"git status exited with {completed.returncode}"
    return (not bool(completed.stdout.strip())), None


def _read_legacy_session_manifest(project_root: str) -> dict[str, Any] | None:
    manifest_path = resolve_project_runner_path(
        project_root, "runtime", "executor-session.json"
    )
    try:
        with open(manifest_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload if isinstance(payload, dict) else None
    except (OSError, ValueError):
        return None


def _is_historical_session_live(legacy: dict[str, Any] | None) -> bool:
    return isinstance(legacy, dict) and legacy.get("active") is True


def _normalize_repository(origin: str) -> str | None:
    normalized = MCPGitHubDeliveryManager._normalize_github_origin(origin)
    if normalized is not None:
        return normalized
    candidate = origin.strip()
    return candidate if candidate else None


def _clean_liveness_status(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    return text or None


def _live_run_snapshot_running(live_run: dict[str, Any] | None) -> bool:
    """Whether a live-run snapshot indicates a running executor.

    Mirrors ``runner.executor_session._live_run_is_running`` so fresh
    admission shares the canonical live-run semantics instead of inventing a
    second rule set.
    """
    if not isinstance(live_run, dict) or live_run.get("available") is not True:
        return False
    candidates = [
        live_run.get("status"),
        live_run.get("run_status"),
        live_run.get("claim_status"),
        live_run.get("executor_run_status"),
    ]
    claim = live_run.get("claim")
    if isinstance(claim, dict):
        candidates.append(claim.get("status"))
    return any(_clean_liveness_status(value) == "running" for value in candidates)


def _scan_claim_artifacts(project_root: str) -> dict[str, Any]:
    """Directly inspect executor-workflow claim artifacts with positive proof.

    Every claim artifact must be interpretable against the known status
    vocabulary.  A malformed, unreadable, missing-status, or unknown-status
    claim is ``unavailable`` (fail-closed) -- never silently treated as idle.
    """
    root = os.path.abspath(os.path.expanduser(project_root))
    claims_root = os.path.join(root, *_CLAIMS_REL_PARTS)
    if not os.path.isdir(claims_root):
        return {"state": "idle", "reason": "no_claim_artifacts"}
    try:
        names = sorted(os.listdir(claims_root))
    except OSError as exc:
        return {
            "state": "unavailable",
            "reason": f"claim_scan_unreadable:{type(exc).__name__}",
        }
    artifact_names: list[str] = []
    for name in names:
        if not name.endswith(".json"):
            continue
        path = os.path.join(claims_root, name)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, ValueError):
            return {
                "state": "unavailable",
                "reason": f"claim_unreadable:{name}",
            }
        if not isinstance(payload, dict):
            return {"state": "unavailable", "reason": f"claim_malformed:{name}"}
        if "status" not in payload:
            return {"state": "unavailable", "reason": f"claim_missing_status:{name}"}
        main_status = _clean_liveness_status(payload.get("status"))
        if main_status is None:
            return {"state": "unavailable", "reason": f"claim_status_null:{name}"}
        if main_status in _LIVENESS_LIVE_STATUSES:
            return {"state": "live", "reason": f"claim_running:{name}"}
        if main_status not in _LIVENESS_CLAIM_IDLE_STATUSES:
            return {
                "state": "unavailable",
                "reason": f"claim_unknown_status:{name}:{main_status}",
            }
        # Supplementary status-like fields must also be interpretable: a field
        # that is present but null / wrong-typed is malformed (fail-closed),
        # never silently treated as absent.
        for key in ("claim_status", "run_status", "executor_run_status"):
            if key not in payload:
                continue
            raw_value = payload[key]
            if raw_value is None or not isinstance(raw_value, str):
                return {
                    "state": "unavailable",
                    "reason": f"claim_status_field_malformed:{name}:{key}",
                }
            value = _clean_liveness_status(raw_value)
            if value is None:
                continue
            if value in _LIVENESS_LIVE_STATUSES:
                return {"state": "live", "reason": f"claim_running:{name}:{key}"}
            if value not in _LIVENESS_CLAIM_KNOWN_STATUSES:
                return {
                    "state": "unavailable",
                    "reason": f"claim_unknown_status:{name}:{key}:{value}",
                }
        if "operation_running" in payload:
            raw_operation_running = payload["operation_running"]
            if not isinstance(raw_operation_running, bool):
                return {
                    "state": "unavailable",
                    "reason": f"claim_operation_running_not_bool:{name}",
                }
            if raw_operation_running is True:
                return {"state": "live", "reason": f"claim_operation_running:{name}"}
        if "job_status" in payload:
            raw_job_status = payload["job_status"]
            if not isinstance(raw_job_status, str):
                return {
                    "state": "unavailable",
                    "reason": f"claim_job_status_not_string:{name}",
                }
            job_status = _clean_liveness_status(raw_job_status)
            if job_status == "running":
                return {"state": "live", "reason": f"claim_job_running:{name}"}
            if job_status is not None and job_status not in {
                "idle", "completed", "finished", "done", "not_found",
            }:
                return {
                    "state": "unavailable",
                    "reason": f"claim_unknown_job_status:{name}:{job_status}",
                }
        artifact_names.append(name)
    return {
        "state": "idle",
        "reason": "no_live_claim_artifacts",
        "claim_artifacts": artifact_names,
    }


def _collect_operation_liveness(project_root: str) -> dict[str, Any]:
    """Evaluate canonical executor-operation liveness with positive proof.

    Returns ``{"state": "idle"|"live"|"unavailable", "reason", "evidence"}``.

    The canonical ``latest_run_status`` contract must be interpretable: the
    ``status`` field is required, must be a string, and must be a known status
    value.  Unknown schemas/values, malformed evidence, and read failures are
    ``unavailable`` (a blocker), never treated as "definitely idle".
    """
    from runner.executor_read import handle_inspect_executor_activity

    try:
        result = handle_inspect_executor_activity(
            project_root, "latest_run_status", {}
        )
    except Exception as exc:
        return {
            "state": "unavailable",
            "reason": f"activity_read_failed:{type(exc).__name__}",
        }
    if not isinstance(result, dict):
        return {"state": "unavailable", "reason": "activity_result_not_mapping"}
    if result.get("warning") == "LATEST_RUN_STATUS_UNAVAILABLE":
        return {
            "state": "unavailable",
            "reason": "latest_run_status_unavailable",
        }

    # Positive schema: status is required and must be a known value.
    if "status" not in result:
        return {"state": "unavailable", "reason": "liveness_schema_missing_status"}
    latest_run_status = _clean_liveness_status(result.get("status"))
    if latest_run_status is None:
        return {
            "state": "unavailable",
            "reason": "liveness_schema_status_not_string",
        }
    if latest_run_status not in _LIVENESS_KNOWN_STATUSES:
        return {
            "state": "unavailable",
            "reason": f"liveness_schema_unknown_status:{latest_run_status}",
        }

    live = result.get("live")
    if not isinstance(live, dict):
        live = result.get("stale_orphan_claim")
    latest_claim_status = None
    if isinstance(live, dict):
        # Positive nested schema (repair 3): a nested liveness field that is
        # PRESENT but malformed (null / wrong type / non-mapping claim) is
        # uninterpretable -> LIVENESS_UNAVAILABLE.  "field absent" keeps the
        # existing semantics; malformed is never silently treated as absent.
        if "available" in live and not isinstance(live.get("available"), bool):
            return {
                "state": "unavailable",
                "reason": "liveness_schema_available_not_bool",
            }
        if "claim_status" in live:
            raw_claim_status = live.get("claim_status")
            if raw_claim_status is None or not isinstance(raw_claim_status, str):
                return {
                    "state": "unavailable",
                    "reason": "liveness_schema_claim_status_not_string",
                }
        if "claim" in live and not isinstance(live.get("claim"), dict):
            return {
                "state": "unavailable",
                "reason": "liveness_schema_claim_not_mapping",
            }
        live_claim_statuses: set[str] = set()
        raw_claim_statuses: list[Any] = []
        if "claim_status" in live:
            raw_claim_status = live["claim_status"]
            if raw_claim_status != "":
                raw_claim_statuses.append(raw_claim_status)
        claim = live.get("claim")
        if isinstance(claim, dict) and "status" in claim:
            raw_claim_status = claim["status"]
            if raw_claim_status is None or not isinstance(raw_claim_status, str):
                return {
                    "state": "unavailable",
                    "reason": "liveness_schema_claim_status_not_string",
                }
            if raw_claim_status != "":
                raw_claim_statuses.append(raw_claim_status)
        for raw_status in raw_claim_statuses:
            cleaned_status = _clean_liveness_status(raw_status)
            live_claim_statuses.add(cleaned_status)
        unknown_claim_statuses = live_claim_statuses - _LIVENESS_KNOWN_STATUSES
        if unknown_claim_statuses:
            return {
                "state": "unavailable",
                "reason": (
                    "liveness_schema_unknown_claim_status:"
                    + sorted(unknown_claim_statuses)[0]
                ),
            }
        if "running" in live_claim_statuses:
            latest_claim_status = "running"
    live_run_running = _live_run_snapshot_running(live)

    evidence = {
        "latest_run_status": latest_run_status,
        "latest_claim_status": latest_claim_status,
        "live_run_running": live_run_running,
    }
    if latest_run_status in _LIVENESS_LIVE_STATUSES:
        return {
            "state": "live",
            "reason": "latest_run_running_or_orphaned",
            "evidence": evidence,
        }
    if latest_claim_status == "running":
        return {
            "state": "live",
            "reason": "latest_claim_running",
            "evidence": evidence,
        }
    if live_run_running:
        return {
            "state": "live",
            "reason": "live_run_running",
            "evidence": evidence,
        }

    claim_scan = _scan_claim_artifacts(project_root)
    claim_scan["evidence"] = evidence
    return claim_scan


def _path_contained(candidate: str, allowed_root: str) -> bool:
    """True iff ``realpath(candidate)`` is inside ``realpath(allowed_root)``.

    Uses ``os.path.commonpath`` after resolving symlinks; a plain string
    prefix comparison is not reliable for containment.
    """
    candidate_real = os.path.realpath(candidate)
    root_real = os.path.realpath(allowed_root)
    try:
        return os.path.commonpath([candidate_real, root_real]) == root_real
    except ValueError:
        return False


def _verify_authority_state_root(project_root: str) -> dict[str, Any]:
    """Verify the executor-sessions state root cannot escape the project root.

    Checks every parent component of
    ``<project_root>/.colameta/runtime/executor-sessions``: the resolved path
    of each level must be contained within its parent, and ``.colameta`` itself
    must not be a symlink.  The final write still uses ``O_CREAT|O_EXCL`` for
    the admission file; this check closes the parent-chain escape.
    """
    root = os.path.abspath(os.path.expanduser(project_root))
    runner_dir = os.path.join(root, _RUNNER_DIRNAME)
    runtime_dir = os.path.join(runner_dir, *_EXECUTOR_RUNTIME_PARTS[:-1])
    sessions_dir = os.path.join(runner_dir, *_EXECUTOR_RUNTIME_PARTS)
    if os.path.islink(runner_dir):
        return {
            "ok": False,
            "reason": "runner_dir_symlink",
            "authority_root": sessions_dir,
        }
    for label, candidate, parent in (
        (_RUNNER_DIRNAME, runner_dir, root),
        ("/".join(_EXECUTOR_RUNTIME_PARTS[:-1]), runtime_dir, runner_dir),
        ("/".join(_EXECUTOR_RUNTIME_PARTS), sessions_dir, runtime_dir),
    ):
        if not _path_contained(candidate, parent):
            return {
                "ok": False,
                "reason": f"{label}_escapes_state_root",
                "authority_root": sessions_dir,
            }
    return {"ok": True, "authority_root": sessions_dir}


def _open_or_create_dir_relative(component: str, parent_fd: int) -> int:
    """Open an existing directory component relative to ``parent_fd``.

    Uses ``O_NOFOLLOW`` so a symlink at the component is never followed
    (ELOOP -> fail closed).  If the component is absent it is created first and
    then re-opened with ``O_NOFOLLOW``; a symlink swapped in between mkdir and
    open also fails closed.
    """
    try:
        return os.open(
            component,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=parent_fd,
        )
    except FileNotFoundError:
        os.mkdir(component, dir_fd=parent_fd, mode=0o700)
        return os.open(
            component,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=parent_fd,
        )


def _close_fds(fds: list[int]) -> None:
    for fd in fds:
        try:
            os.close(fd)
        except OSError:
            pass


def _state_root_open_error_code(exc: OSError) -> str:
    if exc.errno in (errno.ELOOP, errno.ENOTDIR, errno.EACCES, errno.EPERM):
        return FRESH_EXECUTOR_ADMISSION_STATE_ROOT_ESCAPE
    return FRESH_EXECUTOR_ADMISSION_WRITE_FAILED


def _open_authority_state_fds(project_root: str) -> dict[str, Any]:
    """Open the canonical authority state root via fd-anchored traversal.

    ``canonical_project_root -> .colameta -> runtime -> executor-sessions``
    is opened one component at a time, each relative to its already-open parent
    with ``O_NOFOLLOW``.  The write authority is therefore the open directory
    objects, not a re-resolved pathname: a parent path swapped for a symlink
    after this point cannot redirect the write.  Callers must close the
    returned fds.
    """
    root = os.path.abspath(os.path.expanduser(project_root))
    fds: list[int] = []
    try:
        project_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        fds.append(project_fd)
        colameta_fd = _open_or_create_dir_relative(_RUNNER_DIRNAME, project_fd)
        fds.append(colameta_fd)
        runtime_fd = _open_or_create_dir_relative("runtime", colameta_fd)
        fds.append(runtime_fd)
        sessions_fd = _open_or_create_dir_relative("executor-sessions", runtime_fd)
        fds.append(sessions_fd)
    except OSError as exc:
        _close_fds(fds)
        return {
            "ok": False,
            "error_code": _state_root_open_error_code(exc),
            "reason": f"{type(exc).__name__}:{exc.errno}",
        }
    return {
        "ok": True,
        "project_fd": project_fd,
        "colameta_fd": colameta_fd,
        "runtime_fd": runtime_fd,
        "sessions_fd": sessions_fd,
        "canonical_project_root": root,
        "authority_root_path": os.path.join(
            root, _RUNNER_DIRNAME, "runtime", "executor-sessions"
        ),
    }


def _open_authority_dir(sessions_fd: int, authority_id: str) -> tuple[int, str | None]:
    """Create/open ``<authority_id>/`` anchored to ``sessions_fd``.

    Returns ``(authority_fd, None)`` on success or ``(-1, error_code)``.  A
    pre-existing directory is a collision (AUTHORITY_EXISTS).  A symlink
    appearing between mkdir and open fails with O_NOFOLLOW
    (STATE_ROOT_ESCAPE) and no bytes are written outside.
    """
    try:
        os.mkdir(authority_id, dir_fd=sessions_fd, mode=0o700)
    except FileExistsError:
        return -1, FRESH_EXECUTOR_ADMISSION_AUTHORITY_EXISTS
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.ENOTDIR):
            return -1, FRESH_EXECUTOR_ADMISSION_STATE_ROOT_ESCAPE
        return -1, FRESH_EXECUTOR_ADMISSION_WRITE_FAILED
    try:
        return os.open(
            authority_id,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=sessions_fd,
        ), None
    except OSError:
        return -1, FRESH_EXECUTOR_ADMISSION_STATE_ROOT_ESCAPE


def _write_all_fd(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        view = view[written:]


def _rename_noreplace(src: str, dst: str, directory_fd: int) -> None:
    """Atomically publish one name without replacing an existing object."""

    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        raise OSError(errno.ENOSYS, "renameat2 unavailable")
    renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    renameat2.restype = ctypes.c_int
    result = renameat2(
        directory_fd,
        os.fsencode(src),
        directory_fd,
        os.fsencode(dst),
        1,  # RENAME_NOREPLACE
    )
    if result != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), dst)


def _publish_json_create_exclusive(
    directory_fd: int,
    filename: str,
    record: dict[str, Any],
) -> dict[str, Any]:
    """Durably publish bounded JSON without exposing partially written bytes."""

    payload = (
        json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    if len(payload) > _MAX_AUTHORITY_RECORD_BYTES:
        return {"ok": False, "error_code": STAGE_SHARD_AUTHORITY_PUBLICATION_FAILED}
    temporary = f".{filename}.{uuid.uuid4().hex}.tmp"
    file_fd = -1
    try:
        file_fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=directory_fd,
        )
        _write_all_fd(file_fd, payload)
        os.fsync(file_fd)
        os.close(file_fd)
        file_fd = -1
        _rename_noreplace(temporary, filename, directory_fd)
        os.fsync(directory_fd)
        metadata = os.stat(filename, dir_fd=directory_fd, follow_symlinks=False)
        if not _trusted_authority_file(metadata):
            return {"ok": False, "error_code": STAGE_SHARD_AUTHORITY_PUBLICATION_FAILED}
        return {
            "ok": True,
            "raw_sha256": hashlib.sha256(payload).hexdigest(),
            "raw": payload,
        }
    except FileExistsError:
        return {"ok": False, "error_code": FRESH_EXECUTOR_ADMISSION_AUTHORITY_EXISTS}
    except OSError as exc:
        return {
            "ok": False,
            "error_code": STAGE_SHARD_AUTHORITY_PUBLICATION_FAILED,
            "reason": f"{type(exc).__name__}:{exc.errno}",
        }
    finally:
        if file_fd >= 0:
            try:
                os.close(file_fd)
            except OSError:
                pass
        try:
            os.unlink(temporary, dir_fd=directory_fd)
        except OSError:
            pass


def collect_fresh_admission_facts(project_root: str) -> dict[str, Any]:
    """Collect read-only facts used by the fresh admission decision."""

    root = os.path.abspath(os.path.expanduser(project_root))
    facts: dict[str, Any] = {"project_root": root}
    if not os.path.isdir(root):
        facts["project_root_valid"] = False
        return facts
    facts["project_root_valid"] = True
    head = _run_git(root, "rev-parse", "HEAD")
    facts["project_head"] = head.lower() if _FULL_HEAD_RE.fullmatch(head) else None
    branch = _run_git(root, "rev-parse", "--abbrev-ref", "HEAD")
    facts["git_branch"] = branch or None
    origin = _run_git(root, "remote", "get-url", "origin")
    facts["origin"] = origin
    facts["repository"] = _normalize_repository(origin)
    legacy = _read_legacy_session_manifest(root)
    facts["legacy_session_present"] = legacy is not None
    facts["historical_session_live"] = _is_historical_session_live(legacy)
    worktree_clean, worktree_error = _git_worktree_clean(root)
    facts["worktree_clean"] = worktree_clean
    facts["worktree_state_available"] = worktree_clean is not None
    if worktree_error:
        facts["worktree_state_error"] = worktree_error
    facts["operation_liveness"] = _collect_operation_liveness(root)
    facts["authority_root"] = executor_authority_dir(root)
    facts["authority_root_safe"] = _verify_authority_state_root(root)["ok"]
    return facts


def build_fresh_admission_decision(facts: dict[str, Any]) -> dict[str, Any]:
    """Decide whether a NEW authority may be born (no continuation logic)."""

    if not isinstance(facts, dict) or facts.get("project_root_valid") is not True:
        return {
            "allowed": False,
            "error_code": FRESH_EXECUTOR_ADMISSION_PROJECT_ROOT_INVALID,
            "hard_blockers": ["project_root_invalid"],
            "reason": "project root is not a valid directory",
        }
    blockers: list[str] = []
    error_code = ""
    if not _FULL_HEAD_RE.fullmatch(str(facts.get("project_head") or "")):
        blockers.append("head_unresolved")
        error_code = FRESH_EXECUTOR_ADMISSION_HEAD_UNRESOLVED
    if not facts.get("repository"):
        blockers.append("repository_unresolved")
        error_code = error_code or FRESH_EXECUTOR_ADMISSION_REPOSITORY_UNRESOLVED
    if facts.get("historical_session_live") is True:
        blockers.append("historical_session_live")
        error_code = error_code or FRESH_EXECUTOR_ADMISSION_HISTORICAL_SESSION_LIVE
    # P1-3: the authority directory must never escape the canonical state root.
    if facts.get("authority_root_safe") is not True:
        blockers.append("state_root_escape")
        error_code = error_code or FRESH_EXECUTOR_ADMISSION_STATE_ROOT_ESCAPE
    # P1-1: exact HEAD does not prove the working tree actually matches it.
    if facts.get("worktree_clean") is False:
        blockers.append("worktree_dirty")
        error_code = error_code or FRESH_EXECUTOR_ADMISSION_WORKTREE_DIRTY
    elif facts.get("worktree_clean") is not True:
        blockers.append("worktree_state_unavailable")
        error_code = error_code or FRESH_EXECUTOR_ADMISSION_WORKTREE_STATE_UNAVAILABLE
    # P1-2: ``active=false`` on the legacy manifest is not proof that no
    # executor operation is live.
    liveness = facts.get("operation_liveness")
    liveness_state = liveness.get("state") if isinstance(liveness, dict) else None
    if liveness_state == "live":
        blockers.append("live_operation_running")
        error_code = error_code or FRESH_EXECUTOR_ADMISSION_LIVE_OPERATION
    elif liveness_state != "idle":
        blockers.append("liveness_evidence_unavailable")
        error_code = error_code or FRESH_EXECUTOR_ADMISSION_LIVENESS_UNAVAILABLE
    return {
        "allowed": not blockers,
        "error_code": error_code or None,
        "hard_blockers": blockers,
        "project_head": facts.get("project_head"),
        "git_branch": facts.get("git_branch"),
        "repository": facts.get("repository"),
        "reason": "fresh_authority_allowed"
        if not blockers
        else ",".join(blockers),
    }


def executor_authority_dir(project_root: str) -> str:
    return resolve_project_runner_path(
        project_root, *EXECUTOR_SESSIONS_PARTS
    )


def executor_authority_path(project_root: str, authority_id: str) -> str:
    """Return the admission record path for a validated authority id."""

    if _AUTHORITY_ID_RE.fullmatch(authority_id) is None:
        raise ValueError("malformed executor authority id")
    return os.path.join(
        executor_authority_dir(project_root), authority_id, ADMISSION_FILENAME
    )


def _validate_authority_id(authority_id: str) -> bool:
    return _AUTHORITY_ID_RE.fullmatch(authority_id) is not None


def _build_admission_record(
    *,
    authority_id: str,
    facts: dict[str, Any],
    created_at: str,
) -> dict[str, Any]:
    return {
        "schema_version": FRESH_EXECUTOR_AUTHORITY_SCHEMA_VERSION,
        "executor_authority_id": authority_id,
        "project_root": facts["project_root"],
        "repository": facts.get("repository"),
        "git_branch": facts.get("git_branch"),
        "admitted_head": facts.get("project_head"),
        "created_at": created_at,
        "admission_state": FRESH_EXECUTOR_AUTHORITY_STATE,
        "operation_state": FRESH_EXECUTOR_OPERATION_STATE,
        "provider": "codex",
        "provider_session_identity": None,
        "parent_authority_id": None,
        "continuation_from": None,
        "historical_session_inherited": False,
        "provider_invoked": False,
        "work_started": False,
        "source": FRESH_EXECUTOR_AUTHORITY_SOURCE,
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_fresh_executor_authority(
    project_root: str, authority_id: str
) -> dict[str, Any] | None:
    """Read an exact verified admission record, or fail closed with ``None``."""

    verification = _read_admission_verification(project_root, authority_id)
    record = verification.get("record") if verification.get("ok") else None
    return record if isinstance(record, dict) else None


def create_fresh_executor_authority(
    project_root: str,
    *,
    expected_head: str | None = None,
    facts: dict[str, Any] | None = None,
    authority_id: str | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    """Create a brand-new ColaMeta executor authority (create-only, no work).

    - ``expected_head`` binds creation to the HEAD observed at preview time;
      any drift is fail-closed (``FRESH_EXECUTOR_ADMISSION_HEAD_DRIFT``).
    - ``facts`` may be injected for tests; otherwise collected live.
    - ``authority_id`` may be injected for tests; otherwise ColaMeta generates
      a new UUID4.  The id must be a valid 32-hex UUID form.

    Ordering (P1 repair): preview facts -> acquire the exclusive project lease
    -> re-read HEAD/worktree/liveness/state-root under the lease -> validate ->
    verify state-root containment -> create-exclusive write -> release.
    """

    observed = collect_fresh_admission_facts(project_root)
    base_facts = dict(facts) if isinstance(facts, dict) else observed
    base_facts.setdefault("project_root", observed.get("project_root"))
    base_facts.setdefault("project_root_valid", observed.get("project_root_valid"))
    decision = build_fresh_admission_decision(base_facts)
    if not decision.get("allowed"):
        return {
            "ok": False,
            "error_code": decision.get("error_code"),
            "hard_blockers": decision.get("hard_blockers"),
            "reason": decision.get("reason"),
        }

    if expected_head is not None:
        normalized_expected = str(expected_head).lower()
        if _FULL_HEAD_RE.fullmatch(normalized_expected) is None:
            return {
                "ok": False,
                "error_code": FRESH_EXECUTOR_ADMISSION_INVALID_FACTS,
                "reason": "expected_head is not a full object id",
            }
        if base_facts.get("project_head") != normalized_expected:
            return {
                "ok": False,
                "error_code": FRESH_EXECUTOR_ADMISSION_HEAD_DRIFT,
                "observed_head": base_facts.get("project_head"),
                "expected_head": normalized_expected,
                "reason": "project HEAD drifted between preview and creation",
            }

    if authority_id is None:
        authority_id = uuid.uuid4().hex
    authority_id = str(authority_id)
    if _validate_authority_id(authority_id) is False:
        return {
            "ok": False,
            "error_code": FRESH_EXECUTOR_ADMISSION_INVALID_AUTHORITY_ID,
            "reason": "authority id must be a 32-hex-char ColaMeta-generated UUID",
        }

    lease = ProjectOperationLease(project_root)
    lease.acquire()
    if not lease.held:
        if lease.error_code == PROJECT_OPERATION_BUSY:
            return {
                "ok": False,
                "error_code": FRESH_EXECUTOR_ADMISSION_PROJECT_BUSY,
                "reason": "a competing project operation lease is held",
            }
        return {
            "ok": False,
            "error_code": FRESH_EXECUTOR_ADMISSION_LEASE_UNAVAILABLE,
            "reason": "project operation lease is unavailable for this project root",
        }
    try:
        # Revalidate facts under the exclusive lease (HEAD + worktree +
        # liveness + state root), then enforce create-exclusive semantics.
        revalidated = collect_fresh_admission_facts(project_root)
        live_decision = build_fresh_admission_decision(revalidated)
        if not live_decision.get("allowed"):
            return {
                "ok": False,
                "error_code": live_decision.get("error_code"),
                "hard_blockers": live_decision.get("hard_blockers"),
                "reason": live_decision.get("reason"),
            }
        if expected_head is not None and revalidated.get("project_head") != normalized_expected:
            return {
                "ok": False,
                "error_code": FRESH_EXECUTOR_ADMISSION_HEAD_DRIFT,
                "observed_head": revalidated.get("project_head"),
                "expected_head": normalized_expected,
                "reason": "project HEAD drifted while creating the authority",
            }

        # P1-a (repair 2): the write authority is the already-open state-root
        # directory objects, not a re-resolved pathname.  Each component is
        # opened relative to its parent with O_NOFOLLOW, so a parent path
        # swapped for a symlink after this point cannot redirect the write;
        # the admission record is created relative to the open authority
        # directory FD with O_CREAT|O_EXCL|O_NOFOLLOW.
        effective_facts = {**revalidated}
        record = _build_admission_record(
            authority_id=authority_id,
            facts=effective_facts,
            created_at=now or _now_iso(),
        )

        state_root = _open_authority_state_fds(project_root)
        if not state_root.get("ok"):
            return {
                "ok": False,
                "error_code": state_root.get("error_code"),
                "reason": state_root.get("reason"),
            }
        try:
            authority_fd, authority_error = _open_authority_dir(
                state_root["sessions_fd"], authority_id
            )
            if authority_fd < 0:
                return {
                    "ok": False,
                    "error_code": authority_error,
                    "executor_authority_id": authority_id,
                    "reason": "authority directory collision or escape",
                }
            try:
                try:
                    record_fd = os.open(
                        ADMISSION_FILENAME,
                        os.O_WRONLY
                        | os.O_CREAT
                        | os.O_EXCL
                        | os.O_NOFOLLOW
                        | os.O_CLOEXEC,
                        0o600,
                        dir_fd=authority_fd,
                    )
                except FileExistsError:
                    return {
                        "ok": False,
                        "error_code": FRESH_EXECUTOR_ADMISSION_AUTHORITY_EXISTS,
                        "executor_authority_id": authority_id,
                        "reason": "admission record already exists",
                    }
                except OSError:
                    return {
                        "ok": False,
                        "error_code": FRESH_EXECUTOR_ADMISSION_STATE_ROOT_ESCAPE,
                        "executor_authority_id": authority_id,
                        "reason": "admission record open refused by anchored create",
                    }
                try:
                    try:
                        payload = (
                            json.dumps(
                                record,
                                indent=2,
                                sort_keys=True,
                                ensure_ascii=False,
                            )
                            + "\n"
                        )
                        _write_all_fd(record_fd, payload.encode("utf-8"))
                        os.fsync(record_fd)
                    except OSError:
                        return {
                            "ok": False,
                            "error_code": FRESH_EXECUTOR_ADMISSION_WRITE_FAILED,
                            "reason": "failed to persist the admission record",
                        }
                finally:
                    os.close(record_fd)
            finally:
                os.close(authority_fd)
        finally:
            _close_fds(
                [
                    state_root["project_fd"],
                    state_root["colameta_fd"],
                    state_root["runtime_fd"],
                    state_root["sessions_fd"],
                ]
            )

        record_path = os.path.join(
            state_root["authority_root_path"], authority_id, ADMISSION_FILENAME
        )
        return {
            "ok": True,
            "executor_authority_id": authority_id,
            "admission_record_path": record_path,
            "record": record,
        }
    finally:
        lease.release()


def _stage_shard_reservation_binding(record: dict[str, Any]) -> dict[str, Any]:
    return {
        key: record[key]
        for key in (
            "project_identity", "project_root", "repository",
            "stage_preview_sha256", "runner_plan_sha256", "stage_id",
            "parallel_group_id", "task_id", "work_item_id", "task_version",
            "attempt_id", "artifact_refs", "artifact_refs_sha256",
            "git_branch", "git_head", "provider",
        )
    }


def _validate_stage_shard_reservation(
    record: Any,
    *,
    authority_id: str,
) -> bool:
    if not isinstance(record, dict) or frozenset(record) != _STAGE_SHARD_RESERVATION_FIELDS:
        return False
    if (
        record.get("schema_version") != STAGE_SHARD_RESERVATION_SCHEMA_VERSION
        or record.get("source") != STAGE_SHARD_RESERVATION_SOURCE
        or record.get("reserved_authority_id") != authority_id
        or _validate_authority_id(authority_id) is False
    ):
        return False
    for field in (
        "stage_shard_admission_key", "project_identity", "stage_preview_sha256",
        "runner_plan_sha256", "artifact_refs_sha256",
    ):
        if not isinstance(record.get(field), str) or _SHA256_RE.fullmatch(record[field]) is None:
            return False
    if not isinstance(record.get("git_head"), str) or _FULL_HEAD_RE.fullmatch(record["git_head"]) is None:
        return False
    for field in (
        "project_root", "repository", "stage_id", "parallel_group_id", "task_id",
        "work_item_id", "attempt_id", "git_branch", "provider", "created_at",
    ):
        if not isinstance(record.get(field), str) or not record[field] or len(record[field]) > 4096:
            return False
    if isinstance(record.get("task_version"), bool) or not isinstance(record.get("task_version"), int) or record["task_version"] < 1:
        return False
    artifact_refs = record.get("artifact_refs")
    if not isinstance(artifact_refs, list) or artifact_refs != sorted(set(artifact_refs)):
        return False
    target = {
        "work_item_id": record["work_item_id"],
        "task_version": record["task_version"],
        "attempt_id": record["attempt_id"],
        "artifact_refs": artifact_refs,
    }
    if optional_work_item_reference_rejections(target):
        return False
    if record["artifact_refs_sha256"] != _content_sha256({"artifact_refs": artifact_refs}):
        return False
    binding = _stage_shard_reservation_binding(record)
    if record["stage_shard_admission_key"] != _content_sha256(binding):
        return False
    expected_project_identity = _content_sha256(
        {"project_root": record["project_root"], "repository": record["repository"]}
    )
    return record["project_identity"] == expected_project_identity


def _read_stage_shard_reservation(
    state: dict[str, Any], authority_fd: int, authority_id: str
) -> dict[str, Any]:
    evidence = _read_verified_authority_file(
        authority_fd,
        STAGE_SHARD_RESERVATION_FILENAME,
        state=state,
        authority_id=authority_id,
        authority_fd=authority_fd,
    )
    if not evidence.get("ok"):
        return evidence
    try:
        record = json.loads(evidence["raw"].decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return {"ok": False, "error_code": STAGE_SHARD_AUTHORITY_RESERVATION_MALFORMED}
    if not _validate_stage_shard_reservation(record, authority_id=authority_id):
        return {"ok": False, "error_code": STAGE_SHARD_AUTHORITY_RESERVATION_MALFORMED}
    return {"ok": True, "record": record, "raw_sha256": evidence["raw_sha256"]}


def create_or_resolve_stage_shard_fresh_executor_authority(
    project_root: str,
    *,
    expected_repository: str,
    stage_preview_sha256: str,
    runner_plan_sha256: str,
    stage_id: str,
    parallel_group_id: str,
    task_id: str,
    work_item_id: str,
    task_version: int,
    attempt_id: str,
    artifact_refs: list[str],
    expected_git_branch: str,
    expected_head: str,
    provider: str = "codex",
    now: str | None = None,
) -> dict[str, Any]:
    """Create or recover one exact, unconsumed Stage-shard authority.

    The ordinary one-shot Fresh Authority API is intentionally not involved.
    Recovery is keyed by an immutable private reservation while authority IDs
    remain random UUID4-style values.
    """

    root = os.path.abspath(os.path.expanduser(project_root))
    if not isinstance(expected_repository, str) or not expected_repository:
        return {"ok": False, "error_code": STAGE_SHARD_AUTHORITY_BINDING_MISMATCH}
    for digest in (stage_preview_sha256, runner_plan_sha256):
        if not isinstance(digest, str) or _SHA256_RE.fullmatch(digest) is None:
            return {"ok": False, "error_code": STAGE_SHARD_AUTHORITY_BINDING_MISMATCH}
    if not isinstance(expected_head, str) or _FULL_HEAD_RE.fullmatch(expected_head) is None:
        return {"ok": False, "error_code": STAGE_SHARD_AUTHORITY_BINDING_MISMATCH}
    for value in (stage_id, parallel_group_id, task_id, expected_git_branch):
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > 256:
            return {"ok": False, "error_code": STAGE_SHARD_AUTHORITY_BINDING_MISMATCH}
    target = {
        "work_item_id": work_item_id,
        "task_version": task_version,
        "attempt_id": attempt_id,
        "artifact_refs": artifact_refs,
    }
    if optional_work_item_reference_rejections(target):
        return {"ok": False, "error_code": STAGE_SHARD_AUTHORITY_BINDING_MISMATCH}
    if artifact_refs != sorted(set(artifact_refs)) or provider != "codex":
        return {"ok": False, "error_code": STAGE_SHARD_AUTHORITY_BINDING_MISMATCH}

    project_identity = _content_sha256(
        {"project_root": root, "repository": expected_repository}
    )
    binding = {
        "project_identity": project_identity,
        "project_root": root,
        "repository": expected_repository,
        "stage_preview_sha256": stage_preview_sha256,
        "runner_plan_sha256": runner_plan_sha256,
        "stage_id": stage_id.strip(),
        "parallel_group_id": parallel_group_id.strip(),
        "task_id": task_id.strip(),
        "work_item_id": work_item_id,
        "task_version": task_version,
        "attempt_id": attempt_id,
        "artifact_refs": list(artifact_refs),
        "artifact_refs_sha256": _content_sha256({"artifact_refs": artifact_refs}),
        "git_branch": expected_git_branch.strip(),
        "git_head": expected_head,
        "provider": provider,
    }
    reservation_key = _content_sha256(binding)

    lease = ProjectOperationLease(
        root,
        operation_kind="stage_shard_fresh_authority",
        surface="stage_parallel_admission",
    ).acquire()
    for _ in range(200):
        if lease.held or lease.error_code != PROJECT_OPERATION_BUSY:
            break
        time.sleep(0.005)
        lease = ProjectOperationLease(
            root,
            operation_kind="stage_shard_fresh_authority",
            surface="stage_parallel_admission",
        ).acquire()
    if not lease.held:
        return {
            "ok": False,
            "error_code": (
                FRESH_EXECUTOR_ADMISSION_PROJECT_BUSY
                if lease.error_code == PROJECT_OPERATION_BUSY
                else FRESH_EXECUTOR_ADMISSION_LEASE_UNAVAILABLE
            ),
        }
    try:
        facts = collect_fresh_admission_facts(root)
        decision = build_fresh_admission_decision(facts)
        if not decision.get("allowed"):
            return {
                "ok": False,
                "error_code": decision.get("error_code"),
                "hard_blockers": decision.get("hard_blockers"),
            }
        if (
            facts.get("repository") != expected_repository
            or facts.get("git_branch") != expected_git_branch
            or facts.get("project_head") != expected_head
        ):
            return {"ok": False, "error_code": STAGE_SHARD_AUTHORITY_BINDING_MISMATCH}

        writable = _open_authority_state_fds(root)
        if not writable.get("ok"):
            return writable
        _close_fds(
            [writable["project_fd"], writable["colameta_fd"], writable["runtime_fd"], writable["sessions_fd"]]
        )
        state = _open_authority_state_read_fds(root)
        if not state.get("ok"):
            return state
        matching: list[tuple[str, int, dict[str, Any]]] = []
        opened: list[int] = []
        try:
            for candidate in sorted(os.listdir(state["sessions_fd"])):
                if _validate_authority_id(candidate) is False:
                    continue
                authority_fd, authority_error = _open_existing_authority_dir(
                    state["sessions_fd"], candidate
                )
                if authority_fd < 0:
                    if authority_error == FRESH_EXECUTOR_AUTHORITY_NOT_FOUND:
                        continue
                    return {"ok": False, "error_code": STAGE_SHARD_AUTHORITY_RESERVATION_MALFORMED}
                reservation = _read_stage_shard_reservation(state, authority_fd, candidate)
                if reservation.get("error_code") == "NOT_FOUND":
                    os.close(authority_fd)
                    continue
                if not reservation.get("ok"):
                    os.close(authority_fd)
                    return {"ok": False, "error_code": STAGE_SHARD_AUTHORITY_RESERVATION_MALFORMED}
                record = reservation["record"]
                if record["stage_shard_admission_key"] == reservation_key:
                    matching.append((candidate, authority_fd, record))
                    opened.append(authority_fd)
                else:
                    os.close(authority_fd)

            if len(matching) > 1:
                return {"ok": False, "error_code": STAGE_SHARD_AUTHORITY_RESERVATION_CONFLICT}
            if matching:
                authority_id, authority_fd, reservation_record = matching[0]
                if _stage_shard_reservation_binding(reservation_record) != binding:
                    return {"ok": False, "error_code": STAGE_SHARD_AUTHORITY_BINDING_MISMATCH}
                recovered = True
            else:
                recovered = False
                authority_id = ""
                authority_fd = -1
                for _ in range(16):
                    candidate = uuid.uuid4().hex
                    try:
                        os.mkdir(candidate, dir_fd=state["sessions_fd"], mode=0o700)
                        os.fsync(state["sessions_fd"])
                    except FileExistsError:
                        continue
                    authority_fd, authority_error = _open_existing_authority_dir(
                        state["sessions_fd"], candidate
                    )
                    if authority_fd < 0:
                        return {"ok": False, "error_code": authority_error}
                    authority_id = candidate
                    opened.append(authority_fd)
                    break
                if not authority_id:
                    return {"ok": False, "error_code": STAGE_SHARD_AUTHORITY_RESERVATION_CONFLICT}
                reservation_record = {
                    "schema_version": STAGE_SHARD_RESERVATION_SCHEMA_VERSION,
                    "source": STAGE_SHARD_RESERVATION_SOURCE,
                    "reserved_authority_id": authority_id,
                    "stage_shard_admission_key": reservation_key,
                    **binding,
                    "created_at": now or _now_iso(),
                }
                published = _publish_json_create_exclusive(
                    authority_fd,
                    STAGE_SHARD_RESERVATION_FILENAME,
                    reservation_record,
                )
                if not published.get("ok") or not _verify_authority_ancestor_chain(
                    state, authority_id=authority_id, authority_fd=authority_fd
                ):
                    return {"ok": False, "error_code": STAGE_SHARD_AUTHORITY_PUBLICATION_FAILED}

            admission = _read_admission_verification_from_fd(
                state,
                authority_fd,
                authority_id=authority_id,
                expected_head=expected_head,
                expected_provider=provider,
                expected_repository=expected_repository,
                expected_git_branch=expected_git_branch,
            )
            if admission.get("error_code") == FRESH_EXECUTOR_AUTHORITY_NOT_FOUND:
                admission_record = _build_admission_record(
                    authority_id=authority_id,
                    facts=facts,
                    created_at=now or _now_iso(),
                )
                published = _publish_json_create_exclusive(
                    authority_fd, ADMISSION_FILENAME, admission_record
                )
                if not published.get("ok") or not _verify_authority_ancestor_chain(
                    state, authority_id=authority_id, authority_fd=authority_fd
                ):
                    return {"ok": False, "error_code": STAGE_SHARD_AUTHORITY_PUBLICATION_FAILED}
                admission = _read_admission_verification_from_fd(
                    state,
                    authority_fd,
                    authority_id=authority_id,
                    expected_head=expected_head,
                    expected_provider=provider,
                    expected_repository=expected_repository,
                    expected_git_branch=expected_git_branch,
                )
            if not admission.get("ok"):
                return {**admission, "executor_authority_id": authority_id}
            binding_evidence = _read_verified_authority_file(
                authority_fd,
                EXECUTION_BINDING_FILENAME,
                state=state,
                authority_id=authority_id,
                authority_fd=authority_fd,
            )
            if binding_evidence.get("error_code") != "NOT_FOUND":
                return {
                    "ok": False,
                    "error_code": STAGE_SHARD_AUTHORITY_ALREADY_CONSUMED,
                    "executor_authority_id": authority_id,
                }
            return {
                "ok": True,
                "status": "authority_recovered" if recovered else "authority_created",
                "executor_authority_id": authority_id,
                "admission_sha256": admission["admission_sha256"],
                "stage_shard_admission_key": reservation_key,
                "record": admission["record"],
                "reservation": reservation_record,
                "unconsumed": True,
                "idempotent_replay": recovered,
                "provider_started": False,
            }
        finally:
            for fd in set(opened):
                try:
                    os.close(fd)
                except OSError:
                    pass
            _close_fds(state["fds"])
    finally:
        lease.release()


def _best_effort_remove_empty_dir(path: str) -> None:
    try:
        os.rmdir(path)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# R0 binding: authoritative execution read + single-consumption binding
# ---------------------------------------------------------------------------

def _open_authority_state_read_fds(project_root: str) -> dict[str, Any]:
    """Open the canonical authority state root READ-ONLY (never creates).

    Every component is opened relative to its already-open parent with
    ``O_NOFOLLOW``, so a symlink at any level fails closed and a missing
    component means the authority cannot exist (``AUTHORITY_NOT_FOUND``).
    """
    root = os.path.abspath(os.path.expanduser(project_root))
    fds: list[int] = []
    links: list[tuple[int | None, str, int, int]] = []
    try:
        root_before = os.stat(root, follow_symlinks=False)
        project_fd = os.open(
            root,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
        fds.append(project_fd)
        project_stat = os.fstat(project_fd)
        if (
            not _trusted_authority_ancestor(project_stat)
            or (root_before.st_dev, root_before.st_ino)
            != (project_stat.st_dev, project_stat.st_ino)
        ):
            raise OSError(errno.EPERM, "unsafe project root")
        links.append((None, root, project_stat.st_dev, project_stat.st_ino))
        parent_fd = project_fd
        opened_children: list[int] = []
        for component in (_RUNNER_DIRNAME, "runtime", "executor-sessions"):
            child_fd = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=parent_fd,
            )
            fds.append(child_fd)
            opened_children.append(child_fd)
            child_stat = os.fstat(child_fd)
            if not _trusted_authority_ancestor(child_stat):
                raise OSError(errno.EPERM, "unsafe authority ancestor")
            links.append(
                (parent_fd, component, child_stat.st_dev, child_stat.st_ino)
            )
            parent_fd = child_fd
        colameta_fd, runtime_fd, sessions_fd = opened_children
    except OSError as exc:
        _close_fds(fds)
        return {
            "ok": False,
            "error_code": FRESH_EXECUTOR_AUTHORITY_NOT_FOUND,
            "reason": f"{type(exc).__name__}:{exc.errno}",
        }
    return {
        "ok": True,
        "project_fd": project_fd,
        "colameta_fd": colameta_fd,
        "runtime_fd": runtime_fd,
        "sessions_fd": sessions_fd,
        "fds": fds,
        "links": links,
        "canonical_project_root": root,
        "authority_root_path": os.path.join(
            root, _RUNNER_DIRNAME, "runtime", "executor-sessions"
        ),
    }


def _open_existing_authority_dir(
    sessions_fd: int, authority_id: str
) -> tuple[int, str | None]:
    """Open an EXISTING authority directory anchored to ``sessions_fd``.

    Returns ``(authority_fd, None)`` or ``(-1, error_code)``.  Never creates.
    """
    try:
        authority_fd = os.open(
            authority_id,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=sessions_fd,
        )
        if not _trusted_authority_directory(os.fstat(authority_fd)):
            os.close(authority_fd)
            return -1, FRESH_EXECUTOR_AUTHORITY_MALFORMED
        return authority_fd, None
    except FileNotFoundError:
        return -1, FRESH_EXECUTOR_AUTHORITY_NOT_FOUND
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.ENOTDIR):
            return -1, FRESH_EXECUTOR_AUTHORITY_MALFORMED
        return -1, FRESH_EXECUTOR_AUTHORITY_NOT_FOUND


def _verify_authority_ancestor_chain(
    state: dict[str, Any], *, authority_id: str | None = None, authority_fd: int = -1
) -> bool:
    try:
        for parent_fd, name, device, inode in state["links"]:
            current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            if (
                not _trusted_authority_ancestor(current)
                or (current.st_dev, current.st_ino) != (device, inode)
            ):
                return False
        if authority_id is not None:
            current = os.stat(
                authority_id,
                dir_fd=state["sessions_fd"],
                follow_symlinks=False,
            )
            opened = os.fstat(authority_fd)
            if (
                not _trusted_authority_directory(current)
                or not _trusted_authority_directory(opened)
                or (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino)
            ):
                return False
        return True
    except OSError:
        return False


def _read_verified_authority_file(
    parent_fd: int,
    filename: str,
    *,
    state: dict[str, Any],
    authority_id: str,
    authority_fd: int,
) -> dict[str, Any]:
    """Read one authority record with stable bytes, metadata, and path proof.

    Missing files are also path-revalidated so an ancestor/name replacement
    cannot turn an existing-binding absence probe into authority to create.
    """
    file_fd = -1
    try:
        if not _verify_authority_ancestor_chain(
            state, authority_id=authority_id, authority_fd=authority_fd
        ):
            return {"ok": False, "error_code": "ANCESTOR_UNSTABLE"}
        try:
            file_fd = os.open(
                filename,
                os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=parent_fd,
            )
        except FileNotFoundError:
            if not _verify_authority_ancestor_chain(
                state, authority_id=authority_id, authority_fd=authority_fd
            ):
                return {"ok": False, "error_code": "ANCESTOR_UNSTABLE"}
            return {"ok": False, "error_code": "NOT_FOUND"}
        except OSError:
            return {"ok": False, "error_code": "FILE_UNSAFE"}
        before = os.fstat(file_fd)
        if not _trusted_authority_file(before):
            return {"ok": False, "error_code": "FILE_UNSAFE"}

        def read_complete() -> bytes:
            remaining = before.st_size
            chunks: list[bytes] = []
            while remaining:
                chunk = os.read(file_fd, min(65536, remaining))
                if not chunk:
                    raise OSError("authority record truncated")
                chunks.append(chunk)
                remaining -= len(chunk)
            if os.read(file_fd, 1):
                raise OSError("authority record grew")
            return b"".join(chunks)

        raw = read_complete()
        os.lseek(file_fd, 0, os.SEEK_SET)
        repeated = read_complete()
        after = os.fstat(file_fd)
        current = os.stat(filename, dir_fd=parent_fd, follow_symlinks=False)
        if (
            raw != repeated
            or not _same_authority_file_snapshot(before, after)
            or not _same_authority_file_snapshot(before, current)
            or not _trusted_authority_file(after)
            or not _trusted_authority_file(current)
            or not _verify_authority_ancestor_chain(
                state, authority_id=authority_id, authority_fd=authority_fd
            )
        ):
            return {"ok": False, "error_code": "FILE_UNSTABLE"}
        return {
            "ok": True,
            "raw": raw,
            "identity": _durable_identity(before),
            "metadata": _durable_metadata(before),
            "raw_sha256": hashlib.sha256(raw).hexdigest(),
        }
    except OSError:
        return {"ok": False, "error_code": "FILE_UNSTABLE"}
    finally:
        if file_fd >= 0:
            try:
                os.close(file_fd)
            except OSError:
                pass


def _validate_admission_for_execution(
    record: Any,
    *,
    authority_id: str,
    canonical_project_root: str,
    expected_head: str | None,
    expected_provider: str,
    expected_repository: str | None,
    expected_git_branch: str | None,
) -> str | None:
    """Exact schema validation of an admission record for execution.

    Returns ``None`` when the record is a valid, current, idle, unconsumed
    authority for the requested context; otherwise the precise error code.
    """
    if not isinstance(record, dict):
        return FRESH_EXECUTOR_AUTHORITY_MALFORMED
    if frozenset(record) != _ADMISSION_FIELDS:
        return FRESH_EXECUTOR_AUTHORITY_MALFORMED
    if record.get("schema_version") != FRESH_EXECUTOR_AUTHORITY_SCHEMA_VERSION:
        return FRESH_EXECUTOR_AUTHORITY_MALFORMED
    if (
        not isinstance(record.get("executor_authority_id"), str)
        or record["executor_authority_id"] != authority_id
    ):
        return FRESH_EXECUTOR_AUTHORITY_MALFORMED
    if (
        not isinstance(record.get("project_root"), str)
        or record["project_root"] != canonical_project_root
    ):
        return FRESH_EXECUTOR_AUTHORITY_MALFORMED
    repository = record.get("repository")
    if not isinstance(repository, str) or not repository.strip():
        return FRESH_EXECUTOR_AUTHORITY_MALFORMED
    git_branch = record.get("git_branch")
    if not isinstance(git_branch, str) or not git_branch.strip():
        return FRESH_EXECUTOR_AUTHORITY_MALFORMED
    if (
        not isinstance(record.get("source"), str)
        or record["source"] != FRESH_EXECUTOR_AUTHORITY_SOURCE
    ):
        return FRESH_EXECUTOR_AUTHORITY_MALFORMED
    if expected_repository is not None and repository != expected_repository:
        return FRESH_EXECUTOR_AUTHORITY_MALFORMED
    if expected_git_branch is not None and git_branch != expected_git_branch:
        return FRESH_EXECUTOR_AUTHORITY_MALFORMED
    admitted_head = record.get("admitted_head")
    if not isinstance(admitted_head, str) or _FULL_HEAD_RE.fullmatch(admitted_head) is None:
        return FRESH_EXECUTOR_AUTHORITY_MALFORMED
    if expected_head is not None and admitted_head.lower() != str(expected_head).lower():
        return FRESH_EXECUTOR_AUTHORITY_HEAD_MISMATCH
    if not isinstance(record.get("provider"), str):
        return FRESH_EXECUTOR_AUTHORITY_MALFORMED
    if record["provider"] != expected_provider:
        return FRESH_EXECUTOR_AUTHORITY_PROVIDER_MISMATCH
    if not isinstance(record.get("admission_state"), str):
        return FRESH_EXECUTOR_AUTHORITY_MALFORMED
    if record["admission_state"] != FRESH_EXECUTOR_AUTHORITY_STATE:
        return FRESH_EXECUTOR_AUTHORITY_STATE_INVALID
    if not isinstance(record.get("operation_state"), str):
        return FRESH_EXECUTOR_AUTHORITY_MALFORMED
    if record["operation_state"] != FRESH_EXECUTOR_OPERATION_STATE:
        return FRESH_EXECUTOR_AUTHORITY_STATE_INVALID
    if record.get("provider_session_identity") is not None:
        return FRESH_EXECUTOR_AUTHORITY_STATE_INVALID
    if record.get("parent_authority_id") is not None:
        return FRESH_EXECUTOR_AUTHORITY_STATE_INVALID
    if record.get("continuation_from") is not None:
        return FRESH_EXECUTOR_AUTHORITY_STATE_INVALID
    if type(record.get("historical_session_inherited")) is not bool:
        return FRESH_EXECUTOR_AUTHORITY_MALFORMED
    if record["historical_session_inherited"] is not False:
        return FRESH_EXECUTOR_AUTHORITY_STATE_INVALID
    if type(record.get("provider_invoked")) is not bool:
        return FRESH_EXECUTOR_AUTHORITY_MALFORMED
    if record["provider_invoked"] is not False:
        return FRESH_EXECUTOR_AUTHORITY_STATE_INVALID
    if type(record.get("work_started")) is not bool:
        return FRESH_EXECUTOR_AUTHORITY_MALFORMED
    if record["work_started"] is not False:
        return FRESH_EXECUTOR_AUTHORITY_STATE_INVALID
    if not isinstance(record.get("created_at"), str) or not record["created_at"].strip():
        return FRESH_EXECUTOR_AUTHORITY_MALFORMED
    return None


def _read_admission_verification_from_fd(
    state: dict[str, Any],
    authority_fd: int,
    *,
    authority_id: str,
    expected_admission_sha256: str | None = None,
    expected_head: str | None = None,
    expected_provider: str = "codex",
    expected_repository: str | None = None,
    expected_git_branch: str | None = None,
) -> dict[str, Any]:
    evidence = _read_verified_authority_file(
        authority_fd,
        ADMISSION_FILENAME,
        state=state,
        authority_id=authority_id,
        authority_fd=authority_fd,
    )
    if not evidence.get("ok"):
        missing = evidence.get("error_code") == "NOT_FOUND"
        return {
            "ok": False,
            "error_code": (
                FRESH_EXECUTOR_AUTHORITY_NOT_FOUND
                if missing
                else FRESH_EXECUTOR_AUTHORITY_MALFORMED
            ),
            "reason": "admission record missing" if missing else "admission record unsafe",
        }
    admission_sha256 = evidence["raw_sha256"]
    if expected_admission_sha256 is not None:
        normalized_expected = str(expected_admission_sha256).lower()
        if _SHA256_RE.fullmatch(normalized_expected) is None:
            return {
                "ok": False,
                "error_code": FRESH_EXECUTOR_AUTHORITY_INVALID_CONTEXT,
                "reason": "malformed expected admission hash",
            }
        if admission_sha256 != normalized_expected:
            return {
                "ok": False,
                "error_code": FRESH_EXECUTOR_AUTHORITY_HASH_MISMATCH,
                "observed_sha256": admission_sha256,
                "expected_sha256": normalized_expected,
                "reason": "admission bytes do not match the expected hash",
            }
    try:
        record = json.loads(evidence["raw"].decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return {
            "ok": False,
            "error_code": FRESH_EXECUTOR_AUTHORITY_MALFORMED,
            "reason": "admission record is not valid JSON",
        }
    validation_error = _validate_admission_for_execution(
        record,
        authority_id=authority_id,
        canonical_project_root=state["canonical_project_root"],
        expected_head=expected_head,
        expected_provider=expected_provider,
        expected_repository=expected_repository,
        expected_git_branch=expected_git_branch,
    )
    if validation_error is not None:
        return {
            "ok": False,
            "error_code": validation_error,
            "reason": f"admission validation failed: {validation_error}",
        }
    assert isinstance(record, dict)
    return {
        "ok": True,
        "record": record,
        "admission_sha256": admission_sha256,
        "durable_contract": {
            "identity": evidence["identity"],
            "metadata": evidence["metadata"],
            "raw_sha256": admission_sha256,
            "content_sha256": _content_sha256(record),
        },
    }


def _read_admission_verification(
    project_root: str,
    authority_id: str,
    **expected: Any,
) -> dict[str, Any]:
    """Private exact admission read carrying non-public durable evidence."""

    if _validate_authority_id(authority_id) is False:
        return {"ok": False, "error_code": FRESH_EXECUTOR_AUTHORITY_INVALID_CONTEXT}
    state = _open_authority_state_read_fds(project_root)
    if not state.get("ok"):
        return {
            "ok": False,
            "error_code": state.get("error_code"),
            "reason": state.get("reason"),
        }
    authority_fd = -1
    try:
        authority_fd, authority_error = _open_existing_authority_dir(
            state["sessions_fd"], authority_id
        )
        if authority_fd < 0:
            return {"ok": False, "error_code": authority_error}
        return _read_admission_verification_from_fd(
            state,
            authority_fd,
            authority_id=authority_id,
            **expected,
        )
    finally:
        if authority_fd >= 0:
            try:
                os.close(authority_fd)
            except OSError:
                pass
        _close_fds(state["fds"])


def inspect_fresh_executor_authority_for_execution(
    project_root: str,
    authority_id: str,
    *,
    expected_admission_sha256: str | None = None,
    expected_head: str | None = None,
    expected_provider: str = "codex",
    expected_repository: str | None = None,
    expected_git_branch: str | None = None,
) -> dict[str, Any]:
    """Authoritative, FD-anchored admission read for execution decisions.

    This read walks ``project -> .colameta -> runtime ->
    executor-sessions -> <authority_id>`` one ``O_NOFOLLOW`` component at a
    time relative to already-open parent FDs, hashes the raw admission bytes
    and compares against ``expected_admission_sha256`` when supplied, then
    JSON-parses and exact-schema-validates the record.  It also reports
    whether an ``execution-binding.json`` already exists (consumption state).
    Never mutates anything.
    """
    if _validate_authority_id(authority_id) is False:
        return {
            "ok": False,
            "error_code": FRESH_EXECUTOR_AUTHORITY_INVALID_CONTEXT,
            "reason": "malformed authority id",
        }
    root = os.path.abspath(os.path.expanduser(project_root))
    state = _open_authority_state_read_fds(root)
    if not state.get("ok"):
        return {
            "ok": False,
            "error_code": state.get("error_code"),
            "reason": state.get("reason"),
        }
    authority_fd = -1
    try:
        authority_fd, authority_error = _open_existing_authority_dir(
            state["sessions_fd"], authority_id
        )
        if authority_fd < 0:
            return {
                "ok": False,
                "error_code": authority_error,
                "executor_authority_id": authority_id,
                "reason": "authority directory unavailable",
            }
        admission = _read_admission_verification_from_fd(
            state,
            authority_fd,
            authority_id=authority_id,
            expected_admission_sha256=expected_admission_sha256,
            expected_head=expected_head,
            expected_provider=expected_provider,
            expected_repository=expected_repository,
            expected_git_branch=expected_git_branch,
        )
        if not admission.get("ok"):
            return {**admission, "executor_authority_id": authority_id}
        record = admission["record"]
        admission_sha256 = admission["admission_sha256"]

        binding_present = False
        binding_record: dict[str, Any] | None = None
        binding_evidence = _read_verified_authority_file(
            authority_fd,
            EXECUTION_BINDING_FILENAME,
            state=state,
            authority_id=authority_id,
            authority_fd=authority_fd,
        )
        if binding_evidence.get("error_code") == "NOT_FOUND":
            binding_present = False
        else:
            binding_present = True
            if not binding_evidence.get("ok"):
                return {
                    "ok": False,
                    "error_code": FRESH_EXECUTOR_AUTHORITY_MALFORMED,
                    "executor_authority_id": authority_id,
                    "reason": "execution binding unsafe",
                }
            try:
                parsed = json.loads(binding_evidence["raw"].decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                parsed = None
            if (
                _validate_execution_binding_contract(
                    parsed,
                    authority_id=authority_id,
                    canonical_project_root=root,
                )
                is not None
            ):
                return {
                    "ok": False,
                    "error_code": FRESH_EXECUTOR_AUTHORITY_MALFORMED,
                    "executor_authority_id": authority_id,
                    "reason": "execution binding malformed",
                }
            binding_record = parsed

        if not _verify_authority_ancestor_chain(
            state, authority_id=authority_id, authority_fd=authority_fd
        ):
            return {
                "ok": False,
                "error_code": FRESH_EXECUTOR_AUTHORITY_MALFORMED,
                "executor_authority_id": authority_id,
                "reason": "authority ancestor chain changed during inspection",
            }

        return {
            "ok": True,
            "executor_authority_id": authority_id,
            "admission_sha256": admission_sha256,
            "admission_record_path": os.path.join(
                state["authority_root_path"], authority_id, ADMISSION_FILENAME
            ),
            "record": record,
            "execution_binding_present": binding_present,
            "execution_binding": binding_record,
            "unconsumed": not binding_present,
        }
    finally:
        if authority_fd >= 0:
            try:
                os.close(authority_fd)
            except OSError:
                pass
        _close_fds(
            [
                state["project_fd"],
                state["colameta_fd"],
                state["runtime_fd"],
                state["sessions_fd"],
            ]
        )


def inspect_stage_shard_fresh_executor_authority(
    project_root: str,
    authority_id: str,
    *,
    expected_stage_shard_admission_key: str,
    expected_admission_sha256: str,
    expected_binding: dict[str, Any],
) -> dict[str, Any]:
    """Read-only verification of an exact Stage reservation/admission pair."""

    if (
        _validate_authority_id(authority_id) is False
        or not isinstance(expected_stage_shard_admission_key, str)
        or _SHA256_RE.fullmatch(expected_stage_shard_admission_key) is None
        or not isinstance(expected_binding, dict)
    ):
        return {"ok": False, "error_code": STAGE_SHARD_AUTHORITY_BINDING_MISMATCH}
    root = os.path.abspath(os.path.expanduser(project_root))
    state = _open_authority_state_read_fds(root)
    if not state.get("ok"):
        return {"ok": False, "error_code": STAGE_SHARD_AUTHORITY_RESERVATION_MALFORMED}
    authority_fd = -1
    try:
        authority_fd, authority_error = _open_existing_authority_dir(
            state["sessions_fd"], authority_id
        )
        if authority_fd < 0:
            return {"ok": False, "error_code": authority_error}
        reservation = _read_stage_shard_reservation(state, authority_fd, authority_id)
        if not reservation.get("ok"):
            return {"ok": False, "error_code": STAGE_SHARD_AUTHORITY_RESERVATION_MALFORMED}
        record = reservation["record"]
        if (
            record.get("stage_shard_admission_key")
            != expected_stage_shard_admission_key
            or _stage_shard_reservation_binding(record) != expected_binding
            or not _verify_authority_ancestor_chain(
                state, authority_id=authority_id, authority_fd=authority_fd
            )
        ):
            return {"ok": False, "error_code": STAGE_SHARD_AUTHORITY_BINDING_MISMATCH}
    finally:
        if authority_fd >= 0:
            try:
                os.close(authority_fd)
            except OSError:
                pass
        _close_fds(
            [
                state["project_fd"], state["colameta_fd"],
                state["runtime_fd"], state["sessions_fd"],
            ]
        )
    admission = inspect_fresh_executor_authority_for_execution(
        root,
        authority_id,
        expected_admission_sha256=expected_admission_sha256,
        expected_head=expected_binding.get("git_head"),
        expected_provider=str(expected_binding.get("provider") or ""),
        expected_repository=str(expected_binding.get("repository") or ""),
        expected_git_branch=str(expected_binding.get("git_branch") or ""),
    )
    if not admission.get("ok") or admission.get("unconsumed") is not True:
        return admission
    return {
        **admission,
        "stage_shard_admission_key": expected_stage_shard_admission_key,
        "stage_reservation_verified": True,
    }


def _validate_execution_binding_contract(
    record: Any,
    *,
    authority_id: str,
    canonical_project_root: str,
    expected_run_id: str | None = None,
) -> str | None:
    if not isinstance(record, dict):
        return "BINDING_CONTRACT_NOT_OBJECT"
    if frozenset(record) != _BINDING_FIELDS:
        return "BINDING_CONTRACT_FIELDS_INVALID"
    if record.get("schema_version") != FRESH_EXECUTOR_BINDING_SCHEMA_VERSION:
        return "BINDING_SCHEMA_VERSION_INVALID"
    if record.get("executor_authority_id") != authority_id:
        return "BINDING_AUTHORITY_ID_MISMATCH"
    admission_sha256 = record.get("admission_sha256")
    if not isinstance(admission_sha256, str) or _SHA256_RE.fullmatch(admission_sha256) is None:
        return "BINDING_ADMISSION_DIGEST_INVALID"
    if record.get("project_root") != canonical_project_root:
        return "BINDING_PROJECT_ROOT_MISMATCH"
    repository = record.get("repository")
    if repository is not None and (not isinstance(repository, str) or not repository.strip()):
        return "BINDING_REPOSITORY_INVALID"
    run_id = record.get("run_id")
    if not isinstance(run_id, str) or _RUN_ID_RE.fullmatch(run_id) is None:
        return "BINDING_RUN_ID_INVALID"
    if expected_run_id is not None and run_id != expected_run_id:
        return "BINDING_RUN_ID_MISMATCH"
    preview_id = record.get("preview_id")
    if not isinstance(preview_id, str) or _PREVIEW_ID_RE.fullmatch(preview_id) is None:
        return "BINDING_PREVIEW_ID_INVALID"
    admitted_head = record.get("admitted_head")
    if not isinstance(admitted_head, str) or _FULL_HEAD_RE.fullmatch(admitted_head) is None:
        return "BINDING_HEAD_INVALID"
    if record.get("provider") != "codex":
        return "BINDING_PROVIDER_INVALID"
    if record.get("executor_session_mode") != "start_new":
        return "BINDING_SESSION_MODE_INVALID"
    if record.get("source") != FRESH_EXECUTOR_BINDING_SOURCE:
        return "BINDING_SOURCE_INVALID"
    event_stream_error = _validate_event_stream_contract(record.get("event_stream"))
    if event_stream_error is not None:
        return event_stream_error
    if not isinstance(record.get("bound_at"), str) or not record["bound_at"].strip():
        return "BINDING_BOUND_AT_INVALID"
    work_target = {
        field: record[field]
        for field in ("work_item_id", "task_version", "attempt_id", "artifact_refs")
    }
    if optional_work_item_reference_rejections(work_target):
        return "BINDING_WORK_TARGET_INVALID"
    return None


def _read_execution_binding_verification(
    project_root: str,
    authority_id: str,
    *,
    expected_run_id: str | None = None,
) -> dict[str, Any]:
    """Internal exact binding read with safe durable evidence."""

    if _validate_authority_id(authority_id) is False:
        return {"ok": False, "error_code": "BINDING_AUTHORITY_ID_INVALID"}
    root = os.path.abspath(os.path.expanduser(project_root))
    state = _open_authority_state_read_fds(root)
    if not state.get("ok"):
        return {"ok": False, "error_code": "BINDING_ANCESTOR_UNSAFE"}
    authority_fd = -1
    try:
        authority_fd, authority_error = _open_existing_authority_dir(
            state["sessions_fd"], authority_id
        )
        if authority_fd < 0:
            return {
                "ok": False,
                "error_code": authority_error or "BINDING_AUTHORITY_UNSAFE",
            }
        evidence = _read_verified_authority_file(
            authority_fd,
            EXECUTION_BINDING_FILENAME,
            state=state,
            authority_id=authority_id,
            authority_fd=authority_fd,
        )
        if not evidence.get("ok"):
            return {
                "ok": False,
                "error_code": f"BINDING_{evidence.get('error_code') or 'READ_FAILED'}",
            }
        if not _verify_authority_ancestor_chain(
            state, authority_id=authority_id, authority_fd=authority_fd
        ):
            return {"ok": False, "error_code": "BINDING_ANCESTOR_UNSTABLE"}
        raw = evidence["raw"]
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return {"ok": False, "error_code": "BINDING_JSON_INVALID"}
        contract_error = _validate_execution_binding_contract(
            parsed,
            authority_id=authority_id,
            canonical_project_root=root,
            expected_run_id=expected_run_id,
        )
        if contract_error is not None:
            return {"ok": False, "error_code": contract_error}
        assert isinstance(parsed, dict)
        durable_contract = {
            "identity": evidence["identity"],
            "metadata": evidence["metadata"],
            "raw_sha256": evidence["raw_sha256"],
            "content_sha256": _content_sha256(parsed),
        }
        return {
            "ok": True,
            "record": parsed,
            "durable_contract": durable_contract,
        }
    finally:
        if authority_fd >= 0:
            try:
                os.close(authority_fd)
            except OSError:
                pass
        _close_fds(
            [
                state["project_fd"], state["colameta_fd"],
                state["runtime_fd"], state["sessions_fd"],
            ]
        )


def read_execution_binding(
    project_root: str, authority_id: str
) -> dict[str, Any] | None:
    """Read an exact durable execution binding, or fail closed with ``None``."""

    verification = _read_execution_binding_verification(project_root, authority_id)
    record = verification.get("record") if verification.get("ok") else None
    return record if isinstance(record, dict) else None


def _build_execution_binding_payload(
    *,
    authority_id: str,
    admission_sha256: str | None,
    project_root: str,
    repository: str | None,
    run_id: str,
    preview_id: str,
    admitted_head: str,
    provider: str,
    executor_session_mode: str,
    work_item_id: Any,
    task_version: Any,
    attempt_id: Any,
    artifact_refs: list[str],
    event_stream: dict[str, Any],
    now: str | None = None,
) -> dict[str, Any]:
    """Shared execution-binding payload (immutable fields)."""

    return {
        "schema_version": FRESH_EXECUTOR_BINDING_SCHEMA_VERSION,
        "executor_authority_id": authority_id,
        "admission_sha256": admission_sha256,
        "project_root": project_root,
        "repository": repository,
        "run_id": run_id,
        "preview_id": preview_id,
        "admitted_head": admitted_head,
        "provider": provider,
        "executor_session_mode": executor_session_mode,
        "work_item_id": work_item_id,
        "task_version": task_version,
        "attempt_id": attempt_id,
        "artifact_refs": artifact_refs,
        "event_stream": event_stream,
        "bound_at": now or _now_iso(),
        "source": FRESH_EXECUTOR_BINDING_SOURCE,
    }


def create_execution_binding(
    project_root: str,
    authority_id: str,
    *,
    run_id: str,
    preview_id: str,
    admitted_head: str,
    provider: str = "codex",
    executor_session_mode: str = "start_new",
    work_target: dict[str, Any] | None = None,
    admission_sha256: str | None = None,
    repository: str | None = None,
    event_stream: dict[str, Any] | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    """Atomically consume an authority by creating ``execution-binding.json``.

    The binding is created relative to the already-open authority directory FD
    with ``O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC`` (mode 0600), then fsync'd
    (file + authority directory).  The admission record is never modified.

    Existing-binding semantics are never-continue: a binding for the same
    run/preview is ``AUTHORITY_ALREADY_CONSUMED``; any other or malformed
    binding is ``AUTHORITY_BINDING_CONFLICT``.
    """
    if _validate_authority_id(authority_id) is False:
        return {
            "ok": False,
            "error_code": FRESH_EXECUTOR_AUTHORITY_INVALID_CONTEXT,
            "reason": "malformed authority id",
        }
    if (
        not isinstance(run_id, str)
        or not run_id.strip()
        or not isinstance(preview_id, str)
        or not preview_id.strip()
    ):
        return {
            "ok": False,
            "error_code": FRESH_EXECUTOR_AUTHORITY_INVALID_CONTEXT,
            "reason": "run_id and preview_id are required",
        }
    if provider != "codex":
        return {
            "ok": False,
            "error_code": FRESH_EXECUTOR_AUTHORITY_PROVIDER_MISMATCH,
            "reason": "R0 fresh binding is codex-only",
        }
    if executor_session_mode != "start_new":
        return {
            "ok": False,
            "error_code": FRESH_EXECUTOR_AUTHORITY_SESSION_MODE_MISMATCH,
            "reason": "fresh authority binding requires executor_session_mode=start_new",
        }
    event_stream_error = _validate_event_stream_contract(event_stream)
    if event_stream_error is not None:
        return {
            "ok": False,
            "error_code": FRESH_EXECUTOR_AUTHORITY_INVALID_CONTEXT,
            "reason": event_stream_error,
        }
    if not isinstance(admitted_head, str) or _FULL_HEAD_RE.fullmatch(admitted_head) is None:
        return {
            "ok": False,
            "error_code": FRESH_EXECUTOR_AUTHORITY_INVALID_CONTEXT,
            "reason": "malformed admitted_head",
        }
    work_item_id = None
    task_version = None
    attempt_id = None
    artifact_refs: list[str] = []
    if isinstance(work_target, dict):
        work_item_id = work_target.get("work_item_id")
        task_version = work_target.get("task_version")
        attempt_id = work_target.get("attempt_id")
        artifact_refs = list(work_target.get("artifact_refs") or [])
        if not all(
            field in work_target
            for field in ("work_item_id", "task_version", "attempt_id", "artifact_refs")
        ):
            return {
                "ok": False,
                "error_code": FRESH_EXECUTOR_AUTHORITY_WORK_TARGET_REQUIRED,
                "reason": "complete governed work target required",
            }
        from runner.work_item_governance.references import (
            optional_work_item_reference_rejections,
        )

        rejections = optional_work_item_reference_rejections(work_target)
        if rejections:
            return {
                "ok": False,
                "error_code": FRESH_EXECUTOR_AUTHORITY_WORK_TARGET_REQUIRED,
                "reason": f"invalid governed work target: {rejections}",
            }
    else:
        return {
            "ok": False,
            "error_code": FRESH_EXECUTOR_AUTHORITY_WORK_TARGET_REQUIRED,
            "reason": "governed work target required for fresh authority binding",
        }

    root = os.path.abspath(os.path.expanduser(project_root))
    state = _open_authority_state_read_fds(root)
    if not state.get("ok"):
        return {
            "ok": False,
            "error_code": state.get("error_code"),
            "reason": state.get("reason"),
        }
    authority_fd = -1
    binding_fd = -1
    try:
        authority_fd, authority_error = _open_existing_authority_dir(
            state["sessions_fd"], authority_id
        )
        if authority_fd < 0:
            return {
                "ok": False,
                "error_code": authority_error,
                "executor_authority_id": authority_id,
                "reason": "authority directory unavailable",
            }

        existing = _read_verified_authority_file(
            authority_fd,
            EXECUTION_BINDING_FILENAME,
            state=state,
            authority_id=authority_id,
            authority_fd=authority_fd,
        )
        if existing.get("error_code") != "NOT_FOUND":
            parsed: Any = None
            if existing.get("ok"):
                try:
                    parsed = json.loads(existing["raw"].decode("utf-8"))
                except (UnicodeDecodeError, ValueError):
                    parsed = None
            contract_error = _validate_execution_binding_contract(
                parsed,
                authority_id=authority_id,
                canonical_project_root=root,
            )
            if (
                existing.get("ok")
                and contract_error is None
                and parsed.get("run_id") == run_id
                and parsed.get("preview_id") == preview_id
            ):
                return {
                    "ok": False,
                    "error_code": FRESH_EXECUTOR_AUTHORITY_ALREADY_CONSUMED,
                    "executor_authority_id": authority_id,
                    "reason": "authority already consumed by this run",
                    "execution_binding": parsed,
                }
            return {
                "ok": False,
                "error_code": FRESH_EXECUTOR_AUTHORITY_BINDING_CONFLICT,
                "executor_authority_id": authority_id,
                "reason": "existing execution binding is unsafe or conflicts",
                "execution_binding": parsed if contract_error is None else None,
            }

        if not _verify_authority_ancestor_chain(
            state, authority_id=authority_id, authority_fd=authority_fd
        ):
            return {
                "ok": False,
                "error_code": FRESH_EXECUTOR_AUTHORITY_BINDING_CONFLICT,
                "executor_authority_id": authority_id,
                "reason": "authority ancestor chain changed before binding create",
            }

        binding = _build_execution_binding_payload(
            authority_id=authority_id,
            admission_sha256=admission_sha256,
            project_root=root,
            repository=repository,
            run_id=run_id,
            preview_id=preview_id,
            admitted_head=admitted_head,
            provider=provider,
            executor_session_mode=executor_session_mode,
            work_item_id=work_item_id,
            task_version=task_version,
            attempt_id=attempt_id,
            artifact_refs=artifact_refs,
            event_stream=dict(event_stream or {}),
            now=now,
        )
        payload = (
            json.dumps(binding, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        )
        try:
            try:
                binding_fd = os.open(
                    EXECUTION_BINDING_FILENAME,
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | os.O_NOFOLLOW
                    | os.O_CLOEXEC,
                    0o600,
                    dir_fd=authority_fd,
                )
            except FileExistsError:
                return {
                    "ok": False,
                    "error_code": FRESH_EXECUTOR_AUTHORITY_ALREADY_CONSUMED,
                    "executor_authority_id": authority_id,
                    "reason": "concurrent binding create lost the race",
                }
            except OSError as exc:
                if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                    return {
                        "ok": False,
                        "error_code": FRESH_EXECUTOR_ADMISSION_STATE_ROOT_ESCAPE,
                        "executor_authority_id": authority_id,
                        "reason": "binding open refused by anchored create",
                    }
                return {
                    "ok": False,
                    "error_code": FRESH_EXECUTOR_AUTHORITY_BINDING_WRITE_FAILED,
                    "executor_authority_id": authority_id,
                    "reason": f"{type(exc).__name__}:{exc.errno}",
                }
            try:
                try:
                    _write_all_fd(binding_fd, payload.encode("utf-8"))
                    os.fsync(binding_fd)
                except OSError:
                    return {
                        "ok": False,
                        "error_code": FRESH_EXECUTOR_AUTHORITY_BINDING_WRITE_FAILED,
                        "executor_authority_id": authority_id,
                        "reason": "failed to persist the execution binding",
                    }
            finally:
                os.close(binding_fd)
                binding_fd = -1
        finally:
            if binding_fd >= 0:
                try:
                    os.close(binding_fd)
                except OSError:
                    pass
        try:
            os.fsync(authority_fd)
        except OSError:
            return {
                "ok": False,
                "error_code": FRESH_EXECUTOR_AUTHORITY_BINDING_WRITE_FAILED,
                "executor_authority_id": authority_id,
                "reason": "failed to persist the execution binding directory entry",
            }

        binding_evidence = _read_verified_authority_file(
            authority_fd,
            EXECUTION_BINDING_FILENAME,
            state=state,
            authority_id=authority_id,
            authority_fd=authority_fd,
        )
        if not binding_evidence.get("ok"):
            return {
                "ok": False,
                "error_code": FRESH_EXECUTOR_AUTHORITY_BINDING_WRITE_FAILED,
                "executor_authority_id": authority_id,
                "reason": "persisted execution binding could not be verified",
            }
        try:
            verified_binding = json.loads(binding_evidence["raw"].decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            verified_binding = None
        if (
            verified_binding != binding
            or _validate_execution_binding_contract(
                verified_binding,
                authority_id=authority_id,
                canonical_project_root=root,
                expected_run_id=run_id,
            )
            is not None
        ):
            return {
                "ok": False,
                "error_code": FRESH_EXECUTOR_AUTHORITY_BINDING_WRITE_FAILED,
                "executor_authority_id": authority_id,
                "reason": "persisted execution binding contract mismatch",
            }

        return {
            "ok": True,
            "executor_authority_id": authority_id,
            "execution_binding_path": os.path.join(
                state["authority_root_path"], authority_id, EXECUTION_BINDING_FILENAME
            ),
            "binding": binding,
        }
    finally:
        if authority_fd >= 0:
            try:
                os.close(authority_fd)
            except OSError:
                pass
        _close_fds(
            [
                state["project_fd"],
                state["colameta_fd"],
                state["runtime_fd"],
                state["sessions_fd"],
            ]
        )


def validate_and_create_execution_binding(
    project_root: str,
    authority_id: str,
    *,
    expected_admission_sha256: str,
    expected_head: str,
    expected_provider: str = "codex",
    expected_repository: str | None = None,
    expected_git_branch: str | None = None,
    run_id: str,
    preview_id: str,
    executor_session_mode: str = "start_new",
    work_target: dict[str, Any] | None = None,
    repository: str | None = None,
    event_stream: dict[str, Any] | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    """Public validate-and-bind result with private evidence removed."""

    result = _validate_and_create_execution_binding_verification(
        project_root,
        authority_id,
        expected_admission_sha256=expected_admission_sha256,
        expected_head=expected_head,
        expected_provider=expected_provider,
        expected_repository=expected_repository,
        expected_git_branch=expected_git_branch,
        run_id=run_id,
        preview_id=preview_id,
        executor_session_mode=executor_session_mode,
        work_target=work_target,
        repository=repository,
        event_stream=event_stream,
        now=now,
    )
    private_fields = {
        "_internal_verification",
        "executor_authority_id",
        "admission_sha256",
        "event_stream",
        "execution_binding_path",
        "project_root",
    }

    def project(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: project(item)
                for key, item in value.items()
                if key not in private_fields
            }
        if isinstance(value, list):
            return [project(item) for item in value]
        return value

    projected = project(result)
    return projected if isinstance(projected, dict) else {"ok": False}


def _validate_and_create_execution_binding_verification(
    project_root: str,
    authority_id: str,
    *,
    expected_admission_sha256: str,
    expected_head: str,
    expected_provider: str = "codex",
    expected_repository: str | None = None,
    expected_git_branch: str | None = None,
    run_id: str,
    preview_id: str,
    executor_session_mode: str = "start_new",
    work_target: dict[str, Any] | None = None,
    repository: str | None = None,
    event_stream: dict[str, Any] | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    """Atomic authoritative validate-and-bind (P1-1 repair).

    This is the ONLY provider-before security proof.  It performs the
    authoritative admission read and the create-exclusive execution-binding
    write inside ONE fd transaction on the SAME authority directory object:

        open authority_fd
        -> read admission.json through authority_fd (raw bytes)
        -> hash exact bytes + schema/HEAD/repository/provider validate
        -> classify any existing execution-binding.json through authority_fd
        -> create execution-binding.json through the SAME authority_fd
        -> fsync(file) + fsync(authority_fd)
        -> close

    The authority path and every ancestor are revalidated around each read and
    again before creation.  A rename, replacement, or symlink swap therefore
    blocks instead of consuming a detached directory object.  The admission
    record is never modified.
    """
    if _validate_authority_id(authority_id) is False:
        return {
            "ok": False,
            "error_code": FRESH_EXECUTOR_AUTHORITY_INVALID_CONTEXT,
            "reason": "malformed authority id",
        }
    if (
        not isinstance(run_id, str)
        or not run_id.strip()
        or not isinstance(preview_id, str)
        or not preview_id.strip()
    ):
        return {
            "ok": False,
            "error_code": FRESH_EXECUTOR_AUTHORITY_INVALID_CONTEXT,
            "reason": "run_id and preview_id are required",
        }
    if expected_provider != "codex":
        return {
            "ok": False,
            "error_code": FRESH_EXECUTOR_AUTHORITY_PROVIDER_MISMATCH,
            "reason": "R0 fresh binding is codex-only",
        }
    if executor_session_mode != "start_new":
        return {
            "ok": False,
            "error_code": FRESH_EXECUTOR_AUTHORITY_SESSION_MODE_MISMATCH,
            "reason": "fresh authority binding requires executor_session_mode=start_new",
        }
    event_stream_error = _validate_event_stream_contract(event_stream)
    if event_stream_error is not None:
        return {
            "ok": False,
            "error_code": FRESH_EXECUTOR_AUTHORITY_INVALID_CONTEXT,
            "reason": event_stream_error,
        }
    if not isinstance(expected_head, str) or _FULL_HEAD_RE.fullmatch(expected_head) is None:
        return {
            "ok": False,
            "error_code": FRESH_EXECUTOR_AUTHORITY_INVALID_CONTEXT,
            "reason": "malformed expected_head",
        }
    if not isinstance(expected_admission_sha256, str) or re.fullmatch(
        r"[0-9a-f]{64}", expected_admission_sha256.lower()
    ) is None:
        return {
            "ok": False,
            "error_code": FRESH_EXECUTOR_AUTHORITY_INVALID_CONTEXT,
            "reason": "malformed expected admission hash",
        }

    work_item_id = None
    task_version = None
    attempt_id = None
    artifact_refs: list[str] = []
    if isinstance(work_target, dict):
        work_item_id = work_target.get("work_item_id")
        task_version = work_target.get("task_version")
        attempt_id = work_target.get("attempt_id")
        artifact_refs = list(work_target.get("artifact_refs") or [])
        if not all(
            field in work_target
            for field in ("work_item_id", "task_version", "attempt_id", "artifact_refs")
        ):
            return {
                "ok": False,
                "error_code": FRESH_EXECUTOR_AUTHORITY_WORK_TARGET_REQUIRED,
                "reason": "complete governed work target required",
            }
        from runner.work_item_governance.references import (
            optional_work_item_reference_rejections,
        )

        rejections = optional_work_item_reference_rejections(work_target)
        if rejections:
            return {
                "ok": False,
                "error_code": FRESH_EXECUTOR_AUTHORITY_WORK_TARGET_REQUIRED,
                "reason": f"invalid governed work target: {rejections}",
            }
    else:
        return {
            "ok": False,
            "error_code": FRESH_EXECUTOR_AUTHORITY_WORK_TARGET_REQUIRED,
            "reason": "governed work target required for fresh authority binding",
        }

    root = os.path.abspath(os.path.expanduser(project_root))
    state = _open_authority_state_read_fds(root)
    if not state.get("ok"):
        return {
            "ok": False,
            "error_code": state.get("error_code"),
            "reason": state.get("reason"),
        }
    authority_fd = -1
    binding_fd = -1
    try:
        authority_fd, authority_error = _open_existing_authority_dir(
            state["sessions_fd"], authority_id
        )
        if authority_fd < 0:
            return {
                "ok": False,
                "error_code": authority_error,
                "executor_authority_id": authority_id,
                "reason": "authority directory unavailable",
            }

        # --- authoritative admission read on the SAME authority_fd ---
        admission = _read_admission_verification_from_fd(
            state,
            authority_fd,
            authority_id=authority_id,
            expected_admission_sha256=expected_admission_sha256,
            expected_head=expected_head,
            expected_provider=expected_provider,
            expected_repository=expected_repository,
            expected_git_branch=expected_git_branch,
        )
        if not admission.get("ok"):
            return {**admission, "executor_authority_id": authority_id}
        admission_sha256 = admission["admission_sha256"]

        # --- existing binding classification on the SAME authority_fd ---
        existing = _read_verified_authority_file(
            authority_fd,
            EXECUTION_BINDING_FILENAME,
            state=state,
            authority_id=authority_id,
            authority_fd=authority_fd,
        )
        if existing.get("error_code") != "NOT_FOUND":
            parsed: Any = None
            if existing.get("ok"):
                try:
                    parsed = json.loads(existing["raw"].decode("utf-8"))
                except (UnicodeDecodeError, ValueError):
                    parsed = None
            contract_error = _validate_execution_binding_contract(
                parsed,
                authority_id=authority_id,
                canonical_project_root=root,
            )
            if (
                existing.get("ok")
                and contract_error is None
                and parsed.get("run_id") == run_id
                and parsed.get("preview_id") == preview_id
            ):
                return {
                    "ok": False,
                    "error_code": FRESH_EXECUTOR_AUTHORITY_ALREADY_CONSUMED,
                    "executor_authority_id": authority_id,
                    "reason": "authority already consumed by this run",
                    "execution_binding": parsed,
                }
            return {
                "ok": False,
                "error_code": FRESH_EXECUTOR_AUTHORITY_BINDING_CONFLICT,
                "executor_authority_id": authority_id,
                "reason": "existing execution binding is unsafe or conflicts",
                "execution_binding": parsed if contract_error is None else None,
            }

        if not _verify_authority_ancestor_chain(
            state, authority_id=authority_id, authority_fd=authority_fd
        ):
            return {
                "ok": False,
                "error_code": FRESH_EXECUTOR_AUTHORITY_BINDING_CONFLICT,
                "executor_authority_id": authority_id,
                "reason": "authority ancestor chain changed before binding create",
            }

        # --- create execution-binding.json on the SAME authority_fd ---
        binding = _build_execution_binding_payload(
            authority_id=authority_id,
            admission_sha256=admission_sha256,
            project_root=root,
            repository=repository,
            run_id=run_id,
            preview_id=preview_id,
            admitted_head=expected_head,
            provider=expected_provider,
            executor_session_mode=executor_session_mode,
            work_item_id=work_item_id,
            task_version=task_version,
            attempt_id=attempt_id,
            artifact_refs=artifact_refs,
            event_stream=dict(event_stream or {}),
            now=now,
        )
        payload = (
            json.dumps(binding, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        )
        try:
            try:
                binding_fd = os.open(
                    EXECUTION_BINDING_FILENAME,
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | os.O_NOFOLLOW
                    | os.O_CLOEXEC,
                    0o600,
                    dir_fd=authority_fd,
                )
            except FileExistsError:
                return {
                    "ok": False,
                    "error_code": FRESH_EXECUTOR_AUTHORITY_ALREADY_CONSUMED,
                    "executor_authority_id": authority_id,
                    "reason": "concurrent binding create lost the race",
                }
            except OSError as exc:
                if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                    return {
                        "ok": False,
                        "error_code": FRESH_EXECUTOR_ADMISSION_STATE_ROOT_ESCAPE,
                        "executor_authority_id": authority_id,
                        "reason": "binding open refused by anchored create",
                    }
                return {
                    "ok": False,
                    "error_code": FRESH_EXECUTOR_AUTHORITY_BINDING_WRITE_FAILED,
                    "executor_authority_id": authority_id,
                    "reason": f"{type(exc).__name__}:{exc.errno}",
                }
            try:
                try:
                    _write_all_fd(binding_fd, payload.encode("utf-8"))
                    os.fsync(binding_fd)
                except OSError:
                    return {
                        "ok": False,
                        "error_code": FRESH_EXECUTOR_AUTHORITY_BINDING_WRITE_FAILED,
                        "executor_authority_id": authority_id,
                        "reason": "failed to persist the execution binding",
                    }
            finally:
                os.close(binding_fd)
                binding_fd = -1
        finally:
            if binding_fd >= 0:
                try:
                    os.close(binding_fd)
                except OSError:
                    pass
        try:
            os.fsync(authority_fd)
        except OSError:
            return {
                "ok": False,
                "error_code": FRESH_EXECUTOR_AUTHORITY_BINDING_WRITE_FAILED,
                "executor_authority_id": authority_id,
                "reason": "failed to persist the execution binding directory entry",
            }

        binding_evidence = _read_verified_authority_file(
            authority_fd,
            EXECUTION_BINDING_FILENAME,
            state=state,
            authority_id=authority_id,
            authority_fd=authority_fd,
        )
        if not binding_evidence.get("ok"):
            return {
                "ok": False,
                "error_code": FRESH_EXECUTOR_AUTHORITY_BINDING_WRITE_FAILED,
                "executor_authority_id": authority_id,
                "reason": "persisted execution binding could not be verified",
            }
        try:
            verified_binding = json.loads(binding_evidence["raw"].decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            verified_binding = None
        if (
            verified_binding != binding
            or _validate_execution_binding_contract(
                verified_binding,
                authority_id=authority_id,
                canonical_project_root=root,
                expected_run_id=run_id,
            )
            is not None
        ):
            return {
                "ok": False,
                "error_code": FRESH_EXECUTOR_AUTHORITY_BINDING_WRITE_FAILED,
                "executor_authority_id": authority_id,
                "reason": "persisted execution binding contract mismatch",
            }

        return {
            "ok": True,
            "executor_authority_id": authority_id,
            "admission_sha256": admission_sha256,
            "execution_binding_path": os.path.join(
                state["authority_root_path"], authority_id, EXECUTION_BINDING_FILENAME
            ),
            "binding": binding,
            "_internal_verification": {
                "admission": admission["durable_contract"],
                "binding": {
                    "identity": binding_evidence["identity"],
                    "metadata": binding_evidence["metadata"],
                    "raw_sha256": binding_evidence["raw_sha256"],
                    "content_sha256": _content_sha256(verified_binding),
                },
            },
        }
    finally:
        if authority_fd >= 0:
            try:
                os.close(authority_fd)
            except OSError:
                pass
        _close_fds(
            [
                state["project_fd"],
                state["colameta_fd"],
                state["runtime_fd"],
                state["sessions_fd"],
            ]
        )
