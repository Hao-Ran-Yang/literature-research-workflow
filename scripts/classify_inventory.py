import argparse
import csv
import json
import re
from pathlib import Path

from workflow_safety import atomic_write_csv, require_write_permission


DEFAULT_RULES = {
    "method_categories": {
        "Survey and benchmark": ["survey", "review", "benchmark", "evaluation", "leaderboard", "dataset"],
        "Reasoning and planning": ["reasoning", "planning", "deliberation", "chain-of-thought", "latent thought"],
        "Test-time computation": ["test-time", "inference-time", "adaptive computation", "self-correction", "refinement"],
        "Training and optimization": ["training", "fine-tuning", "preference", "reinforcement learning", "optimization"],
        "Representation and latent space": ["latent", "representation", "embedding", "activation", "manifold"],
        "Agent and tool use": ["agent", "tool", "workflow", "multi-agent", "memory"],
        "Safety and alignment": ["safety", "alignment", "unlearning", "jailbreak", "hallucination", "steering"],
        "Multimodal and vision-language": ["vision-language", "multimodal", "visual", "image", "video"],
        "Robotics and embodied control": ["robot", "embodied", "action", "control", "manipulation", "navigation"],
    },
    "application_tags": {
        "General reasoning": ["reasoning", "math", "logic", "planning"],
        "Code and tool use": ["code", "program", "tool", "api"],
        "Vision-language": ["vision", "visual", "image", "video", "multimodal"],
        "Robotics": ["robot", "embodied", "control", "action", "navigation"],
        "Safety": ["safety", "alignment", "unlearning", "jailbreak", "hallucination"],
        "Evaluation": ["benchmark", "evaluation", "dataset", "metric"],
    },
    "priority": {
        "core": ["survey", "review", "benchmark", "foundation", "foundational", "overview", "dataset", "evaluation"],
        "high": ["state-of-the-art", "framework", "unified", "general", "theory", "analysis"],
        "low": ["application", "case study", "demo"],
    },
}

CORE_PRIORITY = "core"
HIGH_PRIORITY = "high"
MEDIUM_PRIORITY = "medium"
LOW_PRIORITY = "low"


def read_rows(path: Path) -> tuple[list[str], list[dict]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def write_rows(path: Path, fields: list[str], rows: list[dict]) -> None:
    atomic_write_csv(path, fields, rows)


def load_rules(path: str | None) -> dict:
    if not path:
        return DEFAULT_RULES
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    rules = json.loads(json.dumps(DEFAULT_RULES))
    for group in ("method_categories", "application_tags", "priority"):
        rules[group].update(data.get(group, {}))
    return rules


def haystack(row: dict) -> str:
    parts = [
        row.get("title", ""),
        row.get("section", ""),
        row.get("method_category", ""),
        row.get("application_tag", ""),
        row.get("notes", ""),
    ]
    return " ".join(parts).lower()


def score_label(text: str, mapping: dict[str, list[str]]) -> tuple[str, int, list[str]]:
    best_label = ""
    best_hits: list[str] = []
    for label, keywords in mapping.items():
        hits = [kw for kw in keywords if re.search(r"\b" + re.escape(kw.lower()) + r"\b", text)]
        if len(hits) > len(best_hits):
            best_label = label
            best_hits = hits
    return best_label, len(best_hits), best_hits


def choose_priority(text: str, rules: dict) -> tuple[str, list[str]]:
    priority_rules = rules.get("priority", {})
    for priority in (CORE_PRIORITY, HIGH_PRIORITY, LOW_PRIORITY):
        keywords = priority_rules.get(priority, [])
        hits = [kw for kw in keywords if re.search(r"\b" + re.escape(kw.lower()) + r"\b", text)]
        if hits:
            return priority, hits
    return MEDIUM_PRIORITY, []


def confidence(hit_count: int, existing_value: bool) -> str:
    if existing_value:
        return "manual_or_source"
    if hit_count >= 2:
        return "medium"
    if hit_count == 1:
        return "low"
    return "needs_review"


def append_note(row: dict, note: str) -> None:
    current = (row.get("notes") or "").strip()
    if note in current:
        return
    row["notes"] = f"{current}; {note}" if current else note


def classify_row(row: dict, rules: dict, overwrite_labels: bool) -> dict:
    text = haystack(row)
    source_bits = []

    method_existing = bool((row.get("method_category") or "").strip())
    method_label, method_hits, method_keywords = score_label(text, rules["method_categories"])
    if (overwrite_labels or not method_existing) and method_label:
        row["method_category"] = method_label
        source_bits.append(f"method:{','.join(method_keywords)}")

    app_existing = bool((row.get("application_tag") or "").strip())
    app_label, app_hits, app_keywords = score_label(text, rules["application_tags"])
    if (overwrite_labels or not app_existing) and app_label:
        row["application_tag"] = app_label
        source_bits.append(f"app:{','.join(app_keywords)}")

    priority, priority_hits = choose_priority(text, rules)
    if overwrite_labels or not (row.get("reading_priority") or "").strip():
        row["reading_priority"] = priority
    if priority_hits:
        source_bits.append(f"priority:{','.join(priority_hits)}")

    row["classification_confidence"] = confidence(max(method_hits, app_hits), method_existing or app_existing)
    row["classification_source"] = "rule:" + "|".join(source_bits) if source_bits else "rule:no_keyword_hit"
    if row["classification_confidence"] == "needs_review":
        append_note(row, "classification needs review")
    elif row["classification_confidence"] == "low":
        append_note(row, "low-confidence classification")
    return row


def main() -> None:
    parser = argparse.ArgumentParser(description="Add conservative first-pass labels and priorities to an inventory CSV.")
    parser.add_argument("--inventory", default="phase1_inventory.csv")
    parser.add_argument("--output", default="")
    parser.add_argument("--rules", help="Optional JSON rules file with method_categories/application_tags/priority mappings.")
    parser.add_argument("--overwrite", action="store_true", help="Allow replacing the input inventory.")
    parser.add_argument("--overwrite-labels", action="store_true", help="Overwrite existing category/tag/priority labels.")
    parser.add_argument("--allow-write", action="store_true")
    args = parser.parse_args()
    require_write_permission(args, "classified inventory output")

    inventory = Path(args.inventory)
    fields, rows = read_rows(inventory)
    for field in ["reading_priority", "classification_confidence", "classification_source"]:
        if field not in fields:
            fields.append(field)
    for field in ["method_category", "application_tag", "notes"]:
        if field not in fields:
            fields.append(field)

    rules = load_rules(args.rules)
    rows = [classify_row(row, rules, args.overwrite_labels) for row in rows]

    output = Path(args.output) if args.output else inventory
    if output == inventory and not args.overwrite:
        raise FileExistsError("Refusing to overwrite input inventory; pass --overwrite or --output")
    write_rows(output, fields, rows)

    counts = {
        "reading_priority": {},
        "classification_confidence": {},
    }
    for row in rows:
        for key in counts:
            value = row.get(key, "") or "<missing>"
            counts[key][value] = counts[key].get(value, 0) + 1
    print(json.dumps({"output": str(output), "rows": len(rows), "counts": counts}, ensure_ascii=False))


if __name__ == "__main__":
    main()
