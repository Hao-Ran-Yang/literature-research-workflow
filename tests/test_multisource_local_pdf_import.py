import csv
import importlib.util
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
    spec = importlib.util.spec_from_file_location("awesome_literature_harness_local_import_tests", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def write_inventory(root: Path, rows: list[dict]) -> None:
    path = root / "inventory/workflow_inventory.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "schema_version",
        "paper_id",
        "dedup_key",
        "arxiv_id",
        "source_family_id",
        "canonical_title",
        "public_pdf_url",
        "reading_batch",
        "pdf_status",
        "local_pdf_path",
        "notes",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def read_inventory(root: Path) -> list[dict]:
    with (root / "inventory/workflow_inventory.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


class MultiSourceLocalPdfImportTests(unittest.TestCase):
    def test_import_local_pdf_matches_doi_source_family_id(self) -> None:
        harness = load_harness()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / "raw_papers"
            raw.mkdir()
            (raw / "10.5555 Foo Bar.pdf").write_bytes(b"%PDF-")
            write_inventory(
                root,
                [
                    {
                        "schema_version": "template-v2.1",
                        "paper_id": "doi:10.5555/foo.bar",
                        "dedup_key": "doi:10.5555/foo.bar",
                        "source_family_id": "10.5555/foo.bar",
                        "canonical_title": "Different Title",
                        "reading_batch": "B01",
                        "pdf_status": "needs_pdf_review",
                    }
                ],
            )

            result = harness.import_local_pdfs(SimpleNamespace(root=str(root), source="raw_papers", batch="B01", allow_write=True, replace_managed=False, force=False))

            self.assertEqual(result["status"], "imported")
            self.assertEqual(result["matched"][0]["paper_id"], "doi:10.5555/foo.bar")
            row = read_inventory(root)[0]
            self.assertEqual(row["pdf_status"], "available")
            self.assertEqual(row["local_pdf_path"], "phase2_papers/managed_pdfs/doi_10.5555_foo.bar.pdf")

    def test_import_local_pdf_matches_openreview_id_preserving_case(self) -> None:
        harness = load_harness()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / "raw_papers"
            raw.mkdir()
            (raw / "AbC_123-XyZ.pdf").write_bytes(b"%PDF-")
            write_inventory(
                root,
                [
                    {
                        "schema_version": "template-v2.1",
                        "paper_id": "openreview:AbC_123-XyZ",
                        "dedup_key": "openreview:AbC_123-XyZ",
                        "source_family_id": "AbC_123-XyZ",
                        "canonical_title": "Different Title",
                        "reading_batch": "B01",
                        "pdf_status": "needs_pdf_review",
                    }
                ],
            )

            result = harness.import_local_pdfs(SimpleNamespace(root=str(root), source="raw_papers", batch="B01", allow_write=True, replace_managed=False, force=False))

            self.assertEqual(result["matched"][0]["paper_id"], "openreview:AbC_123-XyZ")
            self.assertTrue((root / "phase2_papers/managed_pdfs/openreview_AbC_123-XyZ.pdf").exists())


if __name__ == "__main__":
    unittest.main()
