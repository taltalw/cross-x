#!/usr/bin/env python3
"""Offline visible-length/quality statistics and explicit content-based pairing."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from _concise_fusion import budget_for, digest, hard_issues, length_stats, plan_key


def records(root, audit=False):
    paths = [root] if root.is_file() else sorted(root.rglob('*.jsonl'))
    for path in paths:
        is_audit = 'audit' in path.name.lower()
        if not audit and is_audit:
            continue
        with path.open(encoding='utf-8') as stream:
            for line, text in enumerate(stream, 1):
                if not text.strip():
                    continue
                row = json.loads(text)
                if not isinstance(row, dict):
                    raise ValueError(f'{path}:{line}: expected a JSON object')
                if audit:
                    if 'event' in row:
                        yield path, line, row
                elif 'event' not in row and 'question' in row and 'options' in row:
                    yield path, line, row


def distribution(values):
    if not values:
        return None
    ordered = sorted(values)
    # Linear interpolation, matching a conventional percentile definition.
    position = (len(ordered)-1)*.95
    lo = int(position)
    p95 = ordered[lo] + (ordered[min(lo+1,len(ordered)-1)]-ordered[lo])*(position-lo)
    return dict(mean=statistics.mean(values), median=statistics.median(values), p95=p95)


def group_name(row):
    return '/'.join(str(row.get(k, 'unknown')) for k in ('source_domain','domain_count','difficulty'))


def summarize(rows):
    groups = defaultdict(list)
    for _, _, row in rows:
        status = row.get('construction', {}).get('semantic_audit_status', 'legacy_not_audited')
        groups[(group_name(row), status)].append(row)
    result = {}
    for (group, status), items in sorted(groups.items()):
        stats = [length_stats(r) for r in items]
        # Unsafe prose references are not length violations.
        over = sum(any(i['check']=='length' for i in hard_issues(r, r.get('construction', {}).get('length_budget') or budget_for(r['domain_count']))) for r in items)
        errors = defaultdict(Counter)
        for row in items:
            for entry in row['distractor_analysis']:
                errors[entry['type']][entry['option']] += 1
        result[group + '/' + status] = dict(
            count=len(items), length={k: distribution([s[k] for s in stats]) for k in
                ('question_words','options_words','total_visible_words','question_chars','options_chars','total_visible_chars')},
            individual_option_words=distribution([w for s in stats for w in s['option_words'].values()]),
            per_option_words={label:distribution([s['option_words'][label] for s in stats]) for label in 'ABCD'},
            budget_exceeded=over, budget_exceeded_rate=over/len(items),
            answer_positions=dict(Counter(r['answer'] for r in items)),
            construction_error_type_positions={k:dict(v) for k,v in errors.items()})
    return result


def audit_summary(rows):
    counts = Counter(dict.fromkeys(('input_plans','feasible_plans','screen_rejected','duplicate_plans',
                                     'initial_candidates','repair_candidates','accepted','rejected',
                                     'repairing','debug_accepted','fatal_errors'), 0))
    reasons = Counter()
    groups = defaultdict(Counter)
    rejected_lengths, repair_lengths, debug_lengths = [], [], []
    final_reasons = Counter()
    initial_lengths = []
    all_lengths = []
    group_lengths = defaultdict(lambda: defaultdict(list))
    plan_occurrences = set()
    for path, line, r in rows:
        event, status = r.get('event'), r.get('status')
        plan_occurrences.add((str(path), r['upstream_line']))
        if event == 'screening':
            counts['feasible_plans'] += status == 'passed'
            counts['screen_rejected'] += status == 'rejected'
            counts['duplicate_plans'] += status == 'duplicate'
        elif event == 'fatal_error':
            counts['fatal_errors'] += 1
        elif event == 'candidate':
            group = groups[group_name(r)]
            counter = 'initial_candidates' if r['attempt'] == 0 else 'repair_candidates'
            counts[counter] += 1
            group[counter] += 1
            if status == 'rejected':
                for issue in r.get('issues', []): final_reasons[str(issue.get('check', 'unknown'))] += 1
            outcome = 'debug_accepted' if status == 'accepted' and r['semantic_audit_status'] != 'passed' else status
            counts[outcome] += 1
            group[outcome] += 1
            for issue in r.get('issues', []):
                reasons[str(issue.get('check', 'unknown'))] += 1
                group['reason:'+str(issue.get('check', 'unknown'))] += 1
            stats = r.get('length_stats')
            if stats:
                all_lengths.append(stats['total_visible_words'])
                group_lengths[group_name(r)][counter].append(stats['total_visible_words'])
                if r['attempt'] == 0: initial_lengths.append(stats['total_visible_words'])
                if status == 'rejected': rejected_lengths.append(stats['total_visible_words'])
                if r['attempt'] > 0: repair_lengths.append(stats['total_visible_words'])
                if outcome == 'debug_accepted': debug_lengths.append(stats['total_visible_words'])
    counts['input_plans'] = len(plan_occurrences)
    count = counts['initial_candidates']
    accepted = counts['accepted']
    return dict(counts=dict(counts), quality_acceptance=f'{accepted}/{count}',
                quality_acceptance_rate=accepted/count if count else None,
                rejection_and_repair_issue_counts=dict(reasons), final_rejection_reasons=dict(final_reasons),
                audit_files_present=bool(rows),
                planned_quality_coverage=f'{accepted}/{3*counts["input_plans"]}',
                all_candidate_length=distribution(all_lengths), initial_candidate_length=distribution(initial_lengths),
                by_group={k:dict(v, quality_acceptance=f'{v["accepted"]}/{v["initial_candidates"]}',
                                    quality_acceptance_rate=v['accepted']/v['initial_candidates'] if v['initial_candidates'] else None,
                                    candidate_lengths={attempt:distribution(values) for attempt,values in group_lengths[k].items()})
                          for k,v in sorted(groups.items())},
                final_rejected_length=distribution(rejected_lengths),
                repair_attempt_length=distribution(repair_lengths), debug_length=distribution(debug_lengths))


def provenance_signature(row):
    return digest([row['source_domain'], {k:row['sample'][k] for k in ('prompt','completion')}, sorted(row['fusion_domains'])])


def pair_records(old, new, upstream=None, manifest=None):
    upstream = upstream or []
    by_source = defaultdict(dict)
    for _, _, row in upstream:
        by_source[provenance_signature(row)][plan_key(row)] = row
    new_by_key = defaultdict(list)
    for path, line, row in new:
        if row.get('construction', {}).get('semantic_audit_status') != 'passed':
            continue
        key = row['construction']['plan_key']
        new_by_key[(provenance_signature(row), key, row['difficulty'])].append((path,line,row))
    old_by_key = defaultdict(list)
    unmatched = []
    for path, line, row in old:
        source = provenance_signature(row)
        key = row.get('construction', {}).get('plan_key') or row.get('plan_id')
        method = 'stored_plan_identity'
        if key is None and manifest:
            key = manifest.get(f'{path.resolve()}:{line}')
            method = 'explicit_manifest'
        if key is None:
            candidates = by_source[source]
            exact = [k for k,r in candidates.items() if all(row.get(f)==r.get(f) for f in ('question_plan','answer_plans'))]
            if len(exact) == 1:
                key, method = exact[0], 'exact_upstream_plan'
            elif len(candidates) == 1:
                key, method = next(iter(candidates)), 'unique_upstream_plan_for_source_and_domains'
            elif candidates:
                unmatched.append(dict(old_file=str(path), old_line=line, status='ambiguous_upstream', candidates=list(candidates)))
                continue
            else:
                # Valid only when legacy plan fields themselves equal the original plan.
                key, method = plan_key(row), 'legacy_plan_content'
        old_by_key[(source,key,row['difficulty'])].append((path,line,row,method))
    matched, ambiguous = [], []
    for key, values in old_by_key.items():
        targets = new_by_key.get(key, [])
        if len(values)>1 or len(targets)>1:
            ambiguous.append(dict(plan_key=key[1], difficulty=key[2], old_count=len(values), new_count=len(targets)))
        elif not targets:
            path,line,_,method = values[0]
            unmatched.append(dict(old_file=str(path), old_line=line, status='unmatched', method=method))
        else:
            path,line,row,method = values[0]
            new_path,new_line,new_row = targets[0]
            before, after = length_stats(row), length_stats(new_row)
            matched.append(dict(old_file=str(path), old_line=line, new_file=str(new_path), new_line=new_line,
                                plan_key=key[1], difficulty=key[2], method=method,
                                comparison='same_source_plan_reconstruction' if new_row['construction']['scope_change']=='target_narrowed' else 'same_plan_presentation',
                                old_total_words=before['total_visible_words'], new_total_words=after['total_visible_words'],
                                delta_words=after['total_visible_words']-before['total_visible_words']))
    return dict(old_coverage=len(old), new_coverage=len(new), new_quality_passed=sum(len(v) for v in new_by_key.values()),
                matched_count=len(matched), pairs=matched, ambiguous=ambiguous, unmatched=unmatched,
                matched_delta_words=distribution([p['delta_words'] for p in matched]),
                caveat='Matched accepted items are subject to rejection selection bias; target_narrowed is same-source plan reconstruction, not strictly equivalent text compression.')


def build_report(old_root, new_root, audit_root=None, upstream_root=None, manifest=None):
    old, new = list(records(old_root)), list(records(new_root))
    upstream = []
    if upstream_root:
        paths = [upstream_root] if upstream_root.is_file() else sorted(upstream_root.rglob('*.jsonl'))
        for path in paths:
            if 'audit' in path.name.lower(): continue
            for line,text in enumerate(path.read_text(encoding='utf-8').splitlines(),1):
                if text.strip(): upstream.append((path,line,json.loads(text)))
    audit_rows = list(records(audit_root, audit=True)) if audit_root else []
    audit = audit_summary(audit_rows) if audit_root else {'available': False, 'reason': 'No audit-root supplied'}
    return dict(old=summarize(old), new=summarize(new), audits=audit,
                quality_passed_length=distribution([length_stats(r)['total_visible_words'] for _,_,r in new
                    if r.get('construction',{}).get('semantic_audit_status')=='passed']),
                matching=pair_records(old,new,upstream,manifest),
                limitations=['Length budgets are project engineering choices, not official benchmark parameters.',
                             'Error-type positions describe construction intent, not observed model cognition.',
                             'Audit acceptance is unavailable if audit-root is omitted; empty accepted lengths are null.'])


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--old-root', required=True, type=Path)
    parser.add_argument('--new-root', required=True, type=Path)
    parser.add_argument('--audit-root', type=Path)
    parser.add_argument('--upstream-root', type=Path)
    parser.add_argument('--match-manifest', type=Path, help='JSON object: absolute old-file:line -> original plan_key')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    for p in (args.old_root, args.new_root, args.audit_root, args.upstream_root, args.match_manifest):
        if p and not p.exists(): parser.error(f'input does not exist: {p}')
    manifest = json.loads(args.match_manifest.read_text()) if args.match_manifest else None
    if manifest is not None and (not isinstance(manifest,dict) or any(not isinstance(k,str) or not isinstance(v,str) for k,v in manifest.items())):
        parser.error('match-manifest must map file:line strings to plan_key strings')
    report = build_report(args.old_root,args.new_root,args.audit_root,args.upstream_root,manifest)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        with args.output.open('x',encoding='utf-8') as stream: stream.write(text+'\n')
    else: print(text)


if __name__ == '__main__':
    main()
