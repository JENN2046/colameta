"""One explainable project-state projection for ChatGPT and local operators.

The runtime has several legitimate sources of truth: Git describes the current
checkout, Runner describes the planned/current version, executor reports are
historical evidence, and runtime/connector probes have their own freshness.
This module does not collapse those facts into a single ambiguous boolean.
Instead it publishes their authority and freshness explicitly, then derives a
small current conclusion from the current observations only.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from runner.project_context_binding import collect_project_context_binding


CANONICAL_PROJECT_STATE_SCHEMA_VERSION = "colameta.canonical_project_state.v1"


def build_canonical_project_state(
    *,
    project_root: str,
    project_identity: dict[str, Any],
    mode: str,
    git: dict[str, Any],
    runner: dict[str, Any],
    plan: dict[str, Any],
    executor: dict[str, Any],
    reports: dict[str, Any],
    blockers: list[str],
    warnings: list[str],
    partial_errors: list[dict[str, Any]],
    observed_at: datetime | None = None,
    runtime_observation: dict[str, Any] | None = None,
    connector_observation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a public, non-authorizing state projection.

    Inputs are already bounded summaries from ``ProjectSnapshotBuilder``.  This
    function intentionally never opens reports, local state, service records,
    or credentials itself.
    """

    at = observed_at or datetime.now(timezone.utc)
    observed_at_text = _iso(at)
    project_name = _optional_text(project_identity.get("project_name"))
    context_binding = collect_project_context_binding(
        project_root,
        project_name=project_name,
    )
    git_observation = _git_observation(git)
    runner_observation = _runner_observation(runner, mode)
    executor_observation = _executor_observation(executor)
    historical = _historical_verification(reports)
    runtime = _external_observation(runtime_observation)
    connector = _external_observation(connector_observation)

    current_observed = {
        "git": git_observation,
        "runner": runner_observation,
        "executor": executor_observation,
        "runtime": runtime,
        "connector": connector,
    }
    current_conclusion = _current_conclusion(
        mode=mode,
        git=git_observation,
        runner=runner_observation,
        runtime=runtime,
        connector=connector,
        blockers=blockers,
        partial_errors=partial_errors,
    )
    unobserved = [
        name
        for name, observation in (("runtime", runtime), ("connector", connector))
        if observation.get("status") == "not_observed"
    ]
    external_freshness_reasons = _external_freshness_reasons(
        runtime,
        connector,
    )
    external_partial = any(
        observation.get("status") == "partial"
        for observation in (runtime, connector)
    )
    freshness_status = (
        "partial"
        if partial_errors or external_partial
        else "freshness_required"
        if external_freshness_reasons
        else "current"
    )
    return {
        "schema_version": CANONICAL_PROJECT_STATE_SCHEMA_VERSION,
        "observed_at": observed_at_text,
        "context_binding": context_binding,
        "historically_verified": historical,
        "currently_observed": current_observed,
        "freshness": {
            "current_observation": freshness_status,
            "observed_at": observed_at_text,
            "unobserved_sources": unobserved,
            "partial_error_count": len(partial_errors),
        },
        "current_conclusion": current_conclusion,
        "warnings": _unique_texts(warnings),
        "authority_boundary": {
            "observations_do_not_authorize": [
                "executor_run",
                "validation_run",
                "commit",
                "push",
                "stable_replacement",
                "delivery_acceptance",
            ],
            "historical_verification_is_not_current_observation": True,
            "not_observed_is_not_unavailable": True,
        },
    }


def _git_observation(git: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(git, dict) or git.get("ok") is not True:
        return {
            "status": "unavailable",
            "branch": None,
            "head": None,
            "raw_working_tree": "unknown",
            "delivery_working_tree": "unknown",
            "ignored_runtime_file_count": 0,
        }
    raw_clean = git.get("working_tree_clean")
    delivery_clean = git.get("blocking_working_tree_clean")
    ignored = git.get("ignored_runner_runtime_files")
    ignored_count = len(ignored) if isinstance(ignored, list) else 0
    raw_status = _cleanliness(raw_clean)
    delivery_status = _cleanliness(delivery_clean)
    reconciliation = "matched"
    if raw_status == "dirty" and delivery_status == "clean" and ignored_count:
        reconciliation = "ignored_runner_runtime_only"
    elif raw_status != delivery_status:
        reconciliation = "different_policy_scopes"
    return {
        "status": "observed",
        "branch": _optional_text(git.get("branch")),
        "head": _optional_text(git.get("head")),
        "raw_working_tree": raw_status,
        "delivery_working_tree": delivery_status,
        "ignored_runtime_file_count": ignored_count,
        "reconciliation": reconciliation,
    }


def _runner_observation(runner: dict[str, Any], mode: str) -> dict[str, Any]:
    if not isinstance(runner, dict):
        return {
            "status": "unavailable",
            "mode": mode,
            "current_version": None,
            "current_version_status": None,
            "pending_count": None,
        }
    if mode == "source_only":
        status = "source_only"
    elif runner.get("has_runner_state") is True:
        status = "observed"
    else:
        status = "unavailable"
    pending_count = _as_nonnegative_int(runner.get("pending_count"))
    return {
        "status": status,
        "mode": mode,
        "runner_status": _optional_text(runner.get("runner_status")),
        "current_version": _optional_text(runner.get("current_version")),
        "current_version_status": _optional_text(runner.get("current_version_status")),
        "next_version": _optional_text(runner.get("next_version")),
        "pending_count": pending_count,
        "has_pending_versions": bool(runner.get("has_pending_versions")),
        "unreconciled_direct_version_count": _as_nonnegative_int(
            runner.get("unreconciled_direct_version_count")
        )
        or 0,
    }


def _executor_observation(executor: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(executor, dict):
        return {"status": "unavailable"}
    if executor.get("error"):
        status = "unavailable"
    elif executor.get("has_session"):
        status = "active"
    else:
        status = "observed_idle"
    return {
        "status": status,
        "has_session": bool(executor.get("has_session")),
        "continuation_available": bool(executor.get("continuation_available")),
        "risk_level": _optional_text(executor.get("risk_level")),
        "manual_confirmation_required": bool(
            executor.get("manual_confirmation_required")
        ),
    }


def _historical_verification(reports: dict[str, Any]) -> dict[str, Any]:
    latest = reports.get("latest") if isinstance(reports, dict) else None
    if not isinstance(latest, dict) or not latest:
        return {
            "latest_execution_report": {
                "status": "not_available",
                "verified_at": None,
                "report_status": None,
            }
        }
    report_status = _optional_text(latest.get("status"))
    status = "verified" if report_status in {"passed", "completed"} else "recorded"
    return {
        "latest_execution_report": {
            "status": status,
            "verified_at": _optional_text(latest.get("finished_at")),
            "report_status": report_status,
            "version": _optional_text(latest.get("version")),
        }
    }


def _external_observation(value: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {
            "status": "not_observed",
            "observed_at": None,
            "reason_code": "not_requested",
        }
    status = _optional_text(value.get("status")) or _optional_text(
        value.get("state")
    )
    return {
        "status": status.lower() if status else "unavailable",
        "observed_at": _optional_text(value.get("observed_at"))
        or _optional_text(value.get("last_observed_at")),
        "reason_code": _optional_text(value.get("reason_code")),
    }


def _current_conclusion(
    *,
    mode: str,
    git: dict[str, Any],
    runner: dict[str, Any],
    runtime: dict[str, Any],
    connector: dict[str, Any],
    blockers: list[str],
    partial_errors: list[dict[str, Any]],
) -> dict[str, Any]:
    """State both the project-workflow and external-freshness conclusions.

    A clean checkout is not evidence that the currently connected service or
    connector is fresh.  The root status is therefore conservative for the
    complete state model, while the nested project conclusion still tells a
    caller whether a local Git/Runner workflow can proceed.
    """

    reasons = _unique_texts(blockers)
    if reasons:
        project_status = "blocked"
    elif git.get("status") == "unavailable":
        project_status = "freshness_required"
        reasons.append("git_current_observation_unavailable")
    elif partial_errors:
        project_status = "partial_observation"
        reasons.append("state_sources_partially_unavailable")
    elif git.get("delivery_working_tree") == "dirty":
        project_status = "action_required"
        reasons.append("delivery_working_tree_dirty")
    elif mode == "source_only":
        project_status = "source_only"
        reasons.append("runner_plan_not_managed")
    elif runner.get("pending_count") and int(runner["pending_count"]) > 0:
        project_status = "ready_to_execute"
        reasons.append("pending_runner_versions")
    else:
        project_status = "ready"

    external_reasons = _external_freshness_reasons(runtime, connector)
    external_status = (
        "partial_observation"
        if any(
            observation.get("status") == "partial"
            for observation in (runtime, connector)
        )
        else "freshness_required"
        if external_reasons
        else "observed"
    )
    # Immediate project blockers retain their priority.  For an otherwise
    # usable checkout, missing runtime/connector evidence becomes the overall
    # conclusion instead of being silently flattened into "unverified".
    if project_status in {
        "blocked",
        "action_required",
        "partial_observation",
        "source_only",
        "freshness_required",
    }:
        status = project_status
        overall_reasons = reasons
    elif external_status in {
        "freshness_required",
        "partial_observation",
    }:
        status = external_status
        overall_reasons = [*reasons, *external_reasons]
    else:
        status = project_status
        overall_reasons = reasons

    return {
        "status": status,
        "scope": "full_project_and_external_observation",
        "reasons": _unique_texts(overall_reasons),
        "project_checkout": {
            "status": project_status,
            "scope": "project_checkout_and_runner",
            "reasons": reasons,
        },
        "runtime_and_connector": {
            "status": external_status,
            "scope": "runtime_and_connector",
            "reasons": external_reasons,
        },
        "authorization": "observation_only",
    }


def _external_freshness_reasons(
    runtime: dict[str, Any],
    connector: dict[str, Any],
) -> list[str]:
    reasons: list[str] = []
    for name, observation in (("runtime", runtime), ("connector", connector)):
        status = observation.get("status") if isinstance(observation, dict) else None
        if status == "not_observed":
            reasons.append(f"{name}_not_observed")
        elif status in {None, "unavailable", "unknown"}:
            reasons.append(f"{name}_current_observation_unavailable")
        elif status == "partial":
            reasons.append(f"{name}_partial_observation")
        elif status not in {"healthy", "current"}:
            reasons.append(f"{name}_current_observation_not_healthy")
    return reasons


def _cleanliness(value: Any) -> str:
    if value is True:
        return "clean"
    if value is False:
        return "dirty"
    return "unknown"


def _as_nonnegative_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _optional_text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _unique_texts(values: list[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        if isinstance(value, str) and value and value not in result:
            result.append(value)
    return result


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00",
        "Z",
    )
