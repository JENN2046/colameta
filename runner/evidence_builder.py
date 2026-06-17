from typing import Any


def build_post_executor_patch_evidence(
    version: str | None,
    tool: str,
    preview_id: str,
    files_changed: list[str],
    operation: str,
    applied_at: str,
    underlying_action: str | None = None,
    file_signatures: dict[str, Any] | None = None,
) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "version": version,
        "tool": tool,
        "preview_id": preview_id,
        "files_changed": list(files_changed),
        "operation": operation,
        "applied_at": applied_at,
        "evidence_source": "controlled_patch_apply",
    }
    if underlying_action is not None:
        evidence["underlying_action"] = underlying_action
    if file_signatures is not None:
        evidence["file_signatures"] = dict(file_signatures)
    return evidence
