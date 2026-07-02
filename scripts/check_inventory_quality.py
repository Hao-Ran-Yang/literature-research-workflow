import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path


REQUIRED = ["paper_id", "method_category", "reading_batch"]
ANY_OF_REQUIRED = [("title", "canonical_title")]


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
        for group in ANY_OF_REQUIRED:
            if not any((row.get(field) or "").strip() for field in group):
                missing["/".join(group)].append(idx)

    paper_id_counts = Counter((row.get("paper_id") or "").strip() for row in rows if (row.get("paper_id") or "").strip())
    duplicates = {key: count for key, count in paper_id_counts.items() if count > 1}
    arxiv_id_counts = Counter((row.get("arxiv_id") or "").strip() for row in rows if (row.get("arxiv_id") or "").strip())
    duplicate_arxiv_ids = {key: count for key, count in arxiv_id_counts.items() if count > 1}
    batch_counts = Counter((row.get("reading_batch") or "").strip() or "<missing>" for row in rows)
    category_counts = Counter((row.get("method_category") or "").strip() or "<missing>" for row in rows)

    output = {
        "inventory": str(path),
        "rows": len(rows),
        "duplicate_paper_ids": duplicates,
        "duplicate_arxiv_ids": duplicate_arxiv_ids,
        "missing_required": dict(missing),
        "batch_counts": dict(batch_counts),
        "category_counts": dict(category_counts),
        "ok": not duplicates and not missing,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
