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
CANONICAL_CI_WORKFLOW_PATH = ".github/workflows/ci.yml"

CommandRunner = Callable[[list[str], str], subprocess.CompletedProcess[str]]
HealthReader = Callable[[], dict[str, Any]]


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
        stable_checkout: str = CANONICAL_STABLE_CHECKOUT,
        github_manager_factory: Callable[..., MCPGitHubDeliveryManager] = MCPGitHubDeliveryManager,
    ):
        self.project_root = os.path.abspath(os.path.expanduser(project_root))
        self.project_name = project_name
        self.project_mode = project_mode
        self._command_runner = command_runner or self._subprocess_run
        self._health_reader = health_reader or self._read_health
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

        candidate_head = str(project["head"])
        stable_head = str(runtime["checkout_head"])
        if stable_head == candidate_head:
            if runtime.get("exact_loaded_code_verified") is not True:
                return self._blocked(
                    "RUNTIME_EXACT_HEAD_FRESHNESS_UNVERIFIED",
                    project=project,
                    ci=ci,
                    runtime_target=runtime,
                )
            return self._result(
                state="RUNTIME_ALREADY_CURRENT",
                project=project,
                ci=ci,
                runtime=runtime,
                delivery_state="DELIVERY_COMPLETE",
            )

        observed_at = datetime.now(timezone.utc).isoformat()
        handoff = {
            "mode": "external",
            "target": COLAMETA_STABLE_LOCAL_TARGET,
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
            external_handoff=handoff,
        )

    def _project_truth(self) -> tuple[dict[str, Any], str | None]:
        metadata = git_checkout_metadata(self.project_root)
        branch = str(metadata.get("branch") or "")
        head = str(metadata.get("head") or "").lower()
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
        remote_head = ""
        if remote.returncode == 0:
            parts = remote.stdout.strip().split()
            if len(parts) == 2 and parts[1] == "refs/heads/main":
                remote_head = parts[0].lower()
        project = {
            "identity": "canonical_colameta_repository",
            "name": self.project_name,
            "repository": repository,
            "mode": self.project_mode,
            "branch": branch,
            "head": head or None,
            "worktree_clean": status.returncode == 0 and not status.stdout,
            "origin_main_head": remote_head or None,
            "ahead": 0 if head and head == remote_head else None,
            "behind": 0 if head and head == remote_head else None,
        }
        if repository != CANONICAL_REPOSITORY:
            return project, "RUNTIME_TARGET_PROJECT_MISMATCH"
        if branch != "main":
            return project, "RUNTIME_DELIVERY_BRANCH_INVALID"
        if status.returncode != 0 or status.stdout:
            return project, "RUNTIME_DELIVERY_WORKTREE_DIRTY"
        if re.fullmatch(r"[0-9a-f]{40,64}", head) is None or not remote_head:
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
        stable_head = str(metadata.get("head") or "").lower()
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
        loaded_head = (
            str(loaded_head_raw).lower()
            if isinstance(loaded_head_raw, str) and loaded_head_raw
            else None
        )
        runtime_checkout_head = str(
            health.get("runtime_project_checkout_head") or ""
        ).lower()
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
        checkout_coherent = bool(stable_head) and runtime_checkout_head == stable_head
        loaded_coherent = loaded_head in {None, stable_head}
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
            "checkout_head": stable_head or None,
            "checkout_clean": status.returncode == 0 and not status.stdout,
            "service_identity": CANONICAL_STABLE_SERVICE,
            "service_state": "active" if healthy else "unhealthy_or_unavailable",
            "pid": pid if isinstance(pid, int) and pid > 0 else None,
            "loaded_runtime_head": loaded_head,
            "runtime_project_checkout_head": runtime_checkout_head or None,
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
        if status.returncode != 0 or status.stdout or not stable_head:
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
        show = self._command_runner(
            [
                "systemctl",
                "show",
                CANONICAL_STABLE_SERVICE,
                "--property=ActiveState",
                "--property=SubState",
                "--property=MainPID",
                "--no-pager",
            ],
            self.project_root,
        )
        values: dict[str, str] = {}
        if show.returncode == 0:
            for line in show.stdout.splitlines():
                key, separator, value = line.partition("=")
                if separator:
                    values[key] = value
        main_pid_text = values.get("MainPID", "")
        main_pid = int(main_pid_text) if main_pid_text.isdigit() else 0
        sockets = self._command_runner(
            ["ss", "-H", "-ltnp", "sport", "=", ":8766"],
            self.project_root,
        )
        listener_pids = {
            int(value)
            for value in re.findall(r"\bpid=(\d+)\b", sockets.stdout)
        } if sockets.returncode == 0 else set()
        loopback_listener = any(
            token in sockets.stdout
            for token in ("127.0.0.1:8766", "[::1]:8766")
        )
        return {
            "active": values.get("ActiveState") == "active"
            and values.get("SubState") == "running"
            and main_pid > 0,
            "main_pid": main_pid or None,
            "listener_owned": loopback_listener and main_pid in listener_pids,
        }

    def _result(
        self,
        *,
        state: str,
        project: dict[str, Any],
        ci: dict[str, Any],
        runtime: dict[str, Any],
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
    ) -> dict[str, Any]:
        payload = {
            "state": "RUNTIME_CLOSEOUT_BLOCKED",
            "reason_code": reason,
            "project": project,
            "ci": ci,
            "runtime_target": runtime_target,
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
        request = Request(CANONICAL_STABLE_HEALTH_URL, method="GET")
        with open_http_url(
            request,
            timeout=5,
            allowed_schemes=("http",),
            redirect_policy=HTTPRedirectPolicy(allow_cross_host=False),
            host_policy=lambda hostname: hostname == "127.0.0.1",
        ) as response:
            if response.status != 200:
                raise RuntimeError("Stable health endpoint is unavailable.")
            payload = response.read(1024 * 1024 + 1)
        if len(payload) > 1024 * 1024:
            raise RuntimeError("Stable health response is oversized.")
        parsed = json.loads(payload.decode("utf-8"))
        if not isinstance(parsed, dict):
            raise RuntimeError("Stable health response is invalid.")
        return parsed
