import difflib

from runner.file_signature import sha256_text


def synthetic_unified_diff(rel_path: str, old_content: str, new_content: str) -> str:
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)
    diff = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=f"a/{rel_path}",
        tofile=f"b/{rel_path}",
    )
    return "".join(diff)


def truncate_text(text: str, max_chars: int) -> str:
    if len(text) > max_chars:
        return text[:max_chars]
    return text


def diff_hash(text: str) -> str:
    return sha256_text(text)
