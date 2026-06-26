import argparse
import shutil
import subprocess
from pathlib import Path

from workflow_safety import atomic_write_json, atomic_write_text, require_write_permission

SCHEMA_VERSION = "template-v2.1"
SKILL_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_VENDOR_DIRS = ["scripts", "docs", "schemas", "templates"]


TEMPLATE_V2_DIRS = [
    "docs",
    "batches",
    "inventory",
    "raw_papers",
    "phase2_papers",
    "notes/accepted",
    "notes/drafts",
    "reports/accepted_overviews",
    "reports/drafts",
    "candidates/accepted",
    "candidates/drafts",
    "archive",
    "archive/repair_history",
    "archive/superseded_notes",
    "archive/superseded_reports",
    "archive/raw_tables",
    ".codex",
    ".codex/source_cache",
    ".codex/tasks",
]
WORKFLOW_INVENTORY_HEADER = (
    "schema_version,paper_id,dedup_key,arxiv_id,canonical_title,canonical_source,"
    "official_url,public_pdf_url,source_type,source_role,venue,year,authors,abstract,"
    "section,method_category,application_tag,reading_batch,reading_priority,"
    "metadata_status,metadata_evidence,pdf_status,extraction_status,packet_status,notes\n"
)
SOURCE_ITEMS_HEADER = (
    "schema_version,source_item_id,paper_id,dedup_key,source_snapshot_id,source_file,"
    "source_section,source_line,source_item_text,source_url,link_type,title_hint,"
    "venue_hint,year_hint,tag_hint,created_at\n"
)
REPRESENTATIVE_HEADER = (
    "schema_version,paper_id,dedup_key,canonical_title,source_type,source_role,"
    "selection_role,selection_axis,selection_reason,evidence,confidence,selected_for_phase3,selection_notes\n"
)
CONFLICTS_HEADER = (
    "schema_version,conflict_id,paper_id,dedup_key,conflict_type,field,left_value,right_value,"
    "evidence,severity,status,resolution_notes\n"
)
TEMPLATE_V2_FILES = {
    "README.md": "# Literature Project\n\n",
    "PROJECT_STATUS.md": "\n".join(
        [
            "# Project Status",
            "",
            "## Current Phase",
            "",
            "- Phase: Phase 1 / Phase 2 / Phase 3 / Final",
            "- Active batch: N/A",
            "- Next gate: define scope and build inventory",
            "- Schema version: template-v2.1",
            "",
            "## Accepted Outputs",
            "",
            "- Notes: see `notes/accepted/` and `batches/accepted_artifacts.json`",
            "- Overviews: see `reports/accepted_overviews/`",
            "- Candidate tables: see `candidates/accepted/`",
            "",
            "## Open Checks",
            "",
            "- Registry check:",
            "- Context-budget check:",
            "- Metadata gaps:",
            "- User decisions needed:",
            "",
        ]
    ),
    ".gitignore": "\n".join(
        [
            ".codex/",
            "*.tmp",
            "*.part",
            "__pycache__/",
            "*.pyc",
            "raw_papers/",
            "phase2_papers/**/*.pdf",
            "phase2_papers/**/*.body.txt",
            "phase2_papers/**/*.deep.txt",
            "phase2_papers/**/*packet*.md",
            "",
        ]
    ),
    "source_links.md": "# Source Links\n\n",
    "scope.md": "# Scope\n\n## Inclusion\n\n## Exclusion\n\n## Research Lens\n\n",
    "docs/workflow_spec.md": "# Project Workflow Spec\n\nUse the skill workflow spec as the default. Record project-local taxonomy, selection policy, source-role policy, and note-template deviations here.\n",
    "docs/checker_policy.md": "# Checker Policy\n\nTemplate-v2 projects treat registry checks and current note gates as strict.\n",
    "docs/git_policy.md": "# Git Policy\n\nGit initialization is explicit via `--init-git`. Never commit automatically. Track accepted artifacts, inventory, registry, status, schemas, scripts, docs, and templates. Ignore raw PDFs, extracted body/deep text, packets, and `.codex/` caches.\n",
    "batches/batch_config.csv": "schema_version,batch_id,paper_id,technical_route,batch_goal,selection_mode,max_core_papers,microbatch_size,status,notes\n",
    "batches/reading_plan.md": "# Reading Plan\n\n- schema_version: template-v2.1\n- frozen: no\n\n",
    "inventory/source_items.csv": SOURCE_ITEMS_HEADER,
    "inventory/conflicts.csv": CONFLICTS_HEADER,
    "inventory/source_snapshot.json": "",
    "inventory/representative_candidates.csv": REPRESENTATIVE_HEADER,
    "inventory/metadata_overrides.csv": "arxiv_id,field,value,source,notes\n",
    "inventory/workflow_inventory.csv": WORKFLOW_INVENTORY_HEADER,
}
def template_path() -> Path:
    return Path(__file__).resolve().parents[1] / "templates" / "literature_project" / "AGENTS.md"


def write_if_allowed(path: Path, content: str, force: bool, created: list[str], skipped: list[str]) -> None:
    if path.exists() and not force:
        skipped.append(str(path))
        return
    atomic_write_text(path, content)
    created.append(str(path))


def copy_tree_if_allowed(source: Path, target: Path, force: bool, created: list[str], skipped: list[str]) -> None:
    if not source.exists():
        skipped.append(str(target))
        return
    for item in source.rglob("*"):
        if item.is_dir() or "__pycache__" in item.parts or item.suffix == ".pyc":
            continue
        rel = item.relative_to(source)
        dest = target / rel
        if dest.exists() and not force:
            skipped.append(str(dest))
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, dest)
        created.append(str(dest))


def initialize_git(root: Path, created: list[str], skipped: list[str]) -> None:
    if (root / ".git").exists():
        skipped.append(str(root / ".git"))
        return
    completed = subprocess.run(["git", "init"], cwd=str(root), text=True, capture_output=True)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "git init failed")
    created.append(str(root / ".git"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a standard literature project scaffold.")
    parser.add_argument("--root", default=".", help="Project root directory.")
    parser.add_argument("--force", action="store_true", help="Overwrite existing scaffold files.")
    parser.add_argument(
        "--phase1-only",
        action="store_true",
        help="Compatibility flag; template-v2 scaffold is always created.",
    )
    parser.add_argument("--template-v2", action="store_true", help="Compatibility flag; template-v2 is now the default.")
    parser.add_argument("--vendor-workflow", action="store_true", help="Copy scripts, docs, schemas, and templates into the project.")
    parser.add_argument("--init-git", action="store_true", help="Explicitly run git init in the project root.")
    parser.add_argument("--allow-write", action="store_true")
    args = parser.parse_args()
    require_write_permission(args, "project scaffold output")

    root = Path(args.root).resolve()
    root.mkdir(parents=True, exist_ok=True)

    created = []
    skipped = []
    vendor_workflow = True
    for dirname in TEMPLATE_V2_DIRS:
        path = root / dirname
        if path.exists():
            skipped.append(str(path))
        else:
            path.mkdir(parents=True)
            created.append(str(path))

    agents_template = template_path()
    if agents_template.exists():
        TEMPLATE_V2_FILES["AGENTS.md"] = agents_template.read_text(encoding="utf-8")
    else:
        TEMPLATE_V2_FILES["AGENTS.md"] = "# Literature Project Instructions\n\n"
    for filename, content in TEMPLATE_V2_FILES.items():
        if filename == "inventory/source_snapshot.json":
            continue
        write_if_allowed(root / filename, content, args.force, created, skipped)
    snapshot_path = root / "inventory" / "source_snapshot.json"
    if not snapshot_path.exists() or args.force or not snapshot_path.read_text(encoding="utf-8", errors="replace").strip():
        atomic_write_json(snapshot_path, {"schema_version": SCHEMA_VERSION, "source_snapshot_id": "", "included_files": [], "excluded_files": []})
        created.append(str(snapshot_path))
    registry_path = root / "batches" / "accepted_artifacts.json"
    if registry_path.exists() and not args.force:
        skipped.append(str(registry_path))
    else:
        atomic_write_json(registry_path, {"schema_version": SCHEMA_VERSION, "version": 2, "artifacts": []})
        created.append(str(registry_path))
    if vendor_workflow:
        for dirname in WORKFLOW_VENDOR_DIRS:
            copy_tree_if_allowed(SKILL_ROOT / dirname, root / dirname, args.force, created, skipped)
    if args.init_git:
        initialize_git(root, created, skipped)

    print(
        {
            "root": str(root),
            "created": created,
            "skipped": skipped,
            "force": args.force,
            "phase1_only": args.phase1_only,
            "template_v2": True,
            "vendor_workflow": vendor_workflow,
            "init_git": args.init_git,
        }
    )


if __name__ == "__main__":
    main()
