import csv
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "awesome_literature_harness.py"


def load_harness():
    scripts = str(ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    spec = importlib.util.spec_from_file_location("awesome_literature_harness_pdf_resolution_tests", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def write_inventory(root: Path, rows: list[dict]) -> None:
    path = root / "inventory/workflow_inventory.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["schema_version", "paper_id", "dedup_key", "arxiv_id", "canonical_title", "public_pdf_url", "reading_batch", "pdf_status", "local_pdf_path"]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_packet(root: Path, packet_id: str, paper_id: str, micro_batch: str) -> dict:
    rel = f"phase2_papers/B01_packets/{packet_id}.packet.md"
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Evidence\n\n" + ("Abstract\nEnough evidence text.\n" * 80), encoding="utf-8")
    return {
        "packet_id": packet_id,
        "paper_id": paper_id,
        "batch": "B01",
        "micro_batch": micro_batch,
        "packet_path": rel,
        "quality_status": "pass",
        "status": "created",
    }


def canonical_entry(paper_id: str, title: str, packet_id: str) -> str:
    return f"""### {paper_id} - {title}

#### 1. Problem and difficulty
- [Paper-stated] Problem: Test problem.
- Evidence: paper_id={paper_id}, packet={packet_id}, section=Introduction

#### 2. Motivation / Method Rationale
- [Paper-stated] Motivation: Test motivation.
- [Inferred rationale] Why this method is a natural move: Test rationale.
- Evidence: paper_id={paper_id}, packet={packet_id}, section=Introduction

#### 3. Core method
- One-sentence method: Test method.
- Key mechanism / changed step: Test changed step.

#### 4. Method comparison diagram
<!-- method-comparison:start -->
```text
Direct baseline: Input -> Output
Representative prior: Input -> Prior -> Output
This paper: Input -> KEY CHANGED STEP -> Output
```
<!-- method-comparison:end -->

#### 5. Evidence and uncertainty
- Evidence available in packet: Test evidence.
- Main uncertainty from packet-only reading: Test uncertainty.
"""


class MultiSourcePdfResolutionTests(unittest.TestCase):
    def test_missing_non_arxiv_pdf_reports_needs_review_without_fabricated_url(self) -> None:
        harness = load_harness()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_inventory(
                root,
                [
                    {
                        "schema_version": "template-v2.1",
                        "paper_id": "doi:10.5555/foo.bar",
                        "dedup_key": "doi:10.5555/foo.bar",
                        "canonical_title": "DOI Paper",
                        "public_pdf_url": "",
                        "reading_batch": "B01",
                        "pdf_status": "needs_pdf_review",
                    }
                ],
            )

            report = harness.build_missing_pdf_report(root, "B01")

            self.assertEqual(report["missing_count"], 1)
            self.assertEqual(report["missing_pdfs"][0]["paper_id"], "doi:10.5555/foo.bar")
            self.assertEqual(report["missing_pdfs"][0]["pdf_status"], "needs_pdf_review")
            self.assertEqual(report["missing_pdfs"][0]["public_pdf_url"], "")
            self.assertIn("metadata", report["human_report"].lower())

    def test_run_next_microbatch_sorts_non_arxiv_paper_ids_stably(self) -> None:
        harness = load_harness()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            local_pdf = root / "phase2_papers/managed_pdfs/openreview_AbC.pdf"
            local_pdf.parent.mkdir(parents=True, exist_ok=True)
            local_pdf.write_bytes(b"%PDF-")
            write_json(root / "phase2_papers/B01_manifest.json", {"papers": [
                {"paper_id": "openreview:AbC", "pdf_status": "available", "local_pdf_path": "phase2_papers/managed_pdfs/openreview_AbC.pdf"},
                {"paper_id": "doi:10.5555/foo.bar", "pdf_status": "available", "local_pdf_path": "phase2_papers/managed_pdfs/openreview_AbC.pdf"},
            ]})
            write_json(root / "phase2_papers/B01_body_text_manifest.json", {"bodies": [
                {"paper_id": "openreview:AbC", "quality_status": "pass"},
                {"paper_id": "doi:10.5555/foo.bar", "quality_status": "pass"},
            ]})
            packets = [
                write_packet(root, "B01-P02", "openreview:AbC", "MB01"),
                write_packet(root, "B01-P01", "doi:10.5555/foo.bar", "MB01"),
            ]
            write_json(root / "phase2_papers/B01_packet_manifest.json", {"packets": packets})

            result = harness.run_next_microbatch(SimpleNamespace(root=str(root), batch="B01", allow_write=True))

            self.assertEqual(result["status"], "ready")
            self.assertEqual(result["paper_ids"], ["doi:10.5555/foo.bar", "openreview:AbC"])
            task = (root / result["task_file"]).read_text(encoding="utf-8")
            self.assertRegex(task, r"paper_ids:\n  - doi:10\.5555/foo\.bar\n  - openreview:AbC")

    def test_validate_project_keeps_existing_accepted_artifact_paths(self) -> None:
        harness = load_harness()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_inventory(root, [{"schema_version": "template-v2.1", "paper_id": "openreview:AbC", "dedup_key": "openreview:AbC", "canonical_title": "Legacy Accepted", "reading_batch": "B01"}])
            for rel, text in {
                "inventory/source_items.csv": "schema_version,source_item_id,paper_id,source_snapshot_id\n",
                "inventory/representative_candidates.csv": "schema_version,paper_id,selection_role,selection_axis,selection_reason\n",
                "inventory/conflicts.csv": "schema_version,conflict_id,paper_id,dedup_key,conflict_type,field,left_value,right_value,evidence,severity,status,resolution_notes\n",
                "batches/batch_config.csv": "schema_version,batch_id,paper_id\n",
                "batches/reading_plan.md": "# Reading Plan\n",
                "PROJECT_STATUS.md": "# Project Status\n",
            }.items():
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
            write_json(root / "inventory/source_snapshot.json", {"schema_version": "template-v2.1", "source_snapshot_id": "snapshot:test"})
            note = root / "notes/accepted/B01.md"
            note.parent.mkdir(parents=True, exist_ok=True)
            note_text = "\n".join([
                "---",
                "schema_version: template-v2.1",
                "artifact_type: batch_skim_note",
                "batch: B01",
                "paper_ids:",
                "  - openreview:AbC",
                "source_packets:",
                "  - phase2_papers/B01_packets/B01-P01.packet.md",
                "status: accepted",
                "---",
                "",
                "## 1. Scope",
                "Full batch packet-only note.",
                "",
                "## 2. Coverage status",
                "",
                "## 3. Per-paper skim notes",
                "",
                canonical_entry("openreview:AbC", "Legacy Accepted", "B01-P01"),
                "",
                "## 4. Cross-paper comparison",
                "- Comparison point.",
                "",
                "## 5. Extraction issues",
                "",
                "## 6. Limitations / uncertainty",
                "",
            ])
            note.write_text(note_text, encoding="utf-8")
            digest = harness.content_hash(note)
            write_json(root / "batches/accepted_artifacts.json", {"schema_version": "template-v2.1", "version": 2, "artifacts": [
                {"artifact_type": "batch_skim_note", "path": "notes/accepted/B01.md", "batch": "B01", "paper_ids": ["openreview:AbC"], "status": "active", "content_hash": digest}
            ]})

            result = harness.validate_project(root)

            self.assertEqual(result["status"], "passed")
            self.assertFalse(any("registry path missing" in error for error in result["errors"]))


if __name__ == "__main__":
    unittest.main()
