import tempfile
import unittest
from pathlib import Path

from tests.workflow_test_helpers import read_csv_rows, run_json


class MultiSourceInventoryTests(unittest.TestCase):
    def run_init(self, root: Path, markdown: str) -> dict:
        source = root / "awesome.md"
        source.write_text(markdown, encoding="utf-8")
        return run_json(
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

    def test_hf_papers_and_arxiv_are_deduped_but_hf_resources_are_evidence_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = self.run_init(
                root,
                """# Awesome

## Methods
- [Paper](https://arxiv.org/abs/2401.01614) [HF Paper](https://huggingface.co/papers/2401.01614) [Model](https://huggingface.co/org/model) [Dataset](https://huggingface.co/datasets/squad) [Demo](https://huggingface.co/spaces/org/demo)
""",
            )

            self.assertFalse(result["errors"])
            inventory = read_csv_rows(root / "inventory/workflow_inventory.csv")
            source_items = read_csv_rows(root / "inventory/source_items.csv")
            self.assertEqual([row["paper_id"] for row in inventory], ["arxiv:2401.01614"])
            self.assertEqual({row["paper_id"] for row in source_items}, {"arxiv:2401.01614"})
            self.assertIn("model", {row["source_role"] for row in source_items})
            self.assertIn("dataset", {row["source_role"] for row in source_items})
            self.assertIn("demo", {row["source_role"] for row in source_items})

    def test_table_row_evidence_links_are_assigned_to_primary_paper(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = self.run_init(
                root,
                """# Awesome

## Methods
| Paper | PDF | Code | Project |
|---|---|---|---|
| [OpenReview](https://openreview.net/forum?id=AbC_123-XyZ) | [PDF](https://openreview.net/pdf?id=AbC_123-XyZ) | [Code](https://github.com/example/repo) | [Project](https://example.org/project) |
""",
            )

            self.assertFalse(result["errors"])
            inventory = read_csv_rows(root / "inventory/workflow_inventory.csv")
            source_items = read_csv_rows(root / "inventory/source_items.csv")
            self.assertEqual([row["paper_id"] for row in inventory], ["openreview:AbC_123-XyZ"])
            self.assertEqual({row["paper_id"] for row in source_items}, {"openreview:AbC_123-XyZ"})
            self.assertIn("code", {row["source_role"] for row in source_items})
            self.assertIn("project", {row["source_role"] for row in source_items})
            self.assertEqual(inventory[0]["public_pdf_url"], "https://openreview.net/pdf?id=AbC_123-XyZ")
            self.assertEqual(inventory[0]["pdf_status"], "available")

    def test_titled_block_evidence_lines_are_assigned_to_primary_paper(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = self.run_init(
                root,
                """# Awesome

## Methods

### Block Paper
[Paper](https://doi.org/10.7777/Block.Paper)
[Code](https://github.com/example/block-code)
[Project](https://example.org/block-project)
""",
            )

            self.assertFalse(result["errors"])
            inventory = read_csv_rows(root / "inventory/workflow_inventory.csv")
            source_items = read_csv_rows(root / "inventory/source_items.csv")
            self.assertEqual([row["paper_id"] for row in inventory], ["doi:10.7777/block.paper"])
            self.assertEqual({row["paper_id"] for row in source_items}, {"doi:10.7777/block.paper"})
            self.assertIn("code", {row["source_role"] for row in source_items})
            self.assertIn("project", {row["source_role"] for row in source_items})

    def test_github_only_resource_does_not_create_standalone_paper(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = self.run_init(
                root,
                """# Awesome

## Methods
- [Code only](https://github.com/example/repo)
""",
            )

            self.assertEqual(result["steps"][0]["papers"], 0)
            inventory = read_csv_rows(root / "inventory/workflow_inventory.csv")
            source_items = read_csv_rows(root / "inventory/source_items.csv")
            self.assertEqual(inventory, [])
            self.assertEqual(source_items, [])

    def test_direct_pdf_without_primary_creates_urlhash_paper(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = self.run_init(
                root,
                """# Awesome

## Methods
- [PDF](https://example.org/papers/main.pdf)
""",
            )

            self.assertFalse(result["errors"])
            inventory = read_csv_rows(root / "inventory/workflow_inventory.csv")
            self.assertEqual(len(inventory), 1)
            self.assertTrue(inventory[0]["paper_id"].startswith("urlhash:"))
            self.assertEqual(inventory[0]["public_pdf_url"], "https://example.org/papers/main.pdf")
            self.assertEqual(inventory[0]["pdf_status"], "available")

    def test_direct_pdf_in_new_list_item_is_not_assigned_to_previous_paper(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = self.run_init(
                root,
                """# Awesome

## Methods
- [NeurIPS](https://papers.neurips.cc/paper_files/paper/2023/hash/ABCdef123-Paper-Conference.pdf)
- [Standalone PDF](https://example.org/papers/standalone.pdf)
""",
            )

            self.assertFalse(result["errors"])
            inventory = read_csv_rows(root / "inventory/workflow_inventory.csv")
            paper_ids = {row["paper_id"] for row in inventory}
            self.assertIn("neurips:2023:ABCdef123", paper_ids)
            self.assertTrue(any(paper_id.startswith("urlhash:") for paper_id in paper_ids), paper_ids)
            standalone = next(row for row in inventory if row["paper_id"].startswith("urlhash:"))
            self.assertEqual(standalone["public_pdf_url"], "https://example.org/papers/standalone.pdf")

    def test_non_arxiv_paper_without_pdf_needs_review_not_arxiv_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = self.run_init(
                root,
                """# Awesome

## Methods
- [DOI paper](https://doi.org/10.5555/Foo.Bar)
""",
            )

            self.assertFalse(result["errors"])
            inventory = read_csv_rows(root / "inventory/workflow_inventory.csv")
            self.assertEqual(inventory[0]["paper_id"], "doi:10.5555/foo.bar")
            self.assertEqual(inventory[0]["arxiv_id"], "")
            self.assertEqual(inventory[0]["pdf_status"], "needs_pdf_review")
            quality = run_json(
                "check_inventory_quality.py",
                "--inventory",
                str(root / "inventory/workflow_inventory.csv"),
                cwd=root,
            )
            self.assertTrue(quality["ok"], quality)


if __name__ == "__main__":
    unittest.main()
