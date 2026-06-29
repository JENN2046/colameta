from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


FIELD_RESULT_PRESENT = "present"
FIELD_RESULT_MISSING = "missing"
FIELD_RESULT_EMPTY = "empty"
FIELD_RESULT_MALFORMED = "malformed"
FIELD_RESULT_KNOWN_UNKNOWN = "known_unknown"

VALIDATION_RESULT_PASSED = "passed"
VALIDATION_RESULT_FAILED_CLOSED = "failed_closed"
VALIDATION_RESULT_FAILED_REQUIRED_FIELDS = "failed_required_fields"
VALIDATION_RESULT_KNOWN_UNKNOWN = "known_unknown"

FAIL_CLOSED_RESULT_PASS = "pass"
FAIL_CLOSED_RESULT_FAIL_CLOSED = "fail_closed"

DEFAULT_SCHEMA_PATH = Path(".colameta/taskbooks/stage_taskbook_schema.json")

FORBIDDEN_VALIDATOR_RESULT_FIELDS = frozenset(
    {
        "delivery_state",
        "accepted",
        "executor_authorization",
        "active_stage_authority",
        "review_decision_outcome",
        "gate_event",
    }
)

ANCHOR_FALLBACK_ALLOWED_FIELDS = frozenset({"stage_purpose"})


@dataclass(frozen=True)
class RequiredFieldSpec:
    field: str
    exact_keys: tuple[str, ...]
    anchor_texts: tuple[str, ...]
    fail_closed: bool = False


class StageTaskbookValidatorError(ValueError):
    def __init__(self, error_code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.details = details or {}


def load_stage_taskbook_schema(project_root: str | Path | None = None) -> dict[str, Any]:
    root = Path(project_root or Path.cwd()).resolve()
    schema_path = (root / DEFAULT_SCHEMA_PATH).resolve()
    _ensure_inside_project(root, schema_path, "stage_taskbook_schema_path")
    try:
        raw = schema_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise StageTaskbookValidatorError(
            "STAGE_TASKBOOK_SCHEMA_MISSING",
            "Stage Taskbook schema file does not exist.",
            details={"schema_path": str(schema_path)},
        ) from exc
    try:
        schema = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise StageTaskbookValidatorError(
            "STAGE_TASKBOOK_SCHEMA_INVALID_JSON",
            "Stage Taskbook schema file is not valid JSON.",
            details={"schema_path": str(schema_path), "line": exc.lineno, "column": exc.colno},
        ) from exc
    _validate_schema_shape(schema)
    return schema


def validate_stage_taskbook(
    *,
    stage_taskbook_path: str | Path | None = None,
    raw_content: str | None = None,
    schema: dict[str, Any] | None = None,
    expected_master_taskbook_hash: str | None = None,
    observed_git_head: str | None = None,
) -> dict[str, Any]:
    if schema is None:
        schema = load_stage_taskbook_schema()
    try:
        _validate_schema_shape(schema)
    except StageTaskbookValidatorError as exc:
        result = _known_unknown_result("schema_invalid", schema, details=exc.details)
        _assert_no_forbidden_result_fields(result)
        return result

    raw, resolved_path, read_failure = _read_stage_taskbook(stage_taskbook_path, raw_content)
    if raw is None:
        result = _known_unknown_result(read_failure or "stage_taskbook_unavailable", schema)
        _assert_no_forbidden_result_fields(result)
        return result

    expected_hash = expected_master_taskbook_hash or _schema_expected_master_hash(schema)
    raw_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    yaml_blocks = extract_yaml_blocks(raw)
    specs = _required_field_specs(schema)
    checks = [_check_required_field(raw, spec) for spec in specs]
    master_binding_check = _check_master_binding(raw, expected_hash)
    supports_goal_check = _check_supports_project_goal(raw)
    forbidden_claims = _detect_forbidden_claims(raw, schema)
    evidence_package_check = _check_minimum_evidence_package(raw, schema)

    fail_closed_violations = [
        check["field"]
        for check in checks
        if check["fail_closed"] and check["result"] != FIELD_RESULT_PRESENT
    ]
    if master_binding_check["result"] != FIELD_RESULT_PRESENT:
        fail_closed_violations.append("master_taskbook_ref")
    if supports_goal_check["result"] != FIELD_RESULT_PRESENT:
        fail_closed_violations.append("supports_project_goal")
    if forbidden_claims:
        fail_closed_violations.append("forbidden_stage_authority_claim")
    if evidence_package_check["result"] != FIELD_RESULT_PRESENT:
        fail_closed_violations.append("minimum_evidence_package")
    fail_closed_violations = sorted(set(fail_closed_violations))

    required_field_violations = [
        check["field"]
        for check in checks
        if check["result"] != FIELD_RESULT_PRESENT
    ]
    if fail_closed_violations:
        validation_result = VALIDATION_RESULT_FAILED_CLOSED
        fail_closed_result = FAIL_CLOSED_RESULT_FAIL_CLOSED
    elif required_field_violations:
        validation_result = VALIDATION_RESULT_FAILED_REQUIRED_FIELDS
        fail_closed_result = FAIL_CLOSED_RESULT_PASS
    else:
        validation_result = VALIDATION_RESULT_PASSED
        fail_closed_result = FAIL_CLOSED_RESULT_PASS

    result = {
        "validator_status": "validated",
        "validation_result": validation_result,
        "fail_closed_result": fail_closed_result,
        "stage_taskbook_path": str(resolved_path) if resolved_path else None,
        "stage_taskbook_hash": raw_hash,
        "stage_id": _first_exact_value(raw, ("stage_id",)),
        "stage_name": _first_exact_value(raw, ("stage_name",)),
        "master_taskbook_ref": master_binding_check["master_taskbook_ref"],
        "supports_project_goal": supports_goal_check["supports_project_goal"],
        "required_field_check_table": checks,
        "master_binding_check": master_binding_check,
        "supports_project_goal_check": supports_goal_check,
        "minimum_evidence_package_check": evidence_package_check,
        "fail_closed_negative_case_results": {
            "forbidden_claims": forbidden_claims,
            "fail_closed_violations": fail_closed_violations,
        },
        "yaml_block_summary": {
            "block_count": len(yaml_blocks),
            "block_ids": [block["id"] for block in yaml_blocks],
        },
        "fail_closed_violations": fail_closed_violations,
        "required_field_violations": required_field_violations,
        "observed_git_head": observed_git_head,
        "not_validated": [],
        "remaining_risks": [
            "validator uses bounded markdown and YAML-block text checks; it does not perform full semantic review",
            "validator result is evidence only and does not create review acceptance or Delivery State Gate authority",
        ],
        "validator_result_is_authority": False,
        "creates_review_decision": False,
        "emits_gate_event": False,
        "writes_delivery_state": False,
        "failure_reason_or_none": None,
    }
    _assert_no_forbidden_result_fields(result)
    return result


def extract_yaml_blocks(raw_content: str) -> list[dict[str, str | None]]:
    pattern = re.compile(r"```yaml(?:\s+id=\"([^\"]+)\")?\n(.*?)\n```", re.DOTALL)
    blocks = []
    for match in pattern.finditer(raw_content):
        blocks.append({"id": match.group(1), "content": match.group(2)})
    return blocks


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _validate_schema_shape(schema: dict[str, Any]) -> None:
    if not isinstance(schema, dict):
        raise StageTaskbookValidatorError("STAGE_TASKBOOK_SCHEMA_INVALID", "Schema must be a JSON object.")
    if schema.get("schema_version") != "stage_taskbook_schema.v1":
        raise StageTaskbookValidatorError(
            "STAGE_TASKBOOK_SCHEMA_VERSION_UNSUPPORTED",
            "Stage Taskbook schema version is unsupported.",
            details={"schema_version": schema.get("schema_version")},
        )
    required_fields = schema.get("required_fields")
    if not isinstance(required_fields, list) or not required_fields:
        raise StageTaskbookValidatorError(
            "STAGE_TASKBOOK_SCHEMA_REQUIRED_FIELDS_MISSING",
            "Stage Taskbook schema must list required fields.",
        )


def _required_field_specs(schema: dict[str, Any]) -> tuple[RequiredFieldSpec, ...]:
    specs = []
    for item in schema.get("required_fields", []):
        if not isinstance(item, dict) or not isinstance(item.get("field"), str):
            continue
        specs.append(
            RequiredFieldSpec(
                field=item["field"],
                exact_keys=tuple(str(key) for key in item.get("exact_keys", []) if isinstance(key, str)),
                anchor_texts=tuple(str(text) for text in item.get("anchor_texts", []) if isinstance(text, str)),
                fail_closed=bool(item.get("fail_closed")),
            )
        )
    return tuple(specs)


def _read_stage_taskbook(
    stage_taskbook_path: str | Path | None,
    raw_content: str | None,
) -> tuple[str | None, Path | None, str | None]:
    if raw_content is not None:
        if not isinstance(raw_content, str) or raw_content == "":
            return None, None, "raw_content_empty_or_invalid"
        return raw_content, Path(stage_taskbook_path).resolve() if stage_taskbook_path else None, None
    if stage_taskbook_path is None:
        return None, None, "stage_taskbook_path_missing"
    path = Path(stage_taskbook_path).resolve()
    try:
        return path.read_text(encoding="utf-8"), path, None
    except FileNotFoundError:
        return None, path, "stage_taskbook_path_not_found"
    except UnicodeDecodeError:
        return None, path, "stage_taskbook_not_utf8"


def _check_required_field(raw_content: str, spec: RequiredFieldSpec) -> dict[str, Any]:
    lines = raw_content.splitlines()
    exact_match = _find_exact_field(lines, spec.exact_keys)
    if exact_match is not None:
        line_index, key, value = exact_match
        result, reason = _classify_exact_field(lines, line_index, value)
        return {
            "field": spec.field,
            "result": result,
            "fail_closed": spec.fail_closed,
            "matched_anchor": key,
            "line_number": line_index + 1,
            "failure_reason_or_none": reason,
        }

    anchor_match = _find_anchor(raw_content, lines, spec.anchor_texts)
    if anchor_match is not None:
        line_index, anchor = anchor_match
        result, reason = _classify_anchor_field(lines, line_index, spec)
        return {
            "field": spec.field,
            "result": result,
            "fail_closed": spec.fail_closed,
            "matched_anchor": anchor,
            "line_number": line_index + 1,
            "failure_reason_or_none": reason,
        }

    return {
        "field": spec.field,
        "result": FIELD_RESULT_MISSING,
        "fail_closed": spec.fail_closed,
        "matched_anchor": None,
        "line_number": None,
        "failure_reason_or_none": "required_field_anchor_missing",
    }


def _check_master_binding(raw_content: str, expected_master_hash: str | None) -> dict[str, Any]:
    master_path = _first_exact_value(raw_content, ("master_taskbook_path", "path"))
    master_hash = _master_ref_hash(raw_content)
    malformed = []
    if not master_path:
        malformed.append("master_taskbook_path_missing")
    elif master_path != "PROJECT_MASTER_TASKBOOK.md":
        malformed.append("master_taskbook_path")
    if not _is_sha256(master_hash):
        malformed.append("master_taskbook_raw_snapshot_sha256")
    if expected_master_hash and master_hash != expected_master_hash:
        malformed.append("master_hash_mismatch")
    if malformed:
        result = FIELD_RESULT_MALFORMED
        reason = ",".join(malformed)
    elif master_hash:
        result = FIELD_RESULT_PRESENT
        reason = None
    else:
        result = FIELD_RESULT_MISSING
        reason = "master_taskbook_ref_missing"
    return {
        "result": result,
        "master_taskbook_ref": {
            "path": master_path,
            "raw_snapshot_sha256": master_hash,
        },
        "expected_master_taskbook_hash": expected_master_hash,
        "failure_reason_or_none": reason,
    }


def _check_supports_project_goal(raw_content: str) -> dict[str, Any]:
    value = _first_exact_value(raw_content, ("supports_project_goal",))
    if value is None:
        return {
            "result": FIELD_RESULT_MISSING,
            "supports_project_goal": None,
            "failure_reason_or_none": "supports_project_goal_missing",
        }
    normalized = value.strip().lower()
    if normalized != "true":
        return {
            "result": FIELD_RESULT_MALFORMED,
            "supports_project_goal": value,
            "failure_reason_or_none": "supports_project_goal_not_true",
        }
    return {
        "result": FIELD_RESULT_PRESENT,
        "supports_project_goal": True,
        "failure_reason_or_none": None,
    }


def _check_minimum_evidence_package(raw_content: str, schema: dict[str, Any]) -> dict[str, Any]:
    required = [
        str(item)
        for item in schema.get("minimum_evidence_package_required_fields", [])
        if isinstance(item, str)
    ]
    section_text = _field_section_text(raw_content, "minimum_evidence_package")
    section_items = set(_list_items_under_key(section_text or "", "required_fields"))
    missing = [field for field in required if field not in section_items]
    result = FIELD_RESULT_PRESENT if not missing else FIELD_RESULT_MISSING
    return {
        "result": result,
        "required_fields": required,
        "section_items": sorted(section_items),
        "missing_fields": missing,
        "failure_reason_or_none": None if not missing else "minimum_evidence_package_missing_fields",
    }


def _detect_forbidden_claims(raw_content: str, schema: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    pattern_texts = list(_schema_forbidden_claim_patterns(schema))
    pattern_texts.extend(
        [
            "delivery_state_accepted: true",
            "accepted: true",
            "review_acceptance: true",
            "delivery_state: accepted",
            "executor_run_authorized: true",
            "execution_authority: granted",
        ]
    )
    unique_pattern_texts = tuple(dict.fromkeys(pattern_texts))
    findings = []
    for pattern_text in unique_pattern_texts:
        claim, pattern = _forbidden_claim_pattern(pattern_text)
        for match in pattern.finditer(raw_content):
            findings.append(
                {
                    "claim": claim,
                    "pattern": pattern_text,
                    "matched_text": match.group(0).strip(),
                    "line_number": raw_content[: match.start()].count("\n") + 1,
                }
            )
    return findings


def _known_unknown_result(
    reason: str,
    schema: dict[str, Any] | None,
    *,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    specs = _required_field_specs(schema or {}) if isinstance(schema, dict) else ()
    checks = [
        {
            "field": spec.field,
            "result": FIELD_RESULT_KNOWN_UNKNOWN,
            "fail_closed": spec.fail_closed,
            "matched_anchor": None,
            "line_number": None,
            "failure_reason_or_none": reason,
        }
        for spec in specs
    ]
    return {
        "validator_status": "known_unknown",
        "validation_result": VALIDATION_RESULT_KNOWN_UNKNOWN,
        "fail_closed_result": FAIL_CLOSED_RESULT_FAIL_CLOSED,
        "required_field_check_table": checks,
        "master_binding_check": {"result": FIELD_RESULT_KNOWN_UNKNOWN},
        "fail_closed_violations": [item["field"] for item in checks if item["fail_closed"]],
        "required_field_violations": [item["field"] for item in checks],
        "not_validated": ["stage_taskbook_schema_or_content"],
        "remaining_risks": ["stage taskbook validator could not inspect a usable schema and content pair"],
        "failure_reason_or_none": reason,
        "details": details or {},
    }


def _schema_expected_master_hash(schema: dict[str, Any]) -> str | None:
    master_binding = schema.get("master_binding")
    if isinstance(master_binding, dict):
        value = master_binding.get("required_raw_snapshot_sha256")
        if isinstance(value, str):
            return value.strip()
    return None


def _master_ref_hash(raw_content: str) -> str | None:
    for key in ("master_taskbook_raw_snapshot_sha256", "raw_snapshot_sha256"):
        value = _first_exact_value(raw_content, (key,))
        if _is_sha256(value):
            return value
    return None


def _first_exact_value(raw_content: str, keys: tuple[str, ...]) -> str | None:
    match = _find_exact_field(raw_content.splitlines(), keys)
    if match is None:
        return None
    return match[2].strip()


def _find_exact_field(lines: list[str], keys: tuple[str, ...]) -> tuple[int, str, str] | None:
    patterns = [
        (key, re.compile(rf"^\s*{re.escape(key)}\s*:\s*(.*)$"))
        for key in keys
    ]
    for line_index, line in enumerate(lines):
        for key, pattern in patterns:
            match = pattern.match(line)
            if match:
                return line_index, key, match.group(1)
    return None


def _find_anchor(raw_content: str, lines: list[str], anchors: tuple[str, ...]) -> tuple[int, str] | None:
    lowered = raw_content.lower()
    for anchor in anchors:
        if anchor.lower() not in lowered:
            continue
        for line_index, line in enumerate(lines):
            if anchor.lower() in line.lower():
                return line_index, anchor
    return None


def _classify_exact_field(lines: list[str], line_index: int, value: str) -> tuple[str, str | None]:
    stripped = value.strip()
    if _looks_malformed(stripped):
        return FIELD_RESULT_MALFORMED, "field_value_malformed"
    if stripped in {"", "[]", "{}"}:
        if _has_indented_body(lines, line_index):
            return FIELD_RESULT_PRESENT, None
        return FIELD_RESULT_EMPTY, "field_value_empty"
    return FIELD_RESULT_PRESENT, None


def _classify_anchor_field(
    lines: list[str],
    line_index: int,
    spec: RequiredFieldSpec,
) -> tuple[str, str | None]:
    if not spec.fail_closed:
        return FIELD_RESULT_PRESENT, None
    if spec.field not in ANCHOR_FALLBACK_ALLOWED_FIELDS:
        return FIELD_RESULT_MISSING, "machine_checkable_field_missing"
    if _has_anchor_body(lines, line_index):
        return FIELD_RESULT_PRESENT, None
    return FIELD_RESULT_EMPTY, "anchor_section_empty"


def _has_anchor_body(lines: list[str], line_index: int) -> bool:
    anchor_line = lines[line_index].strip()
    anchor_is_heading = anchor_line.startswith("#")
    in_fence = False
    for line in lines[line_index + 1 :]:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if anchor_is_heading and stripped.startswith("#") and not in_fence:
            return False
        return True
    return False


def _has_indented_body(lines: list[str], line_index: int) -> bool:
    current_indent = len(lines[line_index]) - len(lines[line_index].lstrip(" "))
    for line in lines[line_index + 1 :]:
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent > current_indent:
            return True
        return False
    return False


def _looks_malformed(value: str) -> bool:
    if not value:
        return False
    pairs = (("[", "]"), ("{", "}"), ("'", "'"), ('"', '"'))
    return any(value.startswith(start) and not value.endswith(end) for start, end in pairs)


def _field_section_text(raw_content: str, key: str) -> str | None:
    lines = raw_content.splitlines()
    match = _find_exact_field(lines, (key,))
    if match is None:
        return None
    line_index, _, _ = match
    base_indent = len(lines[line_index]) - len(lines[line_index].lstrip(" "))
    section_lines = [lines[line_index]]
    for line in lines[line_index + 1 :]:
        stripped = line.strip()
        if stripped.startswith("```"):
            break
        if stripped:
            indent = len(line) - len(line.lstrip(" "))
            if indent <= base_indent:
                break
        section_lines.append(line)
    return "\n".join(section_lines)


def _list_items_under_key(section_text: str, key: str) -> list[str]:
    lines = section_text.splitlines()
    match = _find_exact_field(lines, (key,))
    if match is None:
        return []
    line_index, _, _ = match
    key_indent = len(lines[line_index]) - len(lines[line_index].lstrip(" "))
    items = []
    for line in lines[line_index + 1 :]:
        stripped = line.strip()
        if not stripped:
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent <= key_indent:
            break
        match = re.match(r"^\s*-\s*([A-Za-z0-9_.-]+)\s*$", line)
        if match:
            items.append(match.group(1))
    return items


def _schema_forbidden_claim_patterns(schema: dict[str, Any] | None) -> tuple[str, ...]:
    if not isinstance(schema, dict):
        return ()
    raw_patterns = schema.get("forbidden_claim_patterns")
    if not isinstance(raw_patterns, list):
        return ()
    return tuple(item.strip() for item in raw_patterns if isinstance(item, str) and item.strip())


def _forbidden_claim_pattern(pattern_text: str) -> tuple[str, re.Pattern[str]]:
    if ":" in pattern_text:
        key, value = pattern_text.split(":", 1)
        key = key.strip()
        value = value.strip()
        pattern = re.compile(rf"^\s*{re.escape(key)}\s*:\s*{re.escape(value)}\s*$", re.I | re.M)
        return key, pattern
    words = re.escape(pattern_text.strip()).replace(r"\ ", r"\s+")
    return pattern_text.strip().replace(" ", "_"), re.compile(words, re.I)


def _is_sha256(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    clean = value.strip()
    return len(clean) == 64 and all(char in "0123456789abcdef" for char in clean)


def _ensure_inside_project(root: Path, path: Path, field_name: str) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise StageTaskbookValidatorError(
            "PATH_OUTSIDE_PROJECT",
            "Stage Taskbook validator path must stay inside the project.",
            details={field_name: str(path), "project_root": str(root)},
        ) from exc


def _assert_no_forbidden_result_fields(result: dict[str, Any]) -> None:
    forbidden = sorted(_forbidden_field_paths(result))
    if forbidden:
        raise StageTaskbookValidatorError(
            "FORBIDDEN_STAGE_VALIDATOR_RESULT_FIELD",
            "Stage Taskbook validator result contains forbidden authority fields.",
            details={"forbidden_fields": forbidden},
        )


def _forbidden_field_paths(value: Any, prefix: str = "") -> list[str]:
    if isinstance(value, dict):
        paths = []
        for key, nested_value in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if key in FORBIDDEN_VALIDATOR_RESULT_FIELDS:
                paths.append(path)
            paths.extend(_forbidden_field_paths(nested_value, path))
        return paths
    if isinstance(value, list):
        paths = []
        for index, item in enumerate(value):
            path = f"{prefix}[{index}]" if prefix else f"[{index}]"
            paths.extend(_forbidden_field_paths(item, path))
        return paths
    return []
