"""KRC的只读输入、原子样本划分与固定BM25参考范围。"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path

DOMAINS = ['chemistry', 'computer_science', 'financial', 'geography', 'legal', 'mathematics', 'medical']
CONFIG_FIELDS = ('method', 'embedding_config_hash', 'embedding_model', 'rrf_k',
                 'top_k_per_query_method', 'candidate_limit', 'query_instruction',
                 'max_length_tokens', 'chunk_overlap_tokens', 'bm25_k1', 'bm25_b', 'bm25_config')


def digest(value) -> str:
    """生成与原KNC兼容的稳定内容身份。"""
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def finite(value, label: str, lower: float, upper: float = math.inf) -> float:
    """验证数值范围，不接受bool、NaN或无穷。"""
    if type(value) not in (int, float) or not math.isfinite(value) or not lower <= value <= upper:
        raise ValueError(f'{label}: 需要[{lower},{upper}]内有限数值')
    return float(value)


def normalize_record(row: dict, domains: list[str]) -> dict:
    """提取逐需求的原始分数和排名，拒绝重复或冲突记录。"""
    if not isinstance(row, dict):
        raise ValueError('方案必须为JSON对象')
    source, k = row.get('source_domain'), row.get('domain_count')
    added, sample = row.get('fusion_domains'), row.get('sample')
    if source not in domains or type(k) is not int or not 2 <= k <= len(domains):
        raise ValueError('非法源领域或domain_count')
    if not isinstance(added, list) or any(not isinstance(d, str) for d in added):
        raise ValueError('fusion_domains必须为领域列表')
    if len(added) != k - 1 or len(set(added)) != len(added) or source in added or not set(added) <= set(domains):
        raise ValueError('fusion_domains与源领域、领域数不一致')
    if not isinstance(sample, dict) or any(not isinstance(sample.get(f), str) for f in ('prompt', 'completion')):
        raise ValueError('源样本缺少问答文本')
    needs, candidates = row.get('required_key_facts'), row.get('retrieved_samples')
    if not isinstance(needs, dict) or set(needs) != set(added) or not isinstance(candidates, dict) or set(candidates) != set(added):
        raise ValueError('需求与材料必须覆盖全部新增领域')
    config = row.get('retrieval', {})
    if not isinstance(config, dict) or config.get('method') != 'hybrid' or not config.get('embedding_config_hash'):
        raise ValueError('需要hybrid检索和embedding_config_hash元数据')
    if type(config.get('rrf_k')) is not int or config['rrf_k'] < 1:
        raise ValueError('rrf_k必须为正整数')
    normalized = {}
    for d in added:
        if not isinstance(needs[d], list) or not needs[d]:
            raise ValueError(f'{d}: 需求列表必须非空')
        for need in needs[d]:
            if not isinstance(need, dict) or any(not isinstance(need.get(f), str) or not need[f].strip() for f in ('key_fact', 'necessity')):
                raise ValueError(f'{d}: 非法key_fact/necessity')
        if not isinstance(candidates[d], list):
            raise ValueError(f'{d}: 候选应为列表，可明确为空')
        seen, items = set(), []
        for candidate in candidates[d]:
            if not isinstance(candidate, dict):
                raise ValueError('候选应为对象')
            cid, qa = candidate.get('candidate_id'), candidate.get('sample')
            if not isinstance(cid, str) or not cid or cid in seen:
                raise ValueError('candidate_id缺失或重复')
            seen.add(cid)
            if not isinstance(qa, dict) or any(not isinstance(qa.get(f), str) for f in ('prompt', 'completion')):
                raise ValueError(f'{cid}: 缺少候选问答')
            if not isinstance(candidate.get('hits'), list):
                raise ValueError(f'{cid}: 缺少hits列表')
            hits = {}
            for hit in candidate['hits']:
                if not isinstance(hit, dict):
                    raise ValueError('hit必须为对象')
                method, index, rank = hit.get('method'), hit.get('query_index'), hit.get('rank')
                if method not in ('bm25', 'embedding'):
                    continue
                if type(index) is not int or not 1 <= index <= len(needs[d]):
                    raise ValueError('query_index必须为从1开始的领域内需求序号')
                if type(rank) is not int or rank < 1:
                    raise ValueError('rank必须为正整数')
                score = finite(hit.get('score'), method, -1 if method == 'embedding' else 0,
                               1 if method == 'embedding' else math.inf)
                entry = {'score': score, 'rank': rank}
                if (index, method) in hits and hits[index, method] != entry:
                    raise ValueError('重复hit的分数或排名冲突')
                hits[index, method] = entry
            items.append({'candidate_id': cid, 'sample': qa, 'hits': hits,
                          'rrf_score': finite(candidate.get('rrf_score'), 'rrf_score', 0)})
        normalized[d] = items
    atomic = digest([sample['prompt'], sample['completion']])
    return {'plan_id': digest([source, k, atomic]), 'atomic_id': atomic, 'source_domain': source,
            'domain_count': k, 'fusion_domains': added, 'sample': sample,
            'question_plan': row.get('question_plan', ''), 'needs': needs,
            'candidates': normalized, 'config': {f: config.get(f) for f in CONFIG_FIELDS}}


def read_plans(path: Path, domains: list[str], ks: list[int]) -> tuple:
    """读取JSONL，保留文件哈希与物理行号；Unicode分隔符不切行。"""
    if not domains or len(set(domains)) != len(domains) or not ks or len(set(ks)) != len(ks):
        raise ValueError('领域与k列表不得为空或重复')
    if any(type(k) is not int or not 2 <= k <= len(domains) for k in ks):
        raise ValueError('k必须处于[2,领域数]')
    path = path.resolve()
    files = sorted(path.rglob('*.jsonl')) if path.is_dir() else [path]
    plans, seen = [], set()
    meta = {'path': str(path), 'files': [], 'rows_read': 0, 'rows_selected_k': 0}
    for file in files:
        content = file.read_bytes()
        meta['files'].append({'path': str(file), 'sha256': hashlib.sha256(content).hexdigest()})
        for line_no, line in enumerate(content.decode('utf-8-sig').split('\n'), 1):
            if not line.strip():
                continue
            try:
                plan = normalize_record(json.loads(line), domains)
                meta['rows_read'] += 1
                if plan['domain_count'] not in ks:
                    continue
                if plan['plan_id'] in seen:
                    raise ValueError('相同源原子样本同k方案重复')
                seen.add(plan['plan_id'])
                plan.update(input_file=str(file), input_line=line_no)
                plans.append(plan)
            except (ValueError, TypeError) as exc:
                raise ValueError(f'{file}:{line_no}: {exc}') from exc
    if not plans:
        raise ValueError('没有符合指定k的输入方案')
    if len({digest(p['config']) for p in plans}) != 1:
        raise ValueError('输入混合了不兼容检索配置，请分开运行')
    meta['rows_selected_k'] = len(plans)
    return plans, meta


def split_plans(plans: list[dict], ks: list[int], seed: int = 42, fraction: float = 0.2,
                samples_per_source: int = 1, pinned: list[dict] | None = None) -> tuple:
    """跨k配对划分参考集与评测池；固定评测样本优先留出。

    Returns:
        参考方案、试运行方案、完整留出评测池、划分元数据。
    """
    if not 0 < fraction < 1 or type(samples_per_source) is not int or samples_per_source < 1:
        raise ValueError('参考比例需在(0,1)，每源样本数需为正整数')
    grouped = defaultdict(lambda: defaultdict(dict))
    for p in plans:
        grouped[p['source_domain']][p['domain_count']][p['atomic_id']] = p
    pinned_groups = defaultdict(set)
    if pinned is not None:
        seen = set()
        for item in pinned:
            key = (item['source_domain'], item['domain_count'], item['atomic_id'])
            if key in seen:
                raise ValueError('固定样本清单存在重复')
            seen.add(key)
            source, k, atom = key
            if source not in grouped or k not in ks or atom not in grouped[source][k]:
                raise ValueError('固定样本在当前输入或k中不存在')
            pinned_groups[source].add(atom)
        expected = {(s, k, a) for s, atoms in pinned_groups.items() for a in atoms for k in ks}
        if seen != expected:
            raise ValueError('固定样本必须包含指定k的完整配对')
    reference, sample, pool, details = [], [], [], []
    for source in sorted(grouped):
        common = set.intersection(*(set(grouped[source][k]) for k in ks))
        all_atoms = set.union(*(set(grouped[source][k]) for k in ks))
        if not common:
            raise ValueError(f'{source}: 无跨k共有原子样本')
        chosen = pinned_groups[source] if pinned is not None else set(
            sorted(common, key=lambda a: digest(['KRC-evaluation', seed, source, a]))[:samples_per_source])
        if not chosen <= common or (pinned is None and len(chosen) != samples_per_source):
            raise ValueError(f'{source}: 无法选取指定数量的配对样本')
        count = max(1, math.floor(len(common) * fraction))
        remaining = common - chosen
        if len(remaining) < count:
            raise ValueError(f'{source}: 参考集与评测样本无法互斥划分')
        ref = set(sorted(remaining, key=lambda a: digest(['KRC-reference', seed, source, a]))[:count])
        evaluation = common - ref
        for atoms, output in ((ref, reference), (chosen, sample), (evaluation, pool)):
            for atom in sorted(atoms):
                output.extend(grouped[source][k][atom] for k in ks)
        details.append({'source_domain': source, 'common_atoms': len(common),
                        'unpaired_atoms_excluded': len(all_atoms - common),
                        'reference_atoms': sorted(ref), 'evaluation_pool_atoms': sorted(evaluation),
                        'sample_atoms': sorted(chosen)})
    return reference, sample, pool, {'seed': seed, 'reference_fraction': fraction,
        'policy': 'hold out pinned/evaluation atoms before selecting reference atoms', 'sources': details}


def fit_normalization(reference: list[dict]) -> dict:
    """按目标领域拟合固定BM25范围；不对需求或候选预算单独缩放。"""
    values = defaultdict(list)
    for p in reference:
        for d, candidates in p['candidates'].items():
            for c in candidates:
                for (_, method), hit in c['hits'].items():
                    if method == 'bm25':
                        values[d].append(hit['score'])
    ranges = {}
    for d, scores in sorted(values.items()):
        low, high = min(scores), max(scores)
        if low == high:
            raise ValueError(f'{d}: BM25参考范围退化，不能进行Min-Max')
        ranges[d] = {'min': low, 'max': high, 'observed_scores': len(scores)}
    if not ranges:
        raise ValueError('参考集没有可拟合的BM25分数')
    return {'metric_version': 'KRC-observed-v1', 'ranges': ranges,
            'config': reference[0]['config'],
            'reference_plan_ids': sorted(p['plan_id'] for p in reference),
            'reference_atoms': sorted({(p['source_domain'], p['atomic_id']) for p in reference})}


def normalize_bm25(score: float, domain: str, normalization: dict) -> tuple:
    """返回固定范围归一化分数及截断标记。"""
    if domain not in normalization['ranges']:
        raise ValueError(f'{domain}: 缺少BM25参考范围')
    limits = normalization['ranges'][domain]
    value = (score - limits['min']) / (limits['max'] - limits['min'])
    return min(1., max(0., value)), 'low' if value < 0 else ('high' if value > 1 else 'none')
