#!/usr/bin/env python3
"""Generate a four-option fusion question from plans and retrieved samples."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from knowledge.pipelines._knowledge_search_common import APIError, JSONAPI, read_rows, write_row

from _pipeline_common import (
    compact_text,
    row_domains,
    sample_reference,
    validate_generation,
    validate_plans,
    validate_required_key_facts,
    validate_v2_row,
)


DIFFICULTIES = ("easy", "medium", "hard")


SCREEN_PROMPT = """Check whether the retrieved samples provide enough evidence
to construct the planned cross-domain question and all four answer choices.

Tasks:
1. For each required key fact in each fusion domain, identify the retrieved
   samples whose original prompt and completion support it.
2. Decide whether the supported facts can complete question_plan and
   answer_plans together without inventing facts or changing the joint task.

Requirements:
- Judge support from the original sample and retrieved sample prompt/completion.
  Key-fact labels, retrieval matches, and scores are hints, not proof.
- Mark sufficient false if a required fact or a necessary cross-domain link is
  unsupported. List only supplied samples from the corresponding domain.
- Return the supporting samples for each fusion domain. Give a brief reason
  for the decision; an empty list means that domain has no supporting sample.
- Return only an English JSON object in this format:
{
  "sufficient": true,
  "reason": "Which evidence is missing, or why the plan is supported.",
  "supporting_samples": {
    "fusion_domain": [{"prompt": "Original question", "completion": "Original answer"}]
  }
}

Example:
- input
{
  "source_domain": "mathematics",
  "sample": {"prompt": "Calculate the area of a circle of radius r.", "completion": "pi * r**2"},
  "key_facts": ["circle area", "pi times radius squared"],
  "fusion_domains": ["computer_science"],
  "question_plan": "Write a Python function that returns a circle's area.",
  "answer_plans": [
    {"type": "correct", "missing_domain": null, "plan": "Return pi times radius squared."},
    {"type": "missing_domain_knowledge", "missing_domain": "mathematics", "plan": "Omit pi."},
    {"type": "parallel_knowledge", "missing_domain": null, "plan": "Compute the area but return the radius."},
    {"type": "incorrect_domain_relation", "missing_domain": null, "plan": "Square pi with the radius."}
  ],
  "required_key_facts": {
    "computer_science": [
      {"key_fact": "Python return statement", "necessity": "Return the calculation."},
      {"key_fact": "Python math.pi constant", "necessity": "Use pi in code."},
      {"key_fact": "Python exponentiation", "necessity": "Square the radius."}
    ]
  },
  "retrieved_samples": {
    "computer_science": [
      {"prompt": "What does return do in Python?", "completion": "It returns a value from a function."}
    ]
  }
}

- output
{
  "sufficient": false,
  "reason": "The retrieved sample does not support math.pi or exponentiation.",
  "supporting_samples": {
    "computer_science": [
      {"prompt": "What does return do in Python?", "completion": "It returns a value from a function."}
    ]
  }
}
"""


SYSTEM_PROMPT = """Construct one cross-domain multiple-choice question from
the supplied plan and evidence-supported retrieved samples.

The input includes the original atomic sample and key facts, fusion_domains,
question_plan, answer_plans, required_key_facts, retrieved_samples, and the
requested difficulty. The source domain is represented by the original sample;
the fusion domains are represented by retrieved samples.

Tasks:
1. Follow the question_plan to create one natural joint task using the original
   sample's core knowledge and every chosen fusion domain.
2. Create four distinct options: one correct answer and three distractors of
   types missing_domain_knowledge, parallel_knowledge, and
   incorrect_domain_relation. The correct option may be A, B, C, or D.
3. Explain the correct answer, analyze each distractor, and list at least one
   used sample from every fusion domain in used_samples.

Requirements:
- Write the question at the requested difficulty. Do not define difficulty
  levels or put the difficulty label in the question or options.
- Keep the question and answer options as concise as possible while including
  the conditions needed to solve it. Put no extra reasoning steps in the
  question or options; use explanation for reasoning.
- Use the supplied sample text as evidence. Do not invent domain facts, add
  domains, or replace the joint task with another task.
- If the plan needs a substantive adjustment, describe it in plan_adjustment;
  otherwise use an empty string.
- Return only an English JSON object in this format:

{
  "question": "Complete question with all necessary conditions.",
  "options": {"A": "...", "B": "...", "C": "...", "D": "..."},
  "answer": "B",
  "explanation": "Why the correct option follows from the participating domains.",
  "distractor_analysis": [
    {"option": "A", "type": "missing_domain_knowledge", "missing_domain": "domain", "reason": "..."},
    {"option": "C", "type": "parallel_knowledge", "missing_domain": null, "reason": "..."},
    {"option": "D", "type": "incorrect_domain_relation", "missing_domain": null, "reason": "..."}
  ],
  "used_samples": {"fusion_domain": [{"prompt": "Original question", "completion": "Original answer"}]},
  "plan_adjustment": ""
}

Example:
- input
{
  "source_domain": "mathematics",
  "sample": {"prompt": "Calculate the area of a circle of radius r.", "completion": "pi * r**2"},
  "key_facts": ["circle area", "pi times radius squared"],
  "fusion_domains": ["computer_science"],
  "question_plan": "Write a Python function that calculates a circle's area from its radius and returns the result, assuming math is imported and the radius is positive.",
  "answer_plans": [
    {"type": "correct", "missing_domain": null, "plan": "Compute pi times the radius squared and return the computed area."},
    {"type": "missing_domain_knowledge", "missing_domain": "mathematics", "plan": "Return the radius squared while omitting the required factor pi."},
    {"type": "parallel_knowledge", "missing_domain": null, "plan": "Compute the correct area expression but return the radius instead of the computed value."},
    {"type": "incorrect_domain_relation", "missing_domain": null, "plan": "Square the product of pi and the radius, applying the square to pi as well as the radius."}
  ],
  "required_key_facts": {
    "computer_science": [
      {"key_fact": "Python function return statement", "necessity": "The function must return the area."},
      {"key_fact": "Python math module pi constant", "necessity": "The expression needs pi."},
      {"key_fact": "Python exponentiation and parentheses", "necessity": "Only the radius is squared."}
    ]
  },
  "retrieved_samples": {
    "computer_science": [
      {"prompt": "What do return, math.pi, **, and parentheses do in Python?", "completion": "return sends back a value; math.pi is pi; ** exponentiates; parentheses group operations."}
    ]
  },
  "option_count": 4,
  "difficulty": "easy"
}

- output
{
  "question": "With math imported and r > 0, which function returns a circle's area?",
  "options": {
    "A": "def area(r): return math.pi * r**2",
    "B": "def area(r): return r**2",
    "C": "def area(r): math.pi * r**2; return r",
    "D": "def area(r): return (math.pi * r)**2"
  },
  "answer": "A",
  "explanation": "The function returns pi times the radius squared.",
  "distractor_analysis": [
    {"option": "B", "type": "missing_domain_knowledge", "missing_domain": "mathematics", "reason": "It omits pi."},
    {"option": "C", "type": "parallel_knowledge", "missing_domain": null, "reason": "It computes the area but returns the radius."},
    {"option": "D", "type": "incorrect_domain_relation", "missing_domain": null, "reason": "It squares pi along with the radius."}
  ],
  "used_samples": {
    "computer_science": [
      {"prompt": "What do return, math.pi, **, and parentheses do in Python?", "completion": "return sends back a value; math.pi is pi; ** exponentiates; parentheses group operations."}
    ]
  },
  "plan_adjustment": ""
}
"""


def validate_screening(value: Any, required: dict, available_samples: dict[str, set[tuple[str, str]]]) -> dict:
    if not isinstance(value, dict) or type(value.get("sufficient")) is not bool:
        raise ValueError("screening result must contain a boolean sufficient")
    reason = compact_text(value.get("reason"), "screening reason")
    supporting = value.get("supporting_samples")
    if not isinstance(supporting, dict) or set(supporting) != set(required):
        raise ValueError("supporting_samples must cover exactly the fusion domains")
    normalized = {}
    for domain, samples in supporting.items():
        if not isinstance(samples, list):
            raise ValueError(f"supporting_samples.{domain} must be a list")
        normalized[domain] = []
        seen = set()
        for sample in samples:
            reference = sample_reference(sample)
            if reference not in available_samples[domain]:
                raise ValueError(f"supporting_samples.{domain} must cite supplied samples")
            if reference not in seen:
                normalized[domain].append({"prompt": reference[0], "completion": reference[1]})
                seen.add(reference)
        if value["sufficient"] and not normalized[domain]:
            raise ValueError("sufficient screening requires samples from every fusion domain")
    return {"sufficient": value["sufficient"], "reason": reason,
            "supporting_samples": normalized}


def process(input_file: Path, output_file: Path, *, api: JSONAPI, domain_count: int | None,
            num: int | None, max_tokens: int,
            max_input_chars: int, overwrite: bool) -> dict[str, Any]:
    if input_file.resolve() == output_file.resolve():
        raise ValueError("input and output must be different files")
    if not input_file.is_file():
        raise FileNotFoundError(input_file)
    if num is not None and num < 1 or max_tokens < 1 or max_input_chars < 1:
        raise ValueError("num, max-tokens, and max-input-chars must be positive")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    processed = 0
    skipped = 0
    generated_count = 0
    with output_file.open("w" if overwrite else "x", encoding="utf-8") as output:
        for line, row in read_rows(input_file):
            if num is not None and processed >= num:
                break
            try:
                validate_v2_row(row)
                source = row["source_domain"]
                fusion_domains = row_domains(row, domain_count)
                participating = [source, *fusion_domains]
                plans = validate_plans({"question_plan": row.get("question_plan"), "answer_plans": row.get("answer_plans")}, participating)
                required = validate_required_key_facts(row.get("required_key_facts"), fusion_domains)
                retrieved_candidates = row.get("retrieved_samples")
                if not isinstance(retrieved_candidates, dict) or set(retrieved_candidates) != set(fusion_domains):
                    raise ValueError("retrieved_samples must cover exactly the fusion domains")
                retrieved = {}
                empty_domains = []
                for domain in fusion_domains:
                    if not isinstance(retrieved_candidates[domain], list):
                        raise ValueError(f"retrieved_samples.{domain} must be a list")
                    if not retrieved_candidates[domain]:
                        empty_domains.append(domain)
                    retrieved[domain] = []
                    seen = set()
                    for candidate in retrieved_candidates[domain]:
                        if not isinstance(candidate, dict):
                            raise ValueError("retrieved candidate is invalid")
                        source_sample = candidate.get("sample", candidate)
                        if not isinstance(source_sample, dict):
                            raise ValueError("retrieved sample is invalid")
                        sample = {field: source_sample.get(field) for field in ("prompt", "completion")}
                        reference = sample_reference(sample)
                        if reference not in seen:
                            retrieved[domain].append(sample)
                            seen.add(reference)

                processed += 1
                if empty_domains:
                    skipped += 1
                    print(f"line={line} skipped: no retrieved samples for {', '.join(empty_domains)}", file=sys.stderr, flush=True)
                    continue

                base_payload = {
                    "source_domain": source,
                    "sample": row["sample"],
                    "key_facts": row["key_facts"],
                    "fusion_domains": fusion_domains,
                    "question_plan": plans["question_plan"],
                    "answer_plans": plans["answer_plans"],
                    "required_key_facts": required,
                    "retrieved_samples": retrieved,
                }
                if len(json.dumps(base_payload, ensure_ascii=False)) > max_input_chars:
                    raise ValueError("screening input exceeds --max-input-chars; no sample was truncated")

                available = {domain: {sample_reference(sample) for sample in retrieved[domain]}
                             for domain in fusion_domains}
                screen = api.chat(SCREEN_PROMPT, base_payload,
                                  lambda value: validate_screening(value, required, available), max_tokens)
                if not screen["sufficient"]:
                    skipped += 1
                    print(f"line={line} skipped: {screen['reason']}", file=sys.stderr, flush=True)
                    continue

                supported = screen["supporting_samples"]
                supported_keys = {domain: {sample_reference(sample) for sample in supported[domain]}
                                  for domain in fusion_domains}

                for difficulty in DIFFICULTIES:
                    payload = {**base_payload, "retrieved_samples": supported,
                               "option_count": 4, "difficulty": difficulty}
                    if len(json.dumps(payload, ensure_ascii=False)) > max_input_chars:
                        raise ValueError("generation input exceeds --max-input-chars; no sample was truncated")

                    def validate(value: Any) -> dict[str, Any]:
                        return validate_generation(value, participating, supported_keys)

                    generated = api.chat(SYSTEM_PROMPT, payload, validate, max_tokens)
                    output_row = {
                        "source_file": row.get("source_file", str(input_file.resolve())),
                        "source_domain": source,
                        "model": api.model,
                        "sample": row["sample"],
                        "key_facts": row["key_facts"],
                        "fusion_domains": fusion_domains,
                        "domain_count": row["domain_count"],
                        "question_plan": plans["question_plan"],
                        "answer_plans": plans["answer_plans"],
                        "required_key_facts": required,
                        "retrieved_samples": retrieved,
                        "retrieval": row.get("retrieval", {}),
                        **generated,
                        "difficulty": difficulty,
                    }
                    write_row(output, output_row)
                    generated_count += 1
                    print(f"line={line} difficulty={difficulty} generated={generated_count}", file=sys.stderr, flush=True)
            except APIError as exc:
                raise APIError(f"{input_file}:{line}: {exc}; completed output retained") from None
            except ValueError as exc:
                raise ValueError(f"{input_file}:{line}: {exc}; completed output retained") from None
    return {"processed": processed, "skipped": skipped, "generated": generated_count,
            "output": str(output_file.resolve())}


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
    args = parser.parse_args()
    try:
        api = JSONAPI(args.api_base_url, args.api_key, args.model, args.timeout, args.retries)
        report = process(args.input, args.output, api=api, domain_count=args.domain_count,
                         num=args.num, max_tokens=args.max_tokens,
                         max_input_chars=args.max_input_chars, overwrite=args.overwrite)
    except (OSError, ValueError, APIError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
