from __future__ import annotations

import re
from typing import Any

from runner.sensitive_redaction import redact_sensitive_text


MAX_VALIDATION_EXCERPT_CHARS = 1200
MAX_VALIDATION_TEXT_FIELD_CHARS = 2000

_STATUS_PREFIX_PATTERN = re.compile(r"^\s*(PASSED|FAILED)\s*:\s*(.*?)\s*$", re.IGNORECASE)
_FAILED_TEXT_PATTERN = re.compile(
    r"\b(failed|failing|failure|non[- ]zero|permissionerror|traceback)\b"
    r"|(?:exit(?:ed)?(?:\s+code)?|exit_code)\s*(?:=|:)?\s*[1-9]\d*",
    re.IGNORECASE,
)
_PASSED_TEXT_PATTERN = re.compile(
    r"\b(passed|success|successful)\b"
    r"|(?:exit(?:ed)?(?:\s+code)?|exit_code)\s*(?:=|:)?\s*0\b",
    re.IGNORECASE,
)


def summarize_legacy_validation_results(results: list[str]) -> str:
    if not results:
        return "unknown"
    passed = 0
    failed = 0
    for item in results:
        upper = item.upper()
        if upper.startswith("PASSED:"):
            passed += 1
        elif upper.startswith("FAILED:"):
            failed += 1
    if failed > 0:
        return "failed"
    if passed > 0:
        return "passed"
    return "unknown"


def build_validation_truth(
    validation_results: list[Any] | None,
    command_records: list[Any] | None = None,
    *,
    executor_report_text: str | None = None,
) -> dict[str, Any]:
    result_strings = [str(item) for item in (validation_results or []) if isinstance(item, str)]
    raw_records = command_records if isinstance(command_records, list) and command_records else None
    truth_source = "structured_command_records" if raw_records else "legacy_validation_results"
    if raw_records is None:
        raw_records = _records_from_legacy_results(result_strings)
        if not raw_records:
            truth_source = "none"

    records = normalize_validation_command_records(
        raw_records,
        executor_report_text=executor_report_text,
        default_source=truth_source,
    )
    inconsistency_reasons = _collect_inconsistency_reasons(records)
    validation_inconsistent = bool(inconsistency_reasons)
    has_nonzero_exit = any(
        isinstance(record.get("exit_code"), int) and record.get("exit_code") != 0
        for record in records
    )
    has_failed_evidence = has_nonzero_exit or any(
        str(record.get("derived_status") or "").upper() == "FAILED"
        or (
            str(record.get("status") or "").upper() == "FAILED"
            and record.get("exit_code") is None
        )
        for record in records
    )
    has_passed_evidence = any(
        str(record.get("derived_status") or "").upper() == "PASSED"
        or (
            str(record.get("status") or "").upper() == "PASSED"
            and record.get("exit_code") is None
        )
        for record in records
    )

    if validation_inconsistent:
        status_summary = "inconsistent"
    elif has_failed_evidence:
        status_summary = "failed"
    elif has_passed_evidence:
        status_summary = "passed"
    else:
        status_summary = summarize_legacy_validation_results(result_strings)

    if has_nonzero_exit and status_summary == "passed":
        status_summary = "failed"

    failed_count = sum(
        1
        for record in records
        if (
            isinstance(record.get("exit_code"), int)
            and record.get("exit_code") != 0
        )
        or str(record.get("status") or "").upper() == "FAILED"
        or str(record.get("derived_status") or "").upper() == "FAILED"
    )

    return {
        "validation_status_summary": status_summary,
        "validation_inconsistent": validation_inconsistent,
        "validation_inconsistency_reasons": inconsistency_reasons,
        "validation_truth_source": truth_source,
        "validation_command_count": len(records),
        "validation_failed_command_count": failed_count,
        "validation_command_records": records,
        "validation_sample": result_strings[:5],
    }


def validation_truth_from_summary(
    summary: dict[str, Any] | None,
    *,
    executor_report_text: str | None = None,
) -> dict[str, Any]:
    summary_obj = summary if isinstance(summary, dict) else {}
    return build_validation_truth(
        summary_obj.get("validation_results"),
        summary_obj.get("validation_command_records"),
        executor_report_text=executor_report_text,
    )


def bounded_validation_command_records(records: Any, *, limit: int = 50) -> list[dict[str, Any]]:
    if not isinstance(records, list):
        return []
    bounded_limit = max(0, min(int(limit), 200))
    output: list[dict[str, Any]] = []
    for item in records[:bounded_limit]:
        if isinstance(item, dict):
            output.append(dict(item))
    return output


def normalize_validation_command_records(
    records: list[Any] | None,
    *,
    executor_report_text: str | None = None,
    default_source: str = "structured_command_records",
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for idx, raw in enumerate(records or [], start=1):
        record = _normalize_command_record(raw, idx, default_source=default_source)
        contradiction = _report_text_contradiction(record, executor_report_text or "")
        if contradiction:
            _append_inconsistency_reason(record, contradiction)
        normalized.append(record)
    return normalized


def _records_from_legacy_results(results: list[str]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for item in results:
        match = _STATUS_PREFIX_PATTERN.match(item)
        if not match:
            continue
        status = match.group(1).upper()
        command = match.group(2).strip()
        records.append({
            "command": command,
            "original_command": command,
            "executed_command": "",
            "status": status,
            "raw_summary": item,
        })
    return records


def _normalize_command_record(raw: Any, index: int, *, default_source: str) -> dict[str, Any]:
    data = raw if isinstance(raw, dict) else _object_to_record(raw)
    command_index = _coerce_index(data.get("command_index"), data.get("index"), index)
    command = _safe_text(data.get("command"))
    original_command = _safe_text(data.get("original_command"))
    executed_command = _safe_text(data.get("executed_command"))
    if not command:
        command = executed_command or original_command
    if not original_command:
        original_command = command
    status = _safe_text(data.get("status") or data.get("status_recorded")).upper() or "UNKNOWN"
    exit_code = _coerce_exit_code(data.get("exit_code"))
    derived_status = _derive_status_from_exit_code(exit_code)

    stdout_excerpt, stdout_truncated = _bounded_excerpt(
        data.get("stdout") if data.get("stdout") is not None else data.get("stdout_excerpt"),
        bool(data.get("stdout_truncated") is True),
    )
    stderr_excerpt, stderr_truncated = _bounded_excerpt(
        data.get("stderr") if data.get("stderr") is not None else data.get("stderr_excerpt"),
        bool(data.get("stderr_truncated") is True),
    )
    reasons = _existing_reasons(data)
    mismatch = _status_exit_code_mismatch(status, exit_code, derived_status)
    if mismatch:
        reasons.append(mismatch)

    record = {
        "id": _safe_text(data.get("id")) or f"validation-command-{command_index}",
        "command_index": command_index,
        "command": command[:MAX_VALIDATION_TEXT_FIELD_CHARS],
        "original_command": original_command[:MAX_VALIDATION_TEXT_FIELD_CHARS],
        "executed_command": executed_command[:MAX_VALIDATION_TEXT_FIELD_CHARS],
        "status": status,
        "status_recorded": status,
        "derived_status": derived_status,
        "exit_code": exit_code,
        "stdout_excerpt": stdout_excerpt,
        "stdout_truncated": stdout_truncated,
        "stderr_excerpt": stderr_excerpt,
        "stderr_truncated": stderr_truncated,
        "source": _safe_text(data.get("source")) or default_source,
    }
    raw_summary = _safe_text(data.get("raw_summary"))
    if raw_summary:
        record["raw_summary"] = raw_summary[:MAX_VALIDATION_TEXT_FIELD_CHARS]
    if reasons:
        deduped = _dedupe(reasons)
        record["inconsistency_reasons"] = deduped
        record["inconsistency_reason"] = "; ".join(deduped)
    else:
        record["inconsistency_reasons"] = []
        record["inconsistency_reason"] = ""
    return record


def _object_to_record(raw: Any) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for key in (
        "command",
        "original_command",
        "executed_command",
        "status",
        "exit_code",
        "stdout",
        "stderr",
        "started_at",
        "completed_at",
        "duration_ms",
        "cwd",
    ):
        if hasattr(raw, key):
            data[key] = getattr(raw, key)
    return data


def _coerce_index(*values: Any) -> int:
    for value in values:
        try:
            parsed = int(value)
            if parsed > 0:
                return parsed
        except Exception:
            continue
    return 1


def _coerce_exit_code(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except Exception:
        return None


def _derive_status_from_exit_code(exit_code: int | None) -> str:
    if exit_code is None:
        return "UNKNOWN"
    if exit_code == 0:
        return "PASSED"
    return "FAILED"


def _bounded_excerpt(value: Any, already_truncated: bool = False) -> tuple[str, bool]:
    text = _safe_text(value)
    redacted = redact_sensitive_text(
        text,
        replacement_token="<redacted>",
        preserve_token_prefix=False,
    )
    truncated = already_truncated or len(redacted) > MAX_VALIDATION_EXCERPT_CHARS
    return redacted[:MAX_VALIDATION_EXCERPT_CHARS], truncated


def _status_exit_code_mismatch(status: str, exit_code: int | None, derived_status: str) -> str:
    if exit_code is None:
        return ""
    if status not in {"PASSED", "FAILED"}:
        return ""
    if status == derived_status:
        return ""
    return f"status_exit_code_mismatch: recorded_status={status}, exit_code={exit_code}, derived_status={derived_status}"


def _report_text_contradiction(record: dict[str, Any], executor_report_text: str) -> str:
    if not executor_report_text:
        return ""
    expected = _record_outcome(record)
    if expected not in {"PASSED", "FAILED"}:
        return ""
    command_variants = _command_variants(record)
    if not command_variants:
        return ""
    for line in str(executor_report_text).splitlines():
        normalized_line = _normalize_text(line)
        if not normalized_line:
            continue
        if not any(cmd in normalized_line for cmd in command_variants):
            continue
        line_failed = bool(_FAILED_TEXT_PATTERN.search(line))
        line_passed = bool(_PASSED_TEXT_PATTERN.search(line))
        if expected == "PASSED" and line_failed:
            return "executor_report_contradicts_validation_summary: report_text_failed_same_command"
        if expected == "FAILED" and line_passed and not line_failed:
            return "executor_report_contradicts_validation_summary: report_text_passed_same_command"
    return ""


def _record_outcome(record: dict[str, Any]) -> str:
    exit_code = record.get("exit_code")
    if isinstance(exit_code, int):
        return "PASSED" if exit_code == 0 else "FAILED"
    status = str(record.get("status") or "").upper()
    if status in {"PASSED", "FAILED"}:
        return status
    return ""


def _command_variants(record: dict[str, Any]) -> list[str]:
    variants = []
    for key in ("executed_command", "original_command", "command"):
        text = _normalize_text(record.get(key))
        if text and text not in variants:
            variants.append(text)
    return variants


def _normalize_text(value: Any) -> str:
    text = _safe_text(value).lower()
    return " ".join(text.split())


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _existing_reasons(data: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    raw_reasons = data.get("inconsistency_reasons")
    if isinstance(raw_reasons, list):
        reasons.extend(_safe_text(item) for item in raw_reasons if _safe_text(item))
    raw_reason = _safe_text(data.get("inconsistency_reason"))
    if raw_reason:
        reasons.append(raw_reason)
    return _dedupe(reasons)


def _append_inconsistency_reason(record: dict[str, Any], reason: str) -> None:
    reasons = list(record.get("inconsistency_reasons") or [])
    reasons.append(reason)
    deduped = _dedupe([_safe_text(item) for item in reasons if _safe_text(item)])
    record["inconsistency_reasons"] = deduped
    record["inconsistency_reason"] = "; ".join(deduped)


def _collect_inconsistency_reasons(records: list[dict[str, Any]]) -> list[str]:
    reasons: list[str] = []
    for record in records:
        for reason in record.get("inconsistency_reasons") or []:
            text = _safe_text(reason)
            if text:
                prefix = _safe_text(record.get("id")) or f"validation-command-{record.get('command_index', '')}"
                reasons.append(f"{prefix}: {text}")
    return _dedupe(reasons)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output
