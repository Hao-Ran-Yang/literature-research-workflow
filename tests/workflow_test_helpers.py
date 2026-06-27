import csv
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
import os
from unittest import mock
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
INVENTORY_FIELDS = [
    "section",
    "method_category",
    "application_tag",
    "reading_batch",
    "arxiv_id",
    "title",
    "authors",
    "first_submitted",
    "latest_version_date",
    "abs_url",
    "pdf_url",
    "source_url",
    "reading_priority",
    "classification_confidence",
    "classification_source",
    "notes",
]


def run_json(script: str, *args: str, cwd: Path) -> dict:
    command = [sys.executable, "-B", str(SCRIPTS / script), *args]
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            check=True,
            text=True,
            capture_output=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        raise AssertionError(
            "command timed out after 60s\n"
            f"command: {' '.join(command)}\n"
            f"stdout tail: {stdout[-1000:]}\n"
            f"stderr tail: {stderr[-1000:]}"
        ) from exc
    return json.loads(completed.stdout)


def write_accepted_registry(root: Path, artifacts: list[dict]) -> None:
    path = root / "batches" / "accepted_artifacts.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = []
    for artifact in artifacts:
        item = dict(artifact)
        item.setdefault("status", "active")
        normalized.append(item)
    path.write_text(json.dumps({"schema_version": "template-v2.1", "version": 2, "artifacts": normalized}), encoding="utf-8")


def read_csv_rows(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def load_awesome_harness():
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("awesome_literature_harness_for_tests", SCRIPTS / "awesome_literature_harness.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def rich_body_text(label: str) -> str:
    return f"""Abstract
{label} studies a reliable literature workflow for paper evidence extraction. The abstract describes the scope, input assumptions, and expected review artifacts in enough detail for testing.

Introduction
The introduction explains why placeholder evidence is unsafe. A reading workflow should distinguish available PDFs from actually extracted paper text. This section mentions references in prose without using the references heading. This section repeats enough natural language to produce a substantial body for packet creation and quality checks.

Method
The method uses validated local PDFs, main-body extraction, section-aware packet construction, and explicit evidence pointers. It blocks placeholder text and records status for each paper. The implementation is conservative and avoids inventing claims.

Experiments
The experiments evaluate fake PDFs, locally imported PDFs, non-arXiv paper identifiers, idempotent reruns, and packet manifests. Results show that only genuine body text should become readable packet evidence.

Results
The result section confirms that readable papers require pass-quality body text. Packet text remains bounded, structured, and marked as untrusted evidence.

Conclusion
The conclusion summarizes that template-v2 should block placeholder packets and proceed only after valid extraction or existing high-quality body text.
""" * 4


def minimal_text_pdf_bytes(text: str) -> bytes:
    lines = [line for line in text.splitlines() if line.strip()]
    escaped_lines = []
    for line in lines[:80]:
        safe = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        escaped_lines.append(f"({safe}) Tj T*")
    stream = "BT /F1 10 Tf 50 760 Td 12 TL\n" + "\n".join(escaped_lines) + "\nET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(stream.encode('latin-1', errors='replace'))} >>\nstream\n{stream}\nendstream".encode("latin-1", errors="replace"),
    ]
    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for idx, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{idx} 0 obj\n".encode("ascii"))
        pdf.extend(obj)
        pdf.extend(b"\nendobj\n")
    xref = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    pdf.extend(f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("ascii"))
    return bytes(pdf)


def write_inventory(root: Path) -> dict:
    row = {
        "section": "Core",
        "method_category": "Adapters",
        "application_tag": "NLP",
        "reading_batch": "B01 Core",
        "arxiv_id": "2401.00001",
        "title": "Example Paper",
        "authors": "A. Author",
        "first_submitted": "2024-01-01",
        "latest_version_date": "2024-01-02",
        "abs_url": "https://arxiv.org/abs/2401.00001",
        "pdf_url": "https://arxiv.org/pdf/2401.00001.pdf",
        "source_url": "",
        "reading_priority": "high",
        "classification_confidence": "high",
        "classification_source": "test",
        "notes": "",
    }
    with (root / "phase1_inventory.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=INVENTORY_FIELDS)
        writer.writeheader()
        writer.writerow(row)
    (root / "source_links.md").write_text("# Source Links\n", encoding="utf-8")
    (root / "scope.md").write_text("# Scope\n", encoding="utf-8")
    (root / "phase1_report.md").write_text("# Phase 1 Report\n\nComplete.\n", encoding="utf-8")
    return row


def write_inventory_rows(root: Path, rows: list[dict], report: bool = True) -> None:
    with (root / "phase1_inventory.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=INVENTORY_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    (root / "source_links.md").write_text("# Source Links\n", encoding="utf-8")
    (root / "scope.md").write_text("# Scope\n", encoding="utf-8")
    if report:
        (root / "phase1_report.md").write_text("# Phase 1 Report\n\nComplete.\n", encoding="utf-8")


def create_ready_batch(root: Path, row: dict) -> tuple[Path, Path]:
    pdf = root / "phase2_papers" / "Core" / "Adapters" / "2401.00001.pdf"
    pdf.parent.mkdir(parents=True, exist_ok=True)
    pdf.write_bytes(b"%PDF-" + b"x" * 22000)
    body = pdf.with_suffix(".body.txt")
    body.write_text("main body " * 200, encoding="utf-8")
    manifest_row = {**row, "pdf_path": str(pdf)}
    manifest = root / "phase2_papers" / "B01_manifest.json"
    manifest.write_text(json.dumps([manifest_row], indent=2), encoding="utf-8")
    return manifest, pdf


def complete_skim_notes() -> str:
    return """# Phase 2 Skim Notes

## B01 Skim Notes

#### 1. Example Paper

- Note type: non-current-skim
- arXiv: 2401.00001
- Technical route: Adapters

### 1. Problem and difficulty
- Problem: Reduce adaptation cost.
- Why hard: Full updates are expensive.
- [Paper-stated] The paper studies efficient adaptation.
- [Interpretation] The changed bottleneck is the update path.

### 2. Motivation / Method Rationale
- [Paper-stated] Motivation: Full-model adaptation is costly enough to make efficient task transfer important.
- [Paper-stated] Why existing methods are not enough: Full updates spend parameters on broad changes rather than a narrow adaptation path.
- [Inferred rationale] Why this method is natural: If the bottleneck is update dimensionality, a residual adapter is a direct way to constrain the trainable subspace.
- Evidence pointer: Introduction / Section 1.

### 3. Core method
- One-sentence method: Add a small trainable adapter.
- Intuitive view: Update a narrow branch.
- Mathematical view: Optimize a low-dimensional residual.

### 4. Method comparison diagram
- Diagram type: inference / reasoning pipeline
- Diagram verification: verified
<!-- method-comparison:start -->
```text
Direct baseline:      [Input] -> [Full-model update] -> [Output]
Representative prior: [Input] -> [Reduced update path] -> [Output]
This paper:           [Input] -> [KEY CHANGED STEP: adapter update] -> [Output]
```
<!-- method-comparison:end -->

| Aspect | Baseline / Prior | This paper |
|---|---|---|
| Changed component | Full-model update | Adapter branch |
| Intuition | Update every parameter | Update a narrow branch |
| Weakness addressed | Full updates are expensive | Reduce trainable parameters |
| Remaining weakness | High adaptation cost | Adapter width sensitivity |

### 5. Evidence strength
- Evidence strength: medium
- Main evidence: Table 1 compares accuracy and cost.
- [Evidence] Table 1.
- Main uncertainty: Appendix scaling remains to inspect.

### 6. Deep-read decision
- Deep-read recommendation: yes
- Priority: high
- Reason: It represents the adapter route.
"""


def complete_deep_notes() -> str:
    return """# Phase 3 Deep Notes

## B01 Phase 3 Selected Deep Reading

#### 1. Example Paper

- Note type: non-current-deep
- arXiv: 2401.00001
- Why selected: Representative route.
- Appendix checked: yes
- Appendix sections checked: A and B.

### 1. Research decision summary
- Research question: Can adaptation cost be reduced?
- Core idea: Train a residual adapter branch.
- Why it matters: It avoids full-model updates.
- [Paper-stated] The adapter is trainable.
- [Interpretation] The key change is update dimensionality.

### 2. Annotated Method Comparison Diagram
- Diagram type: training / post-training
- Baseline components: pretrained model, full update
- Changed component: adapter
- Ours components: pretrained model, adapter update
- Diagram verification: verified
- Diagram evidence location: Section 2.
- [Interpretation] The claimed benefit follows the paper's cost comparison.
<!-- method-comparison:start -->
```mermaid
flowchart LR
  subgraph baseline["Direct baseline"]
    B1["Input"] --> B2["Full-model update"] --> B3["Output<br/>Main weakness: expensive updates"]
  end
  subgraph prior["Representative prior"]
    P1["Input"] --> P2["Reduced update path"] --> P3["Output<br/>Main weakness: limited flexibility"]
  end
  subgraph ours["This paper"]
    O1["Input"] --> O2["KEY CHANGED STEP: adapter update<br/>Claimed benefit: lower adaptation cost<br/>Weakness addressed: expensive full updates"] --> O3["Output<br/>Remaining weakness: adapter width sensitivity"]
  end
```
<!-- method-comparison:end -->

| Aspect | Baseline / Prior | This paper |
|---|---|---|
| Changed component | Full-model update | Adapter branch |
| Intuition | Update every parameter | Train a residual branch |
| Weakness addressed | Expensive updates | Reduce trainable parameters |
| Remaining weakness | High adaptation cost | Adapter width sensitivity |

### 3. Technical mechanism
- Problem formulation: Adapt a pretrained model.
- Objective: Minimize task loss.
- Optimization: Update adapter parameters.
- Inference flow: Run base model with adapter.
- Assumptions: Base features transfer.

### 4. Claim-Evidence-Risk table
| Claim | Status: proved / supported / suggested | Evidence location | Alternative explanation or risk |
|---|---|---|---|
| Adapters reduce cost | supported | Table 1 | Hardware effects may vary |

### 5. Experiments and appendix-aware findings
- Main experiments: Accuracy and cost comparison.
- Ablations: Adapter width.
- Dataset details: Appendix A.
- Hyperparameters: Appendix B.
- Scaling results: Not provided by the paper.
- Efficiency results: Table 1.
- Limitations: Limited model scale.
- [Evidence] Table 1 and Appendix A.

### 6. Reproduction and follow-up notes
- Code/data availability: Not provided by the paper.
- Minimal reproduction path: Add an adapter module and run one task.
- Missing implementation details: Initialization details.
- Candidate code changes: Add adapter configuration.
- Follow-up experiment: Sweep adapter width.
- Main risk: Cost gains may not transfer.

### 7. Research judgment
- Strengths: Clear computation change.
- Weaknesses: Limited scale.
- Relation to my interests: Efficient post-training.
- Next action: Reproduce one task.
"""


def complete_deep_v2_notes() -> str:
    return """# Phase 3 Deep Notes

## B01 Phase 3 Selected Deep Reading

#### 1. Example Paper

- Note type: phase3-deep-v2
- arXiv: 2401.00001
- Appendix checked: yes
- Appendix sections checked: A and B.

### 1. Research decision summary
- Research question: Can adaptation cost be reduced?
- Core contribution in one sentence: Train a residual adapter branch.
- Why selected: Representative route.
- Why it matters: It avoids full-model updates.
- Main caution: Evidence is limited to controlled settings.
- Initial reading decision: Reproduce one task.
- [Paper-stated] The adapter is trainable.
- [Interpretation] The key change is update dimensionality.

### 2. Annotated Method Comparison Diagram
- Diagram type: training / post-training
- Diagram verification: verified
- Diagram evidence location: Section 2.
- Prior choice rationale: Reduced update paths are the closest computation-flow comparison.
<!-- method-comparison:start -->
```text
Direct baseline
  [Input] -> [Full-model update] -> [Output]

Representative prior
  [Input] -> [Reduced update path] -> [Output]

This paper
  [Input] -> [KEY CHANGED STEP: adapter update] -> [Output]
```
<!-- method-comparison:end -->

| Aspect | Direct baseline | Representative prior | This paper |
|---|---|---|---|
| Core operation | Full-model update | Reduced update path | Adapter update |
| Key representation / module / objective | Full parameters | Restricted update path | Residual adapter |
| Main weakness | Expensive updates | Limited flexibility | Width sensitivity |
| Key difference | Update everything | Restrict updates | Add a trainable branch |
| Claimed benefit | Flexible adaptation | Lower cost | Lower adaptation cost |
| Remaining weakness | High adaptation cost | Restricted updates | Adapter width sensitivity |

### 3. Technical mechanism
- Problem formulation: Adapt a pretrained model.
- Objective: Minimize task loss.
- Optimization / curriculum: Update adapter parameters.
- Inference procedure: Run base model with adapter.
- Assumptions: Base features transfer.
- Computation cost: Adds a narrow residual branch.

### 4. Claim-Evidence-Risk-Use table
| Claim | Status: proved / supported / suggested | Evidence | Risk / alternative explanation | My verdict / use |
|---|---|---|---|---|
| Adapters reduce cost | supported | Table 1 | Hardware effects may vary | Reliable enough for a small reproduction |

### 5. Decision-critical evidence and appendix-aware findings
- Main evidence supporting the paper: Table 1 compares accuracy and cost.
- Evidence that weakens or bounds the claim: Results cover limited model scale.
- Appendix findings that change the judgment: Appendix A reports width sensitivity.
- Limitations: Limited model scale.
- [Evidence] Table 1 and Appendix A.

### 6. Reproduction and follow-up notes
- Code/data availability: Not provided by the paper.
- Reproduction-critical dataset details: Appendix A.
- Reproduction-critical hyperparameters: Appendix B.
- Minimal reproduction path: Add an adapter module and run one task.
- Missing implementation details: Initialization details.
- Follow-up experiments: Sweep adapter width.
- Main reproduction risk: Cost gains may not transfer.

### 7. Research judgment
- What is solid: The computation change is clear.
- What is suggestive but not proven: Cost gains may generalize.
- What is likely task-specific: The best adapter width.
- What may fail when scaling: Efficiency gains may shrink.
- Best follow-up for my research: Reproduce one task and sweep width.
- Final reading decision: Build on the controlled result only.
"""


def non_current_notes() -> str:
    return """# Phase 2 Reading Notes

## B01 Non-current Notes

#### 1. Example Paper

1. **Basic information**
- arXiv: 2401.00001
2. **Research problem**
- Summary: Efficient adaptation.
3. **Core idea**
- Adapter branch.
4. **Method details**
- Section 2 describes the method.
5. **Experiments**
- Table 1 reports 2 datasets.
6. **Weaknesses and assumptions**
- Limited scale.
7. **One-sentence takeaway**
- Useful adapter baseline.
"""


def v2_notes() -> str:
    return """# Phase 2 Reading Notes

## B01 V2 Notes

#### 1. Example Paper

1. **Basic information**
- arXiv: 2401.00001
2. **Research problem**
- [Paper-stated] Efficient adaptation.
3. **Core idea**
- [Interpretation] Adapter branch.
4. **Method details**
- [Evidence] Section 2.
5. **Experiments**
- Table 1 reports 2 datasets.
6. **Weaknesses and assumptions**
- Limited scale.
7. **One-sentence takeaway**
- Useful adapter baseline.
"""
