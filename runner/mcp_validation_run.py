import hashlib
import hmac
import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from runner.core_confirmation import (
    confirmation_apply_guard,
    confirmation_guard_reports_expired_before_mismatch,
)
from runner.current_version import load_current_version
from runner.path_policy import RunnerPathPolicy
from runner.plan_loader import PlanLoader
from runner.review_manifest_validation import (
    build_review_manifest_validation_contract,
    canonical_manifest_validation_sha256,
    manifest_validation_contract_from_artifact,
    normalize_review_manifest_validation_source,
)
from runner.runner_paths import resolve_project_runner_path
from runner.work_item_governance.source_binding import (
    _inspect_git_checkout,
    _trusted_git_for_checkout,
)


PREVIEW_TTL_SECONDS = 3600
PREVIEWS_DIR = os.path.join("runtime", "validation-run-previews")
RUNS_DIR = os.path.join("runtime", "validation-runs")
MAX_TARGET_FILES = 50
MAX_COMMANDS = 50
MAX_STDOUT_CHARS = 8000
MAX_STDERR_CHARS = 6000
MAX_TOTAL_OUTPUT_CHARS = 16000
VALID_SCOPES = {"changed_files", "target_files", "current_version", "full"}
MIN_TIMEOUT_SECONDS = 10
MAX_TIMEOUT_SECONDS = 900
DEFAULT_TIMEOUT_SECONDS = 300
VALIDATION_RUN_RESULT_SCHEMA_VERSION = "colameta.validation_run_result.v1"
P1_VALIDATION_MAX_AGE_SECONDS = 24 * 60 * 60
SHELL_META_PATTERNS = ("&&", ";", "|", ">", "<", "`", "$(", "${", "\n", "\r")
DANGEROUS_EXECUTABLES = {"rm", "sudo", "su", "chmod", "chown", "curl", "wget", "ssh", "scp", "rsync", "docker", "podman", "kubectl", "terraform"}

SENSITIVE_TEXT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"Bearer\s+\S+", re.IGNORECASE), "Bearer ***"),
    (re.compile(r"api[_-]?key=\S+", re.IGNORECASE), "api_key=[REDACTED]"),
    (re.compile(r"token=\S+", re.IGNORECASE), "token=[REDACTED]"),
    (re.compile(r"secret=\S+", re.IGNORECASE), "secret=[REDACTED]"),
    (re.compile(r"sk-[A-Za-z0-9_-]+"), "[REDACTED]"),
    (re.compile(r"https://[^/\s:@]+:[^@\s]+@"), "https://***@"),
]

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_FULL_GIT_OBJECT_ID_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_RUN_RESULT_FIELDS = frozenset(
    {
        "schema_version",
        "run_id",
        "preview_id",
        "action",
        "status",
        "passed",
        "scope",
        "target_files",
        "strategy",
        "validation_groups",
        "command_summary",
        "command_count",
        "command_results",
        "failed_command_indexes",
        "failed_command_index",
        "output_summary",
        "started_at",
        "completed_at",
        "duration_seconds",
        "manifest_validation",
    }
)
_TERMINAL_RUN_RESULT_FIELDS = _RUN_RESULT_FIELDS | {"validation_result_sha256"}
_LEGACY_TERMINAL_REQUIRED_FIELDS = frozenset(
    {
        "run_id",
        "preview_id",
        "action",
        "status",
        "passed",
        "scope",
        "target_files",
        "strategy",
        "validation_groups",
        "command_results",
        "failed_command_indexes",
        "failed_command_index",
        "output_summary",
        "started_at",
        "completed_at",
        "duration_seconds",
    }
)
_LEGACY_TERMINAL_OPTIONAL_FIELDS = frozenset(
    {"command_summary", "command_count", "manifest_validation"}
)
_P1_COMMAND_CONTRACT = (
    (
        "pytest",
        (".venv/bin/python", "-m", "pytest", "-q"),
        900,
    ),
    (
        "self_hosting_smoke",
        (".venv/bin/python", "scripts/self_hosting_smoke.py"),
        900,
    ),
    (
        "compileall",
        (
            ".venv/bin/python",
            "-m",
            "compileall",
            "-q",
            "adapters",
            "runner",
            "schemas",
            "scripts",
            "tests",
        ),
        600,
    ),
    (
        "ruff",
        (
            ".venv/bin/python",
            "-m",
            "ruff",
            "check",
            "adapters",
            "runner",
            "schemas",
            "scripts",
            "tests",
        ),
        600,
    ),
    (
        "git_diff_check",
        ("git", "diff", "--check"),
        600,
    ),
)
_P1_COMMAND_FAMILIES = tuple(
    family for family, _argv, _timeout in _P1_COMMAND_CONTRACT
)
_ISOLATED_CHECKOUT_MODE = "isolated_detached_worktree"
_CHECKOUT_PROVENANCE_FIELDS = frozenset(
    {
        "mode",
        "candidate_head",
        "candidate_tree",
        "source_before",
        "source_after",
        "source_binding_match",
        "isolated_from_project_worktree",
        "cleanup_complete",
    }
)
_CHECKOUT_SNAPSHOT_FIELDS = frozenset(
    {
        "head",
        "tree",
        "candidate_clean",
        "git_object_format",
        "git_object_manifest_sha256",
        "tracked_path_count",
        "worktree_id_sha256",
        "violation_count",
    }
)


class P1ValidationResultError(ValueError):
    """Fail-closed, path-free validation result error for P1 evidence."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def canonical_validation_result_sha256(result: dict[str, Any]) -> str:
    """Hash one closed terminal result without its self-referential digest."""

    payload = {
        key: value
        for key, value in result.items()
        if key != "validation_result_sha256"
    }
    # The existing manifest helper is the canonicalization authority.  This
    # explicit pass adds the validation-result requirement to reject NaN and
    # infinity before using that helper's byte-compatible valid-value output.
    json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return canonical_manifest_validation_sha256(payload)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _redact_sensitive_text(value: Any) -> str:
    text = value if isinstance(value, str) else str(value or "")
    result = text
    for pattern, replacement in SENSITIVE_TEXT_PATTERNS:
        result = pattern.sub(replacement, result)
    return result


def _truncate(text: str, max_chars: int) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars], True


def _validate_preview_id(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not 8 <= len(stripped) <= 64:
        return None
    if not re.fullmatch(r"[A-Za-z0-9_-]+", stripped):
        return None
    return stripped


class MCPValidationRunManager:
    def __init__(self, project_root: str):
        self.project_root = os.path.abspath(os.path.expanduser(project_root))
        self._previews_root = resolve_project_runner_path(self.project_root, PREVIEWS_DIR)
        self._runs_root = resolve_project_runner_path(self.project_root, RUNS_DIR)
        self._path_policy = RunnerPathPolicy()

    def handle(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        normalized_action = action.strip().lower() if isinstance(action, str) else ""
        if normalized_action == "inspect":
            return self.inspect()
        if normalized_action == "preview":
            return self.preview(params)
        if normalized_action == "run":
            return self.run(params)
        if normalized_action == "status":
            return self.status(params)
        return {
            "ok": False,
            "action": normalized_action or "unknown",
            "error_code": "UNKNOWN_ACTION",
            "message": "action 仅支持 inspect、preview、run 或 status。",
        }

    def inspect(self) -> dict[str, Any]:
        current_version = load_current_version(self.project_root)
        acceptance_commands, acceptance_warnings = self._current_acceptance_commands()
        detected_project_types = self._detect_project_types()
        return {
            "ok": True,
            "action": "inspect",
            "supported_scopes": sorted(VALID_SCOPES),
            "fixed_interface": {"inputs": ["scope", "target_files"], "language_suite_exposed": False},
            "current_version": current_version,
            "acceptance_command_count": len(acceptance_commands),
            "acceptance_warnings": acceptance_warnings,
            "detected_project_types": detected_project_types,
            "recommended_scopes": ["current_version", "changed_files", "target_files", "full"],
        }

    def preview(self, params: dict[str, Any]) -> dict[str, Any]:
        scope, scope_error = self._normalize_scope(params.get("scope"))
        if scope_error:
            return scope_error

        target_files, target_error = self._normalize_target_files(params.get("target_files"))
        if target_error:
            return target_error

        resolved_files = list(target_files)
        if scope == "changed_files":
            changed_files, changed_error = self._collect_changed_files()
            if changed_error:
                return changed_error
            resolved_files = changed_files
        elif scope == "target_files" and not resolved_files:
            return {
                "ok": False,
                "action": "preview",
                "error_code": "TARGET_FILES_REQUIRED",
                "message": "scope=target_files 时必须提供 target_files。",
            }

        commands, command_specs, strategy, warnings, validation_groups = self._select_commands(scope, resolved_files)
        blockers: list[str] = []
        if not commands:
            blockers.append("NO_VALIDATION_COMMANDS")

        now = _utc_now()
        preview_id = uuid.uuid4().hex[:12]
        current_head = self._git_stdout(["rev-parse", "HEAD"]).strip()
        artifact = {
            "preview_id": preview_id,
            "artifact_kind": "validation_run",
            "project_root": self.project_root,
            "scope": scope,
            "target_files": resolved_files,
            "strategy": strategy,
            "validation_groups": validation_groups,
            "commands": commands,
            "command_specs": command_specs,
            "current_head": current_head,
            "created_at": _iso(now),
            "expires_at": _iso(now + timedelta(seconds=PREVIEW_TTL_SECONDS)),
            "blockers": blockers,
            "warnings": warnings,
        }
        self._write_preview(preview_id, artifact)

        can_run = len(blockers) == 0
        return {
            "ok": True,
            "action": "preview",
            "preview_id": preview_id,
            "scope": scope,
            "target_files": resolved_files,
            "strategy": strategy,
            "validation_groups": validation_groups,
            "command_summary": self._command_summary(commands),
            "command_count": len(commands),
            "can_run": can_run,
            "blockers": blockers,
            "warnings": warnings,
            "created_at": artifact["created_at"],
            "expires_at": artifact["expires_at"],
            "next_actions": [
                {
                    "tool": "manage_validation_run",
                    "action": "run",
                    "params": {"action": "run", "preview_id": preview_id},
                    "reason": "使用 preview 固化的验证命令运行一次。",
                    "requires_confirmation": True,
                    "risk_level": "commit",
                }
            ] if can_run else [],
        }

    def preview_manifest_bound(self, manifest_source: dict[str, Any]) -> dict[str, Any]:
        """Freeze one inspected review manifest's declared validation contract.

        The public MCP layer is responsible for re-verifying the short-lived
        review session before it calls this method.  This manager then applies
        the same shell-free command policy used for normal Runner acceptance
        commands and persists only effective argv specs in the normal preview
        store.  A later run is separately re-verified by the MCP layer.
        """

        source = normalize_review_manifest_validation_source(manifest_source)
        if source is None:
            return {
                "ok": False,
                "action": "preview",
                "error_code": "INVALID_MANIFEST_VALIDATION_SOURCE",
                "message": "manifest validation source 无效，未生成验证 preview。",
            }

        command_specs, rejection_details = self._manifest_bound_command_specs(
            source["acceptance_commands"]
        )
        blockers: list[str] = []
        warnings: list[str] = []
        if rejection_details:
            blockers.append("MANIFEST_VALIDATION_COMMAND_REJECTED")
            warnings.append("至少一条 manifest acceptance command 未通过本地 shell-free 执行策略。")
            # A mixed safe/unsafe declaration must not silently turn into a
            # partial execution. The whole declared contract is rejected.
            command_specs = []
        if not source["acceptance_commands"]:
            blockers.append("NO_MANIFEST_ACCEPTANCE_COMMANDS")
            warnings.append("review manifest 没有声明 acceptance_commands。")
        if not command_specs and not blockers:
            blockers.append("NO_MANIFEST_VALIDATION_COMMANDS")
            warnings.append("review manifest 没有可执行的 acceptance_commands。")

        commands = [list(spec["argv"]) for spec in command_specs]
        manifest_validation = build_review_manifest_validation_contract(
            source,
            command_specs,
        )
        target_files = [subject["path"] for subject in source["subjects"]]
        now = _utc_now()
        preview_id = uuid.uuid4().hex[:12]
        artifact = {
            "preview_id": preview_id,
            "artifact_kind": "validation_run",
            "project_root": self.project_root,
            "scope": "manifest_bound",
            "target_files": target_files,
            "strategy": "manifest_acceptance",
            "validation_groups": [{
                "strategy": "manifest_acceptance",
                "files": target_files,
                "command_count": len(commands),
                "manifest_sha256": manifest_validation["manifest_sha256"],
                "contract_sha256": manifest_validation["contract_sha256"],
            }],
            "commands": commands,
            "command_specs": command_specs,
            "manifest_validation": manifest_validation,
            "current_head": self._git_stdout(["rev-parse", "HEAD"]).strip(),
            "created_at": _iso(now),
            "expires_at": _iso(now + timedelta(seconds=PREVIEW_TTL_SECONDS)),
            "blockers": blockers,
            "warnings": warnings,
        }
        self._write_preview(preview_id, artifact)

        can_run = not blockers and bool(commands)
        return {
            "ok": True,
            "action": "preview",
            "preview_id": preview_id,
            "scope": artifact["scope"],
            "target_files": target_files,
            "strategy": artifact["strategy"],
            "validation_groups": artifact["validation_groups"],
            "command_summary": self._command_summary(commands),
            "command_count": len(commands),
            "manifest_validation": manifest_validation,
            "manifest_validation_rejections": rejection_details,
            "can_run": can_run,
            "blockers": blockers,
            "warnings": warnings,
            "created_at": artifact["created_at"],
            "expires_at": artifact["expires_at"],
            "next_actions": [
                {
                    "tool": "manage_validation_run",
                    "action": "run",
                    "params": {"action": "run", "preview_id": preview_id},
                    "reason": "使用已绑定且会在执行前重新复核的 manifest validation preview 运行一次。",
                    "requires_confirmation": True,
                    "risk_level": "commit",
                }
            ] if can_run else [],
        }

    def run(self, params: dict[str, Any]) -> dict[str, Any]:
        preview_id = _validate_preview_id(params.get("preview_id"))
        if preview_id is None:
            return {
                "ok": False,
                "action": "run",
                "error_code": "INVALID_PREVIEW_ID",
                "message": "run 需要合法 preview_id。",
            }
        artifact = self._read_preview(preview_id)
        if artifact is None:
            return {
                "ok": False,
                "action": "run",
                "error_code": "PREVIEW_NOT_FOUND",
                "message": "preview_id 不存在或已过期。",
            }

        if str(artifact.get("artifact_kind") or "") != "validation_run":
            return {
                "ok": False,
                "action": "run",
                "error_code": "PREVIEW_KIND_MISMATCH",
                "message": "preview_id 类型不匹配。",
            }

        guard = confirmation_apply_guard(self, preview_id, project_root=self.project_root, payload=artifact)
        if not guard["ok"]:
            ec = guard["error_code"]
            if ec == "PREVIEW_NOT_FOUND":
                return {
                    "ok": False, "action": "run",
                    "error_code": "PREVIEW_NOT_FOUND",
                    "message": "preview_id 不存在或已过期。",
                }
            # Preserve original ordering: expiry before project mismatch.
            if confirmation_guard_reports_expired_before_mismatch(guard, self.is_expired):
                return {
                    "ok": False, "action": "run",
                    "error_code": "PREVIEW_EXPIRED",
                    "message": "preview_id 已过期，请重新生成 preview。",
                }
            if ec == "PROJECT_MISMATCH":
                return {
                    "ok": False, "action": "run",
                    "error_code": "PROJECT_ROOT_MISMATCH",
                    "message": "preview 绑定的项目目录与当前项目不一致。",
                }
            if ec == "PREVIEW_EXPIRED":
                return {
                    "ok": False, "action": "run",
                    "error_code": "PREVIEW_EXPIRED",
                    "message": "preview_id 已过期，请重新生成 preview。",
                }
            return {
                "ok": False,
                "action": "run",
                "error_code": str(ec or "PREVIEW_INVALID"),
                "message": "preview no longer matches the authorized artifact.",
            }
        artifact = guard["payload"]
        blockers = artifact.get("blockers")
        if isinstance(blockers, list) and blockers:
            return {
                "ok": False,
                "action": "run",
                "error_code": "PREVIEW_BLOCKED",
                "message": "preview 包含阻断项，不能运行；请重新生成有效 preview。",
            }
        commands = artifact.get("commands")
        command_specs = artifact.get("command_specs")
        if not isinstance(command_specs, list) or not command_specs:
            command_specs = self._command_specs_for_commands(commands if isinstance(commands, list) else [])
        if not isinstance(commands, list) or not commands:
            return {
                "ok": False,
                "action": "run",
                "error_code": "NO_VALIDATION_COMMANDS",
                "message": "preview 中没有可执行验证命令。",
            }
        if len(commands) > MAX_COMMANDS:
            return {
                "ok": False,
                "action": "run",
                "error_code": "TOO_MANY_COMMANDS",
                "message": "preview 命令数量超过限制。",
            }

        started_at = _utc_now()
        run_id = f"validation_run_{started_at.strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:8]}"
        run_record = self._initial_run_record(run_id, preview_id, artifact, commands, started_at)
        run_file = self._write_run_result(run_id, run_record)
        worker = threading.Thread(
            target=self._execute_run_worker_safe,
            args=(run_id, preview_id, artifact, command_specs, commands, started_at),
            name=f"validation-run-{run_id}",
            daemon=True,
        )
        worker.start()

        result = {
            "ok": True,
            "action": "run",
            "run_id": run_id,
            "preview_id": preview_id,
            "status": "running",
            "passed": None,
            "scope": artifact.get("scope"),
            "target_files": artifact.get("target_files", []),
            "strategy": artifact.get("strategy"),
            "validation_groups": artifact.get("validation_groups", []),
            "command_summary": self._command_summary(commands),
            "command_count": len(commands),
            "run_file": run_file,
            "message": "验证已启动，请用 status 轮询结果。",
        }
        manifest_validation = artifact.get("manifest_validation")
        if isinstance(manifest_validation, dict):
            result["manifest_validation"] = dict(manifest_validation)
        return result

    def _execute_run_worker_safe(
        self,
        run_id: str,
        preview_id: str,
        artifact: dict[str, Any],
        command_specs: list[dict[str, Any]],
        commands: list[list[str]],
        started_at: datetime,
    ) -> None:
        try:
            self._execute_run_worker(run_id, preview_id, artifact, command_specs, commands, started_at)
        except Exception as exc:
            completed_at = _utc_now()
            stderr = f"VALIDATION_RUN_FAILED: {_redact_sensitive_text(str(exc))}"
            run_record = {
                **self._initial_run_record(run_id, preview_id, artifact, commands, started_at),
                "status": "failed",
                "passed": False,
                "command_results": [{
                    "index": 0,
                    "ok": False,
                    "returncode": 125,
                    "error_code": "VALIDATION_RUN_FAILED",
                    "command": "",
                    "stdout": "",
                    "stderr": stderr,
                    "stdout_truncated": False,
                    "stderr_truncated": False,
                }],
                "failed_command_indexes": [0],
                "failed_command_index": 0,
                "output_summary": {"total_output_chars": len(stderr), "redacted": True, "truncated": False},
                "completed_at": _iso(completed_at),
                "duration_seconds": max(0.0, (completed_at - started_at).total_seconds()),
            }
            self._write_terminal_run_result(run_id, run_record)

    def _execute_run_worker(
        self,
        run_id: str,
        preview_id: str,
        artifact: dict[str, Any],
        command_specs: list[dict[str, Any]],
        commands: list[list[str]],
        started_at: datetime,
    ) -> None:
        command_results: list[dict[str, Any]] = []
        total_output_chars = 0
        failed_indexes: list[int] = []
        isolated_checkout: dict[str, Any] | None = None
        execution_root = self.project_root
        source_after: dict[str, Any] | None = None
        cleanup_complete = True
        try:
            if artifact.get("scope") == "manifest_bound":
                candidate_head = self._manifest_candidate_head(artifact)
                if candidate_head is None:
                    raise RuntimeError(
                        "manifest-bound validation has no candidate checkout"
                    )
                isolated_checkout = self._prepare_isolated_checkout(
                    candidate_head,
                    run_id,
                )
                execution_root = str(isolated_checkout["root"])

            for index, spec in enumerate(command_specs):
                command = spec.get("argv") if isinstance(spec, dict) else None
                timeout_seconds = self._normalize_timeout_seconds(
                    spec.get("timeout_seconds")
                    if isinstance(spec, dict)
                    else None
                )
                continue_on_failure = (
                    bool(spec.get("continue_on_failure", False))
                    if isinstance(spec, dict)
                    else False
                )
                if not self._is_safe_command(command):
                    failed_indexes.append(index)
                    command_results.append({
                        "index": index,
                        "ok": False,
                        "returncode": 127,
                        "command": self._display_command(command),
                        "stdout": "",
                        "stderr": "命令结构无效，已阻断。",
                        "stdout_truncated": False,
                        "stderr_truncated": False,
                    })
                    break
                result = self._run_command(
                    command,
                    timeout_seconds=timeout_seconds,
                    cwd=execution_root,
                )
                stdout = result["stdout"]
                stderr = result["stderr"]
                remaining = max(
                    0,
                    MAX_TOTAL_OUTPUT_CHARS - total_output_chars,
                )
                per_stream_limit = min(MAX_STDOUT_CHARS, remaining)
                stdout, stdout_truncated = _truncate(stdout, per_stream_limit)
                total_output_chars += len(stdout)
                remaining = max(
                    0,
                    MAX_TOTAL_OUTPUT_CHARS - total_output_chars,
                )
                per_stream_limit = min(MAX_STDERR_CHARS, remaining)
                stderr, stderr_truncated = _truncate(stderr, per_stream_limit)
                total_output_chars += len(stderr)
                ok = result["returncode"] == 0
                if not ok:
                    failed_indexes.append(index)
                command_results.append({
                    "index": index,
                    "ok": ok,
                    "returncode": result["returncode"],
                    "error_code": result.get("error_code"),
                    "timeout_seconds": timeout_seconds,
                    "continue_on_failure": continue_on_failure,
                    "command": self._display_command(command),
                    "stdout": stdout,
                    "stderr": stderr,
                    "stdout_truncated": stdout_truncated,
                    "stderr_truncated": stderr_truncated,
                })
                if not ok and not continue_on_failure:
                    break

            if isolated_checkout is not None:
                self._remove_isolated_execution_overlays(
                    isolated_checkout
                )
                source_after = self._capture_checkout_snapshot(
                    Path(execution_root)
                )
        finally:
            if isolated_checkout is not None:
                cleanup_complete = self._cleanup_isolated_checkout(
                    isolated_checkout
                )

        checkout_provenance: dict[str, Any] | None = None
        if isolated_checkout is not None:
            source_before = isolated_checkout["source_before"]
            source_binding_match = (
                isinstance(source_after, dict)
                and source_before == source_after
            )
            checkout_provenance = {
                "mode": _ISOLATED_CHECKOUT_MODE,
                "candidate_head": isolated_checkout["candidate_head"],
                "candidate_tree": isolated_checkout["candidate_tree"],
                "source_before": source_before,
                "source_after": source_after,
                "source_binding_match": source_binding_match,
                "isolated_from_project_worktree": isolated_checkout[
                    "isolated_from_project_worktree"
                ],
                "cleanup_complete": cleanup_complete,
            }
            provenance_valid = (
                source_binding_match
                and source_before.get("candidate_clean") is True
                and checkout_provenance["isolated_from_project_worktree"]
                is True
                and cleanup_complete
            )
            if not provenance_valid:
                failed_index = max(0, len(command_results) - 1)
                if failed_index not in failed_indexes:
                    failed_indexes.append(failed_index)
                if command_results:
                    command_result = command_results[failed_index]
                    command_result["ok"] = False
                    if command_result.get("returncode") == 0:
                        command_result["returncode"] = 125
                    command_result["error_code"] = (
                        "VALIDATION_CHECKOUT_PROVENANCE_INVALID"
                    )
                    message = (
                        "Validation checkout provenance changed or cleanup "
                        "did not complete."
                    )
                    command_result["stderr"] = message
                    command_result["stderr_truncated"] = False
                    total_output_chars += len(message)

        failed_indexes.sort()
        status = "passed" if not failed_indexes else "failed"
        completed_at = _utc_now()
        output_summary: dict[str, Any] = {
            "total_output_chars": total_output_chars,
            "redacted": True,
            "truncated": total_output_chars >= MAX_TOTAL_OUTPUT_CHARS,
        }
        if checkout_provenance is not None:
            output_summary["checkout_provenance"] = checkout_provenance
        run_record = {
            "schema_version": VALIDATION_RUN_RESULT_SCHEMA_VERSION,
            "run_id": run_id,
            "preview_id": preview_id,
            "action": "run",
            "status": status,
            "passed": status == "passed",
            "scope": artifact.get("scope"),
            "target_files": artifact.get("target_files", []),
            "strategy": artifact.get("strategy"),
            "validation_groups": artifact.get("validation_groups", []),
            "command_summary": self._command_summary(commands),
            "command_count": len(commands),
            "command_results": command_results,
            "failed_command_indexes": failed_indexes,
            "failed_command_index": failed_indexes[0] if failed_indexes else None,
            "output_summary": output_summary,
            "started_at": _iso(started_at),
            "completed_at": _iso(completed_at),
            "duration_seconds": max(0.0, (completed_at - started_at).total_seconds()),
            "manifest_validation": (
                dict(artifact["manifest_validation"])
                if isinstance(artifact.get("manifest_validation"), dict)
                else None
            ),
        }
        self._write_terminal_run_result(run_id, run_record)

    def _initial_run_record(
        self,
        run_id: str,
        preview_id: str,
        artifact: dict[str, Any],
        commands: list[list[str]],
        started_at: datetime,
    ) -> dict[str, Any]:
        result = {
            "schema_version": VALIDATION_RUN_RESULT_SCHEMA_VERSION,
            "run_id": run_id,
            "preview_id": preview_id,
            "action": "run",
            "status": "running",
            "passed": None,
            "scope": artifact.get("scope"),
            "target_files": artifact.get("target_files", []),
            "strategy": artifact.get("strategy"),
            "validation_groups": artifact.get("validation_groups", []),
            "command_summary": self._command_summary(commands),
            "command_count": len(commands),
            "command_results": [],
            "failed_command_indexes": [],
            "failed_command_index": None,
            "output_summary": {"total_output_chars": 0, "redacted": True, "truncated": False},
            "started_at": _iso(started_at),
            "completed_at": None,
            "duration_seconds": None,
            "manifest_validation": (
                dict(artifact["manifest_validation"])
                if isinstance(artifact.get("manifest_validation"), dict)
                else None
            ),
        }
        return result

    def status(self, params: dict[str, Any]) -> dict[str, Any]:
        run_id = self._validate_run_id(params.get("run_id"))
        if run_id is None:
            return {"ok": False, "action": "status", "error_code": "INVALID_RUN_ID", "message": "status 需要合法 run_id。"}
        data, read_error = self._read_verified_run_result(run_id)
        if read_error == "RUN_NOT_FOUND":
            return {"ok": False, "action": "status", "error_code": "RUN_NOT_FOUND", "message": "run_id 不存在。"}
        if read_error is not None:
            classification = (
                "unverified_legacy"
                if read_error == "RUN_RESULT_UNVERIFIED_LEGACY"
                else "integrity_failure"
            )
            return {
                "ok": False,
                "action": "status",
                "error_code": read_error,
                "message": "run result 未通过闭合 schema 与 canonical digest 校验。",
                "integrity_classification": classification,
            }
        assert data is not None
        response = dict(data)
        response["action"] = "status"
        response["ok"] = True
        response["integrity_classification"] = (
            "non_terminal" if data["status"] == "running" else "verified"
        )
        return response

    def verify_p1_result(
        self,
        run_id: Any,
        *,
        candidate_head: str,
        expected_validation_result_sha256: str,
        expected_contract_sha256: str,
        expected_manifest_sha256: str,
        now: datetime,
        require_current_head: bool,
        phase: str,
    ) -> dict[str, Any]:
        """Re-read and verify one manifest-bound run selected only by run_id."""

        normalized_run_id = self._validate_run_id(run_id)
        if normalized_run_id is None:
            raise P1ValidationResultError(
                "P1_VALIDATION_RESULT_NOT_FOUND",
                "The referenced validation result was not found.",
            )
        data, read_error = self._read_verified_run_result(
            normalized_run_id,
            validate_manifest_contract=False,
        )
        if read_error == "RUN_NOT_FOUND":
            raise P1ValidationResultError(
                "P1_VALIDATION_RESULT_NOT_FOUND",
                "The referenced validation result was not found.",
            )
        if read_error == "RUN_RESULT_UNVERIFIED_LEGACY":
            raise P1ValidationResultError(
                "P1_LEGACY_VALIDATION_PROVENANCE_MISSING",
                "The validation result predates canonical result provenance.",
            )
        if read_error == "RUN_RESULT_DIGEST_MISMATCH":
            raise P1ValidationResultError(
                "P1_VALIDATION_RESULT_DIGEST_MISMATCH",
                "The validation result canonical digest does not match.",
            )
        if read_error is not None or data is None:
            raise P1ValidationResultError(
                "P1_VALIDATION_RESULT_SCHEMA_INVALID",
                "The validation result has an invalid closed schema.",
            )
        if data.get("status") == "running":
            raise P1ValidationResultError(
                "P1_VALIDATION_RESULT_NOT_TERMINAL",
                "The validation result is not terminal.",
            )
        if data.get("status") != "passed" or data.get("passed") is not True:
            raise P1ValidationResultError(
                "P1_VALIDATION_RESULT_NOT_PASSED",
                "The validation result did not pass.",
            )
        if (
            data.get("scope") != "manifest_bound"
            or data.get("strategy") != "manifest_acceptance"
        ):
            raise P1ValidationResultError(
                "P1_VALIDATION_RESULT_SCHEMA_INVALID",
                "The validation result is not a manifest-bound acceptance run.",
            )

        contract = data.get("manifest_validation")
        if not isinstance(contract, dict):
            raise P1ValidationResultError(
                "P1_VALIDATION_RESULT_SCHEMA_INVALID",
                "The validation result does not contain a manifest contract.",
            )
        command_specs = contract.get("command_specs")
        try:
            fresh_specs_sha256 = canonical_manifest_validation_sha256(command_specs)
        except (TypeError, ValueError):
            raise P1ValidationResultError(
                "P1_VALIDATION_RESULT_SCHEMA_INVALID",
                "The manifest command specs are invalid.",
            ) from None
        if not hmac.compare_digest(
            str(contract.get("command_specs_sha256") or ""),
            fresh_specs_sha256,
        ):
            raise P1ValidationResultError(
                "P1_VALIDATION_COMMAND_SPECS_DIGEST_MISMATCH",
                "The manifest command-spec digest does not match.",
            )
        try:
            contract_payload = {
                key: value
                for key, value in contract.items()
                if key != "contract_sha256"
            }
            fresh_contract_sha256 = canonical_manifest_validation_sha256(
                contract_payload
            )
        except (TypeError, ValueError):
            raise P1ValidationResultError(
                "P1_VALIDATION_RESULT_SCHEMA_INVALID",
                "The manifest validation contract is invalid.",
            ) from None
        if not hmac.compare_digest(
            str(contract.get("contract_sha256") or ""),
            fresh_contract_sha256,
        ):
            raise P1ValidationResultError(
                "P1_VALIDATION_CONTRACT_DIGEST_MISMATCH",
                "The manifest validation contract digest does not match.",
            )
        if manifest_validation_contract_from_artifact(
            {"manifest_validation": contract}
        ) is None:
            raise P1ValidationResultError(
                "P1_VALIDATION_RESULT_SCHEMA_INVALID",
                "The manifest validation contract is structurally invalid.",
            )

        contract_head = (
            contract.get("review_context_binding", {}).get("head")
            if isinstance(contract.get("review_context_binding"), dict)
            else None
        )
        current_head = self._git_stdout(["rev-parse", "HEAD"]).strip().lower()
        normalized_candidate = (
            candidate_head.lower() if isinstance(candidate_head, str) else ""
        )
        if (
            contract_head != normalized_candidate
            or (require_current_head and current_head != normalized_candidate)
        ):
            raise P1ValidationResultError(
                "P1_VALIDATION_CANDIDATE_MISMATCH",
                "The validation contract candidate does not match the P1 candidate.",
            )

        self._verify_p1_checkout_provenance(
            data,
            normalized_candidate,
        )

        families = self._p1_command_families(command_specs)
        command_results = data.get("command_results")
        if (
            families != list(_P1_COMMAND_FAMILIES)
            or not isinstance(command_results, list)
            or len(command_results) != len(command_specs)
            or not isinstance(data.get("command_summary"), list)
            or len(data["command_summary"]) != len(command_specs)
            or data.get("command_count") != len(command_specs)
            or data.get("failed_command_indexes") != []
            or data.get("failed_command_index") is not None
        ):
            raise P1ValidationResultError(
                "P1_VALIDATION_COMMAND_COVERAGE_INCOMPLETE",
                "The validation result does not contain complete required command coverage.",
            )
        for index, (spec, command_result) in enumerate(
            zip(command_specs, command_results, strict=True)
        ):
            expected_command = self._display_command(spec["argv"])
            if (
                not isinstance(command_result, dict)
                or command_result.get("index") != index
                or command_result.get("ok") is not True
                or command_result.get("returncode") != 0
                or command_result.get("command") != expected_command
                or command_result.get("timeout_seconds")
                != spec["timeout_seconds"]
                or command_result.get("continue_on_failure")
                is not spec["continue_on_failure"]
                or data["command_summary"][index] != expected_command
            ):
                raise P1ValidationResultError(
                    "P1_VALIDATION_COMMAND_COVERAGE_INCOMPLETE",
                    "The validation command results are incomplete or out of order.",
                )

        completed_at = self._parse_result_time(data.get("completed_at"))
        observed_now = (
            now.astimezone(timezone.utc)
            if now.tzinfo is not None
            else now.replace(tzinfo=timezone.utc)
        )
        if completed_at is None:
            raise P1ValidationResultError(
                "P1_VALIDATION_RESULT_SCHEMA_INVALID",
                "The validation completion time is invalid.",
            )
        age_seconds = (observed_now - completed_at).total_seconds()
        if age_seconds < -300 or age_seconds > P1_VALIDATION_MAX_AGE_SECONDS:
            raise P1ValidationResultError(
                "P1_VALIDATION_RESULT_STALE",
                "The validation result is outside the P1 freshness window.",
            )

        actual_result_sha256 = str(data["validation_result_sha256"])
        if not hmac.compare_digest(
            actual_result_sha256,
            expected_validation_result_sha256,
        ):
            code = (
                "P1_VALIDATION_RESULT_CHANGED_AFTER_PREVIEW"
                if phase == "apply"
                else "P1_VALIDATION_RESULT_DIGEST_MISMATCH"
            )
            raise P1ValidationResultError(
                code,
                "The verified validation result differs from the bound expected digest.",
            )
        if not hmac.compare_digest(
            fresh_contract_sha256,
            expected_contract_sha256,
        ):
            raise P1ValidationResultError(
                "P1_VALIDATION_CONTRACT_DIGEST_MISMATCH",
                "The verified validation contract differs from the bound expected digest.",
            )
        actual_manifest_sha256 = str(contract["manifest_sha256"])
        if not hmac.compare_digest(
            actual_manifest_sha256,
            expected_manifest_sha256,
        ):
            raise P1ValidationResultError(
                "P1_VALIDATION_MANIFEST_DIGEST_MISMATCH",
                "The verified manifest differs from the bound expected digest.",
            )
        return {
            "run_id": normalized_run_id,
            "validation_result_sha256": actual_result_sha256,
            "contract_sha256": fresh_contract_sha256,
            "manifest_sha256": actual_manifest_sha256,
            "candidate_head": normalized_candidate,
            "observed_at": data["completed_at"],
            "source_kind": "server_verified_validation_run",
            "required_command_families": list(_P1_COMMAND_FAMILIES),
        }

    def _verify_p1_checkout_provenance(
        self,
        data: dict[str, Any],
        candidate_head: str,
    ) -> None:
        output_summary = data.get("output_summary")
        provenance = (
            output_summary.get("checkout_provenance")
            if isinstance(output_summary, dict)
            else None
        )
        if not isinstance(provenance, dict):
            raise P1ValidationResultError(
                "P1_VALIDATION_CHECKOUT_PROVENANCE_MISSING",
                "The validation result does not bind the checkout it executed.",
            )
        if set(provenance) != _CHECKOUT_PROVENANCE_FIELDS:
            raise P1ValidationResultError(
                "P1_VALIDATION_CHECKOUT_PROVENANCE_MISMATCH",
                "The validation checkout provenance has an invalid schema.",
            )
        source_before = provenance.get("source_before")
        source_after = provenance.get("source_after")
        try:
            git = _trusted_git_for_checkout(
                Path(self.project_root).resolve()
            )
            candidate_tree = git.run(
                Path(self.project_root).resolve(),
                "rev-parse",
                "--verify",
                f"{candidate_head}^{{tree}}",
            ).strip().lower()
        except Exception:
            raise P1ValidationResultError(
                "P1_VALIDATION_CHECKOUT_PROVENANCE_MISMATCH",
                "The validation candidate tree cannot be verified.",
            ) from None

        def valid_snapshot(value: Any) -> bool:
            if (
                not isinstance(value, dict)
                or set(value) != _CHECKOUT_SNAPSHOT_FIELDS
            ):
                return False
            tracked_path_count = value.get("tracked_path_count")
            violation_count = value.get("violation_count")
            return (
                value.get("head") == candidate_head
                and value.get("tree") == candidate_tree
                and value.get("candidate_clean") is True
                and value.get("git_object_format") in {"sha1", "sha256"}
                and isinstance(
                    value.get("git_object_manifest_sha256"),
                    str,
                )
                and _SHA256_RE.fullmatch(
                    value["git_object_manifest_sha256"]
                )
                is not None
                and isinstance(value.get("worktree_id_sha256"), str)
                and _SHA256_RE.fullmatch(value["worktree_id_sha256"])
                is not None
                and not isinstance(tracked_path_count, bool)
                and isinstance(tracked_path_count, int)
                and tracked_path_count >= 0
                and not isinstance(violation_count, bool)
                and violation_count == 0
            )

        if (
            provenance.get("mode") != _ISOLATED_CHECKOUT_MODE
            or provenance.get("candidate_head") != candidate_head
            or provenance.get("candidate_tree") != candidate_tree
            or not valid_snapshot(source_before)
            or not valid_snapshot(source_after)
            or source_before != source_after
            or provenance.get("source_binding_match") is not True
            or provenance.get("isolated_from_project_worktree") is not True
            or provenance.get("cleanup_complete") is not True
        ):
            raise P1ValidationResultError(
                "P1_VALIDATION_CHECKOUT_PROVENANCE_MISMATCH",
                "The validation result is not bound to one clean isolated candidate checkout.",
            )

    def _normalize_scope(self, value: Any) -> tuple[str, dict[str, Any] | None]:
        if value is None:
            return "changed_files", None
        if not isinstance(value, str) or not value.strip():
            return "changed_files", None
        scope = value.strip().lower()
        if scope not in VALID_SCOPES:
            return "", {
                "ok": False,
                "action": "preview",
                "error_code": "INVALID_SCOPE",
                "message": "scope 仅支持 changed_files、target_files、current_version、full。",
            }
        return scope, None

    def _normalize_target_files(self, value: Any) -> tuple[list[str], dict[str, Any] | None]:
        if value is None:
            return [], None
        if not isinstance(value, list):
            return [], {
                "ok": False,
                "action": "preview",
                "error_code": "INVALID_TARGET_FILES",
                "message": "target_files 必须是字符串数组。",
            }
        result: list[str] = []
        for item in value:
            if not isinstance(item, str) or not item.strip():
                return [], {
                    "ok": False,
                    "action": "preview",
                    "error_code": "INVALID_TARGET_FILE",
                    "message": "target_files 只能包含非空字符串。",
                }
            normalized = self._normalize_repo_relative_path(item)
            if normalized is None:
                return [], {
                    "ok": False,
                    "action": "preview",
                    "error_code": "TARGET_FILE_NOT_ALLOWED",
                    "message": "target_files 必须是项目内相对路径，且不能包含 ..。",
                }
            if self._path_policy.is_denied_source_path(normalized):
                return [], {
                    "ok": False,
                    "action": "preview",
                    "error_code": "TARGET_FILE_DENIED",
                    "message": f"target file 命中禁止路径：{normalized}",
                }
            if normalized not in result:
                result.append(normalized)
        if len(result) > MAX_TARGET_FILES:
            return [], {
                "ok": False,
                "action": "preview",
                "error_code": "TOO_MANY_TARGET_FILES",
                "message": f"target_files 最多 {MAX_TARGET_FILES} 个。",
            }
        return result, None

    def _normalize_repo_relative_path(self, value: str) -> str | None:
        normalized = value.strip().replace("\\", "/")
        while normalized.startswith("./"):
            normalized = normalized[2:]
        if not normalized:
            return None
        pure = PurePosixPath(normalized)
        if pure.is_absolute():
            return None
        if any(part in ("", ".", "..") for part in pure.parts):
            return None
        return str(pure)

    def _collect_changed_files(self) -> tuple[list[str], dict[str, Any] | None]:
        proc = subprocess.run(
            ["git", "status", "--short"],
            cwd=self.project_root,
            capture_output=True,
            text=True,
            check=False,
            shell=False,
        )
        if proc.returncode != 0:
            return [], {
                "ok": False,
                "action": "preview",
                "error_code": "GIT_STATUS_FAILED",
                "message": _redact_sensitive_text(proc.stderr)[:500],
            }
        files: list[str] = []
        for line in proc.stdout.splitlines():
            if not line.strip() or len(line) < 4:
                continue
            path_text = line[3:].strip()
            if " -> " in path_text:
                path_text = path_text.split(" -> ", 1)[1].strip()
            normalized = self._normalize_repo_relative_path(path_text)
            if normalized and not self._path_policy.is_denied_source_path(normalized) and normalized not in files:
                files.append(normalized)
        return files[:MAX_TARGET_FILES], None

    def _select_commands(self, scope: str, target_files: list[str]) -> tuple[list[list[str]], list[dict[str, Any]], str, list[str], list[dict[str, Any]]]:
        warnings: list[str] = []
        commands: list[list[str]] = []
        command_specs: list[dict[str, Any]] = []
        validation_groups: list[dict[str, Any]] = []

        if scope == "current_version":
            acceptance, acceptance_warnings = self._current_acceptance_commands()
            warnings.extend(acceptance_warnings)
            if acceptance:
                command_specs.extend(acceptance[:MAX_COMMANDS])
                commands.extend([item["argv"] for item in command_specs])
                validation_groups.append({"strategy": "plan_acceptance", "files": [], "command_count": len(command_specs)})
                return commands, command_specs, "plan_acceptance", warnings, validation_groups
            warnings.append("当前版本没有可用 acceptance_commands。")
            return [], [], "unsupported_strategy", warnings, validation_groups

        if scope == "full":
            acceptance, acceptance_warnings = self._current_acceptance_commands()
            warnings.extend(acceptance_warnings)
            if acceptance:
                for spec in acceptance[:MAX_COMMANDS]:
                    command_specs.append(spec)
                    commands.append(spec["argv"])
                validation_groups.append({"strategy": "plan_acceptance", "files": [], "command_count": len(acceptance)})

            full_strategies = self._full_validation_strategies()
            for strategy in full_strategies:
                argv = strategy["argv"]
                spec = {"argv": argv, "timeout_seconds": DEFAULT_TIMEOUT_SECONDS, "continue_on_failure": True}
                command_specs.append(spec)
                commands.append(argv)
                validation_groups.append({"strategy": strategy["strategy"], "files": [], "command_count": 1})

            if len(full_strategies) > 1:
                git_check = ["git", "diff", "--check"]
                spec = {"argv": git_check, "timeout_seconds": DEFAULT_TIMEOUT_SECONDS, "continue_on_failure": True}
                command_specs.append(spec)
                commands.append(git_check)
                validation_groups.append({"strategy": "git_diff_check", "files": [], "command_count": 1})

            if not full_strategies:
                if acceptance:
                    warnings.append("full scope 不能仅依赖 plan acceptance_commands；未检测到 project-level 验证策略。")
                elif not acceptance_warnings:
                    warnings.append("未检测到受支持的 project 类型，无法确定 full 验证策略。")
                return [], [], "unsupported_strategy", warnings, []

            strategy_names = [g["strategy"] for g in validation_groups]
            overall_strategy = "+".join(strategy_names)

            return commands[:MAX_COMMANDS], command_specs[:MAX_COMMANDS], overall_strategy, warnings, validation_groups

        file_set = set(target_files)
        py_files = sorted([path for path in file_set if path.endswith(".py")])
        test_files = sorted([path for path in py_files if path.startswith("tests/test_")])
        detected = self._detect_project_types()
        if test_files:
            command = [self._python_executable(), "-m", "pytest", *test_files[:20], "-q"]
            commands.append(command)
            command_specs.extend(self._command_specs_for_commands([command]))
            validation_groups.append({"strategy": "python_targeted", "files": test_files[:20], "command_count": 1})
            strategy = "python_targeted"
        elif any(kind in detected for kind in ("node", "php", "go", "rust")):
            acceptance, acceptance_warnings = self._current_acceptance_commands()
            warnings.extend(acceptance_warnings)
            if acceptance:
                command_specs.extend(acceptance[:MAX_COMMANDS])
                commands.extend([item["argv"] for item in command_specs])
                validation_groups.append({"strategy": "plan_acceptance", "files": target_files, "command_count": len(command_specs)})
                strategy = "plan_acceptance"
            else:
                warnings.append("检测到非 Python 项目线索；请将验证命令写入 acceptance_commands。")
                strategy = "unsupported_strategy"
        else:
            strategy = "quick_static"

        commands.append(["git", "diff", "--check"])
        command_specs.extend(self._command_specs_for_commands([["git", "diff", "--check"]]))
        validation_groups.append({"strategy": "quick_static", "files": [], "command_count": 1})
        if not target_files and scope == "changed_files":
            warnings.append("没有检测到 changed files，执行通用 diff 检查。")
        return commands[:MAX_COMMANDS], command_specs[:MAX_COMMANDS], strategy, warnings, validation_groups

    def _current_acceptance_commands(self) -> tuple[list[dict[str, Any]], list[str]]:
        warnings: list[str] = []
        version = load_current_version(self.project_root)
        if not version:
            return [], ["未找到 current_version，无法读取 acceptance_commands。"]
        plan_file = resolve_project_runner_path(self.project_root, "plan.json")
        try:
            plan = PlanLoader().load_plan(plan_file)
        except Exception as exc:
            return [], [f"plan 加载失败：{_redact_sensitive_text(str(exc))[:200]}"]
        selected = next((item for item in plan.versions if item.version == version), None)
        if selected is None:
            return [], [f"current_version {version} 不在 plan 中。"]
        result: list[dict[str, Any]] = []
        for index, command in enumerate(selected.acceptance_commands):
            raw_command = str(getattr(command, "command", "") or "").strip()
            if not raw_command:
                continue
            argv, error = self._parse_command_string(raw_command)
            if error:
                warnings.append(f"acceptance command #{index + 1} 不安全：{error}")
                continue
            result.append({
                "argv": argv,
                "timeout_seconds": self._normalize_timeout_seconds(getattr(command, "timeout_seconds", DEFAULT_TIMEOUT_SECONDS)),
                "continue_on_failure": bool(getattr(command, "continue_on_failure", False)),
            })
        return result, warnings

    def _manifest_bound_command_specs(
        self,
        acceptance_commands: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Convert manifest declarations into exact, safe executable argv specs."""

        command_specs: list[dict[str, Any]] = []
        rejections: list[dict[str, Any]] = []
        for index, item in enumerate(acceptance_commands, start=1):
            if not isinstance(item, dict):
                rejections.append({"command_index": index, "reason": "invalid_declaration"})
                continue
            raw_command = item.get("command")
            if not isinstance(raw_command, str) or not raw_command.strip():
                rejections.append({"command_index": index, "reason": "invalid_declaration"})
                continue
            # A command that visibly embeds a known secret-shaped value is not
            # eligible for a public preview, even if its executable is otherwise
            # permitted. Do not echo the command text in the rejection.
            if _redact_sensitive_text(raw_command) != raw_command:
                rejections.append({"command_index": index, "reason": "sensitive_value"})
                continue
            argv, parse_error = self._parse_command_string(raw_command)
            if parse_error:
                rejections.append({"command_index": index, "reason": "command_not_allowed"})
                continue
            timeout_seconds = item.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
            if (
                isinstance(timeout_seconds, bool)
                or not isinstance(timeout_seconds, int)
                or not MIN_TIMEOUT_SECONDS <= timeout_seconds <= MAX_TIMEOUT_SECONDS
            ):
                rejections.append({"command_index": index, "reason": "timeout_not_allowed"})
                continue
            continue_on_failure = item.get("continue_on_failure", False)
            if not isinstance(continue_on_failure, bool):
                rejections.append({"command_index": index, "reason": "invalid_declaration"})
                continue
            command_specs.append(
                {
                    "argv": argv,
                    "timeout_seconds": timeout_seconds,
                    "continue_on_failure": continue_on_failure,
                }
            )
        return command_specs, rejections

    def _command_specs_for_commands(self, commands: list[list[str]]) -> list[dict[str, Any]]:
        return [
            {
                "argv": command,
                "timeout_seconds": DEFAULT_TIMEOUT_SECONDS,
                "continue_on_failure": False,
            }
            for command in commands
        ]

    def _normalize_timeout_seconds(self, value: Any) -> int:
        try:
            parsed = int(value)
        except Exception:
            parsed = DEFAULT_TIMEOUT_SECONDS
        return max(MIN_TIMEOUT_SECONDS, min(MAX_TIMEOUT_SECONDS, parsed))

    def _parse_command_string(self, command: str) -> tuple[list[str], str | None]:
        if any(pattern in command for pattern in SHELL_META_PATTERNS):
            return [], "包含 shell meta 字符"
        try:
            argv = shlex.split(command)
        except ValueError as exc:
            return [], str(exc)
        if not argv:
            return [], "空命令"
        if not self._is_safe_command(argv):
            return [], "命令不在安全白名单内"
        return argv, None

    def _detect_project_types(self) -> list[str]:
        checks = {
            "node": "package.json",
            "php": "composer.json",
            "go": "go.mod",
            "rust": "Cargo.toml",
            "python": "pyproject.toml",
        }
        result = [name for name, rel in checks.items() if os.path.exists(os.path.join(self.project_root, rel))]
        if os.path.isdir(os.path.join(self.project_root, "tests")) and "python" not in result:
            result.append("python")
        return sorted(result)

    def _is_python_project(self) -> bool:
        return "python" in self._detect_project_types() or os.path.isdir(os.path.join(self.project_root, "tests"))

    def _full_validation_strategies(self) -> list[dict[str, Any]]:
        strategies: list[dict[str, Any]] = []
        detected = self._detect_project_types()

        if "python" in detected:
            strategies.append({
                "strategy": "python_full",
                "argv": [self._python_executable(), "-m", "pytest", "tests", "-q"],
            })

        if "node" in detected:
            pkg_path = os.path.join(self.project_root, "package.json")
            if os.path.isfile(pkg_path):
                try:
                    with open(pkg_path, encoding="utf-8") as f:
                        pkg = json.load(f)
                    if isinstance(pkg, dict) and "scripts" in pkg and "test" in pkg["scripts"]:
                        strategies.append({
                            "strategy": "node_full",
                            "argv": ["npm", "test"],
                        })
                except Exception:
                    pass

        if "php" in detected:
            phpunit_path = os.path.join(self.project_root, "vendor", "bin", "phpunit")
            if os.path.isfile(phpunit_path) and os.access(phpunit_path, os.X_OK):
                strategies.append({
                    "strategy": "php_full",
                    "argv": ["vendor/bin/phpunit"],
                })
            else:
                strategies.append({
                    "strategy": "php_full",
                    "argv": ["phpunit"],
                })

        if "go" in detected:
            strategies.append({
                "strategy": "go_full",
                "argv": ["go", "test", "./..."],
            })

        if "rust" in detected:
            strategies.append({
                "strategy": "rust_full",
                "argv": ["cargo", "test"],
            })

        return strategies

    def _python_executable(self) -> str:
        venv_python = os.path.join(self.project_root, ".venv", "bin", "python")
        if os.path.isfile(venv_python) and os.access(venv_python, os.X_OK):
            return venv_python
        return "python3"

    def _is_safe_command(self, command: Any) -> bool:
        if not isinstance(command, list) or not command:
            return False
        if len(command) > 30:
            return False
        if not all(isinstance(part, str) and part for part in command):
            return False
        if any(any(pattern in part for pattern in SHELL_META_PATTERNS) for part in command):
            return False
        first = command[0]
        executable_name = os.path.basename(first)
        if executable_name in DANGEROUS_EXECUTABLES:
            return False
        if executable_name == "git":
            return command == ["git", "diff", "--check"]
        if os.path.isabs(first):
            # Allow the project virtualenv Python selected by Runner; do not allow arbitrary absolute executables.
            if first != self._python_executable():
                return False
        elif "/" in first:
            normalized = self._normalize_repo_relative_path(first)
            if normalized is None:
                return False
        if len(command) >= 3 and command[1:3] == ["-m", "pytest"]:
            return all(self._normalize_repo_relative_path(part) is not None for part in command[3:] if not part.startswith("-"))
        if command[:3] == [first, "-m", "compileall"]:
            args = command[3:]
            while args and args[0] == "-q":
                args = args[1:]
            if not args:
                return False
            for part in args:
                normalized = self._normalize_repo_relative_path(part)
                if normalized is None or self._path_policy.is_denied_source_path(normalized):
                    return False
            return True
        return True

    def _manifest_candidate_head(
        self,
        artifact: dict[str, Any],
    ) -> str | None:
        contract = artifact.get("manifest_validation")
        binding = (
            contract.get("review_context_binding")
            if isinstance(contract, dict)
            else None
        )
        head = binding.get("head") if isinstance(binding, dict) else None
        if not isinstance(head, str):
            return None
        normalized = head.strip().lower()
        return (
            normalized
            if _FULL_GIT_OBJECT_ID_RE.fullmatch(normalized)
            else None
        )

    @staticmethod
    def _worktree_id_sha256(path: Path) -> str:
        return hashlib.sha256(
            path.resolve().as_posix().encode("utf-8")
        ).hexdigest()

    def _capture_checkout_snapshot(
        self,
        checkout: Path,
    ) -> dict[str, Any]:
        requested = checkout.resolve()
        git = _trusted_git_for_checkout(requested)
        exact = _inspect_git_checkout(
            requested,
            git=git,
            pathspecs=(),
        )
        tracked = [
            item
            for item in git.run(
                requested,
                "diff",
                "--name-only",
                "-z",
            ).split("\0")
            if item
        ]
        staged = [
            item
            for item in git.run(
                requested,
                "diff",
                "--cached",
                "--name-only",
                "-z",
            ).split("\0")
            if item
        ]
        untracked = [
            item
            for item in git.run(
                requested,
                "ls-files",
                "--others",
                "--exclude-standard",
                "-z",
            ).split("\0")
            if item
        ]
        exact_violation_count = sum(
            len(exact.get(key, []))
            for key in (
                "object_mismatches",
                "assume_unchanged_paths",
                "skip_worktree_paths",
                "ignored_execution_overlays",
                "untracked_execution_overlays",
            )
        )
        violation_count = (
            len(tracked)
            + len(staged)
            + len(untracked)
            + exact_violation_count
        )
        return {
            "head": git.run(
                requested,
                "rev-parse",
                "--verify",
                "HEAD",
            ).strip().lower(),
            "tree": git.run(
                requested,
                "rev-parse",
                "--verify",
                "HEAD^{tree}",
            ).strip().lower(),
            "candidate_clean": violation_count == 0,
            "git_object_format": exact.get("object_format"),
            "git_object_manifest_sha256": exact.get("manifest_digest"),
            "tracked_path_count": exact.get("tracked_path_count"),
            "worktree_id_sha256": self._worktree_id_sha256(requested),
            "violation_count": violation_count,
        }

    def _prepare_isolated_checkout(
        self,
        candidate_head: str,
        run_id: str,
    ) -> dict[str, Any]:
        project_root = Path(self.project_root).resolve()
        git = _trusted_git_for_checkout(project_root)
        candidate_tree = git.run(
            project_root,
            "rev-parse",
            "--verify",
            f"{candidate_head}^{{tree}}",
        ).strip().lower()
        parent = Path(
            tempfile.mkdtemp(
                prefix=f"colameta-validation-{run_id[-8:]}-",
            )
        )
        checkout = parent / "checkout"
        added = False
        try:
            git.run(
                project_root,
                "worktree",
                "add",
                "--detach",
                checkout.as_posix(),
                candidate_head,
            )
            added = True
            source_before = self._capture_checkout_snapshot(checkout)
            isolated = (
                source_before["worktree_id_sha256"]
                != self._worktree_id_sha256(project_root)
            )
            if (
                source_before.get("head") != candidate_head
                or source_before.get("tree") != candidate_tree
                or source_before.get("candidate_clean") is not True
                or not isolated
            ):
                raise RuntimeError(
                    "isolated validation checkout did not match candidate"
                )
            project_venv = project_root / ".venv"
            checkout_venv = checkout / ".venv"
            if project_venv.is_dir():
                checkout_venv.symlink_to(
                    project_venv,
                    target_is_directory=True,
                )
            return {
                "root": checkout,
                "parent": parent,
                "git": git,
                "checkout_venv": checkout_venv,
                "candidate_head": candidate_head,
                "candidate_tree": candidate_tree,
                "source_before": source_before,
                "isolated_from_project_worktree": isolated,
            }
        except Exception as exc:
            if added:
                try:
                    git.run(
                        project_root,
                        "worktree",
                        "remove",
                        "--force",
                        checkout.as_posix(),
                    )
                except Exception:
                    pass
            shutil.rmtree(parent, ignore_errors=True)
            raise RuntimeError(
                "isolated validation checkout preparation failed"
            ) from exc

    def _remove_isolated_execution_overlays(
        self,
        isolated_checkout: dict[str, Any],
    ) -> None:
        checkout = isolated_checkout.get("root")
        checkout_venv = isolated_checkout.get("checkout_venv")
        git = isolated_checkout.get("git")
        if (
            not isinstance(checkout, Path)
            or not isinstance(checkout_venv, Path)
            or git is None
        ):
            raise RuntimeError(
                "isolated validation overlay cleanup is unavailable"
            )
        if checkout_venv.is_symlink():
            checkout_venv.unlink()
        elif checkout_venv.exists():
            raise RuntimeError(
                "isolated validation virtualenv overlay was rebound"
            )
        git.run(
            checkout,
            "clean",
            "-fdX",
        )

    def _cleanup_isolated_checkout(
        self,
        isolated_checkout: dict[str, Any],
    ) -> bool:
        project_root = Path(self.project_root).resolve()
        checkout = isolated_checkout.get("root")
        parent = isolated_checkout.get("parent")
        git = isolated_checkout.get("git")
        if (
            not isinstance(checkout, Path)
            or not isinstance(parent, Path)
            or git is None
        ):
            return False
        try:
            git.run(
                project_root,
                "worktree",
                "remove",
                "--force",
                checkout.as_posix(),
            )
        except Exception:
            return False
        shutil.rmtree(parent, ignore_errors=True)
        return not checkout.exists()

    def _run_command(
        self,
        command: list[str],
        *,
        timeout_seconds: int,
        cwd: str | None = None,
    ) -> dict[str, Any]:
        execution_root = os.path.abspath(cwd or self.project_root)
        effective_command = list(command)
        if effective_command[0] == ".venv/bin/python":
            effective_command[0] = self._python_executable()
        environment = dict(os.environ)
        for key in list(environment):
            if key.startswith("GIT_") or key in {
                "PYTHONHOME",
                "PYTHONSTARTUP",
                "PYTHONUSERBASE",
            }:
                environment.pop(key, None)
        if os.path.realpath(execution_root) != os.path.realpath(
            self.project_root
        ):
            environment["PYTHONPATH"] = execution_root
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
        try:
            proc = subprocess.run(
                effective_command,
                cwd=execution_root,
                capture_output=True,
                text=True,
                check=False,
                shell=False,
                timeout=timeout_seconds,
                env=environment,
            )
            return {
                "returncode": proc.returncode,
                "stdout": _redact_sensitive_text(proc.stdout),
                "stderr": _redact_sensitive_text(proc.stderr),
                "error_code": None,
            }
        except subprocess.TimeoutExpired as exc:
            return {
                "returncode": 124,
                "stdout": _redact_sensitive_text(exc.stdout or ""),
                "stderr": f"VALIDATION_RUN_TIMEOUT: command exceeded {timeout_seconds}s",
                "error_code": "VALIDATION_RUN_TIMEOUT",
            }
        except Exception as exc:
            return {
                "returncode": 125,
                "stdout": "",
                "stderr": f"VALIDATION_RUN_FAILED: {_redact_sensitive_text(str(exc))}",
                "error_code": "VALIDATION_RUN_FAILED",
            }

    def _git_stdout(self, args: list[str]) -> str:
        proc = subprocess.run(
            ["git", *args],
            cwd=self.project_root,
            capture_output=True,
            text=True,
            check=False,
            shell=False,
        )
        return proc.stdout if proc.returncode == 0 else ""

    def _command_summary(self, commands: list[list[str]]) -> list[str]:
        return [self._display_command(command) for command in commands]

    def _display_command(self, command: Any) -> str:
        if not isinstance(command, list):
            return ""
        return " ".join(str(part) for part in command)

    def _preview_path(self, preview_id: str) -> str:
        return os.path.join(self._previews_root, f"{preview_id}.json")

    def _write_preview(self, preview_id: str, artifact: dict[str, Any]) -> None:
        os.makedirs(self._previews_root, exist_ok=True)
        with open(self._preview_path(preview_id), "w", encoding="utf-8") as f:
            json.dump(artifact, f, ensure_ascii=False, indent=2)
            f.write("\n")

    def _read_preview(self, preview_id: str) -> dict[str, Any] | None:
        path = self._preview_path(preview_id)
        if not os.path.isfile(path):
            return None
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    def read(self, preview_id: str) -> dict[str, Any] | None:
        """Duck-typed read for confirmation_apply_guard."""
        return self._read_preview(preview_id)

    def is_expired(self, payload: dict[str, Any]) -> bool:
        """Duck-typed is_expired for confirmation_apply_guard."""
        return self._is_expired(str(payload.get("expires_at", "") or ""))

    def _validate_run_id(self, value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        stripped = value.strip()
        if not 8 <= len(stripped) <= 80:
            return None
        if not re.fullmatch(r"[A-Za-z0-9_-]+", stripped):
            return None
        return stripped

    def _run_result_path(self, run_id: str) -> str:
        return os.path.join(self._runs_root, f"{run_id}.json")

    def _write_terminal_run_result(
        self,
        run_id: str,
        result: dict[str, Any],
    ) -> str:
        terminal = dict(result)
        terminal["schema_version"] = VALIDATION_RUN_RESULT_SCHEMA_VERSION
        terminal["validation_result_sha256"] = canonical_validation_result_sha256(
            terminal
        )
        return self._write_run_result(run_id, terminal)

    def _write_run_result(self, run_id: str, result: dict[str, Any]) -> str:
        os.makedirs(self._runs_root, exist_ok=True)
        path = self._run_result_path(run_id)
        tmp_path = f"{path}.{uuid.uuid4().hex[:8]}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp_path, path)
        return os.path.relpath(path, self.project_root)

    def _read_verified_run_result(
        self,
        run_id: str,
        *,
        validate_manifest_contract: bool = True,
    ) -> tuple[dict[str, Any] | None, str | None]:
        path = self._run_result_path(run_id)
        runs_root = os.path.realpath(self._runs_root)
        candidate = os.path.realpath(path)
        try:
            within_store = os.path.commonpath([candidate, runs_root]) == runs_root
        except ValueError:
            within_store = False
        if (
            not within_store
            or os.path.islink(path)
            or not os.path.exists(path)
        ):
            return None, "RUN_NOT_FOUND"
        if not os.path.isfile(path):
            return None, "RUN_RESULT_INVALID"
        try:
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None, "RUN_RESULT_INVALID"
        if not isinstance(data, dict):
            return None, "RUN_RESULT_INVALID"
        persisted_run_id = data.get("run_id")
        persisted_preview_id = data.get("preview_id")
        normalized_preview_id = _validate_preview_id(persisted_preview_id)
        if (
            persisted_run_id != run_id
            or self._validate_run_id(persisted_run_id) != run_id
            or normalized_preview_id is None
            or normalized_preview_id != persisted_preview_id
            or data.get("action") != "run"
        ):
            return None, "RUN_RESULT_INVALID"

        status = data.get("status")
        if status == "running":
            if (
                set(data) != _RUN_RESULT_FIELDS
                or data.get("schema_version")
                != VALIDATION_RUN_RESULT_SCHEMA_VERSION
                or "validation_result_sha256" in data
                or data.get("passed") is not None
                or data.get("completed_at") is not None
                or data.get("duration_seconds") is not None
            ):
                return None, "RUN_RESULT_INVALID"
            manifest_validation = data.get("manifest_validation")
            if (
                validate_manifest_contract
                and
                manifest_validation is not None
                and manifest_validation_contract_from_artifact(
                    {"manifest_validation": manifest_validation}
                )
                is None
            ):
                return None, "RUN_RESULT_INVALID"
            return data, None

        if status not in {"passed", "failed"}:
            return None, "RUN_RESULT_INVALID"
        digest = data.get("validation_result_sha256")
        if digest is None:
            actual_fields = set(data)
            if (
                "schema_version" not in data
                and _LEGACY_TERMINAL_REQUIRED_FIELDS <= actual_fields
                and not (
                    actual_fields
                    - _LEGACY_TERMINAL_REQUIRED_FIELDS
                    - _LEGACY_TERMINAL_OPTIONAL_FIELDS
                )
                and data.get("action") == "run"
                and data.get("passed") is (status == "passed")
                and isinstance(data.get("completed_at"), str)
            ):
                return None, "RUN_RESULT_UNVERIFIED_LEGACY"
            return None, "RUN_RESULT_INVALID"
        if (
            set(data) != _TERMINAL_RUN_RESULT_FIELDS
            or data.get("schema_version") != VALIDATION_RUN_RESULT_SCHEMA_VERSION
            or not isinstance(digest, str)
            or _SHA256_RE.fullmatch(digest) is None
            or data.get("passed") is not (status == "passed")
            or not isinstance(data.get("completed_at"), str)
            or isinstance(data.get("duration_seconds"), bool)
            or not isinstance(data.get("duration_seconds"), (int, float))
        ):
            return None, "RUN_RESULT_INVALID"
        try:
            expected = canonical_validation_result_sha256(data)
        except (TypeError, ValueError):
            return None, "RUN_RESULT_INVALID"
        if not hmac.compare_digest(digest, expected):
            return None, "RUN_RESULT_DIGEST_MISMATCH"
        manifest_validation = data.get("manifest_validation")
        if (
            validate_manifest_contract
            and
            manifest_validation is not None
            and manifest_validation_contract_from_artifact(
                {"manifest_validation": manifest_validation}
            )
            is None
        ):
            return None, "RUN_RESULT_INVALID"
        return data, None

    @staticmethod
    def _parse_result_time(value: Any) -> datetime | None:
        if not isinstance(value, str) or not value or len(value) > 64:
            return None
        try:
            parsed = datetime.fromisoformat(
                value[:-1] + "+00:00" if value.endswith("Z") else value
            )
        except ValueError:
            return None
        return (
            parsed.replace(tzinfo=timezone.utc)
            if parsed.tzinfo is None
            else parsed.astimezone(timezone.utc)
        )

    @staticmethod
    def _p1_command_families(command_specs: Any) -> list[str]:
        if (
            not isinstance(command_specs, list)
            or len(command_specs) != len(_P1_COMMAND_CONTRACT)
        ):
            return []
        families: list[str] = []
        for spec, (
            family,
            expected_argv,
            expected_timeout,
        ) in zip(command_specs, _P1_COMMAND_CONTRACT, strict=True):
            if not isinstance(spec, dict):
                return []
            if (
                set(spec)
                != {"argv", "timeout_seconds", "continue_on_failure"}
                or spec.get("argv") != list(expected_argv)
                or spec.get("timeout_seconds") != expected_timeout
                or spec.get("continue_on_failure") is not False
            ):
                return []
            families.append(family)
        return families

    def _is_expired(self, expires_at: str) -> bool:
        if not expires_at:
            return False
        try:
            normalized = expires_at.replace("Z", "+00:00")
            return _utc_now() > datetime.fromisoformat(normalized)
        except Exception:
            return False
