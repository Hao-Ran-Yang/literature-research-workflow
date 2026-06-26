import argparse
import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from workflow_safety import atomic_write_json, atomic_write_text, require_write_permission
from awesome_literature_harness import validate_project as validate_project_v2
from registry_utils import is_active_artifact, lifecycle_status, normalize_artifact_entry


REGISTRY_PATH = Path("batches") / "accepted_artifacts.json"
ACTIVE_ACCEPTED_ROOTS = [
    Path("notes") / "accepted",
    Path("reports") / "accepted_overviews",
    Path("candidates") / "accepted",
]
LEGACY_ACCEPTED_FILES = [
    Path("phase2_skim_notes.md"),
    Path("phase2_skim_overview.md"),
    Path("phase2_deep_reading_candidates.csv"),
    Path("phase3_deep_notes.md"),
    Path("final_literature_map.md"),
    Path("key_papers.md"),
    Path("research_opportunities.md"),
    Path("open_questions.md"),
]
REPRESENTATIVE_FIELDS = [
    "paper_id",
    "dedup_key",
    "source_type",
    "source_role",
    "selection_role",
    "selection_axis",
    "selection_reason",
]
BLOCKED_CONTEXT_SUFFIXES = {".pdf"}
BODY_TEXT_RE = re.compile(r"\.(body|deep)\.txt$", re.IGNORECASE)
TMP_RE = re.compile(r"(\.tmp$|_stubs?\.md$)", re.IGNORECASE)
ARCHIVE_PARTS = {"archive"}
DEFAULT_PACKET_CHARS = 12000
ROOT_ALLOWED_FILES = {
    ".gitignore",
    "AGENTS.md",
    "PROJECT_STATUS.md",
    "README.md",
    "scope.md",
    "source_links.md",
}
LEGACY_FLAT_FILES = set(path.as_posix() for path in LEGACY_ACCEPTED_FILES) | {"phase1_inventory.csv", "phase1_report.md"}
LARGE_TABLE_BYTES = 200_000


def project_path(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def is_project_relative(value: str) -> bool:
    if not value:
        return False
    path = Path(value)
    if path.is_absolute():
        return False
    return ".." not in path.parts


def read_json(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"__error__": str(exc)}


def read_json_list(path: Path) -> list[dict]:
    data = read_json(path)
    return data if isinstance(data, list) else []


def normalized_arxiv_id(value: str) -> str:
    return re.sub(r"v\d+$", "", value or "", flags=re.IGNORECASE)


def safe_packet_name(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]", "_", value or "")
    return value.strip("._") or "paper"


def trim_text(text: str, limit: int) -> tuple[str, bool]:
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) <= limit:
        return text, False
    return text[:limit].rstrip() + "\n\n[Packet truncated at configured character budget.]", True


def registry_entries(data) -> tuple[list[dict], str, list[str]]:
    warnings = []
    if data is None:
        return [], "missing", []
    if isinstance(data, dict) and "__error__" in data:
        return [], "invalid-json", [f"registry JSON could not be parsed: {data['__error__']}"]
    if not isinstance(data, dict):
        return [], "unsupported", ["registry must be a v2 object with an artifacts list"]
    if isinstance(data, dict):
        raw_entries = data.get("artifacts", [])
        fmt = "v2-object" if str(data.get("version", "2")) == "2" else "object"
        if not isinstance(raw_entries, list):
            return [], fmt, ["registry field `artifacts` must be a list"]

    entries = []
    for idx, item in enumerate(raw_entries):
        if isinstance(item, dict):
            entry = normalize_artifact_entry(item)
            entry.setdefault("type", "other")
            entry["_index"] = idx
            entries.append(entry)
        else:
            warnings.append(f"registry entry #{idx} must be an object")
    return entries, fmt, warnings


def validate_registry(root: Path) -> dict:
    path = root / REGISTRY_PATH
    data = read_json(path)
    entries, fmt, warnings = registry_entries(data)
    errors = []
    normalized = []
    active_paths = {}

    for entry in entries:
        rel = str(entry.get("path", "")).strip()
        status = lifecycle_status(entry)
        item = {
            "index": entry.get("_index"),
            "type": entry.get("type", "other"),
            "path": rel,
            "status": status,
            "exists": False,
            "legacy": bool(entry.get("_legacy")),
        }
        if not rel:
            errors.append(f"registry entry #{entry.get('_index')} has an empty path")
        elif not is_project_relative(rel):
            errors.append(f"registry entry #{entry.get('_index')} path must be project-relative: {rel}")
        else:
            item["exists"] = project_path(root, rel).exists()
            if not item["exists"]:
                warnings.append(f"registered artifact path does not exist: {rel}")
            if "archive" in Path(rel).parts and status == "active":
                warnings.append(f"active registry entry points into archive: {rel}")
            is_phase1_report = entry.get("artifact_type") == "phase1_report" or str(rel).startswith("reports/accepted_overviews/phase1_report_")
            if not item["legacy"] and item["type"] in {"note", "overview", "candidate_table"} and not is_phase1_report and not entry.get("batch"):
                errors.append(f"registry entry #{entry.get('_index')} type {item['type']} requires batch")
            if status == "active":
                previous = active_paths.get(rel)
                if previous is not None:
                    errors.append(f"duplicate active registry path: {rel} at entries {previous} and {entry.get('_index')}")
                active_paths[rel] = entry.get("_index")
        normalized.append(item)

    return {
        "registry_path": str(path),
        "exists": path.exists(),
        "format": fmt,
        "entries": normalized,
        "active_entries": sum(1 for item in normalized if item["status"] == "active"),
        "warnings": warnings,
        "errors": errors,
    }


def accepted_paths(registry: dict) -> set[str]:
    return {
        item["path"].replace("\\", "/")
        for item in registry.get("entries", [])
        if item.get("path") and item.get("status") == "active"
    }


def registry_paths_by_status(registry: dict, status: str) -> set[str]:
    return {
        item["path"].replace("\\", "/")
        for item in registry.get("entries", [])
        if item.get("path") and item.get("status") == status
    }


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def note_paper_ids(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    ids = {f"arxiv:{match.group(1)}" for match in re.finditer(r"(?i)(?:arxiv:)?(\d{4}\.\d{4,5})(?:v\d+)?", text)}
    return sorted(ids)


def scan_files(root: Path, rel_roots: list[Path]) -> list[str]:
    found = []
    for rel_root in rel_roots:
        base = root / rel_root
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if path.is_file():
                found.append(path.relative_to(root).as_posix())
    return found


def check_root_clean(root: Path) -> dict:
    registry = validate_registry(root)
    accepted = accepted_paths(registry)
    superseded = registry_paths_by_status(registry, "superseded")
    registered = accepted | superseded
    active_files = scan_files(root, ACTIVE_ACCEPTED_ROOTS)
    legacy_files = [path.as_posix() for path in LEGACY_ACCEPTED_FILES if (root / path).exists()]
    unregistered = [path for path in active_files if path not in accepted and path not in superseded]
    orphan_tmp = []
    root_unexpected_files = []
    root_legacy_files = []
    extensionless_tmp_files = []
    archive_references = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        rel_text = rel.as_posix()
        if TMP_RE.search(path.name) and not (set(rel.parts) & ARCHIVE_PARTS):
            orphan_tmp.append(rel_text)
        if len(rel.parts) == 1:
            if rel_text in LEGACY_FLAT_FILES:
                if rel_text not in registered:
                    root_legacy_files.append(rel_text)
            elif path.suffix.lower() in {".md", ".csv"} and rel_text not in ROOT_ALLOWED_FILES:
                root_unexpected_files.append(rel_text)
            elif not path.suffix and path.name.lower() not in {".gitignore", "license", "copying"}:
                extensionless_tmp_files.append(rel_text)
        if set(rel.parts) & ARCHIVE_PARTS and rel_text in accepted:
            archive_references.append(rel_text)
    warnings = list(registry["warnings"])
    if unregistered:
        warnings.append("accepted output files exist but are not registered")
    if orphan_tmp:
        warnings.append("temporary or stub files are present")
    if root_unexpected_files:
        warnings.append("unexpected root-level Markdown/CSV files are present")
    if root_legacy_files:
        warnings.append("legacy flat workflow files are present at project root")
    if extensionless_tmp_files:
        warnings.append("extensionless root-level temporary-looking files are present")
    return {
        "root": str(root),
        "registry": registry,
        "active_files": active_files,
        "legacy_files": legacy_files,
        "unregistered_accepted_files": unregistered,
        "orphan_tmp_files": orphan_tmp,
        "root_unexpected_files": root_unexpected_files,
        "root_legacy_files": root_legacy_files,
        "extensionless_tmp_files": extensionless_tmp_files,
        "archive_references": archive_references,
        "warnings": warnings,
        "errors": registry["errors"],
    }


def check_context_budget(root: Path, paths: list[str], max_packets: int, max_chars: int) -> dict:
    warnings = []
    errors = []
    items = []
    total_chars = 0
    packet_count = 0
    for value in paths:
        rel_ok = is_project_relative(value)
        path = project_path(root, value)
        suffix = path.suffix.lower()
        blocked = suffix in BLOCKED_CONTEXT_SUFFIXES or BODY_TEXT_RE.search(path.name) or TMP_RE.search(path.name)
        chars = 0
        size = path.stat().st_size if path.exists() and path.is_file() else 0
        lower_value = value.replace("\\", "/").lower()
        large_inventory = suffix == ".csv" and ("inventory" in lower_value or size > LARGE_TABLE_BYTES)
        if large_inventory:
            blocked = True
        if path.exists() and path.is_file() and not blocked:
            try:
                chars = len(path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                chars = 0
        if "packet" in path.name.lower():
            packet_count += 1
        if blocked:
            errors.append(f"context input is blocked by packet-only policy: {value}")
        if not rel_ok:
            errors.append(f"context input must be project-relative: {value}")
        total_chars += chars
        items.append({"path": value, "exists": path.exists(), "blocked": bool(blocked), "chars": chars, "bytes": size})
    if packet_count > max_packets:
        errors.append(f"packet count {packet_count} exceeds budget {max_packets}")
    if total_chars > max_chars:
        errors.append(f"context character budget {total_chars} exceeds limit {max_chars}")
    if not paths:
        warnings.append("no context paths were provided")
    return {
        "root": str(root),
        "items": items,
        "packet_count": packet_count,
        "total_chars": total_chars,
        "max_packets": max_packets,
        "max_chars": max_chars,
        "warnings": warnings,
        "errors": errors,
    }


def resolve_representative_candidates(root: Path, requested: str) -> tuple[Path, str]:
    requested_path = project_path(root, requested)
    if requested_path.exists():
        return requested_path, requested
    legacy = root / "inventory" / "phase2a_representative_candidates.csv"
    if legacy.exists():
        return legacy, "inventory/phase2a_representative_candidates.csv"
    return requested_path, requested


def check_representative_candidates(root: Path, requested: str) -> dict:
    path, rel = resolve_representative_candidates(root, requested)
    warnings = []
    errors = []
    rows = []
    if not path.exists():
        errors.append(f"representative candidates file is missing: {rel}")
        return {"path": str(path), "rows": 0, "warnings": warnings, "errors": errors}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames or []
        legacy_fields = {"item_name", "verified_title", "arxiv_id", "canonical_url"}
        required_fields = REPRESENTATIVE_FIELDS if not legacy_fields.intersection(fields) else [
            "dedup_key",
            "source_type",
            "selection_role",
            "selection_axis",
            "selection_reason",
        ]
        missing = [field for field in required_fields if field not in fields]
        if missing:
            errors.append("missing representative candidate fields: " + ", ".join(missing))
        for idx, row in enumerate(reader, start=2):
            rows.append(row)
            if (row.get("reading_priority") or "").strip() == "core_skim":
                for field in ["selection_role", "selection_axis", "selection_reason"]:
                    if not (row.get(field) or "").strip():
                        errors.append(f"row {idx} core_skim is missing {field}")
                reason = (row.get("selection_reason") or "").lower()
                if reason and not any(token in reason for token in ["source", "abstract", "metadata", "manual", "人工"]):
                    warnings.append(f"row {idx} selection_reason should name its evidence basis")
    return {"path": str(path), "rows": len(rows), "warnings": warnings, "errors": errors}


def plan_micro_batches(root: Path, packet_dir: str, size: int) -> dict:
    base = project_path(root, packet_dir)
    packets = []
    if base.exists():
        packets = sorted(path.relative_to(root).as_posix() for path in base.rglob("*") if path.is_file())
    groups = [packets[idx : idx + size] for idx in range(0, len(packets), size)]
    return {
        "root": str(root),
        "packet_dir": packet_dir,
        "micro_batch_size": size,
        "packet_count": len(packets),
        "micro_batches": [{"id": f"MB{idx + 1:02d}", "paths": group} for idx, group in enumerate(groups)],
        "warnings": [] if packets else ["no packet files found"],
        "errors": [],
    }


def resolve_manifest_path(root: Path, requested: str, batch: str, suffix: str) -> Path:
    if requested:
        return project_path(root, requested)
    if not batch:
        return root / suffix
    return root / "phase2_papers" / f"{batch}_{suffix}"


def create_evidence_packets(args, root: Path) -> dict:
    require_write_permission(args, "evidence packet output")
    warnings = []
    errors = []
    batch = args.batch
    manifest_path = resolve_manifest_path(root, args.manifest, batch, "manifest.json")
    body_manifest_path = resolve_manifest_path(root, args.body_manifest, batch, "body_text_manifest.json")
    packet_dir = project_path(root, args.packet_dir or f"phase2_papers/{batch}_packets")
    packet_manifest_path = project_path(root, args.packet_manifest or f"phase2_papers/{batch}_packet_manifest.json")

    manifest_rows = read_json_list(manifest_path)
    body_rows = read_json_list(body_manifest_path)
    metadata_by_id = {normalized_arxiv_id(row.get("arxiv_id", "")): row for row in manifest_rows}
    if not body_rows:
        errors.append(f"body text manifest is missing or empty: {body_manifest_path}")
    if not packet_dir.is_relative_to(root):
        errors.append("packet directory must be inside the project root")
    if errors:
        return {"root": str(root), "created": [], "packet_manifest": str(packet_manifest_path), "warnings": warnings, "errors": errors}

    packet_rows = []
    created = []
    for row in body_rows:
        arxiv_id = normalized_arxiv_id(row.get("arxiv_id", ""))
        status_value = row.get("status", "")
        body_path = Path(row.get("body_text_path") or "")
        if not body_path.is_absolute():
            body_path = root / body_path
        if status_value not in {"exists", "extracted"}:
            warnings.append(f"skip {arxiv_id or '<missing-id>'}: body status is {status_value or 'missing'}")
            continue
        if not body_path.exists():
            warnings.append(f"skip {arxiv_id or '<missing-id>'}: body text missing at {body_path}")
            continue
        metadata = metadata_by_id.get(arxiv_id, {})
        text = body_path.read_text(encoding="utf-8", errors="replace")
        packet_text, truncated = trim_text(text, args.max_packet_chars)
        title = metadata.get("title") or row.get("title") or arxiv_id
        packet_path = packet_dir / f"{safe_packet_name(arxiv_id)}.packet.md"
        content = "\n".join(
            [
                f"# Evidence Packet: {title}",
                "",
                f"- arXiv: {arxiv_id}",
                f"- Batch: {batch}",
                f"- Source body: {body_path.relative_to(root).as_posix() if body_path.is_relative_to(root) else str(body_path)}",
                f"- Packet chars: {len(packet_text)}",
                f"- Truncated: {'yes' if truncated else 'no'}",
                f"- Technical route: {metadata.get('method_category', '')}",
                "",
                "## Bounded Main-Body Evidence",
                "",
                packet_text,
                "",
            ]
        )
        atomic_write_json(packet_path.with_suffix(".quality.json"), {
            "arxiv_id": arxiv_id,
            "batch": batch,
            "body_chars": len(text),
            "packet_chars": len(packet_text),
            "truncated": truncated,
            "status": "packet_created",
        })
        atomic_write_text(packet_path, content)
        rel_packet = packet_path.relative_to(root).as_posix()
        created.append(rel_packet)
        packet_rows.append(
            {
                "arxiv_id": arxiv_id,
                "title": title,
                "batch": batch,
                "packet_path": rel_packet,
                "body_text_path": body_path.relative_to(root).as_posix() if body_path.is_relative_to(root) else str(body_path),
                "packet_chars": len(packet_text),
                "body_chars": len(text),
                "truncated": truncated,
                "quality_path": packet_path.with_suffix(".quality.json").relative_to(root).as_posix(),
                "status": "packet_created",
            }
        )
    atomic_write_json(
        packet_manifest_path,
        {
            "version": 1,
            "batch": batch,
            "max_packet_chars": args.max_packet_chars,
            "packet_count": len(packet_rows),
            "packets": packet_rows,
        },
    )
    return {
        "root": str(root),
        "batch": batch,
        "created": created,
        "packet_manifest": str(packet_manifest_path),
        "packet_count": len(packet_rows),
        "warnings": warnings,
        "errors": [],
    }


def packet_paths_from_manifest(root: Path, packet_manifest: str) -> list[str]:
    path = project_path(root, packet_manifest)
    data = read_json(path)
    if isinstance(data, dict) and isinstance(data.get("packets"), list):
        return [row.get("packet_path", "") for row in data["packets"] if row.get("packet_path")]
    return []


def plan_micro_batches_from_packets(root: Path, packet_dir: str, packet_manifest: str, size: int) -> dict:
    packets = packet_paths_from_manifest(root, packet_manifest) if packet_manifest else []
    if not packets:
        return plan_micro_batches(root, packet_dir, size)
    groups = [packets[idx : idx + size] for idx in range(0, len(packets), size)]
    return {
        "root": str(root),
        "packet_dir": packet_dir,
        "packet_manifest": packet_manifest,
        "micro_batch_size": size,
        "packet_count": len(packets),
        "micro_batches": [{"id": f"MB{idx + 1:02d}", "paths": group} for idx, group in enumerate(groups)],
        "warnings": [],
        "errors": [],
    }


def check_overview_gate(root: Path, batch: str, packet_manifest: str, micro_batch_size: int) -> dict:
    registry = validate_registry(root)
    plan = plan_micro_batches_from_packets(root, f"phase2_papers/{batch}_packets", packet_manifest, micro_batch_size)
    expected_micro_batches = [item["id"] for item in plan.get("micro_batches", [])]
    manifest = read_json(project_path(root, packet_manifest)) or {}
    expected_paper_ids = []
    if isinstance(manifest, dict):
        for packet in manifest.get("packets", []):
            if not isinstance(packet, dict):
                continue
            if packet.get("status") != "created" or (packet.get("quality_status") and packet.get("quality_status") != "pass"):
                continue
            paper_id = packet.get("paper_id")
            if paper_id:
                expected_paper_ids.append(paper_id)
    accepted_micro_batches = []
    accepted_paper_ids = []
    has_batch_level_note = False
    raw = read_json(root / REGISTRY_PATH)
    entries, _, entry_warnings = registry_entries(raw)
    for entry in entries:
        if entry.get("batch") != batch:
            continue
        if entry.get("type") != "note" and entry.get("artifact_type") not in {"batch_skim_note", "micro_batch_skim_note"}:
            continue
        if not is_active_artifact(entry):
            continue
        if entry.get("micro_batch"):
            accepted_micro_batches.append(entry.get("micro_batch"))
        elif entry.get("artifact_type") == "batch_skim_note":
            has_batch_level_note = True
        paper_ids = entry.get("paper_ids") or []
        if isinstance(paper_ids, list):
            accepted_paper_ids.extend(str(pid) for pid in paper_ids if pid)
    missing_paper_ids = [item for item in sorted(set(expected_paper_ids)) if item not in set(accepted_paper_ids)]
    if has_batch_level_note and expected_paper_ids and not missing_paper_ids:
        missing_micro_batches = []
    else:
        missing_micro_batches = [item for item in expected_micro_batches if item not in set(accepted_micro_batches)]
    warnings = list(registry.get("warnings", [])) + entry_warnings
    if not expected_micro_batches:
        warnings.append("no planned micro-batches found")
    paper_coverage_ok = not accepted_paper_ids or not missing_paper_ids
    planned_work_exists = bool(expected_paper_ids or expected_micro_batches)
    return {
        "root": str(root),
        "batch": batch,
        "expected_micro_batches": expected_micro_batches,
        "accepted_micro_batches": sorted(set(accepted_micro_batches)),
        "missing_micro_batches": missing_micro_batches,
        "expected_paper_ids": sorted(set(expected_paper_ids)),
        "accepted_paper_ids": sorted(set(accepted_paper_ids)),
        "missing_paper_ids": missing_paper_ids,
        "ready_for_overview": planned_work_exists and paper_coverage_ok and not missing_micro_batches and not registry.get("errors"),
        "warnings": warnings,
        "errors": registry.get("errors", []),
    }


def load_registry_for_write(root: Path) -> tuple[dict, list[dict], list[str], list[str]]:
    path = root / REGISTRY_PATH
    data = read_json(path)
    warnings = []
    errors = []
    if data is None:
        data = {"version": 2, "artifacts": []}
    elif isinstance(data, dict) and "__error__" in data:
        return {}, [], warnings, [f"registry JSON could not be parsed: {data['__error__']}"]
    elif isinstance(data, list):
        return {}, [], warnings, ["register-artifact requires a current v2 object registry"]
    elif not isinstance(data, dict):
        return {}, [], warnings, ["registry must be a v2 object for register-artifact"]
    data.setdefault("version", 2)
    artifacts = data.setdefault("artifacts", [])
    if not isinstance(artifacts, list):
        errors.append("registry field `artifacts` must be a list")
        artifacts = []
    return data, artifacts, warnings, errors


def register_artifact(args, root: Path) -> dict:
    require_write_permission(args, "accepted artifact registry update")
    warnings = []
    errors = []
    rel = (args.artifact_path or "").strip().replace("\\", "/")
    if args.artifact_type in {"note", "overview", "candidate_table", "phase3_deep_note"} and not args.batch:
        errors.append(f"{args.artifact_type} artifacts require --batch")
    if not is_project_relative(rel):
        errors.append(f"artifact path must be project-relative: {args.artifact_path}")
    path = project_path(root, rel)
    if rel and not path.exists():
        errors.append(f"artifact path does not exist: {rel}")
    if rel and "archive" in Path(rel).parts and args.quality_status != "superseded":
        errors.append(f"active artifact path must not point into archive: {rel}")

    registry_data, artifacts, load_warnings, load_errors = load_registry_for_write(root)
    warnings.extend(load_warnings)
    errors.extend(load_errors)
    supersedes = [item.replace("\\", "/") for item in args.supersedes]
    active_paths = {
        str(item.get("path", "")).replace("\\", "/"): item
        for item in artifacts
        if isinstance(item, dict) and is_active_artifact(item)
    }
    if rel in active_paths and rel not in supersedes:
        errors.append(f"active artifact is already registered: {rel}; use --supersedes {rel} to replace it explicitly")
    for superseded in supersedes:
        if not is_project_relative(superseded):
            errors.append(f"superseded path must be project-relative: {superseded}")
        elif superseded not in active_paths:
            warnings.append(f"superseded path is not an active registry entry: {superseded}")
    if errors:
        return {
            "root": str(root),
            "registry_path": str(root / REGISTRY_PATH),
            "registered": False,
            "warnings": warnings,
            "errors": errors,
        }

    for superseded in supersedes:
        entry = active_paths.get(superseded)
        if entry is not None:
            entry["status"] = "superseded"
            entry.pop("quality_status", None)
            entry.setdefault("notes", "")
            note = f"Superseded by {rel}"
            entry["notes"] = f"{entry['notes']}; {note}" if entry["notes"] else note

    requested_status = "superseded" if args.quality_status == "superseded" else "active"
    new_entry = {
        "artifact_type": args.artifact_type,
        "type": args.artifact_type,
        "path": rel,
        "status": requested_status,
        "review_status": "clean" if args.quality_status in {"accepted", "unknown"} else args.quality_status,
        "registered_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
    if path.exists() and path.is_file():
        new_entry["content_hash"] = file_sha256(path)
    if args.artifact_type == "phase3_deep_note":
        new_entry["type"] = "note"
        new_entry["paper_ids"] = note_paper_ids(path)
        candidate_table = f"candidates/accepted/{args.batch}_deep_reading_candidates.csv"
        deep_manifest = f"phase2_papers/{args.batch}_deep_text_manifest.json"
        if (root / candidate_table).exists():
            new_entry["source_candidate_table"] = candidate_table
        if (root / deep_manifest).exists():
            new_entry["source_deep_manifest"] = deep_manifest
    for key, value in [
        ("batch", args.batch),
        ("artifact_label", args.artifact_label),
        ("micro_batch", args.micro_batch),
        ("notes", args.notes),
    ]:
        if value:
            new_entry[key] = value
    default_artifact_id = (
        f"{new_entry.get('artifact_type', new_entry.get('type', 'artifact'))}:"
        f"{new_entry.get('batch', '')}:"
        f"{new_entry.get('micro_batch', '')}:"
        f"{new_entry.get('path')}"
    )
    new_entry.setdefault("artifact_id", default_artifact_id)
    existing_artifact_ids = {
        item.get("artifact_id")
        for item in artifacts
        if isinstance(item, dict) and item.get("artifact_id")
    }
    if new_entry["artifact_id"] in existing_artifact_ids:
        suffix = new_entry.get("content_hash", new_entry["registered_at"]).replace(":", "").replace("-", "")[:12]
        new_entry["artifact_id"] = f"{default_artifact_id}:{suffix}"
    if supersedes:
        new_entry["supersedes"] = supersedes
    artifacts.append(new_entry)
    atomic_write_json(root / REGISTRY_PATH, registry_data)
    return {
        "root": str(root),
        "registry_path": str(root / REGISTRY_PATH),
        "registered": True,
        "entry": new_entry,
        "warnings": warnings,
        "errors": [],
    }


def refresh_artifact_hash(args, root: Path) -> dict:
    require_write_permission(args, "accepted artifact registry hash refresh")
    rel = (args.artifact_path or "").strip().replace("\\", "/")
    errors = []
    warnings = []
    if not is_project_relative(rel):
        errors.append(f"artifact path must be project-relative: {args.artifact_path}")
    path = project_path(root, rel)
    if rel and not path.exists():
        errors.append(f"artifact path does not exist: {rel}")
    registry_data, artifacts, load_warnings, load_errors = load_registry_for_write(root)
    warnings.extend(load_warnings)
    errors.extend(load_errors)
    matches = [
        item for item in artifacts
        if isinstance(item, dict)
        and str(item.get("path", "")).replace("\\", "/") == rel
        and is_active_artifact(item)
    ]
    if not matches:
        errors.append(f"active artifact is not registered: {rel}")
    if len(matches) > 1:
        errors.append(f"multiple active registry entries found for: {rel}")
    if errors:
        return {
            "root": str(root),
            "registry_path": str(root / REGISTRY_PATH),
            "artifact_path": rel,
            "refreshed": False,
            "warnings": warnings,
            "errors": errors,
        }
    entry = matches[0]
    old_hash = entry.get("content_hash", "")
    new_hash = file_sha256(path)
    entry["content_hash"] = new_hash
    atomic_write_json(root / REGISTRY_PATH, registry_data)
    return {
        "root": str(root),
        "registry_path": str(root / REGISTRY_PATH),
        "artifact_path": rel,
        "refreshed": True,
        "old_hash": old_hash,
        "new_hash": new_hash,
        "warnings": warnings,
        "errors": [],
    }


def archive_target_for(rel: str) -> str:
    path = Path(rel)
    if rel.startswith("notes/"):
        return (Path("archive") / "superseded_notes" / path.name).as_posix()
    if rel.startswith("reports/"):
        return (Path("archive") / "superseded_reports" / path.name).as_posix()
    if path.suffix.lower() == ".csv":
        return (Path("archive") / "raw_tables" / path.name).as_posix()
    return (Path("archive") / "repair_history" / path.name).as_posix()


def archive_superseded(args, root: Path) -> dict:
    registry_data = read_json(root / REGISTRY_PATH)
    entries, _, warnings = registry_entries(registry_data)
    errors = []
    moves = []
    for entry in entries:
        if lifecycle_status(entry) != "superseded":
            continue
        source = str(entry.get("path", "")).replace("\\", "/")
        if not is_project_relative(source):
            errors.append(f"superseded path must be project-relative: {source}")
            continue
        source_path = root / source
        target = archive_target_for(source)
        target_path = root / target
        moves.append({"source": source, "target": target, "exists": source_path.exists()})
        if args.plan_only:
            continue
        if not args.allow_write:
            errors.append("archive-superseded requires --plan-only or --allow-write")
            continue
        if not source_path.exists():
            warnings.append(f"superseded source does not exist: {source}")
            continue
        if target_path.exists():
            errors.append(f"archive target already exists: {target}")
            continue
        target_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.replace(target_path)
        entry["path"] = target
        entry.setdefault("notes", "")
        note = f"Archived from {source}"
        entry["notes"] = f"{entry['notes']}; {note}" if entry["notes"] else note
    if not args.plan_only and args.allow_write and not errors:
        if isinstance(registry_data, dict):
            atomic_write_json(root / REGISTRY_PATH, registry_data)
        else:
            errors.append("archive-superseded write mode requires a v2 registry object")
    return {
        "root": str(root),
        "plan_only": bool(args.plan_only),
        "moves": moves,
        "warnings": warnings,
        "errors": errors,
    }


def status(root: Path) -> dict:
    registry = validate_registry(root)
    cache_paths = sorted((root / ".codex").glob("*state*.json")) if (root / ".codex").exists() else []
    clean = check_root_clean(root)
    if registry["exists"] and not registry["errors"]:
        if registry["active_entries"] == 0:
            effective = "registry_initialized"
            next_gate = "registry initialized; run phase workflow or import sources before registering accepted artifacts"
        else:
            effective = "registry_available"
            next_gate = "use registered accepted artifacts; inspect warnings before synthesis" if registry["warnings"] else "ready for registered artifact workflow"
    elif clean["legacy_files"]:
        effective = "legacy_files_available"
        next_gate = "legacy project: keep read-preserve behavior and consider migration-plan before strict registry use"
    else:
        effective = "no_accepted_registry"
        next_gate = "run phase workflow or initialize accepted artifact registry for new template projects"
    return {
        "root": str(root),
        "registry": registry,
        "filesystem_facts": {
            "active_accepted_files": clean["active_files"],
            "legacy_files": clean["legacy_files"],
        },
        "cache_receipts": [str(path.relative_to(root)) for path in cache_paths],
        "effective_status": effective,
        "next_gate": next_gate,
        "warnings": registry["warnings"] + clean["warnings"],
        "errors": registry["errors"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only harness checks for arXiv literature projects.")
    parser.add_argument("--root", default=".")
    parser.add_argument(
        "--action",
        choices=[
            "status",
            "check-registry",
            "check-root-clean",
            "check-context-budget",
            "check-representative-candidates",
            "plan-micro-batches",
            "register-artifact",
            "refresh-artifact-hash",
            "create-evidence-packets",
            "check-overview-gate",
            "archive-superseded",
            "validate-project",
        ],
        default="status",
    )
    parser.add_argument("--paths", nargs="*", default=[], help="Project-relative context files for check-context-budget.")
    parser.add_argument("--max-packets", type=int, default=4)
    parser.add_argument("--max-chars", type=int, default=48000)
    parser.add_argument("--candidates", default="inventory/representative_candidates.csv")
    parser.add_argument("--packet-dir", default="")
    parser.add_argument("--packet-manifest", default="")
    parser.add_argument("--micro-batch-size", type=int, default=4)
    parser.add_argument("--batch", default="")
    parser.add_argument("--manifest", default="")
    parser.add_argument("--body-manifest", default="")
    parser.add_argument("--max-packet-chars", type=int, default=DEFAULT_PACKET_CHARS)
    parser.add_argument("--allow-write", action="store_true")
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--artifact-type", default="note", choices=["note", "phase3_deep_note", "overview", "candidate_table", "final_report", "failure", "other"])
    parser.add_argument("--artifact-path", default="")
    parser.add_argument("--quality-status", default="accepted", choices=["accepted", "warning", "failed", "superseded", "unknown"])
    parser.add_argument("--artifact-label", default="")
    parser.add_argument("--micro-batch", default="")
    parser.add_argument("--supersedes", nargs="*", default=[])
    parser.add_argument("--notes", default="")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if args.action == "status":
        result = status(root)
    elif args.action == "check-registry":
        result = validate_registry(root)
    elif args.action == "check-root-clean":
        result = check_root_clean(root)
    elif args.action == "check-context-budget":
        result = check_context_budget(root, args.paths, args.max_packets, args.max_chars)
    elif args.action == "check-representative-candidates":
        result = check_representative_candidates(root, args.candidates)
    elif args.action == "register-artifact":
        result = register_artifact(args, root)
    elif args.action == "refresh-artifact-hash":
        result = refresh_artifact_hash(args, root)
    elif args.action == "create-evidence-packets":
        result = create_evidence_packets(args, root)
    elif args.action == "check-overview-gate":
        result = check_overview_gate(root, args.batch, args.packet_manifest, args.micro_batch_size)
    elif args.action == "archive-superseded":
        result = archive_superseded(args, root)
    elif args.action == "validate-project":
        result = validate_project_v2(root)
    else:
        result = plan_micro_batches_from_packets(root, args.packet_dir or "phase2_papers", args.packet_manifest, args.micro_batch_size)
    result["action"] = args.action
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
