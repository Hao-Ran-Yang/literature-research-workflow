import argparse
import csv
import json
import re
import tempfile
from collections import defaultdict
from pathlib import Path

from note_quality_rules import format_missing_fields
from workflow_safety import require_write_permission


ENTRY_RE = re.compile(r"^####\s+(.+)$", re.MULTILINE)
BATCH_HEADING_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)
V2_ENTRY_RE = re.compile(r"^###\s+(.+)$", re.MULTILINE)
ARXIV_RE = re.compile(r"(?:arXiv[:\s]*)?(\d{4}\.\d{4,5}(?:v\d+)?)", re.IGNORECASE)
CANDIDATE_FIELDS = [
    "paper_id",
    "title",
    "main_problem",
    "motivation",
    "core_method",
    "key_changed_step",
    "evidence_uncertainty",
    "technical_route",
    "read_priority",
    "read_reason",
    "first_sections_to_read",
    "possible_gpt_question",
    "deep_note_candidate",
    "deep_note_reason",
    "arxiv_id",
    "reading_batch",
    "recommendation",
    "recommendation_reason",
    "evidence_strength",
    "selected_for_phase3",
    "selection_notes",
]
CANONICAL_ENTRY_RE = re.compile(r"^###\s+(\S+)\s+-\s+(.+)$", re.MULTILINE)


def normalized_arxiv_id(value: str) -> str:
    return re.sub(r"v\d+$", "", value or "", flags=re.IGNORECASE)


def normalized_paper_id(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    match = ARXIV_RE.search(value)
    if match:
        return f"arxiv:{normalized_arxiv_id(match.group(1))}"
    return value


def paper_id_from_arxiv(arxiv_id: str) -> str:
    arxiv_id = normalized_arxiv_id(arxiv_id)
    return f"arxiv:{arxiv_id}" if arxiv_id else ""


def batch_code(value: str) -> str:
    match = re.search(r"\b(B\d{2,})\b", value or "")
    return match.group(1) if match else ""


def field(body: str, label: str) -> str:
    match = re.search(rf"^\s*-\s*{re.escape(label)}\s*:\s*(.+?)\s*$", body, re.IGNORECASE | re.MULTILINE)
    if match:
        return match.group(1).strip()
    bold_match = re.search(rf"^\s*\*\*{re.escape(label)}\.\*\*\s*(.+?)\s*$", body, re.IGNORECASE | re.MULTILINE)
    return bold_match.group(1).strip() if bold_match else ""


def first_sentence(value: str) -> str:
    value = re.sub(r"\s+", " ", value or "").strip()
    match = re.match(r"(.+?)(?:\s+Evidence:\s+|$)", value, flags=re.IGNORECASE)
    return (match.group(1) if match else value).strip()


def per_paper_area(body: str) -> str:
    match = re.search(r"(?im)^##\s+(?:\d+\.\s*)?Per-paper skim notes\s*$", body)
    if not match:
        return body
    rest = body[match.end() :]
    end = re.search(r"(?m)^##\s+", rest)
    return rest[: end.start()] if end else rest


def section_body(entry_body: str, heading: str) -> str:
    pattern = re.compile(rf"(?ims)^####\s+\d+\.\s+{re.escape(heading)}\s*$")
    match = pattern.search(entry_body)
    if not match:
        return ""
    rest = entry_body[match.end() :]
    next_heading = re.search(r"(?m)^####\s+\d+\.\s+", rest)
    return rest[: next_heading.start()].strip() if next_heading else rest.strip()


def bullet_value(body: str, label: str) -> str:
    match = re.search(rf"(?im)^\s*-\s*(?:\[[^\]]+\]\s*)?{re.escape(label)}\s*:\s*(.+)$", body)
    return match.group(1).strip() if match else ""


def evidence_pointers(body: str) -> str:
    pointers = re.findall(r"(?im)Evidence:\s*(.+)$", body)
    return "; ".join(pointer.strip() for pointer in pointers)


def changed_step_from_diagram(body: str) -> str:
    match = re.search(r"<!--\s*method-comparison:start\s*-->(.*?)<!--\s*method-comparison:end\s*-->", body, flags=re.I | re.S)
    diagram = match.group(1) if match else body
    line = re.search(r"(?im)^This paper\s*:\s*(.+)$", diagram)
    if not line:
        return bullet_value(body, "Key mechanism / changed step")
    text = line.group(1).strip()
    key = re.search(r"KEY CHANGED STEP[^->\n]*", text)
    return key.group(0).strip() if key else text


def recommendation_value(body: str) -> str:
    value = field(body, "Deep-read recommendation")
    match = re.search(r"\b(yes|maybe|no)\b", value or "", flags=re.IGNORECASE)
    return match.group(1).lower() if match else value.lower()


def recommendation_reason(body: str) -> str:
    value = field(body, "Deep-read recommendation")
    match = re.search(r"\bReason:\s*(.+)$", value or "", flags=re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return field(body, "Reason")


def aspect_value(body: str, aspect: str, column: int) -> str:
    match = re.search(rf"^\s*\|\s*{re.escape(aspect)}\s*\|(.+?)\|\s*$", body, re.IGNORECASE | re.MULTILINE)
    if not match:
        return ""
    cells = [cell.strip() for cell in match.group(1).split("|")]
    return cells[column].strip() if len(cells) > column else ""


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


def split_v2_batch_note(markdown: str) -> list[dict]:
    fm, body = parse_frontmatter(markdown)
    if fm.get("artifact_type") != "batch_skim_note":
        return []
    batch = str(fm.get("batch", ""))
    area = per_paper_area(body)
    frontmatter_ids = set(fm.get("paper_ids", [])) if isinstance(fm.get("paper_ids"), list) else set()
    entries = list(CANONICAL_ENTRY_RE.finditer(area))
    papers = []
    for entry_index, entry in enumerate(entries):
        entry_end = entries[entry_index + 1].start() if entry_index + 1 < len(entries) else len(area)
        entry_body = area[entry.start() : entry_end]
        paper_id = normalized_paper_id(entry.group(1))
        if frontmatter_ids and paper_id not in frontmatter_ids:
            continue
        arxiv_match = ARXIV_RE.search(paper_id) or ARXIV_RE.search(entry_body)
        arxiv_id = normalized_arxiv_id(arxiv_match.group(1) if arxiv_match else "")
        title = entry.group(2).strip()
        problem_section = section_body(entry_body, "Problem and difficulty")
        motivation_section = section_body(entry_body, "Motivation / Method Rationale")
        method_section = section_body(entry_body, "Core method")
        diagram_section = section_body(entry_body, "Method comparison diagram")
        uncertainty_section = section_body(entry_body, "Evidence and uncertainty")
        main_problem = bullet_value(problem_section, "Problem") or field(entry_body, "Problem") or field(entry_body, "Research problem")
        motivation = bullet_value(motivation_section, "Motivation") or field(entry_body, "Motivation / Method Rationale")
        core_method = bullet_value(method_section, "One-sentence method") or field(entry_body, "One-sentence method") or field(entry_body, "Method details")
        key_changed_step = bullet_value(method_section, "Key mechanism / changed step") or changed_step_from_diagram(diagram_section)
        evidence_uncertainty = bullet_value(uncertainty_section, "Main uncertainty from packet-only reading") or field(entry_body, "Main uncertainty")
        papers.append(
            {
                "arxiv_id": arxiv_id,
                "paper_id": paper_id,
                "title": title or paper_id_from_arxiv(arxiv_id),
                "reading_batch": batch,
                "technical_route": field(entry_body, "Technical route") or field(entry_body, "Basic information"),
                "main_problem": first_sentence(main_problem),
                "motivation": first_sentence(motivation),
                "core_method": first_sentence(core_method),
                "key_changed_step": first_sentence(key_changed_step),
                "evidence_uncertainty": first_sentence(evidence_uncertainty),
                "evidence_pointers": evidence_pointers(entry_body),
                "problem": first_sentence(main_problem),
                "method": first_sentence(core_method),
                "essential_change": first_sentence(key_changed_step) or field(entry_body, "Essential change") or aspect_value(entry_body, "Changed component", 1),
                "recurring_weakness": field(entry_body, "Recurring weakness") or field(entry_body, "Weaknesses / assumptions") or aspect_value(entry_body, "Remaining weakness", 1),
                "evidence_strength": field(entry_body, "Evidence strength"),
                "recommendation": recommendation_value(entry_body),
                "recommendation_reason": recommendation_reason(entry_body),
                "main_uncertainty": first_sentence(evidence_uncertainty),
                "diagram_verification": field(entry_body, "Diagram verification"),
                "needs_review": "",
            }
        )
    return papers


def split_notes(markdown: str) -> list[dict]:
    v2_papers = split_v2_batch_note(markdown)
    if v2_papers:
        return v2_papers
    headings = list(BATCH_HEADING_RE.finditer(markdown))
    papers = []
    for heading_index, heading in enumerate(headings):
        section_end = headings[heading_index + 1].start() if heading_index + 1 < len(headings) else len(markdown)
        section = markdown[heading.end() : section_end]
        entries = list(ENTRY_RE.finditer(section))
        for entry_index, entry in enumerate(entries):
            entry_end = entries[entry_index + 1].start() if entry_index + 1 < len(entries) else len(section)
            body = section[entry.start() : entry_end]
            arxiv_match = ARXIV_RE.search(body)
            papers.append(
                {
                    "arxiv_id": normalized_arxiv_id(arxiv_match.group(1) if arxiv_match else ""),
                    "paper_id": paper_id_from_arxiv(arxiv_match.group(1) if arxiv_match else ""),
                    "title": re.sub(r"^\d+\.\s*", "", entry.group(1)).strip(),
                    "reading_batch": batch_code(heading.group(1)),
                    "technical_route": field(body, "Technical route"),
                    "main_problem": field(body, "Problem"),
                    "motivation": field(body, "Motivation") or field(body, "Motivation / Method Rationale"),
                    "core_method": field(body, "One-sentence method"),
                    "key_changed_step": field(body, "Essential change") or aspect_value(body, "Changed component", 1),
                    "evidence_uncertainty": field(body, "Main uncertainty"),
                    "evidence_pointers": evidence_pointers(body),
                    "problem": field(body, "Problem"),
                    "method": field(body, "One-sentence method"),
                    "essential_change": field(body, "Essential change") or aspect_value(body, "Changed component", 1),
                    "recurring_weakness": field(body, "Recurring weakness") or aspect_value(body, "Remaining weakness", 1),
                    "evidence_strength": field(body, "Evidence strength"),
                    "recommendation": field(body, "Deep-read recommendation").lower(),
                    "recommendation_reason": field(body, "Reason"),
                    "main_uncertainty": field(body, "Main uncertainty"),
                    "diagram_verification": field(body, "Diagram verification"),
                    "needs_review": format_missing_fields(body),
                }
            )
    return papers


def read_existing_candidates(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = {}
        for row in csv.DictReader(handle):
            key = normalized_paper_id(row.get("paper_id", "")) or paper_id_from_arxiv(row.get("arxiv_id", ""))
            if key:
                rows[key] = row
        return rows


def reusable_existing_value(value: str) -> str:
    value = value or ""
    if re.search(r"\?{3,}", value):
        return ""
    non_space = sum(1 for char in value if not char.isspace())
    question_marks = value.count("?")
    if non_space >= 80 and question_marks >= 8 and question_marks / non_space > 0.05:
        return ""
    return value


def atomic_write(path: Path, text: str, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding=encoding, newline="", delete=False, dir=path.parent, prefix=path.name + ".", suffix=".tmp") as handle:
        handle.write(text)
        temp_path = Path(handle.name)
    temp_path.replace(path)


def write_candidates(path: Path, papers: list[dict]) -> list[dict]:
    previous = read_existing_candidates(path)
    candidates = []
    for paper in papers:
        if paper["needs_review"]:
            continue
        old = previous.get(paper["paper_id"], {})
        row = {key: paper.get(key, "") for key in CANDIDATE_FIELDS}
        row["read_priority"] = old.get("read_priority") or ("" if paper.get("main_problem") else {
            "yes": "high",
            "maybe": "medium",
            "no": "low",
        }.get(paper["recommendation"], ""))
        row["read_reason"] = reusable_existing_value(old.get("read_reason", "")) or ("" if paper.get("main_problem") else paper.get("recommendation_reason", ""))
        row["first_sections_to_read"] = reusable_existing_value(old.get("first_sections_to_read", "")) or "Introduction; Method; Conclusion/Limitations if present in packet."
        row["possible_gpt_question"] = reusable_existing_value(old.get("possible_gpt_question", "")) or (
            f"What problem, motivation, core method, changed step, and packet-only uncertainty should I keep in mind for {paper['title']}?"
            if paper.get("title")
            else ""
        )
        row["deep_note_candidate"] = reusable_existing_value(old.get("deep_note_candidate", "")) or ("" if paper.get("main_problem") else paper.get("recommendation", ""))
        row["deep_note_reason"] = reusable_existing_value(old.get("deep_note_reason", "")) or ("" if paper.get("main_problem") else paper.get("recommendation_reason", ""))
        row["selected_for_phase3"] = old.get("selected_for_phase3", "")
        row["selection_notes"] = old.get("selection_notes", "")
        candidates.append(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8-sig", newline="", delete=False, dir=path.parent, prefix=path.name + ".", suffix=".tmp") as handle:
        writer = csv.DictWriter(handle, fieldnames=CANDIDATE_FIELDS)
        writer.writeheader()
        writer.writerows(candidates)
        temp_path = Path(handle.name)
    temp_path.replace(path)
    return candidates


def shorten(value: str, limit: int = 240) -> str:
    value = re.sub(r"\s+", " ", str(value)).strip()
    return value if len(value) <= limit else value[: limit - 3].rstrip() + "..."


def md_table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return "- To be filled."
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(shorten(item).replace("|", "/") for item in row) + " |")
    return "\n".join(lines)


def write_overview(path: Path, papers: list[dict], candidates: list[dict]) -> None:
    routes = defaultdict(lambda: {"papers": [], "ideas": [], "changes": [], "weaknesses": [], "uncertainties": []})
    for paper in papers:
        route = paper["technical_route"] or "<unclassified>"
        routes[route]["papers"].append(paper["title"])
        if paper["method"] and paper["method"] not in routes[route]["ideas"]:
            routes[route]["ideas"].append(paper["method"])
        if paper["essential_change"] and paper["essential_change"] not in routes[route]["changes"]:
            routes[route]["changes"].append(paper["essential_change"])
        if paper["recurring_weakness"] and paper["recurring_weakness"] not in routes[route]["weaknesses"]:
            routes[route]["weaknesses"].append(paper["recurring_weakness"])
        if paper["main_uncertainty"] and paper["main_uncertainty"] not in routes[route]["uncertainties"]:
            routes[route]["uncertainties"].append(paper["main_uncertainty"])

    route_rows = [
        [route, len(data["papers"]), "; ".join(data["papers"]), "; ".join(data["ideas"]), "; ".join(data["changes"]), "; ".join(data["weaknesses"]), "; ".join(data["uncertainties"])]
        for route, data in sorted(routes.items())
    ]
    candidate_rows = [
        [row["reading_batch"], row["title"], row["paper_id"] or row["arxiv_id"], row["main_problem"], row["key_changed_step"], row["evidence_uncertainty"]]
        for row in candidates
    ]
    skip_rows = [
        [paper["reading_batch"], paper["title"], paper["arxiv_id"], paper["recommendation_reason"]]
        for paper in papers
        if paper["recommendation"] == "no"
    ]
    diagram_review_rows = [
        [paper["reading_batch"], paper["title"], paper["arxiv_id"], paper["diagram_verification"] or "missing"]
        for paper in papers
        if paper.get("diagram_verification") and paper["diagram_verification"].lower() != "verified"
    ]
    complete = sum(1 for paper in papers if not paper["needs_review"])
    needs_review = len(papers) - complete
    atomic_write(
        path,
        "\n".join(
            [
                "# Phase 2 Field Skim Overview",
                "",
                "> Evidence level: skim. Treat route-level conclusions as provisional until selected Phase 3 deep reading is complete.",
                f"> Quality summary: complete={complete}, needs_review={needs_review}. Candidate CSV is a reading-priority navigation table for complete notes.",
                "> The Technical Routes table is the default route-level taxonomy matrix. Add a route map only when it improves clarity.",
                "",
                "## Technical Routes",
                "",
                md_table(["Route", "Paper count", "Representative papers", "Core ideas", "Essential changes", "Recurring weaknesses", "Main uncertainties"], route_rows),
                "",
                "## Reading-Priority Candidates",
                "",
                md_table(["Batch", "Paper", "Paper ID", "Main problem", "Key changed step", "Evidence uncertainty"], candidate_rows),
                "",
                "## Low-Priority Or Skippable Papers",
                "",
                md_table(["Batch", "Paper", "arXiv", "Reason"], skip_rows),
                "",
                "## Method Diagrams Needing Review",
                "",
                md_table(["Batch", "Paper", "arXiv", "Diagram verification"], diagram_review_rows),
                "",
            ]
        ),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a cumulative skim overview and merge a reading-priority candidate table.")
    parser.add_argument("--notes", default="phase2_skim_notes.md")
    parser.add_argument("--output", default="phase2_skim_overview.md")
    parser.add_argument("--candidates", default="phase2_deep_reading_candidates.csv")
    parser.add_argument("--allow-write", action="store_true")
    args = parser.parse_args()
    require_write_permission(args, "skim overview and candidate output")

    notes_path = Path(args.notes)
    markdown = notes_path.read_text(encoding="utf-8", errors="replace") if notes_path.exists() else ""
    papers = split_notes(markdown)
    candidates = write_candidates(Path(args.candidates), papers)
    write_overview(Path(args.output), papers, candidates)
    print(json.dumps({"overview": args.output, "candidates": args.candidates, "skim_entries": len(papers), "candidate_entries": len(candidates)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
