from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from urllib.parse import urlsplit

from runner.mcp_git_remote import MCPGitRemoteManager
from runner.operator_artifact_binding import canonical_artifact_digest
from runner.runner_paths import resolve_project_runner_path


CommandRunner = Callable[[list[str], str], subprocess.CompletedProcess[str]]


class MCPGitHubDeliveryManager:
    """Bound synchronized Git truth to bounded GitHub PR delivery actions."""

    _MAX_PREVIEW_BYTES = 1024 * 1024
    _PREVIEW_ID_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
    _SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
    _OWNER_REPO_RE = re.compile(
        r"^(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+)$"
    )
    _MAX_PROVIDER_PAGES = 10
    _MAX_PROVIDER_ITEMS = 1000
    _PENDING_STATES = frozenset(
        {"queued", "waiting", "pending", "in_progress", "requested"}
    )
    _FAILED_CONCLUSIONS = frozenset(
        {
            "failure",
            "cancelled",
            "timed_out",
            "action_required",
            "startup_failure",
            "stale",
            "error",
        }
    )

    def __init__(
        self,
        project_root: str,
        *,
        command_runner: CommandRunner | None = None,
        gh_resolver: Callable[[str], str | None] = shutil.which,
    ):
        self.project_root = os.path.abspath(os.path.expanduser(project_root))
        self.preview_dir = resolve_project_runner_path(
            self.project_root,
            "runtime",
            "github-delivery-previews",
        )
        self.preview_ttl_seconds = 1800
        self._command_runner = command_runner or self._subprocess_run
        self._gh_resolver = gh_resolver

    def pr_status(self, *, project_name: str) -> dict[str, Any]:
        context = self._delivery_context()
        if context.get("ok") is not True:
            return context
        pull_requests, error = self._matching_pull_requests(context)
        if error is not None:
            return error
        exact, classification_error, warnings = self._classify_pull_requests(
            pull_requests, context
        )
        if classification_error is not None:
            return self._classification_error(
                "pr_status", classification_error, warnings
            )
        if exact is not None:
            return self._pr_present(
                "pr_status", context, exact, project_name, warnings=warnings
            )
        return {
            "ok": True,
            "action": "pr_status",
            "workflow": "github_delivery",
            "phase": "pr_status",
            "status": "succeeded",
            "state": "PR_ACTION_REQUIRED",
            "read_only": True,
            "side_effects": False,
            "repository": context["repository"],
            "head_repository": context["head_repository"],
            "base_branch": context["base_branch"],
            "head_branch": context["head_branch"],
            "head_sha": context["head_sha"],
            "remote_head_sha": context["remote_head_sha"],
            "pull_request": {"present": False},
            "next_actions": [
                {
                    "tool": "run_mcp_workflow",
                    "params": {
                        "workflow": "github_delivery",
                        "phase": "pr_preview",
                        "project_name": project_name,
                    },
                    "reason": "Preview one exact-head-bound Draft pull request.",
                    "requires_confirmation": False,
                }
            ],
            "blockers": [],
            "warnings": warnings,
        }

    def pr_preview(self, *, project_name: str) -> dict[str, Any]:
        context = self._delivery_context()
        if context.get("ok") is not True:
            return context
        pull_requests, error = self._matching_pull_requests(context)
        if error is not None:
            return error
        exact, classification_error, warnings = self._classify_pull_requests(
            pull_requests, context
        )
        if classification_error is not None:
            return self._classification_error(
                "pr_preview", classification_error, warnings
            )
        if exact is not None:
            result = self._pr_present(
                "pr_preview", context, exact, project_name, warnings=warnings
            )
            result["already_satisfied"] = True
            return result

        preview_id = secrets.token_urlsafe(18)
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=self.preview_ttl_seconds)
        title = self._pull_request_title()
        body = self._pull_request_body(context)
        payload = {
            "schema_version": "github_pr_preview.v1",
            "action": "github_delivery_pr_preview",
            "preview_id": preview_id,
            "project_root": self.project_root,
            "project_name": project_name,
            "remote_name": "origin",
            "repository": context["repository"],
            "head_repository": context["head_repository"],
            "base_branch": context["base_branch"],
            "head_branch": context["head_branch"],
            "head_sha": context["head_sha"],
            "remote_head_sha": context["remote_head_sha"],
            "title": title,
            "body": body,
            "draft": True,
            "created_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
            "consumed": False,
        }
        preview_digest = canonical_artifact_digest(payload)
        self._write_preview(preview_id, payload)
        return {
            "ok": True,
            "action": "pr_preview",
            "workflow": "github_delivery",
            "phase": "pr_preview",
            "status": "succeeded",
            "state": "PR_PREVIEW_READY",
            "read_only": True,
            "side_effects": False,
            "preview_id": preview_id,
            "preview_digest": preview_digest,
            "repository": context["repository"],
            "head_repository": context["head_repository"],
            "base_branch": context["base_branch"],
            "head_branch": context["head_branch"],
            "head_sha": context["head_sha"],
            "title": title,
            "body": body,
            "draft": True,
            "created_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
            "can_apply": True,
            "requires_confirmation": True,
            "next_actions": [
                {
                    "tool": "run_mcp_workflow",
                    "params": {
                        "workflow": "github_delivery",
                        "phase": "pr_apply",
                        "project_name": project_name,
                        "preview_id": preview_id,
                        "preview_digest": preview_digest,
                    },
                    "reason": "Confirm creation of this exact Draft pull request.",
                    "requires_confirmation": True,
                }
            ],
            "blockers": [],
            "warnings": warnings,
        }

    def pr_apply(
        self,
        *,
        project_name: str,
        preview_id: str,
        preview_digest: str,
    ) -> dict[str, Any]:
        normalized_id = self._validate_preview_id(preview_id)
        if normalized_id is None:
            return self._error(
                "pr_apply", "INVALID_PREVIEW_ID", "preview_id is invalid."
            )
        normalized_digest = self._validate_preview_digest(preview_digest)
        if normalized_digest is None:
            code = (
                "PREVIEW_DIGEST_REQUIRED"
                if not isinstance(preview_digest, str) or not preview_digest.strip()
                else "PREVIEW_DIGEST_INVALID"
            )
            return self._error("pr_apply", code, "preview_digest is invalid.")

        preview, read_error = self._read_preview_secure(normalized_id)
        if read_error is not None or preview is None:
            return self._error(
                "pr_apply",
                read_error or "PREVIEW_INVALID",
                "The GitHub PR preview is unavailable or unsafe.",
            )
        actual_digest = canonical_artifact_digest(preview)
        if not secrets.compare_digest(normalized_digest, actual_digest):
            return self._error(
                "pr_apply",
                "PREVIEW_DIGEST_MISMATCH",
                "The GitHub PR preview no longer matches the confirmed digest.",
            )

        preview_error = self._validate_apply_preview(preview, project_name)
        if preview_error is not None:
            return preview_error
        context = self._delivery_context()
        if context.get("ok") is not True:
            return context
        mismatch = self._preview_context_mismatch(preview, context)
        if mismatch is not None:
            return self._error("pr_apply", mismatch, "GitHub delivery context drifted.")

        pull_requests, error = self._matching_pull_requests(context)
        if error is not None:
            return error
        exact, classification_error, warnings = self._classify_pull_requests(
            pull_requests, context
        )
        if classification_error is not None:
            return self._classification_error(
                "pr_apply", classification_error, warnings
            )
        if exact is not None:
            self._consume_preview(normalized_id, preview)
            result = self._pr_present(
                "pr_apply", context, exact, project_name, warnings=warnings
            )
            result.update(
                {
                    "already_satisfied": True,
                    "preview_id": normalized_id,
                    "preview_consumed": True,
                }
            )
            return result

        created = self._run(
            [
                "gh",
                "pr",
                "create",
                "--repo",
                context["repository"],
                "--base",
                context["base_branch"],
                "--head",
                context["head_branch"],
                "--title",
                str(preview["title"]),
                "--body",
                str(preview["body"]),
                "--draft",
            ]
        )
        pull_requests, error = self._matching_pull_requests(context)
        if error is not None:
            return self._error(
                "pr_apply",
                "GITHUB_PR_POST_CREATE_UNVERIFIED",
                "Draft pull-request creation could not be verified.",
                partial_mutation=True,
            )
        exact, classification_error, warnings = self._classify_pull_requests(
            pull_requests, context
        )
        if classification_error is not None:
            return self._classification_error(
                "pr_apply",
                classification_error,
                warnings,
                partial_mutation=created.returncode == 0,
            )
        if exact is not None:
            self._consume_preview(normalized_id, preview)
            result = self._pr_present(
                "pr_apply", context, exact, project_name, warnings=warnings
            )
            result.update(
                {
                    "created": created.returncode == 0,
                    "already_satisfied": created.returncode != 0,
                    "preview_id": normalized_id,
                    "preview_consumed": True,
                }
            )
            return result
        if created.returncode != 0:
            return self._error(
                "pr_apply",
                "GITHUB_PR_CREATE_FAILED",
                "GitHub did not confirm Draft pull-request creation.",
            )
        if exact is None:
            return self._error(
                "pr_apply",
                "GITHUB_PR_POST_CREATE_UNVERIFIED",
                "Created pull request does not match the exact preview.",
                partial_mutation=True,
            )
        return self._error(
            "pr_apply",
            "GITHUB_PR_POST_CREATE_UNVERIFIED",
            "Created pull request is not a Draft PR.",
            partial_mutation=True,
        )

    def merge_status(self, *, project_name: str) -> dict[str, Any]:
        readiness = self._merge_readiness(project_name=project_name)
        return self._merge_status_result(readiness, project_name=project_name)

    def _merge_readiness(
        self,
        *,
        project_name: str,
    ) -> dict[str, Any]:
        context = self._merge_context()
        if context.get("ok") is not True:
            return self._readiness_error(context)
        pull_requests, error = self._all_pull_requests(context)
        if error is not None:
            return self._readiness_error(error)
        identity, identity_error, warnings = self._classify_canonical_identity(
            pull_requests,
            context,
        )
        if identity_error is not None:
            return self._blocked_readiness(identity_error, context, warnings)
        if identity is None:
            return self._blocked_readiness(
                "GITHUB_PR_NOT_FOUND",
                context,
                warnings,
            )
        if identity.get("state") != "open" or identity.get("draft") is not True:
            return self._blocked_readiness(
                "GITHUB_PR_STATE_OUTSIDE_AUTHORITY",
                context,
                warnings,
                pull_request=identity,
            )

        details, details_error = self._pull_request_details(context, identity)
        if details_error is not None:
            return self._readiness_error(details_error)
        if details is None:
            return self._blocked_readiness(
                "GITHUB_PR_STATUS_INVALID", context, warnings
            )
        if details.get("state") != "open" or details.get("draft") is not True:
            return self._blocked_readiness(
                "GITHUB_PR_STATE_OUTSIDE_AUTHORITY",
                context,
                warnings,
                pull_request=details,
            )

        ancestry = self._run(
            [
                "gh",
                "api",
                f"repos/{context['repository']}/compare/{context['base_head_sha']}...{context['head_sha']}",
                "--jq",
                ".status",
            ]
        )
        if ancestry.returncode != 0 or ancestry.stdout.strip() not in {
            "ahead",
            "identical",
        }:
            return self._blocked_readiness(
                "GITHUB_HEAD_NOT_UP_TO_DATE",
                context,
                warnings,
                pull_request=details,
            )

        ci = self._observe_ci(context)
        if ci.get("state") == "INCOMPLETE":
            return self._blocked_readiness(
                str(ci.get("error_code") or "GITHUB_CI_DATA_INCOMPLETE"),
                context,
                warnings,
                pull_request=details,
                ci=ci,
            )
        if ci.get("state") == "INCONSISTENT":
            return self._blocked_readiness(
                "GITHUB_PROVIDER_STATE_INCONSISTENCY",
                context,
                warnings,
                pull_request=details,
                ci=ci,
                next="COMMANDER_ADJUDICATION_REQUIRED",
            )
        if ci.get("state") == "BLOCKED":
            return self._blocked_readiness(
                "GITHUB_CI_FAILED",
                context,
                warnings,
                pull_request=details,
                ci=ci,
            )
        review = self._observe_review(context, details)
        if review.get("state") == "INCOMPLETE":
            return self._blocked_readiness(
                "GITHUB_REVIEW_DATA_INCOMPLETE",
                context,
                warnings,
                pull_request=details,
                ci=ci,
                review=review,
            )
        if review.get("state") == "BLOCKED":
            return self._blocked_readiness(
                str(review.get("error_code") or "GITHUB_REVIEW_BLOCKED"),
                context,
                warnings,
                pull_request=details,
                ci=ci,
                review=review,
            )
        if ci.get("state") == "WAITING" or review.get("state") == "WAITING":
            return {
                "state": "WAITING_FOR_EXTERNAL_GATE",
                "context": context,
                "pull_request": details,
                "ci": ci,
                "review": review,
                "warnings": warnings,
            }
        if details.get("mergeable") != "MERGEABLE":
            return self._blocked_readiness(
                "GITHUB_PR_NOT_MERGEABLE",
                context,
                warnings,
                pull_request=details,
                ci=ci,
                review=review,
            )
        observed_at = datetime.now(timezone.utc).isoformat()
        return {
            "state": "READY_FOR_EXTERNAL_MERGE",
            "context": context,
            "pull_request": details,
            "ci": ci,
            "review": review,
            "draft": True,
            "project_name": project_name,
            "merge_authority": {
                "mode": "external",
                "atomic_provider_guard_available": False,
                "observation_is_point_in_time": True,
            },
            "merge_handoff": {
                "repository": context["repository"],
                "pr_number": details["number"],
                "base_branch": context["base_branch"],
                "observed_base_sha": context["base_head_sha"],
                "head_repository": context["head_repository"],
                "head_branch": context["head_branch"],
                "head_sha": context["head_sha"],
                "draft": True,
                "ci_state": ci["state"],
                "review_state": review["state"],
                "observed_at": observed_at,
            },
            "warnings": [*warnings, "fresh_recheck_required_before_external_merge"],
        }

    def _merge_context(self) -> dict[str, Any]:
        context = self._delivery_context()
        if context.get("ok") is not True:
            return context
        base = self._run(
            [
                "gh",
                "api",
                f"repos/{context['repository']}/git/ref/heads/{context['base_branch']}",
            ]
        )
        if base.returncode != 0:
            return self._error(
                "merge_status",
                "GITHUB_BASE_HEAD_UNAVAILABLE",
                "GitHub base branch HEAD is unavailable.",
            )
        try:
            base_head_sha = str(json.loads(base.stdout)["object"]["sha"]).lower()
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            base_head_sha = ""
        if re.fullmatch(r"[0-9a-f]{40,64}", base_head_sha) is None:
            return self._error(
                "merge_status",
                "GITHUB_BASE_HEAD_UNAVAILABLE",
                "GitHub base branch HEAD is unavailable.",
            )
        return {**context, "base_head_sha": base_head_sha}

    def _all_pull_requests(
        self,
        context: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        completed = self._run(
            [
                "gh",
                "pr",
                "list",
                "--repo",
                str(context["repository"]),
                "--state",
                "all",
                "--head",
                str(context["head_branch"]),
                "--limit",
                "100",
                "--json",
                "number,url,state,isDraft,baseRefName,headRefName,headRefOid,headRepository,headRepositoryOwner,mergedAt,mergeCommit",
            ]
        )
        if completed.returncode != 0:
            return [], self._error(
                "merge_status",
                "GITHUB_PR_STATUS_FAILED",
                "GitHub pull-request state is unavailable.",
            )
        try:
            raw = json.loads(completed.stdout)
        except json.JSONDecodeError:
            raw = None
        if not isinstance(raw, list) or len(raw) >= 100:
            return [], self._error(
                "merge_status",
                "GITHUB_PR_STATUS_INVALID",
                "GitHub pull-request state is incomplete or invalid.",
            )
        normalized: list[dict[str, Any]] = []
        for item in raw:
            if not isinstance(item, dict):
                return [], self._error(
                    "merge_status",
                    "GITHUB_PR_STATUS_INVALID",
                    "GitHub pull-request state is invalid.",
                )
            pull_request = self._normalize_pr(
                item,
                str(context["repository"]),
                allow_closed=True,
            )
            if pull_request is None:
                return [], self._error(
                    "merge_status",
                    "GITHUB_PR_STATUS_INVALID",
                    "GitHub pull-request state is invalid.",
                )
            normalized.append(pull_request)
        return normalized, None

    def _pull_request_details(
        self,
        context: dict[str, Any],
        identity: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        completed = self._run(
            [
                "gh",
                "pr",
                "view",
                str(identity["number"]),
                "--repo",
                str(context["repository"]),
                "--json",
                "number,url,state,isDraft,baseRefName,headRefName,headRefOid,headRepository,headRepositoryOwner,mergeable,mergeStateStatus,reviewDecision,mergedAt,mergeCommit",
            ]
        )
        if completed.returncode != 0:
            return None, self._error(
                "merge_status",
                "GITHUB_PR_STATUS_FAILED",
                "GitHub pull-request details are unavailable.",
            )
        try:
            raw = json.loads(completed.stdout)
        except json.JSONDecodeError:
            raw = None
        if not isinstance(raw, dict):
            return None, self._error(
                "merge_status",
                "GITHUB_PR_STATUS_INVALID",
                "GitHub pull-request details are invalid.",
            )
        normalized = self._normalize_pr(
            raw,
            str(context["repository"]),
            allow_closed=True,
        )
        expected_identity = {
            "number": identity.get("number"),
            "base_repository": context.get("repository"),
            "base_branch": context.get("base_branch"),
            "head_repository": context.get("head_repository"),
            "head_branch": context.get("head_branch"),
            "head_sha": context.get("head_sha"),
            "state": "open",
            "draft": True,
        }
        identity_changed = normalized is None or any(
            (
                str(normalized.get(key) or "").casefold()
                != str(value or "").casefold()
                if key in {"base_repository", "head_repository"}
                else normalized.get(key) != value
            )
            for key, value in expected_identity.items()
        )
        if identity_changed:
            return None, self._error(
                "merge_status",
                "GITHUB_PR_CONTEXT_AMBIGUOUS",
                "GitHub pull-request identity changed.",
            )
        normalized.update(
            {
                "mergeable": str(raw.get("mergeable") or "").upper(),
                "merge_state_status": str(raw.get("mergeStateStatus") or "").upper(),
                "review_decision": str(raw.get("reviewDecision") or "").upper(),
            }
        )
        return normalized, None

    def _observe_ci(self, context: dict[str, Any]) -> dict[str, Any]:
        runs, runs_error = self._paged_rest_items(
            f"repos/{context['repository']}/actions/runs",
            "workflow_runs",
            query={"event": "pull_request", "head_sha": context["head_sha"]},
        )
        if runs_error is not None:
            return {"state": "INCOMPLETE", "error_code": runs_error}
        exact_runs = [
            item
            for item in runs
            if str(item.get("head_sha") or "").lower() == context["head_sha"]
            and str(item.get("event") or "") == "pull_request"
        ]
        current: dict[str, dict[str, Any]] = {}
        for item in exact_runs:
            workflow_key = str(item.get("workflow_id") or item.get("name") or "")
            if not workflow_key:
                return {"state": "INCOMPLETE", "error_code": "GITHUB_CI_DATA_INCOMPLETE"}
            attempt = int(item.get("run_attempt") or 0)
            run_id = int(item.get("id") or 0)
            previous = current.get(workflow_key)
            previous_key = (
                int(previous.get("run_attempt") or 0),
                int(previous.get("id") or 0),
            ) if previous else (-1, -1)
            if (attempt, run_id) > previous_key:
                current[workflow_key] = item
        workflow_projection: list[dict[str, Any]] = []
        checks_projection: list[dict[str, Any]] = []
        inconsistent = False
        waiting = not current
        blocked = False
        for item in sorted(current.values(), key=lambda value: int(value.get("id") or 0)):
            run_id = int(item.get("id") or 0)
            status = str(item.get("status") or "").lower()
            conclusion = self._normalize_conclusion(item.get("conclusion"))
            workflow_projection.append(
                {
                    "workflow": str(item.get("name") or item.get("workflow_id") or ""),
                    "run_id": run_id,
                    "attempt": int(item.get("run_attempt") or 0),
                    "status": status,
                    "conclusion": conclusion,
                }
            )
            if status in self._PENDING_STATES or status != "completed":
                waiting = True
            elif conclusion in self._FAILED_CONCLUSIONS:
                blocked = True
            elif conclusion != "success":
                blocked = True
            jobs, jobs_error = self._paged_rest_items(
                f"repos/{context['repository']}/actions/runs/{run_id}/jobs",
                "jobs",
            )
            if jobs_error is not None:
                return {"state": "INCOMPLETE", "error_code": jobs_error}
            for job in jobs:
                job_status = str(job.get("status") or "").lower()
                job_conclusion = self._normalize_conclusion(job.get("conclusion"))
                checks_projection.append(
                    {
                        "name": str(job.get("name") or ""),
                        "app": "github_actions",
                        "status": job_status,
                        "conclusion": job_conclusion,
                        "run_id": run_id,
                        "job_id": int(job.get("id") or 0),
                    }
                )
                if status == "completed" and conclusion == "success" and (
                    job_status in self._PENDING_STATES or not job_conclusion
                ):
                    inconsistent = True
                elif job_status in self._PENDING_STATES or job_status != "completed":
                    waiting = True
                elif job_conclusion in self._FAILED_CONCLUSIONS:
                    blocked = True
                elif job_conclusion not in {"success", "skipped", "neutral"}:
                    blocked = True

        check_runs, checks_error = self._paged_rest_items(
            f"repos/{context['repository']}/commits/{context['head_sha']}/check-runs",
            "check_runs",
        )
        if checks_error is not None:
            return {"state": "INCOMPLETE", "error_code": checks_error}
        latest_checks: dict[tuple[str, str], dict[str, Any]] = {}
        for check in check_runs:
            app = check.get("app")
            app_slug = str(app.get("slug") or "unknown") if isinstance(app, dict) else "unknown"
            check_key = (str(check.get("name") or ""), app_slug)
            previous = latest_checks.get(check_key)
            if previous is None or int(check.get("id") or 0) > int(previous.get("id") or 0):
                latest_checks[check_key] = check
        for check in latest_checks.values():
            check_status = str(check.get("status") or "").lower()
            check_conclusion = self._normalize_conclusion(check.get("conclusion"))
            app = check.get("app")
            projected = {
                "name": str(check.get("name") or ""),
                "app": str(app.get("slug") or "unknown") if isinstance(app, dict) else "unknown",
                "status": check_status,
                "conclusion": check_conclusion,
                "check_id": int(check.get("id") or 0),
            }
            checks_projection.append(projected)
            if check_status in self._PENDING_STATES or check_status != "completed":
                waiting = True
            elif check_conclusion in self._FAILED_CONCLUSIONS:
                blocked = True
            elif check_conclusion not in {"success", "skipped", "neutral"}:
                blocked = True

        raw_statuses, statuses_error = self._paged_rest_items(
            f"repos/{context['repository']}/commits/{context['head_sha']}/status",
            "statuses",
        )
        if statuses_error is not None:
            return {"state": "INCOMPLETE", "error_code": "GITHUB_CI_DATA_INCOMPLETE"}
        commit_statuses: list[dict[str, Any]] = []
        latest_status: dict[str, dict[str, Any]] = {}
        for item in raw_statuses:
            if not isinstance(item, dict):
                return {"state": "INCOMPLETE", "error_code": "GITHUB_CI_DATA_INCOMPLETE"}
            context_name = str(item.get("context") or "")
            previous = latest_status.get(context_name)
            if context_name and (
                previous is None
                or int(item.get("id") or 0) > int(previous.get("id") or 0)
            ):
                latest_status[context_name] = item
        for context_name in sorted(latest_status):
            state = str(latest_status[context_name].get("state") or "").lower()
            commit_statuses.append({"context": context_name, "state": state})
            if state == "pending":
                waiting = True
            elif state in {"failure", "error"}:
                blocked = True
            elif state != "success":
                blocked = True
        state = (
            "INCONSISTENT"
            if inconsistent
            else "BLOCKED"
            if blocked
            else "WAITING"
            if waiting
            else "PASS"
        )
        return {
            "head_sha": context["head_sha"],
            "state": state,
            "workflow_runs": workflow_projection,
            "checks": sorted(
                checks_projection,
                key=lambda value: (
                    str(value.get("name") or ""),
                    int(value.get("job_id") or value.get("check_id") or 0),
                ),
            ),
            "commit_statuses": commit_statuses,
        }

    def _observe_review(
        self,
        context: dict[str, Any],
        pull_request: dict[str, Any],
    ) -> dict[str, Any]:
        threads, threads_error = self._paged_graphql_connection(
            repository=str(context["repository"]),
            pr_number=int(pull_request["number"]),
            connection="reviewThreads",
        )
        if threads_error is not None:
            return {"state": "INCOMPLETE", "error_code": threads_error}
        reviews, reviews_error = self._paged_graphql_connection(
            repository=str(context["repository"]),
            pr_number=int(pull_request["number"]),
            connection="reviews",
        )
        if reviews_error is not None:
            return {"state": "INCOMPLETE", "error_code": reviews_error}
        unresolved = sum(
            1 for item in threads if item.get("isResolved") is not True
        )
        normalized_reviews: list[dict[str, Any]] = []
        for item in reviews:
            author = item.get("author")
            reviewer = str(author.get("login") or "") if isinstance(author, dict) else ""
            state = str(item.get("state") or "").upper()
            if not reviewer or state not in {
                "APPROVED",
                "CHANGES_REQUESTED",
                "DISMISSED",
                "COMMENTED",
            }:
                return {"state": "INCOMPLETE", "error_code": "GITHUB_REVIEW_DATA_INCOMPLETE"}
            normalized_reviews.append(
                {
                    "reviewer": reviewer,
                    "state": state,
                    "submitted_at": str(item.get("submittedAt") or ""),
                }
            )
        normalized_reviews.sort(
            key=lambda item: (str(item["submitted_at"]), str(item["reviewer"]))
        )
        effective: dict[str, str] = {}
        for item in normalized_reviews:
            if item["state"] in {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}:
                effective[str(item["reviewer"])] = str(item["state"])
        decision = str(pull_request.get("review_decision") or "").upper()
        if unresolved:
            state = "BLOCKED"
            error_code = "GITHUB_REVIEW_THREAD_UNRESOLVED"
        elif decision == "CHANGES_REQUESTED" or "CHANGES_REQUESTED" in effective.values():
            state = "BLOCKED"
            error_code = "GITHUB_REVIEW_CHANGES_REQUESTED"
        elif decision == "REVIEW_REQUIRED":
            state = "WAITING"
            error_code = None
        else:
            state = "PASS"
            error_code = None
        return {
            "state": state,
            "error_code": error_code,
            "review_decision": decision,
            "unresolved_thread_count": unresolved,
            "effective_reviews": [
                {"reviewer": reviewer, "state": effective[reviewer]}
                for reviewer in sorted(effective)
            ],
            "reviews": normalized_reviews,
        }

    def _paged_rest_items(
        self,
        endpoint: str,
        key: str,
        *,
        query: dict[str, Any] | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        items: list[dict[str, Any]] = []
        for page in range(1, self._MAX_PROVIDER_PAGES + 1):
            separator = "&" if "?" in endpoint else "?"
            query_parts = [f"per_page=100", f"page={page}"]
            if query:
                query_parts.extend(
                    f"{name}={value}" for name, value in sorted(query.items())
                )
            completed = self._run(
                ["gh", "api", f"{endpoint}{separator}{'&'.join(query_parts)}"]
            )
            if completed.returncode != 0:
                return [], "GITHUB_PROVIDER_DATA_INCOMPLETE"
            try:
                payload = json.loads(completed.stdout)
            except json.JSONDecodeError:
                return [], "GITHUB_PROVIDER_DATA_INCOMPLETE"
            page_items = payload.get(key) if isinstance(payload, dict) else None
            if not isinstance(page_items, list) or not all(
                isinstance(item, dict) for item in page_items
            ):
                return [], "GITHUB_PROVIDER_DATA_INCOMPLETE"
            items.extend(page_items)
            if len(items) > self._MAX_PROVIDER_ITEMS:
                return [], "GITHUB_PROVIDER_DATA_INCOMPLETE"
            if len(page_items) < 100:
                return items, None
        return [], "GITHUB_PROVIDER_DATA_INCOMPLETE"

    def _paged_graphql_connection(
        self,
        *,
        repository: str,
        pr_number: int,
        connection: str,
    ) -> tuple[list[dict[str, Any]], str | None]:
        if connection not in {"reviewThreads", "reviews"}:
            return [], "GITHUB_REVIEW_DATA_INCOMPLETE"
        owner, name = repository.split("/", 1)
        cursor: str | None = None
        items: list[dict[str, Any]] = []
        if connection == "reviewThreads":
            query = (
                "query ReviewThreads($owner:String!,$name:String!,$number:Int!,$cursor:String) {"
                " repository(owner:$owner,name:$name) { pullRequest(number:$number) {"
                " reviewThreads(first:100,after:$cursor) { nodes { id isResolved }"
                " pageInfo { hasNextPage endCursor } } } } }"
            )
        else:
            query = (
                "query Reviews($owner:String!,$name:String!,$number:Int!,$cursor:String) {"
                " repository(owner:$owner,name:$name) { pullRequest(number:$number) {"
                " reviews(first:100,after:$cursor) { nodes { id state submittedAt author { login } }"
                " pageInfo { hasNextPage endCursor } } } } }"
            )
        for _page in range(self._MAX_PROVIDER_PAGES):
            args = [
                "gh",
                "api",
                "graphql",
                "-f",
                f"query={query}",
                "-F",
                f"owner={owner}",
                "-F",
                f"name={name}",
                "-F",
                f"number={pr_number}",
            ]
            if cursor is not None:
                args.extend(["-F", f"cursor={cursor}"])
            completed = self._run(args)
            if completed.returncode != 0:
                return [], "GITHUB_REVIEW_DATA_INCOMPLETE"
            try:
                payload = json.loads(completed.stdout)
                connection_payload = payload["data"]["repository"]["pullRequest"][connection]
                nodes = connection_payload["nodes"]
                page_info = connection_payload["pageInfo"]
            except (KeyError, TypeError, json.JSONDecodeError):
                return [], "GITHUB_REVIEW_DATA_INCOMPLETE"
            if not isinstance(nodes, list) or not all(
                isinstance(item, dict) for item in nodes
            ) or not isinstance(page_info, dict):
                return [], "GITHUB_REVIEW_DATA_INCOMPLETE"
            items.extend(nodes)
            if len(items) > self._MAX_PROVIDER_ITEMS:
                return [], "GITHUB_REVIEW_DATA_INCOMPLETE"
            has_next = page_info.get("hasNextPage")
            end_cursor = page_info.get("endCursor")
            if has_next is False:
                return items, None
            if has_next is not True or not isinstance(end_cursor, str) or not end_cursor:
                return [], "GITHUB_REVIEW_DATA_INCOMPLETE"
            cursor = end_cursor
        return [], "GITHUB_REVIEW_DATA_INCOMPLETE"

    @staticmethod
    def _normalize_conclusion(value: Any) -> str:
        return str(value or "").strip().lower()

    @staticmethod
    def _classify_canonical_identity(
        pull_requests: list[dict[str, Any]],
        context: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, str | None, list[str]]:
        canonical_repository = str(context.get("repository") or "")
        canonical = [
            item
            for item in pull_requests
            if isinstance(item.get("head_repository"), str)
            and str(item["head_repository"]).casefold()
            == canonical_repository.casefold()
        ]
        warnings = (
            ["foreign_head_pr_ignored"]
            if len(canonical) != len(pull_requests)
            else []
        )
        exact = [
            item
            for item in canonical
            if str(item.get("base_repository") or "").casefold()
            == canonical_repository.casefold()
            and item.get("base_branch") == context.get("base_branch")
            and item.get("head_branch") == context.get("head_branch")
            and item.get("head_sha") == context.get("head_sha")
        ]
        if len(exact) > 1 or len(canonical) != len(exact):
            return None, "GITHUB_PR_CONTEXT_AMBIGUOUS", warnings
        return (exact[0] if exact else None), None, warnings

    def _merge_status_result(
        self,
        readiness: dict[str, Any],
        *,
        project_name: str,
    ) -> dict[str, Any]:
        state = str(readiness.get("state") or "BLOCKED")
        context = readiness.get("context") if isinstance(readiness.get("context"), dict) else {}
        read_only = True
        result: dict[str, Any] = {
            "ok": state in {"READY_FOR_EXTERNAL_MERGE", "WAITING_FOR_EXTERNAL_GATE"},
            "action": "merge_status",
            "workflow": "github_delivery",
            "phase": "merge_status",
            "status": "blocked" if state == "BLOCKED" else "succeeded",
            "state": state,
            "read_only": read_only,
            "side_effects": False,
            "repository": context.get("repository"),
            "base_branch": context.get("base_branch"),
            "base_head_sha": context.get("base_head_sha"),
            "head_repository": context.get("head_repository"),
            "head_branch": context.get("head_branch"),
            "head_sha": context.get("head_sha"),
            "pull_request": readiness.get("pull_request"),
            "ci": readiness.get("ci"),
            "review": readiness.get("review"),
            "draft": readiness.get("draft"),
            "merge_authority": readiness.get("merge_authority"),
            "merge_handoff": readiness.get("merge_handoff"),
            "next_actions": [],
            "blockers": list(readiness.get("blockers") or []),
            "warnings": list(readiness.get("warnings") or []),
        }
        return result

    @staticmethod
    def _readiness_error(error: dict[str, Any]) -> dict[str, Any]:
        return {
            "state": "BLOCKED",
            "blockers": [str(error.get("error_code") or "GITHUB_DELIVERY_BLOCKED")],
            "warnings": list(error.get("warnings") or []),
            "error": error,
        }

    @staticmethod
    def _blocked_readiness(
        error_code: str,
        context: dict[str, Any],
        warnings: list[str],
        **details: Any,
    ) -> dict[str, Any]:
        return {
            "state": "BLOCKED",
            "context": context,
            "blockers": [error_code],
            "warnings": warnings,
            **details,
        }

    def _delivery_context(self) -> dict[str, Any]:
        authority = self._authority_preflight()
        if authority is not None:
            return authority
        origin = self._git(["remote", "get-url", "origin"])
        if origin.returncode != 0:
            return self._error(
                "pr_status", "GITHUB_ORIGIN_UNAVAILABLE", "Git origin is unavailable."
            )
        repository = self._normalize_github_origin(origin.stdout.strip())
        if repository is None:
            return self._error(
                "pr_status",
                "GITHUB_ORIGIN_INVALID",
                "Git origin is not a supported credential-free GitHub repository.",
            )

        status = MCPGitRemoteManager(self.project_root).push_status()
        if status.get("ok") is not True:
            return self._error(
                "pr_status",
                str(status.get("error_code") or "GITHUB_GIT_STATUS_UNAVAILABLE"),
                "Git delivery status is unavailable.",
            )
        branch = str(status.get("branch") or "")
        policy_blocker = MCPGitRemoteManager(
            self.project_root
        ).delivery_branch_policy_blocker(branch)
        if policy_blocker is not None:
            return self._error(
                "pr_status", "GITHUB_HEAD_BRANCH_BLOCKED", "Delivery branch is not allowed."
            )
        expected_upstream = f"origin/{branch}"
        blockers = [
            str(item)
            for item in (status.get("blockers") or [])
            if str(item) != "nothing_to_push"
        ]
        if status.get("blocking_working_tree_clean") is not True:
            blockers.append("WORKTREE_DIRTY")
        if status.get("upstream") != expected_upstream:
            blockers.append("GITHUB_UPSTREAM_MISMATCH")
        if status.get("remote_name") != "origin":
            blockers.append("GITHUB_REMOTE_NOT_ORIGIN")
        if status.get("ahead") != 0:
            blockers.append("GITHUB_BRANCH_AHEAD")
        if status.get("behind") != 0:
            blockers.append("GITHUB_BRANCH_BEHIND")
        if blockers:
            return self._error(
                "pr_status",
                str(blockers[0]),
                "Git branch is not synchronized for GitHub PR admission.",
            )
        head = str(status.get("head") or "")
        remote = self._git(["ls-remote", "--exit-code", "origin", f"refs/heads/{branch}"])
        remote_head = self._parse_ls_remote(remote.stdout) if remote.returncode == 0 else None
        if remote_head != head:
            return self._error(
                "pr_status",
                "GITHUB_REMOTE_HEAD_MISMATCH",
                "Actual remote branch HEAD does not match local HEAD.",
            )
        repo = self._run(
            ["gh", "repo", "view", repository, "--json", "defaultBranchRef"]
        )
        if repo.returncode != 0:
            return self._error(
                "pr_status",
                "GITHUB_REPOSITORY_READ_FAILED",
                "GitHub repository metadata is unavailable.",
            )
        try:
            base_branch = str(json.loads(repo.stdout)["defaultBranchRef"]["name"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return self._error(
                "pr_status",
                "GITHUB_REPOSITORY_READ_FAILED",
                "GitHub default branch is unavailable.",
            )
        if not base_branch or base_branch == branch:
            return self._error(
                "pr_status",
                "GITHUB_BASE_BRANCH_INVALID",
                "GitHub default branch cannot admit this delivery branch.",
            )
        return {
            "ok": True,
            "repository": repository,
            "head_repository": repository,
            "base_branch": base_branch,
            "head_branch": branch,
            "head_sha": head,
            "remote_head_sha": remote_head,
        }

    def _authority_preflight(self) -> dict[str, Any] | None:
        if self._gh_resolver("gh") is None:
            return self._error(
                "pr_status",
                "GITHUB_AUTHORITY_UNAVAILABLE",
                "Server-owned GitHub CLI authority is unavailable.",
            )
        version = self._run(["gh", "--version"])
        auth = self._run(["gh", "auth", "status", "--hostname", "github.com"])
        if version.returncode != 0 or auth.returncode != 0:
            return self._error(
                "pr_status",
                "GITHUB_AUTHORITY_UNAVAILABLE",
                "Server-owned GitHub CLI authority is unavailable.",
            )
        return None

    def _matching_pull_requests(
        self, context: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        completed = self._run(
            [
                "gh",
                "pr",
                "list",
                "--repo",
                context["repository"],
                "--state",
                "open",
                "--head",
                context["head_branch"],
                "--json",
                "number,url,state,isDraft,baseRefName,headRefName,headRefOid,headRepository,headRepositoryOwner",
            ]
        )
        if completed.returncode != 0:
            return [], self._error(
                "pr_status",
                "GITHUB_PR_STATUS_FAILED",
                "GitHub pull-request state is unavailable.",
            )
        try:
            raw = json.loads(completed.stdout)
        except json.JSONDecodeError:
            raw = None
        if not isinstance(raw, list) or not all(isinstance(item, dict) for item in raw):
            return [], self._error(
                "pr_status", "GITHUB_PR_STATUS_INVALID", "GitHub PR response is invalid."
            )
        normalized: list[dict[str, Any]] = []
        for item in raw:
            pull_request = self._normalize_pr(item, str(context["repository"]))
            if pull_request is None:
                return [], self._error(
                    "pr_status",
                    "GITHUB_PR_STATUS_INVALID",
                    "GitHub PR response is invalid.",
                )
            normalized.append(pull_request)
        return normalized, None

    @staticmethod
    def _normalize_pr(
        item: dict[str, Any], repository: str, *, allow_closed: bool = False
    ) -> dict[str, Any] | None:
        number = item.get("number")
        state = str(item.get("state") or "").lower()
        url = str(item.get("url") or "")
        base_branch = str(item.get("baseRefName") or "")
        head_branch = str(item.get("headRefName") or "")
        head_sha = str(item.get("headRefOid") or "").lower()
        head_repository_data = item.get("headRepository")
        head_owner_data = item.get("headRepositoryOwner")
        head_repository: str | None = None
        if isinstance(head_repository_data, dict) and isinstance(
            head_owner_data, dict
        ):
            repository_name = head_repository_data.get("name")
            owner_login = head_owner_data.get("login")
            if isinstance(repository_name, str) and isinstance(owner_login, str):
                candidate = f"{owner_login}/{repository_name}"
                if MCPGitHubDeliveryManager._OWNER_REPO_RE.fullmatch(candidate):
                    head_repository = candidate
        parsed = urlsplit(url)
        expected_path = f"/{repository}/pull/{number}"
        if (
            not isinstance(number, int)
            or isinstance(number, bool)
            or number <= 0
            or state not in ({"open", "closed", "merged"} if allow_closed else {"open"})
            or not isinstance(item.get("isDraft"), bool)
            or parsed.scheme != "https"
            or parsed.netloc != "github.com"
            or parsed.path.casefold() != expected_path.casefold()
            or parsed.query
            or parsed.fragment
            or not re.fullmatch(r"[A-Za-z0-9._/-]{1,255}", base_branch)
            or not re.fullmatch(r"[A-Za-z0-9._/-]{1,255}", head_branch)
            or not re.fullmatch(r"[0-9a-f]{40,64}", head_sha)
        ):
            return None
        merged_at = item.get("mergedAt")
        merge_commit = item.get("mergeCommit")
        merge_sha = (
            str(merge_commit.get("oid") or "").lower()
            if isinstance(merge_commit, dict)
            else ""
        )
        merged = state == "merged" or (
            state == "closed" and isinstance(merged_at, str) and bool(merged_at)
        )
        if merged and re.fullmatch(r"[0-9a-f]{40,64}", merge_sha) is None:
            return None
        return {
            "present": True,
            "number": number,
            "state": state,
            "draft": item.get("isDraft") is True,
            "url": url,
            "base_repository": repository,
            "base_branch": base_branch,
            "head_repository": head_repository,
            "head_branch": head_branch,
            "head_sha": head_sha,
            "merged": merged,
            "merge_sha": merge_sha if merged else None,
        }

    @staticmethod
    def _classify_pull_requests(
        pull_requests: list[dict[str, Any]], context: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, str | None, list[str]]:
        exact, error, warnings = MCPGitHubDeliveryManager._classify_canonical_identity(
            pull_requests,
            context,
        )
        if error is not None:
            return None, error, warnings
        if exact is not None:
            if exact.get("state") != "open" or exact.get("draft") is not True:
                return None, "GITHUB_PR_STATE_OUTSIDE_AUTHORITY", warnings
            return exact, None, warnings
        return None, None, warnings

    def _pr_present(
        self,
        action: str,
        context: dict[str, Any],
        pull_request: dict[str, Any],
        project_name: str,
        *,
        warnings: list[str],
    ) -> dict[str, Any]:
        return {
            "ok": True,
            "action": action,
            "workflow": "github_delivery",
            "phase": action,
            "status": "succeeded",
            "state": "PR_PRESENT",
            "read_only": action != "pr_apply",
            "side_effects": action == "pr_apply",
            "repository": context["repository"],
            "head_repository": context["head_repository"],
            "base_branch": context["base_branch"],
            "head_branch": context["head_branch"],
            "head_sha": context["head_sha"],
            "pull_request": pull_request,
            "next_actions": [
                {
                    "tool": "run_mcp_workflow",
                    "params": {
                        "workflow": "github_delivery",
                        "phase": "merge_status",
                        "project_name": project_name,
                    },
                    "reason": "Observe exact-head CI and review merge readiness.",
                    "requires_confirmation": False,
                }
            ],
            "blockers": [],
            "warnings": warnings,
        }

    def _classification_error(
        self,
        action: str,
        error_code: str,
        warnings: list[str],
        **details: Any,
    ) -> dict[str, Any]:
        message = (
            "The canonical origin pull request is outside Draft-only authority."
            if error_code == "GITHUB_PR_STATE_OUTSIDE_AUTHORITY"
            else "Canonical pull-request state is ambiguous for this delivery context."
        )
        result = self._error(action, error_code, message, **details)
        result["warnings"] = warnings
        return result

    def _validate_apply_preview(
        self, preview: dict[str, Any], project_name: str
    ) -> dict[str, Any] | None:
        if preview.get("schema_version") != "github_pr_preview.v1" or preview.get(
            "action"
        ) != "github_delivery_pr_preview":
            return self._error("pr_apply", "PREVIEW_INVALID", "Preview action is invalid.")
        if os.path.abspath(str(preview.get("project_root") or "")) != self.project_root:
            return self._error(
                "pr_apply", "PREVIEW_PROJECT_MISMATCH", "Preview belongs to another project."
            )
        if preview.get("project_name") != project_name:
            return self._error(
                "pr_apply", "PREVIEW_PROJECT_MISMATCH", "Preview project identity changed."
            )
        if preview.get("consumed") is True:
            return self._error(
                "pr_apply", "PREVIEW_CONSUMED", "Preview was already consumed."
            )
        expires_at = self._parse_time(preview.get("expires_at"))
        if expires_at is None or expires_at <= datetime.now(timezone.utc):
            return self._error("pr_apply", "PREVIEW_EXPIRED", "Preview has expired.")
        if preview.get("draft") is not True:
            return self._error("pr_apply", "PREVIEW_INVALID", "Preview must create a Draft PR.")
        if not isinstance(preview.get("title"), str) or not preview["title"].strip():
            return self._error("pr_apply", "PREVIEW_INVALID", "Preview title is invalid.")
        if not isinstance(preview.get("body"), str):
            return self._error("pr_apply", "PREVIEW_INVALID", "Preview body is invalid.")
        return None

    @staticmethod
    def _preview_context_mismatch(
        preview: dict[str, Any], context: dict[str, Any]
    ) -> str | None:
        checks = {
            "repository": "GITHUB_REPOSITORY_DRIFT",
            "head_repository": "GITHUB_HEAD_REPOSITORY_DRIFT",
            "base_branch": "GITHUB_BASE_BRANCH_DRIFT",
            "head_branch": "GITHUB_HEAD_BRANCH_DRIFT",
            "head_sha": "GITHUB_HEAD_SHA_DRIFT",
            "remote_head_sha": "GITHUB_REMOTE_HEAD_MISMATCH",
        }
        for key, error_code in checks.items():
            if preview.get(key) != context.get(key):
                return error_code
        if preview.get("remote_name") != "origin":
            return "GITHUB_REMOTE_DRIFT"
        return None

    def _pull_request_title(self) -> str:
        completed = self._git(["log", "-1", "--format=%s", "HEAD"])
        title = " ".join(completed.stdout.split()) if completed.returncode == 0 else ""
        title = "".join(char for char in title if ord(char) >= 32 and ord(char) != 127)
        if re.search(
            r"(?i)(?:github_pat_|gh[pousr]_|sk-(?:proj-)?|token\s*[:=]|password\s*[:=])",
            title,
        ):
            title = ""
        return (title[:120].strip() or "Deliver reviewed project changes")

    @staticmethod
    def _pull_request_body(context: dict[str, Any]) -> str:
        return "\n".join(
            [
                "Bounded ColaMeta delivery candidate.",
                "",
                f"- Base: `{context['base_branch']}`",
                f"- Head: `{context['head_branch']}`",
                f"- Exact commit: `{context['head_sha']}`",
            ]
        )

    @classmethod
    def _normalize_github_origin(cls, value: str) -> str | None:
        if not isinstance(value, str) or not value or any(char.isspace() for char in value):
            return None
        candidate = ""
        if value.startswith("git@github.com:"):
            candidate = value[len("git@github.com:") :]
        elif value.startswith("https://github.com/"):
            candidate = value[len("https://github.com/") :]
        else:
            return None
        if "@" in candidate or ":" in candidate or "?" in candidate or "#" in candidate:
            return None
        candidate = candidate.removesuffix(".git").strip("/")
        match = cls._OWNER_REPO_RE.fullmatch(candidate)
        if match is None or match.group("owner") in {".", ".."} or match.group("repo") in {".", ".."}:
            return None
        return f"{match.group('owner')}/{match.group('repo')}"

    @staticmethod
    def _parse_ls_remote(stdout: str) -> str | None:
        fields = stdout.strip().split()
        if len(fields) < 2 or not re.fullmatch(r"[0-9a-fA-F]{40,64}", fields[0]):
            return None
        return fields[0].lower()

    def _write_preview(self, preview_id: str, payload: dict[str, Any]) -> None:
        os.makedirs(self.preview_dir, mode=0o700, exist_ok=True)
        self._validate_preview_directory()
        path = self._preview_path(preview_id)
        fd, temporary = tempfile.mkstemp(prefix=".github-pr-", dir=self.preview_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                handle.write("\n")
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _read_preview_secure(
        self, preview_id: str
    ) -> tuple[dict[str, Any] | None, str | None]:
        try:
            self._validate_preview_directory()
        except ValueError:
            return None, "PREVIEW_UNSAFE"
        path = self._preview_path(preview_id)
        try:
            entry = os.lstat(path)
        except OSError:
            return None, "PREVIEW_NOT_FOUND"
        if not stat.S_ISREG(entry.st_mode):
            return None, "PREVIEW_UNSAFE"
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(path, flags)
        except OSError:
            return None, "PREVIEW_UNSAFE"
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode) or (
                entry.st_dev,
                entry.st_ino,
            ) != (opened.st_dev, opened.st_ino):
                return None, "PREVIEW_UNSAFE"
            raw = os.read(descriptor, self._MAX_PREVIEW_BYTES + 1)
            if len(raw) > self._MAX_PREVIEW_BYTES:
                return None, "PREVIEW_INVALID"
        finally:
            os.close(descriptor)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None, "PREVIEW_INVALID"
        return (payload, None) if isinstance(payload, dict) else (None, "PREVIEW_INVALID")

    def _consume_preview(self, preview_id: str, preview: dict[str, Any]) -> None:
        preview["consumed"] = True
        preview["consumed_at"] = datetime.now(timezone.utc).isoformat()
        self._write_preview(preview_id, preview)

    def _preview_path(self, preview_id: str) -> str:
        path = os.path.abspath(os.path.join(self.preview_dir, f"{preview_id}.json"))
        root = os.path.abspath(self.preview_dir)
        if os.path.commonpath([root, path]) != root:
            raise ValueError("preview path escaped preview directory")
        return path

    def _validate_preview_directory(self) -> None:
        project_root = os.path.realpath(self.project_root)
        preview_root = os.path.realpath(self.preview_dir)
        if os.path.commonpath([project_root, preview_root]) != project_root:
            raise ValueError("preview directory escaped project root")

    @classmethod
    def _validate_preview_id(cls, value: str) -> str | None:
        normalized = value.strip() if isinstance(value, str) else ""
        return normalized if cls._PREVIEW_ID_RE.fullmatch(normalized) else None

    @classmethod
    def _validate_preview_digest(cls, value: str) -> str | None:
        normalized = value.strip() if isinstance(value, str) else ""
        return normalized if cls._SHA256_RE.fullmatch(normalized) else None

    @staticmethod
    def _parse_time(value: Any) -> datetime | None:
        if not isinstance(value, str):
            return None
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else None

    def _git(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        return self._run(["git", *args])

    def _run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        return self._command_runner(args, self.project_root)

    @staticmethod
    def _subprocess_run(
        args: list[str], cwd: str
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            args,
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )

    @staticmethod
    def _error(
        action: str,
        error_code: str,
        message: str,
        **details: Any,
    ) -> dict[str, Any]:
        return {
            "ok": False,
            "action": action,
            "workflow": "github_delivery",
            "phase": action,
            "status": "blocked",
            "state": "BLOCKED",
            "error_code": error_code,
            "message": message,
            "read_only": action != "pr_apply",
            "side_effects": False,
            "blockers": [error_code],
            "warnings": [],
            **details,
        }
