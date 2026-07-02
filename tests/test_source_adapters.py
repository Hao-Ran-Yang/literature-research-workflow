import unittest

from scripts import source_adapters as adapters


class SourceAdapterTests(unittest.TestCase):
    def test_arxiv_urls_inline_and_hf_papers_share_canonical_id(self) -> None:
        values = [
            "https://arxiv.org/abs/2401.01614",
            "https://arxiv.org/pdf/2401.01614v2.pdf",
            "arXiv:2401.01614v3",
            "https://huggingface.co/papers/2401.01614",
        ]

        paper_ids = {adapters.parse_source_url(value).paper_id for value in values}

        self.assertEqual(paper_ids, {"arxiv:2401.01614"})

    def test_arxiv_doi_normalizes_to_arxiv_identity(self) -> None:
        identity = adapters.parse_source_url("doi:10.48550/arXiv.2401.01614")

        self.assertEqual(identity.paper_id, "arxiv:2401.01614")
        self.assertEqual(identity.arxiv_id, "2401.01614")
        self.assertEqual(identity.source_family, "arxiv")

    def test_regular_doi_preserves_doi_identity(self) -> None:
        identity = adapters.parse_source_url("https://doi.org/10.5555/Foo.Bar")

        self.assertEqual(identity.paper_id, "doi:10.5555/foo.bar")
        self.assertEqual(identity.source_family, "doi")
        self.assertEqual(identity.pdf_status, "needs_pdf_review")

    def test_openreview_forum_and_pdf_preserve_case_sensitive_id(self) -> None:
        forum = adapters.parse_source_url("https://openreview.net/forum?id=AbC_123-XyZ")
        pdf = adapters.parse_source_url("https://openreview.net/pdf?id=AbC_123-XyZ")

        self.assertEqual(forum.paper_id, "openreview:AbC_123-XyZ")
        self.assertEqual(pdf.paper_id, "openreview:AbC_123-XyZ")
        self.assertEqual(forum.public_pdf_url, "https://openreview.net/pdf?id=AbC_123-XyZ")

    def test_hf_model_dataset_and_space_are_resources_not_papers(self) -> None:
        examples = [
            ("https://huggingface.co/bigscience/bloom", "model"),
            ("https://huggingface.co/datasets/squad", "dataset"),
            ("https://huggingface.co/spaces/acme/demo", "demo"),
        ]

        for url, role in examples:
            with self.subTest(url=url):
                identity = adapters.parse_source_url(url)
                self.assertEqual(identity.source_role, role)
                self.assertEqual(identity.paper_id, "")
                self.assertEqual(identity.pdf_status, "pdf_unavailable")

    def test_direct_pdf_alone_generates_urlhash_identity(self) -> None:
        identity = adapters.parse_source_url("https://example.org/papers/main.pdf")

        self.assertTrue(identity.paper_id.startswith("urlhash:"))
        self.assertEqual(identity.source_family, "pdf")
        self.assertEqual(identity.public_pdf_url, "https://example.org/papers/main.pdf")
        self.assertEqual(identity.pdf_status, "available")

    def test_neurips_stable_url_uses_year_and_hash(self) -> None:
        identity = adapters.parse_source_url(
            "https://papers.neurips.cc/paper_files/paper/2023/hash/ABCdef123-Paper-Conference.pdf"
        )

        self.assertEqual(identity.paper_id, "neurips:2023:ABCdef123")
        self.assertEqual(identity.source_family, "neurips")

    def test_neurips_unstable_url_falls_back_to_urlhash_and_review(self) -> None:
        identity = adapters.parse_source_url("https://neurips.cc/virtual/2023/poster/12345")

        self.assertTrue(identity.paper_id.startswith("urlhash:"))
        self.assertEqual(identity.source_family, "neurips")
        self.assertEqual(identity.metadata_status, "needs_metadata_review")
        self.assertEqual(identity.pdf_status, "needs_pdf_review")

    def test_safe_filename_and_pdf_match_keys_support_non_arxiv_ids(self) -> None:
        row = {
            "paper_id": "doi:10.5555/foo.bar",
            "source_family_id": "10.5555/foo.bar",
            "canonical_title": "A Useful Paper",
        }

        self.assertEqual(adapters.safe_filename_for_paper_id(row["paper_id"]), "doi_10.5555_foo.bar")
        keys = adapters.pdf_match_keys(row)
        self.assertIn("doi105555foobar", keys)
        self.assertIn("105555foobar", keys)
        self.assertIn("ausefulpaper", keys)


if __name__ == "__main__":
    unittest.main()
