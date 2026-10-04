#!/usr/bin/env python3
"""Generate a fusion-question plan and four answer-construction plans."""

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
    DOMAIN_DESCRIPTIONS,
    validate_selected_plan,
    validate_v2_row,
)


SYSTEM_PROMPT = """Design a concise idea for constructing a natural cross-domain question.
The question should ask for one joint task that integrates knowledge from
multiple domains; its four answer choices should contain one correct answer and three distractor answers.

The input contains an original atomic sample, its key facts, the source domain,
a list of candidate domains, and the requested total domain_count.

Tasks:
1. Based on the sample and its key facts, consider which additional domains can
   participate in cross-domain question construction. Choose exactly domain_count - 1 distinct
   candidate domains, excluding the source domain.
2. Using the chosen domains and the source domain, design one joint task that
   integrates knowledge from multiple domains. Provide a brief question-construction
   idea as a single string in question_plan.
3. Consider how to construct four answer choices. Provide four answer-construction ideas:
   - correct: combine the domain knowledge correctly and answer the joint task;
   - missing_domain_knowledge: omit a necessary fact from one named domain;
   - parallel_knowledge: include the relevant knowledge but fail to connect it
     to the answer;
   - incorrect_domain_relation: connect the domain knowledge incorrectly.

Requirements:
- Construct a natural question; avoid forced or awkward combinations of domains.
- Do not write the complete question or final options. The later stage will
  create exactly four options and may place the correct option anywhere.
- Return only an English JSON object in the following format. Include exactly
  domain_count - 1 fusion_domains:
{
  "fusion_domains": ["selected_candidate_domain"],
  "question_plan": "Brief idea for one joint task integrating the chosen domains.",
  "answer_plans": [
    {"type": "correct", "missing_domain": null, "plan": "..."},
    {"type": "missing_domain_knowledge", "missing_domain": "one participating domain", "plan": "..."},
    {"type": "parallel_knowledge", "missing_domain": null, "plan": "..."},
    {"type": "incorrect_domain_relation", "missing_domain": null, "plan": "..."}
  ]
}

Example:
- input
{
  "source_domain": "mathematics",
  "sample": {"prompt": "Calculate the area of a circle of radius r.", "completion": "pi * r**2"},
  "key_facts": ["circle area", "pi times radius squared"],
  "candidate_domains": [
    {"name": "medical", "description": "Medicine: physiology, disease, diagnosis, treatment, pharmacology, and public health."},
    {"name": "legal", "description": "Law: legal rules, rights, obligations, contracts, liability, procedure, and compliance."},
    {"name": "financial", "description": "Finance: money, banking, investment, asset pricing, corporate finance, accounting, and risk."},
    {"name": "computer_science", "description": "Computer science: algorithms, data structures, networks, operating systems, databases, and security."},
    {"name": "geography", "description": "Geography: landforms, geology, climate, hydrology, spatial distributions, resources, and human-environment relations."},
    {"name": "chemistry", "description": "Chemistry: matter, chemical reactions, mechanisms, analytical methods, and chemical safety."}
  ],
  "domain_count": 2
}

- output
{
  "fusion_domains": ["computer_science"],
  "question_plan": "Write a Python function that calculates a circle's area from its radius and returns the result, assuming math is imported and the radius is positive.",
  "answer_plans": [
    {"type": "correct", "missing_domain": null, "plan": "Compute pi times the radius squared and return the computed area."},
    {"type": "missing_domain_knowledge", "missing_domain": "mathematics", "plan": "Return the radius squared while omitting the required factor pi."},
    {"type": "parallel_knowledge", "missing_domain": null, "plan": "Compute the correct area expression but return the radius instead of the computed value."},
    {"type": "incorrect_domain_relation", "missing_domain": null, "plan": "Square the product of pi and the radius, applying the square to pi as well as the radius."}
  ]
}
"""


def process(input_file: Path, output_file: Path, *, api: JSONAPI, domain_count: int,
            num: int | None, max_tokens: int, overwrite: bool) -> dict[str, Any]:
    if input_file.resolve() == output_file.resolve():
        raise ValueError("input and output must be different files")
    if not input_file.is_file():
        raise FileNotFoundError(input_file)
    if type(domain_count) is not int or not 2 <= domain_count <= len(DOMAIN_DESCRIPTIONS):
        raise ValueError("domain-count must be between 2 and 7, including the source domain")
    if num is not None and num < 1:
        raise ValueError("num must be positive")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with output_file.open("w" if overwrite else "x", encoding="utf-8") as output:
        for line, row in read_rows(input_file):
            try:
                validate_v2_row(row)
                source = row["source_domain"]
                payload = {
                    "source_domain": source,
                    "sample": row["sample"],
                    "key_facts": row["key_facts"],
                    "candidate_domains": [{"name": d, "description": desc} for d, desc in DOMAIN_DESCRIPTIONS.items() if d != source],
                    "domain_count": domain_count,
                }

                def validate(value: Any) -> dict[str, Any]:
                    return validate_selected_plan(value, source, domain_count)

                plans = api.chat(SYSTEM_PROMPT, payload, validate, max_tokens)
            except APIError as exc:
                raise APIError(f"{input_file}:{line}: {exc}; completed output retained") from None
            except ValueError as exc:
                raise ValueError(f"{input_file}:{line}: {exc}; completed output retained") from None
            result = {
                "source_file": row.get("source_file", str(input_file.resolve())),
                "source_domain": source,
                "model": api.model,
                "sample": row["sample"],
                "key_facts": row["key_facts"],
                "domain_count": domain_count,
                **plans,
            }
            write_row(output, result)
            count += 1
            print(f"line={line} planned={count}", file=sys.stderr, flush=True)
            if num is not None and count >= num:
                break
    return {"processed": count, "output": str(output_file.resolve())}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--domain-count", type=int, required=True)
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
