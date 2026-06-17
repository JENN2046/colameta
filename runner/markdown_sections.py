import re
from typing import Any


def parse_headings(content: str) -> list[dict[str, Any]]:
    headings: list[dict[str, Any]] = []
    for i, line in enumerate(content.splitlines(), start=1):
        m = re.match(r"^(#{1,6})\s+(.+)$", line)
        if m:
            level = len(m.group(1))
            heading = m.group(2).strip()
            slug = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff\- ]", "", heading.lower())
            slug = re.sub(r"\s+", "-", slug.strip())
            headings.append({
                "level": level,
                "heading": heading,
                "line": i,
                "slug": slug,
            })
    return headings


def find_section(content: str, heading: str) -> dict[str, Any] | None:
    if not heading.strip():
        return None
    heading = heading.strip()

    candidates: list[dict[str, Any]] = []
    for i, line in enumerate(content.splitlines(), start=1):
        m = re.match(r"^(#{1,6})\s+(.+)$", line)
        if m:
            h_text = m.group(2).strip()
            if h_text.lower() == heading.lower():
                candidates.append({
                    "line": i,
                    "level": len(m.group(1)),
                    "heading": h_text,
                })

    if len(candidates) == 0:
        return None
    if len(candidates) > 1:
        return {"ambiguous": True, "matches": len(candidates)}

    cand = candidates[0]
    lines = content.splitlines(keepends=True)
    start_line = cand["line"]
    start_idx = start_line - 1

    end_idx = len(lines)
    for j in range(start_idx + 1, len(lines)):
        m2 = re.match(r"^(#{1,6})\s+(.+)$", lines[j])
        if m2 and len(m2.group(1)) <= cand["level"]:
            end_idx = j
            break

    section_text = "".join(lines[start_idx:end_idx])
    body = "".join(lines[start_idx + 1:end_idx])

    return {
        "line": start_line,
        "end_line": end_idx,
        "level": cand["level"],
        "heading": cand["heading"],
        "section_text": section_text,
        "body": body,
    }


def normalize_section_body(body: str) -> str:
    body = body.lstrip("\n")
    body = "\n" + body
    body = body.rstrip("\n") + "\n\n"
    body = re.sub(r"\n{4,}", "\n\n\n", body)
    return body


def replace_section_body(content: str, heading: str, new_body: str) -> str | dict[str, Any]:
    section = find_section(content, heading)
    if section is None:
        return {"error_code": "SECTION_NOT_FOUND", "message": f"未找到 heading：{heading}"}
    if section.get("ambiguous"):
        return {
            "error_code": "SECTION_AMBIGUOUS",
            "message": f"heading「{heading}」匹配到 {section['matches']} 处，不唯一。",
        }

    body = normalize_section_body(new_body)

    lines = content.splitlines(keepends=True)
    heading_line = lines[section["line"] - 1]
    body_start = section["line"]
    body_end = section["end_line"]

    new_lines = lines[:body_start - 1]
    new_lines.append(heading_line)
    new_lines.append(body)
    new_lines.extend(lines[body_end:])
    result = "".join(new_lines)
    result = re.sub(r"\n{5,}", "\n\n\n", result)
    return result


def append_section(
    content: str,
    section_heading: str,
    section_content: str,
    after_heading: str | None = None,
) -> str | dict[str, Any]:
    existing = find_section(content, section_heading)
    if existing is not None and not existing.get("ambiguous"):
        return {"error_code": "SECTION_ALREADY_EXISTS", "message": f"section「{section_heading}」已存在。"}

    body_normalized = normalize_section_body(section_content)
    new_section = f"## {section_heading}" + body_normalized

    if after_heading:
        after_section = find_section(content, after_heading)
        if after_section is None:
            return {"error_code": "AFTER_HEADING_NOT_FOUND", "message": f"未找到 after_heading：{after_heading}"}
        lines = content.splitlines(keepends=True)
        insert_at = after_section["end_line"]
        spacing_before = "\n" if insert_at > 0 and not lines[insert_at - 1].isspace() else ""
        new_lines = lines[:insert_at] + [spacing_before + new_section + "\n"] + lines[insert_at:]
        result = "".join(new_lines)
        result = re.sub(r"\n{5,}", "\n\n\n", result)
        return result

    result = content.rstrip("\n") + "\n\n" + new_section + "\n"
    result = re.sub(r"\n{5,}", "\n\n\n", result)
    return result
