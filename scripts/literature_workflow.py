import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from workflow_safety import atomic_write_json
from registry_utils import is_active_artifact
from awesome_literature_harness import (
    accept_draft as v2_accept_draft,
    accept_phase1 as v2_accept_phase1,
    build_missing_pdf_report as v2_build_missing_pdf_report,
    check_phase3_selection as v2_check_phase3_selection,
    import_local_pdfs as v2_import_local_pdfs,
    init_from_awesome as v2_init_from_awesome,
    prepare_batch as v2_prepare_batch,
    run_next_microbatch as v2_run_next_microbatch,
    validate_project as v2_validate_project,
)


SCRIPT_DIR = Path(__file__).resolve().parent
SCHEMA_DIR = SCRIPT_DIR.parent / "schemas"
CONTRACTS = {
    "workflow_state": {
        "path": SCHEMA_DIR / "workflow_state.schema.json",
        "purpose": "Advisory contract for project workflow state and future persistent state files.",
    },
    "inventory_row": {
        "path": SCHEMA_DIR / "inventory.schema.json",
        "purpose": "Advisory row-level contract for phase1 inventory CSV data.",
    },
    "paper_note": {
        "path": SCHEMA_DIR / "paper_note.schema.json",
        "purpose": "Advisory contract for future paper_notes/*.json structured notes.",
    },
    "skim_note": {
        "path": SCHEMA_DIR / "skim_note.schema.json",
        "purpose": "Advisory contract for Phase 2 skim-note derived JSON.",
    },
    "deep_reading_candidate": {
        "path": SCHEMA_DIR / "deep_reading_candidate.schema.json",
        "purpose": "Advisory row-level contract for reading-priority candidate table data.",
    },
    "runner_summary": {
        "path": SCHEMA_DIR / "runner_summary.schema.json",
        "purpose": "Advisory contract for this runner's JSON summary output.",
    },
    "accepted_artifacts": {
        "path": SCHEMA_DIR / "accepted_artifacts.schema.json",
        "purpose": "Advisory contract for batches/accepted_artifacts.json accepted-output registries.",
    },
    "evidence_packet_manifest": {
        "path": SCHEMA_DIR / "evidence_packet_manifest.schema.json",
        "purpose": "Advisory contract for Phase 2 packet-only evidence packet manifests.",
    },
}


def run(command: list[str], cwd: Path) -> dict:
    completed = subprocess.run(command, cwd=str(cwd), text=True, capture_output=True)
    item = {
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }
    if completed.returncode != 0:
        raise RuntimeError(json.dumps(item, ensure_ascii=False, indent=2))
    return item


def inventory_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def empty_or_header_only(path: Path) -> bool:
    if not path.exists():
        return True
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    return not text or len(text.splitlines()) <= 1


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
    if preferred:
        return preferred[0]
    return path


def resolve_candidates(root: Path, requested: str, batch: str = "", explicit: bool = False) -> Path:
    requested_path = Path(requested)
    fallback = requested_path if requested_path.is_absolute() else root / requested_path
    if explicit:
        return fallback
    registry_path = root / "batches" / "accepted_artifacts.json"
    matches = []
    if registry_path.exists():
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        if isinstance(registry, dict):
            for item in registry.get("artifacts", []):
                artifact_type = item.get("artifact_type") or item.get("type")
                if artifact_type != "candidate_table" or not is_active_artifact(item):
                    continue
                if batch and item.get("batch") != batch:
                    continue
                rel = item.get("path", "")
                if not rel:
                    continue
                path = root / rel
                if path.exists():
                    matches.append(path)
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        scope = f" for batch {batch}" if batch else ""
        choices = ", ".join(path.relative_to(root).as_posix() for path in matches)
        raise ValueError(f"ambiguous active candidate tables{scope}: {choices}; pass --candidates explicitly" if not batch else f"ambiguous active candidate tables{scope}: {choices}")
    return fallback


def is_template_v2(root: Path) -> bool:
    return (root / "inventory" / "workflow_inventory.csv").exists() and (root / "batches" / "accepted_artifacts.json").exists()


def default_inventory_for(root: Path, requested: str) -> str:
    if requested != "phase1_inventory.csv":
        return requested
    if is_template_v2(root):
        return "inventory/workflow_inventory.csv"
    return requested


def default_phase1_report_for(root: Path) -> Path:
    if is_template_v2(root):
        return root / "reports" / "drafts" / "phase1_report.md"
    return root / "phase1_report.md"


def script(name: str) -> str:
    return str(SCRIPT_DIR / name)


def node_script(name: str) -> str:
    return str(SCRIPT_DIR / name)


def resolve_node_command(args) -> dict:
    if getattr(args, "node_command", None):
        return {"command": args.node_command, "source": "cli"}
    if getattr(args, "node", None):
        return {"command": args.node, "source": "cli-alias"}
    env_node = os.environ.get("LITFLOW_NODE")
    if env_node:
        return {"command": env_node, "source": "env"}
    path_node = shutil.which("node")
    if path_node:
        return {"command": path_node, "source": "path"}
    return {"command": None, "source": "none"}


def run_version_command(command: str) -> tuple[bool, str, str]:
    try:
        completed = subprocess.run([command, "--version"], text=True, capture_output=True, timeout=15)
    except Exception as exc:  # noqa: BLE001
        return False, "", str(exc)
    return completed.returncode == 0, completed.stdout.strip(), completed.stderr.strip()


def check_node_runtime(args) -> dict:
    resolved = resolve_node_command(args)
    command = resolved["command"]
    warnings = []
    errors = []
    node_version = ""
    executable = False

    if command:
        executable, stdout, stderr = run_version_command(command)
        node_version = stdout
        if not executable:
            errors.append(
                "Resolved Node command could not execute `node --version`: "
                f"{stderr or stdout or 'no output'}"
            )
            if "WindowsApps" in str(command) or "OpenAI.Codex" in str(command):
                warnings.append("WindowsApps or Codex App packaged Node may be inaccessible from this shell.")
    else:
        errors.append("No Node runtime was found from --node-command, LITFLOW_NODE, or PATH.")

    npm_path = shutil.which("npm")
    npm_version = ""
    npm_found = bool(npm_path)
    if npm_path:
        npm_ok, npm_stdout, npm_stderr = run_version_command(npm_path)
        npm_version = npm_stdout if npm_ok else ""
        if not npm_ok:
            warnings.append(f"npm was found but could not execute: {npm_stderr or npm_stdout or 'no output'}")
    else:
        warnings.append("npm was not found in PATH; this is not blocking because downloader scripts use only Node built-ins.")

    if errors:
        warnings.extend(
            [
                "Install official Node.js 18+ or provide an explicit runtime with --node-command.",
                "Alternatively set LITFLOW_NODE to a known executable node.exe path.",
                "npm is optional for the current downloader scripts.",
            ]
        )

    return {
        "resolved_node_command": command,
        "resolution_source": resolved["source"],
        "node_version": node_version,
        "node_executable": executable,
        "npm_found": npm_found,
        "npm_version": npm_version,
        "downloader_scripts_found": {
            "ensure_raw_papers_node.mjs": (SCRIPT_DIR / "ensure_raw_papers_node.mjs").exists(),
            "download_batch_node.mjs": (SCRIPT_DIR / "download_batch_node.mjs").exists(),
        },
        "warnings": warnings,
        "errors": errors,
        "next_action": (
            "Node runtime is usable for downloader diagnostics."
            if executable
            else "Install Node.js 18+ or rerun with --node-command / LITFLOW_NODE pointing to an executable Node runtime."
        ),
    }


def require_node_command(args) -> str:
    diagnostics = check_node_runtime(args)
    if not diagnostics["node_executable"]:
        raise RuntimeError(json.dumps(diagnostics, ensure_ascii=False, indent=2))
    return diagnostics["resolved_node_command"]


def contracts_summary() -> dict:
    return {
        name: {
            "path": str(item["path"]),
            "exists": item["path"].exists(),
            "purpose": item["purpose"],
        }
        for name, item in CONTRACTS.items()
    }


def lightweight_validate_summary(summary: dict) -> list[str]:
    warnings = []
    required = {
        "action": str,
        "root": str,
        "steps": list,
        "planned_steps": list,
        "warnings": list,
        "errors": list,
        "next_action": (str, type(None)),
        "network_required": bool,
        "write_operations": list,
    }
    for field, expected in required.items():
        if field not in summary:
            warnings.append(f"runner_summary missing required field: {field}")
        elif not isinstance(summary[field], expected):
            warnings.append(f"runner_summary field has unexpected type: {field}")
    for field in ["initial_state", "final_state"]:
        if field in summary and summary[field] is not None and not isinstance(summary[field], dict):
            warnings.append(f"runner_summary field should be object or null: {field}")
    return warnings


def validate_contracts(summary: dict) -> list[str]:
    warnings = []
    schema_path = CONTRACTS["runner_summary"]["path"]
    if not schema_path.exists():
        warnings.append(f"runner_summary schema not found: {schema_path}")
        return warnings + lightweight_validate_summary(summary)

    try:
        import jsonschema  # type: ignore
    except Exception:
        warnings.append("jsonschema is not installed; used lightweight contract validation only.")
        return warnings + lightweight_validate_summary(summary)

    try:
        schema_data = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.validate(instance=summary, schema=schema_data)
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"runner_summary schema validation warning: {exc}")
    return warnings


def validate_workflow_state_contract(state: dict | None) -> list[str]:
    if state is None:
        return []
    warnings = []
    schema_path = CONTRACTS["workflow_state"]["path"]
    if not schema_path.exists():
        return [f"workflow_state schema not found: {schema_path}"]
    try:
        import jsonschema  # type: ignore
    except Exception:
        if not isinstance(state.get("root", ""), str):
            warnings.append("workflow_state root should be a string")
        if "counts" in state and not isinstance(state["counts"], dict):
            warnings.append("workflow_state counts should be an object")
        if "batch_status" in state and not isinstance(state["batch_status"], dict):
            warnings.append("workflow_state batch_status should be an object")
        return warnings
    try:
        schema_data = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.validate(instance=state, schema=schema_data)
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"workflow_state schema validation warning: {exc}")
    return warnings


def run_phase1(args) -> list[dict]:
    root = Path(args.root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    steps = []
    steps.append(run([args.python, script("scaffold_literature_project.py"), "--root", str(root), "--phase1-only", "--allow-write"], root))

    inventory = root / args.inventory
    if inventory.exists() and not empty_or_header_only(inventory) and not args.overwrite:
        raise FileExistsError(f"{inventory} already has rows; pass --overwrite to rebuild Phase 1")
    if not args.source:
        raise ValueError("--source is required for --phase phase1")

    build_cmd = [
        args.python,
        script("build_phase1_inventory.py"),
        "--source",
        args.source,
        "--output",
        str(inventory),
        "--overwrite",
        "--allow-write",
    ]
    if args.fetch_metadata:
        build_cmd.append("--fetch-metadata")
    if args.fetch_metadata or is_url(args.source):
        build_cmd.append("--allow-network")
    if args.source_url:
        build_cmd.extend(["--source-url", args.source_url])
    steps.append(run(build_cmd, root))

    classify_cmd = [
        args.python,
        script("classify_inventory.py"),
        "--inventory",
        str(inventory),
        "--overwrite",
        "--allow-write",
    ]
    if args.rules:
        classify_cmd.extend(["--rules", args.rules])
    if args.overwrite_labels:
        classify_cmd.append("--overwrite-labels")
    steps.append(run(classify_cmd, root))

    steps.append(
        run(
            [
                args.python,
                script("plan_reading_batches.py"),
                "--inventory",
                str(inventory),
                "--overwrite",
                "--allow-write",
            ],
            root,
        )
    )
    steps.append(run([args.python, script("check_inventory_quality.py"), "--inventory", str(inventory)], root))
    steps.append(
        run(
            [
                args.python,
                script("write_phase1_report.py"),
                "--inventory",
                str(inventory),
                "--output",
                str(root / "phase1_report.md"),
                "--overwrite",
                "--allow-write",
                *(["--metadata-unverified"] if not args.fetch_metadata else []),
            ],
            root,
        )
    )
    return steps


def batch_code(value: str) -> str:
    return value.split()[0]


def normalized_arxiv_id(value: str) -> str:
    return re.sub(r"v\d+$", "", value or "", flags=re.IGNORECASE)


def normalized_paper_id(value: str) -> str:
    match = re.search(r"(?i)(?:arxiv:)?(\d{4}\.\d{4,5})(?:v\d+)?", value or "")
    return f"arxiv:{match.group(1)}" if match else (value or "").strip().lower()


def safe_path_name(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9 -]", "", value or "")
    return value.replace(" ", "_")


def derived_pdf_path(phase2_root: Path, row: dict) -> Path:
    section = re.sub(r"[^A-Za-z0-9-]", "_", row.get("section", ""))
    return phase2_root / section / safe_path_name(row.get("method_category", "")) / f"{row.get('arxiv_id', '')}.pdf"


def read_accepted_failures(root: Path) -> dict[str, set[str]]:
    path = root / "accepted_failures.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        key: {normalized_arxiv_id(str(item)) for item in values}
        for key, values in data.items()
        if isinstance(values, list)
    }


def batch_inventory_rows(root: Path, inventory_name: str, batch: str) -> list[dict]:
    return [row for row in inventory_rows(resolve_inventory(root, inventory_name)) if batch_code(row.get("reading_batch", "")) == batch]


def validate_skim_inputs(root: Path, inventory_name: str, manifest_path: Path, batch: str) -> dict:
    expected_rows = batch_inventory_rows(root, inventory_name, batch)
    manifest_rows = json.loads(manifest_path.read_text(encoding="utf-8"))
    body_manifest_path = manifest_path.with_name(f"{batch}_body_text_manifest.json")
    body_rows = json.loads(body_manifest_path.read_text(encoding="utf-8")) if body_manifest_path.exists() else []
    body_by_id = {normalized_arxiv_id(row.get("arxiv_id", "")): row for row in body_rows}
    inventory_by_id = {normalized_arxiv_id(row.get("arxiv_id", "")): row for row in expected_rows}
    expected_ids = {normalized_arxiv_id(row.get("arxiv_id", "")) for row in expected_rows}
    manifest_ids = {normalized_arxiv_id(row.get("arxiv_id", "")) for row in manifest_rows}
    accepted = read_accepted_failures(root).get("phase2_body_text", set())
    missing_body = []
    for row in manifest_rows:
        arxiv_id = normalized_arxiv_id(row.get("arxiv_id", ""))
        body_row = body_by_id.get(arxiv_id, {})
        pdf_path = Path(body_row.get("pdf_path") or row.get("pdf_path") or derived_pdf_path(manifest_path.parent, inventory_by_id.get(arxiv_id, row)))
        body_path = Path(body_row.get("body_text_path") or row.get("body_text_path") or pdf_path.with_suffix(".body.txt"))
        if arxiv_id not in accepted and (not body_path.exists() or body_path.stat().st_size <= 1000):
            missing_body.append(arxiv_id or "<missing arxiv_id>")
    errors = []
    if len(manifest_rows) != len(expected_rows) or manifest_ids != expected_ids:
        errors.append(
            "manifest rows do not match inventory batch: "
            f"expected={sorted(expected_ids)}, manifest={sorted(manifest_ids)}"
        )
    if missing_body:
        errors.append("missing valid .body.txt for: " + ", ".join(sorted(missing_body)))
    return {"errors": errors, "accepted_failures": sorted(accepted & manifest_ids)}


def run_batch(args) -> list[dict]:
    root = Path(args.root).resolve()
    phase2_root = root / args.phase2_root
    inventory = resolve_inventory(root, args.inventory)
    batch = args.batch
    manifest = phase2_root / f"{batch}_manifest.json"
    node_command = require_node_command(args)
    steps = []

    if not manifest.exists() or args.overwrite:
        steps.append(
            run(
                [
                    args.python,
                    script("prepare_batch_manifest_extract.py"),
                    "--batch",
                    batch,
                    "--inventory",
                    str(inventory),
                    "--root",
                    str(phase2_root),
                    "--mode",
                    "manifest",
                    "--allow-write",
                ],
                root,
            )
        )

    ensure_cmd = [
        node_command,
        node_script("ensure_raw_papers_node.mjs"),
        "--manifest",
        str(manifest),
        "--raw-dir",
        str(root / "raw_papers"),
        "--quiet",
    ]
    if args.download:
        ensure_cmd.extend(["--download", "--allow-network", "--allow-write"])
    else:
        ensure_cmd.extend(["--dry-run", "--allow-write"])
    steps.append(run(ensure_cmd, root))

    steps.append(
        run(
            [
                args.python,
                script("import_local_pdfs.py"),
                "--manifest",
                str(manifest),
                "--source",
                str(root / "raw_papers"),
                "--copy",
                "--allow-write",
            ],
            root,
        )
    )

    validate = run(
        [
            node_command,
            node_script("download_batch_node.mjs"),
            "--manifest",
            str(manifest),
            "--validate-only",
            "--quiet",
            "--allow-write",
        ],
        root,
    )
    steps.append(validate)
    try:
        validate_summary = json.loads(validate["stdout"])
    except json.JSONDecodeError:
        validate_summary = {}

    if validate_summary.get("failed", 1) == 0:
        steps.append(
            run(
                [
                    args.python,
                    script("prepare_batch_manifest_extract.py"),
                    "--batch",
                    batch,
                    "--inventory",
                    str(inventory),
                    "--root",
                    str(phase2_root),
                    "--mode",
                    "extract",
                    "--allow-write",
                ],
                root,
            )
        )
    return steps


def active_artifact_registered(root: Path, artifact_type: str, rel_path: str, batch: str) -> bool:
    registry = root / "batches" / "accepted_artifacts.json"
    if not registry.exists():
        return False
    data = json.loads(registry.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return False
    for item in data.get("artifacts", []):
        if not is_active_artifact(item):
            continue
        kind = item.get("artifact_type") or item.get("type")
        if kind == artifact_type and item.get("path") == rel_path and item.get("batch") == batch:
            return True
    return False


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def active_artifact_hash(root: Path, artifact_type: str, rel_path: str, batch: str) -> str:
    registry = root / "batches" / "accepted_artifacts.json"
    if not registry.exists():
        return ""
    data = json.loads(registry.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return ""
    for item in reversed(data.get("artifacts", [])):
        kind = item.get("artifact_type") or item.get("type")
        if is_active_artifact(item) and kind == artifact_type and item.get("path") == rel_path and item.get("batch") == batch:
            return item.get("content_hash", "")
    return ""


def register_v2_artifact(args, artifact_type: str, rel_path: str, batch: str) -> dict:
    root = Path(args.root).resolve()
    path = root / rel_path
    old_hash = active_artifact_hash(root, artifact_type, rel_path, batch)
    if old_hash and path.exists() and old_hash == file_sha256(path):
        return {
            "command": ["register-artifact", artifact_type, rel_path],
            "returncode": 0,
            "stdout": json.dumps({"registered": False, "already_registered": True, "path": rel_path}, ensure_ascii=False),
            "stderr": "",
        }
    command = [
            args.python,
            script("literature_harness.py"),
            "--root",
            str(root),
            "--action",
            "register-artifact",
            "--artifact-type",
            artifact_type,
            "--artifact-path",
            rel_path,
            "--batch",
            batch,
            "--review-status",
            "accepted",
    ]
    if old_hash:
        command.extend(["--supersedes", rel_path])
    command.append("--allow-write")
    return run(
        command,
        root,
    )


def phase2_overview_paths(args) -> tuple[Path, Path, Path, bool]:
    root = Path(args.root).resolve()
    template_v2 = is_template_v2(root)
    if not template_v2:
        return root / args.skim_notes, root / args.skim_overview, root / args.candidates, False
    if not args.batch and (args.skim_overview == "phase2_skim_overview.md" or args.candidates == "phase2_deep_reading_candidates.csv"):
        raise ValueError("template-v2 phase2-overview requires --batch unless explicit v2 output paths are provided")
    notes = root / args.skim_notes
    overview = root / args.skim_overview
    candidates = root / args.candidates
    if args.batch:
        accepted = accepted_batch_skim_note_path(root, args.batch)
        if args.skim_notes == "phase2_skim_notes.md":
            if not accepted:
                raise FileNotFoundError(f"accepted batch skim note not found for {args.batch}")
            notes = accepted
        if args.skim_overview == "phase2_skim_overview.md":
            overview = root / "reports" / "accepted_overviews" / f"{args.batch}_skim_overview.md"
        if args.candidates == "phase2_deep_reading_candidates.csv":
            candidates = root / "candidates" / "accepted" / f"{args.batch}_deep_reading_candidates.csv"
    return notes, overview, candidates, True


def run_phase2_overview(args) -> list[dict]:
    root = Path(args.root).resolve()
    notes, overview, candidates, template_v2 = phase2_overview_paths(args)
    steps = []
    if not template_v2:
        steps.append(
            run(
                [
                    args.python,
                    script("parse_reading_notes.py"),
                    "--notes",
                    str(notes),
                ],
                root,
            )
        )
    steps.append(
        run(
            [
                args.python,
                script("write_skim_overview.py"),
                "--notes",
                str(notes),
                "--output",
                str(overview),
                "--candidates",
                str(candidates),
                "--allow-write",
            ],
            root,
        )
    )
    if template_v2 and args.batch:
        steps.append(register_v2_artifact(args, "overview", overview.relative_to(root).as_posix(), args.batch))
        steps.append(register_v2_artifact(args, "candidate_table", candidates.relative_to(root).as_posix(), args.batch))
    return steps


def maybe_generate_v2_overview_after_accept(args, accept_result: dict) -> dict:
    root = Path(args.root).resolve()
    if not is_template_v2(root) or not args.batch:
        return {"status": "skipped", "reason": "not_template_v2_batch"}
    if accept_result.get("status") not in {"accepted", "already_accepted", "replaced"}:
        return {"status": "skipped", "reason": "draft_not_accepted"}
    packet_manifest = root / args.phase2_root / f"{args.batch}_packet_manifest.json"
    if not packet_manifest.exists():
        return {"status": "blocked", "reason": "packet_manifest_missing", "packet_manifest": str(packet_manifest.relative_to(root))}
    gate_step = run(
        [
            args.python,
            script("literature_harness.py"),
            "--root",
            str(root),
            "--action",
            "check-overview-gate",
            "--batch",
            args.batch,
            "--packet-manifest",
            str(packet_manifest.relative_to(root)),
        ],
        root,
    )
    gate = json.loads(gate_step.get("stdout") or "{}")
    if not gate.get("ready_for_overview"):
        return {"status": "blocked", "reason": "overview_gate_not_ready", "gate": gate, "gate_step": gate_step}
    overview_args = argparse.Namespace(**vars(args))
    overview_args.action = "phase2-overview"
    steps = run_phase2_overview(overview_args)
    _notes, overview, candidates, _template_v2 = phase2_overview_paths(overview_args)
    return {
        "status": "generated",
        "overview": overview.relative_to(root).as_posix(),
        "candidates": candidates.relative_to(root).as_posix(),
        "gate": gate,
        "gate_step": gate_step,
        "steps": steps,
    }


def run_phase3_deep(args) -> list[dict]:
    root = Path(args.root).resolve()
    candidates = resolve_candidates(root, args.candidates, batch=args.batch or "", explicit=getattr(args, "candidates_explicit", False))
    if not candidates.exists():
        raise FileNotFoundError(f"candidate CSV not found: {candidates}; run --action phase2-overview first")
    with candidates.open("r", encoding="utf-8-sig", newline="") as handle:
        selected = [row for row in csv.DictReader(handle) if (row.get("selected_for_phase3") or "").strip().lower() == "yes"]
    if not selected:
        raise ValueError("no candidate rows have selected_for_phase3=yes")
    phase2_root = root / args.phase2_root
    deep_manifest_name = f"{args.batch}_deep_text_manifest.json" if args.batch else "phase3_deep_text_manifest.json"
    deep_stub_name = f"{args.batch}_phase3_deep_note_stubs.md" if args.batch else "phase3_deep_note_stubs.md"
    deep_manifest = phase2_root / deep_manifest_name
    extract_command = [
        args.python,
        script("prepare_batch_manifest_extract.py"),
        "--inventory",
        str(resolve_inventory(root, args.inventory)),
        "--root",
        str(phase2_root),
        "--mode",
        "extract-deep",
        "--candidates",
        str(candidates),
        "--allow-write",
    ]
    if args.batch:
        extract_command.extend(["--batch", args.batch])
    steps = [
        run(extract_command, root)
    ]
    deep_rows = json.loads(deep_manifest.read_text(encoding="utf-8"))
    successful = [
        row
        for row in deep_rows
        if row.get("status") in {"exists", "extracted"}
        and row.get("deep_text_path")
        and Path(row["deep_text_path"]).exists()
        and Path(row["deep_text_path"]).stat().st_size > 1000
    ]
    failed = [
        {
            "paper_id": row.get("paper_id") or (f"arxiv:{row.get('arxiv_id', '')}" if row.get("arxiv_id") else ""),
            "arxiv_id": row.get("arxiv_id", ""),
            "status": row.get("status", ""),
            "error": row.get("error", ""),
        }
        for row in deep_rows
        if row not in successful
    ]
    if not successful:
        raise RuntimeError("selected deep-text extraction produced no usable .deep.txt files: " + json.dumps(failed, ensure_ascii=False))
    command = [
        args.python,
        script("write_batch_note_stubs.py"),
        "--manifest",
        str(deep_manifest),
        "--output",
        str(phase2_root / deep_stub_name),
        "--template",
        "phase3-deep",
        "--candidates",
        str(candidates),
        "--allow-write",
    ]
    if args.overwrite:
        command.append("--overwrite")
    steps.append(run(command, root))
    steps.append(
        {
            "command": ["phase3-deep-summary"],
            "returncode": 0,
            "stdout": json.dumps(
                {
                    "selected": len(selected),
                    "successful": [row.get("paper_id") or row.get("arxiv_id", "") for row in successful],
                    "failed": failed,
                    "pending": [row.get("paper_id") or row.get("arxiv_id", "") for row in deep_rows if row not in successful],
                },
                ensure_ascii=False,
            ),
            "stderr": "",
        }
    )
    return steps


def selected_phase3_ids(candidates: Path) -> list[str]:
    if not candidates.exists():
        return []
    with candidates.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = csv.DictReader(handle)
        return sorted(
            normalized_paper_id(row.get("paper_id") or row.get("arxiv_id", ""))
            for row in rows
            if (row.get("selected_for_phase3") or "").strip().lower() == "yes"
        )


def run_promote_to_deep(args) -> list[dict]:
    if not args.paper_id:
        raise ValueError("--paper-id is required for --action promote-to-deep")
    root = Path(args.root).resolve()
    candidates = resolve_candidates(root, args.candidates, batch=args.batch or "", explicit=getattr(args, "candidates_explicit", False))
    if not candidates.exists():
        raise FileNotFoundError(f"candidate CSV not found: {candidates}; run --action phase2-overview first")
    target = normalized_paper_id(args.paper_id)
    with candidates.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        fieldnames = list(reader.fieldnames or [])
    for required in ["selected_for_phase3", "selection_notes"]:
        if required not in fieldnames:
            fieldnames.append(required)

    matched = []
    for row in rows:
        row_id = normalized_paper_id(row.get("paper_id") or row.get("arxiv_id", ""))
        if row_id == target:
            row["selected_for_phase3"] = "yes"
            existing = (row.get("selection_notes") or "").strip()
            note = "promoted to deep note archival mode"
            row["selection_notes"] = existing if note in existing else "; ".join(item for item in [existing, note] if item)
            matched.append(row)
    if not matched:
        raise ValueError(f"paper_id not found in candidate CSV: {args.paper_id}")

    with tempfile.NamedTemporaryFile("w", encoding="utf-8-sig", newline="", delete=False, dir=candidates.parent, prefix=candidates.name + ".", suffix=".tmp") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        temp_path = Path(handle.name)
    temp_path.replace(candidates)
    return [
        {
            "command": ["promote-to-deep", args.paper_id],
            "returncode": 0,
            "stdout": json.dumps({"candidate_table": str(candidates), "promoted": [target]}, ensure_ascii=False),
            "stderr": "",
        }
    ]


def default_phase3_notes_path(root: Path, batch: str, requested: str) -> Path:
    accepted = root / "notes" / "accepted" / f"{batch}_deep.md"
    if accepted.exists():
        return accepted
    draft = root / "notes" / "drafts" / f"{batch}_deep.md"
    if draft.exists():
        return draft
    return root / requested


def run_check_phase3_notes(args) -> dict:
    root = Path(args.root).resolve()
    if not args.batch:
        raise ValueError("--batch is required for --action check-phase3-notes")
    candidates = resolve_candidates(root, args.candidates, batch=args.batch or "", explicit=getattr(args, "candidates_explicit", False))
    expected_ids = selected_phase3_ids(candidates)
    notes_path = default_phase3_notes_path(root, args.batch, args.deep_notes)
    heading = f"{args.batch} Phase 3 Selected Deep Reading"
    result = run(
        [
            args.python,
            script("check_notes_quality.py"),
            "--notes",
            str(notes_path),
            "--batch-heading",
            heading,
            "--expected",
            str(len(expected_ids)),
            "--expected-ids",
            ",".join(expected_ids),
        ],
        root,
    )
    parsed = {}
    try:
        parsed = json.loads(result.get("stdout") or "{}")
    except json.JSONDecodeError:
        parsed = {"raw_stdout": result.get("stdout", "")}
    return {
        "status": "passed" if result["returncode"] == 0 and parsed.get("count_ok") and parsed.get("ids_ok") and not parsed.get("needs_review") else "failed",
        "notes_path": str(notes_path.relative_to(root)) if notes_path.exists() else str(notes_path),
        "candidate_path": str(candidates.relative_to(root)) if candidates.exists() and candidates.is_relative_to(root) else str(candidates),
        "expected_paper_ids": expected_ids,
        "quality": parsed,
        "command": result["command"],
        "returncode": result["returncode"],
        "stderr": result["stderr"],
        "warnings": [],
        "errors": [] if result["returncode"] == 0 else [result["stderr"] or "check_notes_quality failed"],
    }


def run_accept_phase3(args) -> dict:
    root = Path(args.root).resolve()
    if not args.batch:
        raise ValueError("--batch is required for --action accept-phase3")
    if not args.allow_write:
        raise PermissionError("--action accept-phase3 requires --allow-write")
    source = root / (args.draft or args.deep_notes)
    if not source.exists():
        raise FileNotFoundError(f"Phase 3 note source not found: {source}")
    target = root / "notes" / "accepted" / f"{args.batch}_deep.md"
    if target.exists() and not args.force:
        raise FileExistsError(f"accepted Phase 3 note already exists: {target}; use --force to replace")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    check_args = argparse.Namespace(**vars(args))
    check_args.deep_notes = str(target.relative_to(root))
    check = run_check_phase3_notes(check_args)
    if check["status"] != "passed":
        return {"status": "failed", "accepted_note": str(target.relative_to(root)), "check": check, "warnings": [], "errors": ["Phase 3 note quality gate failed"]}
    register = run(
        [
            args.python,
            script("literature_harness.py"),
            "--root",
            str(root),
            "--action",
            "register-artifact",
            "--artifact-type",
            "phase3_deep_note",
            "--artifact-path",
            str(target.relative_to(root)),
            "--batch",
            args.batch,
            "--artifact-label",
            f"{args.batch}-phase3-deep-notes",
            "--review-status",
            "accepted",
            "--allow-write",
        ],
        root,
    )
    return {
        "status": "accepted" if register["returncode"] == 0 else "failed",
        "accepted_note": str(target.relative_to(root)),
        "check": check,
        "register": register,
        "warnings": [],
        "errors": [] if register["returncode"] == 0 else [register["stderr"] or "register-artifact failed"],
    }


def run_final(args) -> list[dict]:
    root = Path(args.root).resolve()
    final_files = ["final_literature_map.md", "key_papers.md", "research_opportunities.md", "open_questions.md"]
    placeholder = all((not (root / name).exists()) or (root / name).stat().st_size <= 80 for name in final_files)
    command = [
        args.python,
        script("write_final_synthesis.py"),
        "--inventory",
        str(resolve_inventory(root, args.inventory)),
        "--skim-notes",
        str(root / args.skim_notes),
        "--deep-notes",
        str(root / args.deep_notes),
        "--candidates",
        str(root / args.candidates),
        "--phase2-root",
        args.phase2_root,
        "--allow-write",
        "--output-dir",
        str(root),
    ]
    if args.overwrite or placeholder:
        command.append("--overwrite")
    return [
        run(command, root)
    ]


def run_state(args) -> dict:
    root = Path(args.root).resolve()
    inventory_name = default_inventory_for(root, args.inventory)
    result = run(
        [
            args.python,
            script("check_workflow_state.py"),
            "--root",
        str(root),
            "--inventory",
            str(resolve_inventory(root, inventory_name)),
            "--phase2-root",
            args.phase2_root,
            "--skim-notes",
            args.skim_notes,
            "--skim-overview",
            args.skim_overview,
            "--candidates",
            args.candidates,
            "--deep-notes",
            args.deep_notes,
        ],
        root,
    )
    return json.loads(result["stdout"])


def state_file_path(args) -> Path:
    requested = getattr(args, "state_file", "") or ""
    root = Path(args.root).resolve()
    path = Path(requested) if requested else root / ".codex" / "literature_workflow_state.json"
    return path if path.is_absolute() else root / path


def read_persistent_state(args) -> tuple[dict | None, list[str]]:
    path = state_file_path(args)
    if not path.exists():
        return None, []
    try:
        return json.loads(path.read_text(encoding="utf-8")), []
    except Exception as exc:  # noqa: BLE001
        return None, [f"failed to read persistent state {path}: {exc}"]


def infer_phase(scan: dict) -> str:
    phase1 = scan.get("phase1", {})
    phase2 = scan.get("phase2", {})
    batches = scan.get("batches", {})
    final = scan.get("final_synthesis", {})
    phase3 = scan.get("phase3", {})
    if final.get("ready"):
        return "final"
    if phase3.get("status") in {"selected_pending", "deep_text_ready", "deep_notes_complete"}:
        return "phase3"
    if phase2.get("started") or any(item.get("notes_entries", 0) > 0 for item in batches.values()):
        return "phase2"
    if phase1.get("phase1_report_exists") or phase1.get("inventory_exists"):
        return "phase1"
    return "unknown"


def batch_from_next_action(next_action: str) -> str | None:
    match = re.search(r"\b(B[0-9]{2,})\b", next_action or "")
    return match.group(1) if match else None


def infer_workflow_state(args, scan: dict | None = None) -> dict:
    root = Path(args.root).resolve()
    scan_state = scan if scan is not None else run_state(args)
    phase1 = scan_state.get("phase1", {})
    batches = scan_state.get("batches", {})
    final = scan_state.get("final_synthesis", {})
    phase2 = scan_state.get("phase2", {})
    next_action = scan_state.get("next_action", "")
    completed = [code for code, item in batches.items() if item.get("status") in {"notes_complete", "skim_complete"}]
    inventory_path = phase1.get("inventory_path") or str(resolve_inventory(root, default_inventory_for(root, args.inventory)))
    phase1_report = Path(phase1.get("phase1_report_path") or default_phase1_report_for(root))
    notes_path = root / args.skim_notes
    warnings = []
    if phase1.get("missing_project_files"):
        warnings.append("missing_project_files: " + ", ".join(phase1.get("missing_project_files", [])))
    if phase2.get("missing_files"):
        warnings.append("phase2_missing_files: " + ", ".join(phase2.get("missing_files", [])))
    return {
        "project_type": "literature_research_workflow",
        "workflow_mode": scan_state.get("workflow_mode", "three_stage"),
        "phase": infer_phase(scan_state),
        "root": str(root),
        "inventory_path": inventory_path if Path(inventory_path).exists() else None,
        "phase1_report_path": str(phase1_report) if phase1_report.exists() else None,
        "notes_path": str(notes_path) if notes_path.exists() else None,
        "raw_papers_dir": str(root / "raw_papers"),
        "phase2_dir": str(root / args.phase2_root),
        "current_batch": batch_from_next_action(next_action),
        "completed_batches": completed,
        "batch_status": batches,
        "counts": scan_state.get("counts", {}),
        "last_successful_step": "",
        "next_recommended_action": next_action,
        "next_action": next_action,
        "network_policy": "unknown",
        "accepted_failures": [],
        "warnings": warnings,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "phase1": phase1,
        "phase2": phase2,
        "phase3": scan_state.get("phase3", {}),
        "batches": batches,
        "final_synthesis": final,
    }


def merge_workflow_state(persistent: dict | None, inferred: dict) -> tuple[dict, list[str]]:
    persistent = persistent or {}
    merged = dict(persistent)
    preserve_keys = {"accepted_failures", "last_successful_step", "network_policy", "user_notes"}
    for key, value in inferred.items():
        if key in preserve_keys and persistent.get(key) not in (None, "", [], {}):
            continue
        merged[key] = value
    merged["warnings"] = list(dict.fromkeys([*(persistent.get("warnings") or []), *(inferred.get("warnings") or [])]))
    mismatch_warnings = []
    if persistent:
        for key in ["inventory_path", "phase1_report_path", "notes_path", "next_recommended_action"]:
            old = persistent.get(key)
            new = inferred.get(key)
            if old not in (None, "", [], {}) and new not in (None, "", [], {}) and old != new:
                mismatch_warnings.append(f"persistent state differs from filesystem for {key}; filesystem value is used")
        persistent_completed = set(persistent.get("completed_batches") or [])
        inferred_completed = set(inferred.get("completed_batches") or [])
        stale_completed = sorted(persistent_completed - inferred_completed)
        if stale_completed:
            mismatch_warnings.append(
                "persistent completed_batches not confirmed by filesystem: " + ", ".join(stale_completed)
            )
        if persistent_completed:
            merged["completed_batches"] = sorted(persistent_completed | inferred_completed)
    if mismatch_warnings:
        merged["warnings"] = list(dict.fromkeys([*merged.get("warnings", []), *mismatch_warnings]))
    return merged, mismatch_warnings


def merged_workflow_state(args) -> tuple[dict, dict | None, dict, list[str]]:
    scan = run_state(args)
    persistent, read_warnings = read_persistent_state(args)
    inferred = infer_workflow_state(args, scan)
    merged, mismatch_warnings = merge_workflow_state(persistent, inferred)
    return merged, persistent, inferred, [*read_warnings, *mismatch_warnings]


def write_state_file(args, state: dict) -> Path:
    path = state_file_path(args)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, state)
    return path


def first_planned_batch(state: dict) -> str:
    next_action = state.get("next_action", "")
    parts = next_action.split()
    for part in parts:
        if part.startswith("B") and len(part) >= 3:
            return part[:3]
    return ""


def is_url(value: str | None) -> bool:
    return bool(value and value.startswith(("http://", "https://")))


def resolve_action(args) -> str:
    if args.action:
        return args.action
    if args.phase == "phase1":
        return "phase1"
    if args.batch:
        return "prepare-batch"
    if args.phase == "final":
        return "final"
    if args.continue_workflow:
        return "next"
    return "state"


def write_operations_for(action: str, args) -> list[str]:
    if action == "init-from-awesome":
        return ["write template-v2 scaffold", "write source snapshot, source items, workflow inventory, candidates, conflicts, batch plan, Phase 1 report draft, and PROJECT_STATUS.md"]
    if action == "accept-phase1":
        return ["copy accepted Phase 1 report", "register accepted artifact", "freeze batch plan", "update PROJECT_STATUS.md"]
    if action == "import-local-pdfs":
        return ["copy or register local PDFs without moving raw_papers", "update inventory PDF status"]
    if action == "run-next-microbatch":
        return ["check batch PDF and extraction readiness", "write .codex task file only when a readable uncovered micro-batch is ready", "create or update batch-level draft note target if missing"]
    if action == "accept-draft":
        return ["quality-check draft", "copy accepted note", "register accepted artifact", "update PROJECT_STATUS.md"]
    if action == "phase1":
        return [
            "scaffold project files if missing",
            f"write or update {args.inventory}",
            "classify inventory",
            "plan reading batches",
            "write phase1_report.md",
        ]
    if action == "prepare-batch":
        items = [
            f"write or reuse {args.batch}_manifest.json",
            "write raw PDF ensure status",
            "copy local PDFs from raw_papers into phase2_papers",
            "write validation status",
            "extract body text if PDFs validate",
        ]
        if args.write_stubs:
            items.append("write batch note stubs")
        return items
    if action == "phase2-overview":
        if is_template_v2(Path(args.root).resolve()) and args.batch:
            overview = f"reports/accepted_overviews/{args.batch}_skim_overview.md" if args.skim_overview == "phase2_skim_overview.md" else args.skim_overview
            candidates = f"candidates/accepted/{args.batch}_deep_reading_candidates.csv" if args.candidates == "phase2_deep_reading_candidates.csv" else args.candidates
            return [f"write {overview}", f"merge {candidates} while preserving user selections", "register accepted overview and candidate table"]
        return [f"write {args.skim_overview}", f"merge {args.candidates} while preserving user selections"]
    if action == "phase3-deep":
        deep_manifest_name = f"{args.batch}_deep_text_manifest.json" if args.batch else "phase3_deep_text_manifest.json"
        deep_stub_name = f"{args.batch}_phase3_deep_note_stubs.md" if args.batch else "phase3_deep_note_stubs.md"
        return [
            "write selected-paper .deep.txt sidecars including appendices",
            f"write {args.phase2_root}/{deep_manifest_name}",
            f"write {args.phase2_root}/{deep_stub_name}",
        ]
    if action == "promote-to-deep":
        return ["mark one reading-priority candidate as selected_for_phase3=yes"]
    if action == "accept-phase3":
        return [f"write notes/accepted/{args.batch}_deep.md", "register accepted Phase 3 deep note"]
    if action == "final":
        return [
            "write phase2_reading_notes.parsed.json",
            "write final_literature_map.md, key_papers.md, research_opportunities.md, and open_questions.md",
        ]
    if action == "init-state":
        return [f"create {state_file_path(args)} if it does not already exist"]
    if action == "update-state":
        return [f"update existing {state_file_path(args)} from filesystem scan while preserving accepted history fields"]
    return []


def planned_steps_for(action: str, args) -> list[dict]:
    root = Path(args.root).resolve()
    if action in {"init-from-awesome", "accept-phase1", "import-local-pdfs", "run-next-microbatch", "accept-draft", "validate-project", "check-phase3-selection"}:
        return [{"description": f"run template-v2 harness action {action}"}]
    if action == "phase1":
        steps = [{"description": "create standard scaffold files if missing"}]
        if args.source:
            steps.extend(
                [
                    {"description": "build phase1 inventory", "source": args.source, "output": str(root / args.inventory)},
                    {"description": "classify inventory", "inventory": str(root / args.inventory)},
                    {"description": "plan reading batches", "inventory": str(root / args.inventory)},
                    {"description": "check inventory quality", "inventory": str(root / args.inventory)},
                    {"description": "write phase1 report", "output": str(root / "phase1_report.md")},
                ]
            )
        else:
            steps.append({"description": "missing required --source; no Phase 1 commands can run yet"})
        return steps
    if action == "prepare-batch":
        if not args.batch:
            return [{"description": "missing required --batch; no batch preparation commands can run yet"}]
        manifest = root / args.phase2_root / f"{args.batch}_manifest.json"
        steps = [
            {"description": "create or reuse batch manifest", "manifest": str(manifest)},
            {"description": "ensure raw PDFs", "download": bool(args.download), "raw_dir": str(root / "raw_papers")},
            {"description": "copy local PDFs from raw_papers into phase2_papers"},
            {"description": "validate existing PDFs without downloading"},
            {"description": "extract main-body text only if PDFs validate"},
        ]
        if args.write_stubs:
            steps.append({"description": "write structured note stubs"})
        return steps
    if action == "phase2-overview":
        if is_template_v2(root) and args.batch:
            overview = root / ("reports/accepted_overviews/" + f"{args.batch}_skim_overview.md") if args.skim_overview == "phase2_skim_overview.md" else root / args.skim_overview
            candidates = root / ("candidates/accepted/" + f"{args.batch}_deep_reading_candidates.csv") if args.candidates == "phase2_deep_reading_candidates.csv" else root / args.candidates
            return [
                {"description": "parse accepted batch skim note", "batch": args.batch},
                {"description": "write batch skim overview", "output": str(overview)},
                {"description": "merge reading-priority candidate CSV and preserve user selections", "output": str(candidates)},
                {"description": "register accepted overview and candidate table", "batch": args.batch},
            ]
        return [
            {"description": "parse cumulative skim notes"},
            {"description": "write cumulative field skim overview", "output": str(root / args.skim_overview)},
            {"description": "merge Phase 3 candidate CSV and preserve user selections", "output": str(root / args.candidates)},
        ]
    if action == "phase3-deep":
        candidates = resolve_candidates(root, args.candidates, batch=args.batch or "", explicit=getattr(args, "candidates_explicit", False))
        deep_manifest_name = f"{args.batch}_deep_text_manifest.json" if args.batch else "phase3_deep_text_manifest.json"
        deep_stub_name = f"{args.batch}_phase3_deep_note_stubs.md" if args.batch else "phase3_deep_note_stubs.md"
        return [
            {"description": "read candidates selected with selected_for_phase3=yes", "candidates": str(candidates)},
            {"description": "extract selected PDF full text including appendix into .deep.txt sidecars", "manifest": str(root / args.phase2_root / deep_manifest_name)},
            {"description": "write compact selected deep-reading stubs", "output": str(root / args.phase2_root / deep_stub_name)},
        ]
    if action == "promote-to-deep":
        return [{"description": "promote one core paper from the reading-priority candidate table", "paper_id": args.paper_id}]
    if action == "check-phase3-notes":
        return [{"description": "validate selected Phase 3 deep note coverage and note quality", "batch": args.batch}]
    if action == "accept-phase3":
        return [{"description": "copy Phase 3 deep note into notes/accepted, validate selected coverage, and register artifact", "batch": args.batch}]
    if action == "final":
        return [{"description": "create final synthesis draft files from active registry artifacts"}]
    if action == "check-batch":
        return [{"description": "inspect batch state"}, {"description": "optionally run notes quality checker", "enabled": bool(args.check_notes_quality)}]
    if action == "init-state":
        return [{"description": "infer workflow state from filesystem"}, {"description": "create state file if absent", "path": str(state_file_path(args))}]
    if action == "update-state":
        return [{"description": "read existing persistent state"}, {"description": "merge filesystem facts into persistent state", "path": str(state_file_path(args))}]
    if action == "check-node":
        return [{"description": "resolve and test local Node runtime without running downloader scripts"}]
    return [{"description": "inspect workflow state"}]


def network_required_for(action: str, args) -> bool:
    if action == "init-from-awesome":
        return bool(is_url(args.source))
    if action == "phase1":
        return bool(args.fetch_metadata or is_url(args.source))
    if action == "prepare-batch":
        return bool(args.download)
    return False


def node_summary(args, diagnostics: dict) -> dict:
    return {
        "action": "check-node",
        "root": str(Path(args.root).resolve()),
        "steps": [],
        "planned_steps": planned_steps_for("check-node", args),
        "warnings": diagnostics["warnings"],
        "errors": diagnostics["errors"],
        "initial_state": None,
        "final_state": None,
        "next_action": diagnostics["next_action"],
        "network_required": False,
        "write_operations": [],
        "state_file": str(state_file_path(args)),
        "resolved_node_command": diagnostics["resolved_node_command"],
        "resolution_source": diagnostics["resolution_source"],
        "node_version": diagnostics["node_version"],
        "node_executable": diagnostics["node_executable"],
        "npm_found": diagnostics["npm_found"],
        "npm_version": diagnostics["npm_version"],
        "downloader_scripts_found": diagnostics["downloader_scripts_found"],
    }


def explicit_action(args) -> bool:
    return bool(args.action)


def action_guard(args, action: str) -> tuple[bool, list[str], list[str]]:
    warnings = []
    errors = []
    if action in {"state", "next", "check-batch", "init-state", "update-state", "check-node", "validate-project", "check-phase3-selection"}:
        return False, warnings, errors

    if args.plan_only:
        warnings.append("--plan-only was set; no workflow commands were executed.")
        return True, warnings, errors

    if network_required_for(action, args) and not args.allow_network:
        errors.append("network_required is true; rerun with --allow-network after user approval.")
    if write_operations_for(action, args) and not args.allow_write:
        errors.append("write_operations are planned; rerun with --allow-write after confirming writes are intended.")
    return bool(errors), warnings, errors


def build_summary(
    args,
    action: str,
    steps: list[dict] | None = None,
    initial_state: dict | None = None,
    final_state: dict | None = None,
    warnings: list[str] | None = None,
    errors: list[str] | None = None,
) -> dict:
    final = final_state
    if final is None:
        try:
            final = run_state(args)
        except Exception as exc:  # noqa: BLE001
            final = None
            warnings = list(warnings or [])
            warnings.append(f"final_state_unavailable: {exc}")
    return {
        "action": action,
        "root": str(Path(args.root).resolve()),
        "steps": steps or [],
        "planned_steps": planned_steps_for(action, args),
        "warnings": warnings or [],
        "errors": errors or [],
        "initial_state": initial_state,
        "final_state": final,
        "next_action": (final or initial_state or {}).get("next_action", ""),
        "network_required": network_required_for(action, args),
        "write_operations": write_operations_for(action, args),
        "state_file": str(state_file_path(args)),
    }


def apply_contract_validation(summary: dict) -> None:
    summary.setdefault("warnings", []).extend(validate_contracts(summary))
    summary.setdefault("warnings", []).extend(validate_workflow_state_contract(summary.get("initial_state")))
    summary.setdefault("warnings", []).extend(validate_workflow_state_contract(summary.get("final_state")))


def run_next_report(args) -> tuple[dict, list[str]]:
    state, persistent, _inferred, state_warnings = merged_workflow_state(args)
    next_action = state.get("next_action", "")
    warnings = [
        "--action next is conservative and does not automatically write files, download PDFs, fetch metadata, or write notes.",
    ]
    warnings.extend(state_warnings)
    if persistent and state_warnings:
        warnings.append("Persistent state may be stale; consider --action update-state --plan-only.")
    if next_action == "run phase1":
        warnings.append("Provide --source and run --action phase1 when ready. If the source is a URL, ask for network permission first.")
    elif next_action == "write phase1 report":
        warnings.append("Next deterministic write would create or overwrite phase1_report.md; run an explicit phase1/report step only after confirming.")
    elif next_action.startswith("process "):
        warnings.append("Next batch preparation may write manifests/status files and may require PDFs in raw_papers/ or explicit --download permission.")
    elif next_action.startswith("write notes for ") or next_action.startswith("write skim notes for "):
        warnings.append("Reading notes are intentionally not written by this runner; read extracted body text and append notes manually or via a dedicated notes workflow.")
    elif next_action == "write phase2 skim overview":
        warnings.append("Generate the cumulative skim overview and candidate CSV with --action phase2-overview when skim notes are ready.")
    elif next_action == "review invalid phase3 selections":
        warnings.append("Review candidate rows whose selected_for_phase3 value is neither yes nor no; blank means not promoted.")
    elif next_action == "prepare phase3 deep reading":
        warnings.append("Promoted papers are ready for appendix-aware extraction with --action phase3-deep.")
    elif next_action == "write deep notes for selected papers":
        warnings.append("Deep-note stubs are ready; complete notes/drafts/Bxx_deep.md for selected papers, then accept to notes/accepted/Bxx_deep.md.")
    elif next_action == "review phase3 failures or continue final with warnings":
        warnings.append("Accepted Phase 3 failures remain unresolved. Review them or run --action final with the recorded warnings.")
    elif next_action == "write final synthesis":
        warnings.append("Final synthesis writes draft files; run --action final only when ready.")
    return state, warnings


def find_batch_heading(notes_path: Path, batch: str) -> tuple[str, list[str]]:
    warnings = []
    if not notes_path.exists():
        return "", [f"notes file not found: {notes_path}"]
    markdown = notes_path.read_text(encoding="utf-8", errors="replace")
    headings = re.findall(r"^##\s+(.+)$", markdown, flags=re.MULTILINE)
    matches = [heading for heading in headings if re.search(rf"\b{re.escape(batch)}\b", heading)]
    if not matches:
        warnings.append(f"no notes heading found for {batch}")
        return "", warnings
    if len(matches) > 1:
        warnings.append(f"multiple notes headings found for {batch}; using the first one")
    return matches[0], warnings


def find_template_v2_skim_heading(notes_path: Path) -> str:
    if not notes_path.exists():
        return ""
    markdown = notes_path.read_text(encoding="utf-8", errors="replace")
    headings = re.findall(r"^##\s+(.+)$", markdown, flags=re.MULTILINE)
    for heading in headings:
        if "per-paper skim notes" in heading.lower():
            return heading
    return headings[0] if headings else ""


def accepted_batch_skim_note_path(root: Path, batch: str) -> Path | None:
    registry = root / "batches" / "accepted_artifacts.json"
    if not registry.exists():
        return None
    data = json.loads(registry.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return None
    candidates = []
    for item in data.get("artifacts", []):
        artifact_type = item.get("artifact_type") or item.get("type")
        if artifact_type != "batch_skim_note" or not is_active_artifact(item):
            continue
        if item.get("batch") != batch:
            continue
        rel = item.get("path", "")
        if not rel:
            continue
        path = root / rel
        if path.exists():
            candidates.append(path)
    return candidates[-1] if candidates else None


def quality_notes_for_batch(args, state: dict, batch: str, item: dict) -> tuple[Path, str, list[str]]:
    root = Path(args.root).resolve()
    skim_path = root / args.skim_notes
    deep_path = root / args.deep_notes
    accepted_skim_path = accepted_batch_skim_note_path(root, batch)
    if accepted_skim_path:
        heading, warnings = find_batch_heading(accepted_skim_path, batch)
        if not heading:
            skim_heading = find_template_v2_skim_heading(accepted_skim_path)
            if skim_heading:
                return accepted_skim_path, skim_heading, []
        return accepted_skim_path, heading, warnings
    for path in [deep_path, skim_path]:
        heading, _warnings = find_batch_heading(path, batch)
        if heading:
            return path, heading, []
    heading, warnings = find_batch_heading(skim_path, batch)
    return skim_path, heading, warnings


def check_batch(args) -> tuple[dict, list[str], list[dict]]:
    if not args.batch:
        raise ValueError("--batch is required for --action check-batch")
    state = run_state(args)
    batch = args.batch.split()[0]
    batches = state.get("batches", {})
    warnings = []
    steps = []
    if is_template_v2(Path(args.root).resolve()):
        missing_report = v2_build_missing_pdf_report(Path(args.root).resolve(), batch)
        if missing_report.get("missing_count", 0):
            state["missing_pdfs"] = missing_report["missing_pdfs"]
            state["human_report"] = missing_report["human_report"]
    if batch not in batches:
        warnings.append(f"{batch} not found in workflow state.")
    else:
        item = batches[batch]
        if item.get("notes_entries", 0) < item.get("papers", 0):
            warnings.append(f"{batch} notes are incomplete or not yet recorded.")
        if item.get("body_texts", 0) < item.get("papers", 0):
            warnings.append(f"{batch} body text count is below expected paper count.")
        if item.get("pdfs", 0) < item.get("papers", 0):
            warnings.append(f"{batch} valid PDF count is below expected paper count.")
        if args.check_notes_quality:
            notes_path, heading, heading_warnings = quality_notes_for_batch(args, state, batch, item)
            warnings.extend(heading_warnings)
            if heading:
                try:
                    steps.append(
                        run(
                            [
                                args.python,
                                script("check_notes_quality.py"),
                                "--notes",
                                str(notes_path),
                                "--batch-heading",
                                heading,
                                "--expected",
                                str(item.get("papers", 0)),
                            ],
                            Path(args.root).resolve(),
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    warnings.append(f"notes quality check failed: {exc}")
    return state, warnings, steps


def init_state(args) -> tuple[dict, list[str], list[dict]]:
    path = state_file_path(args)
    persistent, read_warnings = read_persistent_state(args)
    merged, _persistent, _inferred, state_warnings = merged_workflow_state(args)
    warnings = [*read_warnings, *state_warnings]
    steps = []
    if persistent is not None:
        warnings.append(f"state file already exists and will not be overwritten by init-state: {path}")
        return merged, warnings, steps
    if args.plan_only or not args.allow_write:
        if not args.allow_write:
            warnings.append("init-state requires --allow-write to create the state file.")
        return merged, warnings, steps
    write_state_file(args, merged)
    steps.append({"command": ["write_state_file", str(path)], "returncode": 0, "stdout": str(path), "stderr": ""})
    return merged, warnings, steps


def update_state(args) -> tuple[dict, list[str], list[dict]]:
    path = state_file_path(args)
    persistent, read_warnings = read_persistent_state(args)
    if persistent is None:
        merged, _persistent, _inferred, state_warnings = merged_workflow_state(args)
        warnings = [*read_warnings, f"state file does not exist; run --action init-state first: {path}", *state_warnings]
        return merged, warnings, []
    merged, _persistent, _inferred, state_warnings = merged_workflow_state(args)
    warnings = [*read_warnings, *state_warnings]
    steps = []
    if args.plan_only or not args.allow_write:
        if not args.allow_write:
            warnings.append("update-state requires --allow-write to write the state file.")
        return merged, warnings, steps
    write_state_file(args, merged)
    steps.append({"command": ["write_state_file", str(path)], "returncode": 0, "stdout": str(path), "stderr": ""})
    return merged, warnings, steps


def main() -> None:
    parser = argparse.ArgumentParser(description="One-entry orchestration for the literature research workflow.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--layout", default="auto", choices=["auto", "template-v2"], help="Workflow layout. Current projects use auto/template-v2.")
    parser.add_argument("--source", help="Source file or URL for Phase 1.")
    parser.add_argument("--source-url", default="")
    parser.add_argument(
        "--action",
        choices=["state", "next", "phase1", "prepare-batch", "phase2-overview", "promote-to-deep", "phase3-deep", "check-phase3-notes", "accept-phase3", "check-batch", "final", "init-state", "update-state", "check-node", "init-from-awesome", "accept-phase1", "import-local-pdfs", "run-next-microbatch", "accept-draft", "validate-project", "check-phase3-selection"],
        help="Clear workflow action.",
    )
    parser.add_argument("--phase", choices=["phase1", "state", "final"], help="Workflow phase to run.")
    parser.add_argument("--continue-workflow", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--batch", help="Run a Bxx batch preparation pipeline.")
    parser.add_argument("--paper-id", default="", help="Stable paper id for promote-to-deep, such as arxiv:2401.00001.")
    parser.add_argument("--draft", default="", help="Draft artifact path for accept-draft.")
    parser.add_argument("--micro-batch", default="", help="Optional micro-batch id such as MB01. New template-v2 skim notes are batch-level by default.")
    parser.add_argument("--inventory", default="phase1_inventory.csv")
    parser.add_argument("--phase2-root", default="phase2_papers")
    parser.add_argument("--skim-notes", default="phase2_skim_notes.md", help=argparse.SUPPRESS)
    parser.add_argument("--skim-overview", default="phase2_skim_overview.md", help=argparse.SUPPRESS)
    parser.add_argument("--candidates", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--deep-notes", default="phase3_deep_notes.md", help=argparse.SUPPRESS)
    parser.add_argument("--download", action="store_true", help="Allow PDF downloads for batch preparation.")
    parser.add_argument("--fetch-metadata", action="store_true", help="Allow arXiv API metadata fetching in Phase 1.")
    parser.add_argument("--rules", help="Optional JSON taxonomy rules for Phase 1 classification.")
    parser.add_argument("--overwrite-labels", action="store_true", help="Allow classifier to overwrite existing labels.")
    parser.add_argument("--write-stubs", action="store_true", help="Write Bxx note stubs after extraction succeeds.")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--plan-only", action="store_true", help="Show planned steps and safety requirements without executing workflow writes or network actions.")
    parser.add_argument("--allow-network", action="store_true", help="Explicitly allow network actions when network_required is true.")
    parser.add_argument("--allow-write", action="store_true", help="Explicitly allow workflow commands to write project files.")
    parser.add_argument("--allow-open-conflicts", action="store_true", help="Allow accept-phase1 to proceed with severe unresolved conflicts.")
    parser.add_argument("--allow-partial-skim", action="store_true", help="Allow run-next-microbatch to proceed with pass-quality packets even when the batch has missing PDFs or low-quality extractions.")
    parser.add_argument("--replace-managed", action="store_true", help="Allow import-local-pdfs to replace an existing managed PDF from raw_papers without modifying raw_papers.")
    parser.add_argument("--force", action="store_true", help="Force replacement for idempotent v2 actions where supported.")
    parser.add_argument("--check-notes-quality", action="store_true", help="For --action check-batch, run the local notes quality checker when the batch heading can be found.")
    parser.add_argument("--print-contracts", action="store_true", help="Print available schema contracts and exit without running workflow actions.")
    parser.add_argument("--validate-contracts", action="store_true", help="Advisory validation of the runner summary contract; does not enforce strict migration.")
    parser.add_argument("--state-file", default="", help="Optional persistent workflow state path. Defaults to <root>/.codex/literature_workflow_state.json.")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--node-command", help="Explicit Node.js runtime path or command for downloader helpers.")
    parser.add_argument("--node", dest="node", help=argparse.SUPPRESS)
    args = parser.parse_args()
    args.candidates_explicit = args.candidates is not None
    args.candidates = args.candidates or "phase2_deep_reading_candidates.csv"

    if args.print_contracts:
        print(json.dumps({"contracts": contracts_summary()}, ensure_ascii=False, indent=2))
        return

    steps = []
    state = None
    warnings = []
    action = resolve_action(args)

    try:
        blocked, guard_warnings, guard_errors = action_guard(args, action)
        warnings.extend(guard_warnings)
        if blocked:
            state = run_state(args)
            summary = build_summary(args, action, initial_state=state, final_state=state, warnings=warnings, errors=guard_errors)
            if args.validate_contracts:
                apply_contract_validation(summary)
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            raise SystemExit(1 if guard_errors else 0)

        if action == "state":
            state, _persistent, _inferred, warnings = merged_workflow_state(args)
            summary = build_summary(args, action, initial_state=state, final_state=state, warnings=warnings)
        elif action == "check-node":
            diagnostics = check_node_runtime(args)
            summary = node_summary(args, diagnostics)
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            raise SystemExit(0 if diagnostics["node_executable"] else 1)
        elif action == "next":
            state, warnings = run_next_report(args)
            summary = build_summary(args, action, initial_state=state, final_state=state, warnings=warnings)
        elif action == "phase1":
            steps = run_phase1(args)
            summary = build_summary(args, action, steps=steps)
        elif action == "init-from-awesome":
            result = v2_init_from_awesome(args)
            summary = build_summary(args, action, steps=[result], warnings=result.get("warnings", []), errors=result.get("errors", []))
        elif action == "accept-phase1":
            result = v2_accept_phase1(args)
            summary = build_summary(args, action, steps=[result], warnings=result.get("warnings", []), errors=result.get("errors", []))
        elif action == "prepare-batch":
            if not args.batch:
                raise ValueError("--batch is required for --action prepare-batch")
            if is_template_v2(Path(args.root).resolve()):
                result = v2_prepare_batch(args)
                steps = [result]
            else:
                steps = run_batch(args)
            summary = build_summary(args, action, steps=steps)
            if is_template_v2(Path(args.root).resolve()) and steps:
                result = steps[0]
                if isinstance(result, dict) and result.get("missing_pdfs"):
                    summary["missing_pdfs"] = result.get("missing_pdfs", [])
                    summary["human_report"] = result.get("human_report", "")
        elif action == "import-local-pdfs":
            result = v2_import_local_pdfs(args)
            summary = build_summary(args, action, steps=[result], warnings=result.get("warnings", []), errors=result.get("errors", []))
        elif action == "run-next-microbatch":
            result = v2_run_next_microbatch(args)
            summary = build_summary(args, action, steps=[result], warnings=result.get("warnings", []), errors=result.get("errors", []), final_state=run_state(args))
            summary.update(result)
        elif action == "accept-draft":
            result = v2_accept_draft(args)
            result["overview"] = maybe_generate_v2_overview_after_accept(args, result)
            summary = build_summary(args, action, steps=[result], warnings=result.get("warnings", []), errors=result.get("errors", []))
        elif action == "validate-project":
            result = v2_validate_project(Path(args.root).resolve())
            summary = build_summary(args, action, steps=[result], warnings=result.get("warnings", []), errors=result.get("errors", []))
        elif action == "check-phase3-selection":
            result = v2_check_phase3_selection(args)
            summary = build_summary(args, action, steps=[result], warnings=result.get("warnings", []), errors=result.get("errors", []))
        elif action == "check-phase3-notes":
            result = run_check_phase3_notes(args)
            summary = build_summary(args, action, steps=[result], warnings=result.get("warnings", []), errors=result.get("errors", []))
        elif action == "accept-phase3":
            result = run_accept_phase3(args)
            summary = build_summary(args, action, steps=[result], warnings=result.get("warnings", []), errors=result.get("errors", []))
        elif action == "phase2-overview":
            steps = run_phase2_overview(args)
            summary = build_summary(args, action, steps=steps)
        elif action == "promote-to-deep":
            steps = run_promote_to_deep(args)
            summary = build_summary(args, action, steps=steps)
        elif action == "phase3-deep":
            steps = run_phase3_deep(args)
            summary = build_summary(args, action, steps=steps)
        elif action == "check-batch":
            state, warnings, steps = check_batch(args)
            summary = build_summary(args, action, steps=steps, initial_state=state, final_state=state, warnings=warnings)
            if state.get("missing_pdfs"):
                summary["missing_pdfs"] = state.get("missing_pdfs", [])
                summary["human_report"] = state.get("human_report", "")
        elif action == "final":
            steps = run_final(args)
            summary = build_summary(args, action, steps=steps)
        elif action == "init-state":
            state, warnings, steps = init_state(args)
            summary = build_summary(args, action, steps=steps, initial_state=state, final_state=state, warnings=warnings)
        elif action == "update-state":
            state, warnings, steps = update_state(args)
            summary = build_summary(args, action, steps=steps, initial_state=state, final_state=state, warnings=warnings)
        else:
            raise ValueError(f"Unsupported action: {action}")
    except Exception as exc:  # noqa: BLE001
        summary = build_summary(args, action, warnings=warnings, errors=[str(exc)], final_state=None)
        if args.validate_contracts:
            apply_contract_validation(summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        raise SystemExit(1) from exc

    if args.validate_contracts:
        apply_contract_validation(summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
