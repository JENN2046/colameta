from __future__ import annotations

import json
import os
from typing import Any


ARTIFACT_KIND = "stage_parallel_shard_input_overlay"
OVERLAY_REL_DIR = os.path.join("runtime", "stage-parallel-shard-inputs", "current")


def overlay_paths(project_root: str) -> dict[str, str]:
    root = os.path.abspath(os.path.expanduser(project_root))
    overlay_root = os.path.join(root, ".colameta", OVERLAY_REL_DIR)
    return {
        "project_root": root,
        "overlay_root": overlay_root,
        "manifest_file": os.path.join(overlay_root, "manifest.json"),
        "plan_file": os.path.join(overlay_root, "plan.json"),
        "state_file": os.path.join(overlay_root, "state.json"),
        "prompt_file": os.path.join(overlay_root, "prompt.md"),
        "runtime_dir": os.path.join(overlay_root, "runtime"),
        "logs_dir": os.path.join(overlay_root, "logs"),
    }


def load_valid_overlay(project_root: str) -> dict[str, Any] | None:
    paths = overlay_paths(project_root)
    manifest_file = paths["manifest_file"]
    if not os.path.isfile(manifest_file):
        return None
    try:
        with open(manifest_file, "r", encoding="utf-8") as handle:
            manifest = json.load(handle)
    except Exception:
        return None
    if not isinstance(manifest, dict) or manifest.get("artifact_kind") != ARTIFACT_KIND:
        return None
    if os.path.abspath(str(manifest.get("worktree_path") or "")) != paths["project_root"]:
        return None
    for key in ("plan_file", "state_file", "prompt_file"):
        value = manifest.get(key)
        if not isinstance(value, str) or not _is_under(value, paths["overlay_root"]):
            return None
        if not os.path.isfile(value):
            return None
    for key in ("runtime_dir", "logs_dir"):
        value = manifest.get(key)
        if not isinstance(value, str) or not _is_under(value, paths["overlay_root"]):
            return None
    return {**manifest, "overlay_root": paths["overlay_root"]}


def _is_under(path: str, parent: str) -> bool:
    try:
        return os.path.commonpath([os.path.abspath(path), os.path.abspath(parent)]) == os.path.abspath(parent)
    except ValueError:
        return False
