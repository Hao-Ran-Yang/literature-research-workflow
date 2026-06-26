import argparse
import csv
import re
from collections import Counter
from pathlib import Path

from workflow_safety import atomic_write_csv, require_write_permission


CORE_HINTS = re.compile(r"\b(survey|review|benchmark|overview|foundation|foundational|primer|tutorial)\b", re.IGNORECASE)
PRIORITY_ORDER = {"core": 0, "high": 1, "medium": 2, "low": 3}


def read_rows(path: Path) -> tuple[list[str], list[dict]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def write_rows(path: Path, fields: list[str], rows: list[dict]) -> None:
    atomic_write_csv(path, fields, rows)


def year(row: dict) -> str:
    for key in ("first_submitted", "latest_version_date"):
        value = row.get(key, "")
        if len(value) >= 4 and value[:4].isdigit():
            return value[:4]
    arxiv_id = row.get("arxiv_id", "")
    if re.match(r"\d{4}\.", arxiv_id):
        yy = int(arxiv_id[:2])
        return str(2000 + yy if yy < 90 else 1900 + yy)
    return "9999"


def infer_category(row: dict) -> str:
    for key in ("method_category", "section", "application_tag"):
        value = (row.get(key) or "").strip()
        if value:
            return value
    return "Uncategorized"


def batch_label(index: int, category: str) -> str:
    compact = re.sub(r"\s+", " ", category).strip()
    return f"B{index:02d} {compact[:60]}" if compact else f"B{index:02d}"


def batch_number(row: dict) -> int:
    match = re.match(r"B(\d+)", row.get("reading_batch", ""))
    return int(match.group(1)) if match else 9999


def priority_rank(row: dict) -> int:
    return PRIORITY_ORDER.get((row.get("reading_priority") or "medium").strip().lower(), 2)


def is_core_candidate(row: dict) -> bool:
    priority = (row.get("reading_priority") or "").strip().lower()
    if priority in {"core", "high"}:
        return True
    return bool(CORE_HINTS.search(" ".join([row.get("title", ""), row.get("notes", "")])))


def assign_batches(rows: list[dict], min_size: int, max_size: int) -> list[dict]:
    for row in rows:
        if not row.get("method_category"):
            row["method_category"] = (row.get("section") or "Uncategorized").strip()

    core = [row for row in rows if is_core_candidate(row)]
    core.sort(key=lambda row: (priority_rank(row), row.get("section", ""), infer_category(row), year(row), row.get("arxiv_id", "")))
    non_core = [row for row in rows if row not in core]
    batches: list[tuple[str, list[dict]]] = []
    if core:
        batches.append(("Core and survey papers", core[:max_size]))
        non_core = core[max_size:] + non_core

    non_core.sort(key=lambda row: (priority_rank(row), row.get("section", ""), infer_category(row), year(row), row.get("arxiv_id", "")))
    current: list[dict] = []
    current_category = ""
    for row in non_core:
        category = infer_category(row)
        if not current:
            current = [row]
            current_category = category
            continue
        should_split = len(current) >= max_size or (category != current_category and len(current) >= min_size)
        if should_split:
            batches.append((current_category, current))
            current = [row]
            current_category = category
        else:
            current.append(row)
    if current:
        if batches and len(current) < min_size and len(batches[-1][1]) + len(current) <= max_size:
            batches[-1][1].extend(current)
        else:
            batches.append((current_category, current))

    for idx, (category, batch_rows) in enumerate(batches, start=1):
        label = batch_label(idx, category)
        for row in batch_rows:
            row["reading_batch"] = label
    rows.sort(key=lambda row: (batch_number(row), priority_rank(row), row.get("section", ""), infer_category(row), year(row), row.get("arxiv_id", "")))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Assign first-pass Bxx reading batches.")
    parser.add_argument("--inventory", default="phase1_inventory.csv")
    parser.add_argument("--output", default="")
    parser.add_argument("--min-size", type=int, default=10)
    parser.add_argument("--max-size", type=int, default=35)
    parser.add_argument("--overwrite", action="store_true", help="Allow replacing the input file.")
    parser.add_argument("--allow-write", action="store_true")
    args = parser.parse_args()
    require_write_permission(args, "reading batch plan output")

    inventory = Path(args.inventory)
    fields, rows = read_rows(inventory)
    if "reading_batch" not in fields:
        fields.append("reading_batch")
    if "method_category" not in fields:
        fields.append("method_category")
    if "reading_priority" not in fields:
        fields.append("reading_priority")

    rows = assign_batches(rows, args.min_size, args.max_size)
    output = Path(args.output) if args.output else inventory
    if output == inventory and not args.overwrite:
        raise FileExistsError("Refusing to overwrite input inventory; pass --overwrite or --output")
    write_rows(output, fields, rows)

    counts = Counter(row.get("reading_batch", "") for row in rows)
    print({"output": str(output), "rows": len(rows), "batches": dict(counts)})


if __name__ == "__main__":
    main()
