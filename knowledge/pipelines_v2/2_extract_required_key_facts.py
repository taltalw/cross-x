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


SYSTEM_PROMPT = """You extract the external knowledge needed to complete a cross-domain
question-construction task.

The input contains an original atomic sample, its key facts, a question-construction
idea (question_plan), and four answer-construction ideas (answer_plans).
What knowledge does each domain in fusion_domains need to provide to construct
the question and four types of answers following these ideas? For each domain,
list exactly three short English key-fact phrases to retrieve atomic samples
that contain this knowledge. A required key fact must be a concrete concept,
mechanism, rule, condition, or relationship; do not output a complete question,
generic domain labels, or facts belonging to another domain.

Cover what the question-construction idea and answer-construction ideas actually
need, including the knowledge needed for their cross-domain reasoning links.
The three facts for a domain must be distinct and collectively useful.
Mark which construction ideas use each
fact with values from question, correct, missing_domain_knowledge,
parallel_knowledge, and incorrect_domain_relation. Explain why each fact is
necessary in one concise sentence. Do not invent a fact merely to fill a slot.

Return only this JSON object:
{
  "required_key_facts": {
    "domain_a": [
      {"key_fact": "specific phrase", "used_by": ["question", "correct"], "necessity": "Why it is needed."},
      {"key_fact": "specific phrase", "used_by": ["correct", "missing_domain_knowledge"], "necessity": "Why it is needed."},
      {"key_fact": "specific phrase", "used_by": ["question", "parallel_knowledge"], "necessity": "Why it is needed."}
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
