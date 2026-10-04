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
    validate_plans,
    validate_required_key_facts,
    validate_v2_row,
)


DIFFICULTIES = ("easy", "medium", "hard")


from _concise_prompts import SCREEN_PROMPT, SYSTEM_PROMPT, AUDIT_PROMPT, REPAIR_PROMPT
from _concise_fusion import (
    VERSION, audit_payload, audit_issues, budget_for, digest,
    hard_issues, item_id, json_object, length_stats, load_budget_file, plan_key,
    shuffle_options, validate_audit, validate_blueprint, validate_generation,
)


def validate_screening(value: Any, source: str, fusion_domains: list[str],
                       available_samples: dict[str, set[tuple[str, str]]], blueprint_limits=None) -> dict:
    if not isinstance(value, dict) or type(value.get("feasible")) is not bool:
        raise ValueError("screening result must contain a boolean feasible")
    if any(field not in value for field in ("question_plan", "answer_plans", "required_key_facts", "compact_blueprint")):
        raise ValueError("screening must include all plan fields and compact_blueprint (null if infeasible)")
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
                                        ("question_plan", "answer_plans", "required_key_facts", "compact_blueprint")):
            raise ValueError("infeasible screening must not return samples or plans")
        return {"feasible": False, "reason": reason, "selected_samples": normalized, "compact_blueprint": None}
    plans = validate_plans(value, [source, *fusion_domains])
    required = validate_required_key_facts(value.get("required_key_facts"), fusion_domains)
    return {"feasible": True, "reason": reason, "selected_samples": normalized,
            **plans, "required_key_facts": required,
            "compact_blueprint": validate_blueprint(value.get("compact_blueprint"), [source, *fusion_domains], blueprint_limits)}


def preflight_paths(input_file, output_file, audit_file, overwrite):
    paths = [Path(p) for p in (input_file, output_file, audit_file)]
    for i, first in enumerate(paths):
        for second in paths[i+1:]:
            if first.resolve() == second.resolve() or (first.exists() and second.exists() and os.path.samefile(first, second)):
                raise ValueError('input, output and audit paths must refer to different files')
    if not paths[0].is_file():
        raise FileNotFoundError(paths[0])
    for path in paths[1:]:
        if path.exists() and (not overwrite or not path.is_file()):
            raise FileExistsError(f'output exists: {path}; choose a new path or use --overwrite')
        parent = path.parent
        while not parent.exists():
            parent = parent.parent
        if not parent.is_dir():
            raise ValueError(f'output parent is not a directory: {parent}')
    return paths


def process(input_file: Path, output_file: Path, *, api: JSONAPI, domain_count: int | None,
            num: int | None, max_tokens: int, max_input_chars: int, overwrite: bool,
            max_repairs: int = 1, seed: int = 42, judge_api=None,
            skip_semantic_audit: bool = False, length_budget_file: Path | None = None,
            audit_output: Path | None = None) -> dict[str, Any]:
    if num is not None and num < 1 or max_tokens < 1 or max_input_chars < 1:
        raise ValueError('num, max-tokens, and max-input-chars must be positive')
    if type(max_repairs) is not int or max_repairs not in (0, 1):
        raise ValueError('max-repairs must be 0 or 1 (at most one directed rewrite)')
    if type(seed) is not int:
        raise ValueError('seed must be an integer')
    budgets, blueprint_limits = load_budget_file(length_budget_file)
    input_file, output_file, audit_file = preflight_paths(
        input_file, output_file, audit_output or output_file.with_suffix('.audit.jsonl'), overwrite)
    judge_api = judge_api or api
    if skip_semantic_audit:
        print('WARNING: semantic audit disabled; outputs are format-debug records, not quality-qualified items', file=sys.stderr)
    for path in (output_file, audit_file):
        path.parent.mkdir(parents=True, exist_ok=True)
    report = dict(processed=0, skipped=0, feasible_plans=0, initial_candidates=0,
                  repair_candidates=0, generated=0, accepted=0, debug_accepted=0,
                  final_rejected=0, duplicate_plans=0, logical_api_calls=0)
    seen_plans = {}
    output_ids = set()

    def call(client, prompt, payload, validate):
        if len(json.dumps(payload, ensure_ascii=False, allow_nan=False)) > max_input_chars:
            raise ValueError('API input exceeds --max-input-chars; no evidence or code was truncated')
        report['logical_api_calls'] += 1
        return client.chat(prompt, payload, validate, max_tokens)

    with output_file.open('w' if overwrite else 'x', encoding='utf-8') as output, \
            audit_file.open('w' if overwrite else 'x', encoding='utf-8') as audit:
        for line, row in read_rows(input_file):
            if num is not None and report['processed'] >= num:
                break
            context = dict(upstream_line=line, source_domain=row.get('source_domain'),
                           domain_count=row.get('domain_count'), generation_model=api.model,
                           judge_model=judge_api.model, semantic_audit_enabled=not skip_semantic_audit,
                           api_retry_limits={'generation': getattr(api, 'retries', None),
                                             'judge': getattr(judge_api, 'retries', None)},
                           max_tokens=max_tokens, max_input_chars=max_input_chars,
                           max_repairs=max_repairs, seed=seed)
            try:
                validate_v2_row(row)
                source = row['source_domain']
                domains = row_domains(row, domain_count)
                participating = [source, *domains]
                plans = validate_plans(row, participating)
                required = validate_required_key_facts(row.get('required_key_facts'), domains)
                retrieved_candidates = row.get('retrieved_samples')
                if not isinstance(retrieved_candidates, dict) or set(retrieved_candidates) != set(domains):
                    raise ValueError('retrieved_samples must cover exactly the fusion domains')
                retrieved = {}
                for domain in domains:
                    candidates = retrieved_candidates[domain]
                    if not isinstance(candidates, list):
                        raise ValueError(f'retrieved_samples.{domain} must be a list')
                    retrieved[domain] = []
                    references = set()
                    for candidate in candidates:
                        if not isinstance(candidate, dict):
                            raise ValueError('retrieved candidate is invalid')
                        sample = candidate.get('sample', candidate)
                        if not isinstance(sample, dict):
                            raise ValueError('retrieved sample is invalid')
                        sample = {k: sample.get(k) for k in ('prompt', 'completion')}
                        reference = sample_reference(sample)
                        if reference not in references:
                            retrieved[domain].append(sample)
                            references.add(reference)
                report['processed'] += 1
                key = plan_key(row)
                context['plan_key'] = key
                # Different contents with an explicit shared ID are an input error.
                fingerprint = digest({k: row[k] for k in ('source_domain', 'sample', 'key_facts', 'fusion_domains',
                                                         'question_plan', 'answer_plans', 'required_key_facts')})
                if key in seen_plans:
                    if seen_plans[key] != fingerprint:
                        raise ValueError('plan_key collision with different input contents')
                    report['duplicate_plans'] += 1
                    report['skipped'] += 1
                    write_row(audit, {**context, 'event': 'screening', 'status': 'duplicate',
                                      'issues': [{'check': 'duplicate_input', 'reason': 'Identical plan already processed'}]})
                    continue
                seen_plans[key] = fingerprint
                empty = [d for d in domains if not retrieved[d]]
                if empty:
                    report['skipped'] += 1
                    write_row(audit, {**context, 'event': 'screening', 'status': 'rejected',
                                      'issues': [{'check': 'empty_retrieval', 'domains': empty}]})
                    continue
                budget = budget_for(row['domain_count'], budgets)
                if budget['status'] == 'uncalibrated_extension':
                    print(f'line={line} budget=uncalibrated_extension domains={row["domain_count"]}', file=sys.stderr)
                screen_payload = dict(source_domain=source, sample=row['sample'], key_facts=row['key_facts'],
                                      fusion_domains=domains, **plans, required_key_facts=required,
                                      retrieved_samples=retrieved, blueprint_limits=blueprint_limits)
                available = {d: {sample_reference(s) for s in retrieved[d]} for d in domains}
                screen = call(api, SCREEN_PROMPT, screen_payload,
                              lambda v: validate_screening(v, source, domains, available, blueprint_limits))
                write_row(audit, {**context, 'event': 'screening', 'status': 'passed' if screen['feasible'] else 'rejected',
                                  'screening': screen, 'issues': [] if screen['feasible'] else [
                                      {'check': 'infeasible', 'reason': screen['reason']}]})
                if not screen['feasible']:
                    report['skipped'] += 1
                    continue
                report['feasible_plans'] += 1
                selected = screen['selected_samples']
                selected_keys = {d: {sample_reference(s) for s in selected[d]} for d in domains}
                original_plan = {k: row[k] for k in ('question_plan', 'answer_plans', 'required_key_facts')}
                scope = 'none' if all(screen[k] == row[k] for k in original_plan) else 'target_narrowed'
                previous_items = []
                for difficulty in DIFFICULTIES:
                    identity = item_id(key, difficulty)
                    payload = {**screen_payload, 'question_plan': screen['question_plan'],
                               'answer_plans': screen['answer_plans'], 'required_key_facts': screen['required_key_facts'],
                               'retrieved_samples': selected, 'compact_blueprint': screen['compact_blueprint'],
                               'length_budget': budget, 'option_count': 4, 'difficulty': difficulty}
                    repair_payload = None
                    for attempt in range(max_repairs + 1):
                        counter = 'initial_candidates' if attempt == 0 else 'repair_candidates'
                        report[counter] += 1
                        raw = call(api, SYSTEM_PROMPT if attempt == 0 else REPAIR_PROMPT,
                                   payload if attempt == 0 else repair_payload, json_object)
                        issues, stats, semantic, mapping = [], None, None, None
                        generated = None
                        # Candidate structure failures are quality failures, not malformed HTTP/JSON.
                        try:
                            generated = validate_generation(raw, participating, selected_keys, screen['compact_blueprint']['answer_form'])
                        except ValueError as exc:
                            issues = [{'check': 'structure', 'reason': str(exc)}]
                        if generated is not None:
                            stats = length_stats(generated)
                            issues = hard_issues(generated, budget)
                            if not issues:
                                generated, mapping = shuffle_options(generated, seed, identity)
                                if not skip_semantic_audit:
                                    semantic = call(judge_api, AUDIT_PROMPT,
                                                    audit_payload(generated, source, row['sample'], domains, selected),
                                                    lambda v: validate_audit(v, participating))
                                    issues += audit_issues(semantic, generated['answer'])
                        passed = not issues
                        status = 'accepted' if passed else ('repairing' if attempt < max_repairs else 'rejected')
                        audit_status = ('passed' if passed else 'failed') if semantic is not None else 'not_run'
                        # Compare visible content, ignoring option order and difficulty labels.
                        signature = digest([generated['question'], sorted(generated['options'].values())]) if generated else None
                        duplicate_difficulties = [d for d, s in previous_items if s == signature] if signature else []
                        write_row(audit, {**context, 'event': 'candidate', 'item_id': identity,
                                          'difficulty': difficulty, 'attempt': attempt, 'status': status,
                                          'issues': issues, 'length_budget': budget, 'length_stats': stats,
                                          'semantic_audit_status': audit_status, 'semantic_audit': semantic,
                                          'option_permutation': mapping, 'original_candidate': raw,
                                          'candidate': generated, 'duplicate_difficulties': duplicate_difficulties})
                        if passed:
                            if identity in output_ids:
                                raise ValueError('duplicate item_id; refusing duplicate output')
                            output_ids.add(identity)
                            construction = dict(version=VERSION, plan_key=key, upstream_line=line,
                                                compact_blueprint=screen['compact_blueprint'], original_plan=original_plan,
                                                selected_samples=selected, length_budget=budget, length_stats=stats,
                                                scope_change=scope, difficulty_status='uncalibrated',
                                                error_label_status='construction_intent', semantic_audit_status=audit_status,
                                                semantic_audit=semantic, repair_count=attempt, option_permutation=mapping,
                                                seed=seed, generation_model=api.model, judge_model=judge_api.model,
                                                duplicate_difficulties=duplicate_difficulties)
                            write_row(output, dict(source_file=row.get('source_file', str(input_file.resolve())),
                                                   source_domain=source, model=api.model, sample=row['sample'],
                                                   key_facts=row['key_facts'], fusion_domains=domains, domain_count=row['domain_count'],
                                                   question_plan=screen['question_plan'], answer_plans=screen['answer_plans'],
                                                   required_key_facts=screen['required_key_facts'], retrieved_samples=retrieved,
                                                   retrieval=row.get('retrieval', {}), **generated,
                                                   difficulty=difficulty, item_id=identity, construction=construction))
                            report['generated'] += 1
                            report['debug_accepted' if skip_semantic_audit else 'accepted'] += 1
                            previous_items.append((difficulty, signature))
                            break
                        if attempt == max_repairs:
                            report['final_rejected'] += 1
                        else:
                            repair_payload = {**payload, 'original_candidate': raw,
                                              'feedback': {'issues': issues, 'semantic_audit': semantic,
                                                           'audited_candidate': generated, 'option_permutation': mapping,
                                                           'preserve': ['source sample core knowledge', 'all participating domains',
                                                                        'blueprint final target', 'supported facts and necessary conditions',
                                                                        'one correct option and three concrete wrong outcomes']}}
                    print(f'line={line} difficulty={difficulty} status={status} generated={report["generated"]}', file=sys.stderr, flush=True)
            except (APIError, ValueError) as exc:
                write_row(audit, {**context, 'event': 'fatal_error', 'status': 'error', 'reason': str(exc)})
                message = f'{input_file}:{line}: {exc}; completed output retained at {output_file}; audit retained at {audit_file}'
                raise type(exc)(message) from None
    return {**report, 'output': str(output_file.resolve()), 'audit_output': str(audit_file.resolve()),
            'transport_attempts': 'not_exposed_by_shared_JSONAPI'}


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
        judge = JSONAPI(args.api_base_url, args.api_key, args.judge_model, args.timeout, args.retries) if args.judge_model else api
        report = process(args.input, args.output, api=api, domain_count=args.domain_count,
                         num=args.num, max_tokens=args.max_tokens,
                         max_input_chars=args.max_input_chars, overwrite=args.overwrite,
                         max_repairs=args.max_repairs, seed=args.seed, judge_api=judge,
                         skip_semantic_audit=args.skip_semantic_audit,
                         length_budget_file=args.length_budget_file, audit_output=args.audit_output)
    except (OSError, ValueError, APIError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
