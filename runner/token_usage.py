from __future__ import annotations

from typing import Any


RAW_USAGE_MAX_KEYS = 40
RAW_USAGE_STRING_MAX_CHARS = 500


def normalize_token_usage(
    usage: dict[str, Any] | None,
    *,
    source: str = "",
    provider: str = "",
) -> dict[str, Any]:
    """Normalize executor or API token usage into one Runner-internal shape."""
    if not isinstance(usage, dict) or not usage:
        return _empty_usage(source=source, provider=provider, raw_usage={})

    warnings: list[str] = []
    raw_usage = _bounded_raw_usage(usage)

    input_tokens = _coerce_token_int(usage.get("input_tokens"), "input_tokens", warnings)
    output_tokens = _coerce_token_int(usage.get("output_tokens"), "output_tokens", warnings)
    total_tokens = _coerce_optional_token_int(usage.get("total_tokens"), "total_tokens", warnings)

    input_details = usage.get("input_tokens_details")
    output_details = usage.get("output_tokens_details")
    cached_raw = usage.get("cached_input_tokens")
    if cached_raw is None and isinstance(input_details, dict):
        cached_raw = input_details.get("cached_tokens")
    cached_input_tokens = _coerce_token_int(cached_raw, "cached_input_tokens", warnings)

    reasoning_raw = usage.get("reasoning_output_tokens")
    if reasoning_raw is None and isinstance(output_details, dict):
        reasoning_raw = output_details.get("reasoning_tokens")
    reasoning_output_tokens = _coerce_token_int(
        reasoning_raw,
        "reasoning_output_tokens",
        warnings,
    )

    if cached_input_tokens > input_tokens:
        warnings.append("cached_input_tokens_clamped_to_input_tokens")
        cached_input_tokens = input_tokens

    if total_tokens is None:
        total_tokens = input_tokens + output_tokens

    cache_hit_rate = None
    cache_hit_rate_percent = "-"
    if input_tokens > 0:
        cache_hit_rate = cached_input_tokens / input_tokens
        cache_hit_rate_percent = f"{cache_hit_rate * 100:.1f}%"

    return {
        "available": True,
        "source": _first_non_empty_str(source, usage.get("source")),
        "provider": _first_non_empty_str(provider, usage.get("provider")),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_input_tokens": cached_input_tokens,
        "reasoning_output_tokens": reasoning_output_tokens,
        "total_tokens": total_tokens,
        "cache_hit_rate": cache_hit_rate,
        "cache_hit_rate_percent": cache_hit_rate_percent,
        "raw_usage": raw_usage,
        "warnings": warnings,
    }


def _empty_usage(*, source: str, provider: str, raw_usage: dict[str, Any]) -> dict[str, Any]:
    return {
        "available": False,
        "source": str(source or ""),
        "provider": str(provider or ""),
        "input_tokens": 0,
        "output_tokens": 0,
        "cached_input_tokens": 0,
        "reasoning_output_tokens": 0,
        "total_tokens": None,
        "cache_hit_rate": None,
        "cache_hit_rate_percent": "-",
        "raw_usage": raw_usage,
        "warnings": [],
    }


def _coerce_optional_token_int(value: Any, field: str, warnings: list[str]) -> int | None:
    if value is None:
        return None
    return _coerce_token_int(value, field, warnings)


def _coerce_token_int(value: Any, field: str, warnings: list[str]) -> int:
    if value is None:
        return 0
    if isinstance(value, bool):
        warnings.append(f"{field}_invalid")
        return 0
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        warnings.append(f"{field}_invalid")
        return 0
    if numeric < 0:
        warnings.append(f"{field}_negative_clamped_to_zero")
        return 0
    return numeric


def _first_non_empty_str(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _bounded_raw_usage(usage: dict[str, Any]) -> dict[str, Any]:
    raw: dict[str, Any] = {}
    for index, (key, value) in enumerate(usage.items()):
        if index >= RAW_USAGE_MAX_KEYS:
            raw["__truncated__"] = True
            break
        raw[str(key)] = _bounded_raw_value(value)
    return raw


def _bounded_raw_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(k): _bounded_raw_value(v)
            for index, (k, v) in enumerate(value.items())
            if index < RAW_USAGE_MAX_KEYS
        }
    if isinstance(value, list):
        return [_bounded_raw_value(item) for item in value[:RAW_USAGE_MAX_KEYS]]
    if isinstance(value, str):
        if len(value) > RAW_USAGE_STRING_MAX_CHARS:
            return value[:RAW_USAGE_STRING_MAX_CHARS]
        return value
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:RAW_USAGE_STRING_MAX_CHARS]
