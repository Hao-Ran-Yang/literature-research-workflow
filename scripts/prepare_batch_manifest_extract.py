import argparse
import csv
import json
import re
from pathlib import Path

from workflow_safety import atomic_write_json, atomic_write_text, require_write_permission

STOP_HEADING = re.compile(
    r"(?im)^\s*(?:\d+\.?\s*)?(references|bibliography|appendix|appendices)\s*$"
)


def safe_name(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9 -]", "", value)
    return value.replace(" ", "_")


def target_path(root: Path, row: dict) -> Path:
    section = re.sub(r"[^A-Za-z0-9-]", "_", row["section"])
    method = safe_name(row["method_category"])
    return root / section / method / f"{row['arxiv_id']}.pdf"


def load_rows(inventory: Path, root: Path, batch: str) -> list[dict]:
    rows = []
    with inventory.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if row["reading_batch"].startswith(batch + " "):
                row["pdf_path"] = str(target_path(root, row))
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
    paper_id = normalized_paper_id(row_or_value)
    return normalized_arxiv_id(paper_id)


def load_selected_candidate_rows(candidates: Path) -> dict[str, dict]:
    selected = {}
    with candidates.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if (row.get("selected_for_phase3") or "").strip().lower() != "yes":
                continue
            paper_id = normalized_paper_id(row)
            if paper_id:
                selected[paper_id] = row
    return selected


def phase2_project_root(phase2_root: Path) -> Path:
    return phase2_root.parent if phase2_root.name == "phase2_papers" else phase2_root


def selected_rows_from_v2_manifests(root: Path, selected: dict[str, dict]) -> list[dict]:
    rows = []
    seen = set()
    project_root = phase2_project_root(root)
    for manifest_path in sorted(root.glob("B*_manifest.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        batch = manifest_path.name.replace("_manifest.json", "")
        papers = []
        if isinstance(manifest, dict):
            batch = manifest.get("batch") or batch
            papers = manifest.get("papers", [])
        elif isinstance(manifest, list):
            papers = manifest
        if not isinstance(papers, list):
            papers = []
        for paper in papers:
            if not isinstance(paper, dict):
                continue
            paper_id = normalized_paper_id(paper)
            if paper_id not in selected or paper_id in seen:
                continue
            candidate = selected[paper_id]
            rel_pdf = paper.get("local_pdf_path") or paper.get("managed_pdf_path") or paper.get("pdf_path") or ""
            pdf_path = Path(rel_pdf)
            if rel_pdf and not pdf_path.is_absolute():
                pdf_path = project_root / rel_pdf
            row = {
                **paper,
                **candidate,
                "paper_id": paper_id,
                "arxiv_id": bare_arxiv_id(paper_id),
                "title": candidate.get("title") or paper.get("canonical_title") or paper.get("title") or paper_id,
                "reading_batch": candidate.get("batch") or batch,
                "pdf_path": str(pdf_path),
            }
            rows.append(row)
            seen.add(paper_id)
    return rows


def load_selected_rows(inventory: Path, root: Path, candidates: Path) -> list[dict]:
    selected = load_selected_candidate_rows(candidates)
    rows = selected_rows_from_v2_manifests(root, selected)
    if rows:
        return rows
    selected_ids = set(selected)
    project_root = inventory.parent.parent if inventory.parent.name == "inventory" else Path(".")
    rows = []
    with inventory.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            paper_id = normalized_paper_id(row)
            if paper_id in selected_ids:
                rel_pdf = row.get("local_pdf_path") or ""
                if rel_pdf:
                    pdf_path = Path(rel_pdf)
                    if not pdf_path.is_absolute():
                        pdf_path = project_root / rel_pdf
                    row["pdf_path"] = str(pdf_path)
                else:
                    row["pdf_path"] = str(target_path(root, row))
                row["paper_id"] = paper_id
                row["arxiv_id"] = bare_arxiv_id(paper_id)
                row["title"] = selected[paper_id].get("title") or row.get("canonical_title") or row.get("title") or paper_id
                rows.append(row)
    return rows


def extract_body(pdf_path: Path) -> dict:
    try:
        from pypdf import PdfReader
    except (ImportError, ModuleNotFoundError) as exc:
        raise RuntimeError(
            "pypdf is required only for --mode extract.\n"
            "Install it with: pip install pypdf\n"
            "Manifest mode and --help do not require pypdf."
        ) from exc

    reader = PdfReader(str(pdf_path))
    body_parts = []
    cutoff = None
    for page_no, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        stop = STOP_HEADING.search(text)
        if stop:
            text = text[: stop.start()]
            cutoff = {"page": page_no, "heading": stop.group(1)}
        text = text.encode("utf-8", errors="replace").decode("utf-8")
        if text.strip():
            body_parts.append(f"\n<<< PDF PAGE {page_no} >>>\n{text.strip()}\n")
        if stop:
            break
    text_path = pdf_path.with_suffix(".body.txt")
    body_text = "".join(body_parts)
    atomic_write_text(text_path, body_text)
    return {
        "arxiv_id": pdf_path.stem,
        "pdf_path": str(pdf_path),
        "body_text_path": str(text_path),
        "pdf_pages": len(reader.pages),
        "body_pages_read": cutoff["page"] if cutoff else len(reader.pages),
        "cutoff": cutoff,
        "body_chars": len(body_text),
        "status": "extracted",
    }


def extract_full_text(pdf_path: Path) -> dict:
    try:
        from pypdf import PdfReader
    except (ImportError, ModuleNotFoundError) as exc:
        raise RuntimeError(
            "pypdf is required only for --mode extract or extract-deep.\n"
            "Install it with: pip install pypdf\n"
            "Manifest mode and --help do not require pypdf."
        ) from exc

    reader = PdfReader(str(pdf_path))
    parts = []
    for page_no, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").encode("utf-8", errors="replace").decode("utf-8")
        if text.strip():
            parts.append(f"\n<<< PDF PAGE {page_no} >>>\n{text.strip()}\n")
    text_path = pdf_path.with_suffix(".deep.txt")
    full_text = "".join(parts)
    atomic_write_text(text_path, full_text)
    return {
        "pdf_path": str(pdf_path),
        "deep_text_path": str(text_path),
        "pdf_pages": len(reader.pages),
        "deep_chars": len(full_text),
        "status": "extracted",
    }


def write_manifest(root: Path, batch: str, rows: list[dict]) -> Path:
    path = root / f"{batch}_manifest.json"
    atomic_write_json(path, rows)
    return path


def extract_batch(root: Path, batch: str, rows: list[dict]) -> Path:
    results = []
    for row in rows:
        pdf_path = Path(row["pdf_path"])
        body_path = pdf_path.with_suffix(".body.txt")
        if not pdf_path.exists() or pdf_path.stat().st_size <= 10000:
            results.append(
                {
                    "arxiv_id": row["arxiv_id"],
                    "pdf_path": str(pdf_path),
                    "status": "missing_pdf",
                }
            )
            continue
        if body_path.exists() and body_path.stat().st_size > 1000:
            results.append(
                {
                    "arxiv_id": row["arxiv_id"],
                    "pdf_path": str(pdf_path),
                    "body_text_path": str(body_path),
                    "body_chars": body_path.stat().st_size,
                    "status": "exists",
                }
            )
            continue
        try:
            result = extract_body(pdf_path)
            if result["body_chars"] <= 1000:
                result["status"] = "empty_text"
            results.append(result)
        except Exception as exc:  # noqa: BLE001
            results.append(
                {
                    "arxiv_id": row["arxiv_id"],
                    "pdf_path": str(pdf_path),
                    "status": "parse_failed",
                    "error": str(exc).encode("utf-8", errors="replace").decode("utf-8"),
                }
            )

    path = root / f"{batch}_body_text_manifest.json"
    atomic_write_json(path, results)
    return path


def extract_deep(root: Path, rows: list[dict], batch: str = "") -> Path:
    results = []
    for row in rows:
        pdf_path = Path(row["pdf_path"])
        deep_path = pdf_path.with_suffix(".deep.txt")
        result = dict(row)
        if not pdf_path.exists() or pdf_path.stat().st_size <= 10000:
            result["status"] = "missing_pdf"
        elif deep_path.exists() and deep_path.stat().st_size > 1000:
            result.update({"deep_text_path": str(deep_path), "deep_chars": deep_path.stat().st_size, "status": "exists"})
        else:
            try:
                extracted = extract_full_text(pdf_path)
                result.update(extracted)
                if result["deep_chars"] <= 1000:
                    result["status"] = "empty_text"
            except Exception as exc:  # noqa: BLE001
                result.update(
                    {
                        "status": "parse_failed",
                        "error": str(exc).encode("utf-8", errors="replace").decode("utf-8"),
                    }
                )
        results.append(result)
    name = f"{batch}_deep_text_manifest.json" if batch else "phase3_deep_text_manifest.json"
    path = root / name
    atomic_write_json(path, results)
    return path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", default="")
    parser.add_argument("--inventory", required=True)
    parser.add_argument("--root", required=True)
    parser.add_argument("--mode", choices=["manifest", "extract", "all", "extract-deep"], default="all")
    parser.add_argument("--candidates", help="Candidate CSV used by --mode extract-deep.")
    parser.add_argument("--allow-write", action="store_true")
    args = parser.parse_args()
    require_write_permission(args, "manifest or text extraction output")

    inventory = Path(args.inventory)
    root = Path(args.root)
    root.mkdir(parents=True, exist_ok=True)

    if args.mode == "extract-deep":
        if not args.candidates:
            raise ValueError("--candidates is required for --mode extract-deep")
        rows = load_selected_rows(inventory, root, Path(args.candidates))
        deep_manifest = extract_deep(root, rows, args.batch)
        print(json.dumps({"papers": len(rows), "deep_manifest": str(deep_manifest)}, ensure_ascii=False))
        return

    if not args.batch:
        raise ValueError("--batch is required for manifest and main-body extraction modes")
    rows = load_rows(inventory, root, args.batch)
    output = {"batch": args.batch, "papers": len(rows)}
    if args.mode in {"manifest", "all"}:
        output["manifest"] = str(write_manifest(root, args.batch, rows))
    if args.mode in {"extract", "all"}:
        body_manifest = extract_batch(root, args.batch, rows)
        output["body_manifest"] = str(body_manifest)

    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
