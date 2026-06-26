import argparse
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

from workflow_safety import atomic_write_json, require_network_permission, require_write_permission


ARXIV_RE = re.compile(
    r"""
    (?:
      arxiv\.org/(?:abs|pdf)/ |
      arXiv:
    )?
    (?P<id>
      (?:\d{4}\.\d{4,5})
      (?:v(?P<version>\d+))?
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


def fetch_text(url: str, timeout: int) -> str:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "literature-research-workflow/collect/1.0"},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response:
        data = response.read()
    return data.decode("utf-8", errors="replace")


def read_source(source: str, timeout: int) -> str:
    if re.match(r"https?://", source, re.IGNORECASE):
        return fetch_text(source, timeout)
    return Path(source).read_text(encoding="utf-8", errors="replace")


def normalize_ids(text: str) -> list[dict]:
    by_base: dict[str, dict] = {}
    for match in ARXIV_RE.finditer(text):
        raw_id = match.group("id")
        base_id = raw_id.split("v", 1)[0]
        version = f"v{match.group('version')}" if match.group("version") else None
        current = by_base.get(base_id)
        if current is None:
            by_base[base_id] = {"arxiv_id": base_id, "version": version, "seen": [raw_id]}
            continue
        current["seen"].append(raw_id)
        if version and (current["version"] is None or int(version[1:]) > int(current["version"][1:])):
            current["version"] = version
    return [by_base[key] for key in sorted(by_base)]


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


def existing_candidates(raw_dir: Path, arxiv_id: str) -> list[Path]:
    return sorted(path for path in raw_dir.glob(f"*{arxiv_id}*.pdf") if path.is_file())


def best_existing(raw_dir: Path, arxiv_id: str, min_bytes: int) -> dict | None:
    candidates = []
    for path in existing_candidates(raw_dir, arxiv_id):
        valid, reason, size = validate_pdf(path, min_bytes)
        candidates.append({"path": str(path), "valid": valid, "reason": reason, "bytes": size})
    valid_candidates = [item for item in candidates if item["valid"]]
    if not valid_candidates:
        return None
    valid_candidates.sort(key=lambda item: item["bytes"], reverse=True)
    return valid_candidates[0]


def pdf_url(item: dict) -> str:
    suffix = item["version"] or ""
    return f"https://arxiv.org/pdf/{item['arxiv_id']}{suffix}"


def target_path(raw_dir: Path, item: dict) -> Path:
    suffix = item["version"] or ""
    return raw_dir / f"{item['arxiv_id']}{suffix}.pdf"


def download_pdf(url: str, target: Path, min_bytes: int, timeout: int) -> tuple[bool, str, int]:
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_suffix(target.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "literature-research-workflow/collect/1.0"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=timeout) as response:
            data = response.read()
        part.write_bytes(data)
        valid, reason, size = validate_pdf(part, min_bytes)
        if not valid:
            return False, reason, size
        target.write_bytes(part.read_bytes())
        valid, reason, size = validate_pdf(target, min_bytes)
        return valid, reason, size
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return False, str(exc), 0
    finally:
        try:
            part.unlink(missing_ok=True)
        except OSError:
            pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", action="append", required=True, help="URL or local text/markdown/html file")
    parser.add_argument("--raw-dir", default="raw_papers")
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--delay-ms", type=int, default=500)
    parser.add_argument("--min-bytes", type=int, default=20000)
    parser.add_argument("--status-path")
    parser.add_argument("--allow-write", action="store_true")
    parser.add_argument("--allow-network", action="store_true")
    args = parser.parse_args()
    require_write_permission(args, "arXiv collection status or PDF output")
    if args.download or any(re.match(r"https?://", source, re.IGNORECASE) for source in args.source):
        require_network_permission(args, "arXiv collection fetch or download")

    raw_dir = Path(args.raw_dir)
    combined = []
    source_errors = []
    for source in args.source:
        try:
            combined.append(read_source(source, args.timeout))
        except Exception as exc:  # noqa: BLE001
            source_errors.append({"source": source, "error": str(exc)})

    items = normalize_ids("\n".join(combined))
    results = []
    for item in items:
        existing = best_existing(raw_dir, item["arxiv_id"], args.min_bytes)
        if existing:
            results.append(
                {
                    **item,
                    "status": "exists",
                    "pdf_url": pdf_url(item),
                    "target_path": existing["path"],
                    "bytes": existing["bytes"],
                    "error": None,
                }
            )
            continue

        target = target_path(raw_dir, item)
        if args.dry_run or not args.download:
            results.append(
                {
                    **item,
                    "status": "missing",
                    "pdf_url": pdf_url(item),
                    "target_path": str(target),
                    "bytes": 0,
                    "error": None,
                }
            )
            continue

        ok, reason, size = download_pdf(pdf_url(item), target, args.min_bytes, args.timeout)
        results.append(
            {
                **item,
                "status": "downloaded" if ok else "download_failed",
                "pdf_url": pdf_url(item),
                "target_path": str(target),
                "bytes": size,
                "error": None if ok else reason,
            }
        )
        if args.delay_ms > 0:
            time.sleep(args.delay_ms / 1000)

    counts: dict[str, int] = {}
    for row in results:
        counts[row["status"]] = counts.get(row["status"], 0) + 1

    status_path = Path(args.status_path) if args.status_path else raw_dir / "arxiv_collect_status.json"
    atomic_write_json(status_path, {"source_errors": source_errors, "papers": results})

    print(
        json.dumps(
            {
                "sources": len(args.source),
                "source_errors": len(source_errors),
                "unique_arxiv_ids": len(items),
                "exists": counts.get("exists", 0),
                "missing": counts.get("missing", 0),
                "downloaded": counts.get("downloaded", 0),
                "download_failed": counts.get("download_failed", 0),
                "status_path": str(status_path),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
