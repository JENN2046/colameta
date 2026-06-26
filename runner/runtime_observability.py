from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any


PROCESS_START_TIME_ISO = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
LOADED_SOURCE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))

_HEX_HEAD_RE = re.compile(r"^[0-9a-fA-F]{7,128}$")


def git_checkout_metadata(project_root: str | None) -> dict[str, Any]:
    root = os.path.abspath(os.path.expanduser(project_root or ""))
    result: dict[str, Any] = {
        "project_root": root if project_root else None,
        "branch": None,
        "head": None,
        "head_available": False,
        "git_dir_available": False,
        "head_source": "unavailable",
    }
    if not project_root or not os.path.isdir(root):
        result["head_source"] = "missing_project_root"
        return result

    git_dir = _resolve_git_dir(root)
    if not git_dir:
        result["head_source"] = "missing_git_dir"
        return result

    result["git_dir_available"] = True
    head_text = _read_text(os.path.join(git_dir, "HEAD"), max_chars=4096)
    if not head_text:
        result["head_source"] = "missing_head"
        return result

    head_line = head_text.splitlines()[0].strip()
    if head_line.startswith("ref:"):
        ref_name = head_line[4:].strip()
        result["branch"] = _branch_from_ref(ref_name)
        ref_head = _read_ref(git_dir, ref_name)
        if ref_head:
            result["head"] = ref_head
            result["head_available"] = True
            result["head_source"] = "git_ref"
        else:
            result["head_source"] = "missing_ref"
        return result

    if _looks_like_head(head_line):
        result["head"] = head_line
        result["head_available"] = True
        result["head_source"] = "detached_head"
    else:
        result["head_source"] = "invalid_head"
    return result


def get_runtime_version_status(
    project_root: str | None,
    *,
    loaded_runtime_head: str | None = None,
    loaded_runtime_branch: str | None = None,
    process_start_time_iso: str | None = None,
) -> dict[str, Any]:
    loaded_head = _clean_head(loaded_runtime_head if loaded_runtime_head is not None else LOADED_RUNTIME_HEAD)
    project = git_checkout_metadata(project_root)
    project_head = _clean_head(project.get("head"))
    restart_needed, reason = _restart_needed(loaded_head, project_head)

    return {
        "ok": True,
        "source": "runtime_version_observability",
        "scope": "mcp:read",
        "read_only": True,
        "side_effects": False,
        "process_start_time_iso": process_start_time_iso or PROCESS_START_TIME_ISO,
        "loaded_runtime": {
            "source_root": LOADED_SOURCE_ROOT,
            "head": loaded_head,
            "head_available": bool(loaded_head),
            "branch": loaded_runtime_branch if loaded_runtime_branch is not None else LOADED_RUNTIME_BRANCH,
            "head_source": LOADED_RUNTIME_HEAD_SOURCE,
            "captured_at_process_start": True,
        },
        "project_checkout": {
            "project_root": project.get("project_root"),
            "head": project_head,
            "head_available": bool(project_head),
            "branch": project.get("branch"),
            "git_dir_available": bool(project.get("git_dir_available")),
            "head_source": project.get("head_source"),
        },
        "restart_needed": restart_needed,
        "restart_needed_state": "unknown" if restart_needed is None else ("needed" if restart_needed else "not_needed"),
        "restart_needed_reason": reason,
    }


def _restart_needed(loaded_head: str | None, project_head: str | None) -> tuple[bool | None, str]:
    if not loaded_head:
        return None, "unknown_loaded_runtime_head"
    if not project_head:
        return None, "unknown_project_checkout_head"
    if loaded_head == project_head:
        return False, "heads_match"
    return True, "loaded_runtime_head_differs_from_project_checkout_head"


def _resolve_git_dir(project_root: str) -> str | None:
    dot_git = os.path.join(project_root, ".git")
    if os.path.isdir(dot_git):
        return dot_git
    if not os.path.isfile(dot_git):
        return None
    content = _read_text(dot_git, max_chars=4096)
    if not content:
        return None
    first_line = content.splitlines()[0].strip()
    if not first_line.lower().startswith("gitdir:"):
        return None
    gitdir = first_line.split(":", 1)[1].strip()
    if not gitdir:
        return None
    if not os.path.isabs(gitdir):
        gitdir = os.path.join(project_root, gitdir)
    gitdir = os.path.abspath(gitdir)
    return gitdir if os.path.isdir(gitdir) else None


def _read_ref(git_dir: str, ref_name: str) -> str | None:
    ref_path = os.path.join(git_dir, *ref_name.split("/"))
    ref_text = _read_text(ref_path, max_chars=4096)
    if ref_text:
        candidate = ref_text.splitlines()[0].strip()
        if _looks_like_head(candidate):
            return candidate
    return _read_packed_ref(git_dir, ref_name)


def _read_packed_ref(git_dir: str, ref_name: str) -> str | None:
    packed_refs = _read_text(os.path.join(git_dir, "packed-refs"), max_chars=1_000_000)
    if not packed_refs:
        return None
    for raw_line in packed_refs.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("^"):
            continue
        parts = line.split(" ", 1)
        if len(parts) != 2:
            continue
        candidate, packed_ref_name = parts[0].strip(), parts[1].strip()
        if packed_ref_name == ref_name and _looks_like_head(candidate):
            return candidate
    return None


def _branch_from_ref(ref_name: str) -> str | None:
    prefix = "refs/heads/"
    if ref_name.startswith(prefix):
        return ref_name[len(prefix):]
    return None


def _read_text(path: str, *, max_chars: int) -> str | None:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read(max_chars)
    except OSError:
        return None


def _looks_like_head(value: str) -> bool:
    return bool(_HEX_HEAD_RE.match(value))


def _clean_head(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not _looks_like_head(candidate):
        return None
    return candidate


_LOADED_RUNTIME_GIT_METADATA = git_checkout_metadata(LOADED_SOURCE_ROOT)
LOADED_RUNTIME_HEAD = _LOADED_RUNTIME_GIT_METADATA.get("head")
LOADED_RUNTIME_BRANCH = _LOADED_RUNTIME_GIT_METADATA.get("branch")
LOADED_RUNTIME_HEAD_SOURCE = _LOADED_RUNTIME_GIT_METADATA.get("head_source")
