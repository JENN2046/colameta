from __future__ import annotations

import os
from dataclasses import dataclass
from textwrap import dedent
from typing import Any

from runner.path_glob import match as glob_match, normalize as glob_normalize
from runner.runner_paths import (
    PRIMARY_PROJECT_RUNNER_DIRNAME,
    project_runner_dirnames,
    resolve_project_runner_dir,
)


@dataclass(frozen=True)
class RunnerDataPathRule:
    pattern: str
    category: str
    track_policy: str
    reason: str


def _rules_for_runner_dirs(
    specs: tuple[tuple[str, str, str, str], ...],
) -> tuple[RunnerDataPathRule, ...]:
    return tuple(
        RunnerDataPathRule(
            pattern=f"{dirname}/{suffix}",
            category=category,
            track_policy=track_policy,
            reason=reason,
        )
        for dirname in project_runner_dirnames()
        for suffix, category, track_policy, reason in specs
    )


PROJECT_TRACKED_RULES = _rules_for_runner_dirs(
    (
        ("plan.json", "project_tracked", "track", "Version plan is shared project memory and should be tracked."),
        ("todolist.json", "project_tracked", "track", "Todo memo history is shared project memory and should be tracked."),
        ("prompts/**", "project_tracked", "track", "Prompt files are shared project memory and should be tracked."),
        ("shared/**", "project_tracked", "track", "Shared summaries and reusable project memory should be tracked."),
    )
)

PROJECT_LOCAL_RULES = _rules_for_runner_dirs(
    (
        ("local/**", "project_local", "private", "Local project-only settings should stay on the current machine."),
        ("state.json", "project_local", "private", "Runtime state is machine-local and should not be tracked."),
        ("executor-session.json", "project_local", "private", "Executor session data is machine-local and should not be tracked."),
        ("executor-sessions/**", "project_local", "private", "Executor session data is machine-local and should not be tracked."),
        ("settings.json", "project_local", "private", "Local Runner settings should stay machine-private."),
        ("runner-settings.json", "project_local", "private", "Local Runner settings should stay machine-private."),
    )
)

RUNTIME_EPHEMERAL_RULES = _rules_for_runner_dirs(
    tuple(
        (suffix, "runtime_ephemeral", "ignore", reason)
        for suffix, reason in (
            ("runtime/**", "Runtime artifacts are temporary and should not be tracked."),
            ("logs/**", "Logs are temporary runtime artifacts and should not be tracked."),
            ("plan-patches/**", "Plan patch artifacts are runtime-only and should not be tracked."),
            ("checkpoints/**", "Checkpoints are runtime-only and should not be tracked."),
            ("tmp/**", "Temporary files are runtime-only and should not be tracked."),
            ("*.lock", "Lock files are ephemeral coordination artifacts and should not be tracked."),
            ("**/*.lock", "Lock files are ephemeral coordination artifacts and should not be tracked."),
        )
    )
)

ARCHIVE_PRIVATE_OR_EXPORTABLE_RULES = _rules_for_runner_dirs(
    (
        ("reports/**", "archive_private_or_exportable", "exportable", "Reports are archive artifacts that are not tracked by default but may be exported later."),
        ("audits/**", "archive_private_or_exportable", "exportable", "Audit artifacts are archive data that are not tracked by default but may be exported later."),
    )
)

_ALL_RULES = (
    *PROJECT_TRACKED_RULES,
    *PROJECT_LOCAL_RULES,
    *RUNTIME_EPHEMERAL_RULES,
    *ARCHIVE_PRIVATE_OR_EXPORTABLE_RULES,
)

_RECOMMENDED_GITIGNORE_TEXT = dedent(
    f"""
    # ColaMeta local/private/runtime data
    {PRIMARY_PROJECT_RUNNER_DIRNAME}/runtime/
    {PRIMARY_PROJECT_RUNNER_DIRNAME}/logs/
    {PRIMARY_PROJECT_RUNNER_DIRNAME}/local/
    {PRIMARY_PROJECT_RUNNER_DIRNAME}/reports/
    {PRIMARY_PROJECT_RUNNER_DIRNAME}/audits/
    {PRIMARY_PROJECT_RUNNER_DIRNAME}/plan-patches/
    {PRIMARY_PROJECT_RUNNER_DIRNAME}/checkpoints/
    {PRIMARY_PROJECT_RUNNER_DIRNAME}/tmp/
    {PRIMARY_PROJECT_RUNNER_DIRNAME}/*.lock
    {PRIMARY_PROJECT_RUNNER_DIRNAME}/**/*.lock
    {PRIMARY_PROJECT_RUNNER_DIRNAME}/state.json
    {PRIMARY_PROJECT_RUNNER_DIRNAME}/settings.json
    {PRIMARY_PROJECT_RUNNER_DIRNAME}/runner-settings.json
    {PRIMARY_PROJECT_RUNNER_DIRNAME}/executor-session.json
    {PRIMARY_PROJECT_RUNNER_DIRNAME}/executor-sessions/

    # ColaMeta shared project memory
    !{PRIMARY_PROJECT_RUNNER_DIRNAME}/
    !{PRIMARY_PROJECT_RUNNER_DIRNAME}/plan.json
    !{PRIMARY_PROJECT_RUNNER_DIRNAME}/todolist.json
    !{PRIMARY_PROJECT_RUNNER_DIRNAME}/prompts/
    !{PRIMARY_PROJECT_RUNNER_DIRNAME}/prompts/**
    !{PRIMARY_PROJECT_RUNNER_DIRNAME}/shared/
    !{PRIMARY_PROJECT_RUNNER_DIRNAME}/shared/**
    """
).strip()


def _normalize_input_path(path: str) -> str:
    normalized = path.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    while "//" in normalized:
        normalized = normalized.replace("//", "/")
    return normalized


def _runner_relative_path(path: str) -> str | None:
    normalized = _normalize_input_path(path)
    if not normalized:
        return None
    parts = [part for part in normalized.split("/") if part not in ("", ".")]
    for index, part in enumerate(parts):
        if part in project_runner_dirnames():
            return "/".join(parts[index:])
    return None


def _pattern_matches(pattern: str, path: str) -> bool:
    normalized_pattern = _normalize_input_path(pattern)
    normalized_path = _normalize_input_path(path)
    if not normalized_pattern or not normalized_path:
        return False
    if normalized_pattern.endswith("/**"):
        base = normalized_pattern[:-3].rstrip("/")
        if normalized_path == base or normalized_path.startswith(base + "/"):
            return True
    return glob_match(glob_normalize(normalized_pattern), glob_normalize(normalized_path))


def _match_rule(path: str) -> RunnerDataPathRule | None:
    for rule in _ALL_RULES:
        if _pattern_matches(rule.pattern, path):
            return rule
    return None


def _rule_to_payload(path: str, rule: RunnerDataPathRule | None, fallback_category: str, fallback_policy: str, fallback_reason: str) -> dict[str, Any]:
    if rule is None:
        return {
            "path": path,
            "category": fallback_category,
            "track_policy": fallback_policy,
            "matched_pattern": None,
            "reason": fallback_reason,
        }
    return {
        "path": path,
        "category": rule.category,
        "track_policy": rule.track_policy,
        "matched_pattern": rule.pattern,
        "reason": rule.reason,
    }


def classify_runner_path(path: str) -> dict[str, Any]:
    normalized = _normalize_input_path(path)
    runner_relative = _runner_relative_path(normalized)
    if runner_relative is None:
        return {
            "path": normalized,
            "category": "outside_runner_data",
            "track_policy": "ignore",
            "matched_pattern": None,
            "reason": "Path is outside ColaMeta Runner metadata.",
        }

    rule = _match_rule(runner_relative)
    if rule is not None:
        return _rule_to_payload(runner_relative, rule, "unknown_runner_data", "ignore_review_required", "Path is under Runner metadata but no rule matched.")

    return {
        "path": runner_relative,
        "category": "unknown_runner_data",
        "track_policy": "ignore_review_required",
        "matched_pattern": None,
        "reason": "Path is under Runner metadata but no rule matched.",
    }


def recommended_gitignore_rules() -> str:
    return _RECOMMENDED_GITIGNORE_TEXT


def _read_gitignore_rules(gitignore_path: str) -> list[str]:
    if not os.path.isfile(gitignore_path):
        return []
    try:
        with open(gitignore_path, "r", encoding="utf-8") as f:
            return [line.rstrip("\n") for line in f]
    except OSError:
        return []


def _gitignore_contains_rule(lines: list[str], rule: str) -> bool:
    return any(line.strip() == rule for line in lines)


def _collect_runner_files(runner_dir: str, max_depth: int = 4) -> list[str]:
    if not os.path.isdir(runner_dir):
        return []

    collected: list[str] = []
    for root, dirs, files in os.walk(runner_dir):
        rel_root = os.path.relpath(root, runner_dir)
        if rel_root == ".":
            depth = 0
        else:
            depth = len(rel_root.replace("\\", "/").split("/"))
        if depth >= max_depth:
            dirs[:] = []
        for file_name in files:
            abs_path = os.path.join(root, file_name)
            rel_path = os.path.relpath(abs_path, os.path.dirname(runner_dir))
            collected.append(rel_path.replace("\\", "/"))
    collected.sort()
    return collected


def inspect_project_layout(project_root: str) -> dict[str, Any]:
    project_root_abs = os.path.abspath(os.path.expanduser(project_root))
    runner_dir = resolve_project_runner_dir(project_root_abs)
    gitignore_path = os.path.join(project_root_abs, ".gitignore")
    runner_dir_exists = os.path.isdir(runner_dir)
    gitignore_exists = os.path.isfile(gitignore_path)
    gitignore_lines = _read_gitignore_rules(gitignore_path)

    blanket_ignore_rule = f"{PRIMARY_PROJECT_RUNNER_DIRNAME}/"
    recommended_shared_allow_rules = (
        f"!{PRIMARY_PROJECT_RUNNER_DIRNAME}/",
        f"!{PRIMARY_PROJECT_RUNNER_DIRNAME}/plan.json",
        f"!{PRIMARY_PROJECT_RUNNER_DIRNAME}/todolist.json",
        f"!{PRIMARY_PROJECT_RUNNER_DIRNAME}/prompts/",
        f"!{PRIMARY_PROJECT_RUNNER_DIRNAME}/prompts/**",
        f"!{PRIMARY_PROJECT_RUNNER_DIRNAME}/shared/",
        f"!{PRIMARY_PROJECT_RUNNER_DIRNAME}/shared/**",
    )
    recommended_private_ignore_rules = (
        f"{PRIMARY_PROJECT_RUNNER_DIRNAME}/runtime/",
        f"{PRIMARY_PROJECT_RUNNER_DIRNAME}/logs/",
        f"{PRIMARY_PROJECT_RUNNER_DIRNAME}/local/",
        f"{PRIMARY_PROJECT_RUNNER_DIRNAME}/reports/",
        f"{PRIMARY_PROJECT_RUNNER_DIRNAME}/audits/",
        f"{PRIMARY_PROJECT_RUNNER_DIRNAME}/plan-patches/",
        f"{PRIMARY_PROJECT_RUNNER_DIRNAME}/checkpoints/",
        f"{PRIMARY_PROJECT_RUNNER_DIRNAME}/tmp/",
        f"{PRIMARY_PROJECT_RUNNER_DIRNAME}/*.lock",
        f"{PRIMARY_PROJECT_RUNNER_DIRNAME}/**/*.lock",
        f"{PRIMARY_PROJECT_RUNNER_DIRNAME}/state.json",
        f"{PRIMARY_PROJECT_RUNNER_DIRNAME}/settings.json",
        f"{PRIMARY_PROJECT_RUNNER_DIRNAME}/runner-settings.json",
        f"{PRIMARY_PROJECT_RUNNER_DIRNAME}/executor-session.json",
        f"{PRIMARY_PROJECT_RUNNER_DIRNAME}/executor-sessions/",
    )

    has_blanket_colameta_ignore = _gitignore_contains_rule(gitignore_lines, blanket_ignore_rule)
    has_recommended_shared_allow_rules = all(_gitignore_contains_rule(gitignore_lines, rule) for rule in recommended_shared_allow_rules)
    has_recommended_private_ignore_rules = all(_gitignore_contains_rule(gitignore_lines, rule) for rule in recommended_private_ignore_rules)

    tracked_candidates: list[str] = []
    private_candidates: list[str] = []
    runtime_candidates: list[str] = []
    archive_candidates: list[str] = []
    unknown_candidates: list[str] = []
    classified_paths: list[dict[str, Any]] = []

    for rel_path in _collect_runner_files(runner_dir):
        classification = classify_runner_path(rel_path)
        classified_paths.append(classification)
        category = classification.get("category")
        if category == "project_tracked":
            tracked_candidates.append(rel_path)
        elif category == "project_local":
            private_candidates.append(rel_path)
        elif category == "runtime_ephemeral":
            runtime_candidates.append(rel_path)
        elif category == "archive_private_or_exportable":
            archive_candidates.append(rel_path)
        elif category == "unknown_runner_data":
            unknown_candidates.append(rel_path)

    classification_count = len(classified_paths)
    needs_gitignore_migration = (
        has_blanket_colameta_ignore
        or not has_recommended_shared_allow_rules
        or not has_recommended_private_ignore_rules
    )
    if not gitignore_exists:
        one_line = "当前项目缺少 .gitignore，建议按 Runner 数据分层补充分开忽略与放行规则。"
    elif has_blanket_colameta_ignore and not (has_recommended_shared_allow_rules and has_recommended_private_ignore_rules):
        one_line = f"当前 .gitignore 仍在整体忽略 {PRIMARY_PROJECT_RUNNER_DIRNAME}/，建议改为分层忽略私有/运行时路径并放行共享记忆文件。"
    elif has_blanket_colameta_ignore:
        one_line = f"当前 .gitignore 仍在整体忽略 {PRIMARY_PROJECT_RUNNER_DIRNAME}/，建议移除该规则并保留分层忽略/放行规则。"
    elif not has_recommended_shared_allow_rules or not has_recommended_private_ignore_rules:
        one_line = "当前 .gitignore 还没有完整的 Runner 分层规则，建议补齐共享放行与私有/运行时忽略规则。"
    else:
        one_line = "当前 .gitignore 已体现 Runner 数据分层，继续保持共享记忆可跟踪、私有与运行时不可跟踪。"

    return {
        "ok": True,
        "action": "inspect_project_layout",
        "project_root": project_root_abs,
        "runner_dir_exists": runner_dir_exists,
        "runner_dir": os.path.basename(runner_dir),
        "gitignore_exists": gitignore_exists,
        "has_blanket_colameta_ignore": has_blanket_colameta_ignore,
        "has_recommended_shared_allow_rules": has_recommended_shared_allow_rules,
        "has_recommended_private_ignore_rules": has_recommended_private_ignore_rules,
        "recommendation": {
            "needs_gitignore_migration": needs_gitignore_migration,
            "one_line": one_line,
        },
        "classified_paths": classified_paths,
        "tracked_candidates": tracked_candidates,
        "private_candidates": private_candidates,
        "runtime_candidates": runtime_candidates,
        "archive_candidates": archive_candidates,
        "unknown_candidates": unknown_candidates,
        "recommended_gitignore_rules": recommended_gitignore_rules(),
        "classified_path_count": classification_count,
    }
