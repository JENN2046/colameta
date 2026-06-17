import json
import os
import re
import shlex
import subprocess
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath
from typing import Any

from runner.core_confirmation import (
    confirmation_apply_guard,
    confirmation_guard_reports_expired_before_mismatch,
)
from runner.current_version import load_current_version
from runner.path_policy import RunnerPathPolicy
from runner.plan_loader import PlanLoader
from runner.runner_paths import resolve_project_runner_path


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
        artifact = guard["payload"]
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

        return {
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
            self._write_run_result(run_id, run_record)

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
        for index, spec in enumerate(command_specs):
            command = spec.get("argv") if isinstance(spec, dict) else None
            timeout_seconds = self._normalize_timeout_seconds(spec.get("timeout_seconds") if isinstance(spec, dict) else None)
            continue_on_failure = bool(spec.get("continue_on_failure", False)) if isinstance(spec, dict) else False
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
            result = self._run_command(command, timeout_seconds=timeout_seconds)
            stdout = result["stdout"]
            stderr = result["stderr"]
            remaining = max(0, MAX_TOTAL_OUTPUT_CHARS - total_output_chars)
            per_stream_limit = min(MAX_STDOUT_CHARS, remaining)
            stdout, stdout_truncated = _truncate(stdout, per_stream_limit)
            total_output_chars += len(stdout)
            remaining = max(0, MAX_TOTAL_OUTPUT_CHARS - total_output_chars)
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

        status = "passed" if not failed_indexes else "failed"
        completed_at = _utc_now()
        run_record = {
            "run_id": run_id,
            "preview_id": preview_id,
            "action": "run",
            "status": status,
            "passed": status == "passed",
            "scope": artifact.get("scope"),
            "target_files": artifact.get("target_files", []),
            "strategy": artifact.get("strategy"),
            "validation_groups": artifact.get("validation_groups", []),
            "command_results": command_results,
            "failed_command_indexes": failed_indexes,
            "failed_command_index": failed_indexes[0] if failed_indexes else None,
            "output_summary": {
                "total_output_chars": total_output_chars,
                "redacted": True,
                "truncated": total_output_chars >= MAX_TOTAL_OUTPUT_CHARS,
            },
            "started_at": _iso(started_at),
            "completed_at": _iso(completed_at),
            "duration_seconds": max(0.0, (completed_at - started_at).total_seconds()),
        }
        self._write_run_result(run_id, run_record)

    def _initial_run_record(
        self,
        run_id: str,
        preview_id: str,
        artifact: dict[str, Any],
        commands: list[list[str]],
        started_at: datetime,
    ) -> dict[str, Any]:
        return {
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
        }

    def status(self, params: dict[str, Any]) -> dict[str, Any]:
        run_id = self._validate_run_id(params.get("run_id"))
        if run_id is None:
            return {"ok": False, "action": "status", "error_code": "INVALID_RUN_ID", "message": "status 需要合法 run_id。"}
        path = self._run_result_path(run_id)
        if not os.path.isfile(path):
            return {"ok": False, "action": "status", "error_code": "RUN_NOT_FOUND", "message": "run_id 不存在。"}
        try:
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
            if not isinstance(data, dict):
                raise ValueError("invalid result")
        except Exception:
            return {"ok": False, "action": "status", "error_code": "RUN_RESULT_INVALID", "message": "run result 无法读取。"}
        data["action"] = "status"
        data["ok"] = True
        return data

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

    def _run_command(self, command: list[str], *, timeout_seconds: int) -> dict[str, Any]:
        try:
            proc = subprocess.run(
                command,
                cwd=self.project_root,
                capture_output=True,
                text=True,
                check=False,
                shell=False,
                timeout=timeout_seconds,
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

    def _write_run_result(self, run_id: str, result: dict[str, Any]) -> str:
        os.makedirs(self._runs_root, exist_ok=True)
        path = self._run_result_path(run_id)
        tmp_path = f"{path}.{uuid.uuid4().hex[:8]}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp_path, path)
        return os.path.relpath(path, self.project_root)

    def _is_expired(self, expires_at: str) -> bool:
        if not expires_at:
            return False
        try:
            normalized = expires_at.replace("Z", "+00:00")
            return _utc_now() > datetime.fromisoformat(normalized)
        except Exception:
            return False
