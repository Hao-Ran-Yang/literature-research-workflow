import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from registry_utils import is_active_artifact

ENTRY_RE = re.compile(r"^####\s+", re.MULTILINE)
HEADING_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)
BATCH_RE = re.compile(r"\b(B\d{2,})\b")
ARXIV_RE = re.compile(r"(?:arXiv[:\s]*)?(\d{4}\.\d{4,5}(?:v\d+)?)", re.IGNORECASE)


def read_inventory(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def resolve_inventory(root: Path, requested: str) -> Path:
    requested_path = Path(requested)
    path = requested_path if requested_path.is_absolute() else root / requested_path
    if path.exists():
        return path
    v2 = root / "inventory" / "workflow_inventory.csv"
    if v2.exists():
        return v2
    candidates = sorted(root.glob("phase1*_inventory.csv"))
    if len(candidates) == 1:
        return candidates[0]
    preferred = [item for item in candidates if item.name == "phase1_inventory.csv"]
    return preferred[0] if preferred else path


def is_template_v2(root: Path) -> bool:
    return (root / "inventory" / "workflow_inventory.csv").exists() and (root / "batches" / "accepted_artifacts.json").exists()


def rel_or_requested(root: Path, path: Path, requested: str) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return requested


def phase1_report_path(root: Path) -> Path:
    accepted_dir = root / "reports" / "accepted_overviews"
    accepted = sorted(accepted_dir.glob("*phase1*.md")) if accepted_dir.exists() else []
    if accepted:
        return accepted[0]
    draft = root / "reports" / "drafts" / "phase1_report.md"
    if draft.exists():
        return draft
    return root / "phase1_report.md"


def batch_code(value: str) -> str:
    match = BATCH_RE.search(value or "")
    return match.group(1) if match else ""


def batch_sort_key(code: str) -> int:
    match = re.match(r"B(\d+)", code or "")
    return int(match.group(1)) if match else 9999


def normalized_arxiv_id(value: str) -> str:
    value = re.sub(r"^arxiv:", "", value or "", flags=re.IGNORECASE)
    return re.sub(r"v\d+$", "", value, flags=re.IGNORECASE)


def normalized_paper_id(value: str) -> str:
    value = str(value or "").strip()
    if not value:
        return ""
    match = re.search(r"(?i)(?:arxiv:)?(\d{4}\.\d{4,5})(?:v\d+)?", value)
    if match:
        return f"arxiv:{match.group(1)}"
    return value


def normalized_row_arxiv_id(row: dict) -> str:
    return normalized_paper_id(row.get("paper_id") or row.get("arxiv_id") or "")


def safe_name(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9 -]", "", value or "")
    return value.replace(" ", "_")


def derived_pdf_path(phase2_root: Path, row: dict) -> Path:
    section = re.sub(r"[^A-Za-z0-9-]", "_", row.get("section", ""))
    method = safe_name(row.get("method_category", ""))
    return phase2_root / section / method / f"{row.get('arxiv_id', '')}.pdf"


def read_json(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def accepted_phase1_report(root: Path) -> bool:
    data = read_json(root / "batches" / "accepted_artifacts.json") or {}
    artifacts = data.get("artifacts", []) if isinstance(data, dict) else []
    for item in artifacts:
        if not isinstance(item, dict):
            continue
        kind = item.get("artifact_type") or item.get("type")
        if (kind == "phase1_report" or (kind == "overview" and "phase1" in str(item.get("path", "")).lower())) and is_active_artifact(item):
            return True
    return False


def has_substantive_content(path: Path) -> bool:
    if not path.exists() or not path.is_file():
        return False
    if path.suffix.lower() == ".json":
        return bool(read_json(path))
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() == ".csv":
        return len([line for line in text.splitlines() if line.strip()]) > 1
    return any(line.strip() and not line.lstrip().startswith("#") for line in text.splitlines())


def directory_has_files(path: Path) -> bool:
    return path.exists() and any(item.is_file() for item in path.rglob("*"))


def note_ids_by_batch(notes_path: Path, inventory_batch_by_id: dict[str, str]) -> dict[str, set[str]]:
    if not notes_path.exists():
        return {}
    markdown = notes_path.read_text(encoding="utf-8", errors="replace")
    headings = list(HEADING_RE.finditer(markdown))
    ids_by_batch: dict[str, set[str]] = defaultdict(set)
    for idx, heading in enumerate(headings):
        code = batch_code(heading.group(1))
        start = heading.end()
        end = headings[idx + 1].start() if idx + 1 < len(headings) else len(markdown)
        section = markdown[start:end]
        ids = {normalized_arxiv_id(match.group(1)) for match in ARXIV_RE.finditer(section)}
        for arxiv_id in ids:
            resolved_code = code or inventory_batch_by_id.get(arxiv_id, "")
            if resolved_code:
                ids_by_batch[resolved_code].add(arxiv_id)
    # Older notes may have no useful ## heading at all.
    if not any(ids_by_batch.values()):
        for match in ARXIV_RE.finditer(markdown):
            arxiv_id = normalized_arxiv_id(match.group(1))
            code = inventory_batch_by_id.get(arxiv_id, "")
            if code:
                ids_by_batch[code].add(arxiv_id)
    return dict(ids_by_batch)


def note_arxiv_ids(notes_path: Path) -> set[str]:
    if not notes_path.exists():
        return set()
    return {normalized_arxiv_id(match.group(1)) for match in ARXIV_RE.finditer(notes_path.read_text(encoding="utf-8", errors="replace"))}


def note_paper_ids(notes_path: Path) -> set[str]:
    if not notes_path.exists():
        return set()
    text = notes_path.read_text(encoding="utf-8", errors="replace")
    ids = {normalized_paper_id(match.group(1)) for match in re.finditer(r"(?m)^###\s+(\S+)\s+-\s+", text)}
    ids.update(normalized_paper_id(match.group(1)) for match in re.finditer(r"(?i)paper_id=([^\s,;]+)", text))
    ids.update(f"arxiv:{item}" for item in note_arxiv_ids(notes_path))
    return {item for item in ids if item}


def registry_skim_ids_by_batch(root: Path) -> dict[str, set[str]]:
    data = read_json(root / "batches" / "accepted_artifacts.json") or {}
    artifacts = data.get("artifacts", []) if isinstance(data, dict) else []
    ids_by_batch: dict[str, set[str]] = defaultdict(set)
    for item in artifacts:
        if not isinstance(item, dict):
            continue
        kind = item.get("artifact_type") or item.get("type")
        if kind not in {"batch_skim_note", "micro_batch_skim_note"} or not is_active_artifact(item):
            continue
        code = batch_code(item.get("batch", ""))
        if not code:
            continue
        for paper_id in item.get("paper_ids") or []:
            normalized = normalized_paper_id(str(paper_id))
            if normalized:
                ids_by_batch[code].add(normalized)
    return dict(ids_by_batch)


def normalize_manifest_rows(phase2_root: Path, inventory_rows: list[dict], manifest: list[dict], body_manifest: list[dict]) -> list[dict]:
    def key_for(row: dict) -> str:
        return row.get("paper_id") or normalized_arxiv_id(row.get("arxiv_id", ""))

    manifest_by_id = {key_for(row): row for row in manifest if isinstance(row, dict)}
    body_by_id = {key_for(row): row for row in body_manifest if isinstance(row, dict)}
    normalized = []
    for inventory_row in inventory_rows:
        item_key = key_for(inventory_row)
        row = {**inventory_row, **manifest_by_id.get(item_key, {})}
        body_row = body_by_id.get(item_key, {})
        row["pdf_path"] = body_row.get("pdf_path") or row.get("pdf_path") or str(derived_pdf_path(phase2_root, inventory_row))
        row["body_text_path"] = body_row.get("body_text_path") or row.get("body_text_path") or str(Path(row["pdf_path"]).with_suffix(".body.txt"))
        normalized.append(row)
    return normalized


def count_valid_pdfs(manifest: list[dict]) -> int:
    count = 0
    for row in manifest:
        path = Path(row.get("pdf_path", ""))
        if path.exists() and path.is_file() and path.stat().st_size > 20000:
            try:
                with path.open("rb") as handle:
                    if handle.read(5) == b"%PDF-":
                        count += 1
            except OSError:
                pass
    return count


def count_body_texts(manifest: list[dict]) -> int:
    return sum(
        1
        for row in manifest
        if Path(row.get("body_text_path") or Path(row.get("pdf_path", "")).with_suffix(".body.txt")).exists()
        and Path(row.get("body_text_path") or Path(row.get("pdf_path", "")).with_suffix(".body.txt")).stat().st_size > 1000
    )


def missing_project_files(root: Path, inventory_path: Path, requested_inventory: str, rows: list[dict], phase1_report: bool, mature_project: bool) -> list[str]:
    missing = []
    template_v2 = is_template_v2(root)
    if not (root / "source_links.md").exists():
        missing.append("source_links.md")
    if rows or phase1_report:
        if not (root / "scope.md").exists():
            missing.append("scope.md")
    if not inventory_path.exists():
        missing.append(rel_or_requested(root, inventory_path, requested_inventory))
    if rows and not phase1_report and not mature_project:
        missing.append("reports/drafts/phase1_report.md" if template_v2 else "phase1_report.md")
    return missing


def new_batch_status(expected: int, manifest_exists: bool, pdfs: int, bodies: int, skim_notes: int) -> str:
    if expected <= 0:
        return "empty"
    if skim_notes >= expected:
        return "skim_complete"
    if skim_notes:
        return "skim_started"
    if bodies >= expected:
        return "ready_for_skim"
    if pdfs >= expected:
        return "pdfs_valid"
    if manifest_exists:
        return "manifest_ready"
    return "planned"


def read_candidates(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def accepted_candidate_table_path(root: Path, requested: Path) -> Path:
    registry = read_json(root / "batches" / "accepted_artifacts.json") or {}
    if not isinstance(registry, dict):
        return requested
    for item in registry.get("artifacts", []):
        artifact_type = item.get("artifact_type") or item.get("type")
        if artifact_type != "candidate_table" or not is_active_artifact(item):
            continue
        rel = item.get("path", "")
        if not rel:
            continue
        path = root / rel
        if path.exists():
            return path
    return requested


def accepted_skim_overview_path(root: Path, requested: Path) -> Path:
    registry = read_json(root / "batches" / "accepted_artifacts.json") or {}
    if not isinstance(registry, dict):
        return requested
    for item in registry.get("artifacts", []):
        artifact_type = item.get("artifact_type") or item.get("type")
        rel = item.get("path", "")
        if artifact_type != "overview" or not is_active_artifact(item) or not rel:
            continue
        if "phase1_report" in rel.lower():
            continue
        path = root / rel
        if path.exists():
            return path
    return requested


def accepted_candidate_batch(root: Path, candidates_path: Path) -> str:
    registry = read_json(root / "batches" / "accepted_artifacts.json") or {}
    if not isinstance(registry, dict):
        return ""
    rel_target = candidates_path.relative_to(root).as_posix() if candidates_path.is_relative_to(root) else candidates_path.as_posix()
    for item in registry.get("artifacts", []):
        artifact_type = item.get("artifact_type") or item.get("type")
        if artifact_type == "candidate_table" and is_active_artifact(item) and item.get("path") == rel_target:
            return batch_code(item.get("batch", ""))
    return ""


def accepted_deep_note_path(root: Path, requested: Path, batch: str = "") -> Path:
    registry = read_json(root / "batches" / "accepted_artifacts.json") or {}
    if not isinstance(registry, dict):
        return requested
    candidates = []
    for item in registry.get("artifacts", []):
        artifact_type = item.get("artifact_type") or item.get("type")
        label = str(item.get("artifact_label", ""))
        if not is_active_artifact(item):
            continue
        if artifact_type not in {"phase3_deep_note", "note"}:
            continue
        if batch and batch_code(item.get("batch", "")) != batch:
            continue
        if artifact_type != "phase3_deep_note" and "phase3" not in label.lower() and "deep" not in str(item.get("path", "")).lower():
            continue
        rel = item.get("path", "")
        if rel:
            path = root / rel
            if path.exists():
                candidates.append(path)
    return candidates[-1] if candidates else requested


def accepted_failure_ids(root: Path, stage: str) -> set[str]:
    data = read_json(root / "accepted_failures.json") or {}
    return {normalized_paper_id(str(item)) for item in data.get(stage, [])} if isinstance(data.get(stage, []), list) else set()


def phase3_summary(root: Path, candidates_path: Path, deep_manifest_path: Path, deep_notes_path: Path, phase2_complete: bool) -> dict:
    candidates = read_candidates(candidates_path)
    undecided = [
        row
        for row in candidates
        if (row.get("selected_for_phase3") or "").strip().lower()
        and (row.get("selected_for_phase3") or "").strip().lower() not in {"yes", "no"}
    ]
    selected = [row for row in candidates if (row.get("selected_for_phase3") or "").strip().lower() == "yes"]
    deep_manifest = read_json(deep_manifest_path) or []
    ready_ids = {
        normalized_row_arxiv_id(row)
        for row in deep_manifest
        if row.get("status") in {"exists", "extracted"}
        and row.get("deep_text_path")
        and Path(row.get("deep_text_path", "")).exists()
        and Path(row.get("deep_text_path", "")).stat().st_size > 1000
    }
    selected_ids = {normalized_row_arxiv_id(row) for row in selected}
    accepted_ids = accepted_failure_ids(root, "phase3_deep_text") & selected_ids
    required_ids = selected_ids - accepted_ids
    deep_note_ids = note_paper_ids(deep_notes_path)
    required_notes_complete = bool(required_ids) and required_ids.issubset(deep_note_ids)
    accepted_failures_only = bool(selected_ids) and not required_ids and bool(accepted_ids)
    can_continue_final_with_warnings = bool(accepted_ids) and required_ids.issubset(deep_note_ids)
    warnings = []
    if accepted_ids:
        warnings.append(
            "Accepted Phase 3 deep-text failures are tracked separately and are not counted as completed deep notes."
        )
    if not phase2_complete and candidates_path.exists():
        warnings.append(
            "Global Phase 2 is not complete; Phase 3 readiness is based on the accepted selected candidate table."
        )

    if not candidates_path.exists():
        status = "not_ready"
    elif not candidates:
        status = "skipped"
    elif undecided:
        status = "awaiting_selection_review"
    elif not selected:
        status = "skipped"
    elif not required_ids.issubset(ready_ids):
        status = "selected_pending"
    elif accepted_failures_only:
        status = "accepted_failures_only"
    elif required_notes_complete and accepted_ids:
        status = "deep_notes_complete_with_accepted_failures"
    elif required_notes_complete:
        status = "deep_notes_complete"
    else:
        status = "deep_text_ready"
    return {
        "status": status,
        "candidates_path": str(candidates_path) if candidates_path.exists() else "",
        "candidate_entries": len(candidates),
        "undecided_entries": len(undecided),
        "selected_entries": len(selected),
        "accepted_failure_entries": len(accepted_ids),
        "accepted_failure_ids": sorted(accepted_ids),
        "warnings": warnings,
        "deep_manifest_path": str(deep_manifest_path) if deep_manifest_path.exists() else "",
        "deep_texts_ready": len(ready_ids & selected_ids),
        "deep_notes_path": str(deep_notes_path) if deep_notes_path.exists() else "",
        "deep_notes_complete": len(deep_note_ids & selected_ids),
        "deep_started": bool(selected_ids or accepted_ids or deep_note_ids or deep_manifest),
        "deep_complete": bool(selected_ids) and not accepted_ids and selected_ids.issubset(deep_note_ids),
        "can_continue_final_with_warnings": can_continue_final_with_warnings,
    }


def choose_next_action(rows: list[dict], batches: dict[str, dict], phase1_report: bool, mature_project: bool, workflow_mode: str, overview_exists: bool, candidates_exists: bool, phase3: dict, final_ready: bool, template_v2: bool = False, phase1_accepted: bool = False) -> str:
    if not rows:
        return "run phase1"
    if any(not batch_code(row.get("reading_batch", "")) for row in rows):
        return "plan reading batches"
    if template_v2 and phase1_report and not phase1_accepted:
        return "accept_phase1"
    if not phase1_report and not mature_project:
        return "write phase1 report"
    for code in sorted(batches, key=batch_sort_key):
        status = batches[code]["status"]
        if status in {"planned", "manifest_ready", "pdfs_valid"}:
            return f"prepare {code}" if template_v2 else f"process {code}"
        if status == "ready_for_reading":
            return f"write notes for {code}"
        if status in {"ready_for_skim", "skim_started"}:
            return f"write skim notes for {code}"
    if not overview_exists or not candidates_exists:
        return "write phase2 skim overview"
    if phase3["status"] == "awaiting_selection_review":
        return "review invalid phase3 selections"
    if phase3["status"] == "selected_pending":
        return "prepare phase3 deep reading"
    if phase3["status"] == "deep_text_ready":
        return "write deep notes for selected papers"
    if phase3["status"] in {"accepted_failures_only", "deep_notes_complete_with_accepted_failures"}:
        return "review phase3 failures or continue final with warnings"
    return "complete" if final_ready else "write final synthesis"


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect an arXiv literature workflow project.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--inventory", default="phase1_inventory.csv")
    parser.add_argument("--phase2-root", default="phase2_papers")
    parser.add_argument("--skim-notes", default="phase2_skim_notes.md")
    parser.add_argument("--skim-overview", default="phase2_skim_overview.md")
    parser.add_argument("--candidates", default="phase2_deep_reading_candidates.csv")
    parser.add_argument("--deep-notes", default="phase3_deep_notes.md")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    template_v2 = is_template_v2(root)
    inventory_path = resolve_inventory(root, args.inventory)
    phase2_root = root / args.phase2_root
    skim_notes_path = root / args.skim_notes
    overview_path = root / args.skim_overview
    candidates_path = root / args.candidates
    if template_v2:
        overview_path = accepted_skim_overview_path(root, overview_path)
        candidates_path = accepted_candidate_table_path(root, candidates_path)
    phase3_batch = accepted_candidate_batch(root, candidates_path) if template_v2 else ""
    deep_notes_path = root / args.deep_notes
    if template_v2:
        deep_notes_path = accepted_deep_note_path(root, deep_notes_path, phase3_batch)
    rows = read_inventory(inventory_path)
    inventory_batch_by_id = {}
    for row in rows:
        code = batch_code(row.get("reading_batch", ""))
        paper_id = normalized_paper_id(row.get("paper_id") or row.get("arxiv_id") or "")
        if paper_id:
            inventory_batch_by_id[paper_id] = code
        arxiv_id = normalized_arxiv_id(row.get("arxiv_id", ""))
        if arxiv_id:
            inventory_batch_by_id[arxiv_id] = code
    skim_ids_by_batch = note_ids_by_batch(skim_notes_path, inventory_batch_by_id)
    registry_skim_ids = registry_skim_ids_by_batch(root)
    for code, ids in registry_skim_ids.items():
        skim_ids_by_batch.setdefault(code, set()).update(ids)
    deep_ids_by_batch = note_ids_by_batch(deep_notes_path, inventory_batch_by_id)
    skim_counts = {code: len(ids) for code, ids in skim_ids_by_batch.items()}
    has_new_files = any(has_substantive_content(path) for path in [skim_notes_path, overview_path, candidates_path, deep_notes_path])
    workflow_mode = "three_stage"

    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        code = batch_code(row.get("reading_batch", ""))
        if code:
            grouped[code].append(row)

    batches = {}
    for code, batch_rows in sorted(grouped.items(), key=lambda item: batch_sort_key(item[0])):
        manifest_path = phase2_root / f"{code}_manifest.json"
        body_manifest_path = phase2_root / f"{code}_body_text_manifest.json"
        manifest_data = read_json(manifest_path) or []
        body_manifest_data = read_json(body_manifest_path) or []
        manifest = manifest_data.get("papers", []) if isinstance(manifest_data, dict) else manifest_data
        body_manifest = body_manifest_data.get("bodies", []) if isinstance(body_manifest_data, dict) else body_manifest_data
        normalized_manifest = normalize_manifest_rows(phase2_root, batch_rows, manifest, body_manifest)
        pdfs = count_valid_pdfs(normalized_manifest)
        bodies = count_body_texts(normalized_manifest)
        skim_ids = skim_ids_by_batch.get(code, set())
        deep_ids = deep_ids_by_batch.get(code, set())
        batch_mode = "three_stage"
        effective_ids = deep_ids | skim_ids
        notes = len(skim_ids)
        expected = len(batch_rows)
        status = new_batch_status(expected, manifest_path.exists(), pdfs, bodies, notes)
        batches[code] = {
            "papers": expected,
            "manifest": manifest_path.exists(),
            "manifest_path": str(manifest_path) if manifest_path.exists() else "",
            "body_manifest": body_manifest_path.exists(),
            "pdfs": pdfs,
            "body_texts": bodies,
            "notes_entries": notes,
            "effective_notes_entries": len(effective_ids),
            "skim_notes_entries": skim_counts.get(code, 0),
            "deep_notes_entries": len(deep_ids),
            "workflow_mode": batch_mode,
            "status": status,
        }

    report_path = phase1_report_path(root)
    phase1_report = report_path.exists()
    phase1_accepted = accepted_phase1_report(root)
    mature_project = bool(
        any(item["manifest"] or item["pdfs"] or item["body_texts"] or item["effective_notes_entries"] for item in batches.values())
        or overview_path.exists()
        or candidates_path.exists()
        or deep_notes_path.exists()
    )
    phase2_complete = bool(batches) and all(item["status"] in {"skim_complete", "notes_complete"} for item in batches.values())
    batch_deep_manifest = phase2_root / f"{phase3_batch}_deep_text_manifest.json" if phase3_batch else phase2_root / "phase3_deep_text_manifest.json"
    deep_manifest_path = batch_deep_manifest if batch_deep_manifest.exists() else phase2_root / "phase3_deep_text_manifest.json"
    phase3 = phase3_summary(root, candidates_path, deep_manifest_path, deep_notes_path, phase2_complete)
    final_files = ["final_literature_map.md", "key_papers.md", "research_opportunities.md", "open_questions.md"]
    final_ready = all((root / name).exists() and (root / name).stat().st_size > 50 for name in final_files)
    final_started = any(has_substantive_content(root / name) for name in final_files)
    phase2_started = (
        directory_has_files(root / "raw_papers")
        or directory_has_files(phase2_root)
        or has_substantive_content(skim_notes_path)
    )
    skim_started = bool(any(skim_counts.values()) or has_substantive_content(skim_notes_path))
    three_stage_batches = [item for item in batches.values() if item["workflow_mode"] == "three_stage"]
    skim_complete = bool(three_stage_batches) and all(item["status"] == "skim_complete" for item in three_stage_batches)
    not_started_optional = []
    if not phase2_started:
        not_started_optional.extend([args.skim_notes, args.phase2_root, "raw_papers"])
    if phase3["status"] in {"not_ready", "skipped"}:
        not_started_optional.extend([args.deep_notes, str(deep_manifest_path.relative_to(root))])
    if not final_started:
        not_started_optional.extend(final_files)

    state = {
        "root": str(root),
        "layout": "template-v2" if template_v2 else "current-incomplete",
        "workflow_mode": workflow_mode,
        "phase1": {
            "inventory_exists": inventory_path.exists(),
            "inventory_path": str(inventory_path) if inventory_path.exists() else "",
            "papers": len(rows),
            "batches_assigned": bool(rows) and all(batch_code(row.get("reading_batch", "")) for row in rows),
            "phase1_report_exists": phase1_report,
            "phase1_report_path": str(report_path) if report_path.exists() else "",
            "phase1_accepted": phase1_accepted,
            "missing_project_files": missing_project_files(root, inventory_path, args.inventory, rows, phase1_report, mature_project),
            "warnings": ["Phase 1 report is missing in a mature project; continue without forcing historical reconstruction."] if rows and not phase1_report and mature_project else [],
            "not_started_optional_files": not_started_optional,
        },
        "counts": {
            "sections": dict(Counter(row.get("section", "") or "<missing>" for row in rows)),
            "method_categories": dict(Counter(row.get("method_category", "") or "<missing>" for row in rows)),
            "reading_priorities": dict(Counter(row.get("reading_priority", "") or "<missing>" for row in rows)),
            "classification_confidence": dict(Counter(row.get("classification_confidence", "") or "<missing>" for row in rows)),
            "batches": {code: len(items) for code, items in grouped.items()},
        },
        "batches": batches,
        "phase2": {
            "started": phase2_started,
            "complete": phase2_complete,
            "skim_started": skim_started,
            "skim_complete": skim_complete,
            "skim_notes_path": str(skim_notes_path) if skim_notes_path.exists() else "",
            "skim_overview_path": str(overview_path) if overview_path.exists() else "",
            "missing_files": [],
        },
        "phase3": phase3,
        "final_synthesis": {
            "ready": final_ready,
            "files": {name: (root / name).exists() for name in final_files},
            "started": final_started,
            "missing_files": [name for name in final_files if not (root / name).exists()] if final_started else [],
        },
        "next_action": choose_next_action(
            rows,
            batches,
            phase1_report,
            mature_project,
            workflow_mode,
            overview_path.exists(),
            candidates_path.exists(),
            phase3,
            final_ready,
            template_v2,
            phase1_accepted,
        ),
    }
    print(json.dumps(state, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
