# Literature Research Workflow CLI Reference

Prefer `scripts/literature_workflow.py` for normal use. Use direct helpers for debugging or recovery.

All runner commands that write files require `--allow-write`, including legacy spellings such as bare `--batch B03`, `--phase phase1`, and `--phase final`. Network actions additionally require `--allow-network`.

## Daily State Commands

```bash
python scripts/literature_workflow.py --root . --action state
python scripts/literature_workflow.py --root . --action next
python scripts/check_workflow_state.py --root .
```

## Read-Only Harness Checks

Use the harness for registry-aware inspection, root hygiene, context budgeting, and representative-candidate validation. These checks do not write, move, delete, download, or register artifacts.

```bash
python scripts/literature_harness.py --root . --action status
python scripts/literature_harness.py --root . --action check-registry
python scripts/literature_harness.py --root . --action check-root-clean
python scripts/literature_harness.py --root . --action check-context-budget --paths phase2_papers/B01/example.packet.md
python scripts/literature_harness.py --root . --action check-representative-candidates
python scripts/literature_harness.py --root . --action plan-micro-batches --packet-dir phase2_papers/B01_packets
```

`check-root-clean` reports unexpected root-level Markdown/CSV files, legacy flat workflow files, extensionless temporary-looking files, unregistered accepted outputs, and archive references. `check-context-budget` rejects PDFs, complete `.body.txt` / `.deep.txt`, temporary stubs, inventory CSVs, and large CSV tables as model context inputs. `check-registry` supports legacy v1 string/list registries and newer v2 structured entries without migrating either format.

Create bounded evidence packets after main-body text exists:

```bash
python scripts/literature_harness.py --root . --action create-evidence-packets --batch B01 --allow-write
python scripts/literature_harness.py --root . --action create-evidence-packets --batch B01 --max-packet-chars 8000 --allow-write
```

Plan low-context micro-batches and gate overview generation:

```bash
python scripts/literature_harness.py --root . --action plan-micro-batches --packet-manifest phase2_papers/B01_packet_manifest.json --micro-batch-size 4
python scripts/literature_harness.py --root . --action check-overview-gate --batch B01 --packet-manifest phase2_papers/B01_packet_manifest.json --micro-batch-size 4
```

`check-overview-gate` requires the accepted batch skim note to cover every pass-quality packet in the packet manifest. Micro-batches are writing/scheduling units only; they are not accepted independently in new template-v2 work.

Register accepted outputs with an explicit write gate:

```bash
python scripts/literature_harness.py --root . --action register-artifact --artifact-type note --artifact-path notes/accepted/B01.md --batch B01 --allow-write
python scripts/literature_harness.py --root . --action register-artifact --artifact-type overview --artifact-path reports/accepted_overviews/B01.md --batch B01 --artifact-label B01-overview --allow-write
python scripts/literature_harness.py --root . --action register-artifact --artifact-type note --artifact-path notes/accepted/B01-v2.md --batch B01 --supersedes notes/accepted/B01.md --allow-write
```

`register-artifact` creates a v2 registry when none exists. It refuses to rewrite legacy v1 list registries, refuses missing or non-project-relative paths, requires `--batch` for `note`, `overview`, and `candidate_table`, and requires `--supersedes` before replacing an active registered path.

Archive superseded registry entries only after inspecting the plan:

```bash
python scripts/literature_harness.py --root . --action archive-superseded --plan-only
python scripts/literature_harness.py --root . --action archive-superseded --allow-write
```

Create a registry-aware new-project scaffold:

```bash
python scripts/scaffold_literature_project.py --root path/to/project --template-v2 --allow-write
```

## Phase 1

```bash
python scripts/literature_workflow.py --root path/to/project --source path/to/source.md --phase phase1
python scripts/literature_workflow.py --root . --action phase1 --source source_links.md --plan-only
python scripts/literature_workflow.py --root . --action phase1 --source source_links.md --allow-write
```

URL sources and metadata fetching require `--allow-network`.

## Phase 2 Skim Reading

Template-v2 projects should use accepted outputs under `notes/accepted/`, `reports/accepted_overviews/`, and `candidates/accepted/`, then register them in `batches/accepted_artifacts.json`. The flat-output runner commands below are preserved for legacy compatibility and low-level recovery.

Prepare PDFs and main-body text. Substitute the current batch from workflow state; do not assume it is `B03`:

```bash
python scripts/literature_workflow.py --root . --action prepare-batch --batch B03 --plan-only
python scripts/literature_workflow.py --root . --action prepare-batch --batch B03 --allow-write
python scripts/literature_workflow.py --root . --action import-local-pdfs --source raw_papers/ --batch B03 --allow-write
```

For template-v2 projects, local PDFs can be copied into managed project storage with `import-local-pdfs` from `raw_papers/` without moving or deleting the originals. Template-v2 PDF extraction requires `pypdf`; install it with `python -m pip install pypdf`. `prepare-batch` creates evidence packets only for PDFs or existing body text that yield real, mechanically pass-quality main-body text. If `pypdf` is unavailable, a PDF is invalid, extraction fails, or only placeholder text is present, no packet is created and `run-next-microbatch` returns a blocked state such as `no_readable_papers`.

Download missing PDFs only after approval:

```bash
python scripts/literature_workflow.py --root . --action prepare-batch --batch B03 --download --allow-network --allow-write
```

Legacy skim-note stubs:

```bash
python scripts/literature_workflow.py --root . --action phase2-skim --batch B03 --plan-only
python scripts/literature_workflow.py --root . --action phase2-skim --batch B03 --allow-write
```

`phase2-skim` is a legacy/stub-only/recovery action. It is not the main template-v2 packet-only writing path and does not mean a formal skim note has been written.

Template-v2 packet-only writing:

```bash
python scripts/literature_workflow.py --root . --action run-next-microbatch --batch Bxx --allow-write
python scripts/literature_workflow.py --root . --action accept-draft --draft notes/drafts/Bxx.md --batch Bxx --allow-write
```

`run-next-microbatch` writes the next task file and maintains one batch-level draft target under `notes/drafts/Bxx.md`. Append or merge each micro-batch into that draft without overwriting earlier per-paper entries. `accept-draft` is a full-batch gate: it derives expected paper IDs and source packets from pass-quality packet-manifest entries, not from draft frontmatter alone.

When `run-next-microbatch` returns `status: ready`, do not stop after reporting only readiness. Execute the generated task, update the batch draft, and rerun `run-next-microbatch` until it returns `blocked`, `draft_complete`, or `complete`; run `accept-draft` after `draft_complete`.

Legacy flat-output overview and candidate CSV:

```bash
python scripts/literature_workflow.py --root . --action phase2-overview --plan-only
python scripts/literature_workflow.py --root . --action phase2-overview --allow-write
```

For legacy projects, candidate selections live in `phase2_deep_reading_candidates.csv`. Regeneration preserves `selected_for_phase3` and `selection_notes`.

## Phase 3 Selected Deep Reading

For template-v2, explicitly promote a core paper in its batch, then extract appendix-aware `.deep.txt` sidecars and write compact deep-note stubs:

```bash
python scripts/literature_workflow.py --root . --action promote-to-deep --batch B01 --paper-id arxiv:2401.00001 --allow-write
python scripts/literature_workflow.py --root . --action phase3-deep --batch B01 --plan-only
python scripts/literature_workflow.py --root . --action phase3-deep --batch B01 --allow-write
```

The template-v2 accepted deep note is batch-scoped, for example `notes/accepted/B01_deep.md`. Directly editing `selected_for_phase3` and using `phase3_deep_notes.md` remain legacy/manual compatibility paths, not the template-v2 primary flow. `--candidates` has highest resolution priority; otherwise `--batch Bxx` selects the same-batch active registry table, and multiple active tables without a selector fail as ambiguous.

## Final

```bash
python scripts/literature_workflow.py --root . --action final --plan-only
python scripts/literature_workflow.py --root . --action final --allow-write
python scripts/literature_workflow.py --root . --phase final
```

For template-v2, Final synthesis aggregates active skim notes, deep notes, candidate tables, and overviews from `batches/accepted_artifacts.json`. Deep notes override matching paper evidence while skim notes remain inputs. Legacy flat files (`phase3_deep_notes.md`, `phase2_skim_notes.md`, candidate CSV, and `phase2_reading_notes.md`) are fallback inputs only when the registry/layout is absent.

Build a clean distributable zip with `python scripts/package_skill.py --output path/to/literature-research-workflow.zip`. The packager requires the core skill files, uses POSIX entry names, and excludes bytecode, caches, temporary files, and system metadata.

Accepted Phase 3 deep-text failures are reported separately. They may allow Final synthesis to continue with warnings, but they never count as completed deep notes.

## Notes Helpers

The following helpers operate on legacy flat Markdown files unless you pass template-v2 accepted paths explicitly.

Historical 12-section v3 stub, preserved for direct-call compatibility:

```bash
python scripts/write_batch_note_stubs.py --manifest phase2_papers/B03_manifest.json --output B03_note_stubs.md --overwrite --allow-write
```

New templates:

```bash
python scripts/write_batch_note_stubs.py --manifest phase2_papers/B03_manifest.json --template phase2-skim --output B03_skim_note_stubs.md --overwrite --allow-write
python scripts/write_batch_note_stubs.py --manifest phase2_papers/phase3_deep_text_manifest.json --template phase3-deep --candidates phase2_deep_reading_candidates.csv --output phase3_deep_note_stubs.md --overwrite --allow-write
```

Parse and check notes:

```bash
python scripts/parse_reading_notes.py --notes phase2_skim_notes.md --output phase2_skim_notes.parsed.json --allow-write
python scripts/check_notes_quality.py --notes phase2_skim_notes.md --batch-heading "B03 Skim Notes" --expected 20
python scripts/write_skim_overview.py --notes phase2_skim_notes.md --output phase2_skim_overview.md --candidates phase2_deep_reading_candidates.csv --allow-write
```

`check_notes_quality.py` explicitly runs the strict advisory diagram checks for new skim and deep notes. It reports entries needing review without rewriting notes or blocking legacy parsing, overview generation, candidate merging, or state detection.

## PDF Helpers

Create manifest and main-body text:

```bash
python scripts/prepare_batch_manifest_extract.py --batch B03 --inventory phase1_inventory.csv --root phase2_papers --mode manifest --allow-write
python scripts/prepare_batch_manifest_extract.py --batch B03 --inventory phase1_inventory.csv --root phase2_papers --mode extract --allow-write
```

Extract selected full text including appendices:

```bash
python scripts/prepare_batch_manifest_extract.py --inventory phase1_inventory.csv --root phase2_papers --mode extract-deep --candidates phase2_deep_reading_candidates.csv --allow-write
```

Raw ensure, import, and validation:

```bash
node scripts/ensure_raw_papers_node.mjs --manifest phase2_papers/B03_manifest.json --raw-dir raw_papers --dry-run --no-status-write --quiet
python scripts/import_local_pdfs.py --manifest phase2_papers/B03_manifest.json --source raw_papers --copy --allow-write
node scripts/download_batch_node.mjs --manifest phase2_papers/B03_manifest.json --validate-only --no-status-write --quiet
```

Direct phase2 downloading is an emergency fallback and requires explicit `--download`.

## Contracts And Runtime

```bash
python scripts/literature_workflow.py --print-contracts
python scripts/literature_workflow.py --root . --action state --validate-contracts
python scripts/literature_workflow.py --action check-node
```

Use `LITFLOW_NODE` or `--node-command` when Node is not discoverable.

## Compatibility

- Bare `--batch B03` still maps to `prepare-batch`.
- `--phase phase1` and `--phase final` remain available.
- Legacy command names remain available, but they no longer bypass `--allow-write` or `--allow-network`.
- Old `phase2_reading_notes.md` remains valid input.
- Legacy, v2, and old v3 Markdown notes remain parseable without migration.
