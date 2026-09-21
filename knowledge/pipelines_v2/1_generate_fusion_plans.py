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


SYSTEM_PROMPT = """You design a concise construction idea for a cross-domain question,
to guide subsequent external-knowledge extraction, sample retrieval, and
generation of the question and its four answer options.

The input contains an original atomic sample, its key facts, the source domain,
a list of candidate domains, and the requested total domain_count.
Based on the sample and its key facts, consider which additional domains can
participate in one cross-domain question. Choose exactly domain_count - 1 distinct
candidate domains, excluding the source domain, and return one combination in
fusion_domains. The total includes the source domain. Select domains for their
necessary specialized knowledge, not generic associations with domain names.
Using the chosen domains and the source domain, design one joint task that
integrates knowledge from multiple domains. A cross-domain question
requires specialized knowledge from every participating domain to work together
toward the same task objective. Merely changing the setting, adding terminology,
or concatenating unrelated questions does not constitute valid fusion.
Retain the original sample's core knowledge. Do not invent supporting facts:
identify what must be provided by later retrieved samples.

Provide a concise question-construction idea and four answer-construction ideas:
1. correct: combine all domains and their necessary relationships correctly;
2. missing_domain_knowledge: omit one specific necessary fact from one
   participating domain while using the other domains correctly;
3. parallel_knowledge: use domain facts correctly in isolation but fail to model
   their necessary interaction;
4. incorrect_domain_relation: use relevant facts but connect domains incorrectly,
   such as reversing causality or applying a condition to the wrong result.

Use question_plan to record the question-construction idea and answer_plans to
record the four answer-construction ideas. Briefly state the joint objective,
essential conditions, each domain's contribution, and their reasoning link.
Keep each explanatory field to one short sentence and each answer-construction
idea to one or two sentences. Do not write the complete question or final options.
The later stage will create exactly four options and may place the correct
option anywhere.
Return English text and only the requested JSON object.

Required JSON structure (expand fusion_domains and domain_roles to the requested count):
{
  "fusion_domains": ["selected_candidate_domain"],
  "question_plan": {
    "objective": "One joint task objective.",
    "conditions": "Essential givens or conditions needed to solve it.",
    "domain_roles": [
      {"domain": "exact domain", "role": "necessary contribution", "knowledge_needed": "specific knowledge needed"}
    ],
    "reasoning_link": "How the domain contributions interact toward one answer."
  },
  "answer_plans": [
    {"type": "correct", "missing_domain": null, "plan": "..."},
    {"type": "missing_domain_knowledge", "missing_domain": "one participating domain", "plan": "..."},
    {"type": "parallel_knowledge", "missing_domain": null, "plan": "..."},
    {"type": "incorrect_domain_relation", "missing_domain": null, "plan": "..."}
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
