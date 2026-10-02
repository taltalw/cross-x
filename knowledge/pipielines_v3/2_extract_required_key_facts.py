#!/usr/bin/env python3
"""Identify three required key facts for each fusion domain."""

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
    ANSWER_TYPES,
    row_domains,
    validate_plans,
    validate_required_key_facts,
    validate_v2_row,
)


SYSTEM_PROMPT = """Identify the external knowledge needed to construct a cross-domain
question and its four answer choices.

The input contains an original atomic sample, its key facts, the source domain,
the chosen fusion_domains, a question-construction idea (question_plan), and
four answer-construction ideas (answer_plans).

Tasks:
1. For each domain in fusion_domains, identify exactly three short English
   key-fact phrases needed to construct the question and four answer choices.
2. Explain in one concise sentence why each key fact is needed in necessity.

Requirements:
- Cover the knowledge needed by question_plan and answer_plans, including
  their cross-domain reasoning links.
- Each key_fact must name a concrete concept, mechanism, rule, condition, or
  relationship from its fusion domain. The three facts for a domain must be
  distinct and collectively useful; do not invent a fact just to fill a slot.
- Do not write the complete question, generic domain labels, or facts belonging
  to another domain.
- Return only an English JSON object in this format, with exactly three entries
  for every domain in fusion_domains:
{
  "required_key_facts": {
    "fusion_domain": [
      {"key_fact": "specific phrase", "necessity": "Why it is needed."},
      {"key_fact": "specific phrase", "necessity": "Why it is needed."},
      {"key_fact": "specific phrase", "necessity": "Why it is needed."}
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
  "question_plan": "Write a Python function that calculates a circle's area from its radius and returns the result, assuming math is imported and the radius is positive.",
  "answer_plans": [
    {"type": "correct", "missing_domain": null, "plan": "Compute pi times the radius squared and return the computed area."},
    {"type": "missing_domain_knowledge", "missing_domain": "mathematics", "plan": "Return the radius squared while omitting the required factor pi."},
    {"type": "parallel_knowledge", "missing_domain": null, "plan": "Compute the correct area expression but return the radius instead of the computed value."},
    {"type": "incorrect_domain_relation", "missing_domain": null, "plan": "Square the product of pi and the radius, applying the square to pi as well as the radius."}
  ],
  "answer_plan_types": ["correct", "missing_domain_knowledge", "parallel_knowledge", "incorrect_domain_relation"]
}

- output
{
  "required_key_facts": {
    "computer_science": [
      {"key_fact": "Python function return statement", "necessity": "The area expression must become the function's returned value rather than an unused computation."},
      {"key_fact": "Python math module pi constant", "necessity": "The function needs a Python expression for the mathematical factor pi."},
      {"key_fact": "Python exponentiation and parentheses", "necessity": "The code must square the radius without also squaring pi."}
    ]
  }
}
"""


def process(input_file: Path, output_file: Path, *, api: JSONAPI, domain_count: int | None,
            num: int | None, max_tokens: int, overwrite: bool) -> dict[str, Any]:
    if input_file.resolve() == output_file.resolve():
        raise ValueError("input and output must be different files")
    if not input_file.is_file():
        raise FileNotFoundError(input_file)
    if num is not None and num < 1:
        raise ValueError("num must be positive")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with output_file.open("w" if overwrite else "x", encoding="utf-8") as output:
        for line, row in read_rows(input_file):
            try:
                validate_v2_row(row)
                source = row["source_domain"]
                fusion_domains = row_domains(row, domain_count)
                plans = validate_plans({
                    "question_plan": row.get("question_plan"),
                    "answer_plans": row.get("answer_plans"),
                }, [source, *fusion_domains])
                payload = {
                    "source_domain": source,
                    "sample": row["sample"],
                    "key_facts": row["key_facts"],
                    "fusion_domains": fusion_domains,
                    "question_plan": plans["question_plan"],
                    "answer_plans": plans["answer_plans"],
                    "answer_plan_types": list(ANSWER_TYPES),
                }

                def validate(value: Any) -> dict[str, Any]:
                    if not isinstance(value, dict):
                        raise ValueError("LLM result must be an object")
                    return {"required_key_facts": validate_required_key_facts(value.get("required_key_facts"), fusion_domains)}

                result = api.chat(SYSTEM_PROMPT, payload, validate, max_tokens)
            except APIError as exc:
                raise APIError(f"{input_file}:{line}: {exc}; completed output retained") from None
            except ValueError as exc:
                raise ValueError(f"{input_file}:{line}: {exc}; completed output retained") from None
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
                "required_key_facts": result["required_key_facts"],
            }
            write_row(output, output_row)
            count += 1
            print(f"line={line} required-facts={count}", file=sys.stderr, flush=True)
            if num is not None and count >= num:
                break
    return {"processed": count, "output": str(output_file.resolve())}


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
    parser.add_argument("--max-tokens", type=int, default=2048)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    try:
        if args.num is not None and args.num < 1 or args.max_tokens < 1:
            raise ValueError("num and max-tokens must be positive")
        api = JSONAPI(args.api_base_url, args.api_key, args.model, args.timeout, args.retries)
        report = process(args.input, args.output, api=api, domain_count=args.domain_count,
                         num=args.num, max_tokens=args.max_tokens,
                         overwrite=args.overwrite)
    except (OSError, ValueError, APIError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
