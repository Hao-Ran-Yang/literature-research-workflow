import argparse
import csv
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

from workflow_safety import atomic_write_csv, require_network_permission, require_write_permission


FIELDS = [
    "section",
    "method_category",
    "application_tag",
    "reading_batch",
    "arxiv_id",
    "title",
    "authors",
    "first_submitted",
    "latest_version_date",
    "abs_url",
    "pdf_url",
    "source_url",
    "reading_priority",
    "classification_confidence",
    "classification_source",
    "notes",
]

ARXIV_RE = re.compile(
    r"(?:(?:https?://)?arxiv\.org/(?:abs|pdf)/|arXiv:)?(?P<id>\d{4}\.\d{4,5})(?:v(?P<version>\d+))?",
    re.IGNORECASE,
)

HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*$")


def read_source(source: str, timeout: int) -> str:
    if re.match(r"https?://", source, re.IGNORECASE):
        request = urllib.request.Request(
            source,
            headers={"User-Agent": "literature-research-workflow/build-inventory/1.0"},
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace")
    return Path(source).read_text(encoding="utf-8", errors="replace")


def clean_heading(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[\[\]()`*_]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def collect_ids(text: str) -> list[dict]:
    rows_by_id: dict[str, dict] = {}
    order: list[str] = []
    current_section = "Uncategorized"
    lines = text.splitlines()
    for line_no, line in enumerate(lines, start=1):
        heading = HEADING_RE.match(line)
        if heading:
            current_section = clean_heading(heading.group(2)) or current_section
        for match in ARXIV_RE.finditer(line):
            base_id = match.group("id")
            version = f"v{match.group('version')}" if match.group("version") else ""
            row = rows_by_id.get(base_id)
            if row is None:
                order.append(base_id)
                rows_by_id[base_id] = {
                    "section": current_section,
                    "method_category": "",
                    "application_tag": "",
                    "reading_batch": "",
                    "arxiv_id": base_id,
                    "title": infer_title(line, base_id),
                    "authors": "",
                    "first_submitted": "",
                    "latest_version_date": "",
                    "abs_url": f"https://arxiv.org/abs/{base_id}",
                    "pdf_url": f"https://arxiv.org/pdf/{base_id}.pdf",
                    "source_url": "",
                    "reading_priority": "",
                    "classification_confidence": "",
                    "classification_source": "",
                    "notes": f"first-pass extraction line {line_no}" + (f"; seen {version}" if version else ""),
                }
                continue
            if version and version not in row["notes"]:
                row["notes"] += f"; seen {version}"
    return [rows_by_id[key] for key in order]


def infer_title(line: str, arxiv_id: str) -> str:
    line = re.sub(r"\[([^\]]+)\]\([^)]*arxiv\.org/[^)]*\)", r"\1", line, flags=re.IGNORECASE)
    line = re.sub(r"https?://arxiv\.org/(?:abs|pdf)/\S+", " ", line, flags=re.IGNORECASE)
    line = re.sub(r"arXiv:\s*" + re.escape(arxiv_id) + r"(?:v\d+)?", " ", line, flags=re.IGNORECASE)
    line = re.sub(re.escape(arxiv_id) + r"(?:v\d+)?", " ", line)
    line = re.sub(r"<[^>]+>", " ", line)
    line = re.sub(r"^[\s>*#\-\d.)]+", "", line)
    line = re.sub(r"\[[^\]]*\]\([^)]*\)", " ", line)
    line = re.sub(r"[\[\]()`*_]+", "", line)
    line = re.sub(r"\s+", " ", line).strip(" -:|")
    return line[:240]


def fetch_arxiv_metadata(ids: list[str], timeout: int) -> dict[str, dict]:
    if not ids:
        return {}
    metadata = {}
    chunk_size = 100
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    for start in range(0, len(ids), chunk_size):
        chunk = ids[start : start + chunk_size]
        query = urllib.parse.urlencode({"id_list": ",".join(chunk)})
        url = f"https://export.arxiv.org/api/query?{query}"
        request = urllib.request.Request(url, headers={"User-Agent": "literature-research-workflow/metadata/1.0"})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=timeout) as response:
            root = ET.fromstring(response.read())
        for entry in root.findall("atom:entry", ns):
            raw_id = entry.findtext("atom:id", default="", namespaces=ns).rstrip("/").split("/")[-1]
            base_id = raw_id.split("v", 1)[0]
            title = " ".join((entry.findtext("atom:title", default="", namespaces=ns) or "").split())
            authors = "; ".join(
                " ".join((author.findtext("atom:name", default="", namespaces=ns) or "").split())
                for author in entry.findall("atom:author", ns)
            )
            published = entry.findtext("atom:published", default="", namespaces=ns)[:10]
            updated = entry.findtext("atom:updated", default="", namespaces=ns)[:10]
            metadata[base_id] = {
                "title": title,
                "authors": authors,
                "first_submitted": published,
                "latest_version_date": updated,
                "abs_url": f"https://arxiv.org/abs/{base_id}",
                "pdf_url": f"https://arxiv.org/pdf/{base_id}.pdf",
            }
    return metadata


def append_note(row: dict, note: str) -> None:
    existing = row.get("notes", "")
    if note in existing:
        return
    row["notes"] = f"{existing}; {note}" if existing else note


def write_inventory(path: Path, rows: list[dict], overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(f"{path} exists; pass --overwrite to replace it")
    atomic_write_csv(path, FIELDS, rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a first-pass arXiv literature inventory.")
    parser.add_argument("--source", required=True, help="Local text/Markdown/HTML file or URL.")
    parser.add_argument("--output", default="phase1_inventory.csv")
    parser.add_argument("--fetch-metadata", action="store_true", help="Fetch arXiv API metadata.")
    parser.add_argument("--source-url", default="", help="Original source URL to store in each row.")
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--allow-write", action="store_true")
    parser.add_argument("--allow-network", action="store_true")
    args = parser.parse_args()
    require_write_permission(args, "Phase 1 inventory output")
    if re.match(r"https?://", args.source, re.IGNORECASE) or args.fetch_metadata:
        require_network_permission(args, "Phase 1 source or metadata fetch")

    text = read_source(args.source, args.timeout)
    rows = collect_ids(text)
    for row in rows:
        row["source_url"] = args.source_url or (args.source if re.match(r"https?://", args.source) else "")

    if args.fetch_metadata:
        meta = fetch_arxiv_metadata([row["arxiv_id"] for row in rows], args.timeout)
        for row in rows:
            item = meta.get(row["arxiv_id"], {})
            for key, value in item.items():
                if value:
                    row[key] = value
    else:
        for row in rows:
            append_note(row, "metadata_not_fetched; local arXiv ID extraction only")

    write_inventory(Path(args.output), rows, args.overwrite)
    print({"output": args.output, "rows": len(rows), "metadata_fetched": args.fetch_metadata})


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print({"error": str(exc)}, file=sys.stderr)
        raise
