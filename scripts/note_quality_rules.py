import re


NOTE_TYPE_RE = re.compile(r"^\s*-\s*Note type\s*:\s*(\S+)\s*$", re.IGNORECASE | re.MULTILINE)
METHOD_DIAGRAM_RE = re.compile(
    r"<!--\s*method-comparison:start\s*-->.*?<!--\s*method-comparison:end\s*-->",
    re.IGNORECASE | re.DOTALL,
)
ANNOTATED_DIAGRAM_HEADING_RE = re.compile(
    r"^\s*###\s+2\.\s+Annotated Method Comparison Diagram\s*$",
    re.IGNORECASE | re.MULTILINE,
)
MERMAID_SUBGRAPH_RE = re.compile(
    r"^\s*subgraph\s+([^\r\n]+)\r?\n(.*?)^\s*end\s*$",
    re.IGNORECASE | re.MULTILINE | re.DOTALL,
)
ASCII_PIPELINE_RE = re.compile(
    r"^\s*([A-Za-z][A-Za-z0-9 /_-]{1,80})\s*:\s*(.*(?:--?>|->).*)$",
    re.MULTILINE,
)
ASCII_BLOCK_PIPELINE_RE = re.compile(
    r"^\s*(Direct baseline|Representative prior(?:\s+\d+)?|This paper)\s*$\r?\n\s+(.+(?:--?>|->).*)$",
    re.IGNORECASE | re.MULTILINE,
)
AUXILIARY_DIAGRAM_RE = re.compile(
    r"^\s*#{1,6}\s+(?:Optional\s+)?(?:Training-to-Inference|Mechanism Evidence|System Architecture|Dataset/Evaluation Protocol)\s+Diagram\s*$",
    re.IGNORECASE | re.MULTILINE,
)
SPECULATIVE_DIAGRAM_RE = re.compile(
    r"\b(?:because|therefore|implies?|likely|may|might|causes?|enables?|improves?|mechanism|claimed benefit)\b",
    re.IGNORECASE,
)
SPECULATIVE_SECTION_RE = re.compile(
    r"\b(?:because|therefore|implies?|likely|may|might|causes?|enables?|improves?|mechanism)\b",
    re.IGNORECASE,
)
NO_REPRESENTATIVE_PRIOR_RE = re.compile(
    r"N/A\s*:\s*no representative prior identified",
    re.IGNORECASE,
)
DIAGRAM_TYPES = {
    "inference / reasoning pipeline",
    "training / post-training",
    "architecture / system",
    "objective / optimization / theory",
    "benchmark / dataset",
}
COMPARISON_TABLE_ASPECTS = {
    "changed component",
    "intuition",
    "weakness addressed",
    "remaining weakness",
}
DEEP_V2_COMPARISON_TABLE_ASPECTS = {
    "core operation",
    "key representation / module / objective",
    "main weakness",
    "key difference",
    "claimed benefit",
    "remaining weakness",
}
V3_REQUIRED_TAGS = ("Paper-stated", "Interpretation", "Evidence")
DEEP_V2_REQUIRED_FIELDS = (
    "Research question",
    "Core contribution in one sentence",
    "Why selected",
    "Why it matters",
    "Main caution",
    "Initial reading decision",
    "Final reading decision",
    "Appendix checked",
    "Problem formulation",
    "Objective",
    "Optimization / curriculum",
    "Inference procedure",
    "Assumptions",
    "Computation cost",
    "Main evidence supporting the paper",
    "Evidence that weakens or bounds the claim",
    "Appendix findings that change the judgment",
    "Limitations",
    "Code/data availability",
    "Reproduction-critical dataset details",
    "Reproduction-critical hyperparameters",
    "Minimal reproduction path",
    "Missing implementation details",
    "Follow-up experiments",
    "Main reproduction risk",
    "What is solid",
    "What is suggestive but not proven",
    "What is likely task-specific",
    "What may fail when scaling",
    "Best follow-up for my research",
    "Diagram verification",
    "Diagram evidence location",
    "Prior choice rationale",
)


def detect_note_format(body: str) -> str:
    match = NOTE_TYPE_RE.search(body)
    if match:
        return match.group(1).lower()
    return "unknown"


def has_nonempty_tag(body: str, tag: str) -> bool:
    pattern = re.compile(
        rf"^[^\S\r\n]*-[^\S\r\n]*\[{re.escape(tag)}\][^\S\r\n]*:?[^\S\r\n]*(.*)$",
        re.IGNORECASE | re.MULTILINE,
    )
    return any(match.group(1).strip() for match in pattern.finditer(body))


def has_nonempty_field(body: str, field: str) -> bool:
    pattern = re.compile(
        rf"^[^\S\r\n]*-[^\S\r\n]*(?:\[[^\]]+\][^\S\r\n]*)?{re.escape(field)}[^\S\r\n]*:[^\S\r\n]*(.*)$",
        re.IGNORECASE | re.MULTILINE,
    )
    return any(match.group(1).strip() for match in pattern.finditer(body))


def has_method_comparison_diagram(body: str) -> bool:
    match = METHOD_DIAGRAM_RE.search(body)
    if not match:
        return False
    diagram = match.group(0).lower()
    placeholders = (
        "prior / baseline step",
        "ours: changed step",
        "prior / baseline pipeline",
        "ours: changed component",
        "[baseline step]",
        "[prior step]",
        "[key changed step: ...]",
        "baseline step / representation",
        "baseline operation / representation",
        "prior module / objective",
    )
    return ("prior" in diagram or "baseline" in diagram) and ("ours" in diagram or "this paper" in diagram) and not any(item in diagram for item in placeholders)


def diagram_text(body: str) -> str:
    match = METHOD_DIAGRAM_RE.search(body)
    return match.group(0).lower() if match else ""


def append_unique(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def role_occurrences(diagram: str, role: str) -> int:
    if role == "representative prior":
        return len(re.findall(r"\brepresentative prior(?:\s+\d+)?\b", diagram, re.IGNORECASE))
    return len(re.findall(rf"\b{re.escape(role)}\b", diagram, re.IGNORECASE))


def diagram_blocks(diagram: str) -> list[tuple[str, str]]:
    subgraphs = [(header.strip(), content.strip()) for header, content in MERMAID_SUBGRAPH_RE.findall(diagram)]
    if subgraphs:
        return subgraphs
    block_pipelines = [(label.strip(), pipeline.strip()) for label, pipeline in ASCII_BLOCK_PIPELINE_RE.findall(diagram)]
    if block_pipelines:
        return block_pipelines
    return [(label.strip(), pipeline.strip()) for label, pipeline in ASCII_PIPELINE_RE.findall(diagram)]


def is_mermaid_diagram(diagram: str) -> bool:
    return "```mermaid" in diagram.lower()


def diagram_global_node_count(diagram: str) -> int:
    return block_node_count(diagram)


def has_no_representative_prior(diagram: str) -> bool:
    return bool(NO_REPRESENTATIVE_PRIOR_RE.search(diagram))


def has_no_representative_prior_reason(diagram: str) -> bool:
    return bool(re.search(r"N/A\s*:\s*no representative prior identified.*?\bReason\s*:\s*\S+", diagram, re.IGNORECASE | re.DOTALL))


def block_node_count(content: str) -> int:
    node_ids = set(re.findall(r"\b([A-Za-z][A-Za-z0-9_]*)\s*(?=\[|\()", content))
    if node_ids:
        return len(node_ids)
    return len(re.findall(r"\[[^\]]+\]", content))


def has_complete_diagram_comparison_table(body: str) -> bool:
    match = METHOD_DIAGRAM_RE.search(body)
    if not match:
        return False
    remainder = body[match.end() :]
    next_heading = re.search(r"^\s*###\s+", remainder, re.MULTILINE)
    table_area = remainder[: next_heading.start()] if next_heading else remainder
    complete = set()
    for line in table_area.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) >= 3 and cells[0].lower() in COMPARISON_TABLE_ASPECTS and all(cells[1:3]):
            complete.add(cells[0].lower())
    return complete == COMPARISON_TABLE_ASPECTS


def has_complete_deep_v2_comparison_table(body: str) -> bool:
    match = METHOD_DIAGRAM_RE.search(body)
    if not match:
        return False
    remainder = body[match.end() :]
    next_heading = re.search(r"^\s*###\s+", remainder, re.MULTILINE)
    table_area = remainder[: next_heading.start()] if next_heading else remainder
    expected_header = ["aspect", "direct baseline", "representative prior", "this paper"]
    header_ok = False
    complete = set()
    for line in table_area.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if [cell.lower() for cell in cells] == expected_header:
            header_ok = True
        if len(cells) >= 4 and cells[0].lower() in DEEP_V2_COMPARISON_TABLE_ASPECTS and all(cells[1:4]):
            complete.add(cells[0].lower())
    return header_ok and complete == DEEP_V2_COMPARISON_TABLE_ASPECTS


def has_repeated_long_explanation(body: str) -> bool:
    seen = set()
    for line in body.splitlines():
        if line.lstrip().startswith("|"):
            continue
        normalized = re.sub(r"\s+", " ", re.sub(r"^\s*-\s*(?:\[[^\]]+\]\s*)?", "", line)).strip().lower()
        if len(normalized) < 120:
            continue
        if normalized in seen:
            return True
        seen.add(normalized)
    return False


def has_verbose_mermaid_node_explanation(body: str) -> bool:
    diagram = diagram_text(body)
    if not is_mermaid_diagram(diagram):
        return False
    labels = re.findall(r"\[\"?([^\]]+)\"?\]", diagram)
    explanatory = re.compile(r"\b(?:main weakness|claimed benefit|weakness addressed|remaining weakness)\s*:", re.IGNORECASE)
    return any(explanatory.search(label) or len(label) > 100 or label.lower().count("<br/>") > 1 for label in labels)


def diagram_type_issues(body: str) -> list[str]:
    value = field_value(body, "Diagram type").strip().lower()
    if not value:
        return ["Diagram type content"]
    if value not in DIAGRAM_TYPES:
        return ["Diagram type selection"]
    return []


def has_unmarked_speculative_diagram_claim(body: str) -> bool:
    diagram = diagram_text(body)
    if not SPECULATIVE_DIAGRAM_RE.search(diagram):
        return False
    match = METHOD_DIAGRAM_RE.search(body)
    if not match:
        return False
    section_start = body.rfind("###", 0, match.start())
    section_end_match = re.search(r"^\s*###\s+", body[match.end() :], re.MULTILINE)
    section_end = match.end() + section_end_match.start() if section_end_match else len(body)
    context = body[max(0, section_start) : section_end]
    return not (has_nonempty_tag(context, "Interpretation") or has_nonempty_tag(context, "Needs verification"))


def has_unmarked_speculative_deep_section_claim(body: str) -> bool:
    heading = ANNOTATED_DIAGRAM_HEADING_RE.search(body)
    if not heading:
        return False
    section_end_match = re.search(r"^\s*###\s+", body[heading.end() :], re.MULTILINE)
    section_end = heading.end() + section_end_match.start() if section_end_match else len(body)
    context = body[heading.start() : section_end]
    return bool(SPECULATIVE_SECTION_RE.search(context)) and not (
        has_nonempty_tag(context, "Interpretation") or has_nonempty_tag(context, "Needs verification")
    )


def strict_skim_diagram_issues(body: str) -> list[str]:
    issues = diagram_type_issues(body)
    diagram = diagram_text(body)
    counts = {role: role_occurrences(diagram, role) for role in ("direct baseline", "representative prior", "this paper")}
    prior_ok = counts["representative prior"] == 1 or (counts["representative prior"] == 0 and has_no_representative_prior(diagram))
    if counts["direct baseline"] != 1 or not prior_ok or counts["this paper"] != 1:
        append_unique(issues, "Skim diagram canonical roles")
    blocks = diagram_blocks(diagram)
    if is_mermaid_diagram(diagram) and not MERMAID_SUBGRAPH_RE.search(diagram):
        append_unique(issues, "Skim Mermaid method blocks need review")
    if len(blocks) > 3:
        append_unique(issues, "Skim diagram compared methods <= 3")
    if any(block_node_count(content) > 5 for _label, content in blocks):
        append_unique(issues, "Skim diagram nodes per method <= 5")
    if is_mermaid_diagram(diagram) and diagram_global_node_count(diagram) > 15:
        append_unique(issues, "Skim Mermaid total nodes <= 15")
    if "key changed step" not in diagram:
        append_unique(issues, "Skim diagram KEY CHANGED STEP")
    if not has_complete_diagram_comparison_table(body):
        append_unique(issues, "diagram comparison table")
    if has_repeated_long_explanation(body):
        append_unique(issues, "Repeated long method explanation")
    if has_unmarked_speculative_diagram_claim(body):
        append_unique(issues, "Unsupported diagram claims need verification")
    return issues


def strict_deep_v2_diagram_issues(body: str) -> list[str]:
    issues = diagram_type_issues(body)
    diagram = diagram_text(body)
    baseline_count = role_occurrences(diagram, "direct baseline")
    prior_count = role_occurrences(diagram, "representative prior")
    paper_count = role_occurrences(diagram, "this paper")
    prior_ok = prior_count in {1, 2} or (prior_count == 0 and has_no_representative_prior(diagram))
    if baseline_count != 1 or not prior_ok or paper_count != 1:
        append_unique(issues, "Deep diagram baseline / prior / this paper")
    blocks = diagram_blocks(diagram)
    if is_mermaid_diagram(diagram) and not MERMAID_SUBGRAPH_RE.search(diagram):
        append_unique(issues, "Deep Mermaid method blocks need review")
    if len(blocks) > 4:
        append_unique(issues, "Deep diagram compared methods <= 4")
    if any(block_node_count(content) > 6 for _label, content in blocks):
        append_unique(issues, "Deep diagram nodes per method <= 6")
    if is_mermaid_diagram(diagram) and diagram_global_node_count(diagram) > 24:
        append_unique(issues, "Deep Mermaid total nodes <= 24")
    if "key changed step" not in diagram:
        append_unique(issues, "Deep diagram KEY CHANGED STEP")
    if has_no_representative_prior(diagram) and not has_no_representative_prior_reason(diagram):
        append_unique(issues, "Deep diagram no-prior reason")
    if not ANNOTATED_DIAGRAM_HEADING_RE.search(body):
        append_unique(issues, "Annotated Method Comparison Diagram heading")
    if not has_complete_deep_v2_comparison_table(body):
        append_unique(issues, "deep three-way diagram comparison table")
    if len(AUXILIARY_DIAGRAM_RE.findall(body)) > 1:
        append_unique(issues, "at most one auxiliary diagram")
    if has_verbose_mermaid_node_explanation(body):
        append_unique(issues, "Deep Mermaid nodes should stay computation-flow focused")
    if has_repeated_long_explanation(body):
        append_unique(issues, "Repeated long method explanation")
    if has_unmarked_speculative_deep_section_claim(body):
        append_unique(issues, "Unsupported diagram claims need verification")
    return issues


def meaningful_component_tokens(value: str) -> list[str]:
    generic = {"module", "component", "changed", "step", "method", "block", "ours", "baseline", "prior", "pipeline"}
    return [token for token in re.findall(r"[A-Za-z0-9_-]{3,}", value.lower()) if token not in generic]


def diagram_matches_changed_component(body: str) -> bool:
    tokens = meaningful_component_tokens(field_value(body, "Changed component"))
    diagram = diagram_text(body)
    return bool(tokens) and any(token in diagram for token in tokens)


def distinct_component_lists(body: str) -> bool:
    baseline = field_value(body, "Baseline components").strip().lower()
    ours = field_value(body, "Ours components").strip().lower()
    return bool(baseline and ours and baseline != ours)


def field_value(body: str, field: str) -> str:
    pattern = re.compile(
        rf"^[^\S\r\n]*-[^\S\r\n]*{re.escape(field)}[^\S\r\n]*:[^\S\r\n]*(.*)$",
        re.IGNORECASE | re.MULTILINE,
    )
    match = pattern.search(body)
    return match.group(1).strip() if match else ""


def require_enum(body: str, field: str, allowed: set[str], missing: list[str]) -> None:
    value = field_value(body, field).lower()
    if value and value not in allowed:
        missing.append(f"{field} enum")


def has_evidence_location(body: str, field: str) -> bool:
    return bool(re.search(r"\b(?:section|sec\.?|table|figure|fig\.?|appendix|page|equation|eq\.?)\s*[A-Za-z0-9.]+", field_value(body, field), re.IGNORECASE))


def has_complete_comparison_row(body: str) -> bool:
    for line in body.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) == 4 and cells[0].lower() not in {"variant", "prior / baseline", "ours", "---"} and all(cells):
            return True
        if len(cells) == 4 and cells[0].lower() in {"prior / baseline", "ours"} and all(cells[1:]):
            return True
    return False


def has_complete_claim_risk_row(body: str) -> bool:
    for line in body.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) == 4 and cells[1].lower() in {"proved", "supported", "suggested"} and all(cells):
            return True
    return False


def has_complete_claim_risk_use_row(body: str) -> bool:
    for line in body.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) == 5 and cells[1].lower() in {"proved", "supported", "suggested"} and all(cells):
            return True
    return False


def deep_v2_missing_fields(body: str, *, strict_diagrams: bool = False) -> list[str]:
    if detect_note_format(body) != "phase3-deep-v2":
        return []
    missing = [f"{field} content" for field in DEEP_V2_REQUIRED_FIELDS if not has_nonempty_field(body, field)]
    for tag in V3_REQUIRED_TAGS:
        if not has_nonempty_tag(body, tag):
            missing.append(f"[{tag}] content")
    if not has_method_comparison_diagram(body):
        missing.append("method comparison diagram")
    appendix = field_value(body, "Appendix checked").lower()
    require_enum(body, "Appendix checked", {"yes", "no", "not applicable"}, missing)
    if appendix == "no":
        missing.append("Appendix checked must be yes or justified not applicable")
    if appendix == "not applicable" and not has_nonempty_field(body, "Appendix not applicable reason"):
        missing.append("Appendix not applicable reason content")
    if field_value(body, "Diagram verification").lower() != "verified":
        missing.append("Diagram verification must be verified")
    if not has_evidence_location(body, "Diagram evidence location"):
        missing.append("Diagram evidence location")
    if not has_complete_deep_v2_comparison_table(body):
        missing.append("direct baseline / representative prior / this paper comparison content")
    if not re.search(r"^\s*###\s+4\.\s+Claim-Evidence-Risk-Use table\s*$", body, re.IGNORECASE | re.MULTILINE):
        missing.append("Claim-Evidence-Risk-Use table")
    elif not has_complete_claim_risk_use_row(body):
        missing.append("Claim-Evidence-Risk-Use content")
    if strict_diagrams:
        for issue in strict_deep_v2_diagram_issues(body):
            append_unique(missing, issue)
    return missing


def format_missing_fields(body: str, *, strict_diagrams: bool = False) -> list[str]:
    note_format = detect_note_format(body)
    if note_format == "phase3-deep-v2":
        return deep_v2_missing_fields(body, strict_diagrams=strict_diagrams)
    return ["current note type phase3-deep-v2"]
