import fnmatch


def normalize(path: str) -> str:
    normalized = path.strip().replace("\\", "/")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def match(pattern: str, path: str) -> bool:
    pattern = normalize(pattern)
    path = normalize(path)
    if not pattern or not path:
        return False
    return _match_parts(pattern.split("/"), path.split("/"))


def match_any(path: str, patterns: list[str]) -> bool:
    if not patterns:
        return False
    return any(match(p, path) for p in patterns)


def _match_parts(patterns: list[str], parts: list[str]) -> bool:
    while patterns and patterns[0] == "**":
        if _match_parts(patterns[1:], parts):
            return True
        if not parts:
            return False
        parts = parts[1:]

    if not patterns and not parts:
        return True
    if not patterns or not parts:
        return False

    if not fnmatch.fnmatch(parts[0], patterns[0]):
        return False

    return _match_parts(patterns[1:], parts[1:])
