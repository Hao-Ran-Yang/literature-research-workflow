import argparse
import csv
import json
import re
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from parse_reading_notes import parse_notes  # noqa: E402
from workflow_safety import require_write_permission  # noqa: E402


def resolve_inventory(root: Path, requested: str) -> Path:
    requested_path = Path(requested)
    path = requested_path if requested_path.is_absolute() else root / requested_path
    if path.exists():
        return path
    candidates = sorted(root.glob("phase1*_inventory.csv"))
    if len(candidates) == 1:
        return candidates[0]
    if candidates:
        preferred = [item for item in candidates if item.name == "phase1_inventory.csv"]
        if preferred:
            return preferred[0]
    raise FileNotFoundError(f"inventory not found: {path}")


def read_inventory(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def batch_code(value: str) -> str:
    match = re.search(r"\b(B\d{2})\b", value or "")
    return match.group(1) if match else ""


def index_notes(parsed: dict) -> dict[str, dict]:
    by_id = {}
    for paper in parsed["papers"]:
        if paper.get("arxiv_id"):
            by_id[paper["arxiv_id"].split("v", 1)[0]] = paper
    return by_id


def resolved_note_path(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def resolve_synthesis_inputs(root: Path, skim_notes: str, deep_notes: str, candidates: str) -> dict:
    registry_path = root / "batches" / "accepted_artifacts.json"
    if registry_path.exists():
        registry = read_json_if_exists(registry_path)
        if isinstance(registry, dict) and isinstance(registry.get("artifacts"), list):
            resolved = {"layout": "template-v2", "skim_notes": [], "deep_notes": [], "candidate_tables": [], "overviews": []}
            for item in registry["artifacts"]:
                if not isinstance(item, dict):
                    continue
                status = item.get("status") or item.get("quality_status", "accepted")
                if status not in {"accepted", "active"}:
                    continue
                artifact_type = item.get("artifact_type") or item.get("type")
                rel = item.get("path", "")
                if not rel:
                    continue
                path = resolved_note_path(root, rel)
                if not path.exists():
                    continue
                if artifact_type == "batch_skim_note":
                    resolved["skim_notes"].append(path)
                elif artifact_type == "phase3_deep_note":
                    resolved["deep_notes"].append(path)
                elif artifact_type in {"candidate_table", "phase3_candidates"}:
                    resolved["candidate_tables"].append(path)
                elif artifact_type in {"overview", "skim_overview", "batch_skim_overview"}:
                    resolved["overviews"].append(path)
            for key in ("skim_notes", "deep_notes", "candidate_tables", "overviews"):
                resolved[key] = sorted(set(resolved[key]), key=lambda path: path.as_posix())
            return resolved
    return {
        "layout": "legacy",
        "skim_notes": [resolved_note_path(root, skim_notes)],
        "deep_notes": [resolved_note_path(root, deep_notes)],
        "candidate_tables": [resolved_note_path(root, candidates)],
        "overviews": [],
    }


def merge_parsed_notes(note_inputs: list[tuple[str, Path]]) -> tuple[dict, dict[str, int]]:
    merged: dict[str, dict] = {}
    anonymous = []
    source_counts = {}
    for level, path in note_inputs:
        parsed = parse_notes(path)
        source_counts[level] = source_counts.get(level, 0) + parsed["summary"]["paper_entries"]
        for paper in parsed["papers"]:
            item = dict(paper)
            item["synthesis_evidence_level"] = level
            key = (paper.get("arxiv_id") or "").split("v", 1)[0]
            if key:
                merged[key] = item
            else:
                anonymous.append(item)
    papers = [*merged.values(), *anonymous]
    return {
        "notes": [str(path) for _level, path in note_inputs],
        "papers": papers,
        "summary": {
            "paper_entries": len(papers),
            "needs_review": sum(1 for paper in papers if paper["quality_flags"]["needs_review"]),
        },
    }, source_counts


def md_table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return "- To be filled.\n"
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        cleaned = [str(item).replace("\n", " ").replace("|", "/").strip() for item in row]
        lines.append("| " + " | ".join(cleaned) + " |")
    return "\n".join(lines) + "\n"


def short(text: str, limit: int = 180) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def write(path: Path, text: str, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(f"{path} exists; pass --overwrite to replace it")
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=path.parent, prefix=path.name + ".", suffix=".tmp") as handle:
        handle.write(text)
        temp_path = Path(handle.name)
    temp_path.replace(path)


def read_csv_if_exists(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def read_json_if_exists(path: Path):
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def normalized_arxiv_id(value: str) -> str:
    return re.sub(r"v\d+$", "", value or "", flags=re.IGNORECASE)


def accepted_deep_failure_rows(root: Path, deep_manifest: list[dict]) -> list[list[str]]:
    data = read_json_if_exists(root / "accepted_failures.json")
    if not isinstance(data, dict) or not isinstance(data.get("phase3_deep_text"), list):
        return []
    manifest_by_id = {
        normalized_arxiv_id(str(row.get("arxiv_id", ""))): row
        for row in deep_manifest
        if row.get("arxiv_id")
    }
    rows = []
    for item in data["phase3_deep_text"]:
        arxiv_id = normalized_arxiv_id(str(item))
        if not arxiv_id or any(row[0] == arxiv_id for row in rows):
            continue
        manifest_row = manifest_by_id.get(arxiv_id, {})
        reason = manifest_row.get("error") or manifest_row.get("status") or "accepted deep-text failure"
        rows.append([arxiv_id, reason, "accepted_failures.json"])
    return rows


def collect_field(parsed: dict, field: str, limit: int = 40) -> list[list[str]]:
    rows = []
    for paper in parsed["papers"]:
        value = paper["fields"].get(field, "")
        if value:
            rows.append([paper.get("batch", ""), paper.get("entry_title", ""), paper.get("arxiv_id", ""), short(value)])
    return rows[:limit]


def collect_top_level_field(parsed: dict, field: str, limit: int = 40) -> list[list[str]]:
    rows = []
    for paper in parsed["papers"]:
        value = paper.get(field, "")
        if value:
            rows.append([paper.get("batch", ""), paper.get("entry_title", ""), paper.get("arxiv_id", ""), short(value)])
    return rows[:limit]


def collect_limitations_and_assumptions(parsed: dict, limit: int = 40) -> list[list[str]]:
    rows = []
    for paper in parsed["papers"]:
        value = paper["fields"].get("limitations", "")
        if not value:
            value = "; ".join(item for item in [paper.get("limitations_summary", ""), paper.get("assumptions", "")] if item)
        if value:
            rows.append([paper.get("batch", ""), paper.get("entry_title", ""), paper.get("arxiv_id", ""), short(value)])
    return rows[:limit]


def collect_prior_method_comparisons(parsed: dict, limit: int = 80) -> list[list[str]]:
    rows = []
    for paper in parsed["papers"]:
        for comparison in paper.get("prior_method_comparisons", []):
            rows.append(
                [
                    paper.get("batch", ""),
                    paper.get("entry_title", ""),
                    comparison.get("existing_approach", ""),
                    comparison.get("what_it_achieves", ""),
                    comparison.get("limitation", ""),
                ]
            )
    return rows[:limit]


def aggregate_prior_method_families(parsed: dict, limit: int = 40) -> list[list[str]]:
    families = defaultdict(lambda: {"papers": [], "achievements": [], "limitations": []})
    for paper in parsed["papers"]:
        for comparison in paper.get("prior_method_comparisons", []):
            approach = comparison.get("existing_approach", "").strip()
            if not approach:
                continue
            family = families[approach]
            paper_title = paper.get("entry_title", "")
            if paper_title and paper_title not in family["papers"]:
                family["papers"].append(paper_title)
            achievement = comparison.get("what_it_achieves", "").strip()
            if achievement and achievement not in family["achievements"]:
                family["achievements"].append(achievement)
            limitation = comparison.get("limitation", "").strip()
            if limitation and limitation not in family["limitations"]:
                family["limitations"].append(limitation)
    rows = []
    for approach, family in families.items():
        rows.append(
            [
                approach,
                len(family["papers"]),
                "; ".join(family["papers"]),
                "; ".join(family["achievements"]),
                "; ".join(family["limitations"]),
            ]
        )
    return sorted(rows, key=lambda row: (-row[1], row[0]))[:limit]


def collect_selected_deep_judgments(parsed: dict, limit: int = 40) -> list[list[str]]:
    rows = []
    for paper in parsed["papers"]:
        if paper.get("synthesis_evidence_level") != "selected-deep":
            continue
        rows.append(
            [
                paper.get("entry_title", ""),
                paper.get("arxiv_id", ""),
                short(paper.get("research_question", "")),
                short(paper.get("core_contribution", "") or paper.get("core_idea_summary", "")),
                short(paper.get("main_caution", "")),
                short(paper.get("what_is_solid", "")),
                short(paper.get("best_follow_up", "") or paper.get("follow_up_experiment", "")),
                short(paper.get("final_reading_decision", "") or paper.get("reading_decision", "")),
            ]
        )
    return rows[:limit]


def collect_selected_deep_method_comparisons(parsed: dict, limit: int = 120) -> list[list[str]]:
    rows = []
    for paper in parsed["papers"]:
        if paper.get("synthesis_evidence_level") != "selected-deep":
            continue
        for comparison in paper.get("deep_method_comparison", []):
            rows.append(
                [
                    paper.get("entry_title", ""),
                    paper.get("arxiv_id", ""),
                    comparison.get("aspect", ""),
                    comparison.get("direct_baseline", ""),
                    comparison.get("representative_prior", ""),
                    comparison.get("this_paper", ""),
                ]
            )
    return rows[:limit]


def main() -> None:
    parser = argparse.ArgumentParser(description="Create final synthesis draft files from inventory and parsed notes.")
    parser.add_argument("--inventory", default="phase1_inventory.csv")
    parser.add_argument("--notes", default="", help="Legacy alias for --legacy-notes.")
    parser.add_argument("--skim-notes", default="phase2_skim_notes.md")
    parser.add_argument("--deep-notes", default="phase3_deep_notes.md")
    parser.add_argument("--legacy-notes", default="phase2_reading_notes.md")
    parser.add_argument("--output-dir", default=".")
    parser.add_argument("--parsed-output", default="phase2_reading_notes.parsed.json")
    parser.add_argument("--candidates", default="phase2_deep_reading_candidates.csv")
    parser.add_argument("--phase2-root", default="phase2_papers")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--allow-write", action="store_true")
    args = parser.parse_args()
    require_write_permission(args, "final synthesis output")

    out = Path(args.output_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    inventory_path = resolve_inventory(out, args.inventory)
    rows = read_inventory(inventory_path)
    synthesis_inputs = resolve_synthesis_inputs(out, args.skim_notes, args.deep_notes, args.candidates)
    note_inputs = []
    if synthesis_inputs["layout"] == "legacy":
        note_inputs.append(("legacy-deep", resolved_note_path(out, args.notes or args.legacy_notes)))
    note_inputs.extend(("skim", path) for path in synthesis_inputs["skim_notes"])
    note_inputs.extend(("selected-deep", path) for path in synthesis_inputs["deep_notes"])
    parsed, source_counts = merge_parsed_notes(note_inputs)
    note_by_id = index_notes(parsed)
    parsed_path = out / args.parsed_output
    parsed["synthesis_inputs"] = {
        key: ([str(path) for path in value] if isinstance(value, list) else value)
        for key, value in synthesis_inputs.items()
    }
    write(parsed_path, json.dumps(parsed, ensure_ascii=False, indent=2) + "\n", True)
    candidates = []
    for candidate_path in synthesis_inputs["candidate_tables"]:
        candidates.extend(read_csv_if_exists(candidate_path))
    undecided_candidates = [
        row for row in candidates if (row.get("selected_for_phase3") or "").strip().lower() not in {"yes", "no"}
    ]
    deep_manifest = read_json_if_exists(out / args.phase2_root / "phase3_deep_text_manifest.json")
    accepted_deep_failures = accepted_deep_failure_rows(out, deep_manifest)
    accepted_deep_failure_ids = {row[0] for row in accepted_deep_failures}
    deep_failures = [
        row
        for row in deep_manifest
        if row.get("status") not in {"exists", "extracted"}
        and normalized_arxiv_id(str(row.get("arxiv_id", ""))) not in accepted_deep_failure_ids
    ]

    category_counts = Counter(row.get("method_category", "") or "<missing>" for row in rows)
    batch_counts = Counter(batch_code(row.get("reading_batch", "")) or "<missing>" for row in rows)
    priority_counts = Counter(row.get("reading_priority", "") or "<missing>" for row in rows)

    matrix_rows = []
    for row in rows:
        arxiv_id = (row.get("arxiv_id") or "").split("v", 1)[0]
        note = note_by_id.get(arxiv_id, {})
        matrix_rows.append(
            [
                row.get("method_category", "") or "<missing>",
                row.get("reading_batch", ""),
                row.get("reading_priority", "") or "medium",
                row.get("title", "") or note.get("entry_title", ""),
                arxiv_id,
                "yes" if note else "no",
                ", ".join(note.get("missing_fields", [])) if note else "not read",
            ]
        )

    review_rows = [
        [paper.get("batch", ""), paper.get("entry_title", ""), paper.get("arxiv_id", ""), ", ".join(paper.get("missing_fields", []))]
        for paper in parsed["papers"]
        if paper["quality_flags"]["needs_review"]
    ]
    diagram_review_rows = [
        [paper.get("batch", ""), paper.get("entry_title", ""), paper.get("arxiv_id", ""), paper.get("diagram_verification", "") or "missing"]
        for paper in parsed["papers"]
        if paper.get("diagram_verification", "").lower() not in {"", "verified"}
    ]

    write(
        out / "final_literature_map.md",
        "\n".join(
            [
                "# Final Literature Map",
                "",
                "## Coverage",
                "",
                f"- Inventory file: `{inventory_path.name}`",
                f"- Inventory papers: {len(rows)}",
                f"- Reading-note entries parsed: {parsed['summary']['paper_entries']}",
                f"- Note entries needing review: {parsed['summary']['needs_review']}",
                f"- Evidence levels: legacy-deep={source_counts['legacy-deep']}, skim={source_counts['skim']}, selected-deep={source_counts['selected-deep']}",
                "- Synthesis policy: selected deep notes override skim notes for the same arXiv ID; skim-level conclusions remain provisional.",
                "",
                "## Method Families",
                "",
                "\n".join(f"- {key}: {value}" for key, value in category_counts.most_common()) or "- To be filled.",
                "",
                "## Problem Landscape",
                "",
                md_table(["Batch", "Paper", "arXiv", "Problem statement"], collect_top_level_field(parsed, "problem_statement")),
                "",
                "## Mathematical Formulations",
                "",
                md_table(["Batch", "Paper", "arXiv", "Mathematical view"], collect_top_level_field(parsed, "mathematical_view")),
                "",
                "## Existing Method Families",
                "",
                md_table(
                    ["Approach", "Paper count", "Papers", "Recurring achievements", "Recurring limitations"],
                    aggregate_prior_method_families(parsed),
                ),
                "",
                "## Method Comparison Matrix",
                "",
                md_table(["Batch", "Paper", "Approach", "What it achieves", "Limitation"], collect_prior_method_comparisons(parsed)),
                "",
                "## Selected Deep Research Judgments",
                "",
                md_table(
                    ["Paper", "arXiv", "Research question", "Core contribution", "Main caution", "What is solid", "Best follow-up", "Final decision"],
                    collect_selected_deep_judgments(parsed),
                ),
                "",
                "## Selected Deep Method Comparisons",
                "",
                md_table(
                    ["Paper", "arXiv", "Aspect", "Direct baseline", "Representative prior", "This paper"],
                    collect_selected_deep_method_comparisons(parsed),
                ),
                "",
                "## Recurring Motivations",
                "",
                md_table(["Batch", "Paper", "arXiv", "Motivation"], collect_top_level_field(parsed, "motivation")),
                "",
                "## Remaining Unresolved Problems",
                "",
                md_table(["Batch", "Paper", "arXiv", "Unresolved aspect"], collect_top_level_field(parsed, "remaining_unresolved_aspects")),
                "",
                "## Research Opportunities",
                "",
                md_table(["Batch", "Paper", "arXiv", "Possible extension"], collect_field(parsed, "possible_extensions")),
                "",
                "## Method-Paper Matrix",
                "",
                md_table(
                    ["Method", "Batch", "Priority", "Paper", "arXiv", "Read", "Missing note fields"],
                    matrix_rows,
                ),
                "",
                "## Timeline And Technical Shifts",
                "",
                "To be written from the parsed notes and paper order. Keep paper-stated facts separate from interpretation.",
                "",
                "## Cross-Paper Tensions",
                "",
                "To be written after comparing problem formulations, objectives, optimization views, experiments, and limitations.",
                "",
            ]
        ),
        args.overwrite,
    )

    key_rows = [
        [
            row.get("reading_priority", "") or "medium",
            row.get("reading_batch", ""),
            row.get("method_category", "") or "<missing>",
            row.get("title", ""),
            row.get("arxiv_id", ""),
        ]
        for row in rows
        if (row.get("reading_priority") or "").lower() in {"core", "high"}
    ]
    write(
        out / "key_papers.md",
        "\n".join(
            [
                "# Key Papers",
                "",
                "## Must-Read Candidates",
                "",
                md_table(["Priority", "Batch", "Method", "Paper", "arXiv"], key_rows),
                "",
                "## Batch Coverage",
                "",
                "\n".join(f"- {key}: {value}" for key, value in batch_counts.items()) or "- To be filled.",
                "",
                "## Priority Distribution",
                "",
                "\n".join(f"- {key}: {value}" for key, value in priority_counts.most_common()) or "- To be filled.",
                "",
            ]
        ),
        args.overwrite,
    )

    write(
        out / "research_opportunities.md",
        "\n".join(
            [
                "# Research Opportunities",
                "",
                "## Paper-Stated Limitations And Assumptions",
                "",
                md_table(["Batch", "Paper", "arXiv", "Limitation/assumption"], collect_limitations_and_assumptions(parsed)),
                "",
                "## Possible Extensions Mentioned In Notes",
                "",
                md_table(["Batch", "Paper", "arXiv", "Possible extension"], collect_field(parsed, "possible_extensions")),
                "",
                "## Inferred Research Ideas",
                "",
                "To be written by comparing recurring limitations, missing evaluations, and the user's research lens.",
                "",
                "## Verification Steps",
                "",
                "- Recheck claims against the original PDF sections/tables/figures before treating them as paper-stated facts.",
                "",
            ]
        ),
        args.overwrite,
    )

    write(
        out / "open_questions.md",
        "\n".join(
            [
                "# Open Questions",
                "",
                "## Notes Needing Review",
                "",
                md_table(["Batch", "Paper", "arXiv", "Missing fields"], review_rows),
                "",
                "## Metadata",
                "",
                "- Check entries with missing title, method category, priority, venue, or version metadata.",
                "",
                "## Claims To Verify",
                "",
                "- Verify major empirical claims and numerical comparisons against PDF tables/figures/sections.",
                "",
                "## Papers Needing Deeper Reading",
                "",
                "- Add papers whose body text is incomplete, appendix-dependent, or only skimmed.",
                "",
                "## Phase 3 Candidate Review",
                "",
                md_table(
                    ["Paper", "arXiv", "Recommendation", "Selection status"],
                    [
                        [row.get("title", ""), row.get("arxiv_id", ""), row.get("recommendation", ""), row.get("selected_for_phase3", "") or "undecided"]
                        for row in undecided_candidates
                    ],
                ),
                "",
                "## Phase 3 Extraction Failures",
                "",
                md_table(
                    ["arXiv", "Status", "Error"],
                    [[row.get("arxiv_id", ""), row.get("status", ""), row.get("error", "")] for row in deep_failures],
                ),
                "",
                *(
                    [
                        "## Accepted deep-reading failures / warnings",
                        "",
                        "The following selected deep-reading papers had accepted extraction or deep-text failures. They were allowed to proceed, but they should not be treated as completed deep notes.",
                        "",
                        md_table(["Paper ID", "Reason", "Source"], accepted_deep_failures),
                        "",
                    ]
                    if accepted_deep_failures
                    else []
                ),
                "## Method Diagrams Needing Review",
                "",
                md_table(["Batch", "Paper", "arXiv", "Diagram verification"], diagram_review_rows),
                "",
            ]
        ),
        args.overwrite,
    )

    print(json.dumps({"output_dir": str(out), "inventory_rows": len(rows), "note_entries": parsed["summary"]["paper_entries"], "parsed_output": str(parsed_path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
