import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path


REQUIRED = ["arxiv_id", "title", "abs_url", "pdf_url", "method_category", "reading_batch"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a Phase 1 literature inventory.")
    parser.add_argument("--inventory", default="phase1_inventory.csv")
    parser.add_argument("--require", nargs="*", default=REQUIRED)
    args = parser.parse_args()

    path = Path(args.inventory)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    missing = defaultdict(list)
    for idx, row in enumerate(rows, start=2):
        for field in args.require:
            if not (row.get(field) or "").strip():
                missing[field].append(idx)

    id_counts = Counter((row.get("arxiv_id") or "").strip() for row in rows if (row.get("arxiv_id") or "").strip())
    duplicates = {key: count for key, count in id_counts.items() if count > 1}
    batch_counts = Counter((row.get("reading_batch") or "").strip() or "<missing>" for row in rows)
    category_counts = Counter((row.get("method_category") or "").strip() or "<missing>" for row in rows)

    output = {
        "inventory": str(path),
        "rows": len(rows),
        "duplicate_arxiv_ids": duplicates,
        "missing_required": dict(missing),
        "batch_counts": dict(batch_counts),
        "category_counts": dict(category_counts),
        "ok": not duplicates and not missing,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
