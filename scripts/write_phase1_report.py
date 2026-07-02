import argparse
import csv
from collections import Counter
from pathlib import Path

from workflow_safety import atomic_write_text, require_write_permission


def read_rows(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def year(row: dict) -> str:
    if (row.get("year") or "").strip():
        return row["year"].strip()
    for key in ("first_submitted", "latest_version_date"):
        value = row.get(key, "")
        if len(value) >= 4 and value[:4].isdigit():
            return value[:4]
    arxiv_id = row.get("arxiv_id", "")
    if len(arxiv_id) >= 2 and arxiv_id[:2].isdigit():
        yy = int(arxiv_id[:2])
        return str(2000 + yy if yy < 90 else 1900 + yy)
    return "unknown"


def count_table(title: str, counts: Counter) -> str:
    lines = [f"## {title}", "", "| Item | Count |", "|---|---:|"]
    for key, value in counts.most_common():
        lines.append(f"| {key or '<missing>'} | {value} |")
    return "\n".join(lines) + "\n"


def priority_rank(row: dict) -> int:
    order = {"core": 0, "high": 1, "medium": 2, "low": 3}
    return order.get((row.get("reading_priority") or "medium").strip().lower(), 2)


def paper_label(row: dict) -> str:
    title = row.get("title") or row.get("canonical_title") or "<missing title>"
    paper_id = row.get("paper_id") or row.get("arxiv_id") or "<missing id>"
    category = row.get("method_category") or "<missing category>"
    priority = row.get("reading_priority") or "medium"
    return f"- **{title}** ({paper_id}) [{priority}; {category}]"


def main() -> None:
    parser = argparse.ArgumentParser(description="Write a first-pass Phase 1 report from an inventory CSV.")
    parser.add_argument("--inventory", default="phase1_inventory.csv")
    parser.add_argument("--output", default="phase1_report.md")
    parser.add_argument("--title", default="Phase 1 Literature Inventory Report")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--metadata-unverified",
        action="store_true",
        help="Mark the report as local no-metadata Phase 1 output.",
    )
    parser.add_argument("--allow-write", action="store_true")
    args = parser.parse_args()
    require_write_permission(args, "Phase 1 report output")

    output = Path(args.output)
    if output.exists() and not args.overwrite:
        raise FileExistsError(f"{output} exists; pass --overwrite to replace it")

    rows = read_rows(Path(args.inventory))
    section_counts = Counter(row.get("section", "") for row in rows)
    category_counts = Counter(row.get("method_category", "") for row in rows)
    app_counts = Counter(row.get("application_tag", "") for row in rows)
    batch_counts = Counter(row.get("reading_batch", "") for row in rows)
    year_counts = Counter(year(row) for row in rows)
    priority_counts = Counter(row.get("reading_priority", "") or "<missing>" for row in rows)
    confidence_counts = Counter(row.get("classification_confidence", "") or "<missing>" for row in rows)
    core_candidates = sorted(
        [row for row in rows if (row.get("reading_priority") or "").lower() in {"core", "high"}],
        key=priority_rank,
    )
    low_confidence = [
        row
        for row in rows
        if (row.get("classification_confidence") or "").lower() in {"low", "needs_review"}
        or "classification needs review" in (row.get("notes") or "")
    ]

    lines = [
        f"# {args.title}",
        "",
        "## Scope And Source",
        "",
        "- This is a first-pass report generated from the inventory.",
        "- Treat taxonomy and batch labels as provisional until papers are read.",
        *(
            [
                "- Metadata status: unverified local extraction.",
                "- No arXiv metadata API was called.",
                "- Titles, authors, and submission dates may be missing until metadata fetch is explicitly allowed.",
            ]
            if args.metadata_unverified
            else []
        ),
        "",
        "## Summary",
        "",
        f"- Total papers: {len(rows)}",
        f"- Unique paper IDs: {len(set((row.get('paper_id') or row.get('arxiv_id') or '') for row in rows if (row.get('paper_id') or row.get('arxiv_id'))))}",
        "",
        count_table("Source Sections", section_counts),
        count_table("Method Categories", category_counts),
        count_table("Application Tags", app_counts),
        count_table("Reading Priorities", priority_counts),
        count_table("Classification Confidence", confidence_counts),
        count_table("Years", year_counts),
        count_table("Reading Batches", batch_counts),
        "## Recommended Core Papers",
        "",
        "\n".join(paper_label(row) for row in core_candidates[:30])
        if core_candidates
        else "To be filled after inspecting titles, abstracts, source ranking, or user priorities.",
        "",
        "## Low-Confidence Classifications",
        "",
        "\n".join(paper_label(row) for row in low_confidence[:50])
        if low_confidence
        else "- No low-confidence classifications flagged by the rule-based pass.",
        "",
        "## Metadata Gaps And Verification Needs",
        "",
    ]

    gaps = []
    for row in rows:
        missing = [key for key in ("authors", "method_category", "reading_batch") if not row.get(key)]
        if not (row.get("title") or row.get("canonical_title")):
            missing.append("title/canonical_title")
        if missing:
            gaps.append(f"- {row.get('paper_id') or row.get('arxiv_id') or '<missing id>'}: missing {', '.join(missing)}")
    lines.extend(gaps or ["- No obvious required metadata gaps detected."])
    lines.append("")

    atomic_write_text(output, "\n".join(lines))
    print({"output": str(output), "rows": len(rows)})


if __name__ == "__main__":
    main()
