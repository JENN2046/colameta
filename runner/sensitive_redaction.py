import re


_AUTHORIZATION_BEARER_PATTERN = re.compile(r"(?i)(authorization:\s*bearer\s+)\S+")
_BEARER_PATTERN = re.compile(r"(?i)(bearer\s+)\S+")
_X_API_KEY_HEADER_PATTERN = re.compile(r"(?i)(x-api-key:\s*)\S+")
_ACCESS_TOKEN_PATTERN = re.compile(r"(?i)(access_token['\"]?\s*[:=]\s*['\"]?)[^\s'\"]+")
_AUTHORIZATION_CODE_PATTERN = re.compile(r"(?i)(authorization_code['\"]?\s*[:=]\s*['\"]?)[^\s'\"]+")
_API_KEY_PATTERN = re.compile(r"(?i)(api[_-]?key['\"]?\s*[:=]\s*['\"]?)[^\s'\"]+")
_TOKEN_PATTERN = re.compile(r"(?i)(token['\"]?\s*[:=]\s*['\"]?)[^\s'\"]+")
_SECRET_PATTERN = re.compile(r"(?i)(secret['\"]?\s*[:=]\s*['\"]?)[^\s'\"]+")
_PASSWORD_PATTERN = re.compile(r"(?i)(password['\"]?\s*[:=]\s*['\"]?)[^\s'\"]+")
_OAUTH_STORE_PATTERN = re.compile(r"(?i)(oauth.store|oauth-store)[A-Za-z0-9_.+/=-]{0,50}")
_SK_TOKEN_PATTERN = re.compile(r"(?i)\b(sk-)[A-Za-z0-9_.+/=-]{3,}")
_GH_TOKEN_PATTERN = re.compile(r"(?i)\b(gh[pousr]_)[A-Za-z0-9_.+/=-]{3,}")
_URL_USERINFO_PATTERN = re.compile(r"(?i)https://[^/\s@]+@")
_ENV_REFERENCE_PATTERN = re.compile(r"(?i)(\.env(?:\.[A-Za-z0-9_.-]+)?)(?:[^\n]*)")


def redact_sensitive_text(
    text: str,
    *,
    replacement_token: str = "<redacted>",
    preserve_token_prefix: bool = False,
) -> str:
    result = text if isinstance(text, str) else str(text or "")

    def replace_prefixed(pattern: re.Pattern[str]) -> None:
        nonlocal result
        result = pattern.sub(lambda match: f"{match.group(1)}{replacement_token}", result)

    replace_prefixed(_AUTHORIZATION_BEARER_PATTERN)
    replace_prefixed(_BEARER_PATTERN)
    replace_prefixed(_X_API_KEY_HEADER_PATTERN)
    replace_prefixed(_ACCESS_TOKEN_PATTERN)
    replace_prefixed(_AUTHORIZATION_CODE_PATTERN)
    replace_prefixed(_API_KEY_PATTERN)
    replace_prefixed(_TOKEN_PATTERN)
    replace_prefixed(_SECRET_PATTERN)
    replace_prefixed(_PASSWORD_PATTERN)
    result = _OAUTH_STORE_PATTERN.sub(r"\1", result)
    if preserve_token_prefix:
        result = _SK_TOKEN_PATTERN.sub(lambda match: f"{match.group(1)}{replacement_token}", result)
        result = _GH_TOKEN_PATTERN.sub(lambda match: f"{match.group(1)}{replacement_token}", result)
    else:
        result = _SK_TOKEN_PATTERN.sub(replacement_token, result)
        result = _GH_TOKEN_PATTERN.sub(replacement_token, result)
    result = _URL_USERINFO_PATTERN.sub("https://***@", result)
    result = _ENV_REFERENCE_PATTERN.sub(rf"\1 {replacement_token}", result)
    return result
