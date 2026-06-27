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
LITERATURE_HARNESS = ROOT / "scripts" / "literature_harness.py"
PREPARE_EXTRACT = ROOT / "scripts" / "prepare_batch_manifest_extract.py"
WRITE_STUBS = ROOT / "scripts" / "write_batch_note_stubs.py"
CHECK_NOTES_QUALITY = ROOT / "scripts" / "check_notes_quality.py"
WRITE_SKIM_OVERVIEW = ROOT / "scripts" / "write_skim_overview.py"


def load_harness():
    scripts = str(ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    spec = importlib.util.spec_from_file_location("awesome_literature_harness_project_tests", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_literature_harness():
    scripts = str(ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    spec = importlib.util.spec_from_file_location("literature_harness_project_tests", LITERATURE_HARNESS)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_prepare_extract():
    scripts = str(ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    spec = importlib.util.spec_from_file_location("prepare_extract_project_tests", PREPARE_EXTRACT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_write_stubs():
    scripts = str(ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    spec = importlib.util.spec_from_file_location("write_stubs_project_tests", WRITE_STUBS)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_check_notes_quality():
    scripts = str(ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    spec = importlib.util.spec_from_file_location("check_notes_quality_project_tests", CHECK_NOTES_QUALITY)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_write_skim_overview():
    scripts = str(ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    spec = importlib.util.spec_from_file_location("write_skim_overview_project_tests", WRITE_SKIM_OVERVIEW)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def write_v2_inventory(root: Path, rows: list[dict]) -> None:
    inventory = root / "inventory/workflow_inventory.csv"
    inventory.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "schema_version",
        "paper_id",
        "arxiv_id",
        "canonical_title",
        "public_pdf_url",
        "reading_batch",
        "pdf_status",
        "local_pdf_path",
    ]
    with inventory.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_packet(root: Path, packet_id: str, paper_id: str, micro_batch: str) -> dict:
    rel = f"phase2_papers/B01_packets/{packet_id}_{paper_id.replace(':', '_')}.packet.md"
    packet_path = root / rel
    packet_path.parent.mkdir(parents=True, exist_ok=True)
    packet_path.write_text("# Evidence\n\n" + ("Abstract\nEnough evidence text.\n" * 80), encoding="utf-8")
    return {
        "packet_id": packet_id,
        "paper_id": paper_id,
        "batch": "B01",
        "micro_batch": micro_batch,
        "packet_path": rel,
        "quality_status": "pass",
        "status": "created",
    }


def write_packet_manifest(root: Path, batch: str, paper_ids: list[str]) -> None:
    packet_dir = root / "phase2_papers" / f"{batch}_packets"
    packet_dir.mkdir(parents=True, exist_ok=True)
    packets = []
    for idx, paper_id in enumerate(paper_ids, start=1):
        packet_id = f"{batch}-P{idx:02d}"
        safe_paper_id = paper_id.replace(":", "_").replace("/", "_")
        rel = f"phase2_papers/{batch}_packets/{packet_id}_{safe_paper_id}.packet.md"
        (root / rel).write_text(
            "\n".join(
                [
                    f"# Evidence Packet {packet_id}",
                    "",
                    f"- packet_id: {packet_id}",
                    f"- paper_id: {paper_id}",
                    "- section_hint: Introduction/Method",
                    "- char_range: 0-1200",
                    "",
                    "## Evidence",
                    ("Problem, motivation, method, and uncertainty evidence for the synthetic paper. " * 20),
                ]
            ),
            encoding="utf-8",
        )
        packets.append(
            {
                "packet_id": packet_id,
                "paper_id": paper_id,
                "batch": batch,
                "micro_batch": f"MB{idx:02d}",
                "packet_path": rel,
                "section_hint": "Introduction/Method",
                "char_range": "0-1200",
                "quality_status": "pass",
                "status": "created",
            }
        )
    write_json(root / "phase2_papers" / f"{batch}_packet_manifest.json", {"schema_version": "template-v2.1", "batch": batch, "packets": packets})
    write_json(
        root / "phase2_papers" / f"{batch}_manifest.json",
        {
            "schema_version": "template-v2.1",
            "batch": batch,
            "papers": [{"schema_version": "template-v2.1", "paper_id": paper_id, "packet_status": "created"} for paper_id in paper_ids],
        },
    )


def canonical_entry(paper_id: str, title: str, packet_id: str, *, extra: list[str] | None = None, marker: bool = True) -> str:
    diagram = [
        "<!-- method-comparison:start -->",
        "```text",
        "Direct baseline: Input -> direct route -> Output",
        "Representative prior: Input -> prior route -> Output",
        "This paper: Input -> KEY CHANGED STEP -> Output",
        "```",
        "<!-- method-comparison:end -->",
    ] if marker else [
        "```text",
        "Direct baseline: Input -> direct route -> Output",
        "Representative prior: Input -> prior route -> Output",
        "This paper: Input -> KEY CHANGED STEP -> Output",
        "```",
    ]
    return "\n".join(
        [
            f"### {paper_id} - {title}",
            "",
            f"**Source packet.** `phase2_papers/B01_packets/{packet_id}.packet.md`  ",
            "**Skim status.** packet-only skim; not full-paper review.",
            "",
            "#### 1. Problem and difficulty",
            "- [Paper-stated] Problem: The paper addresses a concrete synthetic problem with enough paper-specific detail.",
            "- [Paper-stated] Why hard: The packet says the direct route lacks a stable intermediate representation.",
            "- [Interpretation] Why this matters: It affects fast comparison across papers.",
            f"- Evidence: paper_id={paper_id}, packet={packet_id}, section=Introduction",
            "",
            "#### 2. Motivation / Method Rationale",
            "- [Paper-stated] Motivation: The packet motivates a compact latent-style method.",
            "- [Paper-stated] Why existing methods are not enough: Existing direct methods do not expose the changed step.",
            "- [Inferred rationale] Why this method is a natural move: A bounded representation makes the comparison auditable.",
            f"- Evidence: paper_id={paper_id}, packet={packet_id}, section=Introduction/Method",
            "",
            "#### 3. Core method",
            "- One-sentence method: Replace the direct route with a changed intermediate step.",
            "- Intuitive view: Add a small inspected middle step before the output.",
            "- Key mechanism / changed step: KEY CHANGED STEP.",
            "- Compared with prior work, the main difference is: The changed step is explicit in the computation flow.",
            "",
            "#### 4. Method comparison diagram",
            *diagram,
            "",
            "#### 5. Evidence and uncertainty",
            "- Evidence available in packet: Problem, motivation, method opening, and uncertainty are present.",
            "- Main uncertainty from packet-only reading: Exact ablation evidence is not available in packet.",
            *(extra or []),
        ]
    )


def canonical_batch_note(root: Path, batch: str, paper_ids: list[str], entries: list[str]) -> Path:
    draft = root / "notes" / "drafts" / f"{batch}.md"
    draft.parent.mkdir(parents=True, exist_ok=True)
    source_packets = [f"phase2_papers/{batch}_packets/{batch}-P{idx:02d}_{paper_id.replace(':', '_').replace('/', '_')}.packet.md" for idx, paper_id in enumerate(paper_ids, start=1)]
    draft.write_text(
        "\n".join(
            [
                "---",
                "schema_version: template-v2.1",
                "artifact_type: batch_skim_note",
                f"batch: {batch}",
                "paper_ids:",
                *[f"  - {paper_id}" for paper_id in paper_ids],
                "source_packets:",
                *[f"  - {path}" for path in source_packets],
                "status: draft",
                "---",
                "",
                f"# {batch} Skim Note",
                "",
                "## 1. Scope",
                "",
                "## 2. Coverage status",
                "",
                "## 3. Per-paper skim notes",
                "",
                *entries,
                "",
                "## 4. Cross-paper comparison",
                "",
                "## 5. Extraction issues",
                "",
                "## 6. Limitations / uncertainty",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return draft


def write_managed_pdf(root: Path, paper_id: str) -> str:
    rel = f"phase2_papers/managed_pdfs/{paper_id.replace(':', '_')}.pdf"
    pdf = root / rel
    pdf.parent.mkdir(parents=True, exist_ok=True)
    pdf.write_bytes(b"%PDF-1.4\n%test\n%%EOF\n")
    return rel


class Phase2BatchGateTests(unittest.TestCase):
    def test_accept_draft_uses_manifest_expected_full_batch_not_draft_frontmatter(self) -> None:
        harness = load_harness()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paper_ids = ["arxiv:2401.00001", "arxiv:2401.00002"]
            write_packet_manifest(root, "B01", paper_ids)
            draft = canonical_batch_note(
                root,
                "B01",
                ["arxiv:2401.00001"],
                [canonical_entry("arxiv:2401.00001", "Only First Paper", "B01-P01")],
            )

            result = harness.accept_draft(SimpleNamespace(root=str(root), batch="B01", draft=str(draft.relative_to(root)), micro_batch="", force=False, allow_write=True))

            self.assertEqual(result["status"], "failed")
            self.assertIn("missing expected paper: arxiv:2401.00002", "\n".join(result["errors"]))

    def test_accept_draft_rejects_missing_canonical_method_marker(self) -> None:
        harness = load_harness()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paper_ids = ["arxiv:2401.00001"]
            write_packet_manifest(root, "B01", paper_ids)
            draft = canonical_batch_note(
                root,
                "B01",
                paper_ids,
                [canonical_entry("arxiv:2401.00001", "No Marker Paper", "B01-P01", marker=False)],
            )

            result = harness.accept_draft(SimpleNamespace(root=str(root), batch="B01", draft=str(draft.relative_to(root)), micro_batch="", force=False, allow_write=True))

            self.assertEqual(result["status"], "failed")
            self.assertIn("missing method-comparison marker: arxiv:2401.00001", "\n".join(result["errors"]))

    def test_accept_draft_rejects_noncanonical_paper_heading(self) -> None:
        harness = load_harness()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paper_ids = ["arxiv:2401.00001"]
            write_packet_manifest(root, "B01", paper_ids)
            entry = canonical_entry("arxiv:2401.00001", "Canonical Paper", "B01-P01").replace(
                "### arxiv:2401.00001 - Canonical Paper",
                "### arxiv:2401.00001",
            )
            draft = canonical_batch_note(root, "B01", paper_ids, [entry])

            result = harness.accept_draft(SimpleNamespace(root=str(root), batch="B01", draft=str(draft.relative_to(root)), micro_batch="", force=False, allow_write=True))

            self.assertEqual(result["status"], "failed")
            self.assertIn("missing canonical heading: arxiv:2401.00001", "\n".join(result["errors"]))

    def test_accept_draft_rejects_empty_title_and_duplicate_canonical_heading(self) -> None:
        harness = load_harness()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paper_ids = ["arxiv:2401.00001"]
            write_packet_manifest(root, "B01", paper_ids)
            empty_title = canonical_entry("arxiv:2401.00001", "Canonical Paper", "B01-P01").replace(
                "### arxiv:2401.00001 - Canonical Paper",
                "### arxiv:2401.00001 - ",
            )
            empty_draft = canonical_batch_note(root, "B01", paper_ids, [empty_title])

            empty_result = harness.accept_draft(SimpleNamespace(root=str(root), batch="B01", draft=str(empty_draft.relative_to(root)), micro_batch="", force=False, allow_write=True))

            self.assertEqual(empty_result["status"], "failed")
            self.assertIn("missing canonical heading: arxiv:2401.00001", "\n".join(empty_result["errors"]))

            duplicate_draft = canonical_batch_note(
                root,
                "B01",
                paper_ids,
                [
                    canonical_entry("arxiv:2401.00001", "Canonical Paper", "B01-P01"),
                    canonical_entry("arxiv:2401.00001", "Duplicate Paper", "B01-P01"),
                ],
            )

            duplicate_result = harness.accept_draft(SimpleNamespace(root=str(root), batch="B01", draft=str(duplicate_draft.relative_to(root)), micro_batch="", force=True, allow_write=True))

            self.assertEqual(duplicate_result["status"], "failed")
            self.assertIn("duplicate canonical heading: arxiv:2401.00001", "\n".join(duplicate_result["errors"]))

    def test_accept_draft_exact_heading_supports_openreview_and_doi_ids(self) -> None:
        harness = load_harness()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paper_ids = ["openreview:abc123", "doi:10.5555/foo_bar.v1"]
            write_packet_manifest(root, "B01", paper_ids)
            draft = canonical_batch_note(
                root,
                "B01",
                paper_ids,
                [
                    canonical_entry("openreview:abc123", "OpenReview Paper", "B01-P01"),
                    canonical_entry("doi:10.5555/foo_bar.v1", "DOI Paper", "B01-P02"),
                ],
            )

            result = harness.accept_draft(SimpleNamespace(root=str(root), batch="B01", draft=str(draft.relative_to(root)), micro_batch="", force=False, allow_write=True))

            self.assertEqual(result["status"], "accepted", result)

    def test_accept_draft_warns_but_accepts_historical_recommendation_fields(self) -> None:
        harness = load_harness()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paper_ids = ["arxiv:2401.00001"]
            write_packet_manifest(root, "B01", paper_ids)
            draft = canonical_batch_note(
                root,
                "B01",
                paper_ids,
                [
                    canonical_entry(
                        "arxiv:2401.00001",
                        "Historical Field Paper",
                        "B01-P01",
                        extra=["- Deep-read recommendation: yes", "- Read priority: high"],
                    )
                ],
            )

            result = harness.accept_draft(SimpleNamespace(root=str(root), batch="B01", draft=str(draft.relative_to(root)), micro_batch="", force=False, allow_write=True))

            self.assertEqual(result["status"], "accepted", result)
            self.assertIn("historical_recommendation_fields", result.get("warning_codes", []))

    def test_run_next_microbatch_task_injects_canonical_block_and_full_batch_contract(self) -> None:
        harness = load_harness()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paper_ids = ["arxiv:2401.00001", "arxiv:2401.00002"]
            write_packet_manifest(root, "B01", paper_ids)

            result = harness.run_next_microbatch(SimpleNamespace(root=str(root), batch="B01", allow_partial_skim=True, allow_write=True))

            self.assertEqual(result["status"], "ready", result)
            task_text = (root / result["task_file"]).read_text(encoding="utf-8")
            self.assertIn("### arxiv:2401.00001 - arxiv:2401.00001", task_text)
            self.assertIn("#### 1. Problem and difficulty", task_text)
            self.assertIn("#### 5. Evidence and uncertainty", task_text)
            self.assertIn("<!-- method-comparison:start -->", task_text)
            self.assertIn("Direct baseline", task_text)
            self.assertIn("Representative prior", task_text)
            self.assertIn("This paper", task_text)
            self.assertIn("KEY CHANGED STEP", task_text)
            self.assertIn("`status: ready` means continue now", task_text)
            self.assertIn("Do not stop after reporting that this micro-batch is ready", task_text)
            self.assertIn("Micro-batches are writing units only", task_text)
            self.assertIn("`accept-draft` is a full-batch gate", task_text)
            self.assertIn("`notes/accepted/**`", task_text)
            self.assertIn("`phase2_papers/**/*.body.txt`", task_text)
            self.assertNotIn("large CSV tables", task_text)
            draft_text = (root / result["draft_target"]).read_text(encoding="utf-8")
            self.assertIn("  - arxiv:2401.00001", draft_text)
            self.assertIn("  - arxiv:2401.00002", draft_text)

    def test_two_microbatches_share_one_draft_and_accept_only_after_full_batch(self) -> None:
        harness = load_harness()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paper_ids = ["arxiv:2401.00001", "arxiv:2401.00002"]
            write_packet_manifest(root, "B01", paper_ids)

            first = harness.run_next_microbatch(SimpleNamespace(root=str(root), batch="B01", allow_partial_skim=True, allow_write=True))
            self.assertEqual(first["status"], "ready", first)
            self.assertEqual(first["micro_batch"], "MB01")

            draft = canonical_batch_note(
                root,
                "B01",
                paper_ids,
                [canonical_entry("arxiv:2401.00001", "First Paper", "B01-P01")],
            )
            partial_accept = harness.accept_draft(SimpleNamespace(root=str(root), batch="B01", draft=str(draft.relative_to(root)), micro_batch="", force=False, allow_write=True))
            self.assertEqual(partial_accept["status"], "failed")
            self.assertIn("arxiv:2401.00002", "\n".join(partial_accept["errors"]))

            second = harness.run_next_microbatch(SimpleNamespace(root=str(root), batch="B01", allow_partial_skim=True, allow_write=True))
            self.assertEqual(second["status"], "ready", second)
            self.assertEqual(second["micro_batch"], "MB02")
            self.assertEqual(second["draft_target"], "notes/drafts/B01.md")

            canonical_batch_note(
                root,
                "B01",
                paper_ids,
                [
                    canonical_entry("arxiv:2401.00001", "First Paper", "B01-P01"),
                    canonical_entry("arxiv:2401.00002", "Second Paper", "B01-P02"),
                ],
            )
            full_accept = harness.accept_draft(SimpleNamespace(root=str(root), batch="B01", draft=str(draft.relative_to(root)), micro_batch="", force=False, allow_write=True))
            self.assertEqual(full_accept["status"], "accepted", full_accept)

    def test_skim_overview_v2_parser_uses_canonical_entries_and_preserves_manual_selection(self) -> None:
        overview = load_write_skim_overview()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            notes = canonical_batch_note(
                root,
                "B01",
                ["arxiv:2401.00001"],
                [canonical_entry("arxiv:2401.00001", "Canonical Paper", "B01-P01")],
            )
            markdown = notes.read_text(encoding="utf-8")
            papers = overview.split_notes(markdown)
            self.assertEqual(len(papers), 1)
            self.assertEqual(papers[0]["paper_id"], "arxiv:2401.00001")
            self.assertEqual(papers[0]["title"], "Canonical Paper")
            self.assertIn("synthetic problem", papers[0]["main_problem"])
            self.assertIn("KEY CHANGED STEP", papers[0]["key_changed_step"])

            candidates = root / "candidates.csv"
            with candidates.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["paper_id", "selected_for_phase3", "selection_notes", "read_priority"])
                writer.writeheader()
                writer.writerow({"paper_id": "arxiv:2401.00001", "selected_for_phase3": "yes", "selection_notes": "manual", "read_priority": "high"})
            rows = overview.write_candidates(candidates, papers)
            self.assertEqual(rows[0]["selected_for_phase3"], "yes")
            self.assertEqual(rows[0]["selection_notes"], "manual")
            self.assertEqual(rows[0]["read_priority"], "high")
            self.assertEqual(rows[0]["deep_note_candidate"], "")

    def test_numbered_section_headings_count_as_structure(self) -> None:
        harness = load_harness()
        text = "\n".join([
            "Title",
            "1 Introduction",
            "This section introduces the problem.",
            "2. Methodology",
            "This section explains the method.",
            "3 Experiments",
            "This section reports evaluation.",
            "4 Discussion and Limitations",
            "This section discusses limits.",
            "5 Conclusion",
            "This section concludes.",
            "body " * 250,
        ])

        quality = harness.assess_body_text_quality(text)

        self.assertEqual(quality["quality_status"], "pass")
        self.assertIn("introduction", quality["section_hits"])
        self.assertIn("method", quality["section_hits"])
        self.assertIn("experiments", quality["section_hits"])
        self.assertIn("conclusion", quality["section_hits"])

    def test_current_b01_layout_variants_are_not_low_quality(self) -> None:
        harness = load_harness()
        ids = ["2412.06769", "2412.17747", "2502.08524", "2502.16280"]
        for arxiv_id in ids:
            body = ROOT / "phase2_papers" / "body_text" / f"arxiv_{arxiv_id}.body.txt"
            if not body.exists():
                self.skipTest(f"project fixture missing: {body}")
            with self.subTest(arxiv_id=arxiv_id):
                quality = harness.assess_body_text_quality(body.read_text(encoding="utf-8", errors="replace"))
                self.assertEqual(quality["quality_status"], "pass")

    def test_section_packet_prioritizes_intro_and_conclusion_over_related_work_and_experiments(self) -> None:
        harness = load_harness()
        text = "\n\n".join([
            "Abstract\nABSTRACT-MARKER " + ("abstract evidence. " * 80),
            "1 Introduction\nINTRO-START " + ("introduction motivation and method rationale. " * 260) + " INTRO-END",
            "2 Related Work\nRELATED-WORK-MARKER " + ("related work should not consume skim packet budget. " * 220),
            "3 Method\nMETHOD-OPENING-MARKER " + ("method opening detail. " * 260),
            "4 Experiments\nEXPERIMENT-MARKER " + ("experiment detail. " * 220),
            "5 Conclusion\nCONCLUSION-MARKER " + ("conclusion limitation and takeaway. " * 80),
            "References\n[1] Example.",
        ])

        packet_text, metadata = harness.build_section_aware_packet(text, 12000)
        section_names = [section["name"] for section in metadata["selected_sections"]]

        self.assertLessEqual(len(packet_text), 12000)
        self.assertEqual(metadata["packet_strategy"], "intro_method_conclusion_v1")
        self.assertIn("ABSTRACT-MARKER", packet_text)
        self.assertIn("INTRO-START", packet_text)
        self.assertIn("CONCLUSION-MARKER", packet_text)
        self.assertIn("METHOD-OPENING-MARKER", packet_text)
        self.assertNotIn("RELATED-WORK-MARKER", packet_text)
        self.assertNotIn("EXPERIMENT-MARKER", packet_text)
        self.assertIn("abstract", section_names)
        self.assertIn("introduction", section_names)
        self.assertIn("method", section_names)
        self.assertIn("conclusion", section_names)

    def test_packet_manifest_records_packet_strategy_and_selected_sections(self) -> None:
        harness = load_harness()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            body = root / "phase2_papers/body_text/arxiv_2401.00001.body.txt"
            body.parent.mkdir(parents=True, exist_ok=True)
            body.write_text(
                "\n\n".join([
                    "Abstract\nA compact abstract.",
                    "Introduction\n" + ("intro motivation. " * 500),
                    "Related Work\n" + ("related work. " * 300),
                    "Method\nMETHOD-OPENING-MARKER " + ("method. " * 400),
                    "Experiments\n" + ("experiments. " * 300),
                    "Conclusion\nCONCLUSION-MARKER " + ("conclusion. " * 100),
                ]),
                encoding="utf-8",
            )

            packet = harness.write_packet_for_body(
                root,
                "B01",
                {"paper_id": "arxiv:2401.00001"},
                body,
                1,
                {"quality_status": "pass", "body_chars": body.stat().st_size, "warnings": []},
            )
            packet_text = (root / packet["packet_path"]).read_text(encoding="utf-8")

            self.assertEqual(packet["packet_strategy"], "intro_method_conclusion_v1")
            self.assertIn("selected_sections", packet)
            self.assertIn("abstract", [section["name"] for section in packet["selected_sections"]])
            self.assertIn("- packet_strategy: intro_method_conclusion_v1", packet_text)
            self.assertIn("- selected_sections:", packet_text)
            self.assertIn("CONCLUSION-MARKER", packet_text)

    def test_missing_pdf_report_lists_download_links_and_missing_metadata(self) -> None:
        harness = load_harness()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / "raw_papers"
            raw.mkdir(parents=True)
            (raw / "arxiv_2401_00001.pdf").write_bytes(b"%PDF-" + b"x" * 200)
            write_v2_inventory(
                root,
                [
                    {
                        "schema_version": "template-v2.1",
                        "paper_id": "arxiv:2401.00001",
                        "arxiv_id": "2401.00001",
                        "canonical_title": "Already Local",
                        "public_pdf_url": "https://arxiv.org/pdf/2401.00001.pdf",
                        "reading_batch": "B01",
                        "pdf_status": "available_remote",
                    },
                    {
                        "schema_version": "template-v2.1",
                        "paper_id": "arxiv:2401.00002",
                        "arxiv_id": "2401.00002",
                        "canonical_title": "Needs Download",
                        "public_pdf_url": "https://arxiv.org/pdf/2401.00002.pdf",
                        "reading_batch": "B01",
                        "pdf_status": "available_remote",
                    },
                    {
                        "schema_version": "template-v2.1",
                        "paper_id": "local:missing",
                        "arxiv_id": "",
                        "canonical_title": "Missing Metadata",
                        "public_pdf_url": "",
                        "reading_batch": "B01",
                        "pdf_status": "pdf_unavailable",
                    },
                ],
            )

            report = harness.build_missing_pdf_report(root, "B01")

            self.assertEqual(report["missing_count"], 2)
            missing_ids = {item["paper_id"] for item in report["missing_pdfs"]}
            self.assertNotIn("arxiv:2401.00001", missing_ids)
            self.assertIn("arxiv:2401.00002", missing_ids)
            self.assertIn("local:missing", missing_ids)
            self.assertIn("https://arxiv.org/pdf/2401.00002.pdf", report["human_report"])
            self.assertIn("下载链接: 缺失，需要补 metadata 或人工查找", report["human_report"])
            self.assertIn("raw_papers/ 和 managed_pdfs/ 中未发现本地 PDF", report["human_report"])

    def test_run_next_microbatch_blocks_when_batch_has_missing_pdf(self) -> None:
        harness = load_harness()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            local_pdf = write_managed_pdf(root, "arxiv:2401.00001")
            write_json(root / "phase2_papers/B01_manifest.json", {
                "papers": [
                    {"paper_id": "arxiv:2401.00001", "pdf_status": "imported_local", "packet_status": "created", "local_pdf_path": local_pdf},
                    {
                        "paper_id": "arxiv:2401.00002",
                        "canonical_title": "Missing PDF",
                        "pdf_status": "available_remote",
                        "packet_status": "skipped_no_text",
                        "public_pdf_url": "https://arxiv.org/pdf/2401.00002.pdf",
                    },
                ]
            })
            write_json(root / "phase2_papers/B01_body_text_manifest.json", {"bodies": []})
            packet = write_packet(root, "B01-P01", "arxiv:2401.00001", "MB01")
            write_json(root / "phase2_papers/B01_packet_manifest.json", {"packets": [packet]})

            result = harness.run_next_microbatch(SimpleNamespace(root=str(root), batch="B01", allow_write=True))

            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["reason"], "batch_not_ready")
            self.assertEqual(result["missing_pdfs"][0]["paper_id"], "arxiv:2401.00002")
            self.assertIn("human_report", result)
            self.assertIn("https://arxiv.org/pdf/2401.00002.pdf", result["human_report"])

    def test_run_next_microbatch_blocks_when_batch_has_low_quality_text(self) -> None:
        harness = load_harness()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            local_pdf_1 = write_managed_pdf(root, "arxiv:2401.00001")
            local_pdf_2 = write_managed_pdf(root, "arxiv:2401.00002")
            write_json(root / "phase2_papers/B01_manifest.json", {
                "papers": [
                    {"paper_id": "arxiv:2401.00001", "pdf_status": "imported_local", "packet_status": "created", "local_pdf_path": local_pdf_1},
                    {
                        "paper_id": "arxiv:2401.00002",
                        "canonical_title": "Low Quality",
                        "pdf_status": "imported_local",
                        "packet_status": "blocked_no_valid_text",
                        "local_pdf_path": local_pdf_2,
                        "public_pdf_url": "https://arxiv.org/pdf/2401.00002.pdf",
                    },
                ]
            })
            write_json(root / "phase2_papers/B01_body_text_manifest.json", {
                "bodies": [
                    {
                        "paper_id": "arxiv:2401.00002",
                        "quality_status": "low_quality",
                        "section_hits": ["method"],
                        "warnings": ["missing_abstract_or_introduction", "insufficient_section_structure"],
                    }
                ]
            })
            packet = write_packet(root, "B01-P01", "arxiv:2401.00001", "MB01")
            write_json(root / "phase2_papers/B01_packet_manifest.json", {"packets": [packet]})

            result = harness.run_next_microbatch(SimpleNamespace(root=str(root), batch="B01", allow_write=True))

            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["reason"], "batch_not_ready")
            self.assertEqual(result["low_quality"][0]["paper_id"], "arxiv:2401.00002")

    def test_accepted_coverage_is_by_paper_not_only_microbatch(self) -> None:
        harness = load_harness()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            local_pdf_1 = write_managed_pdf(root, "arxiv:2401.00001")
            local_pdf_2 = write_managed_pdf(root, "arxiv:2401.00002")
            write_json(root / "phase2_papers/B01_manifest.json", {
                "papers": [
                    {"paper_id": "arxiv:2401.00001", "pdf_status": "imported_local", "packet_status": "created", "local_pdf_path": local_pdf_1},
                    {"paper_id": "arxiv:2401.00002", "pdf_status": "imported_local", "packet_status": "created", "local_pdf_path": local_pdf_2},
                ]
            })
            write_json(root / "phase2_papers/B01_body_text_manifest.json", {
                "bodies": [
                    {"paper_id": "arxiv:2401.00001", "quality_status": "pass"},
                    {"paper_id": "arxiv:2401.00002", "quality_status": "pass"},
                ]
            })
            packets = [
                write_packet(root, "B01-P01", "arxiv:2401.00001", "MB01"),
                write_packet(root, "B01-P02", "arxiv:2401.00002", "MB01"),
            ]
            write_json(root / "phase2_papers/B01_packet_manifest.json", {"packets": packets})
            write_json(root / "batches/accepted_artifacts.json", {
                "schema_version": "template-v2.1",
                "version": 2,
                "artifacts": [
                    {
                        "artifact_type": "micro_batch_skim_note",
                        "batch": "B01",
                        "micro_batch": "MB01",
                        "paper_ids": ["arxiv:2401.00001"],
                        "status": "accepted",
                        "path": "notes/accepted/B01-MB01.md",
                    }
                ],
            })

            result = harness.run_next_microbatch(SimpleNamespace(root=str(root), batch="B01", allow_write=True))

            self.assertEqual(result["status"], "ready")
            self.assertEqual(result["micro_batch"], "MB01")
            self.assertEqual(result["paper_ids"], ["arxiv:2401.00002"])
            self.assertEqual(result["draft_target"], "notes/drafts/B01.md")
            draft = root / "notes/drafts/B01.md"
            self.assertTrue(draft.exists())
            self.assertIn("artifact_type: batch_skim_note", draft.read_text(encoding="utf-8"))
            task = (root / ".codex/tasks/B01-MB01.task.md").read_text(encoding="utf-8")
            self.assertIn("## Canonical per-paper block", task)
            self.assertIn("#### 2. Motivation / Method Rationale", task)
            self.assertIn("`accept-draft` is a full-batch gate", task)

    def test_batch_skim_note_acceptance_and_coverage(self) -> None:
        harness = load_harness()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            canonical_batch_note(
                root,
                "B01",
                ["arxiv:2401.00001"],
                [canonical_entry("arxiv:2401.00001", "Test Paper", "B01-P01")],
            )

            result = harness.accept_draft(SimpleNamespace(root=str(root), batch="B01", draft="notes/drafts/B01.md", micro_batch="", force=False, allow_write=True))

            self.assertEqual(result["status"], "accepted")
            self.assertEqual(result["accepted_note"], "notes/accepted/B01.md")
            self.assertEqual(harness.accepted_paper_ids(root, "B01"), {"arxiv:2401.00001"})

    def test_accept_draft_updates_visible_accepted_status_text(self) -> None:
        harness = load_harness()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            canonical_batch_note(
                root,
                "B01",
                ["arxiv:2401.00001"],
                [canonical_entry("arxiv:2401.00001", "Test Paper", "B01-P01")],
            )
            draft = root / "notes/drafts/B01.md"
            draft_text = draft.read_text(encoding="utf-8")
            draft.write_text(
                draft_text.replace(
                    "## 1. Scope",
                    "- Accepted status: not accepted. Run `accept-draft` only after all pass-quality packets are represented.\n\n## 1. Scope",
                ),
                encoding="utf-8",
            )

            result = harness.accept_draft(SimpleNamespace(root=str(root), batch="B01", draft="notes/drafts/B01.md", micro_batch="", force=False, allow_write=True))

            self.assertEqual(result["status"], "accepted", result)
            accepted = (root / "notes/accepted/B01.md").read_text(encoding="utf-8")
            self.assertIn("- Accepted status: accepted.", accepted)
            self.assertNotIn("Accepted status: not accepted", accepted)

    def test_batch_skim_note_accepts_embedded_evidence_without_tail_sections(self) -> None:
        harness = load_harness()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            canonical_batch_note(
                root,
                "B01",
                ["arxiv:2401.00001"],
                [canonical_entry("arxiv:2401.00001", "Test Paper", "B01-P01")],
            )

            result = harness.accept_draft(SimpleNamespace(root=str(root), batch="B01", draft="notes/drafts/B01.md", micro_batch="", force=False, allow_write=True))

            self.assertEqual(result["status"], "accepted", result)
            accepted = (root / "notes/accepted/B01.md").read_text(encoding="utf-8")
            self.assertNotIn("## 5. Evidence pointers", accepted)
            self.assertNotIn("Candidate deep-reading suggestions", accepted)

    def test_batch_skim_note_still_requires_per_paper_embedded_evidence(self) -> None:
        harness = load_harness()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft = root / "notes/drafts/B01.md"
            draft.parent.mkdir(parents=True, exist_ok=True)
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
                    "### arxiv:2401.00001 - Test Paper",
                    "",
                    "**Research problem.** This section deliberately omits the machine-readable local evidence pointer while providing enough prose to avoid failing only on length.",
                    "",
                    "**Core idea.** It has substantial content but no embedded paper_id evidence marker, so the coverage gate should reject it.",
                    "",
                    "**Method details.** The note describes a method in enough words to pass the minimum subsection length check, but the required evidence pointer is absent.",
                    "",
                    "**Computation-flow diagram.**",
                    "```text",
                    "Direct baseline",
                    "  input -> baseline output",
                    "Representative prior",
                    "  input -> prior output",
                    "This paper",
                    "  input -> proposed method -> output",
                    "```",
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

            result = harness.accept_draft(SimpleNamespace(root=str(root), batch="B01", draft="notes/drafts/B01.md", micro_batch="", force=False, allow_write=True))

            self.assertEqual(result["status"], "failed")
            self.assertIn("missing paper evidence pointer: arxiv:2401.00001", result["errors"])

    def test_batch_skim_note_rejects_question_mark_encoding_corruption(self) -> None:
        harness = load_harness()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft = root / "notes/drafts/B01.md"
            draft.parent.mkdir(parents=True, exist_ok=True)
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
                    "A normal English question? This should remain allowed.",
                    "",
                    "## 2. Coverage status",
                    "All planned papers are covered.",
                    "",
                    "## 3. Per-paper skim notes",
                    "",
                    "### arxiv:2401.00001 - Corrupted Paper",
                    "",
                    "**Basic information.** Test route.",
                    "",
                    "**Research problem.** ???? ????? ???? ????? ???? ????? ???? Evidence: paper_id=arxiv:2401.00001, packet=B01-P01, section=Introduction.",
                    "",
                    "**Core idea.** The paper is unreadable because non-ASCII text was replaced by question marks.",
                    "",
                    "**Motivation / Method Rationale.**",
                    "- [Paper-stated] ????? ????? ?????.",
                    "- [Interpretation] ????? ????? ?????.",
                    "",
                    "**Method details.** ???? ????? ???? ????? ???? ????? ???? Evidence: paper_id=arxiv:2401.00001, packet=B01-P01, section=Method.",
                    "",
                    "**Computation-flow diagram.**",
                    "```text",
                    "Direct baseline",
                    "  input -> baseline output",
                    "",
                    "Representative prior",
                    "  input -> prior reasoning trace -> output",
                    "",
                    "This paper",
                    "  input -> corrupted note -> candidate table",
                    "```",
                    "",
                    "**Weaknesses / assumptions.** The note body has enough length but its prose is corrupted by question marks.",
                    "",
                    "**Deep-read recommendation.** maybe. Reason: this field is structurally parseable despite corruption.",
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

            result = harness.accept_draft(SimpleNamespace(root=str(root), batch="B01", draft="notes/drafts/B01.md", micro_batch="", force=False, allow_write=True))

            self.assertEqual(result["status"], "failed", result)
            self.assertIn("possible question-mark encoding corruption", "\n".join(result["errors"]))

    def test_batch_skim_note_rejects_repeated_generic_motivation(self) -> None:
        harness = load_harness()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repeated = "\n".join([
                "- [Paper-stated] Motivation: The paper positions latent computation as a way to move beyond direct reasoning.",
                "- [Paper-stated] Why existing methods are not enough: Prior direct methods do not allocate enough internal computation.",
                "- [Inferred rationale] If the bottleneck is visible-token cost or shallow computation, then an internal reasoning state can provide additional compute.",
            ])
            entries = [
                canonical_entry("arxiv:2401.00001", "Template Paper 1", "B01-P01").replace(
                    "- [Paper-stated] Motivation: The packet motivates a compact latent-style method.\n- [Paper-stated] Why existing methods are not enough: Existing direct methods do not expose the changed step.\n- [Inferred rationale] Why this method is a natural move: A bounded representation makes the comparison auditable.",
                    repeated,
                ),
                canonical_entry("arxiv:2401.00002", "Template Paper 2", "B01-P02").replace(
                    "- [Paper-stated] Motivation: The packet motivates a compact latent-style method.\n- [Paper-stated] Why existing methods are not enough: Existing direct methods do not expose the changed step.\n- [Inferred rationale] Why this method is a natural move: A bounded representation makes the comparison auditable.",
                    repeated,
                ),
            ]
            canonical_batch_note(
                root,
                "B01",
                ["arxiv:2401.00001", "arxiv:2401.00002"],
                entries,
            )

            result = harness.accept_draft(SimpleNamespace(root=str(root), batch="B01", draft="notes/drafts/B01.md", micro_batch="", force=False, allow_write=True))

            self.assertEqual(result["status"], "accepted", result)
            self.assertIn("generic_motivation_review", result["warning_codes"])

    def test_batch_skim_note_rejects_stale_microbatch_scope(self) -> None:
        harness = load_harness()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft = canonical_batch_note(
                root,
                "B01",
                ["arxiv:2401.00001"],
                [canonical_entry("arxiv:2401.00001", "Template Paper", "B01-P01")],
            )
            text = draft.read_text(encoding="utf-8")
            draft.write_text(
                text.replace(
                    "## 1. Scope\n\n## 2. Coverage status",
                    "## 1. Scope\n\nThis is a packet-only Phase 2 skim note for B01. Current coverage: MB01 only, covering 1 of 4 B01 papers.\n\n## 2. Coverage status",
                ),
                encoding="utf-8",
            )

            result = harness.accept_draft(SimpleNamespace(root=str(root), batch="B01", draft="notes/drafts/B01.md", micro_batch="", force=False, allow_write=True))

            self.assertEqual(result["status"], "failed", result)
            self.assertIn("stale micro-batch coverage statement in Scope", "\n".join(result["errors"]))

    def test_batch_skim_note_warns_on_dense_cross_paper_comparison(self) -> None:
        harness = load_harness()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft = canonical_batch_note(
                root,
                "B01",
                ["arxiv:2401.00001"],
                [canonical_entry("arxiv:2401.00001", "Template Paper", "B01-P01")],
            )
            dense = (
                "Across this batch, the comparison is deliberately written as one dense paragraph "
                "without bullets. It has enough length to be hard to scan for a reader, and the "
                "workflow should flag it for review while still accepting the mechanically valid "
                "batch note because this is a presentation-quality issue rather than a coverage "
                "or evidence-integrity failure."
            )
            text = draft.read_text(encoding="utf-8")
            draft.write_text(
                text.replace(
                    "## 4. Cross-paper comparison\n\n## 5. Extraction issues",
                    f"## 4. Cross-paper comparison\n\n{dense}\n\n## 5. Extraction issues",
                ),
                encoding="utf-8",
            )

            result = harness.accept_draft(SimpleNamespace(root=str(root), batch="B01", draft="notes/drafts/B01.md", micro_batch="", force=False, allow_write=True))

            self.assertEqual(result["status"], "accepted", result)
            self.assertIn("dense_cross_paper_comparison", result["warning_codes"])

    def test_batch_skim_note_rejects_method_details_that_are_reading_todos(self) -> None:
        harness = load_harness()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            entry = canonical_entry("arxiv:2401.00001", "Todo Paper", "B01-P01").replace(
                "- Key mechanism / changed step: KEY CHANGED STEP.",
                "- Key mechanism / changed step: TODO need full paper.",
            )
            canonical_batch_note(
                root,
                "B01",
                ["arxiv:2401.00001"],
                [entry],
            )

            result = harness.accept_draft(SimpleNamespace(root=str(root), batch="B01", draft="notes/drafts/B01.md", micro_batch="", force=False, allow_write=True))

            self.assertEqual(result["status"], "failed", result)
            self.assertIn("note contains TODO/placeholder text", "\n".join(result["errors"]))

    def test_batch_skim_note_rejects_migration_placeholder(self) -> None:
        harness = load_harness()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft = root / "notes/drafts/B01.md"
            draft.parent.mkdir(parents=True, exist_ok=True)
            draft.write_text(
                "\n".join([
                    "---",
                    "schema_version: template-v2.1",
                    "artifact_type: batch_skim_note",
                    "batch: B01",
                    "paper_ids:",
                    "  - arxiv:2411.04282",
                    "source_packets:",
                    "  - phase2_papers/B01_packets/B01-P05_arxiv_2411.04282.packet.md",
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
                    "### arxiv:2411.04282 - Language Models are Hidden Reasoners",
                    "",
                    "[Needs verification] Existing accepted note did not expose a parseable per-paper subsection during migration.",
                    "",
                    "Evidence: paper_id=arxiv:2411.04282, packet=B01-P05, section=packet.",
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

            result = harness.accept_draft(SimpleNamespace(root=str(root), batch="B01", draft="notes/drafts/B01.md", micro_batch="", force=False, allow_write=True))

            self.assertEqual(result["status"], "failed")
            self.assertIn("note contains migration placeholder text", result["errors"])
            self.assertIn("placeholder per-paper subsection: arxiv:2411.04282", result["errors"])

    def test_batch_skim_note_requires_paper_id_in_subsection_heading(self) -> None:
        harness = load_harness()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft = root / "notes/drafts/B01.md"
            draft.parent.mkdir(parents=True, exist_ok=True)
            draft.write_text(
                "\n".join([
                    "---",
                    "schema_version: template-v2.1",
                    "artifact_type: batch_skim_note",
                    "batch: B01",
                    "paper_ids:",
                    "  - arxiv:2411.04282",
                    "source_packets:",
                    "  - phase2_papers/B01_packets/B01-P05_arxiv_2411.04282.packet.md",
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
                    "#### 1. Language Models are Hidden Reasoners",
                    "",
                    "- arXiv: 2411.04282",
                    "- Problem: This section has useful text but the heading itself is not traceable by paper id.",
                    "- Core idea: It resembles a non-current micro-batch section and should be manually or mechanically converted before batch acceptance.",
                    "- Method sketch: The model samples rationales, scores them by answer likelihood, and updates toward high-quality latent reasoning.",
                    "- Evidence strength: medium at skim level, from a bounded packet rather than a full deep read.",
                    "- Deep-read recommendation: yes, high priority for objective construction and self-rewarding post-training.",
                    "",
                    "Evidence: paper_id=arxiv:2411.04282, packet=B01-P05, section=packet.",
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

            result = harness.accept_draft(SimpleNamespace(root=str(root), batch="B01", draft="notes/drafts/B01.md", micro_batch="", force=False, allow_write=True))

            self.assertEqual(result["status"], "failed")
            self.assertIn("missing canonical heading: arxiv:2411.04282", result["errors"])

    def test_batch_skim_note_accepts_twenty_traceable_papers(self) -> None:
        harness = load_harness()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paper_ids = [f"arxiv:2401.{idx:05d}" for idx in range(1, 21)]
            canonical_batch_note(
                root,
                "B01",
                paper_ids,
                [
                    canonical_entry(paper_id, f"Synthetic Paper {idx}", f"B01-P{idx:02d}")
                    for idx, paper_id in enumerate(paper_ids, start=1)
                ],
            )

            result = harness.accept_draft(SimpleNamespace(root=str(root), batch="B01", draft="notes/drafts/B01.md", micro_batch="", force=False, allow_write=True))

            self.assertEqual(result["status"], "accepted")
            self.assertEqual(harness.accepted_paper_ids(root, "B01"), set(paper_ids))

    def test_overview_gate_uses_batch_note_paper_coverage(self) -> None:
        literature_harness = load_literature_harness()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet_1 = write_packet(root, "B01-P01", "arxiv:2401.00001", "MB01")
            packet_2 = write_packet(root, "B01-P02", "arxiv:2401.00002", "MB01")
            write_json(root / "phase2_papers/B01_packet_manifest.json", {"packets": [packet_1, packet_2]})
            accepted = root / "notes/accepted/B01.md"
            accepted.parent.mkdir(parents=True, exist_ok=True)
            accepted.write_text("# B01\n", encoding="utf-8")
            write_json(root / "batches/accepted_artifacts.json", {
                "version": 2,
                "artifacts": [
                    {
                        "type": "note",
                        "artifact_type": "batch_skim_note",
                        "path": "notes/accepted/B01.md",
                        "batch": "B01",
                        "quality_status": "accepted",
                        "paper_ids": ["arxiv:2401.00001", "arxiv:2401.00002"],
                    }
                ],
            })

            result = literature_harness.check_overview_gate(root, "B01", "phase2_papers/B01_packet_manifest.json", 4)

            self.assertTrue(result["ready_for_overview"])
            self.assertEqual(result["missing_paper_ids"], [])

    def test_phase3_selection_accepts_v2_candidate_table_registry_shape(self) -> None:
        harness = load_harness()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidates = root / "candidates/accepted/B01_deep_reading_candidates.csv"
            candidates.parent.mkdir(parents=True, exist_ok=True)
            candidates.write_text(
                "\n".join([
                    "paper_id,title,batch,selected_for_phase3",
                    "arxiv:2401.00001,Selected Paper,B01,yes",
                    "arxiv:2401.00002,Rejected Paper,B01,no",
                ]),
                encoding="utf-8",
            )
            write_json(root / "batches/accepted_artifacts.json", {
                "version": 2,
                "artifacts": [
                    {
                        "type": "candidate_table",
                        "path": "candidates/accepted/B01_deep_reading_candidates.csv",
                        "quality_status": "accepted",
                        "batch": "B01",
                    }
                ],
            })

            result = harness.check_phase3_selection(SimpleNamespace(root=str(root), batch="B01"))

            self.assertEqual(result["status"], "ready")
            self.assertEqual(result["count"], 1)
            self.assertEqual(result["selected_paper_ids"], ["arxiv:2401.00001"])
            self.assertEqual(result["candidate_path"], "candidates/accepted/B01_deep_reading_candidates.csv")

    def test_phase3_selected_rows_support_paper_id_only_candidate_table_and_v2_manifest(self) -> None:
        prepare = load_prepare_extract()
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            phase2 = project / "phase2_papers"
            pdf = phase2 / "managed_pdfs/arxiv_2401.00001.pdf"
            pdf.parent.mkdir(parents=True, exist_ok=True)
            pdf.write_bytes(b"%PDF-1.4\n" + (b"0" * 12000) + b"\n%%EOF\n")
            write_json(phase2 / "B01_manifest.json", {
                "schema_version": "template-v2.1",
                "batch": "B01",
                "papers": [
                    {
                        "paper_id": "arxiv:2401.00001",
                        "canonical_title": "Selected Paper",
                        "local_pdf_path": "phase2_papers/managed_pdfs/arxiv_2401.00001.pdf",
                    },
                    {
                        "paper_id": "arxiv:2401.00002",
                        "canonical_title": "Not Selected",
                        "local_pdf_path": "phase2_papers/managed_pdfs/arxiv_2401.00002.pdf",
                    },
                ],
            })
            inventory = project / "inventory/workflow_inventory.csv"
            inventory.parent.mkdir(parents=True, exist_ok=True)
            inventory.write_text("paper_id,arxiv_id,reading_batch,section,method_category\n", encoding="utf-8")
            candidates = project / "candidates/accepted/B01_deep_reading_candidates.csv"
            candidates.parent.mkdir(parents=True, exist_ok=True)
            candidates.write_text(
                "\n".join([
                    "paper_id,title,batch,selected_for_phase3",
                    "arxiv:2401.00001,Selected Paper,B01,yes",
                ]),
                encoding="utf-8",
            )

            rows = prepare.load_selected_rows(inventory, phase2, candidates)

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["paper_id"], "arxiv:2401.00001")
            self.assertEqual(rows[0]["arxiv_id"], "2401.00001")
            self.assertEqual(rows[0]["title"], "Selected Paper")
            self.assertEqual(rows[0]["pdf_path"], str(project / "phase2_papers/managed_pdfs/arxiv_2401.00001.pdf"))

    def test_phase3_stub_filter_supports_paper_id_only_candidate_table(self) -> None:
        stubs = load_write_stubs()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidates = root / "candidates.csv"
            candidates.write_text(
                "\n".join([
                    "paper_id,title,selected_for_phase3",
                    "arxiv:2401.00001,Selected Paper,yes",
                    "arxiv:2401.00002,Rejected Paper,no",
                ]),
                encoding="utf-8",
            )

            keep = stubs.selected_ids(candidates)

            self.assertEqual(keep, {"arxiv:2401.00001"})

    def test_phase3_extract_deep_writes_batch_specific_manifest(self) -> None:
        prepare = load_prepare_extract()
        with tempfile.TemporaryDirectory() as tmp:
            phase2 = Path(tmp)
            pdf = phase2 / "managed_pdfs/arxiv_2401.00001.pdf"
            pdf.parent.mkdir(parents=True, exist_ok=True)
            pdf.write_bytes(b"%PDF-1.4\n" + (b"0" * 12000) + b"\n%%EOF\n")
            deep = pdf.with_suffix(".deep.txt")
            deep.write_text("deep text\n" * 200, encoding="utf-8")

            manifest = prepare.extract_deep(phase2, [{"paper_id": "arxiv:2401.00001", "arxiv_id": "2401.00001", "pdf_path": str(pdf)}], "B01")

            self.assertEqual(manifest.name, "B01_deep_text_manifest.json")
            self.assertTrue(manifest.exists())
            self.assertFalse((phase2 / "phase3_deep_text_manifest.json").exists())

    def test_check_notes_quality_can_validate_expected_ids(self) -> None:
        quality = load_check_notes_quality()
        body = "\n".join([
            "## B01 Phase 3 Selected Deep Reading",
            "",
            "#### 1. Test Paper (arxiv:2401.00001)",
            "",
            "- Note type: phase3-deep-v2",
            "- arXiv: 2401.00001",
            "- Research question: q",
            "- Core contribution in one sentence: c",
            "- Why selected: selected",
            "- Why it matters: matters",
            "- Main caution: caution",
            "- Initial reading decision: read",
            "- Final reading decision: keep",
            "- Appendix checked: not applicable",
            "- Appendix not applicable reason: no appendix in synthetic test",
            "- Problem formulation: formulation",
            "- Objective: objective",
            "- Optimization / curriculum: optimization",
            "- Inference procedure: inference",
            "- Assumptions: assumptions",
            "- Computation cost: cost",
            "- Main evidence supporting the paper: Section 1",
            "- Evidence that weakens or bounds the claim: Section 2",
            "- Appendix findings that change the judgment: N/A",
            "- Limitations: limits",
            "- Code/data availability: unknown",
            "- Reproduction-critical dataset details: data",
            "- Reproduction-critical hyperparameters: params",
            "- Minimal reproduction path: path",
            "- Missing implementation details: missing",
            "- Follow-up experiments: follow",
            "- Main reproduction risk: risk",
            "- What is solid: solid",
            "- What is suggestive but not proven: suggestive",
            "- What is likely task-specific: task",
            "- What may fail when scaling: scaling",
            "- Best follow-up for my research: next",
            "- Diagram type: inference / reasoning pipeline",
            "- Diagram verification: verified",
            "- Diagram evidence location: Section 1",
            "- Prior choice rationale: rationale",
            "- [Paper-stated]: fact",
            "- [Interpretation]: interpretation",
            "- [Evidence]: Section 1",
            "### 2. Annotated Method Comparison Diagram",
            "```mermaid",
            "flowchart LR",
            "  subgraph baseline[\"Direct baseline\"]",
            "    B1[\"Input\"] --> B2[\"Baseline\"] --> B3[\"Output\"]",
            "  end",
            "  subgraph prior[\"Representative prior\"]",
            "    P1[\"Input\"] --> P2[\"Prior\"] --> P3[\"Output\"]",
            "  end",
            "  subgraph ours[\"This paper\"]",
            "    O1[\"Input\"] --> O2[\"KEY CHANGED STEP: method\"] --> O3[\"Output\"]",
            "  end",
            "```",
            "| Aspect | Direct baseline | Representative prior | This paper |",
            "|---|---|---|---|",
            "| Core operation | a | b | c |",
            "| Key representation / module / objective | a | b | c |",
            "| Main weakness | a | b | c |",
            "| Key difference | a | b | c |",
            "| Claimed benefit | a | b | c |",
            "| Remaining weakness | a | b | c |",
            "### 4. Claim-Evidence-Risk-Use table",
            "| Claim | Status: proved / supported / suggested | Evidence | Risk / alternative explanation | My verdict / use |",
            "|---|---|---|---|---|",
            "| claim | supported | Section 1 | risk | use |",
        ])

        review = quality.review_entry("1. Test Paper (arxiv:2401.00001)", body)

        self.assertIn("arxiv:2401.00001", review["paper_ids"])

    def test_check_notes_quality_accepts_canonical_batch_skim_note_without_historical_field_noise(self) -> None:
        quality = load_check_notes_quality()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            note = canonical_batch_note(
                root,
                "B01",
                ["openreview:abc123"],
                [canonical_entry("openreview:abc123", "OpenReview Canonical Paper", "B01-P01")],
            )
            markdown = note.read_text(encoding="utf-8").replace("status: draft", "status: accepted")

            result = quality.review_markdown(markdown, "B01 Skim Note", 1)

            self.assertEqual(result["passed"], 1, result)
            self.assertEqual(result["needs_review"], [])
            rendered = json.dumps(result)
            self.assertNotIn("basic_info", rendered)
            self.assertNotIn("section_table_or_figure", rendered)
            self.assertNotIn("limitations", rendered)
            self.assertNotIn("numeric_result", rendered)

    def test_register_phase3_deep_note_records_hash_and_paper_ids(self) -> None:
        literature_harness = load_literature_harness()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            note = root / "notes/accepted/B01_deep.md"
            note.parent.mkdir(parents=True, exist_ok=True)
            note.write_text("#### Paper (arxiv:2401.00001)\n\n- Note type: phase3-deep-v2\n", encoding="utf-8")
            (root / "candidates/accepted").mkdir(parents=True, exist_ok=True)
            (root / "candidates/accepted/B01_deep_reading_candidates.csv").write_text("paper_id,selected_for_phase3\narxiv:2401.00001,yes\n", encoding="utf-8")
            (root / "phase2_papers").mkdir(parents=True, exist_ok=True)
            write_json(root / "phase2_papers/B01_deep_text_manifest.json", [{"paper_id": "arxiv:2401.00001"}])

            result = literature_harness.register_artifact(
                SimpleNamespace(
                    artifact_path="notes/accepted/B01_deep.md",
                    artifact_type="phase3_deep_note",
                    batch="B01",
                    quality_status="accepted",
                    artifact_label="B01-phase3-deep-notes",
                    micro_batch="",
                    notes="",
                    supersedes=[],
                    allow_write=True,
                ),
                root,
            )

            self.assertTrue(result["registered"])
            entry = result["entry"]
            self.assertEqual(entry["type"], "note")
            self.assertEqual(entry["artifact_type"], "phase3_deep_note")
            self.assertEqual(entry["paper_ids"], ["arxiv:2401.00001"])
            self.assertIn("content_hash", entry)
            self.assertEqual(entry["source_candidate_table"], "candidates/accepted/B01_deep_reading_candidates.csv")
            self.assertEqual(entry["source_deep_manifest"], "phase2_papers/B01_deep_text_manifest.json")

    def test_root_clean_ignores_superseded_active_files_and_registered_unsupported_root_note(self) -> None:
        literature_harness = load_literature_harness()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            partial = root / "reports/accepted_overviews/B01_partial_skim_overview.md"
            partial.parent.mkdir(parents=True, exist_ok=True)
            partial.write_text("partial", encoding="utf-8")
            unsupported = root / "phase3_deep_notes.md"
            unsupported.write_text("registered accepted root note", encoding="utf-8")
            write_json(root / "batches/accepted_artifacts.json", {
                "version": 2,
                "artifacts": [
                    {"type": "overview", "path": "reports/accepted_overviews/B01_partial_skim_overview.md", "quality_status": "superseded", "batch": "B01"},
                    {"type": "note", "path": "phase3_deep_notes.md", "quality_status": "accepted", "batch": "B01", "artifact_label": "B01-phase3-deep-notes"},
                ],
            })

            result = literature_harness.check_root_clean(root)

            self.assertNotIn("reports/accepted_overviews/B01_partial_skim_overview.md", result["unregistered_accepted_files"])
            self.assertNotIn("phase3_deep_notes.md", result["unsupported_root_files"])


if __name__ == "__main__":
    unittest.main()
