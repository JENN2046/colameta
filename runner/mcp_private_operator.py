from __future__ import annotations

import contextlib
import contextvars
import copy
try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None
import hashlib
import json
import os
import re
import secrets
import stat
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from runner._internal_utils import write_json_atomic
from runner.operator_artifact_binding import operator_artifact_binding_scope
from runner.runner_paths import user_config_dir


_HAS_SECURE_DIRFD = (
    os.open in os.supports_dir_fd
    and os.mkdir in os.supports_dir_fd
    and os.rename in os.supports_dir_fd
    and os.unlink in os.supports_dir_fd
    and os.stat in os.supports_dir_fd
    and os.chmod in os.supports_dir_fd
)
OPERATOR_PROFILE_DISABLED = "disabled"
OPERATOR_PROFILE_JENN = "jenn_private_operator"
DEFAULT_OPERATOR_TTL_SECONDS = 300
DEFAULT_OPERATOR_MAX_STEPS = 8
OPERATOR_TTL_RANGE = (1, 900)
OPERATOR_STEP_RANGE = (1, 16)
OPERATOR_CONFIG_VERSION = "jenn_private_operator.v1"
OPERATOR_MANIFEST_VERSION = "jenn_private_operator_manifest.v1"
OPERATOR_QUARANTINE_ATTENTION_THRESHOLD = 1
OPERATOR_QUARANTINE_ALERT_CODE = "OPERATOR_FD_QUARANTINE_ATTENTION"
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,96}$")
_STEP_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_ERROR_CODE_RE = re.compile(r"^[A-Z0-9_]{1,80}$")
_TICKET_STATES = frozenset({"pending", "claimed", "consumed", "failed", "indeterminate"})
_STEP_STATES = frozenset({
    "pending", "running", "succeeded", "started_async", "failed", "not_started", "indeterminate",
})


_CURRENT_OPERATOR_AUTH: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "colameta_current_operator_auth",
    default=None,
)
_ACTIVE_BATCHES: set[str] = set()
_ACTIVE_CLAIM_FDS: dict[str, int] = {}
_ACTIVE_ROOT_FDS: dict[str, int] = {}
_QUARANTINED_CLOSE_FDS: set[int] = set()
_ACTIVE_BATCHES_LOCK = threading.Lock()


@contextlib.contextmanager
def operator_authenticated_request_scope(auth_context: object) -> Iterator[None]:
    value = auth_context if isinstance(auth_context, dict) else None
    token = _CURRENT_OPERATOR_AUTH.set(value)
    try:
        yield
    finally:
        _CURRENT_OPERATOR_AUTH.reset(token)


def current_operator_auth_context() -> dict[str, Any] | None:
    return _CURRENT_OPERATOR_AUTH.get()


def _batch_is_active(batch_id: str) -> bool:
    with _ACTIVE_BATCHES_LOCK:
        return batch_id in _ACTIVE_BATCHES


def _release_batch(batch_id: str) -> tuple[int | None, int | None]:
    claim_fd: int | None = None
    root_fd: int | None = None
    with _ACTIVE_BATCHES_LOCK:
        _ACTIVE_BATCHES.discard(batch_id)
        claim_fd = _ACTIVE_CLAIM_FDS.pop(batch_id, None)
        root_fd = _ACTIVE_ROOT_FDS.pop(batch_id, None)
    if claim_fd is not None:
        with contextlib.suppress(BaseException):
            if fcntl is not None:
                fcntl.flock(claim_fd, fcntl.LOCK_UN)
        _close_owned_fd(claim_fd)
    if root_fd is not None:
        _close_owned_fd(root_fd)
    return claim_fd, root_fd


def _active_root_fd(batch_id: str) -> int | None:
    with _ACTIVE_BATCHES_LOCK:
        return _ACTIVE_ROOT_FDS.get(batch_id)


def _private_operator_runtime_counters() -> dict[str, int]:
    with _ACTIVE_BATCHES_LOCK:
        return {
            "quarantined_close_fd_count": len(_QUARANTINED_CLOSE_FDS),
        }


def private_operator_local_runtime_status() -> dict[str, Any]:
    count = _private_operator_runtime_counters()["quarantined_close_fd_count"]
    attention = count >= OPERATOR_QUARANTINE_ATTENTION_THRESHOLD
    return {
        "quarantined_close_fd_count": count,
        "quarantine_attention_threshold": OPERATOR_QUARANTINE_ATTENTION_THRESHOLD,
        "quarantine_status": "attention" if attention else "clear",
        "local_alert_code": OPERATOR_QUARANTINE_ALERT_CODE if attention else None,
    }


def _close_owned_fd(fd: int) -> bool:
    try:
        os.close(fd)
    except BaseException:
        with _ACTIVE_BATCHES_LOCK:
            _QUARANTINED_CLOSE_FDS.add(fd)
        return False
    with _ACTIVE_BATCHES_LOCK:
        _QUARANTINED_CLOSE_FDS.discard(fd)
    return True


def _existing_path_has_symlink(path: str) -> bool:
    candidate = Path(path).absolute()
    for item in reversed((candidate, *candidate.parents)):
        if not os.path.lexists(item):
            continue
        try:
            if stat.S_ISLNK(os.lstat(item).st_mode):
                return True
        except OSError:
            return True
    return False


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_iso(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _manifest_digest(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class OperatorPrincipalDecision:
    allowed: bool
    error_code: str
    subject_fingerprint: str | None = None
    client_fingerprint: str | None = None


class OperatorSettingsStore:
    """Private Jenn principal configuration; raw identifiers are never stored."""

    def __init__(self, config_dir: str | None = None):
        self.config_dir = os.path.abspath(os.path.expanduser(config_dir or user_config_dir()))
        self.path = os.path.join(self.config_dir, "operator.json")

    def defaults(self) -> dict[str, Any]:
        return {
            "schema_version": OPERATOR_CONFIG_VERSION,
            "oauth_operator_profile": OPERATOR_PROFILE_DISABLED,
            "oauth_operator_permit_ttl_seconds": DEFAULT_OPERATOR_TTL_SECONDS,
            "oauth_operator_batch_max_steps": DEFAULT_OPERATOR_MAX_STEPS,
        }

    def load(self) -> dict[str, Any]:
        if os.path.lexists(self.config_dir):
            safety = self._validate_private_dir(self.config_dir)
            if safety is not None:
                return safety
        if not os.path.lexists(self.path):
            return {"ok": True, "settings": self.defaults(), "exists": False}
        safety = self._validate_private_file(self.path)
        if safety is not None:
            return safety
        try:
            data = json.loads(Path(self.path).read_text(encoding="utf-8"))
        except Exception:
            return self._error("OPERATOR_CONFIG_INVALID")
        validated = self._validate(data)
        if not validated.get("ok"):
            return validated
        return {"ok": True, "settings": validated["settings"], "exists": True}

    def enable(
        self,
        subject: str,
        client: str,
        *,
        ttl_seconds: int = DEFAULT_OPERATOR_TTL_SECONDS,
        max_steps: int = DEFAULT_OPERATOR_MAX_STEPS,
    ) -> dict[str, Any]:
        subject_value = subject.strip() if isinstance(subject, str) else ""
        client_value = client.strip() if isinstance(client, str) else ""
        if not subject_value or not client_value:
            return self._error("OPERATOR_PRINCIPAL_INPUT_INVALID")
        candidate = {
            "schema_version": OPERATOR_CONFIG_VERSION,
            "oauth_operator_profile": OPERATOR_PROFILE_JENN,
            "oauth_operator_permit_ttl_seconds": ttl_seconds,
            "oauth_operator_batch_max_steps": max_steps,
            "subject_fingerprint": _fingerprint(subject_value),
            "client_fingerprint": _fingerprint(client_value),
        }
        validated = self._validate(candidate)
        if not validated.get("ok"):
            return validated
        try:
            self._ensure_private_dir(self.config_dir)
            self._reject_symlink(self.path)
            write_json_atomic(self.path, validated["settings"])
            self._chmod(self.path, 0o600)
        except Exception:
            return self._error("OPERATOR_CONFIG_WRITE_FAILED")
        return {"ok": True, **self.public_status(validated["settings"])}

    def disable(self) -> dict[str, Any]:
        settings = self.defaults()
        try:
            self._ensure_private_dir(self.config_dir)
            self._reject_symlink(self.path)
            write_json_atomic(self.path, settings)
            self._chmod(self.path, 0o600)
        except Exception:
            return self._error("OPERATOR_CONFIG_WRITE_FAILED")
        return {"ok": True, **self.public_status(settings)}

    def status(self) -> dict[str, Any]:
        loaded = self.load()
        if not loaded.get("ok"):
            return loaded
        return {"ok": True, **self.public_status(loaded["settings"])}

    def public_status(self, settings: dict[str, Any]) -> dict[str, Any]:
        profile = settings.get("oauth_operator_profile", OPERATOR_PROFILE_DISABLED)
        return {
            "enabled": profile == OPERATOR_PROFILE_JENN,
            "profile": profile,
            "permit_ttl_seconds": settings.get(
                "oauth_operator_permit_ttl_seconds", DEFAULT_OPERATOR_TTL_SECONDS
            ),
            "batch_max_steps": settings.get(
                "oauth_operator_batch_max_steps", DEFAULT_OPERATOR_MAX_STEPS
            ),
        }

    def _validate(self, data: object) -> dict[str, Any]:
        if not isinstance(data, dict) or data.get("schema_version") != OPERATOR_CONFIG_VERSION:
            return self._error("OPERATOR_CONFIG_INVALID")
        profile = data.get("oauth_operator_profile", OPERATOR_PROFILE_DISABLED)
        if profile not in {OPERATOR_PROFILE_DISABLED, OPERATOR_PROFILE_JENN}:
            return self._error("OPERATOR_CONFIG_INVALID")
        ttl = data.get("oauth_operator_permit_ttl_seconds", DEFAULT_OPERATOR_TTL_SECONDS)
        max_steps = data.get("oauth_operator_batch_max_steps", DEFAULT_OPERATOR_MAX_STEPS)
        if not isinstance(ttl, int) or isinstance(ttl, bool) or not OPERATOR_TTL_RANGE[0] <= ttl <= OPERATOR_TTL_RANGE[1]:
            return self._error("OPERATOR_CONFIG_INVALID")
        if not isinstance(max_steps, int) or isinstance(max_steps, bool) or not OPERATOR_STEP_RANGE[0] <= max_steps <= OPERATOR_STEP_RANGE[1]:
            return self._error("OPERATOR_CONFIG_INVALID")
        normalized = {
            "schema_version": OPERATOR_CONFIG_VERSION,
            "oauth_operator_profile": profile,
            "oauth_operator_permit_ttl_seconds": ttl,
            "oauth_operator_batch_max_steps": max_steps,
        }
        if profile == OPERATOR_PROFILE_JENN:
            for key in ("subject_fingerprint", "client_fingerprint"):
                value = data.get(key)
                if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
                    return self._error("OPERATOR_CONFIG_INVALID")
                normalized[key] = value
        return {"ok": True, "settings": normalized}

    def _validate_private_file(self, path: str) -> dict[str, Any] | None:
        try:
            info = os.lstat(path)
        except OSError:
            return self._error("OPERATOR_CONFIG_UNSAFE")
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            return self._error("OPERATOR_CONFIG_UNSAFE")
        if os.name == "posix":
            if stat.S_IMODE(info.st_mode) != 0o600 or info.st_uid != os.getuid():
                return self._error("OPERATOR_CONFIG_UNSAFE")
        return None

    def _ensure_private_dir(self, path: str) -> None:
        if _existing_path_has_symlink(path):
            raise OSError("unsafe directory path")
        if os.path.lexists(path):
            if self._validate_private_dir(path) is not None:
                raise OSError("unsafe directory")
            return
        os.makedirs(path, mode=0o700, exist_ok=False)
        self._chmod(path, 0o700)
        if self._validate_private_dir(path) is not None:
            raise OSError("unsafe directory")

    def _validate_private_dir(self, path: str) -> dict[str, Any] | None:
        if _existing_path_has_symlink(path):
            return self._error("OPERATOR_CONFIG_UNSAFE")
        try:
            info = os.lstat(path)
        except OSError:
            return self._error("OPERATOR_CONFIG_UNSAFE")
        if not stat.S_ISDIR(info.st_mode):
            return self._error("OPERATOR_CONFIG_UNSAFE")
        if os.name == "posix":
            if stat.S_IMODE(info.st_mode) != 0o700 or info.st_uid != os.getuid():
                return self._error("OPERATOR_CONFIG_UNSAFE")
        return None

    def _reject_symlink(self, path: str) -> None:
        if os.path.lexists(path) and os.path.islink(path):
            raise OSError("unsafe path")

    def _chmod(self, path: str, mode: int) -> None:
        if os.name == "posix":
            os.chmod(path, mode)

    def _error(self, code: str) -> dict[str, Any]:
        return {"ok": False, "error_code": code, "message": "Operator configuration is unavailable."}


def evaluate_operator_principal(
    auth_context: object,
    settings: dict[str, Any],
) -> OperatorPrincipalDecision:
    if settings.get("oauth_operator_profile") != OPERATOR_PROFILE_JENN:
        return OperatorPrincipalDecision(False, "OPERATOR_PROFILE_DISABLED")
    if not isinstance(auth_context, dict) or auth_context.get("mode") != "external-oauth":
        return OperatorPrincipalDecision(False, "OPERATOR_PRINCIPAL_DENIED")
    token = auth_context.get("token")
    provider = auth_context.get("oauth_provider")
    if not isinstance(token, dict) or provider is None:
        return OperatorPrincipalDecision(False, "OPERATOR_PRINCIPAL_DENIED")
    issuer = getattr(provider, "issuer", None)
    if not isinstance(issuer, str) or token.get("iss") != issuer:
        return OperatorPrincipalDecision(False, "OPERATOR_PRINCIPAL_DENIED")
    resource = getattr(provider, "resource", None)
    audience = getattr(provider, "audience", None) or resource
    if not isinstance(resource, str) or not isinstance(audience, str):
        return OperatorPrincipalDecision(False, "OPERATOR_PRINCIPAL_DENIED")
    if not (_claim_contains(token.get("aud"), audience) or _claim_contains(token.get("resource"), resource)):
        return OperatorPrincipalDecision(False, "OPERATOR_PRINCIPAL_DENIED")
    subject = token.get("sub")
    if not isinstance(subject, str) or not subject:
        return OperatorPrincipalDecision(False, "OPERATOR_PRINCIPAL_DENIED")
    azp = token.get("azp")
    client_id = token.get("client_id")
    if isinstance(azp, str) and azp and isinstance(client_id, str) and client_id and azp != client_id:
        return OperatorPrincipalDecision(False, "OPERATOR_CLIENT_CLAIM_AMBIGUOUS")
    client = azp if isinstance(azp, str) and azp else client_id
    if not isinstance(client, str) or not client:
        return OperatorPrincipalDecision(False, "OPERATOR_CLIENT_CLAIM_MISSING")
    subject_fp = _fingerprint(subject)
    client_fp = _fingerprint(client)
    if subject_fp != settings.get("subject_fingerprint") or client_fp != settings.get("client_fingerprint"):
        return OperatorPrincipalDecision(False, "OPERATOR_PRINCIPAL_DENIED")
    return OperatorPrincipalDecision(True, "", subject_fp, client_fp)


_ALLOWED_OPERATIONS: dict[tuple[str, str, str], tuple[str, ...]] = {
    ("run_mcp_workflow", "plan_update", "apply"): ("mcp:plan",),
    ("run_mcp_workflow", "small_project_patch", "apply"): ("mcp:commit",),
    ("run_mcp_workflow", "docs_update", "apply"): ("mcp:commit",),
    ("run_mcp_workflow", "git_commit", "commit"): ("mcp:commit",),
    ("run_mcp_workflow", "agent_dispatch", "apply"): ("mcp:commit",),
    ("run_mcp_workflow", "prompt_to_plan", "apply"): ("mcp:commit",),
    ("run_mcp_workflow", "prompt_to_plan", "plan_apply"): ("mcp:plan",),
    ("run_mcp_workflow", "prompt_to_plan", "run"): ("mcp:commit",),
    ("manage_validation_run", "run", "run"): ("mcp:commit",),
    ("manage_git", "commit_apply", "commit_apply"): ("mcp:commit",),
}
_ASYNC_OPERATIONS = {
    ("run_mcp_workflow", "prompt_to_plan", "run"),
    ("manage_validation_run", "run", "run"),
}

_OPERATION_PREVIEW_FIELDS: dict[tuple[str, str, str], tuple[str, ...]] = {
    ("run_mcp_workflow", "plan_update", "apply"): ("patch_id",),
    ("run_mcp_workflow", "small_project_patch", "apply"): ("preview_id",),
    ("run_mcp_workflow", "docs_update", "apply"): ("preview_id",),
    ("run_mcp_workflow", "git_commit", "commit"): ("preview_id",),
    ("run_mcp_workflow", "agent_dispatch", "apply"): ("preview_id", "patch_id"),
    ("run_mcp_workflow", "prompt_to_plan", "apply"): ("preview_id",),
    ("run_mcp_workflow", "prompt_to_plan", "plan_apply"): ("patch_id",),
    ("run_mcp_workflow", "prompt_to_plan", "run"): ("preview_id",),
    ("manage_validation_run", "run", "run"): ("preview_id",),
    ("manage_git", "commit_apply", "commit_apply"): ("preview_id",),
}


def _allowed_param_keys(tool: str) -> set[str]:
    if tool == "run_mcp_workflow":
        return {"workflow", "phase", "preview_id", "patch_id", "provider", "message", "reason"}
    return {"action", "preview_id", "message"}


def normalize_operator_operations(
    operations: object,
    *,
    max_steps: int,
    preview_validator: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    if not isinstance(operations, list) or not operations:
        return _error("OPERATOR_BATCH_EMPTY")
    if len(operations) > max_steps:
        return _error("OPERATOR_BATCH_TOO_LARGE")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    required_scopes: set[str] = set()
    for index, raw in enumerate(operations):
        if not isinstance(raw, dict) or set(raw) != {"step_id", "tool", "params"}:
            return _error("OPERATOR_OPERATION_INVALID")
        step_id = raw.get("step_id")
        tool = raw.get("tool")
        params = raw.get("params")
        if not isinstance(step_id, str) or not _STEP_ID_RE.fullmatch(step_id):
            return _error("OPERATOR_OPERATION_INVALID")
        if step_id in seen:
            return _error("OPERATOR_DUPLICATE_STEP_ID")
        seen.add(step_id)
        if not isinstance(tool, str) or not isinstance(params, dict):
            return _error("OPERATOR_OPERATION_INVALID")
        if "project_name" in params or "project_root" in params:
            return _error("OPERATOR_PROJECT_OVERRIDE_DENIED")
        if _contains_private_key(params):
            return _error("OPERATOR_PRIVATE_INPUT_DENIED")
        if tool == "run_mcp_workflow":
            operation = str(params.get("workflow") or "").strip().lower()
            phase = str(params.get("phase") or "").strip().lower()
        elif tool == "manage_validation_run":
            operation = str(params.get("action") or "").strip().lower()
            phase = operation
        elif tool == "manage_git":
            operation = str(params.get("action") or "").strip().lower()
            phase = operation
        else:
            return _error("OPERATOR_OPERATION_DENIED")
        key = (tool, operation, phase)
        scopes = _ALLOWED_OPERATIONS.get(key)
        if scopes is None:
            return _error("OPERATOR_OPERATION_DENIED")
        allowed_param_keys = _allowed_param_keys(tool)
        if set(params) - allowed_param_keys:
            return _error("OPERATOR_OPERATION_ARGUMENTS_DENIED")
        if any(not isinstance(value, str) for value in params.values()):
            return _error("OPERATOR_OPERATION_ARGUMENTS_DENIED")
        if key in _ASYNC_OPERATIONS and index != len(operations) - 1:
            return _error("OPERATOR_ASYNC_STEP_NOT_LAST")
        allowed_preview_fields = _OPERATION_PREVIEW_FIELDS[key]
        preview_fields = [field for field in allowed_preview_fields if field in params]
        if set(params).intersection({"preview_id", "patch_id"}) - set(allowed_preview_fields):
            return _error("OPERATOR_OPERATION_ARGUMENTS_DENIED")
        if len(preview_fields) != 1:
            return _error("OPERATOR_OPERATION_ARGUMENTS_DENIED")
        preview_id = params.get(preview_fields[0])
        if not isinstance(preview_id, str) or not _ID_RE.fullmatch(preview_id.strip()):
            return _error("OPERATOR_PREVIEW_NOT_FOUND")
        clean_params = dict(params)
        clean_params.pop("project_name", None)
        validation = preview_validator({
            "tool": tool,
            "operation": operation,
            "phase": phase,
            "preview_id": preview_id.strip(),
            "params": clean_params,
        })
        if not isinstance(validation, dict) or not validation.get("ok"):
            code = validation.get("error_code") if isinstance(validation, dict) else None
            return _error(code if isinstance(code, str) else "OPERATOR_PREVIEW_NOT_FOUND")
        preview_digest = validation.get("preview_digest")
        if not isinstance(preview_digest, str) or not _DIGEST_RE.fullmatch(preview_digest):
            return _error("OPERATOR_PREVIEW_DIGEST_INVALID")
        required_scopes.update(scopes)
        normalized.append({
            "step_id": step_id,
            "tool": tool,
            "operation": operation,
            "phase": phase,
            "params": clean_params,
            "preview_id": preview_id.strip(),
            "preview_digest": preview_digest,
            "required_scopes": list(scopes),
            "async": key in _ASYNC_OPERATIONS,
        })
    return {"ok": True, "operations": normalized, "required_scopes": sorted(required_scopes)}


def _ticket_manifest(ticket: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": ticket.get("schema_version"),
        "project_name": ticket.get("project_name"),
        "operations": ticket.get("operations"),
        "required_scopes": ticket.get("required_scopes"),
        "expires_at": ticket.get("expires_at"),
    }


def _ticket_state_is_consistent(ticket: dict[str, Any]) -> bool:
    state = ticket.get("state")
    steps = ticket.get("steps")
    operations = ticket.get("operations")
    if not isinstance(steps, list) or not isinstance(operations, list):
        return False
    statuses = [step.get("status") for step in steps if isinstance(step, dict)]
    if len(statuses) != len(steps):
        return False
    claimed_at = _parse_iso(ticket.get("claimed_at"))
    completed_at = _parse_iso(ticket.get("completed_at"))
    if state == "pending":
        return claimed_at is None and completed_at is None and all(
            status == "pending" for status in statuses
        )
    if state == "claimed":
        if claimed_at is None or completed_at is not None:
            return False
        phase = "succeeded"
        running_seen = False
        for index, status in enumerate(statuses):
            if status in {"succeeded", "started_async"} and phase == "succeeded":
                if status == "succeeded" and operations[index].get("async"):
                    return False
                if status == "started_async" and not operations[index].get("async"):
                    return False
                continue
            if status == "running" and phase == "succeeded" and not running_seen:
                running_seen = True
                phase = "pending"
                continue
            if status == "pending" and phase in {"succeeded", "pending"}:
                phase = "pending"
                continue
            return False
        return True
    if claimed_at is None or completed_at is None:
        return False
    if state == "consumed":
        return all(
            (status == "started_async")
            if operations[index].get("async") is True
            else (status == "succeeded")
            for index, status in enumerate(statuses)
        )
    if state == "failed":
        failed_indexes = [index for index, status in enumerate(statuses) if status == "failed"]
        if len(failed_indexes) != 1:
            return False
        failed_index = failed_indexes[0]
        return (
            all(
                status == "succeeded" and operations[index].get("async") is not True
                for index, status in enumerate(statuses[:failed_index])
            )
            and all(status == "not_started" for status in statuses[failed_index + 1:])
            and isinstance(steps[failed_index].get("error_code"), str)
        )
    if state == "indeterminate":
        if not statuses:
            return False
        if all(
            status == "succeeded" and operations[index].get("async") is not True
            for index, status in enumerate(statuses)
        ):
            return True
        if (
            statuses[-1] == "started_async"
            and operations[-1].get("async") is True
            and all(status == "succeeded" for status in statuses[:-1])
        ):
            return True
        uncertain_indexes = [
            index for index, status in enumerate(statuses) if status == "indeterminate"
        ]
        if len(uncertain_indexes) != 1:
            return False
        uncertain_index = uncertain_indexes[0]
        return (
            all(
                status == "succeeded" and operations[index].get("async") is not True
                for index, status in enumerate(statuses[:uncertain_index])
            )
            and all(status == "not_started" for status in statuses[uncertain_index + 1:])
        )
    return False


def _make_ticket_indeterminate(ticket: dict[str, Any]) -> dict[str, Any]:
    ticket["state"] = "indeterminate"
    ticket["completed_at"] = _iso(_utc_now())
    if _parse_iso(ticket.get("claimed_at")) is None:
        ticket["claimed_at"] = ticket["completed_at"]
    uncertain_seen = False
    for step in ticket.get("steps", []):
        if not isinstance(step, dict):
            continue
        status = step.get("status")
        if status in {"succeeded", "started_async"} and not uncertain_seen:
            continue
        step.pop("error_code", None)
        if not uncertain_seen:
            step["status"] = "indeterminate"
            uncertain_seen = True
        else:
            step["status"] = "not_started"
    return ticket


def validate_operator_ticket(ticket: object) -> dict[str, Any]:
    if not isinstance(ticket, dict):
        return _error("OPERATOR_TICKET_INVALID")
    allowed_ticket_keys = {
        "schema_version", "project_name", "operations", "required_scopes", "expires_at",
        "manifest_digest", "created_at", "subject_fingerprint", "client_fingerprint",
        "batch_preview_id", "state", "steps", "claimed_at", "completed_at",
    }
    if set(ticket) - allowed_ticket_keys:
        return _error("OPERATOR_TICKET_INVALID")
    if ticket.get("schema_version") != OPERATOR_MANIFEST_VERSION:
        return _error("OPERATOR_TICKET_INVALID")
    project_name = ticket.get("project_name")
    if (
        not isinstance(project_name, str)
        or not project_name.strip()
        or project_name != project_name.strip()
        or len(project_name) > 128
        or any(ord(char) < 32 for char in project_name)
    ):
        return _error("OPERATOR_TICKET_INVALID")
    batch_id = ticket.get("batch_preview_id")
    if not isinstance(batch_id, str) or not _ID_RE.fullmatch(batch_id):
        return _error("OPERATOR_TICKET_INVALID")
    digest = ticket.get("manifest_digest")
    if not isinstance(digest, str) or not _DIGEST_RE.fullmatch(digest):
        return _error("OPERATOR_TICKET_INVALID")
    created_at = _parse_iso(ticket.get("created_at"))
    expires_at = _parse_iso(ticket.get("expires_at"))
    if created_at is None or expires_at is None or expires_at <= created_at:
        return _error("OPERATOR_TICKET_INVALID")
    for optional_time in ("claimed_at", "completed_at"):
        if optional_time in ticket and _parse_iso(ticket.get(optional_time)) is None:
            return _error("OPERATOR_TICKET_INVALID")
    for fingerprint_key in ("subject_fingerprint", "client_fingerprint"):
        value = ticket.get(fingerprint_key)
        if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
            return _error("OPERATOR_TICKET_INVALID")
    state = ticket.get("state")
    if state not in _TICKET_STATES:
        return _error("OPERATOR_TICKET_INVALID")
    operations = ticket.get("operations")
    if not isinstance(operations, list) or not 1 <= len(operations) <= OPERATOR_STEP_RANGE[1]:
        return _error("OPERATOR_TICKET_INVALID")
    normalized_scopes: set[str] = set()
    operation_step_ids: list[str] = []
    for operation_index, item in enumerate(operations):
        if not isinstance(item, dict) or set(item) != {
            "step_id", "tool", "operation", "phase", "params", "preview_id",
            "preview_digest", "required_scopes", "async",
        }:
            return _error("OPERATOR_TICKET_INVALID")
        step_id = item.get("step_id")
        tool = item.get("tool")
        operation = item.get("operation")
        phase = item.get("phase")
        params = item.get("params")
        preview_id = item.get("preview_id")
        preview_digest = item.get("preview_digest")
        scopes = item.get("required_scopes")
        async_step = item.get("async")
        if not isinstance(step_id, str) or not _STEP_ID_RE.fullmatch(step_id) or step_id in operation_step_ids:
            return _error("OPERATOR_TICKET_INVALID")
        if not all(isinstance(value, str) for value in (tool, operation, phase)) or not isinstance(params, dict):
            return _error("OPERATOR_TICKET_INVALID")
        key = (tool, operation, phase)
        expected_scopes = _ALLOWED_OPERATIONS.get(key)
        if expected_scopes is None or scopes != list(expected_scopes):
            return _error("OPERATOR_TICKET_INVALID")
        if async_step is not (key in _ASYNC_OPERATIONS):
            return _error("OPERATOR_TICKET_INVALID")
        if async_step and operation_index != len(operations) - 1:
            return _error("OPERATOR_TICKET_INVALID")
        if set(params) - _allowed_param_keys(tool) or _contains_private_key(params):
            return _error("OPERATOR_TICKET_INVALID")
        if any(not isinstance(value, str) for value in params.values()):
            return _error("OPERATOR_TICKET_INVALID")
        if "project_name" in params or "project_root" in params:
            return _error("OPERATOR_TICKET_INVALID")
        if tool == "run_mcp_workflow":
            if params.get("workflow") != operation or params.get("phase") != phase:
                return _error("OPERATOR_TICKET_INVALID")
        elif params.get("action") != operation or phase != operation:
            return _error("OPERATOR_TICKET_INVALID")
        allowed_preview_fields = _OPERATION_PREVIEW_FIELDS[key]
        preview_fields = [field for field in allowed_preview_fields if field in params]
        if set(params).intersection({"preview_id", "patch_id"}) - set(allowed_preview_fields):
            return _error("OPERATOR_TICKET_INVALID")
        if len(preview_fields) != 1:
            return _error("OPERATOR_TICKET_INVALID")
        param_preview_id = params.get(preview_fields[0])
        if preview_id != param_preview_id or not isinstance(preview_id, str) or not _ID_RE.fullmatch(preview_id):
            return _error("OPERATOR_TICKET_INVALID")
        if not isinstance(preview_digest, str) or not _DIGEST_RE.fullmatch(preview_digest):
            return _error("OPERATOR_TICKET_INVALID")
        operation_step_ids.append(step_id)
        normalized_scopes.update(expected_scopes)
    required_scopes = ticket.get("required_scopes")
    if required_scopes != sorted(normalized_scopes):
        return _error("OPERATOR_TICKET_INVALID")
    steps = ticket.get("steps")
    if not isinstance(steps, list) or len(steps) != len(operations):
        return _error("OPERATOR_TICKET_INVALID")
    for index, step in enumerate(steps):
        if not isinstance(step, dict) or set(step) - {"step_id", "status", "error_code"}:
            return _error("OPERATOR_TICKET_INVALID")
        if step.get("step_id") != operation_step_ids[index] or step.get("status") not in _STEP_STATES:
            return _error("OPERATOR_TICKET_INVALID")
        error_code = step.get("error_code")
        if error_code is not None and (not isinstance(error_code, str) or not _ERROR_CODE_RE.fullmatch(error_code)):
            return _error("OPERATOR_TICKET_INVALID")
        if error_code is not None and step.get("status") != "failed":
            return _error("OPERATOR_TICKET_INVALID")
    if not _ticket_state_is_consistent(ticket):
        return _error("OPERATOR_TICKET_INVALID")
    claimed_at = _parse_iso(ticket.get("claimed_at"))
    completed_at = _parse_iso(ticket.get("completed_at"))
    if claimed_at is not None and claimed_at < created_at:
        return _error("OPERATOR_TICKET_INVALID")
    if completed_at is not None and (claimed_at is None or completed_at < claimed_at):
        return _error("OPERATOR_TICKET_INVALID")
    manifest = _ticket_manifest(ticket)
    computed_digest = _manifest_digest(manifest)
    if computed_digest != digest:
        return _error("OPERATOR_MANIFEST_MISMATCH")
    return {
        "ok": True,
        "ticket": ticket,
        "manifest": manifest,
        "manifest_digest": computed_digest,
        "required_scopes": tuple(required_scopes),
    }


class OperatorPermitStore:
    def __init__(self, config_dir: str | None = None):
        base = os.path.abspath(os.path.expanduser(config_dir or user_config_dir()))
        self.root = os.path.join(base, "operator-permits")

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        root_fd = self._ensure_root_fd()
        fd: int | None = None
        ticket_name: str | None = None
        committed = False
        try:
            batch_id = f"opb_{secrets.token_hex(16)}"
            body = dict(payload)
            body["batch_preview_id"] = batch_id
            body["state"] = "pending"
            body["steps"] = [
                {"step_id": item["step_id"], "status": "pending"}
                for item in body.get("operations", [])
            ]
            if not validate_operator_ticket(body).get("ok"):
                raise ValueError("invalid operator ticket")
            data = _canonical_json(body).encode("utf-8")
            ticket_name = self._ticket_name(batch_id)
            fd = self._open_name_at(
                root_fd,
                ticket_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            os.fchmod(fd, 0o600)
            self._write_all(fd, data)
            os.fsync(fd)
            os.fsync(root_fd)
            committed = True
            return body
        finally:
            self._close_fd(fd)
            if ticket_name is not None and not committed:
                with contextlib.suppress(OSError):
                    os.unlink(ticket_name, dir_fd=root_fd)
                    os.fsync(root_fd)
            self._close_fd(root_fd)

    def read(self, batch_id: str) -> dict[str, Any] | None:
        if not isinstance(batch_id, str) or not _ID_RE.fullmatch(batch_id):
            return None
        try:
            root_fd = self._open_root_dir_fd()
        except OSError:
            return None
        try:
            return self._read_ticket_from_root_fd(root_fd, batch_id)
        finally:
            self._close_fd(root_fd)

    def claim(
        self,
        batch_id: str,
        *,
        expected_ticket: dict[str, Any],
        on_claimed: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        try:
            frozen_expected_ticket = copy.deepcopy(expected_ticket)
        except Exception:
            return _error("OPERATOR_TICKET_INVALID")
        expected_validation = validate_operator_ticket(frozen_expected_ticket)
        if (
            not isinstance(batch_id, str)
            or not _ID_RE.fullmatch(batch_id)
            or not expected_validation.get("ok")
            or frozen_expected_ticket.get("batch_preview_id") != batch_id
        ):
            return _error("OPERATOR_TICKET_INVALID")
        if frozen_expected_ticket.get("state") == "indeterminate":
            return _error("OPERATOR_EXECUTION_INDETERMINATE")
        if frozen_expected_ticket.get("state") == "claimed":
            return _error("OPERATOR_TICKET_ALREADY_CLAIMED")
        if frozen_expected_ticket.get("state") != "pending":
            return _error("OPERATOR_TICKET_NOT_PENDING")
        frozen_expected_canonical = _canonical_json(frozen_expected_ticket)
        try:
            root_fd = self._open_root_dir_fd()
        except OSError:
            return _error("OPERATOR_PERMIT_UNSAFE")
        claim_fd: int | None = None
        try:
            try:
                ticket = self._read_ticket_from_root_fd(root_fd, batch_id)
                binding_error = self._claim_binding_error(ticket, frozen_expected_canonical)
                if binding_error is not None:
                    return _error(binding_error)
                marker_state = self._indeterminate_marker_state_from_root_fd(
                    root_fd,
                    batch_id,
                )
                if marker_state == "unsafe":
                    return _error("OPERATOR_PERMIT_UNSAFE")
                if marker_state == "valid":
                    return _error("OPERATOR_EXECUTION_INDETERMINATE")
                if ticket.get("state") == "claimed":
                    return _error("OPERATOR_TICKET_ALREADY_CLAIMED")
                if ticket.get("state") != "pending":
                    return _error("OPERATOR_TICKET_NOT_PENDING")
                claim_fd = self._open_name_at(
                    root_fd,
                    self._claim_name(batch_id),
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                )
            except FileExistsError:
                return _error("OPERATOR_TICKET_ALREADY_CLAIMED")
            except OSError:
                return _error("OPERATOR_PERMIT_UNSAFE")
            try:
                if os.name == "posix":
                    os.fchmod(claim_fd, 0o600)
                if fcntl is not None:
                    fcntl.flock(claim_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._write_all(claim_fd, f"pid={os.getpid()}\n".encode("ascii"))
                os.fsync(claim_fd)
                os.fsync(root_fd)
                locked_ticket = self._read_ticket_from_root_fd(root_fd, batch_id)
                binding_error = self._claim_binding_error(
                    locked_ticket,
                    frozen_expected_canonical,
                )
                if binding_error is not None:
                    self._mark_indeterminate_from_root_fd(
                        root_fd,
                        copy.deepcopy(frozen_expected_ticket),
                    )
                    return _error(binding_error)
                locked_ticket["state"] = "claimed"
                locked_ticket["claimed_at"] = _iso(_utc_now())
                if not self._update_from_root_fd(root_fd, locked_ticket):
                    self._mark_indeterminate_from_root_fd(root_fd, locked_ticket)
                    return _error("OPERATOR_EXECUTION_INDETERMINATE")
                self._register_active_claim(batch_id, claim_fd, root_fd)
                claim_fd = None
                root_fd = None
                if on_claimed is not None:
                    try:
                        return on_claimed(locked_ticket)
                    finally:
                        _release_batch(batch_id)
                return {"ok": True, "ticket": locked_ticket}
            except BaseException:
                if self._claim_fds_are_registered(batch_id, claim_fd, root_fd):
                    released_claim_fd, released_root_fd = _release_batch(batch_id)
                    if released_claim_fd == claim_fd:
                        claim_fd = None
                    if released_root_fd == root_fd:
                        root_fd = None
                elif claim_fd is not None and root_fd is not None:
                    self._mark_indeterminate_from_root_fd(
                        root_fd,
                        copy.deepcopy(frozen_expected_ticket),
                    )
                raise
        finally:
            self._close_fd(claim_fd)
            self._close_fd(root_fd)

    @staticmethod
    def _register_active_claim(batch_id: str, claim_fd: int, root_fd: int) -> None:
        with _ACTIVE_BATCHES_LOCK:
            if (
                batch_id in _ACTIVE_BATCHES
                or batch_id in _ACTIVE_CLAIM_FDS
                or batch_id in _ACTIVE_ROOT_FDS
            ):
                raise OSError("operator batch is already active")
            try:
                _ACTIVE_CLAIM_FDS[batch_id] = claim_fd
                _ACTIVE_ROOT_FDS[batch_id] = root_fd
                _ACTIVE_BATCHES.add(batch_id)
            except BaseException:
                _ACTIVE_BATCHES.discard(batch_id)
                if _ACTIVE_CLAIM_FDS.get(batch_id) == claim_fd:
                    _ACTIVE_CLAIM_FDS.pop(batch_id, None)
                if _ACTIVE_ROOT_FDS.get(batch_id) == root_fd:
                    _ACTIVE_ROOT_FDS.pop(batch_id, None)
                raise

    @staticmethod
    def _claim_fds_are_registered(
        batch_id: str,
        claim_fd: int | None,
        root_fd: int | None,
    ) -> bool:
        with _ACTIVE_BATCHES_LOCK:
            if batch_id not in _ACTIVE_BATCHES:
                return False
            claim_matches = (
                batch_id in _ACTIVE_CLAIM_FDS
                if claim_fd is None
                else _ACTIVE_CLAIM_FDS.get(batch_id) == claim_fd
            )
            root_matches = (
                batch_id in _ACTIVE_ROOT_FDS
                if root_fd is None
                else _ACTIVE_ROOT_FDS.get(batch_id) == root_fd
            )
            return claim_matches and root_matches

    @staticmethod
    def _claim_binding_error(
        observed_ticket: dict[str, Any] | None,
        expected_canonical: str,
    ) -> str | None:
        if observed_ticket is None:
            return "OPERATOR_TICKET_NOT_FOUND"
        validated = validate_operator_ticket(observed_ticket)
        if not validated.get("ok"):
            return str(validated.get("error_code") or "OPERATOR_TICKET_INVALID")
        if _canonical_json(observed_ticket) != expected_canonical:
            return "OPERATOR_TICKET_CHANGED"
        return None

    def _read_ticket_from_root_fd(
        self,
        root_fd: int,
        batch_id: str,
    ) -> dict[str, Any] | None:
        try:
            fd = self._open_name_at(root_fd, self._ticket_name(batch_id), os.O_RDONLY)
        except OSError:
            return None
        try:
            if not self._private_regular_fd(fd):
                return None
            raw = self._read_limited(fd, 1_000_000)
            value = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
        finally:
            self._close_fd(fd)
        return value if isinstance(value, dict) else None

    def _open_name_at(
        self,
        root_fd: int,
        name: str,
        flags: int,
        mode: int = 0o600,
    ) -> int:
        safe_flags = flags | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        if not self._dirfd_supported():
            raise OSError("operator permit dirfd operations are unsupported")
        return os.open(name, safe_flags, mode, dir_fd=root_fd)

    @staticmethod
    def _read_limited(fd: int, limit: int) -> bytes:
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(fd, min(65_536, limit + 1 - total))
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)
            total += len(chunk)
            if total > limit:
                raise OSError("operator permit file exceeds size limit")

    @staticmethod
    def _private_regular_fd(fd: int) -> bool:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            return False
        if os.name == "posix":
            return stat.S_IMODE(info.st_mode) == 0o600 and info.st_uid == os.getuid()
        return True

    def has_claim(self, batch_id: str) -> bool:
        if not isinstance(batch_id, str) or not _ID_RE.fullmatch(batch_id):
            return False
        try:
            root_fd = self._open_root_dir_fd()
        except OSError:
            return False
        try:
            try:
                fd = self._open_name_at(root_fd, self._claim_name(batch_id), os.O_RDONLY)
            except OSError:
                return False
            try:
                return self._private_regular_fd(fd)
            finally:
                self._close_fd(fd)
        finally:
            self._close_fd(root_fd)

    def claim_is_live(self, batch_id: str) -> bool:
        if _batch_is_active(batch_id):
            return True
        if not isinstance(batch_id, str) or not _ID_RE.fullmatch(batch_id):
            return False
        try:
            root_fd = self._open_root_dir_fd()
        except OSError:
            return True
        try:
            try:
                fd = self._open_name_at(root_fd, self._claim_name(batch_id), os.O_RDONLY)
            except FileNotFoundError:
                return False
            except OSError:
                return True
            try:
                private_regular = self._private_regular_fd(fd)
            except OSError:
                self._close_fd(fd)
                return True
            if not private_regular:
                self._close_fd(fd)
                return True
        finally:
            self._close_fd(root_fd)
        try:
            if fcntl is not None:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return True
                except OSError:
                    return True
                fcntl.flock(fd, fcntl.LOCK_UN)
                return False
            marker = os.read(fd, 64).decode("ascii", errors="ignore")
            match = re.fullmatch(r"pid=([1-9][0-9]*)\n?", marker)
            if match is None:
                return False
            try:
                os.kill(int(match.group(1)), 0)
            except ProcessLookupError:
                return False
            except PermissionError:
                return True
            return True
        finally:
            self._close_fd(fd)

    def update(self, ticket: dict[str, Any]) -> bool:
        batch_id = ticket.get("batch_preview_id")
        if not isinstance(batch_id, str) or not _ID_RE.fullmatch(batch_id):
            return False
        if not validate_operator_ticket(ticket).get("ok"):
            return False
        root_fd = _active_root_fd(batch_id)
        if root_fd is not None:
            return self._update_from_root_fd(root_fd, ticket)
        try:
            root_fd = self._open_root_dir_fd()
        except OSError:
            return False
        try:
            return self._update_from_root_fd(root_fd, ticket)
        finally:
            self._close_fd(root_fd)

    def _update_from_root_fd(self, root_fd: int, ticket: dict[str, Any]) -> bool:
        batch_id = ticket.get("batch_preview_id")
        if (
            not isinstance(batch_id, str)
            or not _ID_RE.fullmatch(batch_id)
            or not validate_operator_ticket(ticket).get("ok")
        ):
            return False
        temporary_name = f".{batch_id}.{secrets.token_hex(8)}.tmp"
        fd: int | None = None
        try:
            fd = self._open_name_at(
                root_fd,
                temporary_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            os.fchmod(fd, 0o600)
            self._write_all(fd, (_canonical_json(ticket) + "\n").encode("utf-8"))
            os.fsync(fd)
            self._close_fd(fd)
            fd = None
            os.rename(
                temporary_name,
                self._ticket_name(batch_id),
                src_dir_fd=root_fd,
                dst_dir_fd=root_fd,
            )
            os.fsync(root_fd)
            return True
        except Exception:
            return False
        finally:
            self._close_fd(fd)
            with contextlib.suppress(OSError):
                os.unlink(temporary_name, dir_fd=root_fd)

    def indeterminate_marker_state(self, batch_id: str) -> str:
        if not isinstance(batch_id, str) or not _ID_RE.fullmatch(batch_id):
            return "unsafe"
        try:
            root_fd = self._open_root_dir_fd()
        except OSError:
            return "unsafe"
        try:
            return self._indeterminate_marker_state_from_root_fd(root_fd, batch_id)
        finally:
            self._close_fd(root_fd)

    def _indeterminate_marker_state_from_root_fd(
        self,
        root_fd: int,
        batch_id: str,
    ) -> str:
        try:
            fd = self._open_name_at(root_fd, self._poison_name(batch_id), os.O_RDONLY)
        except FileNotFoundError:
            return "absent"
        except OSError:
            return "unsafe"
        try:
            return "valid" if self._private_regular_fd(fd) else "unsafe"
        except OSError:
            return "unsafe"
        finally:
            self._close_fd(fd)

    def is_indeterminate(self, batch_id: str) -> bool:
        return self.indeterminate_marker_state(batch_id) == "valid"

    def mark_indeterminate(self, ticket: dict[str, Any]) -> bool:
        batch_id = ticket.get("batch_preview_id")
        if not isinstance(batch_id, str) or not _ID_RE.fullmatch(batch_id):
            return False
        root_fd = _active_root_fd(batch_id)
        if root_fd is not None:
            return self._mark_indeterminate_from_root_fd(root_fd, ticket)
        try:
            root_fd = self._open_root_dir_fd()
        except OSError:
            return False
        try:
            return self._mark_indeterminate_from_root_fd(root_fd, ticket)
        finally:
            self._close_fd(root_fd)

    def _mark_indeterminate_from_root_fd(
        self,
        root_fd: int,
        ticket: dict[str, Any],
    ) -> bool:
        batch_id = ticket.get("batch_preview_id")
        digest = ticket.get("manifest_digest")
        _make_ticket_indeterminate(ticket)
        if (
            not isinstance(batch_id, str)
            or not _ID_RE.fullmatch(batch_id)
            or not isinstance(digest, str)
            or not _DIGEST_RE.fullmatch(digest)
        ):
            return False
        fd: int | None = None
        durable = False
        try:
            fd = self._open_name_at(
                root_fd,
                self._poison_name(batch_id),
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
        except FileExistsError:
            durable = self._indeterminate_marker_state_from_root_fd(root_fd, batch_id) == "valid"
            if durable:
                try:
                    os.fsync(root_fd)
                except OSError:
                    durable = False
        except OSError:
            durable = False
        else:
            try:
                os.fchmod(fd, 0o600)
                self._write_all(fd, _canonical_json({
                    "batch_preview_id": batch_id,
                    "manifest_digest": digest,
                    "state": "indeterminate",
                }).encode("utf-8"))
                os.fsync(fd)
                os.fsync(root_fd)
                durable = True
            except OSError:
                durable = False
            finally:
                self._close_fd(fd)
        self._update_from_root_fd(root_fd, ticket)
        return durable

    @staticmethod
    def _write_all(fd: int, data: bytes) -> None:
        remaining = memoryview(data)
        while remaining:
            written = os.write(fd, remaining)
            if written <= 0:
                raise OSError("operator permit write did not make progress")
            remaining = remaining[written:]

    def _open_root_dir_fd(self) -> int:
        return self._walk_root_dir_fd(create_final=False)

    def _ensure_root_fd(self) -> int:
        return self._walk_root_dir_fd(create_final=True)

    def _walk_root_dir_fd(self, *, create_final: bool) -> int:
        if not self._dirfd_supported():
            raise OSError("operator permit dirfd operations are unsupported")
        flags = (
            os.O_RDONLY
            | os.O_CLOEXEC
            | os.O_DIRECTORY
            | os.O_NOFOLLOW
        )
        directory_fd = os.open(os.path.sep, flags)
        try:
            components = Path(self.root).parts[1:]
            for index, component in enumerate(components):
                final_component = index == len(components) - 1
                created = False
                try:
                    next_fd = os.open(component, flags, dir_fd=directory_fd)
                except FileNotFoundError:
                    if not create_final or not final_component:
                        raise
                    try:
                        os.mkdir(component, 0o700, dir_fd=directory_fd)
                        created = True
                        os.fsync(directory_fd)
                    except FileExistsError:
                        pass
                    if created:
                        os.chmod(
                            component,
                            0o700,
                            dir_fd=directory_fd,
                            follow_symlinks=False,
                        )
                        created_info = os.stat(
                            component,
                            dir_fd=directory_fd,
                            follow_symlinks=False,
                        )
                    next_fd = os.open(component, flags, dir_fd=directory_fd)
                    if created:
                        opened_info = os.fstat(next_fd)
                        if (
                            opened_info.st_dev != created_info.st_dev
                            or opened_info.st_ino != created_info.st_ino
                        ):
                            self._close_fd(next_fd)
                            raise OSError("operator permit root changed during creation")
                self._close_fd(directory_fd)
                directory_fd = next_fd
                if created:
                    os.fsync(directory_fd)
            opened = os.fstat(directory_fd)
            if (
                not stat.S_ISDIR(opened.st_mode)
                or stat.S_IMODE(opened.st_mode) != 0o700
                or opened.st_uid != os.getuid()
            ):
                raise OSError("unsafe operator permit root")
            return directory_fd
        except BaseException:
            self._close_fd(directory_fd)
            raise

    def _ensure_root(self) -> None:
        root_fd = self._ensure_root_fd()
        self._close_fd(root_fd)

    @staticmethod
    def _dirfd_supported() -> bool:
        return (
            os.name == "posix"
            and hasattr(os, "O_CLOEXEC")
            and hasattr(os, "O_DIRECTORY")
            and hasattr(os, "O_NOFOLLOW")
            and _HAS_SECURE_DIRFD
        )

    @staticmethod
    def _close_fd(fd: int | None) -> None:
        if fd is None:
            return
        _close_owned_fd(fd)

    def _ticket_path(self, batch_id: str) -> str:
        return os.path.join(self.root, self._ticket_name(batch_id))

    @staticmethod
    def _ticket_name(batch_id: str) -> str:
        return f"{batch_id}.json"

    def _claim_path(self, batch_id: str) -> str:
        return os.path.join(self.root, self._claim_name(batch_id))

    @staticmethod
    def _claim_name(batch_id: str) -> str:
        return f"{batch_id}.claim"

    def _poison_path(self, batch_id: str) -> str:
        return os.path.join(self.root, self._poison_name(batch_id))

    @staticmethod
    def _poison_name(batch_id: str) -> str:
        return f"{batch_id}.indeterminate"


class _OperatorDispatchCapability:
    __slots__ = ()


OPERATOR_DISPATCH_CAPABILITY = _OperatorDispatchCapability()


class OperatorBatchService:
    def __init__(
        self,
        *,
        settings_store: OperatorSettingsStore,
        permit_store: OperatorPermitStore,
        preview_validator: Callable[[dict[str, Any]], dict[str, Any]],
        dispatch: Callable[[object, str, dict[str, Any]], dict[str, Any]],
    ):
        self.settings_store = settings_store
        self.permit_store = permit_store
        self.preview_validator = preview_validator
        self.dispatch = dispatch

    def required_scopes(self, params: dict[str, Any]) -> tuple[str, ...]:
        phase = str(params.get("phase") or "").strip().lower()
        if phase == "status":
            return ("mcp:read",)
        if phase == "preview":
            loaded = self.settings_store.load()
            max_steps = DEFAULT_OPERATOR_MAX_STEPS
            if loaded.get("ok"):
                max_steps = loaded["settings"]["oauth_operator_batch_max_steps"]
            normalized = normalize_operator_operations(
                params.get("operations"),
                max_steps=max_steps,
                preview_validator=self.preview_validator,
            )
            if normalized.get("ok"):
                return tuple(normalized["required_scopes"])
            return ("mcp:commit", "mcp:plan")
        if phase == "execute":
            requested_digest = params.get("manifest_digest")
            ticket = self.permit_store.read(str(params.get("batch_preview_id") or ""))
            if isinstance(ticket, dict):
                validated = validate_operator_ticket(ticket)
                if (
                    validated.get("ok")
                    and isinstance(requested_digest, str)
                    and _DIGEST_RE.fullmatch(requested_digest)
                    and requested_digest == validated.get("manifest_digest")
                ):
                    return tuple(validated["required_scopes"])
            return ("mcp:commit", "mcp:plan")
        return ()

    def handle(self, project_name: str, params: dict[str, Any]) -> dict[str, Any]:
        phase = str(params.get("phase") or "").strip().lower()
        loaded = self.settings_store.load()
        if not loaded.get("ok"):
            return _error(str(loaded.get("error_code") or "OPERATOR_CONFIG_INVALID"))
        settings = loaded["settings"]
        decision = evaluate_operator_principal(current_operator_auth_context(), settings)
        if not decision.allowed:
            return _error(decision.error_code)
        if phase == "preview":
            return self._preview(project_name, params, settings, decision)
        if phase == "execute":
            return self._execute(project_name, params, decision)
        if phase == "status":
            return self._status(project_name, params, decision)
        return _error("OPERATOR_PHASE_INVALID")

    def _preview(
        self,
        project_name: str,
        params: dict[str, Any],
        settings: dict[str, Any],
        decision: OperatorPrincipalDecision,
    ) -> dict[str, Any]:
        allowed_keys = {"workflow", "phase", "project_name", "operations"}
        if set(params) - allowed_keys:
            return _error("OPERATOR_PREVIEW_ARGUMENTS_INVALID")
        normalized = normalize_operator_operations(
            params.get("operations"),
            max_steps=settings["oauth_operator_batch_max_steps"],
            preview_validator=self.preview_validator,
        )
        if not normalized.get("ok"):
            return normalized
        now = _utc_now()
        expires = now + timedelta(seconds=settings["oauth_operator_permit_ttl_seconds"])
        manifest = {
            "schema_version": OPERATOR_MANIFEST_VERSION,
            "project_name": project_name,
            "operations": normalized["operations"],
            "required_scopes": normalized["required_scopes"],
            "expires_at": _iso(expires),
        }
        digest = _manifest_digest(manifest)
        ticket = self.permit_store.create({
            **manifest,
            "manifest_digest": digest,
            "created_at": _iso(now),
            "subject_fingerprint": decision.subject_fingerprint,
            "client_fingerprint": decision.client_fingerprint,
        })
        return {
            "ok": True,
            "batch_preview_id": ticket["batch_preview_id"],
            "manifest_digest": digest,
            "required_scopes": list(normalized["required_scopes"]),
            "operations": [self._public_operation(item) for item in normalized["operations"]],
            "expires_at": ticket["expires_at"],
            "requires_confirmation": True,
        }

    def _execute(
        self,
        project_name: str,
        params: dict[str, Any],
        decision: OperatorPrincipalDecision,
    ) -> dict[str, Any]:
        allowed_keys = {"workflow", "phase", "project_name", "batch_preview_id", "manifest_digest"}
        if set(params) != allowed_keys:
            return _error("OPERATOR_EXECUTE_ARGUMENTS_INVALID")
        batch_id = params.get("batch_preview_id")
        digest = params.get("manifest_digest")
        ticket = self.permit_store.read(str(batch_id or ""))
        if ticket is None:
            return _error("OPERATOR_TICKET_NOT_FOUND")
        validated_ticket = validate_operator_ticket(ticket)
        if not validated_ticket.get("ok"):
            return _error(str(validated_ticket.get("error_code") or "OPERATOR_TICKET_INVALID"))
        ticket = validated_ticket["ticket"]
        if ticket.get("project_name") != project_name:
            return _error("OPERATOR_PROJECT_MISMATCH")
        if digest != ticket.get("manifest_digest"):
            return _error("OPERATOR_MANIFEST_MISMATCH")
        if ticket.get("subject_fingerprint") != decision.subject_fingerprint or ticket.get("client_fingerprint") != decision.client_fingerprint:
            return _error("OPERATOR_PRINCIPAL_DENIED")
        marker_state = self.permit_store.indeterminate_marker_state(str(batch_id))
        if marker_state == "unsafe":
            return _error("OPERATOR_PERMIT_UNSAFE")
        if marker_state == "valid":
            return self._public_ticket(
                _make_ticket_indeterminate(ticket),
                "OPERATOR_EXECUTION_INDETERMINATE",
            )
        orphaned = self._reconcile_orphaned_claim(ticket)
        if orphaned is not None:
            return orphaned
        if ticket.get("state") == "claimed":
            return _error("OPERATOR_TICKET_ALREADY_CLAIMED")
        if ticket.get("state") != "pending":
            return _error("OPERATOR_TICKET_NOT_PENDING")
        expires = _parse_iso(ticket.get("expires_at"))
        if expires is None or _utc_now() > expires:
            return _error("OPERATOR_TICKET_EXPIRED")
        operations = ticket.get("operations")
        if not isinstance(operations, list):
            return _error("OPERATOR_TICKET_INVALID")
        for operation in operations:
            validation = self.preview_validator(operation)
            if not isinstance(validation, dict) or not validation.get("ok"):
                return _error(str(validation.get("error_code") if isinstance(validation, dict) else "OPERATOR_PREVIEW_NOT_FOUND"))
            if validation.get("preview_digest") != operation.get("preview_digest"):
                return _error("OPERATOR_PREVIEW_CHANGED")
        return self.permit_store.claim(
            str(batch_id),
            expected_ticket=ticket,
            on_claimed=self._execute_registered_claim,
        )

    def _execute_registered_claim(self, ticket: dict[str, Any]) -> dict[str, Any]:
        claimed_operations = ticket.get("operations")
        if not isinstance(claimed_operations, list):
            self.permit_store.mark_indeterminate(ticket)
            return self._public_ticket(ticket, "OPERATOR_EXECUTION_INDETERMINATE")
        return self._execute_claimed(ticket, claimed_operations)

    def _execute_claimed(
        self,
        ticket: dict[str, Any],
        operations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        for index, operation in enumerate(operations):
            ticket["steps"][index]["status"] = "running"
            if not self.permit_store.update(ticket):
                self.permit_store.mark_indeterminate(ticket)
                return self._public_ticket(ticket, "OPERATOR_EXECUTION_INDETERMINATE")
            try:
                with operator_artifact_binding_scope(
                    operation["preview_id"],
                    operation["preview_digest"],
                ):
                    result = self.dispatch(
                        OPERATOR_DISPATCH_CAPABILITY,
                        operation["tool"],
                        operation["params"],
                    )
            except Exception:
                self.permit_store.mark_indeterminate(ticket)
                return self._public_ticket(ticket, "OPERATOR_EXECUTION_INDETERMINATE")
            succeeded = isinstance(result, dict) and result.get("ok") is True
            if succeeded:
                ticket["steps"][index]["status"] = "started_async" if operation.get("async") else "succeeded"
                if not self.permit_store.update(ticket):
                    self.permit_store.mark_indeterminate(ticket)
                    return self._public_ticket(ticket, "OPERATOR_EXECUTION_INDETERMINATE")
                continue
            ticket["steps"][index]["status"] = "failed"
            ticket["steps"][index]["error_code"] = self._safe_error_code(result)
            for remaining in ticket["steps"][index + 1:]:
                remaining["status"] = "not_started"
            ticket["state"] = "failed"
            ticket["completed_at"] = _iso(_utc_now())
            if not self.permit_store.update(ticket):
                self.permit_store.mark_indeterminate(ticket)
                return self._public_ticket(ticket, "OPERATOR_EXECUTION_INDETERMINATE")
            return self._public_ticket(ticket, "OPERATOR_STEP_FAILED")
        ticket["state"] = "consumed"
        ticket["completed_at"] = _iso(_utc_now())
        if not self.permit_store.update(ticket):
            self.permit_store.mark_indeterminate(ticket)
            return self._public_ticket(ticket, "OPERATOR_EXECUTION_INDETERMINATE")
        return self._public_ticket(ticket)

    def _status(
        self,
        project_name: str,
        params: dict[str, Any],
        decision: OperatorPrincipalDecision,
    ) -> dict[str, Any]:
        allowed_keys = {"workflow", "phase", "project_name", "batch_preview_id"}
        if set(params) != allowed_keys:
            return _error("OPERATOR_STATUS_ARGUMENTS_INVALID")
        ticket = self.permit_store.read(str(params.get("batch_preview_id") or ""))
        if ticket is None:
            return _error("OPERATOR_TICKET_NOT_FOUND")
        validated_ticket = validate_operator_ticket(ticket)
        if not validated_ticket.get("ok"):
            return _error(str(validated_ticket.get("error_code") or "OPERATOR_TICKET_INVALID"))
        ticket = validated_ticket["ticket"]
        if ticket.get("project_name") != project_name:
            return _error("OPERATOR_PROJECT_MISMATCH")
        if ticket.get("subject_fingerprint") != decision.subject_fingerprint or ticket.get("client_fingerprint") != decision.client_fingerprint:
            return _error("OPERATOR_PRINCIPAL_DENIED")
        marker_state = self.permit_store.indeterminate_marker_state(
            str(params.get("batch_preview_id") or "")
        )
        if marker_state == "unsafe":
            return _error("OPERATOR_PERMIT_UNSAFE")
        if marker_state == "valid":
            return self._public_ticket(
                _make_ticket_indeterminate(ticket),
                "OPERATOR_EXECUTION_INDETERMINATE",
            )
        orphaned = self._reconcile_orphaned_claim(ticket)
        if orphaned is not None:
            return orphaned
        return self._public_ticket(ticket)

    def _reconcile_orphaned_claim(self, ticket: dict[str, Any]) -> dict[str, Any] | None:
        batch_id = str(ticket.get("batch_preview_id") or "")
        state = ticket.get("state")
        claim_exists = self.permit_store.has_claim(batch_id)
        if state not in {"pending", "claimed"}:
            return None
        if claim_exists and self.permit_store.claim_is_live(batch_id):
            return None
        if state == "pending" and not claim_exists:
            return None
        self.permit_store.mark_indeterminate(ticket)
        return self._public_ticket(ticket, "OPERATOR_EXECUTION_INDETERMINATE")

    def _public_ticket(self, ticket: dict[str, Any], error_code: str | None = None) -> dict[str, Any]:
        batch_id = ticket.get("batch_preview_id")
        safe_batch_id = batch_id if isinstance(batch_id, str) and _ID_RE.fullmatch(batch_id) else None
        digest = ticket.get("manifest_digest")
        safe_digest = digest if isinstance(digest, str) and _DIGEST_RE.fullmatch(digest) else None
        state = ticket.get("state")
        safe_state = state if state in _TICKET_STATES else "indeterminate"
        parsed_expiry = _parse_iso(ticket.get("expires_at"))
        safe_expires_at = _iso(parsed_expiry.astimezone(timezone.utc)) if parsed_expiry is not None else None
        safe_steps: list[dict[str, Any]] = []
        raw_steps = ticket.get("steps")
        if isinstance(raw_steps, list):
            for index, step in enumerate(raw_steps[:OPERATOR_STEP_RANGE[1]]):
                if not isinstance(step, dict):
                    continue
                step_id = step.get("step_id")
                safe_step_id = step_id if isinstance(step_id, str) and _STEP_ID_RE.fullmatch(step_id) else f"step-{index + 1}"
                step_state = step.get("status")
                safe_step_state = step_state if step_state in _STEP_STATES else "indeterminate"
                public_step: dict[str, Any] = {"step_id": safe_step_id, "status": safe_step_state}
                step_error = step.get("error_code")
                if isinstance(step_error, str) and _ERROR_CODE_RE.fullmatch(step_error):
                    public_step["error_code"] = step_error
                safe_steps.append(public_step)
        result = {
            "ok": error_code is None,
            "batch_preview_id": safe_batch_id,
            "manifest_digest": safe_digest,
            "state": safe_state,
            "steps": safe_steps,
            "expires_at": safe_expires_at,
        }
        if error_code is not None:
            result["error_code"] = (
                error_code
                if isinstance(error_code, str) and _ERROR_CODE_RE.fullmatch(error_code)
                else "OPERATOR_REQUEST_FAILED"
            )
            result["message"] = "Operator batch did not complete."
        return result

    def _public_operation(self, operation: dict[str, Any]) -> dict[str, Any]:
        return {
            "step_id": operation.get("step_id"),
            "tool": operation.get("tool"),
            "operation": operation.get("operation"),
            "phase": operation.get("phase"),
        }

    def _safe_error_code(self, result: object) -> str:
        if isinstance(result, dict):
            value = result.get("error_code")
            if isinstance(value, str) and re.fullmatch(r"[A-Z0-9_]{1,80}", value):
                return value
        return "OPERATOR_STEP_ERROR"


def _error(code: str) -> dict[str, Any]:
    safe_code = code if isinstance(code, str) and _ERROR_CODE_RE.fullmatch(code) else "OPERATOR_REQUEST_FAILED"
    return {"ok": False, "error_code": safe_code, "message": "Operator request was denied."}


def _contains_private_key(value: object) -> bool:
    private_keys = {
        "authorization", "cookie", "cookies", "token", "access_token",
        "refresh_token", "client_secret", "secret", "private_key",
    }
    if isinstance(value, dict):
        for key, nested in value.items():
            if str(key).strip().lower() in private_keys or _contains_private_key(nested):
                return True
    elif isinstance(value, list):
        return any(_contains_private_key(item) for item in value)
    return False


def _claim_contains(value: object, expected: str) -> bool:
    if isinstance(value, str):
        return value == expected
    if isinstance(value, (list, tuple, set)):
        return any(isinstance(item, str) and item == expected for item in value)
    return False
