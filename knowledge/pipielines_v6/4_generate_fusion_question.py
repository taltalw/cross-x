#!/usr/bin/env python3
"""Generate a four-option fusion question from plans and retrieved samples."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import random
import re
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from knowledge.pipelines._knowledge_search_common import APIError, JSONAPI, read_rows, write_row

from _pipeline_common import (
    compact_text,
    row_domains,
    sample_reference,
    validate_generation as shared_validate_generation,
    validate_plans,
    validate_required_key_facts,
    validate_v2_row,
)


DIFFICULTIES = ("easy", "medium", "hard")


SCREEN_PROMPT = """Find a natural cross-domain question that can be constructed
from the original sample and the retrieved samples in every fusion domain.
The existing question_plan and answer_plans are optional starting points,
not requirements that the retrieved samples must match.

Tasks:
1. Select the exact retrieved samples that can contribute necessary knowledge
   to one joint question with the source sample. Use every fusion domain.
2. If such a question is feasible, revise question_plan and all four
   answer_plans to fit the selected samples. Preserve the source sample's core
   knowledge and the chosen fusion_domains.
3. Rewrite required_key_facts to describe the knowledge actually used from
   each fusion domain: exactly three short keyword phrases and a brief
   necessity for each.

Requirements:
- Judge facts from the original prompt and completion of each sample. Do not
  invent facts or add an unrelated domain merely to force a combination.
- Do not reject a useful sample because it does not support the old plan;
  adjust the plan to what the retrieved material can naturally support.
- Set feasible to false only when the available samples cannot support one
  coherent joint task using every fusion domain. Then use null for all plan
  fields and empty selected_samples lists.
- List only exact supplied samples from their own domains. Keep each key_fact
  to a few English words, not a sentence; put explanations in necessity.
- Return only this English JSON object:
{
  "feasible": true,
  "reason": "Why the selected samples form one joint task, or why none do.",
  "selected_samples": {
    "fusion_domain": [{"prompt": "Original question", "completion": "Original answer"}]
  },
  "question_plan": "Brief revised joint question idea.",
  "answer_plans": [
    {"type": "correct", "missing_domain": null, "plan": "..."},
    {"type": "missing_domain_knowledge", "missing_domain": "participating domain", "plan": "..."},
    {"type": "parallel_knowledge", "missing_domain": null, "plan": "..."},
    {"type": "incorrect_domain_relation", "missing_domain": null, "plan": "..."}
  ],
  "required_key_facts": {
    "fusion_domain": [
      {"key_fact": "short phrase", "necessity": "Why needed."},
      {"key_fact": "short phrase", "necessity": "Why needed."},
      {"key_fact": "short phrase", "necessity": "Why needed."}
    ]
  }
}

Example:
- input
{
  "source_domain": "mathematics",
  "sample": {"prompt": "Calculate the area of a circle of radius r.", "completion": "pi * r**2"},
  "key_facts": ["circle area", "pi times radius squared"],
  "fusion_domains": ["computer_science"],
  "question_plan": "Reverse a string before calculating a circle's area.",
  "answer_plans": [
    {"type": "correct", "missing_domain": null, "plan": "Reverse the string and calculate the area."},
    {"type": "missing_domain_knowledge", "missing_domain": "mathematics", "plan": "Omit pi."},
    {"type": "parallel_knowledge", "missing_domain": null, "plan": "Keep the two computations separate."},
    {"type": "incorrect_domain_relation", "missing_domain": null, "plan": "Apply the string operation to the radius."}
  ],
  "retrieved_samples": {
    "computer_science": [
      {"prompt": "What do return, math.pi, and ** do in Python?", "completion": "return sends back a value; math.pi is pi; ** exponentiates."}
    ]
  }
}

- output
{
  "feasible": true,
  "reason": "The Python sample can express and return the circle-area calculation.",
  "selected_samples": {
    "computer_science": [
      {"prompt": "What do return, math.pi, and ** do in Python?", "completion": "return sends back a value; math.pi is pi; ** exponentiates."}
    ]
  },
  "question_plan": "Write a Python function that returns the area of a circle from its radius.",
  "answer_plans": [
    {"type": "correct", "missing_domain": null, "plan": "Return pi times radius squared."},
    {"type": "missing_domain_knowledge", "missing_domain": "mathematics", "plan": "Return radius squared without pi."},
    {"type": "parallel_knowledge", "missing_domain": null, "plan": "Compute the area but return the radius."},
    {"type": "incorrect_domain_relation", "missing_domain": null, "plan": "Square pi with the radius."}
  ],
  "required_key_facts": {
    "computer_science": [
      {"key_fact": "Python return statement", "necessity": "Return the computed value."},
      {"key_fact": "math.pi constant", "necessity": "Represent pi in code."},
      {"key_fact": "Python exponentiation", "necessity": "Square the radius."}
    ]
  }
}
"""


SYSTEM_PROMPT = r'''Construct one concise cross-domain multiple-choice question from the screened plan and selected evidence.

The input describes an already completed screening decision. It contains the original atomic sample and key facts, fusion_domains, the screened question_plan and answer_plans, required_key_facts, selected retrieved_samples, a compact_blueprint derived from the screened plan, the requested difficulty, and a length_budget. Do not redo screening or change the selected domains.

Tasks:
1. Write a self-contained question that keeps only the necessary situation,
   instance data, assumptions, boundary conditions, and one final question.
   Preserve the screened task's core and require the source knowledge plus every
   selected fusion domain to determine the result.
2. Produce four distinct options answering that same question in one consistent
   answer form. Make them concise final outcomes: a number, decision, short
   conclusion, expression, or local code result. Produce one correct outcome
   and one concrete wrong outcome for each retained error mechanism.
3. Put the complete solution in explanation. For each wrong option, write a
   private distractor_analysis reason connecting: erroneous step -> wrong result
   -> the corresponding option content. Cite actually used selected samples in
   used_samples and record any substantive presentation change in plan_adjustment.

Requirements:
- Screening is complete. Do not reject or replace a screened task because it is
  difficult to present. Do not add a planning call, domain, evidence source,
  independent subquestion, report, checklist, or full worked artifact.
- The visible question contains only necessary context, data, and boundaries plus
  one final question. Shared conditions or code appear once in the question.
  Intermediate reasoning, domain names as hints, construction labels, retrieval
  details, and explanations belong in private fields.
- Preserve all participating-domain dependencies and necessary conditions. Do
  not shorten by deleting a required concept, weakening a domain contribution,
  supplying the tested general rule/formula/bridge, or changing the screened
  target. Include units, precision, local API contracts and edge conditions when
  needed for a unique answer.
- All four options must use the same semantic answer form and be final outcomes,
  not explanations of why an answer is wrong. A short numeric option is valid;
  it must not carry a forced error explanation or error label.
- Keep these mechanisms in private metadata only:
  missing_domain_knowledge = omit or misuse necessary knowledge and produce a
  concrete wrong result;
  parallel_knowledge = a local result exists but is not used in the final
  judgment;
  incorrect_domain_relation = use a wrong mapping, direction, object, or
  combination and produce a concrete wrong result.
  In each reason state erroneous step -> wrong result -> option content. Do not
  make the visible option self-diagnose its mechanism. These labels are
  construction intent, not a unique diagnosis of model cognition.
- Use only exact selected prompt/completion samples in used_samples, at least
  one per fusion domain. Do not expose source evidence or metadata in the item.
- Respect length_budget word and character hard limits. The soft target is only
  guidance and options have no minimum length. Never truncate text or code,
  delete spaces, break indentation, omit conditions, or discard a domain.
- Difficulty changes application conditions, relations, or boundary cases within
  the same target; it must not mainly add background or independent outputs.
- Return only the JSON object below. Do not mention option letters in free prose;
  the program will decide the final option positions after validation.

Return only this English JSON object:
{
  "question": "Necessary context and one final question.",
  "options": {"A": "Final outcome", "B": "Final outcome", "C": "Final outcome", "D": "Final outcome"},
  "answer": "A",
  "explanation": "Complete private reasoning for the correct outcome.",
  "distractor_analysis": [
    {"option": "B", "type": "missing_domain_knowledge", "missing_domain": "participating domain", "reason": "Erroneous step -> wrong result -> option content."},
    {"option": "C", "type": "parallel_knowledge", "missing_domain": null, "reason": "Erroneous step -> wrong result -> option content."},
    {"option": "D", "type": "incorrect_domain_relation", "missing_domain": null, "reason": "Erroneous step -> wrong result -> option content."}
  ],
  "used_samples": {"fusion_domain": [{"prompt": "Exact selected prompt", "completion": "Exact selected completion"}]},
  "plan_adjustment": "Empty string unless the visible presentation changed substantively."
}

Example:
- input
{
  "source_domain": "mathematics",
  "sample": {"prompt": "Calculate the area of a circle of radius r.", "completion": "pi * r**2"},
  "key_facts": ["circle area", "pi times radius squared"],
  "fusion_domains": ["computer_science"],
  "question_plan": "Write a Python function that returns a circle's area from its radius.",
  "answer_plans": [
    {"type": "correct", "missing_domain": null, "plan": "Return pi times radius squared."},
    {"type": "missing_domain_knowledge", "missing_domain": "mathematics", "plan": "Return radius squared without pi."},
    {"type": "parallel_knowledge", "missing_domain": null, "plan": "Compute area but return radius."},
    {"type": "incorrect_domain_relation", "missing_domain": null, "plan": "Square pi together with radius."}
  ],
  "required_key_facts": {"computer_science": [
    {"key_fact": "Python return statement", "necessity": "Return the computed value."},
    {"key_fact": "math.pi constant", "necessity": "Represent pi in code."},
    {"key_fact": "Python exponentiation", "necessity": "Square the radius."}
  ]},
  "retrieved_samples": {"computer_science": [
    {"prompt": "What do return, math.pi and ** mean in Python?", "completion": "return sends a value back; math.pi is pi; ** exponentiates."}
  ]},
  "compact_blueprint": {"target": "The value returned by the area function", "answer_form": "code_or_expression", "dependency_summary": "Circle geometry determines the expression and Python semantics determine the returned value.", "domain_roles": {"mathematics": "area formula", "computer_science": "return and expression semantics"}},
  "length_budget": {"question_target_words": [30, 55], "question_max_words": 75, "option_max_words": 18, "total_visible_max_words": 130, "question_max_chars": 900, "option_max_chars": 216, "total_visible_max_chars": 1560},
  "option_count": 4,
  "difficulty": "easy"
}

- output
{
  "question": "With math imported and r > 0, which function body makes area(r) return the circle's area?",
  "options": {"A": "return math.pi * r**2", "B": "return r**2", "C": "math.pi * r**2\\nreturn r", "D": "return (math.pi * r)**2"},
  "answer": "A",
  "explanation": "The area is pi times radius squared, and the function must return that computed value.",
  "distractor_analysis": [
    {"option": "B", "type": "missing_domain_knowledge", "missing_domain": "mathematics", "reason": "Omitting pi yields radius squared, the concrete value shown by this option."},
    {"option": "C", "type": "parallel_knowledge", "missing_domain": null, "reason": "The area is evaluated but the returned value is radius, the concrete result shown by this option."},
    {"option": "D", "type": "incorrect_domain_relation", "missing_domain": null, "reason": "Applying the square to pi as well as radius yields pi squared times radius squared, shown by this option."}
  ],
  "used_samples": {"computer_science": [{"prompt": "What do return, math.pi and ** mean in Python?", "completion": "return sends a value back; math.pi is pi; ** exponentiates."}]},
  "plan_adjustment": ""
}
'''

AUDIT_PROMPT = r'''Audit the visible multiple-choice item produced after screening and generation. The proposed answer key, explanation, distractor labels, plans, blueprint, and construction metadata are deliberately withheld.

The input contains only the visible question/options, participating domains, the source sample, and the selected evidence references. Evidence is private provenance: use it to check domain facts, but do not supply instance-specific conditions that the visible question omitted.

Tasks:
1. Independently solve the visible item and list all correct option labels. Allow
   zero or multiple labels when the item is invalid, ambiguous, or underdetermined.
2. Check whether the item has one final target, is self-contained, is grounded in
   the supplied evidence, avoids giving away the tested knowledge or full bridge,
   uses one answer form across all options, and has no obvious surface shortcut.
3. For every participating domain, including the source domain, identify its
   necessary contribution and what becomes wrong or underdetermined without its
   knowledge. Mentioning a setting or vocabulary is not enough.
4. Report concrete unresolved issues. Do not infer a unique error mechanism from
   a short wrong answer; mechanism review requires private construction metadata.

Requirements:
- This is an answer-label-blind quality audit with reference evidence, not a
  closed-book capability test and not independent expert validation.
- Removing a domain name from the wording is different from removing its
  knowledge. Check actual dependence on each domain.
- Use pass, fail, or uncertain for every check. Use true, false, or null for
  necessary. Uncertain never passes the programmatic gate.
- `correct_options` may be empty or contain multiple distinct labels. Do not
  force a single answer. `issues` must be empty only if no concrete issue remains.
- Return only the following English JSON object.

{
  "correct_options": ["C"],
  "solution_summary": "Brief independent verification.",
  "checks": {
    "single_target": "pass",
    "self_contained": "pass",
    "evidence_grounded": "pass",
    "no_knowledge_giveaway": "pass",
    "same_answer_form": "pass",
    "no_surface_shortcut": "pass"
  },
  "domain_necessity": {"actual_domain": {"necessary": true, "reason": "Necessary inference and removal consequence."}},
  "issues": []
}

Example:
- input
{
  "question": "With math imported and r > 0, which function body makes area(r) return the circle's area?",
  "options": {"A": "return (math.pi * r)**2", "B": "math.pi * r**2\\nreturn r", "C": "return math.pi * r**2", "D": "return r**2"},
  "participating_domains": ["mathematics", "computer_science"],
  "source_sample": {"prompt": "Calculate the area of a circle of radius r.", "completion": "pi * r**2"},
  "selected_samples": {"computer_science": [{"prompt": "What do return, math.pi and ** mean in Python?", "completion": "return sends a value back; math.pi is pi; ** exponentiates."}]}
}

- output
{
  "correct_options": ["C"],
  "solution_summary": "Only the third body returns pi times the radius squared.",
  "checks": {"single_target": "pass", "self_contained": "pass", "evidence_grounded": "pass", "no_knowledge_giveaway": "pass", "same_answer_form": "pass", "no_surface_shortcut": "pass"},
  "domain_necessity": {"mathematics": {"necessary": true, "reason": "The area relation determines pi times radius squared."}, "computer_science": {"necessary": true, "reason": "Return and exponentiation semantics determine the function result."}},
  "issues": []
}
'''

REPAIR_PROMPT = r'''Repair one rejected generated candidate after screening. Return a complete new candidate in the generation JSON schema.

Tasks:
1. Read the original candidate, concrete rejection issues, the screened plan,
   compact_blueprint, selected evidence, and length_budget.
2. Fix every reported structure, visible-length, code-format, self-containedness,
   target, domain-necessity, or semantic issue while preserving the same screened
   target, source knowledge, all domains, evidence and necessary conditions.
3. Return one fresh unshuffled candidate. Do not audit, change the answer merely
   to match a judge label, or request another rewrite.

Requirements:
- Keep visible content to necessary context, data, boundaries, and one final
  question. Keep explanations and error mechanisms in private fields.
- A short numeric/result option is valid and must not contain a forced mechanism
  explanation. Write mechanism details only in distractor_analysis.reason as
  erroneous step -> wrong result -> option content.
- Do not truncate code, remove spaces, omit conditions, drop a domain, replace
  the screened target, invent evidence, or turn the item into a report.
- Use exact selected prompt/completion samples in used_samples. Recheck all four
  options, three mechanisms, answer coverage, length_budget, and code formatting.
- Return only the complete generation JSON object shown in the original
  generation prompt. The program will validate and permute it again.
'''


def validate_screening(value: Any, source: str, fusion_domains: list[str],
                       available_samples: dict[str, set[tuple[str, str]]]) -> dict:
    if not isinstance(value, dict) or type(value.get("feasible")) is not bool:
        raise ValueError("screening result must contain a boolean feasible")
    reason = compact_text(value.get("reason"), "screening reason")
    selected = value.get("selected_samples")
    if not isinstance(selected, dict) or set(selected) != set(fusion_domains):
        raise ValueError("selected_samples must cover exactly the fusion domains")
    normalized = {}
    for domain, samples in selected.items():
        if not isinstance(samples, list):
            raise ValueError(f"selected_samples.{domain} must be a list")
        normalized[domain] = []
        seen = set()
        for sample in samples:
            reference = sample_reference(sample)
            if reference not in available_samples[domain]:
                raise ValueError(f"selected_samples.{domain} must cite supplied samples")
            if reference not in seen:
                normalized[domain].append({"prompt": reference[0], "completion": reference[1]})
                seen.add(reference)
        if value["feasible"] and not normalized[domain]:
            raise ValueError("feasible screening requires samples from every fusion domain")
    if not value["feasible"]:
        if any(normalized.values()) or any(value.get(field) is not None for field in
                                        ("question_plan", "answer_plans", "required_key_facts")):
            raise ValueError("infeasible screening must not return samples or plans")
        return {"feasible": False, "reason": reason, "selected_samples": normalized}
    plans = validate_plans(value, [source, *fusion_domains])
    required = validate_required_key_facts(value.get("required_key_facts"), fusion_domains)
    return {"feasible": True, "reason": reason, "selected_samples": normalized,
            **plans, "required_key_facts": required}


# Generation-only helpers. Screening above remains the original implementation.
VERSION = "v6-concise-1"
LABELS = "ABCD"
ERROR_TYPES = {"missing_domain_knowledge", "parallel_knowledge", "incorrect_domain_relation"}
AUDIT_CHECKS = ("single_target", "self_contained", "evidence_grounded",
                "no_knowledge_giveaway", "same_answer_form", "no_surface_shortcut")

def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def default_length_budget(domain_count):
    if type(domain_count) is not int or not 2 <= domain_count <= 7:
        raise ValueError("domain-count must be between 2 and 7")
    extra = domain_count - 2
    result = {
        "question_target_words": [30 + 10 * extra, 55 + 15 * extra],
        "question_max_words": 75 + 20 * extra,
        "option_max_words": 18 + 2 * extra,
        "total_visible_max_words": 130 + 30 * extra,
    }
    result.update({
        "question_max_chars": result["question_max_words"] * 12,
        "option_max_chars": result["option_max_words"] * 12,
        "total_visible_max_chars": result["total_visible_max_words"] * 12,
        "budget_status": "engineering_default" if domain_count <= 4 else "uncalibrated_extension",
    })
    return result


def validate_length_budget(value):
    required = set(default_length_budget(2)) - {"budget_status"}
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError("length budget must contain every required field")
    target = value["question_target_words"]
    if (not isinstance(target, list) or len(target) != 2 or
            any(type(n) is not int or n < 0 for n in target)):
        raise ValueError("question_target_words must contain two nonnegative integers")
    for key in required - {"question_target_words"}:
        if type(value[key]) is not int or value[key] < 0:
            raise ValueError(f"{key} must be a nonnegative integer")
    if not target[0] <= target[1] <= value["question_max_words"] <= value["total_visible_max_words"]:
        raise ValueError("invalid question and total word budget")
    if value["option_max_words"] > value["total_visible_max_words"]:
        raise ValueError("option budget exceeds total word budget")
    if any(value[f"{field}_max_chars"] < value[f"{field}_max_words"]
           for field in ("question", "option", "total_visible")):
        raise ValueError("character budget must be at least the word budget")
    if max(value["question_max_chars"], value["option_max_chars"]) > value["total_visible_max_chars"]:
        raise ValueError("total character budget must cover individual fields")
    return copy.deepcopy(value)


def load_length_budget(path, domain_count):
    default = default_length_budget(domain_count)
    if path is None:
        return default
    with Path(path).open(encoding="utf-8") as stream:
        value = json.load(stream)
    if isinstance(value, dict) and "budgets" in value:
        budgets = value.get("budgets")
        if not isinstance(budgets, dict):
            raise ValueError("budget file budgets must be an object")
        value = budgets.get(str(domain_count), budgets.get(domain_count))
    if not isinstance(value, dict):
        raise ValueError(f"budget file has no complete budget for domain count {domain_count}")
    result = validate_length_budget(value)
    result["budget_status"] = "custom"
    return result


def validate_budget_file(path):
    """Validate every configured budget before the first screening request."""
    if path is None:
        return
    with Path(path).open(encoding="utf-8") as stream:
        value = json.load(stream)
    budgets = value.get("budgets", value) if isinstance(value, dict) else None
    if not isinstance(budgets, dict):
        raise ValueError("budget file must be an object or contain a budgets object")
    for key, budget in budgets.items():
        try:
            count = int(key)
        except (TypeError, ValueError):
            raise ValueError("budget keys must be domain counts 2 through 7") from None
        if str(count) != str(key) or not 2 <= count <= 7:
            raise ValueError("budget keys must be domain counts 2 through 7")
        validate_length_budget(budget)


def _word_char_stats(row):
    question, options = row["question"], row["options"]
    option_words = {label: len(options[label].split()) for label in LABELS}
    option_chars = {label: len(options[label]) for label in LABELS}
    return {
        "question_words": len(question.split()), "option_words": option_words,
        "options_words": sum(option_words.values()),
        "total_visible_words": len(question.split()) + sum(option_words.values()),
        "question_chars": len(question), "option_chars": option_chars,
        "options_chars": sum(option_chars.values()),
        "total_visible_chars": len(question) + sum(option_chars.values()),
    }


def hard_generation_issues(row, budget):
    stats = _word_char_stats(row)
    issues = []
    for unit in ("words", "chars"):
        checks = [("question", stats[f"question_{unit}"], budget[f"question_max_{unit}"]),
                  ("total_visible", stats[f"total_visible_{unit}"], budget[f"total_visible_max_{unit}"])]
        checks.extend((f"options.{label}", stats[f"option_{unit}"][label], budget[f"option_max_{unit}"])
                      for label in LABELS)
        issues.extend({"check": "length", "field": field, "unit": unit,
                       "actual": actual, "limit": limit}
                      for field, actual, limit in checks if actual > limit)
    prose = [("explanation", row["explanation"]), ("plan_adjustment", row["plan_adjustment"])]
    prose.extend((f"distractor_analysis.{i}.reason", entry["reason"])
                 for i, entry in enumerate(row["distractor_analysis"]))
    option_ref = re.compile(r"(?i)\b(?:option|choice|answer)s?\s*[\(\[]?\s*[A-D]\b|\b[A-D]\s*[).:]\s")
    for field, text in prose:
        if option_ref.search(text):
            issues.append({"check": "unsafe_option_reference", "field": field})
    return issues


def validate_generation(value, participating, available_samples):
    if not isinstance(value, dict):
        raise ValueError("generation result must be an object")
    options = value.get("options")
    if not isinstance(options, dict) or set(options) != set(LABELS):
        raise ValueError("options must contain exactly A, B, C, and D")
    visible_options = {}
    for label in LABELS:
        text = options[label]
        visible_options[label] = text.strip() if isinstance(text, str) else compact_text(text, f"option {label}")
        if not visible_options[label]:
            raise ValueError(f"option {label} must be nonempty")
    if len({text.casefold() for text in visible_options.values()}) != 4:
        raise ValueError("options must be distinct")
    # Shared validation checks the original schema and citations. Placeholder
    # options prevent its whitespace compaction from changing valid code layout.
    checked = dict(value, options={label: f"distinct_option_{label}" for label in LABELS})
    try:
        result = shared_validate_generation(checked, participating, available_samples)
    except (TypeError, KeyError, IndexError) as exc:
        raise ValueError(f"invalid generation schema: {exc}") from None
    result["question"] = value.get("question", "").strip()
    if not result["question"]:
        raise ValueError("question must be nonempty")
    result["options"] = visible_options
    entries = result["distractor_analysis"]
    if ({entry["option"] for entry in entries} != set(LABELS) - {result["answer"]} or
            len({entry["option"] for entry in entries}) != 3):
        raise ValueError("each wrong option must be annotated exactly once")
    return result


def build_compact_blueprint(source, domains, screen):
    roles = {source: {"knowledge": "Source sample core knowledge", "role": "Constrains the final result",
                      "removal_effect": "The result loses a necessary source constraint"}}
    roles.update({domain: {"knowledge": "Selected evidence-supported knowledge", "role": "Constrains the final result",
                           "removal_effect": "The result becomes wrong or underdetermined"}
                  for domain in domains})
    return {"target": screen["question_plan"], "answer_form": "one_consistent_final_result_form",
            "dependency_summary": "The source and every screened fusion domain jointly determine one final result.",
            "domain_roles": roles}


def plan_key(row):
    if row.get("plan_id") is not None:
        if not isinstance(row["plan_id"], str) or not row["plan_id"].strip():
            raise ValueError("plan_id must be a nonempty string")
        return row["plan_id"]
    return _digest({"sample": row["sample"], "source_domain": row["source_domain"],
                    "fusion_domains": sorted(row["fusion_domains"]),
                    "question_plan": row["question_plan"], "answer_plans": row["answer_plans"]})


def stable_item_id(key, difficulty):
    return _digest([VERSION, key, difficulty])


def shuffle_options(row, seed, identity):
    result = copy.deepcopy(row)
    order = list(LABELS)
    random.Random(int(_digest([seed, identity]), 16)).shuffle(order)
    mapping = dict(zip(LABELS, order))
    result["options"] = {mapping[label]: row["options"][label] for label in LABELS}
    result["answer"] = mapping[row["answer"]]
    for entry in result["distractor_analysis"]:
        entry["option"] = mapping[entry["option"]]
    return result, mapping


def validate_audit(value, domains):
    if not isinstance(value, dict):
        raise ValueError("audit result must be an object")
    labels = value.get("correct_options")
    if (not isinstance(labels, list) or any(not isinstance(label, str) or label not in LABELS for label in labels)
            or len(set(labels)) != len(labels)):
        raise ValueError("correct_options must be a distinct list of A-D labels")
    checks = value.get("checks")
    if (not isinstance(checks, dict) or set(checks) != set(AUDIT_CHECKS)
            or any(status not in ("pass", "fail", "uncertain") for status in checks.values())):
        raise ValueError("audit checks are invalid")
    necessity = value.get("domain_necessity")
    if not isinstance(necessity, dict) or set(necessity) != set(domains):
        raise ValueError("audit domain_necessity must cover every participating domain")
    for domain, entry in necessity.items():
        if (not isinstance(entry, dict) or set(entry) != {"necessary", "reason"}
                or type(entry["necessary"]) not in (bool, type(None))):
            raise ValueError(f"invalid necessity audit for {domain}")
        compact_text(entry["reason"], f"{domain} necessity reason")
    if not isinstance(value.get("issues"), list) or any(not isinstance(item, str) or not item.strip() for item in value["issues"]):
        raise ValueError("audit issues must be nonempty strings")
    compact_text(value.get("solution_summary"), "audit solution_summary")
    return copy.deepcopy(value)


def audit_issues(audit, answer):
    issues = []
    if audit["correct_options"] != [answer]:
        issues.append({"check": "answer_conflict", "proposed": answer, "audited": audit["correct_options"]})
    issues.extend({"check": key, "status": status} for key, status in audit["checks"].items() if status != "pass")
    issues.extend({"check": "domain_necessity", "domain": domain, **entry}
                  for domain, entry in audit["domain_necessity"].items() if entry["necessary"] is not True)
    issues.extend({"check": "semantic_issue", "reason": issue} for issue in audit["issues"])
    return issues


def blind_audit_payload(row, source, sample, domains, selected):
    return {"question": row["question"], "options": row["options"],
            "participating_domains": [source, *domains], "source_sample": sample,
            "selected_samples": selected}


def preflight_paths(input_file, output_file, audit_file, overwrite):
    paths = [Path(path) for path in (input_file, output_file, audit_file)]
    for index, first in enumerate(paths):
        for second in paths[index + 1:]:
            if first.resolve() == second.resolve():
                raise ValueError("input, output and audit paths must be different files")
            if first.exists() and second.exists() and os.path.samefile(first, second):
                raise ValueError("input, output and audit paths must refer to different files")
    if not paths[0].is_file():
        raise FileNotFoundError(paths[0])
    for path in paths[1:]:
        if path.exists() and not overwrite:
            raise FileExistsError(f"output exists: {path}; use --overwrite")
    return paths


def process(input_file: Path, output_file: Path, *, api: JSONAPI, domain_count: int | None,
            num: int | None, max_tokens: int, max_input_chars: int, overwrite: bool,
            max_repairs: int = 1, seed: int = 42, judge_api=None,
            skip_semantic_audit: bool = False, length_budget_file: Path | None = None,
            audit_output: Path | None = None) -> dict[str, Any]:
    if (num is not None and num < 1) or max_tokens < 1 or max_input_chars < 1:
        raise ValueError("num, max-tokens, and max-input-chars must be positive")
    if type(max_repairs) is not int or max_repairs not in (0, 1):
        raise ValueError("max-repairs must be 0 or 1")
    if type(seed) is not int:
        raise ValueError("seed must be an integer")
    if domain_count is not None and not 2 <= domain_count <= 7:
        raise ValueError("domain-count must be between 2 and 7")
    judge_api = judge_api or api
    # The repository's legacy FakeAPI adapters predate the semantic-audit
    # interface and have no retry configuration. Real JSONAPI clients (and
    # new mocks that expose retries) always run the audit unless explicitly
    # skipped for format debugging.
    audit_capable = isinstance(judge_api, JSONAPI) or hasattr(judge_api, "retries")
    audit_file = audit_output or output_file.with_suffix(".audit.jsonl")
    input_file, output_file, audit_file = preflight_paths(input_file, output_file, audit_file, overwrite)
    validate_budget_file(length_budget_file)
    report = {"processed": 0, "skipped": 0, "feasible_plans": 0, "initial_candidates": 0,
              "repair_candidates": 0, "generated": 0, "accepted": 0, "debug_accepted": 0,
              "final_rejected": 0, "screening_infeasible": 0, "logical_api_calls": 0}
    budget_cache = {}
    if skip_semantic_audit:
        print("WARNING: semantic audit disabled; output is format-debug only", file=sys.stderr)

    def call(client, prompt, payload, validator):
        if len(json.dumps(payload, ensure_ascii=False, allow_nan=False)) > max_input_chars:
            raise ValueError("API input exceeds --max-input-chars; no text or code was truncated")
        report["logical_api_calls"] += 1
        return client.chat(prompt, payload, validator, max_tokens)

    output_file.parent.mkdir(parents=True, exist_ok=True)
    audit_file.parent.mkdir(parents=True, exist_ok=True)
    with output_file.open("w" if overwrite else "x", encoding="utf-8") as output, \
            audit_file.open("w" if overwrite else "x", encoding="utf-8") as audit:
        for line, row in read_rows(input_file):
            if num is not None and report["processed"] >= num:
                break
            try:
                validate_v2_row(row)
                source = row["source_domain"]
                fusion_domains = row_domains(row, domain_count)
                participating = [source, *fusion_domains]
                plans = validate_plans({"question_plan": row.get("question_plan"),
                                        "answer_plans": row.get("answer_plans")}, participating)
                validate_required_key_facts(row.get("required_key_facts"), fusion_domains)
                candidates = row.get("retrieved_samples")
                if not isinstance(candidates, dict) or set(candidates) != set(fusion_domains):
                    raise ValueError("retrieved_samples must cover exactly the fusion domains")
                retrieved = {}
                empty = []
                for domain in fusion_domains:
                    if not isinstance(candidates[domain], list):
                        raise ValueError(f"retrieved_samples.{domain} must be a list")
                    if not candidates[domain]:
                        empty.append(domain)
                    retrieved[domain] = []
                    seen = set()
                    for candidate in candidates[domain]:
                        if not isinstance(candidate, dict):
                            raise ValueError("retrieved candidate is invalid")
                        sample = candidate.get("sample", candidate)
                        if not isinstance(sample, dict):
                            raise ValueError("retrieved sample is invalid")
                        sample = {field: sample.get(field) for field in ("prompt", "completion")}
                        reference = sample_reference(sample)
                        if reference not in seen:
                            retrieved[domain].append(sample)
                            seen.add(reference)
                report["processed"] += 1
                if empty:
                    report["skipped"] += 1
                    write_row(audit, {"event": "screening", "status": "rejected", "upstream_line": line,
                                      "reason": "no retrieved samples", "domains": empty})
                    continue

                # Keep this payload exactly as the pre-existing screening call.
                screen_payload = {"source_domain": source, "sample": row["sample"],
                                  "key_facts": row["key_facts"], "fusion_domains": fusion_domains,
                                  "question_plan": plans["question_plan"],
                                  "answer_plans": plans["answer_plans"],
                                  "retrieved_samples": retrieved}
                available = {domain: {sample_reference(sample) for sample in retrieved[domain]}
                             for domain in fusion_domains}
                screen = call(api, SCREEN_PROMPT, screen_payload,
                              lambda value: validate_screening(value, source, fusion_domains, available))
                screen_snapshot = copy.deepcopy(screen)
                write_row(audit, {"event": "screening", "status": "passed" if screen["feasible"] else "rejected",
                                  "upstream_line": line, "screening": screen_snapshot})
                if not screen["feasible"]:
                    report["skipped"] += 1
                    report["screening_infeasible"] += 1
                    print(f"line={line} skipped: {screen['reason']}", file=sys.stderr, flush=True)
                    continue
                report["feasible_plans"] += 1
                selected = screen["selected_samples"]
                selected_keys = {domain: {sample_reference(sample) for sample in selected[domain]}
                                 for domain in fusion_domains}
                blueprint = build_compact_blueprint(source, fusion_domains, screen)
                original_plan = {field: copy.deepcopy(row[field]) for field in
                                 ("question_plan", "answer_plans", "required_key_facts")}
                key = plan_key(row)
                scope_change = "none" if all(screen[field] == original_plan[field]
                                             for field in original_plan) else "presentation_only"
                previous_items = []
                for difficulty in DIFFICULTIES:
                    identity = stable_item_id(key, difficulty)
                    budget = budget_cache.setdefault(row["domain_count"],
                                                     load_length_budget(length_budget_file, row["domain_count"]))
                    generation_payload = {**screen_payload,
                                         "question_plan": screen["question_plan"],
                                         "answer_plans": screen["answer_plans"],
                                         "required_key_facts": screen["required_key_facts"],
                                         "retrieved_samples": selected,
                                         "compact_blueprint": blueprint,
                                         "length_budget": budget,
                                         "option_count": 4, "difficulty": difficulty}
                    repair_payload = None
                    for attempt in range(max_repairs + 1):
                        report["initial_candidates" if attempt == 0 else "repair_candidates"] += 1
                        raw = call(api, SYSTEM_PROMPT if attempt == 0 else REPAIR_PROMPT,
                                   generation_payload if attempt == 0 else repair_payload, lambda value: value)
                        generated = None
                        issues = []
                        stats = None
                        audit_result = None
                        permutation = None
                        try:
                            generated = validate_generation(raw, participating, selected_keys)
                            stats = _word_char_stats(generated)
                            issues = hard_generation_issues(generated, budget)
                            if not issues:
                                generated, permutation = shuffle_options(generated, seed, identity)
                                if not skip_semantic_audit and audit_capable:
                                    audit_result = call(
                                        judge_api, AUDIT_PROMPT,
                                        blind_audit_payload(generated, source, row["sample"], fusion_domains, selected),
                                        lambda value: validate_audit(value, participating))
                                    issues.extend(audit_issues(audit_result, generated["answer"]))
                        except ValueError as exc:
                            issues = [{"check": "structure", "reason": str(exc)}]
                        accepted = not issues
                        status = "accepted" if accepted else ("repairing" if attempt < max_repairs else "rejected")
                        signature = (_digest([generated["question"], sorted(generated["options"].values())])
                                     if generated else None)
                        duplicate_difficulties = [old for old, old_signature in previous_items
                                                  if signature and old_signature == signature]
                        write_row(audit, {"event": "candidate", "status": status, "upstream_line": line,
                                          "item_id": identity, "difficulty": difficulty, "attempt": attempt,
                                          "issues": issues, "length_budget": budget, "length_stats": stats,
                                          "semantic_audit_status": "passed" if audit_result is not None and not issues else
                                          ("failed" if audit_result is not None else "not_run"),
                                          "semantic_audit": audit_result, "option_permutation": permutation,
                                          "candidate": generated, "original_candidate": raw,
                                          "screening_snapshot": screen_snapshot,
                                          "duplicate_difficulties": duplicate_difficulties})
                        if accepted:
                            construction = {
                                "version": VERSION, "plan_key": key, "upstream_line": line,
                                "compact_blueprint": blueprint, "original_plan": original_plan,
                                "selected_samples": selected, "retrieved_candidates": candidates,
                                "visible_fields": ["question", "options"], "length_budget": budget,
                                "length_stats": stats, "scope_change": scope_change,
                                "difficulty_status": "uncalibrated", "error_label_status": "construction_intent",
                                "semantic_audit_status": "not_run" if (skip_semantic_audit or not audit_capable) else "passed",
                                "semantic_audit": audit_result, "repair_count": attempt,
                                "option_permutation": permutation, "seed": seed,
                                "generation_model": api.model, "judge_model": judge_api.model,
                                "duplicate_difficulties": duplicate_difficulties,
                            }
                            write_row(output, {"source_file": row.get("source_file", str(input_file.resolve())),
                                               "source_domain": source, "model": api.model,
                                               "sample": row["sample"], "key_facts": row["key_facts"],
                                               "fusion_domains": fusion_domains, "domain_count": row["domain_count"],
                                               "question_plan": screen["question_plan"],
                                               "answer_plans": screen["answer_plans"],
                                               "required_key_facts": screen["required_key_facts"],
                                               "retrieved_samples": retrieved,
                                               "retrieval": row.get("retrieval", {}), **generated,
                                               "difficulty": difficulty, "item_id": identity,
                                               "construction": construction})
                            report["generated"] += 1
                            report["debug_accepted" if (skip_semantic_audit or not audit_capable) else "accepted"] += 1
                            previous_items.append((difficulty, signature))
                            break
                        if attempt == max_repairs:
                            report["final_rejected"] += 1
                        else:
                            repair_payload = {**generation_payload, "original_candidate": raw,
                                              "feedback": {"issues": issues, "screening_snapshot": screen_snapshot,
                                                           "audited_candidate": generated,
                                                           "option_permutation": permutation,
                                                           "preserve": ["screened target", "source knowledge",
                                                                        "all fusion domains", "selected evidence",
                                                                        "necessary conditions", "one final question"]}}
                    print(f"line={line} difficulty={difficulty} status={status} generated={report['generated']}",
                          file=sys.stderr, flush=True)
            except APIError as exc:
                write_row(audit, {"event": "fatal_error", "status": "error", "upstream_line": line,
                                  "reason": str(exc), "screening_snapshot": locals().get("screen_snapshot")})
                raise APIError(f"{input_file}:{line}: {exc}; completed output retained") from None
            except ValueError as exc:
                write_row(audit, {"event": "fatal_error", "status": "error", "upstream_line": line,
                                  "reason": str(exc), "screening_snapshot": locals().get("screen_snapshot")})
                raise ValueError(f"{input_file}:{line}: {exc}; completed output retained") from None
    return {**report, "output": str(output_file.resolve()), "audit_output": str(audit_file.resolve())}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--domain-count", type=int, choices=range(2, 8), help="Optional check against input records; domains are read from each row")
    parser.add_argument("--num", type=int)
    parser.add_argument("--api-base-url", default=os.getenv("API_BASE_URL"))
    parser.add_argument("--api-key", default=os.getenv("API_KEY"))
    parser.add_argument("--model", default=os.getenv("MODEL"))
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--max-input-chars", type=int, default=160000)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--max-repairs", type=int, choices=(0, 1), default=1)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--judge-model")
    parser.add_argument("--skip-semantic-audit", action="store_true")
    parser.add_argument("--length-budget-file", type=Path)
    parser.add_argument("--audit-output", type=Path)
    args = parser.parse_args()
    try:
        api = JSONAPI(args.api_base_url, args.api_key, args.model, args.timeout, args.retries)
        judge_api = (JSONAPI(args.api_base_url, args.api_key, args.judge_model,
                             args.timeout, args.retries)
                     if args.judge_model else api)
        report = process(args.input, args.output, api=api, domain_count=args.domain_count,
                         num=args.num, max_tokens=args.max_tokens,
                         max_input_chars=args.max_input_chars, overwrite=args.overwrite,
                         max_repairs=args.max_repairs, seed=args.seed, judge_api=judge_api,
                         skip_semantic_audit=args.skip_semantic_audit,
                         length_budget_file=args.length_budget_file,
                         audit_output=args.audit_output)
    except (OSError, ValueError, APIError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
