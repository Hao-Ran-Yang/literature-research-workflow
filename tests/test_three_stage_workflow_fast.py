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


class ThreeStageWorkflowFastTests(unittest.TestCase):
    def test_unsupported_root_state_and_final_paths_are_not_current_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_inventory(root)
            (root / "phase2_reading_notes.md").write_text(non_current_notes(), encoding="utf-8")
            (root / "phase2_skim_notes.md").write_text(complete_skim_notes(), encoding="utf-8")
            state = run_json("check_workflow_state.py", "--root", str(root), cwd=root)
            self.assertEqual(state["workflow_mode"], "three_stage")
            self.assertNotIn("unsupported_root_workflow_files", state.get("batches", {}))

            run_json("literature_workflow.py", "--root", str(root), "--action", "final", "--allow-write", cwd=root)
            parsed_final = json.loads((root / "phase2_reading_notes.parsed.json").read_text(encoding="utf-8"))
            self.assertEqual(parsed_final["summary"]["paper_entries"], 0)

    def test_quality_parser_rejects_removed_skim_stub_template_and_merges_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            row = write_inventory(root)
            manifest, _pdf = create_ready_batch(root, row)
            rejected = subprocess.run(
                [sys.executable, "-B", str(SCRIPTS / "write_batch_note_stubs.py"), "--manifest", str(manifest), "--template", "phase2-skim", "--output", str(root / "empty_skim.md"), "--allow-write"],
                cwd=str(root),
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("invalid choice", rejected.stderr)

            notes = root / "phase2_skim_notes.md"
            notes.write_text(complete_skim_notes(), encoding="utf-8")
            quality = run_json(
                "check_notes_quality.py",
                "--notes",
                str(notes),
                "--batch-heading",
                "B01 Skim Notes",
                "--expected",
                "1",
                cwd=root,
            )
            self.assertEqual(quality["passed"], 0)
            self.assertIn("current note type phase3-deep-v2", quality["needs_review"][0]["missing"])

    def test_check_batch_quality_uses_template_v2_accepted_skim_note(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            row = write_inventory(root)
            create_ready_batch(root, row)
            accepted = root / "notes" / "accepted" / "B01.md"
            accepted.parent.mkdir(parents=True)
            accepted.write_text(
                complete_skim_notes().replace(
                    "# Phase 2 Skim Notes\n\n## B01 Skim Notes",
                    "# Phase 2 Skim Notes\n\n## 1. Scope\n\nBatch summary.\n\n## 2. Per-paper skim notes",
                ),
                encoding="utf-8",
            )
            registry = root / "batches" / "accepted_artifacts.json"
            registry.parent.mkdir(parents=True)
            registry.write_text(
                json.dumps(
                    {
                        "version": 2,
                        "artifacts": [
                            {
                                "artifact_type": "batch_skim_note",
                                "type": "note",
                                "path": "notes/accepted/B01.md",
                                "batch": "B01",
                                "quality_status": "accepted",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            checked = run_json(
                "literature_workflow.py",
                "--root",
                str(root),
                "--action",
                "check-batch",
                "--batch",
                "B01",
                "--check-notes-quality",
                cwd=root,
            )

            self.assertFalse(any("phase2_skim_notes.md" in warning for warning in checked["warnings"]))
            self.assertFalse(any("no notes heading found" in warning for warning in checked["warnings"]))
            self.assertTrue(checked["steps"])
            quality = json.loads(checked["steps"][0]["stdout"])
            self.assertEqual(quality["batch_heading"], "2. Per-paper skim notes")
            self.assertTrue(quality["count_ok"])

    def test_deep_quality_accepts_current_v2_and_rejects_non_current_note(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_inventory(root)
            deep = root / "phase3_deep_notes.md"
            deep.write_text(complete_deep_v2_notes(), encoding="utf-8")
            deep_quality = run_json(
                "check_notes_quality.py",
                "--notes",
                str(deep),
                "--batch-heading",
                "B01 Phase 3 Selected Deep Reading",
                "--expected",
                "1",
                cwd=root,
            )
            self.assertEqual(deep_quality["passed"], 1, deep_quality)
            deep_parsed = run_json("parse_reading_notes.py", "--notes", str(deep), cwd=root)
            self.assertEqual(deep_parsed["papers"][0]["note_format"], "phase3-deep-v2")

            non_current = root / "non_current_deep.md"
            non_current.write_text(complete_deep_notes(), encoding="utf-8")
            non_current_quality = run_json(
                "check_notes_quality.py",
                "--notes",
                str(non_current),
                "--batch-heading",
                "B01 Phase 3 Selected Deep Reading",
                "--expected",
                "1",
                cwd=root,
            )
            self.assertEqual(non_current_quality["passed"], 0)
            self.assertIn("current note type phase3-deep-v2", non_current_quality["needs_review"][0]["missing"])

    def test_phase3_deep_v2_contract_quality_parser_and_v1_compatibility(self) -> None:
        template = (SKILL_ROOT / "templates" / "notes" / "phase3_deep_note.md").read_text(encoding="utf-8")
        self.assertIn("- Note type: phase3-deep-v2", template)
        for field in ["Baseline components", "Changed component", "Ours components"]:
            self.assertNotIn(f"- {field}:", template)
        self.assertIn("| Aspect | Direct baseline | Representative prior | This paper |", template)
        self.assertIn("```text", template)
        self.assertIn("Direct baseline", template)
        self.assertIn("Representative prior", template)
        self.assertIn("This paper", template)
        self.assertIn("KEY CHANGED STEP", template)
        self.assertNotIn("```mermaid", template)
        self.assertIn("| Claimed benefit |", template)
        self.assertIn("### 4. Claim-Evidence-Risk-Use table", template)
        self.assertIn("### 5. Decision-critical evidence and appendix-aware findings", template)
        self.assertIn("- Reproduction-critical dataset details:", template)
        self.assertIn("- What is suggestive but not proven:", template)
        self.assertIn("- Initial reading decision:", template)
        self.assertIn("- Final reading decision:", template)
        self.assertNotIn("- Reading decision:", template)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_inventory(root)
            v2 = root / "v2_deep.md"
            v2.write_text(complete_deep_v2_notes(), encoding="utf-8")
            quality = run_json(
                "check_notes_quality.py",
                "--notes",
                str(v2),
                "--batch-heading",
                "B01 Phase 3 Selected Deep Reading",
                "--expected",
                "1",
                cwd=root,
            )
            self.assertEqual(quality["passed"], 1, quality)
            parsed = run_json("parse_reading_notes.py", "--notes", str(v2), cwd=root)
            paper = parsed["papers"][0]
            self.assertEqual(paper["note_format"], "phase3-deep-v2")
            self.assertEqual(paper["core_contribution"], "Train a residual adapter branch.")
            self.assertEqual(paper["problem_statement"], "Can adaptation cost be reduced?")
            self.assertEqual(paper["core_idea_summary"], "Train a residual adapter branch.")
            self.assertEqual(paper["optimization"], "Update adapter parameters.")
            self.assertEqual(paper["inference_flow"], "Run base model with adapter.")
            self.assertEqual(paper["follow_up_experiment"], "Sweep adapter width.")
            self.assertEqual(paper["initial_reading_decision"], "Reproduce one task.")
            self.assertEqual(paper["final_reading_decision"], "Build on the controlled result only.")
            self.assertEqual(paper["claim_evidence_risks"][0]["my_verdict_or_use"], "Reliable enough for a small reproduction")
            self.assertEqual(paper["deep_method_comparison"][0]["direct_baseline"], "Full-model update")
            (root / "phase3_deep_notes.md").write_text(complete_deep_v2_notes(), encoding="utf-8")
            write_accepted_registry(root, [{
                "type": "note",
                "artifact_type": "phase3_deep_note",
                "path": "phase3_deep_notes.md",
                "batch": "B01",
                "paper_ids": ["arxiv:2401.00001"],
            }])
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
            parsed_final = json.loads((root / "phase2_reading_notes.parsed.json").read_text(encoding="utf-8"))
            self.assertEqual(parsed_final["papers"][0]["note_format"], "phase3-deep-v2")
            literature_map = (root / "final_literature_map.md").read_text(encoding="utf-8")
            self.assertIn("## Selected Deep Research Judgments", literature_map)
            self.assertIn("Train a residual adapter branch.", literature_map)
            self.assertIn("## Selected Deep Method Comparisons", literature_map)
            self.assertIn("| 1. Example Paper | 2401.00001 | Core operation | Full-model update | Reduced update path | Adapter update |", literature_map)
            opportunities = (root / "research_opportunities.md").read_text(encoding="utf-8")
            self.assertIn("Limited model scale.; Base features transfer.", opportunities)

    def test_phase3_deep_v2_no_prior_and_verbose_mermaid_advisory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def quality_missing(markdown: str) -> list[str]:
                notes = root / "deep.md"
                notes.write_text(markdown, encoding="utf-8")
                quality = run_json(
                    "check_notes_quality.py",
                    "--notes",
                    str(notes),
                    "--batch-heading",
                    "B01 Phase 3 Selected Deep Reading",
                    "--expected",
                    "1",
                    cwd=root,
                )
                return quality["needs_review"][0]["missing"] if quality["needs_review"] else []

            no_prior = complete_deep_v2_notes().replace(
                "Representative prior\n"
                "  [Input] -> [Reduced update path] -> [Output]\n\n",
                "N/A: no representative prior identified. Reason: benchmark-only protocol.\n\n",
            )
            no_prior = no_prior.replace(" | Reduced update path | ", " | N/A | ")
            no_prior = no_prior.replace(" | Restricted update path | ", " | N/A | ")
            no_prior = no_prior.replace(" | Limited flexibility | ", " | N/A | ")
            no_prior = no_prior.replace(" | Restrict updates | ", " | N/A | ")
            no_prior = no_prior.replace(" | Lower cost | ", " | N/A | ")
            no_prior = no_prior.replace(" | Restricted updates | ", " | N/A | ")
            self.assertEqual(quality_missing(no_prior), [])

            no_prior_blank = no_prior.replace(" | N/A | ", " |  | ")
            self.assertIn("direct baseline / representative prior / this paper comparison content", quality_missing(no_prior_blank))

            no_prior_without_reason = no_prior.replace(". Reason: benchmark-only protocol.", ".")
            self.assertIn("Deep diagram no-prior reason", quality_missing(no_prior_without_reason))

            verbose_mermaid = complete_deep_v2_notes().replace(
                "```text\n"
                "Direct baseline\n"
                "  [Input] -> [Full-model update] -> [Output]\n\n"
                "Representative prior\n"
                "  [Input] -> [Reduced update path] -> [Output]\n\n"
                "This paper\n"
                "  [Input] -> [KEY CHANGED STEP: adapter update] -> [Output]\n"
                "```",
                "```mermaid\n"
                "flowchart LR\n"
                "  subgraph baseline[\"Direct baseline\"]\n"
                "    B1[\"Input\"] --> B2[\"Full-model update\"] --> B3[\"Output\"]\n"
                "  end\n"
                "  subgraph prior[\"Representative prior\"]\n"
                "    P1[\"Input\"] --> P2[\"Reduced update path\"] --> P3[\"Output\"]\n"
                "  end\n"
                "  subgraph ours[\"This paper\"]\n"
                "    O1[\"Input\"] --> O2[\"KEY CHANGED STEP: adapter update<br/>Claimed benefit: lower cost<br/>Remaining weakness: width sensitivity\"] --> O3[\"Output\"]\n"
                "  end\n"
                "```",
            )
            self.assertIn("Deep Mermaid nodes should stay computation-flow focused", quality_missing(verbose_mermaid))

            missing_verdict = complete_deep_v2_notes().replace(
                "| Adapters reduce cost | supported | Table 1 | Hardware effects may vary | Reliable enough for a small reproduction |",
                "| Adapters reduce cost | supported | Table 1 | Hardware effects may vary | |",
            )
            self.assertIn("Claim-Evidence-Risk-Use content", quality_missing(missing_verdict))

            wrong_header = complete_deep_v2_notes().replace(
                "| Aspect | Direct baseline | Representative prior | This paper |",
                "| Aspect | This paper | Unrelated method | Direct baseline |",
            )
            self.assertIn("deep three-way diagram comparison table", quality_missing(wrong_header))

            speculative_table = complete_deep_v2_notes().replace(
                "| Claimed benefit | Flexible adaptation | Lower cost | Lower adaptation cost |",
                "| Claimed benefit | Flexible adaptation | Lower cost | Enables latent search mechanism |",
            )
            self.assertIn("Unsupported diagram claims need verification", quality_missing(speculative_table))

            self.assertEqual(quality_missing(complete_deep_v2_notes()), [])

    def test_non_current_note_formats_are_not_current_parser_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            v2 = root / "v2.md"
            v2.write_text(v2_notes(), encoding="utf-8")
            parsed_v2 = run_json("parse_reading_notes.py", "--notes", str(v2), cwd=root)
            self.assertEqual(parsed_v2["papers"][0]["note_format"], "unknown")
            self.assertTrue(parsed_v2["papers"][0]["quality_flags"]["needs_review"])

            completed = subprocess.run(
                [sys.executable, "-B", str(SCRIPTS / "literature_workflow.py"), "--root", str(root), "--action", "phase2-skim", "--plan-only"],
                cwd=str(root),
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("invalid choice", completed.stderr)

    def test_root_non_current_notes_do_not_contribute_to_current_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_inventory(root)
            (root / "phase2_reading_notes.md").write_text("# Non-current\n\n#### Paper\n- arXiv: 2401.00001\n", encoding="utf-8")
            state = run_json("check_workflow_state.py", "--root", str(root), cwd=root)
            self.assertEqual(state["workflow_mode"], "three_stage")
            self.assertEqual(state["batches"]["B01"]["effective_notes_entries"], 0)
            self.assertNotIn("root_notes_entries", state["batches"]["B01"])

    def test_hybrid_notes_do_not_inflate_skim_completion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = write_inventory(root)
            rows = []
            for index in range(1, 4):
                row = dict(base)
                row["arxiv_id"] = f"2401.0000{index}"
                row["title"] = f"Paper {index}"
                row["reading_batch"] = "B01 Mixed"
                rows.append(row)
            write_inventory_rows(root, rows)
            (root / "phase2_skim_notes.md").write_text("# Skim\n\n#### Paper 1\n- arXiv: 2401.00001\n", encoding="utf-8")
            (root / "phase2_reading_notes.md").write_text("# Non-current\n\n#### Paper 2\n- arXiv: 2401.00002\n", encoding="utf-8")
            (root / "phase3_deep_notes.md").write_text("# Deep\n\n#### Paper 3\n- arXiv: 2401.00003\n", encoding="utf-8")
            state = run_json("check_workflow_state.py", "--root", str(root), cwd=root)
            self.assertEqual(state["batches"]["B01"]["status"], "skim_started")
            self.assertEqual(state["batches"]["B01"]["notes_entries"], 1)
            self.assertFalse(state["phase2"]["skim_complete"])

    def test_accepted_phase3_failure_warns_without_deep_completion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_inventory(root)
            (root / "phase2_skim_notes.md").write_text(complete_skim_notes(), encoding="utf-8")
            (root / "phase2_skim_overview.md").write_text("# Overview\n\nComplete.\n", encoding="utf-8")
            with (root / "phase2_deep_reading_candidates.csv").open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["arxiv_id", "selected_for_phase3"])
                writer.writeheader()
                writer.writerow({"arxiv_id": "2401.00001", "selected_for_phase3": "yes"})
            (root / "accepted_failures.json").write_text(json.dumps({"phase3_deep_text": ["2401.00001"]}), encoding="utf-8")
            state = run_json("check_workflow_state.py", "--root", str(root), cwd=root)
            self.assertEqual(state["phase3"]["status"], "accepted_failures_only")
            self.assertEqual(state["phase3"]["accepted_failure_entries"], 1)
            self.assertFalse(state["phase3"]["deep_complete"])
            self.assertTrue(state["phase3"]["can_continue_final_with_warnings"])
            self.assertIn("review phase3 failures", state["next_action"])
            self.assertTrue(state["phase3"]["warnings"])

    def test_check_batch_quality_ignores_root_non_current_notes_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_inventory(root)
            (root / "phase2_reading_notes.md").write_text(non_current_notes(), encoding="utf-8")
            checked = run_json(
                "literature_workflow.py", "--root", str(root), "--action", "check-batch", "--batch", "B01", "--check-notes-quality", cwd=root
            )
            serialized = json.dumps(checked)
            self.assertNotIn("phase2_reading_notes.md", serialized)
            self.assertIn("notes file not found", serialized)

    def test_strict_quality_rejects_current_deep_unchecked_appendix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            deep = root / "deep.md"
            deep.write_text(complete_deep_v2_notes().replace("- Appendix checked: yes", "- Appendix checked: no"), encoding="utf-8")
            deep_quality = run_json(
                "check_notes_quality.py",
                "--notes",
                str(deep),
                "--batch-heading",
                "B01 Phase 3 Selected Deep Reading",
                "--expected",
                "1",
                cwd=root,
            )
            self.assertIn("Appendix checked must be yes or justified not applicable", deep_quality["needs_review"][0]["missing"])

    def test_current_deep_v2_diagram_quality_rules_are_targeted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            counter = 0

            def missing_for(markdown: str) -> list[str]:
                nonlocal counter
                counter += 1
                notes = root / f"deep_{counter}.md"
                notes.write_text(markdown, encoding="utf-8")
                quality = run_json(
                    "check_notes_quality.py",
                    "--notes",
                    str(notes),
                    "--batch-heading",
                    "B01 Phase 3 Selected Deep Reading",
                    "--expected",
                    "1",
                    cwd=root,
                )
                return quality["needs_review"][0]["missing"] if quality["needs_review"] else []

            missing_role = complete_deep_v2_notes().replace("Representative prior", "Related prior")
            self.assertIn("Deep diagram baseline / prior / this paper", missing_for(missing_role))

            missing_table = complete_deep_v2_notes().replace("| Remaining weakness | High adaptation cost | Restricted updates | Adapter width sensitivity |\n", "")
            self.assertIn("direct baseline / representative prior / this paper comparison content", missing_for(missing_table))

            too_many_auxiliary = complete_deep_v2_notes() + "\n### Training-to-Inference Diagram\n\n### System Architecture Diagram\n"
            self.assertIn("at most one auxiliary diagram", missing_for(too_many_auxiliary))

    def test_skim_template_keeps_current_canonical_blocks(self) -> None:
        template = (SKILL_ROOT / "templates" / "notes" / "phase2_skim_note.md").read_text(encoding="utf-8")
        self.assertIn("#### 2. Motivation / Method Rationale", template)
        self.assertIn("[Inferred rationale] Why this method is a natural move", template)
        self.assertIn("Evidence: paper_id={paper_id}, packet={packet_id}, section={section_hint}", template)
        self.assertIn("<!-- method-comparison:start -->", template)
        self.assertIn("<!-- method-comparison:end -->", template)

    def test_current_deep_v2_diagram_metadata_needs_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            deep_review = root / "deep_review.md"
            deep_review.write_text(complete_deep_v2_notes().replace("- Diagram verification: verified", "- Diagram verification: needs review"), encoding="utf-8")
            quality = run_json(
                "check_notes_quality.py",
                "--notes",
                str(deep_review),
                "--batch-heading",
                "B01 Phase 3 Selected Deep Reading",
                "--expected",
                "1",
                cwd=root,
            )
            self.assertIn("Diagram verification must be verified", quality["needs_review"][0]["missing"])

if __name__ == "__main__":
    unittest.main()
