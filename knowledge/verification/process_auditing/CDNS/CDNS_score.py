"""CDNS、逐领域 DC、样本内最佳单域遮蔽 IG 的离线评分。"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

from CDNS_data import digest, file_digest, fresh_directory, load_bundle, read_jsonl, write_json, write_jsonl


def mean(values):
    """返回均值，零分母返回 None。"""
    return sum(values) / len(values) if values else None


def evaluate(samples, answers, requests, predictions):
    """计算单次作答指标，缺失和失败不当作答错。

    Args:
        samples: 规范样本列表，无金标。
        answers: sample_id 到标准答案的映射。
        requests: 构造好的完整条件请求。
        predictions: 绑定请求摘要和单一推理配置的结果列表。

    Returns:
        样本分数、分组指标、域贡献、诊断准确率与分母审计。
    """
    request_map = {r['request_id']: r for r in requests}
    if len(request_map) != len(requests):
        raise ValueError('重复请求 ID')
    lookup, configs, simulations, statuses = {}, set(), set(), Counter()
    for prediction in predictions:
        rid = prediction.get('request_id')
        if rid not in request_map or rid in lookup:
            raise ValueError('预测含未知或重复请求 ID')
        request = request_map[rid]
        if prediction.get('prompt_sha256') != request['prompt_sha256']:
            raise ValueError('预测与 Prompt 摘要不匹配')
        config = prediction.get('inference_config')
        if not isinstance(config, dict) or not config or prediction.get('inference_id') != digest(config):
            raise ValueError('缺少有效推理配置及其摘要')
        configs.add(prediction['inference_id'])
        if type(prediction.get('simulation')) is not bool:
            raise ValueError('预测必须声明 simulation')
        simulations.add(prediction['simulation'])
        status = prediction.get('status')
        if status not in ('ok', 'error', 'invalid_format'):
            raise ValueError('未知预测状态')
        if status == 'ok' and prediction.get('answer') not in [*request['option_labels'], 'ABSTAIN']:
            raise ValueError('ok 结果的答案标签非法')
        lookup[rid] = prediction
        statuses[status] += 1
    if len(configs) > 1 or len(simulations) > 1:
        raise ValueError('禁止混合推理配置或混合模拟/真实结果')
    outcomes, correctness = {}, {}
    for request in requests:
        prediction = lookup.get(request['request_id'])
        value = None
        if prediction and prediction['status'] == 'ok':
            value = int(prediction['answer'] == answers[request['sample_id']])
        key = (request['sample_id'], request['condition'], request['domain'])
        if key in outcomes:
            raise ValueError('重复实验条件')
        outcomes[key] = value
        correctness[request['request_id']] = value
    per_sample, domain_rows, diagnostic_rows = [], [], []
    for sample in samples:
        sid, domains = sample['sample_id'], sample['domains']
        full = outcomes.get((sid, 'full', None))
        masked = {d: outcomes.get((sid, 'mask', d)) for d in domains}
        complete = full is not None and all(y is not None for y in masked.values())
        cdns = int(full == 1 and all(y == 0 for y in masked.values())) if complete else None
        ig = full - max(masked.values()) if complete else None
        per_sample.append({'sample_id': sid, 'source_domain': sample['source_domain'],
                           'k': len(domains), 'difficulty': sample['difficulty'],
                           'full_correct': full, 'mask_correct': masked,
                           'complete_core': complete, 'CDNS': cdns, 'IG': ig})
        for domain, value in masked.items():
            domain_rows.append({'sample_id': sid, 'domain': domain, 'k': len(domains),
                                'difficulty': sample['difficulty'], 'source_domain': sample['source_domain'],
                                'full_correct': full, 'mask_correct': value,
                                'DC': full - value if full is not None and value is not None else None})
    groups = [('overall', 'all', per_sample)]
    for field in ('k', 'difficulty', 'source_domain'):
        for value in sorted({s[field] for s in per_sample}):
            groups.append((field, str(value), [s for s in per_sample if s[field] == value]))
    for k, level in sorted({(s['k'], s['difficulty']) for s in per_sample}):
        groups.append(('k_difficulty', f'{k}:{level}',
                       [s for s in per_sample if s['k'] == k and s['difficulty'] == level]))
    summaries, contributions = [], []
    for dimension, value, subset in groups:
        complete = [s for s in subset if s['complete_core']]
        summaries.append({'group_by': dimension, 'group': value,
                          'n_total': len(subset), 'n_complete': len(complete),
                          'n_excluded': len(subset) - len(complete),
                          'n_full_correct_complete': sum(s['full_correct'] for s in complete),
                          'CDNS': mean([s['CDNS'] for s in complete]),
                          'IG': mean([s['IG'] for s in complete]),
                          'full_accuracy_complete': mean([s['full_correct'] for s in complete]),
                          'best_mask_accuracy_complete': mean([max(s['mask_correct'].values()) for s in complete])})
        ids = {s['sample_id'] for s in subset}
        for domain in sorted({d['domain'] for d in domain_rows if d['sample_id'] in ids}):
            eligible = [d for d in domain_rows if d['sample_id'] in ids and d['domain'] == domain]
            paired = [d for d in eligible if d['DC'] is not None]
            contributions.append({'group_by': dimension, 'group': value, 'domain': domain,
                                  'n_total': len(eligible), 'n_paired': len(paired),
                                  'n_excluded': len(eligible) - len(paired),
                                  'full_accuracy_paired': mean([d['full_correct'] for d in paired]),
                                  'mask_accuracy_paired': mean([d['mask_correct'] for d in paired]),
                                  'DC': mean([d['DC'] for d in paired])})
        buckets = defaultdict(list)
        for request in requests:
            if request['sample_id'] in ids:
                buckets[(request['condition'], request['domain'])].append(request)
        for (condition, domain), rows in buckets.items():
            valid = [r for r in rows if correctness[r['request_id']] is not None]
            abstain = sum(lookup[r['request_id']]['answer'] == 'ABSTAIN' for r in valid)
            diagnostic_rows.append({'group_by': dimension, 'group': value, 'condition': condition,
                                    'domain': domain, 'n_total': len(rows), 'n_valid': len(valid),
                                    'n_excluded': len(rows) - len(valid), 'n_abstain': abstain,
                                    'accuracy': mean([correctness[r['request_id']] for r in valid])})
    return {'simulation': next(iter(simulations), None), 'inference_ids': sorted(configs),
            'expected_requests': len(requests), 'received_predictions': len(predictions),
            'missing_predictions': len(requests) - len(predictions), 'statuses': dict(statuses),
            'sample_scores': per_sample, 'domain_sample_scores': domain_rows,
            'summary': summaries, 'domain_contribution': contributions, 'condition_accuracy': diagnostic_rows,
            'aggregation': 'sample_micro; IG uses per-sample max; one response per condition',
            'interpretation': '模拟结果仅验证实现；真实结果仅表征固定模型和Prompt下的样本依赖'}


def write_csv(path, rows):
    """写入矩形指标表，None 留空表示未定义。"""
    with Path(path).open('w', encoding='utf-8', newline='') as stream:
        if rows:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)


def score(input_dir, predictions_file, output_dir):
    """评分并导出 JSON/CSV/Markdown；没有结果时不捏造零分。"""
    samples, answers, requests, manifest = load_bundle(input_dir)
    predictions = [row for _, row in read_jsonl(predictions_file)]
    report = evaluate(samples, answers, requests, predictions)
    report['input_files'] = manifest['files']
    report['predictions_sha256'] = file_digest(predictions_file)
    root = fresh_directory(output_dir)
    write_json(root / 'CDNS_metrics.json', report)
    write_jsonl(root / 'CDNS_sample_scores.jsonl', report['sample_scores'])
    write_jsonl(root / 'CDNS_domain_sample_scores.jsonl', report['domain_sample_scores'])
    for field, name in [('summary', 'CDNS_summary.csv'), ('domain_contribution', 'CDNS_DC.csv'),
                        ('condition_accuracy', 'CDNS_condition_accuracy.csv')]:
        write_csv(root / name, report[field])
    overall = report['summary'][0]
    kind = '模拟验证，不能作为实验结论' if report['simulation'] else '推理结果评分（仍需审查缺失与材料质量）'
    if not predictions:
        kind = '无推理结果，指标未定义'
    text = f'''# CDNS 评分报告

状态：{kind}。

样本总数：{overall['n_total']}；核心条件完整：{overall['n_complete']}；排除：{overall['n_excluded']}。
CDNS：{overall['CDNS']}；IG：{overall['IG']}（None 表示分母为零）。
预期请求：{report['expected_requests']}；缺失：{report['missing_predictions']}；状态：{report['statuses']}。

- CDNS 分母包含 Full 答错的完整样本，不是 Full 答对条件下的比例。
- IG 先逐样本取最佳 Mask，再对完整样本平均，保留负值。
- DC 使用各领域 Full/Mask 配对分母，见 CDNS_DC.csv。
- No Domain/Only 为诊断，不参与 CDNS、IG 核心完整性判断。
- 汇总是样本等权平均；按 k、难度、源域、k×难度分组见 CDNS_summary.csv。
- 单次作答下 IG=CDNS−P(Full错且至少一个Mask对)，并非独立的香农信息量。
- 模型内化知识、题干提供规则和选项捷径可能降低分数；分数不证明绝对不可解。
'''
    (root / 'CDNS_report.md').write_text(text, encoding='utf-8')
    return report


def main():
    """运行离线评分 CLI。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir', type=Path, required=True)
    parser.add_argument('--predictions-file', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    try:
        report = score(**vars(args))
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(2, f'CDNS 评分失败：{exc}\n')
    print(json.dumps(report['summary'][0], ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
