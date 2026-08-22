from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.request import Request

from runner.http_url_policy import HTTPRedirectPolicy, open_http_url
from runner.mcp_github_delivery import MCPGitHubDeliveryManager
from runner.runtime_observability import git_checkout_metadata


MANAGED_RUNTIME_CLOSEOUT_WORKFLOW = "managed_runtime_closeout"
COLAMETA_STABLE_LOCAL_TARGET = "colameta_stable_local"
CANONICAL_REPOSITORY = "JENN2046/colameta"
CANONICAL_STABLE_CHECKOUT = "/home/jenn/tools/colameta"
CANONICAL_STABLE_SERVICE = "colameta-stable.service"
CANONICAL_STABLE_HEALTH_URL = "http://127.0.0.1:8766/healthz"
CANONICAL_EXTERNAL_RUNTIME_SERVICE = "colameta-mcp-remote.service"
CANONICAL_EXTERNAL_RUNTIME_HEALTH_URL = "http://127.0.0.1:8767/healthz"
CANONICAL_CI_WORKFLOW_PATH = ".github/workflows/ci.yml"

CommandRunner = Callable[[list[str], str], subprocess.CompletedProcess[str]]
HealthReader = Callable[[], dict[str, Any]]

_FULL_GIT_OBJECT_ID_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
_SS_OWNER_METADATA_RE = re.compile(
    r'users:\(\(\"(?P<process_name>[A-Za-z0-9_.+-]+)\",'
    r'pid=(?P<pid>[1-9][0-9]{0,9}),fd=(?P<fd>0|[1-9][0-9]{0,9})\)\)'
)


# Exact `systemctl show` property contract.  The parser admits no other key,
# so any property added to a future command must also extend this set and the
# per-property grammar below (state fields or strict ASCII decimal fields).
_SYSTEMCTL_SHOW_EXPECTED_PROPERTIES = frozenset(
    {"ActiveState", "SubState", "MainPID"}
)
_SYSTEMCTL_STATE_PROPERTIES = frozenset({"ActiveState", "SubState"})
_SYSTEMCTL_PID_PROPERTIES = frozenset({"MainPID"})

# Strict ASCII decimal grammar: either "0" or a non-zero digit followed by
# ASCII digits.  This intentionally rejects Unicode digits (Arabic, full-width,
# superscripts), signs, separators, whitespace, and trailing junk.  The same
# grammar is used for every host-observed numeric authority field.
_ASCII_DECIMAL_RE = re.compile(r"(?:0|[1-9][0-9]*)")


def _is_strict_ascii_field_value(value: Any) -> bool:
    """Admit a non-empty printable-ASCII field with no surrounding whitespace."""

    if not isinstance(value, str) or not value:
        return False
    if value != value.strip():
        return False
    return all(0x20 <= ord(ch) <= 0x7E for ch in value)


def _parse_systemctl_show_exact(
    stdout: str,
    *,
    expected_properties: frozenset[str] = _SYSTEMCTL_SHOW_EXPECTED_PROPERTIES,
    state_properties: frozenset[str] = _SYSTEMCTL_STATE_PROPERTIES,
    pid_properties: frozenset[str] = _SYSTEMCTL_PID_PROPERTIES,
) -> dict[str, str] | None:
    """Strictly parse a complete ``systemctl show`` evidence blob.

    Returns the parsed ``key -> value`` map only when the entire stdout is
    consumed: every line is ``ASCII_KEY "=" VALUE``, the key is an exact member
    of ``expected_properties``, every expected key appears exactly once, no
    unknown/duplicate/malformed/empty line exists, and every value satisfies
    its per-property grammar (state fields or strict ASCII decimal).  Returns
    ``None`` (fail closed) on any deviation.
    """

    if not isinstance(stdout, str):
        return None
    expected = set(expected_properties)
    known_grammars = set(state_properties) | set(pid_properties)
    if not expected or not expected.issubset(known_grammars):
        return None
    lines = stdout.splitlines()
    if not lines:
        return None
    seen: set[str] = set()
    values: dict[str, str] = {}
    for line in lines:
        if not line:
            return None
        key, separator, value = line.partition("=")
        if not separator or not key:
            return None
        if key not in expected or key in seen:
            return None
        seen.add(key)
        values[key] = value
    if seen != expected:
        return None
    for key in expected:
        value = values[key]
        if key in state_properties:
            if not _is_strict_ascii_field_value(value):
                return None
        elif key in pid_properties:
            if _ASCII_DECIMAL_RE.fullmatch(value) is None:
                return None
        else:  # pragma: no cover - guarded by expected subset check above
            return None
    return values


def _normalize_git_object_identity(value: Any) -> str | None:
    """Admit only a complete full-length Git object identity."""

    if not isinstance(value, str):
        return None
    normalized = value.lower()
    return normalized if _FULL_GIT_OBJECT_ID_RE.fullmatch(normalized) else None


def _parse_ss_owner_metadata(metadata: str) -> tuple[int, ...] | None:
    """Parse one complete, unambiguous ss process-owner token."""

    match = _SS_OWNER_METADATA_RE.fullmatch(metadata)
    if match is None:
        return None
    try:
        owner_pid = int(match.group("pid"))
        int(match.group("fd"))
    except ValueError:
        return None
    return (owner_pid,)


def _parse_listener_rows(
    output: str,
) -> list[tuple[str, int, tuple[int, ...]]] | None:
    """Parse ss listener rows without combining evidence across rows."""

    rows: list[tuple[str, int, tuple[int, ...]]] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        columns = line.split(maxsplit=5)
        if len(columns) < 5 or columns[0] != "LISTEN":
            return None
        local_endpoint = columns[3]
        if local_endpoint.startswith("["):
            closing = local_endpoint.rfind("]:")
            if closing < 0:
                return None
            address = local_endpoint[1:closing]
            port_text = local_endpoint[closing + 2 :]
        else:
            address, separator, port_text = local_endpoint.rpartition(":")
            if not separator or not address:
                return None
        if _ASCII_DECIMAL_RE.fullmatch(port_text) is None:
            return None
        if len(columns) != 6:
            return None
        owner_pids = _parse_ss_owner_metadata(columns[5])
        if owner_pids is None:
            return None
        rows.append((address, int(port_text), owner_pids))
    return rows


def _listener_matches_service(
    output: str,
    *,
    expected_address: str,
    expected_port: int,
    main_pid: int,
) -> bool:
    """Require one exact listener row owned only by the service MainPID."""

    if main_pid <= 0:
        return False
    rows = _parse_listener_rows(output)
    if rows is None or len(rows) != 1:
        return False
    address, port, owner_pids = rows[0]
    return (
        address == expected_address
        and port == expected_port
        and owner_pids == (main_pid,)
    )


class MCPManagedRuntimeCloseoutManager:
    """Project exact delivery/runtime truth without owning promotion authority."""

    def __init__(
        self,
        project_root: str,
        *,
        project_name: str,
        project_mode: str = "managed",
        command_runner: CommandRunner | None = None,
        health_reader: HealthReader | None = None,
        external_health_reader: HealthReader | None = None,
        stable_checkout: str = CANONICAL_STABLE_CHECKOUT,
        github_manager_factory: Callable[..., MCPGitHubDeliveryManager] = MCPGitHubDeliveryManager,
    ):
        self.project_root = os.path.abspath(os.path.expanduser(project_root))
        self.project_name = project_name
        self.project_mode = project_mode
        self._command_runner = command_runner or self._subprocess_run
        self._health_reader = health_reader or self._read_health
        self._external_health_reader = (
            external_health_reader or self._read_external_health
        )
        self._stable_checkout = os.path.abspath(stable_checkout)
        self._github_manager_factory = github_manager_factory

    def status(self, *, runtime_target: str) -> dict[str, Any]:
        target = str(runtime_target or "").strip()
        if target != COLAMETA_STABLE_LOCAL_TARGET:
            return self._blocked("RUNTIME_TARGET_UNSUPPORTED")
        if self.project_mode != "managed":
            return self._blocked("RUNTIME_TARGET_PROJECT_MISMATCH")

        project, project_error = self._project_truth()
        if project_error is not None:
            return self._blocked(project_error, project=project)
        ci = self._exact_main_ci(project)
        if ci.get("state") != "PASS":
            return self._blocked(self._ci_blocker(ci), project=project, ci=ci)

        runtime, runtime_error = self._runtime_truth()
        if runtime_error is not None:
            return self._blocked(
                runtime_error,
                project=project,
                ci=ci,
                runtime_target=runtime,
            )

        external_runtime, external_runtime_error = self._external_runtime_truth()
        if external_runtime_error is not None:
            return self._blocked(
                external_runtime_error,
                project=project,
                ci=ci,
                runtime_target=runtime,
                external_runtime=external_runtime,
            )

        candidate_head = str(project["head"])
        stable_head = str(runtime["checkout_head"])
        external_head = str(external_runtime["runtime_project_checkout_head"])
        if stable_head == candidate_head and external_head == candidate_head:
            if runtime.get("exact_loaded_code_verified") is not True:
                return self._blocked(
                    "RUNTIME_EXACT_HEAD_FRESHNESS_UNVERIFIED",
                    project=project,
                    ci=ci,
                    runtime_target=runtime,
                    external_runtime=external_runtime,
                )
            if external_runtime.get("exact_loaded_code_verified") is not True:
                return self._blocked(
                    "EXTERNAL_RUNTIME_EXACT_HEAD_FRESHNESS_UNVERIFIED",
                    project=project,
                    ci=ci,
                    runtime_target=runtime,
                    external_runtime=external_runtime,
                )
            return self._result(
                state="RUNTIME_ALREADY_CURRENT",
                project=project,
                ci=ci,
                runtime=runtime,
                external_runtime=external_runtime,
                delivery_state="DELIVERY_COMPLETE",
            )

        observed_at = datetime.now(timezone.utc).isoformat()
        required_targets = [
            target
            for target, current_head in (
                (COLAMETA_STABLE_LOCAL_TARGET, stable_head),
                ("colameta_external_web_gpt_mcp", external_head),
            )
            if current_head != candidate_head
        ]
        handoff = {
            "mode": "external",
            "target": (
                required_targets[0]
                if len(required_targets) == 1
                else "multiple_runtime_targets"
            ),
            "candidate_head": candidate_head,
            "observed_origin_main": project["origin_main_head"],
            "stable_before": {
                "checkout_head": runtime["checkout_head"],
                "loaded_runtime_head": runtime["loaded_runtime_head"],
                "service_state": runtime["service_state"],
                "pid": runtime["pid"],
                "package_matches_checkout": runtime["package_matches_checkout"],
                "healthy": runtime["healthy"],
            },
            "external_runtime_before": {
                "runtime_project_checkout_head": external_runtime[
                    "runtime_project_checkout_head"
                ],
                "loaded_runtime_head": external_runtime["loaded_runtime_head"],
                "service_state": external_runtime["service_state"],
                "pid": external_runtime["pid"],
                "package_matches_checkout": external_runtime[
                    "package_matches_checkout"
                ],
                "healthy": external_runtime["healthy"],
            },
            "required_targets": required_targets,
            "observed_at": observed_at,
            "authority": {
                "colaMeta_can_apply": False,
                "privileged_controller_available": False,
                "generic_sudo_not_product_authority": True,
            },
            "requirement": {
                "fresh_recheck_before_external_promotion": True,
            },
        }
        return self._result(
            state="READY_FOR_EXTERNAL_RUNTIME_PROMOTION",
            project=project,
            ci=ci,
            runtime=runtime,
            external_runtime=external_runtime,
            external_handoff=handoff,
        )

    def _project_truth(self) -> tuple[dict[str, Any], str | None]:
        metadata = git_checkout_metadata(self.project_root)
        branch = str(metadata.get("branch") or "")
        head = _normalize_git_object_identity(metadata.get("head"))
        origin = self._git(self.project_root, "remote", "get-url", "origin")
        repository = (
            MCPGitHubDeliveryManager._normalize_github_origin(origin.stdout.strip())
            if origin.returncode == 0
            else None
        )
        status = self._git(
            self.project_root,
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
        )
        remote = self._git(
            self.project_root,
            "ls-remote",
            "--exit-code",
            "origin",
            "refs/heads/main",
        )
        remote_head: str | None = None
        if remote.returncode == 0:
            parts = remote.stdout.strip().split()
            if len(parts) == 2 and parts[1] == "refs/heads/main":
                remote_head = _normalize_git_object_identity(parts[0])
        project = {
            "identity": "canonical_colameta_repository",
            "name": self.project_name,
            "repository": repository,
            "mode": self.project_mode,
            "branch": branch,
            "head": head,
            "worktree_clean": status.returncode == 0 and not status.stdout,
            "origin_main_head": remote_head,
            "ahead": 0 if head and head == remote_head else None,
            "behind": 0 if head and head == remote_head else None,
        }
        if repository != CANONICAL_REPOSITORY:
            return project, "RUNTIME_TARGET_PROJECT_MISMATCH"
        if branch != "main":
            return project, "RUNTIME_DELIVERY_BRANCH_INVALID"
        if status.returncode != 0 or status.stdout:
            return project, "RUNTIME_DELIVERY_WORKTREE_DIRTY"
        if head is None or remote_head is None:
            return project, "RUNTIME_DELIVERY_HEAD_UNRESOLVED"
        if head != remote_head:
            return project, "RUNTIME_DELIVERY_HEAD_DRIFT"
        return project, None

    def _exact_main_ci(self, project: dict[str, Any]) -> dict[str, Any]:
        manager = self._github_manager_factory(
            self.project_root,
            command_runner=self._command_runner,
        )
        return manager.observe_exact_ci(
            repository=str(project["repository"]),
            head_sha=str(project["head"]),
            event="push",
            branch="main",
            workflow_path=CANONICAL_CI_WORKFLOW_PATH,
        )

    @staticmethod
    def _ci_blocker(ci: dict[str, Any]) -> str:
        state = str(ci.get("state") or "")
        if state == "INCONSISTENT":
            return "GITHUB_PROVIDER_STATE_INCONSISTENCY"
        if state == "BLOCKED":
            return "RUNTIME_EXACT_HEAD_CI_FAILED"
        if state == "WAITING":
            return "RUNTIME_EXACT_HEAD_CI_PENDING"
        return str(ci.get("error_code") or "RUNTIME_EXACT_HEAD_CI_UNVERIFIED")

    def _runtime_truth(self) -> tuple[dict[str, Any], str | None]:
        metadata = git_checkout_metadata(self._stable_checkout)
        stable_head = _normalize_git_object_identity(metadata.get("head"))
        status = self._git(
            self._stable_checkout,
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
        )
        origin = self._git(self._stable_checkout, "remote", "get-url", "origin")
        stable_origin = origin.stdout.strip() if origin.returncode == 0 else ""
        stable_repository = MCPGitHubDeliveryManager._normalize_github_origin(
            stable_origin
        )
        stable_origin_is_canonical = stable_repository == CANONICAL_REPOSITORY
        if not stable_origin_is_canonical and os.path.isabs(stable_origin):
            stable_origin_is_canonical = (
                os.path.realpath(stable_origin) == os.path.realpath(self.project_root)
            )
        try:
            health = self._health_reader()
        except Exception:
            health = {}
        service = self._service_truth()
        loaded_head_raw = health.get("loaded_runtime_head")
        loaded_head = _normalize_git_object_identity(loaded_head_raw)
        loaded_head_valid = loaded_head_raw is None or loaded_head is not None
        runtime_checkout_head = _normalize_git_object_identity(
            health.get("runtime_project_checkout_head")
        )
        package_matches = health.get("installed_package_matches_project_checkout") is True
        source_clean = health.get("installed_package_project_source_clean") is True
        verification_match = health.get("installed_package_verification_status") == "match"
        stale = health.get("runtime_loaded_code_stale")
        reload_needed = health.get("reload_needed_for_verification")
        pid = service.get("main_pid")
        healthy = (
            health.get("ok") is True
            and service.get("active") is True
            and service.get("listener_owned") is True
        )
        checkout_coherent = stable_head is not None and runtime_checkout_head == stable_head
        loaded_coherent = loaded_head_valid and loaded_head in {None, stable_head}
        exact_loaded_code_verified = bool(
            healthy
            and checkout_coherent
            and loaded_coherent
            and package_matches
            and source_clean
            and verification_match
            and stale is False
            and reload_needed is False
        )
        runtime = {
            "id": COLAMETA_STABLE_LOCAL_TARGET,
            "checkout_identity": "canonical_colameta_stable_checkout",
            "checkout_head": stable_head,
            "checkout_clean": status.returncode == 0 and not status.stdout,
            "service_identity": CANONICAL_STABLE_SERVICE,
            "service_state": "active" if healthy else "unhealthy_or_unavailable",
            "pid": pid if isinstance(pid, int) and pid > 0 else None,
            "loaded_runtime_head": loaded_head,
            "runtime_project_checkout_head": runtime_checkout_head,
            "package_matches_checkout": package_matches,
            "package_source_clean": source_clean,
            "package_verification_status": health.get("installed_package_verification_status"),
            "runtime_loaded_code_stale": stale,
            "reload_needed_for_verification": reload_needed,
            "reload_awareness_reason": health.get("reload_awareness_reason"),
            "healthy": healthy,
            "exact_loaded_code_verified": exact_loaded_code_verified,
        }
        if not stable_origin_is_canonical:
            return runtime, "RUNTIME_TARGET_IDENTITY_UNAVAILABLE"
        if status.returncode != 0 or status.stdout or stable_head is None:
            return runtime, "RUNTIME_TARGET_CHECKOUT_UNSAFE"
        if not healthy:
            return runtime, "RUNTIME_TARGET_UNHEALTHY"
        if not package_matches or not source_clean or not verification_match:
            return runtime, "RUNTIME_PACKAGE_PROVENANCE_MISMATCH"
        if stale is not False or reload_needed is not False:
            return runtime, "RUNTIME_FRESHNESS_INCONSISTENT"
        if not checkout_coherent or not loaded_coherent:
            return runtime, "RUNTIME_PROVENANCE_INCONSISTENT"
        return runtime, None

    def _service_truth(self) -> dict[str, Any]:
        return self._bounded_service_truth(CANONICAL_STABLE_SERVICE, 8766)

    def _external_runtime_truth(self) -> tuple[dict[str, Any], str | None]:
        try:
            health = self._external_health_reader()
        except Exception:
            health = {}
        service = self._bounded_service_truth(
            CANONICAL_EXTERNAL_RUNTIME_SERVICE,
            8767,
        )
        loaded_head_raw = health.get("loaded_runtime_head")
        loaded_head = _normalize_git_object_identity(loaded_head_raw)
        loaded_head_valid = loaded_head_raw is None or loaded_head is not None
        runtime_checkout_head = _normalize_git_object_identity(
            health.get("runtime_project_checkout_head")
        )
        package_matches = health.get("installed_package_matches_project_checkout") is True
        source_clean = health.get("installed_package_project_source_clean") is True
        verification_match = health.get("installed_package_verification_status") == "match"
        stale = health.get("runtime_loaded_code_stale")
        reload_needed = health.get("reload_needed_for_verification")
        application_identity_matches = health.get("service") == "colameta-mcp"
        healthy = bool(
            health.get("ok") is True
            and health.get("auth_mode") == "external-oauth"
            and application_identity_matches
            and service.get("active") is True
            and service.get("listener_owned") is True
        )
        loaded_coherent = (
            loaded_head_valid
            and runtime_checkout_head is not None
            and loaded_head in {None, runtime_checkout_head}
        )
        exact_loaded_code_verified = bool(
            healthy
            and runtime_checkout_head
            and loaded_coherent
            and package_matches
            and source_clean
            and verification_match
            and stale is False
            and reload_needed is False
        )
        runtime = {
            "id": "colameta_external_web_gpt_mcp",
            "service_identity": CANONICAL_EXTERNAL_RUNTIME_SERVICE,
            "service_state": "active" if healthy else "unhealthy_or_unavailable",
            "pid": service.get("main_pid"),
            "loaded_runtime_head": loaded_head,
            "runtime_project_checkout_head": runtime_checkout_head,
            "package_matches_checkout": package_matches,
            "package_source_clean": source_clean,
            "package_verification_status": health.get(
                "installed_package_verification_status"
            ),
            "runtime_loaded_code_stale": stale,
            "reload_needed_for_verification": reload_needed,
            "reload_awareness_reason": health.get("reload_awareness_reason"),
            "application_service": health.get("service"),
            "application_identity_matches": application_identity_matches,
            "healthy": healthy,
            "exact_loaded_code_verified": exact_loaded_code_verified,
            "promotion_authority": "external",
        }
        if not application_identity_matches:
            return runtime, "EXTERNAL_RUNTIME_APPLICATION_IDENTITY_MISMATCH"
        if not healthy:
            return runtime, "EXTERNAL_RUNTIME_UNHEALTHY"
        if not package_matches or not source_clean or not verification_match:
            return runtime, "EXTERNAL_RUNTIME_PACKAGE_PROVENANCE_MISMATCH"
        if stale is not False or reload_needed is not False:
            return runtime, "EXTERNAL_RUNTIME_FRESHNESS_INCONSISTENT"
        if runtime_checkout_head is None or not loaded_coherent:
            return runtime, "EXTERNAL_RUNTIME_PROVENANCE_INCONSISTENT"
        return runtime, None

    def _bounded_service_truth(self, service_name: str, port: int) -> dict[str, Any]:
        show = self._command_runner(
            [
                "systemctl",
                "show",
                service_name,
                "--property=ActiveState",
                "--property=SubState",
                "--property=MainPID",
                "--no-pager",
            ],
            self.project_root,
        )
        values = None
        if show.returncode == 0:
            values = _parse_systemctl_show_exact(show.stdout)
        main_pid_text = values["MainPID"] if values is not None else ""
        main_pid = 0
        # The strict parser already guarantees ASCII-decimal admission; the
        # guard below keeps the conversion exception-free by construction.
        if _ASCII_DECIMAL_RE.fullmatch(main_pid_text) is not None:
            main_pid = int(main_pid_text)
        sockets = self._command_runner(
            ["ss", "-H", "-ltnp", "sport", "=", f":{port}"],
            self.project_root,
        )
        listener_owned = bool(
            sockets.returncode == 0
            and _listener_matches_service(
                sockets.stdout,
                expected_address="127.0.0.1",
                expected_port=port,
                main_pid=main_pid,
            )
        )
        return {
            "active": bool(
                values is not None
                and values.get("ActiveState") == "active"
                and values.get("SubState") == "running"
                and main_pid > 0
            ),
            "main_pid": main_pid or None,
            "listener_owned": listener_owned,
            "systemctl_evidence_complete": values is not None,
        }

    def _result(
        self,
        *,
        state: str,
        project: dict[str, Any],
        ci: dict[str, Any],
        runtime: dict[str, Any],
        external_runtime: dict[str, Any],
        delivery_state: str | None = None,
        external_handoff: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "state": state,
            "project": project,
            "candidate": {
                "head": project["head"],
                "repository": project["repository"],
                "ci": ci,
            },
            "runtime_target": runtime,
            "external_runtime": external_runtime,
            "authority_boundary": self._authority_boundary(),
        }
        if delivery_state is not None:
            payload["delivery"] = {"state": delivery_state}
        if external_handoff is not None:
            payload["external_runtime_promotion"] = external_handoff
        return {
            "ok": True,
            "source": "managed_runtime_closeout",
            "action": "managed_runtime_closeout",
            "workflow": MANAGED_RUNTIME_CLOSEOUT_WORKFLOW,
            "phase": "status",
            "status": "succeeded",
            "risk_level": "info",
            "result": {
                "ok": True,
                "read_only": True,
                "side_effects": False,
                "runtime_closeout": payload,
            },
            "steps": [],
            "changed_files": [],
            "preview_ids": [],
            "next_actions": [],
            "requires_confirmation": False,
            "blockers": [],
            "warnings": [],
        }

    def _blocked(
        self,
        reason: str,
        *,
        project: dict[str, Any] | None = None,
        ci: dict[str, Any] | None = None,
        runtime_target: dict[str, Any] | None = None,
        external_runtime: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "state": "RUNTIME_CLOSEOUT_BLOCKED",
            "reason_code": reason,
            "project": project,
            "ci": ci,
            "runtime_target": runtime_target,
            "external_runtime": external_runtime,
            "authority_boundary": self._authority_boundary(),
        }
        return {
            "ok": False,
            "source": "managed_runtime_closeout",
            "action": "managed_runtime_closeout",
            "workflow": MANAGED_RUNTIME_CLOSEOUT_WORKFLOW,
            "phase": "status",
            "status": "blocked",
            "risk_level": "blocked",
            "message": "Managed runtime closeout observation is blocked.",
            "result": {
                "ok": False,
                "read_only": True,
                "side_effects": False,
                "runtime_closeout": payload,
            },
            "steps": [],
            "changed_files": [],
            "preview_ids": [],
            "next_actions": [],
            "requires_confirmation": False,
            "blockers": [reason],
            "warnings": [],
        }

    @staticmethod
    def _authority_boundary() -> dict[str, Any]:
        return {
            "stable_promotion": "external",
            "external_runtime_promotion": "external",
            "internal_mutation": False,
            "service_mutation": False,
            "git_mutation": False,
            "package_mutation": False,
            "privileged_calls": False,
            "privileged_controller_available": False,
            "generic_sudo_productized": False,
            "observation_is_point_in_time": True,
        }

    def _git(self, cwd: str, *args: str) -> subprocess.CompletedProcess[str]:
        return self._command_runner(["git", *args], cwd)

    @staticmethod
    def _subprocess_run(args: list[str], cwd: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            args,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )

    @staticmethod
    def _read_health() -> dict[str, Any]:
        return MCPManagedRuntimeCloseoutManager._read_bounded_health(
            CANONICAL_STABLE_HEALTH_URL,
            timeout_seconds=5,
            allow_redirects=True,
            require_exact_url=False,
            allow_environment_proxy=False,
        )

    @staticmethod
    def _read_external_health() -> dict[str, Any]:
        return MCPManagedRuntimeCloseoutManager._read_bounded_health(
            CANONICAL_EXTERNAL_RUNTIME_HEALTH_URL,
            timeout_seconds=2,
            allow_redirects=False,
            require_exact_url=True,
            allow_environment_proxy=False,
        )

    @staticmethod
    def _read_bounded_health(
        url: str,
        *,
        timeout_seconds: int,
        allow_redirects: bool,
        require_exact_url: bool,
        allow_environment_proxy: bool = False,
    ) -> dict[str, Any]:
        request = Request(url, method="GET")
        with open_http_url(
            request,
            timeout=timeout_seconds,
            allowed_schemes=("http",),
            redirect_policy=HTTPRedirectPolicy(
                allow_redirects=allow_redirects,
                allow_cross_host=False,
                reject_https_downgrade=True,
            ),
            host_policy=lambda hostname: hostname == "127.0.0.1",
            allow_environment_proxy=allow_environment_proxy,
        ) as response:
            if require_exact_url and response.geturl() != url:
                raise RuntimeError("Runtime health endpoint identity is invalid.")
            if response.status != 200:
                raise RuntimeError("Stable health endpoint is unavailable.")
            payload = response.read(1024 * 1024 + 1)
        if len(payload) > 1024 * 1024:
            raise RuntimeError("Stable health response is oversized.")
        parsed = json.loads(payload.decode("utf-8"))
        if not isinstance(parsed, dict):
            raise RuntimeError("Stable health response is invalid.")
        return parsed
