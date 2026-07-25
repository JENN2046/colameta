from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import re
import unicodedata
from typing import Any

import yaml


HASH_BINDING_RESULT_MATCH = "match"
HASH_BINDING_RESULT_MISMATCH = "mismatch"
HASH_BINDING_RESULT_MISSING_INPUT = "missing_input"
HASH_BINDING_RESULT_KNOWN_UNKNOWN = "known_unknown"
HASH_BINDING_RESULT_VALUES = (
    HASH_BINDING_RESULT_MATCH,
    HASH_BINDING_RESULT_MISMATCH,
    HASH_BINDING_RESULT_MISSING_INPUT,
    HASH_BINDING_RESULT_KNOWN_UNKNOWN,
)

FAIL_CLOSED_RESULT_PASS = "pass"
FAIL_CLOSED_RESULT_FAIL_CLOSED = "fail_closed"

CANONICAL_PAYLOAD_SCHEMA_VERSION = "colameta.master_taskbook_canonical_payload.v1"
CANONICALIZER_VERSION = "ColaMeta.master_taskbook_canonicalizer.v1"
FREEZE_HASH_DOMAIN_SEPARATOR = "ColaMeta.freeze_candidate.v1"
MASTER_SUMMARY_BLOCK_ID = "master-taskbook-canonical-summary"
HASH_POLICY_BLOCK_ID = "hash-policy"
YAML_FENCE_PATTERN = re.compile(
    r'^```yaml[ \t]+id="(?P<block_id>[A-Za-z0-9][A-Za-z0-9._-]*)"[ \t]*\n'
    r"(?P<body>.*?)"
    r"^```[ \t]*$",
    re.MULTILINE | re.DOTALL,
)
HEADING_PATTERN = re.compile(r"^(?P<marks>#{1,6})[ \t]+(?P<title>.+?)\s*$")

FORBIDDEN_HASH_BINDING_RESULT_FIELDS = frozenset(
    {
        "delivery_state",
        "accepted",
        "executor_authorization",
        "active_master_authority",
        "review_decision_outcome",
        "gate_event",
        "canonical_payload_hash",
        "canonical_receipt_hash",
    }
)


class MasterTaskbookHashBindingError(ValueError):
    def __init__(self, error_code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.details = details or {}


class _UniqueKeySafeLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(
    loader: _UniqueKeySafeLoader,
    node: yaml.nodes.MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise MasterTaskbookHashBindingError(
                "CANONICAL_YAML_KEY_INVALID",
                "Canonical YAML mapping keys must be hashable.",
            ) from exc
        if duplicate:
            raise MasterTaskbookHashBindingError(
                "CANONICAL_YAML_DUPLICATE_KEY",
                "Canonical YAML blocks must not contain duplicate mapping keys.",
                details={"duplicate_key": str(key)},
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def parse_master_taskbook_yaml_blocks(raw_content: str) -> dict[str, Any]:
    normalized_source = _normalize_source_text(raw_content)
    blocks: dict[str, Any] = {}
    for match in YAML_FENCE_PATTERN.finditer(normalized_source):
        block_id = match.group("block_id")
        if block_id in blocks:
            raise MasterTaskbookHashBindingError(
                "CANONICAL_YAML_BLOCK_ID_DUPLICATE",
                "Canonical YAML block ids must be unique.",
                details={"block_id": block_id},
            )
        loader = _UniqueKeySafeLoader(match.group("body"))
        try:
            parsed = loader.get_single_data()
        except MasterTaskbookHashBindingError:
            raise
        except yaml.YAMLError as exc:
            raise MasterTaskbookHashBindingError(
                "CANONICAL_YAML_INVALID",
                "A canonical YAML block could not be parsed safely.",
                details={"block_id": block_id, "yaml_error": str(exc)},
            ) from exc
        finally:
            loader.dispose()
        if parsed is None:
            raise MasterTaskbookHashBindingError(
                "CANONICAL_YAML_BLOCK_EMPTY",
                "Canonical YAML blocks must not be empty.",
                details={"block_id": block_id},
            )
        blocks[block_id] = parsed
    return blocks


def build_master_taskbook_canonical_payload(raw_content: str) -> dict[str, Any]:
    normalized_source = _normalize_source_text(raw_content)
    blocks = parse_master_taskbook_yaml_blocks(normalized_source)
    master = _required_mapping_root(blocks, MASTER_SUMMARY_BLOCK_ID, "master_taskbook")
    hash_policy = _required_mapping_root(blocks, HASH_POLICY_BLOCK_ID, "hash_policy")
    reproducibility = _required_mapping(hash_policy, "reproducible_canonicalization")
    _validate_reproducibility_contract(reproducibility)

    manifest = hash_policy.get("canonical_fields")
    if not isinstance(manifest, list) or not manifest or not all(isinstance(item, str) and item for item in manifest):
        raise MasterTaskbookHashBindingError(
            "CANONICAL_FIELD_MANIFEST_INVALID",
            "hash_policy.canonical_fields must be a non-empty list of selector strings.",
        )
    normalized_manifest = [_normalize_string(item) for item in manifest]
    if any(not item for item in normalized_manifest):
        raise MasterTaskbookHashBindingError(
            "CANONICAL_FIELD_MANIFEST_INVALID",
            "hash_policy.canonical_fields selectors must remain non-empty after normalization.",
        )
    if len(normalized_manifest) != len(set(normalized_manifest)):
        raise MasterTaskbookHashBindingError(
            "CANONICAL_FIELD_MANIFEST_DUPLICATE",
            "hash_policy.canonical_fields must not contain duplicate normalized selectors.",
        )

    section_selectors = _required_mapping(hash_policy, "markdown_section_selectors")
    values = {
        selector: _normalize_json_value(
            _resolve_canonical_selector(
                selector=selector,
                master=master,
                hash_policy=hash_policy,
                blocks=blocks,
                section_selectors=section_selectors,
                normalized_source=normalized_source,
            )
        )
        for selector in normalized_manifest
    }
    canonical_path = master.get("canonical_path")
    if not isinstance(canonical_path, str) or not canonical_path.strip():
        raise MasterTaskbookHashBindingError(
            "CANONICAL_SOURCE_PATH_INVALID",
            "master_taskbook.canonical_path must be a non-empty string.",
        )

    return {
        "schema_version": CANONICAL_PAYLOAD_SCHEMA_VERSION,
        "canonicalizer_version": CANONICALIZER_VERSION,
        "source_document": _normalize_string(canonical_path),
        "field_manifest": normalized_manifest,
        "field_values": values,
    }


def canonicalize_master_taskbook(raw_content: str | bytes) -> dict[str, Any]:
    if isinstance(raw_content, bytes):
        raw_bytes = raw_content
        try:
            source_text = raw_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise MasterTaskbookHashBindingError(
                "CANONICAL_SOURCE_NOT_UTF8",
                "Master Taskbook source bytes must decode as UTF-8.",
            ) from exc
    elif isinstance(raw_content, str):
        source_text = raw_content
        raw_bytes = raw_content.encode("utf-8")
    else:
        raise MasterTaskbookHashBindingError(
            "CANONICAL_SOURCE_INVALID",
            "Master Taskbook source must be UTF-8 bytes or text.",
        )
    if not raw_bytes:
        raise MasterTaskbookHashBindingError(
            "CANONICAL_SOURCE_INVALID",
            "Master Taskbook source must not be empty.",
        )
    payload = build_master_taskbook_canonical_payload(source_text)
    canonical_json = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    canonical_bytes = canonical_json.encode("utf-8")
    freeze_input = f"{FREEZE_HASH_DOMAIN_SEPARATOR}\n".encode("utf-8") + canonical_bytes
    return {
        "canonicalization_status": "computed_evidence_only",
        "payload_schema_version": CANONICAL_PAYLOAD_SCHEMA_VERSION,
        "canonicalizer_version": CANONICALIZER_VERSION,
        "yaml_library": "PyYAML",
        "yaml_library_version": str(yaml.__version__),
        "hash_algorithm": "sha256",
        "domain_separator": FREEZE_HASH_DOMAIN_SEPARATOR,
        "raw_snapshot_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "canonical_payload_sha256": hashlib.sha256(canonical_bytes).hexdigest(),
        "freeze_content_hash": hashlib.sha256(freeze_input).hexdigest(),
        "canonical_payload_field_count": len(payload["field_manifest"]),
        "canonical_payload": payload,
        "canonical_json": canonical_json,
        "canonicalization_result_is_authority": False,
        "canonical_receipt_generated": False,
    }


def bind_master_hashes(
    *,
    registry_input: dict[str, Any] | None,
    reader_result: dict[str, Any] | None,
    validator_result: dict[str, Any] | None,
    observed_git_head: str | None = None,
    source_version_taskbook_refs: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    registry_hash = _registry_master_hash(registry_input)
    reader_hash = _reader_master_hash(reader_result)
    validator_hash = _validator_input_hash(validator_result)
    inputs = {
        "registry_master_raw_snapshot_sha256": registry_hash,
        "reader_raw_content_sha256": reader_hash,
        "validator_input_raw_content_sha256": validator_hash,
    }
    missing_inputs = sorted(name for name, value in inputs.items() if not _is_sha256(value))
    known_unknown_inputs = _known_unknown_inputs(registry_input, reader_result, validator_result)

    if missing_inputs:
        binding_result = HASH_BINDING_RESULT_MISSING_INPUT
        fail_closed_result = FAIL_CLOSED_RESULT_FAIL_CLOSED
        failure_reason = "required_hash_input_missing"
    elif known_unknown_inputs:
        binding_result = HASH_BINDING_RESULT_KNOWN_UNKNOWN
        fail_closed_result = FAIL_CLOSED_RESULT_FAIL_CLOSED
        failure_reason = "upstream_input_known_unknown"
    else:
        unique_hashes = set(inputs.values())
        if len(unique_hashes) == 1:
            binding_result = HASH_BINDING_RESULT_MATCH
            fail_closed_result = FAIL_CLOSED_RESULT_PASS
            failure_reason = None
        else:
            binding_result = HASH_BINDING_RESULT_MISMATCH
            fail_closed_result = FAIL_CLOSED_RESULT_FAIL_CLOSED
            failure_reason = "master_hash_inputs_do_not_match"

    result = {
        "hash_binding_status": "evaluated",
        "hash_binding_result": binding_result,
        "fail_closed_result": fail_closed_result,
        "registry_master_raw_snapshot_sha256": registry_hash,
        "reader_raw_content_sha256": reader_hash,
        "validator_input_raw_content_sha256": validator_hash,
        "observed_git_head": _first_non_empty(
            observed_git_head,
            _dict_get(reader_result, "observed_git_head"),
            _dict_get(_dict_get(validator_result, "reader_result_input"), "observed_git_head"),
        ),
        "source_version_taskbook_refs": [dict(item) for item in source_version_taskbook_refs or []],
        "missing_inputs": missing_inputs,
        "known_unknown_inputs": known_unknown_inputs,
        "failure_reason_or_none": failure_reason,
        "canonical_receipt_generation": "deferred_not_generated",
        "canonical_payload_hash_finalization": "deferred_not_finalized",
        "binding_result_is_authority": False,
        "forbidden_authority_claims_present": [],
    }
    _assert_no_forbidden_result_fields(result)
    return result


def _required_mapping_root(blocks: dict[str, Any], block_id: str, root_key: str) -> dict[str, Any]:
    block = blocks.get(block_id)
    if not isinstance(block, dict):
        raise MasterTaskbookHashBindingError(
            "CANONICAL_YAML_BLOCK_MISSING",
            "A required canonical YAML block is missing or malformed.",
            details={"block_id": block_id},
        )
    return _required_mapping(block, root_key)


def _required_mapping(value: dict[str, Any], key: str) -> dict[str, Any]:
    child = value.get(key)
    if not isinstance(child, dict):
        raise MasterTaskbookHashBindingError(
            "CANONICAL_MAPPING_MISSING",
            "A required canonical mapping is missing or malformed.",
            details={"key": key},
        )
    return child


def _validate_reproducibility_contract(contract: dict[str, Any]) -> None:
    expected = {
        "payload_schema_version": CANONICAL_PAYLOAD_SCHEMA_VERSION,
        "canonicalizer_version": CANONICALIZER_VERSION,
        "domain_separator": FREEZE_HASH_DOMAIN_SEPARATOR,
    }
    mismatches = {
        key: {"expected": expected_value, "actual": contract.get(key)}
        for key, expected_value in expected.items()
        if contract.get(key) != expected_value
    }
    if mismatches:
        raise MasterTaskbookHashBindingError(
            "CANONICALIZER_CONTRACT_MISMATCH",
            "Master canonicalization contract does not match the installed canonicalizer.",
            details={"mismatches": mismatches},
        )
    parser_contract = _required_mapping(contract, "yaml_parser_contract")
    parser_expected = {
        "library": "PyYAML",
        "version": str(yaml.__version__),
        "loader": "safe_yaml",
    }
    parser_mismatches = {
        key: {"expected": expected_value, "actual": parser_contract.get(key)}
        for key, expected_value in parser_expected.items()
        if str(parser_contract.get(key)) != expected_value
    }
    if parser_mismatches:
        raise MasterTaskbookHashBindingError(
            "CANONICALIZER_RUNTIME_DEPENDENCY_MISMATCH",
            "Master YAML parser contract does not match the installed canonicalizer dependency.",
            details={"mismatches": parser_mismatches},
        )


def _resolve_canonical_selector(
    *,
    selector: str,
    master: dict[str, Any],
    hash_policy: dict[str, Any],
    blocks: dict[str, Any],
    section_selectors: dict[str, Any],
    normalized_source: str,
) -> Any:
    prefix, separator, remainder = selector.partition(".")
    if not separator or not remainder:
        raise MasterTaskbookHashBindingError(
            "CANONICAL_SELECTOR_INVALID",
            "Canonical field selectors must use a supported prefix and path.",
            details={"selector": selector},
        )
    if prefix == "master_taskbook":
        return _resolve_value_path(master, remainder, selector)
    if prefix == "hash_policy":
        return _resolve_value_path(hash_policy, remainder, selector)
    if prefix == "yaml_block":
        if remainder not in blocks:
            raise MasterTaskbookHashBindingError(
                "CANONICAL_YAML_SELECTOR_MISSING",
                "Canonical YAML selector references a missing fenced block.",
                details={"selector": selector, "block_id": remainder},
            )
        return blocks[remainder]
    if prefix == "markdown_section":
        heading = section_selectors.get(remainder)
        if not isinstance(heading, str) or not heading.strip():
            raise MasterTaskbookHashBindingError(
                "CANONICAL_MARKDOWN_SELECTOR_MISSING",
                "Canonical Markdown selector has no exact heading mapping.",
                details={"selector": selector, "section_slug": remainder},
            )
        return _extract_markdown_section(normalized_source, heading)
    raise MasterTaskbookHashBindingError(
        "CANONICAL_SELECTOR_PREFIX_UNSUPPORTED",
        "Canonical field selector uses an unsupported prefix.",
        details={"selector": selector, "prefix": prefix},
    )


def _resolve_value_path(value: Any, raw_path: str, selector: str) -> Any:
    tokens = raw_path.split(".")

    def walk(current: Any, index: int) -> Any:
        if index == len(tokens):
            return current
        token = tokens[index]
        wildcard = token.endswith("[*]")
        key = token[:-3] if wildcard else token
        if not isinstance(current, dict) or key not in current:
            raise MasterTaskbookHashBindingError(
                "CANONICAL_SELECTOR_PATH_MISSING",
                "Canonical field selector does not resolve to a source value.",
                details={"selector": selector, "missing_component": key},
            )
        child = current[key]
        if wildcard:
            if not isinstance(child, list):
                raise MasterTaskbookHashBindingError(
                    "CANONICAL_SELECTOR_WILDCARD_INVALID",
                    "Canonical wildcard selectors must resolve to a list.",
                    details={"selector": selector, "component": key},
                )
            return [walk(item, index + 1) for item in child]
        return walk(child, index + 1)

    return walk(value, 0)


def _extract_markdown_section(normalized_source: str, exact_heading: str) -> str:
    lines = normalized_source.split("\n")
    matching_indexes = [index for index, line in enumerate(lines) if line == exact_heading]
    if len(matching_indexes) != 1:
        raise MasterTaskbookHashBindingError(
            "CANONICAL_MARKDOWN_HEADING_AMBIGUOUS",
            "Canonical Markdown headings must match exactly once.",
            details={"heading": exact_heading, "match_count": len(matching_indexes)},
        )
    start = matching_indexes[0]
    heading_match = HEADING_PATTERN.match(lines[start])
    if heading_match is None:
        raise MasterTaskbookHashBindingError(
            "CANONICAL_MARKDOWN_HEADING_INVALID",
            "Canonical Markdown selector must point to a Markdown heading.",
            details={"heading": exact_heading},
        )
    level = len(heading_match.group("marks"))
    end = len(lines)
    for index in range(start + 1, len(lines)):
        candidate = HEADING_PATTERN.match(lines[index])
        if candidate is not None and len(candidate.group("marks")) <= level:
            end = index
            break
    section_lines = [line.rstrip(" \t") for line in lines[start:end]]
    while section_lines and not section_lines[-1]:
        section_lines.pop()
    return "\n".join(section_lines)


def _normalize_source_text(value: str) -> str:
    if not isinstance(value, str):
        raise MasterTaskbookHashBindingError(
            "CANONICAL_SOURCE_INVALID",
            "Master Taskbook source must be text.",
        )
    return unicodedata.normalize("NFC", value.replace("\r\n", "\n").replace("\r", "\n"))


def _normalize_string(value: str) -> str:
    return _normalize_source_text(value).strip()


def _normalize_json_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise MasterTaskbookHashBindingError(
                "CANONICAL_NUMBER_INVALID",
                "Canonical numeric values must be finite.",
            )
        return value
    if isinstance(value, str):
        return _normalize_string(value)
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat()
    if isinstance(value, list):
        return [_normalize_json_value(item) for item in value]
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, child in value.items():
            if not isinstance(key, str):
                raise MasterTaskbookHashBindingError(
                    "CANONICAL_MAPPING_KEY_INVALID",
                    "Canonical mapping keys must be strings.",
                    details={"key_type": type(key).__name__},
                )
            normalized_key = _normalize_string(key)
            if normalized_key in normalized:
                raise MasterTaskbookHashBindingError(
                    "CANONICAL_MAPPING_KEY_COLLISION",
                    "Canonical mapping keys must remain unique after normalization.",
                    details={"normalized_key": normalized_key},
                )
            normalized[normalized_key] = _normalize_json_value(child)
        return normalized
    raise MasterTaskbookHashBindingError(
        "CANONICAL_VALUE_TYPE_UNSUPPORTED",
        "Canonical payload contains an unsupported YAML value type.",
        details={"value_type": type(value).__name__},
    )


def _registry_master_hash(registry_input: dict[str, Any] | None) -> str | None:
    if not isinstance(registry_input, dict):
        return None
    direct = _dict_get(registry_input, "registry_master_raw_snapshot_sha256")
    if direct is not None:
        return str(direct).strip()
    expected = _dict_get(registry_input, "master_expected_sha256")
    if expected is not None:
        return str(expected).strip()
    record = _dict_get(registry_input, "record")
    record_hash = _dict_get(record, "master_raw_snapshot_sha256")
    if record_hash is not None:
        return str(record_hash).strip()
    raw = _dict_get(registry_input, "master_raw_snapshot_sha256")
    return str(raw).strip() if raw is not None else None


def _reader_master_hash(reader_result: dict[str, Any] | None) -> str | None:
    raw = _dict_get(reader_result, "raw_content_sha256")
    return str(raw).strip() if raw is not None else None


def _validator_input_hash(validator_result: dict[str, Any] | None) -> str | None:
    direct = _dict_get(validator_result, "validator_input_raw_content_sha256")
    if direct is not None:
        return str(direct).strip()
    reader_input = _dict_get(validator_result, "reader_result_input")
    raw = _dict_get(reader_input, "raw_content_sha256")
    return str(raw).strip() if raw is not None else None


def _known_unknown_inputs(
    registry_input: dict[str, Any] | None,
    reader_result: dict[str, Any] | None,
    validator_result: dict[str, Any] | None,
) -> list[str]:
    known_unknown = []
    if _dict_get(registry_input, "hash_binding_input_status") == HASH_BINDING_RESULT_KNOWN_UNKNOWN:
        known_unknown.append("registry_input")
    if _dict_get(reader_result, "read_status") == HASH_BINDING_RESULT_KNOWN_UNKNOWN:
        known_unknown.append("reader_result")
    if _dict_get(validator_result, "validation_result") == HASH_BINDING_RESULT_KNOWN_UNKNOWN:
        known_unknown.append("validator_result")
    if _dict_get(validator_result, "validator_status") == HASH_BINDING_RESULT_KNOWN_UNKNOWN:
        known_unknown.append("validator_result")
    return sorted(set(known_unknown))


def _dict_get(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return None


def _first_non_empty(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _is_sha256(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    clean = value.strip()
    return len(clean) == 64 and all(char in "0123456789abcdef" for char in clean)


def _assert_no_forbidden_result_fields(result: dict[str, Any]) -> None:
    forbidden = sorted(key for key in result if key in FORBIDDEN_HASH_BINDING_RESULT_FIELDS)
    if forbidden:
        raise MasterTaskbookHashBindingError(
            "FORBIDDEN_HASH_BINDING_RESULT_FIELD",
            "Hash binding result contains forbidden authority or receipt fields.",
            details={"forbidden_fields": forbidden},
        )
