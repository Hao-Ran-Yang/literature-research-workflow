import argparse
import json
import re
from collections import Counter
from pathlib import Path

from note_quality_rules import detect_note_format, format_missing_fields
from workflow_safety import atomic_write_text, require_write_permission


BATCH_HEADING_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)
ENTRY_RE = re.compile(r"^####\s+(.+)$", re.MULTILINE)
ARXIV_RE = re.compile(r"(?:arXiv[:\s]*)?(\d{4}\.\d{4,5}(?:v\d+)?)", re.IGNORECASE)
NUMBER_RE = re.compile(r"(?<![A-Za-z])\d+(?:\.\d+)?\s*(?:%|x|×|points?|pts?|tokens?|steps?|tasks?|datasets?|models?)?", re.IGNORECASE)
EVIDENCE_RE = re.compile(
    r"(Table\s*\d+|Figure\s*\d+|Fig\.?\s*\d+|Section\s*\d+(?:\.\d+)*|Sec\.?\s*\d+(?:\.\d+)*|"
    r"表\s*\d+|图\s*\d+|第\s*\d+(?:\.\d+)*\s*节)",
    re.IGNORECASE,
)
TAG_LINE_RE = re.compile(
    r"^\s*-\s*\[(Paper-stated|Interpretation|Evidence|Needs verification|Research idea|Inferred rationale)\]\s*:?\s*(.*)$",
    re.IGNORECASE,
)
LABELED_FIELD_RE = re.compile(
    r"^\s*-\s*(?:\[(?:Paper-stated|Interpretation|Evidence|Needs verification|Research idea|Inferred rationale)\]\s*)?(Problem statement|Essential question|Mathematical view|Frontier position|Applications and potential|"
    r"Existing approach|What it achieves|Limitation|Innovation over prior work|Remaining unresolved aspects|"
    r"Motivation|Why existing methods are not enough|Why this method is natural|Evidence pointer|Why this direction may work|Core intuition|Method preview|Problem formulation|Objective|"
    r"Optimization|Inference flow|Verification experiment|Main risk|Technical route|Problem|Why hard|"
    r"One-sentence method|Intuitive view|Prior or baseline|Essential change|Recurring weakness|Diagram type|Baseline components|Changed component|Ours components|Diagram verification|Diagram evidence location|Evidence strength|Main evidence|"
    r"Main uncertainty|Deep-read recommendation|Priority|Reason|Reading batch|Why selected|Appendix checked|Appendix not applicable reason|"
    r"Appendix sections checked|Research question|Core contribution in one sentence|Core idea|Why it matters|Main caution|Initial reading decision|Final reading decision|Reading decision|Prior choice rationale|"
    r"Optimization / curriculum|Inference procedure|Assumptions|Computation cost|Main evidence supporting the paper|Evidence that weakens or bounds the claim|Appendix findings that change the judgment|"
    r"Reproduction-critical dataset details|Reproduction-critical hyperparameters|Follow-up experiments|Main reproduction risk|What is solid|What is suggestive but not proven|"
    r"What is likely task-specific|What may fail when scaling|Best follow-up for my research|Main experiments|Ablations|Dataset details|"
    r"Hyperparameters|Scaling results|Efficiency results|Limitations|Code/data availability|Minimal reproduction path|"
    r"Missing implementation details|Candidate code changes|Follow-up experiment|Next action)\s*:\s*(.*)$",
    re.IGNORECASE,
)
SECTION_LINE_RE = re.compile(r"^\s*(?:\d+\.\s+|#{1,6}\s+)")
NUMBERED_SECTION_RE = re.compile(r"^\s*\d+\.\s+\*\*(.+?)\*\*\s*$")
PLACEHOLDER_LINE_RE = re.compile(
    r"^(?:Motivation|Verification experiment|Main risk|Confidence)\s*:.*$",
    re.IGNORECASE,
)

FIELD_PATTERNS = {
    "basic_info": [r"Basic information", r"基本信息"],
    "research_problem": [r"Research problem", r"研究问题", r"问题"],
    "core_idea": [r"Motivation and core idea", r"Core idea", r"核心思想", r"核心思路"],
    "method_details": [r"Method details", r"方法细节", r"方法"],
    "theoretical_claims": [r"Theoretical claims", r"理论"],
    "experiments": [r"Experiments", r"实验"],
    "strengths": [r"Strengths", r"优点", r"优势"],
    "limitations": [r"Weaknesses and assumptions", r"Limitations", r"局限", r"不足", r"假设"],
    "relation_to_interests": [r"Relation to my interests", r"关联", r"兴趣"],
    "possible_extensions": [r"Possible research extensions", r"Possible improvements", r"研究扩展", r"改进"],
    "takeaway": [r"One-sentence takeaway", r"一句话"],
}


def batch_code(value: str) -> str:
    match = re.search(r"\b(B\d{2})\b", value or "")
    return match.group(1) if match else ""


def section_spans(markdown: str) -> list[tuple[str, int, int]]:
    headings = list(BATCH_HEADING_RE.finditer(markdown))
    spans = []
    for idx, match in enumerate(headings):
        start = match.start()
        end = headings[idx + 1].start() if idx + 1 < len(headings) else len(markdown)
        spans.append((match.group(1).strip(), start, end))
    return spans


def split_entries(section: str) -> list[tuple[str, str]]:
    matches = list(ENTRY_RE.finditer(section))
    entries = []
    for idx, match in enumerate(matches):
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(section)
        entries.append((match.group(1).strip(), section[start:end].strip()))
    return entries


def strip_markdown(value: str) -> str:
    value = re.sub(r"\*\*([^*]+)\*\*", r"\1", value)
    value = re.sub(r"`([^`]+)`", r"\1", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip(" -:\n\t")


def extract_field(body: str, patterns: list[str]) -> str:
    fields = extract_fields(body)
    for key, key_patterns in FIELD_PATTERNS.items():
        if key_patterns == patterns:
            return fields.get(key, "")
    return ""


def heading_to_key(line: str) -> str:
    stripped = line.strip()
    looks_numbered = bool(re.match(r"^\d+\.\s+", stripped))
    looks_bold = "**" in stripped
    looks_short_heading = len(stripped) <= 24 and not re.search(r"[。.!?；;]", stripped)
    if not (looks_numbered or looks_bold or looks_short_heading):
        return ""
    cleaned = re.sub(r"^\s*(?:\d+\.\s*)?", "", stripped)
    cleaned = cleaned.strip("*:：# ")
    for key, patterns in FIELD_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, cleaned, re.IGNORECASE):
                return key
    return ""


def extract_fields(body: str) -> dict[str, str]:
    fields = {key: "" for key in FIELD_PATTERNS}
    current = ""
    chunks: dict[str, list[str]] = {key: [] for key in FIELD_PATTERNS}
    for line in body.splitlines():
        key = heading_to_key(line)
        if key:
            current = key
            remainder = re.sub(r"^\s*(?:\d+\.\s*)?", "", line).strip()
            remainder = re.sub(r"^\*\*.*?\*\*\s*[:：]?\s*", "", remainder)
            if remainder and remainder != line.strip():
                chunks[current].append(remainder)
            continue
        if current:
            chunks[current].append(line)
    for key, lines in chunks.items():
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        fields[key] = "\n".join(lines).strip()
    return fields


def unique_nonempty(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def clean_block(lines: list[str]) -> str:
    return "\n".join(line.rstrip() for line in lines).strip(" \n-")


def extract_numbered_sections(body: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current = ""
    for line in body.splitlines():
        match = NUMBERED_SECTION_RE.match(line)
        if match:
            current = match.group(1).strip().lower()
            sections.setdefault(current, [])
            continue
        if current:
            sections[current].append(line)
    return {key: "\n".join(lines).strip() for key, lines in sections.items()}


def research_idea_has_content(value: str) -> bool:
    meaningful = [
        line.strip()
        for line in value.splitlines()
        if line.strip() and not PLACEHOLDER_LINE_RE.match(line.strip(" -"))
    ]
    return bool(meaningful)


def extract_tagged_blocks(body: str) -> dict[str, list[str]]:
    tagged = {
        "paper_stated_facts": [],
        "interpretations": [],
        "inferred_rationales": [],
        "possible_research_ideas": [],
        "evidence_references": [],
        "needs_review": [],
    }
    tag_keys = {
        "paper-stated": "paper_stated_facts",
        "interpretation": "interpretations",
        "inferred rationale": "inferred_rationales",
        "research idea": "possible_research_ideas",
        "evidence": "evidence_references",
        "needs verification": "needs_review",
    }
    current_key = ""
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_key, current_lines
        value = clean_block(current_lines)
        if value and (current_key != "possible_research_ideas" or research_idea_has_content(value)):
            tagged[current_key].append(value)
        current_key = ""
        current_lines = []

    for line in body.splitlines():
        tag_match = TAG_LINE_RE.match(line)
        if tag_match:
            flush()
            current_key = tag_keys[tag_match.group(1).lower()]
            if tag_match.group(2).strip():
                current_lines.append(tag_match.group(2).strip())
            continue
        if current_key and (
            SECTION_LINE_RE.match(line)
            or LABELED_FIELD_RE.match(line)
            or re.match(r"^\s*-\s*\S.+?:\s*$", line)
        ):
            flush()
            continue
        if current_key:
            current_lines.append(line.strip())
    flush()
    return {key: unique_nonempty(values) for key, values in tagged.items()}


def extract_labeled_values(body: str) -> dict[str, list[str]]:
    values = {
        "problem_statement": [],
        "essential_question": [],
        "mathematical_view": [],
        "frontier_position": [],
        "applications_and_potential": [],
        "existing_approach": [],
        "what_it_achieves": [],
        "limitation": [],
        "innovation_over_prior_work": [],
        "remaining_unresolved_aspects": [],
        "motivation": [],
        "why_existing_methods_are_not_enough": [],
        "why_this_method_is_natural": [],
        "motivation_evidence_pointer": [],
        "why_this_direction_may_work": [],
        "core_intuition": [],
        "method_preview": [],
        "problem_formulation": [],
        "objective": [],
        "optimization": [],
        "inference_flow": [],
        "verification_experiments": [],
        "research_idea_risks": [],
        "technical_route": [],
        "problem": [],
        "why_hard": [],
        "one_sentence_method": [],
        "intuitive_view": [],
        "prior_or_baseline": [],
        "essential_change": [],
        "recurring_weakness": [],
        "diagram_type": [],
        "baseline_components": [],
        "changed_component": [],
        "ours_components": [],
        "diagram_verification": [],
        "diagram_evidence_location": [],
        "evidence_strength": [],
        "main_evidence": [],
        "main_uncertainty": [],
        "deep_read_recommendation": [],
        "priority": [],
        "reason": [],
        "why_selected": [],
        "appendix_checked": [],
        "appendix_not_applicable_reason": [],
        "appendix_sections_checked": [],
        "research_question": [],
        "core_idea_summary": [],
        "core_contribution": [],
        "why_it_matters": [],
        "main_caution": [],
        "reading_decision": [],
        "initial_reading_decision": [],
        "final_reading_decision": [],
        "prior_choice_rationale": [],
        "optimization_curriculum": [],
        "inference_procedure": [],
        "assumptions": [],
        "computation_cost": [],
        "main_supporting_evidence": [],
        "bounding_evidence": [],
        "judgment_changing_appendix_findings": [],
        "main_experiments": [],
        "ablations": [],
        "dataset_details": [],
        "hyperparameters": [],
        "scaling_results": [],
        "efficiency_results": [],
        "limitations_summary": [],
        "code_data_availability": [],
        "minimal_reproduction_path": [],
        "missing_implementation_details": [],
        "reproduction_dataset_details": [],
        "reproduction_hyperparameters": [],
        "candidate_code_changes": [],
        "follow_up_experiment": [],
        "follow_up_experiments": [],
        "main_reproduction_risk": [],
        "next_action": [],
        "what_is_solid": [],
        "what_is_suggestive": [],
        "what_is_task_specific": [],
        "what_may_fail_when_scaling": [],
        "best_follow_up": [],
    }
    field_keys = {
        "problem statement": "problem_statement",
        "essential question": "essential_question",
        "mathematical view": "mathematical_view",
        "frontier position": "frontier_position",
        "applications and potential": "applications_and_potential",
        "existing approach": "existing_approach",
        "what it achieves": "what_it_achieves",
        "limitation": "limitation",
        "innovation over prior work": "innovation_over_prior_work",
        "remaining unresolved aspects": "remaining_unresolved_aspects",
        "motivation": "motivation",
        "why existing methods are not enough": "why_existing_methods_are_not_enough",
        "why this method is natural": "why_this_method_is_natural",
        "evidence pointer": "motivation_evidence_pointer",
        "why this direction may work": "why_this_direction_may_work",
        "core intuition": "core_intuition",
        "method preview": "method_preview",
        "problem formulation": "problem_formulation",
        "objective": "objective",
        "optimization": "optimization",
        "inference flow": "inference_flow",
        "verification experiment": "verification_experiments",
        "main risk": "research_idea_risks",
        "technical route": "technical_route",
        "problem": "problem",
        "why hard": "why_hard",
        "one-sentence method": "one_sentence_method",
        "intuitive view": "intuitive_view",
        "prior or baseline": "prior_or_baseline",
        "essential change": "essential_change",
        "recurring weakness": "recurring_weakness",
        "diagram type": "diagram_type",
        "baseline components": "baseline_components",
        "changed component": "changed_component",
        "ours components": "ours_components",
        "diagram verification": "diagram_verification",
        "diagram evidence location": "diagram_evidence_location",
        "evidence strength": "evidence_strength",
        "main evidence": "main_evidence",
        "main uncertainty": "main_uncertainty",
        "deep-read recommendation": "deep_read_recommendation",
        "priority": "priority",
        "reason": "reason",
        "why selected": "why_selected",
        "appendix checked": "appendix_checked",
        "appendix not applicable reason": "appendix_not_applicable_reason",
        "appendix sections checked": "appendix_sections_checked",
        "research question": "research_question",
        "core idea": "core_idea_summary",
        "core contribution in one sentence": "core_contribution",
        "why it matters": "why_it_matters",
        "main caution": "main_caution",
        "reading decision": "reading_decision",
        "initial reading decision": "initial_reading_decision",
        "final reading decision": "final_reading_decision",
        "prior choice rationale": "prior_choice_rationale",
        "optimization / curriculum": "optimization_curriculum",
        "inference procedure": "inference_procedure",
        "assumptions": "assumptions",
        "computation cost": "computation_cost",
        "main evidence supporting the paper": "main_supporting_evidence",
        "evidence that weakens or bounds the claim": "bounding_evidence",
        "appendix findings that change the judgment": "judgment_changing_appendix_findings",
        "main experiments": "main_experiments",
        "ablations": "ablations",
        "dataset details": "dataset_details",
        "hyperparameters": "hyperparameters",
        "scaling results": "scaling_results",
        "efficiency results": "efficiency_results",
        "limitations": "limitations_summary",
        "code/data availability": "code_data_availability",
        "minimal reproduction path": "minimal_reproduction_path",
        "missing implementation details": "missing_implementation_details",
        "reproduction-critical dataset details": "reproduction_dataset_details",
        "reproduction-critical hyperparameters": "reproduction_hyperparameters",
        "candidate code changes": "candidate_code_changes",
        "follow-up experiment": "follow_up_experiment",
        "follow-up experiments": "follow_up_experiments",
        "main reproduction risk": "main_reproduction_risk",
        "next action": "next_action",
        "what is solid": "what_is_solid",
        "what is suggestive but not proven": "what_is_suggestive",
        "what is likely task-specific": "what_is_task_specific",
        "what may fail when scaling": "what_may_fail_when_scaling",
        "best follow-up for my research": "best_follow_up",
    }
    current_key = ""
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_key, current_lines
        value = clean_block(current_lines)
        if current_key and value:
            values[current_key].append(value)
        current_key = ""
        current_lines = []

    for line in body.splitlines():
        field_match = LABELED_FIELD_RE.match(line)
        if field_match:
            flush()
            current_key = field_keys[field_match.group(1).lower()]
            if field_match.group(2).strip():
                current_lines.append(field_match.group(2).strip())
            continue
        if current_key and (TAG_LINE_RE.match(line) or SECTION_LINE_RE.match(line) or re.match(r"^\s*-\s*\S.+?:", line)):
            flush()
            continue
        if current_key:
            current_lines.append(line.strip())
    flush()
    return {key: unique_nonempty(items) for key, items in values.items()}


def extract_prior_method_comparisons(body: str) -> list[dict[str, str]]:
    comparisons = []
    current: dict[str, str] = {}
    keys = {
        "existing approach": "existing_approach",
        "what it achieves": "what_it_achieves",
        "limitation": "limitation",
    }
    for line in body.splitlines():
        match = LABELED_FIELD_RE.match(line)
        if not match:
            continue
        label = match.group(1).lower()
        if label not in keys:
            continue
        if label == "existing approach" and current:
            comparisons.append(current)
            current = {}
        value = match.group(2).strip()
        if value:
            current[keys[label]] = value
    if current:
        comparisons.append(current)
    return comparisons


def joined(values: list[str]) -> str:
    return "\n".join(values)


def extract_claim_evidence_risks(body: str) -> list[dict[str, str]]:
    rows = []
    in_table = False
    for line in body.splitlines():
        if re.match(r"^\s*###\s+4\.\s+Claim-Evidence-Risk(?:-Use)? table\s*$", line, re.IGNORECASE):
            in_table = True
            continue
        if in_table and line.startswith("### "):
            break
        if not in_table or not line.strip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) not in {4, 5} or cells[0].lower() in {"claim", "---", ""} or all(set(cell) <= {"-", ":", " "} for cell in cells):
            continue
        row = {"claim": cells[0], "status": cells[1], "evidence_location": cells[2], "alternative_explanation_or_risk": cells[3]}
        if len(cells) == 5:
            row["my_verdict_or_use"] = cells[4]
        rows.append(row)
    return rows


def extract_deep_method_comparison(body: str) -> list[dict[str, str]]:
    rows = []
    in_section = False
    for line in body.splitlines():
        if re.match(r"^\s*###\s+2\.\s+Annotated Method Comparison Diagram\s*$", line, re.IGNORECASE):
            in_section = True
            continue
        if in_section and line.startswith("### "):
            break
        if not in_section or not line.strip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 4 or cells[0].lower() in {"aspect", "---", ""} or all(set(cell) <= {"-", ":", " "} for cell in cells):
            continue
        rows.append(
            {
                "aspect": cells[0],
                "direct_baseline": cells[1],
                "representative_prior": cells[2],
                "this_paper": cells[3],
            }
        )
    return rows


def parse_entry(batch_heading: str, title: str, body: str) -> dict:
    arxiv_match = ARXIV_RE.search(body)
    fields = extract_fields(body)
    evidence = sorted(set(EVIDENCE_RE.findall(body)))
    numbers = [strip_markdown(item.group(0)) for item in NUMBER_RE.finditer(body)]
    note_format = detect_note_format(body)
    general_missing = (
        []
        if note_format in {"phase2-skim-v1", "phase3-deep-v1", "phase3-deep-v2"}
        else [key for key in ("research_problem", "core_idea", "method_details", "experiments", "limitations", "takeaway") if not fields.get(key)]
    )
    quality_missing_fields = format_missing_fields(body)
    missing_fields = unique([*general_missing, *quality_missing_fields])
    tagged = extract_tagged_blocks(body)
    sections = extract_numbered_sections(body)
    labeled = extract_labeled_values(body)
    problem = extract_labeled_values(sections.get("research problem", ""))
    novelty = extract_labeled_values(sections.get("existing methods and novelty", ""))
    core = extract_labeled_values(sections.get("motivation and core idea", ""))
    method = extract_labeled_values(sections.get("method details", ""))
    extensions = extract_labeled_values(sections.get("possible research extensions", ""))
    evidence_references = unique_nonempty([*tagged["evidence_references"], *evidence])
    needs_review = bool(
        missing_fields
        or not arxiv_match
        or (note_format not in {"phase2-skim-v1", "phase3-deep-v1", "phase3-deep-v2"} and (not evidence_references or not numbers))
        or tagged["needs_review"]
    )
    return {
        "batch": batch_code(batch_heading),
        "batch_heading": batch_heading,
        "entry_title": strip_markdown(title),
        "arxiv_id": arxiv_match.group(1) if arxiv_match else "",
        "note_format": note_format,
        "fields": fields,
        "evidence_refs": evidence[:30],
        "paper_stated_facts": tagged["paper_stated_facts"],
        "interpretations": tagged["interpretations"],
        "inferred_rationales": tagged["inferred_rationales"],
        "possible_research_ideas": tagged["possible_research_ideas"],
        "evidence_references": evidence_references[:30],
        "needs_review": tagged["needs_review"],
        "problem_statement": joined(problem["problem_statement"] or labeled["problem_statement"] or labeled["problem"] or labeled["research_question"]),
        "essential_question": joined(problem["essential_question"] or labeled["essential_question"]),
        "mathematical_view": joined(problem["mathematical_view"] or labeled["mathematical_view"]),
        "frontier_position": joined(problem["frontier_position"] or labeled["frontier_position"]),
        "applications_and_potential": joined(problem["applications_and_potential"] or labeled["applications_and_potential"]),
        "prior_method_comparisons": extract_prior_method_comparisons(sections.get("existing methods and novelty", "")),
        "innovation_over_prior_work": joined(novelty["innovation_over_prior_work"] or labeled["innovation_over_prior_work"]),
        "remaining_unresolved_aspects": joined(novelty["remaining_unresolved_aspects"] or labeled["remaining_unresolved_aspects"]),
        "motivation": joined(core["motivation"] or labeled["motivation"]),
        "why_existing_methods_are_not_enough": joined(core["why_existing_methods_are_not_enough"] or labeled["why_existing_methods_are_not_enough"]),
        "why_this_method_is_natural": joined(core["why_this_method_is_natural"] or labeled["why_this_method_is_natural"]),
        "motivation_evidence_pointer": joined(core["motivation_evidence_pointer"] or labeled["motivation_evidence_pointer"]),
        "why_this_direction_may_work": joined(core["why_this_direction_may_work"] or labeled["why_this_direction_may_work"]),
        "core_intuition": joined(core["core_intuition"] or labeled["core_intuition"]),
        "method_preview": joined(core["method_preview"] or labeled["method_preview"] or labeled["one_sentence_method"] or labeled["core_contribution"]),
        "problem_formulation": joined(method["problem_formulation"] or labeled["problem_formulation"]),
        "objective": joined(method["objective"] or labeled["objective"]),
        "optimization": joined(method["optimization"] or labeled["optimization"] or labeled["optimization_curriculum"]),
        "inference_flow": joined(method["inference_flow"] or labeled["inference_flow"] or labeled["inference_procedure"]),
        "verification_experiments": extensions["verification_experiments"] or labeled["verification_experiments"],
        "research_idea_risks": extensions["research_idea_risks"] or labeled["research_idea_risks"],
        "technical_route": joined(labeled["technical_route"]),
        "problem": joined(labeled["problem"]),
        "why_hard": joined(labeled["why_hard"]),
        "one_sentence_method": joined(labeled["one_sentence_method"]),
        "intuitive_view": joined(labeled["intuitive_view"]),
        "prior_or_baseline": joined(labeled["prior_or_baseline"]),
        "essential_change": joined(labeled["essential_change"]),
        "recurring_weakness": joined(labeled["recurring_weakness"]),
        "diagram_type": joined(labeled["diagram_type"]),
        "baseline_components": labeled["baseline_components"],
        "changed_component": joined(labeled["changed_component"]),
        "ours_components": labeled["ours_components"],
        "diagram_verification": joined(labeled["diagram_verification"]),
        "diagram_evidence_location": joined(labeled["diagram_evidence_location"]),
        "evidence_strength": joined(labeled["evidence_strength"]),
        "main_evidence": joined(labeled["main_evidence"]),
        "main_uncertainty": joined(labeled["main_uncertainty"]),
        "deep_read_recommendation": joined(labeled["deep_read_recommendation"]),
        "priority": joined(labeled["priority"]),
        "recommendation_reason": joined(labeled["reason"]),
        "why_selected": joined(labeled["why_selected"]),
        "appendix_checked": joined(labeled["appendix_checked"]),
        "appendix_not_applicable_reason": joined(labeled["appendix_not_applicable_reason"]),
        "appendix_sections_checked": joined(labeled["appendix_sections_checked"]),
        "research_question": joined(labeled["research_question"]),
        "core_idea_summary": joined(labeled["core_idea_summary"] or labeled["core_contribution"]),
        "core_contribution": joined(labeled["core_contribution"]),
        "why_it_matters": joined(labeled["why_it_matters"]),
        "main_caution": joined(labeled["main_caution"]),
        "reading_decision": joined(labeled["reading_decision"] or labeled["final_reading_decision"] or labeled["initial_reading_decision"]),
        "initial_reading_decision": joined(labeled["initial_reading_decision"]),
        "final_reading_decision": joined(labeled["final_reading_decision"]),
        "prior_choice_rationale": joined(labeled["prior_choice_rationale"]),
        "optimization_curriculum": joined(labeled["optimization_curriculum"]),
        "inference_procedure": joined(labeled["inference_procedure"]),
        "assumptions": joined(labeled["assumptions"]),
        "computation_cost": joined(labeled["computation_cost"]),
        "main_supporting_evidence": joined(labeled["main_supporting_evidence"]),
        "bounding_evidence": joined(labeled["bounding_evidence"]),
        "judgment_changing_appendix_findings": joined(labeled["judgment_changing_appendix_findings"]),
        "main_experiments": joined(labeled["main_experiments"]),
        "ablations": joined(labeled["ablations"]),
        "dataset_details": joined(labeled["dataset_details"]),
        "hyperparameters": joined(labeled["hyperparameters"]),
        "scaling_results": joined(labeled["scaling_results"]),
        "efficiency_results": joined(labeled["efficiency_results"]),
        "limitations_summary": joined(labeled["limitations_summary"]),
        "code_data_availability": joined(labeled["code_data_availability"]),
        "minimal_reproduction_path": joined(labeled["minimal_reproduction_path"]),
        "missing_implementation_details": joined(labeled["missing_implementation_details"]),
        "reproduction_dataset_details": joined(labeled["reproduction_dataset_details"]),
        "reproduction_hyperparameters": joined(labeled["reproduction_hyperparameters"]),
        "candidate_code_changes": joined(labeled["candidate_code_changes"]),
        "follow_up_experiment": joined(labeled["follow_up_experiment"] or labeled["follow_up_experiments"]),
        "follow_up_experiments": joined(labeled["follow_up_experiments"]),
        "main_reproduction_risk": joined(labeled["main_reproduction_risk"]),
        "next_action": joined(labeled["next_action"]),
        "what_is_solid": joined(labeled["what_is_solid"]),
        "what_is_suggestive": joined(labeled["what_is_suggestive"]),
        "what_is_task_specific": joined(labeled["what_is_task_specific"]),
        "what_may_fail_when_scaling": joined(labeled["what_may_fail_when_scaling"]),
        "best_follow_up": joined(labeled["best_follow_up"]),
        "claim_evidence_risks": extract_claim_evidence_risks(body),
        "deep_method_comparison": extract_deep_method_comparison(body),
        "numeric_mentions": numbers[:50],
        "quality_missing_fields": quality_missing_fields,
        "missing_fields": missing_fields,
        "quality_flags": {
            "has_arxiv": bool(arxiv_match),
            "has_evidence_ref": bool(evidence),
            "has_numeric_result": bool(numbers),
            "needs_review": needs_review,
        },
    }


def parse_notes(path: Path) -> dict:
    markdown = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    papers = []
    for heading, start, end in section_spans(markdown):
        section = markdown[start:end]
        code = batch_code(heading)
        if not code:
            continue
        for title, body in split_entries(section):
            papers.append(parse_entry(heading, title, body))
    missing_counter = Counter()
    for paper in papers:
        missing_counter.update(paper["missing_fields"])
    return {
        "notes": str(path),
        "papers": papers,
        "summary": {
            "paper_entries": len(papers),
            "batches": dict(Counter(paper["batch"] for paper in papers)),
            "needs_review": sum(1 for paper in papers if paper["quality_flags"]["needs_review"]),
            "missing_fields": dict(missing_counter),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse structured Phase 2 reading notes into JSON.")
    parser.add_argument("--notes", default="phase2_reading_notes.md")
    parser.add_argument("--output", help="Optional JSON output path.")
    parser.add_argument("--allow-write", action="store_true")
    args = parser.parse_args()

    parsed = parse_notes(Path(args.notes))
    text = json.dumps(parsed, ensure_ascii=False, indent=2)
    if args.output:
        require_write_permission(args, "parsed notes JSON output")
        atomic_write_text(Path(args.output), text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
