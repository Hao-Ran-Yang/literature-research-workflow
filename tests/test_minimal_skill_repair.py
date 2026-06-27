import csv
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def load_script(name: str):
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    path = SCRIPTS / name
    spec = importlib.util.spec_from_file_location(f"minimal_repair_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0])
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_registry(root: Path, artifacts: list[dict]) -> None:
    path = root / "batches" / "accepted_artifacts.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema_version": "2.0", "version": 2, "artifacts": artifacts}), encoding="utf-8")


def scaffold_validation_files(root: Path) -> None:
    files = {
        "inventory/workflow_inventory.csv": "schema_version,paper_id,dedup_key,reading_batch\n",
        "inventory/source_items.csv": "schema_version,source_item_id,paper_id,source_snapshot_id\n",
        "inventory/representative_candidates.csv": "schema_version,paper_id,selection_role,selection_axis,selection_reason\n",
        "inventory/conflicts.csv": "conflict_id,status,severity\n",
        "inventory/source_snapshot.json": "{}\n",
        "batches/batch_config.csv": "batch\n",
        "batches/reading_plan.md": "# Reading plan\n",
        "PROJECT_STATUS.md": "# Project status\n",
    }
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


class ValidateProjectCurrentOnlyTests(unittest.TestCase):
    def test_active_noncanonical_batch_note_fails_validation(self) -> None:
        harness = load_script("awesome_literature_harness.py")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scaffold_validation_files(root)
            note = root / "notes/accepted/B01.md"
            note.parent.mkdir(parents=True)
            note.write_text("---\nartifact_type: batch_skim_note\nbatch: B01\npaper_ids:\n  - arxiv:2401.00001\n---\n## Non-current paper\nNon-current prose.\n", encoding="utf-8")
            digest = hashlib.sha256(note.read_bytes()).hexdigest()
            write_registry(root, [{
                "type": "note", "artifact_type": "batch_skim_note", "path": "notes/accepted/B01.md",
                "batch": "B01", "paper_ids": ["arxiv:2401.00001"], "status": "accepted", "content_hash": digest,
            }])

            result = harness.validate_project(root)

            self.assertEqual(result["status"], "failed", result)
            self.assertTrue(any("missing canonical heading" in error for error in result["errors"]), result)

    def test_archived_noncanonical_batch_note_is_ignored(self) -> None:
        harness = load_script("awesome_literature_harness.py")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scaffold_validation_files(root)
            note = root / "notes/accepted/B01.md"
            note.parent.mkdir(parents=True)
            note.write_text("---\nartifact_type: batch_skim_note\nbatch: B01\npaper_ids:\n  - arxiv:2401.00001\n---\n## Non-current paper\nNon-current prose.\n", encoding="utf-8")
            digest = hashlib.sha256(note.read_bytes()).hexdigest()
            write_registry(root, [{
                "type": "note", "artifact_type": "batch_skim_note", "path": "notes/accepted/B01.md",
                "batch": "B01", "paper_ids": ["arxiv:2401.00001"], "status": "archived", "content_hash": digest,
            }])

            result = harness.validate_project(root)

            self.assertEqual(result["status"], "passed", result)


class CandidateResolverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workflow = load_script("literature_workflow.py")

    def make_tables(self, root: Path) -> dict[str, Path]:
        artifacts = []
        paths = {}
        for batch in ("B01", "B02", "B03", "B04"):
            path = root / f"candidates/accepted/{batch}_deep_reading_candidates.csv"
            write_csv(path, [{"paper_id": f"arxiv:{batch}", "selected_for_phase3": ""}])
            paths[batch] = path
            artifacts.append({"type": "candidate_table", "artifact_type": "candidate_table", "path": path.relative_to(root).as_posix(), "batch": batch, "status": "accepted"})
        write_registry(root, artifacts)
        return paths

    def test_batch_selects_same_batch_candidate_table(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self.make_tables(root)
            actual = self.workflow.resolve_candidates(root, "phase2_deep_reading_candidates.csv", batch="B04")
            self.assertEqual(actual, paths["B04"])

    def test_explicit_candidates_override_batch_registry_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self.make_tables(root)
            actual = self.workflow.resolve_candidates(root, str(paths["B03"]), batch="B04", explicit=True)
            self.assertEqual(actual, paths["B03"])

    def test_multiple_active_tables_without_batch_are_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_tables(root)
            with self.assertRaisesRegex(ValueError, "ambiguous.*candidate"):
                self.workflow.resolve_candidates(root, "phase2_deep_reading_candidates.csv")


class FinalInputAggregationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.final = load_script("write_final_synthesis.py")

    def test_registry_aggregates_batch_skim_notes_without_flat_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifacts = []
            for batch in ("B01", "B02"):
                path = root / f"notes/accepted/{batch}.md"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"## {batch}\n", encoding="utf-8")
                artifacts.append({"type": "note", "artifact_type": "batch_skim_note", "path": path.relative_to(root).as_posix(), "batch": batch, "status": "accepted"})
            write_registry(root, artifacts)
            inputs = self.final.resolve_synthesis_inputs(root, "phase2_skim_notes.md", "phase3_deep_notes.md", "phase2_deep_reading_candidates.csv")
            self.assertEqual(inputs["layout"], "template-v2")
            self.assertEqual([path.name for path in inputs["skim_notes"]], ["B01.md", "B02.md"])

    def test_registry_recognizes_deep_note_and_other_active_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            specs = [
                ("note", "batch_skim_note", "notes/accepted/B01.md"),
                ("note", "phase3_deep_note", "notes/accepted/B01_deep.md"),
                ("candidate_table", "candidate_table", "candidates/accepted/B01_deep_reading_candidates.csv"),
                ("overview", "overview", "reports/accepted_overviews/B01_skim_overview.md"),
            ]
            artifacts = []
            for broad_type, artifact_type, rel in specs:
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("paper_id,selected_for_phase3\n" if path.suffix == ".csv" else "# artifact\n", encoding="utf-8")
                artifacts.append({"type": broad_type, "artifact_type": artifact_type, "path": rel, "batch": "B01", "status": "accepted"})
            write_registry(root, artifacts)
            inputs = self.final.resolve_synthesis_inputs(root, "flat-skim.md", "flat-deep.md", "flat-candidates.csv")
            self.assertEqual([path.name for path in inputs["deep_notes"]], ["B01_deep.md"])
            self.assertEqual(len(inputs["candidate_tables"]), 1)
            self.assertEqual(len(inputs["overviews"]), 1)

    def test_missing_registry_does_not_fallback_to_flat_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("phase2_skim_notes.md", "phase3_deep_notes.md", "phase2_deep_reading_candidates.csv"):
                (root / name).write_text("x\n", encoding="utf-8")
            inputs = self.final.resolve_synthesis_inputs(root, "phase2_skim_notes.md", "phase3_deep_notes.md", "phase2_deep_reading_candidates.csv")
            self.assertEqual(inputs["layout"], "current-empty")
            self.assertEqual(inputs["skim_notes"], [])
            self.assertEqual(inputs["deep_notes"], [])
            self.assertEqual(inputs["candidate_tables"], [])


class RegistrySchemaTests(unittest.TestCase):
    def test_writer_registry_with_clean_review_status_validates(self) -> None:
        schema = json.loads((ROOT / "schemas/accepted_artifacts.schema.json").read_text(encoding="utf-8"))
        sample = {
            "schema_version": "2.0", "version": 2,
            "artifacts": [{
                "type": "note", "artifact_type": "batch_skim_note", "path": "notes/accepted/B01.md",
                "batch": "B01", "paper_ids": ["arxiv:2401.00001"], "status": "active",
                "review_status": "clean", "warning_codes": [], "content_hash": "a" * 64,
            }],
        }
        jsonschema.validate(sample, schema)


class PackageIntegrityTests(unittest.TestCase):
    def test_package_is_complete_clean_and_uses_posix_entries(self) -> None:
        packager = load_script("package_skill.py")
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "literature-research-workflow.zip"
            packager.build_skill_zip(ROOT, output)
            with zipfile.ZipFile(output) as archive:
                names = archive.namelist()
            self.assertIn("SKILL.md", names)
            for required in ("scripts/", "schemas/", "docs/", "templates/", "tests/"):
                self.assertTrue(any(name.startswith(required) for name in names), required)
            self.assertTrue(all("\\" not in name for name in names))
            self.assertFalse(any(".git/" in name or name.startswith(".git/") for name in names))
            self.assertFalse(any("__pycache__" in name or name.endswith(".pyc") for name in names))
            self.assertFalse(any(".pytest_cache" in name or name.endswith((".tmp", ".temp", ".bak", "~")) for name in names))
            self.assertFalse(any(Path(name).name in {".DS_Store", "Thumbs.db"} for name in names))


if __name__ == "__main__":
    unittest.main()
