import hashlib
import hmac
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import tempfile
import threading
import uuid
from contextvars import ContextVar
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
from runner.toolchain_environment import (
    ValidationEnvironment,
    ValidationEnvironmentError,
    build_validation_subprocess_environment,
    command_uses_python,
    materialize_frozen_toolchain_environment,
    materialize_trusted_source_venv,
    prepare_validation_environment,
    rewrite_command_for_validation_environment,
    verify_bound_wheel_asset,
    venv_bin_dir,
    venv_python,
)
from runner.work_item_governance.source_binding import (
    _inspect_git_checkout,
    _trusted_git_for_checkout,
)
from runner.work_item_governance.toolchain_binding import (
    load_verified_frozen_toolchain_record,
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
MANIFEST_PYTHON_EXECUTABLES = {
    "python",
    "python3",
    ".venv/bin/python",
}

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
        "candidate_identity",
        "validation_selection",
        "validation_lanes",
        "aggregate",
    }
)
_TERMINAL_RUN_RESULT_FIELDS = _RUN_RESULT_FIELDS | {"validation_result_sha256"}
_LEGACY_TERMINAL_FIELDS = (
    _TERMINAL_RUN_RESULT_FIELDS
    - {
        "candidate_identity",
        "validation_selection",
        "validation_lanes",
        "aggregate",
    }
)
_LEGACY_RUNNING_FIELDS = _RUN_RESULT_FIELDS - {
    "candidate_identity",
    "validation_selection",
    "validation_lanes",
    "aggregate",
}
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
    {
        "command_summary",
        "command_count",
        "manifest_validation",
        "candidate_identity",
        "validation_selection",
        "validation_lanes",
        "aggregate",
    }
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
_CANDIDATE_LANE = "candidate"
_HOST_FROZEN_LANE = "host_frozen"
_VALIDATION_LANES = {_CANDIDATE_LANE, _HOST_FROZEN_LANE}
_HOST_FROZEN_MARKER = "host_frozen_toolchain"
_CANDIDATE_MARKER_EXPRESSION = f"not {_HOST_FROZEN_MARKER}"
_HOST_MARKER_EXPRESSION = _HOST_FROZEN_MARKER
_HOST_FROZEN_TEST_FILE = "tests/test_work_item_r3_closeout_runner.py"
_FROZEN_CRYPTOGRAPHY_WHEEL_ENV = "COLAMETA_FROZEN_CRYPTOGRAPHY_WHEEL"
_FROZEN_TOOLCHAIN_ASSET_DIR_ENV = "COLAMETA_FROZEN_TOOLCHAIN_ASSET_DIR"
_TRUSTED_LAUNCHER_BINDING_ENV = "COLAMETA_TRUSTED_LAUNCHER_BINDING_FILE"
_TRUSTED_LAUNCHER_BINDING_FILENAME = "trusted-launcher-binding.json"
_TRUSTED_LAUNCHER_RELATIVE_PATH = "scripts/work_item_r3_trusted_launcher.py"
_HOST_FROZEN_TRIGGER_PATHS = frozenset(
    {
        "runner/mcp_validation_run.py",
        "runner/toolchain_environment.py",
        "runner/work_item_governance/toolchain_binding.py",
        "scripts/work_item_r3_closeout.py",
        "scripts/work_item_r3_trusted_launcher.py",
        _HOST_FROZEN_TEST_FILE,
    }
)

# This is an execution skip policy, not a lane classification list.  The
# exact skip is an existing dirty-checkout protection in the ordinary
# candidate suite.  Any other candidate skip is unexpected and fails closed.
_ALLOWED_CANDIDATE_SKIP_SIGNATURES = frozenset(
    {
        "tests/test_work_item_r3_closeout.py:546: positive exact-attestation assertion requires the committed candidate",
    }
)
_VALIDATION_ENVIRONMENT_CONTEXT: ContextVar[ValidationEnvironment | None] = ContextVar(
    "colameta_validation_environment",
    default=None,
)
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

        (
            candidate_source_bindings,
            candidate_delta_paths,
            candidate_delta_error,
        ) = self._build_full_worktree_candidate_bindings()
        if candidate_delta_error is not None:
            return candidate_delta_error
        if scope == "changed_files":
            resolved_files = candidate_delta_paths[:MAX_TARGET_FILES]

        (
            commands,
            command_specs,
            strategy,
            warnings,
            validation_groups,
            lane_assignments,
        ) = self._select_commands(scope, resolved_files)
        blockers: list[str] = []
        if not commands:
            blockers.append("NO_VALIDATION_COMMANDS")

        now = _utc_now()
        preview_id = uuid.uuid4().hex[:12]
        current_head = self._git_stdout(["rev-parse", "HEAD"]).strip()
        candidate_identity = self._candidate_identity(
            current_head,
            candidate_source_bindings,
            binding_scope="full_allowed_worktree_delta",
        )
        validation_selection = self._validation_selection(
            scope,
            resolved_files,
            command_specs,
            lane_assignments=lane_assignments,
        )
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
            "candidate_source_bindings": candidate_source_bindings,
            "candidate_delta_mode": "full_allowed_worktree_delta",
            "candidate_identity": candidate_identity,
            "validation_selection": validation_selection,
            "validation_lanes": lane_assignments,
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
            "candidate_identity": candidate_identity,
            "validation_selection": validation_selection,
            "validation_lanes": lane_assignments,
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
        current_head = self._git_stdout(["rev-parse", "HEAD"]).strip()
        candidate_source_bindings = self._manifest_source_bindings(
            manifest_validation
        )
        candidate_identity = self._candidate_identity(
            current_head,
            candidate_source_bindings,
            binding_scope="manifest_subjects",
        )
        validation_selection = self._validation_selection(
            "manifest_bound",
            target_files,
            command_specs,
            lane_assignments=[_CANDIDATE_LANE] * len(command_specs),
        )
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
            "candidate_source_bindings": candidate_source_bindings,
            "candidate_delta_mode": "manifest_subjects",
            "candidate_identity": candidate_identity,
            "validation_selection": validation_selection,
            "validation_lanes": [_CANDIDATE_LANE] * len(command_specs),
            "current_head": current_head,
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
            "candidate_identity": candidate_identity,
            "validation_selection": validation_selection,
            "validation_lanes": [_CANDIDATE_LANE] * len(command_specs),
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
        lane_assignments = artifact.get("validation_lanes")
        if lane_assignments is None:
            lane_assignments = [_CANDIDATE_LANE] * len(command_specs)
        if (
            not isinstance(lane_assignments, list)
            or len(lane_assignments) != len(command_specs)
            or any(lane not in _VALIDATION_LANES for lane in lane_assignments)
        ):
            return {
                "ok": False,
                "action": "run",
                "error_code": "VALIDATION_LANE_ASSIGNMENT_INVALID",
                "message": "preview 的验证通道绑定无效，拒绝启动。",
            }

        candidate_head = self._bound_candidate_head(artifact)
        if candidate_head is not None:
            current_head = self._git_stdout(["rev-parse", "HEAD"]).strip().lower()
            if current_head != candidate_head:
                return {
                    "ok": False,
                    "action": "run",
                    "error_code": "VALIDATION_CANDIDATE_HEAD_MISMATCH",
                    "message": "preview 绑定的候选 HEAD 已发生变化，请重新生成 validation preview。",
                }

        if not self._verify_candidate_source_bindings(artifact):
            delta_incomplete = (
                artifact.get("candidate_delta_mode")
                == "full_allowed_worktree_delta"
            )
            return {
                "ok": False,
                "action": "run",
                "error_code": (
                    "VALIDATION_CANDIDATE_DELTA_INCOMPLETE"
                    if delta_incomplete
                    else "VALIDATION_SOURCE_BINDING_MISMATCH"
                ),
                "message": (
                    "preview 绑定的完整候选工作树差异已发生变化，请重新生成 validation preview。"
                    if delta_incomplete
                    else "preview 绑定的候选文件已发生变化，请重新生成 validation preview。"
                ),
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
            "candidate_identity": artifact.get("candidate_identity"),
            "validation_selection": artifact.get("validation_selection"),
            "validation_lanes": list(lane_assignments),
            "run_file": run_file,
            "message": "验证已启动，请用 status 轮询结果。",
        }
        manifest_validation = artifact.get("manifest_validation")
        if isinstance(manifest_validation, dict):
            result["manifest_validation"] = dict(manifest_validation)
        return result

    def _resolve_frozen_toolchain_asset(self) -> dict[str, Any]:
        """Resolve and verify the locally bound cryptography wheel asset."""

        try:
            record = load_verified_frozen_toolchain_record()
        except Exception as exc:
            return {
                "ok": False,
                "error_code": getattr(exc, "code", "FROZEN_TOOLCHAIN_RECORD_INVALID"),
            }
        assets = record.get("required_assets")
        cryptography = assets.get("cryptography") if isinstance(assets, dict) else None
        if not isinstance(cryptography, dict):
            return {
                "ok": False,
                "error_code": "FROZEN_TOOLCHAIN_ASSET_BINDING_INVALID",
            }
        filename = cryptography.get("filename")
        expected_sha256 = cryptography.get("sha256")
        distribution = cryptography.get("distribution", "cryptography")
        version = cryptography.get("version")
        if not all(
            isinstance(value, str) and value.strip()
            for value in (filename, expected_sha256, distribution, version)
        ):
            return {
                "ok": False,
                "error_code": "FROZEN_TOOLCHAIN_ASSET_BINDING_INVALID",
            }
        candidates: list[Path] = []
        explicit = os.environ.get(_FROZEN_CRYPTOGRAPHY_WHEEL_ENV)
        if explicit:
            candidates.append(Path(explicit).expanduser())
        asset_dir = os.environ.get(_FROZEN_TOOLCHAIN_ASSET_DIR_ENV)
        if asset_dir:
            candidates.append(Path(asset_dir).expanduser() / filename)
        for candidate in candidates:
            try:
                verified = verify_bound_wheel_asset(
                    candidate,
                    expected_filename=filename,
                    expected_sha256=expected_sha256,
                )
            except Exception:
                continue
            return {
                "ok": True,
                "path": Path(candidate).resolve(),
                "filename": filename,
                "sha256": expected_sha256,
                "distribution": distribution,
                "version": version,
                "asset": verified,
            }
        return {
            "ok": False,
            "error_code": "FROZEN_TOOLCHAIN_LOCAL_ASSETS_UNAVAILABLE",
        }

    def _write_trusted_launcher_binding_receipt(
        self,
        *,
        artifact: dict[str, Any],
        preview_id: str,
        candidate_root: Path,
        run_parent: Path,
        host_preflight: dict[str, Any],
    ) -> tuple[Path, dict[str, Any]]:
        """Create one temporary, hash-bound contract for the trusted launcher."""

        identity = artifact.get("candidate_identity")
        selection = artifact.get("validation_selection")
        bindings = self._source_bindings_for_artifact(artifact)
        if not isinstance(identity, dict) or not isinstance(selection, dict):
            raise ValidationEnvironmentError("trusted launcher candidate binding is unavailable")
        if identity.get("source_binding_scope") != "full_allowed_worktree_delta":
            raise ValidationEnvironmentError("trusted launcher requires a full candidate delta")
        binding_digest = canonical_manifest_validation_sha256(bindings)
        if (
            identity.get("source_binding_sha256") != binding_digest
            or identity.get("worktree_delta_sha256") != binding_digest
            or identity.get("source_binding_count") != len(bindings)
        ):
            raise ValidationEnvironmentError("trusted launcher candidate digest binding mismatch")
        launcher = candidate_root / _TRUSTED_LAUNCHER_RELATIVE_PATH
        if launcher.is_symlink() or not launcher.is_file():
            raise ValidationEnvironmentError("trusted launcher candidate bytes are unavailable")
        toolchain_project_root = host_preflight.get("toolchain_project_root")
        environment_root = host_preflight.get("environment_root")
        environment_root_sha256 = host_preflight.get("environment_root_sha256")
        frozen_record_sha256 = host_preflight.get("frozen_toolchain_record_sha256")
        cryptography_version = host_preflight.get("cryptography_version")
        if not all(
            isinstance(value, str) and value.strip()
            for value in (
                toolchain_project_root,
                environment_root,
                environment_root_sha256,
                frozen_record_sha256,
                cryptography_version,
            )
        ):
            raise ValidationEnvironmentError("trusted launcher toolchain binding is incomplete")
        if cryptography_version != "50.0.0":
            raise ValidationEnvironmentError("trusted launcher cryptography binding mismatch")
        receipt = {
            "schema_version": "colameta.trusted_launcher_binding.v1",
            "candidate": {
                "head": identity.get("head"),
                "root": candidate_root.resolve().as_posix(),
                "worktree_delta_sha256": identity["worktree_delta_sha256"],
                "source_binding_sha256": identity["source_binding_sha256"],
                "source_binding_count": identity["source_binding_count"],
                "source_binding_scope": identity["source_binding_scope"],
                "source_bindings": bindings,
            },
            "toolchain": {
                "project_root": Path(toolchain_project_root).resolve().as_posix(),
                "environment_root": Path(environment_root).resolve().as_posix(),
                "environment_root_sha256": environment_root_sha256,
                "frozen_record_sha256": frozen_record_sha256,
                "cryptography_version": cryptography_version,
            },
            "launcher": {
                "path": _TRUSTED_LAUNCHER_RELATIVE_PATH,
                "sha256": self._sha256_file(launcher),
            },
            "validation": {
                "preview_id": preview_id,
                "command_specs_sha256": selection.get("command_specs_sha256"),
                "lane": _HOST_FROZEN_LANE,
            },
        }
        receipt["receipt_sha256"] = canonical_manifest_validation_sha256(receipt)
        run_parent = run_parent.resolve()
        run_parent.mkdir(parents=True, exist_ok=True)
        receipt_path = run_parent / _TRUSTED_LAUNCHER_BINDING_FILENAME
        if receipt_path.exists() or receipt_path.is_symlink():
            raise ValidationEnvironmentError("trusted launcher receipt path collision")
        temporary_path: Path | None = None
        descriptor: int | None = None
        try:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{_TRUSTED_LAUNCHER_BINDING_FILENAME}.",
                dir=run_parent,
            )
            temporary_path = Path(temporary_name)
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                descriptor = None
                json.dump(receipt, handle, ensure_ascii=False, sort_keys=True, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, receipt_path)
            temporary_path = None
            os.chmod(receipt_path, 0o600)
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if temporary_path is not None:
                try:
                    temporary_path.unlink()
                except FileNotFoundError:
                    pass
        return receipt_path, receipt

    def _host_frozen_environment(
        self,
        *,
        candidate_root: Path,
        work_root: Path,
        host_venv: Path,
        frozen_asset: dict[str, Any] | None = None,
        toolchain_project_root: Path | None = None,
        trusted_source_root: Path | None = None,
        binding_receipt_path: Path | None = None,
    ) -> dict[str, str]:
        """Build the host-lane environment without importing serving source."""

        environment = build_validation_subprocess_environment(
            candidate_root=candidate_root,
            parent_environment=dict(os.environ),
            temp_root=work_root,
            forbidden_roots=(Path(self.project_root).resolve(),),
        )
        environment["PATH"] = os.pathsep.join(
            [str(venv_bin_dir(host_venv)), os.defpath]
        )
        environment["VIRTUAL_ENV"] = str(host_venv)
        environment["COLAMETA_VALIDATION_LANE"] = _HOST_FROZEN_LANE
        environment["COLAMETA_FROZEN_TOOLCHAIN_PROJECT_ROOT"] = str(
            (toolchain_project_root or Path(self.project_root)).resolve()
        )
        environment["COLAMETA_FROZEN_SOURCE_ROOT"] = str(candidate_root.resolve())
        if trusted_source_root is not None:
            environment["COLAMETA_FROZEN_TRUSTED_SOURCE_ROOT"] = str(
                trusted_source_root.resolve()
            )
        if isinstance(frozen_asset, dict) and isinstance(frozen_asset.get("path"), Path):
            environment[_FROZEN_CRYPTOGRAPHY_WHEEL_ENV] = str(
                frozen_asset["path"].resolve()
            )
        if binding_receipt_path is not None:
            environment[_TRUSTED_LAUNCHER_BINDING_ENV] = str(
                binding_receipt_path.resolve()
            )
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        return environment

    def _host_frozen_preflight(
        self,
        *,
        candidate_root: Path,
        work_root: Path,
        trusted_source_root: Path | None = None,
        frozen_asset: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Select an actually verified frozen host environment."""

        active_project = Path(self.project_root).resolve()
        active_root = (active_project / ".venv").resolve()
        host_python = venv_python(active_root)
        base: dict[str, Any] = {
            "frozen_record_valid": False,
            "environment_root_matches": False,
            "bytecode_policy_satisfied": False,
            "total_host_venv_bytecode_count": 0,
            "record_owned_preimport_bytecode_count": 0,
            "unrelated_bytecode_count": 0,
            "unknown_owner_bytecode_count": 0,
            "active_total_host_venv_bytecode_count": 0,
            "active_record_owned_preimport_bytecode_count": 0,
            "active_unrelated_bytecode_count": 0,
            "active_unknown_owner_bytecode_count": 0,
            "selected_environment_bytecode_count": 0,
            "module_provenance": False,
            "serving_checkout_source_loaded": None,
            "frozen_toolchain_record_sha256": None,
            "environment_root_sha256": None,
            "environment_root_binding_sha256": None,
            "toolchain_project_root": None,
            "environment_root": None,
            "python_executable": None,
            "environment_kind": None,
            "strict_measure_passed": False,
            "active_venv_status": "unverified",
            "active_venv_disposition": None,
            "active_venv_mutated": False,
            "local_assets_only": False,
            "network_used": False,
            "bytecode_deleted": False,
            "trusted_source_checkout_verified": False,
            "frozen_asset_verified": False,
            "frozen_asset_sha256": (
                frozen_asset.get("sha256")
                if isinstance(frozen_asset, dict)
                else None
            ),
            "cryptography_version": (
                frozen_asset.get("version")
                if isinstance(frozen_asset, dict)
                else None
            ),
            "error_code": None,
        }
        if not active_root.is_dir() or not host_python.is_file():
            base["error_code"] = "FROZEN_TOOLCHAIN_AUTHORITY_UNAVAILABLE"
            return base

        probe = r'''
import importlib
import json
import os
import sys

candidate = os.path.realpath(sys.argv[2])
serving = os.path.realpath(sys.argv[3])
module = importlib.import_module("runner.work_item_governance.toolchain_binding")
module_file = os.path.realpath(getattr(module, "__file__", ""))
def within(path, root):
    try:
        return os.path.commonpath([path, root]) == root
    except ValueError:
        return False
payload = {
    "module_from_candidate": within(module_file, candidate),
    "serving_checkout_source_loaded": within(module_file, serving),
    "record_sha256": None,
    "record_hashes_verified": False,
    "environment_root_sha256": None,
    "environment_root_matches": False,
    "inspection_status": None,
    "bytecode_inventory": {},
    "bytecode_policy_satisfied": False,
    "strict_measure_passed": False,
    "strict_measure_error_code": None,
    "error_code": None,
}
try:
    record = module.load_verified_frozen_toolchain_record()
    inspection = module.inspect_frozen_toolchain_environment(sys.argv[1])
    payload["record_sha256"] = record.get("record_sha256")
    payload["record_hashes_verified"] = inspection.get("record_hashes_verified") is True
    payload["environment_root_sha256"] = inspection.get("environment_root_sha256")
    payload["environment_root_matches"] = inspection.get("environment_root_matches") is True
    payload["inspection_status"] = inspection.get("status")
    payload["bytecode_inventory"] = inspection.get("bytecode_inventory", {})
    payload["bytecode_policy_satisfied"] = inspection.get("bytecode_policy_satisfied") is True
    payload["error_code"] = (inspection.get("blocking_reasons") or [None])[0]
except Exception as exc:
    payload["error_code"] = getattr(exc, "code", type(exc).__name__)
try:
    measured = module.measure_closeout_toolchain(sys.argv[1])
    payload["strict_measure_passed"] = True
    payload["record_sha256"] = measured.get("frozen_toolchain_record_sha256", payload["record_sha256"])
    payload["record_hashes_verified"] = measured.get("record_hashes_verified") is True
    payload["environment_root_sha256"] = measured.get("environment_root_sha256")
    payload["environment_root_matches"] = True
    payload["bytecode_policy_satisfied"] = measured.get("bytecode_policy_satisfied") is True
except Exception as exc:
    payload["strict_measure_error_code"] = getattr(exc, "code", type(exc).__name__)
print(json.dumps(payload, sort_keys=True))
'''

        def run_probe(
            *,
            python: Path,
            toolchain_project_root: Path,
            probe_work_root: Path,
            host_venv: Path,
        ) -> dict[str, Any]:
            environment = self._host_frozen_environment(
                candidate_root=candidate_root,
                work_root=probe_work_root,
                host_venv=host_venv,
                frozen_asset=frozen_asset,
                toolchain_project_root=toolchain_project_root,
                trusted_source_root=trusted_source_root,
            )
            try:
                completed = subprocess.run(
                    [
                        str(python),
                        "-c",
                        probe,
                        str(toolchain_project_root),
                        str(candidate_root.resolve()),
                        str(active_project),
                    ],
                    cwd=candidate_root,
                    env=environment,
                    capture_output=True,
                    text=True,
                    check=False,
                    shell=False,
                    timeout=120,
                )
                payload = (
                    json.loads(completed.stdout)
                    if completed.returncode == 0
                    else {}
                )
            except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, TypeError):
                payload = {}
            return payload if isinstance(payload, dict) else {}

        def ready(payload: dict[str, Any]) -> bool:
            return (
                payload.get("strict_measure_passed") is True
                and payload.get("record_hashes_verified") is True
                and payload.get("environment_root_matches") is True
                and payload.get("bytecode_policy_satisfied") is True
                and payload.get("module_from_candidate") is True
                and payload.get("serving_checkout_source_loaded") is not True
            )

        def inventory_value(payload: dict[str, Any], key: str) -> int:
            inventory = payload.get("bytecode_inventory")
            value = inventory.get(key) if isinstance(inventory, dict) else None
            return value if isinstance(value, int) and not isinstance(value, bool) else 0

        active_payload = run_probe(
            python=host_python,
            toolchain_project_root=active_project,
            probe_work_root=work_root / "active-probe",
            host_venv=active_root,
        )
        base["active_total_host_venv_bytecode_count"] = inventory_value(
            active_payload, "total_count"
        )
        base["active_record_owned_preimport_bytecode_count"] = inventory_value(
            active_payload, "record_listed_count"
        )
        base["active_unrelated_bytecode_count"] = inventory_value(
            active_payload, "non_record_listed_count"
        )
        base["active_unknown_owner_bytecode_count"] = inventory_value(
            active_payload, "unknown_owner_count"
        )
        base["total_host_venv_bytecode_count"] = base[
            "active_total_host_venv_bytecode_count"
        ]
        base["active_venv_status"] = (
            "matched" if active_payload.get("inspection_status") == "matched" else "drifted"
        )
        base["active_venv_disposition"] = (
            "active_verified" if ready(active_payload) else "not_frozen"
        )

        selected_payload = active_payload
        materialized = False
        if not ready(active_payload):
            try:
                if not isinstance(frozen_asset, dict) or not isinstance(
                    frozen_asset.get("path"), Path
                ):
                    raise RuntimeError("frozen toolchain asset is unavailable")
                _selected_project, _selected_root, materialization = (
                    materialize_frozen_toolchain_environment(
                        source_venv=active_root,
                        work_root=work_root / "ephemeral-host",
                        frozen_asset=frozen_asset["path"],
                        frozen_asset_filename=str(frozen_asset["filename"]),
                        frozen_asset_sha256=str(frozen_asset["sha256"]),
                        frozen_asset_distribution=str(frozen_asset["distribution"]),
                        frozen_asset_version=str(frozen_asset["version"]),
                    )
                )
                selected_payload = run_probe(
                    python=venv_python(_selected_root),
                    toolchain_project_root=_selected_project,
                    probe_work_root=work_root / "ephemeral-host-probe",
                    host_venv=_selected_root,
                )
                materialized = ready(selected_payload)
                base["local_assets_only"] = materialization.get(
                    "local_assets_only"
                ) is True
                base["network_used"] = materialization.get("network_used") is True
                base["frozen_asset_verified"] = materialization.get("frozen_asset") is not None
            except Exception:
                base["error_code"] = "FROZEN_TOOLCHAIN_MATERIALIZATION_CONTRACT_UNAVAILABLE"
        if not materialized and not ready(active_payload):
            if base["error_code"] is None:
                base["error_code"] = (
                    selected_payload.get("strict_measure_error_code")
                    or selected_payload.get("error_code")
                    or "FROZEN_TOOLCHAIN_MATERIALIZATION_CONTRACT_UNAVAILABLE"
                )
            return base

        base["frozen_record_valid"] = selected_payload.get(
            "record_hashes_verified"
        ) is True
        base["environment_root_matches"] = selected_payload.get(
            "environment_root_matches"
        ) is True
        base["bytecode_policy_satisfied"] = selected_payload.get(
            "bytecode_policy_satisfied"
        ) is True
        base["strict_measure_passed"] = selected_payload.get(
            "strict_measure_passed"
        ) is True
        base["record_owned_preimport_bytecode_count"] = inventory_value(
            selected_payload, "record_listed_count"
        )
        base["unrelated_bytecode_count"] = inventory_value(
            selected_payload, "non_record_listed_count"
        )
        base["selected_environment_bytecode_count"] = inventory_value(
            selected_payload, "total_count"
        )
        base["module_provenance"] = selected_payload.get(
            "module_from_candidate"
        ) is True
        base["serving_checkout_source_loaded"] = selected_payload.get(
            "serving_checkout_source_loaded"
        ) is True
        base["environment_kind"] = "ephemeral_verified" if materialized else "active_verified"
        base["active_venv_mutated"] = False
        selected_project_root = (
            _selected_project if materialized else active_project
        )
        selected_environment_root = (
            _selected_root if materialized else active_root
        )
        base["toolchain_project_root"] = selected_project_root.resolve().as_posix()
        base["environment_root"] = selected_environment_root.resolve().as_posix()
        # Keep the venv launcher path rather than collapsing it to the system
        # interpreter.  Invoking ``/usr/bin/python3.12`` directly bypasses the
        # venv's site-packages, which would make the host lane appear frozen
        # while silently losing pytest and the other frozen wrappers.
        base["python_executable"] = venv_python(selected_environment_root).absolute().as_posix()
        record_sha256 = selected_payload.get("record_sha256")
        if isinstance(record_sha256, str) and _SHA256_RE.fullmatch(record_sha256):
            base["frozen_toolchain_record_sha256"] = record_sha256
        root_digest = selected_payload.get("environment_root_sha256")
        if isinstance(root_digest, str) and _SHA256_RE.fullmatch(root_digest):
            base["environment_root_sha256"] = root_digest
            base["environment_root_binding_sha256"] = canonical_manifest_validation_sha256(
                {"environment_root_sha256": root_digest}
            )
        if base["serving_checkout_source_loaded"] is True:
            base["error_code"] = "HOST_TOOLCHAIN_SERVING_SOURCE_LEAK"
        elif not base["module_provenance"]:
            base["error_code"] = "HOST_TOOLCHAIN_CANDIDATE_SOURCE_UNPROVEN"
        elif not ready(selected_payload):
            base["error_code"] = (
                selected_payload.get("strict_measure_error_code")
                or selected_payload.get("error_code")
                or "FROZEN_TOOLCHAIN_STRICT_MEASURE_FAILED"
            )
        else:
            base["error_code"] = None
        return base

    @staticmethod
    def _pytest_command_metrics(
        command: Any,
        stdout: str,
        stderr: str,
    ) -> dict[str, Any]:
        """Extract measurable pytest coverage evidence from one command."""

        if not (
            isinstance(command, list)
            and len(command) >= 3
            and command[1:3] == ["-m", "pytest"]
        ):
            return {
                "selected_test_count": 0,
                "skipped_count": 0,
                "xfailed_count": 0,
                "xpassed_count": 0,
                "skipped_nodes": [],
            }

        output = f"{stdout}\n{stderr}"
        summary_lines = [
            line.strip()
            for line in output.splitlines()
            if re.search(r"\bin\s+\d+(?:\.\d+)?s\b", line)
            and re.search(
                r"\b(?:passed|failed|skipped|error|errors|xfailed|xpassed)\b",
                line,
            )
        ]
        counts = {
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "error": 0,
            "errors": 0,
            "xfailed": 0,
            "xpassed": 0,
        }
        if summary_lines:
            for match in re.finditer(
                r"(?P<count>\d+)\s+(?P<outcome>passed|failed|skipped|error|errors|xfailed|xpassed)\b",
                summary_lines[-1],
            ):
                counts[match.group("outcome")] += int(match.group("count"))

        skipped_nodes: list[str] = []
        for line in output.splitlines():
            match = re.match(r"\s*SKIPPED\s+\[(\d+)\]\s+(.+?)\s*$", line)
            if match:
                skipped_nodes.extend([match.group(2)] * int(match.group(1)))

        return {
            "selected_test_count": sum(counts.values()),
            "skipped_count": counts["skipped"],
            "xfailed_count": counts["xfailed"],
            "xpassed_count": counts["xpassed"],
            "skipped_nodes": skipped_nodes,
        }

    @staticmethod
    def _validation_lane_evidence(
        *,
        command_specs: list[dict[str, Any]],
        command_results: list[dict[str, Any]],
        lane_assignments: list[str],
        candidate_delta_sha256: str | None,
        candidate_module_provenance: bool | None,
        host_preflight: dict[str, Any] | None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        lane_payloads: dict[str, dict[str, Any]] = {}
        for lane in (_CANDIDATE_LANE, _HOST_FROZEN_LANE):
            expected_indexes = [
                index for index, assigned in enumerate(lane_assignments) if assigned == lane
            ]
            lane_specs = [command_specs[index] for index in expected_indexes]
            lane_results = [
                result
                for result in command_results
                if isinstance(result, dict) and result.get("lane") == lane
            ]
            required = bool(expected_indexes)
            if not required:
                status = "not_required"
                result_digest = None
            elif lane == _HOST_FROZEN_LANE and isinstance(host_preflight, dict) and host_preflight.get("error_code"):
                status = "blocked"
                result_digest = canonical_manifest_validation_sha256(
                    {"lane": lane, "preflight": host_preflight, "results": lane_results}
                )
            elif len(lane_results) != len(expected_indexes):
                status = "incomplete"
                result_digest = canonical_manifest_validation_sha256(
                    {"lane": lane, "results": lane_results}
                )
            elif all(result.get("ok") is True for result in lane_results):
                status = "passed"
                result_digest = canonical_manifest_validation_sha256(
                    {"lane": lane, "results": lane_results}
                )
            else:
                status = "failed"
                result_digest = canonical_manifest_validation_sha256(
                    {"lane": lane, "results": lane_results}
                )

            selected_test_count = sum(
                int(result.get("selected_test_count", 0))
                for result in lane_results
                if isinstance(result.get("selected_test_count", 0), int)
                and not isinstance(result.get("selected_test_count", 0), bool)
            )
            skipped_count = sum(
                int(result.get("skipped_count", 0))
                for result in lane_results
                if isinstance(result.get("skipped_count", 0), int)
                and not isinstance(result.get("skipped_count", 0), bool)
            )
            allowed_skip_count = sum(
                int(result.get("allowed_skip_count", 0))
                for result in lane_results
                if isinstance(result.get("allowed_skip_count", 0), int)
                and not isinstance(result.get("allowed_skip_count", 0), bool)
            )
            unexpected_skip_count = sum(
                int(result.get("unexpected_skip_count", 0))
                for result in lane_results
                if isinstance(result.get("unexpected_skip_count", 0), int)
                and not isinstance(result.get("unexpected_skip_count", 0), bool)
            )
            required_skipped_count = (
                sum(
                    int(result.get("required_skipped_count", 0))
                    for result in lane_results
                    if isinstance(result.get("required_skipped_count", 0), int)
                    and not isinstance(result.get("required_skipped_count", 0), bool)
                )
                if lane == _HOST_FROZEN_LANE
                else 0
            )
            if unexpected_skip_count > 0 or required_skipped_count > 0:
                status = "failed"

            payload: dict[str, Any] = {
                "status": status,
                "result_sha256": result_digest,
                "command_specs_sha256": canonical_manifest_validation_sha256(lane_specs),
                "candidate_delta_sha256": candidate_delta_sha256,
                "selected_test_count": selected_test_count,
                "skipped_count": skipped_count,
                "allowed_skip_count": allowed_skip_count,
                "unexpected_skip_count": unexpected_skip_count,
                "required_skipped_count": required_skipped_count,
                "module_provenance": (
                    candidate_module_provenance
                    if lane == _CANDIDATE_LANE
                    else (
                        host_preflight.get("module_provenance")
                        if isinstance(host_preflight, dict)
                        else None
                    )
                ),
            }
            if lane == _HOST_FROZEN_LANE:
                payload.update(
                    {
                        "frozen_toolchain_record_sha256": (
                            host_preflight.get("frozen_toolchain_record_sha256")
                            if isinstance(host_preflight, dict)
                            else None
                        ),
                        "environment_root_binding_sha256": (
                            host_preflight.get("environment_root_binding_sha256")
                            if isinstance(host_preflight, dict)
                            else None
                        ),
                        "total_host_venv_bytecode_count": (
                            host_preflight.get("total_host_venv_bytecode_count", 0)
                            if isinstance(host_preflight, dict)
                            else 0
                        ),
                        "record_owned_preimport_bytecode_count": (
                            host_preflight.get("record_owned_preimport_bytecode_count", 0)
                            if isinstance(host_preflight, dict)
                            else 0
                        ),
                        "unrelated_bytecode_count": (
                            host_preflight.get("unrelated_bytecode_count", 0)
                            if isinstance(host_preflight, dict)
                            else 0
                        ),
                        "bytecode_deleted": (
                            host_preflight.get("bytecode_deleted") is True
                            if isinstance(host_preflight, dict)
                            else False
                        ),
                        "environment_kind": (
                            host_preflight.get("environment_kind")
                            if isinstance(host_preflight, dict)
                            else None
                        ),
                        "strict_measure_passed": (
                            host_preflight.get("strict_measure_passed") is True
                            if isinstance(host_preflight, dict)
                            else False
                        ),
                    }
                )
            lane_payloads[lane] = payload

        candidate_status = lane_payloads[_CANDIDATE_LANE]["status"]
        host_status = lane_payloads[_HOST_FROZEN_LANE]["status"]
        if host_status in {"blocked", "incomplete"} or candidate_status == "incomplete":
            aggregate_status = "incomplete"
        elif candidate_status == "passed" and host_status in {"passed", "not_required"}:
            aggregate_status = "passed"
        elif candidate_status == "not_required" and host_status == "not_required":
            aggregate_status = "incomplete"
        else:
            aggregate_status = "failed"
        aggregate = {
            "status": aggregate_status,
            "lane_result_digest": canonical_manifest_validation_sha256(lane_payloads),
            "both_lanes_required": host_status != "not_required",
            "classification_exhaustive": True,
            "classification_basis": "complementary_marker_expressions",
        }
        return lane_payloads, aggregate

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
                "validation_lanes": None,
                "aggregate": None,
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
        lane_assignments = artifact.get("validation_lanes")
        if not isinstance(lane_assignments, list) or len(lane_assignments) != len(command_specs):
            lane_assignments = [_CANDIDATE_LANE] * len(command_specs)
        lane_checkouts: dict[str, dict[str, Any]] = {}
        isolated_checkout: dict[str, Any] | None = None
        source_after: dict[str, Any] | None = None
        source_after_by_lane: dict[str, dict[str, Any] | None] = {}
        cleanup_complete = True
        manifest_candidate_head: str | None = None
        validation_environment: ValidationEnvironment | None = None
        validation_context_token = None
        host_environment: dict[str, str] | None = None
        host_preflight: dict[str, Any] | None = None
        trusted_source_checkout: dict[str, Any] | None = None
        frozen_asset: dict[str, Any] | None = None
        trusted_launcher_binding_receipt: dict[str, Any] | None = None
        trusted_launcher_binding_path: Path | None = None
        execution_overlays_removed: dict[str, bool] = {}
        try:
            manifest_candidate_head = self._bound_candidate_head(artifact)
            if manifest_candidate_head is not None:
                source_bindings = self._source_bindings_for_artifact(artifact)
                binding_kind = str(
                    artifact.get("candidate_delta_mode") or "source_files"
                )
                required_lanes = {
                    lane
                    for lane in lane_assignments
                    if lane in _VALIDATION_LANES
                }
                for lane in sorted(required_lanes):
                    checkout = self._prepare_isolated_checkout(
                        manifest_candidate_head,
                        f"{run_id}-{lane}",
                    )
                    lane_checkouts[lane] = checkout
                    execution_overlays_removed[lane] = False
                    checkout["source_overlay_summary"] = (
                        self._apply_candidate_source_overlays(
                            checkout,
                            source_bindings,
                            binding_kind=binding_kind,
                        )
                    )
                isolated_checkout = lane_checkouts.get(_CANDIDATE_LANE) or lane_checkouts.get(
                    _HOST_FROZEN_LANE
                )

                candidate_specs = [
                    spec
                    for index, spec in enumerate(command_specs)
                    if lane_assignments[index] == _CANDIDATE_LANE
                    and isinstance(spec, dict)
                ]
                needs_candidate_python = any(
                    command_uses_python(spec.get("argv", []))
                    for spec in candidate_specs
                )
                needs_host_python = any(
                    lane_assignments[index] == _HOST_FROZEN_LANE
                    and isinstance(spec, dict)
                    and command_uses_python(spec.get("argv", []))
                    for index, spec in enumerate(command_specs)
                )
                needs_python = needs_candidate_python or needs_host_python
                if needs_python:
                    frozen_asset = self._resolve_frozen_toolchain_asset()
                    if frozen_asset.get("ok") is not True:
                        raise ValidationEnvironmentError(
                            str(
                                frozen_asset.get("error_code")
                                or "FROZEN_TOOLCHAIN_LOCAL_ASSETS_UNAVAILABLE"
                            )
                        )
                if _CANDIDATE_LANE in required_lanes:
                    candidate_checkout = lane_checkouts.get(_CANDIDATE_LANE)
                    if candidate_checkout is None:
                        raise ValidationEnvironmentError(
                            "candidate checkout is unavailable"
                        )
                    validation_environment = prepare_validation_environment(
                        candidate_root=Path(candidate_checkout["root"]),
                        work_root=Path(candidate_checkout["parent"])
                        / "toolchain",
                        parent_environment=dict(os.environ),
                        forbidden_roots=(Path(self.project_root).resolve(),),
                        needs_python=needs_candidate_python,
                        frozen_asset=(
                            frozen_asset.get("path")
                            if isinstance(frozen_asset, dict)
                            else None
                        ),
                        frozen_asset_filename=(
                            str(frozen_asset["filename"])
                            if isinstance(frozen_asset, dict)
                            else None
                        ),
                        frozen_asset_sha256=(
                            str(frozen_asset["sha256"])
                            if isinstance(frozen_asset, dict)
                            else None
                        ),
                        frozen_asset_distribution=(
                            str(frozen_asset["distribution"])
                            if isinstance(frozen_asset, dict)
                            else "cryptography"
                        ),
                        frozen_asset_version=(
                            str(frozen_asset["version"])
                            if isinstance(frozen_asset, dict)
                            else "50.0.0"
                        ),
                    )
                    candidate_checkout["validation_venv"] = (
                        validation_environment.venv_dir
                    )
                    validation_context_token = _VALIDATION_ENVIRONMENT_CONTEXT.set(
                        validation_environment
                    )

                if _HOST_FROZEN_LANE in lane_assignments:
                    host_checkout = lane_checkouts.get(_HOST_FROZEN_LANE)
                    if host_checkout is None:
                        raise ValidationEnvironmentError(
                            "host frozen checkout is unavailable"
                        )
                    trusted_source_checkout = self._prepare_isolated_checkout(
                        manifest_candidate_head,
                        f"{run_id}-trusted-source",
                    )
                    trusted_source_checkout["source_overlay_summary"] = (
                        self._apply_candidate_source_overlays(
                            trusted_source_checkout,
                            self._source_bindings_for_artifact(artifact),
                            binding_kind=(
                                str(
                                    artifact.get("candidate_delta_mode")
                                    or "source_files"
                                )
                            ),
                        )
                    )
                    host_preflight = self._host_frozen_preflight(
                        candidate_root=Path(host_checkout["root"]),
                        work_root=Path(host_checkout["parent"]) / "host-toolchain",
                        trusted_source_root=Path(trusted_source_checkout["root"]),
                        frozen_asset=frozen_asset,
                    )
                    if (
                        host_preflight.get("error_code") is None
                        and host_preflight.get("frozen_record_valid") is True
                        and host_preflight.get("environment_root_matches") is True
                        and host_preflight.get("bytecode_policy_satisfied") is True
                        and host_preflight.get("module_provenance") is True
                        and host_preflight.get("serving_checkout_source_loaded") is not True
                    ):
                        if host_preflight.get("environment_kind") == "ephemeral_verified":
                            selected_toolchain_project = (
                                Path(host_checkout["parent"])
                                / "host-toolchain"
                                / "ephemeral-host"
                                / "frozen-toolchain-project"
                            ).resolve()
                            selected_host_venv = selected_toolchain_project / ".venv"
                        else:
                            selected_toolchain_project = Path(self.project_root).resolve()
                            selected_host_venv = selected_toolchain_project / ".venv"
                        try:
                            materialize_trusted_source_venv(
                                source_venv=selected_host_venv,
                                source_checkout=Path(trusted_source_checkout["root"]),
                            )
                        except Exception:
                            host_preflight["error_code"] = (
                                "FROZEN_TOOLCHAIN_MATERIALIZATION_CONTRACT_UNAVAILABLE"
                            )
                        else:
                            host_preflight["trusted_source_checkout_verified"] = True
                            try:
                                (
                                    trusted_launcher_binding_path,
                                    trusted_launcher_binding_receipt,
                                ) = self._write_trusted_launcher_binding_receipt(
                                    artifact=artifact,
                                    preview_id=preview_id,
                                    candidate_root=Path(host_checkout["root"]),
                                    run_parent=Path(host_checkout["parent"]),
                                    host_preflight=host_preflight,
                                )
                            except Exception:
                                host_preflight["error_code"] = (
                                    "TRUSTED_LAUNCHER_BINDING_RECEIPT_UNAVAILABLE"
                                )
                            else:
                                host_preflight[
                                    "trusted_launcher_binding_receipt_sha256"
                                ] = trusted_launcher_binding_receipt[
                                    "receipt_sha256"
                                ]
                            host_environment = self._host_frozen_environment(
                                candidate_root=Path(host_checkout["root"]),
                                work_root=Path(host_checkout["parent"])
                                / "host-toolchain",
                                host_venv=selected_host_venv,
                                frozen_asset=frozen_asset,
                                toolchain_project_root=selected_toolchain_project,
                                trusted_source_root=Path(
                                    trusted_source_checkout["root"]
                                ),
                                binding_receipt_path=trusted_launcher_binding_path,
                            )

            for index, spec in enumerate(command_specs):
                command = spec.get("argv") if isinstance(spec, dict) else None
                lane = lane_assignments[index]
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
                manifest_command_allowed = (
                    artifact.get("scope") != "manifest_bound"
                    or self._is_supported_manifest_command(command)
                )
                if (
                    not self._is_safe_command(command)
                    or not manifest_command_allowed
                ):
                    failed_indexes.append(index)
                    command_results.append({
                        "index": index,
                        "lane": lane,
                        "ok": False,
                        "returncode": 127,
                        "command": self._display_command(command),
                        "stdout": "",
                        "stderr": "命令结构无效，已阻断。",
                        "stdout_truncated": False,
                        "stderr_truncated": False,
                    })
                    break
                if lane == _HOST_FROZEN_LANE and (
                    not isinstance(host_preflight, dict)
                    or host_preflight.get("error_code") is not None
                    or host_environment is None
                ):
                    error_code = (
                        host_preflight.get("error_code")
                        if isinstance(host_preflight, dict)
                        else "FROZEN_TOOLCHAIN_AUTHORITY_UNAVAILABLE"
                    )
                    failed_indexes.append(index)
                    command_results.append({
                        "index": index,
                        "lane": lane,
                        "ok": False,
                        "returncode": 126,
                        "error_code": error_code,
                        "timeout_seconds": timeout_seconds,
                        "continue_on_failure": continue_on_failure,
                        "command": self._display_command(command),
                        "executed_command": self._display_command(command),
                        "stdout": "",
                        "stderr": "frozen host toolchain preflight rejected execution",
                        "stdout_truncated": False,
                        "stderr_truncated": False,
                    })
                    continue
                effective_command = list(command)
                if manifest_candidate_head is not None:
                    effective_command = self._manifest_execution_command(
                        effective_command,
                        manifest_candidate_head,
                    )
                if lane == _HOST_FROZEN_LANE and command_uses_python(effective_command):
                    selected_python = (
                        host_preflight.get("python_executable")
                        if isinstance(host_preflight, dict)
                        else None
                    )
                    if not isinstance(selected_python, str) or not selected_python:
                        failed_indexes.append(index)
                        command_results.append({
                            "index": index,
                            "lane": lane,
                            "ok": False,
                            "returncode": 126,
                            "error_code": "FROZEN_TOOLCHAIN_AUTHORITY_UNAVAILABLE",
                            "timeout_seconds": timeout_seconds,
                            "continue_on_failure": continue_on_failure,
                            "command": self._display_command(command),
                            "executed_command": self._display_command(command),
                            "stdout": "",
                            "stderr": "frozen host Python binding unavailable",
                            "stdout_truncated": False,
                            "stderr_truncated": False,
                        })
                        continue
                    effective_command[0] = selected_python
                lane_checkout = lane_checkouts.get(lane)
                if lane_checkout is None and manifest_candidate_head is not None:
                    failed_indexes.append(index)
                    command_results.append({
                        "index": index,
                        "lane": lane,
                        "ok": False,
                        "returncode": 126,
                        "error_code": "VALIDATION_CHECKOUT_UNAVAILABLE",
                        "timeout_seconds": timeout_seconds,
                        "continue_on_failure": continue_on_failure,
                        "command": self._display_command(command),
                        "executed_command": self._display_command(command),
                        "stdout": "",
                        "stderr": "validation lane checkout unavailable",
                        "stdout_truncated": False,
                        "stderr_truncated": False,
                    })
                    continue
                lane_execution_root = (
                    str(lane_checkout["root"])
                    if lane_checkout is not None
                    else self.project_root
                )
                if lane == _HOST_FROZEN_LANE:
                    result = self._run_command(
                        effective_command,
                        timeout_seconds=timeout_seconds,
                        cwd=lane_execution_root,
                        lane=lane,
                        host_environment=host_environment,
                    )
                else:
                    # Keep the established candidate-lane call shape so
                    # existing adapters and test doubles remain compatible.
                    result = self._run_command(
                        effective_command,
                        timeout_seconds=timeout_seconds,
                        cwd=lane_execution_root,
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
                error_code = result.get("error_code")
                pytest_metrics = self._pytest_command_metrics(
                    command,
                    stdout,
                    stderr,
                )
                allowed_skip_count = sum(
                    1
                    for signature in pytest_metrics["skipped_nodes"]
                    if signature in _ALLOWED_CANDIDATE_SKIP_SIGNATURES
                )
                skipped_count = int(pytest_metrics["skipped_count"])
                unexpected_skip_count = (
                    max(0, skipped_count - allowed_skip_count)
                    + int(pytest_metrics["xfailed_count"])
                    + int(pytest_metrics["xpassed_count"])
                    if lane == _CANDIDATE_LANE
                    else 0
                )
                required_skipped_count = (
                    skipped_count
                    + int(pytest_metrics["xfailed_count"])
                    + int(pytest_metrics["xpassed_count"])
                    if lane == _HOST_FROZEN_LANE
                    else 0
                )
                if ok and required_skipped_count > 0:
                    ok = False
                    error_code = "REQUIRED_TEST_SKIPPED"
                    stderr = (stderr + "\n" if stderr else "") + (
                        "host-bound tests may not be skipped"
                    )
                elif ok and unexpected_skip_count > 0:
                    ok = False
                    error_code = "UNEXPECTED_TEST_SKIPPED"
                    stderr = (stderr + "\n" if stderr else "") + (
                        "candidate tests produced an unexpected skip"
                    )
                if not ok:
                    failed_indexes.append(index)
                command_results.append({
                    "index": index,
                    "lane": lane,
                    "ok": ok,
                    "returncode": result["returncode"],
                    "error_code": error_code,
                    "timeout_seconds": timeout_seconds,
                    "continue_on_failure": continue_on_failure,
                    "command": self._display_command(command),
                    "executed_command": self._display_command(
                        effective_command
                    ),
                    "stdout": stdout,
                    "stderr": stderr,
                    "stdout_truncated": stdout_truncated,
                    "stderr_truncated": stderr_truncated,
                    "selected_test_count": int(
                        pytest_metrics["selected_test_count"]
                    ),
                    "skipped_count": skipped_count,
                    "allowed_skip_count": allowed_skip_count,
                    "unexpected_skip_count": unexpected_skip_count,
                    "required_skipped_count": required_skipped_count,
                    "skipped_nodes": list(pytest_metrics["skipped_nodes"]),
                })
                if not ok and not continue_on_failure:
                    break

            for lane, checkout in lane_checkouts.items():
                self._remove_isolated_execution_overlays(checkout)
                execution_overlays_removed[lane] = True
                source_after_by_lane[lane] = self._capture_checkout_snapshot(
                    Path(checkout["root"])
                )
                if checkout is isolated_checkout:
                    source_after = source_after_by_lane[lane]
        finally:
            if validation_context_token is not None:
                _VALIDATION_ENVIRONMENT_CONTEXT.reset(validation_context_token)
            for lane, checkout in lane_checkouts.items():
                if not execution_overlays_removed.get(lane, False):
                    try:
                        self._remove_isolated_execution_overlays(
                            checkout
                        )
                        execution_overlays_removed[lane] = True
                        if lane not in source_after_by_lane:
                            source_after_by_lane[lane] = (
                                self._capture_checkout_snapshot(
                                    Path(checkout["root"])
                                )
                            )
                        if checkout is isolated_checkout:
                            source_after = source_after_by_lane[lane]
                    except Exception:
                        cleanup_complete = False
                cleanup_complete = (
                    self._cleanup_isolated_checkout(checkout)
                    and cleanup_complete
                    and checkout.get(
                        "source_overlay_cleanup_complete",
                        True,
                    ) is True
                )
            if trusted_source_checkout is not None:
                try:
                    self._remove_isolated_execution_overlays(
                        trusted_source_checkout
                    )
                except Exception:
                    cleanup_complete = False
                cleanup_complete = (
                    self._cleanup_isolated_checkout(trusted_source_checkout)
                    and cleanup_complete
                )

        lane_checkout_provenance: dict[str, dict[str, Any]] = {}
        for lane, checkout in lane_checkouts.items():
            lane_source_before = checkout["source_before"]
            lane_source_after = source_after_by_lane.get(lane)
            lane_checkout_provenance[lane] = {
                "candidate_head": checkout["candidate_head"],
                "candidate_tree": checkout["candidate_tree"],
                "source_before": lane_source_before,
                "source_after": lane_source_after,
                "source_binding_match": (
                    isinstance(lane_source_after, dict)
                    and lane_source_before == lane_source_after
                ),
                "isolated_from_project_worktree": checkout[
                    "isolated_from_project_worktree"
                ],
                "cleanup_complete": (
                    execution_overlays_removed.get(lane, False)
                    and checkout.get("source_overlay_cleanup_complete", True)
                    and cleanup_complete
                ),
            }

        checkout_provenance: dict[str, Any] | None = None
        if isolated_checkout is not None:
            isolated_lane = (
                _CANDIDATE_LANE
                if _CANDIDATE_LANE in lane_checkouts
                else _HOST_FROZEN_LANE
            )
            isolated_provenance = lane_checkout_provenance[isolated_lane]
            source_before = isolated_provenance["source_before"]
            checkout_provenance = {
                "mode": _ISOLATED_CHECKOUT_MODE,
                "candidate_head": isolated_checkout["candidate_head"],
                "candidate_tree": isolated_checkout["candidate_tree"],
                "source_before": source_before,
                "source_after": isolated_provenance["source_after"],
                "source_binding_match": isolated_provenance[
                    "source_binding_match"
                ],
                "isolated_from_project_worktree": isolated_checkout[
                    "isolated_from_project_worktree"
                ],
                "cleanup_complete": isolated_provenance["cleanup_complete"],
            }
            provenance_valid = all(
                item.get("source_binding_match") is True
                and item.get("source_before", {}).get("candidate_clean") is True
                and item.get("isolated_from_project_worktree") is True
                and item.get("cleanup_complete") is True
                for item in lane_checkout_provenance.values()
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

        candidate_identity = artifact.get("candidate_identity")
        candidate_delta_sha256 = (
            candidate_identity.get("worktree_delta_sha256")
            if isinstance(candidate_identity, dict)
            else None
        )
        candidate_module_provenance = (
            validation_environment.summary.get("candidate_module_provenance_verified")
            if validation_environment is not None
            else None
        )
        validation_lanes, aggregate = self._validation_lane_evidence(
            command_specs=command_specs,
            command_results=command_results,
            lane_assignments=lane_assignments,
            candidate_delta_sha256=candidate_delta_sha256,
            candidate_module_provenance=candidate_module_provenance,
            host_preflight=host_preflight,
        )
        failed_indexes.sort()
        status = "passed" if not failed_indexes and aggregate["status"] == "passed" else "failed"
        completed_at = _utc_now()
        output_summary: dict[str, Any] = {
            "total_output_chars": total_output_chars,
            "redacted": True,
            "truncated": total_output_chars >= MAX_TOTAL_OUTPUT_CHARS,
        }
        if checkout_provenance is not None:
            output_summary["checkout_provenance"] = checkout_provenance
        candidate_identity_payload = artifact.get("candidate_identity")
        lane_identity: dict[str, Any] = {}
        if isinstance(candidate_identity_payload, dict):
            lane_identity = {
                key: candidate_identity_payload.get(key)
                for key in (
                    "head",
                    "worktree_delta_sha256",
                    "source_binding_sha256",
                    "source_binding_count",
                )
            }
        lane_checkout_summary: dict[str, Any] = {}
        for lane, provenance in lane_checkout_provenance.items():
            lane_checkout_summary[lane] = {
                "candidate_identity": dict(lane_identity),
                "source_binding_match": provenance.get(
                    "source_binding_match"
                ),
                "cleanup_complete": provenance.get("cleanup_complete"),
            }
        if lane_checkout_summary:
            output_summary["lane_checkouts"] = {
                **lane_checkout_summary,
                "distinct_checkout_roots": (
                    len(lane_checkouts) == 2
                    and len(
                        {
                            str(checkout["root"].resolve())
                            for checkout in lane_checkouts.values()
                        }
                    )
                    == 2
                ),
            }
            output_summary["lane_cleanup"] = {
                "candidate_checkout_cleanup": (
                    execution_overlays_removed.get(_CANDIDATE_LANE) is True
                    and (
                        _CANDIDATE_LANE not in lane_checkouts
                        or lane_checkouts[_CANDIDATE_LANE].get(
                            "source_overlay_cleanup_complete", True
                        )
                        is True
                    )
                ),
                "host_checkout_cleanup": (
                    execution_overlays_removed.get(_HOST_FROZEN_LANE) is True
                    and (
                        _HOST_FROZEN_LANE not in lane_checkouts
                        or lane_checkouts[_HOST_FROZEN_LANE].get(
                            "source_overlay_cleanup_complete", True
                        )
                        is True
                    )
                ),
                "candidate_venv_cleanup": (
                    _CANDIDATE_LANE not in lane_checkouts
                    or lane_checkouts[_CANDIDATE_LANE].get("validation_venv")
                    is None
                    or not Path(
                        lane_checkouts[_CANDIDATE_LANE]["validation_venv"]
                    ).exists()
                ),
                "host_trusted_source_cleanup": trusted_source_checkout is None
                or not Path(trusted_source_checkout["root"]).exists(),
                "host_frozen_environment_cleanup": (
                    _HOST_FROZEN_LANE not in lane_checkouts
                    or not Path(lane_checkouts[_HOST_FROZEN_LANE]["parent"]).exists()
                ),
            }
        if validation_environment is not None:
            output_summary["validation_environment"] = {
                **validation_environment.summary,
                "candidate_code_authority": True,
                "shell_false": True,
                "fixed_argv_preserved": True,
            }
        if host_preflight is not None:
            output_summary["host_frozen_preflight"] = dict(host_preflight)
        if isolated_checkout is not None:
            overlay_summary = isolated_checkout.get("source_overlay_summary")
            if isinstance(overlay_summary, dict):
                output_summary["candidate_source_overlay"] = dict(
                    overlay_summary
                )
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
            "candidate_identity": dict(
                artifact.get("candidate_identity")
                if isinstance(artifact.get("candidate_identity"), dict)
                else {}
            ),
            "validation_selection": dict(
                artifact.get("validation_selection")
                if isinstance(artifact.get("validation_selection"), dict)
                else {}
            ),
            "validation_lanes": validation_lanes,
            "aggregate": aggregate,
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
            "candidate_identity": dict(
                artifact.get("candidate_identity")
                if isinstance(artifact.get("candidate_identity"), dict)
                else {}
            ),
            "validation_selection": dict(
                artifact.get("validation_selection")
                if isinstance(artifact.get("validation_selection"), dict)
                else {}
            ),
            "validation_lanes": None,
            "aggregate": None,
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
            expected_executed_command = self._display_command(
                self._manifest_execution_command(
                    spec["argv"],
                    normalized_candidate,
                )
            )
            if (
                not isinstance(command_result, dict)
                or command_result.get("index") != index
                or command_result.get("ok") is not True
                or command_result.get("returncode") != 0
                or command_result.get("command") != expected_command
                or command_result.get("executed_command")
                != expected_executed_command
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

    @staticmethod
    def _is_runtime_delta_path(normalized: str) -> bool:
        parts = PurePosixPath(normalized).parts
        if not parts:
            return False
        if parts[0] == ".colameta" and len(parts) > 1:
            return parts[1] in {
                "runtime",
                "logs",
                "reports",
                "audits",
                "plan-patches",
                "tmp",
                "local",
                "executor-sessions",
            }
        return (
            parts[0] in {".venv", "build", "dist", ".pytest_cache", "__pycache__"}
            or normalized == ".coverage"
            or normalized.endswith(".egg-info")
            or ".egg-info/" in normalized
        )

    @staticmethod
    def _sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _candidate_identity(
        candidate_head: str,
        bindings: list[dict[str, Any]],
        *,
        binding_scope: str,
    ) -> dict[str, Any]:
        binding_sha256 = canonical_manifest_validation_sha256(bindings)
        return {
            "head": candidate_head,
            "worktree_delta_sha256": binding_sha256,
            "source_binding_count": len(bindings),
            "source_binding_sha256": binding_sha256,
            "source_binding_scope": binding_scope,
        }

    @staticmethod
    def _validation_selection(
        scope: str,
        target_files: list[str],
        command_specs: list[dict[str, Any]],
        *,
        lane_assignments: list[str] | None = None,
    ) -> dict[str, Any]:
        assignments = list(lane_assignments or [_CANDIDATE_LANE] * len(command_specs))
        if len(assignments) != len(command_specs) or any(
            lane not in _VALIDATION_LANES for lane in assignments
        ):
            raise ValueError("validation lane assignments do not match command specs")
        return {
            "scope": scope,
            "target_files": list(target_files),
            "command_specs_sha256": canonical_manifest_validation_sha256(
                command_specs
            ),
            "lane_assignments": assignments,
            "lane_assignments_sha256": canonical_manifest_validation_sha256(
                assignments
            ),
            "classification_mechanism": "pytest_marker_partition",
            "marker": _HOST_FROZEN_MARKER,
            "candidate_expression": _CANDIDATE_MARKER_EXPRESSION,
            "host_expression": _HOST_MARKER_EXPRESSION,
            "fixed_node_list_used": False,
            "classification_exhaustive": {
                "value": True,
                "basis": "complementary_marker_expressions",
            },
        }

    @staticmethod
    def _manifest_source_bindings(
        manifest_validation: dict[str, Any],
    ) -> list[dict[str, Any]]:
        subjects = manifest_validation.get("subjects")
        if not isinstance(subjects, list):
            return []
        return [
            {
                "path": subject.get("path"),
                "present": True,
                "sha256": subject.get("sha256"),
            }
            for subject in subjects
            if isinstance(subject, dict)
        ]

    def _collect_worktree_delta_paths(
        self,
    ) -> tuple[list[str], dict[str, Any] | None]:
        """Return every non-ignored, source-eligible path in the worktree delta.

        Porcelain ``-z`` is used so spaces and rename pairs cannot be
        misparsed.  A rename contributes both its current path and its deleted
        predecessor; the binding builder below determines their present state
        from the actual worktree.
        """

        proc = subprocess.run(
            [
                "git",
                "status",
                "--porcelain=v1",
                "-z",
                "--untracked-files=all",
            ],
            cwd=self.project_root,
            capture_output=True,
            check=False,
            shell=False,
        )
        if proc.returncode != 0:
            return [], {
                "ok": False,
                "action": "preview",
                "error_code": "GIT_STATUS_FAILED",
                "message": "无法读取当前工作树差异。",
            }

        paths: set[str] = set()
        records = proc.stdout.split(b"\0")
        index = 0
        while index < len(records):
            record = records[index]
            index += 1
            if not record:
                continue
            if len(record) < 4:
                return [], {
                    "ok": False,
                    "action": "preview",
                    "error_code": "VALIDATION_CANDIDATE_DELTA_INCOMPLETE",
                    "message": "工作树差异记录无法完整解析，已拒绝候选验证。",
                }
            status = record[:2].decode("ascii", errors="replace")
            path_bytes = record[3:]
            path_text = os.fsdecode(path_bytes)
            normalized = self._normalize_repo_relative_path(path_text)
            if normalized is None:
                return [], {
                    "ok": False,
                    "action": "preview",
                    "error_code": "VALIDATION_CANDIDATE_DELTA_INCOMPLETE",
                    "message": "工作树存在无法安全绑定的候选路径。",
                }
            if self._path_policy.is_denied_source_path(normalized):
                if self._is_runtime_delta_path(normalized):
                    continue
                return [], {
                    "ok": False,
                    "action": "preview",
                    "error_code": "VALIDATION_CANDIDATE_DELTA_INCOMPLETE",
                    "message": "工作树存在未纳入候选绑定的非 runtime 改动。",
                }
            if not self._path_policy.is_allowed_source_path(normalized):
                return [], {
                    "ok": False,
                    "action": "preview",
                    "error_code": "VALIDATION_CANDIDATE_DELTA_INCOMPLETE",
                    "message": "工作树存在不在 source path policy 内的改动。",
                }
            paths.add(normalized)
            if "R" in status or "C" in status:
                if index >= len(records) or not records[index]:
                    return [], {
                        "ok": False,
                        "action": "preview",
                        "error_code": "VALIDATION_CANDIDATE_DELTA_INCOMPLETE",
                        "message": "rename/copy 差异缺少完整路径对。",
                    }
                old_text = os.fsdecode(records[index])
                index += 1
                old_normalized = self._normalize_repo_relative_path(old_text)
                if (
                    old_normalized is None
                    or self._is_runtime_delta_path(old_normalized)
                    or self._path_policy.is_denied_source_path(old_normalized)
                    or not self._path_policy.is_allowed_source_path(old_normalized)
                ):
                    if old_normalized and self._is_runtime_delta_path(old_normalized):
                        continue
                    return [], {
                        "ok": False,
                        "action": "preview",
                        "error_code": "VALIDATION_CANDIDATE_DELTA_INCOMPLETE",
                        "message": "rename/copy 差异包含无法纳入候选的路径。",
                    }
                paths.add(old_normalized)

        return sorted(paths), None

    def _build_full_worktree_candidate_bindings(
        self,
    ) -> tuple[list[dict[str, Any]], list[str], dict[str, Any] | None]:
        paths, path_error = self._collect_worktree_delta_paths()
        if path_error is not None:
            return [], [], path_error
        bindings, binding_error = self._build_candidate_source_bindings(paths)
        if binding_error is not None:
            return [], [], binding_error
        return bindings, paths, None

    def _build_candidate_source_bindings(
        self,
        paths: list[str],
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        """Bind target files to the current worktree bytes at preview time."""

        project_root = Path(self.project_root).resolve()
        bindings: list[dict[str, Any]] = []
        for relative in paths:
            normalized = self._normalize_repo_relative_path(relative)
            if (
                normalized is None
                or self._path_policy.is_denied_source_path(normalized)
            ):
                return [], {
                    "ok": False,
                    "action": "preview",
                    "error_code": "CANDIDATE_SOURCE_BINDING_INVALID",
                    "message": "候选验证文件路径不符合安全约束。",
                }
            source = project_root / normalized
            resolved_source = Path(os.path.realpath(source))
            try:
                contained = os.path.commonpath(
                    [str(resolved_source), str(project_root)]
                ) == str(project_root)
            except ValueError:
                contained = False
            if not contained or source.is_symlink():
                return [], {
                    "ok": False,
                    "action": "preview",
                    "error_code": "CANDIDATE_SOURCE_BINDING_INVALID",
                    "message": "候选验证文件不能通过符号链接逃逸项目目录。",
                }
            if source.exists() and not source.is_file():
                return [], {
                    "ok": False,
                    "action": "preview",
                    "error_code": "CANDIDATE_SOURCE_BINDING_INVALID",
                    "message": "候选验证目标必须是普通文件。",
                }
            present = source.is_file()
            bindings.append(
                {
                    "path": normalized,
                    "present": present,
                    "sha256": self._sha256_file(source) if present else None,
                }
            )
        return bindings, None

    def _source_bindings_for_artifact(
        self,
        artifact: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Return source bindings for a manifest or target-files artifact."""

        contract = artifact.get("manifest_validation")
        if isinstance(contract, dict):
            subjects = contract.get("subjects")
            if not isinstance(subjects, list):
                return []
            return [
                {
                    "path": subject.get("path"),
                    "present": True,
                    "sha256": subject.get("sha256"),
                }
                for subject in subjects
                if isinstance(subject, dict)
            ]
        bindings = artifact.get("candidate_source_bindings")
        return list(bindings) if isinstance(bindings, list) else []

    def _verify_candidate_source_bindings(
        self,
        artifact: dict[str, Any],
    ) -> bool:
        """Re-read bound worktree bytes before starting asynchronous execution."""

        bindings = self._source_bindings_for_artifact(artifact)
        binding_scope = artifact.get("candidate_delta_mode")
        identity = artifact.get("candidate_identity")
        if binding_scope in {"manifest_subjects", "full_allowed_worktree_delta"}:
            if not isinstance(identity, dict):
                return False
            binding_digest = canonical_manifest_validation_sha256(bindings)
            if (
                identity.get("source_binding_scope") != binding_scope
                or identity.get("source_binding_sha256") != binding_digest
                or identity.get("worktree_delta_sha256") != binding_digest
                or identity.get("source_binding_count") != len(bindings)
            ):
                return False
        if binding_scope == "full_allowed_worktree_delta":
            current_bindings, _paths, error = self._build_full_worktree_candidate_bindings()
            if error is not None or current_bindings != bindings:
                return False
        if not bindings:
            return True
        project_root = Path(self.project_root).resolve()
        for binding in bindings:
            if not isinstance(binding, dict):
                return False
            relative = binding.get("path")
            expected_present = binding.get("present")
            expected_sha256 = binding.get("sha256")
            if (
                not isinstance(relative, str)
                or not isinstance(expected_present, bool)
                or (expected_present and not isinstance(expected_sha256, str))
            ):
                return False
            normalized = self._normalize_repo_relative_path(relative)
            if (
                normalized is None
                or self._path_policy.is_denied_source_path(normalized)
            ):
                return False
            source = project_root / normalized
            resolved_source = Path(os.path.realpath(source))
            try:
                contained = os.path.commonpath(
                    [str(resolved_source), str(project_root)]
                ) == str(project_root)
            except ValueError:
                contained = False
            if not contained or source.is_symlink():
                return False
            present = source.is_file()
            if present != expected_present:
                return False
            if present and not hmac.compare_digest(
                self._sha256_file(source),
                expected_sha256,
            ):
                return False
            if not present and source.exists():
                return False
        return True

    def _collect_changed_files(self) -> tuple[list[str], dict[str, Any] | None]:
        files, error = self._collect_worktree_delta_paths()
        return files[:MAX_TARGET_FILES], error

    def _select_commands(
        self,
        scope: str,
        target_files: list[str],
    ) -> tuple[
        list[list[str]],
        list[dict[str, Any]],
        str,
        list[str],
        list[dict[str, Any]],
        list[str],
    ]:
        warnings: list[str] = []
        commands: list[list[str]] = []
        command_specs: list[dict[str, Any]] = []
        validation_groups: list[dict[str, Any]] = []
        lane_assignments: list[str] = []

        if scope == "current_version":
            acceptance, acceptance_warnings = self._current_acceptance_commands()
            warnings.extend(acceptance_warnings)
            if acceptance:
                command_specs.extend(acceptance[:MAX_COMMANDS])
                commands.extend([item["argv"] for item in command_specs])
                lane_assignments.extend([_CANDIDATE_LANE] * len(command_specs))
                validation_groups.append({"strategy": "plan_acceptance", "lane": _CANDIDATE_LANE, "files": [], "command_count": len(command_specs)})
                return commands, command_specs, "plan_acceptance", warnings, validation_groups, lane_assignments
            warnings.append("当前版本没有可用 acceptance_commands。")
            return [], [], "unsupported_strategy", warnings, validation_groups, lane_assignments

        if scope == "full":
            acceptance, acceptance_warnings = self._current_acceptance_commands()
            warnings.extend(acceptance_warnings)
            if acceptance:
                for spec in acceptance[:MAX_COMMANDS]:
                    command_specs.append(spec)
                    commands.append(spec["argv"])
                    lane_assignments.append(_CANDIDATE_LANE)
                validation_groups.append({"strategy": "plan_acceptance", "lane": _CANDIDATE_LANE, "files": [], "command_count": len(acceptance)})

            full_strategies = self._full_validation_strategies()
            for strategy in full_strategies:
                argv = strategy["argv"]
                spec = {
                    "argv": argv,
                    "timeout_seconds": self._normalize_timeout_seconds(
                        strategy.get("timeout_seconds", MAX_TIMEOUT_SECONDS)
                    ),
                    "continue_on_failure": True,
                }
                lane = strategy.get("lane", _CANDIDATE_LANE)
                if lane not in _VALIDATION_LANES:
                    raise ValueError("validation strategy has an unknown lane")
                command_specs.append(spec)
                commands.append(argv)
                lane_assignments.append(lane)
                validation_groups.append({"strategy": strategy["strategy"], "lane": lane, "files": [], "command_count": 1})

            if len(full_strategies) > 1:
                git_check = ["git", "diff", "--check"]
                spec = {"argv": git_check, "timeout_seconds": DEFAULT_TIMEOUT_SECONDS, "continue_on_failure": True}
                command_specs.append(spec)
                commands.append(git_check)
                lane_assignments.append(_CANDIDATE_LANE)
                validation_groups.append({"strategy": "git_diff_check", "lane": _CANDIDATE_LANE, "files": [], "command_count": 1})

            if not full_strategies:
                if acceptance:
                    warnings.append("full scope 不能仅依赖 plan acceptance_commands；未检测到 project-level 验证策略。")
                elif not acceptance_warnings:
                    warnings.append("未检测到受支持的 project 类型，无法确定 full 验证策略。")
                return [], [], "unsupported_strategy", warnings, [], []

            strategy_names = [g["strategy"] for g in validation_groups]
            overall_strategy = "+".join(strategy_names)

            return (
                commands[:MAX_COMMANDS],
                command_specs[:MAX_COMMANDS],
                overall_strategy,
                warnings,
                validation_groups,
                lane_assignments[:MAX_COMMANDS],
            )

        file_set = set(target_files)
        py_files = sorted([path for path in file_set if path.endswith(".py")])
        test_files = sorted([path for path in py_files if path.startswith("tests/test_")])
        host_lane_requested = (
            _HOST_FROZEN_TEST_FILE in test_files
            or bool(file_set & _HOST_FROZEN_TRIGGER_PATHS)
        )
        candidate_test_files = [
            path for path in test_files
            if path != _HOST_FROZEN_TEST_FILE
        ]
        detected = self._detect_project_types()
        if candidate_test_files:
            command = [self._python_executable(), "-m", "pytest", *candidate_test_files[:20], "-q"]
            commands.append(command)
            command_specs.extend(self._command_specs_for_commands([command]))
            lane_assignments.append(_CANDIDATE_LANE)
            validation_groups.append({"strategy": "python_targeted", "lane": _CANDIDATE_LANE, "files": candidate_test_files[:20], "command_count": 1})
            strategy = "python_targeted"
        elif host_lane_requested:
            strategy = "python_marker_partition"
        elif any(kind in detected for kind in ("node", "php", "go", "rust")):
            acceptance, acceptance_warnings = self._current_acceptance_commands()
            warnings.extend(acceptance_warnings)
            if acceptance:
                command_specs.extend(acceptance[:MAX_COMMANDS])
                commands.extend([item["argv"] for item in command_specs])
                lane_assignments.extend([_CANDIDATE_LANE] * len(acceptance))
                validation_groups.append({"strategy": "plan_acceptance", "lane": _CANDIDATE_LANE, "files": target_files, "command_count": len(command_specs)})
                strategy = "plan_acceptance"
            else:
                warnings.append("检测到非 Python 项目线索；请将验证命令写入 acceptance_commands。")
                strategy = "unsupported_strategy"
        else:
            strategy = "quick_static"

        if host_lane_requested:
            candidate_command = [
                self._python_executable(),
                "-m",
                "pytest",
                _HOST_FROZEN_TEST_FILE,
                "-q",
                "-m",
                _CANDIDATE_MARKER_EXPRESSION,
                "-rs",
            ]
            commands.append(candidate_command)
            command_specs.extend(self._command_specs_for_commands([candidate_command]))
            lane_assignments.append(_CANDIDATE_LANE)
            validation_groups.append({
                "strategy": "python_candidate_marker_partition",
                "lane": _CANDIDATE_LANE,
                "files": [_HOST_FROZEN_TEST_FILE],
                "marker": _HOST_FROZEN_MARKER,
                "marker_expression": _CANDIDATE_MARKER_EXPRESSION,
                "command_count": 1,
            })

            host_command = [
                self._python_executable(),
                "-m",
                "pytest",
                _HOST_FROZEN_TEST_FILE,
                "-q",
                "-m",
                _HOST_MARKER_EXPRESSION,
                "-rs",
            ]
            commands.append(host_command)
            command_specs.extend(self._command_specs_for_commands([host_command]))
            lane_assignments.append(_HOST_FROZEN_LANE)
            validation_groups.append({
                "strategy": "python_host_frozen_marker_partition",
                "lane": _HOST_FROZEN_LANE,
                "files": [_HOST_FROZEN_TEST_FILE],
                "marker": _HOST_FROZEN_MARKER,
                "marker_expression": _HOST_MARKER_EXPRESSION,
                "command_count": 1,
            })

        commands.append(["git", "diff", "--check"])
        command_specs.extend(self._command_specs_for_commands([["git", "diff", "--check"]]))
        lane_assignments.append(_CANDIDATE_LANE)
        validation_groups.append({"strategy": "quick_static", "lane": _CANDIDATE_LANE, "files": [], "command_count": 1})
        if not target_files and scope == "changed_files":
            warnings.append("没有检测到 changed files，执行通用 diff 检查。")
        return (
            commands[:MAX_COMMANDS],
            command_specs[:MAX_COMMANDS],
            strategy,
            warnings,
            validation_groups,
            lane_assignments[:MAX_COMMANDS],
        )

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
            if (
                parse_error
                or not self._is_supported_manifest_command(argv)
            ):
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
                "strategy": "python_candidate_full",
                "lane": _CANDIDATE_LANE,
                "argv": [
                    self._python_executable(),
                    "-m",
                    "pytest",
                    "tests",
                    "-q",
                    "-m",
                    _CANDIDATE_MARKER_EXPRESSION,
                    "-rs",
                ],
            })
            strategies.append({
                "strategy": "python_host_frozen",
                "lane": _HOST_FROZEN_LANE,
                "argv": [
                    self._python_executable(),
                    "-m",
                    "pytest",
                    _HOST_FROZEN_TEST_FILE,
                    "-q",
                    "-m",
                    _HOST_MARKER_EXPRESSION,
                    "-rs",
                ],
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
            marker_expression_pending = False
            for part in command[3:]:
                if marker_expression_pending:
                    if part not in {
                        _CANDIDATE_MARKER_EXPRESSION,
                        _HOST_MARKER_EXPRESSION,
                    }:
                        return False
                    marker_expression_pending = False
                    continue
                if part == "-m":
                    marker_expression_pending = True
                    continue
                if part.startswith("-"):
                    continue
                if self._normalize_repo_relative_path(part.split("::", 1)[0]) is None:
                    return False
            return not marker_expression_pending
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

    def _is_supported_manifest_command(self, command: Any) -> bool:
        """Accept only explicit validation argv families from review manifests."""

        if not self._is_safe_command(command):
            return False
        if command == ["git", "diff", "--check"]:
            return True
        first = command[0]
        if (
            first not in MANIFEST_PYTHON_EXECUTABLES
            and not (
                os.path.isabs(first)
                and first == self._python_executable()
            )
        ):
            return False
        if command == [first, "scripts/self_hosting_smoke.py"]:
            return True
        if command[1:3] == ["-m", "pytest"]:
            marker_expression_pending = False
            for part in command[3:]:
                if marker_expression_pending:
                    if part not in {
                        _CANDIDATE_MARKER_EXPRESSION,
                        _HOST_MARKER_EXPRESSION,
                    }:
                        return False
                    marker_expression_pending = False
                    continue
                if part == "-m":
                    marker_expression_pending = True
                    continue
                if part in {"-q", "-rs"}:
                    continue
                if part.startswith("-"):
                    return False
                target = part.split("::", 1)[0]
                normalized = self._normalize_repo_relative_path(target)
                if (
                    normalized is None
                    or self._path_policy.is_denied_source_path(normalized)
                ):
                    return False
            return not marker_expression_pending
        if command[1:3] == ["-m", "compileall"]:
            paths = list(command[3:])
            if paths and paths[0] == "-q":
                paths = paths[1:]
            if not paths:
                return False
            for part in paths:
                if part == ".":
                    continue
                if part.startswith("-"):
                    return False
                normalized = self._normalize_repo_relative_path(part)
                if (
                    normalized is None
                    or self._path_policy.is_denied_source_path(normalized)
                ):
                    return False
            return True
        if command[1:4] == ["-m", "ruff", "check"]:
            paths = command[4:]
            if not paths:
                return False
            for part in paths:
                if part.startswith("-"):
                    return False
                if part == ".":
                    continue
                normalized = self._normalize_repo_relative_path(part)
                if (
                    normalized is None
                    or self._path_policy.is_denied_source_path(normalized)
                ):
                    return False
            return True
        return False

    @staticmethod
    def _manifest_execution_command(
        command: list[str],
        candidate_head: str,
    ) -> list[str]:
        """Bind the declared clean-tree diff check to the candidate commit."""

        if command != ["git", "diff", "--check"]:
            return list(command)
        return [
            "git",
            "diff-tree",
            "--check",
            "--root",
            "-r",
            "-m",
            "--no-commit-id",
            "--no-ext-diff",
            "--no-textconv",
            candidate_head,
        ]

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

    def _bound_candidate_head(
        self,
        artifact: dict[str, Any],
    ) -> str | None:
        """Return the candidate HEAD for a canonical preview.

        Older private operator fixtures may contain an intentionally minimal
        target-files artifact with no command-spec binding.  Those records are
        kept on their legacy execution path for compatibility.  Every preview
        produced by this manager has command specs and is therefore required
        to execute from a clean detached candidate checkout.
        """

        command_specs = artifact.get("command_specs")
        if not isinstance(command_specs, list) or not command_specs:
            return None
        if artifact.get("scope") == "manifest_bound":
            return self._manifest_candidate_head(artifact)
        current_head = artifact.get("current_head")
        if not isinstance(current_head, str):
            return None
        normalized = current_head.strip().lower()
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
            return {
                "root": checkout,
                "parent": parent,
                "git": git,
                "candidate_head": candidate_head,
                "candidate_tree": candidate_tree,
                "source_before": source_before,
                "isolated_from_project_worktree": isolated,
                "source_overlays": [],
                "source_overlay_cleanup_complete": True,
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

    @staticmethod
    def _remove_overlay_path(path: Path) -> None:
        if path.is_symlink() or path.is_file():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()

    @staticmethod
    def _read_bound_source_bytes(source: Path) -> bytes:
        """Read one source binding through a no-follow descriptor when available."""

        flags = os.O_RDONLY
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(source, flags)
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise RuntimeError("candidate source overlay is not a file")
            with os.fdopen(descriptor, "rb") as handle:
                descriptor = -1
                return handle.read()
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    def _materialize_bound_file(
        self,
        *,
        source: Path,
        destination: Path,
        expected_sha256: str,
    ) -> None:
        """Atomically materialize exactly the bytes bound by the preview."""

        if _SHA256_RE.fullmatch(expected_sha256) is None:
            raise RuntimeError("candidate source binding digest is invalid")
        if source.is_symlink() or not source.is_file():
            raise RuntimeError("candidate source binding changed")
        source_mode = source.stat().st_mode
        source_bytes = self._read_bound_source_bytes(source)
        source_sha256 = hashlib.sha256(source_bytes).hexdigest()
        if not hmac.compare_digest(source_sha256, expected_sha256):
            raise RuntimeError("candidate source binding changed")

        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        descriptor: int | None = None
        try:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{destination.name}.",
                dir=str(destination.parent),
            )
            temporary_path = Path(temporary_name)
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = None
                handle.write(source_bytes)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary_path, stat.S_IMODE(source_mode))
            os.replace(temporary_path, destination)
            temporary_path = None
            if destination.is_symlink() or not destination.is_file():
                raise RuntimeError("candidate checkout target is not a file")
            destination_sha256 = self._sha256_file(destination)
            if not hmac.compare_digest(destination_sha256, expected_sha256):
                raise RuntimeError("candidate destination digest mismatch")
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if temporary_path is not None:
                try:
                    temporary_path.unlink()
                except FileNotFoundError:
                    pass

    def _apply_candidate_source_overlays(
        self,
        isolated_checkout: dict[str, Any],
        bindings: list[dict[str, Any]],
        *,
        binding_kind: str = "source_files",
    ) -> dict[str, Any]:
        """Overlay the preview-bound worktree bytes onto the detached checkout."""

        checkout = isolated_checkout.get("root")
        parent = isolated_checkout.get("parent")
        if not isinstance(checkout, Path) or not isinstance(parent, Path):
            raise RuntimeError("candidate source overlay root is unavailable")
        project_root = Path(self.project_root).resolve()
        candidate_root = checkout.resolve()
        backup_root = parent / "source-overlay-backups"
        entries: list[dict[str, Any]] = []
        isolated_checkout["source_overlays"] = entries
        isolated_checkout["source_overlay_cleanup_complete"] = not bool(bindings)
        summary = {
            "binding_kind": binding_kind,
            "file_count": len(bindings),
            "binding_sha256": canonical_manifest_validation_sha256(bindings),
            "source_hashes_verified": False,
            "cleanup_complete": not bool(bindings),
        }
        isolated_checkout["source_overlay_summary"] = summary
        try:
            for index, binding in enumerate(bindings):
                if not isinstance(binding, dict):
                    raise RuntimeError("candidate source binding is invalid")
                relative = binding.get("path")
                present = binding.get("present")
                expected_sha256 = binding.get("sha256")
                normalized = (
                    self._normalize_repo_relative_path(relative)
                    if isinstance(relative, str)
                    else None
                )
                if (
                    normalized is None
                    or self._path_policy.is_denied_source_path(normalized)
                    or not isinstance(present, bool)
                    or (present and not isinstance(expected_sha256, str))
                ):
                    raise RuntimeError("candidate source binding is invalid")
                source = project_root / normalized
                destination = candidate_root / normalized
                source_resolved = Path(os.path.realpath(source))
                destination_resolved = Path(os.path.realpath(destination))
                try:
                    source_contained = os.path.commonpath(
                        [str(source_resolved), str(project_root)]
                    ) == str(project_root)
                    destination_contained = os.path.commonpath(
                        [str(destination_resolved), str(candidate_root)]
                    ) == str(candidate_root)
                except ValueError:
                    source_contained = False
                    destination_contained = False
                if (
                    not source_contained
                    or not destination_contained
                    or source.is_symlink()
                    or destination.is_symlink()
                ):
                    raise RuntimeError("candidate source overlay escaped its checkout")
                source_present = source.is_file()
                if source_present != present:
                    raise RuntimeError("candidate source binding changed")
                if source.exists() and not source.is_file():
                    raise RuntimeError("candidate source overlay is not a file")
                if destination.exists() and not destination.is_file():
                    raise RuntimeError("candidate checkout target is not a file")

                existed = destination.is_file()
                backup: Path | None = None
                if existed:
                    backup_root.mkdir(parents=True, exist_ok=True)
                    backup = backup_root / f"{index:04d}.backup"
                    shutil.copy2(destination, backup)
                entries.append(
                    {
                        "path": normalized,
                        "existed": existed,
                        "backup": backup,
                    }
                )
                if source_present:
                    self._materialize_bound_file(
                        source=source,
                        destination=destination,
                        expected_sha256=expected_sha256,
                    )
                else:
                    if existed:
                        self._remove_overlay_path(destination)
                    if destination.exists() or destination.is_symlink():
                        raise RuntimeError(
                            "candidate deletion binding was not materialized"
                        )
            summary["source_hashes_verified"] = True
            summary["cleanup_complete"] = False
            isolated_checkout["source_overlay_cleanup_complete"] = False
            return summary
        except Exception as exc:
            try:
                self._restore_candidate_source_overlays(isolated_checkout)
            except Exception:
                pass
            raise RuntimeError("candidate source overlay preparation failed") from exc

    def _restore_candidate_source_overlays(
        self,
        isolated_checkout: dict[str, Any],
    ) -> None:
        if isolated_checkout.get("source_overlay_cleanup_complete") is True:
            return
        checkout = isolated_checkout.get("root")
        if not isinstance(checkout, Path):
            raise RuntimeError("candidate source overlay root is unavailable")
        candidate_root = checkout.resolve()
        entries = isolated_checkout.get("source_overlays")
        if not isinstance(entries, list):
            raise RuntimeError("candidate source overlay state is invalid")
        try:
            for entry in reversed(entries):
                if not isinstance(entry, dict):
                    raise RuntimeError("candidate source overlay state is invalid")
                relative = entry.get("path")
                if not isinstance(relative, str):
                    raise RuntimeError("candidate source overlay path is invalid")
                normalized = self._normalize_repo_relative_path(relative)
                if normalized is None:
                    raise RuntimeError("candidate source overlay path is invalid")
                destination = candidate_root / normalized
                resolved_destination = Path(os.path.realpath(destination))
                try:
                    contained = os.path.commonpath(
                        [str(resolved_destination), str(candidate_root)]
                    ) == str(candidate_root)
                except ValueError:
                    contained = False
                if not contained:
                    raise RuntimeError("candidate source overlay escaped its checkout")
                if destination.exists() or destination.is_symlink():
                    self._remove_overlay_path(destination)
                if entry.get("existed") is True:
                    backup = entry.get("backup")
                    if not isinstance(backup, Path) or not backup.is_file():
                        raise RuntimeError("candidate source overlay backup is missing")
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(backup, destination)
                current = destination.parent
                while current != candidate_root and current != current.parent:
                    try:
                        current.rmdir()
                    except OSError:
                        break
                    current = current.parent
        except Exception:
            raise
        isolated_checkout["source_overlay_cleanup_complete"] = True
        summary = isolated_checkout.get("source_overlay_summary")
        if isinstance(summary, dict):
            summary["cleanup_complete"] = True

    def _remove_isolated_execution_overlays(
        self,
        isolated_checkout: dict[str, Any],
    ) -> None:
        checkout = isolated_checkout.get("root")
        git = isolated_checkout.get("git")
        if (
            not isinstance(checkout, Path)
            or git is None
        ):
            raise RuntimeError(
                "isolated validation overlay cleanup is unavailable"
            )
        validation_venv = isolated_checkout.get("validation_venv")
        if validation_venv is not None:
            if not isinstance(validation_venv, Path):
                raise RuntimeError(
                    "isolated validation virtualenv overlay is invalid"
                )
            overlay = checkout / ".venv"
            if overlay.resolve() != validation_venv.resolve():
                raise RuntimeError(
                    "isolated validation virtualenv overlay escaped the checkout"
                )
            if overlay.is_symlink():
                overlay.unlink()
            elif overlay.is_dir():
                shutil.rmtree(overlay)
            elif overlay.exists():
                overlay.unlink()
        self._restore_candidate_source_overlays(isolated_checkout)
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
        lane: str = _CANDIDATE_LANE,
        host_environment: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        execution_root = os.path.abspath(cwd or self.project_root)
        effective_command = list(command)
        validation_environment = _VALIDATION_ENVIRONMENT_CONTEXT.get()
        if lane == _HOST_FROZEN_LANE:
            process_command = list(effective_command)
            environment = dict(host_environment or {})
            if not environment:
                return {
                    "returncode": 126,
                    "stdout": "",
                    "stderr": "frozen host toolchain environment unavailable",
                    "error_code": "FROZEN_TOOLCHAIN_AUTHORITY_UNAVAILABLE",
                }
        elif validation_environment is not None:
            process_command = rewrite_command_for_validation_environment(
                effective_command,
                validation_environment.venv_dir,
            )
            environment = dict(validation_environment.env)
        else:
            process_command = list(effective_command)
            environment = build_validation_subprocess_environment(
                candidate_root=Path(execution_root),
                parent_environment=dict(os.environ),
                forbidden_roots=(Path(self.project_root).resolve(),),
            )
        try:
            proc = subprocess.run(
                process_command,
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

    @staticmethod
    def _candidate_evidence_is_valid(data: dict[str, Any]) -> bool:
        identity = data.get("candidate_identity")
        selection = data.get("validation_selection")
        if not isinstance(identity, dict) or not isinstance(selection, dict):
            return False
        head = identity.get("head")
        source_scope = identity.get("source_binding_scope")
        source_binding_sha256 = identity.get("source_binding_sha256")
        worktree_delta_sha256 = identity.get("worktree_delta_sha256")
        source_binding_count = identity.get("source_binding_count")
        if (
            not isinstance(head, str)
            or _FULL_GIT_OBJECT_ID_RE.fullmatch(head) is None
            or source_scope not in {"manifest_subjects", "full_allowed_worktree_delta"}
            or not isinstance(source_binding_sha256, str)
            or _SHA256_RE.fullmatch(source_binding_sha256) is None
            or not isinstance(worktree_delta_sha256, str)
            or _SHA256_RE.fullmatch(worktree_delta_sha256) is None
            or source_binding_sha256 != worktree_delta_sha256
            or isinstance(source_binding_count, bool)
            or not isinstance(source_binding_count, int)
            or source_binding_count < 0
        ):
            return False
        scope = selection.get("scope")
        target_files = selection.get("target_files")
        command_specs_sha256 = selection.get("command_specs_sha256")
        classification_exhaustive = selection.get("classification_exhaustive")
        return (
            scope in VALID_SCOPES | {"manifest_bound"}
            and isinstance(target_files, list)
            and all(isinstance(item, str) for item in target_files)
            and isinstance(command_specs_sha256, str)
            and _SHA256_RE.fullmatch(command_specs_sha256) is not None
            and selection.get("classification_mechanism")
            == "pytest_marker_partition"
            and selection.get("marker") == _HOST_FROZEN_MARKER
            and selection.get("candidate_expression")
            == _CANDIDATE_MARKER_EXPRESSION
            and selection.get("host_expression") == _HOST_MARKER_EXPRESSION
            and selection.get("fixed_node_list_used") is False
            and isinstance(classification_exhaustive, dict)
            and classification_exhaustive.get("value") is True
            and classification_exhaustive.get("basis")
            == "complementary_marker_expressions"
        )

    @staticmethod
    def _dual_lane_evidence_is_valid(data: dict[str, Any]) -> bool:
        lanes = data.get("validation_lanes")
        aggregate = data.get("aggregate")
        if not isinstance(lanes, dict) or set(lanes) != {
            _CANDIDATE_LANE,
            _HOST_FROZEN_LANE,
        }:
            return False
        if not isinstance(aggregate, dict) or set(aggregate) != {
            "status",
            "lane_result_digest",
            "both_lanes_required",
            "classification_exhaustive",
            "classification_basis",
        }:
            return False
        if aggregate.get("status") not in {"passed", "failed", "incomplete"}:
            return False
        if not isinstance(aggregate.get("lane_result_digest"), str) or _SHA256_RE.fullmatch(
            aggregate["lane_result_digest"]
        ) is None:
            return False
        if (
            not isinstance(aggregate.get("both_lanes_required"), bool)
            or aggregate.get("classification_exhaustive") is not True
            or aggregate.get("classification_basis")
            != "complementary_marker_expressions"
        ):
            return False
        for lane, payload in lanes.items():
            if not isinstance(payload, dict):
                return False
            required = {
                "status",
                "result_sha256",
                "command_specs_sha256",
                "candidate_delta_sha256",
                "selected_test_count",
                "skipped_count",
                "allowed_skip_count",
                "unexpected_skip_count",
                "required_skipped_count",
                "module_provenance",
            }
            if lane == _HOST_FROZEN_LANE:
                required |= {
                    "frozen_toolchain_record_sha256",
                    "environment_root_binding_sha256",
                    "total_host_venv_bytecode_count",
                    "record_owned_preimport_bytecode_count",
                    "unrelated_bytecode_count",
                    "bytecode_deleted",
                    "environment_kind",
                    "strict_measure_passed",
                }
            if set(payload) != required:
                return False
            if payload.get("status") not in {"passed", "failed", "blocked", "incomplete", "not_required"}:
                return False
            for key in ("result_sha256", "command_specs_sha256"):
                value = payload.get(key)
                if value is not None and (
                    not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None
                ):
                    return False
            delta = payload.get("candidate_delta_sha256")
            if delta is not None and (
                not isinstance(delta, str) or _SHA256_RE.fullmatch(delta) is None
            ):
                return False
            if payload.get("module_provenance") is not None and not isinstance(
                payload.get("module_provenance"), bool
            ):
                return False
            for count_key in (
                "selected_test_count",
                "skipped_count",
                "allowed_skip_count",
                "unexpected_skip_count",
                "required_skipped_count",
            ):
                count = payload.get(count_key)
                if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                    return False
            if lane == _HOST_FROZEN_LANE:
                for key in (
                    "frozen_toolchain_record_sha256",
                    "environment_root_binding_sha256",
                ):
                    value = payload.get(key)
                    if value is not None and (
                        not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None
                    ):
                        return False
                for count_key in (
                    "total_host_venv_bytecode_count",
                    "record_owned_preimport_bytecode_count",
                    "unrelated_bytecode_count",
                ):
                    count = payload.get(count_key)
                    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                        return False
                if not isinstance(payload.get("bytecode_deleted"), bool):
                    return False
                if payload.get("environment_kind") not in {
                    None,
                    "active_verified",
                    "ephemeral_verified",
                }:
                    return False
                if not isinstance(payload.get("strict_measure_passed"), bool):
                    return False
        return True

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
                set(data)
                not in {
                    _RUN_RESULT_FIELDS,
                    _RUN_RESULT_FIELDS
                    - {"candidate_identity", "validation_selection"},
                    _LEGACY_RUNNING_FIELDS,
                }
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
            if (
                set(data) == _RUN_RESULT_FIELDS
                and not self._candidate_evidence_is_valid(data)
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
            set(data)
            not in {
                _TERMINAL_RUN_RESULT_FIELDS,
                _LEGACY_TERMINAL_FIELDS,
            }
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
        if (
            set(data) == _TERMINAL_RUN_RESULT_FIELDS
            and (
                not self._candidate_evidence_is_valid(data)
                or not self._dual_lane_evidence_is_valid(data)
            )
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
