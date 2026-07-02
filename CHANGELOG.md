# Changelog

All notable changes to this project will be documented in this file.

This project follows a pragmatic alpha-stage changelog format. Version numbers may be adjusted as the public release process becomes more formal.

## [Unreleased]

### Added

- Added `scripts/source_adapters.py` as the canonical helper for source URL classification, `paper_id` normalization, dedup keys, source roles/families, PDF status, safe filenames for newly generated files, and local PDF match aliases.
- Added multi-source tests for arXiv, OpenReview, Hugging Face papers, DOI, ACL Anthology, PMLR, NeurIPS, direct PDF URLs, GitHub code links, and Hugging Face model/dataset/space resources.

### Changed

- Updated the template-v2 main ingestion flow to be `paper_id`-first; `arxiv_id` is now an optional alias rather than a required identity.
- Added conservative canonical `pdf_status` semantics: `available`, `needs_pdf_review`, and `pdf_unavailable`.
- Kept legacy arXiv helpers for older arXiv-only workflows and manual recovery, while documenting that they are not the template-v2 multi-source main entrypoint.

### Fixed

- Prevented non-arXiv papers from failing inventory quality or workflow state checks solely because `arxiv_id` is missing.
- Fixed mixed-source evidence attribution so GitHub/Hugging Face resource links do not become standalone papers when they can be assigned to a primary paper.
- Fixed a boundary case where a standalone direct PDF in a new bullet item could be incorrectly attributed to the previous bullet's paper.

## [0.1.0-alpha] - 2026-06-27

### Added

- Initial public release of `literature-research-workflow` as a Codex skill and local literature research harness.
- Template-v2 literature project layout with separate inventory, draft notes, accepted notes, reports, candidates, raw papers, evidence packets, and archive directories.
- Registry-aware artifact lifecycle through `batches/accepted_artifacts.json`.
- Phase 1 workflow for paper inventory, taxonomy, and batch planning from awesome-paper repositories, Markdown paper lists, curated CSVs, and local sources.
- Phase 2 packet-only skim reading workflow with micro-batch scheduling and context-budget safeguards.
- Batch-level skim note acceptance flow from `notes/drafts/Bxx.md` to `notes/accepted/Bxx.md`.
- Phase 2 overview and reading-priority candidate table generation.
- Explicit `promote-to-deep` entrypoint for optional Phase 3 deep reading of selected core papers.
- Phase 3 deep-note support using the current `phase3-deep-v2` contract.
- Final synthesis workflow that reads active accepted registry artifacts only.
- Evidence packet manifest schema with paper IDs, packet IDs, micro-batch IDs, section hints, character ranges, source body paths, quality status, warnings, and packet metadata.
- Safety gates for write actions, network access, PDF download, packet-only reading, registry validation, and root hygiene checks.
- Packaging helper for building a clean skill zip while excluding generated files and caches.
- Unit and integration tests covering core template-v2 workflow behavior, Phase 2 batch gates, registry handling, artifact acceptance, and compatibility checks.

### Changed

- Clarified the project as an alpha-stage research workflow rather than a fully automatic survey generator.
- Documented the public repository entrypoint through `README.md`.
- Added MIT licensing for public reuse, modification, and distribution.

### Known limitations

- Long integration tests may require separate slow-test handling rather than default CI execution.
- Public examples and CI configuration may continue to evolve.
- PDF extraction quality depends on document formatting and parser behavior.
- Human verification remains required for paper claims, metadata, and final synthesis.
