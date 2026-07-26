from __future__ import annotations

import copy
import hashlib
import json
import subprocess

import pytest

from runner.current_facts_artifact import (
    CURRENT_FACTS_ARCHIVE_ROOT,
    CURRENT_FACTS_ARTIFACT_SCHEMA_VERSION,
    CurrentFactsArtifactError,
    build_current_facts_artifact,
    write_current_facts_archive,
)


def _canonical_state() -> dict:
    return {
        "schema_version": "colameta.canonical_project_state.v1",
        "observed_at": "2026-07-24T08:09:10Z",
        "context_binding": {
            "project_name": "current-facts-fixture",
            "branch": "main",
            "head": "a" * 40,
            "runner_plan": {"mode": "managed", "plan_sha256": "b" * 64},
            "current_version": "v1.0",
        },
        "historically_verified": {
            "latest_execution_report": {
                "status": "verified",
                "verified_at": "2026-07-23T08:09:10Z",
                "report_status": "completed",
                "version": "v1.0",
            }
        },
        "currently_observed": {
            "git": {
                "status": "observed",
                "branch": "main",
                "head": "a" * 40,
                "raw_working_tree": "clean",
                "delivery_working_tree": "clean",
                "ignored_runtime_file_count": 0,
                "reconciliation": "matched",
            },
            "runner": {
                "status": "observed",
                "mode": "runner_managed",
                "runner_status": "COMPLETED",
                "current_version": "v1.0",
                "current_version_status": "PASSED",
                "next_version": None,
                "pending_count": 0,
                "has_pending_versions": False,
                "unreconciled_direct_version_count": 0,
            },
            "executor": {
                "status": "observed_idle",
                "has_session": False,
                "continuation_available": False,
                "risk_level": None,
                "manual_confirmation_required": False,
            },
            "runtime": {
                "status": "healthy",
                "observed_at": "2026-07-24T08:09:00Z",
                "reason_code": None,
            },
            "connector": {
                "status": "healthy",
                "observed_at": "2026-07-24T08:09:01Z",
                "reason_code": None,
            },
        },
        "freshness": {
            "current_observation": "current",
            "observed_at": "2026-07-24T08:09:10Z",
            "unobserved_sources": [],
            "partial_error_count": 0,
        },
        "current_conclusion": {
            "status": "ready",
            "scope": "full_project_and_external_observation",
            "reasons": [],
            "project_checkout": {
                "status": "ready",
                "scope": "project_checkout_and_runner",
                "reasons": [],
            },
            "runtime_and_connector": {
                "status": "observed",
                "scope": "runtime_and_connector",
                "reasons": [],
            },
            "authorization": "observation_only",
        },
        "warnings": ["fixture_warning"],
        "authority_boundary": {
            "observations_do_not_authorize": ["commit"],
            "historical_verification_is_not_current_observation": True,
            "not_observed_is_not_unavailable": True,
        },
    }


def _scenario_state(name: str) -> dict:
    """Return one canonical-state fixture for a public freshness outcome."""

    state = _canonical_state()
    if name == "fresh":
        return state
    if name == "stale":
        state["currently_observed"]["runtime"].update(
            {"status": "stale", "reason_code": "RUNTIME_OBSERVATION_STALE"}
        )
        state["currently_observed"]["connector"].update(
            {"status": "stale", "reason_code": "CONNECTOR_OBSERVATION_STALE"}
        )
        state["freshness"].update(
            {
                "current_observation": "stale",
                "unobserved_sources": ["runtime", "connector"],
            }
        )
        state["current_conclusion"].update(
            {
                "status": "freshness_required",
                "reasons": ["EXTERNAL_OBSERVATION_STALE"],
            }
        )
        return state
    if name == "partial":
        state["currently_observed"]["runtime"].update(
            {"status": "partial", "reason_code": "RUNTIME_PROBE_TIMEOUT"}
        )
        state["freshness"].update(
            {"current_observation": "partial", "partial_error_count": 1}
        )
        state["current_conclusion"].update(
            {"status": "partial", "reasons": ["RUNTIME_PROBE_TIMEOUT"]}
        )
        return state
    if name == "not_observed":
        state["currently_observed"]["runtime"].update(
            {"status": "not_observed", "observed_at": None, "reason_code": "NOT_OBSERVED"}
        )
        state["currently_observed"]["connector"].update(
            {"status": "not_observed", "observed_at": None, "reason_code": "NOT_OBSERVED"}
        )
        state["freshness"].update(
            {
                "current_observation": "not_observed",
                "unobserved_sources": ["runtime", "connector"],
            }
        )
        state["current_conclusion"].update(
            {
                "status": "freshness_required",
                "reasons": ["EXTERNAL_OBSERVATION_REQUIRED"],
            }
        )
        return state
    if name == "conflicting":
        state["currently_observed"]["git"].update(
            {"raw_working_tree": "dirty", "reconciliation": "conflict"}
        )
        state["currently_observed"]["runner"].update(
            {"unreconciled_direct_version_count": 1}
        )
        state["current_conclusion"].update(
            {
                "status": "blocked",
                "reasons": ["GIT_RUNNER_RECONCILIATION_CONFLICT"],
                "project_checkout": {
                    "status": "blocked",
                    "scope": "project_checkout_and_runner",
                    "reasons": ["GIT_RUNNER_RECONCILIATION_CONFLICT"],
                },
            }
        )
        return state
    raise AssertionError(f"unknown fixture scenario: {name}")


def _init_git_project(project, *, ignore_runtime_reports: bool) -> None:
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    subprocess.run(["git", "-C", str(project), "config", "user.email", "artifact@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(project), "config", "user.name", "Artifact Fixture"], check=True)
    if ignore_runtime_reports:
        (project / ".gitignore").write_text(".colameta/reports/**\n", encoding="utf-8")
    (project / "README.md").write_text("artifact fixture\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(project), "add", "."], check=True)
    subprocess.run(["git", "-C", str(project), "commit", "-qm", "fixture"], check=True)


def test_current_facts_artifact_is_deterministic_and_explicitly_non_authorizing() -> None:
    first = build_current_facts_artifact(_canonical_state())
    second = build_current_facts_artifact(_canonical_state())

    assert first.json_text == second.json_text
    assert first.markdown_text == second.markdown_text
    assert first.snapshot_json_sha256 == hashlib.sha256(first.json_text.encode("utf-8")).hexdigest()
    assert first.snapshot_markdown_sha256 == hashlib.sha256(first.markdown_text.encode("utf-8")).hexdigest()
    payload = json.loads(first.json_text)
    assert payload["schema_version"] == CURRENT_FACTS_ARTIFACT_SCHEMA_VERSION
    assert payload["current_facts"]["current_conclusion"]["status"] == "ready"
    assert payload["authority_boundary"]["snapshot_is_observation_only"] is True
    assert "stable_replacement" in payload["authority_boundary"]["does_not_authorize"]
    assert "# Current Facts Snapshot" in first.markdown_text
    assert first.descriptor()["archive_root"] == CURRENT_FACTS_ARCHIVE_ROOT


@pytest.mark.parametrize(
    ("scenario", "expected_conclusion", "expected_freshness"),
    [
        ("fresh", "ready", "current"),
        ("stale", "freshness_required", "stale"),
        ("partial", "partial", "partial"),
        ("not_observed", "freshness_required", "not_observed"),
        ("conflicting", "blocked", "current"),
    ],
)
def test_current_facts_artifact_preserves_conservative_fixture_outcomes_deterministically(
    scenario: str,
    expected_conclusion: str,
    expected_freshness: str,
) -> None:
    state = _scenario_state(scenario)
    first = build_current_facts_artifact(state)
    second = build_current_facts_artifact(_scenario_state(scenario))

    assert first.json_text == second.json_text
    assert first.markdown_text == second.markdown_text
    payload = json.loads(first.json_text)
    facts = payload["current_facts"]
    assert facts["current_conclusion"]["status"] == expected_conclusion
    assert facts["freshness"]["current_observation"] == expected_freshness
    assert facts["currently_observed"]["git"]["status"] == "observed"
    assert facts["currently_observed"]["runner"]["status"] == "observed"
    assert facts["currently_observed"]["runtime"]["status"] == state["currently_observed"]["runtime"]["status"]
    assert facts["currently_observed"]["connector"]["status"] == state["currently_observed"]["connector"]["status"]
    assert payload["observed_at"] == state["observed_at"]
    assert payload["canonical_state_sha256"] == first.canonical_state_sha256
    assert payload["canonical_state_semantic_sha256"] == first.canonical_state_semantic_sha256
    assert "access_token" not in first.json_text
    assert "project_root" not in first.json_text


def test_current_facts_artifact_rejects_sensitive_or_path_like_canonical_fields() -> None:
    state = _canonical_state()
    state["currently_observed"]["runtime"]["access_token"] = "must-not-leak"

    with pytest.raises(CurrentFactsArtifactError) as error:
        build_current_facts_artifact(state)

    assert error.value.code == "CURRENT_FACTS_REDACTION_REQUIRED"
    assert "access_token" in error.value.message


def test_current_facts_semantic_digest_binds_source_observation_timestamps() -> None:
    state = _canonical_state()
    state["currently_observed"]["runtime"]["last_observed_at"] = (
        "2026-07-24T08:08:59Z"
    )
    baseline = build_current_facts_artifact(state)

    recollected = copy.deepcopy(state)
    recollected["observed_at"] = "2026-07-24T08:10:10Z"
    recollected["freshness"]["observed_at"] = "2026-07-24T08:10:10Z"
    assert (
        build_current_facts_artifact(
            recollected
        ).canonical_state_semantic_sha256
        == baseline.canonical_state_semantic_sha256
    )

    runtime_refreshed = copy.deepcopy(recollected)
    runtime_refreshed["currently_observed"]["runtime"]["observed_at"] = (
        "2026-07-24T08:10:00Z"
    )
    assert (
        build_current_facts_artifact(
            runtime_refreshed
        ).canonical_state_semantic_sha256
        != baseline.canonical_state_semantic_sha256
    )

    last_observed_refreshed = copy.deepcopy(recollected)
    last_observed_refreshed["currently_observed"]["runtime"][
        "last_observed_at"
    ] = "2026-07-24T08:10:01Z"
    assert (
        build_current_facts_artifact(
            last_observed_refreshed
        ).canonical_state_semantic_sha256
        != baseline.canonical_state_semantic_sha256
    )


def test_current_facts_archive_writes_only_the_fixed_runtime_pair_and_is_idempotent(tmp_path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _init_git_project(project, ignore_runtime_reports=True)
    artifact = build_current_facts_artifact(_canonical_state())

    written = write_current_facts_archive(str(project), artifact)
    replay = write_current_facts_archive(str(project), artifact)

    assert written["status"] == "written"
    assert replay["status"] == "already_present"
    assert [item["path"] for item in written["files"]] == [
        f"{CURRENT_FACTS_ARCHIVE_ROOT}/{artifact.archive_stem}.json",
        f"{CURRENT_FACTS_ARCHIVE_ROOT}/{artifact.archive_stem}.md",
    ]
    assert (project / CURRENT_FACTS_ARCHIVE_ROOT / f"{artifact.archive_stem}.json").read_text(encoding="utf-8") == artifact.json_text
    assert (project / CURRENT_FACTS_ARCHIVE_ROOT / f"{artifact.archive_stem}.md").read_text(encoding="utf-8") == artifact.markdown_text
    assert not (project / "CURRENT_FACTS.md").exists()
    status = subprocess.run(
        ["git", "-C", str(project), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert status.stdout == ""


def test_current_facts_archive_fails_closed_when_the_fixed_runtime_root_is_not_ignored(tmp_path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _init_git_project(project, ignore_runtime_reports=False)

    with pytest.raises(CurrentFactsArtifactError) as error:
        write_current_facts_archive(str(project), build_current_facts_artifact(_canonical_state()))

    assert error.value.code == "CURRENT_FACTS_ARCHIVE_NOT_IGNORED"
    assert not (project / CURRENT_FACTS_ARCHIVE_ROOT).exists()
