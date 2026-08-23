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
import json
import os
import re
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

FRESH_EXECUTOR_AUTHORITY_SCHEMA_VERSION = "fresh_executor_authority_admission.v1"
FRESH_EXECUTOR_AUTHORITY_SOURCE = "fresh_executor_admission"
FRESH_EXECUTOR_AUTHORITY_STATE = "admitted"
FRESH_EXECUTOR_OPERATION_STATE = "idle"
ADMISSION_FILENAME = "admission.json"
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

# Authority ids are ColaMeta-generated UUID4 hex (32 lowercase hex chars).
_AUTHORITY_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_FULL_HEAD_RE = re.compile(r"^[0-9a-f]{40,64}$")

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
    root = os.path.realpath(os.path.abspath(os.path.expanduser(project_root)))
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
    root = os.path.realpath(os.path.abspath(os.path.expanduser(project_root)))
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
    """Read an existing admission record, or return None (or error)."""

    if _validate_authority_id(authority_id) is False:
        return None
    record_path = executor_authority_path(project_root, authority_id)
    try:
        with open(record_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload if isinstance(payload, dict) else None
    except (OSError, ValueError):
        return None


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


def _best_effort_remove_empty_dir(path: str) -> None:
    try:
        os.rmdir(path)
    except OSError:
        pass
