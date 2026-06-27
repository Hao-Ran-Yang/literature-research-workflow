# Literature Research Workflow Specification

## Quick Contract

Current projects are template-v2 only. `batches/accepted_artifacts.json` is the accepted-artifact source of truth; artifact lifecycle is `status = active | superseded | archived`; Final synthesis reads active registry artifacts only; Phase 2 writing is packet-only through `run-next-microbatch` and `accept-draft`; Phase 3 starts with `promote-to-deep`; `validate-project` is strict for active current artifacts and ignores archived or superseded artifacts.

## How To Read This Spec

- Routine operation: read `Overview`, `Core Rules`, `Template-v2 Standard Layout`, `Default Current Workflow`, and the phase section you are about to run.
- Detailed note rules: read `Method Diagram Policy`, `Phase 2 Skim Note Quality`, and `Phase 3 Deep Note Quality` only when generating or validating notes.
- Recovery/debug: read registry, root-clean, context-budget, and packaging details only when a check fails or a project needs cleanup.

## Overview

This document is the detailed source of truth for the literature-review-centered research workflow. arXiv is one supported source family alongside OpenReview, ACL Anthology, PMLR, NeurIPS pages, official PDFs, local PDFs, and curated inventories.

Default flow:

```text
Phase 1 inventory/taxonomy/batches
-> Phase 2 packet-only batch skim notes
-> batch-level overview
-> reading-priority candidate table
-> user reads selected papers manually and takes personal notes outside this skill
-> optional promote selected core papers to deep note
-> Final synthesis
```

Markdown remains the default note format. JSON is derived only when scripts need structured analysis.

## Core Rules

- Process one batch at a time unless the user explicitly requests a multi-batch run.
- Use 10-35 papers as the normal reading batch size.
- Do not fabricate paper claims, metadata, venues, arXiv IDs, links, or experimental results.
- Ask before webpage access, arXiv API calls, or PDF downloads.
- For GitHub awesome-paper repositories, Phase 1 should prefer raw README fetches as the source snapshot and use `git clone` only when README fetch fails or the paper list spans multiple Markdown files.
- GitHub README/source-list fetching is not the same approval class as arXiv metadata enrichment, PDF download, package installation, or external code execution; keep those later actions separately gated.
- Do not delete, move, or overwrite raw papers or existing reading notes without explicit confirmation.
- Treat Phase 1 taxonomy and skim-level route conclusions as provisional.
- Keep paper-stated facts, interpretation, evidence, verification needs, and research ideas distinct.

## Method Diagram Policy

Every new note must include a compact computation-flow diagram. The diagram is a reading discipline, not decoration: it should force an explicit comparison between the direct baseline, the most relevant representative prior, and this paper. For benchmark, dataset, theory, or objective papers without a reliable representative prior, use `N/A: no representative prior identified.` plus a brief `Reason: ...`. Do not invent a prior to satisfy the template.

General rules:

1. Draw computation flow only. Do not add decorative conceptual illustrations.
2. Make the changed step visible at a glance.
3. Compare only the direct baseline, one or two representative priors, and this paper. Do not draw every related-work method or experimental baseline.
4. Do not invent unsupported modules, training steps, signals, objectives, or claims.
5. Follow the diagram with the stage-appropriate short comparison table. Skim notes use the compact four-row table; deep notes separate direct baseline, representative prior, and this paper.
6. Mark speculative explanations as `[Interpretation]` or `[Needs verification]`; do not present them as paper-stated facts.

Use this deterministic mapping:

| Paper type | Phase 2 skim diagram | Phase 3 deep main diagram |
|---|---|---|
| Inference / reasoning pipeline | Three-line pipeline | Three-role ASCII/text pipeline with Phase 3-level mechanism detail |
| Training / post-training | `data -> objective -> model` comparison | ASCII/text training pipeline; optional training-to-inference auxiliary diagram |
| Architecture / system | Module pipeline | ASCII/text architecture pipeline with the changed module |
| Objective / optimization / theory | `data -> objective -> update` comparison | ASCII/text objective-placement pipeline plus claim-risk table |
| Benchmark / dataset | Dataset / evaluation pipeline | ASCII/text dataset/evaluation pipeline plus protocol comparison table |

The Phase 3 main diagram is always required. A training-to-inference diagram supplements rather than replaces it.

## Standard Project Files

### Template-v2 Standard Layout

New projects must use template-v2 as the default standard layout:

```text
PROJECT_STATUS.md
source_links.md
scope.md
batches/accepted_artifacts.json
batches/batch_config.csv
batches/reading_plan.md
inventory/representative_candidates.csv
inventory/metadata_overrides.csv
inventory/workflow_inventory.csv
raw_papers/
phase2_papers/
notes/accepted/
notes/drafts/
reports/accepted_overviews/
reports/drafts/
candidates/accepted/
candidates/drafts/
archive/repair_history/
archive/superseded_notes/
archive/superseded_reports/
archive/raw_tables/
```

For each new Phase 2 batch, the accepted user-facing outputs should be exactly these artifact families:

```text
notes/accepted/Bxx.md
reports/accepted_overviews/Bxx_overview.md
candidates/accepted/Bxx_deep_reading_candidates.csv
```

Candidate tables are current reading-priority navigation tables, not automatic deep-reading queues.

Register these outputs in `batches/accepted_artifacts.json`. Drafts, packets, manifests, extracted text, and repair receipts are not accepted user-facing outputs until explicitly registered.

### Registry Authority

```text
batches/accepted_artifacts.json
```

This registry is the authority for accepted outputs: notes, overviews, candidate tables, selected final reports, and accepted warning/failure records. Artifact lifecycle is canonicalized in `status = active | superseded | archived`. `quality_status` is not a lifecycle field and should not be written by current registry writers. Filesystem facts still determine whether PDFs, manifests, body text, and deep text exist.

Current projects use strict registry checks: active notes, overviews, and candidate tables must include `batch`; active batch skim notes must include exact `paper_ids`; archive paths must not be active outputs. New Phase 2 skim work uses one batch note per batch.

## Phase 1: Inventory, Taxonomy, And Batch Plan

Phase 1 is intentionally unchanged.

Goal:

```text
source -> inventory -> first-pass taxonomy -> Bxx batch plan -> phase1 report
```

Inventory should preserve the existing CSV fields and metadata policy. Local no-metadata runs must stay explicitly metadata-unverified. Keep Phase 1 scaffolding minimal: source, scope, inventory, and report only.

Exit condition: `phase1_inventory.csv` and `phase1_report.md` exist, batches are assigned, and uncertainties are explicit.

## Phase 2: Skim Reading And Field Overview

Phase 2 is the default high-throughput reading stage. It should support approximately five minutes per paper.

Entry condition: inventory exists, a target Bxx is selected, every paper in the batch has a local PDF, and extraction quality has passed. Missing PDFs and low-quality extraction block routine skim until the user resolves them or explicitly authorizes partial skim.

Reuse the existing PDF safety pipeline:

1. Create or reuse `phase2_papers/Bxx_manifest.json`.
2. Ensure PDFs under immutable `raw_papers/`.
3. Copy valid raw PDFs into categorized `phase2_papers/` paths.
4. Validate PDFs locally.
5. Extract `.body.txt` main-body sidecars, stopping at references or appendices.
6. Check batch readiness before reading:
   - If any paper lacks a local PDF, stop and report paper ID, title, and download link.
   - If any extracted text is `low_quality`, `failed`, or `blocked_no_valid_text`, stop and report paper ID, title, quality status, section hits, warnings, and download link.
   - Continue only after the user resolves the issue or explicitly allows partial skim.
7. Write skim notes only for pass-quality evidence packets.

For template-v2 projects, `check-batch`, `prepare-batch`, and `run-next-microbatch` must surface missing local PDFs at the top level with `missing_pdfs` and a user-facing `human_report` when links are available from local metadata. User-facing replies must show `human_report` directly; do not replace it with only a missing count or title-only list. If a missing paper has no `public_pdf_url`, report `下载链接: 缺失，需要补 metadata 或人工查找` rather than fabricating a URL.

Do not start reading a batch while its PDFs are incomplete. Do not silently skip newly available packets because their micro-batch ID was accepted earlier; completion is determined by accepted paper coverage, not micro-batch ID alone.

Each new Phase 2 skim note is a compact packet-only note. It should answer:

1. What problem does the paper solve, and why is it difficult?
2. Why do the authors think the problem matters, why are existing methods insufficient, and why is the proposed method a natural direction?
3. What is the one-sentence method, intuitive view, and key changed step?
4. What changes relative to prior or baseline computation?
5. What does the packet support, and what remains uncertain?

Use the canonical per-paper heading and five internal blocks:

```md
### {paper_id} - {title}

#### 1. Problem and difficulty
#### 2. Motivation / Method Rationale
#### 3. Core method
#### 4. Method comparison diagram
#### 5. Evidence and uncertainty
```

For new drafts, this heading is exact and `{title}` must be nonempty.

Internal sections must use `####`, not `###`, so v2 parsers can treat only `### {paper_id} - {title}` as a paper entry. Do not add visible `Diagram type`, `Diagram verification`, `Evidence strength`, `Reading decision`, `Read priority`, or `Deep-note candidate` fields to new Phase 2 skim notes.

For batch-level skim notes, keep `Scope` stable across micro-batches: describe the full batch and packet-only status, and put changing coverage details only in `Coverage status`. Do not leave phrases such as `MB01 only`, `current coverage`, or `covering N of M` in Scope after the batch is complete. Write `Cross-paper comparison` as a bullet list grouped by readable comparison dimensions such as method family, objective/optimization, agent/trajectory, safety/alignment, or generalization.

The `Motivation / Method Rationale` block should be short. Prefer evidence from Introduction, Method opening, and Conclusion/Discussion/Limitations. Treat Related Work as fallback. Distinguish `[Paper-stated]` motivation from `[Inferred rationale]`, and include an evidence pointer such as `paper_id=..., packet=..., section=Introduction`.

Each new skim note must contain a compact ASCII comparison diagram inside `method-comparison:start/end` markers. The diagram must contain:

1. `Direct baseline`
2. `Representative prior`
3. `This paper`
4. `KEY CHANGED STEP`

When no reliable representative prior exists, keep the role and write `N/A / not available in packet`. Keep each line to at most 4-5 nodes. Do not include all experimental baselines, full losses, hyperparameters, or training details.

For template-v2 projects, use:

```text
notes/accepted/Bxx.md
reports/accepted_overviews/Bxx_overview.md
candidates/accepted/Bxx_deep_reading_candidates.csv
```

For low-context routine work, prepare or select bounded evidence packets before note writing when available. Do not load PDFs, full `.body.txt` / `.deep.txt`, accepted notes, accepted overviews, accepted candidate tables, deep notes, or archive repair notes into model context. Batch/packet manifests needed for paper_id/title/packet mapping remain allowed.

Packet-only routine:

1. Extract main-body text through the normal Phase 2 preparation pipeline.
2. Create bounded evidence packets with `create-evidence-packets`.
3. Plan micro-batches from the packet manifest, defaulting to at most four packets per turn.
4. Read only the current micro-batch packets plus the allowed batch/packet manifests.
   - `ready` is not a completion state. When `run-next-microbatch` returns `status: ready`, immediately execute the generated task: read allowed packets, update `notes/drafts/Bxx.md`, then rerun `run-next-microbatch`.
   - Stop only on `blocked`, `draft_complete`, or `complete`. After `draft_complete`, run `accept-draft` instead of reporting readiness as the final result.
5. Append or merge the new paper notes into one batch-level draft, `notes/drafts/Bxx.md`; do not overwrite earlier micro-batch entries without explicit user confirmation.
6. Do not accept micro-batches. `accept-draft` is a full-batch gate and computes expected `paper_ids` / `source_packets` from pass-quality packets in the packet manifest, not from draft frontmatter alone.
7. Before acceptance, run the batch-note mechanical check. Every expected paper must have one canonical `### {paper_id} - {title}` entry, the five canonical blocks, a method-comparison marker, `KEY CHANGED STEP`, and at least one evidence pointer. Missing structure, stale Scope micro-batch coverage, forbidden paths, TODOs, and placeholders are hard errors; dense non-bulleted cross-paper comparison, generic motivation, or historical recommendation fields are warnings/review flags.
8. Register the accepted batch note with `artifact_type=batch_skim_note`, `batch`, exact accepted `paper_ids`, and at most lightweight `warning_codes` / `review_status`.
9. Run `check-overview-gate` before writing a cumulative overview or candidate table; the gate is based on paper coverage, not micro-batch file count.

Default packet size is 12k characters. Projects may lower this in their local spec; do not silently raise it during routine runs. The default Phase 2 packet strategy is `intro_method_conclusion_v1`: include a compact Abstract excerpt, prioritize as much Introduction as the budget allows, reserve a bounded Conclusion/Discussion/Limitations excerpt, and use a small remaining budget for the Method opening. Related Work should normally serve as a boundary that prevents the Introduction from swallowing later sections, not as a budget target. Experiments/Results are not allocated routine skim budget; if absent from the packet, skim notes must not claim full experimental verification and should mark detailed result checking as uncertainty or a deep-reading task.

The cumulative overview should summarize technical routes, representative papers, recurring weaknesses, anchor-paper candidates, and low-priority papers. Its `Technical Routes` table is the default route-level taxonomy matrix. A Mermaid route map is optional; do not force a complex diagram into every overview.

The candidate CSV is a reading-navigation table. It should index skim notes without forcing deep-note decisions. Its preferred fields are:

```csv
paper_id,title,main_problem,motivation,core_method,key_changed_step,evidence_uncertainty,first_sections_to_read,possible_gpt_question
```

Candidate tables may preserve historical columns such as `technical_route`, `read_priority`, `read_reason`, `deep_note_candidate`, `deep_note_reason`, `arxiv_id`, `reading_batch`, `recommendation`, `recommendation_reason`, `evidence_strength`, `selected_for_phase3`, and `selection_notes`, but current tools use `paper_id` as the stable identity and `promote-to-deep` as the promotion entrypoint.

Phase 3 promotion must remain explicit. `promote-to-deep` is the primary action. Do not infer deep-note decisions from skim-note text.

## Phase 3: Optional Promoted Deep Reading

Phase 3 is optional archival mode for core papers. It begins only after the user explicitly promotes one or more papers, for example with `promote-to-deep`, "this paper needs a deep note", "deep-dive this paper", "I want to reproduce this", or "this is a core paper".

Selection rules:

- An empty candidate CSV means no Phase 3 work is needed.
- Candidate rows with blank `selected_for_phase3` are not promoted and do not block later batches or skim-level synthesis.
- All rows set to `no` allow skim-level Final synthesis.
- Any row set to `yes` triggers promoted deep reading for those papers only.

For selected papers, create `.deep.txt` sidecars that include appendices. Do not overwrite `.body.txt`.

Template-v2 Phase 3 uses the active accepted candidate table registered in `batches/accepted_artifacts.json`. Selected-paper PDF paths come from the batch manifest in `phase2_papers/` and its `local_pdf_path` / managed PDF path fields; do not reconstruct managed PDF names from inventory metadata when a manifest exists.

Template-v2 Phase 3 is batch-specific. Preparation writes `phase2_papers/Bxx_deep_text_manifest.json` and `phase2_papers/Bxx_phase3_deep_note_stubs.md`. The accepted note lives at `notes/accepted/Bxx_deep.md`.

Before accepting a Phase 3 note, run selected-paper coverage validation: every `selected_for_phase3=yes` paper must have exactly one recognizable deep-note entry, no selected paper may be missing, and unexpected paper IDs should fail the gate. Register accepted notes as `artifact_type=phase3_deep_note` with exact `paper_ids`, content hash, source candidate table, and source deep manifest.

Deep notes should remain compact and judgment-oriented. A deep note is a promoted-paper research judgment and long-term archive, not a longer skim note:

1. Keep the research decision summary short. Record an initial reading decision there, explain the technical mechanism fully once in its dedicated section, and reserve the final reading decision for the closing research judgment.
2. Compare direct baseline, representative prior, and this paper through an `Annotated Method Comparison Diagram` plus a three-way table.
3. Record formulation, objective, optimization or curriculum, inference procedure, assumptions, and computation cost.
4. Use a Claim-Evidence-Risk-Use table that records the research verdict or intended use of each claim.
5. Keep decision-critical evidence and appendix findings separate from reproduction-critical details.
6. End with a structured research judgment: what is solid, suggestive, task-specific, scaling-sensitive, and worth following up.

The Phase 3 main diagram should default to an ASCII/text pipeline. Use the same canonical roles as Phase 2 while increasing the specificity of the nodes to cover the key representation, module, objective, optimization, or inference procedure. Use Mermaid only as an optional auxiliary diagram when the main text pipeline cannot express critical structure. The main diagram must include:

1. `Direct baseline`
2. One or two `Representative prior` blocks
3. `This paper`

When no reliable representative prior exists, record `N/A: no representative prior identified.` and a brief reason instead of inventing a prior block.
Fill the `Representative prior` column in the three-way table with explicit `N/A` values rather than leaving it blank.

Use at most 3-5 nodes per role. Each role should show the core computation flow and key representation, module, or objective. Keep the main diagram concise: the diagram is for computation flow, while the table explains weaknesses, benefits, evidence, and remaining risks. The `This paper` role must label the `KEY CHANGED STEP`.

Keep deep diagram metadata minimal:

```text
Diagram type
Diagram verification
Diagram evidence location
Prior choice rationale
```

Do not repeat `Baseline components`, `Changed component`, or `Ours components` above the diagram. Follow the diagram with:

| Aspect | Direct baseline | Representative prior | This paper |
|---|---|---|---|
| Core operation |  |  |  |
| Key representation / module / objective |  |  |  |
| Main weakness |  |  |  |
| Key difference |  |  |  |
| Claimed benefit |  |  |  |
| Remaining weakness |  |  |  |

Allow at most one auxiliary diagram, and only when the main diagram cannot express critical information:

| Auxiliary diagram | Use case |
|---|---|
| Training-to-Inference Diagram | Post-training, curriculum, distillation, RL, alignment, or agent training |
| Mechanism Evidence Diagram | Strong internal-mechanism claims such as latent search, memory routing, or tool planning |
| System Architecture Diagram | Agent, tool, memory, or retrieval systems |
| Dataset/Evaluation Protocol Diagram | Benchmark, dataset, or evaluation papers |

Appendix-aware reading should check dataset details, hyperparameters, extra ablations, scaling, efficiency, and limitations when present. Put appendix findings that change the research judgment in the evidence section. Put dataset sizes, hyperparameters, schedules, and implementation details needed for reproduction in the reproduction section.

## Final Synthesis

Final synthesis stays a distinct stage.

Template-v2 first aggregates active registry artifacts:

```text
active phase3_deep_note + active batch_skim_note
+ active candidate tables + active overviews
```

For the same paper, selected deep notes override or supplement skim evidence, but skim notes remain in the input set. Final synthesis never reads outside active registry artifacts; repair or register current active artifacts before synthesis.
For `phase3-deep-v2`, the draft also summarizes selected-paper research judgments and the three-way method comparison table.
Deep notes are high-confidence evidence when present, but they are not required. Papers without deep notes must be treated as skim-level evidence only; important claims about them should be labeled provisional and may require manual confirmation or later promotion.

Outputs:

```text
final_literature_map.md
key_papers.md
research_opportunities.md
open_questions.md
```

Clearly label skim-level conclusions as provisional. When structured fields exist, synthesize problem landscape, mathematical formulations, method families, per-paper comparisons, recurring motivations, unresolved problems, and research opportunities.

## Note Quality

The quality checker and parser share `scripts/note_quality_rules.py`.

For new template-v2 Phase 2 batch skim notes, `accept-draft` applies a full-batch mechanical gate before registry acceptance. Hard errors include:

```text
missing expected paper_id from pass-quality packet manifest
missing canonical per-paper entry heading
missing canonical five blocks
missing evidence pointer
missing method-comparison marker
missing Direct baseline / Representative prior / This paper / KEY CHANGED STEP
stale micro-batch coverage statement in Scope
forbidden context path reference
TODO or placeholder content
```

Warnings/review flags include dense non-bulleted cross-paper comparison, generic motivation, historical recommendation fields, or other semantic-quality concerns that are useful for review but should not initially block acceptance. Accepted registry entries may store lightweight `review_status` and `warning_codes`; detailed checker output belongs in stdout or logs/reports.

Non-current notes are outside the normal workflow. Archive them separately or convert them manually before acceptance.

The Motivation / Method Rationale requirements apply to newly generated skim notes and explicit quality checks. Do not batch-rewrite, migrate, or retroactively revalidate already accepted notes/artifacts solely because they predate this subsection.

`validate-project` checks current registry entry shape, active path existence, active content hash, artifact type/batch/active consistency, and canonical active batch-skim-note content. Hash mismatches, missing active paths, and noncanonical active batch notes are hard failures. Archived and superseded artifacts are ignored.

`Diagram type` and stricter structural diagram rules are checked when `scripts/check_notes_quality.py` is explicitly run. Current accepted drafts are still gated by `accept-draft`.

Phase 3 note checks apply to current `phase3-deep-v2` accepted artifacts in the normal path.

For new `phase3-deep-v2`, require a short decision summary, a single full technical-mechanism explanation, decision-critical evidence, reproduction-critical details, a structured research judgment, tagged facts/interpretation/evidence, an annotated comparison diagram, a populated three-way comparison table, and a populated Claim-Evidence-Risk-Use row.

Reject untouched Mermaid placeholders. Require baseline and ours component lists to differ, and require the changed-component text to match at least one meaningful token in the diagram. This is a consistency check, not a substitute for human semantic verification.

When `scripts/check_notes_quality.py` is explicitly run, also apply strict diagram checks:

1. New skim diagrams contain the canonical marker, `Direct baseline`, `Representative prior` or explicit packet-only `N/A`, `This paper`, and `KEY CHANGED STEP`.
2. Deep notes contain the `Annotated Method Comparison Diagram` heading, baseline/prior-or-`N/A`/this-paper roles, and the changed step. For `phase3-deep-v2`, claimed benefit and weaknesses belong in the three-way table rather than crowded diagram nodes.
3. Deep diagrams stay within four compared methods and 3-5 nodes per role for the main ASCII/text pipeline.
4. Notes flag obvious long repeated method explanations.
5. Potentially speculative diagram claims without `[Interpretation]` or `[Needs verification]` are reported for review.

These strict checks are advisory outside acceptance, but active accepted artifacts must satisfy the current template-v2 contract.

Non-current notes are outside the normal workflow. Archive them separately or convert them manually before acceptance.

## State Detection

The state checker reports:

```text
workflow_mode: three_stage
phase2.skim_started
phase2.skim_complete
phase3.deep_started
phase3.deep_complete
phase3.accepted_failure_entries
```

Three-stage batch status:

```text
planned
manifest_ready
pdfs_valid
ready_for_skim
skim_started
skim_complete
```

Phase 3 status:

```text
not_ready
awaiting_selection_review
skipped
selected_pending
deep_text_ready
deep_notes_complete
accepted_failures_only
deep_notes_complete_with_accepted_failures
```

Accepted Phase 3 deep-text failures are counted separately. They may allow Final synthesis to continue with warnings, but they never count as completed deep notes.

Recommended next actions:

```text
run phase1
plan reading batches
write phase1 report
process Bxx
write skim notes for Bxx
write phase2 skim overview
review invalid phase3 selections
promote selected core papers to deep note
prepare phase3 deep reading
write deep notes for selected papers
review phase3 failures or continue final with warnings
write final synthesis
complete
```

Do not report Phase 3 files as missing before selected papers exist. Do not report missing skim notes merely because `raw_papers/` or `phase2_papers/` exists. If accepted registry artifacts are missing, register current artifacts before continuing.

## Runner Actions

Use the high-level runner:

```bash
python scripts/literature_workflow.py --root . --action state
python scripts/literature_workflow.py --root . --action next
python scripts/literature_workflow.py --root . --action prepare-batch --batch B01 --plan-only
python scripts/literature_workflow.py --root . --action phase2-overview --plan-only
python scripts/literature_workflow.py --root . --action promote-to-deep --batch B01 --paper-id arxiv:2401.00001 --plan-only
python scripts/literature_workflow.py --root . --action phase3-deep --plan-only
python scripts/literature_workflow.py --root . --action final --plan-only
```

Use the read-only harness for registry, root-cleanliness, context, and representative-candidate checks:

```bash
python scripts/literature_harness.py --root . --action status
python scripts/literature_harness.py --root . --action check-registry
python scripts/literature_harness.py --root . --action check-root-clean
python scripts/literature_harness.py --root . --action check-context-budget --paths path/to/packet.md
python scripts/literature_harness.py --root . --action check-representative-candidates
python scripts/literature_harness.py --root . --action create-evidence-packets --batch B01 --allow-write
python scripts/literature_harness.py --root . --action plan-micro-batches --packet-manifest phase2_papers/B01_packet_manifest.json
python scripts/literature_harness.py --root . --action check-overview-gate --batch B01 --packet-manifest phase2_papers/B01_packet_manifest.json
python scripts/literature_harness.py --root . --action archive-superseded --plan-only
```

Register accepted outputs through the harness only after quality and path checks:

```bash
python scripts/literature_harness.py --root . --action register-artifact --artifact-type note --artifact-path notes/accepted/B01.md --batch B01 --allow-write
python scripts/literature_harness.py --root . --action register-artifact --artifact-type note --artifact-path notes/accepted/B01-v2.md --supersedes notes/accepted/B01.md --allow-write
```

The register action is append-oriented. It creates v2 registries for new projects and marks explicitly superseded active entries as `superseded` before appending the replacement entry.

The archive action is plan-first. Use `--plan-only` before `--allow-write`; it moves only registry entries already marked `superseded` into `archive/superseded_notes/`, `archive/superseded_reports/`, `archive/raw_tables/`, or `archive/repair_history/`.

All runner writes require `--allow-write`. Network actions require `--allow-network`. Real PDF downloads require `--download --allow-network --allow-write`.

In Codex sessions where the user explicitly approves online literature initialization, prefer the `research-online` profile for shell network access. This avoids repeated failed clone/fetch attempts under the default offline sandbox while preserving separate approval gates for arXiv metadata, PDF download, dependencies, and external code execution.

For template-v2 projects, `prepare-batch` performs real PDF text extraction with `pypdf` when a valid local or downloaded PDF is available. Template-v2 PDF extraction requires `pypdf`; install it with `python -m pip install pypdf`. The runner writes bounded body-text and packet manifests only after the extracted main-body text passes a mechanical quality gate. Placeholder text such as "PDF available..." or "Full extraction not performed..." is blocked and must not become an evidence packet. If `pypdf` is unavailable, the PDF is invalid, extraction fails, or the body text is too weak, the paper remains unreadable for micro-batch work and `run-next-microbatch` blocks until usable text is available.

Low-level helpers enforce the same gates. `--overwrite` permits replacing an existing output but never substitutes for `--allow-write`. Node validation may run without write permission only with `--no-status-write`.


Explicitly accepted text-extraction failures may be recorded in optional `accepted_failures.json`:

```json
{
  "phase2_body_text": ["2401.00001"],
  "phase3_deep_text": ["2401.00002"]
}
```

Without that file, missing required text blocks the corresponding stage.

## Recovery And Safety

- Inspect manifests, status files, PDF counts, and text counts before retrying an interrupted run.
- Retry only missing or invalid PDFs when possible.
- Treat `.part` cleanup warnings as non-blocking when final PDFs validate.
- Never move or delete files in `raw_papers/`.
- Keep scratch test data outside real projects and clean it up afterward.
