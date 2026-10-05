#!/usr/bin/env python3
"""独立从原始JSONL复算KRC，不导入指标实现模块。"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path


def check(condition: bool, message: str) -> None:
    """核验失败时明确报错，避免python -O绕过assert。"""
    if not condition:
        raise ValueError(message)


def equal(actual, expected, label: str) -> None:
    """比较含null的计算结果，允许浮点求和误差。"""
    valid = actual is None if expected is None else (actual is not None and math.isclose(actual, expected, abs_tol=1e-12))
    check(valid, f'{label}: {actual} != {expected}')


def mean(values) -> float | None:
    """独立计算非空组的算术均值。"""
    return sum(values) / len(values) if values else None


def verify(report_path: Path) -> dict:
    """对输入哈希、参考范围、逐需求权重及分层汇总逐项复核。"""
    report = json.loads(report_path.read_text(encoding='utf-8'))
    manifest = report['manifest']
    cache = {}
    for item in manifest['input']['files']:
        content = Path(item['path']).read_bytes()
        check(hashlib.sha256(content).hexdigest() == item['sha256'], '原始输入哈希变化')
        cache[item['path']] = content.decode('utf-8-sig').split('\n')
    for name, expected in manifest['code_sha256'].items():
        check(hashlib.sha256((Path(__file__).parent / name).read_bytes()).hexdigest() == expected, f'代码哈希变化: {name}')

    def raw(item):
        """从清单物理行读取原记录并核验样本身份。"""
        row = json.loads(cache[item['input_file']][item['input_line'] - 1])
        atom = hashlib.sha256(json.dumps([row['sample']['prompt'], row['sample']['completion']], ensure_ascii=False).encode()).hexdigest()
        check(atom == item['atomic_id'] and row['source_domain'] == item['source_domain']
              and row['domain_count'] == item['domain_count'], '清单与原始样本不匹配')
        return row

    ref_atoms = {(p['source_domain'], p['atomic_id']) for p in manifest['reference_sample']}
    eval_atoms = {(p['source_domain'], p['atomic_id']) for p in manifest['sample']}
    check(not ref_atoms & eval_atoms, '参考集与评测集原子泄漏')
    scores = defaultdict(list)
    for item in manifest['reference_sample']:
        row = raw(item)
        for domain, candidates in row['retrieved_samples'].items():
            for candidate in candidates:
                unique = {hit['query_index']: hit['score'] for hit in candidate['hits'] if hit['method'] == 'bm25'}
                scores[domain].extend(unique.values())
    ranges = report['normalization']['ranges']
    check(set(scores) == set(ranges), '参考领域集合不一致')
    for domain, values in scores.items():
        equal(ranges[domain]['min'], min(values), '参考最小值')
        equal(ranges[domain]['max'], max(values), '参考最大值')
        check(ranges[domain]['observed_scores'] == len(values), '参考分数数量')
    original = {p['plan_id']: raw(p) for p in manifest['sample']}
    requirements = {}
    plan_groups = defaultdict(lambda: defaultdict(list))
    alpha = manifest['settings']['alpha']
    for entry in report['requirement_scores']:
        row = original[entry['plan_id']]
        domain, index, budget, mode = (entry[f] for f in ('target_domain', 'query_index', 'budget', 'mode'))
        candidates = row['retrieved_samples'][domain]
        subset = candidates if budget == 'all' else candidates[:int(budget)]
        valid = []
        for candidate in subset:
            hits = {h['method']: h['score'] for h in candidate['hits'] if h['query_index'] == index}
            if 'embedding' not in hits or (mode != 'cosine_observed' and 'bm25' not in hits):
                continue
            e = max(0., min(1., hits['embedding']))
            if mode.startswith('cosine'):
                value = e
            else:
                limits = ranges[domain]
                b = max(0., min(1., (hits['bm25'] - limits['min']) / (limits['max'] - limits['min'])))
                value = b if mode == 'bm25_complete' else alpha * b + (1 - alpha) * e
            valid.append((value, candidate['candidate_id']))
        best = max(valid, key=lambda v: v[0]) if valid else None
        value = best[0] if best else None
        equal(entry['weight'], value, '逐需求权重')
        check(entry['eligible_pairs'] == len(valid), '有效配对计数')
        check(entry['best_candidate_id'] == (best[1] if best else None), '最佳材料ID')
        requirements[(entry['requirement_id'], mode, budget)] = value
        plan_groups[(entry['plan_id'], mode, budget)][domain].append(value)
    for row in report['requirement_coverage']:
        value = requirements[(row['requirement_id'], row['mode'], row['budget'])]
        expected = None if value is None else int(value >= row['threshold'])
        equal(row['covered'], expected, '逐需求二值判定')
    plan_values = {}
    for row in report['per_plan']:
        groups = plan_groups[(row['plan_id'], row['mode'], row['budget'])]
        valid = [[v for v in values if v is not None] for values in groups.values()]
        valid = [values for values in valid if values]
        weighted = mean([mean(values) for values in valid])
        binary = mean([mean([int(v >= row['threshold']) for v in values]) for values in valid])
        equal(row['weighted'], weighted, '逐方案加权')
        equal(row['binary'], binary, '逐方案二值')
        check(row['evaluated_requirements'] == sum(len(v) for v in valid), '条件需求分母')
        plan_values[(row['plan_id'], row['mode'], row['budget'], row['threshold'])] = (binary, weighted)
    for row in report['summary']:
        source = defaultdict(list)
        for item in manifest['sample']:
            if item['domain_count'] == row['domain_count']:
                value = plan_values[(item['plan_id'], row['mode'], row['budget'], row['threshold'])]
                if value[1] is not None:
                    source[item['source_domain']].append(value)
        for index, field in enumerate(('binary', 'weighted')):
            observed = mean([mean([v[index] for v in group]) for group in source.values()])
            full = observed if len(source) == len(manifest['settings']['domains']) else None
            equal(row['macro_' + field], full, '宏平均')
            equal(row['observed_source_' + field], observed, '局部均值')
    total_pairs = embedding_pairs = complete_pairs = 0
    for row in original.values():
        for domain, needs in row['required_key_facts'].items():
            for j in range(1, len(needs) + 1):
                for c in row['retrieved_samples'][domain]:
                    methods = {h['method'] for h in c['hits'] if h['query_index'] == j}
                    total_pairs += 1
                    embedding_pairs += 'embedding' in methods
                    complete_pairs += {'embedding', 'bm25'} <= methods
    for name, expected in [('total_pairs', total_pairs), ('embedding_pairs', embedding_pairs), ('complete_pairs', complete_pairs)]:
        check(report['diagnostics'][name] == expected, '配对可用性计数')
    check(len(report['pair_scores']) == embedding_pairs, '输出配对表必须只包含Embedding可用配对')
    return {'status': 'passed', 'input_hashes_unchanged': len(cache), 'code_hashes_checked': len(manifest['code_sha256']),
            'reference_atoms': len(ref_atoms), 'evaluation_atoms': len(eval_atoms), 'reference_disjoint': True,
            'normalization_domains_checked': len(ranges), 'reference_scores_checked': sum(map(len, scores.values())),
            'requirements_checked': len(requirements), 'binary_rows_checked': len(report['requirement_coverage']),
            'plan_rows_checked': len(report['per_plan']), 'summary_rows_checked': len(report['summary']),
            'total_pairs': total_pairs, 'embedding_pairs': embedding_pairs, 'complete_pairs': complete_pairs}


def main() -> None:
    """独立复算后将验收记录写入结果旁的KRC_validation.json。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True, help='KRC_summary.json')
    args = parser.parse_args()
    result = verify(args.input)
    output = args.input.parent / 'KRC_validation.json'
    if output.is_symlink():
        raise ValueError('拒绝覆盖符号链接')
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
