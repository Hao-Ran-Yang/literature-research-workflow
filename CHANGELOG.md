# Changelog

All notable changes to this project will be documented in this file.

This project follows a pragmatic alpha-stage changelog format. Version numbers may be adjusted as the public release process becomes more formal.

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
