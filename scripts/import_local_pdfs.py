import argparse
import json
import re
import shutil
from pathlib import Path

from workflow_safety import atomic_write_json, require_write_permission


ARXIV_ID_RE = re.compile(r"(?P<id>(?:\d{4}\.\d{4,5})(?:v(?P<version>\d+))?)", re.IGNORECASE)


def pdf_version(pdf_url: str) -> str | None:
    match = re.search(r"(\d{4}\.\d{4,5})v(\d+)", pdf_url or "", re.IGNORECASE)
    return f"v{match.group(2)}" if match else None


def validate_pdf(path: Path, min_bytes: int) -> tuple[bool, str, int]:
    if not path.exists():
        return False, "missing", 0
    size = path.stat().st_size
    if size < min_bytes:
        return False, f"too_small:{size}", size
    with path.open("rb") as handle:
        header = handle.read(5)
    if header != b"%PDF-":
        return False, "not_pdf_header", size
    return True, "ok", size


def load_manifest(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def default_status_path(manifest_path: Path) -> Path:
    return manifest_path.with_name(manifest_path.name.replace("_manifest.json", "_import_status.json"))


def iter_pdfs(sources: list[Path], recursive: bool) -> list[Path]:
    files: list[Path] = []
    for source in sources:
        if not source.exists():
            continue
        if source.is_file() and source.suffix.lower() == ".pdf":
            files.append(source)
            continue
        pattern = "**/*.pdf" if recursive else "*.pdf"
        files.extend(path for path in source.glob(pattern) if path.is_file())
    return files


def index_candidates(files: list[Path], min_bytes: int) -> dict[str, list[dict]]:
    by_id: dict[str, list[dict]] = {}
    for file_path in files:
        match = ARXIV_ID_RE.search(file_path.name)
        if not match:
            continue
        raw_id = match.group("id")
        base_id = raw_id.split("v", 1)[0]
        version_match = re.search(r"v(\d+)$", raw_id, re.IGNORECASE)
        version = f"v{version_match.group(1)}" if version_match else None
        valid, reason, size = validate_pdf(file_path, min_bytes)
        by_id.setdefault(base_id, []).append(
            {
                "path": str(file_path),
                "name": file_path.name,
                "version": version,
                "valid": valid,
                "reason": reason,
                "bytes": size,
                "mtime": file_path.stat().st_mtime,
            }
        )
    return by_id


def choose_candidate(candidates: list[dict], desired_version: str | None) -> tuple[dict | None, bool]:
    valid = [item for item in candidates if item["valid"]]
    if not valid:
        return None, len(candidates) > 1
    scored = []
    for item in valid:
        version_score = 1 if desired_version and item["version"] == desired_version else 0
        unversioned_score = 1 if not item["version"] else 0
        scored.append((version_score, unversioned_score, item["bytes"], item["mtime"], item))
    scored.sort(reverse=True, key=lambda row: row[:4])
    return scored[0][4], len(valid) > 1


def import_row(row: dict, candidates_by_id: dict[str, list[dict]], args: argparse.Namespace) -> dict:
    arxiv_id = row["arxiv_id"]
    target = Path(row["pdf_path"])
    target_valid, target_reason, target_size = validate_pdf(target, args.min_bytes)
    if target_valid:
        return {
            "arxiv_id": arxiv_id,
            "status": "already_valid",
            "source_path": None,
            "target_path": str(target),
            "bytes": target_size,
            "validated": True,
            "multiple_candidates": False,
            "error": None,
        }

    candidates = candidates_by_id.get(arxiv_id, [])
    desired_version = pdf_version(row.get("pdf_url", ""))
    candidate, multiple = choose_candidate(candidates, desired_version)
    if candidate is None:
        invalid_count = len([item for item in candidates if not item["valid"]])
        return {
            "arxiv_id": arxiv_id,
            "status": "invalid_candidate" if invalid_count else "missing",
            "source_path": None,
            "target_path": str(target),
            "bytes": target_size,
            "validated": False,
            "multiple_candidates": multiple,
            "error": "; ".join(f"{item['name']}:{item['reason']}" for item in candidates) or target_reason,
        }

    if args.dry_run or not args.copy:
        return {
            "arxiv_id": arxiv_id,
            "status": "would_import",
            "source_path": candidate["path"],
            "target_path": str(target),
            "bytes": candidate["bytes"],
            "validated": True,
            "multiple_candidates": multiple,
            "error": None,
        }

    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(candidate["path"], target)
    final_valid, final_reason, final_size = validate_pdf(target, args.min_bytes)
    return {
        "arxiv_id": arxiv_id,
        "status": "imported" if final_valid else "import_failed",
        "source_path": candidate["path"],
        "target_path": str(target),
        "bytes": final_size,
        "validated": final_valid,
        "multiple_candidates": multiple,
        "error": None if final_valid else final_reason,
    }


def summarize(results: list[dict], batch: str, status_path: Path) -> dict:
    counts: dict[str, int] = {}
    for item in results:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    return {
        "batch": batch,
        "expected": len(results),
        "already_valid": counts.get("already_valid", 0),
        "imported": counts.get("imported", 0),
        "would_import": counts.get("would_import", 0),
        "missing": counts.get("missing", 0),
        "invalid_candidates": counts.get("invalid_candidate", 0),
        "import_failed": counts.get("import_failed", 0),
        "multiple_candidates": sum(1 for item in results if item.get("multiple_candidates")),
        "status_path": str(status_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--source", action="append", default=["raw_papers"])
    parser.add_argument("--copy", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--recursive", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--min-bytes", type=int, default=20000)
    parser.add_argument("--status-path")
    parser.add_argument("--allow-write", action="store_true")
    args = parser.parse_args()
    require_write_permission(args, "PDF import status or copy output")

    manifest_path = Path(args.manifest)
    rows = load_manifest(manifest_path)
    sources = [Path(source) for source in args.source]
    files = iter_pdfs(sources, args.recursive)
    candidates_by_id = index_candidates(files, args.min_bytes)
    results = [import_row(row, candidates_by_id, args) for row in rows]

    status_path = Path(args.status_path) if args.status_path else default_status_path(manifest_path)
    atomic_write_json(status_path, results)
    batch = manifest_path.name.replace("_manifest.json", "")
    print(json.dumps(summarize(results, batch, status_path), ensure_ascii=False))


if __name__ == "__main__":
    main()
