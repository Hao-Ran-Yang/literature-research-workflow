import argparse
import json
import re
from pathlib import Path

from note_quality_rules import detect_note_format, format_missing_fields


HEADING_RE = re.compile(r"^#{1,6}\s+", re.MULTILINE)
ENTRY_RE = re.compile(r"^#{3,6}\s+(.+)$", re.MULTILINE)
NUMBER_RE = re.compile(r"\d")
EVIDENCE_RE = re.compile(
    r"(Table\s*\d+|Figure\s*\d+|Fig\.?\s*\d+|Section\s*\d+(?:\.\d+)*|Sec\.?\s*\d+(?:\.\d+)*|"
    r"表\s*\d+|图\s*\d+|第\s*\d+(?:\.\d+)*\s*节)",
    re.IGNORECASE,
)
BASIC_RE = re.compile(r"(Basic information|基本信息)", re.IGNORECASE)
INTRO_RE = re.compile(r"(Brief intro|Summary|Research problem|Problem|简介|简要介绍|摘要|研究问题)", re.IGNORECASE)
LIMIT_RE = re.compile(r"(Limitations?|Weaknesses?|Assumptions?|局限|不足|假设)", re.IGNORECASE)
ARXIV_RE = re.compile(r"arXiv|\d{4}\.\d{4,5}(?:v\d+)?", re.IGNORECASE)
ARXIV_ID_RE = re.compile(r"(?i)(?:arxiv:)?(\d{4}\.\d{4,5})(?:v\d+)?")
CANONICAL_BLOCK_HEADINGS = [
    "Problem and difficulty",
    "Motivation / Method Rationale",
    "Core method",
    "Method comparison diagram",
    "Evidence and uncertainty",
]
METHOD_COMPARISON_ROLES = ["Direct baseline", "Representative prior", "This paper", "KEY CHANGED STEP"]


def normalize_paper_id(value: str) -> str:
    match = ARXIV_ID_RE.search(value or "")
    return f"arxiv:{match.group(1)}" if match else (value or "").strip().lower()


def parse_frontmatter(markdown: str) -> tuple[dict, str]:
    if not markdown.startswith("---\n"):
        return {}, markdown
    end = markdown.find("\n---", 4)
    if end < 0:
        return {}, markdown
    data: dict[str, object] = {}
    current = ""
    for line in markdown[4:end].splitlines():
        if line.startswith("  - ") and current:
            data.setdefault(current, [])
            if isinstance(data[current], list):
                data[current].append(line[4:].strip())
            continue
        if ":" in line:
            key, value = line.split(":", 1)
            current = key.strip()
            data[current] = value.strip()
    return data, markdown[end + 4 :]


def per_paper_area(body: str) -> str:
    match = re.search(r"(?im)^##\s+(?:\d+\.\s*)?Per-paper skim notes\s*$", body)
    if not match:
        return body
    rest = body[match.end() :]
    end = re.search(r"(?m)^##\s+", rest)
    return rest[: end.start()] if end else rest


def split_canonical_batch_entries(markdown: str) -> list[tuple[str, str, str]]:
    _fm, body = parse_frontmatter(markdown)
    area = per_paper_area(body)
    heading_matches = []
    for match in re.finditer(r"(?m)^###\s+(.+)$", area):
        heading = match.group(1).strip()
        if " - " not in heading:
            continue
        paper_id, title = heading.split(" - ", 1)
        if paper_id.strip() and title.strip():
            heading_matches.append((match, paper_id.strip(), title.strip()))
    entries = []
    for idx, (match, paper_id, title) in enumerate(heading_matches):
        end = heading_matches[idx + 1][0].start() if idx + 1 < len(heading_matches) else len(area)
        entries.append((f"{paper_id} - {title}", paper_id, area[match.start():end].strip()))
    return entries


def canonical_entry_missing(paper_id: str, body: str) -> list[str]:
    missing = []
    for heading in CANONICAL_BLOCK_HEADINGS:
        if not re.search(rf"(?im)^####\s+\d+\.\s+{re.escape(heading)}\s*$", body):
            missing.append(f"{heading} block")
    diagram_match = re.search(
        r"<!--\s*method-comparison:start\s*-->.*?<!--\s*method-comparison:end\s*-->",
        body,
        flags=re.I | re.S,
    )
    if not diagram_match:
        missing.append("method-comparison marker")
        diagram = body
    else:
        diagram = diagram_match.group(0)
    for role in METHOD_COMPARISON_ROLES:
        if role not in diagram:
            missing.append(f"{role} in method-comparison diagram")
    if not re.search(rf"(?im)Evidence:\s*.*paper_id={re.escape(paper_id)}\b", body):
        missing.append("evidence pointer")
    return missing


def review_canonical_batch_skim_note(markdown: str, batch_heading: str, expected: int) -> dict:
    entries = split_canonical_batch_entries(markdown)
    reviews = []
    for title, paper_id, body in entries:
        reviews.append(
            {
                "entry": title,
                "format": "batch_skim_note",
                "paper_ids": [paper_id],
                "missing": canonical_entry_missing(paper_id, body),
            }
        )
    needs_review = [item for item in reviews if item["missing"]]
    return {
        "batch_heading": batch_heading,
        "batch_entries": len(entries),
        "expected": expected,
        "count_ok": len(entries) == expected,
        "expected_ids": [],
        "missing_expected_ids": [],
        "unexpected_ids": [],
        "ids_ok": True,
        "passed": len(entries) - len(needs_review),
        "needs_review": needs_review,
    }


def section_text(markdown: str, heading: str) -> str:
    match = re.search(rf"^#{{1,6}}\s+{re.escape(heading)}\s*$", markdown, re.MULTILINE)
    if not match:
        raise ValueError(f"batch heading not found: {heading}")

    start = match.start()
    heading_level = len(match.group(0)) - len(match.group(0).lstrip("#"))
    next_heading = re.search(rf"^#{{1,{heading_level}}}\s+", markdown[match.end():], re.MULTILINE)
    if next_heading:
        end = match.end() + next_heading.start()
        return markdown[start:end]
    return markdown[start:]


def split_entries(section: str) -> list[tuple[str, str]]:
    all_matches = list(ENTRY_RE.finditer(section))
    arxiv_title_matches = [match for match in all_matches if ARXIV_ID_RE.search(match.group(1))]
    level4_matches = [
        match
        for match in all_matches
        if len(match.group(0)) - len(match.group(0).lstrip("#")) >= 4
    ]
    matches = arxiv_title_matches or level4_matches or all_matches
    section_headings = list(HEADING_RE.finditer(section))
    parent_level = 2
    if matches:
        first_entry_level = len(matches[0].group(0)) - len(matches[0].group(0).lstrip("#"))
        parent_candidates = [
            len(heading.group(0)) - len(heading.group(0).lstrip("#"))
            for heading in section_headings
            if heading.start() < matches[0].start()
            and len(heading.group(0)) - len(heading.group(0).lstrip("#")) < first_entry_level
        ]
        if parent_candidates:
            parent_level = max(parent_candidates)
    entries = []
    for idx, match in enumerate(matches):
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(section)
        for heading in section_headings:
            if heading.start() <= match.start():
                continue
            level = len(heading.group(0)) - len(heading.group(0).lstrip("#"))
            if level <= parent_level:
                end = min(end, heading.start())
                break
        entries.append((match.group(1).strip(), section[start:end]))
    return entries


def review_entry(title: str, body: str) -> dict:
    note_format = detect_note_format(body)
    missing = []
    if not ARXIV_RE.search(body):
        missing.append("arxiv_version")
    if note_format != "phase3-deep-v2":
        missing.append("current note type phase3-deep-v2")
    missing.extend(format_missing_fields(body, strict_diagrams=True))
    ids = sorted({normalize_paper_id(match.group(0)) for match in ARXIV_ID_RE.finditer(title + "\n" + body)})
    return {"entry": title, "format": note_format, "paper_ids": ids, "missing": missing}


def review_markdown(markdown: str, batch_heading: str, expected: int, expected_ids_text: str = "") -> dict:
    fm, _body = parse_frontmatter(markdown)
    if fm.get("artifact_type") == "batch_skim_note":
        return review_canonical_batch_skim_note(markdown, batch_heading, expected)
    section = section_text(markdown, batch_heading)
    entries = split_entries(section)
    reviews = [review_entry(title, body) for title, body in entries]
    needs_review = [item for item in reviews if item["missing"]]
    expected_ids = {normalize_paper_id(item) for item in expected_ids_text.split(",") if item.strip()}
    found_ids = {paper_id for item in reviews for paper_id in item.get("paper_ids", [])}
    missing_ids = sorted(expected_ids - found_ids)
    unexpected_ids = sorted(found_ids - expected_ids) if expected_ids else []
    return {
        "batch_heading": batch_heading,
        "batch_entries": len(entries),
        "expected": expected,
        "count_ok": len(entries) == expected,
        "expected_ids": sorted(expected_ids),
        "missing_expected_ids": missing_ids,
        "unexpected_ids": unexpected_ids,
        "ids_ok": not expected_ids or (not missing_ids and not unexpected_ids),
        "passed": len(entries) - len(needs_review),
        "needs_review": needs_review,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--notes", required=True)
    parser.add_argument("--batch-heading", required=True)
    parser.add_argument("--expected", required=True, type=int)
    parser.add_argument("--expected-ids", default="", help="Comma-separated paper IDs that must appear in reviewed entries.")
    args = parser.parse_args()

    markdown = Path(args.notes).read_text(encoding="utf-8", errors="replace")
    output = review_markdown(markdown, args.batch_heading, args.expected, args.expected_ids)
    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
