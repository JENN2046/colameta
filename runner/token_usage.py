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
    """Normalize executor or API token usage into canonical Runner-internal shape.

    Canonical fields (single source of truth):
      - prompt_input_tokens: total prompt input including cached tokens
      - fresh_input_tokens: non-cached prompt input, excluding cache read/write tokens
      - cache_read_tokens: tokens served from cache
      - cache_write_tokens: tokens written to cache (null if unavailable)
      - output_tokens: output tokens
      - reasoning_output_tokens: reasoning output tokens (0 if unavailable)
      - total_tokens: total tokens
      - cache_hit_rate: cache_read_tokens / prompt_input_tokens (null if unavailable)
      - cache_hit_rate_percent: formatted percentage or "-"

    Backward-compat legacy fields:
      - input_tokens == prompt_input_tokens
      - cached_input_tokens == cache_read_tokens
      - output_tokens, reasoning_output_tokens, total_tokens unchanged

    OpenCode raw shape: input_tokens=fresh, cache_read_tokens=N, cache_write_tokens=M
    Codex/OpenAI raw shape: input_tokens=total, cached_input_tokens=N
    """
    if not isinstance(usage, dict) or not usage:
        return _empty_usage(source=source, provider=provider, raw_usage={})

    warnings: list[str] = []
    raw_usage = _bounded_raw_usage(usage)

    raw_input_tokens = _coerce_token_int(usage.get("input_tokens"), "input_tokens", warnings)
    output_tokens = _coerce_token_int(usage.get("output_tokens"), "output_tokens", warnings)
    total_tokens = _coerce_optional_token_int(usage.get("total_tokens"), "total_tokens", warnings)

    input_details = usage.get("input_tokens_details")
    output_details = usage.get("output_tokens_details")

    # Cache read: try canonical field first, then legacy, then input_details
    cache_info_explicit = False
    cache_read_raw = usage.get("cache_read_tokens")
    if cache_read_raw is None:
        cache_read_raw = usage.get("cached_input_tokens")
    if cache_read_raw is None and isinstance(input_details, dict):
        cache_read_raw = input_details.get("cached_tokens")
        if cache_read_raw is not None:
            cache_info_explicit = True
    else:
        if cache_read_raw is not None:
            cache_info_explicit = True
    cache_read_tokens = _coerce_token_int(cache_read_raw, "cache_read_tokens", warnings)

    # Cache write: only if explicitly provided in raw dict
    cache_write_explicit = "cache_write_tokens" in usage
    cache_write_tokens: int | None = None
    if cache_write_explicit:
        cache_write_tokens = _coerce_optional_token_int(
            usage.get("cache_write_tokens"), "cache_write_tokens", warnings,
        )

    # Determine if raw uses canonical cache fields (OpenCode style)
    has_canonical_cache_fields = "cache_read_tokens" in usage or cache_write_explicit

    if has_canonical_cache_fields:
        # OpenCode style: input_tokens is fresh input, cache is separate
        prompt_input_tokens = raw_input_tokens + cache_read_tokens + (cache_write_tokens or 0)
        fresh_input_tokens = raw_input_tokens
        cache_info_explicit = True
    else:
        # Standard (Codex/OpenAI) style: input_tokens is total
        prompt_input_tokens = raw_input_tokens
        fresh_input_tokens = max(prompt_input_tokens - cache_read_tokens, 0)

    reasoning_raw = usage.get("reasoning_output_tokens")
    if reasoning_raw is None and isinstance(output_details, dict):
        reasoning_raw = output_details.get("reasoning_tokens")
    reasoning_output_tokens = _coerce_token_int(
        reasoning_raw,
        "reasoning_output_tokens",
        warnings,
    )

    if cache_read_tokens > prompt_input_tokens:
        warnings.append("cache_read_tokens_exceeds_prompt_input_tokens")

    if total_tokens is None:
        total_tokens = prompt_input_tokens + output_tokens

    cache_hit_rate = None
    cache_hit_rate_percent = "-"
    if prompt_input_tokens > 0 and cache_info_explicit:
        cache_hit_rate = cache_read_tokens / prompt_input_tokens
        cache_hit_rate_percent = f"{cache_hit_rate * 100:.1f}%"

    return {
        "available": True,
        "source": _first_non_empty_str(source, usage.get("source")),
        "provider": _first_non_empty_str(provider, usage.get("provider")),
        "prompt_input_tokens": prompt_input_tokens,
        "fresh_input_tokens": fresh_input_tokens,
        "cache_read_tokens": cache_read_tokens,
        "cache_write_tokens": cache_write_tokens,
        "output_tokens": output_tokens,
        "reasoning_output_tokens": reasoning_output_tokens,
        "total_tokens": total_tokens,
        "cache_hit_rate": cache_hit_rate,
        "cache_hit_rate_percent": cache_hit_rate_percent,
        "input_tokens": prompt_input_tokens,
        "cached_input_tokens": cache_read_tokens,
        "raw_usage": raw_usage,
        "warnings": warnings,
    }


def _empty_usage(*, source: str, provider: str, raw_usage: dict[str, Any]) -> dict[str, Any]:
    return {
        "available": False,
        "source": str(source or ""),
        "provider": str(provider or ""),
        "prompt_input_tokens": 0,
        "fresh_input_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": None,
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
