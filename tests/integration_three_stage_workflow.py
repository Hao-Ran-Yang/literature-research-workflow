import csv
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
import os
from unittest import mock
from pathlib import Path

from tests.workflow_test_helpers import *


class ThreeStageWorkflowIntegrationTests(unittest.TestCase):
    def test_phase1_local_regression(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.md"
            source.write_text("# Core\n- Example https://arxiv.org/abs/2401.00001\n", encoding="utf-8")
            run_json(
                "literature_workflow.py",
                "--root",
                str(root),
                "--action",
                "phase1",
                "--source",
                str(source),
                "--allow-write",
                cwd=root,
            )
            self.assertTrue((root / "phase1_inventory.csv").exists())
            self.assertTrue((root / "phase1_report.md").exists())
            self.assertFalse((root / "phase2_skim_notes.md").exists())

    def test_full_scaffold_placeholders_do_not_start_later_phases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            completed = subprocess.run(
                [sys.executable, "-B", str(SCRIPTS / "scaffold_literature_project.py"), "--root", str(root), "--allow-write"],
                cwd=str(root),
                check=True,
                text=True,
                capture_output=True,
            )
            self.assertIn("template_v2", completed.stdout)
            state = run_json("check_workflow_state.py", "--root", str(root), cwd=root)
            self.assertFalse(state["phase2"]["started"])
            self.assertFalse(state["final_synthesis"]["started"])
            self.assertEqual(state["next_action"], "run phase1")

    def test_phase2_gate_and_phase3_stub_filter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            row = write_inventory(root)
            _manifest, pdf = create_ready_batch(root, row)
            removed_action = subprocess.run(
                [sys.executable, "-B", str(SCRIPTS / "literature_workflow.py"), "--root", str(root), "--action", "phase2-skim", "--batch", "B01", "--allow-write"],
                cwd=str(root),
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(removed_action.returncode, 0)
            self.assertIn("invalid choice", removed_action.stderr)

            good_deep = pdf.with_suffix(".deep.txt")
            good_deep.write_text("appendix " * 300, encoding="utf-8")
            failed_pdf = root / "phase2_papers" / "Core" / "Adapters" / "2401.00002.pdf"
            deep_manifest = root / "phase2_papers" / "phase3_deep_text_manifest.json"
            deep_manifest.write_text(
                json.dumps(
                    [
                        {**row, "status": "exists", "deep_text_path": str(good_deep), "pdf_path": str(pdf)},
                        {**row, "arxiv_id": "2401.00002", "status": "parse_failed", "pdf_path": str(failed_pdf), "error": "bad pdf"},
                    ]
                ),
                encoding="utf-8",
            )
            candidates = root / "phase2_deep_reading_candidates.csv"
            with candidates.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["arxiv_id", "selected_for_phase3"])
                writer.writeheader()
                writer.writerows([{"arxiv_id": "2401.00001", "selected_for_phase3": "yes"}, {"arxiv_id": "2401.00002", "selected_for_phase3": "yes"}])
            result = run_json(
                "write_batch_note_stubs.py",
                "--manifest",
                str(deep_manifest),
                "--template",
                "phase3-deep",
                "--candidates",
                str(candidates),
                "--output",
                str(root / "deep.md"),
                "--allow-write",
                cwd=root,
            )
            self.assertEqual(result["stubs"], 1)
            text = (root / "deep.md").read_text(encoding="utf-8")
            self.assertIn("- Note type: phase3-deep-v2", text)
            self.assertIn("2401.00001", text)
            self.assertNotIn("2401.00002", text)

    def test_final_synthesis_reports_accepted_deep_failures_without_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            row = write_inventory(root)
            phase2_root = root / "phase2_papers"
            phase2_root.mkdir()
            manifest = phase2_root / "phase3_deep_text_manifest.json"

            (root / "accepted_failures.json").write_text(
                json.dumps({"phase3_deep_text": ["2401.00001"]}),
                encoding="utf-8",
            )
            run_json(
                "write_final_synthesis.py",
                "--inventory",
                str(root / "phase1_inventory.csv"),
                "--output-dir",
                str(root),
                "--overwrite",
                "--allow-write",
                cwd=root,
            )
            accepted_only = (root / "open_questions.md").read_text(encoding="utf-8")
            self.assertIn("## Accepted deep-reading failures / warnings", accepted_only)
            self.assertIn("| 2401.00001 | accepted deep-text failure | accepted_failures.json |", accepted_only)

            manifest.write_text(
                json.dumps(
                    [
                        {**row, "status": "parse_failed", "error": "bad pdf"},
                        {**row, "arxiv_id": "2401.00002", "status": "parse_failed", "error": "missing appendix"},
                    ]
                ),
                encoding="utf-8",
            )
            run_json(
                "write_final_synthesis.py",
                "--inventory",
                str(root / "phase1_inventory.csv"),
                "--output-dir",
                str(root),
                "--overwrite",
                "--allow-write",
                cwd=root,
            )
            combined = (root / "open_questions.md").read_text(encoding="utf-8")
            self.assertIn("| 2401.00001 | bad pdf | accepted_failures.json |", combined)
            self.assertIn("| 2401.00002 | parse_failed | missing appendix |", combined)
            self.assertEqual(combined.count("2401.00001"), 1)

    def test_final_synthesis_without_accepted_failures_keeps_existing_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_inventory(root)
            run_json(
                "write_final_synthesis.py",
                "--inventory",
                str(root / "phase1_inventory.csv"),
                "--output-dir",
                str(root),
                "--overwrite",
                "--allow-write",
                cwd=root,
            )
            questions = (root / "open_questions.md").read_text(encoding="utf-8")
            self.assertNotIn("## Accepted deep-reading failures / warnings", questions)
            self.assertIn("## Phase 3 Extraction Failures", questions)

    def test_mature_project_missing_report_and_current_alias_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            row = write_inventory(root)
            (root / "phase1_report.md").unlink()
            create_ready_batch(root, row)
            state = run_json("check_workflow_state.py", "--root", str(root), cwd=root)
            self.assertEqual(state["next_action"], "write skim notes for B01")
            self.assertIn("Phase 1 report is missing", state["phase1"]["warnings"][0])

            blocked_write = subprocess.run(
                [sys.executable, "-B", str(SCRIPTS / "literature_workflow.py"), "--root", str(root), "--phase", "final"],
                cwd=str(root),
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(blocked_write.returncode, 0)
            self.assertIn("--allow-write", blocked_write.stdout)

            source_url = "https://example.com/papers"
            blocked_network = subprocess.run(
                [sys.executable, "-B", str(SCRIPTS / "literature_workflow.py"), "--root", str(root), "--phase", "phase1", "--source", source_url],
                cwd=str(root),
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(blocked_network.returncode, 0)
            self.assertIn("--allow-network", blocked_network.stdout)

    def test_helper_permissions_node_read_only_and_atomic_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            blocked = subprocess.run(
                [sys.executable, "-B", str(SCRIPTS / "scaffold_literature_project.py"), "--root", str(root)],
                cwd=str(root),
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(blocked.returncode, 0)
            self.assertIn("--allow-write", blocked.stderr)

            row = write_inventory(root)
            manifest, _pdf = create_ready_batch(root, row)
            blocked_overwrite = subprocess.run(
                [sys.executable, "-B", str(SCRIPTS / "write_batch_note_stubs.py"), "--manifest", str(manifest), "--output", str(root / "stub.md"), "--overwrite"],
                cwd=str(root),
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(blocked_overwrite.returncode, 0)
            self.assertIn("--allow-write", blocked_overwrite.stderr)
            blocked_parse_output = subprocess.run(
                [sys.executable, "-B", str(SCRIPTS / "parse_reading_notes.py"), "--notes", str(root / "missing.md"), "--output", str(root / "parsed.json")],
                cwd=str(root),
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(blocked_parse_output.returncode, 0)
            self.assertIn("--allow-write", blocked_parse_output.stderr)
            node = os.environ.get("LITFLOW_NODE", "node")
            read_only = subprocess.run(
                [node, str(SCRIPTS / "download_batch_node.mjs"), "--manifest", str(manifest), "--validate-only", "--no-status-write", "--quiet"],
                cwd=str(root),
                text=True,
                capture_output=True,
            )
            self.assertEqual(read_only.returncode, 0, read_only.stderr)
            self.assertFalse((root / "phase2_papers" / "B01_download_status.json").exists())
            blocked_download = subprocess.run(
                [node, str(SCRIPTS / "download_batch_node.mjs"), "--manifest", str(manifest), "--download", "--no-status-write", "--quiet"],
                cwd=str(root),
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(blocked_download.returncode, 0)
            self.assertIn("--allow-network", blocked_download.stderr)
            ensure_read_only = subprocess.run(
                [node, str(SCRIPTS / "ensure_raw_papers_node.mjs"), "--manifest", str(manifest), "--raw-dir", str(root / "raw_papers"), "--dry-run", "--no-status-write", "--quiet"],
                cwd=str(root),
                text=True,
                capture_output=True,
            )
            self.assertEqual(ensure_read_only.returncode, 0, ensure_read_only.stderr)
            self.assertFalse((root / "phase2_papers" / "B01_ensure_raw_status.json").exists())

            notes = root / "phase2_skim_notes.md"
            notes.write_text(complete_skim_notes(), encoding="utf-8")
            overview = root / "phase2_skim_overview.md"
            candidates = root / "phase2_deep_reading_candidates.csv"
            run_json("write_skim_overview.py", "--notes", str(notes), "--output", str(overview), "--candidates", str(candidates), "--allow-write", cwd=root)
            self.assertFalse(list(root.glob("*.tmp")))

    def test_harness_registry_v2_current_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            notes = root / "notes" / "accepted" / "B01.md"
            notes.parent.mkdir(parents=True)
            notes.write_text("# Accepted\n", encoding="utf-8")
            registry_dir = root / "batches"
            registry_dir.mkdir()
            (registry_dir / "accepted_artifacts.json").write_text(
                json.dumps(
                    {
                        "version": 2,
                        "artifacts": [
                            {
                                "type": "note",
                                "path": "notes/accepted/B01.md",
                                "batch": "B01",
                                "status": "active",
                            },
                            {
                                "type": "overview",
                                "path": "reports/accepted_overviews/missing.md",
                                "batch": "B01",
                                "status": "active",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            registry = run_json("literature_harness.py", "--root", str(root), "--action", "check-registry", cwd=root)
            self.assertEqual(registry["format"], "v2-object")
            self.assertEqual(registry["active_entries"], 2)
            self.assertTrue(any("does not exist" in item for item in registry["warnings"]))

            missing_batch_root = root / "missing_batch"
            missing_batch_root.mkdir()
            note = missing_batch_root / "note.md"
            note.write_text("# Note\n", encoding="utf-8")
            (missing_batch_root / "batches").mkdir()
            (missing_batch_root / "batches" / "accepted_artifacts.json").write_text(
                json.dumps({"version": 2, "artifacts": [{"type": "note", "path": "note.md"}]}),
                encoding="utf-8",
            )
            strict_registry = run_json("literature_harness.py", "--root", str(missing_batch_root), "--action", "check-registry", cwd=missing_batch_root)
            self.assertTrue(any("requires batch" in item for item in strict_registry["errors"]))

            phase1_root = root / "phase1_report_registry"
            phase1_root.mkdir()
            report = phase1_root / "reports" / "accepted_overviews" / "phase1_report_snapshot_test.md"
            report.parent.mkdir(parents=True)
            report.write_text("# Phase 1\n", encoding="utf-8")
            (phase1_root / "batches").mkdir()
            (phase1_root / "batches" / "accepted_artifacts.json").write_text(
                json.dumps({"version": 2, "artifacts": [{"artifact_type": "phase1_report", "type": "overview", "path": "reports/accepted_overviews/phase1_report_snapshot_test.md"}]}),
                encoding="utf-8",
            )
            phase1_registry = run_json("literature_harness.py", "--root", str(phase1_root), "--action", "check-registry", cwd=phase1_root)
            self.assertFalse(any("requires batch" in item for item in phase1_registry["errors"]))

            status = run_json("literature_harness.py", "--root", str(root), "--action", "status", cwd=root)
            self.assertEqual(status["effective_status"], "registry_available")

            partial_current_root = root / "partial_current"
            partial_current_root.mkdir()
            (partial_current_root / "inventory").mkdir()
            (partial_current_root / "inventory" / "workflow_inventory.csv").write_text("schema_version,paper_id,dedup_key,reading_batch\n", encoding="utf-8")
            partial_status = run_json("literature_harness.py", "--root", str(partial_current_root), "--action", "status", cwd=partial_current_root)
            self.assertEqual(partial_status["effective_status"], "no_accepted_registry")

    def test_harness_root_clean_context_and_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            accepted = root / "notes" / "accepted"
            accepted.mkdir(parents=True)
            (accepted / "unregistered.md").write_text("# Note\n", encoding="utf-8")
            clean = run_json("literature_harness.py", "--root", str(root), "--action", "check-root-clean", cwd=root)
            self.assertIn("notes/accepted/unregistered.md", clean["unregistered_accepted_files"])
            (root / "random_notes.md").write_text("# stray\n", encoding="utf-8")
            (root / "phase2_skim_notes.md").write_text("# non-current root file\n", encoding="utf-8")
            (root / "scratch").write_text("temporary", encoding="utf-8")
            clean = run_json("literature_harness.py", "--root", str(root), "--action", "check-root-clean", cwd=root)
            self.assertIn("random_notes.md", clean["root_unexpected_files"])
            self.assertIn("phase2_skim_notes.md", clean["unsupported_root_files"])
            self.assertIn("scratch", clean["extensionless_tmp_files"])

            body = root / "phase2_papers" / "paper.body.txt"
            body.parent.mkdir()
            body.write_text("body text", encoding="utf-8")
            packet = root / "phase2_papers" / "paper.packet.md"
            packet.write_text("packet", encoding="utf-8")
            context = run_json(
                "literature_harness.py",
                "--root",
                str(root),
                "--action",
                "check-context-budget",
                "--paths",
                "phase2_papers/paper.body.txt",
                "phase2_papers/paper.packet.md",
                cwd=root,
            )
            self.assertTrue(any("blocked" in item for item in context["errors"]))
            self.assertEqual(context["packet_count"], 1)
            inventory_csv = root / "inventory" / "workflow_inventory.csv"
            inventory_csv.parent.mkdir(exist_ok=True)
            inventory_csv.write_text("title\n" + ("x\n" * 1000), encoding="utf-8")
            context = run_json(
                "literature_harness.py",
                "--root",
                str(root),
                "--action",
                "check-context-budget",
                "--paths",
                "inventory/workflow_inventory.csv",
                cwd=root,
            )
            self.assertTrue(context["items"][0]["blocked"])
            self.assertTrue(any("blocked" in item for item in context["errors"]))

            candidates_dir = root / "inventory"
            candidates_dir.mkdir(exist_ok=True)
            candidates_path = candidates_dir / "representative_candidates.csv"
            with candidates_path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "dedup_key",
                        "item_name",
                        "verified_title",
                        "arxiv_id",
                        "canonical_url",
                        "source_host",
                        "source_type",
                        "metadata_status",
                        "reading_priority",
                        "selection_role",
                        "selection_axis",
                        "selection_reason",
                        "technical_route",
                        "source_item_ids",
                        "source_sections",
                        "duplicate_count",
                        "abstract_triage_basis",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "dedup_key": "x",
                        "item_name": "Example",
                        "verified_title": "Example",
                        "arxiv_id": "2401.00001",
                        "canonical_url": "https://arxiv.org/abs/2401.00001",
                        "source_host": "arxiv",
                        "source_type": "paper",
                        "metadata_status": "verified",
                        "reading_priority": "core_skim",
                        "selection_role": "direct_baseline",
                        "selection_axis": "objective",
                        "selection_reason": "source list and abstract indicate centrality",
                        "technical_route": "Adapters",
                        "source_item_ids": "1",
                        "source_sections": "Core",
                        "duplicate_count": "1",
                        "abstract_triage_basis": "abstract",
                    }
                )
            candidates = run_json(
                "literature_harness.py",
                "--root",
                str(root),
                "--action",
                "check-representative-candidates",
                cwd=root,
            )
            self.assertEqual(candidates["rows"], 1)
            self.assertFalse(candidates["errors"])

    def test_harness_register_artifact_append_only_and_supersede(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            note = root / "notes" / "accepted" / "B01.md"
            note.parent.mkdir(parents=True)
            note.write_text("# B01\n", encoding="utf-8")

            blocked = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(SCRIPTS / "literature_harness.py"),
                    "--root",
                    str(root),
                    "--action",
                    "register-artifact",
                    "--artifact-path",
                    "notes/accepted/B01.md",
                ],
                cwd=str(root),
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(blocked.returncode, 0)
            self.assertIn("--allow-write", blocked.stderr)

            registered = run_json(
                "literature_harness.py",
                "--root",
                str(root),
                "--action",
                "register-artifact",
                "--artifact-type",
                "note",
                "--artifact-path",
                "notes/accepted/B01.md",
                "--batch",
                "B01",
                "--allow-write",
                cwd=root,
            )
            self.assertTrue(registered["registered"])
            registry = json.loads((root / "batches" / "accepted_artifacts.json").read_text(encoding="utf-8"))
            self.assertEqual(registry["version"], 2)
            self.assertEqual(registry["artifacts"][0]["path"], "notes/accepted/B01.md")

            duplicate = run_json(
                "literature_harness.py",
                "--root",
                str(root),
                "--action",
                "register-artifact",
                "--artifact-path",
                "notes/accepted/B01.md",
                "--batch",
                "B01",
                "--allow-write",
                cwd=root,
            )
            self.assertFalse(duplicate["registered"])
            self.assertTrue(any("already registered" in item for item in duplicate["errors"]))
            missing_batch = run_json(
                "literature_harness.py",
                "--root",
                str(root),
                "--action",
                "register-artifact",
                "--artifact-type",
                "overview",
                "--artifact-path",
                "notes/accepted/B01.md",
                "--allow-write",
                cwd=root,
            )
            self.assertFalse(missing_batch["registered"])
            self.assertTrue(any("require --batch" in item for item in missing_batch["errors"]))

            replacement = root / "notes" / "accepted" / "B01-v2.md"
            replacement.write_text("# B01 v2\n", encoding="utf-8")
            superseded = run_json(
                "literature_harness.py",
                "--root",
                str(root),
                "--action",
                "register-artifact",
                "--artifact-type",
                "note",
                "--artifact-path",
                "notes/accepted/B01-v2.md",
                "--batch",
                "B01",
                "--supersedes",
                "notes/accepted/B01.md",
                "--allow-write",
                cwd=root,
            )
            self.assertTrue(superseded["registered"])
            registry = json.loads((root / "batches" / "accepted_artifacts.json").read_text(encoding="utf-8"))
            self.assertEqual(registry["artifacts"][0]["status"], "superseded")
            self.assertNotIn("quality_status", registry["artifacts"][0])
            self.assertEqual(registry["artifacts"][1]["supersedes"], ["notes/accepted/B01.md"])
            artifact_ids = [item.get("artifact_id") for item in registry["artifacts"]]
            self.assertEqual(len(artifact_ids), len(set(artifact_ids)))

            replacement.write_text("# B01 v3\n", encoding="utf-8")
            same_path_superseded = run_json(
                "literature_harness.py",
                "--root",
                str(root),
                "--action",
                "register-artifact",
                "--artifact-type",
                "note",
                "--artifact-path",
                "notes/accepted/B01-v2.md",
                "--batch",
                "B01",
                "--supersedes",
                "notes/accepted/B01-v2.md",
                "--allow-write",
                cwd=root,
            )
            self.assertTrue(same_path_superseded["registered"])
            registry = json.loads((root / "batches" / "accepted_artifacts.json").read_text(encoding="utf-8"))
            artifact_ids = [item.get("artifact_id") for item in registry["artifacts"]]
            self.assertEqual(len(artifact_ids), len(set(artifact_ids)))

            archive_plan = run_json(
                "literature_harness.py",
                "--root",
                str(root),
                "--action",
                "archive-superseded",
                "--plan-only",
                cwd=root,
            )
            self.assertTrue(archive_plan["plan_only"])
            self.assertEqual(archive_plan["moves"][0]["source"], "notes/accepted/B01.md")
            self.assertTrue((root / "notes" / "accepted" / "B01.md").exists())
            self.assertFalse((root / "archive" / "superseded_notes" / "B01.md").exists())

    def test_validate_project_ignores_superseded_same_path_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "inventory").mkdir(parents=True)
            (root / "batches").mkdir(parents=True)
            (root / "reports" / "accepted_overviews").mkdir(parents=True)
            (root / "PROJECT_STATUS.md").write_text("# Project Status\n", encoding="utf-8")
            (root / "inventory" / "conflicts.csv").write_text(
                "schema_version,conflict_id,status,severity\n",
                encoding="utf-8",
            )
            (root / "inventory" / "source_snapshot.json").write_text("{}", encoding="utf-8")
            (root / "batches" / "batch_config.csv").write_text(
                "batch_id,status\nB01,skim_complete\n",
                encoding="utf-8",
            )
            (root / "batches" / "reading_plan.md").write_text("# Reading Plan\n", encoding="utf-8")
            (root / "inventory" / "workflow_inventory.csv").write_text(
                "schema_version,paper_id,dedup_key,reading_batch\n"
                "template-v2.1,arxiv:2401.00001,arxiv:2401.00001,B01\n",
                encoding="utf-8",
            )
            (root / "inventory" / "source_items.csv").write_text(
                "schema_version,source_item_id,paper_id,source_snapshot_id\n"
                "template-v2.1,src-1,arxiv:2401.00001,snap-1\n",
                encoding="utf-8",
            )
            (root / "inventory" / "representative_candidates.csv").write_text(
                "schema_version,paper_id,selection_role,selection_axis,selection_reason\n"
                "template-v2.1,arxiv:2401.00001,core,objective,central route\n",
                encoding="utf-8",
            )
            overview = root / "reports" / "accepted_overviews" / "B01_skim_overview.md"
            overview.write_text("# first overview\n", encoding="utf-8")
            first = run_json(
                "literature_harness.py",
                "--root",
                str(root),
                "--action",
                "register-artifact",
                "--artifact-type",
                "overview",
                "--artifact-path",
                "reports/accepted_overviews/B01_skim_overview.md",
                "--batch",
                "B01",
                "--allow-write",
                cwd=root,
            )
            self.assertTrue(first["registered"])
            overview.write_text("# second overview\n", encoding="utf-8")
            second = run_json(
                "literature_harness.py",
                "--root",
                str(root),
                "--action",
                "register-artifact",
                "--artifact-type",
                "overview",
                "--artifact-path",
                "reports/accepted_overviews/B01_skim_overview.md",
                "--batch",
                "B01",
                "--review-status",
                "accepted",
                "--supersedes",
                "reports/accepted_overviews/B01_skim_overview.md",
                "--allow-write",
                cwd=root,
            )
            self.assertTrue(second["registered"])

            validation = run_json("literature_harness.py", "--root", str(root), "--action", "validate-project", cwd=root)

            self.assertEqual(validation["status"], "passed", validation)
            self.assertFalse(any("registry hash mismatch" in item for item in validation["errors"]))

    def test_template_v2_scaffold_creates_registry_layout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            completed = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(SCRIPTS / "scaffold_literature_project.py"),
                    "--root",
                    str(root),
                    "--template-v2",
                    "--allow-write",
                ],
                cwd=str(root),
                check=True,
                text=True,
                capture_output=True,
            )
            summary = eval(completed.stdout, {"__builtins__": {}})
            self.assertTrue(summary["template_v2"])
            self.assertTrue((root / "AGENTS.md").exists())
            self.assertTrue((root / "notes" / "accepted").is_dir())
            self.assertTrue((root / "reports" / "drafts").is_dir())
            self.assertTrue((root / "inventory" / "representative_candidates.csv").exists())
            self.assertTrue((root / ".gitignore").exists())
            self.assertFalse((root / "repair").exists())
            self.assertTrue((root / "archive" / "repair_history").is_dir())
            self.assertFalse((root / "phase2_skim_notes.md").exists())
            self.assertFalse((root / "phase2_skim_overview.md").exists())
            self.assertFalse((root / "phase2_deep_reading_candidates.csv").exists())
            batch_header = (root / "batches" / "batch_config.csv").read_text(encoding="utf-8").splitlines()[0]
            self.assertEqual(batch_header, "schema_version,batch_id,paper_id,technical_route,batch_goal,selection_mode,max_core_papers,microbatch_size,status,notes")
            status_text = (root / "PROJECT_STATUS.md").read_text(encoding="utf-8")
            self.assertIn("## Current Phase", status_text)
            agents_text = (root / "AGENTS.md").read_text(encoding="utf-8")
            source_section = agents_text.split("## Current-only Contract")[0]
            self.assertIn("notes/accepted/", source_section)
            self.assertNotIn("phase2_skim_notes.md", source_section)
            registry = json.loads((root / "batches" / "accepted_artifacts.json").read_text(encoding="utf-8"))
            self.assertEqual(registry["version"], 2)
            self.assertEqual(registry["artifacts"], [])
            self.assertIn("schema_version", registry)
            status = run_json("literature_harness.py", "--root", str(root), "--action", "status", cwd=root)
            self.assertEqual(status["effective_status"], "registry_initialized")

    def test_template_v2_phase2_overview_uses_accepted_batch_paths_and_registry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "inventory").mkdir(parents=True)
            (root / "batches").mkdir(parents=True)
            (root / "notes" / "accepted").mkdir(parents=True)
            (root / "inventory" / "workflow_inventory.csv").write_text(
                "\n".join([
                    "schema_version,paper_id,arxiv_id,canonical_title,reading_batch",
                    "template-v2.1,arxiv:2401.00001,2401.00001,Example Paper,B01",
                ]),
                encoding="utf-8",
            )
            accepted_note = root / "notes" / "accepted" / "B01.md"
            accepted_note.write_text(
                "\n".join([
                    "---",
                    "schema_version: template-v2.1",
                    "artifact_type: batch_skim_note",
                    "batch: B01",
                    "paper_ids:",
                    "  - arxiv:2401.00001",
                    "source_packets:",
                    "  - phase2_papers/B01_packets/B01-P01_arxiv_2401.00001.packet.md",
                    "status: accepted",
                    "---",
                    "",
                    "# B01 Skim Note",
                    "",
                    "## 1. Scope",
                    "",
                    "## 2. Coverage status",
                    "",
                    "## 3. Per-paper skim notes",
                    "",
                    "### arxiv:2401.00001 - Example Paper",
                    "",
                    "**Source packet.** `phase2_papers/B01_packets/B01-P01_arxiv_2401.00001.packet.md`  ",
                    "**Skim status.** packet-only skim; not full-paper review.",
                    "",
                    "#### 1. Problem and difficulty",
                    "- [Paper-stated] Problem: Reduce adaptation cost.",
                    "- [Paper-stated] Why hard: Full updates are costly and difficult to compare.",
                    "- [Interpretation] Why this matters: It affects efficient adaptation choices.",
                    "- Evidence: paper_id=arxiv:2401.00001, packet=B01-P01, section=Introduction",
                    "",
                    "#### 2. Motivation / Method Rationale",
                    "- [Paper-stated] Motivation: Use a focused parameter update path.",
                    "- [Paper-stated] Why existing methods are not enough: Full updates are inefficient.",
                    "- [Inferred rationale] Why this method is a natural move: A small adapter isolates the changed step.",
                    "- Evidence: paper_id=arxiv:2401.00001, packet=B01-P01, section=Method",
                    "",
                    "#### 3. Core method",
                    "- One-sentence method: Add a small trainable adapter.",
                    "- Intuitive view: Route adaptation through a lightweight branch.",
                    "- Key mechanism / changed step: KEY CHANGED STEP trains only the adapter branch.",
                    "- Compared with prior work, the main difference is: The trainable branch is isolated.",
                    "",
                    "#### 4. Method comparison diagram",
                    "<!-- method-comparison:start -->",
                    "```text",
                    "Direct baseline: Input -> full update -> Output",
                    "Representative prior: Input -> reduced update -> Output",
                    "This paper: Input -> KEY CHANGED STEP adapter update -> Output",
                    "```",
                    "<!-- method-comparison:end -->",
                    "",
                    "#### 5. Evidence and uncertainty",
                    "- Evidence available in packet: Problem, motivation, and method opening are available.",
                    "- Main uncertainty from packet-only reading: Appendix scaling remains to inspect.",
                    "",
                    "## 4. Cross-paper comparison",
                    "",
                    "## 5. Evidence pointers",
                    "",
                    "## 6. Extraction issues",
                    "",
                    "## 7. Limitations / uncertainty",
                    "",
                    "## 8. Candidate deep-reading suggestions",
                    "",
                ]),
                encoding="utf-8",
            )
            (root / "batches" / "accepted_artifacts.json").write_text(
                json.dumps(
                    {
                        "schema_version": "template-v2.1",
                        "version": 2,
                        "artifacts": [
                            {
                                "artifact_type": "batch_skim_note",
                                "type": "note",
                                "path": "notes/accepted/B01.md",
                                "batch": "B01",
                                "quality_status": "accepted",
                                "paper_ids": ["arxiv:2401.00001"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = run_json(
                "literature_workflow.py",
                "--root",
                str(root),
                "--action",
                "phase2-overview",
                "--batch",
                "B01",
                "--allow-write",
                cwd=root,
            )

            overview = root / "reports" / "accepted_overviews" / "B01_skim_overview.md"
            candidates = root / "candidates" / "accepted" / "B01_deep_reading_candidates.csv"
            self.assertTrue(overview.exists())
            self.assertTrue(candidates.exists())
            self.assertFalse((root / "phase2_skim_overview.md").exists())
            self.assertFalse((root / "phase2_deep_reading_candidates.csv").exists())
            self.assertIn("reports/accepted_overviews/B01_skim_overview.md", json.dumps(result))
            with candidates.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["paper_id"], "arxiv:2401.00001")
            self.assertEqual(rows[0]["main_problem"], "Reduce adaptation cost.")
            self.assertEqual(rows[0]["key_changed_step"], "KEY CHANGED STEP trains only the adapter branch.")
            self.assertEqual(rows[0]["read_priority"], "")
            self.assertEqual(rows[0]["selected_for_phase3"], "")
            registry = json.loads((root / "batches" / "accepted_artifacts.json").read_text(encoding="utf-8"))
            registered = {(item.get("artifact_type"), item.get("path"), item.get("batch")) for item in registry["artifacts"]}
            self.assertIn(("overview", "reports/accepted_overviews/B01_skim_overview.md", "B01"), registered)
            self.assertIn(("candidate_table", "candidates/accepted/B01_deep_reading_candidates.csv", "B01"), registered)
            state = run_json("check_workflow_state.py", "--root", str(root), cwd=root)
            self.assertNotEqual(state["next_action"], "write phase2 skim overview")

    def test_template_v2_overview_parser_reads_bold_batch_note_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            notes = root / "notes/accepted/B01.md"
            notes.parent.mkdir(parents=True)
            notes.write_text(
                "\n".join([
                    "---",
                    "schema_version: template-v2.1",
                    "artifact_type: batch_skim_note",
                    "batch: B01",
                    "paper_ids:",
                    "  - arxiv:2401.00001",
                    "source_packets:",
                    "  - phase2_papers/B01_packets/B01-P01_arxiv_2401.00001.packet.md",
                    "status: accepted",
                    "---",
                    "",
                    "# B01 Skim Note",
                    "",
                    "## 1. Scope",
                    "",
                    "## 2. Coverage status",
                    "",
                    "## 3. Per-paper skim notes",
                    "",
                    "### arxiv:2401.00001 - Example Paper",
                    "",
                    "**Basic information.** Efficient adaptation / adapter route.",
                    "",
                    "**Research problem.** [Paper-stated] Reduce adaptation cost. Evidence: paper_id=arxiv:2401.00001, packet=B01-P01, section=Introduction.",
                    "",
                    "**Method details.** Add a small trainable adapter branch. Evidence: paper_id=arxiv:2401.00001, packet=B01-P01, section=Method.",
                    "",
                    "**Computation-flow diagram.**",
                    "```text",
                    "Direct baseline",
                    "  input -> full update -> output",
                    "Representative prior",
                    "  input -> reduced update -> output",
                    "This paper",
                    "  input -> adapter update -> output",
                    "```",
                    "",
                    "**Weaknesses / assumptions.** Adapter width sensitivity.",
                    "",
                    "**Deep-read recommendation.** yes. Reason: It represents the adapter route.",
                    "",
                    "**Evidence strength.** Skim-level medium.",
                    "",
                    "## 4. Cross-paper comparison",
                    "",
                    "## 5. Extraction issues",
                    "",
                    "## 6. Limitations / uncertainty",
                    "",
                ]),
                encoding="utf-8",
            )
            overview = root / "reports/accepted_overviews/B01_skim_overview.md"
            candidates = root / "candidates/accepted/B01_deep_reading_candidates.csv"
            candidates.parent.mkdir(parents=True, exist_ok=True)
            with candidates.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=[
                    "paper_id",
                    "title",
                    "technical_route",
                    "read_priority",
                    "read_reason",
                    "first_sections_to_read",
                    "possible_gpt_question",
                    "deep_note_candidate",
                    "deep_note_reason",
                    "arxiv_id",
                    "reading_batch",
                    "recommendation",
                    "recommendation_reason",
                    "evidence_strength",
                    "selected_for_phase3",
                    "selection_notes",
                ])
                writer.writeheader()
                writer.writerow({
                    "paper_id": "arxiv:2401.00001",
                    "read_reason": "??? corrupted reason ???",
                    "deep_note_reason": "??? corrupted deep reason ???",
                    "recommendation_reason": "??? corrupted recommendation reason ???",
                    "selected_for_phase3": "yes",
                    "selection_notes": "keep user decision",
                })

            run_json("write_skim_overview.py", "--notes", str(notes), "--output", str(overview), "--candidates", str(candidates), "--allow-write", cwd=root)

            with candidates.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["technical_route"], "Efficient adaptation / adapter route.")
            self.assertEqual(rows[0]["read_priority"], "")
            self.assertEqual(rows[0]["read_reason"], "")
            self.assertEqual(rows[0]["deep_note_candidate"], "")
            self.assertEqual(rows[0]["deep_note_reason"], "")
            self.assertEqual(rows[0]["evidence_strength"], "Skim-level medium.")
            self.assertEqual(rows[0]["selected_for_phase3"], "yes")
            self.assertEqual(rows[0]["selection_notes"], "keep user decision")

    def test_template_v2_accept_draft_auto_generates_overview_and_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "inventory").mkdir(parents=True)
            (root / "batches").mkdir(parents=True)
            (root / "notes" / "drafts").mkdir(parents=True)
            (root / "phase2_papers" / "B01_packets").mkdir(parents=True)
            (root / "inventory" / "workflow_inventory.csv").write_text(
                "\n".join([
                    "schema_version,paper_id,arxiv_id,canonical_title,reading_batch",
                    "template-v2.1,arxiv:2401.00001,2401.00001,Example Paper,B01",
                ]),
                encoding="utf-8",
            )
            (root / "batches" / "accepted_artifacts.json").write_text(
                json.dumps({"schema_version": "template-v2.1", "version": 2, "artifacts": []}),
                encoding="utf-8",
            )
            (root / "phase2_papers" / "B01_packet_manifest.json").write_text(
                json.dumps(
                    {
                        "packets": [
                            {
                                "packet_id": "B01-P01",
                                "paper_id": "arxiv:2401.00001",
                                "batch": "B01",
                                "micro_batch": "MB01",
                                "packet_path": "phase2_papers/B01_packets/B01-P01_arxiv_2401.00001.packet.md",
                                "status": "created",
                                "quality_status": "pass",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (root / "phase2_papers" / "B01_packets" / "B01-P01_arxiv_2401.00001.packet.md").write_text(
                "# Evidence\n\nEnough bounded packet evidence.\n",
                encoding="utf-8",
            )
            draft = root / "notes" / "drafts" / "B01.md"
            draft.write_text(
                "\n".join([
                    "---",
                    "schema_version: template-v2.1",
                    "artifact_type: batch_skim_note",
                    "batch: B01",
                    "paper_ids:",
                    "  - arxiv:2401.00001",
                    "source_packets:",
                    "  - phase2_papers/B01_packets/B01-P01_arxiv_2401.00001.packet.md",
                    "status: draft",
                    "---",
                    "",
                    "# B01 Skim Note",
                    "",
                    "## 1. Scope",
                    "",
                    "## 2. Coverage status",
                    "",
                    "## 3. Per-paper skim notes",
                    "",
                    "### arxiv:2401.00001 - Example Paper",
                    "",
                    "**Source packet.** `phase2_papers/B01_packets/B01-P01_arxiv_2401.00001.packet.md`  ",
                    "**Skim status.** packet-only skim; not full-paper review.",
                    "",
                    "#### 1. Problem and difficulty",
                    "- [Paper-stated] Problem: Reduce adaptation cost with a focused parameter update path.",
                    "- [Paper-stated] Why hard: Full updates are expensive and obscure which component changed.",
                    "- [Interpretation] Why this matters: It supports traceable skim-level comparison.",
                    "- Evidence: paper_id=arxiv:2401.00001, packet=B01-P01, section=Introduction",
                    "",
                    "#### 2. Motivation / Method Rationale",
                    "- [Paper-stated] Motivation: Keep adaptation compact while preserving useful updates.",
                    "- [Paper-stated] Why existing methods are not enough: Full-parameter updates are inefficient.",
                    "- [Inferred rationale] Why this method is a natural move: A trainable adapter isolates the changed step.",
                    "- Evidence: paper_id=arxiv:2401.00001, packet=B01-P01, section=Method",
                    "",
                    "#### 3. Core method",
                    "- One-sentence method: Add a small trainable adapter.",
                    "- Intuitive view: Adapt through a small branch rather than the whole model.",
                    "- Key mechanism / changed step: KEY CHANGED STEP trains only the adapter branch.",
                    "- Compared with prior work, the main difference is: The adapter branch is the explicit update path.",
                    "",
                    "#### 4. Method comparison diagram",
                    "<!-- method-comparison:start -->",
                    "```text",
                    "Direct baseline: Input -> full update -> Output",
                    "Representative prior: Input -> reduced update -> Output",
                    "This paper: Input -> KEY CHANGED STEP adapter update -> Output",
                    "```",
                    "<!-- method-comparison:end -->",
                    "",
                    "#### 5. Evidence and uncertainty",
                    "- Evidence available in packet: Problem, motivation, and method opening are available.",
                    "- Main uncertainty from packet-only reading: Appendix scaling remains to inspect.",
                    "",
                    "## 4. Cross-paper comparison",
                    "",
                    "## 5. Evidence pointers",
                    "",
                    "## 6. Extraction issues",
                    "",
                    "## 7. Limitations / uncertainty",
                    "",
                    "## 8. Candidate deep-reading suggestions",
                    "",
                ]),
                encoding="utf-8",
            )

            result = run_json(
                "literature_workflow.py",
                "--root",
                str(root),
                "--action",
                "accept-draft",
                "--draft",
                "notes/drafts/B01.md",
                "--batch",
                "B01",
                "--allow-write",
                cwd=root,
            )

            self.assertEqual(result["steps"][0]["status"], "accepted")
            self.assertEqual(result["steps"][0]["overview"]["status"], "generated")
            self.assertTrue((root / "reports" / "accepted_overviews" / "B01_skim_overview.md").exists())
            self.assertTrue((root / "candidates" / "accepted" / "B01_deep_reading_candidates.csv").exists())
            self.assertFalse((root / "phase2_skim_overview.md").exists())
            self.assertFalse((root / "phase2_deep_reading_candidates.csv").exists())

    def test_harness_creates_bounded_evidence_packets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            phase2 = root / "phase2_papers"
            body_dir = phase2 / "Core" / "Adapters"
            body_dir.mkdir(parents=True)
            body = body_dir / "2401.00001.body.txt"
            body.write_text("important evidence " * 200, encoding="utf-8")
            (phase2 / "B01_manifest.json").write_text(
                json.dumps(
                    [
                        {
                            "arxiv_id": "2401.00001",
                            "title": "Packet Paper",
                            "method_category": "Adapters",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            (phase2 / "B01_body_text_manifest.json").write_text(
                json.dumps(
                    [
                        {
                            "arxiv_id": "2401.00001",
                            "body_text_path": "phase2_papers/Core/Adapters/2401.00001.body.txt",
                            "status": "exists",
                        }
                    ]
                ),
                encoding="utf-8",
            )

            blocked = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(SCRIPTS / "literature_harness.py"),
                    "--root",
                    str(root),
                    "--action",
                    "create-evidence-packets",
                    "--batch",
                    "B01",
                ],
                cwd=str(root),
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(blocked.returncode, 0)
            self.assertIn("--allow-write", blocked.stderr)

            created = run_json(
                "literature_harness.py",
                "--root",
                str(root),
                "--action",
                "create-evidence-packets",
                "--batch",
                "B01",
                "--max-packet-chars",
                "500",
                "--allow-write",
                cwd=root,
            )
            self.assertEqual(created["packet_count"], 1)
            packet_path = root / "phase2_papers" / "B01_packets" / "2401.00001.packet.md"
            self.assertTrue(packet_path.exists())
            self.assertIn("Packet truncated", packet_path.read_text(encoding="utf-8"))
            manifest = json.loads((phase2 / "B01_packet_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["packets"][0]["packet_path"], "phase2_papers/B01_packets/2401.00001.packet.md")
            self.assertTrue((root / manifest["packets"][0]["quality_path"]).exists())

    def test_harness_overview_gate_requires_registered_micro_batches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            phase2 = root / "phase2_papers"
            packet_dir = phase2 / "B01_packets"
            packet_dir.mkdir(parents=True)
            packets = []
            for idx in range(5):
                packet = packet_dir / f"2401.0000{idx + 1}.packet.md"
                packet.write_text(f"# Packet {idx + 1}\n", encoding="utf-8")
                packets.append({"packet_path": packet.relative_to(root).as_posix()})
            packet_manifest = phase2 / "B01_packet_manifest.json"
            packet_manifest.write_text(json.dumps({"version": 1, "batch": "B01", "packets": packets}), encoding="utf-8")

            notes_dir = root / "notes" / "accepted"
            notes_dir.mkdir(parents=True)
            mb01 = notes_dir / "B01-MB01.md"
            mb01.write_text("# MB01\n", encoding="utf-8")
            run_json(
                "literature_harness.py",
                "--root",
                str(root),
                "--action",
                "register-artifact",
                "--artifact-type",
                "note",
                "--artifact-path",
                "notes/accepted/B01-MB01.md",
                "--batch",
                "B01",
                "--micro-batch",
                "MB01",
                "--allow-write",
                cwd=root,
            )
            gate = run_json(
                "literature_harness.py",
                "--root",
                str(root),
                "--action",
                "check-overview-gate",
                "--batch",
                "B01",
                "--packet-manifest",
                "phase2_papers/B01_packet_manifest.json",
                "--micro-batch-size",
                "4",
                cwd=root,
            )
            self.assertFalse(gate["ready_for_overview"])
            self.assertEqual(gate["missing_micro_batches"], ["MB02"])

            mb02 = notes_dir / "B01-MB02.md"
            mb02.write_text("# MB02\n", encoding="utf-8")
            run_json(
                "literature_harness.py",
                "--root",
                str(root),
                "--action",
                "register-artifact",
                "--artifact-type",
                "note",
                "--artifact-path",
                "notes/accepted/B01-MB02.md",
                "--batch",
                "B01",
                "--micro-batch",
                "MB02",
                "--allow-write",
                cwd=root,
            )
            gate = run_json(
                "literature_harness.py",
                "--root",
                str(root),
                "--action",
                "check-overview-gate",
                "--batch",
                "B01",
                "--packet-manifest",
                "phase2_papers/B01_packet_manifest.json",
                "--micro-batch-size",
                "4",
                cwd=root,
            )
            self.assertTrue(gate["ready_for_overview"])
            self.assertFalse(gate["missing_micro_batches"])

    def test_raw_readme_cache_is_collected_and_table_titles_are_clean(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / ".codex" / "source_cache" / "raw_test"
            cache.mkdir(parents=True)
            readme = cache / "README.md"
            readme.write_text(
                """# Awesome Latent Space

<p><a href="https://arxiv.org/abs/2604.02029"><img alt="arXiv"></a></p>

## News
**[2026/04/03]** We release our survey: [Survey](https://arxiv.org/pdf/2604.02029)!

## Citation
journal={arXiv preprint arXiv:2604.02029}

## Methods
### Large-Language-Model
| Date | Paper Title | Introduction | Code |
|------|-------------|--------------|------|
| 2024/09 | ![ICLR'25](badge.svg) <br/> [Clean Table Paper](https://arxiv.org/abs/2409.08561) | <img src="img.png"> | [Github](https://github.com/example/paper) |
""",
                encoding="utf-8",
            )
            init = run_json(
                "literature_workflow.py",
                "--root",
                str(root),
                "--action",
                "init-from-awesome",
                "--source",
                str(readme),
                "--allow-write",
                cwd=root,
            )
            self.assertFalse(init["errors"])
            self.assertEqual(init["steps"][0]["papers"], 1)
            inventory_rows = read_csv_rows(root / "inventory" / "workflow_inventory.csv")
            self.assertEqual(len(inventory_rows), 1)
            self.assertEqual(inventory_rows[0]["paper_id"], "arxiv:2409.08561")
            self.assertEqual(inventory_rows[0]["canonical_title"], "Clean Table Paper")
            self.assertNotIn("2604.02029", {row["arxiv_id"] for row in inventory_rows})

    def test_zero_paper_init_reports_warning_when_source_has_paper_links(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "awesome.md"
            source.write_text(
                """# Awesome

## News
- [Ignored outside Methods](https://arxiv.org/abs/2401.01614)

## Methods
""",
                encoding="utf-8",
            )
            init = run_json(
                "literature_workflow.py",
                "--root",
                str(root),
                "--action",
                "init-from-awesome",
                "--source",
                str(source),
                "--allow-write",
                cwd=root,
            )
            self.assertEqual(init["steps"][0]["papers"], 0)
            self.assertTrue(any("0 papers" in warning for warning in init["steps"][0]["warnings"]))

    def test_github_repo_source_prefers_raw_readme_before_clone(self) -> None:
        harness = load_awesome_harness()

        class Args:
            source = "https://github.com/example/awesome-papers"
            allow_network = True

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b"# Awesome\n\n- [Paper](https://arxiv.org/abs/2401.01614)\n"

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch.object(harness.urllib.request, "urlopen", return_value=FakeResponse()) as urlopen:
                with mock.patch.object(harness.subprocess, "run") as subprocess_run:
                    base, commit, included = harness.fetch_or_collect_source(Args(), root)

            self.assertEqual(commit, "")
            self.assertEqual(included, [])
            self.assertTrue((base / "README.md").exists())
            self.assertIn("/main/README.md", urlopen.call_args[0][0].full_url)
            subprocess_run.assert_not_called()

if __name__ == "__main__":
    unittest.main()
