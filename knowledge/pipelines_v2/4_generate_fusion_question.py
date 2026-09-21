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
    row_domains,
    validate_generation,
    validate_plans,
    validate_required_key_facts,
    validate_v2_row,
)


SYSTEM_PROMPT = """You use samples and key facts from all participating domains, together with
the question-construction idea and four answer-construction ideas, to construct
one complete cross-domain multiple-choice question.

The source domain is represented by the original sample and its key facts;
the additional domains are represented by retrieved samples and their key facts.
Use the fusion_domains selected in step 1 without adding or replacing domains.
The input includes an original atomic sample and its key facts, a question
construction idea (question_plan), four answer-construction ideas (answer_plans),
exactly three required key
facts for each fusion domain, and retrieved atomic samples with their key facts.
Use the supplied material as evidence. Do not invent domain facts to fill a gap.
Follow the construction ideas to design one joint task integrating knowledge
from multiple domains, and retain the original sample's core knowledge.
A cross-domain question requires specialized knowledge from every participating
domain to work together toward the same task objective. Merely changing the
setting, adding terminology, or concatenating unrelated questions does not
constitute valid fusion. Develop the concise ideas into a complete question
with all necessary conditions and four concrete answer options.

Create exactly four distinct, plausible options:
- correct: correctly combine all required domain facts and their relationships;
- missing_domain_knowledge: omit one necessary fact from one participating domain;
- parallel_knowledge: use domain facts separately but fail to account for their
  necessary interaction;
- incorrect_domain_relation: connect relevant domain facts incorrectly.

The correct option may be A, B, C, or D. Explain the correct reasoning and give
one analysis for each of the three wrong-option types. Use at least one retrieved
candidate from every fusion domain and return its exact candidate_id. If the
construction ideas need a substantive adjustment, describe it in plan_adjustment;
otherwise use an empty string. Return English text and only this JSON object:

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
  "used_material_ids": ["exact supplied candidate_id"],
  "plan_adjustment": ""
}
"""


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
    count = 0
    with output_file.open("w" if overwrite else "x", encoding="utf-8") as output:
        for line, row in read_rows(input_file):
            try:
                validate_v2_row(row)
                source = row["source_domain"]
                fusion_domains = row_domains(row, domain_count)
                participating = [source, *fusion_domains]
                plans = validate_plans({"question_plan": row.get("question_plan"), "answer_plans": row.get("answer_plans")}, participating)
                required = validate_required_key_facts(row.get("required_key_facts"), fusion_domains)
                retrieved = row.get("retrieved_samples")
                if not isinstance(retrieved, dict) or set(retrieved) != set(fusion_domains):
                    raise ValueError("retrieved_samples must cover exactly the fusion domains")
                candidates = []
                for domain in fusion_domains:
                    if not isinstance(retrieved[domain], list) or not retrieved[domain]:
                        raise ValueError(f"retrieved_samples.{domain} must be nonempty")
                    for candidate in retrieved[domain]:
                        if not isinstance(candidate, dict) or not isinstance(candidate.get("candidate_id"), str):
                            raise ValueError("retrieved candidate is invalid")
                        candidates.append(candidate)
                candidate_ids = {candidate["candidate_id"] for candidate in candidates}
                candidate_domain = {candidate["candidate_id"]: domain for domain in fusion_domains for candidate in retrieved[domain]}

                payload = {
                    "source_domain": source,
                    "sample": row["sample"],
                    "key_facts": row["key_facts"],
                    "fusion_domains": fusion_domains,
                    "question_plan": plans["question_plan"],
                    "answer_plans": plans["answer_plans"],
                    "required_key_facts": required,
                    "retrieved_samples": retrieved,
                    "option_count": 4,
                }
                if len(json.dumps(payload, ensure_ascii=False)) > max_input_chars:
                    raise ValueError("generation input exceeds --max-input-chars; no sample was truncated")

                def validate(value: Any) -> dict[str, Any]:
                    result = validate_generation(value, participating, candidate_ids)
                    used_domains = {candidate_domain[item] for item in result["used_material_ids"]}
                    if used_domains != set(fusion_domains):
                        raise ValueError("used_material_ids must include at least one candidate from every fusion domain")
                    return result

                generated = api.chat(SYSTEM_PROMPT, payload, validate, max_tokens)
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
                "required_key_facts": required,
                "retrieved_samples": retrieved,
                "retrieval": row.get("retrieval", {}),
                **generated,
            }
            write_row(output, output_row)
            count += 1
            print(f"line={line} generated={count}", file=sys.stderr, flush=True)
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
