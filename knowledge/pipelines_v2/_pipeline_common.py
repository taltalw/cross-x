"""Shared validation and argument helpers for pipelines_v2 stages 1-4."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from knowledge.pipelines._knowledge_search_common import DOMAINS, nonempty


DOMAIN_DESCRIPTIONS = {
    "medical": "Medicine: physiology, disease, diagnosis, treatment, pharmacology, and public health.",
    "legal": "Law: legal rules, rights, obligations, contracts, liability, procedure, and compliance.",
    "financial": "Finance: money, banking, investment, asset pricing, corporate finance, accounting, and risk.",
    "mathematics": "Mathematics: algebra, geometry, calculus, probability, statistics, optimization, and modeling.",
    "computer_science": "Computer science: algorithms, data structures, networks, operating systems, databases, and security.",
    "geography": "Geography: landforms, geology, climate, hydrology, spatial distributions, resources, and human-environment relations.",
    "chemistry": "Chemistry: matter, chemical reactions, mechanisms, analytical methods, and chemical safety.",
}


ANSWER_TYPES = (
    "correct",
    "missing_domain_knowledge",
    "parallel_knowledge",
    "incorrect_domain_relation",
)


def compact_text(value: Any, name: str) -> str:
    return " ".join(nonempty(value, name).split())


def sample_hash(sample: dict[str, Any]) -> str:
    value = [" ".join(sample[key].split()).casefold() for key in ("prompt", "completion")]
    return hashlib.sha256(json.dumps(value, ensure_ascii=False).encode()).hexdigest()


def validate_v2_row(row: Any) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise ValueError("row must be an object")
    source = row.get("source_domain")
    if not isinstance(source, str) or source not in DOMAINS:
        raise ValueError("source_domain must be one of the seven supported domains")
    sample = row.get("sample")
    if not isinstance(sample, dict):
        raise ValueError("sample must be an object")
    for field in ("prompt", "completion"):
        compact_text(sample.get(field), f"sample.{field}")
    facts = row.get("key_facts")
    if not isinstance(facts, list) or len(facts) not in (2, 3):
        raise ValueError("key_facts must contain 2 or 3 phrases")
    normalized = [compact_text(value, "key_fact") for value in facts]
    if len({value.casefold() for value in normalized}) != len(normalized):
        raise ValueError("key_facts must be distinct")
    return row


def validate_domain_configuration(domain_count: int, fusion_domains: list[str], source_domain: str) -> None:
    if type(domain_count) is not int or not 2 <= domain_count <= len(DOMAINS):
        raise ValueError(f"domain-count must be between 2 and {len(DOMAINS)} (including source)")
    if not isinstance(fusion_domains, list) or len(fusion_domains) != domain_count - 1:
        raise ValueError("fusion_domains must contain exactly domain_count - 1 domains")
    if any(not isinstance(d, str) or d not in DOMAINS or d == source_domain for d in fusion_domains):
        raise ValueError("fusion_domains must use supported identifiers and exclude source_domain")
    if len(set(fusion_domains)) != len(fusion_domains):
        raise ValueError("fusion_domains must be distinct")


def row_domains(row: dict, expected_count: int | None = None) -> list[str]:
    validate_v2_row(row)
    validate_domain_configuration(row.get("domain_count"), row.get("fusion_domains"), row["source_domain"])
    if expected_count is not None and row["domain_count"] != expected_count:
        raise ValueError("input domain_count differs from --domain-count")
    return list(row["fusion_domains"])


def validate_selected_plan(value: Any, source_domain: str, domain_count: int) -> dict:
    if not isinstance(value, dict):
        raise ValueError("selected plan must be an object")
    domains = value.get("fusion_domains")
    validate_domain_configuration(domain_count, domains, source_domain)
    return {"fusion_domains": domains, **validate_plans(value, [source_domain, *domains])}


def retrieval_query_row(row: dict, expected_count: int | None = None) -> dict:
    """Adapt v2 requirements for the original retrieval and embedding interfaces."""
    domains = row_domains(row, expected_count)
    validate_plans(row, [row["source_domain"], *domains])
    required = validate_required_key_facts(row.get("required_key_facts"), domains)
    return {
        "source_domain": row["source_domain"], "sample": row["sample"],
        "fusion_domains": domains,
        "fusion_idea": json.dumps(row["question_plan"], ensure_ascii=False),
        "queries": {d: [entry["key_fact"] for entry in required[d]] for d in domains},
    }


def validate_required_key_facts(value: Any, domains: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(value, dict) or set(value) != set(domains):
        raise ValueError("required_key_facts must cover exactly the fusion domains")
    normalized: dict[str, list[dict[str, Any]]] = {}
    for domain in domains:
        entries = value[domain]
        if not isinstance(entries, list) or len(entries) != 3:
            raise ValueError(f"{domain} must have exactly 3 required key facts")
        seen = set()
        output = []
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError("required key fact must be an object")
            fact = compact_text(entry.get("key_fact"), "required key_fact")
            folded = fact.casefold()
            if folded in seen:
                raise ValueError(f"duplicate required key fact for {domain}")
            seen.add(folded)
            used_by = entry.get("used_by")
            if not isinstance(used_by, list) or not used_by or any(item not in ANSWER_TYPES + ("question",) for item in used_by):
                raise ValueError("required key fact used_by is invalid")
            output.append({
                "key_fact": fact,
                "used_by": list(dict.fromkeys(used_by)),
                "necessity": compact_text(entry.get("necessity"), "required necessity"),
            })
        normalized[domain] = output
    return normalized


def validate_plans(value: Any, participating: list[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("plan result must be an object")
    question = value.get("question_plan")
    if not isinstance(question, dict):
        raise ValueError("question_plan must be an object")
    objective = compact_text(question.get("objective"), "question objective")
    conditions = compact_text(question.get("conditions"), "question conditions")
    link = compact_text(question.get("reasoning_link"), "question reasoning_link")
    roles = question.get("domain_roles")
    if not isinstance(roles, list) or len(roles) != len(participating):
        raise ValueError("question_plan.domain_roles must cover every participating domain")
    by_domain = {}
    for role in roles:
        if not isinstance(role, dict) or role.get("domain") not in participating or role["domain"] in by_domain:
            raise ValueError("question_plan has unknown or duplicate domain role")
        by_domain[role["domain"]] = {
            "domain": role["domain"],
            "role": compact_text(role.get("role"), "domain role"),
            "knowledge_needed": compact_text(role.get("knowledge_needed"), "domain knowledge_needed"),
        }
    answers = value.get("answer_plans")
    if not isinstance(answers, list) or len(answers) != 4:
        raise ValueError("answer_plans must contain four plans")
    by_type = {}
    for plan in answers:
        if not isinstance(plan, dict) or plan.get("type") not in ANSWER_TYPES or plan["type"] in by_type:
            raise ValueError("answer_plans must contain each answer type exactly once")
        missing = plan.get("missing_domain")
        if plan["type"] == "missing_domain_knowledge":
            if missing not in participating:
                raise ValueError("missing_domain_knowledge must name a participating domain")
        elif missing is not None:
            raise ValueError("only missing_domain_knowledge may name missing_domain")
        by_type[plan["type"]] = {
            "type": plan["type"], "missing_domain": missing,
            "plan": compact_text(plan.get("plan"), "answer plan"),
        }
    return {
        "question_plan": {
            "objective": objective,
            "conditions": conditions,
            "domain_roles": [by_domain[domain] for domain in participating],
            "reasoning_link": link,
        },
        "answer_plans": [by_type[answer_type] for answer_type in ANSWER_TYPES],
    }


def read_json_object(content: str) -> Any:
    """Parse strict JSON, allowing a single fenced block from less strict APIs."""
    text = content.strip()
    if text.startswith("```") and text.endswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE | re.DOTALL)
    return json.loads(text)


def validate_generation(value: Any, participating: list[str], candidate_ids: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("generation result must be an object")
    question = compact_text(value.get("question"), "question")
    options = value.get("options")
    if not isinstance(options, dict) or set(options) != {"A", "B", "C", "D"}:
        raise ValueError("options must contain exactly A, B, C, and D")
    options = {key: compact_text(options[key], f"option {key}") for key in "ABCD"}
    if len({text.casefold() for text in options.values()}) != 4:
        raise ValueError("options must be distinct")
    answer = value.get("answer")
    if answer not in options:
        raise ValueError("answer must be one of A, B, C, D")
    distractors = value.get("distractor_analysis")
    expected_types = {"missing_domain_knowledge", "parallel_knowledge", "incorrect_domain_relation"}
    if not isinstance(distractors, list) or len(distractors) != 3:
        raise ValueError("distractor_analysis must contain three entries")
    seen_types = set()
    normalized = []
    for entry in distractors:
        if not isinstance(entry, dict) or entry.get("type") not in expected_types or entry["type"] in seen_types:
            raise ValueError("distractor types must occur exactly once")
        option = entry.get("option")
        if option not in options or option == answer:
            raise ValueError("distractor must refer to a wrong option")
        missing = entry.get("missing_domain")
        if entry["type"] == "missing_domain_knowledge" and missing not in participating:
            raise ValueError("missing-domain distractor must name a participating domain")
        if entry["type"] != "missing_domain_knowledge" and missing is not None:
            raise ValueError("only missing-domain distractor may name a domain")
        seen_types.add(entry["type"])
        normalized.append({
            "option": option, "type": entry["type"], "missing_domain": missing,
            "reason": compact_text(entry.get("reason"), "distractor reason"),
        })
    used = value.get("used_material_ids")
    if not isinstance(used, list) or not used or any(item not in candidate_ids for item in used):
        raise ValueError("used_material_ids must contain supplied candidate IDs")
    return {
        "question": question, "options": options, "answer": answer,
        "explanation": compact_text(value.get("explanation"), "explanation"),
        "distractor_analysis": normalized,
        "used_material_ids": list(dict.fromkeys(used)),
        "plan_adjustment": compact_text(value.get("plan_adjustment", ""), "plan_adjustment") if value.get("plan_adjustment", "") else "",
    }
