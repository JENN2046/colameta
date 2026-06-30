from __future__ import annotations

import copy
import hashlib
import json
import os
from typing import Any


ARTIFACT_KIND = "final_version_closeout"
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
    "review_decision_write",
    "gate_event_write",
    "delivery_state_accepted_write",
]


def state_content_hash(state: dict[str, Any]) -> str:
    content = json.dumps(state, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def build_final_version_closeout_preview(
    *,
    plan: dict[str, Any],
    state: dict[str, Any],
    target_version: str,
    accepted_commit: str,
    accepted_commit_subject: str,
    expected_head: str,
    current_head: str,
    git_status_short: str | list[str],
    now: str,
    state_file: str,
    project_root: str = "",
    expected_branch: str = "",
    current_branch: str = "",
    commit_exists: bool = False,
    commit_subject: str = "",
    commit_files: list[str] | None = None,
    evidence_refs: list[str] | str | None = None,
    evidence_summary: str = "",
    reason: str = "",
) -> dict[str, Any]:
    blockers: list[dict[str, str]] = []
    warnings: list[str] = []
    status_lines = _status_lines(git_status_short)
    target_version = _clean_str(target_version)
    accepted_commit = _clean_str(accepted_commit)
    accepted_commit_subject = _clean_str(accepted_commit_subject)
    expected_head = _clean_str(expected_head)
    current_head = _clean_str(current_head)
    expected_branch = _clean_str(expected_branch)
    current_branch = _clean_str(current_branch)
    evidence_items = _str_list(evidence_refs)
    commit_file_items = _str_list(commit_files)
    evidence_summary = _clean_str(evidence_summary)
    reason = _clean_str(reason)

    if not target_version:
        blockers.append(_blocker("TARGET_VERSION_REQUIRED", "target_version is required."))
    if not expected_head:
        blockers.append(_blocker("EXPECTED_HEAD_REQUIRED", "expected_head is required."))
    elif current_head != expected_head:
        blockers.append(_blocker("HEAD_MISMATCH", f"current HEAD {current_head} does not match expected {expected_head}."))
    if expected_branch and current_branch and current_branch != expected_branch:
        blockers.append(_blocker("BRANCH_MISMATCH", f"current branch {current_branch} does not match expected {expected_branch}."))
    if status_lines:
        blockers.append(_blocker("WORKTREE_DIRTY", "worktree must be clean before final version closeout."))
    if not reason:
        blockers.append(_blocker("REASON_REQUIRED", "final version closeout requires a reason."))
    if not evidence_items and not evidence_summary:
        blockers.append(_blocker("EVIDENCE_REQUIRED", "final version closeout requires evidence_refs or evidence_summary."))
    blockers.extend(_local_evidence_blockers(evidence_items, project_root))

    plan_versions = _version_index(plan.get("versions"))
    state_versions = _version_index(state.get("versions"))
    plan_order = [version for version, _ in plan_versions]
    state_order = [version for version, _ in state_versions]
    plan_lookup = {version: idx for version, idx in plan_versions}
    state_lookup = {version: idx for version, idx in state_versions}
    if target_version and target_version not in plan_lookup:
        blockers.append(_blocker("TARGET_VERSION_MISSING_FROM_PLAN", f"{target_version} is not present in plan."))
    if target_version and target_version not in state_lookup:
        blockers.append(_blocker("TARGET_VERSION_MISSING_FROM_STATE", f"{target_version} is not present in state."))
    if target_version in plan_lookup and plan_lookup[target_version] != len(plan_order) - 1:
        blockers.append(_blocker("TARGET_VERSION_NOT_FINAL", f"{target_version} is not the final plan version."))
    if target_version in state_lookup and state_lookup[target_version] != len(state_order) - 1:
        blockers.append(_blocker("TARGET_STATE_VERSION_NOT_FINAL", f"{target_version} is not the final state version."))

    target_runtime = _state_runtime_at(state, state_lookup.get(target_version))
    target_runtime_status = _clean_str(target_runtime.get("status")) if target_runtime else ""
    if target_runtime and target_runtime_status not in {"NOT_STARTED", "READY"}:
        blockers.append(_blocker(
            "TARGET_VERSION_STATUS_UNSUPPORTED",
            f"{target_version} status must be NOT_STARTED or READY before final closeout; got {target_runtime_status}.",
        ))

    runner_status = _clean_str(state.get("status"))
    if runner_status not in {"VERSION_PASSED", "READY"}:
        blockers.append(_blocker(
            "RUNNER_STATUS_UNSUPPORTED",
            f"runner status must be VERSION_PASSED or READY before final closeout; got {runner_status}.",
        ))

    if target_version in state_lookup:
        target_idx = state_lookup[target_version]
        for version, idx in state_versions[:target_idx]:
            runtime = _state_runtime_at(state, idx)
            runtime_status = _clean_str(runtime.get("status")) if runtime else ""
            if runtime_status != "PASSED":
                blockers.append(_blocker(
                    "EARLIER_VERSION_NOT_PASSED",
                    f"{version} is before {target_version} and is not PASSED.",
                ))

    if not _looks_like_commit(accepted_commit):
        blockers.append(_blocker("ACCEPTED_COMMIT_REQUIRED", "final version closeout requires a full accepted commit hash."))
    else:
        if not commit_exists:
            blockers.append(_blocker("ACCEPTED_COMMIT_MISSING", "accepted commit is not present in local Git history."))
        actual_subject = _clean_str(commit_subject)
        if not accepted_commit_subject:
            blockers.append(_blocker("ACCEPTED_COMMIT_SUBJECT_REQUIRED", "accepted commit subject is required."))
        elif actual_subject != accepted_commit_subject:
            blockers.append(_blocker("ACCEPTED_COMMIT_SUBJECT_MISMATCH", "accepted commit subject does not match local Git history."))

    before = _state_summary(state)
    proposed_state = _build_proposed_state(
        state=state,
        target_version=target_version,
        target_index=state_lookup.get(target_version, -1),
        accepted_commit=accepted_commit,
        accepted_commit_subject=accepted_commit_subject,
        commit_files=commit_file_items,
        evidence_refs=evidence_items,
        evidence_summary=evidence_summary,
        reason=reason,
        now=now,
    )
    after = _state_summary(proposed_state)
    can_apply = not blockers
    return {
        "ok": True,
        "action": "final_version_closeout_preview",
        "artifact_kind": ARTIFACT_KIND,
        "status": "preview_ready" if can_apply else "blocked",
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
        "target_version": target_version,
        "plan_order": plan_order,
        "state_order": state_order,
        "state_hash": state_content_hash(state),
        "before_state_summary": before,
        "proposed_after_state_summary": after,
        "versions_to_update": _versions_to_update(before, after),
        "accepted_commit": accepted_commit,
        "accepted_commit_subject": accepted_commit_subject,
        "commit_files": commit_file_items,
        "evidence_refs": evidence_items,
        "evidence_summary": evidence_summary,
        "reason": reason,
        "files_apply_would_touch": list(APPLY_TOUCHES),
        "forbidden_side_effects": list(FORBIDDEN_SIDE_EFFECTS),
        "proposed_state": proposed_state if can_apply else None,
        "created_at": now,
    }


def apply_final_version_closeout_artifact(
    *,
    artifact: dict[str, Any],
    current_state: dict[str, Any],
    preview_id: str,
    current_head: str,
    git_status_short: str | list[str],
    current_branch: str = "",
    commit_exists: bool = False,
    commit_subject: str = "",
) -> dict[str, Any]:
    if not preview_id:
        return _apply_blocked("PREVIEW_ID_REQUIRED", "final version closeout apply requires preview_id.")
    if artifact.get("preview_id") != preview_id:
        return _apply_blocked("PREVIEW_ID_MISMATCH", "preview_id does not match the final version closeout artifact.")
    if artifact.get("artifact_kind") != ARTIFACT_KIND:
        return _apply_blocked("PREVIEW_KIND_MISMATCH", "preview artifact is not a final version closeout preview.")
    if not artifact.get("can_apply"):
        return _apply_blocked("PREVIEW_BLOCKED", "preview is not applyable.")
    expected_head = _clean_str(artifact.get("expected_head"))
    if _clean_str(current_head) != expected_head:
        return _apply_blocked("HEAD_CHANGED_SINCE_PREVIEW", "HEAD changed since preview.")
    expected_branch = _clean_str(artifact.get("expected_branch"))
    if expected_branch and current_branch and current_branch != expected_branch:
        return _apply_blocked("BRANCH_CHANGED_SINCE_PREVIEW", "branch changed since preview.")
    if _status_lines(git_status_short):
        return _apply_blocked("WORKTREE_DIRTY", "worktree must be clean before applying final version closeout.")
    if state_content_hash(current_state) != _clean_str(artifact.get("state_hash")):
        return _apply_blocked("STATE_CHANGED_SINCE_PREVIEW", "state changed since preview.")

    accepted_commit = _clean_str(artifact.get("accepted_commit"))
    accepted_subject = _clean_str(artifact.get("accepted_commit_subject"))
    if not commit_exists:
        return _apply_blocked("ACCEPTED_COMMIT_MISSING", "accepted commit is missing.")
    if _clean_str(commit_subject) != accepted_subject:
        return _apply_blocked("ACCEPTED_COMMIT_SUBJECT_MISMATCH", "accepted commit subject changed since preview.")
    if not _looks_like_commit(accepted_commit):
        return _apply_blocked("ACCEPTED_COMMIT_REQUIRED", "accepted commit is invalid.")

    proposed_state = artifact.get("proposed_state")
    if not isinstance(proposed_state, dict):
        return _apply_blocked("PREVIEW_CORRUPTED", "preview artifact has no proposed_state.")
    before = _state_summary(current_state)
    after = _state_summary(proposed_state)
    return {
        "ok": True,
        "action": "final_version_closeout_apply",
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
    target_version: str,
    target_index: int,
    accepted_commit: str,
    accepted_commit_subject: str,
    commit_files: list[str],
    evidence_refs: list[str],
    evidence_summary: str,
    reason: str,
    now: str,
) -> dict[str, Any]:
    proposed = copy.deepcopy(state)
    versions = proposed.get("versions")
    if not isinstance(versions, list):
        versions = []
        proposed["versions"] = versions
    if target_index >= 0 and target_index < len(versions) and isinstance(versions[target_index], dict):
        runtime = versions[target_index]
        metadata = runtime.get("metadata") if isinstance(runtime.get("metadata"), dict) else {}
        metadata["final_version_closeout"] = {
            "target_status": "PASSED",
            "accepted_commit": accepted_commit,
            "accepted_commit_subject": accepted_commit_subject,
            "evidence_refs": list(evidence_refs),
            "evidence_summary": evidence_summary,
            "reason": reason,
            "recorded_at": now,
            "forbidden_side_effects": list(FORBIDDEN_SIDE_EFFECTS),
        }
        runtime["metadata"] = metadata
        runtime["note"] = "final_version_closeout: manually controlled final version completion bound to Runner state."
        runtime["status"] = "PASSED"
        runtime["completed_at"] = runtime.get("completed_at") or now
        runtime["committed_at"] = runtime.get("committed_at") or now
        runtime["commit_hash"] = accepted_commit
        runtime["commit_message"] = accepted_commit_subject
        if commit_files:
            runtime["commit_files"] = list(commit_files)
    proposed["status"] = "COMPLETED"
    proposed["current_version"] = target_version
    proposed["current_version_index"] = target_index
    proposed["updated_at"] = now
    return proposed


def _local_evidence_blockers(evidence_refs: list[str], project_root: str) -> list[dict[str, str]]:
    blockers: list[dict[str, str]] = []
    if not project_root:
        return blockers
    root = os.path.realpath(project_root)
    for ref in evidence_refs:
        path = _evidence_ref_path(ref)
        if not path:
            continue
        candidate = path if os.path.isabs(path) else os.path.join(root, path)
        real_candidate = os.path.realpath(candidate)
        if not (real_candidate == root or real_candidate.startswith(root + os.sep)):
            blockers.append(_blocker("EVIDENCE_PATH_OUTSIDE_PROJECT", f"evidence ref path is outside project: {ref}"))
        elif not os.path.isfile(real_candidate):
            blockers.append(_blocker("EVIDENCE_PATH_NOT_FOUND", f"evidence ref path not found: {ref}"))
    return blockers


def _evidence_ref_path(value: str) -> str:
    text = _clean_str(value)
    for prefix in ("path:", "file:"):
        if text.startswith(prefix):
            return text[len(prefix):].strip()
    if text.startswith(".colameta/") or text.startswith("/"):
        return text
    return ""


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
        "action": "final_version_closeout_apply",
        "status": "blocked",
        "risk_level": "blocked",
        "error_code": code,
        "message": message,
        "blockers": [code],
        "warnings": [],
    }
