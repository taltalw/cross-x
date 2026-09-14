#!/usr/bin/env python3
r"""Generate searchable knowledge queries for step-1 fusion ideas."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DOMAINS = {
    "medical": "Medicine: physiology, disease, diagnosis, treatment, pharmacology, and public health.",
    "legal": "Law: rules, rights, contracts, liability, procedure, and compliance.",
    "financial": "Finance: banking, investment, pricing, corporate finance, accounting, and risk.",
    "mathematics": "Mathematics: algebra, calculus, probability, statistics, optimization, and modeling.",
    "computer_science": "Computer science: algorithms, data structures, networks, systems, databases, and security.",
    "geography": "Geography: landforms, geology, climate, hydrology, spatial distributions, and resources.",
    "chemistry": "Chemistry: matter, reactions, mechanisms, analysis, synthesis, and chemical safety.",
}
QUERIES_PER_DOMAIN = 3
DEFAULT_OUTPUT_ROOT = Path(__file__).resolve().parent / "outputs" / "2_generate_knowledge_queries"

SYSTEM_PROMPT_TEMPLATE = """You generate retrieval queries for step 3 of a cross-domain knowledge dataset.

The user message contains an original question and a feasible fusion idea involving the listed fusion domains. For EACH fusion domain (not the source domain), determine what knowledge that domain needs to provide in order to solve the planned cross-domain question, then generate exactly three concise search phrases for retrieving suitable samples from that domain.

Original question:
{original_question}

Feasible fusion idea:
{fusion_idea}

Fusion domains and descriptions:
{fusion_domains}

Requirements:
1. Generate exactly three queries for every listed fusion domain and no other domains.
2. The queries are for retrieving samples or knowledge entries from the fusion domain that could support construction of the planned cross-domain question. They should target the type of domain knowledge the fusion domain must contribute, rather than ask for a complete cross-domain solution.
3. For each domain, infer from the fusion idea what knowledge is needed to solve the planned question: identify the relevant entities or concepts, mechanisms/relationships/conditions, and facts/rules/methods that a retrieved sample should contain.
4. Queries must be directly usable search phrases, preferably short noun phrases or compact keyword strings rather than complete questions or sentences.
5. Cover different retrieval needs: core concept/entity, mechanism/relationship/condition, and a specific fact/rule/method needed to support the answer. Adapt these categories to the domain and idea; do not use generic placeholders.
6. Anchor every query in the concrete entities, processes, conditions, or answer requirements from the original question and fusion idea. Avoid merely repeating the original question.
7. Avoid vague queries such as "medical knowledge" or "important chemistry facts", and avoid queries that ask an entire cross-domain question. Do not include citations, invented numbers, or unsupported assumptions.
8. Use terminology likely to occur in authoritative domain materials. Keep each query concise (normally 3–12 content words). Queries within a domain must be meaningfully different.
9. Output only JSON, with English domain identifiers as keys and arrays of exactly three English query strings as values.

Output format:
{{"queries": {{"fusion_domain_1": ["query 1", "query 2", "query 3"]}}}}
"""


class APIError(RuntimeError):
    pass


def text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a nonempty string")
    return value.strip()


def validate_input(row: Any) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise ValueError("input row must be an object")
    source = text(row.get("source_domain"), "source_domain")
    if source not in DOMAINS:
        raise ValueError("unsupported source_domain")
    sample = row.get("sample")
    if not isinstance(sample, dict):
        raise ValueError("sample must be an object")
    text(sample.get("prompt"), "sample.prompt")
    text(sample.get("completion"), "sample.completion")
    domains = row.get("fusion_domains")
    if not isinstance(domains, list) or not domains:
        raise ValueError("fusion_domains must be a nonempty list")
    if len(set(domains)) != len(domains) or any(d not in DOMAINS or d == source for d in domains):
        raise ValueError("fusion_domains contains duplicates, source domain, or unknown domain")
    if row.get("status") != "feasible":
        raise ValueError("only feasible step-1 rows can generate queries")
    idea = row.get("fusion_idea")
    if not isinstance(idea, dict):
        raise ValueError("fusion_idea must be an object")
    text(idea.get("idea"), "fusion_idea.idea")
    text(idea.get("correct_answer_plan"), "fusion_idea.correct_answer_plan")
    distractors = idea.get("distractor_plans")
    if not isinstance(distractors, list):
        raise ValueError("fusion_idea.distractor_plans must be a list")
    return row


def build_messages(row: dict[str, Any]) -> list[dict[str, str]]:
    domains = row["fusion_domains"]
    idea = row["fusion_idea"]
    compact_idea = {
        "original_question": row["sample"]["prompt"],
        "fusion_idea": idea["idea"],
        "correct_answer_plan": idea["correct_answer_plan"],
        "distractor_plans": idea["distractor_plans"],
    }
    system = SYSTEM_PROMPT_TEMPLATE.replace("{original_question}", json.dumps(row["sample"]["prompt"], ensure_ascii=False)).replace("{fusion_idea}", json.dumps(compact_idea, ensure_ascii=False)).replace(
        "{fusion_domains}", "\n".join(f"- {d}: {DOMAINS[d]}" for d in domains)
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": "Generate the retrieval queries now."}]


def validate_result(value: Any, domains: list[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or not isinstance(value.get("queries"), dict):
        raise ValueError("response must contain a queries object")
    queries = value["queries"]
    if set(queries) != set(domains):
        raise ValueError("queries must contain exactly the fusion domains")
    normalized = {}
    for domain in domains:
        values = queries[domain]
        if not isinstance(values, list) or len(values) != QUERIES_PER_DOMAIN:
            raise ValueError(f"{domain} must have exactly {QUERIES_PER_DOMAIN} queries")
        cleaned = [text(q, f"{domain} query") for q in values]
        if len({" ".join(q.split()).casefold() for q in cleaned}) != len(cleaned):
            raise ValueError(f"{domain} queries must be distinct")
        normalized[domain] = cleaned
    return {"queries": normalized}


def call_llm(row: dict[str, Any], *, api_base_url: str, api_key: str, model: str,
             timeout: float, retries: int, max_tokens: int) -> dict[str, Any]:
    payload = {"model": model, "messages": build_messages(row), "temperature": 0,
               "max_tokens": max_tokens, "response_format": {"type": "json_object"}}
    last_error = "request failed"
    for attempt in range(retries + 1):
        request = urllib.request.Request(
            api_base_url.rstrip("/") + "/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode(),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = json.load(response)
            raw = body["choices"][0]["message"]["content"]
            return validate_result(json.loads(raw), row["fusion_domains"])
        except urllib.error.HTTPError as exc:
            last_error = f"API returned HTTP {exc.code}"; exc.close()
            if exc.code not in {408, 409, 429} and exc.code < 500:
                raise APIError(last_error) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            last_error = "API connection failed or timed out"
        except (ValueError, KeyError, IndexError, TypeError):
            last_error = "API response is not valid query JSON"
        if attempt < retries:
            time.sleep(min(2 ** attempt, 8))
    raise APIError(f"{last_error}; failed after {retries + 1} attempts")


def run_generation(input_file: Path, output_file: Path, *, overwrite: bool = False, **api_options: Any) -> dict[str, Any]:
    if input_file.resolve() == output_file.resolve():
        raise ValueError("input and output must be different files")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    counts = {"input_rows": 0, "skipped_not_feasible": 0, "generated": 0}
    with input_file.open(encoding="utf-8") as source, output_file.open("w" if overwrite else "x", encoding="utf-8") as output:
        for line_number, line in enumerate(source, 1):
            if not line.strip(): continue
            try: row = json.loads(line)
            except json.JSONDecodeError as exc: raise ValueError(f"invalid JSON at line {line_number}: {exc}") from None
            counts["input_rows"] += 1
            if isinstance(row, dict) and row.get("status") == "not_feasible":
                counts["skipped_not_feasible"] += 1
                continue
            try: row = validate_input(row)
            except ValueError as exc: raise ValueError(f"invalid input at line {line_number}: {exc}") from None
            try: result = call_llm(row, **api_options)
            except APIError as exc: raise APIError(f"line {line_number}: {exc}; completed rows retained") from None
            output_row = {"source_domain": row["source_domain"], "sample": row["sample"],
                          "fusion_domains": row["fusion_domains"], "fusion_idea": row["fusion_idea"]["idea"], **result}
            output.write(json.dumps(output_row, ensure_ascii=False) + "\n"); output.flush()
            counts["generated"] += 1
            print(f"line={line_number} generated={counts['generated']}", file=sys.stderr, flush=True)
    return {**counts, "output": str(output_file.resolve())}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--api-base-url", default=os.getenv("API_BASE_URL"))
    parser.add_argument("--api-key", default=os.getenv("API_KEY"))
    parser.add_argument("--model", default=os.getenv("MODEL"))
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--max-tokens", type=int, default=2048)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    if not math.isfinite(args.timeout) or args.timeout <= 0 or args.retries < 0 or args.max_tokens < 1:
        parser.error("invalid timeout, retries, or max-tokens")
    for name in ("api_base_url", "api_key", "model"):
        if not getattr(args, name) or not getattr(args, name).strip(): parser.error(f"set --{name.replace('_','-')} or its environment variable")
    try:
        report = run_generation(args.input, args.output or DEFAULT_OUTPUT_ROOT / f"2_{args.input.stem}.jsonl",
                                overwrite=args.overwrite, api_base_url=args.api_base_url, api_key=args.api_key,
                                model=args.model, timeout=args.timeout, retries=args.retries, max_tokens=args.max_tokens)
    except (OSError, ValueError, APIError) as exc:
        print(f"Error: {exc}", file=sys.stderr); return 1
    print(json.dumps(report, ensure_ascii=False, indent=2)); return 0


if __name__ == "__main__": raise SystemExit(main())
