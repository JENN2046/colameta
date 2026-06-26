from __future__ import annotations

import copy
import hashlib
import json
from typing import Any


ARTIFACT_KIND = "state_lineage_reconciliation"
APPLY_TOUCHES = [
    ".colameta/state.json",
    ".colameta/runtime/executor-workflow-previews/<preview_id>.json",
]
FORBIDDEN_SIDE_EFFECTS = [
    "executor_run",
    "git_fetch",
    "git_pull",
    "git_push",
    "git_tag",
    "git_release",
    "restart",
    "reload",
    "kill",
    "source_file_mutation",
    "plan_file_mutation",
    "prompt_file_mutation",
]
_PASSED_ALIASES = {"pass", "passed", "complete", "completed", "success", "succeeded"}
_NOT_STARTED_ALIASES = {"not_started", "not-started", "not started", "next_runnable"}


def state_content_hash(state: dict[str, Any]) -> str:
    content = json.dumps(state, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def build_state_lineage_reconciliation_preview(
    *,
    plan: dict[str, Any],
    state: dict[str, Any],
    bindings: list[dict[str, Any]],
    expected_head: str,
    current_head: str,
    git_status_short: str | list[str],
    target_next_version: str,
    now: str,
    state_file: str,
    project_root: str = "",
    expected_branch: str = "",
    current_branch: str = "",
    commit_exists: dict[str, bool] | None = None,
    commit_subjects: dict[str, str] | None = None,
) -> dict[str, Any]:
    commit_exists = commit_exists or {}
    commit_subjects = commit_subjects or {}
    blockers: list[dict[str, str]] = []
    warnings: list[str] = []
    status_lines = _status_lines(git_status_short)

    expected_head = _clean_str(expected_head)
    current_head = _clean_str(current_head)
    target_next_version = _clean_str(target_next_version)
    if not expected_head:
        blockers.append(_blocker("EXPECTED_HEAD_REQUIRED", "expected_head is required."))
    elif current_head != expected_head:
        blockers.append(_blocker("HEAD_MISMATCH", f"current HEAD {current_head} does not match expected {expected_head}."))
    if expected_branch and current_branch and current_branch != expected_branch:
        blockers.append(_blocker("BRANCH_MISMATCH", f"current branch {current_branch} does not match expected {expected_branch}."))
    if status_lines:
        blockers.append(_blocker("WORKTREE_DIRTY", "worktree must be clean before state lineage reconciliation."))
    if not target_next_version:
        blockers.append(_blocker("TARGET_NEXT_VERSION_REQUIRED", "target_next_version is required."))

    plan_versions = _version_index(plan.get("versions"))
    state_versions = _version_index(state.get("versions"))
    plan_order = [version for version, _ in plan_versions]
    state_order = [version for version, _ in state_versions]
    plan_lookup = {version: idx for version, idx in plan_versions}
    state_lookup = {version: idx for version, idx in state_versions}

    if target_next_version and target_next_version not in plan_lookup:
        blockers.append(_blocker("TARGET_NEXT_VERSION_MISSING_FROM_PLAN", f"{target_next_version} is not present in plan."))
    if target_next_version and target_next_version not in state_lookup:
        blockers.append(_blocker("TARGET_NEXT_VERSION_MISSING_FROM_STATE", f"{target_next_version} is not present in state."))

    normalized_bindings: list[dict[str, Any]] = []
    seen_versions: set[str] = set()
    for raw in bindings if isinstance(bindings, list) else []:
        binding = _normalize_binding(raw)
        version = binding["version"]
        if not version:
            blockers.append(_blocker("BINDING_VERSION_REQUIRED", "every binding requires version."))
            continue
        if version in seen_versions:
            blockers.append(_blocker("DUPLICATE_BINDING", f"duplicate binding for {version}."))
        seen_versions.add(version)
        if version not in plan_lookup:
            blockers.append(_blocker("VERSION_MISSING_FROM_PLAN", f"{version} is not present in plan."))
        if version not in state_lookup:
            blockers.append(_blocker("VERSION_MISSING_FROM_STATE", f"{version} is not present in state."))
        _validate_binding(binding, commit_exists, commit_subjects, blockers)
        normalized_bindings.append(binding)
    if not normalized_bindings:
        blockers.append(_blocker("BINDINGS_REQUIRED", "at least one version binding is required."))

    binding_by_version = {binding["version"]: binding for binding in normalized_bindings}
    if target_next_version in plan_lookup:
        target_idx = plan_lookup[target_next_version]
        for version in plan_order[:target_idx]:
            state_idx = state_lookup.get(version)
            runtime = _state_runtime_at(state, state_idx)
            runtime_status = _clean_str(runtime.get("status")) if runtime else ""
            binding = binding_by_version.get(version)
            if runtime_status == "PASSED":
                continue
            if not binding or binding["target_status"] != "PASSED":
                blockers.append(_blocker(
                    "UNRESOLVED_EARLIER_VERSION",
                    f"{version} is before {target_next_version} and is not PASSED without an explicit PASSED binding.",
                ))
        for binding in normalized_bindings:
            version_idx = plan_lookup.get(binding["version"])
            if version_idx is not None and version_idx >= target_idx and binding["target_status"] == "PASSED":
                blockers.append(_blocker(
                    "FUTURE_VERSION_COMPLETION_NOT_ALLOWED",
                    f"{binding['version']} is at or after target_next_version and cannot be marked PASSED here.",
                ))
    target_binding = binding_by_version.get(target_next_version)
    target_runtime = _state_runtime_at(state, state_lookup.get(target_next_version))
    if target_next_version and target_runtime and _clean_str(target_runtime.get("status")) != "NOT_STARTED":
        if not target_binding or target_binding["target_status"] != "NOT_STARTED":
            blockers.append(_blocker(
                "TARGET_NEXT_VERSION_NOT_NOT_STARTED",
                f"{target_next_version} must remain NOT_STARTED or have an explicit NOT_STARTED binding.",
            ))

    before = _state_summary(state)
    proposed_state = _build_proposed_state(
        state=state,
        bindings=normalized_bindings,
        state_lookup=state_lookup,
        target_next_version=target_next_version,
        target_next_index=plan_lookup.get(target_next_version, -1),
        now=now,
    )
    after = _state_summary(proposed_state)
    can_apply = not blockers
    status = "preview_ready" if can_apply else "blocked"
    return {
        "ok": True,
        "action": "state_lineage_reconciliation_preview",
        "artifact_kind": ARTIFACT_KIND,
        "status": status,
        "risk_level": "preview" if can_apply else "blocked",
        "can_apply": can_apply,
        "blockers": blockers,
        "warnings": warnings,
        "project_root": project_root,
        "state_file": state_file,
        "expected_head": expected_head,
        "current_head": current_head,
        "expected_branch": expected_branch,
        "current_branch": current_branch,
        "target_next_version": target_next_version,
        "plan_order": plan_order,
        "state_order": state_order,
        "state_hash": state_content_hash(state),
        "before_state_summary": before,
        "proposed_after_state_summary": after,
        "versions_to_update": _versions_to_update(before, after),
        "commit_bindings": _commit_bindings(normalized_bindings),
        "evidence_refs": _evidence_refs(normalized_bindings),
        "files_apply_would_touch": list(APPLY_TOUCHES),
        "forbidden_side_effects": list(FORBIDDEN_SIDE_EFFECTS),
        "bindings": normalized_bindings,
        "proposed_state": proposed_state if can_apply else None,
        "created_at": now,
    }


def apply_state_lineage_reconciliation_artifact(
    *,
    artifact: dict[str, Any],
    current_state: dict[str, Any],
    preview_id: str,
    current_head: str,
    git_status_short: str | list[str],
    current_branch: str = "",
    commit_exists: dict[str, bool] | None = None,
    commit_subjects: dict[str, str] | None = None,
) -> dict[str, Any]:
    if not preview_id:
        return _apply_blocked("PREVIEW_ID_REQUIRED", "state lineage reconciliation apply requires preview_id.")
    if artifact.get("preview_id") != preview_id:
        return _apply_blocked("PREVIEW_ID_MISMATCH", "preview_id does not match the reconciliation artifact.")
    if artifact.get("artifact_kind") != ARTIFACT_KIND:
        return _apply_blocked("PREVIEW_KIND_MISMATCH", "preview artifact is not a state lineage reconciliation preview.")
    if not artifact.get("can_apply"):
        return _apply_blocked("PREVIEW_BLOCKED", "preview is not applyable.")
    expected_head = _clean_str(artifact.get("expected_head"))
    if _clean_str(current_head) != expected_head:
        return _apply_blocked("HEAD_CHANGED_SINCE_PREVIEW", "HEAD changed since preview.")
    expected_branch = _clean_str(artifact.get("expected_branch"))
    if expected_branch and current_branch and current_branch != expected_branch:
        return _apply_blocked("BRANCH_CHANGED_SINCE_PREVIEW", "branch changed since preview.")
    if _status_lines(git_status_short):
        return _apply_blocked("WORKTREE_DIRTY", "worktree must be clean before applying reconciliation.")
    if state_content_hash(current_state) != _clean_str(artifact.get("state_hash")):
        return _apply_blocked("STATE_CHANGED_SINCE_PREVIEW", "state changed since preview.")

    commit_exists = commit_exists or {}
    commit_subjects = commit_subjects or {}
    for binding in artifact.get("bindings") or []:
        normalized = _normalize_binding(binding)
        if normalized["target_status"] != "PASSED":
            continue
        commit_hash = normalized["accepted_commit"]
        subject = normalized["accepted_commit_subject"]
        if not commit_exists.get(commit_hash):
            return _apply_blocked("ACCEPTED_COMMIT_MISSING", f"accepted commit for {normalized['version']} is missing.")
        if _clean_str(commit_subjects.get(commit_hash)) != subject:
            return _apply_blocked("ACCEPTED_COMMIT_SUBJECT_MISMATCH", f"accepted commit subject changed for {normalized['version']}.")

    proposed_state = artifact.get("proposed_state")
    if not isinstance(proposed_state, dict):
        return _apply_blocked("PREVIEW_CORRUPTED", "preview artifact has no proposed_state.")
    before = _state_summary(current_state)
    after = _state_summary(proposed_state)
    return {
        "ok": True,
        "action": "state_lineage_reconciliation_apply",
        "status": "succeeded",
        "updated_state": copy.deepcopy(proposed_state),
        "before_state_summary": before,
        "after_state_summary": after,
        "versions_updated": _versions_to_update(before, after),
        "files_touched": list(APPLY_TOUCHES),
        "forbidden_side_effects": list(FORBIDDEN_SIDE_EFFECTS),
    }


def _build_proposed_state(
    *,
    state: dict[str, Any],
    bindings: list[dict[str, Any]],
    state_lookup: dict[str, int],
    target_next_version: str,
    target_next_index: int,
    now: str,
) -> dict[str, Any]:
    proposed = copy.deepcopy(state)
    versions = proposed.get("versions")
    if not isinstance(versions, list):
        versions = []
        proposed["versions"] = versions
    for binding in bindings:
        idx = state_lookup.get(binding["version"])
        if idx is None or idx >= len(versions) or not isinstance(versions[idx], dict):
            continue
        runtime = versions[idx]
        metadata = runtime.get("metadata") if isinstance(runtime.get("metadata"), dict) else {}
        metadata["state_lineage_reconciliation"] = {
            "target_status": binding["target_status"],
            "accepted_commit": binding["accepted_commit"],
            "accepted_commit_subject": binding["accepted_commit_subject"],
            "evidence_refs": list(binding["evidence_refs"]),
            "evidence_summary": binding["evidence_summary"],
            "reason": binding["reason"],
            "recorded_at": now,
        }
        runtime["metadata"] = metadata
        runtime["note"] = "state_lineage_reconciliation: manually controlled completion bound to Runner state."
        if binding["target_status"] == "PASSED":
            runtime["status"] = "PASSED"
            runtime["completed_at"] = runtime.get("completed_at") or now
            runtime["committed_at"] = runtime.get("committed_at") or now
            runtime["commit_hash"] = binding["accepted_commit"]
            runtime["commit_message"] = binding["accepted_commit_subject"]
            if binding["commit_files"]:
                runtime["commit_files"] = list(binding["commit_files"])
        elif binding["target_status"] == "NOT_STARTED":
            runtime["status"] = "NOT_STARTED"
    proposed["status"] = "READY"
    proposed["current_version"] = target_next_version
    proposed["current_version_index"] = target_next_index
    proposed["updated_at"] = now
    return proposed


def _normalize_binding(raw: Any) -> dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    target_status = _normalize_status(raw.get("target_status") or raw.get("status"))
    evidence_refs = _str_list(raw.get("evidence_refs"))
    evidence_summary = _clean_str(raw.get("evidence_summary") or raw.get("receipt") or raw.get("evidence"))
    return {
        "version": _clean_str(raw.get("version")),
        "target_status": target_status,
        "accepted_commit": _clean_str(raw.get("accepted_commit") or raw.get("commit_hash")),
        "accepted_commit_subject": _clean_str(raw.get("accepted_commit_subject") or raw.get("commit_subject") or raw.get("commit_message")),
        "commit_files": _str_list(raw.get("commit_files")),
        "evidence_refs": evidence_refs,
        "evidence_summary": evidence_summary,
        "reason": _clean_str(raw.get("reason")),
    }


def _validate_binding(
    binding: dict[str, Any],
    commit_exists: dict[str, bool],
    commit_subjects: dict[str, str],
    blockers: list[dict[str, str]],
) -> None:
    version = binding["version"] or "<unknown>"
    if binding["target_status"] not in {"PASSED", "NOT_STARTED"}:
        blockers.append(_blocker("UNSUPPORTED_TARGET_STATUS", f"{version} target_status must be PASSED or NOT_STARTED."))
    if not binding["reason"]:
        blockers.append(_blocker("REASON_REQUIRED", f"{version} requires reconciliation reason."))
    if not binding["evidence_refs"] and not binding["evidence_summary"]:
        blockers.append(_blocker("EVIDENCE_REQUIRED", f"{version} requires evidence_refs or evidence_summary."))
    if binding["target_status"] != "PASSED":
        return
    commit_hash = binding["accepted_commit"]
    if not _looks_like_commit(commit_hash):
        blockers.append(_blocker("ACCEPTED_COMMIT_REQUIRED", f"{version} requires a full accepted commit hash."))
        return
    if not binding["accepted_commit_subject"]:
        blockers.append(_blocker("ACCEPTED_COMMIT_SUBJECT_REQUIRED", f"{version} requires accepted commit subject."))
    if not commit_exists.get(commit_hash):
        blockers.append(_blocker("ACCEPTED_COMMIT_MISSING", f"{version} accepted commit is not present in local Git history."))
        return
    actual_subject = _clean_str(commit_subjects.get(commit_hash))
    if actual_subject != binding["accepted_commit_subject"]:
        blockers.append(_blocker("ACCEPTED_COMMIT_SUBJECT_MISMATCH", f"{version} accepted commit subject does not match local Git history."))


def _state_summary(state: dict[str, Any]) -> dict[str, Any]:
    versions = []
    for item in state.get("versions") or []:
        if not isinstance(item, dict):
            continue
        versions.append({
            "version": item.get("version"),
            "status": item.get("status"),
            "commit_hash": item.get("commit_hash"),
            "commit_message": item.get("commit_message"),
        })
    return {
        "runner_status": state.get("status"),
        "current_version": state.get("current_version"),
        "current_version_index": state.get("current_version_index"),
        "versions": versions,
    }


def _versions_to_update(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    before_map = {item.get("version"): item for item in before.get("versions") or []}
    updates = []
    for item in after.get("versions") or []:
        version = item.get("version")
        previous = before_map.get(version, {})
        if item != previous:
            updates.append({"version": version, "before": previous, "after": item})
    return updates


def _commit_bindings(bindings: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {
            "version": binding["version"],
            "accepted_commit": binding["accepted_commit"],
            "accepted_commit_subject": binding["accepted_commit_subject"],
        }
        for binding in bindings
        if binding["target_status"] == "PASSED"
    ]


def _evidence_refs(bindings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "version": binding["version"],
            "evidence_refs": list(binding["evidence_refs"]),
            "evidence_summary": binding["evidence_summary"],
        }
        for binding in bindings
    ]


def _version_index(items: Any) -> list[tuple[str, int]]:
    if not isinstance(items, list):
        return []
    result = []
    for idx, item in enumerate(items):
        if isinstance(item, dict) and _clean_str(item.get("version")):
            result.append((_clean_str(item.get("version")), idx))
    return result


def _state_runtime_at(state: dict[str, Any], idx: int | None) -> dict[str, Any] | None:
    versions = state.get("versions")
    if idx is None or not isinstance(versions, list) or idx < 0 or idx >= len(versions):
        return None
    item = versions[idx]
    return item if isinstance(item, dict) else None


def _normalize_status(value: Any) -> str:
    text = _clean_str(value)
    lowered = text.lower()
    if lowered in _PASSED_ALIASES:
        return "PASSED"
    if lowered in _NOT_STARTED_ALIASES:
        return "NOT_STARTED"
    return text.upper()


def _status_lines(value: str | list[str]) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [line.strip() for line in value.splitlines() if line.strip()]
    return []


def _str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _clean_str(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _looks_like_commit(value: str) -> bool:
    return len(value) == 40 and all(ch in "0123456789abcdefABCDEF" for ch in value)


def _blocker(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def _apply_blocked(code: str, message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "action": "state_lineage_reconciliation_apply",
        "status": "blocked",
        "risk_level": "blocked",
        "error_code": code,
        "message": message,
        "blockers": [code],
        "warnings": [],
    }
