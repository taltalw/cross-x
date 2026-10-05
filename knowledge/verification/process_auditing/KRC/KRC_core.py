"""KRC条件覆盖：仅对所需分数完整可用的配对计算，不填补缺失值。"""

from __future__ import annotations

import math
from collections import defaultdict

if __package__:
    from .KRC_data import normalize_bm25
else:
    from KRC_data import normalize_bm25

MODES = ('cosine_observed', 'hybrid_complete', 'cosine_complete', 'bm25_complete')


def average(values) -> float | None:
    """空集合返回None，避免把不可评测组当零分。"""
    return math.fsum(values) / len(values) if values else None


def extract_pairs(plans: list[dict], normalization: dict, alpha: float = 0.5) -> list[dict]:
    """建立需求候选清单；只有Embedding配对可进入任一评测模式。

    Args:
        plans: KRC_data规范化的方案。
        normalization: 固定BM25参考范围。
        alpha: 混合分数中的BM25权重。
    """
    if type(alpha) not in (int, float) or not math.isfinite(alpha) or not 0 <= alpha <= 1:
        raise ValueError('alpha必须为[0,1]内有限数值')
    pairs = []
    for p in plans:
        for d in p['fusion_domains']:
            for j, need in enumerate(p['needs'][d], 1):
                for position, candidate in enumerate(p['candidates'][d], 1):
                    embedding = candidate['hits'].get((j, 'embedding'))
                    bm25 = candidate['hits'].get((j, 'bm25'))
                    e = min(1., max(0., embedding['score'])) if embedding is not None else None
                    # 未保存Embedding的配对仅作数量审计，不进行归一化或满足度评测。
                    b, clipped = normalize_bm25(bm25['score'], d, normalization) if embedding and bm25 else (None, None)
                    rank_sum = sum(1 / (p['config']['rrf_k'] + h['rank']) for h in (embedding, bm25) if h is not None)
                    pairs.append({'plan_id': p['plan_id'], 'atomic_id': p['atomic_id'],
                        'source_domain': p['source_domain'], 'domain_count': p['domain_count'],
                        'requirement_id': f"{p['plan_id']}:{d}:{j}", 'target_domain': d,
                        'query_index': j, 'key_fact': need['key_fact'], 'necessity': need['necessity'],
                        'candidate_id': candidate['candidate_id'], 'candidate_position': position,
                        'bm25_raw': bm25['score'] if bm25 else None,
                        'cosine_raw': embedding['score'] if embedding else None,
                        'bm25_norm': b, 'cosine_norm': e, 'bm25_clipped': clipped,
                        'bm25_rank': bm25['rank'] if bm25 else None,
                        'embedding_rank': embedding['rank'] if embedding else None,
                        'candidate_rrf_score': candidate['rrf_score'],
                        'request_rrf_norm': rank_sum / (2 / (p['config']['rrf_k'] + 1)),
                        'embedding_available': embedding is not None, 'both_available': embedding is not None and bm25 is not None,
                        'hybrid_score': alpha * b + (1 - alpha) * e if b is not None and e is not None else None,
                        'evaluation_status': 'complete' if embedding and bm25 else ('embedding_only' if embedding else 'excluded_no_embedding')})
    return pairs


def requirement_scores(plans: list[dict], pairs: list[dict], budgets: list[str]) -> list[dict]:
    """在每项需求的有效候选内取最大值；无有效材料时权重为None。"""
    grouped = defaultdict(list)
    for pair in pairs:
        grouped[pair['requirement_id']].append(pair)
    result = []
    score_field = {'cosine_observed': 'cosine_norm', 'cosine_complete': 'cosine_norm',
                   'hybrid_complete': 'hybrid_score', 'bm25_complete': 'bm25_norm'}
    for p in plans:
        for d in p['fusion_domains']:
            by_id = {c['candidate_id']: c for c in p['candidates'][d]}
            for j, need in enumerate(p['needs'][d], 1):
                rid = f"{p['plan_id']}:{d}:{j}"
                for budget in budgets:
                    subset = [pair for pair in grouped[rid] if budget == 'all' or pair['candidate_position'] <= int(budget)]
                    for mode in MODES:
                        valid = [pair for pair in subset if pair['embedding_available'] and
                                 (mode == 'cosine_observed' or pair['both_available'])]
                        best = max(valid, key=lambda r: r[score_field[mode]]) if valid else None
                        qa = by_id[best['candidate_id']]['sample'] if best else {}
                        result.append({'plan_id': p['plan_id'], 'atomic_id': p['atomic_id'],
                            'source_domain': p['source_domain'], 'domain_count': p['domain_count'],
                            'requirement_id': rid, 'target_domain': d, 'query_index': j,
                            'key_fact': need['key_fact'], 'necessity': need['necessity'],
                            'budget': budget, 'mode': mode, 'total_pairs': len(subset),
                            'embedding_pairs': sum(r['embedding_available'] for r in subset),
                            'complete_pairs': sum(r['both_available'] for r in subset), 'eligible_pairs': len(valid),
                            'status': 'evaluated' if best else 'excluded_no_eligible_score',
                            'weight': best[score_field[mode]] if best else None,
                            'best_candidate_id': best['candidate_id'] if best else None,
                            'best_candidate_prompt': qa.get('prompt'), 'best_candidate_completion': qa.get('completion')})
    return result


def aggregate(requirements: list[dict], domains: list[str], ks: list[int],
              budgets: list[str], thresholds: list[float]) -> dict:
    """按有分数需求→有分数新增领域→有分数方案→源领域计算条件均值。

    Returns:
        逐需求阈值判定、域/方案/源域条件统计和按k的宏平均；所有排除数量显式保留。
    """
    if not thresholds or any(type(t) not in (int, float) or not math.isfinite(t) or not 0 < t <= 1 for t in thresholds):
        raise ValueError('阈值必须在(0,1]')
    grouped = defaultdict(list)
    for r in requirements:
        grouped[(r['plan_id'], r['budget'], r['mode'])].append(r)
    coverage, per_domain, per_plan = [], [], []
    for (pid, budget, mode), rows in grouped.items():
        for tau in thresholds:
            domain_rows = defaultdict(list)
            for r in rows:
                domain_rows[r['target_domain']].append(r)
                coverage.append({f: r[f] for f in ('plan_id', 'requirement_id', 'mode', 'budget')} |
                    {'threshold': tau, 'covered': int(r['weight'] >= tau) if r['weight'] is not None else None,
                     'status': r['status']})
            entries = []
            for domain, group in domain_rows.items():
                valid = [r for r in group if r['weight'] is not None]
                entry = {'plan_id': pid, 'source_domain': rows[0]['source_domain'],
                    'domain_count': rows[0]['domain_count'], 'target_domain': domain,
                    'mode': mode, 'budget': budget, 'threshold': tau,
                    'total_requirements': len(group), 'evaluated_requirements': len(valid),
                    'excluded_requirements': len(group) - len(valid),
                    'total_pairs': sum(r['total_pairs'] for r in group),
                    'eligible_pairs': sum(r['eligible_pairs'] for r in group),
                    'binary': average([int(r['weight'] >= tau) for r in valid]),
                    'weighted': average([r['weight'] for r in valid])}
                per_domain.append(entry)
                entries.append(entry)
            valid = [e for e in entries if e['weighted'] is not None]
            per_plan.append({'plan_id': pid, 'source_domain': rows[0]['source_domain'],
                'domain_count': rows[0]['domain_count'], 'mode': mode, 'budget': budget, 'threshold': tau,
                'total_requirements': len(rows), 'evaluated_requirements': sum(e['evaluated_requirements'] for e in entries),
                'excluded_requirements': sum(e['excluded_requirements'] for e in entries),
                'total_domains': len(entries), 'evaluated_domains': len(valid),
                'total_pairs': sum(r['total_pairs'] for r in rows), 'eligible_pairs': sum(r['eligible_pairs'] for r in rows),
                'binary': average([e['binary'] for e in valid]), 'weighted': average([e['weighted'] for e in valid])})
    per_source, summary = [], []
    pgroups = defaultdict(list)
    for p in per_plan:
        pgroups[(p['domain_count'], p['budget'], p['mode'], p['threshold'], p['source_domain'])].append(p)
    totals = ('total_requirements', 'evaluated_requirements', 'excluded_requirements', 'total_domains',
              'evaluated_domains', 'total_pairs', 'eligible_pairs')
    for k in ks:
        for budget in budgets:
            for mode in MODES:
                for tau in thresholds:
                    groups = []
                    for source in domains:
                        ps = pgroups[(k, budget, mode, tau, source)]
                        valid = [p for p in ps if p['weighted'] is not None]
                        item = {'source_domain': source, 'domain_count': k, 'mode': mode, 'budget': budget, 'threshold': tau,
                            'total_plans': len(ps), 'evaluated_plans': len(valid),
                            **{f: sum(p[f] for p in ps) for f in totals},
                            'binary': average([p['binary'] for p in valid]), 'weighted': average([p['weighted'] for p in valid])}
                        per_source.append(item)
                        groups.append(item)
                    valid = [g for g in groups if g['weighted'] is not None]
                    item = {'domain_count': k, 'mode': mode, 'budget': budget, 'threshold': tau,
                        'expected_sources': len(domains), 'evaluated_sources': len(valid),
                        'missing_sources': [g['source_domain'] for g in groups if g['weighted'] is None],
                        **{f: sum(g[f] for g in groups) for f in ('total_plans', 'evaluated_plans', *totals)}}
                    for field in ('binary', 'weighted'):
                        value = average([g[field] for g in valid])
                        item['observed_source_' + field] = value
                        item['macro_' + field] = value if len(valid) == len(domains) else None
                    item['requirement_inclusion_rate'] = item['evaluated_requirements'] / item['total_requirements'] if item['total_requirements'] else None
                    item['pair_inclusion_rate'] = item['eligible_pairs'] / item['total_pairs'] if item['total_pairs'] else None
                    summary.append(item)
    return {'requirement_coverage': coverage, 'per_domain': per_domain,
            'per_plan': per_plan, 'per_source': per_source, 'summary': summary}
