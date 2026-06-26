import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path

from workflow_safety import atomic_write_text, require_write_permission


TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates" / "notes"


def batch_code(value: str) -> str:
    match = re.search(r"\b(B\d{2})\b", value or "")
    return match.group(1) if match else value


def load_rows_from_manifest(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_rows_from_inventory(path: Path, batch: str) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if batch_code(row.get("reading_batch", "")) == batch:
                rows.append(row)
    return rows


def normalized_arxiv_id(value: str) -> str:
    value = re.sub(r"^arxiv[:\s]*", "", value or "", flags=re.IGNORECASE)
    return re.sub(r"v\d+$", "", value, flags=re.IGNORECASE)


def normalized_paper_id(row_or_value) -> str:
    if isinstance(row_or_value, dict):
        value = row_or_value.get("paper_id") or row_or_value.get("arxiv_id") or ""
    else:
        value = str(row_or_value or "")
    value = value.strip()
    if not value:
        return ""
    bare = normalized_arxiv_id(value)
    if re.match(r"^\d{4}\.\d{4,5}$", bare):
        return f"arxiv:{bare}"
    return value


def bare_arxiv_id(row_or_value) -> str:
    return normalized_arxiv_id(normalized_paper_id(row_or_value))


def selected_ids(path: Path) -> set[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return {
            normalized_paper_id(row)
            for row in csv.DictReader(handle)
            if (row.get("selected_for_phase3") or "").strip().lower() == "yes"
        }


def template_stub_for(row: dict, index: int, template_name: str) -> str:
    template_files = {
        "phase3-deep": "phase3_deep_note.md",
    }
    template = (TEMPLATE_DIR / template_files[template_name]).read_text(encoding="utf-8")
    values = defaultdict(
        str,
        {
            **row,
            "index": index,
            "title": row.get("title") or row.get("canonical_title") or normalized_paper_id(row) or f"Paper {index}",
            "paper_id": normalized_paper_id(row),
            "arxiv_id": row.get("arxiv_id") or bare_arxiv_id(row),
            "version": row.get("latest_version_date", ""),
            "method_category": row.get("method_category", ""),
            "reading_batch": batch_code(row.get("reading_batch", "")),
            "pdf_path": row.get("deep_text_path") or row.get("pdf_path", ""),
        },
    )
    return template.format_map(values) + "\n"


def markdown_for(rows: list[dict], batch: str, heading: str | None, template: str) -> str:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[batch_code(row.get("reading_batch", "")) or "Selected"].append(row)
    sections = []
    for code, items in sorted(grouped.items()):
        selected_heading = heading or f"{code} Phase 3 Selected Deep Reading"
        stubs = "".join(template_stub_for(row, idx, template) for idx, row in enumerate(items, start=1))
        sections.append("## " + selected_heading + "\n\n" + stubs)
    return "\n".join(sections)


def main() -> None:
    parser = argparse.ArgumentParser(description="Write structured note stubs for a Bxx batch.")
    parser.add_argument("--manifest", help="Batch manifest JSON.")
    parser.add_argument("--inventory", default="phase1_inventory.csv")
    parser.add_argument("--batch", help="Batch code such as B03. Required when --manifest is omitted.")
    parser.add_argument("--output", help="Output Markdown file.")
    parser.add_argument("--append-to", help="Append stubs to an existing notes Markdown file.")
    parser.add_argument("--heading", help="Markdown heading for the batch.")
    parser.add_argument(
        "--template",
        choices=["phase3-deep"],
        default="phase3-deep",
        help="Stub format for current promoted Phase 3 deep notes.",
    )
    parser.add_argument("--candidates", help="Optional candidate CSV. Phase 3 uses rows selected with selected_for_phase3=yes.")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--allow-write", action="store_true")
    args = parser.parse_args()
    require_write_permission(args, "note stub output")

    if args.manifest:
        manifest_path = Path(args.manifest)
        rows = load_rows_from_manifest(manifest_path)
        batch = args.batch or manifest_path.name.replace("_manifest.json", "")
    else:
        if not args.batch:
            raise ValueError("--batch is required when --manifest is omitted")
        batch = args.batch
        rows = load_rows_from_inventory(Path(args.inventory), batch)

    if args.candidates:
        keep = selected_ids(Path(args.candidates))
        rows = [row for row in rows if normalized_paper_id(row) in keep]
    if args.template == "phase3-deep":
        rows = [
            row
            for row in rows
            if row.get("status") in {"exists", "extracted"}
            and row.get("deep_text_path")
            and Path(row["deep_text_path"]).exists()
            and Path(row["deep_text_path"]).stat().st_size > 1000
        ]

    heading = args.heading or ""
    markdown = markdown_for(rows, batch, heading or None, args.template)

    if args.append_to:
        target = Path(args.append_to)
        if target.exists():
            existing = target.read_text(encoding="utf-8", errors="replace")
            if heading and f"## {heading}" in existing and not args.overwrite:
                raise FileExistsError(f"Heading already exists in {target}; pass --overwrite to append anyway")
            atomic_write_text(target, existing.rstrip() + "\n\n" + markdown)
        else:
            atomic_write_text(target, markdown)
        output = target
    else:
        output = Path(args.output or f"{batch}_note_stubs.md")
        if output.exists() and not args.overwrite:
            raise FileExistsError(f"{output} exists; pass --overwrite to replace it")
        atomic_write_text(output, markdown)

    print(json.dumps({"output": str(output), "batch": batch, "stubs": len(rows)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
