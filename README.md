# Literature Research Workflow

A Codex skill for turning paper lists, local PDFs, and literature-review projects into a traceable, staged research workflow.

This project is designed for researchers who want to use Codex as a literature-reading assistant without letting it freely consume huge PDFs, mix draft and accepted notes, or produce final summaries from unverified intermediate files.

The main interface is **conversation with Codex**. The Python scripts in this repository are implementation details used by the skill.

---

## What this skill helps you do

With this skill installed, you can ask Codex to help you:

- turn an awesome-paper list or bibliography into a structured reading project;
- organize papers into batches;
- prepare evidence packets instead of reading entire PDFs at once;
- write Phase 2 skim notes for many papers;
- compare papers and select a small number for deeper reading;
- write optional Phase 3 deep notes for selected core papers;
- generate a final synthesis from accepted artifacts only.

The workflow is intentionally conservative: Codex should read from bounded evidence packets, write drafts first, and only promote files to accepted artifacts after explicit checks.

---

## How to use it in Codex

Install or place this repository as a Codex skill, then open a literature project folder in Codex.

You usually do **not** need to call the underlying scripts yourself. Instead, talk to Codex in natural language.

### Start a new project from an awesome-paper list

Example prompt:

```text
Use the literature-research-workflow skill to initialize a literature project from this awesome-paper list.
First run the initialization and Phase 1 inventory steps only.
Do not download PDFs yet.
Show me the planned batches before continuing.
```

### Continue with the next batch

Example prompt:

```text
Use the literature-research-workflow skill to continue the next planned batch.
Prepare evidence packets first.
Use micro-batches.
Do not read full PDFs directly unless the skill workflow explicitly allows it.
After each micro-batch, write draft Phase 2 skim notes and wait for acceptance.
```

### Import local PDFs

Example prompt:

```text
I have placed several PDFs in this project folder.
Use the literature-research-workflow skill to import the local PDFs into the workflow.
Prepare packet-based Phase 2 reading.
Do not move or delete the original PDFs unless the workflow requires a safe copy.
```

### Accept generated notes

Example prompt:

```text
Check the latest draft Phase 2 skim notes.
If they satisfy the current template and evidence requirements, accept them into the registry.
If not, explain what needs to be fixed.
```

### Select papers for deep reading

Example prompt:

```text
Review the accepted Phase 2 skim notes and candidate table.
Recommend which papers should be promoted to Phase 3 deep reading.
Explain the reason for each recommendation.
Do not create deep notes until I confirm the selection.
```

### Generate a final synthesis

Example prompt:

```text
Use only accepted artifacts in the registry to write the final synthesis.
Do not use stale drafts, raw PDFs, or unaccepted notes.
Separate established findings from uncertain or weakly supported claims.
```

---

## Typical workflow

A normal project looks like this:

```text
paper list or PDFs
→ Phase 1 inventory
→ batch planning
→ packet-based Phase 2 skim notes
→ accepted overviews and candidate tables
→ optional Phase 3 deep notes for selected papers
→ final synthesis from accepted artifacts
```

The important idea is that **Codex should not jump straight from raw PDFs to a final literature review**.  
The skill enforces intermediate artifacts so that the review remains inspectable and correctable.

---

## Safety model

This skill is built around a few practical safety rules:

- **Draft before accept**: generated notes and reports are drafts until explicitly accepted.
- **Registry is authoritative**: final synthesis should rely on accepted artifacts, not random files.
- **Packet-only reading**: Codex should use bounded evidence packets instead of loading full paper bodies into context.
- **Explicit gates**: writing, downloading, and accepting artifacts should happen through deliberate workflow steps.
- **Human selection for deep reading**: Phase 3 deep notes are for a small number of important papers, not every paper.

These rules are meant to reduce hallucination, control context cost, and keep the literature review auditable.

---

## Repository layout

```text
SKILL.md       Codex-facing skill instructions
docs/          workflow specification and reference notes
scripts/       implementation scripts used by the skill
schemas/       JSON schemas for workflow artifacts
templates/     project templates and note templates
tests/         regression tests
agents/        supporting agent instructions
```

Most users should start from `SKILL.md` and the example prompts above.  
The scripts are mainly for Codex and for maintainers who want to inspect or extend the workflow.

---

## Requirements

The workflow is intended for local Codex use.

Basic requirements:

- Python 3.10+
- `pypdf` for PDF text extraction
- Git, optional but useful for projects based on GitHub paper lists
- Node.js, optional for some downloader or fetch-related helpers

Install Python dependencies with:

```bash
pip install -r requirements.txt
```

---

## Current status

This is an early public release of a research workflow skill.

It is suitable for personal research projects and controlled literature-review workflows, but it is not a fully automatic paper-review system. Important claims should still be checked against the original papers.

Recommended release label:

```text
v0.1.0-alpha
```

---

## License

MIT License.
